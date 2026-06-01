from __future__ import annotations

import argparse
import json
import pickle
from datetime import datetime
from pathlib import Path

import pandas as pd

from common import LABELS, add_probability_columns, parse_class_weights, predict_with_jihadi_threshold, repo_root
from evaluate import compute_metrics, write_metric_artifacts
from threshold_tuning import tune_jihadi_threshold


def _require_sklearn():
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.svm import LinearSVC
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "scikit-learn is required for the baseline. Install with: "
            "pip install -r python/model_training/requirements-ml.txt"
        ) from exc
    return TfidfVectorizer, LogisticRegression, LinearSVC, Pipeline


def load_split(data_dir: Path, name: str) -> pd.DataFrame:
    path = data_dir / f"{name}.csv"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run prepare_dataset.py first.")
    return pd.read_csv(path)


def build_pipeline(args: argparse.Namespace, class_weights: dict[str, float]):
    TfidfVectorizer, LogisticRegression, LinearSVC, Pipeline = _require_sklearn()
    vectorizer = TfidfVectorizer(
        lowercase=True,
        strip_accents="unicode",
        ngram_range=(1, args.max_ngram),
        min_df=args.min_df,
        max_features=args.max_features,
        sublinear_tf=True,
    )
    if args.model == "linear_svm":
        classifier = LinearSVC(class_weight=class_weights, random_state=args.seed)
    else:
        classifier = LogisticRegression(
            class_weight=class_weights,
            max_iter=args.max_iter,
            solver="lbfgs",
            random_state=args.seed,
        )
    return Pipeline([("tfidf", vectorizer), ("classifier", classifier)])


def add_predictions(df: pd.DataFrame, predictions: list[str]) -> pd.DataFrame:
    output = df.copy()
    output["prediction"] = predictions
    return output


def predict_probabilities(pipeline, texts: pd.Series):
    if not hasattr(pipeline, "predict_proba"):
        return None
    return pipeline.predict_proba(texts.astype(str))


def train(args: argparse.Namespace) -> dict[str, object]:
    data_dir = Path(args.data_dir)
    run_name = args.run_name or f"baseline_{args.model}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir = Path(args.output_dir) / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    train_df = load_split(data_dir, "train")
    validation_df = load_split(data_dir, "validation")
    test_df = load_split(data_dir, "test")
    class_weights = parse_class_weights(args.class_weights)

    pipeline = build_pipeline(args, class_weights)
    pipeline.fit(train_df["text"].astype(str), train_df["label"].astype(str))

    validation_probabilities = predict_probabilities(pipeline, validation_df[args.text_column])
    threshold_selection = None
    if validation_probabilities is not None:
        validation_probs_df = add_probability_columns(validation_df, validation_probabilities, list(pipeline.classes_))
        threshold_result = tune_jihadi_threshold(
            validation_probs_df,
            prob_columns=[f"prob_{label}" for label in LABELS],
            target_recall=args.target_recall,
            min_precision=args.min_precision,
        )
        threshold_selection = threshold_result["chosen"]
        threshold_result["grid"].to_csv(run_dir / "threshold_grid.csv", index=False, encoding="utf-8")
        (run_dir / "threshold_selection.json").write_text(
            json.dumps(threshold_selection, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    summary = {
        "run_name": run_name,
        "model": args.model,
        "text_column": args.text_column,
        "class_weights": class_weights,
        "threshold_selection": threshold_selection,
        "validation": {},
        "test": {},
        "threshold_validation": {},
        "threshold_test": {},
    }

    for split_name, split_df in [("validation", validation_df), ("test", test_df)]:
        texts = split_df[args.text_column].astype(str)
        predictions = pipeline.predict(texts).tolist()
        predictions_df = add_predictions(split_df, predictions)
        probabilities = predict_probabilities(pipeline, texts)
        if probabilities is not None:
            predictions_df = add_probability_columns(predictions_df, probabilities, list(pipeline.classes_))
        predictions_df.to_csv(run_dir / f"{split_name}_predictions.csv", index=False, encoding="utf-8")
        metrics = compute_metrics(split_df["label"].astype(str).tolist(), predictions)
        write_metric_artifacts(metrics, run_dir, prefix=split_name)
        summary[split_name] = {
            key: metrics[key]
            for key in [
                "accuracy",
                "macro_f1",
                "weighted_f1",
                "salafi_jihadi_precision",
                "salafi_jihadi_recall",
                "salafi_jihadi_f1",
                "salafi_jihadi_f2",
            ]
        }

        if threshold_selection is not None and probabilities is not None:
            threshold_predictions = predict_with_jihadi_threshold(
                probabilities,
                list(pipeline.classes_),
                threshold_selection["threshold"],
            )
            threshold_df = predictions_df.copy()
            threshold_df["threshold_prediction"] = threshold_predictions
            threshold_df.to_csv(run_dir / f"{split_name}_threshold_predictions.csv", index=False, encoding="utf-8")
            threshold_metrics = compute_metrics(split_df["label"].astype(str).tolist(), threshold_predictions)
            write_metric_artifacts(threshold_metrics, run_dir, prefix=f"{split_name}_threshold")
            summary[f"threshold_{split_name}"] = {
                key: threshold_metrics[key]
                for key in [
                    "accuracy",
                    "macro_f1",
                    "weighted_f1",
                    "salafi_jihadi_precision",
                    "salafi_jihadi_recall",
                    "salafi_jihadi_f1",
                    "salafi_jihadi_f2",
                ]
            }

    with (run_dir / "baseline_model.pkl").open("wb") as model_file:
        pickle.dump(pipeline, model_file)
    (run_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(description="Train a TF-IDF baseline for tweet classification.")
    parser.add_argument("--data-dir", default=str(root / "python/model_training/data"))
    parser.add_argument("--output-dir", default=str(root / "python/model_training/runs"))
    parser.add_argument("--run-name")
    parser.add_argument("--model", choices=["logistic", "linear_svm"], default="logistic")
    parser.add_argument("--class-weights", help='JSON object, e.g. {"Irrelevant":0.7,"Salafi jihadi":1.8,"Salafi taklidi":1.15}')
    parser.add_argument("--text-column", default="model_text")
    parser.add_argument("--target-recall", type=float, default=0.80)
    parser.add_argument("--min-precision", type=float, default=0.60)
    parser.add_argument("--max-features", type=int, default=50000)
    parser.add_argument("--max-ngram", type=int, default=2)
    parser.add_argument("--min-df", type=int, default=2)
    parser.add_argument("--max-iter", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(train(parse_args()), ensure_ascii=False, indent=2))
