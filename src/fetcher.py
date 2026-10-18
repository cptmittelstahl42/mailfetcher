#!/usr/bin/env python3

import fcntl
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import poplib
import re
import shutil
import smtplib
import sys
import time
from datetime import datetime
from email.message import EmailMessage
from email import message_from_bytes
from email.utils import getaddresses
from pathlib import Path

import yaml


CONFIG = None
LOGGER = None
LOCK_FILE_HANDLE = None


def load_config():
    global CONFIG
    base_config = Path("/opt/mailfetcher/config.yaml")
    sub_config = Path("/opt/mailfetcher/config/config.yaml")

    config_file = base_config if base_config.exists() else sub_config

    if not config_file.exists():
        raise FileNotFoundError(
            "Configuration file not found. Please create /opt/mailfetcher/config.yaml"
        )

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
    logfile = Path(CONFIG["paths"]["base"]) / "logs" / "fetcher.log"

    # Rotating Log: max 5 MB pro Datei, behält 5 alte Logfiles
    file_handler = RotatingFileHandler(
        logfile, maxBytes=5 * 1024 * 1024, backupCount=5
    )

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        handlers=[
            file_handler,
            logging.StreamHandler()
        ]
    )
    LOGGER = logging.getLogger("mailfetcher")


def acquire_lock():
    """Verhindert parallele Ausführungen des Skripts (z. B. bei kurzen Cronjob-Intervallen)."""
    global LOCK_FILE_HANDLE
    lock_file = Path(CONFIG["paths"]["base"]) / "state" / "fetcher.lock"
    
    LOCK_FILE_HANDLE = open(lock_file, "w")
    try:
        fcntl.flock(LOCK_FILE_HANDLE, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except IOError:
        LOGGER.warning("Mailfetcher is already running. Exiting process.")
        sys.exit(0)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def save_to_pending(raw):
    mail_hash = sha256_bytes(raw)
    filename = f"{mail_hash}.eml"
    target = Path(CONFIG["paths"]["base"]) / "queue" / "pending" / filename

    if target.exists():
        LOGGER.info(f"Mail already queued: {filename}")
        return None

    with open(target, "wb") as f:
        f.write(raw)

    LOGGER.info(f"Queued mail: {filename}")
    return target


def move_file(src_file: Path, target_dir_name: str) -> Path:
    """Hilfsfunktion zum sicheren Verschieben innerhalb der Queue-Ordner."""
    target_dir = Path(CONFIG["paths"]["base"]) / "queue" / target_dir_name
    target = target_dir / src_file.name
    shutil.move(str(src_file), str(target))
    return target


def move_to_processing(eml_file):
    return move_file(eml_file, "processing")


def send_admin_alert(failed_file: Path, error_message: str):
    """Verschickt eine Benachrichtigung per E-Mail an den Admin bei endgültigem Fehlschlag."""
    admin_email = CONFIG.get("admin", {}).get("email")
    if not admin_email:
        LOGGER.warning("No admin email configured in config.yaml. Skipping alert.")
        return

    try:
        msg = EmailMessage()
        msg["Subject"] = f"[ALERT] Mailfetcher Delivery Failed: {failed_file.name}"
        msg["From"] = CONFIG.get("smtp", {}).get("default_sender", "mailfetcher@cooperlan.de")
        msg["To"] = admin_email

        body = (
            f"Hallo Admin,\n\n"
            f"eine E-Mail konnte nach mehreren Versuchen nicht zugestellt werden und wurde nach 'queue/failed' verschoben.\n\n"
            f"Datei: {failed_file.name}\n"
            f"Pfad: {failed_file.absolute()}\n"
            f"Fehlermeldung: {error_message}\n\n"
            f"Bitte prüfe den Exchange-Server oder die Datei manuell.\n\n"
            f"Dein Mailfetcher Service"
        )
        msg.set_content(body)

        timeout = CONFIG["smtp"].get("timeout", 30)
        with smtplib.SMTP(CONFIG["smtp"]["server"], CONFIG["smtp"]["port"], timeout=timeout) as smtp:
            if CONFIG["smtp"].get("use_tls", False):
                smtp.starttls()
            if "username" in CONFIG["smtp"] and "password" in CONFIG["smtp"]:
                smtp.login(CONFIG["smtp"]["username"], CONFIG["smtp"]["password"])
            
            smtp.send_message(msg)

        LOGGER.info(f"Admin alert sent to {admin_email} for file {failed_file.name}")

    except Exception:
        LOGGER.exception("Failed to send admin alert email")


def get_retry_count(eml_file: Path) -> int:
    """Ermittelt die Anzahl bisheriger Versuche anhand des Suffixes im Dateinamen."""
    match = re.search(r'\.retry(\d+)$', eml_file.name)
    if match:
        return int(match.group(1))
    return 0


def handle_failed_mail(processing_file: Path, error_message: str):
    """Verwaltet Fehlversuche und verschiebt die Mail nach Retries oder endgültig nach failed."""
    max_retries = CONFIG.get("options", {}).get("max_retries", 3)
    current_retries = get_retry_count(processing_file)
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
        # Max Retries erreicht -> Endgültig nach failed verschieben & Admin benachrichtigen
        target = Path(CONFIG["paths"]["base"]) / "queue" / "failed" / base_name
        shutil.move(str(processing_file), str(target))
        LOGGER.error(
            f"Max retries ({max_retries}) reached for {base_name}. Moved permanently to failed."
        )
        send_admin_alert(target, error_message)


def download_all_messages():
    timeout = CONFIG["pop3"].get("timeout", 30)
    delete_after_download = CONFIG.get("options", {}).get("delete_after_download", False)

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
            
            # Erst lokal auf Festplatte absichern...
            saved_file = save_to_pending(raw)

            # ...erst danach auf dem POP3-Server zum Löschen markieren!
            if delete_after_download and saved_file is not None:
                pop.dele(i)

        pop.quit()
        LOGGER.info("Download completed successfully")
    except Exception:
        LOGGER.exception("POP3 Error occurred during download")


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

    sender = msg.get("Return-Path", msg.get("From", ""))
    sender = re.sub(r'[<>]', '', sender).strip()
    
    if not sender and "default_sender" in CONFIG.get("smtp", {}):
        sender = CONFIG["smtp"]["default_sender"]

    LOGGER.info(f"Sending mail from {sender} to {recipients}")

    timeout = CONFIG["smtp"].get("timeout", 30)
    with smtplib.SMTP(CONFIG["smtp"]["server"], CONFIG["smtp"]["port"], timeout=timeout) as smtp:
        if CONFIG["smtp"].get("use_tls", False):
            smtp.starttls()
            
        if "username" in CONFIG["smtp"] and "password" in CONFIG["smtp"]:
            smtp.login(CONFIG["smtp"]["username"], CONFIG["smtp"]["password"])

        smtp.sendmail(sender, recipients, raw)

    LOGGER.info("SMTP delivery successful")


def process_pending_queue():
    pending_dir = Path(CONFIG["paths"]["base"]) / "queue" / "pending"

    for eml_file in pending_dir.glob("*.eml*"):
        processing_file = None
        try:
            LOGGER.info(f"Processing {eml_file.name}")
            processing_file = move_to_processing(eml_file)
            
            deliver_to_exchange(processing_file)
            
            # Bei Erfolg Name bereinigen und in delivered verschieben
            clean_name = re.sub(r'\.retry\d+$', '', processing_file.name)
            delivered_dir = Path(CONFIG["paths"]["base"]) / "queue" / "delivered"
            target = delivered_dir / clean_name
            shutil.move(str(processing_file), str(target))
            
            LOGGER.info(f"Successfully delivered {clean_name}")

        except Exception as e:
            # Nutzt LOGGER.exception, um den vollen Traceback im Log zu erfassen
            LOGGER.exception(f"Processing failed for {eml_file.name}")
            target_file = processing_file if processing_file and processing_file.exists() else eml_file
            if target_file.exists():
                handle_failed_mail(target_file, str(e))


def cleanup_old_delivered_mails(days=30):
    """Löscht Mails in queue/delivered, die älter als X Tage sind."""
    delivered_dir = Path(CONFIG["paths"]["base"]) / "queue" / "delivered"
    now = time.time()
    cutoff = now - (days * 86400)

    for eml_file in delivered_dir.glob("*.eml"):
        if eml_file.stat().st_mtime < cutoff:
            eml_file.unlink()
            LOGGER.info(f"Cleaned up old delivered mail: {eml_file.name}")


def main():
    try:
        load_config()
        setup_directories()
        setup_logging()

        # Doppelstarts bei kurzen Cronjob-Intervallen blockieren
        acquire_lock()

        LOGGER.info("Mailfetcher started")

        download_all_messages()
        process_pending_queue()
        cleanup_old_delivered_mails(days=30)

        LOGGER.info("Mailfetcher run finished successfully")

    except Exception as e:
        if LOGGER:
            LOGGER.critical(f"Fatal error in main execution loop: {e}", exc_info=True)
        else:
            print(f"Fatal startup error: {e}")
        # Beendet das Programm mit Fehlercode, damit Systemd den Fehlschlag erfasst
        sys.exit(1)


if __name__ == "__main__":
    main()
