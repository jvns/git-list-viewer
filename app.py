#!/usr/bin/env python3

import subprocess
import re
import email
from email.header import decode_header
from datetime import datetime
import hashlib
from flask import Flask, render_template, request, jsonify
import os
import requests
import gzip
import mailbox
from urllib.parse import quote
import sqlite3
import json
from datetime import datetime, timedelta

app = Flask(__name__)

def sanitize_message_id(message_id):
    """Sanitize message ID for use in HTML element IDs"""
    return message_id.replace('<', '').replace('>', '').replace('@', '_at_').replace('.', '_')

# Register the function as a template filter
app.jinja_env.filters['sanitize_message_id'] = sanitize_message_id

def init_db():
    """Initialize SQLite database for caching"""
    conn = sqlite3.connect('mbox_cache.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS mbox_cache (
            message_id TEXT PRIMARY KEY,
            mbox_content TEXT,
            cached_at TIMESTAMP,
            thread_data TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def get_cached_thread(message_id):
    """Get cached thread data if available and not expired"""
    conn = sqlite3.connect('mbox_cache.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT thread_data, cached_at FROM mbox_cache 
        WHERE message_id = ?
    ''', (message_id,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        thread_data, cached_at = result
        cached_time = datetime.fromisoformat(cached_at)
        
        # Cache expires after 1 hour
        if datetime.now() - cached_time < timedelta(hours=1):
            return json.loads(thread_data)
    
    return None

def cache_thread(message_id, mbox_content, messages):
    """Cache thread data in SQLite"""
    conn = sqlite3.connect('mbox_cache.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT OR REPLACE INTO mbox_cache 
        (message_id, mbox_content, cached_at, thread_data)
        VALUES (?, ?, ?, ?)
    ''', (
        message_id,
        mbox_content,
        datetime.now().isoformat(),
        json.dumps(messages)
    ))
    
    conn.commit()
    conn.close()

# Initialize database on startup
init_db()

def get_git_log():
    """Get recent commits from the git repository"""
    cmd = ["git", "-C", REPO_PATH, "log", "--format=%H|%s|%an|%ae|%ad", "--date=iso", "-30"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    commits = []
    
    for line in result.stdout.strip().split('\n'):
        if line:
            parts = line.split('|', 4)
            if len(parts) == 5:
                commit_hash, subject, author_name, author_email, date = parts
                commits.append({
                    'hash': commit_hash,
                    'subject': subject,
                    'author_name': author_name,
                    'author_email': author_email,
                    'date': date,
                    'thread_id': extract_thread_id(subject)
                })
    
    return commits

def extract_thread_id(subject):
    """Extract thread ID from subject line"""
    # Remove Re: and [PATCH] prefixes and use remaining text as thread ID
    clean_subject = re.sub(r'^(Re:\s*)+', '', subject, flags=re.IGNORECASE)
    clean_subject = re.sub(r'^\[PATCH[^\]]*\]\s*', '', clean_subject)
    clean_subject = re.sub(r'^\[RFC[^\]]*\]\s*', '', clean_subject)
    return hashlib.md5(clean_subject.encode()).hexdigest()[:8]

def get_commit_content(commit_hash):
    """Get the full content of a commit"""
    cmd = ["git", "-C", REPO_PATH, "show", "--format=full", commit_hash]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout

def parse_email_content(content):
    """Parse git commit content to extract email parts"""
    lines = content.split('\n')
    
    # Find the start of the email content (after the git headers)
    email_start = 0
    for i, line in enumerate(lines):
        if line.strip() == '' and i > 0:
            email_start = i + 1
            break
    
    email_content = '\n'.join(lines[email_start:])
    
    try:
        msg = email.message_from_string(email_content)
        
        subject = msg.get('Subject', 'No Subject')
        from_header = msg.get('From', 'Unknown')
        date_header = msg.get('Date', '')
        message_id = msg.get('Message-ID', '')
        in_reply_to = msg.get('In-Reply-To', '')
        
        # Get body
        if msg.is_multipart():
            body = ''
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    body += part.get_payload(decode=True).decode('utf-8', errors='ignore')
        else:
            body = msg.get_payload(decode=True)
            if body:
                body = body.decode('utf-8', errors='ignore')
            else:
                body = msg.get_payload()
        
        return {
            'subject': subject,
            'from': from_header,
            'date': date_header,
            'message_id': message_id,
            'in_reply_to': in_reply_to,
            'body': body
        }
    except Exception as e:
        return {
            'subject': 'Parse Error',
            'from': 'Unknown',
            'date': '',
            'message_id': '',
            'in_reply_to': '',
            'body': f'Error parsing email: {str(e)}\n\nRaw content:\n{email_content}'
        }

def group_by_threads(commits):
    """Group commits by thread"""
    threads = {}
    
    for commit in commits:
        thread_id = commit['thread_id']
        if thread_id not in threads:
            threads[thread_id] = []
        threads[thread_id].append(commit)
    
    # Sort each thread by date
    for thread_id in threads:
        threads[thread_id].sort(key=lambda x: x['date'])
    
    return threads

@app.route('/')
def index():
    commits = get_git_log()
    threads = group_by_threads(commits)
    
    # Sort threads by latest message date
    sorted_threads = sorted(threads.items(), 
                          key=lambda x: max(commit['date'] for commit in x[1]), 
                          reverse=True)
    
    return render_template('index.html', threads=sorted_threads)

def download_mbox_thread(message_id):
    """Download mbox file for a thread from lore.kernel.org"""
    encoded_id = quote(message_id, safe='')
    url = f"https://lore.kernel.org/all/{encoded_id}/t.mbox.gz"
    
    try:
        headers = {'User-Agent': 'curl/7.68.0'}
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Decompress the gzip content
        mbox_content = gzip.decompress(response.content)
        return mbox_content.decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Error downloading mbox: {e}")
        return None

def parse_mbox_content(mbox_content):
    """Parse mbox content into email messages"""
    messages = []
    
    try:
        # Write to a temporary file since mbox needs a file path
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.mbox', delete=False) as temp_file:
            temp_file.write(mbox_content)
            temp_file_path = temp_file.name
        
        mbox = mailbox.mbox(temp_file_path)
        
        for message in mbox:
            msg_data = {
                'subject': message.get('Subject', 'No Subject'),
                'from': message.get('From', 'Unknown'),
                'date': message.get('Date', ''),
                'message_id': message.get('Message-ID', ''),
                'in_reply_to': message.get('In-Reply-To', ''),
                'references': message.get('References', ''),
            }
            
            # Get body
            if message.is_multipart():
                body = ''
                for part in message.walk():
                    if part.get_content_type() == 'text/plain':
                        try:
                            body += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                        except:
                            body += str(part.get_payload())
            else:
                try:
                    payload = message.get_payload(decode=True)
                    if payload:
                        body = payload.decode('utf-8', errors='ignore')
                    else:
                        body = str(message.get_payload())
                except:
                    body = str(message.get_payload())
            
            msg_data['body'] = body
            messages.append(msg_data)
        
        # Clean up temporary file
        os.unlink(temp_file_path)
            
    except Exception as e:
        print(f"Error parsing mbox: {e}")
        return []
    
    return messages

def build_thread_tree(messages):
    """Build nested thread structure from email messages"""
    # Create a dict for quick lookup by message ID
    msg_dict = {}
    subject_dict = {}  # For subject-based threading fallback
    
    for msg in messages:
        msg_id = msg.get('message_id', '').strip('<>')
        if msg_id:
            msg_dict[msg_id] = msg
            msg['children'] = []
            msg['level'] = 0
            msg['parent'] = None
            
        # Also index by normalized subject for fallback threading
        subject = msg.get('subject', '').strip()
        # Remove Re:, Fwd:, etc. and normalize
        normalized_subject = re.sub(r'^(Re|Fwd|Fw):\s*', '', subject, flags=re.IGNORECASE).strip()
        if normalized_subject:
            if normalized_subject not in subject_dict:
                subject_dict[normalized_subject] = []
            subject_dict[normalized_subject].append(msg)
    
    # Build the tree structure using In-Reply-To headers
    root_messages = []
    
    for msg in messages:
        msg_id = msg.get('message_id', '').strip('<>')
        in_reply_to = msg.get('in_reply_to', '').strip('<>')
        
        if in_reply_to and in_reply_to in msg_dict:
            # This is a reply to another message
            parent = msg_dict[in_reply_to]
            parent['children'].append(msg)
            msg['level'] = parent['level'] + 1
            msg['parent'] = parent
        else:
            # Check if this is a subject-based reply
            subject = msg.get('subject', '').strip()
            if subject.lower().startswith('re:'):
                # This looks like a reply, try to find parent by subject
                normalized_subject = re.sub(r'^(Re|Fwd|Fw):\s*', '', subject, flags=re.IGNORECASE).strip()
                if normalized_subject in subject_dict:
                    # Find the earliest message with this subject as potential parent
                    potential_parents = [m for m in subject_dict[normalized_subject] 
                                       if not m.get('subject', '').lower().startswith('re:')]
                    if potential_parents:
                        parent = potential_parents[0]  # Take the first non-reply message
                        parent['children'].append(msg)
                        msg['level'] = parent['level'] + 1
                        msg['parent'] = parent
                        continue
            
            # This is a root message (no parent found)
            root_messages.append(msg)
    
    # Flatten the tree for display while preserving hierarchy
    def flatten_tree(messages, result=None):
        if result is None:
            result = []
        
        for msg in messages:
            result.append(msg)
            if msg.get('children'):
                flatten_tree(msg['children'], result)
        
        return result
    
    # Add display_subject logic
    def should_hide_subject(msg):
        if not msg.get('parent'):
            return False
        
        parent_subject = msg['parent'].get('subject', '').strip()
        current_subject = msg.get('subject', '').strip()
        
        # Remove Re:, Fwd:, etc. and normalize both
        parent_normalized = re.sub(r'^(Re|Fwd|Fw):\s*', '', parent_subject, flags=re.IGNORECASE).strip()
        current_normalized = re.sub(r'^(Re|Fwd|Fw):\s*', '', current_subject, flags=re.IGNORECASE).strip()
        
        # Hide if parent subject is a subset of current subject
        return parent_normalized and parent_normalized in current_normalized
    
    # Get the flattened result first
    flattened_messages = flatten_tree(root_messages)
    
    # Set display_subject for each message first (while parent refs still exist)
    for msg in flattened_messages:
        if not msg.get('parent'):
            msg['display_subject'] = msg.get('subject', '')
        else:
            parent_subject = msg['parent'].get('subject', '').strip()
            current_subject = msg.get('subject', '').strip()
            
            # Remove Re:, Fwd:, etc. and normalize both
            parent_normalized = re.sub(r'^(Re|Fwd|Fw):\s*', '', parent_subject, flags=re.IGNORECASE).strip()
            current_normalized = re.sub(r'^(Re|Fwd|Fw):\s*', '', current_subject, flags=re.IGNORECASE).strip()
            
            # Hide if parent subject is a subset of current subject
            if parent_normalized and parent_normalized in current_normalized:
                print(f"HIDING: Parent '{parent_normalized}' found in '{current_normalized}'")
                msg['display_subject'] = ''
            else:
                print(f"SHOWING: Parent '{parent_normalized}' NOT in '{current_normalized}'")
                msg['display_subject'] = current_subject
    
    # Clean up parent references to avoid circular reference in JSON serialization
    for msg in flattened_messages:
        if 'parent' in msg:
            del msg['parent']
    
    return flattened_messages

@app.route('/commit/<commit_hash>')
def view_commit(commit_hash):
    content = get_commit_content(commit_hash)
    email_data = parse_email_content(content)
    return jsonify(email_data)

@app.route('/<path:message_id>/')
def view_message_by_id(message_id):
    """View message thread by Message-ID from lore.kernel.org"""
    # Check cache first
    cached_messages = get_cached_thread(message_id)
    
    if cached_messages:
        messages = cached_messages
    else:
        # Download and parse if not cached
        mbox_content = download_mbox_thread(message_id)
        
        if not mbox_content:
            return f"Could not download thread for message ID {message_id}", 404
        
        messages = parse_mbox_content(mbox_content)
        
        if not messages:
            return f"No messages found in thread for {message_id}", 404
        
        # Cache the results
        cache_thread(message_id, mbox_content, messages)
    
    # Build threaded structure
    threaded_messages = build_thread_tree(messages)
    
    # Find the specific message or show the first one
    target_message = None
    for msg in threaded_messages:
        if message_id in msg.get('message_id', ''):
            target_message = msg
            break
    
    if not target_message:
        target_message = threaded_messages[0]
    
    return render_template('thread.html', messages=threaded_messages, target_message=target_message, message_id=message_id)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)