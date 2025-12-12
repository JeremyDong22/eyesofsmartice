#!/bin/bash
# Quick Camera Test - One-liner for rapid camera validation
# Version: 1.0.0
# Usage: ./quick_camera_test.sh 202.168.40.35 202.168.40.22 ...

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ $# -eq 0 ]; then
    echo "Usage: $0 <camera_ip_1> [camera_ip_2] [camera_ip_3] ..."
    echo ""
    echo "Examples:"
    echo "  $0 202.168.40.35"
    echo "  $0 202.168.40.35 202.168.40.22"
    echo "  $0 202.168.40.35 202.168.40.22 202.168.40.40"
    echo ""
    echo "Or use run_camera_test.sh for interactive mode"
    exit 1
fi

echo "Quick camera test for: $@"
echo ""

python3 test_camera_connections.py --ips "$@"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo ""
    echo "✅ Test PASSED - At least one camera is working"
else
    echo ""
    echo "❌ Test FAILED - All cameras failed"
fi

exit $exit_code
