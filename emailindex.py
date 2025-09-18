#!/usr/bin/env python3
import sqlite3
import email
import email.utils
import email.policy
import re
import argparse
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass
from pathlib import Path
import logging
import pygit2
from jwz_threading import thread

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EmailMessage:
    def __init__(self, raw_email: bytes):
        self._email = email.message_from_bytes(raw_email, policy=email.policy.default)

    @property
    def message_id(self) -> str:
        return str(self._email.get("Message-ID")).strip().strip("<>")

    @property
    def subject(self) -> str:
        return str(self._email.get("Subject"))

    @property
    def from_name(self) -> str:
        from_header = str(self._email.get("From", ""))
        name, _ = email.utils.parseaddr(from_header)
        return name

    @property
    def from_addr(self) -> str:
        from_header = str(self._email.get("From", ""))
        _, addr = email.utils.parseaddr(from_header)
        return addr

    @property
    def references(self) -> List[str]:
        refs = str(self._email.get("References", ""))
        in_reply_to = str(self._email.get("In-Reply-To", ""))
        all_refs = f"{refs} {in_reply_to}"
        return re.findall(r"<([^>]+)>", all_refs)

    @property
    def date(self) -> datetime:
        date_str = str(self._email.get("Date", ""))
        time_tuple = email.utils.parsedate_tz(date_str)
        timestamp = email.utils.mktime_tz(time_tuple)
        return datetime.fromtimestamp(timestamp)

    @property
    def body(self) -> str:
        payload = self._email.get_payload(decode=True)
        if payload:
            return payload.decode("utf-8", errors="ignore")
        else:
            return str(self._email.get_payload())

    @classmethod
    def from_oid(cls, git_oid, repo):
        """Create EmailMessage from git object ID"""
        blob = repo[git_oid]
        return cls(blob.data)


class EmailIndex:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                subject TEXT,
                from_addr TEXT,
                from_name TEXT,
                date_sent INTEGER,
                git_oid TEXT,
                root_message_id TEXT
            )
        """
        )

        self.conn.commit()

    def index_git_repo(self, repo_path: str, branch: str = "refs/heads/master"):
        repo = pygit2.Repository(repo_path)

        # Collect all commits first for reverse topological order
        commit = repo.references[branch].peel(pygit2.Commit)
        commits = list(repo.walk(commit.id, pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_REVERSE))

        # Dictionary to track message_id -> root_message_id mappings
        msg_root_mapping = {}

        count = 0
        for commit in commits:
            for entry in commit.tree:
                if entry.type == pygit2.GIT_OBJECT_BLOB:
                    blob = repo[entry.id]
                    self._add_message_to_db(blob, str(entry.id), msg_root_mapping, repo)
                    count += 1
                    if count % 100 == 0:
                        logger.info(f"Indexed {count} messages...")

        self.conn.commit()

    def _add_message_to_db(self, blob, git_oid, msg_root_mapping, repo):
        raw_email = blob.data
        if not (b"Message-ID:" in raw_email or b"From:" in raw_email):
            return

        msg = EmailMessage.from_oid(git_oid, repo)
        if not msg.message_id:
            return

        # Calculate root message ID using single-hop lookup
        if not msg.references:
            # No references = thread starter
            root_message_id = msg.message_id
        else:
            # Has references - look up the root of the first reference
            first_ref = msg.references[0]
            if first_ref in msg_root_mapping:
                # Single hop: use the already-calculated root of the first reference
                root_message_id = msg_root_mapping[first_ref]
            else:
                # First reference not seen yet, assume it's the root
                root_message_id = first_ref

        # Store this mapping for future lookups
        msg_root_mapping[msg.message_id] = root_message_id

        self.conn.execute(
            """
            INSERT OR REPLACE INTO messages
            (message_id, subject, from_addr, from_name, date_sent, git_oid, root_message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                msg.message_id,
                msg.subject,
                msg.from_addr,
                msg.from_name,
                int(msg.date.timestamp()),
                git_oid,
                root_message_id,
            ),
        )

    def find_thread(self, target_message_id: str, git_repo_path):
        messages = self.conn.execute(
            """
            SELECT message_id, subject, from_name, from_addr, date_sent, git_oid
            FROM messages
            WHERE root_message_id = (
                SELECT root_message_id FROM messages WHERE message_id = ?
            )
            ORDER BY date_sent
        """,
            (target_message_id,),
        ).fetchall()

        repo = pygit2.Repository(git_repo_path)
        email_objects = [EmailMessage.from_oid(msg["git_oid"], repo) for msg in messages]
        return thread(email_objects)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.conn.close()


def main():
    parser = argparse.ArgumentParser(description="Simple Git Email Indexer")
    parser.add_argument("--db", default="emails.db", help="Database file path")
    parser.add_argument("--git-repo", help="Git repository path to index")

    args = parser.parse_args()

    with EmailIndex(args.db) as index:
        index.index_git_repo(args.git_repo)


if __name__ == "__main__":
    main()
