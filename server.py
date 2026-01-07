from flask import Flask, jsonify, request
from flask_cors import CORS
import json
import os
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Data file paths
DATA_FILE = 'data.json'
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
        return True
    except Exception as e:
        print(f"Error saving data: {e}")
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

if __name__ == '__main__':
    print("🚀 TweetLabeler Server Starting...")
    print("API running at http://localhost:5000")
    print("Data file: ", os.path.abspath(DATA_FILE))
    app.run(debug=True, port=5000)
