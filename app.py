#!/usr/bin/env python3

import os
import re
from datetime import datetime, timedelta
from flask import Flask, render_template
import sqlite3
import json
from mbox_handler import download_mbox_thread, parse_mbox_content

app = Flask(__name__)


def sanitize_message_id(message_id):
    """Sanitize message ID for use in HTML element IDs"""
    return (
        message_id.replace("<", "")
        .replace(">", "")
        .replace("@", "_at_")
        .replace(".", "_")
    )


# Register the function as a template filter
app.jinja_env.filters["sanitize_message_id"] = sanitize_message_id


def init_db():
    """Initialize SQLite database for caching"""
    conn = sqlite3.connect("mbox_cache.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS mbox_cache (
            message_id TEXT PRIMARY KEY,
            mbox_content TEXT,
            cached_at TIMESTAMP,
            thread_data TEXT
        )
    """
    )

    conn.commit()
    conn.close()


def get_cached_thread(message_id):
    """Get cached thread data if available and not expired"""
    conn = sqlite3.connect("mbox_cache.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT thread_data, cached_at FROM mbox_cache
        WHERE message_id = ?
    """,
        (message_id,),
    )

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
    conn = sqlite3.connect("mbox_cache.db")
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT OR REPLACE INTO mbox_cache
        (message_id, mbox_content, cached_at, thread_data)
        VALUES (?, ?, ?, ?)
    """,
        (message_id, mbox_content, datetime.now().isoformat(), json.dumps(messages)),
    )

    conn.commit()
    conn.close()


# Initialize database on startup
init_db()



def build_thread_tree(messages):
    """Build nested thread structure from email messages"""
    # Create a dict for quick lookup by message ID
    msg_dict = {}
    subject_dict = {}  # For subject-based threading fallback

    for msg in messages:
        msg_id = msg.get("message_id", "").strip("<>")
        if msg_id:
            msg_dict[msg_id] = msg
            msg["children"] = []
            msg["level"] = 0
            msg["parent"] = None

        # Also index by normalized subject for fallback threading
        subject = msg.get("subject", "").strip()
        # Remove Re:, Fwd:, etc. and normalize
        normalized_subject = re.sub(
            r"^(Re|Fwd|Fw):\s*", "", subject, flags=re.IGNORECASE
        ).strip()
        if normalized_subject:
            if normalized_subject not in subject_dict:
                subject_dict[normalized_subject] = []
            subject_dict[normalized_subject].append(msg)

    # Build the tree structure using In-Reply-To headers
    root_messages = []

    for msg in messages:
        msg_id = msg.get("message_id", "").strip("<>")
        in_reply_to = msg.get("in_reply_to", "").strip("<>")

        if in_reply_to and in_reply_to in msg_dict:
            # This is a reply to another message
            parent = msg_dict[in_reply_to]
            parent["children"].append(msg)
            msg["level"] = parent["level"] + 1
            msg["parent"] = parent
        else:
            # Check if this is a subject-based reply
            subject = msg.get("subject", "").strip()
            if subject.lower().startswith("re:"):
                # This looks like a reply, try to find parent by subject
                normalized_subject = re.sub(
                    r"^(Re|Fwd|Fw):\s*", "", subject, flags=re.IGNORECASE
                ).strip()
                if normalized_subject in subject_dict:
                    # Find the earliest message with this subject as potential parent
                    potential_parents = [
                        m
                        for m in subject_dict[normalized_subject]
                        if not m.get("subject", "").lower().startswith("re:")
                    ]
                    if potential_parents:
                        parent = potential_parents[
                            0
                        ]  # Take the first non-reply message
                        parent["children"].append(msg)
                        msg["level"] = parent["level"] + 1
                        msg["parent"] = parent
                        continue

            # This is a root message (no parent found)
            root_messages.append(msg)

    # Flatten the tree for display while preserving hierarchy
    def flatten_tree(messages, result=None):
        if result is None:
            result = []

        for msg in messages:
            result.append(msg)
            if msg.get("children"):
                flatten_tree(msg["children"], result)

        return result

    flattened_messages = flatten_tree(root_messages)

    # Set display_subject for each message first (while parent refs still exist)
    for msg in flattened_messages:
        if not msg.get("parent"):
            msg["display_subject"] = msg.get("subject", "")
        else:
            parent_subject = msg["parent"].get("subject", "").strip()
            current_subject = msg.get("subject", "").strip()

            # Remove Re:, Fwd:, etc. and normalize both
            parent_normalized = re.sub(
                r"^(Re|Fwd|Fw):\s*", "", parent_subject, flags=re.IGNORECASE
            ).strip()
            current_normalized = re.sub(
                r"^(Re|Fwd|Fw):\s*", "", current_subject, flags=re.IGNORECASE
            ).strip()

            # Hide if parent subject is a subset of current subject
            if parent_normalized and parent_normalized in current_normalized:
                msg["display_subject"] = ""
            else:
                msg["display_subject"] = current_subject

    # Clean up parent references to avoid circular reference in JSON serialization
    for msg in flattened_messages:
        if "parent" in msg:
            del msg["parent"]

    return flattened_messages


@app.route("/")
def index():
    """Simple info page since no homepage needed"""
    return """
    <html><body>
    <h1>Git Mailing List Viewer</h1>
    <p>Access threads directly by message ID: <code>/{message_id}/</code></p>
    <p>Example: <code>/20231201120000.12345@example.com/</code></p>
    </body></html>
    """


@app.route("/<path:message_id>/")
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

    return render_template(
        "thread.html",
        messages=threaded_messages,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
