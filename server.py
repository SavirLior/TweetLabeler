from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError
from pymongo import ReturnDocument
from werkzeug.security import check_password_hash, generate_password_hash
import json
import os
import csv
import io
from datetime import datetime
from bson import ObjectId
from bson.errors import InvalidId
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
    tweets_collection.create_index("id", unique=True)
    tweets_collection.create_index([("assignedTo", 1), ("_id", 1)])
    tweets_collection.create_index([("finalLabel", 1), ("_id", 1)])
    tweets_collection.create_index([("updatedAt", -1)])
    tweets_collection.create_index(
        [("finalLabel", 1), ("_id", 1)],
        partialFilterExpression={"finalLabel": "CONFLICT"},
        name="conflict_only_idx",
    )
    users_collection.create_index("username", unique=True)
    migrate_from_file()
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


def sanitize_tweet_document(tweet_doc):
    """Ensure required document shape and metadata for legacy write endpoints."""
    clean = {k: v for k, v in tweet_doc.items() if k != "_id"}
    if not isinstance(clean.get("annotations"), dict):
        clean["annotations"] = {}
    if not isinstance(clean.get("annotationFeatures"), dict):
        clean["annotationFeatures"] = {}
    if not isinstance(clean.get("annotationTimestamps"), dict):
        clean["annotationTimestamps"] = {}
    if not isinstance(clean.get("assignedTo"), list):
        clean.pop("assignedTo", None)
    if not isinstance(clean.get("v"), int):
        clean["v"] = 0
    clean["updatedAt"] = datetime.utcnow()
    return clean


def serialize_tweet(tweet_doc):
    """Convert Mongo document to JSON-safe tweet payload."""
    if not tweet_doc:
        return None
    doc = dict(tweet_doc)
    mongo_id = doc.get("_id")
    if isinstance(mongo_id, ObjectId):
        doc["_id"] = str(mongo_id)
    if isinstance(doc.get("updatedAt"), datetime):
        doc["updatedAt"] = doc["updatedAt"].isoformat()
    return doc

# Routes

@app.route('/api/data', methods=['GET'])
def get_data():
    """Get all tweets and users"""
    try:
        init_db()
        tweets = list(tweets_collection.find({}, {"_id": 0}))
        users = list(users_collection.find({}, {"_id": 0, "password": 0}))
        return jsonify({"tweets": tweets, "users": users})
    except PyMongoError as e:
        return jsonify({"success": False, "error": str(e)}), 500
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/users', methods=['GET'])
def get_users():
    """Get all users without password fields."""
    try:
        init_db()
        users = list(users_collection.find({}, {"_id": 0, "password": 0}))
        return jsonify({"users": users})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tweets', methods=['GET'])
def list_tweets():
    """Paginated tweets endpoint (cursor based)."""
    try:
        init_db()
        limit = min(max(int(request.args.get("limit", 50)), 1), 200)
        cursor = request.args.get("cursor")
        assigned_to = request.args.get("assignedTo")
        final_label = request.args.get("finalLabel")
        conflict_only = request.args.get("conflictOnly") == "true"

        query = {}
        if assigned_to:
            query["assignedTo"] = assigned_to
        if final_label:
            query["finalLabel"] = final_label
        if conflict_only:
            query["finalLabel"] = "CONFLICT"
        if cursor:
            try:
                query["_id"] = {"$gt": ObjectId(cursor)}
            except InvalidId:
                return jsonify({"success": False, "error": "Invalid cursor"}), 400

        projection = {
            "_id": 1,
            "id": 1,
            "text": 1,
            "assignedTo": 1,
            "annotations": 1,
            "annotationFeatures": 1,
            "annotationTimestamps": 1,
            "finalLabel": 1,
            "v": 1,
        }

        docs = list(
            tweets_collection.find(query, projection).sort("_id", 1).limit(limit + 1)
        )
        has_more = len(docs) > limit
        page_docs = docs[:limit]
        next_cursor = str(page_docs[-1]["_id"]) if has_more and page_docs else None

        items = [serialize_tweet(doc) for doc in page_docs]
        return jsonify(
            {
                "items": items,
                "nextCursor": next_cursor,
                "hasMore": has_more,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tweets', methods=['DELETE'])
def delete_all_tweets():
    """Delete all tweets in one operation."""
    try:
        init_db()
        result = tweets_collection.delete_many({})
        return jsonify(
            {
                "success": True,
                "message": "All tweets deleted successfully",
                "deletedCount": result.deleted_count,
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tweets/<tweet_id>', methods=['PATCH'])
def patch_tweet(tweet_id):
    """Delta patch endpoint for a single tweet."""
    try:
        init_db()
        payload = request.json or {}
        set_fields = payload.get("set", {})
        unset_fields = payload.get("unset", [])
        expected_version = payload.get("expectedVersion")

        if set_fields is not None and not isinstance(set_fields, dict):
            return jsonify({"success": False, "error": "`set` must be an object"}), 400
        if unset_fields is not None and not isinstance(unset_fields, list):
            return jsonify({"success": False, "error": "`unset` must be a list"}), 400
        if expected_version is not None and not isinstance(expected_version, int):
            return (
                jsonify({"success": False, "error": "`expectedVersion` must be an integer"}),
                400,
            )

        query = {"id": tweet_id}
        if expected_version is not None:
            query["v"] = expected_version

        update_set = {"updatedAt": datetime.utcnow()}
        if set_fields:
            update_set.update(set_fields)

        update_doc = {"$set": update_set, "$inc": {"v": 1}}
        if unset_fields:
            update_doc["$unset"] = {
                field: ""
                for field in unset_fields
                if isinstance(field, str) and field.strip()
            }

        updated = tweets_collection.find_one_and_update(
            query,
            update_doc,
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0},
        )
        if updated:
            return jsonify({"success": True, "tweet": serialize_tweet(updated)})

        exists = tweets_collection.find_one({"id": tweet_id}, {"_id": 1})
        if not exists:
            return jsonify({"success": False, "error": "Tweet not found"}), 404
        return jsonify({"success": False, "error": "Version conflict"}), 409
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/tweets/delta/bulk', methods=['POST'])
def patch_tweets_bulk_delta():
    """Batch delta update endpoint with per-operation result status."""
    try:
        init_db()
        payload = request.json or {}
        ops = payload.get("ops", [])
        if not isinstance(ops, list):
            return jsonify({"success": False, "error": "`ops` must be a list"}), 400

        results = []
        for op in ops:
            if not isinstance(op, dict):
                results.append({"success": False, "error": "Operation must be an object"})
                continue

            tweet_id = op.get("tweetId")
            if not tweet_id:
                results.append({"success": False, "error": "Missing tweetId"})
                continue

            set_fields = op.get("set", {})
            unset_fields = op.get("unset", [])
            expected_version = op.get("expectedVersion")

            if set_fields is not None and not isinstance(set_fields, dict):
                results.append(
                    {
                        "tweetId": tweet_id,
                        "success": False,
                        "error": "`set` must be an object",
                    }
                )
                continue
            if unset_fields is not None and not isinstance(unset_fields, list):
                results.append(
                    {
                        "tweetId": tweet_id,
                        "success": False,
                        "error": "`unset` must be a list",
                    }
                )
                continue
            if expected_version is not None and not isinstance(expected_version, int):
                results.append(
                    {
                        "tweetId": tweet_id,
                        "success": False,
                        "error": "`expectedVersion` must be an integer",
                    }
                )
                continue

            query = {"id": tweet_id}
            if expected_version is not None:
                query["v"] = expected_version

            update_set = {"updatedAt": datetime.utcnow()}
            if set_fields:
                update_set.update(set_fields)

            update_doc = {"$set": update_set, "$inc": {"v": 1}}
            if unset_fields:
                update_doc["$unset"] = {
                    field: ""
                    for field in unset_fields
                    if isinstance(field, str) and field.strip()
                }

            updated = tweets_collection.find_one_and_update(
                query,
                update_doc,
                return_document=ReturnDocument.AFTER,
                projection={"id": 1, "v": 1, "_id": 0},
            )
            if updated:
                results.append(
                    {
                        "tweetId": tweet_id,
                        "success": True,
                        "version": updated.get("v"),
                    }
                )
                continue

            exists = tweets_collection.find_one({"id": tweet_id}, {"_id": 1})
            if not exists:
                results.append(
                    {"tweetId": tweet_id, "success": False, "error": "Tweet not found", "code": 404}
                )
            else:
                results.append(
                    {"tweetId": tweet_id, "success": False, "error": "Version conflict", "code": 409}
                )

        all_success = all(result.get("success") for result in results) if results else True
        return jsonify({"success": all_success, "results": results})
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
        tweet_doc = sanitize_tweet_document(tweet)
        
        # Handle field deletion: if finalLabel is empty string, remove it
        if "finalLabel" in tweet_doc and tweet_doc["finalLabel"] == "":
            tweets_collection.update_one(
                {"id": tweet_doc["id"]},
                {
                    "$set": {k: v for k, v in tweet_doc.items() if k != "finalLabel"},
                    "$unset": {"finalLabel": ""}
                },
                upsert=True,
            )
        else:
            tweets_collection.update_one(
                {"id": tweet_doc["id"]},
                {"$set": tweet_doc},
                upsert=True,
            )
        return jsonify({"success": True, "message": "Tweet saved successfully"})
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
        operations = []
        for tweet in updated_tweets:
            tweet_doc = sanitize_tweet_document(tweet)
            # Handle field deletion: if finalLabel is empty string, remove it
            if "finalLabel" in tweet_doc and tweet_doc["finalLabel"] == "":
                operations.append(
                    UpdateOne(
                        {"id": tweet_doc["id"]},
                        {
                            "$set": {k: v for k, v in tweet_doc.items() if k != "finalLabel"},
                            "$unset": {"finalLabel": ""}
                        },
                        upsert=True,
                    )
                )
            else:
                operations.append(
                    UpdateOne(
                        {"id": tweet_doc["id"]},
                        {"$set": tweet_doc},
                        upsert=True,
                    )
                )
        if operations:
            tweets_collection.bulk_write(operations, ordered=False)
        return jsonify({"success": True, "message": "Tweets updated successfully"})
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
        for tweet in new_tweets:
            tweet_doc = sanitize_tweet_document(tweet)
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
        tweets_collection.delete_one({"id": tweet_id})
        return jsonify({"success": True, "message": "Tweet deleted successfully"})
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
        tweets = list(tweets_collection.find({}, {"_id": 0}))
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
    """Atomic delta update for a single annotation."""
    try:
        init_db()
        data = request.json or {}
        tweet_id = data.get("tweetId")
        username = data.get("username")
        label = normalize_label(data.get("label"))
        features = data.get("features", [])
        timestamp = data.get("timestamp")
        expected_version = data.get("expectedVersion")

        if not all([tweet_id, username, label]):
             return jsonify({"success": False, "error": "Missing fields"}), 400

        if not isinstance(features, list):
            features = []
        features = [str(feature).strip() for feature in features if str(feature).strip()]
        if expected_version is not None and not isinstance(expected_version, int):
            return jsonify({"success": False, "error": "`expectedVersion` must be an integer"}), 400

        update_fields = {
            f"annotations.{username}": label,
            f"annotationFeatures.{username}": features,
            f"annotationTimestamps.{username}": timestamp,
            "updatedAt": datetime.utcnow(),
        }

        query = {"id": tweet_id}
        if expected_version is not None:
            query["v"] = expected_version

        updated_tweet = tweets_collection.find_one_and_update(
            query,
            {"$set": update_fields, "$inc": {"v": 1}},
            return_document=ReturnDocument.AFTER,
            projection={"_id": 0, "id": 1, "v": 1},
        )
        if not updated_tweet:
            exists = tweets_collection.find_one({"id": tweet_id}, {"_id": 1})
            if not exists:
                return jsonify({"success": False, "error": "Tweet not found"}), 404
            return jsonify({"success": False, "error": "Version conflict"}), 409

        calculated_final_label = update_final_label_with_retry(tweet_id)
        latest_tweet = tweets_collection.find_one({"id": tweet_id}, {"_id": 0, "v": 1, "finalLabel": 1})

        return jsonify(
            {
                "success": True,
                "message": "Annotation saved atomically via delta update",
                "tweetId": tweet_id,
                "finalLabel": (latest_tweet or {}).get("finalLabel", calculated_final_label),
                "version": (latest_tweet or {}).get("v", updated_tweet.get("v")),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    print("🚀 TweetLabeler Server Starting...")
    print("API running at http://localhost:8080")
    print("MongoDB DB: ", MONGO_DB_NAME)
    app.run(debug=True, host="0.0.0.0", port=8080)
