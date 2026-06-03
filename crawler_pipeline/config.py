"""Central crawler configuration defaults.

Edit this file when changing crawler runtime defaults. CLI flags can still
override these values for a single run.
"""

from __future__ import annotations

from pathlib import Path


APIFY_ACTOR_ID = "apidojo/tweet-scraper"
KEYWORDS_FILE = Path(__file__).resolve().parent / "keywords.txt"
FINAL_JIHADI_USERS_FILE = Path(__file__).resolve().parent / "final_jihadi_users.txt"
MODEL_EXPORT_DIR = Path(__file__).resolve().parent / "model_export_exp_88_iter_181"
MODEL_DIR = MODEL_EXPORT_DIR / "model"

DEFAULT_TWEET_LANGUAGE = "en"
DEFAULT_DISCOVERY_LIMIT = 100
DEFAULT_USER_TWEET_LIMIT = 10

DEFAULT_POSITIVE_RATIO_THRESHOLD = 0.08
DEFAULT_MIN_POSITIVE_TWEETS = 9
DEFAULT_MIN_PROFILE_EVALUATED_TWEETS = 100
DEFAULT_DEEP_DIVE_TWEET_LIMIT = 150
DEFAULT_PROFILE_OVERFETCH_MULTIPLIER = 1

JIHADI_LABEL_TOKEN = "jihadi"
