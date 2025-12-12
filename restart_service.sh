#!/bin/bash
# Modified: 2025-11-20 - Created restart helper with verbose output
# Feature: Provides clear feedback when restarting surveillance service

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Restaurant Surveillance Service - Restart"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if service exists
if ! systemctl list-unit-files | grep -q ase_surveillance; then
    echo "❌ ERROR: Service 'ase_surveillance' not found"
    exit 1
fi

# Get current status
echo "📊 Current Status:"
systemctl is-active ase_surveillance > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✓ Service is RUNNING"
else
    echo "   ✗ Service is STOPPED"
fi
echo ""

# Restart
echo "🔄 Restarting service..."
sudo systemctl restart ase_surveillance

if [ $? -eq 0 ]; then
    echo "   ✓ Restart command successful"
else
    echo "   ❌ Restart command failed"
    exit 1
fi

# Wait for startup
echo ""
echo "⏳ Waiting for service to start..."
sleep 3

# Check new status
echo ""
echo "📊 New Status:"
systemctl is-active ase_surveillance > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✓ Service is RUNNING"

    # Get PID
    PID=$(systemctl show -p MainPID --value ase_surveillance)
    if [ "$PID" != "0" ]; then
        echo "   ✓ Process ID: $PID"
    fi

    # Get uptime
    SINCE=$(systemctl show -p ActiveEnterTimestamp --value ase_surveillance)
    echo "   ✓ Started: $SINCE"
else
    echo "   ❌ Service FAILED to start"
    echo ""
    echo "Error details:"
    systemctl status ase_surveillance --no-pager -l | tail -20
    exit 1
fi

# Show recent logs
echo ""
echo "📝 Recent Logs (last 10 lines):"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
journalctl -u ase_surveillance -n 10 --no-pager

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Service restart complete!"
echo ""
echo "To view live logs: sudo journalctl -u ase_surveillance -f"
echo "To check status:   sudo systemctl status ase_surveillance"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
