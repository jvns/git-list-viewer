#!/usr/bin/env python3

import os
import re
from flask import Flask, render_template
from mbox_handler import get_thread_messages

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





def normalize_subject(subject):
    """Remove Re:, Fwd:, etc. and normalize subject"""
    return re.sub(r"^(Re|Fwd|Fw):\s*", "", subject, flags=re.IGNORECASE).strip()


def build_message_indexes(messages):
    """Build lookup dictionaries for messages by ID and subject"""
    msg_dict = {}
    subject_dict = {}

    for msg in messages:
        msg_id = msg.get("message_id", "").strip("<>")
        if msg_id:
            msg_dict[msg_id] = msg
            msg["children"] = []
            msg["level"] = 0
            msg["parent"] = None

        # Index by normalized subject for fallback threading
        subject = msg.get("subject", "").strip()
        normalized_subject = normalize_subject(subject)
        if normalized_subject:
            if normalized_subject not in subject_dict:
                subject_dict[normalized_subject] = []
            subject_dict[normalized_subject].append(msg)

    return msg_dict, subject_dict


def link_replies_by_headers(messages, msg_dict):
    """Link replies using In-Reply-To headers"""
    root_messages = []

    for msg in messages:
        in_reply_to = msg.get("in_reply_to", "").strip("<>")

        if in_reply_to and in_reply_to in msg_dict:
            parent = msg_dict[in_reply_to]
            parent["children"].append(msg)
            msg["level"] = parent["level"] + 1
            msg["parent"] = parent
        else:
            root_messages.append(msg)

    return root_messages


def link_replies_by_subject(root_messages, subject_dict):
    """Try to link remaining root messages by subject"""
    final_roots = []

    for msg in root_messages:
        subject = msg.get("subject", "").strip()
        
        if subject.lower().startswith("re:"):
            normalized_subject = normalize_subject(subject)
            if normalized_subject in subject_dict:
                # Find potential parents (non-reply messages)
                potential_parents = [
                    m for m in subject_dict[normalized_subject]
                    if not m.get("subject", "").lower().startswith("re:")
                ]
                if potential_parents:
                    parent = potential_parents[0]
                    parent["children"].append(msg)
                    msg["level"] = parent["level"] + 1
                    msg["parent"] = parent
                    continue

        final_roots.append(msg)

    return final_roots


def flatten_tree(messages):
    """Flatten tree structure while preserving hierarchy"""
    for msg in messages:
        yield msg
        if msg.get("children"):
            yield from flatten_tree(msg["children"])


def set_display_subjects(messages):
    """Set display_subject for each message, hiding duplicates"""
    for msg in messages:
        if not msg.get("parent"):
            msg["display_subject"] = msg.get("subject", "")
        else:
            parent_subject = msg["parent"].get("subject", "").strip()
            current_subject = msg.get("subject", "").strip()

            parent_normalized = normalize_subject(parent_subject)
            current_normalized = normalize_subject(current_subject)

            # Hide if parent subject is subset of current subject
            if parent_normalized and parent_normalized in current_normalized:
                msg["display_subject"] = ""
            else:
                msg["display_subject"] = current_subject


def cleanup_parent_references(messages):
    """Remove parent references to avoid circular refs in JSON"""
    for msg in messages:
        if "parent" in msg:
            del msg["parent"]


def build_thread_tree(messages):
    """Build nested thread structure from email messages"""
    msg_dict, subject_dict = build_message_indexes(messages)
    root_messages = link_replies_by_headers(messages, msg_dict)
    root_messages = link_replies_by_subject(root_messages, subject_dict)
    flattened_messages = list(flatten_tree(root_messages))
    set_display_subjects(flattened_messages)
    cleanup_parent_references(flattened_messages)
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
    messages = get_thread_messages(message_id)

    if not messages:
        return f"Could not download thread for message ID {message_id}", 404

    # Build threaded structure
    threaded_messages = build_thread_tree(messages)

    return render_template(
        "thread.html",
        messages=threaded_messages,
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
