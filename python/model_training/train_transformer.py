from __future__ import annotations

import argparse
import inspect
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from common import ID_TO_LABEL, LABELS, LABEL_TO_ID, parse_class_weights, predict_with_jihadi_threshold, repo_root, write_json
from evaluate import compute_metrics, write_metric_artifacts
from threshold_tuning import tune_jihadi_threshold


def _require_transformers():
    try:
        import numpy as np
        import torch
        from torch.utils.data import Dataset
        from transformers import AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "torch/transformers are required for transformer training. Install with: "
            "pip install -r python/model_training/requirements-ml.txt"
        ) from exc
    return np, torch, Dataset, AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments


class WeightedTrainerMixin:
    def set_class_weights(self, torch_module, weights: list[float], device):
        self.class_weights = torch_module.tensor(weights, dtype=torch_module.float32, device=device)

    def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        logits = outputs.logits
        loss_fct = self.torch_module.nn.CrossEntropyLoss(weight=self.class_weights)
        loss = loss_fct(logits.view(-1, model.config.num_labels), labels.view(-1))
        return (loss, outputs) if return_outputs else loss


def make_dataset_class(torch_dataset_base):
    class TweetDataset(torch_dataset_base):
        def __init__(self, df, tokenizer, max_length: int, text_column: str):
            self.texts = df[text_column].astype(str).tolist()
            self.labels = [LABEL_TO_ID[label] for label in df["label"].astype(str)]
            self.tokenizer = tokenizer
            self.max_length = max_length

        def __len__(self):
            return len(self.texts)

        def __getitem__(self, index):
            encoded = self.tokenizer(
                self.texts[index],
                truncation=True,
                padding="max_length",
                max_length=self.max_length,
                return_tensors="pt",
            )
            item = {key: value.squeeze(0) for key, value in encoded.items()}
            item["labels"] = self.labels[index]
            return item

    return TweetDataset


def build_training_arguments(TrainingArguments, **kwargs):
    signature = inspect.signature(TrainingArguments.__init__)
    if "evaluation_strategy" in kwargs and "evaluation_strategy" not in signature.parameters and "eval_strategy" in signature.parameters:
        kwargs["eval_strategy"] = kwargs.pop("evaluation_strategy")
    if "eval_strategy" in kwargs and "eval_strategy" not in signature.parameters and "evaluation_strategy" in signature.parameters:
        kwargs["evaluation_strategy"] = kwargs.pop("eval_strategy")
    return TrainingArguments(**kwargs)


def build_trainer(Trainer, tokenizer, **kwargs):
    signature = inspect.signature(Trainer.__init__)
    if "processing_class" in signature.parameters:
        kwargs["processing_class"] = tokenizer
    else:
        kwargs["tokenizer"] = tokenizer
    return Trainer(**kwargs)


def load_split(data_dir: Path, name: str) -> pd.DataFrame:
    path = data_dir / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run prepare_dataset.py first.")
    return pd.read_csv(path)


def parse_weight_sweep(raw: str, base_weights: dict[str, float]) -> list[dict[str, float]]:
    weights = []
    for value in raw.split(","):
        candidate = dict(base_weights)
        candidate["Salafi jihadi"] = float(value.strip())
        weights.append(candidate)
    return weights


def metrics_for_trainer(eval_prediction):
    np, *_ = _require_transformers()
    logits, labels = eval_prediction
    predictions = np.argmax(logits, axis=1)
    y_true = [ID_TO_LABEL[int(label)] for label in labels]
    y_pred = [ID_TO_LABEL[int(prediction)] for prediction in predictions]
    metrics = compute_metrics(y_true, y_pred)
    return {
        "accuracy": metrics["accuracy"],
        "macro_f1": metrics["macro_f1"],
        "salafi_jihadi_precision": metrics["salafi_jihadi_precision"],
        "salafi_jihadi_recall": metrics["salafi_jihadi_recall"],
        "salafi_jihadi_f1": metrics["salafi_jihadi_f1"],
        "jihadi_f2": metrics["salafi_jihadi_f2"],
    }


def predictions_dataframe(df: pd.DataFrame, logits, np_module) -> pd.DataFrame:
    shifted_logits = logits - logits.max(axis=1, keepdims=True)
    probabilities = np_module.exp(shifted_logits) / np_module.exp(shifted_logits).sum(axis=1, keepdims=True)
    predictions = probabilities.argmax(axis=1)
    output = df.copy()
    output["prediction"] = [ID_TO_LABEL[int(index)] for index in predictions]
    for label_index, label in ID_TO_LABEL.items():
        output[f"prob_{label}"] = probabilities[:, label_index]
    return output


def select_best_sweep_result(sweep_results: list[dict[str, object]], min_precision: float) -> dict[str, object]:
    viable = [
        result
        for result in sweep_results
        if result["threshold_validation_metrics"]["salafi_jihadi_precision"] >= min_precision
    ]
    candidates = viable or sweep_results
    return max(
        candidates,
        key=lambda result: (
            result["threshold_validation_metrics"]["salafi_jihadi_f2"],
            result["threshold_validation_metrics"]["salafi_jihadi_precision"],
            result["threshold_validation_metrics"]["macro_f1"],
        ),
    )


def train_one(args, run_dir: Path, weight_index: int, class_weights: dict[str, float], train_df, validation_df):
    np, torch, Dataset, AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments = _require_transformers()
    TweetDataset = make_dataset_class(Dataset)

    weight_name = f"jihadi_weight_{class_weights['Salafi jihadi']:.2f}".replace(".", "_")
    output_dir = run_dir / weight_name
    model_name = args.model_name

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(
        model_name,
        num_labels=len(LABELS),
        id2label=ID_TO_LABEL,
        label2id=LABEL_TO_ID,
    )

    training_args = build_training_arguments(
        TrainingArguments,
        output_dir=str(output_dir / "checkpoints"),
        num_train_epochs=args.epochs,
        learning_rate=args.learning_rate,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.eval_batch_size,
        warmup_ratio=args.warmup_ratio,
        weight_decay=args.weight_decay,
        max_steps=args.max_steps,
        evaluation_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="jihadi_f2",
        greater_is_better=True,
        save_total_limit=1,
        seed=args.seed + weight_index,
        report_to="none",
        logging_steps=20,
    )

    class WeightedTrainer(WeightedTrainerMixin, Trainer):
        pass

    trainer = build_trainer(
        WeightedTrainer,
        tokenizer,
        model=model,
        args=training_args,
        train_dataset=TweetDataset(train_df, tokenizer, args.max_length, args.text_column),
        eval_dataset=TweetDataset(validation_df, tokenizer, args.max_length, args.text_column),
        compute_metrics=metrics_for_trainer,
    )
    trainer.torch_module = torch
    trainer.set_class_weights(torch, [class_weights[label] for label in LABELS], trainer.model.device)
    trainer.train()

    validation_output = trainer.predict(TweetDataset(validation_df, tokenizer, args.max_length, args.text_column))
    validation_predictions = predictions_dataframe(validation_df, validation_output.predictions, np)
    validation_predictions.to_csv(output_dir / "validation_predictions.csv", index=False, encoding="utf-8")
    validation_metrics = compute_metrics(validation_df["label"].astype(str).tolist(), validation_predictions["prediction"].tolist())
    write_metric_artifacts(validation_metrics, output_dir, prefix="validation")

    threshold_result = tune_jihadi_threshold(
        validation_predictions,
        prob_columns=[f"prob_{label}" for label in LABELS],
        target_recall=args.target_recall,
        min_precision=args.min_precision,
    )
    threshold_result["grid"].to_csv(output_dir / "threshold_grid.csv", index=False, encoding="utf-8")
    threshold_selection = threshold_result["chosen"]
    write_json(output_dir / "threshold_selection.json", threshold_selection)
    threshold_predictions = predict_with_jihadi_threshold(
        validation_predictions[[f"prob_{label}" for label in LABELS]].to_numpy(),
        LABELS,
        threshold_selection["threshold"],
    )
    validation_predictions["threshold_prediction"] = threshold_predictions
    validation_predictions.to_csv(output_dir / "validation_predictions.csv", index=False, encoding="utf-8")
    threshold_validation_metrics = compute_metrics(validation_df["label"].astype(str).tolist(), threshold_predictions)
    write_metric_artifacts(threshold_validation_metrics, output_dir, prefix="validation_threshold")

    model_dir = output_dir / "best_model"
    trainer.save_model(str(model_dir))
    tokenizer.save_pretrained(str(model_dir))

    return {
        "weight_name": weight_name,
        "class_weights": class_weights,
        "model_dir": str(model_dir),
        "threshold_selection": threshold_selection,
        "validation_metrics": {
            key: validation_metrics[key]
            for key in [
                "accuracy",
                "macro_f1",
                "weighted_f1",
                "salafi_jihadi_precision",
                "salafi_jihadi_recall",
                "salafi_jihadi_f1",
                "salafi_jihadi_f2",
            ]
        },
        "threshold_validation_metrics": {
            key: threshold_validation_metrics[key]
            for key in [
                "accuracy",
                "macro_f1",
                "weighted_f1",
                "salafi_jihadi_precision",
                "salafi_jihadi_recall",
                "salafi_jihadi_f1",
                "salafi_jihadi_f2",
            ]
        },
    }


def train(args: argparse.Namespace) -> dict[str, object]:
    np, torch, Dataset, AutoModelForSequenceClassification, AutoTokenizer, Trainer, TrainingArguments = _require_transformers()
    TweetDataset = make_dataset_class(Dataset)
    data_dir = Path(args.data_dir)
    run_name = args.run_name or f"transformer_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = Path(args.output_dir) / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    train_df = load_split(data_dir, "train")
    validation_df = load_split(data_dir, "validation")
    test_df = load_split(data_dir, "test")

    base_weights = parse_class_weights(args.class_weights)
    sweep_weights = parse_weight_sweep(args.jihadi_weights, base_weights)

    sweep_results = [
        train_one(args, run_dir, index, weights, train_df, validation_df)
        for index, weights in enumerate(sweep_weights)
    ]
    best = select_best_sweep_result(sweep_results, args.min_precision)

    tokenizer = AutoTokenizer.from_pretrained(best["model_dir"])
    model = AutoModelForSequenceClassification.from_pretrained(best["model_dir"])
    training_args = build_training_arguments(
        TrainingArguments,
        output_dir=str(run_dir / "final_eval_tmp"),
        per_device_eval_batch_size=args.eval_batch_size,
        report_to="none",
    )
    trainer = build_trainer(Trainer, tokenizer, model=model, args=training_args)
    test_output = trainer.predict(TweetDataset(test_df, tokenizer, args.max_length, args.text_column))
    test_predictions = predictions_dataframe(test_df, test_output.predictions, np)
    test_predictions.to_csv(run_dir / "test_predictions.csv", index=False, encoding="utf-8")
    test_metrics = compute_metrics(test_df["label"].astype(str).tolist(), test_predictions["prediction"].tolist())
    write_metric_artifacts(test_metrics, run_dir, prefix="test")

    test_threshold_predictions = predict_with_jihadi_threshold(
        test_predictions[[f"prob_{label}" for label in LABELS]].to_numpy(),
        LABELS,
        best["threshold_selection"]["threshold"],
    )
    test_predictions["threshold_prediction"] = test_threshold_predictions
    test_predictions.to_csv(run_dir / "test_predictions.csv", index=False, encoding="utf-8")
    test_threshold_metrics = compute_metrics(test_df["label"].astype(str).tolist(), test_threshold_predictions)
    write_metric_artifacts(test_threshold_metrics, run_dir, prefix="test_threshold")

    summary = {
        "run_name": run_name,
        "model_name": args.model_name,
        "text_column": args.text_column,
        "max_length": args.max_length,
        "selection_metric": "validation_threshold_salafi_jihadi_f2_with_precision_floor",
        "target_recall": args.target_recall,
        "min_precision": args.min_precision,
        "sweep_results": sweep_results,
        "best": best,
        "test_metrics": {
            key: test_metrics[key]
            for key in [
                "accuracy",
                "macro_f1",
                "weighted_f1",
                "salafi_jihadi_precision",
                "salafi_jihadi_recall",
                "salafi_jihadi_f1",
                "salafi_jihadi_f2",
            ]
        },
        "test_threshold_metrics": {
            key: test_threshold_metrics[key]
            for key in [
                "accuracy",
                "macro_f1",
                "weighted_f1",
                "salafi_jihadi_precision",
                "salafi_jihadi_recall",
                "salafi_jihadi_f1",
                "salafi_jihadi_f2",
            ]
        },
    }
    write_json(run_dir / "run_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(description="Fine-tune a transformer tweet classifier.")
    parser.add_argument("--data-dir", default=str(root / "python/model_training/data"))
    parser.add_argument("--output-dir", default=str(root / "python/model_training/runs"))
    parser.add_argument("--run-name")
    parser.add_argument("--model-name", default="cardiffnlp/twitter-roberta-base")
    parser.add_argument("--fallback-model-name", default="roberta-base", help="Documented fallback; rerun with --model-name if needed.")
    parser.add_argument("--class-weights", help='JSON object, e.g. {"Irrelevant":0.7,"Salafi jihadi":1.8,"Salafi taklidi":1.15}')
    parser.add_argument("--jihadi-weights", default="1.6,2.0,2.4,2.8")
    parser.add_argument("--target-recall", type=float, default=0.80)
    parser.add_argument("--min-precision", type=float, default=0.60)
    parser.add_argument("--text-column", default="model_text")
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--epochs", type=float, default=4)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--eval-batch-size", type=int, default=16)
    parser.add_argument("--warmup-ratio", type=float, default=0.1)
    parser.add_argument("--weight-decay", type=float, default=0.01)
    parser.add_argument("--max-steps", type=int, default=-1, help="Use a small value like 1 for a smoke test; -1 means full training.")
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(train(parse_args()), ensure_ascii=False, indent=2))
