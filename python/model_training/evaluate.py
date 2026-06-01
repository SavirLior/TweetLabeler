from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from common import LABELS, ensure_labels


def _require_sklearn():
    try:
        from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, fbeta_score
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "scikit-learn is required for evaluation. Install with: "
            "pip install -r python/model_training/requirements-ml.txt"
        ) from exc
    return accuracy_score, classification_report, confusion_matrix, fbeta_score


def compute_metrics(y_true: list[str], y_pred: list[str]) -> dict[str, object]:
    accuracy_score, classification_report, confusion_matrix, fbeta_score = _require_sklearn()
    report = classification_report(y_true, y_pred, labels=LABELS, output_dict=True, zero_division=0)
    matrix = confusion_matrix(y_true, y_pred, labels=LABELS)
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(report["macro avg"]["f1-score"]),
        "weighted_f1": float(report["weighted avg"]["f1-score"]),
        "salafi_jihadi_precision": float(report["Salafi jihadi"]["precision"]),
        "salafi_jihadi_recall": float(report["Salafi jihadi"]["recall"]),
        "salafi_jihadi_f1": float(report["Salafi jihadi"]["f1-score"]),
        "salafi_jihadi_f2": float(fbeta_score(y_true, y_pred, labels=LABELS, beta=2, average=None, zero_division=0)[1]),
        "classification_report": report,
        "confusion_matrix": matrix.tolist(),
    }


def write_metric_artifacts(metrics: dict[str, object], output_dir: Path, prefix: str = "") -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{prefix}_" if prefix else ""

    (output_dir / f"{stem}metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = pd.DataFrame(metrics["classification_report"]).transpose()
    report.to_csv(output_dir / f"{stem}classification_report.csv", encoding="utf-8")

    matrix = pd.DataFrame(metrics["confusion_matrix"], index=LABELS, columns=LABELS)
    matrix.to_csv(output_dir / f"{stem}confusion_matrix.csv", encoding="utf-8")


def evaluate_predictions(predictions_csv: Path, output_dir: Path, label_column: str, prediction_column: str) -> dict[str, object]:
    df = pd.read_csv(predictions_csv)
    if label_column not in df.columns:
        raise ValueError(f"{predictions_csv} is missing {label_column}")
    if prediction_column not in df.columns:
        raise ValueError(f"{predictions_csv} is missing {prediction_column}")

    ensure_labels(df, label_column)
    ensure_labels(df.rename(columns={prediction_column: label_column}), label_column)
    metrics = compute_metrics(df[label_column].astype(str).tolist(), df[prediction_column].astype(str).tolist())
    write_metric_artifacts(metrics, output_dir)
    return metrics


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a predictions CSV against true labels.")
    parser.add_argument("--predictions-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--label-column", default="label")
    parser.add_argument("--prediction-column", default="prediction")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = evaluate_predictions(
        Path(args.predictions_csv),
        Path(args.output_dir),
        args.label_column,
        args.prediction_column,
    )
    print(json.dumps({k: v for k, v in result.items() if k not in {"classification_report", "confusion_matrix"}}, indent=2))
