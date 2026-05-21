"""Two-phase Twitter/X extraction pipeline backed by Apify.

This module provides infrastructure for:
1. Discovering relevant Twitter/X users from keyword searches.
2. Fetching recent tweets from discovered users.
3. Passing tweet text to a local Fusion model evaluator.

Set APIFY_API_TOKEN in your environment before running against Apify.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import torch
from apify_client import ApifyClient
from transformers import AutoModelForSequenceClassification, AutoTokenizer


APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "YOUR_APIFY_API_TOKEN")
APIFY_ACTOR_ID = "apidojo/tweet-scraper"
MODEL_EXPORT_DIR = Path(__file__).resolve().parent / "model_export_exp_76_iter_153"
MODEL_DIR = MODEL_EXPORT_DIR / "model"
DEFAULT_TWEET_LANGUAGE = "en"
DEFAULT_DISCOVERY_LIMIT = 10
DEFAULT_USER_TWEET_LIMIT = 10
DEFAULT_EXTRA_TWEET_LIMIT = 50
JIHADI_LABEL_TOKEN = "jihadi"

logger = logging.getLogger(__name__)
_local_classifier: "LocalTweetClassifier | None" = None


@dataclass(frozen=True)
class TweetEvaluation:
    """Represents a single tweet classification result from the model layer."""

    tweet: str
    label: str
    flagged: bool
    confidence: float
    probabilities: dict[str, float]


class LocalTweetClassifier:
    """Loads the exported model once and reuses it for batched inference."""

    def __init__(self, model_dir: Path = MODEL_DIR):
        metadata_path = model_dir / "fusion_model_metadata.json"
        if not model_dir.exists():
            raise FileNotFoundError(f"Model directory was not found: {model_dir}")
        if not metadata_path.exists():
            raise FileNotFoundError(f"Model metadata was not found: {metadata_path}")

        with metadata_path.open(encoding="utf-8") as metadata_file:
            self.metadata = json.load(metadata_file)

        self.labels = list(self.metadata["labels"])
        self.max_length = int(self.metadata.get("max_length", 128))
        self.prediction_type = self.metadata.get("prediction_type", "single_label")
        self.device = self._select_device()
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir)
        self.model.to(self.device)
        self.model.eval()

    @staticmethod
    def _select_device() -> torch.device:
        if torch.cuda.is_available():
            return torch.device("cuda")
        if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
            return torch.device("mps")
        return torch.device("cpu")

    @staticmethod
    def _is_jihadi_label(label: str) -> bool:
        return JIHADI_LABEL_TOKEN in label.casefold()

    def predict(self, tweets_list: list[str], batch_size: int = 16) -> list[TweetEvaluation]:
        evaluations: list[TweetEvaluation] = []
        if not tweets_list:
            return evaluations

        with torch.inference_mode():
            for start in range(0, len(tweets_list), batch_size):
                batch = tweets_list[start : start + batch_size]
                encoded = self.tokenizer(
                    batch,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                )
                encoded = {key: value.to(self.device) for key, value in encoded.items()}
                logits = self.model(**encoded).logits

                if self.prediction_type == "multi_label":
                    probabilities_tensor = torch.sigmoid(logits)
                else:
                    probabilities_tensor = torch.softmax(logits, dim=1)

                for tweet, probabilities in zip(
                    batch, probabilities_tensor.detach().cpu().tolist()
                ):
                    predicted_index = max(
                        range(len(probabilities)),
                        key=lambda index: probabilities[index],
                    )
                    label = self.labels[predicted_index]
                    probabilities_by_label = {
                        label_name: float(probability)
                        for label_name, probability in zip(self.labels, probabilities)
                    }
                    evaluations.append(
                        TweetEvaluation(
                            tweet=tweet,
                            label=label,
                            flagged=self._is_jihadi_label(label),
                            confidence=round(float(probabilities[predicted_index]), 6),
                            probabilities=probabilities_by_label,
                        )
                    )

        return evaluations


def get_local_classifier() -> LocalTweetClassifier:
    """Return the process-global classifier, loading it lazily once per run."""
    global _local_classifier
    if _local_classifier is None:
        _local_classifier = LocalTweetClassifier()
    return _local_classifier


def build_apify_client(api_token: str = APIFY_API_TOKEN) -> ApifyClient:
    """Create an Apify client, failing fast if the token was not configured."""
    if not api_token or api_token == "YOUR_APIFY_API_TOKEN":
        raise ValueError(
            "Apify API token is missing. Set APIFY_API_TOKEN in the environment."
        )

    return ApifyClient(api_token)


def normalize_username(username: str) -> str:
    """Normalize a Twitter/X username to a bare handle without the @ prefix."""
    return username.strip().lstrip("@")


def extract_author_username(tweet_item: dict[str, Any]) -> str | None:
    """Extract the author handle from a tweet result returned by the Apify actor."""
    author = tweet_item.get("author")
    if isinstance(author, dict):
        username = author.get("userName") or author.get("username") or author.get("screenName")
        if isinstance(username, str) and username.strip():
            return normalize_username(username)

    for key in ("userName", "username", "screenName", "authorUserName"):
        username = tweet_item.get(key)
        if isinstance(username, str) and username.strip():
            return normalize_username(username)

    return None


def extract_tweet_text(tweet_item: dict[str, Any]) -> str | None:
    """Extract the best available tweet text from an Apify tweet result."""
    candidates: list[str] = []

    for key in ("fullText", "text", "full_text"):
        value = tweet_item.get(key)
        if isinstance(value, str) and value.strip():
            candidates.append(value.strip())

    for nested_key in ("extended_tweet", "legacy"):
        nested = tweet_item.get(nested_key)
        if not isinstance(nested, dict):
            continue

        for text_key in ("full_text", "fullText", "text"):
            value = nested.get(text_key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())

    if not candidates:
        return None

    return max(candidates, key=len)


def run_tweet_scraper(
    client: ApifyClient,
    run_input: dict[str, Any],
) -> list[dict[str, Any]]:
    """Run the configured Apify actor and return dataset items."""
    try:
        logger.info("Starting Apify actor %s", APIFY_ACTOR_ID)
        run = client.actor(APIFY_ACTOR_ID).call(run_input=run_input)
        dataset_id = run.get("defaultDatasetId")

        if not dataset_id:
            logger.warning("Apify run completed without a default dataset id.")
            return []

        items = client.dataset(dataset_id).list_items().items
        return [item for item in items if isinstance(item, dict)]
    except Exception:
        logger.exception("Apify actor call failed.")
        return []


def discover_usernames_by_keywords(
    keywords: Iterable[str],
    *,
    client: ApifyClient | None = None,
    max_items: int = DEFAULT_DISCOVERY_LIMIT,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
) -> list[str]:
    """Search Twitter/X for keywords and return unique author usernames.

    Args:
        keywords: Search terms to send to the Apify tweet scraper.
        client: Optional preconfigured Apify client.
        max_items: Small cap on returned tweets to control Apify credit usage.
        tweet_language: Optional ISO 639-1 language code filter.

    Returns:
        Unique normalized author handles in discovery order.
    """
    clean_keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
    if not clean_keywords:
        logger.warning("No keywords provided for discovery.")
        return []

    apify_client = client or build_apify_client()
    run_input: dict[str, Any] = {
        "searchTerms": clean_keywords,
        "maxItems": max_items,
        "sort": "Latest",
        "includeSearchTerms": False,
        "customMapFunction": "(object) => { return {...object} }",
    }

    if tweet_language:
        run_input["tweetLanguage"] = tweet_language

    items = run_tweet_scraper(apify_client, run_input)

    usernames: list[str] = []
    seen: set[str] = set()
    for item in items:
        username = extract_author_username(item)
        if not username:
            continue

        username_key = username.casefold()
        if username_key not in seen:
            seen.add(username_key)
            usernames.append(username)

    return usernames


def fetch_recent_tweets_for_user(
    username: str,
    *,
    client: ApifyClient | None = None,
    limit: int = DEFAULT_USER_TWEET_LIMIT,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
) -> list[str]:
    """Fetch recent tweets for a specific Twitter/X user.

    Args:
        username: Twitter/X username with or without an @ prefix.
        client: Optional preconfigured Apify client.
        limit: Maximum number of tweets to fetch for this user.
        tweet_language: Optional ISO 639-1 language code filter.

    Returns:
        Tweet text values extracted from the actor dataset.
    """
    normalized_username = normalize_username(username)
    if not normalized_username:
        logger.warning("Cannot fetch tweets for an empty username.")
        return []

    apify_client = client or build_apify_client()
    run_input: dict[str, Any] = {
        "searchTerms": [f"from:{normalized_username} -filter:retweets"],
        "maxItems": limit,
        "sort": "Latest",
        "includeSearchTerms": False,
        "customMapFunction": "(object) => { return {...object} }",
    }

    if tweet_language:
        run_input["tweetLanguage"] = tweet_language

    items = run_tweet_scraper(apify_client, run_input)

    tweets: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = extract_tweet_text(item)
        if not text:
            continue

        dedupe_key = text.casefold()
        if dedupe_key not in seen:
            seen.add(dedupe_key)
            tweets.append(text)

    return tweets


async def evaluate_tweets_with_fusion_model(
    tweets_list: list[str],
) -> list[TweetEvaluation]:
    """Evaluate tweet text with the local model in ./model_export_exp_76_iter_153."""
    await asyncio.sleep(0)
    return get_local_classifier().predict(tweets_list)


async def evaluate_and_scrape_extra_if_jihadi(
    username: str,
    tweets: list[str],
    *,
    client: ApifyClient,
    extra_tweet_limit: int = DEFAULT_EXTRA_TWEET_LIMIT,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
) -> list[TweetEvaluation]:
    """Classify tweets and scrape extra tweets if any are classified as Jihadi."""
    evaluations = await evaluate_tweets_with_fusion_model(tweets)
    flagged_count = sum(evaluation.flagged for evaluation in evaluations)

    if flagged_count == 0:
        logger.info("@%s not flagged: 0/%s jihadi tweets.", username, len(evaluations))
        return evaluations

    logger.warning(
        "@%s flagged: %s/%s tweets classified as Jihadi. Fetching %s extra tweets.",
        username,
        flagged_count,
        len(evaluations),
        extra_tweet_limit,
    )

    extra_tweets = fetch_recent_tweets_for_user(
        username,
        client=client,
        limit=extra_tweet_limit,
        tweet_language=tweet_language,
    )
    seen = {tweet.casefold() for tweet in tweets}
    new_extra_tweets = [tweet for tweet in extra_tweets if tweet.casefold() not in seen]
    if not new_extra_tweets:
        return evaluations

    extra_evaluations = await evaluate_tweets_with_fusion_model(new_extra_tweets)
    return [*evaluations, *extra_evaluations]


async def run_pipeline(
    keywords: Iterable[str],
    *,
    tweets_per_user: int = DEFAULT_USER_TWEET_LIMIT,
    discovery_limit: int = DEFAULT_DISCOVERY_LIMIT,
    extra_tweet_limit: int = DEFAULT_EXTRA_TWEET_LIMIT,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
) -> dict[str, list[TweetEvaluation]]:
    """Run the full two-phase extraction and local-model evaluation pipeline."""
    
    client = build_apify_client()
    usernames = discover_usernames_by_keywords(
        keywords,
        client=client,
        max_items=discovery_limit,
        tweet_language=tweet_language,
    )

    if not usernames:
        logger.warning("No users discovered for the provided keywords.")
        return {}

    results: dict[str, list[TweetEvaluation]] = {}
    for username in usernames:
        tweets = fetch_recent_tweets_for_user(
            username,
            client=client,
            limit=tweets_per_user,
            tweet_language=tweet_language,
        )

        if not tweets:
            logger.info("No tweets fetched for @%s.", username)
            results[username] = []
            continue

        results[username] = await evaluate_and_scrape_extra_if_jihadi(
            username,
            tweets,
            client=client,
            extra_tweet_limit=extra_tweet_limit,
            tweet_language=tweet_language,
        )

    return results


def main() -> None:
    """Example CLI entry point for local pipeline execution."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    example_keywords = ["replace with keyword 1", "replace with keyword 2"]
    asyncio.run(
        run_pipeline(
            example_keywords,
            tweets_per_user=DEFAULT_USER_TWEET_LIMIT,
            discovery_limit=DEFAULT_DISCOVERY_LIMIT,
            extra_tweet_limit=DEFAULT_EXTRA_TWEET_LIMIT,
        )
    )


if __name__ == "__main__":
    main()
