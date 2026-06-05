"""MongoDB persistence for the Twitter/X crawler pipeline.

The crawler uses its own collections so it does not mix operational crawl data
with the manual labeling site's existing ``tweets`` and ``users`` collections.
"""

from __future__ import annotations

import hashlib
import math
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from pymongo import ASCENDING, DESCENDING, MongoClient

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

try:
    from .config import (
        DEFAULT_MIN_PROFILE_EVALUATED_TWEETS,
        DEFAULT_MIN_POSITIVE_TWEETS,
        DEFAULT_POSITIVE_RATIO_THRESHOLD,
        DEFAULT_TAKLIDI_RATIO_MARGIN,
        DEFAULT_TAKLIDI_RATIO_THRESHOLD,
        TAKLIDI_LABEL,
    )
except ImportError:  # Allows running this file directly from crawler_pipeline/.
    from config import (
        DEFAULT_MIN_PROFILE_EVALUATED_TWEETS,
        DEFAULT_MIN_POSITIVE_TWEETS,
        DEFAULT_POSITIVE_RATIO_THRESHOLD,
        DEFAULT_TAKLIDI_RATIO_MARGIN,
        DEFAULT_TAKLIDI_RATIO_THRESHOLD,
        TAKLIDI_LABEL,
    )

STATUS_SALAFI_JIHADI = "salafi_jihadi"
STATUS_SALAFI_TAKLIDI = "salafi_taklidi"
STATUS_NOT_SALAFI_JIHADI = "not_salafi_jihadi"
STATUS_INSUFFICIENT_DATA = "insufficient_data"

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "tweetlabeler")

RUNS_COLLECTION = "crawler_runs"
USERS_COLLECTION = "crawler_users"
USER_RUNS_COLLECTION = "crawler_user_runs"
EVIDENCE_COLLECTION = "crawler_tweet_evidence"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_username(username: str) -> str:
    return username.strip().lstrip("@")


def make_username_key(username: str) -> str:
    return normalize_username(username).casefold()


def make_run_id(now: datetime | None = None) -> str:
    timestamp = (now or utc_now()).strftime("%Y%m%d_%H%M%S")
    return f"crawler_{timestamp}_{uuid.uuid4().hex[:8]}"


def make_tweet_key(
    username: str,
    text: str,
    *,
    tweet_id: str | int | None = None,
) -> str:
    if tweet_id is not None and str(tweet_id).strip():
        clean_tweet_id = str(tweet_id).strip()
        return clean_tweet_id if clean_tweet_id.startswith("x:") else f"x:{clean_tweet_id}"

    digest_source = f"{make_username_key(username)}|{text.strip()}".encode("utf-8")
    return f"hash:{hashlib.sha256(digest_source).hexdigest()}"


def _get_flagged(evaluation: Mapping[str, Any] | Any) -> bool:
    if isinstance(evaluation, Mapping):
        return bool(evaluation.get("flagged"))
    return bool(getattr(evaluation, "flagged", False))


def _get_model_label(evaluation: Mapping[str, Any] | Any) -> str:
    if isinstance(evaluation, Mapping):
        return str(evaluation.get("model_label") or evaluation.get("label") or "")
    return str(getattr(evaluation, "label", ""))


def _get_source(evaluation: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(evaluation, Mapping):
        source = evaluation.get("source")
        return source if isinstance(source, Mapping) else {}
    source = getattr(evaluation, "source", {})
    return source if isinstance(source, Mapping) else {}


def _get_count_value(source: Mapping[str, Any], key: str) -> int:
    value = source.get(key)
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        clean_value = value.strip().replace(",", "")
        if clean_value.isdigit():
            return int(clean_value)
    return 0


def _log_score(value: Any, *, full_score_at: int) -> float:
    if isinstance(value, bool) or value is None:
        return 0.0
    if not isinstance(value, (int, float)):
        return 0.0
    numeric_value = max(0.0, float(value))
    if numeric_value <= 0:
        return 0.0
    return min(100.0, (math.log10(numeric_value + 1) / math.log10(full_score_at + 1)) * 100)


def calculate_influence_score(influence: Mapping[str, Any]) -> int:
    followers_score = _log_score(influence.get("followers_count"), full_score_at=1_000_000)
    views_score = _log_score(influence.get("views_count"), full_score_at=1_000_000)
    engagement_score = _log_score(influence.get("engagement_count"), full_score_at=100_000)
    verified_bonus = 5 if influence.get("verified") else 0
    score = (
        followers_score * 0.35
        + views_score * 0.35
        + engagement_score * 0.25
        + verified_bonus
    )
    return int(round(min(100, score)))


def aggregate_user_influence(evaluations: Iterable[Mapping[str, Any] | Any]) -> dict[str, Any]:
    evaluations_list = list(evaluations)
    engagement_source_count = len(evaluations_list)
    influence: dict[str, Any] = {
        "location": "",
        "description": "",
        "followers_count": None,
        "following_count": None,
        "tweet_count": None,
        "verified": False,
        "views_count": 0,
        "likes_count": 0,
        "replies_count": 0,
        "retweets_count": 0,
        "quotes_count": 0,
        "bookmarks_count": 0,
        "shares_count": 0,
        "engagement_count": 0,
        "influence_score": 0,
        "engagement_source_count": engagement_source_count,
    }

    for evaluation in evaluations_list:
        source = _get_source(evaluation)
        author = source.get("author")
        author = author if isinstance(author, Mapping) else {}

        if not influence["location"] and author.get("location"):
            influence["location"] = str(author.get("location")).strip()
        if not influence["description"] and author.get("description"):
            influence["description"] = str(author.get("description")).strip()

        for key in ("followers_count", "following_count", "tweet_count"):
            value = author.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                current = influence[key]
                influence[key] = int(value) if current is None else max(current, int(value))

        influence["verified"] = bool(influence["verified"] or author.get("verified"))
        influence["views_count"] += _get_count_value(source, "view_count")
        influence["likes_count"] += _get_count_value(source, "like_count")
        influence["replies_count"] += _get_count_value(source, "reply_count")
        influence["retweets_count"] += _get_count_value(source, "retweet_count")
        influence["quotes_count"] += _get_count_value(source, "quote_count")
        influence["bookmarks_count"] += _get_count_value(source, "bookmark_count")

    influence["shares_count"] = influence["retweets_count"] + influence["quotes_count"]
    influence["engagement_count"] = (
        influence["likes_count"]
        + influence["replies_count"]
        + influence["retweets_count"]
        + influence["quotes_count"]
    )
    influence["influence_score"] = calculate_influence_score(influence)
    return influence


def classify_user_score(
    positive_count: int,
    evaluated_count: int,
    *,
    taklidi_count: int = 0,
    positive_ratio_threshold: float = DEFAULT_POSITIVE_RATIO_THRESHOLD,
    min_positive_tweets: int = DEFAULT_MIN_POSITIVE_TWEETS,
    min_evaluated_tweets: int = DEFAULT_MIN_PROFILE_EVALUATED_TWEETS,
    taklidi_ratio_threshold: float = DEFAULT_TAKLIDI_RATIO_THRESHOLD,
    taklidi_ratio_margin: float = DEFAULT_TAKLIDI_RATIO_MARGIN,
) -> str:
    if evaluated_count < min_evaluated_tweets:
        return STATUS_INSUFFICIENT_DATA

    positive_ratio = positive_count / evaluated_count if evaluated_count else 0.0
    taklidi_ratio = taklidi_count / evaluated_count if evaluated_count else 0.0
    if (
        taklidi_ratio > taklidi_ratio_threshold
        and taklidi_ratio >= positive_ratio + taklidi_ratio_margin
    ):
        return STATUS_SALAFI_TAKLIDI

    if (
        positive_count > min_positive_tweets
        and positive_ratio > positive_ratio_threshold
    ):
        return STATUS_SALAFI_JIHADI

    return STATUS_NOT_SALAFI_JIHADI


def calculate_classification_score(
    evaluations: Iterable[Mapping[str, Any] | Any],
    *,
    positive_ratio_threshold: float = DEFAULT_POSITIVE_RATIO_THRESHOLD,
    min_positive_tweets: int = DEFAULT_MIN_POSITIVE_TWEETS,
    min_evaluated_tweets: int = DEFAULT_MIN_PROFILE_EVALUATED_TWEETS,
    taklidi_ratio_threshold: float = DEFAULT_TAKLIDI_RATIO_THRESHOLD,
    taklidi_ratio_margin: float = DEFAULT_TAKLIDI_RATIO_MARGIN,
) -> dict[str, Any]:
    evaluations_list = list(evaluations)
    evaluated_count = len(evaluations_list)
    positive_count = sum(1 for evaluation in evaluations_list if _get_flagged(evaluation))
    taklidi_count = sum(
        1 for evaluation in evaluations_list if _get_model_label(evaluation) == TAKLIDI_LABEL
    )
    positive_ratio = positive_count / evaluated_count if evaluated_count else 0.0
    taklidi_ratio = taklidi_count / evaluated_count if evaluated_count else 0.0
    status = classify_user_score(
        positive_count,
        evaluated_count,
        taklidi_count=taklidi_count,
        positive_ratio_threshold=positive_ratio_threshold,
        min_positive_tweets=min_positive_tweets,
        min_evaluated_tweets=min_evaluated_tweets,
        taklidi_ratio_threshold=taklidi_ratio_threshold,
        taklidi_ratio_margin=taklidi_ratio_margin,
    )

    return {
        "positive_count": positive_count,
        "taklidi_count": taklidi_count,
        "evaluated_count": evaluated_count,
        "positive_ratio": positive_ratio,
        "taklidi_ratio": taklidi_ratio,
        "status": status,
    }


class CrawlerMongoStore:
    """Persistence adapter for crawler runs, users, user runs, and evidence."""

    def __init__(
        self,
        *,
        mongo_uri: str | None = None,
        db_name: str | None = None,
        db: Any | None = None,
    ) -> None:
        self.client = None
        if db is None:
            resolved_mongo_uri = mongo_uri or MONGO_URI
            if not resolved_mongo_uri:
                raise ValueError("MONGO_URI is missing for crawler Mongo storage.")
            self.client = MongoClient(resolved_mongo_uri, serverSelectionTimeoutMS=5000)
            db = self.client[db_name or MONGO_DB_NAME]

        self.db = db
        self.runs = db[RUNS_COLLECTION]
        self.users = db[USERS_COLLECTION]
        self.user_runs = db[USER_RUNS_COLLECTION]
        self.evidence = db[EVIDENCE_COLLECTION]

    def ensure_indexes(self) -> None:
        self.runs.create_index("run_id", unique=True)
        self.runs.create_index([("started_at", DESCENDING)])

        self.users.create_index("username_key", unique=True)
        self.users.create_index("current_status")
        self.users.create_index([("last_seen_at", DESCENDING)])

        self.user_runs.create_index(
            [("run_id", ASCENDING), ("username_key", ASCENDING)],
            unique=True,
        )
        self.user_runs.create_index("username_key")

        self.evidence.create_index(
            [
                ("run_id", ASCENDING),
                ("username_key", ASCENDING),
                ("tweet_key", ASCENDING),
                ("phase", ASCENDING),
            ],
            unique=True,
        )
        self.evidence.create_index("username_key")

    def start_run(
        self,
        *,
        keywords: Iterable[str],
        params: Mapping[str, Any],
        run_id: str | None = None,
    ) -> str:
        self.ensure_indexes()
        now = utc_now()
        clean_run_id = run_id or make_run_id(now)
        self.runs.update_one(
            {"run_id": clean_run_id},
            {
                "$setOnInsert": {
                    "run_id": clean_run_id,
                    "status": "running",
                    "started_at": now,
                    "finished_at": None,
                    "keywords": list(keywords),
                    "params": dict(params),
                    "counts": {},
                    "errors": [],
                }
            },
            upsert=True,
        )
        return clean_run_id

    def finish_run(
        self,
        run_id: str,
        *,
        counts: Mapping[str, Any],
        errors: Iterable[str] | None = None,
        status: str = "completed",
    ) -> None:
        self.runs.update_one(
            {"run_id": run_id},
            {
                "$set": {
                    "status": status,
                    "finished_at": utc_now(),
                    "counts": dict(counts),
                    "errors": list(errors or []),
                }
            },
            upsert=True,
        )

    def save_user_deep_dive(
        self,
        *,
        run_id: str,
        username: str,
        trigger_evidence: Iterable[Mapping[str, Any]],
        profile_evidence: Iterable[Mapping[str, Any]],
        keywords: Iterable[str],
        thresholds: Mapping[str, Any],
    ) -> dict[str, Any]:
        now = utc_now()
        clean_username = normalize_username(username)
        username_key = make_username_key(clean_username)
        trigger_docs = [
            self._normalize_evidence_doc(
                run_id,
                username_key,
                clean_username,
                evidence_doc,
                "keyword_trigger",
                now,
            )
            for evidence_doc in trigger_evidence
        ]
        profile_docs = [
            self._normalize_evidence_doc(
                run_id,
                username_key,
                clean_username,
                evidence_doc,
                "profile_deep_dive",
                now,
            )
            for evidence_doc in profile_evidence
        ]
        all_evidence = [*trigger_docs, *profile_docs]
        score = calculate_classification_score(
            profile_docs,
            positive_ratio_threshold=float(
                thresholds.get(
                    "positive_ratio_threshold",
                    DEFAULT_POSITIVE_RATIO_THRESHOLD,
                )
            ),
            min_positive_tweets=int(
                thresholds.get("min_positive_tweets", DEFAULT_MIN_POSITIVE_TWEETS)
            ),
            min_evaluated_tweets=int(
                thresholds.get(
                    "min_profile_evaluated_tweets",
                    DEFAULT_MIN_PROFILE_EVALUATED_TWEETS,
                )
            ),
            taklidi_ratio_threshold=float(
                thresholds.get(
                    "taklidi_ratio_threshold",
                    DEFAULT_TAKLIDI_RATIO_THRESHOLD,
                )
            ),
            taklidi_ratio_margin=float(
                thresholds.get(
                    "taklidi_ratio_margin",
                    DEFAULT_TAKLIDI_RATIO_MARGIN,
                )
            ),
        )
        status = score["status"]
        influence = aggregate_user_influence(profile_docs or all_evidence)

        for evidence_doc in all_evidence:
            self.evidence.update_one(
                {
                    "run_id": run_id,
                    "username_key": username_key,
                    "tweet_key": evidence_doc["tweet_key"],
                    "phase": evidence_doc["phase"],
                },
                {
                    "$set": evidence_doc,
                    "$unset": {"raw_apify_item": ""},
                },
                upsert=True,
            )

        trigger_tweet_keys = [doc["tweet_key"] for doc in trigger_docs]
        evidence_tweet_keys = [doc["tweet_key"] for doc in all_evidence]
        user_run_doc = {
            "run_id": run_id,
            "username_key": username_key,
            "username": clean_username,
            "status": status,
            "score": {
                "positive_count": score["positive_count"],
                "taklidi_count": score["taklidi_count"],
                "evaluated_count": score["evaluated_count"],
                "positive_ratio": score["positive_ratio"],
                "taklidi_ratio": score["taklidi_ratio"],
                "profile_positive_count": score["positive_count"],
                "profile_taklidi_count": score["taklidi_count"],
                "profile_evaluated_count": score["evaluated_count"],
            },
            "influence": influence,
            "thresholds": dict(thresholds),
            "trigger_tweet_keys": trigger_tweet_keys,
            "evidence_tweet_keys": evidence_tweet_keys,
            "created_at": now,
        }
        self.user_runs.update_one(
            {"run_id": run_id, "username_key": username_key},
            {"$set": user_run_doc},
            upsert=True,
        )

        self.users.update_one(
            {"username_key": username_key},
            {
                "$setOnInsert": {
                    "username_key": username_key,
                    "first_seen_at": now,
                },
                "$set": {
                    "username": clean_username,
                    "current_status": status,
                    "latest_run_id": run_id,
                    "latest_score": user_run_doc["score"],
                    "latest_influence": influence,
                    "latest_thresholds": dict(thresholds),
                    "last_seen_at": now,
                },
                "$addToSet": {
                    "discovered_by_keywords": {"$each": list(keywords)},
                },
            },
            upsert=True,
        )

        return {
            "status": status,
            "score": user_run_doc["score"],
            "evidence_count": len(all_evidence),
        }

    @staticmethod
    def _normalize_evidence_doc(
        run_id: str,
        username_key: str,
        username: str,
        evidence_doc: Mapping[str, Any],
        phase: str,
        collected_at: datetime,
    ) -> dict[str, Any]:
        text = str(evidence_doc.get("text", "")).strip()
        tweet_id = evidence_doc.get("tweet_id")
        tweet_key = evidence_doc.get("tweet_key") or make_tweet_key(
            username,
            text,
            tweet_id=tweet_id,
        )
        return {
            "run_id": run_id,
            "username_key": username_key,
            "username": username,
            "phase": phase,
            "tweet_key": tweet_key,
            "tweet_id": tweet_id,
            "tweet_url": evidence_doc.get("tweet_url"),
            "text": text,
            "model_label": evidence_doc.get("model_label"),
            "flagged": bool(evidence_doc.get("flagged")),
            "confidence": evidence_doc.get("confidence"),
            "probabilities": dict(evidence_doc.get("probabilities") or {}),
            "source": dict(evidence_doc.get("source") or {}),
            "format_version": evidence_doc.get("format_version"),
            "is_retweet": bool(evidence_doc.get("is_retweet")),
            "is_quote": bool(evidence_doc.get("is_quote")),
            "source_text_kind": evidence_doc.get("source_text_kind"),
            "collected_at": collected_at,
        }
