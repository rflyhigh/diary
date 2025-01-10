from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import datetime
import threading
import time
import requests
from dotenv import load_dotenv
import sqlite3

load_dotenv()

app = Flask(__name__)
CORS(app)

# Initialize database
def init_db():
    conn = sqlite3.connect('diary.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS entries
        (id INTEGER PRIMARY KEY AUTOINCREMENT,
         date TEXT NOT NULL,
         content TEXT NOT NULL)
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS visitors
        (count INTEGER DEFAULT 0)
    ''')
    c.execute('INSERT OR IGNORE INTO visitors (rowid, count) VALUES (1, 0)')
    conn.commit()
    conn.close()

init_db()

# Authentication middleware
def check_auth_code():
    auth_code = request.headers.get('X-Auth-Code')
    return auth_code == os.getenv('AUTH_CODE')

# Keep-alive functionality
def ping_self():
    while True:
        try:
            requests.get(os.getenv('APP_URL'))
            time.sleep(840)  # 14 minutes
        except:
            pass

# Start ping thread
if os.getenv('ENVIRONMENT') == 'production':
    ping_thread = threading.Thread(target=ping_self, daemon=True)
    ping_thread.start()

@app.route('/entries', methods=['GET'])
def get_entries():
    conn = sqlite3.connect('diary.db')
    c = conn.cursor()
    c.execute('SELECT * FROM entries ORDER BY date DESC')
    entries = [{'id': row[0], 'date': row[1], 'content': row[2]} for row in c.fetchall()]
    conn.close()
    return jsonify(entries)

@app.route('/entries', methods=['POST'])
def add_entry():
    if not check_auth_code():
        return jsonify({'error': 'Unauthorized'}), 401
    
    data = request.json
    conn = sqlite3.connect('diary.db')
    c = conn.cursor()
    c.execute('INSERT INTO entries (date, content) VALUES (?, ?)',
              (data['date'], data['content']))
    conn.commit()
    conn.close()
    return jsonify({'message': 'Entry added successfully'})

@app.route('/visitors', methods=['GET'])
def get_visitors():
    conn = sqlite3.connect('diary.db')
    c = conn.cursor()
    c.execute('SELECT count FROM visitors WHERE rowid = 1')
    count = c.fetchone()[0]
    conn.close()
    return jsonify({'count': count})

@app.route('/visitors/increment', methods=['POST'])
def increment_visitors():
    conn = sqlite3.connect('diary.db')
    c = conn.cursor()
    c.execute('UPDATE visitors SET count = count + 1 WHERE rowid = 1')
    conn.commit()
    conn.close()
    return jsonify({'message': 'Visitor count incremented'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)))
