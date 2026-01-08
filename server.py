from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS
import json
import os
import csv
import io
import sqlite3
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
DB_FILE = os.path.join('db', 'labeler.db')
CSV_FILE = 'tweet_classifications.csv'

def get_db_connection():
    if not os.path.exists('db'):
        os.makedirs('db')
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create tables
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            role TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tweets (
            id TEXT PRIMARY KEY,
            text TEXT,
            final_label TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS assignments (
            tweet_id TEXT,
            username TEXT,
            PRIMARY KEY (tweet_id, username),
            FOREIGN KEY (tweet_id) REFERENCES tweets (id),
            FOREIGN KEY (username) REFERENCES users (username)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS annotations (
            tweet_id TEXT,
            username TEXT,
            label TEXT,
            timestamp INTEGER,
            features TEXT,
            PRIMARY KEY (tweet_id, username),
            FOREIGN KEY (tweet_id) REFERENCES tweets (id),
            FOREIGN KEY (username) REFERENCES users (username)
        )
    ''')
    
    conn.commit()
    conn.close()

def init_db_from_json():
    """Migrate data from JSON to SQLite if DB is empty"""
    if not os.path.exists(DATA_FILE):
        return

    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Check if users table is empty
    cursor.execute('SELECT count(*) FROM users')
    if cursor.fetchone()[0] > 0:
        conn.close()
        return

    print("Migrating data from JSON to SQLite...")
    
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # Migrate users
        for user in data.get('users', []):
            cursor.execute(
                'INSERT OR IGNORE INTO users (username, password, role) VALUES (?, ?, ?)',
                (user['username'], user['password'], user['role'])
            )
            
        # Migrate tweets and related data
        for tweet in data.get('tweets', []):
            # Insert tweet
            cursor.execute(
                'INSERT OR IGNORE INTO tweets (id, text, final_label) VALUES (?, ?, ?)',
                (tweet['id'], tweet['text'], tweet.get('finalLabel'))
            )
            
            # Insert assignments
            for username in tweet.get('assignedTo', []):
                cursor.execute(
                    'INSERT OR IGNORE INTO assignments (tweet_id, username) VALUES (?, ?)',
                    (tweet['id'], username)
                )
                
            # Insert annotations
            annotations = tweet.get('annotations', {})
            timestamps = tweet.get('annotationTimestamps', {})
            features_map = tweet.get('annotationFeatures', {})
            
            # Get all unique usernames involved in annotations
            annotators = set(annotations.keys()) | set(timestamps.keys()) | set(features_map.keys())
            
            for username in annotators:
                label = annotations.get(username)
                timestamp = timestamps.get(username)
                features = features_map.get(username)
                
                if label or timestamp or features:
                    cursor.execute(
                        '''INSERT OR REPLACE INTO annotations 
                           (tweet_id, username, label, timestamp, features) 
                           VALUES (?, ?, ?, ?, ?)''',
                        (tweet['id'], username, label, timestamp, json.dumps(features) if features else None)
                    )
        
        conn.commit()
        print("Migration completed successfully.")
        
    except Exception as e:
        print(f"Error during migration: {e}")
        conn.rollback()
    finally:
        conn.close()

# Initialize DB on startup
init_db()
init_db_from_json()

def load_data_from_db():
    """Fetch all data from SQL tables and reconstruct the original JSON structure"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    data = {
        'users': [],
        'tweets': []
    }
    
    try:
        # Fetch users
        cursor.execute('SELECT * FROM users')
        users = cursor.fetchall()
        for user in users:
            data['users'].append({
                'username': user['username'],
                'password': user['password'],
                'role': user['role']
            })
            
        # Fetch tweets
        cursor.execute('SELECT * FROM tweets')
        tweets = cursor.fetchall()
        
        for tweet_row in tweets:
            tweet_id = tweet_row['id']
            tweet_obj = {
                'id': tweet_id,
                'text': tweet_row['text'],
                'finalLabel': tweet_row['final_label'],
                'assignedTo': [],
                'annotations': {},
                'annotationTimestamps': {},
                'annotationFeatures': {}
            }
            
            # Fetch assignments for this tweet
            cursor.execute('SELECT username FROM assignments WHERE tweet_id = ?', (tweet_id,))
            assignments = cursor.fetchall()
            tweet_obj['assignedTo'] = [a['username'] for a in assignments]
            
            # Fetch annotations for this tweet
            cursor.execute('SELECT * FROM annotations WHERE tweet_id = ?', (tweet_id,))
            annotations = cursor.fetchall()
            
            for ann in annotations:
                username = ann['username']
                if ann['label']:
                    tweet_obj['annotations'][username] = ann['label']
                if ann['timestamp']:
                    tweet_obj['annotationTimestamps'][username] = ann['timestamp']
                if ann['features']:
                    try:
                        tweet_obj['annotationFeatures'][username] = json.loads(ann['features'])
                    except:
                        pass
            
            data['tweets'].append(tweet_obj)
            
        return data
    except Exception as e:
        print(f"Error loading data from DB: {e}")
        return {'users': [], 'tweets': []}
    finally:
        conn.close()

# Routes

@app.route('/api/data', methods=['GET'])
def get_data():
    """Get all tweets and users"""
    data = load_data_from_db()
    return jsonify(data)

@app.route('/api/tweet', methods=['POST'])
def save_tweet():
    """Save a single tweet with its annotations"""
    try:
        tweet = request.json
        tweet_id = tweet['id']
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Update tweet details
            cursor.execute(
                'INSERT OR REPLACE INTO tweets (id, text, final_label) VALUES (?, ?, ?)',
                (tweet_id, tweet.get('text'), tweet.get('finalLabel'))
            )
            
            # Update assignments
            # First delete existing assignments for this tweet
            cursor.execute('DELETE FROM assignments WHERE tweet_id = ?', (tweet_id,))
            # Then insert new ones
            for username in tweet.get('assignedTo', []):
                cursor.execute(
                    'INSERT INTO assignments (tweet_id, username) VALUES (?, ?)',
                    (tweet_id, username)
                )
            
            # Update annotations
            # First delete existing annotations for this tweet to ensure we match the frontend state
            cursor.execute('DELETE FROM annotations WHERE tweet_id = ?', (tweet_id,))
            
            annotations = tweet.get('annotations', {})
            timestamps = tweet.get('annotationTimestamps', {})
            features_map = tweet.get('annotationFeatures', {})
            
            annotators = set(annotations.keys()) | set(timestamps.keys()) | set(features_map.keys())
            
            for username in annotators:
                label = annotations.get(username)
                timestamp = timestamps.get(username)
                features = features_map.get(username)
                
                cursor.execute(
                    '''INSERT INTO annotations 
                       (tweet_id, username, label, timestamp, features) 
                       VALUES (?, ?, ?, ?, ?)''',
                    (tweet_id, username, label, timestamp, json.dumps(features) if features else None)
                )
            
            conn.commit()
            return jsonify({'success': True, 'message': 'Tweet saved successfully'})
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tweets/bulk', methods=['POST'])
def update_tweets_bulk():
    """Update multiple tweets at once"""
    try:
        updated_tweets = request.json
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            for tweet in updated_tweets:
                tweet_id = tweet['id']
                
                # Update tweet details
                cursor.execute(
                    'INSERT OR REPLACE INTO tweets (id, text, final_label) VALUES (?, ?, ?)',
                    (tweet_id, tweet.get('text'), tweet.get('finalLabel'))
                )
                
                # Update assignments
                cursor.execute('DELETE FROM assignments WHERE tweet_id = ?', (tweet_id,))
                for username in tweet.get('assignedTo', []):
                    cursor.execute(
                        'INSERT INTO assignments (tweet_id, username) VALUES (?, ?)',
                        (tweet_id, username)
                    )
                
                # Update annotations
                cursor.execute('DELETE FROM annotations WHERE tweet_id = ?', (tweet_id,))
                
                annotations = tweet.get('annotations', {})
                timestamps = tweet.get('annotationTimestamps', {})
                features_map = tweet.get('annotationFeatures', {})
                
                annotators = set(annotations.keys()) | set(timestamps.keys()) | set(features_map.keys())
                
                for username in annotators:
                    label = annotations.get(username)
                    timestamp = timestamps.get(username)
                    features = features_map.get(username)
                    
                    cursor.execute(
                        '''INSERT INTO annotations 
                           (tweet_id, username, label, timestamp, features) 
                           VALUES (?, ?, ?, ?, ?)''',
                        (tweet_id, username, label, timestamp, json.dumps(features) if features else None)
                    )
            
            conn.commit()
            return jsonify({'success': True, 'message': 'Tweets updated successfully'})
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tweets/add', methods=['POST'])
def add_tweets():
    """Add new tweets to the database"""
    try:
        new_tweets = request.json
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            count = 0
            for tweet in new_tweets:
                # Check if exists
                cursor.execute('SELECT 1 FROM tweets WHERE id = ?', (tweet['id'],))
                if cursor.fetchone() is None:
                    cursor.execute(
                        'INSERT INTO tweets (id, text, final_label) VALUES (?, ?, ?)',
                        (tweet['id'], tweet['text'], tweet.get('finalLabel'))
                    )
                    count += 1
            
            conn.commit()
            return jsonify({'success': True, 'message': f'Added {count} tweets'})
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/tweet/<tweet_id>', methods=['DELETE'])
def delete_tweet(tweet_id):
    """Delete a tweet by ID"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute('DELETE FROM annotations WHERE tweet_id = ?', (tweet_id,))
            cursor.execute('DELETE FROM assignments WHERE tweet_id = ?', (tweet_id,))
            cursor.execute('DELETE FROM tweets WHERE id = ?', (tweet_id,))
            
            conn.commit()
            return jsonify({'success': True, 'message': 'Tweet deleted successfully'})
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/users/register', methods=['POST'])
def register_user():
    """Register a new user"""
    try:
        new_user = request.json
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Check if user already exists
            cursor.execute('SELECT 1 FROM users WHERE username = ?', (new_user['username'],))
            if cursor.fetchone() is not None:
                return jsonify({'success': False, 'error': 'Username already exists'}), 400
            
            cursor.execute(
                'INSERT INTO users (username, password, role) VALUES (?, ?, ?)',
                (new_user['username'], new_user['password'], new_user['role'])
            )
            
            conn.commit()
            
            # Return user without password
            user_response = {k: v for k, v in new_user.items() if k != 'password'}
            return jsonify(user_response)
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
            
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
        data = load_data_from_db()
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
    print("DB file: ", os.path.abspath(DB_FILE))
    app.run(debug=True, host="0.0.0.0", port=8080)