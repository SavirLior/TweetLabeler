from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
from pymongo import MongoClient, UpdateOne
from pymongo.errors import PyMongoError
import json
import os
import csv
import io
from datetime import datetime

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

# Helper functions
def init_db():
    global db_initialized
    if db_initialized:
        return
    mongo_client.admin.command("ping")
    tweets_collection.create_index("id", unique=True)
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
        if tweets:
            tweets_collection.insert_many(tweets, ordered=False)
        if users:
            users_collection.insert_many(users, ordered=False)
        print("Migrated data.json into MongoDB.")
    except Exception as e:
        print(f"Error migrating data.json: {e}")

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

# Routes

@app.route('/api/data', methods=['GET'])
def get_data():
    """Get all tweets and users"""
    try:
        init_db()
        tweets = list(tweets_collection.find({}, {"_id": 0}))
        users = list(users_collection.find({}, {"_id": 0}))
        return jsonify({"tweets": tweets, "users": users})
    except PyMongoError as e:
        return jsonify({"success": False, "error": str(e)}), 500
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
        tweet_doc = {k: v for k, v in tweet.items() if k != "_id"}
        tweets_collection.update_one(
            {"id": tweet_doc["id"]},
            {"$set": tweet_doc},
            upsert=True,
        )
        update_csv_snapshot()
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
            tweet_doc = {k: v for k, v in tweet.items() if k != "_id"}
            operations.append(
                UpdateOne(
                    {"id": tweet_doc["id"]},
                    {"$set": tweet_doc},
                    upsert=True,
                )
            )
        if operations:
            tweets_collection.bulk_write(operations, ordered=False)
        update_csv_snapshot()
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
            tweet_doc = {k: v for k, v in tweet.items() if k != "_id"}
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
        update_csv_snapshot()
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
        update_csv_snapshot()
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
            
        if users_collection.find_one({"username": new_user["username"]}):
            return jsonify({"success": False, "error": "Username already exists"}), 400
            
        users_collection.insert_one(new_user)        
        new_user["_id"] = str(new_user["_id"])
        user_response = {k: v for k, v in new_user.items() if k != "password"}
        
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
        if user.get("password") != current_password:
            return jsonify({"success": False, "error": "Current password is incorrect"}), 401
        
        # Prevent same password
        if current_password == new_password:
            return jsonify({"success": False, "error": "New password cannot be the same as current password"}), 400
        
        # Update password
        users_collection.update_one(
            {"username": username},
            {"$set": {"password": new_password}}
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

if __name__ == '__main__':
    print("🚀 TweetLabeler Server Starting...")
    print("API running at http://localhost:8080")
    print("MongoDB DB: ", MONGO_DB_NAME)
    app.run(debug=True, host="0.0.0.0", port=8080)
