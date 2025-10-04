#!/usr/bin/env python3

import os
from flask import Flask, render_template, redirect, url_for, request
from mbox_handler import get_thread_messages, search, force_refresh_thread

app = Flask(__name__)

@app.route("/")
def index():
    search_query = request.args.get('search', '').strip()
    cached_threads = search(search_query if search_query else None)
    return render_template("index.html", cached_threads=cached_threads)


@app.route("/refresh/<path:message_id>/")
def force_refresh(message_id):
    """Force refresh a specific thread"""
    force_refresh_thread(message_id)
    return redirect(url_for('view_message_by_id', message_id=message_id))


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
