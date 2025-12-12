#!/bin/bash
# Created: 2025-11-16
# Modified: 2025-11-16 - One-line systemd installation
# Feature: Simplified systemd service installation

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SERVICE_FILE="$SCRIPT_DIR/ase_surveillance.service"
SYSTEMD_DIR="/etc/systemd/system"

echo "========================================================================"
echo "Installing ASE Surveillance Systemd Service"
echo "========================================================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "❌ This script must be run with sudo"
    echo ""
    echo "Please run:"
    echo "  sudo bash scripts/deployment/install_systemd.sh"
    echo ""
    exit 1
fi

# Check if service file exists
if [ ! -f "$SERVICE_FILE" ]; then
    echo "❌ Service file not found: $SERVICE_FILE"
    exit 1
fi

echo "[1/4] Copying service file..."
cp "$SERVICE_FILE" "$SYSTEMD_DIR/"
echo "  ✅ Copied to $SYSTEMD_DIR/ase_surveillance.service"
echo ""

echo "[2/4] Reloading systemd..."
systemctl daemon-reload
echo "  ✅ Systemd reloaded"
echo ""

echo "[3/4] Enabling auto-start on boot..."
systemctl enable ase_surveillance
echo "  ✅ Service enabled"
echo ""

echo "[4/4] Checking service status..."
if systemctl list-unit-files | grep -q ase_surveillance.service; then
    echo "  ✅ Service installed successfully"
else
    echo "  ❌ Installation verification failed"
    exit 1
fi

echo ""
echo "========================================================================"
echo "✅ INSTALLATION COMPLETE!"
echo "========================================================================"
echo ""
echo "Start the service:"
echo "  sudo systemctl start ase_surveillance"
echo ""
echo "Check status:"
echo "  sudo systemctl status ase_surveillance"
echo ""
echo "View logs:"
echo "  sudo journalctl -u ase_surveillance -f"
echo ""
echo "========================================================================"
