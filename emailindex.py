#!/usr/bin/env python3
import sqlite3
import email
import email.utils
import email.header
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


@dataclass
class EmailMessage:
    message_id: str
    subject: str
    from_name: str
    from_addr: str
    date: datetime
    references: List[str]
    _git_repo: Optional[object] = None
    _git_oid: Optional[str] = None

    def __init__(self, raw_email: bytes):
        eml = email.message_from_bytes(raw_email)

        self.message_id = str(eml.get("Message-ID", "")).strip().strip("<>")

        # Decode subject header properly
        subject_header = eml.get("Subject", "")
        if subject_header:
            decoded_parts = email.header.decode_header(subject_header)
            self.subject = ""
            for part, encoding in decoded_parts:
                if part is None:
                    continue
                elif isinstance(part, bytes):
                    # Handle unknown encodings by falling back to utf-8 or latin-1
                    if encoding and encoding.lower() not in ('unknown-8bit', 'unknown'):
                        try:
                            self.subject += part.decode(encoding, errors='replace')
                        except (LookupError, UnicodeDecodeError):
                            # Fall back to utf-8, then latin-1
                            try:
                                self.subject += part.decode('utf-8', errors='replace')
                            except UnicodeDecodeError:
                                self.subject += part.decode('latin-1', errors='replace')
                    else:
                        # Unknown or no encoding - try utf-8, then latin-1
                        try:
                            self.subject += part.decode('utf-8', errors='replace')
                        except UnicodeDecodeError:
                            self.subject += part.decode('latin-1', errors='replace')
                else:
                    self.subject += str(part)
        else:
            self.subject = ""

        from_header = str(eml.get("From", ""))
        self.from_name, self.from_addr = email.utils.parseaddr(from_header)

        refs = str(eml.get("References", ""))
        in_reply_to = str(eml.get("In-Reply-To", ""))
        all_refs = f"{refs} {in_reply_to}"
        self.references = re.findall(r"<([^>]+)>", all_refs)

        date_str = str(eml.get("Date", ""))
        time_tuple = email.utils.parsedate_tz(date_str)
        assert time_tuple is not None
        timestamp = email.utils.mktime_tz(time_tuple)
        self.date = datetime.fromtimestamp(timestamp)

        payload = eml.get_payload(decode=True)
        if payload:
            self.body = payload.decode("utf-8", errors="ignore")
        else:
            self.body = str(eml.get_payload())

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

    def close(self):
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def main():
    parser = argparse.ArgumentParser(description="Simple Git Email Indexer")
    parser.add_argument("--db", default="emails.db", help="Database file path")
    parser.add_argument("--git-repo", help="Git repository path to index")

    args = parser.parse_args()

    with EmailIndex(args.db) as index:
        # Index Git repository
        if args.git_repo:
            index.index_git_repo(args.git_repo)


if __name__ == "__main__":
    main()
