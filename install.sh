#!/bin/bash

set -e

INSTALL_DIR="/opt/mailfetcher"

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

echo "[INFO] Installation completed"
