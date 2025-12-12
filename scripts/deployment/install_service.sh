#!/bin/bash
# ASE Surveillance Service Installation Script
# Version: 1.0.0
# Created: 2025-11-16
#
# Purpose:
# - Install systemd service for automatic startup
# - Configure service to run on boot
# - Set up proper permissions
# - Verify installation
#
# Usage:
#   sudo bash install_service.sh

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}❌ Please run as root: sudo bash install_service.sh${NC}"
    exit 1
fi

echo "========================================"
echo "ASE Surveillance Service Installation"
echo "========================================"
echo ""

# Detect project directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "📂 Project directory: $PROJECT_ROOT"
echo ""

# Get the user who invoked sudo (not root)
REAL_USER=${SUDO_USER:-$USER}
REAL_HOME=$(eval echo ~$REAL_USER)

echo "👤 Service will run as user: $REAL_USER"
echo ""

# Update service file with correct paths
SERVICE_FILE="$SCRIPT_DIR/ase_surveillance.service"
TEMP_SERVICE_FILE="/tmp/ase_surveillance.service"

echo "🔧 Configuring service file..."

# Replace placeholders with actual paths
sed "s|/home/smartahc|$REAL_HOME|g" "$SERVICE_FILE" > "$TEMP_SERVICE_FILE"
sed -i "s|User=smartahc|User=$REAL_USER|g" "$TEMP_SERVICE_FILE"
sed -i "s|Group=smartahc|Group=$REAL_USER|g" "$TEMP_SERVICE_FILE"

# Copy service file to systemd directory
echo "📋 Installing systemd service..."
cp "$TEMP_SERVICE_FILE" /etc/systemd/system/ase_surveillance.service
chown root:root /etc/systemd/system/ase_surveillance.service
chmod 644 /etc/systemd/system/ase_surveillance.service

# Reload systemd
echo "🔄 Reloading systemd daemon..."
systemctl daemon-reload

# Enable service (auto-start on boot)
echo "✅ Enabling service to start on boot..."
systemctl enable ase_surveillance.service

echo ""
echo -e "${GREEN}✅ Installation completed successfully!${NC}"
echo ""
echo "========================================"
echo "Service Management Commands"
echo "========================================"
echo ""
echo "Start service:"
echo "  sudo systemctl start ase_surveillance"
echo ""
echo "Stop service:"
echo "  sudo systemctl stop ase_surveillance"
echo ""
echo "Restart service:"
echo "  sudo systemctl restart ase_surveillance"
echo ""
echo "Check status:"
echo "  sudo systemctl status ase_surveillance"
echo ""
echo "View logs:"
echo "  sudo journalctl -u ase_surveillance -f"
echo ""
echo "Disable auto-start:"
echo "  sudo systemctl disable ase_surveillance"
echo ""
echo "========================================"
echo ""

# Ask if user wants to start now
read -p "Do you want to start the service now? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "🚀 Starting service..."
    systemctl start ase_surveillance
    sleep 2
    echo ""
    echo "📊 Service Status:"
    systemctl status ase_surveillance --no-pager
    echo ""
    echo -e "${GREEN}✅ Service is now running!${NC}"
else
    echo ""
    echo -e "${YELLOW}ℹ️  Service not started. Start manually with:${NC}"
    echo "  sudo systemctl start ase_surveillance"
fi

echo ""
echo "🎉 Setup complete! The system will auto-start on boot."
echo ""

# Cleanup
rm -f "$TEMP_SERVICE_FILE"
