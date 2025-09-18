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

    @classmethod
    def for_threading(cls, message_id: str, subject: str, references: List[str], from_name: str = "", from_addr: str = "", date=None):
        obj = cls.__new__(cls)
        obj.message_id = message_id
        obj.subject = subject
        obj.references = references
        obj.from_name = from_name
        obj.from_addr = from_addr
        obj.date = date or datetime.fromtimestamp(0)
        obj._git_repo = None
        obj._git_oid = None
        return obj

    def get_body(self):
        """Get email body from git repository"""
        if self._git_repo and self._git_oid:
            blob = self._git_repo[self._git_oid]
            eml = email.message_from_bytes(blob.data)

            if eml.is_multipart():
                body = ""
                for part in eml.walk():
                    if part.get_content_type() == "text/plain":
                        try:
                            body += part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        except:
                            body += str(part.get_payload())
            else:
                try:
                    payload = eml.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="ignore")
                    else:
                        body = str(eml.get_payload())
                except:
                    body = str(eml.get_payload())

            return body
        return ""


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
                refs TEXT,
                git_oid TEXT,
                root_message_id TEXT
            )
        """
        )

        self.conn.commit()

    def index_git_repo(self, repo_path: str, branch: str = "refs/heads/master"):
        repo = pygit2.Repository(repo_path)
        # Walk through all commits
        count = 0
        commit = repo.references[branch].peel(pygit2.Commit)
        for commit in repo.walk(commit.id):
            for entry in commit.tree:
                if entry.type == pygit2.GIT_OBJECT_BLOB:
                    blob = repo[entry.id]
                    self._add_message_to_db(blob, str(entry.id))
                    count += 1
                    if count % 100 == 0:
                        logger.info(f"Indexed {count} messages...")

        self.conn.commit()

    def _add_message_to_db(self, blob, git_oid):
        raw_email = blob.data
        if not (b"Message-ID:" in raw_email or b"From:" in raw_email):
            return

        msg = EmailMessage(raw_email)
        if not msg.message_id:
            return

        # Calculate root message ID
        if not msg.references:
            # No references = thread starter
            root_message_id = msg.message_id
        else:
            # Has references = reply, use first reference as root
            root_message_id = msg.references[0]

        self.conn.execute(
            """
            INSERT OR REPLACE INTO messages
            (message_id, subject, from_addr, from_name, date_sent, refs, git_oid, root_message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                msg.message_id,
                msg.subject,
                msg.from_addr,
                msg.from_name,
                int(msg.date.timestamp()),
                " ".join(f"<{ref}>" for ref in msg.references),
                git_oid,
                root_message_id,
            ),
        )

    def find_thread(self, target_message_id: str, git_repo_path: str = None):
        # Find messages that reference our target
        cursor = self.conn.execute(
            """
            SELECT message_id, subject, from_name, from_addr, date_sent, refs, git_oid
            FROM messages
            WHERE refs LIKE ? OR message_id = ?
            ORDER BY date_sent
        """,
            (f"%{target_message_id}%", target_message_id),
        )

        messages = cursor.fetchall()

        # Load git repo if path provided
        repo = None
        if git_repo_path:
            try:
                repo = pygit2.Repository(git_repo_path)
            except:
                pass

        email_objects = []
        for msg in messages:
            # Extract references from refs field
            refs = re.findall(r"<([^>]+)>", msg["refs"]) if msg["refs"] else []
            email_msg = EmailMessage.for_threading(
                msg["message_id"],
                msg["subject"],
                refs,
                msg["from_name"],
                msg["from_addr"],
                datetime.fromtimestamp(msg["date_sent"])
            )

            # Set git repo and object ID for body loading
            if repo and msg["git_oid"]:
                email_msg._git_repo = repo
                email_msg._git_oid = msg["git_oid"]

            email_objects.append(email_msg)

        return thread(email_objects)

    def close(self):
        """Close database connection"""
        if self.conn:
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
