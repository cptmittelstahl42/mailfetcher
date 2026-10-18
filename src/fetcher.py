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
        directory.mkdir(parents=True, exist_ok=True)


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
        LOGGER.info(f"Mail already queued: {filename}")
        return None

    with open(target, "wb") as f:
        f.write(raw)

    LOGGER.info(f"Queued mail: {filename}")
    return target


def move_file(src_file: Path, target_dir_name: str) -> Path:
    """Hilfsfunktion zum sicheren Verschieben innerhalb der Queue."""
    target_dir = Path(CONFIG["paths"]["base"]) / "queue" / target_dir_name
    target = target_dir / src_file.name
    shutil.move(str(src_file), str(target))
    return target


def move_to_processing(eml_file):
    return move_file(eml_file, "processing")


def move_to_delivered(eml_file):
    return move_file(eml_file, "delivered")


def move_to_failed(eml_file):
    return move_file(eml_file, "failed")


def download_all_messages():
    timeout = CONFIG["pop3"].get("timeout", 30)
    
    try:
        pop = poplib.POP3_SSL(
            CONFIG["pop3"]["server"],
            CONFIG["pop3"]["port"],
            timeout=timeout
        )
        pop.user(CONFIG["pop3"]["username"])
        pop.pass_(CONFIG["pop3"]["password"])

        count, size = pop.stat()
        LOGGER.info(f"Downloading {count} messages ({size} bytes)")

        for i in range(1, count + 1):
            response, lines, octets = pop.retr(i)
            raw = b"\r\n".join(lines)
            
            # Speicherst du die Mail erfolgreich...
            saved_file = save_to_pending(raw)
            
            # ...lösche sie auf dem POP3-Server, damit sie nicht erneut heruntergeladen wird
            pop.dele(i)

        pop.quit()
        LOGGER.info("Download completed successfully")
    except Exception as e:
        LOGGER.error(f"POP3 Error: {e}")


def extract_recipients(msg):
    recipients = set()

    for header in ("X-Original-To", "Delivered-To", "Envelope-To", "To", "Cc"):
        if header in msg:
            recipients.update(
                addr for _, addr in getaddresses([msg[header]]) if addr
            )

    received_headers = msg.get_all("Received", [])
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
    recipients = extract_recipients(msg)

    if not recipients:
        raise ValueError("No valid recipients found in headers.")

    # Absender bestimmen mit Fallback auf From oder Config
    sender = msg.get("Return-Path", msg.get("From", ""))
    sender = re.sub(r'[<>]', '', sender).strip()
    
    if not sender and "default_sender" in CONFIG.get("smtp", {}):
        sender = CONFIG["smtp"]["default_sender"]

    LOGGER.info(f"Sending mail from {sender} to {recipients}")

    timeout = CONFIG["smtp"].get("timeout", 30)
    with smtplib.SMTP(CONFIG["smtp"]["server"], CONFIG["smtp"]["port"], timeout=timeout) as smtp:
        # Falls Exchange STARTTLS erfordert:
        if CONFIG["smtp"].get("use_tls", False):
            smtp.starttls()
            
        if "username" in CONFIG["smtp"] and "password" in CONFIG["smtp"]:
            smtp.login(CONFIG["smtp"]["username"], CONFIG["smtp"]["password"])

        smtp.sendmail(sender, recipients, raw)

    LOGGER.info("SMTP delivery successful")


def get_retry_count(eml_file: Path) -> int:
    """Ermittelt die Anzahl bisheriger Versuche anhand des Dateinamens."""
    match = re.search(r'\.retry(\d+)$', eml_file.name)
    if match:
        return int(match.group(1))
    return 0


def handle_failed_mail(processing_file: Path):
    """Verwaltet Fehlversuche und prüft max_retries aus der config.yaml."""
    max_retries = CONFIG.get("options", {}).get("max_retries", 3)
    current_retries = get_retry_count(processing_file)
    
    # Basis-Dateiname ohne alten Retry-Suffix ermitteln
    base_name = re.sub(r'\.retry\d+$', '', processing_file.name)

    if current_retries < max_retries:
        next_retry = current_retries + 1
        new_filename = f"{base_name}.retry{next_retry}"
        target = Path(CONFIG["paths"]["base"]) / "queue" / "pending" / new_filename
        
        shutil.move(str(processing_file), str(target))
        LOGGER.warning(
            f"Retry {next_retry}/{max_retries} scheduled for {base_name}. Re-queued to pending."
        )
    else:
        # Max Retries erreicht -> Endgültig nach failed verschieben
        target = Path(CONFIG["paths"]["base"]) / "queue" / "failed" / base_name
        shutil.move(str(processing_file), str(target))
        LOGGER.error(
            f"Max retries ({max_retries}) reached for {base_name}. Moved permanently to failed."
        )


def process_pending_queue():
    pending_dir = Path(CONFIG["paths"]["base"]) / "queue" / "pending"

    # Verarbeitet alle Dateien in pending (sowohl .eml als auch .eml.retryX)
    for eml_file in pending_dir.glob("*.eml*"):
        processing_file = None
        try:
            LOGGER.info(f"Processing {eml_file.name}")
            processing_file = move_to_processing(eml_file)
            
            deliver_to_exchange(processing_file)
            
            # Bei Erfolg: Zurück zum Originalnamen bereinigen und nach delivered verschieben
            clean_name = re.sub(r'\.retry\d+$', '', processing_file.name)
            delivered_dir = Path(CONFIG["paths"]["base"]) / "queue" / "delivered"
            target = delivered_dir / clean_name
            shutil.move(str(processing_file), str(target))
            
            LOGGER.info(f"Successfully delivered {clean_name}")

        except Exception as e:
            LOGGER.error(f"Processing failed for {eml_file.name}: {e}")
            if processing_file and processing_file.exists():
                handle_failed_mail(processing_file)
            elif eml_file.exists():
                handle_failed_mail(eml_file)


def main():
    try:
        load_config()
        setup_directories()
        setup_logging()

        LOGGER.info("Mailfetcher started")

        # 1. Mails abholen & in pending ablegen (und ggf. vom POP3 löschen)
        download_all_messages()

        # 2. Queue abarbeiten (inkl. Retry-Mechanismus)
        process_pending_queue()

        LOGGER.info("Mailfetcher run finished successfully")

    except Exception as e:
        if LOGGER:
            LOGGER.critical(f"Fatal error in main execution loop: {e}", exc_info=True)
        else:
            print(f"Fatal startup error: {e}")


if __name__ == "__main__":
    main()
