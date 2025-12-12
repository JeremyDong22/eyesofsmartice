#!/bin/bash
"""
Cron Jobs Installation Script for RTX 3060 Production System
Version: 1.0.0
Last Updated: 2025-11-14

Purpose: Install and manage cron jobs for automated restaurant surveillance system

Features:
- Recording schedules (11:30-14:00 lunch, 17:30-22:00 dinner)
- Processing schedule (00:00 midnight - previous day's videos)
- Cleanup schedule (03:00 daily - 2-day retention)
- Monitoring schedules (time sync hourly, disk space every 2h)
- Safe installation to user crontab (no root required)
- Backup existing crontab before changes
- Uninstall capability
- Status checking

Author: ASEOfSmartICE Team
"""

set -euo pipefail

# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# Cron marker for easy identification
CRON_MARKER="# RTX3060-PRODUCTION-SURVEILLANCE"
BACKUP_DIR="$PROJECT_DIR/backups"

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

print_header() {
    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}========================================${NC}\n"
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

print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_step() {
    echo -e "${MAGENTA}▸${NC} $1"
}

confirm_action() {
    local prompt="$1"
    local response
    read -p "$(echo -e "${YELLOW}?${NC} $prompt [y/N]: ")" response
    [[ "$response" =~ ^[Yy]$ ]]
}

# ============================================================================
# VALIDATION FUNCTIONS
# ============================================================================

check_prerequisites() {
    print_header "Checking Prerequisites"

    local all_ok=true

    # Check Python3
    if command -v python3 &> /dev/null; then
        print_success "python3 found: $(python3 --version)"
    else
        print_error "python3 not found"
        all_ok=false
    fi

    # Check scripts exist
    local required_scripts=(
        "video_capture/capture_rtsp_streams.py"
        "orchestration/process_videos_orchestrator.py"
        "maintenance/cleanup_old_videos.sh"
        "maintenance/cleanup_logs.sh"
        "time_sync/verify_time_sync.sh"
        "monitoring/check_disk_space.py"
    )

    for script in "${required_scripts[@]}"; do
        if [ -f "$SCRIPT_DIR/$script" ]; then
            print_success "Found: $script"
        else
            print_error "Missing: $script"
            all_ok=false
        fi
    done

    # Check if scripts are executable
    for script in "maintenance/cleanup_old_videos.sh" "maintenance/cleanup_logs.sh" "time_sync/verify_time_sync.sh"; do
        if [ -x "$SCRIPT_DIR/$script" ]; then
            print_success "$script is executable"
        else
            print_warning "$script is not executable (will be fixed)"
            chmod +x "$SCRIPT_DIR/$script" 2>/dev/null || true
        fi
    done

    # Check cron is available
    if command -v crontab &> /dev/null; then
        print_success "crontab command available"
    else
        print_error "crontab command not found"
        all_ok=false
    fi

    # Check timezone
    if command -v timedatectl &> /dev/null; then
        local current_tz=$(timedatectl | grep "Time zone" | awk '{print $3}' || echo "unknown")
        if [ "$current_tz" = "Asia/Shanghai" ]; then
            print_success "Timezone: Asia/Shanghai (Beijing time)"
        else
            print_warning "Timezone: $current_tz (expected Asia/Shanghai)"
            print_info "Run ./setup_ntp.sh to configure Beijing time"
        fi
    else
        print_warning "timedatectl not available (macOS?)"
        print_info "Cron jobs will use system local time"
    fi

    if [ "$all_ok" = false ]; then
        print_error "Prerequisites check failed"
        return 1
    fi

    print_success "All prerequisites satisfied"
    return 0
}

validate_paths() {
    print_header "Validating Paths"

    # Ensure directories exist
    local dirs=(
        "$PROJECT_DIR/videos"
        "$PROJECT_DIR/results"
        "$PROJECT_DIR/db"
        "$PROJECT_DIR/logs"
        "$BACKUP_DIR"
    )

    for dir in "${dirs[@]}"; do
        if [ ! -d "$dir" ]; then
            print_step "Creating: $dir"
            mkdir -p "$dir"
        fi
        print_success "Directory exists: $dir"
    done

    return 0
}

# ============================================================================
# CRON GENERATION
# ============================================================================

generate_cron_config() {
    print_header "Generating Cron Configuration"

    cat << 'CRONEOF'
# ============================================================================
# RTX 3060 Restaurant Surveillance System - Automated Schedule
# ============================================================================
# Installation Date: $(date '+%Y-%m-%d %H:%M:%S')
# Location: 野百灵火锅店, 1958商圈, Mianyang
# Hardware: RTX 3060 Linux Machine
#
# Schedule Overview:
# - Lunch recording:    11:30-14:00 (2.5 hours)
# - Dinner recording:   17:30-22:00 (4.5 hours)
# - Video processing:   00:00 (midnight, previous day's footage)
# - Cleanup:            03:00 (daily, 2-day retention)
# - Time sync check:    Every hour
# - Disk space check:   Every 2 hours
# ============================================================================
CRONEOF

    echo "$CRON_MARKER"
    echo ""

    # Recording Jobs
    cat << CRONEOF
# ============================================================================
# VIDEO RECORDING JOBS (Beijing Time)
# ============================================================================

# Lunch recording: 11:30 AM - 2:00 PM (2.5 hours = 9000 seconds)
30 11 * * * cd $PROJECT_DIR && python3 video_capture/capture_rtsp_streams.py --duration 9000 >> $PROJECT_DIR/logs/recording.log 2>&1

# Dinner recording: 5:30 PM - 10:00 PM (4.5 hours = 16200 seconds)
30 17 * * * cd $PROJECT_DIR && python3 video_capture/capture_rtsp_streams.py --duration 16200 >> $PROJECT_DIR/logs/recording.log 2>&1

CRONEOF

    # Processing Jobs
    cat << CRONEOF
# ============================================================================
# VIDEO PROCESSING JOBS
# ============================================================================

# Process previous day's videos at midnight (GPU queue management enabled)
0 0 * * * cd $PROJECT_DIR && python3 orchestration/process_videos_orchestrator.py --max-parallel 4 >> $PROJECT_DIR/logs/processing.log 2>&1

CRONEOF

    # Cleanup Jobs
    cat << CRONEOF
# ============================================================================
# CLEANUP JOBS
# ============================================================================

# Daily cleanup at 3 AM: Remove videos older than 2 days
0 3 * * * cd $PROJECT_DIR && bash maintenance/cleanup_old_videos.sh --force >> $PROJECT_DIR/logs/cleanup_videos.log 2>&1

# Daily log cleanup at 2 AM: Keep last 30 days, max 500MB
0 2 * * * cd $PROJECT_DIR && bash scripts/maintenance/cleanup_logs.sh --force >> $PROJECT_DIR/logs/cleanup_logs.log 2>&1

CRONEOF

    # Monitoring Jobs
    cat << CRONEOF
# ============================================================================
# MONITORING JOBS
# ============================================================================

# Time sync verification: Every hour
0 * * * * cd $PROJECT_DIR && bash time_sync/verify_time_sync.sh >> $PROJECT_DIR/logs/time_sync.log 2>&1

# Disk space check: Every 2 hours with automatic cleanup
0 */2 * * * cd $PROJECT_DIR && python3 scripts/monitoring/check_disk_space.py --cleanup >> $PROJECT_DIR/logs/disk_space.log 2>&1

# GPU health check: Every 5 minutes during processing window (11 PM - 7 AM)
# Only runs on Linux with nvidia-smi available
*/5 23-23,0-7 * * * command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total --format=csv,noheader >> $PROJECT_DIR/logs/gpu_health.log 2>&1 || true

CRONEOF

    # End marker
    echo ""
    echo "# End of RTX3060-PRODUCTION-SURVEILLANCE cron jobs"
    echo "$CRON_MARKER-END"
}

# ============================================================================
# INSTALLATION FUNCTIONS
# ============================================================================

backup_existing_crontab() {
    print_header "Backing Up Existing Crontab"

    # Create backup directory
    mkdir -p "$BACKUP_DIR"

    # Backup filename with timestamp
    local backup_file="$BACKUP_DIR/crontab_backup_$(date '+%Y%m%d_%H%M%S').txt"

    # Try to export existing crontab
    if crontab -l > "$backup_file" 2>/dev/null; then
        print_success "Existing crontab backed up to: $backup_file"
        echo "$backup_file"
        return 0
    else
        print_info "No existing crontab found (this is normal for first-time setup)"
        # Create empty backup file for consistency
        touch "$backup_file"
        echo "$backup_file"
        return 0
    fi
}

remove_old_cron_jobs() {
    print_header "Removing Old Cron Jobs"

    local temp_file=$(mktemp)

    # Export current crontab, filter out our jobs, save to temp
    if crontab -l > /dev/null 2>&1; then
        crontab -l | sed "/$CRON_MARKER/,/$CRON_MARKER-END/d" > "$temp_file"
        print_success "Removed old RTX3060-PRODUCTION-SURVEILLANCE jobs"
    else
        # No existing crontab
        touch "$temp_file"
        print_info "No existing crontab to clean"
    fi

    echo "$temp_file"
}

install_cron_jobs() {
    print_header "Installing Cron Jobs"

    # Backup existing crontab
    local backup_file=$(backup_existing_crontab)

    # Remove old jobs
    local clean_crontab=$(remove_old_cron_jobs)

    # Generate new jobs
    local temp_new=$(mktemp)
    generate_cron_config > "$temp_new"

    # Combine: existing (cleaned) + new jobs
    local final_crontab=$(mktemp)
    cat "$clean_crontab" "$temp_new" > "$final_crontab"

    # Install
    if crontab "$final_crontab"; then
        print_success "Cron jobs installed successfully!"

        # Show what was installed
        echo ""
        print_info "Installed jobs:"
        grep -E "^[^#].*" "$temp_new" | grep -v "^$" | while read line; do
            echo "  $line"
        done

        # Cleanup temp files
        rm -f "$clean_crontab" "$temp_new" "$final_crontab"

        return 0
    else
        print_error "Failed to install cron jobs"

        # Restore backup
        print_warning "Attempting to restore backup..."
        if [ -s "$backup_file" ]; then
            crontab "$backup_file" && print_success "Backup restored" || print_error "Backup restore failed"
        fi

        # Cleanup temp files
        rm -f "$clean_crontab" "$temp_new" "$final_crontab"

        return 1
    fi
}

# ============================================================================
# UNINSTALL FUNCTIONS
# ============================================================================

uninstall_cron_jobs() {
    print_header "Uninstalling Cron Jobs"

    # Backup first
    local backup_file=$(backup_existing_crontab)

    # Remove our jobs
    local clean_crontab=$(remove_old_cron_jobs)

    # Install cleaned crontab
    if crontab "$clean_crontab"; then
        print_success "RTX3060-PRODUCTION-SURVEILLANCE cron jobs removed"

        # Check if crontab is now empty
        if [ ! -s "$clean_crontab" ]; then
            print_info "Crontab is now empty"
            if confirm_action "Remove empty crontab entirely?"; then
                crontab -r
                print_success "Crontab removed"
            fi
        fi

        rm -f "$clean_crontab"
        return 0
    else
        print_error "Failed to uninstall cron jobs"

        # Restore backup
        print_warning "Attempting to restore backup..."
        if [ -s "$backup_file" ]; then
            crontab "$backup_file" && print_success "Backup restored" || print_error "Backup restore failed"
        fi

        rm -f "$clean_crontab"
        return 1
    fi
}

# ============================================================================
# STATUS FUNCTIONS
# ============================================================================

show_cron_status() {
    print_header "Current Cron Jobs Status"

    if ! crontab -l > /dev/null 2>&1; then
        print_info "No crontab installed for current user"
        return 1
    fi

    # Check if our jobs are installed
    if crontab -l | grep -q "$CRON_MARKER"; then
        print_success "RTX3060-PRODUCTION-SURVEILLANCE jobs are installed"
        echo ""

        # Show our jobs
        print_info "Installed jobs:"
        crontab -l | sed -n "/$CRON_MARKER/,/$CRON_MARKER-END/p" | grep -E "^[^#].*" | grep -v "^$" | nl -w2 -s'. '

        echo ""

        # Show next scheduled runs (if Linux)
        if command -v systemctl &> /dev/null; then
            print_info "Next scheduled run times:"
            print_info "(Note: Actual times depend on cron daemon)"

            local now=$(date '+%Y-%m-%d %H:%M')
            echo "  Current time: $now"
            echo ""
            echo "  Recording schedule:"
            echo "    - Lunch:  Daily at 11:30 (2.5 hours)"
            echo "    - Dinner: Daily at 17:30 (4.5 hours)"
            echo ""
            echo "  Processing:"
            echo "    - Midnight: 00:00 daily"
            echo ""
            echo "  Maintenance:"
            echo "    - Video cleanup: 03:00 daily (2-day retention)"
            echo "    - Log cleanup:   02:00 daily (30-day retention, 500MB limit)"
            echo ""
            echo "  Monitoring:"
            echo "    - Time sync:   Every hour"
            echo "    - Disk space:  Every 2 hours"
            echo "    - GPU health:  Every 5 min (11PM-7AM only)"
        fi

        return 0
    else
        print_warning "RTX3060-PRODUCTION-SURVEILLANCE jobs are NOT installed"
        print_info "Run with --install to install them"
        return 1
    fi
}

show_log_files() {
    print_header "Recent Log Files"

    local log_dir="$PROJECT_DIR/logs"

    if [ ! -d "$log_dir" ]; then
        print_warning "Log directory does not exist: $log_dir"
        return 1
    fi

    # Find recent logs
    local log_files=(
        "recording.log"
        "processing.log"
        "cleanup.log"
        "time_sync.log"
        "disk_space.log"
        "gpu_health.log"
    )

    for log_file in "${log_files[@]}"; do
        local full_path="$log_dir/$log_file"
        if [ -f "$full_path" ]; then
            local size=$(du -h "$full_path" | cut -f1)
            local modified=$(date -r "$full_path" '+%Y-%m-%d %H:%M' 2>/dev/null || stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$full_path" 2>/dev/null)
            print_success "$log_file ($size, modified: $modified)"
        else
            print_info "$log_file (not created yet)"
        fi
    done

    echo ""
    print_info "To view logs:"
    echo "  tail -f $log_dir/recording.log"
    echo "  tail -f $log_dir/processing.log"
    echo "  less $log_dir/cleanup.log"
}

# ============================================================================
# MAIN FUNCTION
# ============================================================================

show_usage() {
    cat << USAGE
Usage: $0 [OPTIONS]

Install and manage cron jobs for RTX 3060 production surveillance system.

Options:
  --install           Install cron jobs (backs up existing crontab)
  --uninstall         Remove cron jobs (backs up existing crontab)
  --status            Show current cron jobs status
  --logs              Show recent log files
  --preview           Preview cron configuration without installing
  --help              Show this help message

Examples:
  # Install cron jobs
  $0 --install

  # Check current status
  $0 --status

  # Preview what will be installed
  $0 --preview

  # Uninstall cron jobs
  $0 --uninstall

  # View log files
  $0 --logs

Schedule Details:
  Recording:  11:30-14:00 (lunch), 17:30-22:00 (dinner)
  Processing: 00:00 (midnight, previous day's videos)
  Cleanup:    03:00 (daily, 2-day retention)
  Monitoring: Hourly time sync, 2-hourly disk check, 5-min GPU check

Log Files:
  All logs stored in: $PROJECT_DIR/logs/
  - recording.log      (capture script output)
  - processing.log     (detection script output)
  - cleanup.log        (cleanup script output)
  - time_sync.log      (NTP verification)
  - disk_space.log     (disk usage alerts)
  - gpu_health.log     (GPU temperature & utilization)

Notes:
  - Requires Beijing time (Asia/Shanghai timezone)
  - Run ./setup_ntp.sh first to configure NTP
  - All jobs use absolute paths (safe for cron)
  - Backups saved to: $BACKUP_DIR/

USAGE
}

main() {
    # Parse arguments
    local action="${1:-}"

    if [ -z "$action" ]; then
        show_usage
        exit 0
    fi

    case "$action" in
        --install)
            print_header "RTX 3060 Cron Jobs Installation"
            echo "This will install automated scheduling for:"
            echo "  - Video recording (lunch & dinner)"
            echo "  - Video processing (midnight)"
            echo "  - Cleanup (3 AM daily)"
            echo "  - Monitoring (time sync, disk, GPU)"
            echo ""

            if ! confirm_action "Proceed with installation?"; then
                print_info "Installation cancelled"
                exit 0
            fi

            check_prerequisites || exit 1
            validate_paths || exit 1
            install_cron_jobs || exit 1

            echo ""
            print_success "Installation complete!"
            echo ""
            print_info "Next steps:"
            echo "  1. Verify timezone: timedatectl"
            echo "  2. Check status: $0 --status"
            echo "  3. Monitor logs: tail -f $PROJECT_DIR/logs/recording.log"
            echo "  4. Test manually: cd $PROJECT_DIR && python3 video_capture/capture_rtsp_streams.py --duration 60"
            ;;

        --uninstall)
            print_header "RTX 3060 Cron Jobs Uninstallation"

            if ! confirm_action "Remove all RTX3060-PRODUCTION-SURVEILLANCE cron jobs?"; then
                print_info "Uninstallation cancelled"
                exit 0
            fi

            uninstall_cron_jobs || exit 1

            echo ""
            print_success "Uninstallation complete!"
            print_info "Backups preserved in: $BACKUP_DIR/"
            ;;

        --status)
            show_cron_status
            ;;

        --logs)
            show_log_files
            ;;

        --preview)
            print_header "Cron Configuration Preview"
            generate_cron_config
            echo ""
            print_info "This is what will be installed with --install"
            ;;

        --help|-h)
            show_usage
            ;;

        *)
            print_error "Unknown option: $action"
            echo ""
            show_usage
            exit 1
            ;;
    esac
}

# Run main function
main "$@"
