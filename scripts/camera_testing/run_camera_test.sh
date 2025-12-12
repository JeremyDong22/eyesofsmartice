#!/bin/bash
# Camera Connection Test Runner
# Version: 1.0.0
# Quick test runner for camera connectivity validation

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=================================================="
echo "Camera Connection Test System"
echo "=================================================="
echo ""
echo "Choose test mode:"
echo "1) Test cameras from existing config (cameras_config.json)"
echo "2) Test specific IP addresses"
echo "3) Interactive mode (enter IPs manually)"
echo ""
read -p "Select option (1-3): " choice

case $choice in
    1)
        if [ -f "../config/cameras_config.json" ]; then
            echo ""
            echo "Testing all cameras in cameras_config.json..."
            python3 test_camera_connections.py --validate-config ../config/cameras_config.json
        else
            echo ""
            echo "Error: cameras_config.json not found in config/"
            exit 1
        fi
        ;;
    2)
        echo ""
        read -p "Enter camera IPs (space separated): " ips
        if [ -z "$ips" ]; then
            echo "Error: No IPs provided"
            exit 1
        fi
        echo ""
        echo "Testing cameras: $ips"
        python3 test_camera_connections.py --ips $ips
        ;;
    3)
        echo ""
        python3 test_camera_connections.py --interactive
        ;;
    *)
        echo "Invalid option"
        exit 1
        ;;
esac

echo ""
echo "=================================================="
echo "Test completed!"
echo "=================================================="
