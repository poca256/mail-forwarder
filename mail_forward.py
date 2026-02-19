#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import imaplib
import smtplib
import email
import ssl
import json
import logging
import os
from email import policy
from email.message import EmailMessage
from email.header import decode_header
from logging.handlers import RotatingFileHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
UID_STATE_FILE = os.path.join(BASE_DIR, "uid_state.json")
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "mail_forward.log")

def setup_logger():
    logger = logging.getLogger("mail_forward")
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=5)
    formatter = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.addHandler(logging.StreamHandler())
    return logger

def decode_mime_header(value):
    if not value:
        return ""
    decoded_parts = decode_header(value)
    decoded_string = ""
    for part, enc in decoded_parts:
        if isinstance(part, bytes):
            decoded_string += part.decode(enc or "utf-8", errors="replace")
        else:
            decoded_string += part
    return decoded_string

def load_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def load_uid_state():
    if not os.path.exists(UID_STATE_FILE):
        return {}
    with open(UID_STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_uid_state(state):
    with open(UID_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def forward_email(raw_msg, config, logger):
    original = email.message_from_bytes(raw_msg, policy=policy.default)

    original_from = decode_mime_header(original.get("From", ""))
    original_subject = decode_mime_header(original.get("Subject", "(No Subject)"))
    original_date = original.get("Date", "")

    SMTP_SERVER = config["smtp"]["server"]
    SMTP_PORT = config["smtp"]["port"]
    SMTP_AUTH_USER = config["smtp"]["auth_user"]
    SMTP_AUTH_PASSWORD = config["smtp"]["auth_password"]
    SMTP_FROM = config["smtp"]["from_address"]
    FORWARD_TO = config["forward_to"]

    new_msg = EmailMessage()
    new_msg["From"] = SMTP_FROM
    new_msg["To"] = FORWARD_TO
    new_msg["Subject"] = f"[AUTO-FWD] {original_subject}"
    new_msg["Reply-To"] = original_from

    header_text = f"""----- Forwarded Message -----
From: {original_from}
Date: {original_date}
Subject: {original_subject}

"""

    text_body = None
    html_body = None

    for part in original.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_disposition() == "attachment":
            continue

        content_type = part.get_content_type()

        if content_type == "text/html":
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                html_body = payload.decode(charset, errors="replace")

        elif content_type == "text/plain" and html_body is None:
            payload = part.get_payload(decode=True)
            if payload:
                charset = part.get_content_charset() or "utf-8"
                text_body = payload.decode(charset, errors="replace")

    plain_text = header_text
    if text_body:
        plain_text += text_body
    elif html_body:
        plain_text += html_body
    else:
        plain_text += "(No body)"

    new_msg.set_content(
        plain_text,
        subtype="plain",
        charset="utf-8",
        cte="8bit"
    )

    if html_body:
        html_header = f"""
<hr>
<b>----- Forwarded Message -----</b><br>
<b>From:</b> {original_from}<br>
<b>Date:</b> {original_date}<br>
<b>Subject:</b> {original_subject}<br>
<hr>
"""
        new_msg.add_alternative(
            html_header + html_body,
            subtype="html",
            charset="utf-8",
            cte="8bit"
        )

    for part in original.iter_attachments():
        try:
            new_msg.add_attachment(
                part.get_content(),
                maintype=part.get_content_maintype(),
                subtype=part.get_content_subtype(),
                filename=part.get_filename()
            )
        except Exception as e:
            logger.error(f"Attachment error: {e}")

    context = ssl.create_default_context()
    use_ssl = config["smtp"].get("use_ssl", True)

    if use_ssl:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            server.login(SMTP_AUTH_USER, SMTP_AUTH_PASSWORD)
            server.send_message(new_msg)
    else:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(SMTP_AUTH_USER, SMTP_AUTH_PASSWORD)
            server.send_message(new_msg)

    logger.info(f"Forwarded: {original_subject}")

def process_imap_account(account, config, uid_state, logger):
    host = account["host"]
    port = account.get("port", 993)
    user = account["user"]
    password = account["password"]

    logger.info(f"Checking mailbox: {user}")

    mail = imaplib.IMAP4_SSL(host, port)
    mail.login(user, password)
    mail.select("INBOX")

    result, data = mail.uid("search", None, "ALL")
    if result != "OK":
        logger.error(f"UID search failed for {user}")
        mail.logout()
        return

    all_uids = [int(uid) for uid in data[0].split()]
    if not all_uids:
        mail.logout()
        return

    latest_uid = max(all_uids)

    if user not in uid_state:
        logger.info(f"First run for {user} - saving UID only ({latest_uid})")
        uid_state[user] = latest_uid
        mail.logout()
        return

    last_uid = uid_state[user]
    new_uids = [uid for uid in all_uids if uid > last_uid]

    if not new_uids:
        mail.logout()
        return

    for uid in sorted(new_uids):
        result, msg_data = mail.uid("fetch", str(uid), "(RFC822)")
        if result != "OK":
            continue
        raw_msg = msg_data[0][1]
        try:
            forward_email(raw_msg, config, logger)
        except Exception as e:
            logger.error(f"Forward failed ({user}): {e}")

    uid_state[user] = max(new_uids)
    mail.logout()

def main():
    logger = setup_logger()
    config = load_config()
    uid_state = load_uid_state()

    for account in config["imap_accounts"]:
        process_imap_account(account, config, uid_state, logger)

    save_uid_state(uid_state)
    logger.info(f"Saved UID state: {uid_state}")

if __name__ == "__main__":
    main()
