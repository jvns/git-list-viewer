#!/usr/bin/env python3

import os
from flask import Flask, render_template, request
from mbox_handler import get_thread_messages
from search import search

app = Flask(__name__)

DB_PATH = os.environ.get('EMAIL_DB_PATH', 'emails.db')
REPO_PATH = os.environ.get('GIT_REPO_PATH', os.path.expanduser('~/clones/1.git'))

@app.route("/")
def index():
    search_query = request.args.get('search', '').strip()
    threads = search(DB_PATH, REPO_PATH, search_query if search_query else None)
    return render_template("index.html", threads=threads)

@app.route("/<path:message_id>/")
def view_message_by_id(message_id):
    """View message thread by Message-ID from lore.kernel.org"""
    messages = get_thread_messages(message_id)

    if not messages:
        return f"Could not download thread for message ID {message_id}", 404

    return render_template(
        "thread.html",
        messages=messages,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
