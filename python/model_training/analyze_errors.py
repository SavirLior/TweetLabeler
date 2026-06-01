from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from common import JIHADI_LABEL, LABELS, probability_columns


def confidence_columns(df: pd.DataFrame) -> list[str]:
    return [column for column in probability_columns() if column in df.columns]


def add_confidence_fields(df: pd.DataFrame) -> pd.DataFrame:
    output = df.copy()
    prob_columns = confidence_columns(output)
    if prob_columns:
        output["prediction_confidence"] = output[prob_columns].max(axis=1)
        output["jihadi_probability"] = output[f"prob_{JIHADI_LABEL}"]
    return output


def write_subset(df: pd.DataFrame, path: Path, columns: list[str]) -> None:
    existing_columns = [column for column in columns if column in df.columns]
    df[existing_columns].to_csv(path, index=False, encoding="utf-8")


def analyze(args: argparse.Namespace) -> dict[str, int]:
    predictions_path = Path(args.predictions_csv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    df = pd.read_csv(predictions_path)
    if args.label_column not in df.columns:
        raise ValueError(f"{predictions_path} is missing {args.label_column}")
    if args.prediction_column not in df.columns:
        raise ValueError(f"{predictions_path} is missing {args.prediction_column}")

    df = add_confidence_fields(df)
    df["is_correct"] = df[args.label_column].astype(str) == df[args.prediction_column].astype(str)
    df["error_type"] = df[args.label_column].astype(str) + "_as_" + df[args.prediction_column].astype(str)

    base_columns = [
        "tweet_id",
        "label",
        args.prediction_column,
        "prediction_confidence",
        "jihadi_probability",
        "source_file",
        "text",
        "model_text",
    ] + probability_columns()

    jihadi_false_negatives = df[(df[args.label_column] == JIHADI_LABEL) & (df[args.prediction_column] != JIHADI_LABEL)].copy()
    jihadi_false_positives = df[(df[args.label_column] != JIHADI_LABEL) & (df[args.prediction_column] == JIHADI_LABEL)].copy()
    all_errors = df[~df["is_correct"]].copy()

    sort_columns = [column for column in ["jihadi_probability", "prediction_confidence"] if column in df.columns]
    if sort_columns:
        jihadi_false_negatives = jihadi_false_negatives.sort_values(sort_columns, ascending=False)
        jihadi_false_positives = jihadi_false_positives.sort_values(sort_columns, ascending=False)
        all_errors = all_errors.sort_values("prediction_confidence", ascending=False)

    write_subset(jihadi_false_negatives, output_dir / "jihadi_false_negatives.csv", base_columns)
    write_subset(jihadi_false_positives, output_dir / "jihadi_false_positives.csv", base_columns)
    write_subset(all_errors, output_dir / "all_errors.csv", base_columns + ["error_type"])

    pair_counts = (
        df.groupby([args.label_column, args.prediction_column])
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
    )
    pair_counts.to_csv(output_dir / "confusion_pair_counts.csv", index=False, encoding="utf-8")

    summary = {
        "rows": int(len(df)),
        "errors": int(len(all_errors)),
        "jihadi_false_negatives": int(len(jihadi_false_negatives)),
        "jihadi_false_positives": int(len(jihadi_false_positives)),
    }
    pd.DataFrame([summary]).to_csv(output_dir / "error_summary.csv", index=False, encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export focused error-analysis files for tweet classifier predictions.")
    parser.add_argument("--predictions-csv", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--label-column", default="label")
    parser.add_argument("--prediction-column", default="prediction")
    return parser.parse_args()


if __name__ == "__main__":
    print(analyze(parse_args()))
