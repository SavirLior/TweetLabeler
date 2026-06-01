from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from common import JIHADI_LABEL, LABELS, predict_with_jihadi_threshold, probability_columns, repo_root, write_json
from evaluate import compute_metrics, write_metric_artifacts


def threshold_grid(min_threshold: float, max_threshold: float, step: float) -> list[float]:
    values = []
    current = min_threshold
    while current <= max_threshold + 1e-9:
        values.append(round(current, 4))
        current += step
    return values


def tune_jihadi_threshold(
    df: pd.DataFrame,
    prob_columns: list[str],
    target_recall: float,
    min_precision: float,
    min_threshold: float = 0.05,
    max_threshold: float = 0.95,
    step: float = 0.01,
) -> dict[str, object]:
    probabilities = df[prob_columns].to_numpy()
    rows = []
    for threshold in threshold_grid(min_threshold, max_threshold, step):
        predictions = predict_with_jihadi_threshold(probabilities, LABELS, threshold)
        metrics = compute_metrics(df["label"].astype(str).tolist(), predictions)
        rows.append(
            {
                "threshold": threshold,
                "accuracy": metrics["accuracy"],
                "macro_f1": metrics["macro_f1"],
                "salafi_jihadi_precision": metrics["salafi_jihadi_precision"],
                "salafi_jihadi_recall": metrics["salafi_jihadi_recall"],
                "salafi_jihadi_f1": metrics["salafi_jihadi_f1"],
                "salafi_jihadi_f2": metrics["salafi_jihadi_f2"],
            }
        )

    grid = pd.DataFrame(rows)
    viable = grid[
        (grid["salafi_jihadi_recall"] >= target_recall)
        & (grid["salafi_jihadi_precision"] >= min_precision)
    ].copy()
    if len(viable):
        chosen = viable.sort_values(
            ["salafi_jihadi_f2", "salafi_jihadi_precision", "macro_f1"],
            ascending=False,
        ).iloc[0]
        selection_reason = "target_recall_and_precision_floor"
    else:
        precision_viable = grid[grid["salafi_jihadi_precision"] >= min_precision].copy()
        if len(precision_viable):
            chosen = precision_viable.sort_values(
                ["salafi_jihadi_recall", "salafi_jihadi_f2", "macro_f1"],
                ascending=False,
            ).iloc[0]
            selection_reason = "precision_floor_best_recall"
        else:
            chosen = grid.sort_values(
                ["salafi_jihadi_f2", "salafi_jihadi_precision", "macro_f1"],
                ascending=False,
            ).iloc[0]
            selection_reason = "best_f2_no_viable_precision_floor"

    chosen_dict = {key: float(value) for key, value in chosen.to_dict().items()}
    chosen_dict["selection_reason"] = selection_reason
    chosen_dict["target_recall"] = float(target_recall)
    chosen_dict["min_precision"] = float(min_precision)
    return {"chosen": chosen_dict, "grid": grid}


def apply_threshold_to_predictions(
    df: pd.DataFrame,
    prob_columns: list[str],
    threshold: float,
    prediction_column: str = "threshold_prediction",
) -> pd.DataFrame:
    output = df.copy()
    output[prediction_column] = predict_with_jihadi_threshold(output[prob_columns].to_numpy(), LABELS, threshold)
    return output


def tune_from_csv(args: argparse.Namespace) -> dict[str, object]:
    predictions = pd.read_csv(args.predictions_csv)
    prob_columns = args.prob_columns or probability_columns()
    missing = [column for column in prob_columns + ["label"] if column not in predictions.columns]
    if missing:
        raise ValueError(f"{args.predictions_csv} is missing columns: {missing}")

    result = tune_jihadi_threshold(
        predictions,
        prob_columns=prob_columns,
        target_recall=args.target_recall,
        min_precision=args.min_precision,
        min_threshold=args.min_threshold,
        max_threshold=args.max_threshold,
        step=args.step,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    result["grid"].to_csv(output_dir / "threshold_grid.csv", index=False, encoding="utf-8")
    write_json(output_dir / "threshold_selection.json", result["chosen"])

    thresholded = apply_threshold_to_predictions(predictions, prob_columns, result["chosen"]["threshold"])
    thresholded.to_csv(output_dir / "threshold_predictions.csv", index=False, encoding="utf-8")
    metrics = compute_metrics(thresholded["label"].astype(str).tolist(), thresholded["threshold_prediction"].astype(str).tolist())
    write_metric_artifacts(metrics, output_dir, prefix="threshold")
    return {"chosen": result["chosen"], "metrics": metrics}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tune a Salafi jihadi probability threshold on validation predictions.")
    parser.add_argument("--predictions-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--target-recall", type=float, default=0.80)
    parser.add_argument("--min-precision", type=float, default=0.60)
    parser.add_argument("--min-threshold", type=float, default=0.05)
    parser.add_argument("--max-threshold", type=float, default=0.95)
    parser.add_argument("--step", type=float, default=0.01)
    parser.add_argument("--prob-columns", nargs="+")
    return parser.parse_args()


if __name__ == "__main__":
    result = tune_from_csv(parse_args())
    printable = {
        "chosen": result["chosen"],
        "metrics": {k: v for k, v in result["metrics"].items() if k not in {"classification_report", "confusion_matrix"}},
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2))
