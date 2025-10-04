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
import subprocess
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
    def sanitized_message_id(self) -> str:
        return (
            self.message_id.replace("<", "")
            .replace(">", "")
            .replace("@", "_at_")
            .replace(".", "_")
        )

    @property
    def subject(self) -> str:
        return str(self._email.get("Subject"))

    @property
    def from_name(self) -> str:
        from_header = str(self._email.get("From"))
        name, _ = email.utils.parseaddr(from_header)
        return name

    @property
    def from_addr(self) -> str:
        from_header = str(self._email.get("From"))
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

    @property
    def body_html(self) -> str:
        """Return HTML-formatted body with quoted lines styled"""
        import html

        body_text = self.body
        lines = body_text.split('\n')
        processed_lines = []

        for line in lines:
            escaped_line = html.escape(line)
            if line.strip().startswith('>'):
                processed_lines.append(f'<span class="quoted-text">{escaped_line}</span>')
            else:
                processed_lines.append(escaped_line)

        return '\n'.join(processed_lines)

    @classmethod
    def from_oid(cls, git_oid, repo):
        blob = repo[git_oid]
        return cls(blob.data)


class EmailIndex:
    def __init__(self, db_path: str, git_repo_path):
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self.repo = pygit2.Repository(git_repo_path)

    def _calculate_root_message_id(
        self, msg: EmailMessage, msg_root_mapping: Dict[str, str]
    ) -> str:
        if not msg.references:
            return msg.message_id
        else:
            first_ref = msg.references[0]
            # First check in-memory mapping (for current run)
            if first_ref in msg_root_mapping:
                return msg_root_mapping[first_ref]
            # Then check database (for existing messages)
            root_from_db = self._get_root_message_id_from_db(first_ref)
            if root_from_db:
                return root_from_db
            # Fallback: use the reference itself as root
            return first_ref

    def _create_tables(self):
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                subject TEXT,
                from_addr TEXT,
                from_name TEXT,
                date_sent INTEGER,
                commit_id TEXT,
                root_message_id TEXT
            )
        """
        )

        # Create index on commit_id for faster lookups during incremental indexing
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_commit_id ON messages (commit_id)"
        )

        self.conn.commit()

    def _get_latest_processed_commit_id(self) -> Optional[str]:
        """Get the commit_id of the last processed message using rowid"""
        cursor = self.conn.execute(
            "SELECT commit_id FROM messages ORDER BY rowid DESC LIMIT 1"
        )
        result = cursor.fetchone()
        return result[0] if result else None

    def _get_root_message_id_from_db(self, message_id: str) -> Optional[str]:
        """Query database to get root message ID for a given message ID"""
        cursor = self.conn.execute(
            "SELECT root_message_id FROM messages WHERE message_id = ?",
            (message_id,)
        )
        result = cursor.fetchone()
        return result[0] if result else None

    def _get_email_message_from_commit(self, commit_id: str) -> Optional[EmailMessage]:
        """Get the EmailMessage from the single blob in a commit"""
        commit = self.repo[commit_id]
        for entry in commit.tree:
            if entry.type == pygit2.GIT_OBJECT_BLOB:
                git_oid = str(entry.id)
                return EmailMessage.from_oid(git_oid, self.repo)
        return None

    def index_git_repo(self, branch: str = "refs/heads/master"):
        logger.info("Running git fetch to update repository...")
        try:
            subprocess.run(
                ["git", "fetch", "origin"],
                cwd=self.repo.workdir,
                check=True,
                capture_output=True,
                text=True
            )
            logger.info("Git fetch completed successfully")
        except subprocess.CalledProcessError as e:
            logger.warning(f"Git fetch failed: {e.stderr}")

        start_commit = self.repo.references[branch].peel(pygit2.Commit)

        # Find where we left off to avoid walking unnecessary commits

        latest_commit_id = self._get_latest_processed_commit_id()
        commits = list(
            self.repo.walk(
                start_commit.id, pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_REVERSE
            )
        )
        if latest_commit_id:
            for idx, c in enumerate(commits):
                if str(c.id) == str(latest_commit_id):
                    commits = commits[idx + 1:]
                    break
            else:
                raise Exception("didn't find " + latest_commit_id)

        # Dictionary to track message_id -> root_message_id mappings for current run
        msg_root_mapping = {}

        count = 0
        new_count = 0
        for commit in commits:
            commit_id = str(commit.id)
            email_msg = self._get_email_message_from_commit(commit_id)
            if email_msg:
                self._add_message_to_db(email_msg, commit_id, msg_root_mapping)
                count += 1
                new_count += 1
                if count % 100 == 0:
                    logger.info(f"Processed {count} total, {new_count} new messages...")

        logger.info(f"Indexing complete: {new_count} new messages added")
        self.conn.commit()

    def _add_message_to_db(self, msg, commit_id, msg_root_mapping):
        if not msg.message_id:
            return

        root_message_id = self._calculate_root_message_id(msg, msg_root_mapping)
        msg_root_mapping[msg.message_id] = root_message_id

        self.conn.execute(
            """
            INSERT OR REPLACE INTO messages
            (message_id, subject, from_addr, from_name, date_sent, commit_id, root_message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                msg.message_id,
                msg.subject,
                msg.from_addr,
                msg.from_name,
                int(msg.date.timestamp()),
                commit_id,
                root_message_id,
            ),
        )

    def find_thread(self, target_message_id: str):
        messages = self.conn.execute(
            """
            SELECT commit_id FROM messages
            WHERE root_message_id = (
                SELECT root_message_id FROM messages WHERE message_id = ?
            )
            ORDER BY date_sent
        """,
            (target_message_id,),
        ).fetchall()

        email_objects = []
        for msg in messages:
            email_msg = self._get_email_message_from_commit(msg["commit_id"])
            if email_msg:
                email_objects.append(email_msg)
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

    with EmailIndex(args.db, args.git_repo) as index:
        index.index_git_repo()


if __name__ == "__main__":
    main()
