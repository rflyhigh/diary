from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import datetime
import threading
import time
import requests
from dotenv import load_dotenv
import sqlite3
from functools import wraps

load_dotenv()

app = Flask(__name__)
CORS(app)

def init_db():
    conn = sqlite3.connect('diary.db')
    c = conn.cursor()
    
    # Create entries table with id column
    c.execute('''
        CREATE TABLE IF NOT EXISTS entries
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         date TEXT NOT NULL,
         content TEXT NOT NULL,
         created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)
    ''')
    
    # Create visitors table
    c.execute('''
        CREATE TABLE IF NOT EXISTS visitors
        (count INTEGER DEFAULT 0)
    ''')
    
    # Initialize visitors count if not exists
    c.execute('INSERT OR IGNORE INTO visitors (rowid, count) VALUES (1, 0)')
    
    conn.commit()
    conn.close()

init_db()

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
            requests.get(os.getenv('APP_URL'))
            time.sleep(840)  # 14 minutes
        except:
            pass

if os.getenv('ENVIRONMENT') == 'production':
    ping_thread = threading.Thread(target=ping_self, daemon=True)
    ping_thread.start()

@app.route('/entries', methods=['GET'])
def get_entries():
    try:
        conn = sqlite3.connect('diary.db')
        c = conn.cursor()
        c.execute('SELECT id, date, content FROM entries ORDER BY created_at DESC')
        entries = [{'id': row[0], 'date': row[1], 'content': row[2]} for row in c.fetchall()]
        conn.close()
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

        conn = sqlite3.connect('diary.db')
        c = conn.cursor()
        c.execute('INSERT INTO entries (date, content) VALUES (?, ?)',
                 (data['date'], data['content']))
        entry_id = c.lastrowid
        conn.commit()
        conn.close()

        return jsonify({
            'message': 'Entry added successfully',
            'id': entry_id
        }), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/entries/<int:entry_id>', methods=['PUT'])
@require_auth
def update_entry(entry_id):
    try:
        data = request.json
        if not data.get('content'):
            return jsonify({'error': 'Content is required'}), 400

        conn = sqlite3.connect('diary.db')
        c = conn.cursor()
        
        # Check if entry exists
        c.execute('SELECT id FROM entries WHERE id = ?', (entry_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Entry not found'}), 404

        # Update entry
        c.execute('UPDATE entries SET content = ? WHERE id = ?',
                 (data['content'], entry_id))
        conn.commit()
        conn.close()

        return jsonify({'message': 'Entry updated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/entries/<int:entry_id>', methods=['DELETE'])
@require_auth
def delete_entry(entry_id):
    try:
        conn = sqlite3.connect('diary.db')
        c = conn.cursor()
        
        # Check if entry exists
        c.execute('SELECT id FROM entries WHERE id = ?', (entry_id,))
        if not c.fetchone():
            conn.close()
            return jsonify({'error': 'Entry not found'}), 404

        # Delete entry
        c.execute('DELETE FROM entries WHERE id = ?', (entry_id,))
        conn.commit()
        conn.close()

        return jsonify({'message': 'Entry deleted successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/visitors', methods=['GET'])
def get_visitors():
    try:
        conn = sqlite3.connect('diary.db')
        c = conn.cursor()
        c.execute('SELECT count FROM visitors WHERE rowid = 1')
        count = c.fetchone()[0]
        conn.close()
        return jsonify({'count': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/visitors/increment', methods=['POST'])
def increment_visitors():
    try:
        conn = sqlite3.connect('diary.db')
        c = conn.cursor()
        c.execute('UPDATE visitors SET count = count + 1 WHERE rowid = 1')
        conn.commit()
        conn.close()
        return jsonify({'message': 'Visitor count incremented'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Resource not found'}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
