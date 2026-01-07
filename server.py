from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
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

# Data file paths
DATA_FILE = 'data.json'
CSV_FILE = 'tweet_classifications.csv'
DEFAULT_DATA = {
    'tweets': [],
    'users': []
}

# Helper functions
def load_data():
    """Load data from JSON file"""
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading data: {e}")
            return DEFAULT_DATA.copy()
    return DEFAULT_DATA.copy()

def save_data(data):
    """Save data to JSON file"""
    try:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Also save to CSV file
        save_to_csv(data)
        return True
    except Exception as e:
        print(f"Error saving data: {e}")
        return False

def save_to_csv(data):
    """Save tweets with final decisions to CSV file"""
    try:
        tweets = data.get('tweets', [])
        
        with open(CSV_FILE, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            # Write header
            writer.writerow(['Tweet ID', 'Tweet Text', 'Final Decision'])
            
            # Write tweet data
            for tweet in tweets:
                final_label = tweet.get('finalLabel', 'Pending')
                
                # Handle CONFLICT label
                if final_label == 'CONFLICT':
                    final_label = 'CONFLICT (Unresolved)'
                
                writer.writerow([
                    tweet.get('id', ''),
                    tweet.get('text', ''),
                    final_label
                ])
        
        print(f"CSV file updated: {CSV_FILE}")
        return True
    except Exception as e:
        print(f"Error saving CSV: {e}")
        return False

# Routes

@app.route('/api/data', methods=['GET'])
def get_data():
    """Get all tweets and users"""
    data = load_data()
    return jsonify(data)

@app.route('/api/tweet', methods=['POST'])
def save_tweet():
    """Save a single tweet with its annotations"""
    try:
        tweet = request.json
        data = load_data()
        
        # Find and update the tweet, or add it if it doesn't exist
        tweet_index = next((i for i, t in enumerate(data['tweets']) if t['id'] == tweet['id']), None)
        
        if tweet_index is not None:
            data['tweets'][tweet_index] = tweet
        else:
            data['tweets'].append(tweet)
        
        save_data(data)
        return jsonify({'success': True, 'message': 'Tweet saved successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tweets/bulk', methods=['POST'])
def update_tweets_bulk():
    """Update multiple tweets at once"""
    try:
        updated_tweets = request.json
        data = load_data()
        
        # Replace all tweets
        data['tweets'] = updated_tweets
        
        save_data(data)
        return jsonify({'success': True, 'message': 'Tweets updated successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tweets/add', methods=['POST'])
def add_tweets():
    """Add new tweets to the database"""
    try:
        new_tweets = request.json
        data = load_data()
        
        # Add only tweets that don't already exist
        existing_ids = {t['id'] for t in data['tweets']}
        for tweet in new_tweets:
            if tweet['id'] not in existing_ids:
                data['tweets'].append(tweet)
        
        save_data(data)
        return jsonify({'success': True, 'message': f'Added {len(new_tweets)} tweets'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tweet/<tweet_id>', methods=['DELETE'])
def delete_tweet(tweet_id):
    """Delete a tweet by ID"""
    try:
        data = load_data()
        data['tweets'] = [t for t in data['tweets'] if t['id'] != tweet_id]
        
        save_data(data)
        return jsonify({'success': True, 'message': 'Tweet deleted successfully'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/users/register', methods=['POST'])
def register_user():
    """Register a new user"""
    try:
        new_user = request.json
        data = load_data()
        
        # Check if user already exists
        if any(u['username'] == new_user['username'] for u in data['users']):
            return jsonify({'success': False, 'error': 'Username already exists'}), 400
        
        # Add the new user
        data['users'].append(new_user)
        save_data(data)
        
        # Return user without password
        user_response = {k: v for k, v in new_user.items() if k != 'password'}
        return jsonify(user_response)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'ok', 'message': 'TweetLabeler server is running'})

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
        data = load_data()
        tweets = data.get('tweets', [])
        users = data.get('users', [])
        
        # Get list of student usernames
        student_names = [u['username'] for u in users if u.get('role') == 'student']
        
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
        csv_bytes = output.getvalue().encode('utf-8-sig')  # utf-8-sig adds BOM for Excel
        
        return send_file(
            io.BytesIO(csv_bytes),
            mimetype='text/csv',
            as_attachment=True,
            download_name=f'tweets_classifications_{datetime.now().strftime("%Y-%m-%d")}.csv'
        )
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

if __name__ == '__main__':
    print("🚀 TweetLabeler Server Starting...")
    print("API running at http://localhost:8080")
    print("Data file: ", os.path.abspath(DATA_FILE))
    app.run(debug=True, host="0.0.0.0", port=8080)
