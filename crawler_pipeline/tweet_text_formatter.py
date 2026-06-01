"""Tweet text formatting compatible with the legacy Apify scraper output."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


FORMAT_VERSION = "scrape_with_api_v1"
MIN_MODEL_TEXT_LENGTH = 4

FILTER_ARABIC = "arabic"
FILTER_EMPTY_TEXT = "empty_text"
FILTER_SHORT_TEXT = "short_text"


@dataclass(frozen=True)
class FormattedTweetText:
    text: str
    format_version: str
    is_retweet: bool
    is_quote: bool
    source_text_kind: str


@dataclass(frozen=True)
class TweetFormatResult:
    formatted: FormattedTweetText | None
    filter_reason: str | None = None


def clean_text(text: str) -> str:
    if not isinstance(text, str):
        return ""

    text = re.sub(r"http\S+", "", text).strip()
    text = re.sub(r"\[Retweeted\]", "", text, flags=re.IGNORECASE)
    text = text.encode("ascii", "ignore").decode("ascii")
    return text.strip()


def get_best_text(tweet_obj: dict[str, Any]) -> str:
    if not isinstance(tweet_obj, dict):
        return ""

    candidates = [
        tweet_obj.get("fullText"),
        tweet_obj.get("text"),
        tweet_obj.get("full_text"),
    ]

    extended_tweet = tweet_obj.get("extended_tweet")
    if isinstance(extended_tweet, dict):
        candidates.append(extended_tweet.get("full_text"))

    legacy = tweet_obj.get("legacy")
    if isinstance(legacy, dict):
        candidates.append(legacy.get("full_text"))
        candidates.append(legacy.get("text"))

    valid_texts = [text for text in candidates if text and isinstance(text, str)]
    if not valid_texts:
        return ""

    return max(valid_texts, key=len)


def get_retweet_object(tweet_item: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("retweet", "retweetedStatus", "retweeted_status", "retweetedTweet"):
        value = tweet_item.get(key)
        if isinstance(value, dict):
            return value
    return None


def get_quote_object(tweet_item: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("quote", "quoted_status", "quotedTweet"):
        value = tweet_item.get(key)
        if isinstance(value, dict):
            return value
    return None


def format_tweet_text(tweet_item: dict[str, Any]) -> TweetFormatResult:
    if not isinstance(tweet_item, dict):
        return TweetFormatResult(formatted=None, filter_reason=FILTER_EMPTY_TEXT)

    if tweet_item.get("lang") == "ar":
        return TweetFormatResult(formatted=None, filter_reason=FILTER_ARABIC)

    retweet_obj = get_retweet_object(tweet_item)
    if retweet_obj and retweet_obj.get("lang") == "ar":
        return TweetFormatResult(formatted=None, filter_reason=FILTER_ARABIC)

    is_retweet = bool(retweet_obj)
    source_obj = retweet_obj if retweet_obj else tweet_item
    final_user_text = get_best_text(source_obj)
    if not final_user_text:
        return TweetFormatResult(formatted=None, filter_reason=FILTER_EMPTY_TEXT)

    combined_text = ""
    is_quote = False
    quote_obj = get_quote_object(tweet_item)
    if quote_obj:
        if quote_obj.get("lang") == "ar":
            return TweetFormatResult(formatted=None, filter_reason=FILTER_ARABIC)

        quote_content = get_best_text(quote_obj)
        if quote_content:
            is_quote = True
            combined_text = (
                f'""{quote_content}"\n"\n'
                f"--------------\n\n"
                f"{final_user_text}"
            )

    if not is_quote:
        if is_retweet:
            combined_text = f'[Retweeted]\n"{final_user_text}"'
        else:
            combined_text = final_user_text

    cleaned = clean_text(combined_text)
    if not cleaned:
        return TweetFormatResult(formatted=None, filter_reason=FILTER_EMPTY_TEXT)
    if len(cleaned) < MIN_MODEL_TEXT_LENGTH:
        return TweetFormatResult(formatted=None, filter_reason=FILTER_SHORT_TEXT)

    if is_quote:
        source_text_kind = "quote"
    elif is_retweet:
        source_text_kind = "retweet"
    else:
        source_text_kind = "tweet"

    return TweetFormatResult(
        formatted=FormattedTweetText(
            text=cleaned,
            format_version=FORMAT_VERSION,
            is_retweet=is_retweet,
            is_quote=is_quote,
            source_text_kind=source_text_kind,
        )
    )
