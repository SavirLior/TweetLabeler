"""Two-phase Twitter/X extraction pipeline backed by Apify.

This module provides infrastructure for:
1. Discovering relevant Twitter/X users from keyword searches.
2. Fetching recent tweets from discovered users.
3. Passing tweet text to a placeholder Fusion model evaluator.

Set APIFY_API_TOKEN in your environment before running against Apify.
"""

from __future__ import annotations

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from typing import Any, Iterable

from apify_client import ApifyClient


APIFY_API_TOKEN = os.getenv("APIFY_API_TOKEN", "YOUR_APIFY_API_TOKEN")
APIFY_ACTOR_ID = "apidojo/tweet-scraper"
DEFAULT_TWEET_LANGUAGE = "en"
DEFAULT_DISCOVERY_LIMIT = 10
DEFAULT_USER_TWEET_LIMIT = 10
DEFAULT_FLAG_THRESHOLD = 2

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TweetEvaluation:
    """Represents a single tweet classification result from the model layer."""

    tweet: str
    label: str
    flagged: bool
    confidence: float


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
    """Mock evaluator for the future AWS-hosted Fusion LLM integration.

    This function is the integration boundary for the production Fusion model.
    In the final implementation, it should make authenticated HTTP/REST requests
    to the Fusion LLM service currently hosted on AWS, send batches of tweet text,
    handle request timeouts/retries, validate the response schema, and translate
    model output into a stable internal classification format.

    For now, this mock randomly marks a small subset of tweets as "jihadi" or
    "salafi jihadi" so the rest of the pipeline can be exercised without calling
    the AWS service.
    """
    await asyncio.sleep(0)

    evaluations: list[TweetEvaluation] = []
    for tweet in tweets_list:
        roll = random.random()
        if roll < 0.08:
            label = "salafi jihadi"
            flagged = True
            confidence = random.uniform(0.80, 0.98)
        else:
            label = "not flagged"
            flagged = False
            confidence = random.uniform(0.55, 0.95)

        evaluations.append(
            TweetEvaluation(
                tweet=tweet,
                label=label,
                flagged=flagged,
                confidence=round(confidence, 3),
            )
        )

    return evaluations


async def run_pipeline(
    keywords: Iterable[str],
    *,
    tweets_per_user: int = DEFAULT_USER_TWEET_LIMIT,
    discovery_limit: int = DEFAULT_DISCOVERY_LIMIT,
    flag_threshold: int = DEFAULT_FLAG_THRESHOLD,
    tweet_language: str | None = DEFAULT_TWEET_LANGUAGE,
) -> dict[str, list[TweetEvaluation]]:
    """Run the full two-phase extraction and mock evaluation pipeline."""
    
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

        evaluations = await evaluate_tweets_with_fusion_model(tweets)
        flagged_count = sum(evaluation.flagged for evaluation in evaluations)
        results[username] = evaluations

        if flagged_count > flag_threshold:
            print(
                f"WARNING: @{username} flagged. "
                f"{flagged_count}/{len(evaluations)} tweets exceeded the threshold "
                f"of {flag_threshold}."
            )
        else:
            logger.info(
                "@%s not flagged: %s/%s flagged tweets.",
                username,
                flagged_count,
                len(evaluations),
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
            flag_threshold=DEFAULT_FLAG_THRESHOLD,
        )
    )


if __name__ == "__main__":
    main()
