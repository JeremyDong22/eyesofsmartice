#!/usr/bin/env python3
"""
# Modified: 2025-11-20 - Changed raw video cleanup logic to delete >= 2 days unconditionally
# Feature: Raw videos now deleted when >= 2 days old, regardless of processing status
# Reason: Ensures memory/hardware health by preventing accumulation of old files

Disk Space Monitoring and Management
Version: 2.1.0
Last Updated: 2025-11-20

Purpose: Monitor disk space and intelligently manage video storage with predictive analytics

Changes in v2.1.0 (2025-11-20):
- BREAKING: Raw videos now deleted when >= 2 days old (not >2 days)
- BREAKING: Removed "processed video" check - deletes unconditionally
- Reason: Prevent corrupted/failed videos from accumulating indefinitely
- Ensures hardware health by regular cleanup

Changes in v2.0.0:
- Added intelligent disk usage speed monitoring (observe 30 seconds)
- Calculate GB/hour consumption rate during recording hours
- Query active recording processes for remaining time
- Predict total space needed until end of day
- Proactive cleanup based on predictions (not just current state)
- Designed for hourly cron checks (vs 2-hour checks in v1.0)

Features:
- Check available disk space
- Alert when space < 100GB
- Smart cleanup: delete oldest videos first
- Critical alert: can't store 1 day of videos
- Respects processing schedule (keeps yesterday + today)
- Predictive space management based on usage rate

Usage:
  python3 check_disk_space.py --check           # Check only
  python3 check_disk_space.py --cleanup         # Check and cleanup if needed
  python3 check_disk_space.py --min-space 150   # Custom threshold (GB)
  python3 check_disk_space.py --predict         # Show predictions without cleanup
"""

import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta
import argparse
import sys
import time
import subprocess

# Constants
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent.parent
VIDEOS_DIR = PROJECT_DIR / "videos"
RESULTS_DIR = PROJECT_DIR / "results"
DB_DIR = PROJECT_DIR / "db"

MIN_SPACE_GB = 150  # Minimum required space (based on actual 78GB/day + processing + buffer)
ESTIMATED_VIDEO_SIZE_PER_DAY_GB = 80  # Actual measured: 10 cameras × 10 hours @ 0.222 MB/s

# Recording schedule (restaurant operating hours)
RECORDING_START_HOUR = 11  # 11 AM
RECORDING_END_HOUR = 21    # 9 PM (21:00)
OBSERVATION_SECONDS = 30   # Observe disk usage for 30 seconds

# Data retention policies (in days)
SCREENSHOTS_RETENTION_DAYS = 30  # Keep screenshots for 30 days
PROCESSED_VIDEO_RETENTION_DAYS = 2  # Keep processed videos for 2 days
RAW_VIDEO_RETENTION_DAYS = 2  # Keep raw videos max 2 days (or delete when processed)

def get_disk_usage(path):
    """Get disk usage statistics in GB"""
    stat = os.statvfs(str(path))
    total_gb = (stat.f_blocks * stat.f_frsize) / (1024**3)
    free_gb = (stat.f_bavail * stat.f_frsize) / (1024**3)
    used_gb = total_gb - free_gb
    used_percent = (used_gb / total_gb) * 100
    return {
        'total_gb': total_gb,
        'used_gb': used_gb,
        'free_gb': free_gb,
        'used_percent': used_percent
    }

def get_date_folders(directory):
    """Get all YYYYMMDD date folders, sorted oldest first"""
    if not directory.exists():
        return []

    date_folders = []
    for item in directory.iterdir():
        if item.is_dir() and item.name.isdigit() and len(item.name) == 8:
            try:
                date_obj = datetime.strptime(item.name, "%Y%m%d")
                date_folders.append((item, date_obj))
            except ValueError:
                continue

    # Sort by date (oldest first)
    date_folders.sort(key=lambda x: x[1])
    return [folder for folder, _ in date_folders]

def get_folder_size(folder):
    """Calculate total size of folder in GB"""
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(folder):
        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            if os.path.exists(filepath):
                total_size += os.path.getsize(filepath)
    return total_size / (1024**3)  # Convert to GB

def check_video_processed(video_date, camera_id):
    """
    Check if raw video has been processed by looking for results

    Args:
        video_date: Date string (YYYYMMDD)
        camera_id: Camera ID (e.g., camera_35)

    Returns:
        bool: True if processed results exist
    """
    # Check if results folder exists for this date/camera
    result_path = RESULTS_DIR / video_date / camera_id
    if not result_path.exists():
        return False

    # Check if there are any .mp4 files (processed videos)
    mp4_files = list(result_path.glob("*.mp4"))
    return len(mp4_files) > 0

def get_date_age_days(date_str):
    """
    Calculate how many days old a date string is

    Args:
        date_str: Date string (YYYYMMDD)

    Returns:
        int: Number of days old (0 = today, 1 = yesterday, etc.)
    """
    try:
        date_obj = datetime.strptime(date_str, "%Y%m%d")
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        delta = today - date_obj.replace(hour=0, minute=0, second=0, microsecond=0)
        return delta.days
    except ValueError:
        return 999  # Invalid date, treat as very old

def measure_disk_usage_speed(observation_seconds=OBSERVATION_SECONDS):
    """
    Measure disk usage speed by observing for N seconds

    Returns:
        dict with:
        - gb_per_hour: Disk usage rate in GB/hour
        - gb_per_second: Disk usage rate in GB/second
        - initial_used_gb: Initial disk usage
        - final_used_gb: Final disk usage
        - delta_gb: Change in disk usage during observation
    """
    print(f"\n{'='*70}")
    print(f"DISK USAGE SPEED MEASUREMENT")
    print(f"{'='*70}")
    print(f"📊 Observing disk usage for {observation_seconds} seconds...")

    # Initial measurement
    initial_usage = get_disk_usage(PROJECT_DIR)
    initial_used_gb = initial_usage['used_gb']
    initial_time = time.time()

    print(f"   Initial used: {initial_used_gb:.3f} GB")
    print(f"   Waiting {observation_seconds}s...")

    # Wait
    time.sleep(observation_seconds)

    # Final measurement
    final_usage = get_disk_usage(PROJECT_DIR)
    final_used_gb = final_usage['used_gb']
    final_time = time.time()

    # Calculate rate
    delta_gb = final_used_gb - initial_used_gb
    delta_seconds = final_time - initial_time
    gb_per_second = delta_gb / delta_seconds if delta_seconds > 0 else 0
    gb_per_hour = gb_per_second * 3600

    print(f"   Final used: {final_used_gb:.3f} GB")
    print(f"   Delta: {delta_gb:.3f} GB in {delta_seconds:.1f}s")
    print(f"   Rate: {gb_per_hour:.2f} GB/hour ({gb_per_second:.6f} GB/s)")
    print(f"{'='*70}\n")

    return {
        'gb_per_hour': gb_per_hour,
        'gb_per_second': gb_per_second,
        'initial_used_gb': initial_used_gb,
        'final_used_gb': final_used_gb,
        'delta_gb': delta_gb,
        'observation_seconds': delta_seconds
    }

def get_recording_remaining_hours():
    """
    Calculate remaining recording hours for today

    Recording schedule: 11 AM - 9 PM (10 hours daily)

    Returns:
        float: Remaining hours until recording ends (0 if outside recording window)
    """
    now = datetime.now()
    current_hour = now.hour
    current_minute = now.minute

    # Before recording starts
    if current_hour < RECORDING_START_HOUR:
        # Time until recording ends today
        hours_until_start = RECORDING_START_HOUR - current_hour - (current_minute / 60.0)
        total_recording_hours = RECORDING_END_HOUR - RECORDING_START_HOUR
        return hours_until_start + total_recording_hours

    # During recording
    elif RECORDING_START_HOUR <= current_hour < RECORDING_END_HOUR:
        remaining = RECORDING_END_HOUR - current_hour - (current_minute / 60.0)
        return remaining

    # After recording ends
    else:
        return 0.0

def check_active_recording_processes():
    """
    Check for active recording processes

    Returns:
        dict with:
        - active: bool - whether recording is active
        - process_count: int - number of capture processes
        - process_names: list - names of active processes
    """
    try:
        # Look for capture_rtsp_streams.py processes
        result = subprocess.run(
            ['pgrep', '-f', 'capture_rtsp_streams'],
            capture_output=True,
            text=True
        )

        pids = result.stdout.strip().split('\n') if result.stdout.strip() else []
        process_count = len([p for p in pids if p])

        return {
            'active': process_count > 0,
            'process_count': process_count,
            'process_names': ['capture_rtsp_streams.py'] * process_count
        }
    except Exception as e:
        print(f"⚠️  Could not check recording processes: {e}")
        return {
            'active': False,
            'process_count': 0,
            'process_names': []
        }

def predict_space_needed(usage_rate_gb_per_hour, remaining_hours):
    """
    Predict total disk space needed until end of day

    Args:
        usage_rate_gb_per_hour: Current disk usage rate in GB/hour
        remaining_hours: Hours remaining until recording ends

    Returns:
        dict with prediction details
    """
    print(f"\n{'='*70}")
    print(f"SPACE PREDICTION")
    print(f"{'='*70}")

    # Calculate prediction
    predicted_usage_gb = usage_rate_gb_per_hour * remaining_hours

    # Get current space
    current_usage = get_disk_usage(PROJECT_DIR)
    current_free_gb = current_usage['free_gb']

    # Predict free space at end of day
    predicted_free_gb = current_free_gb - predicted_usage_gb

    # Safety margin (20% extra)
    safety_margin_gb = predicted_usage_gb * 0.2
    recommended_free_gb = predicted_usage_gb + safety_margin_gb

    # Status
    sufficient = predicted_free_gb > 0
    safe = predicted_free_gb > safety_margin_gb

    print(f"Current Status:")
    print(f"   Free space now: {current_free_gb:.1f} GB")
    print(f"   Usage rate: {usage_rate_gb_per_hour:.2f} GB/hour")
    print(f"   Remaining hours: {remaining_hours:.1f} hours")
    print(f"")
    print(f"Predictions:")
    print(f"   Expected usage: {predicted_usage_gb:.1f} GB")
    print(f"   Safety margin (20%): {safety_margin_gb:.1f} GB")
    print(f"   Recommended free: {recommended_free_gb:.1f} GB")
    print(f"   Predicted free at end: {predicted_free_gb:.1f} GB")
    print(f"")

    if safe:
        status = "✅ SAFE"
        message = "Sufficient space for remaining recordings with safety margin"
    elif sufficient:
        status = "⚠️  TIGHT"
        message = "Sufficient space but no safety margin - cleanup recommended"
    else:
        status = "🚨 CRITICAL"
        message = "INSUFFICIENT SPACE - will run out before end of day!"

    print(f"Status: {status}")
    print(f"   {message}")
    print(f"{'='*70}\n")

    return {
        'predicted_usage_gb': predicted_usage_gb,
        'predicted_free_gb': predicted_free_gb,
        'safety_margin_gb': safety_margin_gb,
        'recommended_free_gb': recommended_free_gb,
        'sufficient': sufficient,
        'safe': safe,
        'status': status,
        'message': message
    }

def cleanup_screenshots(dry_run=False):
    """
    Clean up old screenshots (>30 days)

    Returns:
        float: GB freed
    """
    print(f"\n{'='*70}")
    print("SCREENSHOT CLEANUP")
    print(f"{'='*70}")
    print(f"Retention policy: {SCREENSHOTS_RETENTION_DAYS} days")

    screenshots_dir = DB_DIR / "screenshots"
    if not screenshots_dir.exists():
        print("No screenshots directory found")
        return 0.0

    freed_gb = 0.0
    cutoff_date = datetime.now() - timedelta(days=SCREENSHOTS_RETENTION_DAYS)

    # Iterate through camera folders
    for camera_folder in screenshots_dir.iterdir():
        if not camera_folder.is_dir():
            continue

        # Iterate through date folders under each camera
        for date_folder in camera_folder.iterdir():
            if not date_folder.is_dir() or not date_folder.name.isdigit():
                continue

            # Check if date is older than retention period
            try:
                folder_date = datetime.strptime(date_folder.name, "%Y%m%d")
                if folder_date < cutoff_date:
                    size_gb = get_folder_size(date_folder)
                    if dry_run:
                        print(f"[DRY RUN] Would delete {camera_folder.name}/{date_folder.name} ({size_gb:.3f} GB)")
                    else:
                        print(f"🗑️  Deleting {camera_folder.name}/{date_folder.name} ({size_gb:.3f} GB)")
                        shutil.rmtree(date_folder)
                    freed_gb += size_gb
            except ValueError:
                continue

    print(f"Screenshots freed: {freed_gb:.3f} GB")
    print(f"{'='*70}\n")
    return freed_gb

def smart_cleanup(target_free_gb, dry_run=False):
    """
    Intelligently delete old data to free up space

    Retention policies:
    - Raw videos (videos/): Delete when >= 2 days old (unconditional)
    - Processed videos (results/): Delete when > 2 days
    - Screenshots (db/screenshots/): Delete when > 30 days
    - Database (db/detection_data.db): Never delete (permanent storage)
    """
    print(f"\n{'='*70}")
    print("INTELLIGENT CLEANUP v2.1")
    print(f"{'='*70}")
    print(f"Target free space: {target_free_gb:.1f} GB")
    print(f"")
    print(f"Retention Policies:")
    print(f"  Raw videos: >= {RAW_VIDEO_RETENTION_DAYS} days (unconditional deletion)")
    print(f"  Processed videos: > {PROCESSED_VIDEO_RETENTION_DAYS} days")
    print(f"  Screenshots: > {SCREENSHOTS_RETENTION_DAYS} days")
    print(f"  Database: Permanent (never deleted)")
    print(f"{'='*70}\n")

    # Get current space
    current = get_disk_usage(PROJECT_DIR)
    total_freed_gb = 0.0

    # Phase 1: Clean up screenshots (always run, independent of disk space)
    print("Phase 1: Screenshot Cleanup")
    screenshot_freed = cleanup_screenshots(dry_run=dry_run)
    total_freed_gb += screenshot_freed

    # Check if we've met target
    projected_free = current['free_gb'] + total_freed_gb
    if projected_free >= target_free_gb:
        print(f"\n✅ Target reached after screenshot cleanup!")
        print(f"   Projected free space: {projected_free:.1f} GB")
        return total_freed_gb

    # Phase 2: Clean up raw videos (unconditional age-based deletion)
    print("Phase 2: Raw Video Cleanup (Age-Based)")
    print(f"{'='*70}")

    video_folders = get_date_folders(VIDEOS_DIR)
    for date_folder in video_folders:
        date_str = date_folder.name
        age_days = get_date_age_days(date_str)

        # Skip today (currently recording)
        if age_days == 0:
            print(f"⏭  Skipping {date_str} (today - still recording)")
            continue

        # Check each camera subfolder
        for camera_folder in date_folder.iterdir():
            if not camera_folder.is_dir():
                continue

            camera_id = camera_folder.name

            # Decision logic: Delete if >= 2 days old (regardless of processing status)
            # This ensures corrupted/failed videos don't accumulate
            if age_days >= RAW_VIDEO_RETENTION_DAYS:
                size_gb = get_folder_size(camera_folder)
                reason = f">={RAW_VIDEO_RETENTION_DAYS} days old (hardware health)"

                if dry_run:
                    print(f"[DRY RUN] Would delete {date_str}/{camera_id} ({size_gb:.2f} GB) - {reason}")
                else:
                    print(f"🗑️  Deleting {date_str}/{camera_id} ({size_gb:.2f} GB) - {reason}")
                    shutil.rmtree(camera_folder)
                total_freed_gb += size_gb

                # Check if target reached
                projected_free = current['free_gb'] + total_freed_gb
                if projected_free >= target_free_gb:
                    print(f"\n✅ Target reached!")
                    print(f"   Projected free space: {projected_free:.1f} GB")
                    return total_freed_gb
            else:
                print(f"⏭  Keeping {date_str}/{camera_id} (age:{age_days}d, <{RAW_VIDEO_RETENTION_DAYS} days)")

    print(f"{'='*70}\n")

    # Phase 3: Clean up processed videos (simple age-based)
    print("Phase 3: Processed Video Cleanup")
    print(f"{'='*70}")

    result_folders = get_date_folders(RESULTS_DIR)
    for date_folder in result_folders:
        date_str = date_folder.name
        age_days = get_date_age_days(date_str)

        # Delete if older than retention policy
        if age_days > PROCESSED_VIDEO_RETENTION_DAYS:
            size_gb = get_folder_size(date_folder)
            if dry_run:
                print(f"[DRY RUN] Would delete results/{date_str} ({size_gb:.2f} GB)")
            else:
                print(f"🗑️  Deleting results/{date_str} ({size_gb:.2f} GB)")
                shutil.rmtree(date_folder)
            total_freed_gb += size_gb

            # Check if target reached
            projected_free = current['free_gb'] + total_freed_gb
            if projected_free >= target_free_gb:
                print(f"\n✅ Target reached!")
                print(f"   Projected free space: {projected_free:.1f} GB")
                return total_freed_gb
        else:
            print(f"⏭  Keeping results/{date_str} (age:{age_days}d)")

    print(f"{'='*70}\n")

    # Summary
    print(f"\n{'='*70}")
    print(f"CLEANUP SUMMARY")
    print(f"{'='*70}")
    print(f"Total space freed: {total_freed_gb:.2f} GB")
    print(f"  Screenshots: {screenshot_freed:.3f} GB")
    print(f"  Videos: {total_freed_gb - screenshot_freed:.2f} GB")
    print(f"Projected free space: {current['free_gb'] + total_freed_gb:.1f} GB")
    print(f"{'='*70}\n")

    return total_freed_gb

def check_and_cleanup(min_space_gb, auto_cleanup=False, dry_run=False, use_prediction=True):
    """Main check and cleanup logic with intelligent prediction"""
    print(f"\n{'='*70}")
    print("INTELLIGENT DISK SPACE MONITOR v2.0")
    print(f"{'='*70}\n")

    # Get disk usage
    usage = get_disk_usage(PROJECT_DIR)

    print(f"Project Path: {PROJECT_DIR}")
    print(f"Total Space:  {usage['total_gb']:.1f} GB")
    print(f"Used Space:   {usage['used_gb']:.1f} GB ({usage['used_percent']:.1f}%)")
    print(f"Free Space:   {usage['free_gb']:.1f} GB")
    print(f"Minimum Req:  {min_space_gb:.1f} GB")

    # ===== NEW: Intelligent prediction during recording hours =====
    prediction = None
    if use_prediction:
        # Check if recording is active
        recording_status = check_active_recording_processes()
        remaining_hours = get_recording_remaining_hours()

        print(f"\n{'='*70}")
        print("RECORDING STATUS")
        print(f"{'='*70}")
        print(f"Active processes: {recording_status['process_count']}")
        print(f"Remaining hours: {remaining_hours:.1f} hours")

        # Only measure speed if recording is active OR within recording window
        if recording_status['active'] or remaining_hours > 0:
            print(f"Status: {'Recording' if recording_status['active'] else 'Idle (within recording window)'}")

            # Measure disk usage speed
            speed_data = measure_disk_usage_speed(OBSERVATION_SECONDS)

            # Only predict if we detected meaningful usage
            if speed_data['gb_per_hour'] > 0.01:  # More than 10 MB/hour
                prediction = predict_space_needed(
                    speed_data['gb_per_hour'],
                    remaining_hours
                )
            else:
                print(f"\n⚠️  Disk usage rate too low to predict ({speed_data['gb_per_hour']:.4f} GB/hour)")
                print(f"   This is normal if recording hasn't started yet or is idle")
        else:
            print(f"Status: Outside recording window")
            print(f"{'='*70}\n")
    # ================================================================

    # Basic check: current free space
    if usage['free_gb'] >= min_space_gb:
        # Additional check: prediction (if available)
        if prediction and not prediction['safe']:
            print(f"\n⚠️  STATUS: PREDICTIVE WARNING")
            print(f"   Current space is healthy, but prediction shows future shortage")
            print(f"   {prediction['message']}")

            if auto_cleanup:
                print(f"\n🧹 Starting proactive cleanup based on prediction...")
                target_space = prediction['recommended_free_gb']
                freed = smart_cleanup(target_space, dry_run=dry_run)

                if freed > 0:
                    print(f"\n✅ Proactive cleanup successful! Freed {freed:.1f} GB")
                    return 0
                else:
                    print(f"\n⚠️  No files to cleanup (only today + yesterday remain)")
                    return 1
            else:
                print(f"\n💡 Run with --cleanup to proactively free space")
                return 1
        else:
            print(f"\n✅ STATUS: HEALTHY (Free space > {min_space_gb}GB)")
            if prediction:
                print(f"   Prediction: {prediction['status']}")
            return 0

    print(f"\n⚠️  STATUS: LOW DISK SPACE (< {min_space_gb}GB)")

    # Check prediction for critical status
    if prediction and not prediction['sufficient']:
        print(f"\n🚨 CRITICAL: Prediction shows insufficient space!")
        print(f"   {prediction['message']}")
        print(f"   Predicted free at end of day: {prediction['predicted_free_gb']:.1f} GB")

    # Check if we can even store 1 day of videos
    if usage['free_gb'] < ESTIMATED_VIDEO_SIZE_PER_DAY_GB:
        print(f"\n🚨 CRITICAL: Cannot store even 1 day of videos!")
        print(f"   Available: {usage['free_gb']:.1f} GB")
        print(f"   Required:  {ESTIMATED_VIDEO_SIZE_PER_DAY_GB:.1f} GB (estimated per day)")
        print(f"\n❌ ACTION REQUIRED: Manually free up disk space or add more storage")
        return 2  # Critical error

    # Determine target cleanup space
    if prediction and prediction['recommended_free_gb'] > min_space_gb:
        target_space = prediction['recommended_free_gb']
        print(f"\n📊 Using predictive target: {target_space:.1f} GB (vs minimum {min_space_gb:.1f} GB)")
    else:
        target_space = min_space_gb

    # Cleanup if requested
    if auto_cleanup:
        print(f"\n🧹 Starting automatic cleanup...")
        freed = smart_cleanup(target_space, dry_run=dry_run)

        if freed > 0:
            print(f"\n✅ Cleanup successful! Freed {freed:.1f} GB")
            return 0
        else:
            print(f"\n⚠️  No files to cleanup (only today + yesterday remain)")
            return 1
    else:
        print(f"\n💡 Run with --cleanup to automatically free space")
        return 1

def main():
    parser = argparse.ArgumentParser(
        description="Monitor disk space and manage video storage with intelligent prediction"
    )
    parser.add_argument("--check", action="store_true",
                       help="Check disk space only (no cleanup)")
    parser.add_argument("--cleanup", action="store_true",
                       help="Check and cleanup if needed")
    parser.add_argument("--predict", action="store_true",
                       help="Show space predictions (implies --check)")
    parser.add_argument("--min-space", type=float, default=MIN_SPACE_GB,
                       help=f"Minimum required space in GB (default: {MIN_SPACE_GB})")
    parser.add_argument("--dry-run", action="store_true",
                       help="Simulate cleanup without deleting files")
    parser.add_argument("--no-prediction", action="store_true",
                       help="Disable intelligent prediction (use basic check only)")

    args = parser.parse_args()

    # Default to check mode if no flags
    if not args.check and not args.cleanup and not args.predict:
        args.check = True

    # --predict implies --check
    if args.predict:
        args.check = True

    exit_code = check_and_cleanup(
        min_space_gb=args.min_space,
        auto_cleanup=args.cleanup,
        dry_run=args.dry_run,
        use_prediction=not args.no_prediction
    )

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
