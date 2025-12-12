# Maintenance Scripts - Algorithm Documentation

**Version:** 2.0.0
**Last Updated:** 2025-12-13
**Purpose:** Automated cleanup algorithms for disk space management and log retention

---

## Overview

The maintenance directory contains two core cleanup scripts implementing intelligent retention policies for the surveillance system. These scripts prevent disk space exhaustion through automated, policy-based cleanup of videos, processed results, screenshots, and logs.

**Core Philosophy:**
- **Proactive Prevention** - Regular cleanup before space runs out
- **Layered Retention** - Different policies for different data types
- **Safety First** - Protect recent data, support dry-run previews
- **Flexible Configuration** - Support archive mode, force mode, custom parameters

**Scripts:**
1. `cleanup_old_videos.sh` - Video retention cleanup (2-day policy)
2. `cleanup_logs.sh` - Log file cleanup (30-day + 500MB policy)

---

## Retention Policies Summary

| Data Type | Retention | Script | Frequency |
|-----------|-----------|--------|-----------|
| **Raw Videos** | 2 days (today + yesterday) | cleanup_old_videos.sh | Daily 3:00 AM |
| **Processed Results** | 2 days (today + yesterday) | cleanup_old_videos.sh | Daily 3:00 AM |
| **Screenshots** | 2 days (today + yesterday) | cleanup_old_videos.sh | Daily 3:00 AM |
| **Service Logs** | 30 days + 500MB limit | cleanup_logs.sh | Daily 2:00 AM |
| **Database** | ∞ Permanent | - | Never deleted |

**Note:** Database (detection_data.db) is permanently retained, containing all business analytics data.

---

## 1. Video Retention Cleanup Algorithm

**File:** `cleanup_old_videos.sh`
**Version:** 1.0.0
**Retention Policy:** "Save-One-Day, Analyze-One-Day, Record-One-Day"

### 1.1 Date Calculation Algorithm

**Problem:** Need cross-platform date arithmetic to determine cutoff dates.

**Algorithm:**

```bash
# Platform-aware date calculation
get_cutoff_date() {
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # macOS (BSD date)
        date -v-${RETENTION_DAYS}d '+%Y%m%d'
    else
        # Linux (GNU date)
        date -d "${RETENTION_DAYS} days ago" '+%Y%m%d'
    fi
}

# Example outputs:
# Today: 20251213
# Yesterday: 20251212
# Cutoff (2 days ago): 20251211
```

**Parameters:**
- `RETENTION_DAYS`: Number of days to keep (default: 2)
- Date format: `YYYYMMDD` (enables numeric comparison)

**Code Location:** Lines 235-244, 247-261

---

### 1.2 Date Preservation Logic

**Problem:** Must protect current and recent data from deletion.

**Algorithm:**

```bash
is_preserve_date() {
    local date_str=$1
    local current_date=$(get_current_date)      # e.g., 20251213
    local yesterday_date=$(get_yesterday_date)  # e.g., 20251212

    # Return true (0) if date matches today OR yesterday
    [[ "$date_str" == "$current_date" ]] || [[ "$date_str" == "$yesterday_date" ]]
}

# Usage in cleanup:
if is_preserve_date "$date_str"; then
    continue  # Skip deletion, preserve this date
fi

if [[ "$date_str" -lt "$cutoff_date" ]]; then
    # Delete: date is older than cutoff
fi
```

**Parameters:**
- `date_str`: Date string in YYYYMMDD format
- Returns: 0 (true) to preserve, 1 (false) to delete

**Code Location:** Lines 289-296

---

### 1.3 Directory Scanning Algorithm

**Problem:** Need to find and size all old directories across multiple locations.

**Algorithm:**

```
┌─────────────────────────────────────────┐
│ 1. Scan Videos Directory                │
│    videos/YYYYMMDD/camera_*/            │
├─────────────────────────────────────────┤
│ FOR each date_dir in videos/*:          │
│   ├─ Validate date format (YYYYMMDD)    │
│   ├─ Skip if preserve_date()            │
│   ├─ Check if date < cutoff_date        │
│   └─ FOR each camera_dir:               │
│       ├─ Calculate size                 │
│       ├─ Add to TOTAL_SIZE_TO_FREE      │
│       └─ Add to ARCHIVE_DETAILS[]       │
└─────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────┐
│ 2. Scan Results Directory               │
│    results/YYYYMMDD/camera_*/           │
│    (Same logic as videos)               │
└─────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────┐
│ 3. Scan Screenshots Directory           │
│    db/screenshots/camera_*/YYYYMMDD/    │
├─────────────────────────────────────────┤
│ FOR each camera_dir:                    │
│   └─ FOR each date_dir in camera_dir:   │
│       ├─ Validate date format           │
│       ├─ Skip if preserve_date()        │
│       ├─ Check if date < cutoff_date    │
│       └─ FOR each session_dir:          │
│           ├─ Calculate size             │
│           ├─ Add to TOTAL_SIZE_TO_FREE  │
│           └─ Add to ARCHIVE_DETAILS[]   │
└─────────────────────────────────────────┘
```

**Parameters:**
- `cutoff_date`: Calculated from `get_cutoff_date()`
- `TOTAL_SIZE_TO_FREE`: Accumulator for total size (bytes)
- `DIRS_TO_DELETE`: Counter for directories to process
- `ARCHIVE_DETAILS[]`: Array storing "path:size" pairs

**Code Location:** Lines 298-477

---

### 1.4 Size Calculation Algorithm

**Problem:** Need accurate cross-platform file/directory size calculation.

**Algorithm:**

```bash
calculate_size() {
    local path=$1

    if [[ -f "$path" ]]; then
        # File: Use stat (cross-platform)
        stat -f%z "$path" 2>/dev/null ||   # macOS
        stat -c%s "$path" 2>/dev/null ||   # Linux
        echo 0

    elif [[ -d "$path" ]]; then
        # Directory: Use du (disk usage)
        du -sk "$path" 2>/dev/null | awk '{print $1 * 1024}' || echo 0

    else
        echo 0  # Path doesn't exist
    fi
}

# Human-readable formatting
format_size() {
    local bytes=$1

    if (( bytes >= 1073741824 )); then
        # >= 1GB: "1.4 GB"
        echo "$(( bytes / 1073741824 )).$(( (bytes % 1073741824) / 107374182 )) GB"
    elif (( bytes >= 1048576 )); then
        # >= 1MB: "488.2 MB"
        echo "$(( bytes / 1048576 )).$(( (bytes % 1048576) / 104857 )) MB"
    elif (( bytes >= 1024 )); then
        # >= 1KB: "10.0 KB"
        echo "$(( bytes / 1024 )).$(( (bytes % 1024) / 102 )) KB"
    else
        # < 1KB: "512 B"
        echo "$bytes B"
    fi
}
```

**Parameters:**
- `path`: File or directory path
- Returns: Size in bytes (as string)

**Code Location:** Lines 278-287, 264-275

---

### 1.5 Safe Deletion Algorithm

**Problem:** Must prevent accidental deletion of system files or wrong paths.

**Algorithm:**

```bash
process_directory() {
    local dir=$1
    local size=$2

    # Safety Check 1: Path exists
    if [[ ! -e "$dir" ]]; then
        return  # Path doesn't exist, skip
    fi

    # Safety Check 2: Is a directory
    if [[ ! -d "$dir" ]]; then
        log_message "WARN" "Not a directory: $dir"
        return
    fi

    # Safety Check 3: Not root or empty
    if [[ "$dir" == "/" ]] || [[ -z "$dir" ]]; then
        log_message "ERROR" "Attempted to delete root or empty path!"
        return 1
    fi

    # Safety Check 4: Within BASE_DIR
    if [[ ! "$dir" =~ ^${BASE_DIR} ]]; then
        log_message "ERROR" "Directory outside BASE_DIR: $dir"
        return 1
    fi

    # Execute: Archive or Delete
    if [[ -n "$ARCHIVE_DIR" ]]; then
        # Archive mode: Move to archive
        local relative_path="${dir#$BASE_DIR/}"
        local archive_path="${ARCHIVE_DIR}/${relative_path}"

        mkdir -p "$(dirname "$archive_path")"
        mv "$dir" "$archive_path"
    else
        # Delete mode: Remove permanently
        rm -rf "$dir"
    fi
}
```

**Safety Layers:**
1. Path existence check
2. Directory type verification
3. Root/empty path protection
4. BASE_DIR boundary enforcement

**Code Location:** Lines 529-562

---

### 1.6 Cleanup Execution Flow

**Algorithm:**

```
┌──────────────────────────────┐
│ Parse Arguments              │
│ --dry-run / --force / etc.   │
└─────────────┬────────────────┘
              ↓
┌──────────────────────────────┐
│ Initialize Logging           │
│ /var/log/rtx3060/cleanup/    │
└─────────────┬────────────────┘
              ↓
┌──────────────────────────────┐
│ Calculate Dates              │
│ current = 20251213           │
│ yesterday = 20251212         │
│ cutoff = 20251211            │
└─────────────┬────────────────┘
              ↓
┌──────────────────────────────┐
│ Scan Phase (3 directories)   │
│ ├─ scan_videos_directory()   │
│ ├─ scan_results_directory()  │
│ └─ scan_screenshots_dir()    │
└─────────────┬────────────────┘
              ↓
┌──────────────────────────────┐
│ Display Summary              │
│ - Dirs: N                    │
│ - Size: X GB                 │
│ - Cutoff: YYYYMMDD           │
└─────────────┬────────────────┘
              ↓
         ┌────┴─────┐
         │ Dry Run? │
         └────┬─────┘
         Yes  │  No
          ↓   │   ↓
       Exit   │  ┌──────────────┐
              │  │ User Confirm?│
              │  └────┬─────────┘
              │    Yes│  No
              │       ↓   ↓
              │      OK  Exit
              ↓
┌──────────────────────────────┐
│ Execute Cleanup (3 phases)   │
│ ├─ cleanup_videos()          │
│ ├─ cleanup_results()         │
│ └─ cleanup_screenshots()     │
└─────────────┬────────────────┘
              ↓
┌──────────────────────────────┐
│ Display Final Summary        │
│ - Freed: X GB                │
│ - Log: /var/log/.../         │
└──────────────────────────────┘
```

**Code Location:** Lines 732-777 (main function)

---

## 2. Log Cleanup Algorithm

**File:** `cleanup_logs.sh`
**Version:** 1.0.0
**Retention Policy:** Dual-limit (30 days + 500MB)

### 2.1 Two-Phase Cleanup Strategy

**Problem:** Need both age-based and size-based cleanup for logs.

**Algorithm:**

```
┌─────────────────────────────────┐
│ Phase 1: Age-Based Cleanup      │
├─────────────────────────────────┤
│ cutoff_date = today - 30 days   │
│                                  │
│ FOR each *.log.YYYYMMDD file:   │
│   ├─ Extract date from filename │
│   ├─ IF date < cutoff_date:     │
│   │   └─ DELETE file            │
│   └─ ELSE: Keep file            │
└─────────────┬───────────────────┘
              ↓
┌─────────────────────────────────┐
│ Phase 2: Size-Based Cleanup     │
├─────────────────────────────────┤
│ total_size = get_total_size()   │
│                                  │
│ IF total_size <= MAX_SIZE:      │
│   └─ EXIT (no cleanup needed)   │
│                                  │
│ need_to_free = total - MAX      │
│                                  │
│ old_files = sort_by_age(*.log.*)│
│                                  │
│ FOR each file in old_files:     │
│   ├─ DELETE file                │
│   ├─ total_size = recalculate() │
│   ├─ IF total_size <= MAX_SIZE: │
│   │   └─ BREAK (target reached) │
│   └─ CONTINUE                   │
└─────────────────────────────────┘
```

**Parameters:**
- `RETENTION_DAYS`: 30 (default)
- `MAX_SIZE_MB`: 500 (default)

**Code Location:** Lines 142-253

---

### 2.2 Age-Based Cleanup Algorithm

**Problem:** Delete logs older than retention period.

**Algorithm:**

```bash
cleanup_old_logs() {
    # Calculate cutoff date
    if [[ "$OSTYPE" == "darwin"* ]]; then
        CUTOFF_DATE=$(date -v-${RETENTION_DAYS}d +%Y%m%d)
    else
        CUTOFF_DATE=$(date -d "$RETENTION_DAYS days ago" +%Y%m%d)
    fi

    # Process dated log files
    for log_file in "$LOGS_DIR"/*.log.*; do
        [ -f "$log_file" ] || continue

        filename=$(basename "$log_file")

        # Extract date: surveillance_service.log.20251213 → 20251213
        if [[ "$filename" =~ \.([0-9]{8})$ ]]; then
            file_date="${BASH_REMATCH[1]}"

            # Numeric comparison (YYYYMMDD format)
            if [ "$file_date" -lt "$CUTOFF_DATE" ]; then
                rm -f "$log_file"
                DELETED_COUNT=$((DELETED_COUNT + 1))
                FREED_SPACE=$((FREED_SPACE + file_size))
            fi
        fi
    done
}
```

**Example:**
```
Today: 2025-12-13
Retention: 30 days
Cutoff: 2025-11-13 (20251113)

surveillance_service.log.20251112 → DELETE (older than cutoff)
surveillance_service.log.20251113 → KEEP (equals cutoff)
surveillance_service.log.20251213 → KEEP (newer than cutoff)
```

**Code Location:** Lines 142-199

---

### 2.3 Size-Based Cleanup Algorithm

**Problem:** Enforce total log size limit when age-based cleanup isn't enough.

**Algorithm:**

```bash
cleanup_by_size() {
    total_size=$(get_total_log_size)  # In MB

    if [ "$total_size" -le "$MAX_SIZE_MB" ]; then
        return  # Size OK, no cleanup needed
    fi

    # Calculate how much to free
    need_to_free=$((total_size - MAX_SIZE_MB))

    # Get backup files sorted by age (oldest first)
    old_files=$(find "$LOGS_DIR" -name "*.log.*" -type f \
                -printf '%T@ %p\n' | sort -n | awk '{print $2}')

    # Delete oldest files until size target reached
    for log_file in $old_files; do
        file_size=$(get_file_size_mb "$log_file")
        rm -f "$log_file"

        # Check if target reached
        total_size=$(get_total_log_size)
        if [ "$total_size" -le "$MAX_SIZE_MB" ]; then
            break  # Target reached, stop deleting
        fi
    done
}
```

**Example Scenario:**
```
Total log size: 650MB
Max limit: 500MB
Need to free: 150MB

Delete oldest backups until total <= 500MB:
1. Delete surveillance_service.log.20250101 (100MB) → Total = 550MB
2. Delete surveillance_service.log.20250102 (80MB)  → Total = 470MB
3. Target reached, stop deletion
```

**Note:** Main log file `surveillance_service.log` is never deleted, only dated backups.

**Code Location:** Lines 201-253

---

### 2.4 Total Size Calculation Algorithm

**Problem:** Calculate total size of all log files efficiently.

**Algorithm:**

```bash
get_total_log_size() {
    # Returns total log size in MB
    if [ -d "$LOGS_DIR" ]; then
        du -sm "$LOGS_DIR" 2>/dev/null | awk '{print $1}' || echo "0"
    else
        echo "0"
    fi
}

get_file_size_mb() {
    # Returns single file size in MB
    local file="$1"
    if [ -f "$file" ]; then
        du -m "$file" 2>/dev/null | awk '{print $1}' || echo "0"
    else
        echo "0"
    fi
}
```

**Parameters:**
- `LOGS_DIR`: Directory to measure
- Returns: Size in MB (as string)

**Code Location:** Lines 123-140

---

## 3. Comparison Matrix

| Feature | cleanup_old_videos.sh | cleanup_logs.sh |
|---------|----------------------|-----------------|
| **Retention Policy** | 2 days (today + yesterday) | 30 days + 500MB limit |
| **Cleanup Frequency** | Daily 3:00 AM | Daily 2:00 AM |
| **Directories Managed** | 3 (videos/results/screenshots) | 1 (logs/) |
| **Cleanup Phases** | 3 phases (by directory) | 2 phases (age + size) |
| **Archive Mode** | ✅ Supported | ❌ Not supported |
| **Protection Mechanism** | Protect today + yesterday | Protect main log file |
| **Size Limit** | ❌ None | ✅ 500MB |
| **Log Output** | /var/log/rtx3060/cleanup/ | Console |
| **Typical Cleanup Volume** | Several GB (large videos) | Tens of MB (small logs) |

---

## 4. Cleanup Decision Flow (ASCII Art)

```
┌─────────────────────────────────────────────────────────────┐
│                    CLEANUP DECISION TREE                     │
└─────────────────────────────────────────────────────────────┘

                    ┌───────────────┐
                    │  File Found   │
                    └───────┬───────┘
                            ↓
                  ┌─────────────────────┐
                  │ Extract Date/Info   │
                  └─────────┬───────────┘
                            ↓
              ┌─────────────────────────────┐
              │ Is Valid Date Format?       │
              │ (YYYYMMDD for videos,       │
              │  *.log.YYYYMMDD for logs)   │
              └──────┬──────────────┬───────┘
                 NO  │              │ YES
                     ↓              ↓
                  ┌──────┐    ┌──────────────────┐
                  │ SKIP │    │ Is Preserve Date?│
                  └──────┘    │ (today/yesterday)│
                              └──────┬──────┬────┘
                                 YES │      │ NO
                                     ↓      ↓
                                  ┌──────┐ │
                                  │ SKIP │ │
                                  └──────┘ │
                                           ↓
                              ┌────────────────────────┐
                              │ Date < Cutoff Date?    │
                              │ OR                     │
                              │ Size > Max Size?       │
                              └──────┬────────┬────────┘
                                  NO │        │ YES
                                     ↓        ↓
                                  ┌──────┐ ┌──────────────┐
                                  │ SKIP │ │ DRY RUN Mode?│
                                  └──────┘ └──────┬───┬───┘
                                              YES │   │ NO
                                                  ↓   ↓
                                           ┌────────┐ │
                                           │ LOG IT │ │
                                           └────────┘ │
                                                      ↓
                                           ┌─────────────────┐
                                           │ Archive Mode?   │
                                           └────┬────────┬───┘
                                            YES │        │ NO
                                                ↓        ↓
                                        ┌─────────┐  ┌────────┐
                                        │  MOVE   │  │ DELETE │
                                        └─────────┘  └────────┘
```

---

## 5. Key Algorithms Summary

### 5.1 Cross-Platform Date Arithmetic

**Challenge:** macOS (BSD) and Linux (GNU) have different date command syntax.

**Solution:**
```bash
# Detect OS and use appropriate syntax
if [[ "$OSTYPE" == "darwin"* ]]; then
    date -v-2d '+%Y%m%d'          # macOS: -v flag
else
    date -d "2 days ago" '+%Y%m%d'  # Linux: -d flag
fi
```

### 5.2 YYYYMMDD Numeric Comparison

**Challenge:** Need to compare dates efficiently.

**Solution:** Use YYYYMMDD format which allows direct numeric comparison:
```bash
cutoff=20251211
file_date=20251210

if [[ "$file_date" -lt "$cutoff" ]]; then
    # 20251210 < 20251211 → true, delete
fi
```

### 5.3 Recursive Size Calculation

**Challenge:** Need total size of nested directories.

**Solution:**
```bash
# du (disk usage) with -s (summarize) and -k (kilobytes)
du -sk "$path" | awk '{print $1 * 1024}'  # Convert KB to bytes
```

### 5.4 Iterative Size-Based Deletion

**Challenge:** Delete oldest files until size target is reached.

**Solution:**
```bash
# Sort files by timestamp, delete oldest first
find "$dir" -name "*.log.*" -printf '%T@ %p\n' | sort -n | \
while read timestamp path; do
    rm -f "$path"
    if [ $(get_total_size) -le $TARGET ]; then
        break
    fi
done
```

### 5.5 Multi-Layer Safety Checks

**Challenge:** Prevent accidental deletion of critical files.

**Solution:**
```bash
# Layer 1: Path existence
[[ ! -e "$dir" ]] && return

# Layer 2: Directory type
[[ ! -d "$dir" ]] && return

# Layer 3: Root protection
[[ "$dir" == "/" || -z "$dir" ]] && return

# Layer 4: BASE_DIR boundary
[[ ! "$dir" =~ ^${BASE_DIR} ]] && return
```

---

## 6. Cron Integration

### 6.1 Recommended Schedule

```bash
# /etc/crontab or crontab -e

# Log cleanup (2:00 AM)
0 2 * * * /path/to/scripts/maintenance/cleanup_logs.sh --force >> /var/log/ase_log_cleanup.log 2>&1

# Video retention cleanup (3:00 AM)
0 3 * * * /path/to/scripts/maintenance/cleanup_old_videos.sh --force >> /var/log/rtx3060/cleanup/cron.log 2>&1
```

### 6.2 Why This Schedule?

```
Timeline:
00:00 (Midnight)   - Processing window starts
02:00 (2 AM)       - Log cleanup (lightweight, fast)
03:00 (3 AM)       - Video cleanup (heavyweight, slow)
08:00 (8 AM)       - System health check
23:00 (11 PM)      - Processing window ends, daily reboot
```

**Rationale:**
- Log cleanup runs first (faster, less disk I/O)
- Video cleanup runs after (heavier, more disk I/O)
- Both run during low-activity hours (2-3 AM)
- Completed before business hours (11:30 AM restaurant opening)

---

## 7. Configuration Reference

### 7.1 cleanup_old_videos.sh Parameters

```bash
# Core Configuration
RETENTION_DAYS=2              # Keep last 2 days
DRY_RUN=false                 # Dry run mode
FORCE_MODE=false              # Skip confirmation
ARCHIVE_DIR=""                # Archive directory (empty = delete mode)

# Directory Paths
BASE_DIR="$(dirname "$SCRIPT_DIR")"
VIDEOS_DIR="${BASE_DIR}/videos"
RESULTS_DIR="${BASE_DIR}/results"
SCREENSHOTS_DIR="${BASE_DIR}/db/screenshots"

# Logging
LOG_DIR="/var/log/rtx3060/cleanup"
LOG_FILE="${LOG_DIR}/$(date +%Y%m%d).log"

# Tracking
TOTAL_SIZE_TO_FREE=0          # Total size to free (bytes)
FILES_TO_DELETE=0             # File count
DIRS_TO_DELETE=0              # Directory count
ARCHIVE_DETAILS=()            # Array: "path:size"
```

### 7.2 cleanup_logs.sh Parameters

```bash
# Core Configuration
RETENTION_DAYS=30             # Keep last 30 days
MAX_SIZE_MB=500               # Max total size 500MB
DRY_RUN=false                 # Dry run mode
FORCE=false                   # Skip confirmation

# Directory Paths
LOGS_DIR="$PROJECT_ROOT/logs"

# Statistics
DELETED_COUNT=0               # Deleted file count
FREED_SPACE=0                 # Freed space (MB)
```

---

## 8. Usage Examples

### 8.1 Video Cleanup

```bash
# Preview what will be deleted
./cleanup_old_videos.sh --dry-run

# Interactive cleanup with confirmation
./cleanup_old_videos.sh

# Automatic cleanup (for cron)
./cleanup_old_videos.sh --force

# Archive old files to backup disk
./cleanup_old_videos.sh --archive /mnt/backup/

# Help
./cleanup_old_videos.sh --help
```

### 8.2 Log Cleanup

```bash
# Preview deletions
./cleanup_logs.sh --dry-run

# Interactive cleanup
./cleanup_logs.sh

# Automatic cleanup (for cron)
./cleanup_logs.sh --force

# Custom retention (7 days)
./cleanup_logs.sh --days 7

# Custom size limit (200MB)
./cleanup_logs.sh --max-size 200

# Combined custom settings
./cleanup_logs.sh --days 14 --max-size 300 --force
```

---

## 9. Related Documentation

**See also:**
- **Root:** `/CLAUDE.md` - System overview, deployment checklist
- **Monitoring:** `scripts/monitoring/CLAUDE.md` - Disk space monitoring, GPU monitoring
- **Database:** `db/CLAUDE.md` - Database schema, Supabase sync
- **Deployment:** `scripts/deployment/CLAUDE.md` - Cron configuration, systemd service

**Workflow Integration:**
1. **Monitoring → Cleanup Trigger**
   - `check_disk_space.py` detects low space
   - Triggers `cleanup_old_videos.sh` to free space

2. **Cleanup → Database Verification**
   - `cleanup_old_videos.sh` before deleting
   - Calls `sync_to_supabase.py` to verify cloud sync

3. **Cleanup → Log Management**
   - `cleanup_logs.sh` manages cleanup script logs
   - Prevents cleanup logs from growing infinitely

---

## Version History

**2.0.0** (2025-12-13)
- ✅ Complete algorithm documentation (English)
- ✅ Added algorithm flow diagrams
- ✅ Added decision tree ASCII art
- ✅ Added detailed code location references
- ✅ Added cross-platform compatibility notes
- ✅ Added key algorithms summary section

**1.0.0** (2025-12-13)
- Initial documentation (Chinese)
- Detailed algorithm analysis for both scripts
- Retention policy documentation
- Cleanup flow diagrams
- Troubleshooting guide

---

**End of Documentation**
