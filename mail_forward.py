#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import imaplib
import smtplib
import email
import ssl
import json
import logging
import os
import email.utils
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
    if not logger.handlers:
        handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5)
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
    my_policy = policy.default.clone(utf8=True)
    original = email.message_from_bytes(raw_msg, policy=my_policy)

    from_raw = original.get("From", "")
    parsed_name, parsed_addr = email.utils.parseaddr(from_raw)    
    decoded_name = decode_mime_header(parsed_name)
    
    if decoded_name:
        original_from = f"{decoded_name} (Email: {parsed_addr})"
    else:
        original_from = parsed_addr

    original_subject = decode_mime_header(original.get("Subject", "(No Subject)"))    
    if decoded_name:
        new_subject = f"[{decoded_name}] {original_subject}"
    else:
        new_subject = f"[AUTO-FWD] {original_subject}"

    original_to = decode_mime_header(original.get("To", ""))
    original_date = original.get("Date", "")

    new_msg = EmailMessage(policy=my_policy)
    new_msg["From"] = config["smtp"]["from_address"]
    new_msg["To"] = config["forward_to"]
    new_msg["Subject"] = new_subject
    new_msg["Reply-To"] = original_from

    # --- Body extraction with fallback ---
    plain_part = original.get_body(preferencelist=('plain'))
    if not plain_part and original.is_multipart():
        for part in original.walk():
            if part.get_content_type() == "text/plain":
                plain_part = part
                break

    html_part = original.get_body(preferencelist=('html'))
    if not html_part and original.is_multipart():
        for part in original.walk():
            if part.get_content_type() == "text/html":
                html_part = part
                break

    # Header text with From (includes address), To, Date, Subject
    header_text = f"----- Forwarded Message -----\nFrom: {original_from}\nTo: {original_to}\nDate: {original_date}\nSubject: {original_subject}\n\n"

    # Set Plain Text (base64 for stability)
    if plain_part:
        new_msg.set_content(header_text + plain_part.get_content(), cte="base64")
    else:
        new_msg.set_content(header_text + "(No plain text body)", cte="base64")

    # Set HTML (base64 for stability)
    if html_part:
        html_header = f"""
<div style="border-bottom: 1px solid #ccc; margin-bottom: 10px; padding-bottom: 10px;">
  <b>----- Forwarded Message -----</b><br>
  <b>From:</b> {original_from}<br>
  <b>To:</b> {original_to}<br>
  <b>Date:</b> {original_date}<br>
  <b>Subject:</b> {original_subject}
</div>
"""
        new_msg.add_alternative(html_header + html_part.get_content(), subtype="html", cte="base64")

    # Attachments
    for part in original.iter_attachments():
        new_msg.add_attachment(
            part.get_content(),
            maintype=part.get_content_maintype(),
            subtype=part.get_content_subtype(),
            filename=part.get_filename()
        )

    # --- Send ---
    context = ssl.create_default_context()
    smtp_cfg = config["smtp"]
    
    if smtp_cfg.get("use_ssl", True):
        with smtplib.SMTP_SSL(smtp_cfg["server"], smtp_cfg["port"], context=context) as server:
            server.login(smtp_cfg["auth_user"], smtp_cfg["auth_password"])
            server.send_message(new_msg)
    else:
        with smtplib.SMTP(smtp_cfg["server"], smtp_cfg["port"]) as server:
            server.starttls(context=context)
            server.login(smtp_cfg["auth_user"], smtp_cfg["auth_password"])
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
    # --- For testing: Process only the single latest email ---
    #new_uids = [max(all_uids)]

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
