#!/usr/bin/env python3

import os
import threading
import time
from flask import Flask, render_template, request
from flask_httpauth import HTTPBasicAuth
from emailindex import EmailIndex
from search import search

DB_PATH = os.environ.get('EMAIL_DB_PATH', 'emails.db')
REPO_PATH = os.environ.get('GIT_REPO_PATH', os.path.expanduser('~/clones/1.git'))

app = Flask(__name__)
auth = HTTPBasicAuth()

@auth.verify_password
def verify_password(username, password):
    if os.environ.get('PASSWORD'):
        return password == os.environ.get('PASSWORD')
    return True  # No auth if PASSWORD not set

def background_indexer():
    while True:
        try:
            with EmailIndex(DB_PATH, REPO_PATH) as index:
                index.index_git_repo()
        except Exception as e:
            print(f"Background reindex failed: {e}")

        time.sleep(300)

@app.route("/")
@auth.login_required
def index():
    search_query = request.args.get('search', '').strip()
    threads = search(DB_PATH, REPO_PATH, search_query if search_query else None)
    return render_template("index.html", threads=threads)

@app.route("/<path:message_id>/")
@auth.login_required
def view_message_by_id(message_id):
    with EmailIndex(DB_PATH, REPO_PATH) as index:
        messages = index.find_thread(message_id)

    if not messages:
        return f"Could not find thread for message ID {message_id}", 404

    return render_template(
        "thread.html",
        messages=messages,
    )

# Start background indexer when module is imported (works with both gunicorn and direct execution)
threading.Thread(target=background_indexer, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
