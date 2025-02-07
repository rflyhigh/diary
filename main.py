from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import datetime
import threading
import time
import requests
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from bson import ObjectId
from functools import wraps
import pytz

load_dotenv()

app = Flask(__name__)
CORS(app)

try:
    client = MongoClient(os.getenv('MONGODB_URI'), serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client[os.getenv('MONGODB_DB', 'diary_db')]
    print("Connected to MongoDB successfully")
except (ConnectionFailure, ServerSelectionTimeoutError) as e:
    print(f"Failed to connect to MongoDB: {e}")

def init_db():
    try:
        if db.visitors.count_documents({}) == 0:
            db.visitors.insert_one({'count': 0})
            print("Initialized visitors collection")
    except Exception as e:
        print(f"Database initialization error: {e}")

def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_code = request.headers.get('X-Auth-Code')
        if auth_code != os.getenv('AUTH_CODE'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

def ping_self():
    while True:
        try:
            app_url = os.getenv('APP_URL')
            if app_url:
                response = requests.get(app_url, timeout=10)
                if response.status_code != 200:
                    print(f"Ping failed with status code: {response.status_code}")
        except Exception as e:
            print(f"Ping error: {str(e)}")
        time.sleep(300)  # 5 minutes

@app.route('/auth', methods=['POST'])
def authenticate():
    data = request.json
    auth_code = data.get('authCode')
    if auth_code != os.getenv('AUTH_CODE'):
        return jsonify({'error': 'Invalid authentication code'}), 401
    return jsonify({'message': 'Authentication successful'})

@app.route('/entries', methods=['GET'])
@require_auth
def get_entries():
    try:
        entries = list(db.entries.find({}, {'_id': 1, 'date': 1, 'content': 1})
                      .sort('created_at', -1))
        
        for entry in entries:
            entry['id'] = str(entry.pop('_id'))
        
        return jsonify(entries)
    except Exception as e:
        print(f"Error fetching entries: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/entries', methods=['POST'])
@require_auth
def add_entry():
    try:
        data = request.json
        if not data.get('content') or not data.get('date'):
            return jsonify({'error': 'Missing required fields'}), 400

        entry = {
            'date': data['date'],
            'content': data['content'],
            'created_at': datetime.datetime.now(pytz.timezone('Asia/Kolkata'))
        }
        
        result = db.entries.insert_one(entry)
        
        return jsonify({
            'message': 'Entry added successfully',
            'id': str(result.inserted_id)
        }), 201
    except Exception as e:
        print(f"Error adding entry: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/entries/<entry_id>', methods=['PUT'])
@require_auth
def update_entry(entry_id):
    try:
        data = request.json
        if not data.get('content'):
            return jsonify({'error': 'Content is required'}), 400

        result = db.entries.update_one(
            {'_id': ObjectId(entry_id)},
            {'$set': {'content': data['content']}}
        )

        if result.matched_count == 0:
            return jsonify({'error': 'Entry not found'}), 404

        return jsonify({'message': 'Entry updated successfully'})
    except Exception as e:
        print(f"Error updating entry: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/entries/<entry_id>', methods=['DELETE'])
@require_auth
def delete_entry(entry_id):
    try:
        result = db.entries.delete_one({'_id': ObjectId(entry_id)})
        
        if result.deleted_count == 0:
            return jsonify({'error': 'Entry not found'}), 404

        return jsonify({'message': 'Entry deleted successfully'})
    except Exception as e:
        print(f"Error deleting entry: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/visitors', methods=['GET'])
@require_auth
def get_visitors():
    try:
        visitor_doc = db.visitors.find_one({})
        if visitor_doc is None:
            return jsonify({'count': 0})
        return jsonify({'count': visitor_doc['count']})
    except Exception as e:
        print(f"Error fetching visitors: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/visitors/increment', methods=['POST'])
@require_auth
def increment_visitors():
    try:
        db.visitors.update_one(
            {},
            {'$inc': {'count': 1}},
            upsert=True
        )
        return jsonify({'message': 'Visitor count incremented'})
    except Exception as e:
        print(f"Error incrementing visitors: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    init_db()
    
    if os.getenv('ENVIRONMENT') == 'production':
        ping_thread = threading.Thread(target=ping_self, daemon=True)
        ping_thread.start()
    
    app.run(host='0.0.0.0', port=port)
