from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from common import ensure_labels, normalize_label, normalize_text, repo_root, twitter_preprocess, write_json
from prepare_dataset import stratified_split, verify_no_text_leakage


def read_input(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    return pd.read_csv(path, encoding="utf-8-sig")


def build_final_dataset(args: argparse.Namespace) -> dict[str, object]:
    input_path = Path(args.input).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    source = read_input(input_path)
    required = {args.id_column, args.text_column, args.label_column}
    missing = required - set(source.columns)
    if missing:
        raise ValueError(f"{input_path} is missing required columns: {sorted(missing)}")

    data = pd.DataFrame(
        {
            "tweet_id": source[args.id_column].fillna("").astype(str).str.strip(),
            "text": source[args.text_column],
            "model_text": source[args.text_column].map(twitter_preprocess),
            "label": source[args.label_column].map(normalize_label),
            "source_file": source["source_file"] if "source_file" in source.columns else str(input_path),
            "normalized_text": source[args.text_column].map(normalize_text),
        }
    )
    data["label"] = data["label"].fillna("").astype(str).str.strip()

    blank_labels = data[data["label"] == ""].copy()
    labeled = data[data["label"] != ""].copy()
    ensure_labels(labeled)

    label_counts_by_text = labeled.groupby("normalized_text")["label"].nunique()
    conflict_keys = set(label_counts_by_text[label_counts_by_text > 1].index)
    conflicts = labeled[labeled["normalized_text"].isin(conflict_keys)].copy()
    if conflict_keys and not args.allow_conflicts:
        conflicts.to_csv(output_dir / "label_conflicts.csv", index=False, encoding="utf-8-sig")
        raise ValueError(f"found {len(conflict_keys)} normalized_text label conflicts; wrote label_conflicts.csv")

    clean = labeled[~labeled["normalized_text"].isin(conflict_keys)].copy()
    canonical = (
        clean.sort_values(["normalized_text", "source_file", "tweet_id"])
        .drop_duplicates("normalized_text", keep="first")
        .reset_index(drop=True)
    )

    train, validation, test = stratified_split(
        canonical,
        test_size=args.test_size,
        validation_size=args.validation_size,
        seed=args.seed,
    )
    verify_no_text_leakage({"train": train, "validation": validation, "test": test})

    column_order = ["tweet_id", "text", "model_text", "label", "source_file", "normalized_text"]
    data[column_order].to_csv(output_dir / "raw_final.csv", index=False, encoding="utf-8-sig")
    blank_labels[column_order].to_csv(output_dir / "blank_labels_removed.csv", index=False, encoding="utf-8-sig")
    conflicts[column_order].to_csv(output_dir / "label_conflicts.csv", index=False, encoding="utf-8-sig")
    canonical[column_order].to_csv(output_dir / "canonical_dataset.csv", index=False, encoding="utf-8-sig")
    train[column_order].to_csv(output_dir / "train.csv", index=False, encoding="utf-8-sig")
    validation[column_order].to_csv(output_dir / "validation.csv", index=False, encoding="utf-8-sig")
    test[column_order].to_csv(output_dir / "test.csv", index=False, encoding="utf-8-sig")

    summary = {
        "input": str(input_path),
        "seed": args.seed,
        "test_size": args.test_size,
        "validation_size_of_train_pool": args.validation_size,
        "raw_rows": int(len(data)),
        "blank_label_rows_removed": int(len(blank_labels)),
        "label_conflict_texts": int(len(conflict_keys)),
        "label_conflict_rows": int(len(conflicts)),
        "canonical_rows": int(len(canonical)),
        "canonical_label_counts": canonical["label"].value_counts().to_dict(),
        "split_rows": {
            "train": int(len(train)),
            "validation": int(len(validation)),
            "test": int(len(test)),
        },
        "split_label_counts": {
            "train": train["label"].value_counts().to_dict(),
            "validation": validation["label"].value_counts().to_dict(),
            "test": test["label"].value_counts().to_dict(),
        },
    }
    write_json(output_dir / "dataset_summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    root = repo_root()
    parser = argparse.ArgumentParser(description="Prepare train/validation/test splits from the final resolved tweet file.")
    parser.add_argument("--input", default=str(root / "python/ELI/all_tweets_plus_site5_final_canonical_readable.csv"))
    parser.add_argument("--output-dir", default=str(root / "python/model_training/data_final"))
    parser.add_argument("--id-column", default="Tweet ID")
    parser.add_argument("--text-column", default="Text")
    parser.add_argument("--label-column", default="Final Decision")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--test-size", type=float, default=0.20)
    parser.add_argument("--validation-size", type=float, default=0.15)
    parser.add_argument("--allow-conflicts", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(build_final_dataset(parse_args()))
