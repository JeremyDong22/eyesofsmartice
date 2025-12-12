#!/bin/bash
# deploy.sh v1.0.0
# Created: 2025-12-13
# One-command production deployment for ASE Restaurant Surveillance System
#
# Usage: sudo ./deploy.sh
#
# This script does everything:
# 1. Configure system (cameras, ROI, settings)
# 2. Install systemd daemon (auto-restart on crash, auto-start on boot)
# 3. Install cron jobs (recording, processing, cleanup, monitoring)
# 4. Add daily reboot at 23:00 (system health)
# 5. Start the service

set -e

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYMENT_DIR="$SCRIPT_DIR/scripts/deployment"
REBOOT_HOUR=23
REBOOT_MINUTE=0

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

print_banner() {
    echo ""
    echo -e "${CYAN}${BOLD}======================================================================${NC}"
    echo -e "${CYAN}${BOLD}  ASE Restaurant Surveillance System - Production Deployment${NC}"
    echo -e "${CYAN}${BOLD}======================================================================${NC}"
    echo ""
}

print_step() {
    echo -e "\n${CYAN}${BOLD}[$1/5] $2${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${RED}${BOLD}Error: This script must be run with sudo${NC}"
        echo ""
        echo "Usage:"
        echo "  sudo ./deploy.sh"
        echo ""
        exit 1
    fi
}

# ============================================================================
# STEP 1: CONFIGURATION
# ============================================================================

run_configuration() {
    print_step "1" "System Configuration"

    echo "Launching configuration wizard..."
    echo "(Configure cameras, ROI, and system settings)"
    echo ""

    # Run as the original user, not root
    SUDO_USER_HOME=$(getent passwd "$SUDO_USER" | cut -d: -f6)

    if [ -f "$SCRIPT_DIR/main.py" ]; then
        # Run configuration as the original user
        sudo -u "$SUDO_USER" python3 "$SCRIPT_DIR/main.py" --configure || {
            print_warning "Configuration skipped or failed"
            read -p "Continue with deployment anyway? (y/n): " response
            if [[ ! "$response" =~ ^[Yy]$ ]]; then
                echo "Deployment cancelled."
                exit 1
            fi
        }
        print_success "Configuration complete"
    else
        print_warning "main.py not found, skipping configuration"
    fi
}

# ============================================================================
# STEP 2: INSTALL SYSTEMD SERVICE
# ============================================================================

install_systemd_service() {
    print_step "2" "Installing Systemd Daemon"

    local service_file="$DEPLOYMENT_DIR/ase_surveillance.service"
    local systemd_dir="/etc/systemd/system"

    if [ ! -f "$service_file" ]; then
        print_error "Service file not found: $service_file"
        exit 1
    fi

    # Copy service file
    cp "$service_file" "$systemd_dir/"
    print_success "Copied service file to $systemd_dir/"

    # Reload systemd
    systemctl daemon-reload
    print_success "Reloaded systemd daemon"

    # Enable auto-start on boot
    systemctl enable ase_surveillance
    print_success "Enabled auto-start on boot"
}

# ============================================================================
# STEP 3: INSTALL CRON JOBS
# ============================================================================

install_cron_jobs() {
    print_step "3" "Installing Cron Jobs (Recording, Processing, Cleanup)"

    local cron_script="$DEPLOYMENT_DIR/install_cron_jobs.sh"

    if [ ! -f "$cron_script" ]; then
        print_warning "Cron jobs script not found: $cron_script"
        print_warning "Skipping cron jobs installation"
        return
    fi

    # Make executable
    chmod +x "$cron_script"

    # Run as original user (cron jobs don't need root)
    sudo -u "$SUDO_USER" bash "$cron_script" --install --yes 2>/dev/null || {
        # If --yes not supported, try without it
        echo "y" | sudo -u "$SUDO_USER" bash "$cron_script" --install
    }

    print_success "Cron jobs installed (recording, processing, cleanup, monitoring)"
}

# ============================================================================
# STEP 4: ADD DAILY REBOOT
# ============================================================================

add_daily_reboot() {
    print_step "4" "Adding Daily Reboot (23:00 - System Health)"

    local cron_marker="# ASE_DAILY_REBOOT"
    local cron_job="$REBOOT_MINUTE $REBOOT_HOUR * * * /sbin/reboot $cron_marker"

    # Check if already exists
    if crontab -l 2>/dev/null | grep -q "$cron_marker"; then
        print_warning "Daily reboot already configured, updating..."
        # Remove old entry
        crontab -l 2>/dev/null | grep -v "$cron_marker" | crontab -
    fi

    # Add new entry to root's crontab
    (crontab -l 2>/dev/null; echo "$cron_job") | crontab -

    print_success "Daily reboot scheduled at ${REBOOT_HOUR}:00"
    print_success "System will auto-restart daemon after reboot"
}

# ============================================================================
# STEP 5: START SERVICE
# ============================================================================

start_service() {
    print_step "5" "Starting Service"

    if systemctl is-active --quiet ase_surveillance; then
        print_warning "Service already running, restarting..."
        systemctl restart ase_surveillance
    else
        systemctl start ase_surveillance
    fi

    # Wait a moment for service to start
    sleep 2

    # Check status
    if systemctl is-active --quiet ase_surveillance; then
        print_success "Service started successfully"
    else
        print_error "Service failed to start"
        echo ""
        echo "Check logs with:"
        echo "  sudo journalctl -u ase_surveillance -n 50"
        exit 1
    fi
}

# ============================================================================
# SUMMARY
# ============================================================================

show_summary() {
    echo ""
    echo -e "${GREEN}${BOLD}======================================================================${NC}"
    echo -e "${GREEN}${BOLD}  DEPLOYMENT COMPLETE!${NC}"
    echo -e "${GREEN}${BOLD}======================================================================${NC}"
    echo ""

    echo -e "${BOLD}Protection Layers Active:${NC}"
    echo "  Layer 1: Daily reboot at 23:00 (system health)"
    echo "  Layer 2: Systemd daemon (auto-restart on crash)"
    echo "  Layer 3: Auto-start on boot"
    echo ""

    echo -e "${BOLD}Scheduled Tasks:${NC}"
    echo "  11:30      Lunch recording starts"
    echo "  14:00      Lunch recording ends"
    echo "  17:30      Dinner recording starts"
    echo "  22:00      Dinner recording ends"
    echo "  23:00      System reboot (health maintenance)"
    echo "  00:00      Video processing starts"
    echo "  02:00      Log cleanup"
    echo "  03:00      Video cleanup"
    echo ""

    echo -e "${BOLD}Management Commands:${NC}"
    echo "  sudo systemctl status ase_surveillance    # Check status"
    echo "  sudo systemctl restart ase_surveillance   # Restart"
    echo "  sudo systemctl stop ase_surveillance      # Stop"
    echo "  sudo journalctl -u ase_surveillance -f    # View logs"
    echo "  sudo crontab -l                           # View scheduled tasks"
    echo ""

    echo -e "${BOLD}Current Service Status:${NC}"
    systemctl status ase_surveillance --no-pager -l | head -10
    echo ""

    echo -e "${GREEN}${BOLD}======================================================================${NC}"
    echo -e "${GREEN}${BOLD}  System is now running! No further action needed.${NC}"
    echo -e "${GREEN}${BOLD}======================================================================${NC}"
    echo ""
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    print_banner
    check_root

    echo -e "${BOLD}This script will:${NC}"
    echo "  1. Configure system (cameras, ROI, settings)"
    echo "  2. Install systemd daemon (auto-restart)"
    echo "  3. Install cron jobs (recording, processing, cleanup)"
    echo "  4. Add daily reboot at 23:00"
    echo "  5. Start the service"
    echo ""

    read -p "Proceed with deployment? (y/n): " response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "Deployment cancelled."
        exit 0
    fi

    run_configuration
    install_systemd_service
    install_cron_jobs
    add_daily_reboot
    start_service
    show_summary
}

main "$@"
