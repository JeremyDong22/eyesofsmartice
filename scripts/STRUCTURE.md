# Scripts Organization Guide

**Version:** 1.0.0
**Last Updated:** 2025-11-16

This document provides a detailed navigation guide for the feature-based organization of the `scripts/` directory.

---

## Directory Structure Overview

```
scripts/
├── STRUCTURE.md              # This file - navigation guide
├── camera_testing/           # Camera connection validation
├── config/                   # Centralized configuration files
├── database_sync/            # Database operations and cloud sync
├── deployment/               # Initial setup and deployment
├── maintenance/              # System cleanup and maintenance
├── monitoring/               # Health monitoring and alerts
├── orchestration/            # Multi-camera batch processing
├── time_sync/                # Time synchronization
├── video_capture/            # RTSP stream recording
└── video_processing/         # AI detection and analysis
```

---

## Detailed Directory Reference

### 📹 camera_testing/

**Purpose:** Camera connection testing and validation

**Scripts:**
- `test_camera_connections.py` - Validate RTSP connections to all cameras
- `quick_camera_test.sh` - Fast connectivity check
- `run_camera_test.sh` - Full camera validation suite

**When to use:**
- Before deployment to verify camera connectivity
- Troubleshooting camera connection issues
- Testing new camera configurations

---

### ⚙️ config/

**Purpose:** Centralized configuration files

**Files:**
- `cameras_config.json` - Camera IP addresses, credentials, and settings
- `table_region_config.json` - ROI polygons for table and region detection

**Format:**
All configuration files use JSON format for easy parsing and editing.

**When to modify:**
- Adding/removing cameras
- Updating camera IP addresses
- Adjusting detection ROI boundaries

---

### 💾 database_sync/

**Purpose:** Database operations and cloud synchronization

**Scripts:**
- `batch_db_writer.py` - High-performance batch insert (100× faster than individual inserts)
- `sync_to_supabase.py` - Hourly cloud sync to Supabase

**Key Features:**
- Batch operations for efficiency
- Automatic retry logic
- Conflict resolution
- Hourly synchronization

**When to use:**
- Manual database sync
- Testing cloud connectivity
- Debugging sync issues

---

### 🚀 deployment/

**Purpose:** Initial setup and deployment automation

**Scripts:**
- `initialize_restaurant.py` - Interactive setup wizard (location + cameras)
- `migrate_database.py` - Database schema migration
- `install_cron_jobs.sh` - Install automated scheduling (cron)
- `install_service.sh` - Install systemd service for auto-start
- `ase_surveillance.service` - Systemd service configuration

**Workflow:**
1. Run `migrate_database.py` to set up database schema
2. Run `initialize_restaurant.py` to configure location and cameras
3. Run `install_cron_jobs.sh` to set up automated tasks
4. Run `install_service.sh` to enable auto-start on boot

**When to use:**
- First-time deployment
- Re-initialization after major changes
- Setting up automated scheduling

---

### 🧹 maintenance/

**Purpose:** System cleanup and maintenance

**Scripts:**
- `cleanup_old_videos.sh` - Delete old raw and processed videos (2-day retention)
- `cleanup_logs.sh` - Rotate log files (30-day retention, 500MB limit)

**Retention Policies:**
- Raw videos: Max 2 days (deleted after processing)
- Processed videos: 2 days
- Screenshots: 30 days
- Logs: 30 days OR 500MB total
- Database: Permanent (never deleted)

**Automation:**
- Runs daily at 2 AM (logs) and 3 AM (videos) via cron

**When to use:**
- Manual cleanup before cron schedule
- Freeing disk space urgently
- Testing cleanup logic

---

### 🏥 monitoring/

**Purpose:** System health monitoring and alerts

**Scripts:**
- `check_disk_space.py` - Predictive disk space monitoring with auto-cleanup
- `monitor_gpu.py` - GPU temperature and utilization tracking
- `system_health.py` - Comprehensive health check

**Key Features:**
- Predictive disk space analysis (calculates future needs)
- GPU temperature alerts (>80°C critical)
- Automatic cleanup triggers
- Exit codes for automation (0=OK, 1=warning, 2=critical)

**Automation:**
- Disk check: Every hour
- GPU check: Every 5 minutes during processing

**When to use:**
- Troubleshooting system issues
- Manual health checks
- Verifying monitoring automation

---

### 🎯 orchestration/

**Purpose:** Multi-camera batch processing coordination

**Scripts:**
- `process_videos_orchestrator.py` - Dynamic GPU scaling, batch processing
- `surveillance_service.py` - Automated service daemon (main automation)

**Key Features:**
- Dynamic GPU worker scaling (1-8 workers based on temperature)
- Intelligent queue management
- Auto-restart on failure
- Time-based scheduling (11 PM - 6 AM processing)

**Architecture:**
```
surveillance_service.py (main daemon)
├── Scheduler Thread (time-based task management)
├── Monitoring Threads (disk, GPU, DB sync, health)
└── Worker Processes (capture, processing)
```

**When to use:**
- Starting the automated service
- Batch processing multiple videos
- Manual processing outside scheduled hours

---

### ⏰ time_sync/

**Purpose:** Time synchronization with Beijing time

**Scripts:**
- `setup_ntp.sh` - Configure NTP synchronization (Asia/Shanghai)
- `verify_time_sync.sh` - Verify time accuracy

**Importance:**
Critical for accurate timestamp recording and scheduled task execution.

**When to use:**
- Initial deployment setup
- Troubleshooting time drift
- After system timezone changes

---

### 📹 video_capture/

**Purpose:** RTSP stream recording

**Scripts:**
- `capture_rtsp_streams.py` - Multi-camera RTSP capture with FPS-based disconnect detection

**Key Features:**
- Multi-threaded capture (one thread per camera)
- FPS-based disconnect detection (< 2 FPS = immediate segmentation)
- Automatic reconnection (10-second retry interval)
- Network health checks (RTT monitoring)
- H.264 encoding for space efficiency

**Performance:**
- Captures 10 cameras simultaneously
- Automatic segmentation on network disconnect
- Coverage tracking and reporting

**When to use:**
- Manual video capture
- Testing camera connections
- Debugging capture issues

---

### 🤖 video_processing/

**Purpose:** AI detection and analysis

**Scripts:**
- `table_and_region_state_detection.py` - Main detection pipeline (two-stage detection)

**Detection Pipeline:**
```
Stage 1: Person Detection (yolov8m.pt)
   ↓
Stage 2: Staff Classification (waiter_customer_classifier.pt)
   ↓
ROI Assignment (tables, sitting areas, service areas, walking areas)
   ↓
State Detection (table states, division states)
   ↓
Output (H.264 video, SQLite database, screenshots)
```

**States Tracked:**
- **Table States:** IDLE, BUSY, CLEANING
- **Division States:** RED (understaffed), YELLOW (busy), GREEN (serving)

**Performance:**
- 3.24× real-time at 5 FPS (RTX 3060)
- 61.7ms per frame average

**When to use:**
- Processing recorded videos
- Interactive ROI configuration
- Testing detection accuracy

---

## Common Workflows

### First-Time Deployment

```bash
# 1. Database migration
python3 scripts/deployment/migrate_database.py --backup

# 2. Initialize location and cameras
python3 scripts/deployment/initialize_restaurant.py

# 3. Install automated scheduling
bash scripts/deployment/install_cron_jobs.sh --install

# 4. Install systemd service (optional - for auto-start on boot)
sudo bash scripts/deployment/install_service.sh

# 5. Start the automated service
python3 start.py
```

### Manual Video Processing

```bash
# Process a specific video
python3 scripts/video_processing/table_and_region_state_detection.py \
    --video videos/20251116/camera_35/video.mp4

# Process all unprocessed videos
python3 scripts/orchestration/process_videos_orchestrator.py
```

### System Maintenance

```bash
# Check system health
python3 scripts/monitoring/system_health.py

# Manual cleanup
bash scripts/maintenance/cleanup_old_videos.sh --dry-run
bash scripts/maintenance/cleanup_logs.sh --dry-run

# Check disk space
python3 scripts/monitoring/check_disk_space.py --check
```

### Debugging

```bash
# Test camera connections
python3 scripts/camera_testing/test_camera_connections.py

# Check GPU status
python3 scripts/monitoring/monitor_gpu.py

# Verify time sync
bash scripts/time_sync/verify_time_sync.sh

# View service logs
tail -f logs/surveillance_service.log
```

---

## Script Dependencies

### External Dependencies
- Python 3.7+
- OpenCV (`opencv-python`)
- Ultralytics YOLO (`ultralytics`)
- Supabase client (`supabase-py`)
- NVIDIA drivers + CUDA (for GPU acceleration)

### Internal Dependencies
- All scripts reference `scripts/config/` for configuration
- Detection scripts require models in `models/` directory
- Database scripts require `db/detection_data.db`

---

## Naming Conventions

### Scripts
- Python: `snake_case.py`
- Shell: `kebab-case.sh` or `snake_case.sh`

### Directories
- Feature-based: `video_capture/`, `video_processing/`
- Descriptive: `camera_testing/`, `database_sync/`

### Configuration
- JSON format: `cameras_config.json`, `table_region_config.json`
- Descriptive names reflecting content

---

## Adding New Scripts

When adding new scripts, follow this structure:

1. **Identify the feature category** - Which directory best fits this script?
2. **Follow naming conventions** - Use snake_case for Python, descriptive names
3. **Add documentation** - Include docstring with purpose, usage, and version
4. **Update this file** - Add entry to appropriate section
5. **Update CLAUDE.md** - Document in project overview if major feature

---

## Quick Reference

| Task | Script | Location |
|------|--------|----------|
| Test cameras | `test_camera_connections.py` | camera_testing/ |
| Capture video | `capture_rtsp_streams.py` | video_capture/ |
| Process video | `table_and_region_state_detection.py` | video_processing/ |
| Batch processing | `process_videos_orchestrator.py` | orchestration/ |
| Check disk space | `check_disk_space.py` | monitoring/ |
| Clean up videos | `cleanup_old_videos.sh` | maintenance/ |
| Sync to cloud | `sync_to_supabase.py` | database_sync/ |
| Set up system | `initialize_restaurant.py` | deployment/ |
| Start service | `surveillance_service.py` | orchestration/ |

---

## Version History

- **1.0.0** (2025-11-16): Initial creation, comprehensive documentation of all script directories

---

For questions or issues, refer to the main project documentation in `CLAUDE.md`.
