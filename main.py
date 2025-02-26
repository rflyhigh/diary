from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import os
import datetime
import threading
import time
import requests
import uuid
import mimetypes
from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, ServerSelectionTimeoutError
from bson import ObjectId, Binary
from functools import wraps
import pytz
import io
import gridfs
from PIL import Image

load_dotenv()

app = Flask(__name__)
CORS(app)

# Configure MongoDB connection
try:
    client = MongoClient(os.getenv('MONGODB_URI'), serverSelectionTimeoutMS=5000)
    client.admin.command('ping')
    db = client[os.getenv('MONGODB_DB', 'diary_db')]
    fs = gridfs.GridFS(db)  # For storing files
    print("Connected to MongoDB successfully")
except (ConnectionFailure, ServerSelectionTimeoutError) as e:
    print(f"Failed to connect to MongoDB: {e}")

def init_db():
    """Initialize database collections if they don't exist"""
    try:
        # Initialize visitors collection if it doesn't exist
        if db.visitors.count_documents({}) == 0:
            db.visitors.insert_one({'count': 0})
            print("Initialized visitors collection")
        
        # Initialize user_settings collection if it doesn't exist
        if db.user_settings.count_documents({}) == 0:
            db.user_settings.insert_one({
                'theme': 'light',
                'background_type': 'color',
                'background_value': '#fafafa',
                'font_family': 'Inter, sans-serif',
                'font_size': 'medium',
                'created_at': datetime.datetime.now(pytz.timezone('Asia/Kolkata'))
            })
            print("Initialized user settings collection")
            
    except Exception as e:
        print(f"Database initialization error: {e}")

def require_auth(f):
    """Authentication decorator for protected routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_code = request.headers.get('X-Auth-Code')
        if auth_code != os.getenv('AUTH_CODE'):
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated_function

def ping_self():
    """Keep the service alive by pinging itself periodically"""
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
    """Authenticate the user"""
    data = request.json
    auth_code = data.get('authCode')
    if auth_code != os.getenv('AUTH_CODE'):
        return jsonify({'error': 'Invalid authentication code'}), 401
    return jsonify({'message': 'Authentication successful'})

@app.route('/entries', methods=['GET'])
@require_auth
def get_entries():
    """Get all diary entries"""
    try:
        entries = list(db.entries.find({}, {
            '_id': 1, 
            'date': 1, 
            'content': 1, 
            'mood': 1, 
            'weather': 1, 
            'tags': 1, 
            'location': 1,
            'has_images': 1,
            'has_voice': 1,
            'background': 1,
            'color_scheme': 1
        }).sort('created_at', -1))
        
        for entry in entries:
            entry['id'] = str(entry.pop('_id'))
        
        return jsonify(entries)
    except Exception as e:
        print(f"Error fetching entries: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/entries/<entry_id>', methods=['GET'])
@require_auth
def get_entry(entry_id):
    """Get a specific entry with all its details"""
    try:
        entry = db.entries.find_one({'_id': ObjectId(entry_id)})
        if not entry:
            return jsonify({'error': 'Entry not found'}), 404
            
        entry['id'] = str(entry.pop('_id'))
        
        # Get image information if the entry has images
        if entry.get('has_images'):
            image_files = list(db.fs.files.find({"metadata.entry_id": entry_id}))
            entry['images'] = [
                {
                    'id': str(img['_id']),
                    'filename': img['filename'],
                    'content_type': img['contentType'],
                    'upload_date': img['uploadDate']
                } for img in image_files
            ]
            
        # Get voice note information if the entry has voice notes
        if entry.get('has_voice'):
            voice_files = list(db.fs.files.find({"metadata.entry_id": entry_id, "metadata.type": "voice"}))
            entry['voice_notes'] = [
                {
                    'id': str(voice['_id']),
                    'filename': voice['filename'],
                    'content_type': voice['contentType'],
                    'duration': voice.get('metadata', {}).get('duration', 0),
                    'upload_date': voice['uploadDate']
                } for voice in voice_files
            ]
            
        return jsonify(entry)
    except Exception as e:
        print(f"Error fetching entry {entry_id}: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/entries', methods=['POST'])
@require_auth
def add_entry():
    """Add a new diary entry"""
    try:
        data = request.json
        if not data.get('content') or not data.get('date'):
            return jsonify({'error': 'Missing required fields'}), 400

        entry = {
            'date': data['date'],
            'content': data['content'],
            'mood': data.get('mood', ''),
            'weather': data.get('weather', ''),
            'tags': data.get('tags', []),
            'location': data.get('location', ''),
            'has_images': False,
            'has_voice': False,
            'background': data.get('background', ''),
            'color_scheme': data.get('color_scheme', ''),
            'created_at': datetime.datetime.now(pytz.timezone('Asia/Kolkata')),
            'updated_at': datetime.datetime.now(pytz.timezone('Asia/Kolkata'))
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
    """Update an existing diary entry"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No update data provided'}), 400

        update_data = {
            'updated_at': datetime.datetime.now(pytz.timezone('Asia/Kolkata'))
        }
        
        # Add fields that can be updated
        for field in ['content', 'mood', 'weather', 'tags', 'location', 'background', 'color_scheme']:
            if field in data:
                update_data[field] = data[field]

        result = db.entries.update_one(
            {'_id': ObjectId(entry_id)},
            {'$set': update_data}
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
    """Delete a diary entry and its associated files"""
    try:
        # Delete all associated files first
        fs_files = db.fs.files.find({"metadata.entry_id": entry_id})
        for file in fs_files:
            fs.delete(file['_id'])
        
        # Delete the entry
        result = db.entries.delete_one({'_id': ObjectId(entry_id)})
        
        if result.deleted_count == 0:
            return jsonify({'error': 'Entry not found'}), 404

        return jsonify({'message': 'Entry deleted successfully'})
    except Exception as e:
        print(f"Error deleting entry: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/entries/<entry_id>/images', methods=['POST'])
@require_auth
def upload_image(entry_id):
    """Upload an image for a diary entry"""
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image file provided'}), 400
            
        file = request.files['image']
        if not file.filename:
            return jsonify({'error': 'No image file selected'}), 400
            
        # Validate file size (10MB limit)
        file_data = file.read()
        if len(file_data) > 10 * 1024 * 1024:  # 10MB
            return jsonify({'error': 'Image size exceeds 10MB limit'}), 400
            
        # Validate file type
        content_type = file.content_type
        if not content_type.startswith('image/'):
            return jsonify({'error': 'File must be an image'}), 400
            
        # Generate a unique filename
        filename = f"{uuid.uuid4()}-{file.filename}"
        
        # Store the file in GridFS
        file_id = fs.put(
            file_data, 
            filename=filename, 
            contentType=content_type,
            metadata={
                'entry_id': entry_id,
                'type': 'image',
                'upload_date': datetime.datetime.now(pytz.timezone('Asia/Kolkata'))
            }
        )
        
        # Update the entry to indicate it has images
        db.entries.update_one(
            {'_id': ObjectId(entry_id)},
            {'$set': {'has_images': True}}
        )
        
        return jsonify({
            'message': 'Image uploaded successfully',
            'image_id': str(file_id),
            'filename': filename
        })
    except Exception as e:
        print(f"Error uploading image: {e}")
        return jsonify({'error': 'Server error'}), 500

@app.route('/entries/<entry_id>/voice', methods=['POST'])
@require_auth
def upload_voice(entry_id):
    """Upload a voice note for a diary entry"""
    try:
        if 'voice' not in request.files:
            return jsonify({'error': 'No voice file provided'}), 400
            
        file = request.files['voice']
        if not file.filename:
            return jsonify({'error': 'No voice file selected'}), 400
            
        # Validate file size (10MB limit)
        file_data = file.read()
        if len(file_data) > 10 * 1024 * 1024:  # 10MB
            return jsonify({'error': 'Voice note size exceeds 10MB limit'}), 400
            
        # Validate file type
        content_type = file.content_type
        if not content_type.startswith('audio/'):
            return jsonify({'error': 'File must be an audio recording'}), 400
            
        # Generate a unique filename
        filename = f"{uuid.uuid4()}-{file.filename}"
        
        # Get duration from request if available
        duration = request.form.get('duration', 0)
        
        # Store the file in GridFS
        file_id = fs.put(
            file_data, 
            filename=filename, 
            contentType=content_type,
            metadata={
                'entry_id': entry_id,
                'type': 'voice',
                'duration': duration,
                'upload_date': datetime.datetime.now(pytz.timezone('Asia/Kolkata'))
            }
        )
        
        # Update the entry to indicate it has voice notes
        db.entries.update_one(
            {'_id': ObjectId(entry_id)},
            {'$set': {'has_voice': True}}
        )
        
        return jsonify({
            'message': 'Voice note uploaded successfully',
            'voice_id': str(file_id),
            'filename': filename
        })
    except Exception as e:
        print(f"Error uploading voice note: {e}")
        return jsonify({'error': 'Server error'}), 500

@app.route('/files/<file_id>', methods=['GET'])
@require_auth
def get_file(file_id):
    """Retrieve a file (image or voice note) from GridFS"""
    try:
        # Retrieve the file from GridFS
        if not ObjectId.is_valid(file_id):
            return jsonify({'error': 'Invalid file ID'}), 400
            
        file = fs.get(ObjectId(file_id))
        if not file:
            return jsonify({'error': 'File not found'}), 404
            
        # Create a response with the file data
        response = send_file(
            io.BytesIO(file.read()),
            mimetype=file.content_type,
            as_attachment=True,
            download_name=file.filename
        )
        
        return response
    except Exception as e:
        print(f"Error retrieving file: {e}")
        return jsonify({'error': 'Server error'}), 500

@app.route('/files/<file_id>', methods=['DELETE'])
@require_auth
def delete_file(file_id):
    """Delete a file from GridFS"""
    try:
        if not ObjectId.is_valid(file_id):
            return jsonify({'error': 'Invalid file ID'}), 400
            
        # Get file info before deletion to update entry if needed
        file_info = db.fs.files.find_one({'_id': ObjectId(file_id)})
        if not file_info:
            return jsonify({'error': 'File not found'}), 404
            
        # Delete the file
        fs.delete(ObjectId(file_id))
        
        # Check if this was the last file of its type for the entry
        entry_id = file_info.get('metadata', {}).get('entry_id')
        file_type = file_info.get('metadata', {}).get('type')
        
        if entry_id and file_type:
            # Count remaining files of this type for the entry
            remaining_count = db.fs.files.count_documents({
                "metadata.entry_id": entry_id,
                "metadata.type": file_type
            })
            
            # Update entry if no files of this type remain
            if remaining_count == 0:
                update_field = 'has_images' if file_type == 'image' else 'has_voice'
                db.entries.update_one(
                    {'_id': ObjectId(entry_id)},
                    {'$set': {update_field: False}}
                )
        
        return jsonify({'message': 'File deleted successfully'})
        except Exception as e:
            print(f"Error deleting file: {e}")
            return jsonify({'error': 'Server error'}), 500

@app.route('/visitors', methods=['GET'])
@require_auth
def get_visitors():
    """Get the current visitor count"""
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
    """Increment the visitor count"""
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

@app.route('/settings', methods=['GET'])
@require_auth
def get_settings():
    """Get user settings"""
    try:
        settings = db.user_settings.find_one({}, {'_id': 0})
        if not settings:
            # Create default settings if none exist
            settings = {
                'theme': 'light',
                'background_type': 'color',
                'background_value': '#fafafa',
                'font_family': 'Inter, sans-serif',
                'font_size': 'medium'
            }
            db.user_settings.insert_one(settings)
        
        return jsonify(settings)
    except Exception as e:
        print(f"Error fetching settings: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/settings', methods=['PUT'])
@require_auth
def update_settings():
    """Update user settings"""
    try:
        data = request.json
        if not data:
            return jsonify({'error': 'No settings provided'}), 400
            
        # Validate settings
        valid_fields = [
            'theme', 'background_type', 'background_value', 
            'font_family', 'font_size', 'accent_color'
        ]
        
        update_data = {
            'updated_at': datetime.datetime.now(pytz.timezone('Asia/Kolkata'))
        }
        
        for field in valid_fields:
            if field in data:
                update_data[field] = data[field]
                
        db.user_settings.update_one(
            {},
            {'$set': update_data},
            upsert=True
        )
        
        return jsonify({'message': 'Settings updated successfully'})
    except Exception as e:
        print(f"Error updating settings: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/settings/background', methods=['POST'])
@require_auth
def upload_background():
    """Upload a custom background image"""
    try:
        if 'background' not in request.files:
            return jsonify({'error': 'No background file provided'}), 400
            
        file = request.files['background']
        if not file.filename:
            return jsonify({'error': 'No background file selected'}), 400
            
        # Validate file size (10MB limit)
        file_data = file.read()
        if len(file_data) > 10 * 1024 * 1024:  # 10MB
            return jsonify({'error': 'Background size exceeds 10MB limit'}), 400
            
        # Validate file type
        content_type = file.content_type
        if not content_type.startswith('image/'):
            return jsonify({'error': 'File must be an image'}), 400
            
        # Delete any existing background
        existing_backgrounds = db.fs.files.find({"metadata.type": "background"})
        for bg in existing_backgrounds:
            fs.delete(bg['_id'])
            
        # Generate a unique filename
        filename = f"background-{uuid.uuid4()}{os.path.splitext(file.filename)[1]}"
        
        # Store the file in GridFS
        file_id = fs.put(
            file_data, 
            filename=filename, 
            contentType=content_type,
            metadata={
                'type': 'background',
                'upload_date': datetime.datetime.now(pytz.timezone('Asia/Kolkata'))
            }
        )
        
        # Update settings
        db.user_settings.update_one(
            {},
            {'$set': {
                'background_type': 'image',
                'background_value': str(file_id),
                'updated_at': datetime.datetime.now(pytz.timezone('Asia/Kolkata'))
            }},
            upsert=True
        )
        
        return jsonify({
            'message': 'Background uploaded successfully',
            'background_id': str(file_id)
        })
    except Exception as e:
        print(f"Error uploading background: {e}")
        return jsonify({'error': 'Server error'}), 500

@app.route('/tags', methods=['GET'])
@require_auth
def get_tags():
    """Get all unique tags used in entries"""
    try:
        # Aggregate all tags from entries
        pipeline = [
            {"$unwind": "$tags"},
            {"$group": {"_id": "$tags"}},
            {"$sort": {"_id": 1}}
        ]
        
        tags_cursor = db.entries.aggregate(pipeline)
        tags = [doc["_id"] for doc in tags_cursor]
        
        return jsonify(tags)
    except Exception as e:
        print(f"Error fetching tags: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/entries/search', methods=['GET'])
@require_auth
def search_entries():
    """Search entries by query text, tags, mood, or date range"""
    try:
        query = request.args.get('q', '')
        tags = request.args.getlist('tags')
        mood = request.args.get('mood')
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        
        # Build the search query
        search_query = {}
        
        if query:
            search_query['$or'] = [
                {'content': {'$regex': query, '$options': 'i'}},
                {'location': {'$regex': query, '$options': 'i'}}
            ]
            
        if tags:
            search_query['tags'] = {'$in': tags}
            
        if mood:
            search_query['mood'] = mood
            
        date_query = {}
        if start_date:
            date_query['$gte'] = start_date
        if end_date:
            date_query['$lte'] = end_date
            
        if date_query:
            search_query['date'] = date_query
            
        # Execute the search
        entries = list(db.entries.find(
            search_query,
            {'_id': 1, 'date': 1, 'content': 1, 'mood': 1, 'tags': 1, 'location': 1, 'has_images': 1, 'has_voice': 1}
        ).sort('created_at', -1))
        
        for entry in entries:
            entry['id'] = str(entry.pop('_id'))
            
        return jsonify(entries)
    except Exception as e:
        print(f"Error searching entries: {e}")
        return jsonify({'error': 'Database error'}), 500

@app.route('/stats', methods=['GET'])
@require_auth
def get_stats():
    """Get diary usage statistics"""
    try:
        total_entries = db.entries.count_documents({})
        
        # Count entries with images
        entries_with_images = db.entries.count_documents({'has_images': True})
        
        # Count entries with voice notes
        entries_with_voice = db.entries.count_documents({'has_voice': True})
        
        # Count total words in all entries
        pipeline = [
            {
                "$project": {
                    "word_count": {
                        "$size": {
                            "$split": ["$content", " "]
                        }
                    }
                }
            },
            {
                "$group": {
                    "_id": None,
                    "total_words": {"$sum": "$word_count"}
                }
            }
        ]
        
        word_count_result = list(db.entries.aggregate(pipeline))
        total_words = word_count_result[0]['total_words'] if word_count_result else 0
        
        # Get most used tags
        tags_pipeline = [
            {"$unwind": "$tags"},
            {"$group": {"_id": "$tags", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 5}
        ]
        
        top_tags = list(db.entries.aggregate(tags_pipeline))
        
        # Get mood distribution
        mood_pipeline = [
            {"$match": {"mood": {"$ne": ""}}},
            {"$group": {"_id": "$mood", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        
        mood_distribution = list(db.entries.aggregate(mood_pipeline))
        
        # Get entry count by month
        month_pipeline = [
            {
                "$project": {
                    "month": {"$substr": ["$date", 0, 7]},
                }
            },
            {"$group": {"_id": "$month", "count": {"$sum": 1}}},
            {"$sort": {"_id": 1}}
        ]
        
        entries_by_month = list(db.entries.aggregate(month_pipeline))
        
        return jsonify({
            'total_entries': total_entries,
            'entries_with_images': entries_with_images,
            'entries_with_voice': entries_with_voice,
            'total_words': total_words,
            'top_tags': top_tags,
            'mood_distribution': mood_distribution,
            'entries_by_month': entries_by_month
        })
    except Exception as e:
        print(f"Error fetching stats: {e}")
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
