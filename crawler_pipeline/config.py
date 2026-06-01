"""Central crawler configuration defaults.

Edit this file when changing crawler runtime defaults. CLI flags can still
override these values for a single run.
"""

from __future__ import annotations

from pathlib import Path


APIFY_ACTOR_ID = "apidojo/tweet-scraper"
MODEL_EXPORT_DIR = Path(__file__).resolve().parent / "model_export_exp_76_iter_153"
MODEL_DIR = MODEL_EXPORT_DIR / "model"

DEFAULT_TWEET_LANGUAGE = "en"
DEFAULT_DISCOVERY_LIMIT = 100
DEFAULT_USER_TWEET_LIMIT = 10

DEFAULT_POSITIVE_RATIO_THRESHOLD = 0.12
DEFAULT_MIN_POSITIVE_TWEETS = 8
DEFAULT_MIN_PROFILE_EVALUATED_TWEETS = 100
DEFAULT_DEEP_DIVE_TWEET_LIMIT = DEFAULT_MIN_PROFILE_EVALUATED_TWEETS
DEFAULT_PROFILE_OVERFETCH_MULTIPLIER = 1.5

JIHADI_LABEL_TOKEN = "jihadi"
