#!/usr/bin/env python3

import os
import re
from emailindex import EmailIndex

# Configuration - can be moved to environment variable or config file
EMAIL_DB_PATH = os.environ.get('EMAIL_DB_PATH', 'emails.db')
GIT_REPO_PATH = os.environ.get('GIT_REPO_PATH', os.path.expanduser('~/clones/1.git'))


def get_thread_messages(message_id):
    with EmailIndex(EMAIL_DB_PATH, GIT_REPO_PATH) as index:
        containers = index.find_thread(message_id)

        if not containers:
            return None
        return list(_flatten(containers))

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

def _flatten(containers, level=0, parent_subject=None):
    for container in containers:
        if hasattr(container, 'message'):
            msg = container.message
            msg.display_subject = _display_subject(msg, parent_subject, level)
            msg.level = level
            yield msg

            # Process children, passing current subject as parent
            if hasattr(container, 'children') and container.children:
                yield from _flatten(container.children, level + 1, msg.subject)
        else:
            # Dummy container - process children with same parent subject
            if hasattr(container, 'children') and container.children:
                yield from _flatten(container.children, level, parent_subject)

