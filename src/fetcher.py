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


def download_first_message():

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

    if count == 0:

        LOGGER.info(
            "Mailbox is empty"
        )

        pop.quit()
        return

    for i in range(1, count + 1):

    response, lines, octets = pop.retr(i)

    raw = b"\r\n".join(lines)

    msg = message_from_bytes(raw)

    LOGGER.info(
        f"Mail {i}: {msg.get('Subject', 'No Subject')}"
    )

    target = (
        Path(CONFIG["paths"]["base"])
        / "queue"
        / "pending"
        / "test.eml"
    )

    with open(target, "wb") as f:
        f.write(raw)

    LOGGER.info(
        f"Downloaded first message ({octets} bytes)"
    )

    pop.quit()

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

def test_delivery():

    eml_file = (
        Path(CONFIG["paths"]["base"])
        / "queue"
        / "pending"
        / "test.eml"
    )

    deliver_to_exchange(
        eml_file
    )

def test_recipient_extraction():

    eml_file = (
        Path(CONFIG["paths"]["base"])
        / "queue"
        / "pending"
        / "test.eml"
    )

    recipients = extract_recipients(
        eml_file
    )

    LOGGER.info(
        f"Recipients found: {recipients}"
    )


def main():

    load_config()

    setup_directories()

    setup_logging()

    LOGGER.info("Mailfetcher started")

    connect_pop3()

    download_first_message()

    test_recipient_extraction()

    test_delivery()


if __name__ == "__main__":
    main()
