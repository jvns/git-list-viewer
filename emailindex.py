#!/usr/bin/env python3
import sqlite3
import email
import email.utils
import email.policy
import re
import argparse
from datetime import datetime
from typing import List, Optional
import logging
import pygit2

from tqdm import tqdm
from jwzthreading import thread, Message

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
        name, addr = email.utils.parseaddr(from_header)
        return name if name else addr

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
        if self._email.is_multipart():
            # For multipart messages, find the first text/plain part
            # This comes up for signed messages
            for part in self._email.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        return payload.decode("utf-8", errors="ignore")
            raise Exception("no body found")
        else:
            # For single-part messages
            payload = self._email.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="ignore")
            raise Exception("no body found")

    @property
    def body_html(self) -> str:
        """Return HTML-formatted body with quoted lines styled"""
        import html

        body_text = self.body
        lines = body_text.split("\n")
        processed_lines = []

        for line in lines:
            escaped_line = html.escape(line)
            if line.strip().startswith(">"):
                processed_lines.append(
                    f'<span class="quoted-text">{escaped_line}</span>'
                )
            else:
                processed_lines.append(escaped_line)

        return "\n".join(processed_lines)

    @classmethod
    def from_oid(cls, git_oid, repo):
        blob = repo[git_oid]
        return cls(blob.data)

    def normalize_subject(self, subject: str) -> str:
        """Strip Re:/Fwd: prefixes from subject"""
        return re.sub(r"^(Re|Fwd|Fw):\s*", "", subject, flags=re.IGNORECASE).strip()

    def get_display_subject(self, parent_subject: str = None, level: int = 0) -> str:
        """Get display subject, hiding it if substantially same as parent"""
        display_subject = self.subject
        if parent_subject and level > 0:
            parent_normalized = self.normalize_subject(parent_subject)
            current_normalized = self.normalize_subject(self.subject)
            if parent_normalized and parent_normalized in current_normalized:
                display_subject = ""
        return display_subject


class EmailIndex:
    def __init__(self, db_path: str, git_repo_path):
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self.repo = pygit2.Repository(git_repo_path)

    def _create_tables(self):
        with open("schema.sql", "r") as f:
            self.conn.executescript(f.read())
        self.conn.commit()

    def _get_root_message_id(self, msg: EmailMessage) -> str:
        if not msg.references:
            # It's the start of a thread
            return msg.message_id
        else:
            first_ref = msg.references[0]
            if root_from_db := self._get_root_message_id_from_db(first_ref):
                return root_from_db
            # It's the first reply
            return first_ref

    def _get_latest_processed_commit_id(self) -> Optional[str]:
        result = self.conn.execute(
            "SELECT commit_id FROM messages ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        return result[0] if result else None

    def _get_root_message_id_from_db(self, message_id: str) -> Optional[str]:
        result = self.conn.execute(
            "SELECT root_message_id FROM messages WHERE message_id = ?", (message_id,)
        ).fetchone()
        return result[0] if result else None

    def _get_email_message(self, commit_id: str) -> EmailMessage:
        commit = self.repo[commit_id]
        for entry in commit.tree:
            if entry.type == pygit2.GIT_OBJECT_BLOB:
                return EmailMessage.from_oid(entry.id, self.repo)
        raise Exception("No commit found")

    def _get_commits(self):
        start_commit = self.repo.references["refs/heads/master"].peel(pygit2.Commit)
        walker = self.repo.walk(
            start_commit.id, pygit2.GIT_SORT_TOPOLOGICAL | pygit2.GIT_SORT_REVERSE
        )

        # Ignore commits that have already been processed
        latest_commit_id = self._get_latest_processed_commit_id()
        if latest_commit_id:
            walker.hide(latest_commit_id)

        return list(walker)

    def index_git_repo(self):
        self.repo.remotes["origin"].fetch()

        commits = self._get_commits()
        for commit in tqdm(commits):
            self._add_message(str(commit.id))

        logger.info(f"Indexing complete: {len(commits)} new messages added")

    def _add_message(self, commit_id):
        msg = self._get_email_message(commit_id)
        root_message_id = self._get_root_message_id(msg)
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
        self.conn.commit()

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

        email_objects = [self._get_email_message(msg["commit_id"]) for msg in messages]

        # Convert EmailMessage objects to jwzthreading.Message objects
        jwz_messages = []
        for email_obj in email_objects:
            jwz_msg = Message(email_obj)
            jwz_msg.message_id = email_obj.message_id
            jwz_msg.subject = email_obj.subject
            jwz_msg.references = email_obj.references
            jwz_messages.append(jwz_msg)

        # Use jwzthreading to build the thread structure
        subject_table = thread(jwz_messages)

        # Convert back to a flat list for compatibility
        return self._flatten_subject_table(subject_table)

    def _flatten_subject_table(self, subject_table):
        """Convert jwzthreading subject table to flat list of messages"""
        flattened = []

        def traverse_container(container, level=0, parent_subject=None):
            if container.message:
                # Extract the original EmailMessage from the Message wrapper
                email_obj = container.message.message
                email_obj.level = level
                email_obj.display_subject = email_obj.get_display_subject(parent_subject, level)
                flattened.append(email_obj)
                current_subject = email_obj.subject
            else:
                current_subject = parent_subject

            # Traverse children
            for child in container.children:
                traverse_container(child, level + 1, current_subject)

        # Process all subjects in the table
        for subject, root_container in subject_table.items():
            traverse_container(root_container)

        return flattened

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
