#!/bin/bash

set -e

INSTALL_DIR="/opt/mailfetcher"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[INFO] Installing system dependencies..."
apt update
apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    rsync

echo "[INFO] Creating directories in ${INSTALL_DIR}..."
mkdir -p \
    ${INSTALL_DIR}/src \
    ${INSTALL_DIR}/config \
    ${INSTALL_DIR}/logs \
    ${INSTALL_DIR}/state \
    ${INSTALL_DIR}/archive \
    ${INSTALL_DIR}/queue/pending \
    ${INSTALL_DIR}/queue/processing \
    ${INSTALL_DIR}/queue/delivered \
    ${INSTALL_DIR}/queue/failed

echo "[INFO] Copying application files..."
# Kopiert Quellcode und requirements ins Zielverzeichnis
cp -r ${SCRIPT_DIR}/src/* ${INSTALL_DIR}/src/ 2>/dev/null || true
cp ${SCRIPT_DIR}/requirements.txt ${INSTALL_DIR}/ 2>/dev/null || true

# Erstellt eine config.yaml aus der Example-Datei, falls noch keine existiert
if [ ! -f "${INSTALL_DIR}/config.yaml" ] && [ -f "${SCRIPT_DIR}/config/config.yaml.example" ]; then
    echo "[INFO] Creating default config.yaml from example..."
    cp ${SCRIPT_DIR}/config/config.yaml.example ${INSTALL_DIR}/config.yaml
fi

echo "[INFO] Creating virtual environment..."
python3 -m venv ${INSTALL_DIR}/venv

echo "[INFO] Installing Python dependencies..."
# Direktes Nutzen der venv-Binaries ist robuster als 'source'
${INSTALL_DIR}/venv/bin/pip install --upgrade pip
if [ -f "${INSTALL_DIR}/requirements.txt" ]; then
    ${INSTALL_DIR}/venv/bin/pip install -r ${INSTALL_DIR}/requirements.txt
fi

echo "[INFO] Installing systemd files..."
if [ -d "${SCRIPT_DIR}/systemd" ]; then
    cp ${SCRIPT_DIR}/systemd/mailfetcher.service /etc/systemd/system/
    cp ${SCRIPT_DIR}/systemd/mailfetcher.timer /etc/systemd/system/
    systemctl daemon-reload
else
    echo "[WARN] Systemd directory not found, skipping service installation."
fi

echo ""
echo "=========================================="
echo " [SUCCESS] Installation complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit configuration file:"
echo "   nano /opt/mailfetcher/config.yaml"
echo ""
echo "2. Enable and start the systemd timer:"
echo "   systemctl enable --now mailfetcher.timer"
echo ""
