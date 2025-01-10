from flask import Flask, request, jsonify
from flask_cors import CORS
from pymongo import MongoClient, DESCENDING
from bson import ObjectId
from functools import wraps
import os
import datetime
import requests
import time
import threading
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# MongoDB Connection with retry logic
def get_db_connection(max_retries=3, retry_delay=5):
    for attempt in range(max_retries):
        try:
            client = MongoClient(os.getenv('MONGODB_URI'), serverSelectionTimeoutMS=5000)
            client.admin.command('ping')  # Test connection
            return client
        except Exception as e:
            if attempt == max_retries - 1:
                raise e
            time.sleep(retry_delay)

# Database initialization
def init_db():
    client = get_db_connection()
    db = client[os.getenv('DB_NAME', 'diary_db')]
    
    # Create indexes
    db.entries.create_index([('created_at', DESCENDING)])
    
    # Initialize visitors collection if needed
    if db.visitors.count_documents({}) == 0:
        db.visitors.insert_one({'count': 0})
    
    return db

# Authentication decorator
def require_auth(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_code = request.headers.get('X-Auth-Code')
        if auth_code != os.getenv('AUTH_CODE'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

# Enhanced self-ping with health check
def ping_self():
    while True:
        try:
            response = requests.get(f"{os.getenv('APP_URL')}/health")
            if response.status_code != 200:
                print(f"Health check failed: {response.status_code}")
        except Exception as e:
            print(f"Ping failed: {str(e)}")
        finally:
            time.sleep(300)  # 5 minutes

if os.getenv('ENVIRONMENT') == 'production':
    ping_thread = threading.Thread(target=ping_self, daemon=True)
    ping_thread.start()

# Routes
@app.route('/health', methods=['GET'])
def health_check():
    try:
        db = get_db_connection().get_database()
        db.command('ping')
        return jsonify({'status': 'healthy'}), 200
    except Exception as e:
        return jsonify({'status': 'unhealthy', 'error': str(e)}), 500

@app.route('/entries', methods=['GET'])
def get_entries():
    try:
        db = get_db_connection().get_database()
        entries = list(db.entries.find({}, {'_id': 1, 'date': 1, 'content': 1})
                      .sort('created_at', DESCENDING))
        
        # Convert ObjectId to string for JSON serialization
        for entry in entries:
            entry['id'] = str(entry.pop('_id'))
        
        return jsonify(entries)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/entries', methods=['POST'])
@require_auth
def add_entry():
    try:
        data = request.json
        if not data.get('content') or not data.get('date'):
            return jsonify({'error': 'Missing required fields'}), 400

        db = get_db_connection().get_database()
        result = db.entries.insert_one({
            'date': data['date'],
            'content': data['content'],
            'created_at': datetime.datetime.utcnow()
        })

        return jsonify({
            'message': 'Entry added successfully',
            'id': str(result.inserted_id)
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/entries/<entry_id>', methods=['PUT'])
@require_auth
def update_entry(entry_id):
    try:
        data = request.json
        if not data.get('content'):
            return jsonify({'error': 'Content is required'}), 400

        db = get_db_connection().get_database()
        result = db.entries.update_one(
            {'_id': ObjectId(entry_id)},
            {'$set': {'content': data['content']}}
        )

        if result.matched_count == 0:
            return jsonify({'error': 'Entry not found'}), 404

        return jsonify({'message': 'Entry updated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/entries/<entry_id>', methods=['DELETE'])
@require_auth
def delete_entry(entry_id):
    try:
        db = get_db_connection().get_database()
        result = db.entries.delete_one({'_id': ObjectId(entry_id)})

        if result.deleted_count == 0:
            return jsonify({'error': 'Entry not found'}), 404

        return jsonify({'message': 'Entry deleted successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/visitors', methods=['GET'])
def get_visitors():
    try:
        db = get_db_connection().get_database()
        visitor_doc = db.visitors.find_one()
        return jsonify({'count': visitor_doc['count']})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/visitors/increment', methods=['POST'])
def increment_visitors():
    try:
        db = get_db_connection().get_database()
        db.visitors.update_one({}, {'$inc': {'count': 1}})
        return jsonify({'message': 'Visitor count incremented'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
