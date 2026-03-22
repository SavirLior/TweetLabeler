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
from datetime import datetime
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
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

# Data file paths (used only for one-time migration/export)
DATA_FILE = "data.json"
CSV_FILE = "tweet_classifications.csv"

# MongoDB configuration
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "tweetlabeler")
MONGO_TWEETS_COLLECTION = os.getenv("MONGO_TWEETS_COLLECTION", "tweets")
MONGO_USERS_COLLECTION = os.getenv("MONGO_USERS_COLLECTION", "users")

mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = mongo_client[MONGO_DB_NAME]
tweets_collection = db[MONGO_TWEETS_COLLECTION]
users_collection = db[MONGO_USERS_COLLECTION]
db_initialized = False
HASH_PREFIXES = ("pbkdf2:", "scrypt:", "argon2:")
UNRESOLVED_FINAL_LABELS = {
    "",
    "pending",
    "not determined",
    "not_determined",
    "conflict",
    "conflict (unresolved)",
}

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


def build_tweet_list_query(args):
    query = base_tweet_query()
    assigned_to = args.get("assignedTo")
    final_label = args.get("finalLabel")
    conflict_only = args.get("conflictOnly") == "true"
    cursor = args.get("cursor")

    if assigned_to:
        query["assignedTo"] = assigned_to
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
        tweets = list(tweets_collection.find(base_tweet_query(), {"_id": 0}))
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
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        query = build_tweet_list_query(request.args)
        projection = {
            "_id": 1,
            "id": 1,
            "text": 1,
            "assignedTo": 1,
            "annotations": 1,
            "annotationFeatures": 1,
            "annotationTimestamps": 1,
            "finalLabel": 1,
            "wasInConflict": 1,
            "conflictHistoryDismissed": 1,
            "conflictDetectedAt": 1,
            "conflictResolvedAt": 1,
            "updatedAt": 1,
            "v": 1,
        }

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
            
        user_doc = {k: v for k, v in new_user.items() if k != "_id"}
        user_doc["password"] = generate_password_hash(new_user["password"])
        users_collection.insert_one(user_doc)
        user_response = {
            k: v for k, v in user_doc.items() if k not in ("password", "_id")
        }
        
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
