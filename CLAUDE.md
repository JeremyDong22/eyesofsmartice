# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Last Updated:** 2025-11-16

## Documentation Structure

- **CLAUDE.md** (this file) - System overview, deployment guide, and configuration reference
- **scripts/STRUCTURE.md** - Detailed scripts organization and navigation guide
- **db/CLAUDE.md** - Cloud database schema, Supabase architecture, and sync details
- **scripts/deployment/DEPLOYMENT_GUIDE.md** - Step-by-step deployment procedures

---

## Project Overview

Production deployment folder for RTX 3060 machine at 野百灵火锅店 (Ye Bai Ling Hotpot Restaurant) in 1958 Commercial District, Mianyang. This is the **live production environment** running on remote Linux hardware in the restaurant location.

**Purpose:** Real-time restaurant surveillance system using computer vision to monitor table states and staff coverage across multiple camera feeds.

## Quick Start - New Deployment (v4.0)

### **Unified Entry Point**

```bash
cd /path/to/production/RTX_3060

# Main entry point (interactive menu)
python3 main.py

# Or direct commands
python3 main.py --configure    # Configure system
python3 main.py --start        # Start service (dev mode)
```

**What main.py does:**
- Interactive menu for all operations
- Guides you through configuration
- Shows production deployment instructions
- Simple, clear interface

---

## Complete Deployment Workflow

### **Step 1: System Configuration (First Time Only)**

```bash
# Interactive configuration wizard
python3 main.py --configure

# OR directly call the configuration script
python3 scripts/deployment/initialize_restaurant.py
```

**What gets configured:**
- ✅ Restaurant location (city, name, commercial area)
- ✅ Camera management (add/edit/delete cameras with full credentials)
- ✅ Camera connection testing (RTSP validation)
- ✅ ROI configuration (interactive table/region drawing)
- ✅ System settings (capture hours, processing windows)

**This step does NOT start the service** - it only configures!

### **Step 2: Install Systemd Service (Production)**

```bash
# Install systemd service (one-time setup)
sudo cp scripts/deployment/ase_surveillance.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ase_surveillance
```

### **Step 3: Start Service**

```bash
# Production (recommended)
sudo systemctl start ase_surveillance

# Management commands
sudo systemctl status ase_surveillance   # Check status
sudo systemctl stop ase_surveillance     # Stop
sudo systemctl restart ase_surveillance  # Restart
sudo journalctl -u ase_surveillance -f   # View logs
```

**Systemd Features:**
- ✅ Auto-restart on crash
- ✅ Auto-start on boot
- ✅ System-level resource management
- ✅ Integrated logging
- ✅ No PID file conflicts

---

## Architecture Overview (v4.0)

### **Entry Points**

| File | Purpose | When to Use |
|------|---------|-------------|
| `main.py` | Unified entry point | Interactive menu for all operations |
| `scripts/deployment/initialize_restaurant.py` | Complete configuration wizard | First-time setup or reconfiguration |
| `interactive_start.py` | ~~Legacy~~ (kept for reference) | ~~Use main.py instead~~ |
| `start.sh` | ~~Legacy~~ (deprecated) | ~~Use systemd instead~~ |

### **Service Management**

| Environment | Command | Notes |
|-------------|---------|-------|
| **Production** | `sudo systemctl start ase_surveillance` | Systemd manages Python service directly |
| **Development** | `python3 main.py --start` | Direct Python execution (not systemd) |
| **Testing** | `python3 scripts/orchestration/surveillance_service.py start --foreground` | Foreground mode with logs |

### **Configuration vs Startup (Clear Separation)**

```
┌─────────────────────────────────────┐
│  CONFIGURATION (One-Time)           │
│  main.py --configure                │
│  └─> initialize_restaurant.py      │
│      ├─ Camera setup                │
│      ├─ ROI drawing                 │
│      ├─ System settings             │
│      └─ NO STARTUP!                 │
└─────────────────────────────────────┘
              ↓
┌─────────────────────────────────────┐
│  STARTUP (Daily Production)         │
│  systemctl start ase_surveillance   │
│  └─> surveillance_service.py       │
│      ├─ Video capture               │
│      ├─ Video processing            │
│      ├─ Monitoring                  │
│      └─ Auto-restart on crash       │
└─────────────────────────────────────┘
```

## Business Context

**Location:** 1958 Commercial District (1958商圈), Mianyang, Sichuan
**Restaurant:** 野百灵火锅店 (Ye Bai Ling Hotpot)
**Hardware:** NVIDIA RTX 3060 Linux machine deployed on-site
**Cameras:** Currently testing with 1 camera (camera_35, 2592x1944)
**Operating Hours (Dual Windows):**
- Morning: 11:30 AM - 2:00 PM (2.5 hours)
- Evening: 5:00 PM - 10:00 PM (5 hours)
- Total: 7.5 hours daily capture
**Processing Window:** 12:00 AM - 11:00 PM (all day, target completion by 11 PM)

## System Architecture

### Two-Stage Detection Pipeline

**Stage 1: Person Detection**
- Model: `yolov8m.pt` (52 MB)
- Detects all people in frame
- Confidence: 0.3, Min size: 40px
- Performance: 14.5ms/frame

**Stage 2: Staff Classification**
- Model: `waiter_customer_classifier.pt` (3.2 MB)
- Classifies persons as waiter/customer
- Confidence: 0.5, Accuracy: 92.38%
- Performance: 47.2ms/frame

**Total Processing:** 61.7ms/frame (3.24x real-time at 5fps)

### Detection Modes

**1. Table State Detection**
- Monitors individual table states
- States: IDLE (green), BUSY (yellow), CLEANING (blue)
- Tracks customer/waiter presence at each table
- Use cases: Turnover analysis, service response time

**2. Region State Detection**
- Monitors division/area coverage by staff
- States: GREEN (serving), YELLOW (busy), RED (understaffed)
- Tracks staff locations in service/walking areas
- Use cases: Zone coverage, staff allocation

**3. Combined Detection**
- Unified system monitoring both tables AND regions
- Comprehensive restaurant floor monitoring
- Three-layer debug: SQLite DB + Screenshots + H.264 video

## Directory Structure

```
production/RTX_3060/
├── start.py             # 🚀 MAIN ENTRY POINT - Start here!
├── scripts/              # Production scripts (feature-based organization)
│   ├── deployment/          # 🔧 Initial setup and deployment
│   │   ├── initialize_restaurant.py  # Interactive wizard: location + cameras
│   │   ├── migrate_database.py       # Database schema migration
│   │   └── DEPLOYMENT_GUIDE.md       # Complete deployment instructions
│   ├── database_sync/       # 📊 Database and cloud synchronization
│   │   ├── batch_db_writer.py        # Batch insert (100× faster)
│   │   └── sync_to_supabase.py       # Hourly cloud sync (DB only)
│   ├── camera_testing/      # Camera connection testing
│   ├── video_capture/       # RTSP stream recording
│   ├── video_processing/    # Detection and analysis (main system)
│   ├── orchestration/       # Multi-camera batch processing
│   ├── time_sync/           # NTP synchronization
│   ├── maintenance/         # General cleanup scripts
│   ├── monitoring/          # System health monitoring
│   │   ├── check_disk_space.py      # Disk space monitoring with smart cleanup
│   │   ├── monitor_gpu.py           # GPU temperature and utilization
│   │   └── system_health.py         # Comprehensive health check
│   ├── config/              # Configuration files
│   │   ├── cameras_config.json       # Camera IP addresses
│   │   └── table_region_config.json  # ROI configuration (5 tables)
│   └── STRUCTURE.md         # Detailed scripts organization guide
├── models/               # Trained YOLO models (53.1 MB total)
│   ├── yolov8m.pt                          # Person detector
│   └── waiter_customer_classifier.pt       # Staff classifier
├── db/                   # Database and documentation
│   ├── detection_data.db                   # Local SQLite database
│   ├── database_schema.sql                 # Database schema (v2.0.0)
│   ├── CLAUDE.md                           # Cloud database documentation
│   └── screenshots/{camera_id}/{date}/     # Auto-saved screenshots
├── results/              # Processed video outputs
└── videos/               # Input video files
```

**Note:** Scripts are organized by feature. See `scripts/STRUCTURE.md` for detailed navigation guide.

## Common Commands

### Interactive ROI Setup
```bash
cd /path/to/production/RTX_3060/scripts
./run_interactive.sh

# Manual version (from scripts/ directory):
python3 video_processing/table_and_region_state_detection.py \
    --video ../videos/camera_35.mp4 \
    --interactive
```

**Workflow:**
1. Draw Division boundary (overall monitored area)
2. For each table: Draw table surface → Draw sitting areas → Press 'D'
3. Draw Service Areas (bar, POS, prep stations)
4. Press Ctrl+S to save to `config/table_region_config.json`

**Keyboard Controls:**
- `Enter` - Complete current ROI polygon
- `D` - Finish current table, move to next
- `S` - Skip remaining tables, go to Service Areas
- `Ctrl+Z` or `U` - Undo last point/ROI
- `Ctrl+S` - Save all configurations
- `Q` - Quit

### Process Video with Existing Config
```bash
cd /path/to/production/RTX_3060/scripts
./run_with_config.sh

# Manual version (from scripts/ directory):
python3 video_processing/table_and_region_state_detection.py \
    --video ../videos/camera_35.mp4 \
    --duration 60  # Process only 60 seconds

# Full video:
python3 video_processing/table_and_region_state_detection.py \
    --video ../videos/camera_35.mp4
```

### Check Database State Changes
```bash
# Connect to SQLite database
sqlite3 ../db/detection_data.db

# View all sessions
SELECT * FROM sessions;

# View division state changes
SELECT frame_number, timestamp, state, walking_area_waiters, service_area_waiters
FROM division_states
WHERE session_id = '20251114_194300'
ORDER BY frame_number;

# View table state changes
SELECT frame_number, table_id, state, customers_count, waiters_count
FROM table_states
WHERE session_id = '20251114_194300'
ORDER BY frame_number;
```

### View Screenshots
```bash
# Screenshots saved automatically on every state change
ls -la ../db/screenshots/[session_id]/

# Division state changes
ls -la ../db/screenshots/[session_id]/division_*.jpg

# Table state changes
ls -la ../db/screenshots/[session_id]/T1_*.jpg
```

## System Monitoring

### monitoring/
Real-time system health monitoring and management.

**Scripts:**
- `check_disk_space.py` v2.0.0 - **Intelligent** disk space monitoring with predictive analytics
- `monitor_gpu.py` - GPU temperature and utilization tracking
- `system_health.py` - Comprehensive health check

**Key Features (v2.0.0):**
- **Intelligent Prediction**: Measures disk usage speed, predicts space needs
- **Proactive Cleanup**: Frees space BEFORE running out (not reactive)
- **Smart Cleanup**: Automatically deletes oldest videos when needed
- **Protected Dates**: Always keeps today + yesterday (for processing)
- **Critical Alerts**: Warns if can't store remaining day of videos
- **GPU Monitoring**: Real-time temperature and utilization
- **Exit Codes**: 0=healthy, 1=warning, 2=critical

**Usage (v2.0.0):**
```bash
# Check disk space with predictions (default)
python3 monitoring/check_disk_space.py --check

# Show detailed predictions
python3 monitoring/check_disk_space.py --predict

# Auto-cleanup with predictive target
python3 monitoring/check_disk_space.py --cleanup

# Dry run (test without deleting)
python3 monitoring/check_disk_space.py --cleanup --dry-run

# Disable predictions (use basic check only)
python3 monitoring/check_disk_space.py --check --no-prediction

# Monitor GPU
python3 monitoring/monitor_gpu.py

# Watch GPU continuously
python3 monitoring/monitor_gpu.py --watch 30

# Full health check
python3 monitoring/system_health.py
```

**Intelligent Prediction Logic (v2.0.0):**
1. Check if recording is active (pgrep capture_rtsp_streams)
2. Calculate remaining recording hours (until 9 PM)
3. Measure disk usage speed (observe 30 seconds)
4. Calculate: Rate (GB/hour) × Remaining hours = Predicted usage
5. Add 20% safety margin
6. Compare predicted free space vs current
7. Proactive cleanup if prediction shows future shortage

**Smart Cleanup Logic (v2.0.0):**

Three-phase intelligent cleanup with different retention policies:

**Phase 1: Screenshot Cleanup**
- Retention: 30 days
- Location: `db/screenshots/`
- Logic: Delete screenshots older than 30 days
- Always runs (independent of disk space)

**Phase 2: Raw Video Cleanup (Intelligent)**
- Retention: Max 2 days (or delete when processed)
- Location: `videos/YYYYMMDD/camera_XX/`
- Logic:
  - **Today (age=0)**: Always keep (currently recording)
  - **≥1 day + processed**: Delete (has results in `results/`)
  - **>2 days**: Delete unconditionally (max retention limit)
- Smart detection: Checks if `results/YYYYMMDD/camera_XX/*.mp4` exists
- Result: Raw videos deleted as soon as processed, freeing space faster

**Phase 3: Processed Video Cleanup**
- Retention: 2 days
- Location: `results/YYYYMMDD/`
- Logic: Delete folders older than 2 days
- Simple age-based cleanup

**Phase 4: Database (Permanent Storage)**
- Retention: ♾️ **Permanent** (never deleted)
- Location: `db/detection_data.db`
- Contains all state change history for business analytics

**Cleanup Priority:**
1. Screenshots (30 days) → Free up screenshot storage
2. Raw videos (intelligent) → Free up largest storage (raw footage)
3. Processed videos (2 days) → Free up processed results
4. Database → **Never deleted** (permanent business data)

**Automated Monitoring:**
Disk space check runs **hourly** via cron (see `deployment/install_cron_jobs.sh`)
- **Changed from 2-hour to 1-hour intervals for better prediction accuracy**
- Automatically triggers cleanup when space < 100GB or prediction shows shortage

## Configuration Files

**Location:** All configuration files are stored in `scripts/config/`

### config/table_region_config.json
**Structure:**
```json
{
  "division": [[x1,y1], [x2,y2], ...],
  "tables": [
    {
      "id": "T1",
      "polygon": [[x1,y1], ...],
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
  "frame_size": [1920, 1080],
  "video": "../videos/camera_35.mp4"
}
```

**Current Setup:** 5 tables, 10 sitting areas, 2 service areas (1920x1080)

## ROI Hierarchy and Logic

### Region Priority (Assignment Order)
1. **Tables** - Individual table surfaces
2. **Sitting Areas** - Chairs/seating (linked to tables)
3. **Service Areas** - Bar, POS, prep stations
4. **Walking Areas** - Implicit (remaining division area)

### Table State Logic
```
IDLE (Green):     customers=0 AND waiters=0
BUSY (Yellow):    customers>0 AND waiters=0
CLEANING (Blue):  waiters>0 (any count)
```

### Division State Logic
```
RED (Understaffed): service_waiters=0 AND walking_waiters=0
YELLOW (Busy):      service_waiters>0 (staff at service area)
GREEN (Serving):    walking_waiters>0 (staff in walking area)
```

**Debouncing:** All state transitions require 1.0s stability to prevent flickering.

## Performance Characteristics

**Validated 2025-11-13 on RTX 3060 Linux:**
- Processing Speed: 3.24x real-time at 5fps
- GPU Utilization: 71.4% (stable)
- Frame Time: 61.7ms/frame average
- Capacity: 100 hours in 17.1 hours (dual-threaded)

**Production Workload (Testing - 1 camera):**
- 1 camera × 7.5 hours = 7.5 hours daily footage (2.5h morning + 5h evening)
- Processing window: 12:00 AM - 11:00 PM (23 hours available)
- Current performance: Processes at 3.24x real-time at 5fps
- Target completion: 11:00 PM (before next day's 11:30 AM capture)

## Database Schema

**sessions** - Video processing sessions
```sql
session_id TEXT PRIMARY KEY
video_file TEXT
start_time TEXT
end_time TEXT
total_frames INTEGER
fps REAL
resolution TEXT
config_file TEXT
```

**division_states** - Division state changes
```sql
session_id TEXT
frame_number INTEGER
timestamp REAL
state TEXT (RED/YELLOW/GREEN)
walking_area_waiters INTEGER
service_area_waiters INTEGER
screenshot_path TEXT
```

**table_states** - Table state changes
```sql
session_id TEXT
frame_number INTEGER
timestamp REAL
table_id TEXT
state TEXT (IDLE/BUSY/CLEANING)
customers_count INTEGER
waiters_count INTEGER
screenshot_path TEXT
```

## Output Files

**Video Output:**
- Location: `../results/`
- Format: H.264 MP4 (hardware accelerated)
- Naming: `table_and_region_state_detection_[input_name].mp4`
- Compression: ~90% smaller than raw (H.264 vs uncompressed)

**Database Output:**
- Location: `../db/detection_data.db`
- All state transitions logged with timestamps
- Indexed for fast queries by session/frame/table

**Screenshots:**
- Location: `../db/screenshots/[session_id]/`
- Saved automatically on every state change
- Quality: 95% JPEG
- Naming: `[prefix]frame_[number].jpg`

## Development Notes

**Model Paths:**
- Relative to script location: `../models/yolov8m.pt`
- Relative to script location: `../models/waiter_customer_classifier.pt`
- Both models must exist or script fails on startup

**Detection Parameters:**
```python
PERSON_CONF_THRESHOLD = 0.3  # Person detection confidence
STAFF_CONF_THRESHOLD = 0.5   # Staff classification confidence
MIN_PERSON_SIZE = 40         # Minimum bbox size (pixels)
STATE_DEBOUNCE_SECONDS = 1.0 # State transition debounce
```

**Color Coding:**
```python
# Table states
IDLE: (0, 255, 0)      # Green
BUSY: (0, 255, 255)    # Yellow
CLEANING: (255, 0, 0)  # Blue

# Division states
RED: (0, 0, 255)       # Understaffed
YELLOW: (0, 255, 255)  # Busy
GREEN: (0, 255, 0)     # Serving

# ROI boundaries
Division: (255, 255, 0)     # Cyan
Service: (255, 0, 255)      # Magenta
Sitting: (128, 128, 128)    # Gray
```

## Deployment Checklist

**Before deploying to RTX 3060:**
1. ✅ Models present in `models/` directory
2. ✅ Configuration file created (run interactive mode first)
3. ✅ Camera RTSP connection configured (camera_35)
4. ⏳ Cloud upload pipeline (Supabase) setup
5. ✅ Cron job for automated scheduling
6. ✅ Error handling and health monitoring
7. ✅ Disk space monitoring (videos + screenshots + DB)

## Important Warnings

1. **Scripts reorganized into feature directories** - See `scripts/STRUCTURE.md` for navigation
2. **DO NOT modify production scripts directly** - Test in `tests/test-scripts/` first
3. **DO NOT run interactive mode on production videos** - Use pre-created configs
4. **Monitor disk space** - H.264 videos + screenshots + DB can grow quickly
5. **Database grows infinitely** - Implement rotation/cleanup policy
6. **Screenshot directory grows** - Consider cleanup after video upload
7. **GPU memory leak risk** - Monitor long-running processes
8. **RTSP connection stability** - Handle reconnection gracefully

## Deployment Tools

### Camera Management Tool

**Script:** `scripts/deployment/manage_cameras.py`

Interactive tool for managing camera configurations after initial deployment.

**Features:**
- List all cameras with details
- Add new cameras (prompts for IP, credentials, port, stream path)
- Edit existing cameras (update any configuration)
- Remove cameras (soft delete in database)
- Test RTSP connections (OpenCV validation)

**Usage:**
```bash
# Interactive menu
python3 scripts/deployment/manage_cameras.py

# Command line
python3 scripts/deployment/manage_cameras.py --list
python3 scripts/deployment/manage_cameras.py --add
```

**What it updates:**
- `scripts/config/cameras_config.json` - Main camera configuration
- Local SQLite database - Camera records
- Validates IP addresses and tests connections

### Configuration Files

**Location:** `scripts/config/`

**Primary Configuration Files:**
1. **`cameras_config.json`** - Main camera configuration
   - Format required by `capture_rtsp_streams.py`
   - Contains: IP, port, username, password, stream_path, resolution, FPS
   - Updated by: `initialize_restaurant.py` and `manage_cameras.py`

2. **`table_region_config.json`** - ROI configuration for detection
   - Division boundaries, table polygons, sitting areas, service areas
   - Created by: Interactive ROI setup mode
   - Used by: Video processing scripts

3. **`{location_id}_cameras.json`** - Location-specific camera backup
   - Derivative of main cameras_config.json
   - Contains database format with additional metadata
   - Auto-generated during initialization

4. **`{location_id}_location.json`** - Location metadata
   - City, restaurant name, commercial area, address, region
   - Created during initial deployment

---

## Recent Improvements (2025-11-16)

### 1. Camera Credential Collection
**File:** `scripts/deployment/initialize_restaurant.py` v1.1.0

**Problem:** Initial deployment script did not ask for camera usernames and passwords.

**Solution:** Added prompts for each camera:
- Username (default: admin)
- Password (default: 123456)
- Port (default: 554)
- Stream path (default: /media/video1)

**Impact:** Proper RTSP authentication configuration during initial setup.

### 2. Camera Management Tool
**File:** `scripts/deployment/manage_cameras.py` (new)

**Problem:** No way to add/remove/edit cameras after initial deployment.

**Solution:** Created interactive management tool with full CRUD operations for cameras.

**Impact:** Flexible camera configuration throughout system lifecycle.

### 3. Robust Startup System
**Files:** `start.sh` (new), `scripts/deployment/ase_surveillance.service` (existing)

**Problem:** Need daemon-level protection with auto-restart and crash recovery.

**Solution:** Two-layer protection system:
- **Layer 1:** Shell script wrapper (`start.sh`) with infinite loop auto-restart
- **Layer 2:** Systemd service with `Restart=on-failure`

**Features:**
- Auto-restart on crash (10-second delay)
- Pre-flight checks (database, models, disk space, network)
- Graceful shutdown (SIGTERM → 30s wait → SIGKILL)
- PID file management (prevents duplicate instances)
- Comprehensive logging to `logs/startup.log`
- Foreground/background modes

**Impact:** Production-grade reliability with automatic crash recovery and system-level daemon protection.

### 4. Architecture Refactoring v4.0 (2025-11-16)
**Files:** `main.py` (new), `scripts/deployment/initialize_restaurant.py` (refactored)

**Problem:** Confusing architecture with overlapping responsibilities:
- `start.sh` mixed configuration and startup
- `interactive_start.py` mixed configuration and service launching
- `initialize_restaurant.py` incomplete (missing ROI, camera editing)
- PID file conflicts between multiple startup methods
- Unclear separation between configuration and production deployment

**Solution:** Complete architecture refactoring with clear separation:

**New Architecture:**
```
main.py (Unified Entry Point)
  ├─ Interactive menu for all operations
  ├─ Configuration → initialize_restaurant.py
  ├─ View config → Read-only display
  ├─ Start service (dev) → Direct Python call
  └─ Production guide → Systemd instructions

initialize_restaurant.py v4.0 (Configuration Only)
  ├─ Complete configuration wizard (merged from interactive_start.py)
  ├─ Camera CRUD (add/edit/delete)
  ├─ ROI interactive drawing
  ├─ System health checks
  └─ NO SERVICE STARTUP (redirects to systemd)

systemd (Production Startup)
  └─ surveillance_service.py (Direct, no wrappers)
```

**Key Changes:**
- ✅ `main.py` - Single, clear entry point for all operations
- ✅ `initialize_restaurant.py` - All configuration features, zero startup code
- ✅ Deprecated `start.sh` and `interactive_start.py` (kept for reference)
- ✅ Systemd as sole production startup method
- ✅ Clear documentation of configuration vs startup separation

**Benefits:**
- 🎯 Clear responsibility: Configure once, start with systemd
- 🚀 No PID file conflicts (systemd manages process directly)
- 📖 Simpler user workflow (main.py → configure → systemctl start)
- 🔧 All interactive features in one place (initialize_restaurant.py)
- 💪 Production-ready with system-level daemon protection

**Migration Path:**
- Old: `./start.sh` → New: `python3 main.py` then `systemctl start`
- Old: `interactive_start.py` → New: `main.py --configure`
- Old: Basic `initialize_restaurant.py` → New: Full-featured configuration wizard

---

## Next Steps for Production

1. ✅ **Camera Management** - Tool created for add/remove/edit cameras
2. ✅ **Robust Startup** - Shell wrapper and systemd service implemented
3. ✅ **Credential Configuration** - Initialization wizard updated
4. ✅ **Architecture Refactoring** - v4.0 complete (main.py + clear separation)
5. ⏳ **ROI Configuration** - Set up table/region polygons for detection
6. ⏳ **Cloud Upload Pipeline** - Results to Supabase after processing
7. ⏳ **Monitoring Dashboard** - Real-time status, GPU usage, disk space
8. ⏳ **Database Cleanup** - Auto-rotate old sessions, compress screenshots
