from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from common import DEFAULT_SOURCE_FILES, LABELS, ensure_labels, load_site_tweets, repo_root, write_json


def stratified_split(
    df: pd.DataFrame,
    test_size: float,
    validation_size: float,
    seed: int,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    train_parts = []
    validation_parts = []
    test_parts = []

    for label in LABELS:
        label_df = df[df["label"] == label].sample(frac=1, random_state=seed).reset_index(drop=True)
        n_total = len(label_df)
        n_test = round(n_total * test_size)
        n_validation = round((n_total - n_test) * validation_size)

        test_parts.append(label_df.iloc[:n_test])
        validation_parts.append(label_df.iloc[n_test : n_test + n_validation])
        train_parts.append(label_df.iloc[n_test + n_validation :])

    train = pd.concat(train_parts, ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)
    validation = pd.concat(validation_parts, ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)
    test = pd.concat(test_parts, ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)
    return train, validation, test


def verify_no_text_leakage(splits: dict[str, pd.DataFrame]) -> None:
    seen: dict[str, set[str]] = {}
    for split_name, split_df in splits.items():
        seen[split_name] = set(split_df["normalized_text"])

    names = list(seen)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            overlap = seen[left] & seen[right]
            if overlap:
                raise ValueError(f"normalized_text leakage between {left} and {right}: {len(overlap)} rows")


def build_dataset(args: argparse.Namespace) -> dict[str, object]:
    root = Path(args.root).resolve()
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    raw = load_site_tweets(root, args.source_files)
    raw["label"] = raw["label"].fillna("").astype(str).str.strip()

    blank_labels = raw[raw["label"] == ""].copy()
    labeled = raw[raw["label"] != ""].copy()
    ensure_labels(labeled)

    label_counts_by_text = labeled.groupby("normalized_text")["label"].nunique()
    conflict_keys = set(label_counts_by_text[label_counts_by_text > 1].index)
    conflicts = labeled[labeled["normalized_text"].isin(conflict_keys)].copy()

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
    raw[column_order].to_csv(output_dir / "raw_combined.csv", index=False, encoding="utf-8")
    blank_labels[column_order].to_csv(output_dir / "blank_labels_removed.csv", index=False, encoding="utf-8")
    conflicts[column_order].to_csv(output_dir / "label_conflicts_for_review.csv", index=False, encoding="utf-8")
    clean[column_order].to_csv(output_dir / "clean_with_same_label_duplicates.csv", index=False, encoding="utf-8")
    canonical[column_order].to_csv(output_dir / "canonical_dataset.csv", index=False, encoding="utf-8")
    train[column_order].to_csv(output_dir / "train.csv", index=False, encoding="utf-8")
    validation[column_order].to_csv(output_dir / "validation.csv", index=False, encoding="utf-8")
    test[column_order].to_csv(output_dir / "test.csv", index=False, encoding="utf-8")

    summary = {
        "source_files": args.source_files,
        "seed": args.seed,
        "test_size": args.test_size,
        "validation_size_of_train_pool": args.validation_size,
        "raw_rows": int(len(raw)),
        "blank_label_rows_removed": int(len(blank_labels)),
        "label_conflict_texts_for_review": int(len(conflict_keys)),
        "label_conflict_rows_for_review": int(len(conflicts)),
        "clean_rows_including_same_label_duplicates": int(len(clean)),
        "same_label_duplicate_rows_removed": int(len(clean) - len(canonical)),
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
    parser = argparse.ArgumentParser(description="Prepare canonical tweet classification train/validation/test splits.")
    parser.add_argument("--root", default=str(repo_root()), help="Repository root.")
    parser.add_argument("--output-dir", default=str(repo_root() / "python/model_training/data"))
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--test-size", type=float, default=0.20)
    parser.add_argument("--validation-size", type=float, default=0.15, help="Validation fraction of the non-test pool.")
    parser.add_argument("--source-files", nargs="+", default=DEFAULT_SOURCE_FILES)
    return parser.parse_args()


if __name__ == "__main__":
    print(build_dataset(parse_args()))
