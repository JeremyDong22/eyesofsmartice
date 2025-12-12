#!/usr/bin/env python3
"""
# Modified: 2025-12-09 - Fixed video encoding and screenshot compression issues
# Issue 1: Video output using MPEG4 (mp4v) resulting in 22x larger files than input
#   - Changed from mp4v (MPEG-4 Part 2) to avc1 (H.264) codec
#   - Expected reduction: 75MB → ~15MB per 60s video
# Issue 2: Screenshots at quality 95 resulting in 1.6MB per image
#   - Reduced JPEG quality from 95 to 80
#   - Expected reduction: 1.6MB → ~300KB per screenshot
# Impact: Daily storage reduced from ~50GB to ~15GB
#
# Modified: 2025-12-03 - Fixed video processing bug creating 258-byte corrupted output files
# Feature: Moved duplicate detection check BEFORE VideoWriter creation
# Issue: VideoWriter creates empty 258-byte container file before duplicate check runs
# Solution: Check database for duplicates early, only create output file if NOT duplicate
# Additional: Changed warning messages to stderr, added distinct exit codes (0/1/2)
#
# Modified: 2025-11-23 - Added automatic ROI configuration scaling for resolution mismatches
# Feature: Auto-scales ROI coordinates when config resolution differs from actual video resolution
# Solves: Configuration created at 1920x1080 on MacBook but production camera runs at 2592x1944
# Result: Automatic alignment of detection zones regardless of resolution differences
#
# Modified: 2025-11-17 - Implemented first-frame duplication for proper debounce buffer filling
# Feature: Properly initializes table and division states by processing first frame multiple times
# to fill debounce buffer and ensure initial states are logged to database
#
Table and Region State Detection System
Version: 3.3.0
Last Updated: 2025-12-03

Purpose: Unified system monitoring both table states and regional staff coverage
Combines table-level monitoring (IDLE/BUSY/CLEANING) with division-level monitoring (staffed/unstaffed)

Changes in v3.2.0:
- Added automatic ROI configuration scaling for resolution mismatches
- Auto-detects when config resolution differs from actual video resolution
- Scales all polygon coordinates (division, tables, sitting areas, service areas)
- Prevents misalignment when config created on different resolution than production
- Example: Config at 1920x1080 auto-scales to 2592x1944 camera feed

Changes in v3.1.0:
- FIXED: First-frame duplication to properly fill debounce buffer
- Process first frame N times (N = target_fps × STATE_DEBOUNCE_SECONDS)
- Removed direct state assignment (now uses update_state() with debounce)
- Removed redundant time.sleep() - replaced with frame duplication loop
- FPS-flexible implementation (works with 5, 10, 20 FPS, etc.)
- Initial states now properly logged to database (fixes commercial metrics)
- Each iteration simulates time progression for proper debounce

Changes in v3.0.0:
- Added first-second preprocessing to establish initial states
- Before video playback starts, pause at first frame for 1 second
- Run detection on first frame to initialize all table and division states
- Ensures all ROIs have baseline states before debounce timer starts
- Addresses issue where 1s debounce delay prevented immediate state establishment

Changes in v2.1.0:
- Added --fps parameter for configurable frame processing rate (default: 5 FPS)
- Smart frame skipping based on video FPS and target FPS
- Maintains original frame numbers in database/screenshots (no renumbering)
- Updated progress display to show processed vs total frames
- ~4x speedup for 5 FPS processing (processes 1 in 4 frames for 20fps video)

Changes in v2.0.0:
- Added three-layer debug system: SQLite database + screenshots + H.264 video
- Database tracks all state changes with timestamps and metadata
- Screenshots saved automatically on every state change
- H.264 video encoding for 90% smaller file sizes (hardware accelerated)
- Moved to production scripts folder with updated paths

Key Features:
- Multi-level ROI system: Division → Tables/Sitting Areas + Service Areas + Walking Areas
- Simultaneous table state and division state detection
- Two-stage detection: YOLOv8m person detection + YOLO11n-cls staff classification
- 1-second debounce for all state transitions
- First-second preprocessing for initial state establishment

ROI Hierarchy:
- Division: Overall monitored area boundary
- Tables: Individual table surfaces (with state colors)
- Sitting Areas: Chairs/seating zones (linked to tables)
- Service Areas: Bar, prep stations, POS areas
- Walking Areas: Implicit - any Division area not covered by above

State Definitions:
Table States (shown via table colors):
- IDLE (Green): No one at table + sitting areas
- BUSY (Yellow): Only customers present
- CLEANING (Blue): Any staff present

Division States (shown via area overlay):
- RED: No staff in Service Area + Walking Area (understaffed/ignored)
- YELLOW: Staff in Service Area (busy at station)
- GREEN: Staff in Walking Area (actively serving customers)

Author: ASEOfSmartICE Team
"""

import cv2
import numpy as np
from ultralytics import YOLO
import os
from pathlib import Path
import argparse
import time
import json
from collections import deque
from enum import Enum
from datetime import datetime
import sqlite3
import re
import sys

# Model paths (relative to script location)
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # production/RTX_3060/ (scripts/video_processing/../.. )
PERSON_DETECTOR_MODEL = str(SCRIPT_DIR.parent / "models" / "yolov8m.pt")
STAFF_CLASSIFIER_MODEL = str(SCRIPT_DIR.parent / "models" / "waiter_customer_classifier.pt")

# Detection parameters
PERSON_CONF_THRESHOLD = 0.3
STAFF_CONF_THRESHOLD = 0.5
MIN_PERSON_SIZE = 40

# Configuration file (in scripts/config/)
CONFIG_FILE = str(SCRIPT_DIR.parent / "config" / "table_region_config.json")

# State transition parameters
STATE_DEBOUNCE_SECONDS = 1.0  # All state changes require 1s stability

# Visual configuration
COLORS = {
    'person': (255, 255, 0),        # Cyan for person detection
    'waiter': (0, 255, 0),          # Green for waiters
    'customer': (0, 0, 255),        # Red for customers
    'unknown': (128, 128, 128),     # Gray for unknown

    # Table state colors
    'table_idle': (0, 255, 0),      # GREEN for IDLE
    'table_busy': (0, 255, 255),    # YELLOW for BUSY
    'table_cleaning': (255, 0, 0),  # BLUE for CLEANING

    # Division state colors
    'division_red': (0, 0, 255),    # RED - understaffed
    'division_yellow': (0, 255, 255), # YELLOW - staff busy
    'division_green': (0, 255, 0),  # GREEN - staff serving

    # ROI boundary colors
    'division': (255, 255, 0),      # Cyan for division boundary
    'service_area': (255, 0, 255),  # Magenta for service area
    'sitting_area': (128, 128, 128), # Gray for sitting areas

    # Drawing colors (during labeling)
    'drawing_division': (255, 255, 0),
    'drawing_table': (0, 255, 255),
    'drawing_sitting': (0, 200, 255),
    'drawing_service': (255, 0, 255),
}

CLASS_NAMES = {0: 'customer', 1: 'waiter'}


def extract_camera_id_from_filename(video_path):
    """
    Extract camera_id from video filename

    Expected formats:
    - camera_35_20251114_183000.mp4 -> camera_35
    - camera_22_something.mp4 -> camera_22

    Returns: camera_id (str) or 'camera_unknown'
    """
    filename = os.path.basename(video_path)
    match = re.match(r'^(camera_\d+)', filename)
    if match:
        return match.group(1)
    return 'camera_unknown'


def extract_date_from_path(video_path):
    """
    Extract date from video path or filename

    Expected:
    - Path: videos/20251022/camera_35/camera_35_20251022_195212.mp4 -> 20251022
    - Filename: camera_35_20251022_195212.mp4 -> 20251022

    Returns: date (str YYYYMMDD) or today's date
    """
    path_str = str(video_path)

    # Try to extract from path (videos/YYYYMMDD/camera_id/)
    path_match = re.search(r'/(\d{8})/', path_str)
    if path_match:
        return path_match.group(1)

    # Try to extract from filename (camera_35_YYYYMMDD_HHMMSS.mp4)
    filename = os.path.basename(path_str)
    filename_match = re.search(r'_(\d{8})_', filename)
    if filename_match:
        return filename_match.group(1)

    # Fallback to today
    return datetime.now().strftime("%Y%m%d")


class TableState(Enum):
    """Table state enumeration"""
    IDLE = "IDLE"
    BUSY = "BUSY"
    CLEANING = "CLEANING"


class Table:
    """Represents a restaurant table with state tracking"""

    def __init__(self, table_id, polygon):
        self.id = table_id
        self.polygon = polygon
        self.state = TableState.IDLE
        self.customers_present = 0
        self.waiters_present = 0
        self.pending_state = None
        self.pending_state_start = None
        self.sitting_area_ids = []
        self.state_transitions = []

    def get_bbox(self):
        """Get bounding box for display"""
        xs = [p[0] for p in self.polygon]
        ys = [p[1] for p in self.polygon]
        return [min(xs), min(ys), max(xs), max(ys)]

    def update_counts(self, customers, waiters):
        """Update customer and waiter counts"""
        self.customers_present = customers
        self.waiters_present = waiters

    def determine_state(self):
        """Determine table state based on counts"""
        if self.customers_present == 0 and self.waiters_present == 0:
            return TableState.IDLE
        elif self.customers_present > 0 and self.waiters_present == 0:
            return TableState.BUSY
        elif self.waiters_present > 0:
            return TableState.CLEANING
        return TableState.IDLE

    def update_state(self, current_time):
        """Update state with 1s debouncing"""
        new_state = self.determine_state()

        if new_state != self.state:
            if self.pending_state != new_state:
                self.pending_state = new_state
                self.pending_state_start = current_time
            else:
                if current_time - self.pending_state_start >= STATE_DEBOUNCE_SECONDS:
                    old_state = self.state
                    self.state = new_state
                    self.pending_state = None
                    self.pending_state_start = None
                    self.state_transitions.append({
                        'time': current_time,
                        'from': old_state.value,
                        'to': new_state.value
                    })
                    return True
        else:
            self.pending_state = None
            self.pending_state_start = None

        return False

    def get_state_color(self):
        """Get color for current state"""
        color_map = {
            TableState.IDLE: COLORS['table_idle'],
            TableState.BUSY: COLORS['table_busy'],
            TableState.CLEANING: COLORS['table_cleaning']
        }
        return color_map.get(self.state, COLORS['table_idle'])


class SittingArea:
    """Represents a sitting area linked to a table"""

    def __init__(self, area_id, polygon, table_id):
        self.id = area_id
        self.polygon = polygon
        self.table_id = table_id


class ServiceArea:
    """Represents a service area (bar, POS, prep station)"""

    def __init__(self, area_id, polygon):
        self.id = area_id
        self.polygon = polygon


class DivisionStateTracker:
    """Tracks division state with debouncing"""

    def __init__(self):
        self.current_state = 'red'
        self.pending_state = None
        self.pending_state_start = None
        self.state_transitions = []

    def determine_state(self, walking_area_waiters, service_area_waiters):
        """Determine division state based on waiter locations"""
        total_waiters = walking_area_waiters + service_area_waiters

        if total_waiters == 0:
            return 'red'  # No staff - understaffed
        elif service_area_waiters > 0:
            return 'yellow'  # Staff at service area - busy
        else:
            return 'green'  # Staff in walking area - serving

    def update_state(self, walking_area_waiters, service_area_waiters, current_time):
        """Update division state with 1s debouncing"""
        new_state = self.determine_state(walking_area_waiters, service_area_waiters)

        if new_state != self.current_state:
            if self.pending_state != new_state:
                self.pending_state = new_state
                self.pending_state_start = current_time
            else:
                if current_time - self.pending_state_start >= STATE_DEBOUNCE_SECONDS:
                    old_state = self.current_state
                    self.current_state = new_state
                    self.pending_state = None
                    self.pending_state_start = None
                    self.state_transitions.append({
                        'time': current_time,
                        'from': old_state,
                        'to': new_state
                    })
                    return True
        else:
            self.pending_state = None
            self.pending_state_start = None

        return False


class PerformanceTracker:
    """Track processing performance metrics"""

    def __init__(self, window_size=30):
        self.window_size = window_size
        self.frame_times = deque(maxlen=window_size)
        self.stage1_times = deque(maxlen=window_size)
        self.stage2_times = deque(maxlen=window_size)

        self.total_frames = 0           # Total frames in video
        self.processed_frames = 0       # Actually processed frames
        self.total_processing_time = 0.0
        self.total_stage1_time = 0.0
        self.total_stage2_time = 0.0

    def add_frame(self, frame_time, stage1_time, stage2_time):
        """Add frame processing stats (only for processed frames)"""
        self.frame_times.append(frame_time)
        self.stage1_times.append(stage1_time)
        self.stage2_times.append(stage2_time)

        self.processed_frames += 1
        self.total_processing_time += frame_time
        self.total_stage1_time += stage1_time
        self.total_stage2_time += stage2_time

    def increment_total_frames(self):
        """Increment total frame count (including skipped frames)"""
        self.total_frames += 1

    def get_current_fps(self):
        """Get current processing FPS"""
        if len(self.frame_times) == 0:
            return 0.0
        avg_time = sum(self.frame_times) / len(self.frame_times)
        return 1.0 / avg_time if avg_time > 0 else 0.0

    def get_avg_stage_times(self):
        """Get average stage times in ms"""
        avg_stage1 = (sum(self.stage1_times) / len(self.stage1_times) * 1000) if self.stage1_times else 0
        avg_stage2 = (sum(self.stage2_times) / len(self.stage2_times) * 1000) if self.stage2_times else 0
        return avg_stage1, avg_stage2

    def print_summary(self, video_duration, original_fps, target_fps=None):
        """Print final processing summary"""
        total_time = self.total_processing_time
        avg_fps = self.processed_frames / total_time if total_time > 0 else 0

        avg_stage1_ms = (self.total_stage1_time / self.processed_frames * 1000) if self.processed_frames > 0 else 0
        avg_stage2_ms = (self.total_stage2_time / self.processed_frames * 1000) if self.processed_frames > 0 else 0

        print(f"\n{'='*70}")
        print(f"Processing Summary")
        print(f"{'='*70}")
        print(f"Video Information:")
        print(f"   Total frames: {self.total_frames}")
        print(f"   Processed frames: {self.processed_frames}")
        if target_fps:
            skip_ratio = self.processed_frames / self.total_frames if self.total_frames > 0 else 0
            print(f"   Frame skip ratio: {skip_ratio:.1%} (processing at {target_fps} FPS)")
        print(f"   Original FPS: {original_fps:.2f}")
        print(f"   Duration: {video_duration:.2f}s")
        print(f"")
        print(f"Performance:")
        print(f"   Processing FPS: {avg_fps:.2f}")
        print(f"   Real-time ratio: {avg_fps/original_fps:.2%}")
        print(f"   Total time: {total_time:.2f}s")
        print(f"   Avg frame time: {(total_time/self.processed_frames)*1000:.1f}ms")
        print(f"")
        print(f"Stage Times (avg):")
        print(f"   Stage 1 (detection): {avg_stage1_ms:.1f}ms")
        print(f"   Stage 2 (classification): {avg_stage2_ms:.1f}ms")
        print(f"   Total pipeline: {avg_stage1_ms + avg_stage2_ms:.1f}ms")
        print(f"{'='*70}\n")


# Global variables for interactive drawing
drawing_points = []
current_stage = 'division'  # 'division', 'table', 'sitting', 'service'
mouse_position = (0, 0)
current_table_index = 0
current_table_sitting_count = 0


def mouse_callback(event, x, y, _flags, _param):
    """Mouse callback for ROI drawing"""
    global drawing_points, mouse_position

    if event == cv2.EVENT_MOUSEMOVE:
        mouse_position = (x, y)

    if event == cv2.EVENT_LBUTTONDOWN:
        drawing_points.append((x, y))
        stage_names = {
            'division': 'DIVISION',
            'table': 'TABLE',
            'sitting': 'SITTING',
            'service': 'SERVICE'
        }
        print(f"   {stage_names.get(current_stage, 'ROI')} Point {len(drawing_points)}: ({x}, {y})")


def point_in_polygon(point, polygon):
    """Check if point is inside polygon using ray casting"""
    x, y = point
    n = len(polygon)
    inside = False

    p1x, p1y = polygon[0]
    for i in range(1, n + 1):
        p2x, p2y = polygon[i % n]
        if y > min(p1y, p2y):
            if y <= max(p1y, p2y):
                if x <= max(p1x, p2x):
                    if p1y != p2y:
                        xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                    if p1x == p2x or x <= xinters:
                        inside = not inside
        p1x, p1y = p2x, p2y

    return inside


def draw_roi_on_frame(frame, points, color, thickness=2, fill_alpha=0.2):
    """Draw ROI polygon on frame"""
    if len(points) < 2:
        return frame

    frame_copy = frame.copy()

    # Draw polygon
    pts = np.array(points, np.int32)
    pts = pts.reshape((-1, 1, 2))
    cv2.polylines(frame_copy, [pts], isClosed=True, color=color, thickness=thickness)

    # Fill with transparency
    if len(points) >= 3:
        overlay = frame_copy.copy()
        cv2.fillPoly(overlay, [pts], color)
        cv2.addWeighted(overlay, fill_alpha, frame_copy, 1 - fill_alpha, 0, frame_copy)

    # Draw points
    for idx, pt in enumerate(points):
        cv2.circle(frame_copy, pt, 7, color, -1)
        cv2.circle(frame_copy, pt, 9, (255, 255, 255), 2)
        cv2.putText(frame_copy, f"{idx+1}", (pt[0] + 12, pt[1] - 5),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    return frame_copy


def create_instruction_window(stage, table_idx, tables_count, sitting_count, service_count, points_count, mouse_pos, current_sitting):
    """Create separate instruction window (doesn't overlay on video)"""
    # Create black background
    panel_height = 400
    panel_width = 700
    panel = np.zeros((panel_height, panel_width, 3), dtype=np.uint8)

    font = cv2.FONT_HERSHEY_SIMPLEX
    y = 40

    # Title
    cv2.putText(panel, "LABELING INSTRUCTIONS", (20, y), font, 0.9, (255, 255, 255), 2)
    y += 40

    # Stage indicator
    stage_map = {
        'division': ('STEP 1/4: DIVISION AREA', COLORS['drawing_division']),
        'table': (f'STEP 2/4: TABLE {table_idx + 1}', COLORS['drawing_table']),
        'sitting': (f'STEP 3/4: SITTING AREAS (T{table_idx + 1})', COLORS['drawing_sitting']),
        'service': (f'STEP 4/4: SERVICE AREAS', COLORS['drawing_service'])
    }
    stage_text, stage_color = stage_map.get(stage, ('UNKNOWN', (255, 255, 255)))
    cv2.rectangle(panel, (15, y-25), (685, y+10), stage_color, 2)
    cv2.putText(panel, stage_text, (25, y), font, 0.7, stage_color, 2)

    # Progress
    y += 50
    workflow_map = {
        'division': 'Draw overall monitoring area boundary',
        'table': f'Draw table surface (T{table_idx + 1})',
        'sitting': f'Draw sitting areas for T{table_idx + 1} (drawn: {current_sitting})',
        'service': f'Draw service areas (bar, POS, prep stations)'
    }
    cv2.putText(panel, workflow_map.get(stage, ''), (25, y), font, 0.5, (150, 255, 150), 1)

    # Counters
    y += 35
    cv2.putText(panel, f"Tables: {tables_count} | Sitting: {sitting_count} | Service: {service_count} | Points: {points_count}",
               (25, y), font, 0.5, (255, 255, 255), 1)

    # Mouse position
    y += 30
    cv2.putText(panel, f"Mouse Position: ({mouse_pos[0]}, {mouse_pos[1]})",
               (25, y), font, 0.5, (255, 255, 0), 1)

    # Special tip for table/sitting stages
    if stage in ['table', 'sitting'] and tables_count > 0:
        y += 35
        cv2.rectangle(panel, (15, y-20), (685, y+10), (0, 255, 255), 2)
        cv2.putText(panel, ">> Press 'S' to skip to Service Areas <<",
                   (25, y), font, 0.6, (0, 255, 255), 2)

    # Instructions
    y += 45
    cv2.putText(panel, "WORKFLOW:", (25, y), font, 0.6, (100, 255, 255), 2)
    y += 25
    instructions = [
        "  1. Division (Cyan) -> Enter",
        "  2. Each Table (Yellow) -> Enter -> Sitting Areas (Light) -> D",
        "  3. Service Areas (Magenta) -> Enter each -> Ctrl+S",
    ]
    for instruction in instructions:
        cv2.putText(panel, instruction, (30, y), font, 0.45, (200, 200, 200), 1)
        y += 22

    y += 15
    cv2.putText(panel, "KEYBOARD CONTROLS:", (25, y), font, 0.6, (100, 255, 255), 2)
    y += 25
    controls = [
        "Enter - Complete current ROI",
        "D - Next table",
        "S - Skip to Service Areas",
        "U or Ctrl+Z - Undo",
        "Ctrl+S - Save all",
        "Q - Quit"
    ]
    for control in controls:
        cv2.putText(panel, control, (30, y), font, 0.45, (200, 200, 200), 1)
        y += 22

    return panel


def setup_all_rois_from_video(video_path):
    """Interactive setup for all ROIs: Division, Tables, Sitting Areas, Service Areas"""
    global drawing_points, current_stage, mouse_position, current_table_index, current_table_sitting_count

    print("\n" + "="*70)
    print("ROI Setup Mode - Complete Workflow")
    print("="*70)

    # Open video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Could not open video: {video_path}")
        return None

    ret, frame = cap.read()
    cap.release()

    if not ret:
        print(f"Could not read first frame")
        return None

    print(f"Using first frame from: {os.path.basename(video_path)}")
    print(f"Frame size: {frame.shape[1]}x{frame.shape[0]}")
    print("\n" + "="*70)
    print("WORKFLOW:")
    print("="*70)
    print("   1. Division - Draw overall area, Enter")
    print("   2. For each Table:")
    print("      - Draw table surface, Enter")
    print("      - Draw sitting areas, Enter each, press D when done")
    print("   3. Service Areas - Draw each, Enter")
    print("   4. Ctrl+S to save all")
    print("\nKEYBOARD SHORTCUTS:")
    print("   Enter - Complete current ROI")
    print("   D - Next table")
    print("   U or Ctrl+Z - Undo")
    print("   Ctrl+S - Save all")
    print("   Q - Quit")
    print("="*70 + "\n")

    # Initialize data structures
    division_polygon = None
    tables = []
    sitting_areas = []
    service_areas = []
    drawing_points = []
    current_stage = 'division'
    current_table_index = 0
    current_table_sitting_count = 0
    operation_history = []

    cv2.namedWindow('ROI Setup - Video', cv2.WINDOW_NORMAL)
    cv2.namedWindow('Instructions', cv2.WINDOW_NORMAL)
    cv2.resizeWindow('ROI Setup - Video', 1280, 720)
    cv2.resizeWindow('Instructions', 700, 400)
    cv2.setMouseCallback('ROI Setup - Video', mouse_callback)

    while True:
        display_frame = frame.copy()

        # Draw completed ROIs
        if division_polygon:
            display_frame = draw_roi_on_frame(display_frame, division_polygon, COLORS['division'], 3, 0.1)

        for table in tables:
            color = COLORS['drawing_table']
            display_frame = draw_roi_on_frame(display_frame, table.polygon, color, 2, 0.15)

        for sitting in sitting_areas:
            color = COLORS['drawing_sitting']
            display_frame = draw_roi_on_frame(display_frame, sitting.polygon, color, 1, 0.05)

        for service in service_areas:
            color = COLORS['drawing_service']
            display_frame = draw_roi_on_frame(display_frame, service.polygon, color, 2, 0.1)

        # Draw current polygon being drawn
        if len(drawing_points) > 0:
            color_map = {
                'division': COLORS['drawing_division'],
                'table': COLORS['drawing_table'],
                'sitting': COLORS['drawing_sitting'],
                'service': COLORS['drawing_service']
            }
            draw_color = color_map.get(current_stage, (255, 255, 255))

            for idx, pt in enumerate(drawing_points):
                cv2.circle(display_frame, pt, 7, draw_color, -1)
                cv2.circle(display_frame, pt, 9, (255, 255, 255), 2)
                cv2.putText(display_frame, f"{idx+1}", (pt[0] + 12, pt[1] - 5),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, draw_color, 2)

            if len(drawing_points) >= 2:
                for i in range(len(drawing_points)):
                    pt1 = drawing_points[i]
                    pt2 = drawing_points[(i + 1) % len(drawing_points)]
                    cv2.line(display_frame, pt1, pt2, draw_color, 3)

        # Draw crosshair
        if mouse_position != (0, 0):
            mx, my = mouse_position
            cv2.drawMarker(display_frame, (mx, my), (255, 255, 255), cv2.MARKER_CROSS, 20, 2)

        # Create separate instruction window
        instruction_panel = create_instruction_window(
            current_stage, current_table_index, len(tables),
            len(sitting_areas), len(service_areas), len(drawing_points),
            mouse_position, current_table_sitting_count
        )

        # Show both windows
        cv2.imshow('ROI Setup - Video', display_frame)
        cv2.imshow('Instructions', instruction_panel)
        key = cv2.waitKey(10) & 0xFF

        # Enter - Complete current ROI
        if key == 13 or key == 10:
            if len(drawing_points) >= 3:
                polygon = drawing_points.copy()

                if current_stage == 'division':
                    division_polygon = polygon
                    operation_history.append(('division', division_polygon))
                    print(f"\n✓ Division completed with {len(polygon)} points")
                    print(f"   >> Switching to TABLES")
                    current_stage = 'table'
                    drawing_points = []

                elif current_stage == 'table':
                    table_id = f"T{current_table_index + 1}"
                    table = Table(table_id, polygon)
                    tables.append(table)
                    operation_history.append(('table', table))
                    print(f"\n✓ Table {table_id} completed")
                    print(f"   >> Switching to SITTING AREAS for {table_id}")
                    current_stage = 'sitting'
                    current_table_sitting_count = 0
                    drawing_points = []

                elif current_stage == 'sitting':
                    current_table_sitting_count += 1
                    sitting_id = f"SA{len(sitting_areas) + 1}"
                    table_id = f"T{current_table_index + 1}"
                    sitting = SittingArea(sitting_id, polygon, table_id)
                    sitting_areas.append(sitting)
                    tables[current_table_index].sitting_area_ids.append(sitting_id)
                    operation_history.append(('sitting', sitting))
                    print(f"\n✓ Sitting Area {sitting_id} completed (linked to {table_id})")
                    print(f"   >> Draw more sitting areas or press 'D' to finish this table")
                    drawing_points = []

                elif current_stage == 'service':
                    service_id = f"SV{len(service_areas) + 1}"
                    service = ServiceArea(service_id, polygon)
                    service_areas.append(service)
                    operation_history.append(('service', service))
                    print(f"\n✓ Service Area {service_id} completed")
                    print(f"   >> Draw more service areas or press Ctrl+S to save")
                    drawing_points = []
            else:
                print(f"\n✗ Need at least 3 points (currently {len(drawing_points)})")

        # D - Next table
        elif key == ord('d') or key == ord('D'):
            if current_stage == 'sitting':
                print(f"\n{'='*70}")
                print(f"✓ Finished {current_table_sitting_count} sitting area(s) for T{current_table_index + 1}")
                print(f"✓ TABLE {current_table_index + 1} COMPLETE!")
                print(f"{'='*70}")

                current_table_index += 1
                current_stage = 'table'
                current_table_sitting_count = 0
                drawing_points = []

                print(f"\n>> Starting TABLE {current_table_index + 1}...")
                print(f"\n   💡 TIP: Press 'S' to skip remaining tables and go to Service Areas")

            elif current_stage == 'table':
                print(f"\n⚠ Complete the table first (press Enter after drawing)")

        # S - Skip to service areas
        elif key == ord('s') or key == ord('S'):
            if current_stage in ['table', 'sitting'] and len(tables) > 0:
                print(f"\n{'='*70}")
                print(f"✓ Finished all tables ({len(tables)} total)")
                print(f"   >> Switching to SERVICE AREAS")
                print(f"{'='*70}")
                current_stage = 'service'
                drawing_points = []

        # Ctrl+S / Ctrl+S - Save all
        elif key == 19:
            if division_polygon and len(tables) > 0:
                config_data = {
                    'division': division_polygon,
                    'tables': [
                        {
                            'id': t.id,
                            'polygon': t.polygon,
                            'sitting_area_ids': t.sitting_area_ids
                        } for t in tables
                    ],
                    'sitting_areas': [
                        {
                            'id': sa.id,
                            'polygon': sa.polygon,
                            'table_id': sa.table_id
                        } for sa in sitting_areas
                    ],
                    'service_areas': [
                        {
                            'id': sv.id,
                            'polygon': sv.polygon
                        } for sv in service_areas
                    ],
                    'frame_size': [frame.shape[1], frame.shape[0]],
                    'video': video_path
                }

                with open(CONFIG_FILE, 'w') as f:
                    json.dump(config_data, f, indent=2)

                print(f"\n{'='*70}")
                print(f"✓ Configuration Saved: {CONFIG_FILE}")
                print(f"{'='*70}")
                print(f"   Division: ✓")
                print(f"   Tables: {len(tables)}")
                print(f"   Sitting Areas: {len(sitting_areas)}")
                print(f"   Service Areas: {len(service_areas)}")
                print(f"{'='*70}\n")

                cv2.destroyAllWindows()
                return config_data
            else:
                print(f"\n⚠ Need at least Division + 1 Table to save")

        # Ctrl+Z or U - Undo
        elif key == 26 or key == ord('u') or key == ord('U'):
            if len(drawing_points) > 0:
                drawing_points.pop()
                print(f"   ↶ Undo: Removed point")
            elif len(operation_history) > 0:
                op_type, _ = operation_history.pop()
                if op_type == 'division':
                    division_polygon = None
                    current_stage = 'division'
                    print(f"\n↶ Undo: Removed division")
                elif op_type == 'table':
                    tables.pop()
                    current_stage = 'table'
                    print(f"\n↶ Undo: Removed table")
                elif op_type == 'sitting':
                    sitting_areas.pop()
                    tables[current_table_index].sitting_area_ids.pop()
                    current_table_sitting_count -= 1
                    print(f"\n↶ Undo: Removed sitting area")
                elif op_type == 'service':
                    service_areas.pop()
                    print(f"\n↶ Undo: Removed service area")

        # Q - Quit
        elif key == ord('q') or key == ord('Q'):
            print("\nSetup cancelled")
            cv2.destroyAllWindows()
            return None


def scale_polygon(polygon, scale_x, scale_y):
    """
    Scale polygon coordinates by given factors

    Args:
        polygon: List of [x, y] coordinates
        scale_x: X-axis scaling factor
        scale_y: Y-axis scaling factor

    Returns:
        Scaled polygon coordinates
    """
    return [[int(x * scale_x), int(y * scale_y)] for x, y in polygon]


def auto_scale_config(config, actual_width, actual_height):
    """
    Automatically scale ROI configuration to match actual frame dimensions.

    This function handles resolution mismatches between the configuration creation
    environment (e.g., MacBook with 1920x1080 test video) and the production
    environment (e.g., Linux RTX with 2592x1944 camera feed).

    Args:
        config: Original configuration dictionary
        actual_width: Actual frame width from video
        actual_height: Actual frame height from video

    Returns:
        Scaled configuration dictionary

    Note:
        Configuration created at 1920x1080 but production camera at 2592x1944?
        This function automatically scales all ROI coordinates to match.
    """
    import copy
    scaled_config = copy.deepcopy(config)

    # Get configured frame size (default to 1920x1080 if not specified)
    config_width, config_height = scaled_config.get('frame_size', [1920, 1080])

    # Check if scaling is needed
    if config_width == actual_width and config_height == actual_height:
        return scaled_config

    # Calculate scaling factors
    scale_x = actual_width / config_width
    scale_y = actual_height / config_height

    print(f"⚠️  Resolution mismatch detected - Auto-scaling ROI configuration")
    print(f"   Config resolution:  {config_width}x{config_height}")
    print(f"   Actual resolution:  {actual_width}x{actual_height}")
    print(f"   Scale factors:      {scale_x:.3f}x (width), {scale_y:.3f}x (height)")

    # Scale division polygon
    if 'division' in scaled_config:
        scaled_config['division'] = scale_polygon(scaled_config['division'], scale_x, scale_y)

    # Scale tables
    if 'tables' in scaled_config:
        for table in scaled_config['tables']:
            table['polygon'] = scale_polygon(table['polygon'], scale_x, scale_y)

    # Scale sitting areas
    if 'sitting_areas' in scaled_config:
        for area in scaled_config['sitting_areas']:
            area['polygon'] = scale_polygon(area['polygon'], scale_x, scale_y)

    # Scale service areas
    if 'service_areas' in scaled_config:
        for area in scaled_config['service_areas']:
            area['polygon'] = scale_polygon(area['polygon'], scale_x, scale_y)

    # Update frame size to actual
    scaled_config['frame_size'] = [actual_width, actual_height]

    print(f"✅ Configuration auto-scaled successfully")

    return scaled_config


def load_config_from_file():
    """Load configuration from file"""
    if not os.path.exists(CONFIG_FILE):
        return None

    try:
        with open(CONFIG_FILE, 'r') as f:
            config = json.load(f)

        print(f"✅ Loaded configuration from: {os.path.basename(CONFIG_FILE)}")
        print(f"   Division: ✓")
        print(f"   Tables: {len(config.get('tables', []))}")
        print(f"   Sitting Areas: {len(config.get('sitting_areas', []))}")
        print(f"   Service Areas: {len(config.get('service_areas', []))}")

        return config
    except Exception as e:
        print(f"❌ Error loading config: {e}")
        return None


def reconstruct_objects_from_config(config):
    """Reconstruct objects from config data"""
    division_polygon = config['division']

    tables = []
    for t_data in config.get('tables', []):
        table = Table(t_data['id'], t_data['polygon'])
        table.sitting_area_ids = t_data.get('sitting_area_ids', [])
        tables.append(table)

    sitting_areas = []
    for sa_data in config.get('sitting_areas', []):
        sitting = SittingArea(sa_data['id'], sa_data['polygon'], sa_data['table_id'])
        sitting_areas.append(sitting)

    service_areas = []
    for sv_data in config.get('service_areas', []):
        service = ServiceArea(sv_data['id'], sv_data['polygon'])
        service_areas.append(service)

    return division_polygon, tables, sitting_areas, service_areas


def init_database(db_path):
    """Initialize SQLite database for state tracking

    Database structure:
    - sessions: Video processing sessions
    - division_states: Division state changes with timestamps
    - table_states: Table state changes with timestamps
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Sessions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            camera_id TEXT,
            video_file TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT,
            total_frames INTEGER,
            fps REAL,
            resolution TEXT,
            config_file TEXT
        )
    ''')

    # Division states table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS division_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            camera_id TEXT,
            frame_number INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            state TEXT NOT NULL,
            walking_area_waiters INTEGER,
            service_area_waiters INTEGER,
            screenshot_path TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    ''')

    # Table states table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS table_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            camera_id TEXT,
            frame_number INTEGER NOT NULL,
            timestamp REAL NOT NULL,
            table_id TEXT NOT NULL,
            state TEXT NOT NULL,
            customers_count INTEGER,
            waiters_count INTEGER,
            screenshot_path TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    ''')

    # Create indexes for faster queries
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_division_session ON division_states(session_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_division_frame ON division_states(frame_number)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_table_session ON table_states(session_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_table_frame ON table_states(frame_number)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_table_id ON table_states(table_id)')

    conn.commit()
    return conn


def save_screenshot(frame, screenshot_dir, camera_id, session_id, frame_number, prefix=""):
    """Save annotated frame as screenshot organized by camera

    Path: screenshots/{camera_id}/{date}/{session_id}/{prefix}frame_{number}.jpg

    Returns: relative path to screenshot file
    """
    # Organize by camera and date
    date_str = datetime.now().strftime('%Y%m%d')
    screenshot_path = Path(screenshot_dir) / camera_id / date_str / session_id
    screenshot_path.mkdir(parents=True, exist_ok=True)

    filename = f"{prefix}frame_{frame_number:06d}.jpg"
    filepath = screenshot_path / filename

    # Save with balanced quality (80 = good quality, ~5x smaller than 95)
    # Modified: 2025-12-09 - Reduced from 95 to 80 to decrease file size
    cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])

    # Return relative path
    return str(filepath.relative_to(Path(screenshot_dir).parent))


def log_division_state_change(conn, session_id, camera_id, frame_number, timestamp, state,
                              walking_waiters, service_waiters, screenshot_path):
    """Log division state change to database"""
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO division_states
        (session_id, camera_id, frame_number, timestamp, state, walking_area_waiters,
         service_area_waiters, screenshot_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (session_id, camera_id, frame_number, timestamp, state, walking_waiters,
          service_waiters, screenshot_path))
    conn.commit()


def log_table_state_change(conn, session_id, camera_id, frame_number, timestamp, table_id,
                           state, customers, waiters, screenshot_path):
    """Log table state change to database"""
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO table_states
        (session_id, camera_id, frame_number, timestamp, table_id, state,
         customers_count, waiters_count, screenshot_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (session_id, camera_id, frame_number, timestamp, table_id, state,
          customers, waiters, screenshot_path))
    conn.commit()


def load_models():
    """Load detection models"""
    print("📦 Loading models...")

    print(f"   Person detector: {os.path.basename(PERSON_DETECTOR_MODEL)}")
    person_detector = YOLO(PERSON_DETECTOR_MODEL)

    if not os.path.exists(STAFF_CLASSIFIER_MODEL):
        print(f"❌ Staff classifier not found: {STAFF_CLASSIFIER_MODEL}")
        return None, None

    print(f"   Staff classifier: {os.path.basename(STAFF_CLASSIFIER_MODEL)}")
    staff_classifier = YOLO(STAFF_CLASSIFIER_MODEL)

    print("✅ Models loaded successfully!\n")
    return person_detector, staff_classifier


def detect_persons(person_detector, frame):
    """Stage 1: Detect all persons"""
    results = person_detector(frame, conf=PERSON_CONF_THRESHOLD, classes=[0], verbose=False)

    person_detections = []
    for result in results:
        boxes = result.boxes
        if boxes is not None:
            for box in boxes:
                x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                confidence = box.conf[0].cpu().numpy()

                width = x2 - x1
                height = y2 - y1
                if width >= MIN_PERSON_SIZE and height >= MIN_PERSON_SIZE:
                    center_x = int((x1 + x2) / 2)
                    center_y = int((y1 + y2) / 2)
                    person_detections.append({
                        'bbox': (int(x1), int(y1), int(x2), int(y2)),
                        'confidence': float(confidence),
                        'center': (center_x, center_y)
                    })

    return person_detections


def classify_persons(staff_classifier, frame, person_detections):
    """Stage 2: Classify persons as waiter or customer"""
    classified_detections = []

    for detection in person_detections:
        x1, y1, x2, y2 = detection['bbox']
        person_crop = frame[y1:y2, x1:x2]

        if person_crop.shape[0] < 20 or person_crop.shape[1] < 20:
            classified_detections.append({
                'class': 'unknown',
                'confidence': 0.0,
                'bbox': detection['bbox'],
                'center': detection['center'],
                'person_confidence': detection['confidence']
            })
            continue

        classification_results = staff_classifier(person_crop, verbose=False)
        result = classification_results[0]

        if result.probs is not None:
            class_id = result.probs.top1
            confidence = float(result.probs.top1conf)
            class_name = CLASS_NAMES[class_id]

            if confidence >= STAFF_CONF_THRESHOLD:
                classified_detections.append({
                    'class': class_name,
                    'confidence': confidence,
                    'bbox': detection['bbox'],
                    'center': detection['center'],
                    'person_confidence': detection['confidence']
                })
            else:
                classified_detections.append({
                    'class': 'unknown',
                    'confidence': confidence,
                    'bbox': detection['bbox'],
                    'center': detection['center'],
                    'person_confidence': detection['confidence']
                })
        else:
            classified_detections.append({
                'class': 'unknown',
                'confidence': 0.0,
                'bbox': detection['bbox'],
                'center': detection['center'],
                'person_confidence': detection['confidence']
            })

    return classified_detections


def assign_detections_to_rois(division_polygon, tables, sitting_areas, service_areas, detections):
    """Assign detections to ROIs and calculate area counts

    Returns:
        (walking_area_waiters, service_area_waiters)
    """
    # Filter to division only
    division_detections = [d for d in detections if point_in_polygon(d['center'], division_polygon)]

    # Reset all counts
    for table in tables:
        table.update_counts(0, 0)

    walking_area_waiters = 0
    service_area_waiters = 0

    # Assign each detection
    for detection in division_detections:
        center = detection['center']
        assigned = False

        # Priority 1: Check tables
        for table in tables:
            if point_in_polygon(center, table.polygon):
                if detection['class'] == 'customer':
                    table.customers_present += 1
                elif detection['class'] == 'waiter':
                    table.waiters_present += 1
                assigned = True
                break

        if assigned:
            continue

        # Priority 2: Check sitting areas
        for sitting in sitting_areas:
            if point_in_polygon(center, sitting.polygon):
                # Find linked table
                for table in tables:
                    if table.id == sitting.table_id:
                        if detection['class'] == 'customer':
                            table.customers_present += 1
                        elif detection['class'] == 'waiter':
                            table.waiters_present += 1
                        assigned = True
                        break
                break

        if assigned:
            continue

        # Priority 3: Check service areas
        for service in service_areas:
            if point_in_polygon(center, service.polygon):
                if detection['class'] == 'waiter':
                    service_area_waiters += 1
                assigned = True
                break

        if assigned:
            continue

        # Priority 4: Walking area (implicit - remaining division area)
        if detection['class'] == 'waiter':
            walking_area_waiters += 1

    return walking_area_waiters, service_area_waiters


def draw_frame_with_all_info(frame, division_polygon, tables, sitting_areas, service_areas,
                              detections, division_state, tracker):
    """Draw complete annotated frame"""
    annotated = frame.copy()

    # 1. Draw division state overlay (on Service Area + Walking Area)
    division_color = {
        'red': COLORS['division_red'],
        'yellow': COLORS['division_yellow'],
        'green': COLORS['division_green']
    }.get(division_state, COLORS['division_red'])

    # Create mask for division
    mask = np.zeros(annotated.shape[:2], dtype=np.uint8)
    pts = np.array(division_polygon, np.int32)
    cv2.fillPoly(mask, [pts], 255)

    # Remove table + sitting areas from mask (they have their own colors)
    for table in tables:
        table_pts = np.array(table.polygon, np.int32)
        cv2.fillPoly(mask, [table_pts], 0)

    for sitting in sitting_areas:
        sitting_pts = np.array(sitting.polygon, np.int32)
        cv2.fillPoly(mask, [sitting_pts], 0)

    # Apply division color to walking + service areas
    overlay = annotated.copy()
    overlay[mask == 255] = division_color
    annotated[mask == 255] = cv2.addWeighted(
        overlay[mask == 255], 0.2,
        annotated[mask == 255], 0.8, 0
    )

    # 2. Draw division boundary
    cv2.polylines(annotated, [pts], True, COLORS['division'], 3)

    # 3. Draw service areas
    for service in service_areas:
        service_pts = np.array(service.polygon, np.int32)
        cv2.polylines(annotated, [service_pts], True, COLORS['service_area'], 2)

    # 4. Draw sitting areas (gray)
    for sitting in sitting_areas:
        sitting_pts = np.array(sitting.polygon, np.int32)
        cv2.polylines(annotated, [sitting_pts], True, COLORS['sitting_area'], 1)

    # 5. Draw tables with state colors
    for table in tables:
        table_pts = np.array(table.polygon, np.int32)
        table_color = table.get_state_color()

        # Fill
        overlay = annotated.copy()
        cv2.fillPoly(overlay, [table_pts], table_color)
        annotated = cv2.addWeighted(overlay, 0.25, annotated, 0.75, 0)

        # Border
        cv2.polylines(annotated, [table_pts], True, table_color, 3)

        # Label
        bbox = table.get_bbox()
        center_x = int((bbox[0] + bbox[2]) / 2)
        center_y = int((bbox[1] + bbox[3]) / 2)

        label_id = f"{table.id}"
        id_size = cv2.getTextSize(label_id, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 2)[0]
        cv2.putText(annotated, label_id,
                   (center_x - id_size[0]//2, center_y - 10),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        label_state = table.state.value
        state_size = cv2.getTextSize(label_state, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)[0]
        cv2.putText(annotated, label_state,
                   (center_x - state_size[0]//2, center_y + 20),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    # 5.5. Draw Division state label in center
    if division_polygon and len(division_polygon) >= 3:
        # Calculate division center
        division_pts = np.array(division_polygon, np.int32)
        M = cv2.moments(division_pts)
        if M['m00'] != 0:
            div_center_x = int(M['m10'] / M['m00'])
            div_center_y = int(M['m01'] / M['m00'])
        else:
            # Fallback to bbox center
            xs = [p[0] for p in division_polygon]
            ys = [p[1] for p in division_polygon]
            div_center_x = int((min(xs) + max(xs)) / 2)
            div_center_y = int((min(ys) + max(ys)) / 2)

        # State names mapping
        state_names = {
            'red': 'UNDERSTAFFED',      # 脱岗
            'yellow': 'STAFF BUSY',      # 忙碌中
            'green': 'STAFF SERVING'     # 服务中
        }

        # Get state info
        state_name = state_names.get(division_state, 'UNKNOWN')

        # Draw semi-transparent background box
        label_title = "DIVISION"
        title_size = cv2.getTextSize(label_title, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 3)[0]
        state_size = cv2.getTextSize(state_name, cv2.FONT_HERSHEY_SIMPLEX, 1.0, 2)[0]

        # Calculate box dimensions
        box_width = max(title_size[0], state_size[0]) + 40
        box_height = title_size[1] + state_size[1] + 60
        box_x1 = div_center_x - box_width // 2
        box_y1 = div_center_y - box_height // 2
        box_x2 = div_center_x + box_width // 2
        box_y2 = div_center_y + box_height // 2

        # Draw background with border
        overlay = annotated.copy()
        cv2.rectangle(overlay, (box_x1, box_y1), (box_x2, box_y2), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.7, annotated, 0.3, 0, annotated)
        cv2.rectangle(annotated, (box_x1, box_y1), (box_x2, box_y2), division_color, 4)

        # Draw DIVISION title
        title_x = div_center_x - title_size[0] // 2
        title_y = div_center_y - 15
        cv2.putText(annotated, label_title,
                   (title_x, title_y),
                   cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)

        # Draw state name
        state_x = div_center_x - state_size[0] // 2
        state_y = div_center_y + state_size[1] + 10
        cv2.putText(annotated, state_name,
                   (state_x, state_y),
                   cv2.FONT_HERSHEY_SIMPLEX, 1.0, division_color, 2)

    # 6. Draw person detections
    for detection in detections:
        x1, y1, x2, y2 = detection['bbox']
        class_name = detection['class']
        confidence = detection['confidence']
        center = detection['center']

        color = COLORS.get(class_name, COLORS['unknown'])
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)

        label = f"{class_name}: {confidence:.1%}" if confidence > 0 else class_name
        label_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0]
        cv2.rectangle(annotated,
                     (x1, y1 - label_size[1] - 8),
                     (x1 + label_size[0] + 6, y1),
                     color, -1)
        cv2.putText(annotated, label, (x1 + 3, y1 - 4),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # Center point
        cv2.circle(annotated, center, 8, (0, 0, 0), -1)
        cv2.circle(annotated, center, 6, (255, 255, 255), -1)
        cv2.circle(annotated, center, 6, color, 2)

    # 7. Draw stats panel
    y = 30
    x = 10
    font = cv2.FONT_HERSHEY_SIMPLEX

    # Background
    overlay = annotated.copy()
    stats_height = 120 + (len(tables) * 25)
    cv2.rectangle(overlay, (5, 5), (450, stats_height), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, annotated, 0.4, 0, annotated)

    # FPS
    fps = tracker.get_current_fps()
    cv2.putText(annotated, f"FPS: {fps:.2f}", (x, y), font, 0.6, (0, 255, 255), 2)

    # Frame
    y += 25
    cv2.putText(annotated, f"Frame: {tracker.total_frames}", (x, y), font, 0.6, (255, 255, 255), 2)

    # Stage times
    avg_s1, avg_s2 = tracker.get_avg_stage_times()
    y += 25
    cv2.putText(annotated, f"Stage1: {avg_s1:.0f}ms | Stage2: {avg_s2:.0f}ms",
               (x, y), font, 0.6, (255, 255, 0), 2)

    # Division state
    y += 25
    division_text = {
        'red': 'DIV: RED (Understaffed)',
        'yellow': 'DIV: YELLOW (Staff Busy)',
        'green': 'DIV: GREEN (Staff Serving)'
    }.get(division_state, 'DIV: UNKNOWN')
    cv2.putText(annotated, division_text, (x, y), font, 0.6, division_color, 2)

    # ROI counts
    y += 25
    cv2.putText(annotated, f"Tables:{len(tables)} Sitting:{len(sitting_areas)} Service:{len(service_areas)}",
               (x, y), font, 0.5, (255, 255, 255), 1)

    # Table states
    for table in tables:
        y += 25
        table_color = table.get_state_color()
        table_info = f"{table.id}: {table.state.value} (C:{table.customers_present} W:{table.waiters_present})"
        cv2.putText(annotated, table_info, (x + 10, y), font, 0.5, table_color, 1)

    return annotated


def process_video(video_path, person_detector, staff_classifier, config, output_dir=None, duration_limit=None, target_fps=5):
    """Process video with table and division state detection

    Args:
        video_path: Path to input video
        person_detector: YOLO person detection model
        staff_classifier: YOLO staff classification model
        config: ROI configuration dictionary
        output_dir: Output directory for results
        duration_limit: Process only first N seconds (None = full video)
        target_fps: Target processing FPS (default: 5). Process at this rate instead of every frame.
    """
    if output_dir is None:
        output_dir = str(SCRIPT_DIR.parent / "test-results")

    # Extract camera_id from filename
    camera_id = extract_camera_id_from_filename(video_path)

    print(f"\n{'='*70}")
    print(f"Processing Video: {os.path.basename(video_path)}")
    print(f"Camera ID: {camera_id}")
    print(f"{'='*70}")

    # Open video
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Could not open video: {video_path}")
        return False

    # Video properties
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration = frame_count / fps if fps > 0 else 0

    # Auto-scale configuration to match actual video resolution
    config = auto_scale_config(config, width, height)

    # Reconstruct objects with scaled configuration
    division_polygon, tables, sitting_areas, service_areas = reconstruct_objects_from_config(config)

    print(f"ROIs: Division=1 Tables={len(tables)} Sitting={len(sitting_areas)} Service={len(service_areas)}\n")

    max_frames = frame_count
    if duration_limit is not None:
        max_frames = int(duration_limit * fps)

    # ===== MODIFIED: Calculate frame skip interval =====
    # Example: Video is 20 FPS, target is 5 FPS -> process every 4th frame (interval=4)
    frame_interval = max(1, int(round(fps / target_fps))) if target_fps > 0 else 1
    expected_processed = max_frames // frame_interval
    # ===================================================

    print(f"Video Properties:")
    print(f"   Resolution: {width}x{height}")
    print(f"   FPS: {fps:.2f}")
    print(f"   Frames: {frame_count}")
    print(f"   Duration: {duration:.2f}s")
    if duration_limit:
        print(f"   Processing: {max_frames} frames ({duration_limit}s)")
    # ===== MODIFIED: Show processing configuration =====
    print(f"\nProcessing Configuration:")
    print(f"   Target FPS: {target_fps}")
    print(f"   Frame interval: {frame_interval} (process 1 in {frame_interval} frames)")
    print(f"   Expected processed: ~{expected_processed} frames")
    print(f"   Speedup: ~{frame_interval}x faster")
    # ====================================================
    print()

    # Extract camera_id and date for symmetric output structure
    camera_id = extract_camera_id_from_filename(video_path)
    video_date = extract_date_from_path(video_path)

    print(f"📹 Camera ID: {camera_id}")
    print(f"📅 Video Date: {video_date}")

    # ===== CRITICAL: Initialize database and check for duplicates FIRST =====
    # This must happen BEFORE VideoWriter creation to prevent 258-byte empty files
    # db/ is at production/RTX_3060/db (same level as results/)
    # Calculate db path using PROJECT_ROOT constant (set at module level)
    db_dir = PROJECT_ROOT / "db"

    # Validate the calculated path makes sense
    if not db_dir.exists() or db_dir.name != "db":
        # Fallback: Try one more level up if PROJECT_ROOT calculation failed
        db_dir = SCRIPT_DIR.parent.parent.parent.parent / "db"

    # Ensure db directory exists
    db_dir.mkdir(parents=True, exist_ok=True)

    # Validate it's writable
    try:
        test_file = db_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
    except (PermissionError, OSError) as e:
        print(f"❌ ERROR: Database directory not writable: {db_dir}", file=sys.stderr)
        print(f"   Error: {e}", file=sys.stderr)
        cap.release()
        return False

    db_path = db_dir / "detection_data.db"
    conn = init_database(str(db_path))

    # Check if video already processed (BEFORE creating output file)
    video_filename = os.path.basename(video_path)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT session_id, start_time FROM sessions
        WHERE camera_id = ? AND video_file = ?
    ''', (camera_id, video_filename))
    existing = cursor.fetchone()

    if existing:
        # Use stderr for warnings so orchestrator can capture them
        print(f"\n⚠️  WARNING: This video has already been processed!", file=sys.stderr)
        print(f"   Video: {video_filename}", file=sys.stderr)
        print(f"   Camera: {camera_id}", file=sys.stderr)
        print(f"   Previous session: {existing[0]}", file=sys.stderr)
        print(f"   Previous time: {existing[1]}", file=sys.stderr)
        print(f"\n❌ Skipping to avoid duplicate data in database", file=sys.stderr)
        print(f"   Delete the previous session first if you want to reprocess.\n", file=sys.stderr)
        cap.release()
        conn.close()
        # Exit with code 2 to indicate "skipped" (not an error)
        sys.exit(2)
    # =====================================================================

    # Setup output: results/YYYYMMDD/camera_id/ (symmetric to videos structure)
    output_path = Path(output_dir) / video_date / camera_id
    output_path.mkdir(parents=True, exist_ok=True)

    script_name = Path(__file__).stem
    output_filename = f"{script_name}_{Path(video_path).stem}.mp4"
    output_file = str(output_path / output_filename)

    # Modified: 2025-11-19 - Fixed H.264 encoder unavailability
    # Changed from 'avc1' (H.264) to 'mp4v' (MPEG-4 Part 2)
    # Reason: OpenCV FFmpeg build missing H.264 encoder (codec_id=27)
    # MPEG-4 provides good compression (better than MJPEG) and universal compatibility
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # MPEG-4 Part 2 codec
    out = cv2.VideoWriter(output_file, fourcc, fps, (width, height))

    if not out.isOpened():
        print(f"❌ Could not create output: {output_file}", file=sys.stderr)
        cap.release()
        conn.close()
        return False

    # Initialize trackers
    tracker = PerformanceTracker(window_size=30)
    division_tracker = DivisionStateTracker()

    # Modified 2025-12-10: Fix session_id concurrency conflict
    # Include video filename timestamp for uniqueness across parallel workers
    # Extract timestamp from filename (e.g., camera_35_20251209_180441.mp4 -> 20251209_180441)
    import re
    video_ts_match = re.search(r'(\d{8}_\d{6})', video_filename)
    video_ts = video_ts_match.group(1) if video_ts_match else datetime.now().strftime("%Y%m%d_%H%M%S")
    session_id = f"{video_ts}_{camera_id}"  # e.g., 20251209_180441_camera_35

    cursor.execute('''
        INSERT INTO sessions
        (session_id, camera_id, video_file, start_time, fps, resolution, config_file)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (session_id, camera_id, video_filename,
          datetime.now().isoformat(), fps, f"{width}x{height}", CONFIG_FILE))
    conn.commit()

    # Create screenshots directory (organized by camera)
    screenshot_dir = db_dir / "screenshots"
    screenshot_dir.mkdir(parents=True, exist_ok=True)

    # ===== FIRST-FRAME DUPLICATION FOR DEBOUNCE BUFFER =====
    # Process first frame multiple times to fill debounce buffer
    print("\n" + "="*70)
    print("First-Frame Preprocessing (v3.1.0)")
    print("="*70)
    print("📌 Processing first frame multiple times to fill debounce buffer...")

    # Read first frame ONCE
    ret, first_frame = cap.read()
    if not ret:
        print("❌ Could not read first frame")
        cap.release()
        out.release()
        conn.close()
        return False

    # Reset to beginning for normal processing
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)

    # Calculate frames needed based on ACTUAL FPS (flexible!)
    frames_for_debounce = int(target_fps * STATE_DEBOUNCE_SECONDS)
    time_step = 1.0 / target_fps

    print(f"   Target FPS: {target_fps}")
    print(f"   Debounce period: {STATE_DEBOUNCE_SECONDS}s")
    print(f"   Frames to process: {frames_for_debounce}")
    print(f"   Time step: {time_step:.3f}s per frame")

    # Process first frame multiple times
    initial_time = time.time()

    for i in range(frames_for_debounce):
        # Simulated time for this iteration
        simulated_time = initial_time + (i * time_step)

        # Run full detection pipeline on SAME frame
        person_detections = detect_persons(person_detector, first_frame)
        classified_detections = classify_persons(staff_classifier, first_frame, person_detections)

        # Assign to ROIs
        walking_waiters, service_waiters = assign_detections_to_rois(
            division_polygon, tables, sitting_areas, service_areas, classified_detections
        )

        # Update states through debounce (NOT direct assignment!)
        for table in tables:
            table.update_state(simulated_time)

        division_tracker.update_state(walking_waiters, service_waiters, simulated_time)

        # Log first iteration only
        if i == 0:
            waiters = sum(1 for d in classified_detections if d['class'] == 'waiter')
            customers = sum(1 for d in classified_detections if d['class'] == 'customer')
            unknown = sum(1 for d in classified_detections if d['class'] == 'unknown')
            print(f"\n   Initial detections (frame 0):")
            print(f"   ✓ Persons: {len(person_detections)} (Waiters: {waiters}, Customers: {customers}, Unknown: {unknown})")
            print(f"   ✓ Walking area waiters: {walking_waiters}")
            print(f"   ✓ Service area waiters: {service_waiters}")

    # After loop, states are established through proper debounce
    print(f"\n   ✅ Processed first frame {frames_for_debounce} times")
    print(f"   ✅ Debounce buffer filled ({STATE_DEBOUNCE_SECONDS}s @ {target_fps} FPS)")
    print("\n   Final initial states:")
    for table in tables:
        print(f"   {table.id}: {table.state.value} (C:{table.customers_present} W:{table.waiters_present})")
    print(f"   DIVISION: {division_tracker.current_state.upper()} (Walking:{walking_waiters} Service:{service_waiters})")
    print("="*70 + "\n")
    # ======================================================

    # Process frames
    frame_idx = 0

    print("🔄 Processing frames...")
    print(f"   Debounce: {STATE_DEBOUNCE_SECONDS}s for all state changes")
    print(f"   Table colors: GREEN=IDLE | YELLOW=BUSY | BLUE=CLEANING")
    print(f"   Division colors: RED=Understaffed | YELLOW=Busy | GREEN=Serving\n")

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame_idx >= max_frames:
                break

            # ===== MODIFIED: Increment total frames (including skipped) =====
            tracker.increment_total_frames()
            # ================================================================

            # ===== MODIFIED: Smart frame skipping =====
            # Skip frames if not at the interval (e.g., skip frames 1,2,3 but process frame 0,4,8,12...)
            if frame_idx % frame_interval != 0:
                frame_idx += 1
                continue
            # ==========================================

            frame_start = time.time()
            current_time = time.time()

            # Stage 1: Detect persons
            stage1_start = time.time()
            person_detections = detect_persons(person_detector, frame)
            stage1_time = time.time() - stage1_start

            # Stage 2: Classify persons
            stage2_start = time.time()
            classified_detections = classify_persons(staff_classifier, frame, person_detections)
            stage2_time = time.time() - stage2_start

            # Assign to ROIs
            walking_waiters, service_waiters = assign_detections_to_rois(
                division_polygon, tables, sitting_areas, service_areas, classified_detections
            )

            # Track state changes for screenshot/logging
            changed_tables = []
            division_changed = False

            # Update table states
            for table in tables:
                if table.update_state(current_time):
                    print(f"   {table.id}: {table.state.value} (C:{table.customers_present} W:{table.waiters_present})")
                    changed_tables.append(table)

            # Update division state
            if division_tracker.update_state(walking_waiters, service_waiters, current_time):
                print(f"   DIVISION: {division_tracker.current_state.upper()} (Walking:{walking_waiters} Service:{service_waiters})")
                division_changed = True

            # Track performance
            frame_time = time.time() - frame_start
            tracker.add_frame(frame_time, stage1_time, stage2_time)

            # Draw annotated frame
            annotated_frame = draw_frame_with_all_info(
                frame, division_polygon, tables, sitting_areas, service_areas,
                classified_detections, division_tracker.current_state, tracker
            )

            # ===== MODIFIED: Maintain original frame numbers in database/screenshots =====
            # Save screenshots and log state changes to database (use original frame_idx)
            for table in changed_tables:
                screenshot_path = save_screenshot(
                    annotated_frame, screenshot_dir, camera_id, session_id,
                    frame_idx, prefix=f"{table.id}_")  # ← Uses original frame_idx
                log_table_state_change(
                    conn, session_id, camera_id, frame_idx, current_time,  # ← Uses original frame_idx
                    table.id, table.state.value,
                    table.customers_present, table.waiters_present,
                    screenshot_path)

            if division_changed:
                screenshot_path = save_screenshot(
                    annotated_frame, screenshot_dir, camera_id, session_id,
                    frame_idx, prefix="division_")  # ← Uses original frame_idx
                log_division_state_change(
                    conn, session_id, camera_id, frame_idx, current_time,  # ← Uses original frame_idx
                    division_tracker.current_state.upper(),
                    walking_waiters, service_waiters,
                    screenshot_path)
            # ===========================================================================

            out.write(annotated_frame)
            frame_idx += 1

            # ===== MODIFIED: Updated progress display =====
            # Progress - show processed vs total
            if tracker.processed_frames % 30 == 0:
                progress = (frame_idx / max_frames) * 100
                table_states = " | ".join([f"{t.id}:{t.state.value[:3]}" for t in tables])
                div_state = division_tracker.current_state.upper()[:3]
                print(f"   Progress: {progress:.1f}% | Frame {frame_idx}/{max_frames} "
                      f"(Processed: {tracker.processed_frames}/{expected_processed}) | "
                      f"FPS: {tracker.get_current_fps():.2f} | DIV:{div_state} | {table_states}")
            # ===============================================

    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")

    finally:
        # Update session end time and close database
        cursor.execute('''
            UPDATE sessions SET end_time = ?, total_frames = ?
            WHERE session_id = ?
        ''', (datetime.now().isoformat(), frame_idx, session_id))
        conn.commit()
        conn.close()

        cap.release()
        out.release()

        # ===== MODIFIED: 2025-12-09 - Re-encode video with H.264 for smaller file size =====
        # OpenCV mp4v creates large files (~75MB/60s), H.264 reduces to ~15MB/60s
        temp_output = output_file + ".temp.mp4"
        os.rename(output_file, temp_output)

        ffmpeg_cmd = [
            'ffmpeg', '-y', '-i', temp_output,
            '-c:v', 'libx264',      # H.264 codec
            '-preset', 'fast',       # Fast encoding, good compression
            '-crf', '23',            # Quality (18-28, lower=better, 23=default)
            '-c:a', 'copy',          # Copy audio if present
            '-movflags', '+faststart',  # Web-friendly
            output_file
        ]

        try:
            import subprocess
            result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=300)
            if result.returncode == 0:
                # Success - remove temp file
                os.unlink(temp_output)
                print(f"🎬 Video re-encoded to H.264 (smaller file size)")
            else:
                # Failed - keep original mp4v file
                os.rename(temp_output, output_file)
                print(f"⚠️ H.264 re-encoding failed, keeping MPEG4 output", file=sys.stderr)
        except Exception as e:
            # Error - keep original mp4v file
            if os.path.exists(temp_output):
                os.rename(temp_output, output_file)
            print(f"⚠️ H.264 re-encoding error: {e}", file=sys.stderr)
        # ==================================================================================

        # ===== MODIFIED: Pass target_fps to summary =====
        # Print summary
        tracker.print_summary(duration if duration_limit is None else duration_limit, fps, target_fps)
        # =================================================

        # Division state summary
        print(f"\n{'='*70}")
        print(f"Division State Summary")
        print(f"{'='*70}")
        print(f"   Final State: {division_tracker.current_state.upper()}")
        print(f"   State Transitions: {len(division_tracker.state_transitions)}")
        if division_tracker.state_transitions:
            print(f"   Recent transitions:")
            for trans in division_tracker.state_transitions[-5:]:
                print(f"      {trans['from'].upper()} -> {trans['to'].upper()}")
        print(f"{'='*70}\n")

        # Table state summary
        print(f"{'='*70}")
        print(f"Table State Summary")
        print(f"{'='*70}")
        for table in tables:
            print(f"\n{table.id}:")
            print(f"   Final State: {table.state.value}")
            print(f"   Customers: {table.customers_present}")
            print(f"   Waiters: {table.waiters_present}")
            print(f"   Transitions: {len(table.state_transitions)}")
            if table.state_transitions:
                print(f"   Recent transitions:")
                for trans in table.state_transitions[-3:]:
                    print(f"      {trans['from']} -> {trans['to']}")
        print(f"{'='*70}\n")

        print(f"💾 Video saved: {output_file}")
        print(f"💾 Database saved: {db_path}")
        print(f"📸 Screenshots: {screenshot_dir}/{camera_id}/{datetime.now().strftime('%Y%m%d')}/{session_id}/")
        print(f"   Camera ID: {camera_id}")
        print(f"   Session ID: {session_id}")
        print(f"✅ Processing complete!\n")

    return True


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Table and Region State Detection System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive setup mode
  python3 table_and_region_state_detection.py --video ../videos/camera_35.mp4 --interactive

  # Process with existing config at 5 FPS (default)
  python3 table_and_region_state_detection.py --video ../videos/camera_35.mp4 --duration 60

  # Process at 10 FPS (higher quality, slower)
  python3 table_and_region_state_detection.py --video ../videos/camera_35.mp4 --fps 10

  # Process at 2 FPS (emergency fast mode)
  python3 table_and_region_state_detection.py --video ../videos/camera_35.mp4 --fps 2

  # Process full video
  python3 table_and_region_state_detection.py --video ../videos/camera_35.mp4
        """
    )
    parser.add_argument("--video", required=True, help="Path to input video")
    parser.add_argument("--output", default=str(PROJECT_ROOT / "results"),
                       help="Output directory (default: ../../results)")
    parser.add_argument("--interactive", action="store_true",
                       help="Interactive ROI setup mode")
    parser.add_argument("--duration", type=int, default=None,
                       help="Process only first N seconds (default: full video)")
    # ===== MODIFIED: Added --fps parameter =====
    parser.add_argument("--fps", type=float, default=5.0,
                       help="Target processing FPS (default: 5.0). Process at this rate instead of every frame.")
    # ===========================================
    parser.add_argument("--person_conf", type=float, default=0.3,
                       help="Person detection confidence (default: 0.3)")
    parser.add_argument("--staff_conf", type=float, default=0.5,
                       help="Staff classification confidence (default: 0.5)")

    args = parser.parse_args()

    # Update thresholds
    global PERSON_CONF_THRESHOLD, STAFF_CONF_THRESHOLD
    PERSON_CONF_THRESHOLD = args.person_conf
    STAFF_CONF_THRESHOLD = args.staff_conf

    # Step 1: Get configuration
    print("\n" + "="*70)
    print("Step 1: Configuration Setup")
    print("="*70)

    config = None

    if args.interactive:
        config = setup_all_rois_from_video(args.video)
        if config is None:
            print("\n❌ Setup cancelled")
            return 1
    else:
        config = load_config_from_file()
        if config is None:
            print(f"\n⚠️  No config found: {CONFIG_FILE}")
            print("   Use --interactive to create configuration")
            return 1

    # Step 2: Load models
    print("\n" + "="*70)
    print("Step 2: Loading Models")
    print("="*70)
    person_detector, staff_classifier = load_models()
    if person_detector is None or staff_classifier is None:
        return 1

    # Step 3: Process video
    print("\n" + "="*70)
    print("Step 3: Video Processing")
    print("="*70)
    # ===== MODIFIED: Pass target_fps to process_video =====
    success = process_video(args.video, person_detector, staff_classifier, config,
                           args.output, args.duration, target_fps=args.fps)
    # =======================================================

    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
