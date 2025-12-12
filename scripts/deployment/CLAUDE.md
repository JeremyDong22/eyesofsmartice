# Deployment Scripts Documentation

**Version:** 2.0.0
**Last Updated:** 2025-12-13

This document provides comprehensive documentation of all deployment algorithms, configuration wizards, and system installation workflows.

---

## Overview

The deployment directory contains tools for:
- Restaurant initialization and configuration
- Camera setup and management
- ROI (Region of Interest) configuration
- Systemd service installation
- Cron job scheduling
- Database schema migration
- Configuration scaling for different resolutions

```
Deployment Flow:
┌──────────────────────────────────────────────────────────────────┐
│  sudo ./deploy.sh (Root directory - One-command deployment)      │
└──────────────────────────────────────────────────────────────────┘
                              ↓
┌──────────────────────────────────────────────────────────────────┐
│  1. Configuration Wizard (initialize_restaurant.py)              │
│     ├─ Location metadata (city, restaurant, address)            │
│     ├─ Camera setup (IP, credentials, resolution)               │
│     ├─ ROI configuration (tables, regions, service areas)       │
│     └─ Health checks (database, models, disk, network)          │
├──────────────────────────────────────────────────────────────────┤
│  2. Systemd Service (install_systemd.sh)                         │
│     ├─ Copy service file to /etc/systemd/system/                │
│     ├─ Enable auto-start on boot                                │
│     ├─ Auto-restart on failure (10-second delay)                │
│     └─ Integrated logging (journalctl)                          │
├──────────────────────────────────────────────────────────────────┤
│  3. Cron Jobs (install_cron_jobs.sh)                             │
│     ├─ Video recording (11:30-14:00, 17:30-22:00)               │
│     ├─ Video processing (00:00 midnight)                        │
│     ├─ Cleanup (02:00 logs, 03:00 videos)                       │
│     ├─ Monitoring (hourly disk, GPU checks)                     │
│     └─ Daily reboot (23:00 system health)                       │
└──────────────────────────────────────────────────────────────────┘
```

---

## File Reference

| File | Type | Purpose | Run As |
|------|------|---------|--------|
| `initialize_restaurant.py` | Python | Configuration wizard entry point | user |
| `interactive_start.py` | Python | Library: InteractiveStartup class | imported |
| `manage_cameras.py` | Python | Camera CRUD management tool | user |
| `migrate_database.py` | Python | Database schema migration | user |
| `scale_roi_config.py` | Python | ROI resolution scaling | user |
| `install_systemd.sh` | Bash | Systemd service installation | sudo |
| `install_cron_jobs.sh` | Bash | Cron job management | user |
| `install_service.sh` | Bash | Legacy systemd installer | sudo |
| `initialize_deployment.sh` | Bash | Legacy deployment wizard | user |
| `ase_surveillance.service` | Unit | Systemd service definition | - |

---

## 1. Restaurant Initialization Wizard

**File:** `initialize_restaurant.py` v4.0
**Class:** `SystemConfiguration` (extends `InteractiveStartup`)

### Purpose

Complete system configuration wizard for new deployments. Handles all interactive setup without starting the service (use systemd instead).

### Algorithm: Configuration Workflow

```
main()
  └─> run()
       ├─> show_welcome()
       │    └─ Display banner with project root, hardware, timestamp
       │
       ├─> run_preflight_checks()
       │    ├─ check_python() → Python 3.7+ validation
       │    ├─ check_database() → SQLite database schema check
       │    ├─ check_models() → YOLO model presence (2 files)
       │    ├─ check_network() → Internet connectivity (ping 8.8.8.8)
       │    ├─ check_disk() → Disk space validation (100+ GB)
       │    └─ check_gpu() → nvidia-smi GPU detection
       │
       ├─> LOOP: Configuration Review
       │    ├─ load_all_configuration()
       │    │    ├─ Load location_config.json
       │    │    ├─ Load cameras_config.json
       │    │    ├─ Load ROI configs (per-camera: camera_XX_roi.json)
       │    │    └─ Load system_config.json
       │    │
       │    ├─ display_configuration_review()
       │    │    ├─ format_location() → City, restaurant, timezone
       │    │    ├─ format_cameras() → IP, credentials, ROI status
       │    │    ├─ format_roi() → Tables, sitting areas, service areas
       │    │    └─ format_system_settings() → Hours, FPS, features
       │    │
       │    └─ prompt_menu()
       │         ├─ "continue" → Break loop, proceed to testing
       │         ├─ "edit" → interactive_editor()
       │         ├─ "reload" → Reload from disk
       │         └─ "exit" → Return False
       │
       ├─> test_all_cameras_workflow()
       │    └─ For each camera:
       │         ├─ test_camera_connection() → OpenCV RTSP validation
       │         ├─ handle_camera_failures() → Interactive retry/edit/skip
       │         └─ Store results in camera_test_results{}
       │
       ├─> configure_roi_for_cameras()
       │    └─ For each camera without ROI:
       │         ├─ prompt: interactive/manual/skip
       │         └─ launch_interactive_roi_drawing()
       │              ├─ Ask for sample video path
       │              ├─ Run: table_and_region_state_detection.py --interactive
       │              ├─ Rename table_region_config.json → camera_XX_roi.json
       │              └─ Reload configuration
       │
       ├─> show_feature_overview()
       │    └─ Display: capture, processing, monitoring, sync features
       │
       └─> show_completion_message()
            └─ Show systemd commands (NO STARTUP, use systemd)
```

### Key Classes and Methods

#### SystemConfiguration Class

**Inheritance:** `InteractiveStartup` (from `interactive_start.py`)

**Purpose:** Configuration-only wizard (startup removed, use systemd)

**Key Overrides:**
- `__init__(quick_mode=False)` → Sets `test_only=True` to disable startup
- `show_completion_message()` → Shows systemd instructions instead of startup prompts
- `run()` → Removes startup mode selection, ends after ROI configuration

#### Pre-flight Checks (Health Validation)

Each check returns `(status, message)` where status is `"ok"`, `"warning"`, or `"error"`.

| Check | Algorithm | Failure Impact |
|-------|-----------|----------------|
| **Python Version** | Parse `sys.version`, validate >= 3.7 | Fatal (exit) |
| **Database** | Query `sqlite_master` for table count | Warning (will create) |
| **YOLO Models** | Check file existence for 2 models | Fatal (exit) |
| **Network** | `ping -c 1 -W 2 8.8.8.8` | Warning (local mode OK) |
| **Disk Space** | `shutil.disk_usage()`, validate > 100GB | Error if < 100GB |
| **GPU** | `nvidia-smi --query-gpu=name,temperature.gpu` | Warning (development mode) |

### Camera Testing Algorithm

**Method:** `test_camera_connection(camera, verbose=False)`

```python
Algorithm: RTSP Connection Test
Input: camera{ip, port, username, password, stream_path}
Output: (success: bool)

1. Build RTSP URL:
   rtsp://username:password@ip:port/stream_path

2. Create VideoCapture:
   cap = cv2.VideoCapture(rtsp_url)

3. Check if opened:
   IF NOT cap.isOpened():
      RETURN False

4. Read one frame:
   ret, frame = cap.read()

5. Validate frame:
   IF ret AND frame is not None:
      ├─ Extract: width, height = frame.shape[:2]
      ├─ Extract: fps = cap.get(cv2.CAP_PROP_FPS)
      ├─ Print: Resolution, FPS, Status
      └─ RETURN True
   ELSE:
      RETURN False

6. Release:
   cap.release()
```

**Retry Logic:** `retry_camera_connection(camera, max_attempts=3)`

```
FOR attempt = 1 TO max_attempts:
   wait_time = 5 * attempt  # Progressive backoff: 5s, 10s, 15s
   sleep(wait_time)

   success = test_camera_connection(camera)

   IF success:
      RETURN True

RETURN False  # All attempts failed
```

### ROI Configuration Per Camera

**Problem:** Each camera monitors different areas with unique table layouts.

**Solution:** Per-camera ROI files (`camera_XX_roi.json`)

**Algorithm:** `configure_roi_for_camera(camera)`

```
1. Find cameras without ROI:
   cameras_needing_roi = [cam for cam in cameras
                          if cam['id'] not in roi_config
                          and cam.get('enabled')]

2. For each camera:
   ├─ Show prompt menu:
   │   ├─ "interactive" → launch_interactive_roi_drawing()
   │   ├─ "manual" → Show instructions for manual creation
   │   ├─ "skip" → Continue to next camera
   │   └─ "cancel" → Abort ROI setup
   │
   ├─ If interactive:
   │   ├─ Ask for sample video path from this camera
   │   ├─ Validate video file exists
   │   ├─ Launch subprocess:
   │   │    python3 table_and_region_state_detection.py \
   │   │         --video <path> \
   │   │         --interactive
   │   │
   │   ├─ Wait for completion
   │   ├─ Check if table_region_config.json created
   │   ├─ Rename to camera_{id}_roi.json
   │   └─ Reload all configuration
   │
   └─ Store ROI in roi_config[camera_id]

3. Legacy migration:
   IF table_region_config.json exists AND no per-camera configs:
      ├─ Assume it belongs to first camera
      ├─ Rename to first_camera_id_roi.json
      └─ Print migration warning
```

**ROI File Naming Convention:**
- Legacy: `table_region_config.json` (single camera, deprecated)
- New: `camera_35_roi.json`, `camera_22_roi.json` (per-camera)

### Configuration File Formats

#### cameras_config.json

```json
{
  "camera_35": {
    "ip": "202.168.40.35",
    "port": 554,
    "username": "admin",
    "password": "123456",
    "stream_path": "/media/video1",
    "resolution": [2592, 1944],
    "fps": 20,
    "division_name": "Main Hall",
    "location_id": "mianyang_1958_yebailing",
    "enabled": true,
    "notes": "Front entrance camera"
  }
}
```

#### camera_XX_roi.json (Per-Camera ROI)

```json
{
  "division": [[x1,y1], [x2,y2], ...],
  "tables": [
    {
      "id": "T1",
      "polygon": [[x1,y1], [x2,y2], ...],
      "sitting_area_ids": ["SA1", "SA2"]
    }
  ],
  "sitting_areas": [
    {
      "id": "SA1",
      "polygon": [[x1,y1], ...],
      "table_id": "T1"
    }
  ],
  "service_areas": [
    {
      "id": "SV1",
      "polygon": [[x1,y1], ...]
    }
  ],
  "frame_size": [2592, 1944],
  "video": "../videos/camera_35.mp4"
}
```

#### system_config.json

```json
{
  "capture_windows": [
    {
      "name": "lunch",
      "start_hour": 11,
      "start_minute": 30,
      "end_hour": 14,
      "end_minute": 0
    },
    {
      "name": "dinner",
      "start_hour": 17,
      "start_minute": 30,
      "end_hour": 22,
      "end_minute": 0
    }
  ],
  "processing_window": {
    "start_hour": 0,
    "end_hour": 23
  },
  "analysis_settings": {
    "fps": 5
  },
  "monitoring_enabled": true,
  "auto_restart_enabled": true,
  "last_updated": "2025-12-13"
}
```

---

## 2. Interactive Startup Library

**File:** `interactive_start.py` v3.0
**Class:** `InteractiveStartup`

### Purpose

Reusable library providing configuration workflow functionality. Imported by `initialize_restaurant.py`.

**Status:** LIBRARY (not a standalone script)

### Key Features

1. **Configuration Loading:** Load all JSON configs (location, cameras, ROI, system)
2. **Interactive Editing:** CRUD operations for cameras, ROI, system settings
3. **Camera Testing:** OpenCV-based RTSP validation with retry logic
4. **Per-Camera ROI:** Support for multiple cameras with individual ROI configs
5. **Feature Overview:** Display system capabilities and schedules

### Interactive Editor Menu

**Method:** `interactive_editor()`

```
Menu Options:
├─ add_camera → add_camera_wizard()
│   └─ Collect: IP, port, username, password, stream_path, division
│
├─ edit_camera → edit_camera_workflow()
│   ├─ select_camera() → Show numbered list
│   └─ edit_camera_wizard() → Update fields
│
├─ delete_camera → delete_camera_workflow()
│   └─ Confirm deletion, remove from cameras[]
│
├─ test_camera → test_single_camera_workflow()
│   └─ select_camera() → test_camera_connection()
│
├─ view_cameras → display_cameras_list()
│   └─ Show: ID, IP, port, username, status
│
├─ configure_roi → configure_roi_workflow()
│   └─ Redirect to per-camera ROI setup
│
├─ operating_hours → edit_operating_hours()
│   ├─ edit_capture_windows() → Update lunch/dinner times
│   └─ edit_processing_window() → Update processing hours
│
├─ features → toggle_features()
│   └─ Toggle: Supabase sync, monitoring
│
├─ save → save_all_configuration()
│   └─ Write cameras_config.json
│
└─ discard → Break without saving
```

### Configuration Review Display

**Method:** `display_configuration_review()`

**Format:**
```
[LOCATION CONFIGURATION]
────────────────────────────────────────────────────────────────────
Location ID:        mianyang_1958_yebailing
Restaurant:         野百灵火锅店
City:               Mianyang
Commercial Area:    1958商圈
Timezone:           Asia/Shanghai
────────────────────────────────────────────────────────────────────

[CAMERA CONFIGURATION]
────────────────────────────────────────────────────────────────────
Found 1 cameras in cameras_config.json:

Camera 1: camera_35
  IP Address:       202.168.40.35:554
  Credentials:      admin:***
  Resolution:       2592x1944 @ 20fps
  Stream:           rtsp://admin:***@202.168.40.35:554/media/video1
  Status:           ✅ Enabled
  ROI Config:       ✅ ROI configured (5 tables, 2 service areas)

────────────────────────────────────────────────────────────────────

[ROI CONFIGURATION]
────────────────────────────────────────────────────────────────────
Configuration files: Per-camera ROI (camera_XX_roi.json)

Cameras with ROI:   1/1

camera_35:
  Frame Size:       2592x1944
  Tables:           5
  Sitting Areas:    10
  Service Areas:    2

────────────────────────────────────────────────────────────────────

[SYSTEM SETTINGS]
────────────────────────────────────────────────────────────────────
Operating Hours:    11:30 AM - 2:00 PM, 5:30 PM - 10:00 PM (capture)
Processing Window:  12:00 AM - 11:00 PM (analysis)
Analysis FPS:       5 fps
Detection Mode:     Combined (Tables + Regions)
Supabase Sync:      ✅ Enabled (hourly)
Monitoring:         ✅ Enabled (disk + GPU)
Auto-restart:       ✅ Enabled (on crash)
────────────────────────────────────────────────────────────────────
```

---

## 3. Camera Management Tool

**File:** `manage_cameras.py` v1.0.0

### Purpose

Standalone tool for managing camera configurations after initial deployment. Provides CRUD operations and connection testing.

### Algorithm: Camera CRUD Operations

```
CameraManager Class:
├─ load_database()
│   ├─ Connect to detection_data.db
│   ├─ Get location_id from locations table
│   └─ Load cameras_config.json
│
├─ list_cameras()
│   └─ For each camera in cameras_config:
│        Print: ID, IP, username, port, stream, division, notes
│
├─ add_camera()
│   ├─ Input: IP address
│   ├─ Validate IP format (XXX.XXX.XXX.XXX)
│   ├─ Generate camera_id: camera_{last_octet}
│   ├─ Input: username, password, port, stream_path
│   ├─ Input: division_name, notes, resolution
│   ├─ Create camera config dict
│   ├─ Save to cameras_config.json
│   └─ Update database (INSERT OR REPLACE INTO cameras)
│
├─ edit_camera()
│   ├─ Prompt: camera_id
│   ├─ Show current config
│   ├─ Input: new values (press Enter to keep)
│   ├─ Update camera config dict
│   ├─ Save to cameras_config.json
│   └─ Update database
│
├─ remove_camera()
│   ├─ Prompt: camera_id
│   ├─ Confirm deletion
│   ├─ Delete from cameras_config.json
│   └─ UPDATE cameras SET status='inactive'
│
└─ test_camera()
    ├─ Prompt: camera_id
    ├─ Build RTSP URL
    ├─ cap = cv2.VideoCapture(rtsp_url)
    ├─ ret, frame = cap.read()
    └─ Display: Connection result, resolution
```

### IP Validation Algorithm

**Method:** `_validate_ip(ip)`

```python
Algorithm: IP Address Validation
Input: ip (string)
Output: valid (boolean)

1. Regex check:
   pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
   IF NOT re.match(pattern, ip):
      RETURN False

2. Octet range check:
   octets = ip.split('.')
   FOR each octet in octets:
      IF NOT (0 <= int(octet) <= 255):
         RETURN False

   RETURN True
```

### Database Update

**Method:** `_update_database_camera(camera_id)`

```sql
Algorithm: Update Camera in Database

1. Build RTSP endpoint:
   rtsp://username:password@ip:port/stream_path

2. Execute SQL:
   INSERT OR REPLACE INTO cameras
   (camera_id, location_id, camera_name, camera_ip_address,
    rtsp_endpoint, camera_type, resolution, division_name, status)
   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)

3. Commit transaction

Parameters:
- camera_id: e.g. "camera_35"
- location_id: from location config
- camera_name: from notes field
- camera_ip_address: IP string
- rtsp_endpoint: full RTSP URL
- camera_type: "UNV" (default)
- resolution: "2592x1944" string format
- division_name: optional area name
- status: "active" or "inactive"
```

---

## 4. Database Migration

**File:** `migrate_database.py` v1.0.0

### Purpose

Migrate database from old schema to v2.0.0 with location_id support and cloud sync columns.

### Algorithm: Migration Workflow

```
DatabaseMigrator.run()
├─> create_backup()
│    ├─ Check if DB exists
│    ├─ Generate timestamp: YYYYMMDD_HHMMSS
│    ├─ Copy: detection_data.db → detection_data_backup_{timestamp}.db
│    └─ Print backup path
│
├─> connect_database()
│    ├─ Create db/ directory if needed
│    └─ sqlite3.connect(detection_data.db)
│
├─> analyze_current_schema()
│    ├─ Query: SELECT name FROM sqlite_master WHERE type='table'
│    ├─ Check for v2.0.0 indicators:
│    │    ├─ 'locations' table exists
│    │    ├─ 'cameras' table exists
│    │    └─ 'location_id' column in sessions
│    └─ Print: Current version status
│
├─> apply_new_schema()
│    ├─ IF database_schema.sql exists:
│    │    ├─ Read schema file
│    │    └─ executescript(schema_sql)
│    ├─ ELSE:
│    │    └─ _create_basic_schema()
│    │         ├─ CREATE TABLE locations
│    │         ├─ CREATE TABLE cameras
│    │         └─ _add_location_id_columns()
│    │              └─ ALTER TABLE sessions ADD COLUMN location_id
│    │              └─ ALTER TABLE division_states ADD COLUMN location_id
│    │              └─ ALTER TABLE table_states ADD COLUMN location_id
│    │
│    └─ commit()
│
├─> backfill_data()
│    ├─ Query: SELECT location_id FROM locations LIMIT 1
│    ├─ IF location exists:
│    │    ├─ UPDATE sessions SET location_id=? WHERE location_id IS NULL
│    │    ├─ UPDATE division_states SET location_id=? WHERE location_id IS NULL
│    │    ├─ UPDATE table_states SET location_id=? WHERE location_id IS NULL
│    │    └─ commit()
│    └─ Print: Rows updated
│
└─> verify_migration()
     ├─ Check required tables exist:
     │    [locations, cameras, sessions, division_states,
     │     table_states, sync_queue, sync_status]
     │
     ├─ Check location_id columns exist in:
     │    [sessions, division_states, table_states]
     │
     ├─ Check synced_to_cloud columns exist in:
     │    [division_states, table_states]
     │
     └─ Print: Schema version 2.0.0 verified
```

### Schema v2.0.0 Changes

**New Tables:**

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `locations` | Restaurant metadata | location_id (PK), city, restaurant_name, commercial_area |
| `cameras` | Camera registry | camera_id (PK), location_id (FK), ip_address, rtsp_endpoint |
| `sync_queue` | Cloud sync queue | id (PK), table_name, record_id, sync_status |
| `sync_status` | Sync tracking | location_id (PK), last_sync_time, records_synced |

**Modified Tables:**

| Table | Added Column | Type | Purpose |
|-------|--------------|------|---------|
| `sessions` | location_id | TEXT | Link to location |
| `division_states` | location_id | TEXT | Link to location |
| `division_states` | synced_to_cloud | INTEGER | Sync flag (0/1) |
| `table_states` | location_id | TEXT | Link to location |
| `table_states` | synced_to_cloud | INTEGER | Sync flag (0/1) |

### Backfill Algorithm

```
Algorithm: Backfill Location References
Problem: Existing data has no location_id
Solution: Assign all to first (default) location

1. Check if any location exists:
   SELECT COUNT(*) FROM locations

   IF count = 0:
      PRINT "No location found, run initialize_restaurant.py"
      RETURN

2. Get default location:
   SELECT location_id FROM locations LIMIT 1
   → default_location_id

3. Update all tables:
   UPDATE sessions SET location_id = ? WHERE location_id IS NULL
   UPDATE division_states SET location_id = ? WHERE location_id IS NULL
   UPDATE table_states SET location_id = ? WHERE location_id IS NULL

4. Print rows affected
```

---

## 5. ROI Configuration Scaling

**File:** `scale_roi_config.py` v1.0.0

### Purpose

Scale ROI coordinates when camera resolution changes (e.g., MacBook test at 1920x1080 → Production camera at 2592x1944).

### Algorithm: Coordinate Scaling

```
scale_config(config_path, target_width, target_height, backup=True)

1. Load configuration:
   config = json.load(config_path)

2. Get original resolution:
   original_width, original_height = config['frame_size']

3. Calculate scaling factors:
   scale_x = target_width / original_width
   scale_y = target_height / original_height

4. Create backup if requested:
   IF backup:
      shutil.copy2(config_path, config_path + "_backup_{timestamp}.json")

5. Scale all polygons:
   FOR each polygon in [division, tables, sitting_areas, service_areas]:
      scaled_polygon = [[int(x * scale_x), int(y * scale_y)]
                        for x, y in polygon]

6. Update frame_size:
   config['frame_size'] = [target_width, target_height]

7. Save scaled configuration:
   json.dump(config, config_path, indent=2)
```

**Example:**
```bash
# Scale from MacBook test (1920x1080) to production camera (2592x1944)
python3 scale_roi_config.py --width 2592 --height 1944

# Original point: (960, 540) → Scaled: (1296, 972)
# Calculation: x' = 960 * (2592/1920) = 1296
#              y' = 540 * (1944/1080) = 972
```

---

## 6. Systemd Service Installation

**File:** `install_systemd.sh` v1.0

### Purpose

Install surveillance system as systemd service for auto-start and auto-restart.

### Algorithm: Service Installation

```bash
Algorithm: Systemd Service Installation

1. Check root permissions:
   IF $EUID != 0:
      PRINT "Must run with sudo"
      EXIT 1

2. Verify service file exists:
   IF NOT exists "ase_surveillance.service":
      PRINT "Service file not found"
      EXIT 1

3. Copy service file:
   cp ase_surveillance.service /etc/systemd/system/
   chown root:root /etc/systemd/system/ase_surveillance.service
   chmod 644 /etc/systemd/system/ase_surveillance.service

4. Reload systemd daemon:
   systemctl daemon-reload

5. Enable auto-start on boot:
   systemctl enable ase_surveillance

6. Verify installation:
   systemctl list-unit-files | grep ase_surveillance.service

   IF found:
      PRINT "Installation successful"
   ELSE:
      PRINT "Installation verification failed"
      EXIT 1

7. Display management commands
```

### Service File Configuration

**File:** `ase_surveillance.service`

```ini
[Unit]
Description=ASE Restaurant Surveillance Service v3.0.0
Documentation=https://github.com/JeremyDong22/ASEOfSmartICE
After=network.target

[Service]
Type=simple
User=smartahc
Group=smartahc
WorkingDirectory=/home/smartahc/smartice/ASEOfSmartICE/production/RTX_3060
ExecStart=/usr/bin/python3 /home/.../surveillance_service.py start
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

# Environment
Environment="PATH=/usr/local/bin:/usr/bin:/bin"
Environment="PYTHONUNBUFFERED=1"

# Resource limits
LimitNOFILE=65536
Nice=-5

# Logging
SyslogIdentifier=ase_surveillance

[Install]
WantedBy=multi-user.target
```

**Key Parameters:**

| Parameter | Value | Effect |
|-----------|-------|--------|
| `Type=simple` | Direct process | Systemd tracks main process directly |
| `Restart=on-failure` | Auto-restart | Restart if exit code != 0 or killed |
| `RestartSec=10` | 10-second delay | Wait 10s before restart |
| `After=network.target` | Network dependency | Start after network is up |
| `WantedBy=multi-user.target` | Boot target | Enable auto-start on boot |
| `Nice=-5` | Priority boost | Higher CPU priority |
| `LimitNOFILE=65536` | File descriptors | Support many open files |

### Management Commands

```bash
# Start service
sudo systemctl start ase_surveillance

# Stop service
sudo systemctl stop ase_surveillance

# Restart service
sudo systemctl restart ase_surveillance

# View status
sudo systemctl status ase_surveillance

# View logs (real-time)
sudo journalctl -u ase_surveillance -f

# View logs (last 50 lines)
sudo journalctl -u ase_surveillance -n 50

# Disable auto-start
sudo systemctl disable ase_surveillance

# Re-enable auto-start
sudo systemctl enable ase_surveillance
```

---

## 7. Cron Job Installation

**File:** `install_cron_jobs.sh` v1.0.0

### Purpose

Install automated cron jobs for recording, processing, cleanup, and monitoring.

### Algorithm: Cron Installation

```bash
install_cron_jobs()

1. check_prerequisites()
   ├─ Verify Python3 installed
   ├─ Check all required scripts exist:
   │   ├─ video_capture/capture_rtsp_streams.py
   │   ├─ orchestration/process_videos_orchestrator.py
   │   ├─ maintenance/cleanup_old_videos.sh
   │   ├─ maintenance/cleanup_logs.sh
   │   ├─ time_sync/verify_time_sync.sh
   │   └─ monitoring/check_disk_space.py
   ├─ Check scripts are executable
   ├─ Verify crontab command available
   └─ Check timezone (should be Asia/Shanghai)

2. backup_existing_crontab()
   ├─ Create backups/ directory
   ├─ Generate backup filename: crontab_backup_{timestamp}.txt
   └─ crontab -l > backup_file

3. remove_old_cron_jobs()
   ├─ Export current crontab
   ├─ Filter out lines between:
   │    # RTX3060-PRODUCTION-SURVEILLANCE
   │    and
   │    # RTX3060-PRODUCTION-SURVEILLANCE-END
   └─ Save to temp file

4. generate_cron_config()
   ├─ Write header with installation date
   ├─ Add recording jobs:
   │    ├─ 30 11 * * * - Lunch recording (11:30 AM, 9000s)
   │    └─ 30 17 * * * - Dinner recording (5:30 PM, 16200s)
   ├─ Add processing job:
   │    └─ 0 0 * * * - Midnight processing
   ├─ Add cleanup jobs:
   │    ├─ 0 2 * * * - Log cleanup (2 AM)
   │    └─ 0 3 * * * - Video cleanup (3 AM)
   ├─ Add monitoring jobs:
   │    ├─ 0 * * * * - Time sync (hourly)
   │    ├─ 0 */1 * * * - Disk space (hourly, changed from 2h)
   │    └─ */5 23-23,0-7 * * * - GPU health (every 5 min, 11PM-7AM)
   └─ Write end marker

5. Combine crontabs:
   cat cleaned_crontab new_jobs > final_crontab

6. Install:
   crontab final_crontab

   IF success:
      PRINT "Installed successfully"
   ELSE:
      PRINT "Installation failed"
      crontab backup_file  # Restore backup

7. Cleanup temp files
```

### Cron Schedule (Beijing Time)

```
┌─────────────────────────────────────────────────────────────────┐
│  Time Schedule (Asia/Shanghai Timezone)                         │
├─────────────────────────────────────────────────────────────────┤
│  00:00  Midnight video processing (previous day)                │
│  02:00  Log cleanup (30-day retention)                          │
│  03:00  Video cleanup (2-day retention)                         │
│  11:30  Lunch recording start (2.5 hours)                       │
│  14:00  Lunch recording end                                     │
│  17:30  Dinner recording start (4.5 hours)                      │
│  22:00  Dinner recording end                                    │
│  23:00  Daily system reboot (health maintenance)                │
│  XX:00  Hourly: Time sync, Disk space check                     │
│  XX:05  Every 5 min (11PM-7AM): GPU health check                │
└─────────────────────────────────────────────────────────────────┘
```

### Cron Job Details

| Job | Schedule | Command | Log |
|-----|----------|---------|-----|
| **Lunch Recording** | `30 11 * * *` | `capture_rtsp_streams.py --duration 9000` | `recording.log` |
| **Dinner Recording** | `30 17 * * *` | `capture_rtsp_streams.py --duration 16200` | `recording.log` |
| **Video Processing** | `0 0 * * *` | `process_videos_orchestrator.py --max-parallel 4` | `processing.log` |
| **Video Cleanup** | `0 3 * * *` | `cleanup_old_videos.sh --force` | `cleanup_videos.log` |
| **Log Cleanup** | `0 2 * * *` | `cleanup_logs.sh --force` | `cleanup_logs.log` |
| **Time Sync** | `0 * * * *` | `verify_time_sync.sh` | `time_sync.log` |
| **Disk Space** | `0 * * * *` | `check_disk_space.py --cleanup` | `disk_space.log` |
| **GPU Health** | `*/5 23-23,0-7 * * *` | `nvidia-smi --query-gpu=...` | `gpu_health.log` |
| **Daily Reboot** | `0 23 * * *` | `sudo /sbin/reboot` | system |

**Duration Calculations:**
- Lunch: 11:30 - 14:00 = 2.5 hours = 150 minutes = 9000 seconds
- Dinner: 17:30 - 22:00 = 4.5 hours = 270 minutes = 16200 seconds

### Cron Management Commands

```bash
# Install cron jobs
./scripts/deployment/install_cron_jobs.sh --install

# Check status
./scripts/deployment/install_cron_jobs.sh --status

# Preview configuration
./scripts/deployment/install_cron_jobs.sh --preview

# Uninstall cron jobs
./scripts/deployment/install_cron_jobs.sh --uninstall

# View log files
./scripts/deployment/install_cron_jobs.sh --logs

# Manual crontab inspection
crontab -l
```

---

## 8. Legacy Scripts

### initialize_deployment.sh

**Status:** Legacy (replaced by `initialize_restaurant.py`)

**Purpose:** Comprehensive bash-based deployment wizard (v1.0.0)

**Features:**
- Pre-flight checks (Python, packages, ffmpeg, GPU, models, disk)
- Camera configuration with IP collection
- ROI interactive setup
- System verification
- Test recording
- Next steps guide

**Differences from v4.0:**
- Bash-based (v4.0 is Python-based)
- Single ROI config (v4.0 supports per-camera ROI)
- Includes startup prompts (v4.0 uses systemd only)

### install_service.sh

**Status:** Legacy (replaced by `install_systemd.sh`)

**Purpose:** Systemd service installation with path substitution

**Features:**
- Auto-detect user and home directory
- Replace placeholders in service file: `/home/smartahc` → actual path
- Interactive startup prompt after installation

**Differences from v4.0:**
- Path substitution (v4.0 uses static paths)
- Interactive prompt to start service (v4.0 just installs)

---

## Configuration Validation

### Health Check Algorithms

#### Disk Space Check

**File:** `scripts/monitoring/check_disk_space.py`

```python
Algorithm: Disk Space Validation
Used by: initialize_restaurant.py preflight checks

1. Get disk usage:
   total, used, free = shutil.disk_usage(PROJECT_ROOT)

2. Convert to GB:
   free_gb = free // (2**30)

3. Evaluate status:
   IF free_gb > 200:
      RETURN ("ok", f"{free_gb} GB free")
   ELIF free_gb > 100:
      RETURN ("warning", f"{free_gb} GB free (getting low)")
   ELSE:
      RETURN ("error", f"{free_gb} GB free (need 100+ GB)")
```

#### Network Check

```python
Algorithm: Internet Connectivity Check

1. Ping Google DNS:
   subprocess.run(["ping", "-c", "1", "-W", "2", "8.8.8.8"],
                  capture_output=True, timeout=5)

2. Evaluate:
   IF returncode == 0:
      RETURN ("ok", "Internet reachable")
   ELSE:
      RETURN ("warning", "No internet (local mode OK)")
```

#### GPU Check

```python
Algorithm: NVIDIA GPU Detection

1. Query GPU info:
   subprocess.run(
      ["nvidia-smi",
       "--query-gpu=name,temperature.gpu",
       "--format=csv,noheader"],
      capture_output=True, timeout=5
   )

2. Parse output:
   IF returncode == 0:
      gpu_info = stdout.strip()  # e.g., "NVIDIA GeForce RTX 3060, 45"
      RETURN ("ok", gpu_info)
   ELSE:
      RETURN ("warning", "GPU not detected")
```

---

## Deployment Best Practices

### First-Time Deployment

```bash
# 1. Clone repository
git clone <repo_url>
cd eyesofsmartice

# 2. Install dependencies (if needed)
pip3 install opencv-python ultralytics numpy

# 3. One-command deployment
sudo ./deploy.sh

# This will:
# - Run initialize_restaurant.py (configure system)
# - Install systemd service
# - Install cron jobs
# - Start the service
```

### Re-Deployment (Update)

```bash
# 1. Stop service
sudo systemctl stop ase_surveillance

# 2. Pull latest code
git pull origin main

# 3. Run database migration (if schema changed)
python3 scripts/deployment/migrate_database.py --backup

# 4. Restart service
sudo systemctl restart ase_surveillance

# 5. Verify
sudo systemctl status ase_surveillance
```

### Adding New Camera

```bash
# Method 1: Interactive menu
python3 scripts/deployment/manage_cameras.py

# Method 2: Command line
python3 scripts/deployment/manage_cameras.py --add

# 3. Configure ROI for new camera
python3 main.py --configure
# Select "Configure ROI" → Choose new camera → Interactive drawing
```

### ROI Reconfiguration

```bash
# 1. Navigate to scripts
cd scripts

# 2. Run interactive mode for specific camera
python3 video_processing/table_and_region_state_detection.py \
   --video ../videos/camera_35.mp4 \
   --interactive

# 3. Configuration saved to:
#    config/table_region_config.json (default)
#    Rename to: config/camera_35_roi.json (for per-camera setup)
```

### Troubleshooting

#### Service Won't Start

```bash
# Check logs
sudo journalctl -u ase_surveillance -n 50

# Check Python environment
which python3
python3 --version

# Manual test
python3 scripts/orchestration/surveillance_service.py start --foreground
```

#### Cron Jobs Not Running

```bash
# Check cron service
sudo systemctl status cron

# View cron logs
grep CRON /var/log/syslog

# Verify crontab
crontab -l | grep RTX3060
```

#### Camera Connection Failed

```bash
# Test camera
python3 scripts/deployment/manage_cameras.py --test camera_35

# Check network
ping 202.168.40.35

# Test RTSP manually
ffprobe rtsp://admin:123456@202.168.40.35:554/media/video1
```

---

## Version History

- **2.0.0** (2025-12-13): Complete rewrite with comprehensive algorithm documentation
- **1.0.0** (2025-12-13): Initial documentation of deployment architecture

---

## Related Documentation

- **Root CLAUDE.md:** Project overview, deployment workflow, architecture
- **scripts/CLAUDE.md:** Documentation index for all script directories
- **scripts/video_processing/CLAUDE.md:** Detection pipeline algorithms
- **db/CLAUDE.md:** Database schema and cloud sync

---

## Summary

This deployment system provides:
- ✅ Interactive configuration wizard (Python-based, v4.0)
- ✅ Per-camera ROI support (multiple cameras, different layouts)
- ✅ Systemd service (auto-start, auto-restart, logging)
- ✅ Cron automation (recording, processing, cleanup, monitoring)
- ✅ Database migration (schema versioning, backfill)
- ✅ Camera management (CRUD, connection testing)
- ✅ ROI scaling (resolution adaptation)
- ✅ Health checks (pre-flight validation, system verification)

All tools are designed for production deployment on RTX 3060 Linux machines with comprehensive error handling and recovery mechanisms.
