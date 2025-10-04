#!/usr/bin/env python3

import os
import re
from emailindex import EmailIndex
from datetime import datetime


# Configuration - can be moved to environment variable or config file
EMAIL_DB_PATH = os.environ.get('EMAIL_DB_PATH', 'emails.db')
GIT_REPO_PATH = os.environ.get('GIT_REPO_PATH', os.path.expanduser('~/clones/1.git'))


def get_thread_messages(message_id):
    with EmailIndex(EMAIL_DB_PATH, GIT_REPO_PATH) as index:
        containers = index.find_thread(message_id)

        if not containers:
            return None

        # Convert containers to message format expected by the frontend
        messages = []
        _flatten(containers, messages)

        return messages


def _normalize_subject(subject):
    return re.sub(r"^(Re|Fwd|Fw):\s*", "", subject, flags=re.IGNORECASE).strip()


def _display_subject(msg, parent_subject, level):
    display_subject = msg.subject
    if parent_subject and level > 0:
        parent_normalized = _normalize_subject(parent_subject)
        current_normalized = _normalize_subject(msg.subject)
        if parent_normalized and parent_normalized in current_normalized:
            display_subject = ""
    return display_subject

def _flatten(containers, messages, level=0, parent_subject=None):
    for container in containers:
        if hasattr(container, 'message') and container.message:
            msg = container.message
            msg.display_subject = _display_subject(msg, parent_subject, level)
            msg.level = level
            messages.append(msg)

            # Process children, passing current subject as parent
            if hasattr(container, 'children') and container.children:
                _flatten(container.children, messages, level + 1, msg.subject)
        else:
            print('hi')
            # Dummy container - process children with same parent subject
            if hasattr(container, 'children') and container.children:
                _flatten(container.children, messages, level, parent_subject)


def search(search_query=None):
    with EmailIndex(EMAIL_DB_PATH, GIT_REPO_PATH) as index:
        # Get all unique message IDs that have been indexed
        # Build search condition
        search_condition = ""
        search_params = []
        if search_query:
            search_condition = """
                AND (subject LIKE ? OR from_name LIKE ? OR from_addr LIKE ?)
            """
            search_like = f"%{search_query}%"
            search_params = [search_like, search_like, search_like]

        cursor = index.conn.execute(f"""
            WITH filtered_messages AS (
                SELECT message_id, subject, from_name, from_addr, date_sent, root_message_id
                FROM messages
                WHERE (subject NOT LIKE 'Re:%' AND subject NOT LIKE 'RE:%')
                  AND (subject NOT LIKE '% v2 %' AND subject NOT LIKE '% v3 %'
                       AND subject NOT LIKE '% v4 %' AND subject NOT LIKE '% v5 %'
                       AND subject NOT LIKE '% v6 %' AND subject NOT LIKE '% v7 %'
                       AND subject NOT LIKE '% v8 %' AND subject NOT LIKE '% v9 %')
                  {search_condition}
            ),
            ranked_messages AS (
                SELECT message_id, subject, from_name, from_addr, date_sent, root_message_id,
                       ROW_NUMBER() OVER (PARTITION BY root_message_id ORDER BY date_sent ASC) as rn
                FROM filtered_messages
            ),
            thread_counts AS (
                SELECT root_message_id, COUNT(*) as thread_count
                FROM messages
                GROUP BY root_message_id
            )
            SELECT r.message_id, r.subject, r.from_name, r.from_addr, r.date_sent, t.thread_count
            FROM ranked_messages r
            JOIN thread_counts t ON r.root_message_id = t.root_message_id
            WHERE r.rn = 1
            ORDER BY r.date_sent DESC
            LIMIT 100
        """, search_params)

        threads = []
        for row in cursor.fetchall():
            threads.append({
                'message_id': row['message_id'],
                'subject': row['subject'],
                'from': f"{row['from_name']} <{row['from_addr']}>",
                'date': datetime.fromtimestamp(row['date_sent']).strftime('%Y-%m-%d'),
                'message_count': row['thread_count']
            })

        return threads
