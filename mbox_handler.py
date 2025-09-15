#!/usr/bin/env python3

import os
import requests
import gzip
import mailbox
import tempfile
import sqlite3
import json
from datetime import datetime, timedelta
from urllib.parse import quote


def download_mbox_thread(message_id):
    """Download mbox file for a thread from lore.kernel.org"""
    encoded_id = quote(message_id, safe="")
    url = f"https://lore.kernel.org/all/{encoded_id}/t.mbox.gz"

    headers = {"User-Agent": "curl/7.68.0"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    # Decompress the gzip content
    mbox_content = gzip.decompress(response.content)
    return mbox_content.decode("utf-8", errors="ignore")


def parse_mbox_content(mbox_content):
    """Parse mbox content into email messages"""
    messages = []

    # Write to a temporary file since mbox needs a file path
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".mbox", delete=False
    ) as temp_file:
        temp_file.write(mbox_content)
        temp_file_path = temp_file.name

    mbox = mailbox.mbox(temp_file_path)

    for message in mbox:
        msg_data = {
            "subject": message.get("Subject", "No Subject"),
            "from": message.get("From", "Unknown"),
            "date": message.get("Date", ""),
            "message_id": message.get("Message-ID", ""),
            "in_reply_to": message.get("In-Reply-To", ""),
            "references": message.get("References", ""),
        }

        # Get body
        if message.is_multipart():
            body = ""
            for part in message.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        body += part.get_payload(decode=True).decode(
                            "utf-8", errors="ignore"
                        )
                    except:
                        body += str(part.get_payload())
        else:
            try:
                payload = message.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="ignore")
                else:
                    body = str(message.get_payload())
            except:
                body = str(message.get_payload())

        msg_data["body"] = body
        messages.append(msg_data)

    # Clean up temporary file
    os.unlink(temp_file_path)


    return messages


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


def get_all_cached_threads():
    """Get all cached threads with basic info"""
    init_db()

    conn = sqlite3.connect("mbox_cache.db")
    cursor = conn.cursor()

    cursor.execute("""
        SELECT message_id, cached_at, thread_data FROM mbox_cache
        ORDER BY cached_at DESC
    """)

    results = cursor.fetchall()
    conn.close()

    threads = []
    for message_id, cached_at, thread_data in results:
        messages = json.loads(thread_data)
        if messages:
            # Get the first message for thread info
            first_msg = messages[0]
            threads.append({
                'message_id': message_id,
                'subject': first_msg.get('subject', 'No Subject'),
                'from': first_msg.get('from', 'Unknown'),
                'date': first_msg.get('date', ''),
                'cached_at': cached_at,
                'message_count': len(messages)
            })

    return threads


def get_thread_messages(message_id):
    """Get thread messages, using cache if available or downloading if needed"""
    # Initialize database if needed
    init_db()

    # Check cache first
    cached_messages = get_cached_thread(message_id)

    if cached_messages:
        return cached_messages

    # Download and parse if not cached
    mbox_content = download_mbox_thread(message_id)

    if not mbox_content:
        return None

    messages = parse_mbox_content(mbox_content)

    if not messages:
        return None

    # Cache the results
    cache_thread(message_id, mbox_content, messages)

    return messages
