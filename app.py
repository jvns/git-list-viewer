#!/usr/bin/env python3

import os
from flask import Flask, render_template
from mbox_handler import get_thread_messages
from thread_tree import build_thread_tree

app = Flask(__name__)

app.jinja_env.filters["sanitize_message_id"] = (
    lambda x: x.replace("<", "").replace(">", "").replace("@", "_at_").replace(".", "_")
)


@app.route("/")
def index():
    return render_template("index.html")


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
