from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

import pandas as pd


LABELS = ["Irrelevant", "Salafi jihadi", "Salafi taklidi"]
LABEL_TO_ID = {label: index for index, label in enumerate(LABELS)}
ID_TO_LABEL = {index: label for label, index in LABEL_TO_ID.items()}
JIHADI_LABEL = "Salafi jihadi"

DEFAULT_CLASS_WEIGHTS = {
    "Irrelevant": 0.7,
    "Salafi jihadi": 1.8,
    "Salafi taklidi": 1.15,
}

DEFAULT_SOURCE_FILES = [
    "python/tweetsFromSite/tweets_from_site5.csv",
    "python/tweetsFromSite/tests_from_site4.csv",
    "python/tweetsFromSite/tweets_from_site4.csv",
    "python/tweetsFromSite/tweets_from_the_site1.csv",
    "python/tweetsFromSite/tweets_from_the_site3.csv",
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def normalize_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip().replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", text)


def twitter_preprocess(value: object) -> str:
    """Match common Twitter-RoBERTa preprocessing for URLs and handles."""
    text = normalize_text(value)
    text = re.sub(r"https?://\S+|www\.\S+", "HTTPURL", text)
    text = re.sub(r"(?<!\w)@\w+", "@USER", text)
    return text


def normalize_label(value: object) -> str:
    if pd.isna(value):
        return ""
    label = str(value).strip()
    aliases = {
        "label_Irrelevant": "Irrelevant",
        "label_Salafi jihadi": "Salafi jihadi",
        "label_Salafi taklidi": "Salafi taklidi",
    }
    return aliases.get(label, label)


def load_site_tweets(root: Path, source_files: Iterable[str] = DEFAULT_SOURCE_FILES) -> pd.DataFrame:
    frames = []
    for source_file in source_files:
        path = root / source_file
        df = pd.read_csv(path)
        text_column = "Text" if "Text" in df.columns else "text"
        if text_column not in df.columns:
            raise ValueError(f"{source_file} is missing Text/text column")
        if "Final Decision" not in df.columns:
            raise ValueError(f"{source_file} is missing Final Decision column")

        frames.append(
            pd.DataFrame(
                {
                    "tweet_id": df["Tweet ID"] if "Tweet ID" in df.columns else "",
                    "text": df[text_column],
                    "model_text": df[text_column].map(twitter_preprocess),
                    "label": df["Final Decision"].map(normalize_label),
                    "source_file": source_file,
                    "normalized_text": df[text_column].map(normalize_text),
                }
            )
        )

    return pd.concat(frames, ignore_index=True)


def parse_class_weights(raw: str | None) -> dict[str, float]:
    if not raw:
        return dict(DEFAULT_CLASS_WEIGHTS)
    weights = json.loads(raw)
    missing = set(LABELS) - set(weights)
    extra = set(weights) - set(LABELS)
    if missing or extra:
        raise ValueError(f"class weights must contain exactly {LABELS}; missing={missing}, extra={extra}")
    return {label: float(weights[label]) for label in LABELS}


def ensure_labels(df: pd.DataFrame, label_column: str = "label") -> None:
    labels = set(df[label_column].dropna().astype(str).str.strip())
    invalid = labels - set(LABELS)
    if invalid:
        raise ValueError(f"invalid labels in {label_column}: {sorted(invalid)}")


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def probability_columns(labels: Iterable[str] = LABELS) -> list[str]:
    return [f"prob_{label}" for label in labels]


def predict_with_jihadi_threshold(
    probabilities,
    labels: list[str],
    jihadi_threshold: float | None = None,
) -> list[str]:
    import numpy as np

    if jihadi_threshold is None:
        return [labels[int(index)] for index in np.asarray(probabilities).argmax(axis=1)]

    jihadi_index = labels.index(JIHADI_LABEL)
    non_jihadi_indices = [index for index, label in enumerate(labels) if label != JIHADI_LABEL]
    predictions = []
    for row in np.asarray(probabilities):
        if row[jihadi_index] >= jihadi_threshold:
            predictions.append(JIHADI_LABEL)
        else:
            best_non_jihadi = non_jihadi_indices[int(np.argmax(row[non_jihadi_indices]))]
            predictions.append(labels[best_non_jihadi])
    return predictions


def add_probability_columns(df: pd.DataFrame, probabilities, labels: list[str]) -> pd.DataFrame:
    output = df.copy()
    for index, label in enumerate(labels):
        output[f"prob_{label}"] = probabilities[:, index]
    return output
