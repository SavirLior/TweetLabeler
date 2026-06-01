from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from common import ID_TO_LABEL, LABELS, predict_with_jihadi_threshold, twitter_preprocess


def _require_transformers():
    try:
        import numpy as np
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "torch/transformers are required for prediction. Install with: "
            "pip install -r python/model_training/requirements-ml.txt"
        ) from exc
    return np, torch, AutoModelForSequenceClassification, AutoTokenizer


def predict(args: argparse.Namespace) -> Path:
    np, torch, AutoModelForSequenceClassification, AutoTokenizer = _require_transformers()
    input_path = Path(args.input_csv)
    output_path = Path(args.output_csv)
    df = pd.read_csv(input_path)
    if args.text_column not in df.columns:
        raise ValueError(f"{input_path} is missing {args.text_column}")

    tokenizer = AutoTokenizer.from_pretrained(args.model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(args.model_dir)
    device = torch.device("cuda" if torch.cuda.is_available() else "mps" if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available() else "cpu")
    model.to(device)
    model.eval()

    probabilities = []
    with torch.inference_mode():
        if args.no_twitter_preprocess:
            texts = df[args.text_column].fillna("").astype(str).tolist()
        else:
            texts = df[args.text_column].map(twitter_preprocess).tolist()
        for start in range(0, len(texts), args.batch_size):
            batch = texts[start : start + args.batch_size]
            encoded = tokenizer(
                batch,
                truncation=True,
                padding=True,
                max_length=args.max_length,
                return_tensors="pt",
            )
            encoded = {key: value.to(device) for key, value in encoded.items()}
            logits = model(**encoded).logits
            batch_probs = torch.softmax(logits, dim=1).detach().cpu().numpy()
            probabilities.append(batch_probs)

    probs = np.vstack(probabilities)
    predictions = predict_with_jihadi_threshold(probs, LABELS, args.jihadi_threshold)
    output = df.copy()
    output["prediction"] = predictions
    if args.jihadi_threshold is not None:
        output["decision_rule"] = f"jihadi_threshold={args.jihadi_threshold}"
    for label_index, label in ID_TO_LABEL.items():
        output[f"prob_{label}"] = probs[:, label_index]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(output_path, index=False, encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Predict tweet labels for a CSV with a fine-tuned transformer model.")
    parser.add_argument("--model-dir", required=True)
    parser.add_argument("--input-csv", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--text-column", default="text")
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=256)
    parser.add_argument("--jihadi-threshold", type=float, help="If set, predict Salafi jihadi when prob_jihadi >= this threshold; otherwise use argmax.")
    parser.add_argument("--no-twitter-preprocess", action="store_true", help="Disable URL/mention normalization before tokenization.")
    return parser.parse_args()


if __name__ == "__main__":
    print(predict(parse_args()))
