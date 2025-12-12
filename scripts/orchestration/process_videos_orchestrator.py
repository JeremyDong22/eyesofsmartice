#!/usr/bin/env python3
"""
Multi-Camera Video Processing Orchestrator with Dynamic GPU Worker Management
Version: 3.1.0
Last Updated: 2025-11-16

Modified 2025-11-16:
- Added date filtering to skip today's videos (process only yesterday and earlier)
- Added database duplicate check to skip already processed videos
- Prevents processing incomplete/currently-recording videos

Purpose: Intelligent GPU-aware orchestration of multi-camera video processing
Uses dynamic worker scaling based on real-time GPU metrics

Major Changes in v3.0.0:
- Dynamic GPU worker management (starts with 1, scales based on metrics)
- Uses pynvml for real-time GPU monitoring (fallback to nvidia-smi)
- Conservative scale-up, aggressive scale-down strategy
- Emergency stop at 80°C temperature threshold
- 60-second cooldown between scaling decisions
- Worker threads self-manage based on dynamic count

Changes in v2.0.0:
- Replaced simple threading with job queue system
- Added GPU temperature/utilization/memory monitoring via nvidia-smi
- Dynamic parallel job limits based on GPU health
- Smart logging system with bi-weekly rotation
- Separate error logs for debugging
- Performance metrics tracking
- Priority-based queue (older videos first)
- Graceful degradation on macOS (no GPU monitoring)

Features:
- Auto-discovery of videos from videos folder
- Groups videos by camera_id (extracted from filename)
- Queue-based processing with GPU-aware concurrency control
- Batch processing (processes multiple segments per camera)
- Progress tracking and detailed logging
- Non-verbose console output (minimal progress bars)

Author: ASEOfSmartICE Team
"""

import os
import subprocess
import threading
import queue
import time
import logging
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Optional, Tuple, Set
import argparse
import re
import sys
import platform

# Try to import pynvml for GPU monitoring
try:
    import pynvml
    PYNVML_AVAILABLE = True
except ImportError:
    PYNVML_AVAILABLE = False
    print("⚠️  Warning: pynvml not installed. Using fallback GPU monitoring.")
    print("   Install with: pip3 install nvidia-ml-py3")


# ============================================================================
# CONFIGURATION
# ============================================================================

SCRIPT_DIR = Path(__file__).parent.resolve()
VIDEOS_DIR = SCRIPT_DIR.parent.parent / "videos"
LOGS_DIR = SCRIPT_DIR.parent.parent / "logs"
DETECTION_SCRIPT = SCRIPT_DIR.parent / "video_processing" / "table_and_region_state_detection.py"
DATABASE_PATH = SCRIPT_DIR.parent.parent / "db" / "detection_data.db"

# GPU monitoring settings
GPU_CHECK_INTERVAL = 30  # Check GPU health every 30 seconds

# Dynamic worker scaling settings (RTX 3060 research-based)
DEFAULT_MIN_WORKERS = 1       # Always start with 1 worker
DEFAULT_MAX_WORKERS = 8       # Maximum workers (conservative for 10 cameras)

# RTX 3060 temperature thresholds (based on research)
TEMP_SCALE_UP_THRESHOLD = 70     # °C - Safe to add workers
TEMP_SCALE_DOWN_THRESHOLD = 75   # °C - Remove workers
TEMP_EMERGENCY_THRESHOLD = 80    # °C - Emergency stop (pause all)

# GPU utilization thresholds
GPU_UTIL_SCALE_UP_THRESHOLD = 70    # % - Safe to add workers
GPU_UTIL_SCALE_DOWN_THRESHOLD = 85  # % - Remove workers

# Memory thresholds
MIN_MEMORY_FREE_GB = 2.0  # Minimum free memory to scale up
SCALE_COOLDOWN_SECONDS = 60  # Wait time between scaling decisions

# Log rotation settings
LOG_RETENTION_DAYS = 14  # Keep 2 weeks of logs


# ============================================================================
# GPU MONITORING
# ============================================================================

class DynamicGPUMonitor:
    """
    Dynamic GPU monitoring and worker scaling for RTX 3060

    Based on research findings:
    - RTX 3060 safe range: 65-80°C
    - Thermal throttling: 83-85°C
    - Start with 1 worker, scale based on metrics

    Uses pynvml (preferred) or falls back to nvidia-smi
    """

    def __init__(self, logger: logging.Logger,
                 min_workers: int = DEFAULT_MIN_WORKERS,
                 max_workers: int = DEFAULT_MAX_WORKERS):
        self.logger = logger
        self.min_workers = min_workers
        self.max_workers = max_workers

        # RTX 3060 thresholds (from research)
        self.TEMP_SCALE_UP_THRESHOLD = TEMP_SCALE_UP_THRESHOLD
        self.TEMP_SCALE_DOWN_THRESHOLD = TEMP_SCALE_DOWN_THRESHOLD
        self.TEMP_EMERGENCY_THRESHOLD = TEMP_EMERGENCY_THRESHOLD

        self.GPU_UTIL_SCALE_UP_THRESHOLD = GPU_UTIL_SCALE_UP_THRESHOLD
        self.GPU_UTIL_SCALE_DOWN_THRESHOLD = GPU_UTIL_SCALE_DOWN_THRESHOLD

        self.MIN_MEMORY_FREE_GB = MIN_MEMORY_FREE_GB
        self.SCALE_COOLDOWN_SECONDS = SCALE_COOLDOWN_SECONDS

        # State tracking
        self.last_scale_time = 0
        self.is_available = False
        self.use_pynvml = False
        self.handle = None

        # Initialize GPU monitoring
        self._initialize()

    def _initialize(self):
        """Initialize GPU monitoring (try pynvml first, fall back to nvidia-smi)"""
        # Try pynvml first
        if PYNVML_AVAILABLE:
            try:
                pynvml.nvmlInit()
                self.handle = pynvml.nvmlDeviceGetHandleByIndex(0)
                self.use_pynvml = True
                self.is_available = True

                # Get GPU name
                name = pynvml.nvmlDeviceGetName(self.handle)
                if isinstance(name, bytes):
                    name = name.decode('utf-8')

                self.logger.info(f"✅ GPU initialized with pynvml: {name}")
                return

            except Exception as e:
                self.logger.warning(f"pynvml initialization failed: {e}")
                self.use_pynvml = False

        # Fall back to nvidia-smi
        try:
            subprocess.run(
                ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
                capture_output=True,
                timeout=5
            )
            self.is_available = True
            self.logger.info("✅ GPU initialized with nvidia-smi (fallback)")

        except (FileNotFoundError, subprocess.TimeoutExpired):
            self.is_available = False
            self.logger.warning("❌ GPU monitoring not available - using default worker count")
            if platform.system() == "Darwin":
                self.logger.info("Running on macOS - GPU monitoring not supported")

    def get_metrics(self) -> Optional[Dict]:
        """Get current GPU metrics"""
        if not self.is_available:
            return None

        # Use pynvml if available
        if self.use_pynvml:
            return self._get_metrics_pynvml()
        else:
            return self._get_metrics_nvidia_smi()

    def _get_metrics_pynvml(self) -> Optional[Dict]:
        """Get metrics using pynvml (preferred)"""
        try:
            # Temperature
            temp = pynvml.nvmlDeviceGetTemperature(
                self.handle,
                pynvml.NVML_TEMPERATURE_GPU
            )

            # Utilization
            util = pynvml.nvmlDeviceGetUtilizationRates(self.handle)

            # Memory
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(self.handle)
            mem_free_gb = mem_info.free / (1024**3)
            mem_total_gb = mem_info.total / (1024**3)

            return {
                'temperature': temp,
                'gpu_utilization': util.gpu,
                'memory_free_gb': mem_free_gb,
                'memory_total_gb': mem_total_gb,
                'memory_used_gb': mem_info.used / (1024**3),
                'memory_percent': (mem_info.used / mem_info.total) * 100,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            self.logger.error(f"Error reading GPU metrics (pynvml): {e}")
            return None

    def _get_metrics_nvidia_smi(self) -> Optional[Dict]:
        """Get metrics using nvidia-smi (fallback)"""
        try:
            # Query multiple metrics in one call
            result = subprocess.run([
                "nvidia-smi",
                "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits"
            ], capture_output=True, text=True, timeout=5)

            if result.returncode != 0:
                return None

            # Parse output (format: "75, 80, 5000, 12000")
            values = [int(x.strip()) for x in result.stdout.strip().split(',')]

            mem_used_mb = values[2]
            mem_total_mb = values[3]
            mem_free_mb = mem_total_mb - mem_used_mb

            return {
                'temperature': values[0],
                'gpu_utilization': values[1],
                'memory_free_gb': mem_free_mb / 1024,
                'memory_total_gb': mem_total_mb / 1024,
                'memory_used_gb': mem_used_mb / 1024,
                'memory_percent': (mem_used_mb / mem_total_mb * 100) if mem_total_mb > 0 else 0,
                'timestamp': datetime.now().isoformat()
            }

        except Exception as e:
            self.logger.error(f"Error reading GPU metrics (nvidia-smi): {e}")
            return None

    def should_scale_up(self, metrics: Dict, current_workers: int) -> bool:
        """Check if conditions allow adding a worker"""
        if not metrics:
            return False

        # Already at max
        if current_workers >= self.max_workers:
            return False

        # Cooldown period
        if time.time() - self.last_scale_time < self.SCALE_COOLDOWN_SECONDS:
            return False

        # All conditions must be met (conservative scaling)
        return (
            metrics['temperature'] < self.TEMP_SCALE_UP_THRESHOLD and
            metrics['gpu_utilization'] < self.GPU_UTIL_SCALE_UP_THRESHOLD and
            metrics['memory_free_gb'] > self.MIN_MEMORY_FREE_GB
        )

    def should_scale_down(self, metrics: Dict, current_workers: int) -> bool:
        """Check if we need to reduce workers"""
        if not metrics:
            return False

        # Already at minimum
        if current_workers <= self.min_workers:
            return False

        # Any condition triggers scale down (aggressive)
        return (
            metrics['temperature'] > self.TEMP_SCALE_DOWN_THRESHOLD or
            metrics['gpu_utilization'] > self.GPU_UTIL_SCALE_DOWN_THRESHOLD or
            metrics['memory_free_gb'] < 1.0
        )

    def is_emergency(self, metrics: Dict) -> bool:
        """Check if emergency stop needed"""
        if not metrics:
            return False

        return metrics['temperature'] >= self.TEMP_EMERGENCY_THRESHOLD

    def record_scaling(self):
        """Record that we just scaled"""
        self.last_scale_time = time.time()

    def log_metrics(self, metrics: Dict):
        """Log GPU metrics to logger"""
        self.logger.info(
            f"GPU: {metrics['temperature']}°C | "
            f"Util: {metrics['gpu_utilization']}% | "
            f"Mem: {metrics['memory_free_gb']:.1f}GB free / "
            f"{metrics['memory_total_gb']:.1f}GB total "
            f"({metrics['memory_percent']:.1f}%)"
        )

    def shutdown(self):
        """Cleanup pynvml"""
        if self.use_pynvml and self.is_available:
            try:
                pynvml.nvmlShutdown()
            except:
                pass


# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logging(log_level: str = "INFO") -> Tuple[logging.Logger, Path]:
    """
    Setup logging system with file and console handlers
    - Bi-weekly rotation (keep last 14 days)
    - Separate error log
    - Non-verbose console output

    Returns: (logger, log_file_path)
    """
    LOGS_DIR.mkdir(exist_ok=True)

    # Cleanup old logs (older than 14 days)
    cleanup_old_logs(LOGS_DIR, LOG_RETENTION_DAYS)

    # Create session log file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOGS_DIR / f"processing_{timestamp}.log"
    error_log_file = LOGS_DIR / f"errors_{datetime.now().strftime('%Y%m%d')}.log"

    # Create logger
    logger = logging.getLogger("VideoOrchestrator")
    logger.setLevel(getattr(logging, log_level.upper()))
    logger.handlers.clear()  # Clear any existing handlers

    # File handler (detailed logs)
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter(
        '%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Error file handler (errors only)
    error_handler = logging.FileHandler(error_log_file, encoding='utf-8')
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(file_formatter)
    logger.addHandler(error_handler)

    # Console handler (minimal output)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    logger.info(f"Logging initialized: {log_file}")
    logger.info(f"Error log: {error_log_file}")

    return logger, log_file


def cleanup_old_logs(logs_dir: Path, retention_days: int):
    """Remove log files older than retention period"""
    cutoff_date = datetime.now() - timedelta(days=retention_days)

    for log_file in logs_dir.glob("*.log"):
        try:
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if mtime < cutoff_date:
                log_file.unlink()
        except Exception:
            pass  # Ignore errors during cleanup


# ============================================================================
# DATABASE DUPLICATE CHECKING
# ============================================================================

def get_processed_videos(logger: logging.Logger) -> Set[str]:
    """
    Get set of already processed video filenames from database

    Modified 2025-12-10: Query 'sessions' table instead of non-existent 'videos' table
    This matches the duplicate check in table_and_region_state_detection.py

    Returns: Set of video filenames that have been processed
    """
    processed_videos = set()

    if not DATABASE_PATH.exists():
        logger.warning(f"Database not found at {DATABASE_PATH}, skipping duplicate check")
        return processed_videos

    try:
        conn = sqlite3.connect(str(DATABASE_PATH))
        cursor = conn.cursor()

        # Modified 2025-12-10: Query sessions table (actual table used by detection script)
        # video_file column contains the filename of processed videos
        cursor.execute("""
            SELECT DISTINCT video_file
            FROM sessions
            WHERE video_file IS NOT NULL
        """)

        for row in cursor.fetchall():
            processed_videos.add(row[0])

        conn.close()
        logger.info(f"Found {len(processed_videos)} already processed videos in database (sessions table)")

    except sqlite3.Error as e:
        logger.error(f"Database error while checking for duplicates: {e}")

    return processed_videos


def extract_date_from_path(video_path: str) -> Optional[str]:
    """
    Extract date from video path structure: videos/YYYYMMDD/camera_id/filename.mp4

    Returns: Date string in YYYYMMDD format, or None if not found
    """
    path = Path(video_path)

    # Try to find YYYYMMDD in path parts
    for part in path.parts:
        if re.match(r'^\d{8}$', part):
            return part

    # Fallback: Try to extract from filename (camera_35_YYYYMMDD_HHMMSS.mp4)
    match = re.search(r'_(\d{8})_', path.name)
    if match:
        return match.group(1)

    return None


# ============================================================================
# VIDEO DISCOVERY
# ============================================================================

def extract_camera_id(video_filename: str) -> Optional[str]:
    """Extract camera_id from filename (e.g., camera_35_20251114.mp4 -> camera_35)"""
    match = re.match(r'^(camera_\d+)', video_filename)
    if match:
        return match.group(1)
    return None


def extract_timestamp(video_filename: str) -> str:
    """Extract timestamp from filename for sorting (camera_35_20251114_183000.mp4 -> 20251114_183000)"""
    match = re.search(r'(\d{8}_\d{6})', video_filename)
    if match:
        return match.group(1)
    return "00000000_000000"  # Default for sorting


def discover_videos(videos_dir: Path, camera_filter: Optional[List[str]] = None,
                   logger: Optional[logging.Logger] = None) -> Dict[str, List[str]]:
    """
    Discover videos in videos directory, filtering by date and checking for duplicates

    Expected structure: videos/YYYYMMDD/camera_id/camera_id_YYYYMMDD_HHMMSS.mp4

    Date filtering:
    - Only includes videos from YESTERDAY and earlier (current_date - 1)
    - Skips TODAY's videos (may still be recording)

    Duplicate checking:
    - Queries database for already processed videos
    - Skips videos that exist in videos table with is_processed = 1

    Returns: dict of {camera_id: [video_paths]} sorted by timestamp (oldest first)
    """
    videos_by_camera = defaultdict(list)

    if not videos_dir.exists():
        return videos_by_camera

    # Get current date and yesterday's date (cutoff for processing)
    today = datetime.now().strftime("%Y%m%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    if logger:
        logger.info(f"Date filter: Processing videos from {yesterday} and earlier (skipping today: {today})")

    # Get already processed videos from database
    processed_videos = get_processed_videos(logger) if logger else set()

    # Counters for logging
    total_found = 0
    skipped_today = 0
    skipped_duplicate = 0
    added = 0

    # Find all mp4 files in date/camera_id structure
    for video_file in videos_dir.rglob("*.mp4"):
        total_found += 1

        camera_id = extract_camera_id(video_file.name)
        if not camera_id:
            continue

        # Filter by camera if specified
        if camera_filter and camera_id not in camera_filter:
            continue

        # Extract date from path (videos/YYYYMMDD/camera_id/...)
        video_date = extract_date_from_path(str(video_file))

        # Skip today's videos (may still be recording)
        if video_date == today:
            skipped_today += 1
            if logger:
                logger.debug(f"Skipping today's video: {video_file.name}")
            continue

        # Skip videos without valid date (shouldn't happen with proper structure)
        if not video_date:
            if logger:
                logger.warning(f"Could not extract date from: {video_file}")
            continue

        # Check if already processed in database
        if video_file.name in processed_videos:
            skipped_duplicate += 1
            if logger:
                logger.debug(f"Skipping already processed: {video_file.name}")
            continue

        # Add to processing list
        videos_by_camera[camera_id].append(str(video_file))
        added += 1

    # Sort videos by timestamp within each camera (oldest first for priority queue)
    for camera_id in videos_by_camera:
        videos_by_camera[camera_id].sort(key=lambda v: extract_timestamp(os.path.basename(v)))

    # Log summary
    if logger:
        logger.info(f"Video discovery summary:")
        logger.info(f"  Total videos found: {total_found}")
        logger.info(f"  Skipped (today): {skipped_today}")
        logger.info(f"  Skipped (already processed): {skipped_duplicate}")
        logger.info(f"  Added to queue: {added}")
        logger.info(f"  Cameras: {len(videos_by_camera)}")

    return dict(videos_by_camera)


# ============================================================================
# JOB QUEUE SYSTEM
# ============================================================================

class ProcessingJob:
    """Represents a single video processing job"""

    def __init__(self, camera_id: str, video_path: str, priority: int,
                 duration: Optional[int] = None, config_path: Optional[str] = None):
        self.camera_id = camera_id
        self.video_path = video_path
        self.priority = priority  # Lower number = higher priority (older videos)
        self.duration = duration
        self.config_path = config_path
        self.video_name = os.path.basename(video_path)

    def __lt__(self, other):
        """Compare by priority for queue ordering"""
        return self.priority < other.priority


class ProcessingQueue:
    """
    GPU-aware processing queue with dynamic worker scaling

    Starts with 1 worker, scales up/down based on GPU metrics
    """

    def __init__(self, logger: logging.Logger, gpu_monitor: DynamicGPUMonitor,
                 max_workers: int = DEFAULT_MAX_WORKERS):
        self.logger = logger
        self.gpu_monitor = gpu_monitor
        self.max_workers = max_workers
        self.min_workers = gpu_monitor.min_workers

        # Dynamic worker management
        self.current_worker_count = 0
        self.worker_threads = []
        self.worker_lock = threading.Lock()
        self.stop_event = threading.Event()

        # Job queue (priority queue - older videos first)
        self.job_queue = queue.PriorityQueue()

        # Active jobs tracking (for monitoring)
        self.active_jobs = {}
        self.active_jobs_lock = threading.Lock()

        # Statistics
        self.jobs_completed = 0
        self.jobs_failed = 0
        self.total_processing_time = 0
        self.start_time = None

        # GPU monitoring thread
        self.gpu_monitoring_thread = None

    def add_job(self, job: ProcessingJob):
        """Add a job to the queue"""
        self.job_queue.put(job)

    def get_queue_status(self) -> Dict:
        """Get current queue status"""
        with self.active_jobs_lock:
            active_count = len(self.active_jobs)

        return {
            'jobs_waiting': self.job_queue.qsize(),
            'jobs_running': active_count,
            'jobs_completed': self.jobs_completed,
            'jobs_failed': self.jobs_failed,
            'current_workers': self.current_worker_count,
            'max_workers': self.max_workers
        }

    def _add_worker(self):
        """Add a new worker thread"""
        with self.worker_lock:
            worker_id = self.current_worker_count
            thread = threading.Thread(
                target=self._worker_thread,
                args=(worker_id,),
                daemon=True,
                name=f"Worker-{worker_id}"
            )
            thread.start()
            self.worker_threads.append(thread)
            self.current_worker_count += 1
            self.gpu_monitor.record_scaling()
            self.logger.info(f"➕ Added worker {worker_id}, total: {self.current_worker_count}")

    def _remove_worker(self):
        """Signal one worker to stop (it will finish current job)"""
        with self.worker_lock:
            if self.current_worker_count > self.min_workers:
                self.current_worker_count -= 1
                self.gpu_monitor.record_scaling()
                self.logger.info(f"➖ Reduced workers to {self.current_worker_count}")

    def process_job(self, job: ProcessingJob) -> bool:
        """
        Process a single job
        Returns: True if successful, False if failed
        """
        worker_id = threading.get_ident()

        # Register job
        with self.active_jobs_lock:
            self.active_jobs[worker_id] = job

        try:
            self.logger.info(f"[{job.camera_id}] START: {job.video_name}")

            # Build command
            cmd = [
                "python3",
                str(DETECTION_SCRIPT),
                "--video", job.video_path
            ]

            if job.duration:
                cmd.extend(["--duration", str(job.duration)])

            if job.config_path:
                # Check for camera-specific config
                camera_config = Path(job.config_path).parent / f"table_region_config_{job.camera_id}.json"
                if camera_config.exists():
                    self.logger.debug(f"[{job.camera_id}] Using camera-specific config: {camera_config.name}")
                else:
                    self.logger.debug(f"[{job.camera_id}] Using default config: {Path(job.config_path).name}")

            # Execute
            start_time = time.time()
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=None  # No timeout for long videos
            )
            elapsed = time.time() - start_time

            # Log result
            if result.returncode == 0:
                self.logger.info(
                    f"[{job.camera_id}] SUCCESS: {job.video_name} | "
                    f"Duration: {elapsed:.1f}s"
                )
                self.jobs_completed += 1
                self.total_processing_time += elapsed
                return True
            else:
                self.logger.error(
                    f"[{job.camera_id}] FAILED: {job.video_name} | "
                    f"Duration: {elapsed:.1f}s"
                )
                self.logger.error(f"[{job.camera_id}] Error output: {result.stderr}")
                self.jobs_failed += 1
                return False

        except Exception as e:
            self.logger.error(f"[{job.camera_id}] EXCEPTION: {job.video_name} | {e}")
            self.jobs_failed += 1
            return False

        finally:
            # Unregister job
            with self.active_jobs_lock:
                self.active_jobs.pop(worker_id, None)

    def _worker_thread(self, worker_id: int):
        """Worker thread that processes jobs from queue"""
        self.logger.info(f"[Worker {worker_id}] Started")

        while not self.stop_event.is_set():
            try:
                # Check if this worker should exit (over limit)
                if worker_id >= self.current_worker_count:
                    self.logger.info(f"[Worker {worker_id}] Exiting (over limit)")
                    break

                # Get next job (with timeout to check shutdown flag)
                try:
                    job = self.job_queue.get(timeout=5)
                except queue.Empty:
                    continue

                # Check again if we should still be running
                if worker_id >= self.current_worker_count:
                    # Put job back
                    self.job_queue.put(job)
                    self.logger.info(f"[Worker {worker_id}] Exiting (over limit)")
                    break

                # Process job
                self.process_job(job)
                self.job_queue.task_done()

            except Exception as e:
                self.logger.error(f"[Worker {worker_id}] Error: {e}")

        self.logger.info(f"[Worker {worker_id}] Stopped")

    def _gpu_monitoring_thread(self):
        """Monitor GPU and adjust worker count dynamically"""
        self.logger.info("GPU monitoring thread started")

        while not self.stop_event.is_set():
            try:
                # Get metrics
                metrics = self.gpu_monitor.get_metrics()

                if metrics:
                    # Log current state
                    self.gpu_monitor.log_metrics(metrics)

                    # Log queue status
                    status = self.get_queue_status()
                    self.logger.info(
                        f"Queue: {status['jobs_running']} running | "
                        f"{status['jobs_waiting']} waiting | "
                        f"{status['jobs_completed']} completed | "
                        f"{status['jobs_failed']} failed | "
                        f"Workers: {status['current_workers']}/{status['max_workers']}"
                    )

                    # Emergency check
                    if self.gpu_monitor.is_emergency(metrics):
                        self.logger.error(
                            f"🚨 EMERGENCY: GPU temperature {metrics['temperature']}°C! "
                            f"Reducing to minimum workers..."
                        )
                        # Reduce to minimum
                        while self.current_worker_count > self.min_workers:
                            self._remove_worker()
                        # Wait 2 minutes for cooldown
                        self.logger.info("Waiting 120 seconds for GPU cooldown...")
                        time.sleep(120)
                        continue

                    # Scale down check (aggressive)
                    if self.gpu_monitor.should_scale_down(metrics, self.current_worker_count):
                        self.logger.warning(
                            f"⚠️  Scaling DOWN: Temp={metrics['temperature']}°C, "
                            f"Util={metrics['gpu_utilization']}%, "
                            f"Free Mem={metrics['memory_free_gb']:.1f}GB"
                        )
                        self._remove_worker()

                    # Scale up check (conservative)
                    elif self.gpu_monitor.should_scale_up(metrics, self.current_worker_count):
                        self.logger.info(
                            f"✅ Scaling UP: Conditions favorable "
                            f"(Temp={metrics['temperature']}°C, "
                            f"Util={metrics['gpu_utilization']}%, "
                            f"Free Mem={metrics['memory_free_gb']:.1f}GB)"
                        )
                        self._add_worker()

                # Wait 30 seconds before next check
                time.sleep(GPU_CHECK_INTERVAL)

            except Exception as e:
                self.logger.error(f"GPU monitoring error: {e}")
                time.sleep(GPU_CHECK_INTERVAL)

        self.logger.info("GPU monitoring thread stopped")

    def start_workers(self, initial_workers: int = 1):
        """Start initial worker threads and GPU monitoring"""
        self.start_time = time.time()
        self.logger.info(f"Starting with {initial_workers} worker thread(s)")

        # Start initial workers
        for i in range(initial_workers):
            self._add_worker()

        # Start GPU monitoring thread
        self.gpu_monitoring_thread = threading.Thread(
            target=self._gpu_monitoring_thread,
            name="GPU-Monitor",
            daemon=True
        )
        self.gpu_monitoring_thread.start()

        return self.worker_threads

    def wait_for_completion(self):
        """Wait for all jobs to complete"""
        self.job_queue.join()
        self.stop_event.set()

        # Wait for GPU monitoring thread to stop
        if self.gpu_monitoring_thread and self.gpu_monitoring_thread.is_alive():
            self.gpu_monitoring_thread.join(timeout=5)

    def get_statistics(self) -> Dict:
        """Get final processing statistics"""
        total_time = time.time() - self.start_time if self.start_time else 0
        total_jobs = self.jobs_completed + self.jobs_failed

        return {
            'total_jobs': total_jobs,
            'jobs_completed': self.jobs_completed,
            'jobs_failed': self.jobs_failed,
            'total_time': total_time,
            'avg_time_per_job': self.total_processing_time / self.jobs_completed if self.jobs_completed > 0 else 0,
            'success_rate': (self.jobs_completed / total_jobs * 100) if total_jobs > 0 else 0
        }




# ============================================================================
# MAIN PROCESSING ORCHESTRATOR
# ============================================================================

def process_with_queue(videos_by_camera: Dict[str, List[str]], logger: logging.Logger,
                      duration: Optional[int] = None, config_path: Optional[str] = None,
                      max_workers: int = DEFAULT_MAX_WORKERS,
                      min_workers: int = DEFAULT_MIN_WORKERS):
    """
    Process videos using dynamic GPU-aware worker scaling
    """
    if not videos_by_camera:
        logger.error("No videos to process")
        return

    # Initialize GPU monitor
    gpu_monitor = DynamicGPUMonitor(logger, min_workers, max_workers)

    # Initialize processing queue
    processing_queue = ProcessingQueue(logger, gpu_monitor, max_workers)

    # Create jobs (priority = timestamp, older videos first)
    total_jobs = 0
    for camera_id, video_paths in videos_by_camera.items():
        for video_path in video_paths:
            timestamp = extract_timestamp(os.path.basename(video_path))
            priority = int(timestamp.replace('_', ''))  # Convert to int for priority

            job = ProcessingJob(camera_id, video_path, priority, duration, config_path)
            processing_queue.add_job(job)
            total_jobs += 1

    logger.info("="*80)
    logger.info("MULTI-CAMERA VIDEO PROCESSING WITH DYNAMIC GPU WORKER SCALING")
    logger.info("="*80)
    logger.info(f"Cameras: {len(videos_by_camera)}")
    logger.info(f"Total jobs: {total_jobs}")
    logger.info(f"Worker range: {min_workers} - {max_workers} (starts with {min_workers})")
    logger.info(f"GPU thresholds: Scale-up <{TEMP_SCALE_UP_THRESHOLD}°C, Scale-down >{TEMP_SCALE_DOWN_THRESHOLD}°C, Emergency >={TEMP_EMERGENCY_THRESHOLD}°C")
    if duration:
        logger.info(f"Processing duration: {duration}s per video")
    logger.info("="*80)

    # Show job details
    for camera_id, video_paths in videos_by_camera.items():
        logger.info(f"{camera_id}: {len(video_paths)} video(s)")
        for video_path in video_paths:
            logger.debug(f"   - {os.path.basename(video_path)}")

    logger.info("="*80)
    logger.info("Starting processing...")
    logger.info("="*80)

    # Start worker threads (includes GPU monitoring)
    worker_threads = processing_queue.start_workers(initial_workers=min_workers)

    # Wait for all jobs to complete
    processing_queue.wait_for_completion()

    # Get statistics
    stats = processing_queue.get_statistics()

    logger.info("="*80)
    logger.info("PROCESSING COMPLETE")
    logger.info("="*80)
    logger.info(f"Total jobs: {stats['total_jobs']}")
    logger.info(f"Completed: {stats['jobs_completed']}")
    logger.info(f"Failed: {stats['jobs_failed']}")
    logger.info(f"Success rate: {stats['success_rate']:.1f}%")
    logger.info(f"Total time: {stats['total_time']:.1f}s ({stats['total_time']/60:.1f} minutes)")
    logger.info(f"Avg time per job: {stats['avg_time_per_job']:.1f}s")
    logger.info("="*80)

    # Log final GPU metrics
    final_metrics = gpu_monitor.get_metrics()
    if final_metrics:
        logger.info("Final GPU state:")
        gpu_monitor.log_metrics(final_metrics)

    # Cleanup GPU monitor
    gpu_monitor.shutdown()


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Orchestrate GPU-aware parallel processing of multi-camera videos",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process all videos with GPU queue management (default)
  python3 process_videos_orchestrator.py

  # Process only specific cameras
  python3 process_videos_orchestrator.py --cameras camera_35 camera_22

  # Process first 60 seconds of each video (for testing)
  python3 process_videos_orchestrator.py --duration 60

  # Custom worker limits (default: 1-8 workers)
  python3 process_videos_orchestrator.py --min-workers 2 --max-workers 6

  # Enable debug logging
  python3 process_videos_orchestrator.py --log-level DEBUG

Workflow:
1. Script scans videos/ folder for all .mp4 files
2. Filters videos by date (only YESTERDAY and earlier, skips TODAY)
3. Checks database for already processed videos (skips duplicates)
4. Groups videos by camera_id (extracted from filename)
5. Creates priority queue (older videos first)
6. Starts with 1 worker thread
7. GPU monitoring thread checks metrics every 30s
8. Dynamically scales workers based on real-time GPU health:
   - Scale UP if: temp <70°C AND util <70% AND mem >2GB (conservative)
   - Scale DOWN if: temp >75°C OR util >85% OR mem <1GB (aggressive)
   - Emergency stop: temp >=80°C (reduce to minimum, wait 2 mins)
   - Cooldown: 60 seconds between scaling decisions
9. Logs all events to logs/processing_YYYYMMDD_HHMMSS.log
10. Generates statistics report at completion

Date Filtering (v3.1.0):
- Only processes videos from YESTERDAY (current_date - 1) and earlier
- Skips TODAY's videos to avoid processing incomplete/recording files
- Extracts date from folder structure: videos/YYYYMMDD/camera_id/
- Prevents errors from processing 18GB+ incomplete videos

Duplicate Prevention (v3.1.0):
- Queries local database (db/detection_data.db)
- Checks videos table for is_processed = 1
- Skips videos already successfully processed
- Prevents wasted GPU cycles on re-processing

Video Naming Convention:
  camera_{id}_{date}_{time}.mp4
  Example: camera_35_20251114_183000.mp4

Log Files:
  - logs/processing_YYYYMMDD_HHMMSS.log (main log)
  - logs/errors_YYYYMMDD.log (errors only)
  - Bi-weekly rotation (keeps last 14 days)
        """
    )

    parser.add_argument("--videos-dir", default=str(VIDEOS_DIR),
                       help=f"Videos directory (default: {VIDEOS_DIR})")
    parser.add_argument("--cameras", nargs='+',
                       help="Process only specific camera IDs (e.g., camera_35 camera_22)")
    parser.add_argument("--duration", type=int,
                       help="Process only first N seconds of each video (for testing)")
    parser.add_argument("--config", default=str(SCRIPT_DIR.parent / "config" / "table_region_config.json"),
                       help="Path to ROI config file")
    parser.add_argument("--list", action="store_true",
                       help="List all discovered videos and exit")
    parser.add_argument("--max-workers", type=int, default=DEFAULT_MAX_WORKERS,
                       help=f"Maximum worker threads (default: {DEFAULT_MAX_WORKERS})")
    parser.add_argument("--min-workers", type=int, default=DEFAULT_MIN_WORKERS,
                       help=f"Minimum worker threads (default: {DEFAULT_MIN_WORKERS})")
    parser.add_argument("--log-level", default="INFO",
                       choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                       help="Logging level (default: INFO)")

    args = parser.parse_args()

    # Setup logging
    logger, log_file = setup_logging(args.log_level)

    logger.info(f"Python version: {sys.version}")
    logger.info(f"Platform: {platform.system()} {platform.release()}")
    logger.info(f"Script directory: {SCRIPT_DIR}")

    videos_dir = Path(args.videos_dir)
    config_path = args.config

    # Discover videos (with date filtering and duplicate checking)
    logger.info(f"Scanning for videos in: {videos_dir}")
    videos_by_camera = discover_videos(videos_dir, args.cameras, logger)

    if not videos_by_camera:
        logger.error("No videos found")
        return

    # List mode
    if args.list:
        print(f"\n📹 Discovered Videos:")
        for camera_id, video_paths in videos_by_camera.items():
            print(f"\n{camera_id}: {len(video_paths)} video(s)")
            for video_path in video_paths:
                video_name = os.path.basename(video_path)
                timestamp = extract_timestamp(video_name)
                print(f"   {timestamp} - {video_name}")
        print()
        return

    # Process with queue
    start_time = datetime.now()
    logger.info(f"Session start: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

    process_with_queue(
        videos_by_camera,
        logger,
        args.duration,
        config_path,
        args.max_workers,
        args.min_workers
    )

    end_time = datetime.now()
    total_duration = (end_time - start_time).total_seconds()

    logger.info(f"Session end: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Total session time: {total_duration:.1f}s ({total_duration/60:.1f} minutes)")
    logger.info(f"Log file: {log_file}")


if __name__ == "__main__":
    main()
