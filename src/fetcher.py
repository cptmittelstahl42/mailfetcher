#!/usr/bin/env python3

import json
import logging
import hashlib
import poplib
import smtplib
import shutil
import re

from pathlib import Path
from datetime import datetime
from email import message_from_bytes
from email.utils import getaddresses

import yaml


CONFIG = None
LOGGER = None


def load_config():
    global CONFIG

    config_file = Path("/opt/mailfetcher/config.yaml")

    with open(config_file, "r") as f:
        CONFIG = yaml.safe_load(f)


def setup_directories():

    base = Path(CONFIG["paths"]["base"])

    dirs = [
        base / "logs",
        base / "state",
        base / "archive",
        base / "queue" / "pending",
        base / "queue" / "processing",
        base / "queue" / "delivered",
        base / "queue" / "failed"
    ]

    for directory in dirs:
        directory.mkdir(
            parents=True,
            exist_ok=True
        )


def setup_logging():

    global LOGGER

    logfile = (
        Path(CONFIG["paths"]["base"])
        / "logs"
        / "fetcher.log"
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        handlers=[
            logging.FileHandler(logfile),
            logging.StreamHandler()
        ]
    )

    LOGGER = logging.getLogger("mailfetcher")


def sha256_bytes(data):

    return hashlib.sha256(data).hexdigest()


def save_to_pending(raw):

    mail_hash = sha256_bytes(raw)

    filename = f"{mail_hash}.eml"

    target = (
        Path(CONFIG["paths"]["base"])
        / "queue"
        / "pending"
        / filename
    )

    if target.exists():

        LOGGER.info(
            f"Mail already queued: {filename}"
        )

        return None

    with open(target, "wb") as f:
        f.write(raw)

    LOGGER.info(
        f"Queued mail: {filename}"
    )

    return target

def move_to_processing(eml_file):

    processing_dir = (
        Path(CONFIG["paths"]["base"])
        / "queue"
        / "processing"
    )

    target = (
        processing_dir
        / eml_file.name
    )

    shutil.move(
        str(eml_file),
        str(target)
    )

    return target

def move_to_delivered(eml_file):

    delivered_dir = (
        Path(CONFIG["paths"]["base"])
        / "queue"
        / "delivered"
    )

    target = (
        delivered_dir
        / eml_file.name
    )

    shutil.move(
        str(eml_file),
        str(target)
    )

    return target

def connect_pop3():

    LOGGER.info(
        f"Connecting to {CONFIG['pop3']['server']}"
    )

    pop = poplib.POP3_SSL(
        CONFIG["pop3"]["server"],
        CONFIG["pop3"]["port"]
    )

    pop.user(
        CONFIG["pop3"]["username"]
    )

    pop.pass_(
        CONFIG["pop3"]["password"]
    )

    count, size = pop.stat()

    LOGGER.info(
        f"Mailbox contains {count} messages ({size} bytes)"
    )

    pop.quit()

    LOGGER.info(
        "POP3 connection closed"
    )


def download_all_messages():

    pop = poplib.POP3_SSL(
        CONFIG["pop3"]["server"],
        CONFIG["pop3"]["port"]
    )

    pop.user(
        CONFIG["pop3"]["username"]
    )

    pop.pass_(
        CONFIG["pop3"]["password"]
    )

    count, size = pop.stat()

    LOGGER.info(
        f"Downloading {count} messages"
    )

    for i in range(1, count + 1):

        response, lines, octets = pop.retr(i)

        raw = b"\r\n".join(lines)

        save_to_pending(raw)

    pop.quit()

    LOGGER.info(
        "Download completed"
    )

def extract_recipients(eml_file):

    with open(eml_file, "rb") as f:
        msg = message_from_bytes(
            f.read()
        )

    recipients = set()

    for header in (
        "X-Original-To",
        "Delivered-To",
        "Envelope-To",
        "To",
        "Cc"
    ):

        if header in msg:

            recipients.update(
                addr
                for _, addr
                in getaddresses(
                    [msg[header]]
                )
            )

    received_headers = msg.get_all(
        "Received",
        []
    )

    for received in received_headers:

        matches = re.findall(
            r'for\s+<?([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})>?',
            received,
            re.IGNORECASE
        )

        recipients.update(matches)

    return list(recipients)

def process_pending_queue():

    pending_dir = (
        Path(CONFIG["paths"]["base"])
        / "queue"
        / "pending"
    )

    for eml_file in pending_dir.glob("*.eml"):

    try:

        LOGGER.*nfo(
            f"Processing {eml*file.name}"
        )

        pro*essing_file = move_to_processing(
*           eml_file
        )

   *    deliver_to_exchange(
         *  processing_file
        )

     *  move_to_delivered(
            p*ocessing_file
        )

        L*GGER.info(
            f"Delivered*{processing_file.name}"
        )
*    except Exception as e:

      * LOGGER.error(
            f"Proce*sing failed: {e}"
        )

def deliver_to_exchange(eml_file):

    with open(eml_file, "rb") as f:

        raw = f.read()

    msg = message_from_bytes(raw)

    recipients = extract_recipients(
        eml_file
    )

    sender = msg.get(
        "Return-Path",
        ""
    )

    sender = sender.replace(
        "<",
        ""
    ).replace(
        ">",
        ""
    )

    LOGGER.info(
        f"Sending mail to {recipients}"
    )

    smtp = smtplib.SMTP(
        CONFIG["smtp"]["server"],
        CONFIG["smtp"]["port"]
    )

    smtp.sendmail(
        sender,
        recipients,
        raw
    )

    smtp.quit()

    LOGGER.info(
        "SMTP delivery successful"
    )


def main():

    load_config()

    setup_directories()

    setup_logging()

    LOGGER.info("Mailfetcher started")

    connect_pop3()

    download_all_messages()

    process_pending_queue()


if __name__ == "__main__":
    main()
