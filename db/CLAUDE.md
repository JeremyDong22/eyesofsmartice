# CLOUD.md

Cloud Database Architecture for ASE Multi-Restaurant Surveillance System

Last Updated: 2025-11-15
Version: 1.0.0

## Overview

This document describes the Supabase cloud database schema, naming conventions, and sync architecture for the ASE (Advanced Surveillance Engine) multi-restaurant deployment.

**Key Principle:** Database records ONLY (no screenshots, no videos) are synced to Supabase for business analytics and multi-location management.

---

## Table Naming Convention

**All Supabase tables use the `ASE_` prefix**

This prefix distinguishes ASE project tables from other projects in the same Supabase instance.

| Local SQLite Table | Supabase Table | Purpose |
|-------------------|----------------|---------|
| `locations` | `ASE_locations` | Restaurant locations |
| `cameras` | `ASE_cameras` | Camera hardware |
| `camera_rois` | `ASE_camera_rois` | ROI configurations (versioned) |
| `videos` | `ASE_videos` | Video file metadata (not files) |
| `sessions` | `ASE_sessions` | Processing sessions |
| `division_states` | `ASE_division_states` | Division state changes |
| `table_states` | `ASE_table_states` | Table state changes |
| - | `ASE_sync_status` | Sync operation tracking |

---

## Supabase Project Details

**Project URL:** `https://wdpeoyugsxqnpwwtkqsl.supabase.co`

**Authentication:**
- Uses `SUPABASE_URL` and `SUPABASE_ANON_KEY` environment variables
- Anon key is safe for client-side use (Row Level Security enforced)

**Region:** Asia Pacific (optimal for Sichuan locations)

---

## Schema Architecture

### 1. Location Identification (Unique Restaurant Identity)

**Table:** `ASE_locations`

**Unique Identifier Components:**
1. **City** (e.g., "Mianyang", "Chengdu")
2. **Restaurant Name** (e.g., "YeBaiLingHotpot")
3. **Commercial Area** (e.g., "1958CommercialDistrict")

**Generated `location_id` Format:**
```
{city}_{restaurant}_{area}
```
Lowercase, no spaces, underscores only.

**Example:**
```
mianyang_yebailinghotpot_1958commercialdistrict
```

**Why This Matters:**
- Different restaurants may have same internal camera IP addresses (e.g., 192.168.1.100)
- `location_id` ensures cameras with same IP are distinguished by restaurant
- Enables multi-location deployment without IP conflicts

**Schema:**
```sql
CREATE TABLE ASE_locations (
    location_id TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    restaurant_name TEXT NOT NULL,
    commercial_area TEXT NOT NULL,
    address TEXT,
    region TEXT,
    timezone TEXT DEFAULT 'Asia/Shanghai',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE(city, restaurant_name, commercial_area)
);
```

---

### 2. Camera Configuration

**Table:** `ASE_cameras`

**Camera ID Format:**
```
camera_{ip_last_segment}
```

**Example:**
- IP: `202.168.40.35` → Camera ID: `camera_35`
- IP: `192.168.1.22` → Camera ID: `camera_22`

**Important:** Same camera ID can exist across different locations (distinguished by `location_id`)

**Schema:**
```sql
CREATE TABLE ASE_cameras (
    camera_id TEXT PRIMARY KEY,
    location_id TEXT NOT NULL REFERENCES ASE_locations(location_id) ON DELETE CASCADE,
    camera_name TEXT,
    camera_ip_address TEXT NOT NULL,
    rtsp_endpoint TEXT,
    camera_type TEXT DEFAULT 'UNV',
    resolution TEXT,
    installation_date DATE,
    division_name TEXT,
    division_description TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(location_id, camera_ip_address)
);
```

**Key Constraint:**
- `UNIQUE(location_id, camera_ip_address)` - Same IP allowed across different restaurants

---

### 3. ROI Configuration (Versioned)

**Table:** `ASE_camera_rois`

**Purpose:**
- Store region-of-interest configurations for each camera
- Version tracking enables ROI changes over time
- Historical processing sessions reference specific ROI versions

**ROI Types:**
- `division` - Overall monitored area
- `table` - Individual table surfaces
- `sitting` - Seating areas (linked to tables)
- `service` - Service counters, POS, prep stations

**Schema:**
```sql
CREATE TABLE ASE_camera_rois (
    roi_id SERIAL PRIMARY KEY,
    camera_id TEXT NOT NULL REFERENCES ASE_cameras(camera_id) ON DELETE CASCADE,
    roi_version INTEGER DEFAULT 1,
    roi_type TEXT NOT NULL CHECK (roi_type IN ('division', 'table', 'sitting', 'service')),
    roi_identifier TEXT NOT NULL,  -- e.g., "T1", "SA1", "SV1"
    polygon_points JSONB NOT NULL,  -- Array of [x, y] coordinates
    linked_to_roi_id TEXT,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(camera_id, roi_identifier, roi_version)
);
```

**Version Strategy:**
- Version 1: Initial ROI configuration
- Version 2+: Updated configurations (e.g., restaurant layout changes)
- Sessions reference `roi_version` to ensure reproducible analysis

---

### 4. Video Metadata (Not Video Files)

**Table:** `ASE_videos`

**Important:** Only metadata is stored in Supabase, NOT actual video files.

**Storage Locations:**
- `local` - Video on RTX machine (videos/YYYYMMDD/camera_XX/)
- `cloud` - Uploaded to Supabase Storage (if implemented later)
- `archive` - Moved to archive/cold storage
- `deleted` - Cleaned up locally

**Schema:**
```sql
CREATE TABLE ASE_videos (
    video_id SERIAL PRIMARY KEY,
    camera_id TEXT NOT NULL REFERENCES ASE_cameras(camera_id) ON DELETE CASCADE,
    video_filename TEXT NOT NULL,
    video_date DATE NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    duration_seconds INTEGER,
    file_size_bytes BIGINT,
    fps REAL,
    resolution TEXT,
    is_processed BOOLEAN DEFAULT FALSE,
    storage_location TEXT DEFAULT 'local',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(camera_id, video_filename)
);
```

---

### 5. Processing Sessions

**Table:** `ASE_sessions`

**Session ID Format:**
```
YYYYMMDD_HHMMSS_{camera_id}
```

**Example:** `20251115_143000_camera_35`

**Links Together:**
- Which camera was used
- Which video was processed
- Which location (restaurant)
- Which ROI version was applied
- Processing results and status

**Schema:**
```sql
CREATE TABLE ASE_sessions (
    session_id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL REFERENCES ASE_cameras(camera_id) ON DELETE CASCADE,
    video_id INTEGER NOT NULL REFERENCES ASE_videos(video_id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES ASE_locations(location_id) ON DELETE CASCADE,
    config_file_path TEXT,
    roi_version INTEGER,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    end_time TIMESTAMP WITH TIME ZONE,
    total_frames INTEGER,
    fps REAL,
    resolution TEXT,
    processing_status TEXT DEFAULT 'pending',
    processing_time_seconds REAL,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

### 6. State Change Tracking (Core Business Data)

**Tables:** `ASE_division_states` and `ASE_table_states`

**Purpose:** Track all detected state changes over time for business analytics

#### Division States

**States:**
- `RED` - Understaffed (no waiters in walking or service areas)
- `YELLOW` - Busy (waiters in service area only)
- `GREEN` - Serving (waiters in walking area)

**Schema:**
```sql
CREATE TABLE ASE_division_states (
    division_state_id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES ASE_sessions(session_id) ON DELETE CASCADE,
    camera_id TEXT NOT NULL REFERENCES ASE_cameras(camera_id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES ASE_locations(location_id) ON DELETE CASCADE,
    frame_number INTEGER NOT NULL,
    timestamp_video REAL NOT NULL,  -- Video timestamp in seconds
    timestamp_recorded TIMESTAMP WITH TIME ZONE NOT NULL,  -- Wall clock time
    state TEXT NOT NULL CHECK (state IN ('RED', 'YELLOW', 'GREEN')),
    walking_area_waiters INTEGER DEFAULT 0,
    service_area_waiters INTEGER DEFAULT 0,
    total_staff INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

#### Table States

**States:**
- `IDLE` - No customers, no waiters (table available)
- `BUSY` - Customers present, no waiters (needs service)
- `CLEANING` - Waiters present (cleaning or serving)

**Schema:**
```sql
CREATE TABLE ASE_table_states (
    table_state_id SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES ASE_sessions(session_id) ON DELETE CASCADE,
    camera_id TEXT NOT NULL REFERENCES ASE_cameras(camera_id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES ASE_locations(location_id) ON DELETE CASCADE,
    frame_number INTEGER NOT NULL,
    timestamp_video REAL NOT NULL,
    timestamp_recorded TIMESTAMP WITH TIME ZONE NOT NULL,
    table_id TEXT NOT NULL,  -- e.g., "T1", "T2"
    state TEXT NOT NULL CHECK (state IN ('IDLE', 'BUSY', 'CLEANING')),
    customers_count INTEGER DEFAULT 0,
    waiters_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

**Important:** No `screenshot_path` in Supabase (screenshots NOT uploaded)

---

### 7. Sync Status Tracking

**Table:** `ASE_sync_status`

**Purpose:** Track sync operations from local RTX machines to Supabase

**Schema:**
```sql
CREATE TABLE ASE_sync_status (
    sync_id SERIAL PRIMARY KEY,
    location_id TEXT NOT NULL REFERENCES ASE_locations(location_id) ON DELETE CASCADE,
    sync_type TEXT NOT NULL,  -- 'division_states', 'table_states', 'sessions', etc.
    last_sync_time TIMESTAMP WITH TIME ZONE NOT NULL,
    records_synced INTEGER DEFAULT 0,
    status TEXT NOT NULL CHECK (status IN ('success', 'partial', 'failed')),
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
```

---

## Data Flow Architecture

### Local → Cloud Sync Strategy

```
┌─────────────────────────────────────────────────────────────────┐
│                    Local RTX 3060 Machine                       │
│                         (Edge Processing)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SQLite Database (detection_data.db)                           │
│  ├── 24-hour transactional buffer                              │
│  ├── Fast writes during processing                             │
│  ├── synced_to_cloud flag (0 = pending, 1 = synced)           │
│  └── Auto-cleanup after successful sync                        │
│                                                                 │
│  Hourly Cron Job:                                              │
│  └── python3 sync_to_supabase.py --mode hourly                 │
│      ├── Upload new records from last 2 hours                  │
│      ├── Mark uploaded records as synced                       │
│      └── Delete synced records older than 24h                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                          ▲ Hourly Upload ▲
                          │ (Database Only) │
                          ▼                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Supabase Cloud Database                      │
│                      (PostgreSQL + Analytics)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ASE_locations        → Restaurant master data (permanent)     │
│  ASE_cameras          → Camera configurations (permanent)      │
│  ASE_camera_rois      → ROI configs (versioned, permanent)     │
│  ASE_videos           → Video metadata (90 days)               │
│  ASE_sessions         → Processing sessions (90 days)          │
│  ASE_division_states  → State changes (90 days)                │
│  ASE_table_states     → State changes (90 days)                │
│  ASE_sync_status      → Sync logs (30 days)                    │
│                                                                 │
│  Business Analytics:                                            │
│  └── Dashboard queries across all locations                    │
│  └── Historical trend analysis                                 │
│  └── Multi-restaurant comparisons                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### What Gets Synced vs What Stays Local

| Data Type | Local Storage | Supabase Cloud | Rationale |
|-----------|---------------|----------------|-----------|
| **Raw Videos** | ✅ Yes (2 days) | ❌ No | Too large (80GB/day/camera) |
| **Processed Videos** | ✅ Yes (7 days) | ❌ No | Large files, limited value |
| **Screenshots** | ✅ Yes (7 days) | ❌ No | Many small files, visual verification only |
| **Video Metadata** | ✅ Yes (cache) | ✅ Yes (90d) | Small, enables cloud tracking |
| **Sessions** | ✅ Yes (cache) | ✅ Yes (90d) | Processing history |
| **Division States** | ✅ Yes (24h buffer) | ✅ Yes (90d) | **Core business data** |
| **Table States** | ✅ Yes (24h buffer) | ✅ Yes (90d) | **Core business data** |
| **ROI Configs** | ✅ Yes (cache) | ✅ Yes (permanent) | Configuration management |
| **Location/Camera** | ✅ Yes (cache) | ✅ Yes (permanent) | Master data |

---

## Indexes for Performance

**Critical indexes for analytics queries:**

```sql
-- Division states: Query by location, time range, state
CREATE INDEX idx_ase_division_location_time
ON ASE_division_states(location_id, timestamp_recorded DESC);

CREATE INDEX idx_ase_division_location_state_time
ON ASE_division_states(location_id, state, timestamp_recorded DESC);

-- Table states: Query by location, table, time range
CREATE INDEX idx_ase_table_location_table_time
ON ASE_table_states(location_id, table_id, timestamp_recorded DESC);

CREATE INDEX idx_ase_table_location_state_time
ON ASE_table_states(location_id, state, timestamp_recorded DESC);

-- Session lookups
CREATE INDEX idx_ase_sessions_camera
ON ASE_sessions(camera_id, created_at DESC);

CREATE INDEX idx_ase_sessions_location
ON ASE_sessions(location_id, created_at DESC);
```

---

## Common Queries

### 1. Get All Locations

```sql
SELECT location_id, city, restaurant_name, commercial_area
FROM ASE_locations
WHERE is_active = TRUE
ORDER BY city, restaurant_name;
```

### 2. Get Cameras for a Location

```sql
SELECT camera_id, camera_name, camera_ip_address, status
FROM ASE_cameras
WHERE location_id = 'mianyang_yebailinghotpot_1958commercialdistrict'
  AND status = 'active'
ORDER BY camera_id;
```

### 3. Division State Timeline for Today

```sql
SELECT
    timestamp_recorded,
    state,
    walking_area_waiters,
    service_area_waiters,
    total_staff
FROM ASE_division_states
WHERE location_id = 'mianyang_yebailinghotpot_1958commercialdistrict'
  AND camera_id = 'camera_35'
  AND timestamp_recorded >= CURRENT_DATE
ORDER BY timestamp_recorded;
```

### 4. Table Turnover Analysis

```sql
-- Count table state transitions for a day
SELECT
    table_id,
    COUNT(*) FILTER (WHERE state = 'IDLE') as idle_count,
    COUNT(*) FILTER (WHERE state = 'BUSY') as busy_count,
    COUNT(*) FILTER (WHERE state = 'CLEANING') as cleaning_count
FROM ASE_table_states
WHERE location_id = 'mianyang_yebailinghotpot_1958commercialdistrict'
  AND timestamp_recorded >= CURRENT_DATE
GROUP BY table_id
ORDER BY table_id;
```

### 5. Understaffed Incidents (RED State)

```sql
SELECT
    timestamp_recorded,
    EXTRACT(EPOCH FROM (
        LEAD(timestamp_recorded) OVER (ORDER BY timestamp_recorded) - timestamp_recorded
    )) / 60 as duration_minutes
FROM ASE_division_states
WHERE location_id = 'mianyang_yebailinghotpot_1958commercialdistrict'
  AND camera_id = 'camera_35'
  AND state = 'RED'
  AND timestamp_recorded >= CURRENT_DATE
ORDER BY timestamp_recorded;
```

---

## Data Retention Policies

| Table | Supabase Retention | Local Retention | Cleanup Method |
|-------|-------------------|-----------------|----------------|
| `ASE_locations` | ♾️ Permanent | ♾️ Permanent | Never |
| `ASE_cameras` | ♾️ Permanent | ♾️ Permanent | Never |
| `ASE_camera_rois` | ♾️ Permanent | ♾️ Permanent | Versioned |
| `ASE_videos` | 90 days | N/A | Manual/Script |
| `ASE_sessions` | 90 days | N/A | Manual/Script |
| `ASE_division_states` | 90 days | 24 hours (buffer) | Auto (local), Manual (cloud) |
| `ASE_table_states` | 90 days | 24 hours (buffer) | Auto (local), Manual (cloud) |
| `ASE_sync_status` | 30 days | 30 days | Manual/Script |

**Future Enhancement:** Aggregate daily summaries before deleting raw state changes

---

## Environment Variables

**Required on RTX 3060 Machines:**

```bash
# Add to ~/.bashrc or /etc/environment

export SUPABASE_URL="https://wdpeoyugsxqnpwwtkqsl.supabase.co"
export SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

**Security Note:** Anon key is safe for client-side use with Row Level Security (RLS)

---

## Cron Job Setup

**Hourly sync (recommended):**

```bash
# Run every hour during operating hours (11 AM - 9 PM) + processing hours
0 11-23 * * * cd /path/to/production/RTX_3060/scripts/database_sync && python3 sync_to_supabase.py --mode hourly >> /var/log/ase_sync.log 2>&1

# Full sync at 3 AM (catch any missed records)
0 3 * * * cd /path/to/production/RTX_3060/scripts/database_sync && python3 sync_to_supabase.py --mode full >> /var/log/ase_sync.log 2>&1
```

---

## Troubleshooting

### Sync Fails with "Network Error"

**Check:**
1. Internet connectivity: `ping supabase.co`
2. Firewall allows HTTPS: `curl https://wdpeoyugsxqnpwwtkqsl.supabase.co`
3. Environment variables set: `echo $SUPABASE_URL`

**Solution:** Sync will retry on next cron run (data queued locally)

### "Duplicate Key" Error

**Cause:** Record already uploaded (e.g., manual sync + auto sync overlap)

**Solution:** Safe to ignore. `synced_to_cloud` flag prevents duplicate uploads.

### Local Database Growing Too Large

**Check sync status:**
```sql
SELECT sync_type, last_sync_time, status, error_message
FROM sync_status
ORDER BY last_sync_time DESC
LIMIT 10;
```

**If syncs failing:**
```bash
# Manual full sync
python3 sync_to_supabase.py --mode full
```

---

## Future Enhancements

**Planned:**
1. Row Level Security (RLS) policies per restaurant
2. Real-time subscriptions for live dashboard updates
3. Screenshot upload to Supabase Storage (critical events only)
4. Daily aggregation materialized views
5. Multi-user access control with restaurant-specific permissions

---

## Contact

For schema changes or cloud infrastructure questions, coordinate with the development team before modifying production tables.

**Schema Version:** 1.0.0
**Last Updated:** 2025-11-15
**Maintained By:** ASE Development Team
