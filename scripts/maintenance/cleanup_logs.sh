#!/bin/bash

################################################################################
# Log File Cleanup Script for ASE Surveillance System
# Version: 1.0.0
# Created: 2025-11-16
#
# Purpose:
#   Manages log file retention to prevent unlimited disk usage.
#   Implements automatic cleanup of old service logs.
#
# Retention Policy:
#   - Keep: Last 30 days of logs
#   - Delete: Logs older than 30 days
#   - Size limit: If total logs > 500MB, delete oldest first
#
# Files Managed:
#   - logs/surveillance_service.log (main service log)
#   - logs/*.log (any other log files)
#
# Usage:
#   ./cleanup_logs.sh [OPTIONS]
#
# Options:
#   --dry-run           Preview what will be deleted without making changes
#   --force             Skip confirmation prompt (for cron jobs)
#   --days N            Keep logs from last N days (default: 30)
#   --max-size N        Max total log size in MB (default: 500)
#   --help              Display usage information
#
# Examples:
#   # Dry run - preview deletions
#   ./cleanup_logs.sh --dry-run
#
#   # Keep only 7 days of logs
#   ./cleanup_logs.sh --days 7
#
#   # Automatic cleanup for cron jobs
#   ./cleanup_logs.sh --force
#
#   # Limit total log size to 200MB
#   ./cleanup_logs.sh --max-size 200
#
# Cron Integration:
#   Add to crontab to run daily at 2 AM:
#   0 2 * * * /path/to/cleanup_logs.sh --force >> /var/log/ase_log_cleanup.log 2>&1
#
# Features:
#   - Dry-run mode for safe previewing
#   - User confirmation before deletion
#   - Detailed logging of all operations
#   - Size-based and age-based cleanup
#   - Preserves current day's logs
#
################################################################################

# Exit on error
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default configuration
RETENTION_DAYS=30
MAX_SIZE_MB=500
DRY_RUN=false
FORCE=false

# Script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOGS_DIR="$PROJECT_ROOT/logs"

# Statistics
DELETED_COUNT=0
FREED_SPACE=0

################################################################################
# Functions
################################################################################

print_header() {
    echo -e "${BLUE}========================================"
    echo "ASE Surveillance System - Log Cleanup"
    echo "========================================"
    echo -e "Version: 1.0.0${NC}"
    echo ""
}

print_usage() {
    cat << EOF
Usage: $0 [OPTIONS]

Options:
  --dry-run           Preview what will be deleted without making changes
  --force             Skip confirmation prompt (for cron jobs)
  --days N            Keep logs from last N days (default: 30)
  --max-size N        Max total log size in MB (default: 500)
  --help              Display this help message

Examples:
  $0 --dry-run        # Preview deletions
  $0 --days 7         # Keep only 7 days
  $0 --force          # Auto cleanup (for cron)

EOF
}

check_logs_dir() {
    if [ ! -d "$LOGS_DIR" ]; then
        echo -e "${YELLOW}⚠️  Logs directory not found: $LOGS_DIR${NC}"
        echo "Creating logs directory..."
        mkdir -p "$LOGS_DIR"
        echo -e "${GREEN}✅ Created logs directory${NC}"
        exit 0
    fi
}

get_total_log_size() {
    # Returns total log size in MB
    if [ -d "$LOGS_DIR" ]; then
        du -sm "$LOGS_DIR" 2>/dev/null | awk '{print $1}' || echo "0"
    else
        echo "0"
    fi
}

get_file_size_mb() {
    # Returns file size in MB
    local file="$1"
    if [ -f "$file" ]; then
        du -m "$file" 2>/dev/null | awk '{print $1}' || echo "0"
    else
        echo "0"
    fi
}

cleanup_old_logs() {
    echo -e "${BLUE}📋 Cleanup Configuration:${NC}"
    echo "  Logs directory: $LOGS_DIR"
    echo "  Retention: Last $RETENTION_DAYS days"
    echo "  Max total size: ${MAX_SIZE_MB}MB"
    echo "  Mode: $([ "$DRY_RUN" = true ] && echo "DRY RUN" || echo "LIVE")"
    echo ""

    # Calculate cutoff date
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS
        CUTOFF_DATE=$(date -v-${RETENTION_DAYS}d +%Y%m%d)
    else
        # Linux
        CUTOFF_DATE=$(date -d "$RETENTION_DAYS days ago" +%Y%m%d)
    fi

    echo -e "${BLUE}🔍 Scanning for old log files...${NC}"
    echo "  Cutoff date: $CUTOFF_DATE"
    echo ""

    # Find and process old log files
    local found_old_files=false

    # Check for dated log files (surveillance_service.log.YYYYMMDD)
    if compgen -G "$LOGS_DIR/*.log.*" > /dev/null 2>&1; then
        for log_file in "$LOGS_DIR"/*.log.*; do
            [ -f "$log_file" ] || continue

            # Extract date from filename (assuming format: *.log.YYYYMMDD or *.log.N)
            filename=$(basename "$log_file")

            # Check if it's a date-based backup
            if [[ "$filename" =~ \.([0-9]{8})$ ]]; then
                file_date="${BASH_REMATCH[1]}"

                if [ "$file_date" -lt "$CUTOFF_DATE" ]; then
                    found_old_files=true
                    file_size=$(get_file_size_mb "$log_file")

                    echo -e "${YELLOW}  DELETE: $filename (${file_size}MB, date: $file_date)${NC}"

                    if [ "$DRY_RUN" = false ]; then
                        rm -f "$log_file"
                        DELETED_COUNT=$((DELETED_COUNT + 1))
                        FREED_SPACE=$((FREED_SPACE + file_size))
                    fi
                fi
            fi
        done
    fi

    if [ "$found_old_files" = false ]; then
        echo -e "${GREEN}  ✅ No old log files found (all logs within retention period)${NC}"
    fi

    echo ""
}

cleanup_by_size() {
    local total_size=$(get_total_log_size)

    echo -e "${BLUE}💾 Checking total log size...${NC}"
    echo "  Current size: ${total_size}MB"
    echo "  Limit: ${MAX_SIZE_MB}MB"
    echo ""

    if [ "$total_size" -le "$MAX_SIZE_MB" ]; then
        echo -e "${GREEN}✅ Total log size is within limit${NC}"
        return
    fi

    echo -e "${YELLOW}⚠️  Total log size exceeds limit!${NC}"
    echo -e "${YELLOW}   Need to free: $((total_size - MAX_SIZE_MB))MB${NC}"
    echo ""

    # Get list of log backup files sorted by age (oldest first)
    # Exclude the main log file (surveillance_service.log)
    local old_files=$(find "$LOGS_DIR" -name "*.log.*" -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | awk '{print $2}')

    if [ -z "$old_files" ]; then
        echo -e "${YELLOW}⚠️  No backup log files to delete${NC}"
        echo -e "${YELLOW}   Consider reducing retention period or archiving main log${NC}"
        return
    fi

    echo -e "${BLUE}🗑️  Deleting oldest log backups to free space...${NC}"

    for log_file in $old_files; do
        [ -f "$log_file" ] || continue

        file_size=$(get_file_size_mb "$log_file")
        filename=$(basename "$log_file")

        echo -e "${YELLOW}  DELETE: $filename (${file_size}MB)${NC}"

        if [ "$DRY_RUN" = false ]; then
            rm -f "$log_file"
            DELETED_COUNT=$((DELETED_COUNT + 1))
            FREED_SPACE=$((FREED_SPACE + file_size))
        fi

        # Check if we've freed enough space
        total_size=$(get_total_log_size)
        if [ "$total_size" -le "$MAX_SIZE_MB" ]; then
            echo -e "${GREEN}  ✅ Target size reached${NC}"
            break
        fi
    done

    echo ""
}

print_summary() {
    echo -e "${BLUE}========================================"
    echo "Cleanup Summary"
    echo "========================================${NC}"

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}Mode: DRY RUN (no files actually deleted)${NC}"
    else
        echo -e "${GREEN}Mode: LIVE${NC}"
    fi

    echo ""
    echo "Files deleted: $DELETED_COUNT"
    echo "Space freed: ${FREED_SPACE}MB"
    echo ""

    local final_size=$(get_total_log_size)
    echo "Final log size: ${final_size}MB"

    if [ "$final_size" -le "$MAX_SIZE_MB" ]; then
        echo -e "${GREEN}Status: ✅ Within size limit${NC}"
    else
        echo -e "${YELLOW}Status: ⚠️  Still exceeds size limit${NC}"
    fi

    echo ""
}

################################################################################
# Main Script
################################################################################

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        --days)
            RETENTION_DAYS="$2"
            shift 2
            ;;
        --max-size)
            MAX_SIZE_MB="$2"
            shift 2
            ;;
        --help)
            print_usage
            exit 0
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}"
            print_usage
            exit 1
            ;;
    esac
done

# Main execution
print_header
check_logs_dir

# Confirmation prompt (skip if --force or --dry-run)
if [ "$FORCE" = false ] && [ "$DRY_RUN" = false ]; then
    echo -e "${YELLOW}⚠️  This will delete log files older than $RETENTION_DAYS days${NC}"
    echo -e "${YELLOW}   and enforce a ${MAX_SIZE_MB}MB size limit.${NC}"
    echo ""
    read -p "Continue? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Cancelled by user${NC}"
        exit 0
    fi
    echo ""
fi

# Run cleanup
cleanup_old_logs
cleanup_by_size

# Print summary
print_summary

# Exit codes
if [ "$DRY_RUN" = true ]; then
    echo -e "${BLUE}ℹ️  Run without --dry-run to actually delete files${NC}"
    exit 0
elif [ "$DELETED_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✅ Cleanup completed successfully${NC}"
    exit 0
else
    echo -e "${GREEN}✅ No cleanup needed${NC}"
    exit 0
fi
