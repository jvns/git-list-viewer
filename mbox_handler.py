#!/usr/bin/env python3

import os
import requests
import gzip
import mailbox
import tempfile
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
