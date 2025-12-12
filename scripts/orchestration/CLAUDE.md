# Orchestration System Documentation

**Version:** 3.1.0
**Last Updated:** 2025-12-13
**Directory:** `/scripts/orchestration/`

本文档详细说明 ASE 监控系统的任务编排架构，包括动态 GPU 工作器扩缩容、优先级队列系统、以及自动化服务守护进程。

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Dynamic GPU Worker Scaling](#dynamic-gpu-worker-scaling)
3. [Priority Queue System](#priority-queue-system)
4. [Surveillance Service Daemon](#surveillance-service-daemon)
5. [Time-Based Scheduling](#time-based-scheduling)
6. [Process Lifecycle Management](#process-lifecycle-management)
7. [Configuration Parameters](#configuration-parameters)
8. [Usage Examples](#usage-examples)

---

## Architecture Overview

### System Components

```
┌─────────────────────────────────────────────────────────────────┐
│                   Surveillance Service Daemon                   │
│                    (surveillance_service.py)                    │
│                                                                 │
│  Main Thread: Service Controller & Scheduler (30s loop)        │
│    ├─ Zombie Process Cleanup (every iteration)                 │
│    ├─ Capture Window Detection (dual windows)                  │
│    ├─ Processing Window Detection (midnight trigger)           │
│    └─ Graceful Process Termination (30s SIGTERM + 5s SIGKILL)  │
│                                                                 │
│  Background Threads:                                            │
│    ├─ Thread 1: Video Capture (11:30-14:00, 17:30-22:00)      │
│    ├─ Thread 2: Video Processing (00:00-23:00)                │
│    ├─ Thread 3: Disk Monitoring (hourly)                      │
│    ├─ Thread 4: GPU Monitoring (5 min)                        │
│    └─ Thread 5: Database Sync (hourly)                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│              Video Processing Orchestrator                      │
│              (process_videos_orchestrator.py)                   │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Video Discovery & Filtering                 │  │
│  │                                                          │  │
│  │  1. Scan videos/YYYYMMDD/camera_id/*.mp4               │  │
│  │  2. Filter: Skip TODAY (only yesterday and earlier)    │  │
│  │  3. Check database: Skip already processed videos      │  │
│  │  4. Group by camera_id                                 │  │
│  │  5. Sort by timestamp (oldest first)                   │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              ↓                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Priority Queue System                       │  │
│  │                                                          │  │
│  │  Jobs: [ProcessingJob1, ProcessingJob2, ...]           │  │
│  │  Priority: timestamp (20251114_183000 → int)           │  │
│  │  Queue Type: PriorityQueue (older videos first)        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              ↓                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │          Dynamic GPU Worker Pool (1-8 workers)          │  │
│  │                                                          │  │
│  │  Worker-0  ────┐                                        │  │
│  │  Worker-1  ────┤  Process videos in parallel           │  │
│  │  Worker-2  ────┤  (dynamically scaled)                 │  │
│  │  ...       ────┘                                        │  │
│  └──────────────────────────────────────────────────────────┘  │
│                              ↓                                  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │       GPU Monitoring Thread (30s interval)              │  │
│  │                                                          │  │
│  │  1. Get metrics (pynvml or nvidia-smi)                 │  │
│  │  2. Check emergency conditions (≥80°C)                 │  │
│  │  3. Check scale-down conditions (>75°C, >85% util)     │  │
│  │  4. Check scale-up conditions (<70°C, <70% util)       │  │
│  │  5. Adjust worker count (60s cooldown)                 │  │
│  └──────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### File Structure

| File | Lines | Purpose |
|------|-------|---------|
| `surveillance_service.py` | 743 | 自动化服务守护进程 - 主调度器 |
| `process_videos_orchestrator.py` | 1107 | GPU 感知的视频处理编排器 |

---

## Dynamic GPU Worker Scaling

### 核心算法 (Conservative Scale-Up, Aggressive Scale-Down)

系统采用**保守扩容、激进缩容**策略，确保 GPU 安全运行。

#### GPU Metrics Collection

```python
class DynamicGPUMonitor:
    """
    实时监控 GPU 指标，基于 RTX 3060 研究结果设计

    数据源优先级:
    1. pynvml (首选) - 更快、更准确
    2. nvidia-smi (备选) - 兼容性更好
    """

    def get_metrics(self) -> Dict:
        return {
            'temperature': 75,        # °C - GPU 温度
            'gpu_utilization': 71,    # % - GPU 使用率
            'memory_free_gb': 8.2,    # GB - 可用显存
            'memory_total_gb': 12.0,  # GB - 总显存
            'memory_percent': 31.7    # % - 显存使用率
        }
```

#### Scaling Decision Tree

```
┌─────────────────────────────────────────────────────────────┐
│               GPU Monitoring Loop (30s interval)            │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Emergency Check (Highest Priority)                │
│                                                             │
│  IF temp >= 80°C:                                          │
│    → 🚨 EMERGENCY STOP                                     │
│    → Reduce to MIN workers (1)                             │
│    → Sleep 120 seconds (cooldown)                          │
│    → Skip all other checks                                 │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 2: Scale-Down Check (Aggressive)                     │
│                                                             │
│  IF any condition is true:                                 │
│    - temp > 75°C          (temperature threshold)          │
│    - gpu_util > 85%       (utilization threshold)          │
│    - mem_free < 1.0 GB    (memory threshold)               │
│                                                             │
│  AND current_workers > MIN_WORKERS                         │
│  AND time_since_last_scale > 60s                           │
│                                                             │
│  THEN:                                                      │
│    → ⚠️  Scale DOWN (remove 1 worker)                     │
│    → Record scaling time                                   │
│    → Log: "Scaling DOWN"                                   │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│  Step 3: Scale-Up Check (Conservative)                     │
│                                                             │
│  IF all conditions are true:                               │
│    - temp < 70°C          (safe temperature)               │
│    - gpu_util < 70%       (low utilization)                │
│    - mem_free > 2.0 GB    (sufficient memory)              │
│                                                             │
│  AND current_workers < MAX_WORKERS                         │
│  AND time_since_last_scale > 60s                           │
│                                                             │
│  THEN:                                                      │
│    → ✅ Scale UP (add 1 worker)                           │
│    → Record scaling time                                   │
│    → Log: "Scaling UP"                                     │
└─────────────────────────────────────────────────────────────┘
                          ↓
                    Wait 30 seconds
                          ↓
                    Loop continues...
```

#### Thresholds (RTX 3060 Optimized)

| Metric | Scale-Up | Scale-Down | Emergency |
|--------|----------|------------|-----------|
| **Temperature** | < 70°C | > 75°C | ≥ 80°C |
| **GPU Utilization** | < 70% | > 85% | - |
| **Free Memory** | > 2.0 GB | < 1.0 GB | - |
| **Cooldown Period** | 60 seconds | 60 seconds | - |

**研究基础:**
- RTX 3060 安全温度范围: 65-80°C
- 热节流温度: 83-85°C
- 保守扩容确保不会超过安全温度上限

#### Worker Thread Lifecycle

```python
def _worker_thread(self, worker_id: int):
    """
    工作线程生命周期

    1. 启动: logger.info(f"[Worker {worker_id}] Started")
    2. 循环: 从队列获取任务 (5s timeout)
    3. 检查: 是否超过当前 worker_count 限制
    4. 处理: 执行视频处理任务
    5. 退出: worker_id >= current_worker_count 时自动退出
    """

    while not self.stop_event.is_set():
        # Check if should exit (over worker limit)
        if worker_id >= self.current_worker_count:
            self.logger.info(f"[Worker {worker_id}] Exiting (over limit)")
            break

        # Get next job (5s timeout)
        try:
            job = self.job_queue.get(timeout=5)
        except queue.Empty:
            continue

        # Double-check still should be running
        if worker_id >= self.current_worker_count:
            self.job_queue.put(job)  # Put job back
            break

        # Process job
        self.process_job(job)
        self.job_queue.task_done()
```

**关键设计:**
- Worker ID 永久分配 (0, 1, 2, ...)
- Worker 自我管理: 检查 `worker_id >= current_worker_count`
- 缩容不杀线程: 线程自然退出 (完成当前任务后)
- 扩容不重启: 直接添加新线程

---

## Priority Queue System

### Queue Architecture

```python
class ProcessingJob:
    """
    单个视频处理任务

    Attributes:
        camera_id: 摄像头ID (camera_35)
        video_path: 视频文件路径
        priority: 优先级 (timestamp 转整数, 越小越优先)
        duration: 处理时长限制 (可选)
        config_path: ROI 配置文件路径
    """

    def __lt__(self, other):
        # PriorityQueue 使用此方法排序
        return self.priority < other.priority
```

### Priority Calculation

```python
# 示例: camera_35_20251114_183000.mp4
timestamp = extract_timestamp(video_filename)
# → "20251114_183000"

priority = int(timestamp.replace('_', ''))
# → 20251114183000 (整数)

# PriorityQueue 自动按此优先级排序
# 20251114183000 < 20251114190000
# → 较早的视频优先处理
```

### Video Discovery & Filtering

#### Phase 1: File System Scan

```python
def discover_videos(videos_dir: Path) -> Dict[str, List[str]]:
    """
    扫描视频目录，应用过滤规则

    目录结构:
        videos/
        ├── 20251213/          # 今天 (TODAY) - 跳过
        │   ├── camera_35/
        │   │   └── camera_35_20251213_113000.mp4  [SKIP]
        │   └── camera_22/
        │       └── camera_22_20251213_113000.mp4  [SKIP]
        ├── 20251212/          # 昨天 (YESTERDAY) - 处理
        │   └── camera_35/
        │       └── camera_35_20251212_113000.mp4  [PROCESS]
        └── 20251211/          # 前天 - 处理
            └── camera_35/
                └── camera_35_20251211_113000.mp4  [PROCESS]
    """
```

#### Phase 2: Date Filtering (Skip Today)

```
today = datetime.now().strftime("%Y%m%d")      # "20251213"
yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")  # "20251212"

IF video_date == today:
    → SKIP (may still be recording, incomplete)
    → Counter: skipped_today += 1

IF video_date <= yesterday:
    → INCLUDE (complete video, safe to process)
    → Continue to duplicate check
```

**原理:**
- 录制进程在今天持续写入视频文件
- 处理正在录制的视频会导致:
  - FFmpeg 错误: "moov atom not found"
  - 文件不完整
  - 数据库状态不正确

#### Phase 3: Duplicate Check (Database Query)

```sql
-- 查询已处理的视频
SELECT DISTINCT video_file
FROM sessions
WHERE video_file IS NOT NULL
```

```python
if video_file.name in processed_videos:
    → SKIP (already in database)
    → Counter: skipped_duplicate += 1

if video_file.name not in processed_videos:
    → INCLUDE (needs processing)
    → Counter: added += 1
```

#### Discovery Summary Log

```
Video discovery summary:
  Total videos found: 150
  Skipped (today): 20           # 今天的视频 (正在录制)
  Skipped (already processed): 100  # 已处理的视频
  Added to queue: 30            # 待处理的视频
  Cameras: 2
```

### Deduplication Strategy

```
┌────────────────────────────────────────────────────────────┐
│  Deduplication Prevents:                                   │
│                                                            │
│  1. Wasted GPU Cycles - 不重复处理已完成的视频                │
│  2. Database Conflicts - 避免重复记录                        │
│  3. Storage Waste - 避免重复生成 results 文件                 │
│  4. Incorrect Statistics - 保证统计数据准确性                 │
└────────────────────────────────────────────────────────────┘
```

---

## Surveillance Service Daemon

### Service Architecture

```python
class SurveillanceService:
    """
    自动化监控服务守护进程
    Version: 2.4.0

    核心职责:
    1. 时间窗口调度 (双时段录制, 午夜处理)
    2. 进程生命周期管理 (启动/停止/监控)
    3. 系统健康监控 (磁盘/GPU/数据库)
    4. 僵尸进程清理 (v2.4.0 新增)
    """
```

### Main Scheduler Loop (30s Cycle)

```python
def scheduler_loop(self):
    """
    主调度循环 - 每 30 秒执行一次

    执行顺序 (Critical Order):
    1. 清理僵尸进程 (v2.4.0)
    2. 检查是否需要停止录制 (在启动新录制之前)
    3. 检查是否需要启动录制 (精确分钟匹配)
    4. 检查是否需要启动处理 (午夜触发)
    5. 检查处理是否超时 (11 PM 警告)
    """

    while self.running:
        # Step 1: Cleanup zombies (v2.4.0)
        self._cleanup_zombies()

        # Step 2: Stop capture if outside window
        if self.capture_process and self.capture_process.poll() is None:
            in_window, active_window = self.is_in_capture_window()
            if not in_window:
                self._stop_capture_process()

        # Step 3: Start capture if in window
        for window in CAPTURE_WINDOWS:
            if current_time == window_start_time:
                self.start_video_capture()

        # Step 4: Start processing at midnight
        if current_hour == 0 and current_minute == 0:
            self.start_video_processing()

        # Step 5: Check processing timeout (11 PM)
        if current_hour == 23 and current_minute == 0:
            if self.processing_process.poll() is None:
                self.logger.warning("Processing still running after 11 PM!")

        time.sleep(30)  # Wait 30 seconds
```

### Zombie Process Cleanup (v2.4.0)

```python
def _cleanup_zombies(self):
    """
    清理僵尸 (defunct) 子进程

    何时产生僵尸进程:
    - 子进程退出但父进程未调用 wait()
    - 进程表中残留 <defunct> 状态

    清理方式:
    - os.waitpid(-1, os.WNOHANG) 非阻塞回收
    - 每次调度循环执行 (30 秒一次)

    Log 示例:
    🧹 Reaped zombie process PID 12345 (exit code: 0)
    🧹 Cleaned up 3 zombie process(es)
    """

    cleaned = 0
    while True:
        pid, status = os.waitpid(-1, os.WNOHANG)
        if pid == 0:  # No more zombies
            break
        cleaned += 1
        self.logger.debug(f"🧹 Reaped zombie PID {pid}")

    if cleaned > 0:
        self.logger.info(f"🧹 Cleaned up {cleaned} zombie process(es)")
```

### Process Termination Strategy

#### Graceful Shutdown with Fallback (v2.3.0)

```python
def _stop_capture_process(self, timeout=30):
    """
    优雅停止录制进程 (30s SIGTERM + 5s SIGKILL)

    v2.3.0 修改: 超时从 10s → 30s
    原因: FFmpeg 需要时间写入 MP4 文件元数据 (moov atom)

    步骤:
    1. SIGTERM (优雅关闭信号)
       └─ 等待 30 秒
    2. SIGKILL (强制杀死信号)
       └─ 等待 5 秒
    3. 总保证时间: 35 秒内停止
    """

    # Step 1: SIGTERM (graceful)
    self.capture_process.terminate()
    try:
        self.capture_process.wait(timeout=30)  # Increased from 10s
        self.logger.info("✅ Stopped gracefully via SIGTERM")
        return True
    except subprocess.TimeoutExpired:
        self.logger.warning("⚠️  SIGTERM timeout, force killing...")

    # Step 2: SIGKILL (force)
    self.capture_process.kill()
    self.capture_process.wait(timeout=5)
    self.logger.info("✅ Force killed with SIGKILL")
```

**Critical Fix Timeline:**
- **v2.0.0 (2025-11-16):** 原始实现 - 仅 `terminate()` 无等待
- **v2.2.0 (2025-11-19):** 添加 10s 超时 + SIGKILL 备用
- **v2.3.0 (2025-11-22):** 超时增加到 30s (修复 MP4 损坏)
- **v2.4.0 (2025-12-12):** 添加僵尸进程清理

**为什么需要 30 秒:**
- FFmpeg 使用 fragment MP4 格式
- 需要在文件末尾写入 moov atom (元数据)
- moov atom 包含: 索引、时长、编解码器信息
- 没有 moov atom → 视频无法播放 ("moov atom not found")

---

## Time-Based Scheduling

### Capture Windows (Dual Schedule)

```json
{
  "capture_windows": [
    {
      "name": "lunch",
      "start_hour": 11,
      "start_minute": 30,
      "end_hour": 14,
      "end_minute": 0,
      "description": "午餐时段 11:30 AM - 2:00 PM"
    },
    {
      "name": "dinner",
      "start_hour": 17,
      "start_minute": 30,
      "end_hour": 22,
      "end_minute": 0,
      "description": "晚餐时段 5:30 PM - 10:00 PM"
    }
  ]
}
```

#### Window Detection Algorithm

```python
def is_in_capture_window(self) -> tuple:
    """
    检查当前时间是否在任一录制窗口

    返回: (bool, dict or None)
        - True, window_config: 在窗口内
        - False, None: 在窗口外
    """

    now = datetime.now()
    current_total_minutes = now.hour * 60 + now.minute

    for window in CAPTURE_WINDOWS:
        start_minutes = window["start_hour"] * 60 + window["start_minute"]
        end_minutes = window["end_hour"] * 60 + window["end_minute"]

        # 使用 < (不包含结束时间) 确保精确停止
        if start_minutes <= current_total_minutes < end_minutes:
            return (True, window)

    return (False, None)
```

**关键细节:**
- 使用 `<` 而非 `<=` 检查结束时间
- 14:00:00 不在窗口内 (13:59:59 是最后一秒)
- 避免窗口重叠和边界问题

#### Daily Timeline

```
00:00 ─────────────────────────────────────────────────────── 24:00
  │
  ├─ 00:00 ─┐ Processing Window Start (午夜处理触发)
  │         │ (Processes yesterday's videos)
  │         │
  ├─ 11:30 ─┼─┐ Capture Window 1 (Lunch)
  │         │ │ Duration: 2.5 hours
  ├─ 14:00 ─┼─┘
  │         │
  ├─ 17:30 ─┼─┐ Capture Window 2 (Dinner)
  │         │ │ Duration: 4.5 hours
  ├─ 22:00 ─┼─┘
  │         │
  ├─ 23:00 ─┼─ Processing Target Completion (警告如果未完成)
  │         │
  └─ 23:59 ─┘ Processing Window End
```

### Processing Window

```json
{
  "processing_window": {
    "start_hour": 0,
    "end_hour": 23,
    "description": "视频处理窗口 12:00 AM - 11:00 PM"
  }
}
```

**Processing Behavior:**
- **Trigger:** Midnight (00:00) - 精确分钟匹配
- **Target Completion:** 11:00 PM (23:00)
- **Warning:** 如果 11 PM 时仍在处理，记录警告日志
- **Duration:** 处理前一天的所有录制视频

---

## Process Lifecycle Management

### Service Control Flow

```
┌─────────────────────────────────────────────────────────┐
│  Command: python3 surveillance_service.py start         │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  Pre-flight Checks:                                     │
│  1. Check if already running (PID file)                │
│  2. Write PID file                                     │
│  3. Setup logging                                      │
│  4. Register signal handlers (SIGTERM, SIGINT)         │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  Start Background Threads:                              │
│  1. DiskMonitor (disk space check, 1 hour)            │
│  2. GPUMonitor (GPU metrics, 5 min)                   │
│  3. DBSync (Supabase sync, 1 hour)                    │
│  4. HealthCheck (service health, 30 min)              │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  Initial Process Start (if in time window):             │
│  1. Check if in capture window → start capture         │
│  2. Check if in processing window → start processing   │
└─────────────────────────────────────────────────────────┘
                        ↓
┌─────────────────────────────────────────────────────────┐
│  Enter Scheduler Loop (infinite):                       │
│  - Run every 30 seconds                                │
│  - Manage capture/processing lifecycle                 │
│  - Handle zombie processes                             │
│  - Respond to time windows                             │
└─────────────────────────────────────────────────────────┘
```

### Thread Safety

```python
class SurveillanceService:
    def __init__(self):
        # Thread locks prevent race conditions
        self.capture_lock = threading.Lock()
        self.processing_lock = threading.Lock()

    def start_video_capture(self):
        with self.capture_lock:  # Atomic operation
            # Only one thread can start capture at a time
            if self.capture_process and self.capture_process.poll() is None:
                return  # Already running
            # Start new capture process
```

**Why locks are needed:**
- 多个线程可能同时调用 `start_video_capture()`
  - Scheduler loop (主线程)
  - Health check thread (监控线程)
- 没有锁 → 可能启动多个录制进程 → 冲突
- 使用锁 → 原子操作 → 只启动一个进程

### PID File Management

```python
PID_FILE = PROJECT_ROOT / "surveillance_service.pid"

# Start: Write PID
with open(PID_FILE, 'w') as f:
    f.write(str(os.getpid()))

# Status: Check PID
if PID_FILE.exists():
    with open(PID_FILE) as f:
        pid = int(f.read().strip())
    try:
        os.kill(pid, 0)  # Check if process exists
        print(f"✅ Service is running (PID: {pid})")
    except OSError:
        print("❌ Service not running (stale PID file)")
        PID_FILE.unlink()

# Stop: Remove PID
if PID_FILE.exists():
    PID_FILE.unlink()
```

---

## Configuration Parameters

### System Configuration File

**Location:** `/scripts/config/system_config.json`

```json
{
  "version": "1.0.0",
  "last_updated": "2025-11-16",

  "capture_windows": [
    {
      "name": "lunch",
      "start_hour": 11,
      "start_minute": 30,
      "end_hour": 14,
      "end_minute": 0,
      "description": "Lunch service - 11:30 AM to 2:00 PM"
    },
    {
      "name": "dinner",
      "start_hour": 17,
      "start_minute": 30,
      "end_hour": 22,
      "end_minute": 0,
      "description": "Dinner service - 5:30 PM to 10:00 PM"
    }
  ],

  "processing_window": {
    "start_hour": 0,
    "end_hour": 23,
    "description": "Video processing - 12:00 AM to 11:00 PM"
  },

  "analysis_settings": {
    "fps": 5,
    "person_confidence_threshold": 0.3,
    "staff_confidence_threshold": 0.5,
    "min_person_size": 40,
    "state_debounce_seconds": 1.0
  },

  "monitoring_intervals": {
    "disk_check_seconds": 3600,    // 1 hour
    "gpu_check_seconds": 300,      // 5 minutes
    "db_sync_seconds": 3600,       // 1 hour
    "health_check_seconds": 1800   // 30 minutes
  },

  "detection_mode": "combined",
  "supabase_sync_enabled": true,
  "monitoring_enabled": true,
  "auto_restart_enabled": true
}
```

### Orchestrator Parameters

```python
# GPU Monitoring
GPU_CHECK_INTERVAL = 30  # seconds - GPU metrics check interval

# Dynamic Worker Scaling
DEFAULT_MIN_WORKERS = 1   # Always start with 1 worker
DEFAULT_MAX_WORKERS = 8   # Maximum workers for 10 cameras

# RTX 3060 Temperature Thresholds
TEMP_SCALE_UP_THRESHOLD = 70      # °C - Safe to add workers
TEMP_SCALE_DOWN_THRESHOLD = 75    # °C - Remove workers
TEMP_EMERGENCY_THRESHOLD = 80     # °C - Emergency stop

# GPU Utilization Thresholds
GPU_UTIL_SCALE_UP_THRESHOLD = 70    # % - Safe to add workers
GPU_UTIL_SCALE_DOWN_THRESHOLD = 85  # % - Remove workers

# Memory Thresholds
MIN_MEMORY_FREE_GB = 2.0           # Minimum free memory to scale up
SCALE_COOLDOWN_SECONDS = 60        # Wait time between scaling decisions

# Logging
LOG_RETENTION_DAYS = 14            # Keep 2 weeks of logs
```

### Performance Characteristics

**Validated on RTX 3060 (2025-11-13):**

| Metric | Value |
|--------|-------|
| Processing Speed | 3.24x real-time @ 5fps |
| GPU Utilization | 71.4% (stable) |
| Frame Time | 61.7ms/frame average |
| Capacity | 100 hours in 17.1 hours |

**Production Workload:**
- 1 camera × 7.5 hours daily = 7.5 hours footage
- Processing window: 23 hours available
- Target completion: 11:00 PM
- Current performance: Processes at 3.24x real-time

---

## Usage Examples

### 1. Start Surveillance Service

```bash
# Production (systemd)
sudo systemctl start ase_surveillance

# Development (foreground)
python3 scripts/orchestration/surveillance_service.py --foreground

# Or use main.py
python3 main.py --start
```

### 2. Check Service Status

```bash
python3 scripts/orchestration/surveillance_service.py status

# Output:
✅ Service is running (PID: 12345)

📊 Current Status:
Time: 2025-12-13 15:30:00
Capture window: 🟢 ACTIVE (Dinner)
Processing window: 🟢 ACTIVE
```

### 3. Stop Service

```bash
python3 scripts/orchestration/surveillance_service.py stop

# Or with systemd
sudo systemctl stop ase_surveillance
```

### 4. Manual Video Processing

```bash
# Process all videos with default settings
python3 scripts/orchestration/process_videos_orchestrator.py

# Process specific cameras
python3 scripts/orchestration/process_videos_orchestrator.py --cameras camera_35 camera_22

# Test mode (first 60 seconds only)
python3 scripts/orchestration/process_videos_orchestrator.py --duration 60

# Custom worker limits
python3 scripts/orchestration/process_videos_orchestrator.py --min-workers 2 --max-workers 6

# List discovered videos (dry run)
python3 scripts/orchestration/process_videos_orchestrator.py --list
```

### 5. Monitor Logs

```bash
# Service log (all events)
tail -f logs/surveillance_service.log

# Processing log (video processing)
tail -f logs/processing_YYYYMMDD_HHMMSS.log

# Error log (errors only)
tail -f logs/errors_YYYYMMDD.log

# Systemd log (if using systemd)
sudo journalctl -u ase_surveillance -f
```

---

## Key Design Principles

### 1. Conservative Resource Management
- Start with minimal workers (1)
- Scale up only when GPU is underutilized
- Scale down aggressively on any stress signal
- Emergency stop at 80°C temperature

### 2. Graceful Degradation
- Fallback to nvidia-smi if pynvml fails
- Continue with default workers if GPU monitoring unavailable
- Workers self-terminate when scaled down (no force kill)

### 3. Data Integrity
- Skip today's videos (avoid incomplete files)
- Database duplicate checking (prevent re-processing)
- Graceful shutdown with 30s timeout (allow FFmpeg to finalize)

### 4. Operational Safety
- Thread locks prevent race conditions
- PID file prevents duplicate service instances
- Zombie process cleanup prevents resource leaks
- Comprehensive logging for debugging

### 5. Production Ready
- Systemd integration for auto-restart
- Health checks for auto-recovery
- Configurable time windows
- Multi-threaded monitoring

---

## Troubleshooting

### Issue: Workers not scaling up

**Check:**
```bash
# GPU metrics
nvidia-smi

# Temperature should be < 70°C
# Utilization should be < 70%
# Free memory should be > 2 GB
```

**Solution:**
- Wait 60 seconds (cooldown period)
- Check if at MAX_WORKERS limit
- Verify pynvml installation: `pip3 install nvidia-ml-py3`

### Issue: Processing still running after 11 PM

**Check:**
```bash
# How many videos in queue?
python3 scripts/orchestration/process_videos_orchestrator.py --list

# GPU performance
nvidia-smi
```

**Solution:**
- Increase MAX_WORKERS if GPU underutilized
- Check for GPU throttling
- Verify video files are not corrupted

### Issue: Capture process won't stop

**Check:**
```bash
# Process status
ps aux | grep capture_rtsp_streams

# Log file
tail -f logs/surveillance_service.log
```

**Solution:**
- v2.3.0 allows 30s for graceful shutdown
- If still hanging, force kill: `sudo pkill -9 -f capture_rtsp_streams`
- Check systemd timeout: `systemctl show ase_surveillance | grep TimeoutStopSec`

### Issue: Zombie processes accumulating

**Check:**
```bash
# List zombie processes
ps aux | grep defunct
```

**Solution:**
- v2.4.0 auto-cleans zombies every 30 seconds
- If persisting, restart service: `systemctl restart ase_surveillance`

---

## Version History

- **v3.1.0** (2025-11-16): Date filtering, database duplicate check
- **v3.0.0** (2025-11-16): Dynamic GPU worker management
- **v2.4.0** (2025-12-12): Zombie process cleanup
- **v2.3.0** (2025-11-22): Increased SIGTERM timeout to 30s
- **v2.2.0** (2025-11-19): Graceful shutdown with SIGKILL fallback
- **v2.1.0** (2025-11-17): Fixed capture window end detection
- **v2.0.0** (2025-11-16): Multiple capture windows, midnight processing

---

## Related Documentation

- **Video Processing:** [../video_processing/CLAUDE.md](../video_processing/CLAUDE.md)
- **Deployment:** [../deployment/CLAUDE.md](../deployment/CLAUDE.md)
- **Database:** [../../db/CLAUDE.md](../../db/CLAUDE.md)
- **Main Documentation:** [../../CLAUDE.md](../../CLAUDE.md)

---

**Last Updated:** 2025-12-13
**Maintained By:** ASE Smartice Team
