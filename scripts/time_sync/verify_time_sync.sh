#!/bin/bash
#
# NTP Time Synchronization Verification Script
# Version 1.0
# Purpose: Verify system time is synchronized with Chinese NTP servers
#
# This script:
# 1. Checks system timezone is Asia/Shanghai
# 2. Verifies NTP synchronization is enabled
# 3. Validates time offset is within acceptable range (< 5 seconds)
# 4. Queries multiple Chinese NTP servers for redundancy
# 5. Logs results to /var/log/rtx3060/monitoring/time_sync.log
# 6. Returns exit code 0 if synced, 1 if not
#
# Usage:
#   ./verify_time_sync.sh                 # Run verification
#   ./verify_time_sync.sh --verbose       # Verbose output
#   ./verify_time_sync.sh --test          # Dry-run mode (for Mac testing)

set -u

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="/var/log/rtx3060/monitoring"
LOG_FILE="${LOG_DIR}/time_sync.log"
LOCK_FILE="/tmp/verify_time_sync.lock"
TIMEOUT=10  # seconds for NTP queries

# NTP servers (Chinese priority)
NTP_SERVERS=(
    "ntp.aliyun.com"
    "ntp1.aliyun.com"
    "time1.cloud.tencent.com"
)

# Thresholds
MAX_TIME_OFFSET=5  # seconds
MAX_LOG_SIZE=10485760  # 10MB

# Flags
VERBOSE=${VERBOSE:-0}
TEST_MODE=${TEST_MODE:-0}

# Color codes (disabled if not TTY)
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'  # No Color
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

# Functions
log_message() {
    local level="$1"
    local message="$2"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')

    # Ensure log directory exists
    if [[ ! -d "$LOG_DIR" ]]; then
        if [[ "$TEST_MODE" == "0" ]]; then
            mkdir -p "$LOG_DIR" 2>/dev/null || {
                echo "ERROR: Cannot create log directory $LOG_DIR" >&2
                return 1
            }
        fi
    fi

    # Rotate log if too large
    if [[ -f "$LOG_FILE" ]]; then
        local size=$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null || echo 0)
        if [[ $size -gt $MAX_LOG_SIZE ]]; then
            if [[ "$TEST_MODE" == "0" ]]; then
                mv "$LOG_FILE" "${LOG_FILE}.$(date +%s)" 2>/dev/null || true
            fi
        fi
    fi

    # Write log
    if [[ "$TEST_MODE" == "0" ]]; then
        echo "$timestamp [$level] $message" >> "$LOG_FILE" 2>/dev/null || true
    fi

    # Console output
    if [[ "$level" == "INFO" ]]; then
        echo -e "${BLUE}$timestamp${NC} [${BLUE}INFO${NC}] $message"
    elif [[ "$level" == "OK" ]]; then
        echo -e "${BLUE}$timestamp${NC} [${GREEN}OK${NC}] $message"
    elif [[ "$level" == "WARN" ]]; then
        echo -e "${BLUE}$timestamp${NC} [${YELLOW}WARN${NC}] $message"
    elif [[ "$level" == "ERROR" ]]; then
        echo -e "${BLUE}$timestamp${NC} [${RED}ERROR${NC}] $message" >&2
    fi
}

print_status() {
    local check_name="$1"
    local status="$2"
    local value="$3"

    if [[ "$status" == "PASS" ]]; then
        echo -e "  ${BLUE}$(date '+%Y-%m-%d %H:%M:%S')${NC} [${GREEN}✓${NC}] $check_name: $value"
    elif [[ "$status" == "FAIL" ]]; then
        echo -e "  ${BLUE}$(date '+%Y-%m-%d %H:%M:%S')${NC} [${RED}✗${NC}] $check_name: $value"
    fi
}

check_timezone() {
    local current_tz

    if [[ "$TEST_MODE" == "1" ]]; then
        # Mac test mode
        current_tz=$(date +%Z)
        echo "MOCK_ASIA_SHANGHAI"
        return 0
    fi

    # Check systemd timedatectl (preferred)
    if command -v timedatectl &>/dev/null; then
        current_tz=$(timedatectl show-timezone --no-pager 2>/dev/null | grep -oP 'Timezone=\K.*')
    fi

    # Fallback to /etc/timezone
    if [[ -z "$current_tz" ]] && [[ -f /etc/timezone ]]; then
        current_tz=$(cat /etc/timezone 2>/dev/null)
    fi

    # Fallback to readlink
    if [[ -z "$current_tz" ]] && [[ -L /etc/localtime ]]; then
        current_tz=$(readlink /etc/localtime 2>/dev/null | sed 's|.*zoneinfo/||')
    fi

    echo "$current_tz"
}

check_ntp_enabled() {
    if [[ "$TEST_MODE" == "1" ]]; then
        # Mac test mode
        echo "enabled"
        return 0
    fi

    # Check if systemd-timesyncd is running
    if systemctl is-active --quiet systemd-timesyncd 2>/dev/null; then
        echo "enabled"
        return 0
    fi

    # Check if ntpd is running
    if pgrep -x "ntpd" > /dev/null 2>&1; then
        echo "enabled"
        return 0
    fi

    # Check timedatectl NTP sync
    if command -v timedatectl &>/dev/null; then
        local ntp_sync=$(timedatectl show-timesync --no-pager 2>/dev/null | grep -i "system-clock-synchronized=yes")
        if [[ -n "$ntp_sync" ]]; then
            echo "enabled"
            return 0
        fi
    fi

    echo "disabled"
    return 1
}

get_ntp_offset() {
    local server="$1"
    local offset_seconds=""

    if [[ "$TEST_MODE" == "1" ]]; then
        # Mac test mode - return mock value
        echo "0.123"
        return 0
    fi

    # Try ntpq if available
    if command -v ntpq &>/dev/null; then
        offset_seconds=$(ntpq -pc rv "$server" 2>/dev/null | grep "offset=" | sed 's/.*offset=\([0-9.-]*\).*/\1/')
        if [[ -n "$offset_seconds" ]]; then
            # ntpq returns offset in milliseconds, convert to seconds
            echo "scale=3; $offset_seconds / 1000" | bc 2>/dev/null || echo "$offset_seconds"
            return 0
        fi
    fi

    # Try ntpstat if available
    if command -v ntpstat &>/dev/null; then
        local ntp_status=$(ntpstat 2>/dev/null)
        if echo "$ntp_status" | grep -q "synchronised"; then
            offset_seconds=$(echo "$ntp_status" | grep -oP 'offset of \K[0-9.]*')
            if [[ -n "$offset_seconds" ]]; then
                echo "$offset_seconds"
                return 0
            fi
        fi
    fi

    # Try using timedatectl show-timesync
    if command -v timedatectl &>/dev/null; then
        local ntp_status=$(timedatectl show-timesync --no-pager 2>/dev/null)
        if echo "$ntp_status" | grep -q "system-clock-synchronized=yes"; then
            offset_seconds=$(echo "$ntp_status" | grep "clock-epoch-usec=" | head -1 | sed 's/.*clock-epoch-usec=\([0-9.-]*\).*/\1/')
            if [[ -n "$offset_seconds" ]]; then
                # Convert microseconds to seconds
                echo "scale=6; $offset_seconds / 1000000" | bc 2>/dev/null || echo "$offset_seconds"
                return 0
            fi
        fi
    fi

    # Fallback: Try to query NTP server directly (requires ntpdate or similar)
    if command -v sntp &>/dev/null; then
        offset_seconds=$(sntp -S -c 1 "$server" 2>/dev/null | grep -oP 'offset \K[0-9.-]*')
        if [[ -n "$offset_seconds" ]]; then
            echo "$offset_seconds"
            return 0
        fi
    fi

    return 1
}

query_ntp_server() {
    local server="$1"
    local result=""

    if [[ "$TEST_MODE" == "1" ]]; then
        echo "online"
        return 0
    fi

    # Try ping with timeout
    if ping -c 1 -W 2 "$server" >/dev/null 2>&1; then
        echo "online"
        return 0
    fi

    # Fallback timeout method for macOS
    if timeout 2 bash -c "echo > /dev/tcp/$server/123" 2>/dev/null; then
        echo "online"
        return 0
    fi

    echo "offline"
    return 1
}

check_ntp_servers() {
    local online_servers=0
    local total_servers=${#NTP_SERVERS[@]}

    for server in "${NTP_SERVERS[@]}"; do
        local status=$(query_ntp_server "$server")
        if [[ "$status" == "online" ]]; then
            ((online_servers++))
            print_status "NTP Server $server" "PASS" "online"
        else
            print_status "NTP Server $server" "FAIL" "offline"
        fi
    done

    # Check if at least one server is reachable
    if [[ $online_servers -gt 0 ]]; then
        return 0
    else
        return 1
    fi
}

main() {
    local exit_code=0

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --verbose)
                VERBOSE=1
                shift
                ;;
            --test)
                TEST_MODE=1
                shift
                ;;
            *)
                echo "Usage: $0 [--verbose] [--test]" >&2
                return 1
                ;;
        esac
    done

    # Prevent concurrent execution
    if [[ -f "$LOCK_FILE" ]]; then
        local lock_age=$(($(date +%s) - $(stat -f%m "$LOCK_FILE" 2>/dev/null || stat -c%Y "$LOCK_FILE" 2>/dev/null)))
        if [[ $lock_age -lt 300 ]]; then  # 5 minutes
            log_message "WARN" "Another verification is already running. Skipping."
            return 0
        fi
    fi

    # Create lock file
    if [[ "$TEST_MODE" == "0" ]]; then
        mkdir -p "$(dirname "$LOCK_FILE")" 2>/dev/null || true
        echo $$ > "$LOCK_FILE" 2>/dev/null || true
        trap "rm -f \"$LOCK_FILE\"" EXIT
    fi

    log_message "INFO" "Starting NTP time synchronization verification"

    # Check 1: Timezone
    echo ""
    local tz=$(check_timezone)
    if [[ "$tz" == "Asia/Shanghai" ]] || [[ "$tz" == "MOCK_ASIA_SHANGHAI" ]]; then
        print_status "Timezone" "PASS" "Asia/Shanghai"
        log_message "INFO" "Timezone check: PASS (Asia/Shanghai)"
    else
        print_status "Timezone" "FAIL" "$tz (expected Asia/Shanghai)"
        log_message "ERROR" "Timezone check: FAIL - Expected Asia/Shanghai, got $tz"
        exit_code=1
    fi

    # Check 2: NTP Enabled
    local ntp_status=$(check_ntp_enabled)
    if [[ "$ntp_status" == "enabled" ]]; then
        print_status "NTP Synchronization" "PASS" "enabled"
        log_message "INFO" "NTP sync check: PASS (enabled)"
    else
        print_status "NTP Synchronization" "FAIL" "not enabled"
        log_message "ERROR" "NTP sync check: FAIL - NTP not enabled"
        exit_code=1
    fi

    # Check 3: NTP Servers
    echo ""
    if check_ntp_servers; then
        log_message "INFO" "NTP servers check: PASS - At least one server is reachable"
    else
        log_message "ERROR" "NTP servers check: FAIL - No NTP servers are reachable"
        exit_code=1
    fi

    # Check 4: Time Offset
    echo ""
    local offset=$(get_ntp_offset "${NTP_SERVERS[0]}" 2>/dev/null || echo "")
    if [[ -n "$offset" ]]; then
        # Convert offset to absolute value
        local abs_offset=$(echo "$offset" | sed 's/-//' | bc 2>/dev/null || echo "$offset")

        if (( $(echo "$abs_offset < $MAX_TIME_OFFSET" | bc -l 2>/dev/null || echo "1") )); then
            print_status "Time Offset" "PASS" "${abs_offset} seconds"
            log_message "INFO" "Time offset check: PASS (${abs_offset} seconds, threshold: ${MAX_TIME_OFFSET}s)"
        else
            print_status "Time Offset" "FAIL" "${abs_offset} seconds (threshold: ${MAX_TIME_OFFSET}s)"
            log_message "WARN" "Time offset check: FAIL - Offset ${abs_offset}s exceeds threshold ${MAX_TIME_OFFSET}s"
            exit_code=1
        fi
    else
        log_message "INFO" "Time offset check: SKIPPED - Unable to query offset"
        print_status "Time Offset" "FAIL" "unable to query (see logs)"
        exit_code=1
    fi

    # Final result
    echo ""
    if [[ $exit_code -eq 0 ]]; then
        echo -e "${GREEN}[OK]${NC} Time synchronization is healthy"
        log_message "OK" "Time synchronization verification completed successfully"
    else
        echo -e "${RED}[FAIL]${NC} Time synchronization has issues"
        log_message "ERROR" "Time synchronization verification failed"
    fi

    return $exit_code
}

main "$@"
exit $?
