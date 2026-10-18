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


def main():

    load_config()

    setup_directories()

    setup_logging()

    LOGGER.info("Mailfetcher started")


if __name__ == "__main__":
    main()
