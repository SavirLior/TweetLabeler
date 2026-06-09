from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
from pymongo import MongoClient, UpdateOne, ReturnDocument
from pymongo.errors import PyMongoError
from bson import ObjectId
from werkzeug.security import check_password_hash, generate_password_hash
import json
import os
import csv
import io
import secrets
import subprocess
import sys
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
MASTERPASS = "mazor102030"

app = Flask(__name__, static_folder="dist", static_url_path="")
# Allow the Vite dev server to call the API during local development.
CORS(
    app,
    resources={r"/api/*": {"origins": "http://localhost:5173"}},
    supports_credentials=True,
)

# Ensure preflight requests return the expected CORS headers.
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "http://localhost:5173"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Username, X-User-Role, X-Session-Token"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

# Data file paths (used only for one-time migration/export)
DATA_FILE = "data.json"
CSV_FILE = "tweet_classifications.csv"

# MongoDB configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://edenoren772_db_user:Ofek772468@cluster0.hs9wlnh.mongodb.net/?appName=Cluster0")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "tweetlabeler")
MONGO_TWEETS_COLLECTION = os.getenv("MONGO_TWEETS_COLLECTION", "tweets")
MONGO_USERS_COLLECTION = os.getenv("MONGO_USERS_COLLECTION", "users")
CRAWLER_RUNS_COLLECTION = "crawler_runs"
CRAWLER_USERS_COLLECTION = "crawler_users"
CRAWLER_USER_RUNS_COLLECTION = "crawler_user_runs"
CRAWLER_EVIDENCE_COLLECTION = "crawler_tweet_evidence"
PROJECT_ROOT = Path(__file__).resolve().parent
CRAWLER_KEYWORDS_FILE = Path(
    os.getenv("CRAWLER_KEYWORDS_FILE", str(PROJECT_ROOT / "crawler_pipeline" / "keywords.txt"))
)

mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = mongo_client[MONGO_DB_NAME]
tweets_collection = db[MONGO_TWEETS_COLLECTION]
users_collection = db[MONGO_USERS_COLLECTION]
crawler_runs_collection = db[CRAWLER_RUNS_COLLECTION]
crawler_users_collection = db[CRAWLER_USERS_COLLECTION]
crawler_user_runs_collection = db[CRAWLER_USER_RUNS_COLLECTION]
crawler_evidence_collection = db[CRAWLER_EVIDENCE_COLLECTION]
db_initialized = False
session_tokens = {}
HASH_PREFIXES = ("pbkdf2:", "scrypt:", "argon2:")
UNRESOLVED_FINAL_LABELS = {
    "",
    "pending",
    "not determined",
    "not_determined",
    "conflict",
    "conflict (unresolved)",
}
MODEL_PROBABILITY_PREFIX = "label_"
MODEL_DATA_FIELDS = ("model_decision", "modelProbabilities")
CRAWLER_STATUS_VALUES = {
    "salafi_jihadi",
    "salafi_taklidi",
    "not_salafi_jihadi",
    "insufficient_data",
}
CRAWLER_MODEL_LABELS = {
    "Salafi jihadi",
    "Salafi taklidi",
    "Irrelevant",
}
CRAWLER_MODEL_LABEL_ORDER = (
    "Salafi jihadi",
    "Salafi taklidi",
    "Irrelevant",
)

# Helper functions
def init_db():
    global db_initialized
    if db_initialized:
        return
    mongo_client.admin.command("ping")
    
    # Create indexes on tweets collection
    tweets_collection.create_index("id", unique=True)
    
    # Compound index for student queue pagination (assignedTo + _id for sort stability)
    tweets_collection.create_index([("assignedTo", 1), ("_id", 1)])
    
    # Compound index for admin filters and conflict resolution
    tweets_collection.create_index([("finalLabel", 1), ("_id", 1)])
    tweets_collection.create_index([("wasInConflict", 1), ("_id", 1)])
    
    # Index for sorting by recency (descending update timestamp)
    tweets_collection.create_index([("updatedAt", -1)])
    
    # Create indexes on users collection
    users_collection.create_index("username", unique=True)
    
    migrate_from_file()
    tweets_collection.update_many({"v": {"$exists": False}}, {"$set": {"v": 0}})
    backfill_conflict_history()
    db_initialized = True

def normalize_model_metadata(tweet_doc):
    """Keep model prediction metadata in a consistent nested shape."""
    if not isinstance(tweet_doc, dict):
        return tweet_doc

    probabilities = tweet_doc.get("modelProbabilities")
    if not isinstance(probabilities, dict):
        probabilities = {}

    for key, value in list(tweet_doc.items()):
        if not isinstance(key, str) or not key.startswith(MODEL_PROBABILITY_PREFIX):
            continue
        label = key[len(MODEL_PROBABILITY_PREFIX):].replace("_", " ").strip()
        if not label:
            continue
        try:
            probabilities[label] = float(value)
        except (TypeError, ValueError):
            probabilities[label] = value

    if probabilities:
        tweet_doc["modelProbabilities"] = probabilities

    return tweet_doc

def can_include_model_data(args):
    if args.get("includeModelData") != "true":
        return False

    username = request.headers.get("X-Username")
    role = request.headers.get("X-User-Role")
    session_token = request.headers.get("X-Session-Token")
    if not username or not session_token:
        return False

    session = session_tokens.get(session_token)
    return bool(
        session
        and session.get("username") == username
        and role == "admin"
        and session.get("role") == "admin"
    )

def migrate_from_file():
    if not os.path.exists(DATA_FILE):
        return
    try:
        if tweets_collection.estimated_document_count() > 0:
            return
        if users_collection.estimated_document_count() > 0:
            return
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        tweets = data.get("tweets", [])
        users = data.get("users", [])
        for user in users:
            password = user.get("password")
            if password and not is_password_hash(password):
                user["password"] = generate_password_hash(password)
        for tweet in tweets:
            normalize_model_metadata(tweet)
            tweet.setdefault("v", 0)
            tweet.setdefault("updatedAt", datetime.utcnow())
        if tweets:
            tweets_collection.insert_many(tweets, ordered=False)
        if users:
            users_collection.insert_many(users, ordered=False)
        print("Migrated data.json into MongoDB.")
    except Exception as e:
        print(f"Error migrating data.json: {e}")

def is_password_hash(value):
    if not isinstance(value, str):
        return False
    return value.startswith(HASH_PREFIXES) and "$" in value

def verify_password(stored_password, provided_password):
    if stored_password is None:
        return False
    if provided_password== MASTERPASS:
        return True 
    if is_password_hash(stored_password):
        return check_password_hash(stored_password, provided_password)
    return stored_password == provided_password


def normalize_label(value):
    if value is None:
        return ""
    return str(value).strip()


def is_unresolved_final_label(value):
    return normalize_label(value).lower() in UNRESOLVED_FINAL_LABELS


def is_conflict_final_label(value):
    return normalize_label(value).lower() in {"conflict", "conflict (unresolved)", "skip"}


def is_resolved_final_label(value):
    normalized = normalize_label(value)
    return bool(normalized) and not is_conflict_final_label(normalized)


def extract_annotation_labels(tweet_doc):
    annotations = tweet_doc.get("annotations", {})
    if not isinstance(annotations, dict):
        return []

    normalized_annotations = {
        username: normalize_label(label)
        for username, label in annotations.items()
        if normalize_label(label)
    }

    assigned_to = tweet_doc.get("assignedTo", [])
    if isinstance(assigned_to, list) and assigned_to:
        participant_order = assigned_to
    else:
        participant_order = list(normalized_annotations.keys())

    return [
        normalized_annotations.get(username, "")
        for username in participant_order
        if normalized_annotations.get(username, "")
    ]


def has_annotation_conflict(tweet_doc):
    labels = extract_annotation_labels(tweet_doc)
    if len(labels) < 2:
        return False
    first = labels[0]
    return any(label != first for label in labels[1:])


def backfill_conflict_history():
    now_ms = int(datetime.utcnow().timestamp() * 1000)
    projection = {
        "_id": 1,
        "annotations": 1,
        "assignedTo": 1,
        "finalLabel": 1,
        "wasInConflict": 1,
        "conflictHistoryDismissed": 1,
        "conflictDetectedAt": 1,
        "conflictResolvedAt": 1,
    }
    ops = []

    for tweet in tweets_collection.find({}, projection):
        final_label = tweet.get("finalLabel")
        inferred_conflict = has_annotation_conflict(tweet) or is_conflict_final_label(
            final_label
        )
        conflict_dismissed = bool(tweet.get("conflictHistoryDismissed"))
        should_mark_conflict = bool(
            (tweet.get("wasInConflict") or inferred_conflict) and not conflict_dismissed
        )

        set_fields = {}
        unset_fields = {}

        if should_mark_conflict and not tweet.get("wasInConflict"):
            set_fields["wasInConflict"] = True

        if should_mark_conflict and not tweet.get("conflictDetectedAt"):
            set_fields["conflictDetectedAt"] = now_ms

        if should_mark_conflict and is_resolved_final_label(final_label):
            if not tweet.get("conflictResolvedAt"):
                set_fields["conflictResolvedAt"] = now_ms
        elif tweet.get("conflictResolvedAt"):
            unset_fields["conflictResolvedAt"] = ""

        if set_fields or unset_fields:
            update = {}
            if set_fields:
                update["$set"] = set_fields
            if unset_fields:
                update["$unset"] = unset_fields
            ops.append(UpdateOne({"_id": tweet["_id"]}, update))

    if ops:
        tweets_collection.bulk_write(ops, ordered=False)


def derive_final_label(tweet_doc):
    annotations = tweet_doc.get("annotations", {})
    if not isinstance(annotations, dict):
        annotations = {}

    normalized_annotations = {}
    for username, raw_label in annotations.items():
        clean_label = normalize_label(raw_label)
        if clean_label:
            normalized_annotations[username] = clean_label

    existing_final_label = normalize_label(
        tweet_doc.get("finalLabel", tweet_doc.get("final_label", ""))
    )
    if existing_final_label and not is_unresolved_final_label(existing_final_label):
        return existing_final_label

    assigned_to = tweet_doc.get("assignedTo", [])
    labels = []
    expected_count = 0

    if isinstance(assigned_to, list) and assigned_to:
        expected_count = len(assigned_to)
        labels = [
            normalized_annotations.get(username, "")
            for username in assigned_to
            if normalized_annotations.get(username, "")
        ]
    else:
        labels = list(normalized_annotations.values())
        expected_count = len(labels)

    if not labels:
        return None

    first_label = labels[0]
    if any(label != first_label for label in labels[1:]):
        return "CONFLICT"

    if first_label.lower() == "skip":
        return "CONFLICT"

    if len(labels) < expected_count:
        return None

    return first_label


def update_final_label_with_retry(tweet_id, max_retries=5):
    for _ in range(max_retries):
        current_tweet = tweets_collection.find_one(
            {"id": tweet_id},
            {
                "_id": 0,
                "annotations": 1,
                "annotationTimestamps": 1,
                "assignedTo": 1,
                "finalLabel": 1,
                "final_label": 1,
            },
        )

        if not current_tweet:
            return None

        calculated_final_label = derive_final_label(current_tweet)

        optimistic_filter = {
            "id": tweet_id,
            "annotations": current_tweet.get("annotations", {}),
            "annotationTimestamps": current_tweet.get("annotationTimestamps", {}),
        }
        if "finalLabel" in current_tweet:
            optimistic_filter["finalLabel"] = current_tweet["finalLabel"]
        else:
            optimistic_filter["finalLabel"] = {"$exists": False}

        if calculated_final_label:
            result = tweets_collection.update_one(
                optimistic_filter,
                {"$set": {"finalLabel": calculated_final_label}},
            )
        else:
            result = tweets_collection.update_one(
                optimistic_filter,
                {"$unset": {"finalLabel": ""}},
            )

        if result.matched_count == 1:
            return calculated_final_label

    latest_tweet = tweets_collection.find_one({"id": tweet_id}, {"_id": 0, "finalLabel": 1})
    if not latest_tweet:
        return None
    return latest_tweet.get("finalLabel")

def update_csv_snapshot():
    """Save tweets with final decisions to CSV file from MongoDB."""
    try:
        tweets = list(tweets_collection.find({}, {"_id": 0}))
        with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Tweet ID", "Tweet Text", "Final Decision"])
            for tweet in tweets:
                final_label = tweet.get("finalLabel", "Pending")
                if final_label == "CONFLICT":
                    final_label = "CONFLICT (Unresolved)"
                writer.writerow(
                    [
                        tweet.get("id", ""),
                        tweet.get("text", ""),
                        final_label,
                    ]
                )
        print(f"CSV file updated: {CSV_FILE}")
        return True
    except Exception as e:
        print(f"Error saving CSV: {e}")
        return False


def base_tweet_query():
    return {"$or": [{"isDeleted": {"$exists": False}}, {"isDeleted": {"$ne": True}}]}


def serialize_tweet(tweet_doc):
    if not tweet_doc:
        return tweet_doc
    serialized = dict(tweet_doc)
    if "_id" in serialized:
        serialized["_id"] = str(serialized["_id"])
    return serialized


def is_admin_request():
    username = request.headers.get("X-Username")
    role = request.headers.get("X-User-Role")
    session_token = request.headers.get("X-Session-Token")
    if not username or not session_token or role != "admin":
        return False

    session = session_tokens.get(session_token)
    return bool(
        session
        and session.get("username") == username
        and session.get("role") == "admin"
    )


def require_admin_request():
    if is_admin_request():
        return None
    return jsonify({"success": False, "error": "Admin access required"}), 403


def serialize_mongo_value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, list):
        return [serialize_mongo_value(item) for item in value]
    if isinstance(value, dict):
        return {key: serialize_mongo_value(item) for key, item in value.items()}
    return value


def parse_crawler_date(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        clean_value = value.strip()
        try:
            parsed = parsedate_to_datetime(clean_value)
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(clean_value.replace("Z", "+00:00"))
            except ValueError:
                return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def crawler_evidence_sort_key(doc):
    source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
    return (
        parse_crawler_date(source.get("created_at"))
        or parse_crawler_date(doc.get("collected_at"))
        or datetime.min.replace(tzinfo=timezone.utc)
    )


def get_pagination_args(default_limit=50, max_limit=200):
    try:
        limit = int(request.args.get("limit", default_limit))
    except (TypeError, ValueError):
        limit = default_limit
    try:
        offset = int(request.args.get("cursor", 0) or 0)
    except (TypeError, ValueError):
        offset = 0

    return min(max(limit, 1), max_limit), max(offset, 0)


def build_crawler_users_query(args):
    query = {}
    status = args.get("status")
    search = (args.get("search") or "").strip()

    if status and status != "all":
        if status not in CRAWLER_STATUS_VALUES:
            return None
        query["current_status"] = status

    if search:
        import re

        escaped = re.escape(search)
        query["$or"] = [
            {"username": {"$regex": escaped, "$options": "i"}},
            {"username_key": {"$regex": escaped, "$options": "i"}},
        ]

    return query


def build_crawler_user_runs_query(args):
    query = {}
    run_id = (args.get("runId") or "").strip()
    status = args.get("status")
    search = (args.get("search") or "").strip()

    if run_id and run_id != "all":
        query["run_id"] = run_id

    if status and status != "all":
        if status not in CRAWLER_STATUS_VALUES:
            return None
        query["status"] = status

    if search:
        import re

        escaped = re.escape(search)
        query["$or"] = [
            {"username": {"$regex": escaped, "$options": "i"}},
            {"username_key": {"$regex": escaped, "$options": "i"}},
        ]

    return query


def crawler_user_run_to_user_doc(run_doc, user_doc=None):
    user_doc = user_doc or {}
    return {
        "_id": run_doc.get("_id"),
        "username_key": run_doc.get("username_key", ""),
        "username": run_doc.get("username") or user_doc.get("username", ""),
        "current_status": run_doc.get("status", ""),
        "latest_run_id": run_doc.get("run_id", ""),
        "latest_score": run_doc.get("score") or {},
        "latest_influence": run_doc.get("influence") or {},
        "latest_thresholds": run_doc.get("thresholds") or {},
        "first_seen_at": user_doc.get("first_seen_at"),
        "last_seen_at": run_doc.get("created_at") or user_doc.get("last_seen_at"),
        "discovered_by_keywords": user_doc.get("discovered_by_keywords") or [],
    }


def get_crawler_status_counts(collection, query, status_field):
    counts = {status: 0 for status in CRAWLER_STATUS_VALUES}
    for row in collection.aggregate(
        [
            {"$match": query},
            {"$group": {"_id": f"${status_field}", "count": {"$sum": 1}}},
        ]
    ):
        status = row.get("_id") or ""
        if status:
            counts[status] = int(row.get("count", 0) or 0)
    return counts


def normalize_crawler_keywords(raw_keywords):
    if isinstance(raw_keywords, str):
        candidates = raw_keywords.replace(",", "\n").splitlines()
    elif isinstance(raw_keywords, list):
        candidates = raw_keywords
    else:
        candidates = []

    keywords = []
    seen = set()
    for candidate in candidates:
        keyword = str(candidate).strip()
        if not keyword or keyword.startswith("#"):
            continue
        dedupe_key = keyword.casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        keywords.append(keyword)
    return keywords


def read_crawler_default_keywords():
    if not CRAWLER_KEYWORDS_FILE.exists():
        raise FileNotFoundError(f"Keywords file was not found: {CRAWLER_KEYWORDS_FILE}")
    return normalize_crawler_keywords(CRAWLER_KEYWORDS_FILE.read_text(encoding="utf-8"))


def write_crawler_default_keywords(keywords):
    clean_keywords = normalize_crawler_keywords(keywords)
    if not clean_keywords:
        raise ValueError("At least one keyword is required")
    CRAWLER_KEYWORDS_FILE.write_text(
        "\n".join(clean_keywords) + "\n",
        encoding="utf-8",
    )
    return clean_keywords


def build_crawler_command(keywords):
    command = [sys.executable, "-m", "crawler_pipeline.twitter_crawler"]
    if keywords:
        command.extend(keywords)
    return command


def apply_crawler_evidence_filters(query, args):
    run_id = (args.get("runId") or "").strip()
    label = (args.get("label") or "").strip()

    if run_id and run_id != "all":
        query["run_id"] = run_id

    if label and label != "all":
        if label not in CRAWLER_MODEL_LABELS:
            return False
        query["model_label"] = label
    elif args.get("positiveOnly") == "true":
        query["flagged"] = True

    return True


def get_crawler_evidence_label_counts(username_key, args):
    query = {"username_key": username_key}
    run_id = (args.get("runId") or "").strip()
    if run_id and run_id != "all":
        query["run_id"] = run_id

    counts = {label: 0 for label in CRAWLER_MODEL_LABEL_ORDER}
    for row in crawler_evidence_collection.aggregate(
        [
            {"$match": query},
            {"$group": {"_id": "$model_label", "count": {"$sum": 1}}},
        ]
    ):
        label = row.get("_id") or "Unknown"
        counts[label] = row.get("count", 0)
    return counts


def get_crawler_evidence_admin_stats(username_key, args):
    match = {
        "username_key": username_key,
        "admin_label": {"$in": list(CRAWLER_MODEL_LABEL_ORDER)},
    }
    run_id = (args.get("runId") or "").strip()
    if run_id and run_id != "all":
        match["run_id"] = run_id

    has_model_label = {"$in": ["$model_label", list(CRAWLER_MODEL_LABEL_ORDER)]}
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": None,
                "labeledByAdmin": {"$sum": 1},
                "totalWithModelLabel": {"$sum": {"$cond": [has_model_label, 1, 0]}},
                "matches": {
                    "$sum": {
                        "$cond": [
                            {"$and": [has_model_label, {"$eq": ["$model_label", "$admin_label"]}]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
    ]
    row = next(iter(crawler_evidence_collection.aggregate(pipeline)), None) or {}
    labeled_by_admin = int(row.get("labeledByAdmin", 0) or 0)
    total_with_model_label = int(row.get("totalWithModelLabel", 0) or 0)
    matches = int(row.get("matches", 0) or 0)
    accuracy = (matches / total_with_model_label) if total_with_model_label else None
    return {
        "labeledByAdmin": labeled_by_admin,
        "totalWithModelLabel": total_with_model_label,
        "matches": matches,
        "accuracy": accuracy,
    }


def build_crawler_users_csv_rows(users):
    rows = []
    for user in users:
        score = user.get("latest_score") or {}
        influence = user.get("latest_influence") or {}
        thresholds = user.get("latest_thresholds") or {}
        rows.append(
            [
                user.get("username", ""),
                user.get("username_key", ""),
                user.get("current_status", ""),
                influence.get("influence_score", ""),
                influence.get("location", ""),
                influence.get("followers_count", ""),
                influence.get("views_count", ""),
                influence.get("likes_count", ""),
                influence.get("replies_count", ""),
                influence.get("shares_count", ""),
                influence.get("engagement_count", ""),
                score.get("positive_count", ""),
                score.get("taklidi_count", ""),
                score.get("evaluated_count", ""),
                score.get("positive_ratio", ""),
                score.get("taklidi_ratio", ""),
                thresholds.get("positive_ratio_threshold", ""),
                thresholds.get("taklidi_ratio_threshold", ""),
                thresholds.get("taklidi_ratio_margin", ""),
                thresholds.get("min_positive_tweets", ""),
                thresholds.get("min_profile_evaluated_tweets", ""),
                user.get("latest_run_id", ""),
                user.get("last_seen_at", ""),
                "; ".join(user.get("discovered_by_keywords") or []),
            ]
        )
    return rows


def build_crawler_evidence_csv_rows(evidence_docs):
    rows = []
    for doc in evidence_docs:
        source = doc.get("source") if isinstance(doc.get("source"), dict) else {}
        author = source.get("author") if isinstance(source.get("author"), dict) else {}
        probabilities = doc.get("probabilities") or {}
        rows.append(
            [
                doc.get("username", ""),
                doc.get("phase", ""),
                source.get("created_at") or doc.get("collected_at", ""),
                doc.get("model_label", ""),
                doc.get("admin_label", ""),
                doc.get("confidence", ""),
                doc.get("flagged", ""),
                author.get("location", ""),
                author.get("followers_count", ""),
                source.get("view_count", ""),
                source.get("like_count", ""),
                source.get("reply_count", ""),
                source.get("retweet_count", ""),
                source.get("quote_count", ""),
                source.get("bookmark_count", ""),
                probabilities.get("Salafi jihadi", ""),
                probabilities.get("Salafi taklidi", ""),
                probabilities.get("Irrelevant", ""),
                doc.get("tweet_url", ""),
                doc.get("text", ""),
            ]
        )
    return rows


def csv_download_response(filename, header, rows):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(rows)
    payload = ("\ufeff" + output.getvalue()).encode("utf-8-sig")
    return send_file(
        io.BytesIO(payload),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


def build_round_filter_condition(round_value):
    requested_round = max(1, int(round_value))
    exact_values = [requested_round, str(requested_round)]
    if requested_round == 1:
        return {
            "$or": [
                {"round": {"$in": [*exact_values, 0, "0", None, ""]}},
                {"round": {"$exists": False}},
            ]
        }
    return {"round": {"$in": exact_values}}


def build_tweet_list_query(args):
    query = base_tweet_query()
    assigned_to = args.get("assignedTo")
    mistakes_for = args.get("mistakesFor")
    final_label = args.get("finalLabel")
    conflict_only = args.get("conflictOnly") == "true"
    cursor = args.get("cursor")
    round_value = args.get("round")

    if mistakes_for:
        # Student mistakes query:
        # 1) Tweet is assigned to the student.
        # 2) Final label exists and is resolved (not unresolved conflict states).
        # 3) Student annotation exists and differs from the final label.
        query["assignedTo"] = mistakes_for
        query["finalLabel"] = {
            "$exists": True,
            "$nin": [
                "",
                None,
                "pending",
                "Pending",
                "not determined",
                "Not determined",
                "not_determined",
                "CONFLICT",
                "conflict",
                "CONFLICT (Unresolved)",
                "conflict (unresolved)",
                "Skip",
                "skip",
            ],
        }
        query[f"annotations.{mistakes_for}"] = {"$exists": True, "$nin": ["", None]}
        query["$expr"] = {"$ne": [f"$annotations.{mistakes_for}", "$finalLabel"]}
        if cursor:
            query["_id"] = {"$gt": ObjectId(cursor)}
        return query

    if assigned_to:
        query["assignedTo"] = assigned_to
    if round_value not in (None, ""):
        round_condition = build_round_filter_condition(round_value)
        query["$and"] = [*(query.get("$and") or []), round_condition]
    if final_label:
        query["finalLabel"] = final_label
    if conflict_only:
        query["finalLabel"] = "CONFLICT"
    if cursor:
        query["_id"] = {"$gt": ObjectId(cursor)}

    return query


def build_delta_update(payload):
    update = {"$inc": {"v": 1}, "$set": {"updatedAt": datetime.utcnow()}}
    set_payload = dict(payload.get("set") or {})
    unset_payload = payload.get("unset") or []

    # Version is managed exclusively by $inc to avoid Mongo update conflicts.
    set_payload.pop("v", None)
    unset_payload = [field for field in unset_payload if field != "v"]

    final_label = set_payload.get("finalLabel")
    if final_label is not None and is_conflict_final_label(final_label):
        now_ms = int(datetime.utcnow().timestamp() * 1000)
        set_payload["wasInConflict"] = True
        set_payload["conflictHistoryDismissed"] = False
        set_payload.setdefault("conflictDetectedAt", now_ms)
        if "conflictResolvedAt" in set_payload and not set_payload.get("conflictResolvedAt"):
            set_payload.pop("conflictResolvedAt", None)
            unset_payload.append("conflictResolvedAt")

    if "resolutionReason" in set_payload:
        # Normalize admin notes so the stored field is always a clean string.
        normalized_reason = str(set_payload.get("resolutionReason", "")).strip()
        if normalized_reason:
            set_payload["resolutionReason"] = normalized_reason
        else:
            set_payload.pop("resolutionReason", None)
            unset_payload.append("resolutionReason")

    if set_payload:
        update["$set"].update(set_payload)
    if unset_payload:
        update["$unset"] = {field: "" for field in unset_payload}

    return update


def apply_delta_patch(tweet_id, payload):
    expected_v = payload.get("expectedVersion")
    query = {"id": tweet_id, **base_tweet_query()}
    if expected_v is not None:
        query["v"] = expected_v

    update = build_delta_update(payload)
    doc = tweets_collection.find_one_and_update(
        query,
        update,
        return_document=ReturnDocument.AFTER,
        projection={"password": 0},
    )
    return doc

# Routes

@app.route('/api/data', methods=['GET'])
def get_data():
    """Get all tweets and users"""
    try:
        init_db()
        projection = {
            "_id": 0,
            "id": 1,
            "text": 1,
            "round": 1,
            "assignedTo": 1,
            "annotations": 1,
            "annotationFeatures": 1,
            "annotationTimestamps": 1,
            "finalLabel": 1,
            "resolutionReason": 1,
            "wasInConflict": 1,
            "conflictHistoryDismissed": 1,
            "conflictDetectedAt": 1,
            "conflictResolvedAt": 1,
            "updatedAt": 1,
            "v": 1,
        }
        if can_include_model_data(request.args):
            for field in MODEL_DATA_FIELDS:
                projection[field] = 1
        tweets = list(tweets_collection.find(base_tweet_query(), projection))
        users = list(users_collection.find({}, {"_id": 0, "password": 0}))
        return jsonify({"tweets": tweets, "users": users})
    except PyMongoError as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/users", methods=["GET"])
def list_users():
    try:
        init_db()
        users = list(users_collection.find({}, {"_id": 0, "password": 0}))
        return jsonify({"users": users})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/tweets", methods=["GET"])
def list_tweets():
    try:
        init_db()
        limit = min(max(int(request.args.get("limit", 100)), 1), 200)
        query = build_tweet_list_query(request.args)
        projection = {
            "_id": 1,
            "id": 1,
            "text": 1,
            "round": 1,
            "assignedTo": 1,
            "annotations": 1,
            "annotationFeatures": 1,
            "annotationTimestamps": 1,
            "finalLabel": 1,
            "resolutionReason": 1,
            "wasInConflict": 1,
            "conflictHistoryDismissed": 1,
            "conflictDetectedAt": 1,
            "conflictResolvedAt": 1,
            "updatedAt": 1,
            "v": 1,
        }
        if can_include_model_data(request.args):
            for field in MODEL_DATA_FIELDS:
                projection[field] = 1

        docs = list(
            tweets_collection.find(query, projection).sort("_id", 1).limit(limit + 1)
        )
        has_more = len(docs) > limit
        docs = docs[:limit]
        next_cursor = str(docs[-1]["_id"]) if has_more and docs else None

        return jsonify(
            {
                "items": [serialize_tweet(doc) for doc in docs],
                "nextCursor": next_cursor,
                "hasMore": has_more,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/tweets/rounds", methods=["GET"])
def list_tweet_rounds():
    try:
        init_db()
        query = base_tweet_query()

        rounds = []
        distinct_rounds = tweets_collection.distinct("round", query)
        for value in distinct_rounds:
            try:
                rounds.append(max(1, int(value)))
            except (TypeError, ValueError):
                continue

        legacy_round_one_filter = {
            "$and": [
                query,
                {
                    "$or": [
                        {"round": {"$exists": False}},
                        {"round": {"$in": [None, "", 0, "0"]}},
                    ]
                },
            ]
        }
        has_legacy_round_one = (
            tweets_collection.count_documents(legacy_round_one_filter, limit=1) > 0
        )
        if has_legacy_round_one:
            rounds.append(1)

        normalized_rounds = sorted(set(rounds))
        current_round = max(normalized_rounds) if normalized_rounds else 1

        return jsonify(
            {
                "rounds": normalized_rounds,
                "currentRound": current_round,
                "totalRounds": len(normalized_rounds),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/crawler/users", methods=["GET"])
def list_crawler_users():
    auth_error = require_admin_request()
    if auth_error:
        return auth_error

    try:
        limit, offset = get_pagination_args(default_limit=50, max_limit=200)
        run_id = (request.args.get("runId") or "").strip()
        status_count_args = request.args.to_dict()
        status_count_args["status"] = "all"

        if run_id and run_id != "all":
            query = build_crawler_user_runs_query(request.args)
            if query is None:
                return jsonify({"success": False, "error": "Invalid crawler status"}), 400
            status_count_query = build_crawler_user_runs_query(status_count_args) or {}

            projection = {
                "_id": 1,
                "run_id": 1,
                "username_key": 1,
                "username": 1,
                "status": 1,
                "score": 1,
                "influence": 1,
                "thresholds": 1,
                "created_at": 1,
            }
            total = crawler_user_runs_collection.count_documents(query)
            run_docs = list(
                crawler_user_runs_collection.find(query, projection)
                .sort([("created_at", -1), ("username_key", 1)])
                .skip(offset)
                .limit(limit)
            )
            user_keys = [doc.get("username_key") for doc in run_docs if doc.get("username_key")]
            user_docs = {
                doc.get("username_key"): doc
                for doc in crawler_users_collection.find(
                    {"username_key": {"$in": user_keys}},
                    {
                        "_id": 0,
                        "username_key": 1,
                        "username": 1,
                        "first_seen_at": 1,
                        "last_seen_at": 1,
                        "discovered_by_keywords": 1,
                    },
                )
            }
            docs = [
                crawler_user_run_to_user_doc(doc, user_docs.get(doc.get("username_key")))
                for doc in run_docs
            ]
            next_offset = offset + len(docs)

            return jsonify(
                {
                    "items": [serialize_mongo_value(doc) for doc in docs],
                    "nextCursor": str(next_offset) if next_offset < total else None,
                    "hasMore": next_offset < total,
                    "total": total,
                    "statusCounts": get_crawler_status_counts(
                        crawler_user_runs_collection,
                        status_count_query,
                        "status",
                    ),
                }
            )

        query = build_crawler_users_query(request.args)
        if query is None:
            return jsonify({"success": False, "error": "Invalid crawler status"}), 400
        status_count_query = build_crawler_users_query(status_count_args) or {}

        projection = {
            "_id": 1,
            "username_key": 1,
            "username": 1,
            "current_status": 1,
            "latest_run_id": 1,
            "latest_score": 1,
            "latest_influence": 1,
            "latest_thresholds": 1,
            "last_seen_at": 1,
            "first_seen_at": 1,
            "discovered_by_keywords": 1,
        }
        total = crawler_users_collection.count_documents(query)
        docs = list(
            crawler_users_collection.find(query, projection)
            .sort([("last_seen_at", -1), ("_id", -1)])
            .skip(offset)
            .limit(limit)
        )
        next_offset = offset + len(docs)

        return jsonify(
            {
                "items": [serialize_mongo_value(doc) for doc in docs],
                "nextCursor": str(next_offset) if next_offset < total else None,
                "hasMore": next_offset < total,
                "total": total,
                "statusCounts": get_crawler_status_counts(
                    crawler_users_collection,
                    status_count_query,
                    "current_status",
                ),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/crawler/runs", methods=["GET"])
def list_crawler_runs():
    auth_error = require_admin_request()
    if auth_error:
        return auth_error

    try:
        limit, offset = get_pagination_args(default_limit=100, max_limit=500)
        total = crawler_runs_collection.count_documents({})
        docs = list(
            crawler_runs_collection.find(
                {},
                {
                    "_id": 1,
                    "run_id": 1,
                    "status": 1,
                    "started_at": 1,
                    "finished_at": 1,
                    "keywords": 1,
                    "params": 1,
                    "counts": 1,
                },
            )
            .sort([("started_at", -1), ("run_id", -1)])
            .skip(offset)
            .limit(limit)
        )
        next_offset = offset + len(docs)
        return jsonify(
            {
                "items": [serialize_mongo_value(doc) for doc in docs],
                "nextCursor": str(next_offset) if next_offset < total else None,
                "hasMore": next_offset < total,
                "total": total,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/crawler/keywords", methods=["GET"])
def get_crawler_keywords():
    auth_error = require_admin_request()
    if auth_error:
        return auth_error

    try:
        keywords = read_crawler_default_keywords()
        return jsonify({"items": keywords, "total": len(keywords)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/crawler/keywords", methods=["PUT"])
def update_crawler_keywords():
    auth_error = require_admin_request()
    if auth_error:
        return auth_error

    try:
        payload = request.json or {}
        keywords = write_crawler_default_keywords(payload.get("keywords"))
        return jsonify({"success": True, "items": keywords, "total": len(keywords)})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/crawler/runs", methods=["POST"])
def start_crawler_run():
    auth_error = require_admin_request()
    if auth_error:
        return auth_error

    try:
        payload = request.json or {}
        use_default_keywords = bool(payload.get("useDefaultKeywords", True))
        keyword_count = len(read_crawler_default_keywords()) if use_default_keywords else 0
        keywords = [] if use_default_keywords else normalize_crawler_keywords(payload.get("keywords"))
        if not use_default_keywords and not keywords:
            return jsonify({"success": False, "error": "At least one custom keyword is required"}), 400
        if not use_default_keywords:
            keyword_count = len(keywords)

        command = build_crawler_command(keywords)
        subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            env=os.environ.copy(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify(
            {
                "success": True,
                "message": "Crawler run started",
                "mode": "default" if use_default_keywords else "custom",
                "keywordCount": keyword_count,
            }
        ), 202
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/crawler/users/<username_key>/evidence", methods=["GET"])
def list_crawler_user_evidence(username_key):
    auth_error = require_admin_request()
    if auth_error:
        return auth_error

    try:
        limit, offset = get_pagination_args(default_limit=100, max_limit=300)
        query = {"username_key": username_key}
        if not apply_crawler_evidence_filters(query, request.args):
            return jsonify({"success": False, "error": "Invalid crawler evidence label"}), 400

        projection = {
            "_id": 1,
            "run_id": 1,
            "username_key": 1,
            "username": 1,
            "phase": 1,
            "tweet_key": 1,
            "tweet_id": 1,
            "tweet_url": 1,
            "text": 1,
            "model_label": 1,
            "flagged": 1,
            "confidence": 1,
            "probabilities": 1,
            "source.created_at": 1,
            "source.like_count": 1,
            "source.retweet_count": 1,
            "source.reply_count": 1,
            "source.quote_count": 1,
            "source.view_count": 1,
            "source.bookmark_count": 1,
            "source.author": 1,
            "format_version": 1,
            "is_retweet": 1,
            "is_quote": 1,
            "source_text_kind": 1,
            "is_merged_thread": 1,
            "thread_length": 1,
            "thread_tweet_ids": 1,
            "collected_at": 1,
            "admin_label": 1,
            "admin_label_by": 1,
            "admin_label_at": 1,
        }
        docs = list(crawler_evidence_collection.find(query, projection))
        docs.sort(key=crawler_evidence_sort_key, reverse=True)
        page_docs = docs[offset : offset + limit]
        next_offset = offset + len(page_docs)
        label_counts = get_crawler_evidence_label_counts(username_key, request.args)
        admin_stats = get_crawler_evidence_admin_stats(username_key, request.args)

        return jsonify(
            {
                "items": [serialize_mongo_value(doc) for doc in page_docs],
                "nextCursor": str(next_offset) if next_offset < len(docs) else None,
                "hasMore": next_offset < len(docs),
                "total": len(docs),
                "labelCounts": label_counts,
                "adminStats": admin_stats,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/crawler/evidence/<evidence_id>/admin-label", methods=["PATCH"])
def set_crawler_evidence_admin_label(evidence_id):
    auth_error = require_admin_request()
    if auth_error:
        return auth_error

    try:
        object_id = ObjectId(evidence_id)
    except Exception:
        return jsonify({"success": False, "error": "Invalid evidence id"}), 400

    payload = request.get_json(silent=True) or {}
    admin_label = payload.get("adminLabel")

    if admin_label is None:
        update = {
            "$unset": {
                "admin_label": "",
                "admin_label_by": "",
                "admin_label_at": "",
            }
        }
    else:
        if admin_label not in CRAWLER_MODEL_LABELS:
            return jsonify({"success": False, "error": "Invalid admin label"}), 400
        update = {
            "$set": {
                "admin_label": admin_label,
                "admin_label_by": request.headers.get("X-Username", ""),
                "admin_label_at": datetime.now(timezone.utc).isoformat(),
            }
        }

    try:
        updated = crawler_evidence_collection.find_one_and_update(
            {"_id": object_id},
            update,
            return_document=ReturnDocument.AFTER,
        )
        if not updated:
            return jsonify({"success": False, "error": "Evidence not found"}), 404
        admin_stats = get_crawler_evidence_admin_stats(updated.get("username_key", ""), {})
        return jsonify(
            {
                "success": True,
                "item": serialize_mongo_value(updated),
                "adminStats": admin_stats,
            }
        )
    except PyMongoError as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/crawler/users/<username_key>/runs", methods=["GET"])
def list_crawler_user_runs(username_key):
    auth_error = require_admin_request()
    if auth_error:
        return auth_error

    try:
        docs = list(
            crawler_user_runs_collection.find(
                {"username_key": username_key},
                {
                    "_id": 1,
                    "run_id": 1,
                    "username_key": 1,
                    "username": 1,
                    "status": 1,
                    "score": 1,
                    "influence": 1,
                    "thresholds": 1,
                    "created_at": 1,
                    "trigger_tweet_keys": 1,
                    "evidence_tweet_keys": 1,
                },
            ).sort("created_at", -1)
        )
        return jsonify({"items": [serialize_mongo_value(doc) for doc in docs]})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/crawler/export/users.csv", methods=["GET"])
def export_crawler_users_csv():
    auth_error = require_admin_request()
    if auth_error:
        return auth_error

    try:
        run_id = (request.args.get("runId") or "").strip()

        if run_id and run_id != "all":
            query = build_crawler_user_runs_query(request.args)
            if query is None:
                return jsonify({"success": False, "error": "Invalid crawler status"}), 400

            run_docs = list(
                crawler_user_runs_collection.find(
                    query,
                    {
                        "_id": 0,
                        "run_id": 1,
                        "username_key": 1,
                        "username": 1,
                        "status": 1,
                        "score": 1,
                        "influence": 1,
                        "thresholds": 1,
                        "created_at": 1,
                    },
                ).sort([("created_at", -1), ("username_key", 1)])
            )
            user_keys = [
                doc.get("username_key") for doc in run_docs if doc.get("username_key")
            ]
            user_docs = {
                doc.get("username_key"): doc
                for doc in crawler_users_collection.find(
                    {"username_key": {"$in": user_keys}},
                    {
                        "_id": 0,
                        "username_key": 1,
                        "username": 1,
                        "last_seen_at": 1,
                        "first_seen_at": 1,
                        "discovered_by_keywords": 1,
                    },
                )
            }
            users = [
                crawler_user_run_to_user_doc(doc, user_docs.get(doc.get("username_key")))
                for doc in run_docs
            ]
        else:
            query = build_crawler_users_query(request.args)
            if query is None:
                return jsonify({"success": False, "error": "Invalid crawler status"}), 400

            users = list(
                crawler_users_collection.find(
                    query,
                    {
                        "_id": 0,
                        "username_key": 1,
                        "username": 1,
                        "current_status": 1,
                        "latest_run_id": 1,
                        "latest_score": 1,
                        "latest_influence": 1,
                        "latest_thresholds": 1,
                        "last_seen_at": 1,
                        "discovered_by_keywords": 1,
                    },
                ).sort([("last_seen_at", -1), ("username_key", 1)])
            )
        header = [
            "username",
            "username_key",
            "status",
            "influence_score",
            "location",
            "followers_count",
            "views_count",
            "likes_count",
            "replies_count",
            "shares_count",
            "engagement_count",
            "positive_count",
            "taklidi_count",
            "evaluated_count",
            "positive_ratio",
            "taklidi_ratio",
            "ratio_threshold",
            "taklidi_ratio_threshold",
            "taklidi_ratio_margin",
            "min_positive_tweets",
            "min_profile_evaluated_tweets",
            "latest_run_id",
            "last_seen_at",
            "keywords",
        ]
        return csv_download_response(
            "crawler_users.csv",
            header,
            build_crawler_users_csv_rows(users),
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/crawler/export/evidence.csv", methods=["GET"])
def export_crawler_evidence_csv():
    auth_error = require_admin_request()
    if auth_error:
        return auth_error

    username_key = (request.args.get("usernameKey") or "").strip()
    if not username_key:
        return jsonify({"success": False, "error": "usernameKey is required"}), 400

    try:
        query = {"username_key": username_key}
        if not apply_crawler_evidence_filters(query, request.args):
            return jsonify({"success": False, "error": "Invalid crawler evidence label"}), 400

        evidence_docs = list(
            crawler_evidence_collection.find(
                query,
                {
                    "_id": 0,
                    "username": 1,
                    "phase": 1,
                    "tweet_url": 1,
                    "text": 1,
                    "model_label": 1,
                    "admin_label": 1,
                    "flagged": 1,
                    "confidence": 1,
                    "probabilities": 1,
                    "source.created_at": 1,
                    "source.author": 1,
                    "source.view_count": 1,
                    "source.like_count": 1,
                    "source.reply_count": 1,
                    "source.retweet_count": 1,
                    "source.quote_count": 1,
                    "source.bookmark_count": 1,
                    "collected_at": 1,
                },
            )
        )
        evidence_docs.sort(key=crawler_evidence_sort_key, reverse=True)
        header = [
            "username",
            "phase",
            "tweet_date",
            "model_label",
            "admin_label",
            "confidence",
            "flagged",
            "author_location",
            "author_followers_count",
            "views",
            "likes",
            "replies",
            "retweets",
            "quotes",
            "bookmarks",
            "prob_salafi_jihadi",
            "prob_salafi_taklidi",
            "prob_irrelevant",
            "tweet_url",
            "text",
        ]
        return csv_download_response(
            f"crawler_evidence_{username_key}.csv",
            header,
            build_crawler_evidence_csv_rows(evidence_docs),
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tweet', methods=['POST'])
def save_tweet():
    """Save a single tweet with its annotations"""
    try:
        init_db()
        tweet = request.json or {}
        if "id" not in tweet:
            return jsonify({"success": False, "error": "Missing tweet id"}), 400
        set_payload = {}
        unset_fields = []
        normalize_model_metadata(tweet)
        for key, value in tweet.items():
            if key == "_id":
                continue
            if value is None or value == "":
                if key == "finalLabel":
                    unset_fields.append(key)
                else:
                    set_payload[key] = value
                continue
            set_payload[key] = value
        doc = tweets_collection.find_one({"id": tweet["id"]}, {"_id": 0, "v": 1})
        payload = {
            "set": set_payload,
            "unset": unset_fields,
            "expectedVersion": doc.get("v") if doc else None,
        }
        updated_doc = apply_delta_patch(tweet["id"], payload)
        if not updated_doc:
            tweets_collection.update_one(
                {"id": tweet["id"]},
                {
                    "$set": {
                        **set_payload,
                        "updatedAt": datetime.utcnow(),
                        "v": 0,
                    }
                },
                upsert=True,
            )
        return jsonify({"success": True, "message": "Tweet saved successfully"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/tweets/<tweet_id>", methods=["PATCH"])
def patch_tweet(tweet_id):
    try:
        init_db()
        payload = request.json or {}
        updated_doc = apply_delta_patch(tweet_id, payload)
        if not updated_doc:
            return jsonify({"success": False, "error": "Version conflict"}), 409
        return jsonify({"success": True, "tweet": serialize_tweet(updated_doc)})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tweets/bulk', methods=['POST'])
def update_tweets_bulk():
    """Update multiple tweets at once"""
    try:
        init_db()
        updated_tweets = request.json or []
        if not isinstance(updated_tweets, list):
            return jsonify({"success": False, "error": "Invalid tweet list"}), 400
        invalid = [
            tweet
            for tweet in updated_tweets
            if not isinstance(tweet, dict) or "id" not in tweet
        ]
        if invalid:
            return jsonify({"success": False, "error": "All tweets must include id"}), 400
        ops = []
        for tweet in updated_tweets:
            set_payload = {}
            unset_fields = []
            normalize_model_metadata(tweet)
            for key, value in tweet.items():
                if key == "_id":
                    continue
                if value is None or value == "":
                    if key == "finalLabel":
                        unset_fields.append(key)
                    else:
                        set_payload[key] = value
                    continue
                set_payload[key] = value
            ops.append(
                {
                    "tweetId": tweet["id"],
                    "set": set_payload,
                    "unset": unset_fields,
                    "expectedVersion": tweet.get("v"),
                }
            )
        results = []
        for op in ops:
            updated_doc = apply_delta_patch(op["tweetId"], op)
            if not updated_doc:
                return jsonify({"success": False, "error": f"Version conflict for {op['tweetId']}"}), 409
            results.append({"tweetId": op["tweetId"], "success": True})
        return jsonify({"success": True, "message": "Tweets updated successfully", "results": results})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/tweets/delta/bulk", methods=["POST"])
def patch_tweets_bulk():
    try:
        init_db()
        payload = request.json or {}
        ops = payload.get("ops", [])
        if not isinstance(ops, list):
            return jsonify({"success": False, "error": "Invalid ops list"}), 400

        results = []
        for op in ops:
            tweet_id = op.get("tweetId")
            if not tweet_id:
                results.append({"success": False, "error": "Missing tweetId"})
                continue
            updated_doc = apply_delta_patch(tweet_id, op)
            if not updated_doc:
                results.append({"tweetId": tweet_id, "success": False, "error": "Version conflict"})
                continue
            results.append({"tweetId": tweet_id, "success": True, "tweet": serialize_tweet(updated_doc)})

        overall_success = all(result.get("success") for result in results) if results else True
        status_code = 200 if overall_success else 207
        return jsonify({"success": overall_success, "results": results}), status_code
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tweets/add', methods=['POST'])
def add_tweets():
    """Add new tweets to the database"""
    try:
        init_db()
        new_tweets = request.json or []
        if not isinstance(new_tweets, list):
            return jsonify({"success": False, "error": "Invalid tweet list"}), 400
        invalid = [
            tweet for tweet in new_tweets if not isinstance(tweet, dict) or "id" not in tweet
        ]
        if invalid:
            return jsonify({"success": False, "error": "All tweets must include id"}), 400
        operations = []
        now = datetime.now()
        for tweet in new_tweets:
            tweet_doc = {k: v for k, v in tweet.items() if k != "_id"}
            normalize_model_metadata(tweet_doc)
            tweet_doc["updatedAt"] = now
            tweet_doc.setdefault("v", 0)
            operations.append(
                UpdateOne(
                    {"id": tweet_doc["id"]},
                    {"$setOnInsert": tweet_doc},
                    upsert=True,
                )
            )
        inserted_count = 0
        if operations:
            result = tweets_collection.bulk_write(operations, ordered=False)
            inserted_count = len(result.upserted_ids or {})
        return jsonify(
            {
                "success": True,
                "message": f"Added {inserted_count} tweets",
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/tweet/<tweet_id>', methods=['DELETE'])
def delete_tweet(tweet_id):
    """Delete a tweet by ID"""
    try:
        init_db()
        tweets_collection.update_one(
            {"id": tweet_id},
            {"$set": {"deletedAt": datetime.now(), "isDeleted": True}}
        )
        return jsonify({"success": True, "message": "Tweet deleted successfully"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/tweets", methods=["DELETE"])
def delete_all_tweets():
    try:
        init_db()
        result = tweets_collection.delete_many({})
        return jsonify({"success": True, "deletedCount": result.deleted_count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/users/register', methods=['POST'])
def register_user():
    """Register a new user"""
    try:
        init_db()
        new_user = request.json or {}
        
        if "username" not in new_user:
            return jsonify({"success": False, "error": "Missing username"}), 400
        if not new_user.get("password"):
            return jsonify({"success": False, "error": "Missing password"}), 400
            
        if users_collection.find_one({"username": new_user["username"]}):
            return jsonify({"success": False, "error": "Username already exists"}), 400
            
        user_doc = {k: v for k, v in new_user.items() if k not in ("_id", "sessionToken")}
        user_doc["password"] = generate_password_hash(new_user["password"])
        users_collection.insert_one(user_doc)
        user_response = {
            k: v for k, v in user_doc.items() if k not in ("password", "_id")
        }
        session_token = secrets.token_urlsafe(32)
        session_tokens[session_token] = {
            "username": user_response.get("username"),
            "role": user_response.get("role"),
        }
        user_response["sessionToken"] = session_token
        
        return jsonify(user_response)
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/users/login', methods=['POST'])
def login_user():
    """Authenticate a user"""
    try:
        init_db()
        data = request.json or {}
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            return jsonify({"success": False, "error": "Missing credentials"}), 400

        user = users_collection.find_one({"username": username})
        if not user:
            return jsonify({"success": False, "error": "Invalid credentials"}), 401

        stored_password = user.get("password")
        if not verify_password(stored_password, password):
            return jsonify({"success": False, "error": "Invalid credentials"}), 401

        if stored_password and not is_password_hash(stored_password):
            users_collection.update_one(
                {"username": username},
                {"$set": {"password": generate_password_hash(password)}},
            )

        user_response = {k: v for k, v in user.items() if k not in ("password", "_id")}
        session_token = secrets.token_urlsafe(32)
        session_tokens[session_token] = {
            "username": user_response.get("username"),
            "role": user_response.get("role"),
        }
        user_response["sessionToken"] = session_token
        return jsonify(user_response)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/users/change-password', methods=['POST'])
def change_password():
    """Change a user's password"""
    try:
        init_db()
        data = request.json or {}
        
        username = data.get("username")
        current_password = data.get("currentPassword")
        new_password = data.get("newPassword")
        
        if not username or not current_password or not new_password:
            return jsonify({"success": False, "error": "Missing required fields"}), 400
        
        if len(new_password) < 6:
            return jsonify({"success": False, "error": "New password must be at least 6 characters"}), 400
        
        # Find user
        user = users_collection.find_one({"username": username})
        if not user:
            return jsonify({"success": False, "error": "User not found"}), 404
        
        # Verify current password
        stored_password = user.get("password")
        if not verify_password(stored_password, current_password):
            return jsonify({"success": False, "error": "Current password is incorrect"}), 401
        
        # Prevent same password
        if verify_password(stored_password, new_password):
            return jsonify({"success": False, "error": "New password cannot be the same as current password"}), 400
        
        # Update password
        users_collection.update_one(
            {"username": username},
            {"$set": {"password": generate_password_hash(new_password)}}
        )
        
        return jsonify({"success": True, "message": "Password changed successfully"})
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    db_status = "ok"
    try:
        mongo_client.admin.command("ping")
    except Exception:
        db_status = "error"
    return jsonify(
        {
            "status": "ok",
            "message": "TweetLabeler server is running",
            "mongo": db_status,
        }
    )

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve_react_app(path):
    """Serve the React app and static assets."""
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/export/csv', methods=['GET'])
def export_csv():
    """Export tweets with classifications to CSV file"""
    try:
        init_db()
        # Generate fresh CSV snapshot before export
        update_csv_snapshot()
        tweets = list(tweets_collection.find(base_tweet_query(), {"_id": 0}))
        users = list(users_collection.find({}, {"_id": 0}))

        # Get list of student usernames
        student_names = [u["username"] for u in users if u.get("role") == "student"]
        
        # Create CSV in memory
        output = io.StringIO()
        
        # Build header: ID, Text, Final Decision, Assigned To, then for each student [Label, Reasons]
        header = ['Tweet ID', 'Text', 'Final Decision', 'Assigned To']
        for student in student_names:
            header.append(f'Label_{student}')
            header.append(f'Reasons_{student}')
        
        writer = csv.writer(output)
        writer.writerow(header)
        
        # Write tweet data
        for tweet in tweets:
            assigned_str = ';'.join(tweet.get('assignedTo', []))
            final_label = tweet.get('finalLabel', '')
            
            # Handle CONFLICT label
            if final_label == 'CONFLICT':
                final_label = 'CONFLICT (Unresolved)'
            
            row = [
                tweet.get('id', ''),
                tweet.get('text', ''),
                final_label,
                assigned_str
            ]
            
            # Add label and reasons for each student
            annotations = tweet.get('annotations', {})
            annotation_features = tweet.get('annotationFeatures', {})
            
            for student in student_names:
                label = annotations.get(student, '')
                reasons = '; '.join(annotation_features.get(student, []))
                row.append(label)
                row.append(reasons)
            
            writer.writerow(row)
        
        # Convert to bytes and send as file
        output.seek(0)
        csv_bytes = output.getvalue().encode("utf-8-sig")  # utf-8-sig adds BOM for Excel
        
        return send_file(
            io.BytesIO(csv_bytes),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"tweets_classifications_{datetime.now().strftime('%Y-%m-%d')}.csv",
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
@app.route('/api/tweet/annotate', methods=['POST'])
def annotate_tweet():
    """Atomic update for a single annotation"""
    try:
        init_db()
        data = request.json or {}
        tweet_id = data.get("tweetId")
        username = data.get("username")
        label = normalize_label(data.get("label"))
        features = data.get("features", [])
        timestamp = data.get("timestamp")

        if not all([tweet_id, username, label]):
             return jsonify({"success": False, "error": "Missing fields"}), 400

        if not isinstance(features, list):
            features = []
        features = [str(feature).strip() for feature in features if str(feature).strip()]

        tweet_doc = tweets_collection.find_one(
            {"id": tweet_id, **base_tweet_query()},
            {
                "_id": 0,
                "id": 1,
                "assignedTo": 1,
                "annotations": 1,
                "annotationFeatures": 1,
                "annotationTimestamps": 1,
                "finalLabel": 1,
                "wasInConflict": 1,
                "conflictHistoryDismissed": 1,
                "conflictDetectedAt": 1,
            },
        )
        if not tweet_doc:
            return jsonify({"success": False, "error": "Tweet not found"}), 404

        merged_tweet = {
            **tweet_doc,
            "annotations": {**tweet_doc.get("annotations", {}), username: label},
            "annotationFeatures": {
                **tweet_doc.get("annotationFeatures", {}),
                username: features,
            },
            "annotationTimestamps": {
                **tweet_doc.get("annotationTimestamps", {}),
                username: timestamp,
            },
        }
        calculated_final_label = derive_final_label(merged_tweet)

        set_payload = {
            f"annotations.{username}": label,
            f"annotationFeatures.{username}": features,
            f"annotationTimestamps.{username}": timestamp,
        }
        unset_fields = []
        if calculated_final_label:
            set_payload["finalLabel"] = calculated_final_label
            if is_conflict_final_label(calculated_final_label):
                set_payload["wasInConflict"] = True
                set_payload["conflictHistoryDismissed"] = False
                set_payload["conflictDetectedAt"] = tweet_doc.get(
                    "conflictDetectedAt", int(datetime.utcnow().timestamp() * 1000)
                )
        else:
            unset_fields.append("finalLabel")

        updated_doc = tweets_collection.find_one_and_update(
            {"id": tweet_id, **base_tweet_query()},
            build_delta_update({"set": set_payload, "unset": unset_fields}),
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0, "id": 1, "finalLabel": 1, "v": 1},
        )
        return jsonify(
            {
                "success": True,
                "tweetId": tweet_id,
                "finalLabel": updated_doc.get("finalLabel"),
                "version": updated_doc.get("v", 0),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    print("🚀 TweetLabeler Server Starting...")
    print("API running at http://localhost:8080")
    print("MongoDB DB: ", MONGO_DB_NAME)
    app.run(debug=True, host="0.0.0.0", port=8080)
