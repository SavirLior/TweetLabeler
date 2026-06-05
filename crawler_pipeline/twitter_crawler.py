"""Two-phase Twitter/X extraction pipeline backed by Apify.

This module provides infrastructure for:
1. Discovering relevant Twitter/X users from keyword searches.
2. Fetching recent tweets from discovered users.
3. Passing tweet text to a local Fusion model evaluator.

Set APIFY_API_TOKEN in your environment before running against Apify.
"""

from __future__ import annotations

import asyncio
import argparse
import json
import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import torch
from apify_client import ApifyClient
from transformers import AutoModelForSequenceClassification, AutoTokenizer

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

try:
    from .config import (
        APIFY_ACTOR_ID,
        DEFAULT_DEEP_DIVE_TWEET_LIMIT,
        DEFAULT_DISCOVERY_LIMIT,
        DEFAULT_MIN_PROFILE_EVALUATED_TWEETS,
        DEFAULT_MIN_POSITIVE_TWEETS,
        DEFAULT_POSITIVE_RATIO_THRESHOLD,
        DEFAULT_PROFILE_OVERFETCH_MULTIPLIER,
        DEFAULT_TAKLIDI_RATIO_MARGIN,
        DEFAULT_TAKLIDI_RATIO_THRESHOLD,
        DEFAULT_TWEET_LANGUAGE,
        DEFAULT_USER_TWEET_LIMIT,
        JIHADI_LABEL_TOKEN,
        KEYWORDS_FILE,
        MODEL_DIR,
        MODEL_EXPORT_DIR,
        FINAL_JIHADI_USERS_FILE,
        TAKLIDI_LABEL,
    )
    from .mongo_store import (
        CrawlerMongoStore,
        calculate_classification_score,
        make_tweet_key,
    )
    from .tweet_text_formatter import (
        FILTER_ARABIC,
        FILTER_EMPTY_TEXT,
        FILTER_SHORT_TEXT,
        format_tweet_text,
        get_quote_object,
        get_retweet_object,
    )
except ImportError:  # Allows running this file directly from crawler_pipeline/.
    from config import (
        APIFY_ACTOR_ID,
        DEFAULT_DEEP_DIVE_TWEET_LIMIT,
        DEFAULT_DISCOVERY_LIMIT,
        DEFAULT_MIN_PROFILE_EVALUATED_TWEETS,
        DEFAULT_MIN_POSITIVE_TWEETS,
        DEFAULT_POSITIVE_RATIO_THRESHOLD,
        DEFAULT_PROFILE_OVERFETCH_MULTIPLIER,
        DEFAULT_TAKLIDI_RATIO_MARGIN,
        DEFAULT_TAKLIDI_RATIO_THRESHOLD,
        DEFAULT_TWEET_LANGUAGE,
        DEFAULT_USER_TWEET_LIMIT,
        JIHADI_LABEL_TOKEN,
        KEYWORDS_FILE,
        MODEL_DIR,
        MODEL_EXPORT_DIR,
        FINAL_JIHADI_USERS_FILE,
        TAKLIDI_LABEL,
    )
    from mongo_store import (
        CrawlerMongoStore,
        calculate_classification_score,
        make_tweet_key,
    )
    from tweet_text_formatter import (
        FILTER_ARABIC,
        FILTER_EMPTY_TEXT,
        FILTER_SHORT_TEXT,
        format_tweet_text,
        get_quote_object,
        get_retweet_object,
    )


APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "YOUR_APIFY_API_TOKEN")
PROFILE_OVERFETCH_MULTIPLIER = DEFAULT_PROFILE_OVERFETCH_MULTIPLIER
MIN_PROFILE_EVALUATED_TWEETS = DEFAULT_MIN_PROFILE_EVALUATED_TWEETS
USER_JIHADI_TWEET_THRESHOLD = DEFAULT_MIN_POSITIVE_TWEETS
POSITIVE_RATIO_THRESHOLD = DEFAULT_POSITIVE_RATIO_THRESHOLD
TAKLIDI_RATIO_THRESHOLD = DEFAULT_TAKLIDI_RATIO_THRESHOLD
TAKLIDI_RATIO_MARGIN = DEFAULT_TAKLIDI_RATIO_MARGIN
TRAINING_USERS_FILE = Path(__file__).resolve().parent / "training_users.txt"

logger = logging.getLogger(__name__)
_local_classifier: "LocalTweetClassifier | None" = None
_training_usernames: set[str] | None = None


@dataclass(frozen=True)
class TweetEvaluation:
    """Represents a single tweet classification result from the model layer."""

    tweet: str
    label: str
    flagged: bool
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class DiscoveredTweet:
    """Represents a keyword-discovered tweet and the author needed for deep dives."""

    username: str
    text: str
    tweet_key: str
    tweet_id: str | None = None
    tweet_url: str | None = None
    source: dict[str, Any] | None = None
    format_version: str | None = None
    is_retweet: bool = False
    is_quote: bool = False
    source_text_kind: str | None = None


@dataclass(frozen=True)
class TweetCollectionResult:
    """Formatted tweets plus counts for raw and filtered Apify items."""

    tweets: list[DiscoveredTweet]
    counts: dict[str, int]


@dataclass(frozen=True)
class EvaluatedTweet:
    """A crawled tweet paired with its model evaluation and crawl phase."""

    tweet: DiscoveredTweet
    evaluation: TweetEvaluation
    phase: str


@dataclass(frozen=True)
class UserDeepDiveResult:
    """The complete model-backed verification result for a Twitter/X user."""

    username: str
    status: str
    score: dict[str, Any]
    trigger_evidence: list[EvaluatedTweet]
    profile_evidence: list[EvaluatedTweet]
    profile_counts: dict[str, int]

    @property
    def all_evidence(self) -> list[EvaluatedTweet]:
        return [*self.trigger_evidence, *self.profile_evidence]

    @property
    def all_evaluations(self) -> list[TweetEvaluation]:
        return [evidence.evaluation for evidence in self.all_evidence]


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
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)#transformer the data to numbers for the model to understand
        self.model = AutoModelForSequenceClassification.from_pretrained(model_dir)#load the model from the directory and move it to the selected device (GPU, MPS, or CPU)
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

    def predict(
        self,
        tweets_list: list[str],
        batch_size: int = 16,
    ) -> list[TweetEvaluation]:
        evaluations: list[TweetEvaluation] = []
        if not tweets_list:
            return evaluations

        with torch.inference_mode():
            for start in range(0, len(tweets_list), batch_size):
                batch = tweets_list[start : start + batch_size]#process the tweets in batches to optimize performance and resource usage
                encoded = self.tokenizer(#tokenize the batch of tweets (create Tensors matrices of input IDs and attention masks)
                    batch,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                    max_length=self.max_length,
                )
                encoded = {key: value.to(self.device) for key, value in encoded.items()}#move the tokenized inputs to the same device as the model for efficient inference
                logits = self.model(**encoded).logits

                if self.prediction_type == "multi_label":
                    probabilities_tensor = torch.sigmoid(logits)
                else:
                    probabilities_tensor = torch.softmax(logits, dim=1)

                for tweet, probabilities in zip(
                    batch, probabilities_tensor.detach().cpu().tolist()#convert the probabilities back to CPU and to a list format for easier processing
                ):
                    predicted_index = max(
                        range(len(probabilities)),
                        key=lambda index: probabilities[index],
                    )
                    label = self.labels[predicted_index]
                    probabilities_by_label = {#create a dictionary mapping each label to its corresponding probability for this tweet, which can be useful for understanding the model's confidence across all classes, not just the predicted one
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


def is_deep_dive_trigger(evaluation: TweetEvaluation) -> bool:
    return evaluation.flagged or evaluation.label == TAKLIDI_LABEL


def build_apify_client(api_token: str = APIFY_API_TOKEN) -> ApifyClient:
    """Create an Apify client, failing fast if the token was not configured."""
    if not api_token or api_token == "YOUR_APIFY_API_TOKEN":
        raise ValueError(
            "Apify API token is missing. Set APIFY_API_TOKEN in the environment."
        )

    return ApifyClient(api_token)


def normalize_username(username: str) -> str:
    """Normalize a Twitter/X username to a bare handle."""
    return username.strip().lstrip("@/").rstrip("/")


def username_key(username: str) -> str:
    """Return the case-insensitive key used for username comparisons."""
    return normalize_username(username).casefold()


def load_training_usernames() -> set[str]:
    """Load training-list usernames once so crawler runs skip known users quickly."""
    global _training_usernames
    if _training_usernames is not None:
        return _training_usernames

    if not TRAINING_USERS_FILE.exists():
        logger.warning("Training users file was not found: %s", TRAINING_USERS_FILE)
        _training_usernames = set()
        return _training_usernames

    usernames: set[str] = set()
    with TRAINING_USERS_FILE.open(encoding="utf-8") as training_file:
        for line in training_file:
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            key = username_key(value)
            if key:
                usernames.add(key)

    _training_usernames = usernames
    logger.info("Loaded %s training users to skip.", len(_training_usernames))
    return _training_usernames


def is_training_user(username: str) -> bool:
    """Return True when a normalized username is already in training_users.txt."""
    key = username_key(username)
    return bool(key and key in load_training_usernames())


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


def extract_tweet_id(tweet_item: dict[str, Any]) -> str | None:
    """Extract the tweet id from an Apify tweet result when available."""
    for key in ("id", "tweetId", "tweet_id", "id_str", "conversationId"):
        value = tweet_item.get(key)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()

    for nested_key in ("legacy", "tweet"):
        nested = tweet_item.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key in ("id", "tweetId", "tweet_id", "id_str"):
            value = nested.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return str(value).strip()

    return None


def extract_tweet_url(
    tweet_item: dict[str, Any],
    *,
    username: str,
    tweet_id: str | None,
) -> str | None:
    """Extract or construct a stable X/Twitter status URL."""
    for key in ("url", "twitterUrl", "tweetUrl", "link"):
        value = tweet_item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    if tweet_id:
        return f"https://x.com/{normalize_username(username)}/status/{tweet_id}"

    return None


def first_present_value(source: dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
    return None


def parse_count(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        clean_value = value.strip().replace(",", "")
        if clean_value.isdigit():
            return int(clean_value)
    return None


def extract_tweet_count(tweet_item: dict[str, Any], keys: Iterable[str]) -> int | None:
    value = first_present_value(tweet_item, keys)
    if value is not None:
        return parse_count(value)

    legacy = tweet_item.get("legacy")
    if isinstance(legacy, dict):
        value = first_present_value(legacy, keys)
        if value is not None:
            return parse_count(value)

    return None


def extract_author_summary(tweet_item: dict[str, Any]) -> dict[str, Any]:
    author = tweet_item.get("author")
    if not isinstance(author, dict):
        return {}

    return {
        "id": author.get("id") or author.get("userId") or author.get("rest_id"),
        "username": author.get("userName") or author.get("username") or author.get("screenName"),
        "name": author.get("name") or author.get("displayName"),
        "location": first_present_value(author, ("location", "userLocation")),
        "description": first_present_value(author, ("description", "bio")),
        "followers_count": parse_count(
            first_present_value(
                author,
                ("followers", "followersCount", "followers_count", "followerCount"),
            )
        ),
        "following_count": parse_count(
            first_present_value(
                author,
                ("following", "followingCount", "friendsCount", "friends_count"),
            )
        ),
        "tweet_count": parse_count(
            first_present_value(
                author,
                ("statusesCount", "statuses_count", "tweetCount", "tweetsCount"),
            )
        ),
        "verified": bool(first_present_value(author, ("isVerified", "verified"))),
    }


def extract_nested_tweet_summary(tweet_item: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(tweet_item, dict):
        return None

    username = extract_author_username(tweet_item) or ""
    tweet_id = extract_tweet_id(tweet_item)
    return {
        "tweet_id": tweet_id,
        "tweet_url": extract_tweet_url(tweet_item, username=username, tweet_id=tweet_id),
        "lang": tweet_item.get("lang"),
        "author": extract_author_summary(tweet_item),
    }


def build_compact_source(tweet_item: dict[str, Any], *, username: str, tweet_id: str | None) -> dict[str, Any]:
    return {
        "provider": "apify",
        "actor_id": APIFY_ACTOR_ID,
        "tweet_id": tweet_id,
        "tweet_url": extract_tweet_url(tweet_item, username=username, tweet_id=tweet_id),
        "created_at": tweet_item.get("createdAt") or tweet_item.get("created_at"),
        "lang": tweet_item.get("lang"),
        "like_count": extract_tweet_count(
            tweet_item,
            ("likeCount", "likes", "favoriteCount", "favorite_count"),
        ),
        "reply_count": extract_tweet_count(tweet_item, ("replyCount", "replies")),
        "retweet_count": extract_tweet_count(tweet_item, ("retweetCount", "retweets")),
        "quote_count": extract_tweet_count(tweet_item, ("quoteCount", "quotes")),
        "view_count": extract_tweet_count(
            tweet_item,
            ("viewCount", "views", "impressionCount", "impressions"),
        ),
        "bookmark_count": extract_tweet_count(tweet_item, ("bookmarkCount", "bookmarks")),
        "author": extract_author_summary(tweet_item),
        "retweet": extract_nested_tweet_summary(get_retweet_object(tweet_item)),
        "quote": extract_nested_tweet_summary(get_quote_object(tweet_item)),
    }


def build_discovered_tweet(tweet_item: dict[str, Any]) -> DiscoveredTweet | None:
    """Normalize an Apify tweet item into the crawler's tweet shape."""
    username = extract_author_username(tweet_item)
    formatted_result = format_tweet_text(tweet_item)
    if not username or not formatted_result.formatted:
        return None
    if is_training_user(username):
        logger.info("Skipping @%s because it is already in training_users.txt.", username)
        return None

    formatted = formatted_result.formatted
    tweet_id = extract_tweet_id(tweet_item)
    return DiscoveredTweet(
        username=username,
        text=formatted.text,
        tweet_id=tweet_id,
        tweet_key=make_tweet_key(username, formatted.text, tweet_id=tweet_id),
        tweet_url=extract_tweet_url(tweet_item, username=username, tweet_id=tweet_id),
        source=build_compact_source(tweet_item, username=username, tweet_id=tweet_id),
        format_version=formatted.format_version,
        is_retweet=formatted.is_retweet,
        is_quote=formatted.is_quote,
        source_text_kind=formatted.source_text_kind,
    )


def calculate_overfetch_limit(
    target_clean_tweets: int,
    overfetch_multiplier: float = PROFILE_OVERFETCH_MULTIPLIER,
) -> int:
    if target_clean_tweets <= 0:
        return 0
    return max(target_clean_tweets, math.ceil(target_clean_tweets * overfetch_multiplier))


def add_counts(target: dict[str, int], source: dict[str, int]) -> None:
    for key, value in source.items():
        target[key] = target.get(key, 0) + int(value)


def empty_filter_counts(scope: str = "") -> dict[str, int]:
    raw_key = f"raw_{scope}_tweets_seen" if scope else "raw_tweets_seen"
    return {
        raw_key: 0,
        "filtered_arabic": 0,
        "filtered_empty_text": 0,
        "filtered_short_text": 0,
        "filtered_training_user": 0,
    }


def increment_filter_count(counts: dict[str, int], reason: str | None) -> None:
    if reason == FILTER_ARABIC:
        counts["filtered_arabic"] += 1
    elif reason == FILTER_EMPTY_TEXT:
        counts["filtered_empty_text"] += 1
    elif reason == FILTER_SHORT_TEXT:
        counts["filtered_short_text"] += 1


def build_discovered_tweets_from_items(
    items: Iterable[dict[str, Any]],
    *,
    scope: str = "",
    max_clean_tweets: int | None = None,
    exclude_tweet_keys: set[str] | None = None,
) -> TweetCollectionResult:
    counts = empty_filter_counts(scope)
    raw_key = f"raw_{scope}_tweets_seen" if scope else "raw_tweets_seen"
    tweets: list[DiscoveredTweet] = []
    seen: set[tuple[str, str]] = set()
    excluded_keys = exclude_tweet_keys or set()

    for item in items:
        counts[raw_key] += 1
        username = extract_author_username(item)
        if username and is_training_user(username):
            counts["filtered_training_user"] += 1
            logger.info(
                "Skipping @%s because it is already in training_users.txt.",
                username,
            )
            continue

        formatted_result = format_tweet_text(item)
        if not formatted_result.formatted:
            increment_filter_count(counts, formatted_result.filter_reason)
            continue

        discovered_tweet = build_discovered_tweet(item)
        if not discovered_tweet:
            counts["filtered_empty_text"] += 1
            continue
        if discovered_tweet.tweet_key in excluded_keys:
            continue

        dedupe_key = (
            discovered_tweet.username.casefold(),
            discovered_tweet.tweet_key,
        )
        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        tweets.append(discovered_tweet)
        if max_clean_tweets is not None and len(tweets) >= max_clean_tweets:
            break

    return TweetCollectionResult(tweets=tweets, counts=counts)


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
        return [item for item in items if isinstance(item, dict)]#filter out any non-dict items just in case, since we expect each item to be a dict representing a tweet result
    except Exception:
        logger.exception("Apify actor call failed.")
        raise


def discover_tweets_by_keywords(
    keywords: Iterable[str],
    *,
    client: ApifyClient | None = None,
    max_items: int = DEFAULT_DISCOVERY_LIMIT,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
) -> list[DiscoveredTweet]:
    """Search Twitter/X for keywords and return tweet text with author handles.

    Args:
        keywords: Search terms to send to the Apify tweet scraper.
        client: Optional preconfigured Apify client.
        max_items: Small cap on returned tweets to control Apify credit usage.
        tweet_language: Optional ISO 639-1 language code filter.

    Returns:
        Keyword-discovered tweets in actor result order.
    """
    clean_keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
    if not clean_keywords:
        logger.warning("No keywords provided for discovery.")
        return []

    apify_client = client or build_apify_client()
    run_input: dict[str, Any] = {
        "searchTerms": clean_keywords,
        "maxItems": max_items,
        "sort": "Latest",#sort the results by latest tweets first to increase the chances of discovering active users
        "includeSearchTerms": False,
        "customMapFunction": "(object) => { return {...object} }",
    }

    if tweet_language:
        run_input["tweetLanguage"] = tweet_language

    items = run_tweet_scraper(apify_client, run_input)
    return build_discovered_tweets_from_items(items, scope="discovery").tweets


def discover_tweet_collection_by_keywords(
    keywords: Iterable[str],
    *,
    client: ApifyClient | None = None,
    max_items: int = DEFAULT_DISCOVERY_LIMIT,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
) -> TweetCollectionResult:
    """Search Twitter/X for keywords and return formatted tweets plus counters."""
    clean_keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
    if not clean_keywords:
        logger.warning("No keywords provided for discovery.")
        return TweetCollectionResult(
            tweets=[],
            counts={
                **empty_filter_counts("discovery"),
                "model_discovery_tweets_evaluated": 0,
            },
        )

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
    result = build_discovered_tweets_from_items(items, scope="discovery")
    result.counts["model_discovery_tweets_evaluated"] = len(result.tweets)
    return result


def discover_usernames_by_keywords(
    keywords: Iterable[str],
    *,
    client: ApifyClient | None = None,
    max_items: int = DEFAULT_DISCOVERY_LIMIT,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
) -> list[str]:
    """Search Twitter/X for keywords and return unique author usernames."""
    usernames: list[str] = []
    seen: set[str] = set()
    for discovered_tweet in discover_tweets_by_keywords(
        keywords,
        client=client,
        max_items=max_items,
        tweet_language=tweet_language,
    ):
        username_key = discovered_tweet.username.casefold()
        if username_key in seen:
            continue
        seen.add(username_key)
        usernames.append(discovered_tweet.username)

    return usernames


def fetch_recent_tweet_details_for_user(
    username: str,
    *,
    client: ApifyClient | None = None,
    limit: int = DEFAULT_USER_TWEET_LIMIT,
    overfetch_multiplier: float = PROFILE_OVERFETCH_MULTIPLIER,
    exclude_tweet_keys: set[str] | None = None,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
) -> list[DiscoveredTweet]:
    """Fetch recent tweets for a specific Twitter/X user.

    Args:
        username: Twitter/X username with or without an @ prefix.
        client: Optional preconfigured Apify client.
        limit: Clean-tweet target used to calculate the raw Apify fetch limit.
        tweet_language: Optional ISO 639-1 language code filter.

    Returns:
        Tweet text values extracted from the actor dataset.
    """
    normalized_username = normalize_username(username)
    if not normalized_username:
        logger.warning("Cannot fetch tweets for an empty username.")
        return []

    apify_client = client or build_apify_client()
    raw_limit = calculate_overfetch_limit(limit, overfetch_multiplier)
    run_input: dict[str, Any] = {
        "searchTerms": [f"from:{normalized_username} -filter:retweets"],
        "maxItems": raw_limit,
        "sort": "Latest",
        "includeSearchTerms": False,
        "customMapFunction": "(object) => { return {...object} }",
    }

    if tweet_language:
        run_input["tweetLanguage"] = tweet_language

    items = run_tweet_scraper(apify_client, run_input)
    return build_discovered_tweets_from_items(
        items,
        scope="profile",
        exclude_tweet_keys=exclude_tweet_keys,
    ).tweets


def fetch_recent_tweet_collection_for_user(
    username: str,
    *,
    client: ApifyClient | None = None,
    limit: int = DEFAULT_USER_TWEET_LIMIT,
    overfetch_multiplier: float = PROFILE_OVERFETCH_MULTIPLIER,
    exclude_tweet_keys: set[str] | None = None,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
) -> TweetCollectionResult:
    """Fetch and format recent profile tweets plus raw/filter counters."""
    normalized_username = normalize_username(username)
    if not normalized_username:
        logger.warning("Cannot fetch tweets for an empty username.")
        return TweetCollectionResult(
            tweets=[],
            counts={
                **empty_filter_counts("profile"),
                "model_profile_tweets_evaluated": 0,
            },
        )

    apify_client = client or build_apify_client()
    raw_limit = calculate_overfetch_limit(limit, overfetch_multiplier)
    run_input: dict[str, Any] = {
        "searchTerms": [f"from:{normalized_username} -filter:retweets"],
        "maxItems": raw_limit,
        "sort": "Latest",
        "includeSearchTerms": False,
        "customMapFunction": "(object) => { return {...object} }",
    }

    if tweet_language:
        run_input["tweetLanguage"] = tweet_language

    items = run_tweet_scraper(apify_client, run_input)
    result = build_discovered_tweets_from_items(
        items,
        scope="profile",
        exclude_tweet_keys=exclude_tweet_keys,
    )
    result.counts["model_profile_tweets_evaluated"] = len(result.tweets)
    return result


def fetch_recent_tweets_for_user(
    username: str,
    *,
    client: ApifyClient | None = None,
    limit: int = DEFAULT_USER_TWEET_LIMIT,
    overfetch_multiplier: float = PROFILE_OVERFETCH_MULTIPLIER,
    exclude_tweet_keys: set[str] | None = None,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
) -> list[str]:
    """Fetch recent tweet texts for callers that do not need metadata."""
    return [
        tweet.text
        for tweet in fetch_recent_tweet_details_for_user(
            username,
            client=client,
            limit=limit,
            overfetch_multiplier=overfetch_multiplier,
            exclude_tweet_keys=exclude_tweet_keys,
            tweet_language=tweet_language,
        )
    ]


async def evaluate_tweets_with_fusion_model(
    tweets_list: list[str],
    *,
    batch_size: int = 16,
) -> list[TweetEvaluation]:
    """Evaluate tweet text with the configured local model export."""
    await asyncio.sleep(0)
    return get_local_classifier().predict(tweets_list, batch_size=batch_size)


async def verify_user_from_triggered_tweet(
    username: str,
    triggered_tweets: list[DiscoveredTweet],
    initial_evaluations: list[TweetEvaluation],
    *,
    client: ApifyClient,
    deep_dive_tweet_limit: int = DEFAULT_DEEP_DIVE_TWEET_LIMIT,
    min_positive_tweets: int = USER_JIHADI_TWEET_THRESHOLD,
    min_profile_evaluated_tweets: int = MIN_PROFILE_EVALUATED_TWEETS,
    positive_ratio_threshold: float = POSITIVE_RATIO_THRESHOLD,
    taklidi_ratio_threshold: float = TAKLIDI_RATIO_THRESHOLD,
    taklidi_ratio_margin: float = TAKLIDI_RATIO_MARGIN,
    profile_overfetch_multiplier: float = PROFILE_OVERFETCH_MULTIPLIER,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
) -> UserDeepDiveResult:
    """Deep-dive a triggered author and return the full verification result."""
    logger.info(
        "Tweet triggered deep dive for @%s. Fetching %s additional recent tweets.",
        username,
        deep_dive_tweet_limit,
    )

    trigger_evidence = [
        EvaluatedTweet(tweet=tweet, evaluation=evaluation, phase="keyword_trigger")
        for tweet, evaluation in zip(triggered_tweets, initial_evaluations)
    ]
    seen_tweet_keys = {evidence.tweet.tweet_key for evidence in trigger_evidence}
    profile_collection = fetch_recent_tweet_collection_for_user(
        username,
        client=client,
        limit=deep_dive_tweet_limit,
        overfetch_multiplier=profile_overfetch_multiplier,
        exclude_tweet_keys=seen_tweet_keys,
        tweet_language=tweet_language,
    )
    additional_tweets = profile_collection.tweets
    additional_evaluations = await evaluate_tweets_with_fusion_model(
        [tweet.text for tweet in additional_tweets],
        batch_size=16,
    )
    profile_evidence: list[EvaluatedTweet] = []
    for tweet, evaluation in zip(additional_tweets, additional_evaluations):
        seen_tweet_keys.add(tweet.tweet_key)
        profile_evidence.append(
            EvaluatedTweet(
                tweet=tweet,
                evaluation=evaluation,
                phase="profile_deep_dive",
            )
        )

    score = calculate_classification_score(
        [evidence.evaluation for evidence in profile_evidence],
        positive_ratio_threshold=positive_ratio_threshold,
        min_positive_tweets=min_positive_tweets,
        min_evaluated_tweets=min_profile_evaluated_tweets,
        taklidi_ratio_threshold=taklidi_ratio_threshold,
        taklidi_ratio_margin=taklidi_ratio_margin,
    )
    status = score["status"]

    if status == "salafi_jihadi":
        logger.warning(
            "@%s officially classified as a Salafi jihadi user: %s/%s evaluated "
            "tweets were classified as Salafi jihadi.",
            username,
            score["positive_count"],
            score["evaluated_count"],
        )
    elif status == "salafi_taklidi":
        logger.info(
            "@%s classified as a Salafi taklidi user: %s/%s taklidi tweets "
            "vs %s/%s jihadi tweets.",
            username,
            score["taklidi_count"],
            score["evaluated_count"],
            score["positive_count"],
            score["evaluated_count"],
        )
    else:
        logger.info(
            "@%s deep dive complete: status=%s, %s/%s positive tweets.",
            username,
            status,
            score["positive_count"],
            score["evaluated_count"],
        )

    return UserDeepDiveResult(
        username=username,
        status=status,
        score=score,
        trigger_evidence=trigger_evidence,
        profile_evidence=profile_evidence,
        profile_counts=profile_collection.counts,
    )


def serialize_evidence_for_storage(evidence: EvaluatedTweet) -> dict[str, Any]:
    """Convert an evaluated tweet into the Mongo evidence document shape."""
    return {
        "tweet_key": evidence.tweet.tweet_key,
        "tweet_id": evidence.tweet.tweet_id,
        "tweet_url": evidence.tweet.tweet_url,
        "text": evidence.tweet.text,
        "source": evidence.tweet.source,
        "format_version": evidence.tweet.format_version,
        "is_retweet": evidence.tweet.is_retweet,
        "is_quote": evidence.tweet.is_quote,
        "source_text_kind": evidence.tweet.source_text_kind,
        "model_label": evidence.evaluation.label,
        "flagged": evidence.evaluation.flagged,
        "confidence": evidence.evaluation.confidence,
        "probabilities": evidence.evaluation.probabilities,
    }


def read_keywords_file(path: str | Path = KEYWORDS_FILE) -> list[str]:
    """Read keyword/search terms from a text file, one per line."""
    keywords_path = Path(path)
    if not keywords_path.exists():
        raise FileNotFoundError(f"Keywords file was not found: {keywords_path}")

    keywords: list[str] = []
    seen: set[str] = set()
    with keywords_path.open(encoding="utf-8") as keywords_file:
        for line in keywords_file:
            keyword = line.strip()
            if not keyword or keyword.startswith("#"):
                continue
            key = keyword.casefold()
            if key in seen:
                continue
            seen.add(key)
            keywords.append(keyword)

    if not keywords:
        raise ValueError(f"Keywords file is empty: {keywords_path}")

    return keywords


def write_final_jihadi_users_file(
    usernames: Iterable[str],
    path: str | Path = FINAL_JIHADI_USERS_FILE,
) -> None:
    """Write the final verified positive usernames to a text file."""
    output_path = Path(path)
    usernames_by_key: dict[str, str] = {}
    for username in usernames:
        normalized = normalize_username(username)
        if normalized:
            usernames_by_key.setdefault(normalized.casefold(), normalized)

    unique_usernames = sorted(usernames_by_key.values(), key=str.casefold)
    with output_path.open("w", encoding="utf-8") as output_file:
        for username in unique_usernames:
            output_file.write(f"{username}\n")


async def run_pipeline(
    keywords: Iterable[str],
    *,
    discovery_limit: int = DEFAULT_DISCOVERY_LIMIT,
    deep_dive_tweet_limit: int = DEFAULT_DEEP_DIVE_TWEET_LIMIT,
    user_jihadi_threshold: int = USER_JIHADI_TWEET_THRESHOLD,
    min_profile_evaluated_tweets: int = MIN_PROFILE_EVALUATED_TWEETS,
    positive_ratio_threshold: float = POSITIVE_RATIO_THRESHOLD,
    taklidi_ratio_threshold: float = TAKLIDI_RATIO_THRESHOLD,
    taklidi_ratio_margin: float = TAKLIDI_RATIO_MARGIN,
    profile_overfetch_multiplier: float = PROFILE_OVERFETCH_MULTIPLIER,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
    mongo_store: CrawlerMongoStore | None = None,
) -> dict[str, list[TweetEvaluation]]:
    """Run tweet-first discovery, evaluation, user verification, and persistence."""
    clean_keywords = [keyword.strip() for keyword in keywords if keyword.strip()]
    store = mongo_store or CrawlerMongoStore()
    thresholds = {
        "positive_ratio_threshold": positive_ratio_threshold,
        "min_positive_tweets": user_jihadi_threshold,
        "min_profile_evaluated_tweets": min_profile_evaluated_tweets,
        "taklidi_ratio_threshold": taklidi_ratio_threshold,
        "taklidi_ratio_margin": taklidi_ratio_margin,
    }
    raw_profile_fetch_limit = calculate_overfetch_limit(
        deep_dive_tweet_limit,
        profile_overfetch_multiplier,
    )
    run_id = store.start_run(
        keywords=clean_keywords,
        params={
            "discovery_limit": discovery_limit,
            "profile_tweet_limit": deep_dive_tweet_limit,
            "profile_overfetch_multiplier": profile_overfetch_multiplier,
            "raw_profile_fetch_limit": raw_profile_fetch_limit,
            "positive_ratio_threshold": positive_ratio_threshold,
            "min_positive_tweets": user_jihadi_threshold,
            "min_profile_evaluated_tweets": min_profile_evaluated_tweets,
            "taklidi_ratio_threshold": taklidi_ratio_threshold,
            "taklidi_ratio_margin": taklidi_ratio_margin,
            "tweet_language": tweet_language,
        },
    )
    verified_users: dict[str, list[TweetEvaluation]] = {}
    counts: dict[str, int] = {
        "discovered_tweets": 0,
        "triggered_tweets": 0,
        "triggered_users": 0,
        "deep_dived_users": 0,
        "positive_users": 0,
        "taklidi_users": 0,
        "evidence_tweets": 0,
        "insufficient_profile_tweet_users": 0,
        "filtered_arabic": 0,
        "filtered_empty_text": 0,
        "filtered_short_text": 0,
        "raw_discovery_tweets_seen": 0,
        "model_discovery_tweets_evaluated": 0,
        "raw_profile_tweets_seen": 0,
        "model_profile_tweets_evaluated": 0,
    }
    errors: list[str] = []
    status = "completed"

    try:
        client = build_apify_client()
        discovery_collection = discover_tweet_collection_by_keywords(
            clean_keywords,
            client=client,
            tweet_language=tweet_language,
            max_items=discovery_limit,
        )
        discovered_tweets = discovery_collection.tweets
        add_counts(counts, discovery_collection.counts)

        counts["discovered_tweets"] = len(discovered_tweets)
        if not discovered_tweets:
            logger.warning("No tweets discovered for the provided keywords.")
            return {}

        initial_evaluations = await evaluate_tweets_with_fusion_model(
            [discovered_tweet.text for discovered_tweet in discovered_tweets],
            batch_size=16,
        )
        triggered_by_user: dict[str, list[tuple[DiscoveredTweet, TweetEvaluation]]] = {}

        for discovered_tweet, evaluation in zip(discovered_tweets, initial_evaluations):
            if not is_deep_dive_trigger(evaluation):
                continue

            username = discovered_tweet.username
            triggered_by_user.setdefault(username, []).append(
                (discovered_tweet, evaluation)
            )

        counts["triggered_tweets"] = sum(
            len(triggered_items) for triggered_items in triggered_by_user.values()
        )
        counts["triggered_users"] = len(triggered_by_user)

        if not triggered_by_user:
            logger.info("No discovered tweets triggered a user deep dive.")
            return {}

        for username, triggered_items in triggered_by_user.items():
            triggered_tweets = [tweet for tweet, _evaluation in triggered_items]
            triggered_evaluations = [
                evaluation for _tweet, evaluation in triggered_items
            ]
            deep_dive_result = await verify_user_from_triggered_tweet(
                username,
                triggered_tweets,
                triggered_evaluations,
                client=client,
                deep_dive_tweet_limit=deep_dive_tweet_limit,
                min_positive_tweets=user_jihadi_threshold,
                min_profile_evaluated_tweets=min_profile_evaluated_tweets,
                positive_ratio_threshold=positive_ratio_threshold,
                taklidi_ratio_threshold=taklidi_ratio_threshold,
                taklidi_ratio_margin=taklidi_ratio_margin,
                profile_overfetch_multiplier=profile_overfetch_multiplier,
                tweet_language=tweet_language,
            )
            add_counts(counts, deep_dive_result.profile_counts)
            counts["deep_dived_users"] += 1
            if deep_dive_result.status == "insufficient_data":
                counts["insufficient_profile_tweet_users"] += 1
            save_result = store.save_user_deep_dive(
                run_id=run_id,
                username=username,
                trigger_evidence=[
                    serialize_evidence_for_storage(evidence)
                    for evidence in deep_dive_result.trigger_evidence
                ],
                profile_evidence=[
                    serialize_evidence_for_storage(evidence)
                    for evidence in deep_dive_result.profile_evidence
                ],
                keywords=clean_keywords,
                thresholds=thresholds,
            )
            counts["evidence_tweets"] += int(save_result["evidence_count"])

            if save_result["status"] == "salafi_jihadi":
                counts["positive_users"] += 1
                verified_users[username] = deep_dive_result.all_evaluations
            elif save_result["status"] == "salafi_taklidi":
                counts["taklidi_users"] += 1

        return verified_users
    except Exception as exc:
        status = "failed"
        errors.append(str(exc))
        logger.exception("Crawler pipeline failed for run %s.", run_id)
        raise
    finally:
        store.finish_run(run_id, counts=counts, errors=errors, status=status)


def main() -> None:
    """CLI entry point for local pipeline execution."""
    parser = argparse.ArgumentParser(description="Run the Twitter/X crawler pipeline.")
    parser.add_argument(
        "keywords",
        nargs="*",
        help="Optional keyword(s) to search. Defaults to --keywords-file.",
    )
    parser.add_argument(
        "--keywords-file",
        default=str(KEYWORDS_FILE),
        help="Text file containing search keywords, one per line.",
    )
    parser.add_argument(
        "--output-file",
        default=str(FINAL_JIHADI_USERS_FILE),
        help="Text file to write final Salafi jihadi usernames to.",
    )
    parser.add_argument(
        "--discovery-limit",
        type=int,
        default=DEFAULT_DISCOVERY_LIMIT,
        help="Number of initial keyword-discovery tweets/users to evaluate.",
    )
    parser.add_argument(
        "--profile-limit",
        type=int,
        default=DEFAULT_DEEP_DIVE_TWEET_LIMIT,
        help="Clean profile tweet target for each triggered user's deep dive.",
    )
    parser.add_argument(
        "--overfetch-multiplier",
        type=float,
        default=PROFILE_OVERFETCH_MULTIPLIER,
        help="Raw profile fetch multiplier. Default 1.5, so profile-limit 150 fetches 225 raw tweets.",
    )
    parser.add_argument(
        "--min-profile-tweets",
        type=int,
        default=MIN_PROFILE_EVALUATED_TWEETS,
        help="Minimum clean profile tweets that must enter the model.",
    )
    parser.add_argument(
        "--min-positive-tweets",
        type=int,
        default=USER_JIHADI_TWEET_THRESHOLD,
        help="Salafi jihadi profile tweet threshold. The count must be greater than this value.",
    )
    parser.add_argument(
        "--ratio",
        type=float,
        default=POSITIVE_RATIO_THRESHOLD,
        help="Salafi jihadi ratio threshold. The ratio must be greater than this value. Default 0.10.",
    )
    parser.add_argument(
        "--taklidi-ratio",
        type=float,
        default=TAKLIDI_RATIO_THRESHOLD,
        help="Minimum Salafi taklidi profile ratio required. Default 0.25.",
    )
    parser.add_argument(
        "--taklidi-margin",
        type=float,
        default=TAKLIDI_RATIO_MARGIN,
        help="Minimum taklidi ratio lead over jihadi ratio. Default 0.07.",
    )
    parser.add_argument(
        "--tweet-language",
        default=DEFAULT_TWEET_LANGUAGE,
        help="Tweet language sent to Apify. Use an empty value to disable.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )

    keywords = args.keywords or read_keywords_file(args.keywords_file)
    verified_users = asyncio.run(
        run_pipeline(
            keywords,
            discovery_limit=args.discovery_limit,
            deep_dive_tweet_limit=args.profile_limit,
            user_jihadi_threshold=args.min_positive_tweets,
            min_profile_evaluated_tweets=args.min_profile_tweets,
            positive_ratio_threshold=args.ratio,
            taklidi_ratio_threshold=args.taklidi_ratio,
            taklidi_ratio_margin=args.taklidi_margin,
            profile_overfetch_multiplier=args.overfetch_multiplier,
            tweet_language=args.tweet_language or None,
        )
    )
    write_final_jihadi_users_file(verified_users.keys(), args.output_file)
    if verified_users:
        print("Positive users:", ", ".join(sorted(verified_users)))
    else:
        print("No positive users found.")
    print(f"Final positive user list written to: {args.output_file}")


if __name__ == "__main__":
    main()
