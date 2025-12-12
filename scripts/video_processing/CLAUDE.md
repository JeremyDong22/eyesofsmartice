# Video Processing Algorithms Documentation

**Version:** 1.0.0
**Last Updated:** 2025-12-13

This document comprehensively details all algorithms, state machines, and processing pipelines in the video processing system.

---

## Table of Contents

1. [Two-Stage Detection Pipeline](#two-stage-detection-pipeline)
2. [ROI Management System](#roi-management-system)
3. [Table State Machine](#table-state-machine)
4. [Division State Machine](#division-state-machine)
5. [Debouncing Algorithm](#debouncing-algorithm)
6. [First-Frame Initialization](#first-frame-initialization)
7. [Resolution Auto-Scaling](#resolution-auto-scaling)
8. [Detection Assignment Logic](#detection-assignment-logic)
9. [Video Encoding Pipeline](#video-encoding-pipeline)
10. [Performance Tracking](#performance-tracking)
11. [Database Integration](#database-integration)

---

## Two-Stage Detection Pipeline

### Overview

The system uses a hierarchical two-stage approach to classify persons as staff or customers.

### Stage 1: Person Detection

**Model**: YOLOv8m (52 MB)
**Purpose**: Detect all persons in the frame

**Algorithm** (`detect_persons()`, lines 1115-1138):

```
FOR each frame:
    results = yolov8m.detect(frame, confidence=0.3, class=person)

    FOR each detected bbox:
        IF width >= 40 AND height >= 40:
            center_x = (x1 + x2) / 2
            center_y = (y1 + y2) / 2

            APPEND {
                bbox: (x1, y1, x2, y2),
                confidence: detection_conf,
                center: (center_x, center_y)
            }

    RETURN person_detections
```

**Key Parameters**:
- `PERSON_CONF_THRESHOLD = 0.3` (line 121) - Lower threshold to catch all persons
- `MIN_PERSON_SIZE = 40` (line 123) - Minimum 40x40 pixels to filter noise

**Performance**: ~14.5ms per frame (Stage 1 timing, line 418)

### Stage 2: Staff Classification

**Model**: YOLO11n-cls (3.2 MB custom classifier)
**Purpose**: Classify each detected person as waiter/customer

**Algorithm** (`classify_persons()`, lines 1141-1192):

```
FOR each person_detection:
    x1, y1, x2, y2 = person.bbox
    person_crop = frame[y1:y2, x1:x2]

    IF crop too small (< 20x20):
        class = 'unknown'
        CONTINUE

    results = staff_classifier.predict(person_crop)
    class_id = results.probs.top1
    confidence = results.probs.top1conf

    IF confidence >= 0.5:
        class = CLASS_NAMES[class_id]  # 'waiter' or 'customer'
    ELSE:
        class = 'unknown'

    RETURN classified_detections
```

**Key Parameters**:
- `STAFF_CONF_THRESHOLD = 0.5` (line 122) - Higher threshold for reliable classification
- `CLASS_NAMES = {0: 'customer', 1: 'waiter'}` (line 160)

**Performance**: ~47.2ms per frame (Stage 2 timing, line 420)

**Total Pipeline**: 14.5ms + 47.2ms = 61.7ms/frame (3.24x real-time at 5fps)

---

## ROI Management System

### Hierarchical Structure

The system uses a four-level ROI hierarchy with priority-based assignment.

```
Division (Overall monitored area)
  ├─ Tables (Individual table surfaces)
  ├─ Sitting Areas (Chairs/seating linked to tables)
  ├─ Service Areas (Bar, POS, prep stations)
  └─ Walking Areas (Implicit - remaining division space)
```

### Point-in-Polygon Detection

**Algorithm** (`point_in_polygon()`, lines 451-469):

Uses ray-casting algorithm for O(n) polygon containment test.

```
FUNCTION point_in_polygon(point, polygon):
    x, y = point
    inside = False

    p1x, p1y = polygon[0]
    FOR i = 1 to n:
        p2x, p2y = polygon[i % n]

        IF y > min(p1y, p2y) AND y <= max(p1y, p2y):
            IF x <= max(p1x, p2x):
                IF p1y != p2y:
                    xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x

                IF p1x == p2x OR x <= xinters:
                    inside = NOT inside

        p1x, p1y = p2x, p2y

    RETURN inside
```

**Complexity**: O(n) where n = number of polygon vertices

### ROI Configuration Format

JSON structure (`table_region_config.json`):

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
  "frame_size": [width, height]
}
```

---

## Table State Machine

### State Definitions

Three states based on occupancy:

```
IDLE (Green):     customers=0 AND waiters=0
BUSY (Yellow):    customers>0 AND waiters=0
CLEANING (Blue):  waiters>0 (any count)
```

### State Determination Logic

**Algorithm** (`Table.determine_state()`, lines 239-247):

```
FUNCTION determine_state():
    IF customers == 0 AND waiters == 0:
        RETURN IDLE
    ELSE IF customers > 0 AND waiters == 0:
        RETURN BUSY
    ELSE IF waiters > 0:
        RETURN CLEANING
    ELSE:
        RETURN IDLE  # Fallback
```

**Priority**: Waiters > Customers > Empty

### Count Updates

**Algorithm** (`Table.update_counts()`, lines 234-237):

```
FUNCTION update_counts(customers, waiters):
    self.customers_present = customers
    self.waiters_present = waiters
```

Called after detection assignment phase for each frame.

---

## Division State Machine

### State Definitions

Three states based on staff location:

```
RED (Understaffed):  No staff in service OR walking areas
YELLOW (Busy):       Staff in service area (at bar/POS)
GREEN (Serving):     Staff in walking area (serving customers)
```

### State Determination Logic

**Algorithm** (`DivisionStateTracker.determine_state()`, lines 311-320):

```
FUNCTION determine_state(walking_waiters, service_waiters):
    total_waiters = walking_waiters + service_waiters

    IF total_waiters == 0:
        RETURN 'red'        # Understaffed
    ELSE IF service_waiters > 0:
        RETURN 'yellow'     # Busy at station
    ELSE:
        RETURN 'green'      # Serving customers
```

**Priority**: Service Area > Walking Area > None

**Rationale**:
- Service area staff = busy preparing orders (YELLOW)
- Walking area staff = actively serving (GREEN)
- No staff = understaffed/ignored (RED)

---

## Debouncing Algorithm

### Problem Solved

Prevents state flickering from:
- Temporary detection errors
- People quickly passing through ROIs
- Momentary classification failures

### Algorithm

**Universal Debounce** (used by both Table and Division states):

```
STATE_DEBOUNCE_SECONDS = 1.0  # Configurable stability period

FUNCTION update_state(current_time):
    new_state = determine_state()

    IF new_state != current_state:
        IF pending_state != new_state:
            # New state detected, start timer
            pending_state = new_state
            pending_state_start = current_time
            RETURN False  # No database write yet
        ELSE:
            # Same pending state, check stability
            elapsed = current_time - pending_state_start

            IF elapsed >= STATE_DEBOUNCE_SECONDS:
                # State stable for 1 second, commit change
                old_state = current_state
                current_state = new_state
                pending_state = None

                # Log transition
                state_transitions.append({
                    'time': current_time,
                    'from': old_state,
                    'to': new_state
                })

                RETURN True  # Trigger database write
            ELSE:
                RETURN False  # Still waiting for stability
    ELSE:
        # State unchanged, reset pending
        pending_state = None
        pending_state_start = None
        RETURN False
```

**Implementation**:
- Table: `Table.update_state()` (lines 249-273)
- Division: `DivisionStateTracker.update_state()` (lines 322-346)

**Key Parameters**:
- `STATE_DEBOUNCE_SECONDS = 1.0` (line 129)
- Processed at 5 FPS = requires 5 consecutive frames with same state

**State Diagram**:

```
Current State: IDLE
       ↓
[Detection: Customer appears]
       ↓
Pending State: BUSY (t=0.0s) ──→ [No DB write]
       ↓
[0.2s] Still BUSY ──→ [No DB write]
[0.4s] Still BUSY ──→ [No DB write]
[0.6s] Still BUSY ──→ [No DB write]
[0.8s] Still BUSY ──→ [No DB write]
[1.0s] Still BUSY ──→ [DB write: IDLE → BUSY] ✓
       ↓
Current State: BUSY
```

---

## First-Frame Initialization

### Problem Solved

Each video segment starts with state machine in default `IDLE` state. Processing immediately would create false state transitions.

### Solution: Buffer Filling

Duplicate first frame processing to fill debounce buffer WITHOUT database writes.

**Algorithm** (lines 1646-1714):

```
FUNCTION initialize_first_frame(first_frame, target_fps):
    # Calculate buffer size
    frames_needed = int(target_fps × STATE_DEBOUNCE_SECONDS)
    time_step = 1.0 / target_fps

    initial_time = current_time()

    FOR i = 0 to frames_needed - 1:
        # Simulate time progression
        simulated_time = initial_time + (i × time_step)

        # Run full detection pipeline
        persons = detect_persons(person_detector, first_frame)
        classified = classify_persons(staff_classifier, first_frame, persons)

        # Assign to ROIs
        walking_waiters, service_waiters = assign_detections_to_rois(
            division_polygon, tables, sitting_areas, service_areas, classified
        )

        # Update states through debounce
        FOR each table:
            table.update_state(simulated_time)  # Returns True/False
            # ❌ DO NOT call log_table_state_change()

        division_tracker.update_state(
            walking_waiters, service_waiters, simulated_time
        )
        # ❌ DO NOT call log_division_state_change()

    # After loop, states are properly initialized
    # Main processing loop begins with correct baseline states
```

**Key Points**:
- At 5 FPS: Process first frame 5 times (5 × 0.2s = 1.0s buffer)
- At 10 FPS: Process first frame 10 times (10 × 0.1s = 1.0s buffer)
- FPS-agnostic implementation
- **No database writes during initialization**

**Timeline Example** (5 FPS):

```
i=0: t=0.000s, State: IDLE → BUSY (pending)
i=1: t=0.200s, State: BUSY (pending 0.2s)
i=2: t=0.400s, State: BUSY (pending 0.4s)
i=3: t=0.600s, State: BUSY (pending 0.6s)
i=4: t=0.800s, State: BUSY (pending 0.8s)
[Loop ends, pending time < 1.0s, state NOT committed]

Main loop frame 0: t=1.000s
State update: BUSY (pending 1.0s) → BUSY committed
Result: State = BUSY, no DB write (already BUSY from init)
```

---

## Resolution Auto-Scaling

### Problem Solved

ROI configuration created on MacBook (1920x1080 test video) must work on production camera (2592x1944).

**Algorithm** (`auto_scale_config()`, lines 866-929):

```
FUNCTION auto_scale_config(config, actual_width, actual_height):
    # Get configured resolution
    config_width, config_height = config.get('frame_size', [1920, 1080])

    # Check if scaling needed
    IF config_width == actual_width AND config_height == actual_height:
        RETURN config  # No scaling needed

    # Calculate scale factors
    scale_x = actual_width / config_width
    scale_y = actual_height / config_height

    # Scale all polygons
    config.division = scale_polygon(config.division, scale_x, scale_y)

    FOR each table IN config.tables:
        table.polygon = scale_polygon(table.polygon, scale_x, scale_y)

    FOR each sitting IN config.sitting_areas:
        sitting.polygon = scale_polygon(sitting.polygon, scale_x, scale_y)

    FOR each service IN config.service_areas:
        service.polygon = scale_polygon(service.polygon, scale_x, scale_y)

    # Update frame size
    config.frame_size = [actual_width, actual_height]

    RETURN config


FUNCTION scale_polygon(polygon, scale_x, scale_y):
    RETURN [[int(x × scale_x), int(y × scale_y)] FOR (x, y) IN polygon]
```

**Example**:

```
Config: 1920x1080 → Production: 2592x1944
scale_x = 2592 / 1920 = 1.35
scale_y = 1944 / 1080 = 1.80

Original point: (100, 100)
Scaled point:   (135, 180)
```

**Automatically invoked** in `process_video()` (line 1509) before processing begins.

---

## Detection Assignment Logic

### Priority-Based Assignment

Persons are assigned to ROIs in strict priority order to avoid double-counting.

**Algorithm** (`assign_detections_to_rois()`, lines 1195-1261):

```
FUNCTION assign_detections_to_rois(division, tables, sitting_areas,
                                    service_areas, detections):
    # Filter to division only
    division_detections = [d FOR d IN detections
                          IF point_in_polygon(d.center, division)]

    # Reset all counts
    FOR each table:
        table.update_counts(0, 0)

    walking_waiters = 0
    service_waiters = 0

    # Assign each detection
    FOR each detection IN division_detections:
        center = detection.center
        assigned = False

        # Priority 1: Check tables
        FOR each table:
            IF point_in_polygon(center, table.polygon):
                IF detection.class == 'customer':
                    table.customers_present += 1
                ELSE IF detection.class == 'waiter':
                    table.waiters_present += 1

                assigned = True
                BREAK  # Stop searching

        IF assigned:
            CONTINUE  # Next detection

        # Priority 2: Check sitting areas
        FOR each sitting IN sitting_areas:
            IF point_in_polygon(center, sitting.polygon):
                # Find linked table
                linked_table = find_table_by_id(sitting.table_id)

                IF detection.class == 'customer':
                    linked_table.customers_present += 1
                ELSE IF detection.class == 'waiter':
                    linked_table.waiters_present += 1

                assigned = True
                BREAK

        IF assigned:
            CONTINUE

        # Priority 3: Check service areas
        FOR each service IN service_areas:
            IF point_in_polygon(center, service.polygon):
                IF detection.class == 'waiter':
                    service_waiters += 1

                assigned = True
                BREAK

        IF assigned:
            CONTINUE

        # Priority 4: Walking area (implicit)
        IF detection.class == 'waiter':
            walking_waiters += 1

    RETURN walking_waiters, service_waiters
```

**Assignment Priority**:
1. **Tables** - Highest priority (person at table surface)
2. **Sitting Areas** - Linked to tables (person in chair)
3. **Service Areas** - Bar, POS, prep stations
4. **Walking Areas** - Implicit (remaining division space)

**Key Invariant**: Each detection assigned to exactly ONE ROI (no double-counting).

---

## Video Encoding Pipeline

### Two-Stage Encoding

**Stage 1: OpenCV VideoWriter** (Real-time encoding):

```python
# Lines 1609-1614
fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # MPEG-4 Part 2
out = cv2.VideoWriter(output_file, fourcc, fps, (width, height))

# During processing
out.write(annotated_frame)
```

**Problem**: MPEG-4 Part 2 creates large files (~75MB per 60s video)

**Stage 2: FFmpeg H.264 Re-encoding** (Post-processing):

```python
# Lines 1836-1867
temp_output = output_file + ".temp.mp4"
os.rename(output_file, temp_output)

ffmpeg_cmd = [
    'ffmpeg', '-y', '-i', temp_output,
    '-c:v', 'libx264',           # H.264 codec
    '-preset', 'fast',            # Fast encoding
    '-crf', '23',                 # Quality (18-28, 23=default)
    '-c:a', 'copy',               # Copy audio if present
    '-movflags', '+faststart',    # Web-friendly
    output_file
]

subprocess.run(ffmpeg_cmd, timeout=300)
os.unlink(temp_output)  # Delete temp file
```

**Compression Ratio**: ~75MB → ~15MB (5x reduction)

**Quality Parameter**: CRF 23 (visually lossless for surveillance footage)

**Why Two Stages?**:
- OpenCV H.264 encoder unreliable/unavailable on some systems
- MPEG-4 Part 2 universally supported for real-time writing
- FFmpeg H.264 post-processing ensures consistent compression

---

## Performance Tracking

### Metrics Collected

**Real-time Metrics** (rolling 30-frame window):
- Processing FPS
- Stage 1 time (person detection)
- Stage 2 time (staff classification)

**Cumulative Metrics**:
- Total frames (including skipped)
- Processed frames (actually analyzed)
- Total processing time
- Stage-wise cumulative time

**Algorithm** (`PerformanceTracker`, lines 349-422):

```python
class PerformanceTracker:
    def __init__(self, window_size=30):
        self.frame_times = deque(maxlen=window_size)  # Rolling window
        self.stage1_times = deque(maxlen=window_size)
        self.stage2_times = deque(maxlen=window_size)

        self.total_frames = 0        # Including skipped
        self.processed_frames = 0    # Actually processed
        self.total_processing_time = 0.0
        self.total_stage1_time = 0.0
        self.total_stage2_time = 0.0

    def add_frame(self, frame_time, stage1_time, stage2_time):
        # Add to rolling windows
        self.frame_times.append(frame_time)
        self.stage1_times.append(stage1_time)
        self.stage2_times.append(stage2_time)

        # Update cumulative
        self.processed_frames += 1
        self.total_processing_time += frame_time
        self.total_stage1_time += stage1_time
        self.total_stage2_time += stage2_time

    def get_current_fps(self):
        if len(self.frame_times) == 0:
            return 0.0
        avg_time = sum(self.frame_times) / len(self.frame_times)
        return 1.0 / avg_time if avg_time > 0 else 0.0
```

### Frame Skipping Logic

**Algorithm** (lines 1520-1738):

```
video_fps = 20.0  # Video recorded at 20 FPS
target_fps = 5.0  # Process at 5 FPS

frame_interval = round(video_fps / target_fps) = 4

# Process frames 0, 4, 8, 12, 16, 20...
# Skip frames 1, 2, 3, 5, 6, 7, 9, 10, 11...

FOR frame_idx = 0 to max_frames:
    tracker.increment_total_frames()  # Count all frames

    IF frame_idx % frame_interval != 0:
        SKIP frame  # Don't process
        CONTINUE

    # Process frame
    stage1_start = time()
    persons = detect_persons(frame)
    stage1_time = time() - stage1_start

    stage2_start = time()
    classified = classify_persons(frame, persons)
    stage2_time = time() - stage2_start

    frame_time = time() - frame_start
    tracker.add_frame(frame_time, stage1_time, stage2_time)
```

**Speedup**: ~4x at 5 FPS (process 1 in 4 frames)

**Database Frame Numbers**: Original frame numbers preserved (not renumbered)

---

## Database Integration

### Schema

**Sessions Table**:
```sql
CREATE TABLE sessions (
    session_id TEXT PRIMARY KEY,        -- YYYYMMDD_HHMMSS_camera_id
    camera_id TEXT,
    video_file TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT,
    total_frames INTEGER,
    fps REAL,
    resolution TEXT,
    config_file TEXT
)
```

**Table States**:
```sql
CREATE TABLE table_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    camera_id TEXT,
    frame_number INTEGER NOT NULL,     -- Original frame number
    timestamp REAL NOT NULL,            -- Unix timestamp
    table_id TEXT NOT NULL,             -- T1, T2, T3...
    state TEXT NOT NULL,                -- IDLE, BUSY, CLEANING
    customers_count INTEGER,
    waiters_count INTEGER,
    screenshot_path TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
)
```

**Division States**:
```sql
CREATE TABLE division_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    camera_id TEXT,
    frame_number INTEGER NOT NULL,
    timestamp REAL NOT NULL,
    state TEXT NOT NULL,                -- RED, YELLOW, GREEN
    walking_area_waiters INTEGER,
    service_area_waiters INTEGER,
    screenshot_path TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
)
```

### Write Logic

**Session Initialization** (lines 1634-1640):

```python
session_id = f"{video_ts}_{camera_id}"  # e.g., 20251213_183000_camera_35

cursor.execute('''
    INSERT INTO sessions
    (session_id, camera_id, video_file, start_time, fps, resolution, config_file)
    VALUES (?, ?, ?, ?, ?, ?, ?)
''', (session_id, camera_id, video_filename,
      datetime.now().isoformat(), fps, f"{width}x{height}", CONFIG_FILE))
conn.commit()
```

**State Change Logging** (lines 1786-1804):

```python
# Only when state actually changes
FOR table IN tables:
    IF table.update_state(current_time):  # Returns True if changed
        screenshot_path = save_screenshot(
            annotated_frame, screenshot_dir, camera_id, session_id,
            frame_idx, prefix=f"{table.id}_"
        )

        log_table_state_change(
            conn, session_id, camera_id, frame_idx, current_time,
            table.id, table.state.value,
            table.customers_present, table.waiters_present,
            screenshot_path
        )
```

**Duplicate Prevention** (lines 1577-1599):

```python
# Check if video already processed BEFORE creating output file
cursor.execute('''
    SELECT session_id, start_time FROM sessions
    WHERE camera_id = ? AND video_file = ?
''', (camera_id, video_filename))

existing = cursor.fetchone()

IF existing:
    print(f"⚠️ WARNING: Video already processed!", file=sys.stderr)
    print(f"Previous session: {existing[0]}", file=sys.stderr)
    cap.release()
    conn.close()
    sys.exit(2)  # Exit code 2 = skipped (not error)
```

### Screenshot Organization

**Directory Structure**:
```
db/screenshots/{camera_id}/{date}/{session_id}/
    ├─ T1_frame_000045.jpg         (Table 1 state change at frame 45)
    ├─ T2_frame_000103.jpg         (Table 2 state change at frame 103)
    ├─ division_frame_000078.jpg   (Division state change at frame 78)
    └─ ...
```

**Compression** (lines 1046-1066):

```python
def save_screenshot(frame, screenshot_dir, camera_id, session_id,
                    frame_number, prefix=""):
    # Organize by camera and date
    date_str = datetime.now().strftime('%Y%m%d')
    screenshot_path = Path(screenshot_dir) / camera_id / date_str / session_id
    screenshot_path.mkdir(parents=True, exist_ok=True)

    filename = f"{prefix}frame_{frame_number:06d}.jpg"
    filepath = screenshot_path / filename

    # Save with 80% JPEG quality (good balance)
    # Modified: 2025-12-09 - Reduced from 95 to 80
    # Reduction: ~1.6MB → ~300KB per screenshot
    cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])

    return str(filepath.relative_to(Path(screenshot_dir).parent))
```

---

## Data Flow Summary

```
┌─────────────────────────────────────────────────────────────────┐
│  Input: RTSP Video Segment (60s, H.264)                         │
│  camera_35_20251213_183000.mp4                                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: Initialize Session                                     │
│  ├─ Check duplicate (exit if already processed)                 │
│  ├─ Create session in database                                  │
│  └─ Load and auto-scale ROI configuration                       │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: First-Frame Buffer Fill                                │
│  ├─ Read first frame                                            │
│  ├─ Process 5 times (5fps × 1s debounce)                        │
│  ├─ Establish initial states (IDLE → actual)                    │
│  └─ ❌ NO database writes during this phase                      │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: Main Processing Loop (Frame Skipping)                  │
│                                                                  │
│  FOR each frame (skip 3 in 4 frames at 5fps):                   │
│    ┌──────────────────────────────────────────────────┐         │
│    │  Stage 1: Person Detection (YOLOv8m)             │         │
│    │  ├─ Detect all persons (conf > 0.3)              │         │
│    │  ├─ Filter by size (>40x40 pixels)               │         │
│    │  └─ Extract center points                        │         │
│    │                                                   │         │
│    │  Stage 2: Staff Classification (YOLO11n-cls)     │         │
│    │  ├─ Crop each person bbox                        │         │
│    │  ├─ Classify as waiter/customer (conf > 0.5)     │         │
│    │  └─ Label as unknown if low confidence           │         │
│    └──────────────────────────────────────────────────┘         │
│                            ↓                                     │
│    ┌──────────────────────────────────────────────────┐         │
│    │  Detection Assignment (Priority-Based)           │         │
│    │  ├─ Filter to division polygon                   │         │
│    │  ├─ Assign to Tables (priority 1)                │         │
│    │  ├─ Assign to Sitting Areas (priority 2)         │         │
│    │  ├─ Assign to Service Areas (priority 3)         │         │
│    │  └─ Remaining → Walking Areas (priority 4)       │         │
│    └──────────────────────────────────────────────────┘         │
│                            ↓                                     │
│    ┌──────────────────────────────────────────────────┐         │
│    │  State Updates (Debounced)                       │         │
│    │  ├─ Update table states (1s debounce)            │         │
│    │  ├─ Update division state (1s debounce)          │         │
│    │  └─ Track state transitions                      │         │
│    └──────────────────────────────────────────────────┘         │
│                            ↓                                     │
│    ┌──────────────────────────────────────────────────┐         │
│    │  Conditional Database Writes                     │         │
│    │  ├─ IF table state changed → Save screenshot     │         │
│    │  │                         → Log to table_states │         │
│    │  ├─ IF division changed    → Save screenshot     │         │
│    │  │                         → Log to division_states│        │
│    │  └─ ELSE → No database write                     │         │
│    └──────────────────────────────────────────────────┘         │
│                            ↓                                     │
│    ┌──────────────────────────────────────────────────┐         │
│    │  Visualization & Output                          │         │
│    │  ├─ Draw ROI overlays (colored by state)         │         │
│    │  ├─ Draw person bboxes (green=waiter, red=customer)│       │
│    │  ├─ Draw stats panel (FPS, frame, states)        │         │
│    │  └─ Write annotated frame to video               │         │
│    └──────────────────────────────────────────────────┘         │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: Finalize Session                                       │
│  ├─ Update session end time                                     │
│  ├─ Close database connection                                   │
│  └─ Release video resources                                     │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  Step 5: H.264 Re-encoding (FFmpeg)                             │
│  ├─ Rename MPEG-4 output to temp file                           │
│  ├─ Re-encode with libx264 (CRF 23, fast preset)                │
│  ├─ Replace original with H.264 version                         │
│  └─ Delete temp file (5x compression: 75MB → 15MB)              │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│  Outputs:                                                        │
│  ├─ Video: results/YYYYMMDD/camera_id/*.mp4 (H.264, annotated)  │
│  ├─ Database: db/detection_data.db (state changes only)         │
│  └─ Screenshots: db/screenshots/camera_id/date/session_id/*.jpg │
└─────────────────────────────────────────────────────────────────┘
```

---

## Performance Characteristics

### Validated Benchmarks (RTX 3060 Linux)

| Metric | Value | Notes |
|--------|-------|-------|
| Person Detection | 14.5ms/frame | YOLOv8m, 2592x1944 |
| Staff Classification | 47.2ms/frame | YOLO11n-cls crops |
| Total Pipeline | 61.7ms/frame | Stage 1 + Stage 2 |
| Processing FPS | ~16.2 fps | 1 / 0.0617s |
| Real-time Ratio | 3.24x | At 5fps processing |
| GPU Utilization | 71.4% | Stable during processing |
| Speedup (5fps vs 20fps) | 4x | Process 1 in 4 frames |

### Scalability Analysis

**Single Camera** (7.5 hours daily):
- 7.5 hours × 3600s = 27,000 seconds
- At 5 FPS: 135,000 frames to process
- Processing time: 135,000 × 0.0617s = 8,330s ≈ 2.3 hours
- **Completion**: 2.3 hours (well within 23-hour processing window)

**Multi-Camera** (10 cameras, dual-threaded):
- Total footage: 75 hours
- With 2 parallel workers: 75 / 2 = 37.5 hours processing
- At 3.24x real-time: 37.5 / 3.24 ≈ 11.6 hours
- **Completion**: 11.6 hours (within 23-hour window)

---

## Configuration Parameters Reference

```python
# Detection Thresholds (lines 120-123)
PERSON_CONF_THRESHOLD = 0.3    # Lower = catch all persons
STAFF_CONF_THRESHOLD = 0.5     # Higher = reliable classification
MIN_PERSON_SIZE = 40           # Minimum bbox dimension (pixels)

# State Machine (line 129)
STATE_DEBOUNCE_SECONDS = 1.0   # State stability period

# Processing (default)
DEFAULT_FPS = 5.0              # Target processing rate

# Video Encoding (lines 1841-1848)
FFMPEG_CRF = 23                # Quality (18-28, lower=better)
FFMPEG_PRESET = 'fast'         # Encoding speed
JPEG_QUALITY = 80              # Screenshot quality (0-100)

# Model Paths (lines 117-118)
PERSON_DETECTOR = '../models/yolov8m.pt'           # 52 MB
STAFF_CLASSIFIER = '../models/waiter_customer_classifier.pt'  # 3.2 MB

# Configuration File (line 126)
CONFIG_FILE = '../config/table_region_config.json'
```

---

## File Locations

| Component | File | Lines |
|-----------|------|-------|
| **Main Script** | `table_and_region_state_detection.py` | 1-1999 |
| **Person Detection** | `detect_persons()` | 1115-1138 |
| **Staff Classification** | `classify_persons()` | 1141-1192 |
| **Detection Assignment** | `assign_detections_to_rois()` | 1195-1261 |
| **Table State Machine** | `Table` class | 214-283 |
| **Division State Machine** | `DivisionStateTracker` class | 302-346 |
| **Debouncing** | `update_state()` methods | 249-273, 322-346 |
| **First-Frame Init** | Buffer filling logic | 1646-1714 |
| **Resolution Scaling** | `auto_scale_config()` | 866-929 |
| **Video Encoding** | `process_video()` finalization | 1836-1867 |
| **Performance Tracking** | `PerformanceTracker` class | 349-422 |
| **Database Schema** | `init_database()` | 976-1043 |
| **Screenshot Saving** | `save_screenshot()` | 1046-1066 |
| **ROI Drawing** | `draw_frame_with_all_info()` | 1264-1469 |

---

## Version History

- **1.0.0** (2025-12-13): Comprehensive algorithm documentation covering all processing pipelines, state machines, and optimization techniques

