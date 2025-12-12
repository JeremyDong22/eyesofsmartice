#!/bin/bash

################################################################################
# Video Retention Cleanup Script for RTX 3060 Restaurant Systems
# Version: 1.0.0
#
# Purpose:
#   Manages video file retention on restaurant Linux machines running RTX 3060.
#   Implements "save-one-day, analyze-one-day, record-one-day" retention policy
#   by keeping only the last 2 days of videos, results, and screenshots.
#
# Retention Policy:
#   - Keep: Today's files + Yesterday's files
#   - Delete: Anything older than 2 days (48 hours)
#
# Directory Structure Cleaned:
#   1. videos/YYYYMMDD/camera_*/ - raw video files
#   2. results/YYYYMMDD/camera_*/ - processed detection results
#   3. db/screenshots/camera_*/YYYYMMDD/ - session screenshots
#
# Usage:
#   ./cleanup_old_videos.sh [OPTIONS]
#
# Options:
#   --dry-run           Preview what will be deleted without making changes
#   --force             Skip confirmation prompt (for cron jobs)
#   --archive DIR       Move files to archive directory instead of deleting
#   --help              Display usage information
#
# Examples:
#   # Dry run - preview deletions
#   ./cleanup_old_videos.sh --dry-run
#
#   # Interactive cleanup with confirmation
#   ./cleanup_old_videos.sh
#
#   # Automatic cleanup for cron jobs
#   ./cleanup_old_videos.sh --force
#
#   # Archive old files instead of deleting
#   ./cleanup_old_videos.sh --archive /mnt/backup/
#
# Cron Integration:
#   Add to crontab to run daily at 3 AM:
#   0 3 * * * /path/to/cleanup_old_videos.sh --force >> /var/log/rtx3060/cleanup/cron.log 2>&1
#
# Features:
#   - Dry-run mode for safe previewing
#   - User confirmation before deletion
#   - Detailed logging of all operations
#   - Archive option to move instead of delete
#   - Disk space calculation and reporting
#   - Exclusion of current day and database files
#   - Preserves .uploaded marker files
#   - Color-coded output for readability
#
# Author: Created for RTX 3060 Restaurant Automation
# Last Updated: 2025-11-14
################################################################################

set -o pipefail

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Configuration
RETENTION_DAYS=2
DRY_RUN=false
FORCE_MODE=false
ARCHIVE_DIR=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"

# Logging configuration
LOG_DIR="/var/log/rtx3060/cleanup"
LOG_FILE="${LOG_DIR}/$(date +%Y%m%d).log"

# Data directories
VIDEOS_DIR="${BASE_DIR}/videos"
RESULTS_DIR="${BASE_DIR}/results"
SCREENSHOTS_DIR="${BASE_DIR}/db/screenshots"

# Tracking variables
TOTAL_SIZE_TO_FREE=0
FILES_TO_DELETE=0
DIRS_TO_DELETE=0
ARCHIVE_DETAILS=()

################################################################################
# Helper Functions
################################################################################

# Initialize logging
init_logging() {
    mkdir -p "$LOG_DIR" 2>/dev/null
    if [[ ! -w "$LOG_DIR" ]]; then
        echo -e "${YELLOW}Warning: Cannot write to $LOG_DIR, using /tmp for logs${NC}"
        LOG_DIR="/tmp/rtx3060_cleanup"
        mkdir -p "$LOG_DIR"
    fi
    LOG_FILE="${LOG_DIR}/$(date +%Y%m%d).log"

    {
        echo "================================================================================"
        echo "Video Retention Cleanup Started"
        echo "Date: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "Retention Policy: Keep last ${RETENTION_DAYS} days"
        echo "Dry Run: ${DRY_RUN}"
        echo "Force Mode: ${FORCE_MODE}"
        echo "================================================================================"
    } >> "$LOG_FILE"
}

# Log messages to file and optionally to console
log_message() {
    local level=$1
    local message=$2
    local console=${3:-true}

    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${timestamp}] [${level}] ${message}" >> "$LOG_FILE"

    if [[ "$console" == "true" ]]; then
        case $level in
            "ERROR")
                echo -e "${RED}[ERROR]${NC} ${message}"
                ;;
            "WARN")
                echo -e "${YELLOW}[WARN]${NC} ${message}"
                ;;
            "SUCCESS")
                echo -e "${GREEN}[SUCCESS]${NC} ${message}"
                ;;
            "INFO")
                echo -e "${BLUE}[INFO]${NC} ${message}"
                ;;
            *)
                echo "[${level}] ${message}"
                ;;
        esac
    fi
}

# Display help message
show_help() {
    cat << 'EOF'
Video Retention Cleanup Script
Version: 1.0.0

Usage: ./cleanup_old_videos.sh [OPTIONS]

OPTIONS:
    --dry-run               Preview what will be deleted without making changes
    --force                 Skip confirmation prompt (for automated cron jobs)
    --archive DIR           Move files to archive directory instead of deleting
    --help                  Display this help message

EXAMPLES:
    # Dry run - preview deletions
    ./cleanup_old_videos.sh --dry-run

    # Interactive cleanup with confirmation
    ./cleanup_old_videos.sh

    # Automatic cleanup for cron jobs
    ./cleanup_old_videos.sh --force

    # Archive old files instead of deleting
    ./cleanup_old_videos.sh --archive /mnt/backup/

RETENTION POLICY:
    Keep: Today's files + Yesterday's files
    Delete: Anything older than 2 days (48 hours)

DIRECTORIES MANAGED:
    - videos/YYYYMMDD/camera_*/
    - results/YYYYMMDD/camera_*/
    - db/screenshots/camera_*/YYYYMMDD/

CRON INTEGRATION:
    Add to crontab for daily 3 AM cleanup:
    0 3 * * * /path/to/cleanup_old_videos.sh --force >> /var/log/rtx3060/cleanup/cron.log 2>&1

For more information, see the script comments.
EOF
}

# Parse command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --force)
                FORCE_MODE=true
                shift
                ;;
            --archive)
                ARCHIVE_DIR="$2"
                shift 2
                ;;
            --help)
                show_help
                exit 0
                ;;
            *)
                echo -e "${RED}Unknown option: $1${NC}"
                show_help
                exit 1
                ;;
        esac
    done

    # Validate archive directory if specified
    if [[ -n "$ARCHIVE_DIR" ]]; then
        if [[ ! -d "$ARCHIVE_DIR" ]]; then
            echo -e "${RED}Error: Archive directory does not exist: $ARCHIVE_DIR${NC}"
            exit 1
        fi
        if [[ ! -w "$ARCHIVE_DIR" ]]; then
            echo -e "${RED}Error: Archive directory is not writable: $ARCHIVE_DIR${NC}"
            exit 1
        fi
    fi
}

# Calculate cutoff date (older than this will be deleted)
get_cutoff_date() {
    # macOS and Linux compatible date calculation
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        date -v-${RETENTION_DAYS}d '+%Y%m%d'
    else
        # Linux
        date -d "${RETENTION_DAYS} days ago" '+%Y%m%d'
    fi
}

# Get current and yesterday dates
get_current_date() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        date '+%Y%m%d'
    else
        date '+%Y%m%d'
    fi
}

get_yesterday_date() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        date -v-1d '+%Y%m%d'
    else
        date -d "yesterday" '+%Y%m%d'
    fi
}

# Format bytes to human-readable size
format_size() {
    local bytes=$1
    if (( bytes >= 1073741824 )); then
        echo "$(( bytes / 1073741824 )).$(( (bytes % 1073741824) / 107374182 )) GB"
    elif (( bytes >= 1048576 )); then
        echo "$(( bytes / 1048576 )).$(( (bytes % 1048576) / 104857 )) MB"
    elif (( bytes >= 1024 )); then
        echo "$(( bytes / 1024 )).$(( (bytes % 1024) / 102 )) KB"
    else
        echo "$bytes B"
    fi
}

# Calculate size of a file or directory
calculate_size() {
    local path=$1
    if [[ -f "$path" ]]; then
        stat -f%z "$path" 2>/dev/null || stat -c%s "$path" 2>/dev/null || echo 0
    elif [[ -d "$path" ]]; then
        du -sk "$path" 2>/dev/null | awk '{print $1 * 1024}' || echo 0
    else
        echo 0
    fi
}

# Check if a date string represents current or yesterday
is_preserve_date() {
    local date_str=$1
    local current_date=$(get_current_date)
    local yesterday_date=$(get_yesterday_date)

    [[ "$date_str" == "$current_date" ]] || [[ "$date_str" == "$yesterday_date" ]]
}

# Scan and process videos directory
scan_videos_directory() {
    local cutoff_date=$(get_cutoff_date)

    echo -e "\n${BOLD}Scanning videos directory...${NC}"
    log_message "INFO" "Scanning videos directory (older than ${cutoff_date})"

    if [[ ! -d "$VIDEOS_DIR" ]]; then
        log_message "WARN" "Videos directory does not exist: $VIDEOS_DIR"
        return
    fi

    local old_count=0

    # Find all date directories in videos/
    for date_dir in "$VIDEOS_DIR"/*; do
        if [[ ! -d "$date_dir" ]]; then
            continue
        fi

        local date_str=$(basename "$date_dir")

        # Validate date format (YYYYMMDD)
        if ! [[ "$date_str" =~ ^[0-9]{8}$ ]]; then
            continue
        fi

        # Skip if this is today or yesterday
        if is_preserve_date "$date_str"; then
            continue
        fi

        # Check if older than retention period
        if [[ "$date_str" -lt "$cutoff_date" ]]; then
            old_count=$((old_count + 1))

            # Process camera subdirectories
            for camera_dir in "$date_dir"/camera_*; do
                if [[ -d "$camera_dir" ]]; then
                    local size=$(calculate_size "$camera_dir")
                    TOTAL_SIZE_TO_FREE=$((TOTAL_SIZE_TO_FREE + size))
                    DIRS_TO_DELETE=$((DIRS_TO_DELETE + 1))

                    log_message "INFO" "Found old directory: $camera_dir ($(format_size $size))" false
                    ARCHIVE_DETAILS+=("$camera_dir:$size")
                fi
            done
        fi
    done

    if [[ $old_count -gt 0 ]]; then
        echo -e "  ${YELLOW}Found ${old_count} old date directories${NC}"
        log_message "SUCCESS" "Videos scan complete: found $old_count old directories"
    else
        echo "  ${GREEN}No old videos to clean${NC}"
    fi
}

# Scan and process results directory
scan_results_directory() {
    local cutoff_date=$(get_cutoff_date)

    echo -e "\n${BOLD}Scanning results directory...${NC}"
    log_message "INFO" "Scanning results directory (older than ${cutoff_date})"

    if [[ ! -d "$RESULTS_DIR" ]]; then
        log_message "WARN" "Results directory does not exist: $RESULTS_DIR"
        return
    fi

    local old_count=0

    # Find all date directories in results/
    for date_dir in "$RESULTS_DIR"/*; do
        if [[ ! -d "$date_dir" ]]; then
            continue
        fi

        local date_str=$(basename "$date_dir")

        # Validate date format (YYYYMMDD)
        if ! [[ "$date_str" =~ ^[0-9]{8}$ ]]; then
            continue
        fi

        # Skip if this is today or yesterday
        if is_preserve_date "$date_str"; then
            continue
        fi

        # Check if older than retention period
        if [[ "$date_str" -lt "$cutoff_date" ]]; then
            old_count=$((old_count + 1))

            # Process camera subdirectories
            for camera_dir in "$date_dir"/camera_*; do
                if [[ -d "$camera_dir" ]]; then
                    local size=$(calculate_size "$camera_dir")
                    TOTAL_SIZE_TO_FREE=$((TOTAL_SIZE_TO_FREE + size))
                    DIRS_TO_DELETE=$((DIRS_TO_DELETE + 1))

                    log_message "INFO" "Found old directory: $camera_dir ($(format_size $size))" false
                    ARCHIVE_DETAILS+=("$camera_dir:$size")
                fi
            done
        fi
    done

    if [[ $old_count -gt 0 ]]; then
        echo -e "  ${YELLOW}Found ${old_count} old date directories${NC}"
        log_message "SUCCESS" "Results scan complete: found $old_count old directories"
    else
        echo "  ${GREEN}No old results to clean${NC}"
    fi
}

# Scan and process screenshots directory
scan_screenshots_directory() {
    local cutoff_date=$(get_cutoff_date)

    echo -e "\n${BOLD}Scanning screenshots directory...${NC}"
    log_message "INFO" "Scanning screenshots directory (older than ${cutoff_date})"

    if [[ ! -d "$SCREENSHOTS_DIR" ]]; then
        log_message "WARN" "Screenshots directory does not exist: $SCREENSHOTS_DIR"
        return
    fi

    local old_count=0

    # Find all camera directories
    for camera_dir in "$SCREENSHOTS_DIR"/camera_*; do
        if [[ ! -d "$camera_dir" ]]; then
            continue
        fi

        # Find date directories within each camera
        for date_dir in "$camera_dir"/*; do
            if [[ ! -d "$date_dir" ]]; then
                continue
            fi

            local date_str=$(basename "$date_dir")

            # Validate date format (YYYYMMDD)
            if ! [[ "$date_str" =~ ^[0-9]{8}$ ]]; then
                continue
            fi

            # Skip if this is today or yesterday
            if is_preserve_date "$date_str"; then
                continue
            fi

            # Check if older than retention period
            if [[ "$date_str" -lt "$cutoff_date" ]]; then
                old_count=$((old_count + 1))

                # Process session subdirectories
                for session_dir in "$date_dir"/*; do
                    if [[ -d "$session_dir" ]]; then
                        local size=$(calculate_size "$session_dir")
                        TOTAL_SIZE_TO_FREE=$((TOTAL_SIZE_TO_FREE + size))
                        DIRS_TO_DELETE=$((DIRS_TO_DELETE + 1))

                        log_message "INFO" "Found old directory: $session_dir ($(format_size $size))" false
                        ARCHIVE_DETAILS+=("$session_dir:$size")
                    fi
                done
            fi
        done
    done

    if [[ $old_count -gt 0 ]]; then
        echo -e "  ${YELLOW}Found ${old_count} old session directories${NC}"
        log_message "SUCCESS" "Screenshots scan complete: found $old_count old directories"
    else
        echo "  ${GREEN}No old screenshots to clean${NC}"
    fi
}

# Display summary and ask for confirmation
display_summary_and_confirm() {
    local cutoff_date=$(get_cutoff_date)
    local retention_start=$(get_yesterday_date)

    echo -e "\n${BOLD}=== Video Retention Cleanup Summary ===${NC}"
    echo -e "Date: $(date '+%Y-%m-%d')"
    echo -e "Retention Policy: Last ${RETENTION_DAYS} days (keep >= ${retention_start})"
    echo -e "Cutoff Date: Anything older than ${cutoff_date}"

    echo -e "\n${BOLD}Cleanup Details:${NC}"
    echo -e "  Directories to process: ${YELLOW}${DIRS_TO_DELETE}${NC}"
    echo -e "  Total space to free: ${YELLOW}$(format_size $TOTAL_SIZE_TO_FREE)${NC}"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo -e "\n${YELLOW}DRY RUN MODE${NC} - No files will be deleted"
    fi

    if [[ -n "$ARCHIVE_DIR" ]]; then
        echo -e "\n${BLUE}Archive Mode Enabled${NC}"
        echo -e "  Archive destination: ${ARCHIVE_DIR}"
    fi

    # Log summary
    log_message "INFO" "Summary: ${DIRS_TO_DELETE} directories, $(format_size $TOTAL_SIZE_TO_FREE) total" false

    if [[ "$DRY_RUN" == "true" ]]; then
        log_message "INFO" "Dry run completed - no changes made"
        return 0
    fi

    if [[ "$FORCE_MODE" == "true" ]]; then
        log_message "INFO" "Force mode enabled - proceeding without confirmation"
        return 0
    fi

    # Ask for confirmation
    echo -e "\n${BOLD}Proceed with cleanup?${NC} [y/N]: "
    read -r response

    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Cleanup cancelled by user${NC}"
        log_message "WARN" "Cleanup cancelled by user"
        return 1
    fi

    return 0
}

# Delete or archive a directory
process_directory() {
    local dir=$1
    local size=$2

    if [[ ! -e "$dir" ]]; then
        return
    fi

    if [[ -n "$ARCHIVE_DIR" ]]; then
        # Archive mode - move files
        local relative_path="${dir#$BASE_DIR/}"
        local archive_path="${ARCHIVE_DIR}/${relative_path}"
        local archive_parent=$(dirname "$archive_path")

        mkdir -p "$archive_parent" 2>/dev/null

        if mv "$dir" "$archive_path" 2>/dev/null; then
            log_message "INFO" "Archived: $dir -> $archive_path"
            return 0
        else
            log_message "ERROR" "Failed to archive: $dir"
            return 1
        fi
    else
        # Delete mode
        if rm -rf "$dir" 2>/dev/null; then
            log_message "INFO" "Deleted: $dir (freed $(format_size $size))"
            return 0
        else
            log_message "ERROR" "Failed to delete: $dir"
            return 1
        fi
    fi
}

# Execute cleanup for videos
cleanup_videos() {
    if [[ "$DRY_RUN" == "true" ]]; then
        return
    fi

    echo -e "\n${BOLD}Cleaning up videos...${NC}"
    log_message "INFO" "Starting videos cleanup"

    local cutoff_date=$(get_cutoff_date)
    local deleted=0

    for date_dir in "$VIDEOS_DIR"/*; do
        if [[ ! -d "$date_dir" ]]; then
            continue
        fi

        local date_str=$(basename "$date_dir")

        if ! [[ "$date_str" =~ ^[0-9]{8}$ ]]; then
            continue
        fi

        if is_preserve_date "$date_str"; then
            continue
        fi

        if [[ "$date_str" -lt "$cutoff_date" ]]; then
            for camera_dir in "$date_dir"/camera_*; do
                if [[ -d "$camera_dir" ]]; then
                    local size=$(calculate_size "$camera_dir")
                    if process_directory "$camera_dir" "$size"; then
                        deleted=$((deleted + 1))
                    fi
                fi
            done
        fi
    done

    echo -e "  ${GREEN}Deleted ${deleted} video directories${NC}"
    log_message "SUCCESS" "Videos cleanup complete: deleted $deleted directories"
}

# Execute cleanup for results
cleanup_results() {
    if [[ "$DRY_RUN" == "true" ]]; then
        return
    fi

    echo -e "\n${BOLD}Cleaning up results...${NC}"
    log_message "INFO" "Starting results cleanup"

    local cutoff_date=$(get_cutoff_date)
    local deleted=0

    for date_dir in "$RESULTS_DIR"/*; do
        if [[ ! -d "$date_dir" ]]; then
            continue
        fi

        local date_str=$(basename "$date_dir")

        if ! [[ "$date_str" =~ ^[0-9]{8}$ ]]; then
            continue
        fi

        if is_preserve_date "$date_str"; then
            continue
        fi

        if [[ "$date_str" -lt "$cutoff_date" ]]; then
            for camera_dir in "$date_dir"/camera_*; do
                if [[ -d "$camera_dir" ]]; then
                    local size=$(calculate_size "$camera_dir")
                    if process_directory "$camera_dir" "$size"; then
                        deleted=$((deleted + 1))
                    fi
                fi
            done
        fi
    done

    echo -e "  ${GREEN}Deleted ${deleted} results directories${NC}"
    log_message "SUCCESS" "Results cleanup complete: deleted $deleted directories"
}

# Execute cleanup for screenshots
cleanup_screenshots() {
    if [[ "$DRY_RUN" == "true" ]]; then
        return
    fi

    echo -e "\n${BOLD}Cleaning up screenshots...${NC}"
    log_message "INFO" "Starting screenshots cleanup"

    local cutoff_date=$(get_cutoff_date)
    local deleted=0

    for camera_dir in "$SCREENSHOTS_DIR"/camera_*; do
        if [[ ! -d "$camera_dir" ]]; then
            continue
        fi

        for date_dir in "$camera_dir"/*; do
            if [[ ! -d "$date_dir" ]]; then
                continue
            fi

            local date_str=$(basename "$date_dir")

            if ! [[ "$date_str" =~ ^[0-9]{8}$ ]]; then
                continue
            fi

            if is_preserve_date "$date_str"; then
                continue
            fi

            if [[ "$date_str" -lt "$cutoff_date" ]]; then
                for session_dir in "$date_dir"/*; do
                    if [[ -d "$session_dir" ]]; then
                        local size=$(calculate_size "$session_dir")
                        if process_directory "$session_dir" "$size"; then
                            deleted=$((deleted + 1))
                        fi
                    fi
                done
            fi
        done
    done

    echo -e "  ${GREEN}Deleted ${deleted} screenshot directories${NC}"
    log_message "SUCCESS" "Screenshots cleanup complete: deleted $deleted directories"
}

# Display final summary
display_final_summary() {
    echo -e "\n${BOLD}=== Cleanup Complete ===${NC}"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo -e "${YELLOW}Dry run mode - no changes were made${NC}"
        echo -e "To execute the cleanup, run without --dry-run flag"
    elif [[ -n "$ARCHIVE_DIR" ]]; then
        echo -e "${GREEN}Files archived successfully${NC}"
        echo -e "  Destination: ${ARCHIVE_DIR}"
        echo -e "  Space freed: $(format_size $TOTAL_SIZE_TO_FREE)"
    else
        echo -e "${GREEN}Cleanup completed successfully${NC}"
        echo -e "  Space freed: $(format_size $TOTAL_SIZE_TO_FREE)"
    fi

    echo -e "\nLog file: ${BLUE}${LOG_FILE}${NC}"

    {
        echo ""
        echo "================================================================================"
        echo "Cleanup Completed"
        echo "Date: $(date '+%Y-%m-%d %H:%M:%S')"
        echo "Space freed: $(format_size $TOTAL_SIZE_TO_FREE)"
        echo "Directories processed: ${DIRS_TO_DELETE}"
        echo "================================================================================"
    } >> "$LOG_FILE"
}

################################################################################
# Main Execution
################################################################################

main() {
    # Parse arguments
    parse_arguments "$@"

    # Initialize logging
    init_logging

    echo -e "${BOLD}=== Video Retention Cleanup Script ===${NC}"
    echo -e "Version: 1.0.0"
    echo -e "Base Directory: ${BASE_DIR}"

    if [[ "$DRY_RUN" == "true" ]]; then
        echo -e "${YELLOW}[DRY RUN MODE]${NC} - No files will be modified"
    fi

    # Scan all directories
    scan_videos_directory
    scan_results_directory
    scan_screenshots_directory

    # Check if there's anything to cleanup
    if [[ $DIRS_TO_DELETE -eq 0 ]]; then
        echo -e "\n${GREEN}No old files found. Cleanup not needed.${NC}"
        log_message "INFO" "No old files found - cleanup not needed"
        display_final_summary
        exit 0
    fi

    # Display summary and get confirmation
    if ! display_summary_and_confirm; then
        exit 0
    fi

    # Execute cleanup
    cleanup_videos
    cleanup_results
    cleanup_screenshots

    # Display final summary
    display_final_summary

    exit 0
}

# Execute main function
main "$@"
