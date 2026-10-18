#!/bin/bash

set -e

INSTALL_DIR="/opt/mailfetcher"

echo "[INFO] Installing dependencies"

apt update
apt install -y \
    python3 \
    python3-pip \
    python3-venv

echo "[INFO] Creating directories"

mkdir -p \
    ${INSTALL_DIR}/logs \
    ${INSTALL_DIR}/state \
    ${INSTALL_DIR}/archive \
    ${INSTALL_DIR}/queue/pending \
    ${INSTALL_DIR}/queue/processing \
    ${INSTALL_DIR}/queue/delivered \
    ${INSTALL_DIR}/queue/failed

echo "[INFO] Creating virtual environment"

python3 -m venv ${INSTALL_DIR}/venv

source ${INSTALL_DIR}/venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

echo "[INFO] Installing systemd files"

cp systemd/mailfetcher.service \
   /etc/systemd/system/

cp systemd/mailfetcher.timer \
   /etc/systemd/system/

systemctl daemon-reload

echo "[INFO] Installation complete"

echo ""
echo "Copy config.yaml.example to:"
echo "/opt/mailfetcher/config.yaml"
echo ""
echo "Edit credentials"
echo ""
echo "Enable timer:"
echo "systemctl enable --now mailfetcher.timer"
