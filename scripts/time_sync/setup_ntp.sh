#!/bin/bash
#
# NTP Setup and Configuration Script
# Version 1.0
# Purpose: One-time setup to configure system time synchronization for Beijing timezone
#
# This script:
# 1. Sets timezone to Asia/Shanghai
# 2. Configures systemd-timesyncd with Chinese NTP servers
# 3. Enables NTP synchronization service
# 4. Verifies setup by running verification script
# 5. Creates log directory and cron job for hourly verification
#
# Usage:
#   sudo ./setup_ntp.sh                    # Run full setup
#   sudo ./setup_ntp.sh --verify-only      # Skip setup, just verify
#   sudo ./setup_ntp.sh --test             # Test mode (Mac compatible)
#
# Requirements:
#   - Root or sudo access
#   - systemd-timesyncd installed (standard on modern Linux)
#   - timedatectl command available

set -u

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY_SCRIPT="${SCRIPT_DIR}/verify_time_sync.sh"
LOG_DIR="/var/log/rtx3060/monitoring"
LOG_FILE="${LOG_DIR}/time_sync.log"
SYSTEMD_CONFIG="/etc/systemd/timesyncd.conf"
CRON_JOB_USER="root"
CRON_MINUTE="0"  # Every hour at minute 00

# Chinese NTP servers
NTP_SERVERS=(
    "ntp.aliyun.com"
    "ntp1.aliyun.com"
    "time1.cloud.tencent.com"
)

# Flags
VERIFY_ONLY=${VERIFY_ONLY:-0}
TEST_MODE=${TEST_MODE:-0}

# Color codes
if [[ -t 1 ]]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

# Functions
log() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

success() {
    echo -e "${GREEN}[OK]${NC} $*"
}

warning() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

error() {
    echo -e "${RED}[ERROR]${NC} $*" >&2
}

check_root() {
    if [[ $EUID -ne 0 ]]; then
        error "This script must be run as root or with sudo"
        echo "Usage: sudo ./setup_ntp.sh" >&2
        return 1
    fi
    return 0
}

check_dependencies() {
    log "Checking dependencies..."

    local missing_deps=0

    if ! command -v timedatectl &>/dev/null && [[ "$TEST_MODE" != "1" ]]; then
        warning "timedatectl not found (required for systemd)"
        missing_deps=1
    fi

    if ! command -v systemctl &>/dev/null && [[ "$TEST_MODE" != "1" ]]; then
        warning "systemctl not found (required for service management)"
        missing_deps=1
    fi

    if ! command -v date &>/dev/null; then
        error "date command not found"
        return 1
    fi

    if [[ "$TEST_MODE" == "1" ]]; then
        success "Test mode enabled - skipping actual dependency checks"
        return 0
    fi

    if [[ $missing_deps -eq 0 ]]; then
        success "All dependencies found"
        return 0
    else
        warning "Some dependencies missing, but will proceed with available tools"
        return 0
    fi
}

setup_timezone() {
    log "Setting timezone to Asia/Shanghai..."

    if [[ "$TEST_MODE" == "1" ]]; then
        log "TEST MODE: Would set timezone to Asia/Shanghai"
        return 0
    fi

    # Method 1: timedatectl (preferred, systemd)
    if command -v timedatectl &>/dev/null; then
        if timedatectl set-timezone Asia/Shanghai 2>/dev/null; then
            success "Timezone set using timedatectl"
            return 0
        fi
    fi

    # Method 2: Create /etc/timezone file
    if echo "Asia/Shanghai" > /etc/timezone 2>/dev/null; then
        success "Timezone set via /etc/timezone"
    else
        error "Failed to set timezone"
        return 1
    fi

    # Method 3: Symlink /etc/localtime
    if [[ -f /usr/share/zoneinfo/Asia/Shanghai ]]; then
        if ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime 2>/dev/null; then
            success "Timezone symlink updated"
            return 0
        fi
    else
        error "Zone file /usr/share/zoneinfo/Asia/Shanghai not found"
        return 1
    fi

    return 0
}

setup_ntp_servers() {
    log "Configuring NTP servers..."

    if [[ "$TEST_MODE" == "1" ]]; then
        log "TEST MODE: Would configure NTP servers"
        return 0
    fi

    # Check if systemd-timesyncd exists
    if ! command -v systemctl &>/dev/null || ! systemctl list-unit-files | grep -q timesyncd.service; then
        warning "systemd-timesyncd not available, attempting to install..."

        # Try to install chrony or ntp as fallback
        if command -v apt-get &>/dev/null; then
            apt-get update -qq && apt-get install -y systemd-timesyncd 2>/dev/null || {
                warning "Failed to install systemd-timesyncd, trying chrony..."
                apt-get install -y chrony 2>/dev/null || {
                    error "Failed to install NTP software"
                    return 1
                }
            }
        elif command -v yum &>/dev/null; then
            yum install -y systemd-timesyncd 2>/dev/null || {
                warning "Failed to install systemd-timesyncd, trying chrony..."
                yum install -y chrony 2>/dev/null || {
                    error "Failed to install NTP software"
                    return 1
                }
            }
        else
            warning "No package manager found, assuming NTP is already installed"
        fi
    fi

    # Configure systemd-timesyncd
    if [[ -f "$SYSTEMD_CONFIG" ]] || [[ "$SYSTEMD_CONFIG" == "/etc/systemd/timesyncd.conf" ]]; then
        log "Creating NTP server configuration at $SYSTEMD_CONFIG..."

        # Create config with proper permissions
        cat > "$SYSTEMD_CONFIG" << EOF
# systemd-timesyncd configuration
# Configured by setup_ntp.sh on $(date)
# Synchronized with Chinese NTP servers for Beijing timezone

[Time]
# NTP servers (Chinese region servers for better reliability)
NTP=$(IFS=' '; echo "${NTP_SERVERS[*]}")
FallbackNTP=pool.ntp.org

# Connection settings
ConnectionRetrySec=10min
SaveInterval=60min
EOF

        if [[ -f "$SYSTEMD_CONFIG" ]]; then
            success "NTP configuration created"
        else
            error "Failed to create NTP configuration"
            return 1
        fi
    else
        error "Cannot determine NTP configuration file location"
        return 1
    fi

    return 0
}

enable_ntp_service() {
    log "Enabling NTP synchronization service..."

    if [[ "$TEST_MODE" == "1" ]]; then
        log "TEST MODE: Would enable NTP service"
        return 0
    fi

    if ! command -v systemctl &>/dev/null; then
        warning "systemctl not available, skipping service enablement"
        return 0
    fi

    # Enable and start systemd-timesyncd
    if systemctl enable systemd-timesyncd 2>/dev/null; then
        success "systemd-timesyncd enabled"
    else
        warning "Failed to enable systemd-timesyncd service"
    fi

    # Start the service
    if systemctl start systemd-timesyncd 2>/dev/null; then
        success "systemd-timesyncd started"
        sleep 2  # Wait for NTP to sync
    else
        warning "Failed to start systemd-timesyncd service"
    fi

    # Verify service is running
    if systemctl is-active --quiet systemd-timesyncd 2>/dev/null; then
        success "systemd-timesyncd is running"
        return 0
    else
        warning "systemd-timesyncd is not running"
        return 1
    fi
}

setup_log_directory() {
    log "Setting up log directory at $LOG_DIR..."

    if [[ "$TEST_MODE" == "1" ]]; then
        log "TEST MODE: Would create log directory at $LOG_DIR"
        return 0
    fi

    if mkdir -p "$LOG_DIR" 2>/dev/null; then
        # Set permissions (644 for files created inside)
        chmod 755 "$LOG_DIR" 2>/dev/null || true
        success "Log directory created"
        return 0
    else
        error "Failed to create log directory"
        return 1
    fi
}

setup_cron_job() {
    log "Setting up hourly verification cron job..."

    if [[ "$TEST_MODE" == "1" ]]; then
        log "TEST MODE: Would create cron job"
        cat << EOF

Proposed cron job (would be added for $CRON_JOB_USER):
  $CRON_MINUTE * * * * $VERIFY_SCRIPT >> $LOG_FILE 2>&1

EOF
        return 0
    fi

    # Create temporary cron file
    local temp_cron=$(mktemp)
    local cron_entry="$CRON_MINUTE * * * * $VERIFY_SCRIPT >> $LOG_FILE 2>&1"

    # Get existing crontab for the user
    if crontab -u "$CRON_JOB_USER" -l 2>/dev/null > "$temp_cron"; then
        # Check if job already exists
        if grep -q "verify_time_sync.sh" "$temp_cron"; then
            warning "Cron job already exists, skipping"
            rm -f "$temp_cron"
            return 0
        fi
    else
        # No existing crontab, create empty one
        > "$temp_cron"
    fi

    # Add new cron job
    echo "$cron_entry" >> "$temp_cron"

    # Install new crontab
    if crontab -u "$CRON_JOB_USER" "$temp_cron" 2>/dev/null; then
        success "Cron job installed for user $CRON_JOB_USER"
        success "Verification will run every hour at minute 00"
        rm -f "$temp_cron"
        return 0
    else
        error "Failed to install cron job"
        rm -f "$temp_cron"
        return 1
    fi
}

verify_setup() {
    log "Verifying NTP setup..."
    echo ""

    if [[ ! -f "$VERIFY_SCRIPT" ]]; then
        error "Verification script not found at $VERIFY_SCRIPT"
        return 1
    fi

    # Make sure script is executable
    chmod +x "$VERIFY_SCRIPT" 2>/dev/null || true

    # Run verification
    if [[ "$TEST_MODE" == "1" ]]; then
        bash "$VERIFY_SCRIPT" --test
    else
        bash "$VERIFY_SCRIPT"
    fi

    local verify_exit=$?

    echo ""
    if [[ $verify_exit -eq 0 ]]; then
        success "NTP setup verified successfully"
        return 0
    else
        warning "NTP verification found issues (see above)"
        return 1
    fi
}

print_setup_summary() {
    cat << EOF

${GREEN}===============================================${NC}
${GREEN}NTP Setup Summary${NC}
${GREEN}===============================================${NC}

Timezone: Asia/Shanghai
NTP Servers: ${NTP_SERVERS[*]}
Configuration: $SYSTEMD_CONFIG
Log Directory: $LOG_DIR
Verification Script: $VERIFY_SCRIPT
Cron Job: $CRON_MINUTE * * * * (every hour)

Next Steps:
1. The system will now synchronize time with Chinese NTP servers
2. Time verification will run automatically every hour
3. Check logs at: $LOG_FILE
4. Manual verification: $VERIFY_SCRIPT

${GREEN}===============================================${NC}

EOF
}

main() {
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --verify-only)
                VERIFY_ONLY=1
                shift
                ;;
            --test)
                TEST_MODE=1
                shift
                ;;
            *)
                echo "Usage: sudo ./setup_ntp.sh [--verify-only] [--test]" >&2
                return 1
                ;;
        esac
    done

    # Check root access
    if [[ "$TEST_MODE" != "1" ]]; then
        if ! check_root; then
            return 1
        fi
    fi

    echo ""
    log "Starting NTP setup for RTX 3060 (Beijing timezone)"
    echo ""

    # If verify-only mode, skip setup steps
    if [[ "$VERIFY_ONLY" == "1" ]]; then
        warning "Verify-only mode: skipping configuration steps"
        echo ""
    else
        # Check dependencies
        if ! check_dependencies; then
            return 1
        fi

        echo ""

        # Setup steps
        if ! setup_timezone; then
            error "Failed to set timezone"
            return 1
        fi

        if ! setup_ntp_servers; then
            error "Failed to configure NTP servers"
            return 1
        fi

        if ! enable_ntp_service; then
            error "Failed to enable NTP service"
            return 1
        fi

        if ! setup_log_directory; then
            error "Failed to setup log directory"
            return 1
        fi

        if ! setup_cron_job; then
            error "Failed to setup cron job"
            return 1
        fi

        echo ""
        print_setup_summary
    fi

    # Run verification
    if ! verify_setup; then
        warning "Setup completed with verification warnings"
        return 1
    fi

    success "NTP setup completed successfully!"
    return 0
}

main "$@"
exit $?
