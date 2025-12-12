-- Local SQLite Database Schema for RTX 3060 Edge Processing
-- Version: 2.0.0
-- Last Updated: 2025-11-15
-- Purpose: Local transactional buffer for real-time processing, syncs to Supabase hourly
-- Note: Schema mirrors Supabase ASE_ tables but adapted for SQLite

-- =============================================================================
-- CORE ENTITY TABLES
-- =============================================================================

-- LOCATIONS: Restaurant location information (cached from Supabase)
CREATE TABLE IF NOT EXISTS locations (
    location_id TEXT PRIMARY KEY,
    city TEXT NOT NULL,
    restaurant_name TEXT NOT NULL,
    commercial_area TEXT NOT NULL,
    address TEXT,
    region TEXT,
    timezone TEXT DEFAULT 'Asia/Shanghai',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

-- CAMERAS: Camera configuration (cached from Supabase)
CREATE TABLE IF NOT EXISTS cameras (
    camera_id TEXT PRIMARY KEY,
    location_id TEXT NOT NULL,
    camera_name TEXT,
    camera_ip_address TEXT NOT NULL,
    rtsp_endpoint TEXT,
    camera_type TEXT DEFAULT 'UNV',
    resolution TEXT,
    installation_date TEXT,
    division_name TEXT,
    division_description TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (location_id) REFERENCES locations(location_id)
);

-- CAMERA_ROIS: ROI configurations (cached from Supabase)
CREATE TABLE IF NOT EXISTS camera_rois (
    roi_id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id TEXT NOT NULL,
    roi_version INTEGER DEFAULT 1,
    roi_type TEXT NOT NULL,
    roi_identifier TEXT NOT NULL,
    polygon_points TEXT NOT NULL,  -- JSON array
    linked_to_roi_id TEXT,
    description TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (camera_id) REFERENCES cameras(camera_id),
    UNIQUE(camera_id, roi_identifier, roi_version)
);

-- =============================================================================
-- VIDEO & SESSION MANAGEMENT
-- =============================================================================

-- VIDEOS: Video file metadata
CREATE TABLE IF NOT EXISTS videos (
    video_id INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id TEXT NOT NULL,
    video_filename TEXT NOT NULL,
    video_date TEXT NOT NULL,  -- YYYY-MM-DD
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_seconds INTEGER,
    file_size_bytes INTEGER,
    fps REAL,
    resolution TEXT,
    is_processed INTEGER DEFAULT 0,
    storage_location TEXT DEFAULT 'local',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (camera_id) REFERENCES cameras(camera_id),
    UNIQUE(camera_id, video_filename)
);

-- SESSIONS: Processing sessions
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    camera_id TEXT NOT NULL,
    video_id INTEGER NOT NULL,
    location_id TEXT NOT NULL,
    config_file_path TEXT,
    roi_version INTEGER,
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    total_frames INTEGER,
    fps REAL,
    resolution TEXT,
    processing_status TEXT DEFAULT 'pending',
    processing_time_seconds REAL,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (camera_id) REFERENCES cameras(camera_id),
    FOREIGN KEY (video_id) REFERENCES videos(video_id),
    FOREIGN KEY (location_id) REFERENCES locations(location_id)
);

-- =============================================================================
-- STATE TRACKING TABLES (Transactional Buffer - 24h retention)
-- =============================================================================

-- DIVISION_STATES: Division state changes (buffered, synced hourly)
CREATE TABLE IF NOT EXISTS division_states (
    division_state_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    camera_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    frame_number INTEGER NOT NULL,
    timestamp_video REAL NOT NULL,
    timestamp_recorded TIMESTAMP NOT NULL,
    state TEXT NOT NULL,
    walking_area_waiters INTEGER DEFAULT 0,
    service_area_waiters INTEGER DEFAULT 0,
    total_staff INTEGER DEFAULT 0,
    screenshot_path TEXT,  -- Local path only (screenshots NOT uploaded)
    synced_to_cloud INTEGER DEFAULT 0,  -- 0 = pending, 1 = synced
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id),
    FOREIGN KEY (camera_id) REFERENCES cameras(camera_id),
    FOREIGN KEY (location_id) REFERENCES locations(location_id)
);

-- TABLE_STATES: Table state changes (buffered, synced hourly)
CREATE TABLE IF NOT EXISTS table_states (
    table_state_id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    camera_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    frame_number INTEGER NOT NULL,
    timestamp_video REAL NOT NULL,
    timestamp_recorded TIMESTAMP NOT NULL,
    table_id TEXT NOT NULL,
    state TEXT NOT NULL,
    customers_count INTEGER DEFAULT 0,
    waiters_count INTEGER DEFAULT 0,
    screenshot_path TEXT,
    synced_to_cloud INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id),
    FOREIGN KEY (camera_id) REFERENCES cameras(camera_id),
    FOREIGN KEY (location_id) REFERENCES locations(location_id)
);

-- =============================================================================
-- SYNC TRACKING
-- =============================================================================

-- SYNC_QUEUE: Tracks what needs to be uploaded to Supabase
CREATE TABLE IF NOT EXISTS sync_queue (
    queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,  -- 'division_states', 'table_states', etc.
    record_id INTEGER NOT NULL,
    retry_count INTEGER DEFAULT 0,
    last_error TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(table_name, record_id)
);

-- SYNC_STATUS: Tracks sync operations
CREATE TABLE IF NOT EXISTS sync_status (
    sync_id INTEGER PRIMARY KEY AUTOINCREMENT,
    location_id TEXT NOT NULL,
    sync_type TEXT NOT NULL,
    last_sync_time TIMESTAMP NOT NULL,
    records_synced INTEGER DEFAULT 0,
    status TEXT NOT NULL,  -- 'success', 'partial', 'failed'
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (location_id) REFERENCES locations(location_id)
);

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================

-- Camera indexes
CREATE INDEX IF NOT EXISTS idx_cameras_location ON cameras(location_id);

-- ROI indexes
CREATE INDEX IF NOT EXISTS idx_rois_camera ON camera_rois(camera_id);
CREATE INDEX IF NOT EXISTS idx_rois_active ON camera_rois(camera_id, is_active) WHERE is_active = 1;

-- Video indexes
CREATE INDEX IF NOT EXISTS idx_videos_camera_date ON videos(camera_id, video_date);
CREATE INDEX IF NOT EXISTS idx_videos_unprocessed ON videos(camera_id, is_processed) WHERE is_processed = 0;

-- Session indexes
CREATE INDEX IF NOT EXISTS idx_sessions_camera ON sessions(camera_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_location ON sessions(location_id, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(processing_status);

-- Division state indexes
CREATE INDEX IF NOT EXISTS idx_division_session_frame ON division_states(session_id, frame_number);
CREATE INDEX IF NOT EXISTS idx_division_camera_time ON division_states(camera_id, timestamp_recorded);
CREATE INDEX IF NOT EXISTS idx_division_unsynced ON division_states(synced_to_cloud) WHERE synced_to_cloud = 0;

-- Table state indexes
CREATE INDEX IF NOT EXISTS idx_table_session_frame ON table_states(session_id, frame_number);
CREATE INDEX IF NOT EXISTS idx_table_camera_time ON table_states(camera_id, timestamp_recorded);
CREATE INDEX IF NOT EXISTS idx_table_location_table_time ON table_states(location_id, table_id, timestamp_recorded);
CREATE INDEX IF NOT EXISTS idx_table_unsynced ON table_states(synced_to_cloud) WHERE synced_to_cloud = 0;

-- Sync queue indexes
CREATE INDEX IF NOT EXISTS idx_sync_queue_pending ON sync_queue(table_name, created_at);

-- Sync status indexes
CREATE INDEX IF NOT EXISTS idx_sync_status_location ON sync_status(location_id, sync_type, created_at);
