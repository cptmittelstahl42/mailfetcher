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

    response, lines, octets = pop.retr(1)

    raw = b"\r\n".join(lines)

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


def main():

    load_config()

    setup_directories()

    setup_logging()

    LOGGER.info("Mailfetcher started")

    connect_pop3()

    download_first_message()


if __name__ == "__main__":
    main()
