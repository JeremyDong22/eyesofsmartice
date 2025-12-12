# Video Capture Architecture

**Version:** 1.1.0
**Last Updated:** 2025-12-13

本文档详细说明RTSP视频采集系统的架构设计、核心算法及故障处理机制。

**主要算法覆盖:**
- RTSP连接管理与重连逻辑
- 60秒分段录制算法
- 多线程并发采集
- 文件命名与轮转策略
- 错误检测与恢复机制
- 内存管理与长期运行稳定性
- 磁盘空间管理策略

---

## System Overview

```
Multi-Camera RTSP Capture System
         ↓
FFmpeg Direct RTSP Connection (No OpenCV)
         ↓
60-Second Segmentation with Auto-Rotation
         ↓
Native Reconnection + Comprehensive Logging
         ↓
Output: H.264 MP4 Segments + Structured Logs
```

**核心特性 (v5.3.0):**
- 直连FFmpeg RTSP (无OpenCV中间层)
- 60秒分段录制 (快速故障恢复)
- 原生重连机制 (无录制间隙)
- 多线程并行采集
- 结构化日志系统 (rotation + 分级)
- PIPE死锁修复 (v5.3.0)

---

## Architecture Evolution

### v3.3.0 - Legacy OpenCV Pipeline (已废弃)

```
┌─────────────────────────────────────────────────────────────────┐
│  OpenCV VideoCapture                                            │
│  ├─ 连接RTSP流                                                   │
│  ├─ 逐帧读取 (cv2.read())                                        │
│  └─ 发送到FFmpeg stdin (管道)                                     │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  FFmpeg Encoder                                                 │
│  ├─ 从stdin读取原始帧                                             │
│  ├─ H.264编码                                                    │
│  └─ 写入MP4文件                                                   │
└─────────────────────────────────────────────────────────────────┘

问题:
- OpenCV断连 → FFmpeg饿死 → 10-30秒录制间隙
- 需要手动重连逻辑 (复杂状态管理)
- 两层进程 (OpenCV + FFmpeg) 增加故障点
```

### v4.0.0 - Direct FFmpeg (架构重构)

```
┌─────────────────────────────────────────────────────────────────┐
│  FFmpeg Direct RTSP                                             │
│  ├─ 直接连接RTSP (rtsp://)                                        │
│  ├─ TCP传输 (可靠性)                                              │
│  ├─ 原生重连 (-reconnect flags)                                  │
│  ├─ Stream copy (无重新编码)                                      │
│  └─ 分段录制 (-t duration)                                        │
└─────────────────────────────────────────────────────────────────┘
                           ↓
                    H.264 MP4 Segments

优势:
- 单进程架构 (FFmpeg)
- 原生重连 (无间隙)
- 更低开销 (stream copy)
- 更简单代码 (无OpenCV)
```

### v5.0.0 - Enhanced Reconnection + Logging

```
┌─────────────────────────────────────────────────────────────────┐
│  FFmpeg + Comprehensive Reconnect Flags                         │
│  ├─ -reconnect 1                    (启用重连)                   │
│  ├─ -reconnect_streamed 1           (流式内容重连)                │
│  ├─ -reconnect_delay_max 5          (最大延迟5秒)                │
│  ├─ -timeout 10000000               (Socket超时10秒)             │
│  ├─ -stimeout 10000000              (流超时10秒)                 │
│  ├─ -analyzeduration 5000000        (快速分析5秒)                │
│  └─ -probesize 5000000              (探测5MB)                   │
└─────────────────────────────────────────────────────────────────┘
                           +
┌─────────────────────────────────────────────────────────────────┐
│  Structured Logging System                                      │
│  ├─ capture.log      (INFO+, 通用事件)                           │
│  ├─ errors.log       (WARNING+, 错误追踪)                        │
│  ├─ performance.log  (DEBUG+, 性能指标)                          │
│  └─ Log rotation     (10MB/文件, 5个备份)                        │
└─────────────────────────────────────────────────────────────────┘
```

### v5.2.0 - RTSP Timeout Fix (关键修复)

**问题:** 2025-12-08起，所有RTSP连接失败 (14.5小时录制丢失)

**原因:** 使用了错误的FFmpeg超时参数：
- `-timeout` (deprecated, 导致FFmpeg进入"监听模式")
- `-rw_timeout` (RTSP demuxer不支持，FFmpeg 4.4.2)

**修复:**
- 只使用 `-stimeout` (RTSP client的正确TCP I/O超时参数)
- 移除 `-reconnect` 系列参数 (仅适用于HTTP/HTTPS, 不适用于RTSP)

```python
# v5.2.0 修复后的FFmpeg命令
ffmpeg_cmd = [
    'ffmpeg',
    '-rtsp_transport', 'tcp',
    '-stimeout', '10000000',  # ✓ 正确: RTSP client超时
    # 注意: 移除了 -reconnect 系列参数 (RTSP不支持)
    '-analyzeduration', '5000000',
    '-probesize', '5000000',
    '-i', rtsp_url,
    '-c:v', 'copy',
    '-c:a', 'copy',
    '-movflags', '+frag_keyframe+empty_moov',
    '-t', segment_duration,
    '-y', output_path
]
```

### v5.3.0 - PIPE Deadlock Fix (稳定性修复)

**问题:** 采集在~155个片段后停止 (2025-12-09晚上录制)
- 进程挂起 (需要SIGKILL才能终止)
- 无错误日志
- 缺失"Starting segment 156"日志条目

**根本原因:** `subprocess.Popen()` PIPE缓冲区死锁
- FFmpeg stderr/stdout输出到 `subprocess.PIPE`
- PIPE缓冲区大小: 64KB (Linux)
- 155个片段后缓冲区满 → Popen()阻塞 → 进程死锁

**修复:**
```python
# v5.3.0 之前 (有问题)
ffmpeg_process = subprocess.Popen(
    ffmpeg_cmd,
    stdout=subprocess.PIPE,  # ❌ 64KB缓冲区会填满
    stderr=subprocess.PIPE   # ❌ 导致死锁
)

# v5.3.0 修复后
ffmpeg_process = subprocess.Popen(
    ffmpeg_cmd,
    stdout=subprocess.DEVNULL,  # ✓ 不使用PIPE
    stderr=subprocess.DEVNULL   # ✓ 防止死锁
)
```

**诊断日志 (v5.3.0):**
```python
# 添加了 [POPEN_TIMING] 和 [LOOP_TIMING] 日志
self.logger.info(f"[POPEN_TIMING] Calling Popen() for segment {n}...")
# ... Popen() call ...
self.logger.info(f"[POPEN_TIMING] Popen() completed in {duration:.3f}s")

# 主循环计时
self.logger.info(f"[LOOP_TIMING] Starting iteration for segment {n} (gap: {gap:.2f}s)")
```

---

## Algorithm 1: RTSP Connection Management

### Problem
建立和维护可靠的RTSP视频流连接，处理网络中断、摄像头重启、超时等各类故障场景。

### Algorithm Description

**Connection Lifecycle:**

```
┌─────────────────────────────────────────────────────────────────┐
│  Phase 1: Pre-Flight Check                                     │
│  ├─ ping_host() - ICMP连通性测试                                 │
│  ├─ RTT测量 (要求 <500ms)                                        │
│  └─ 决策: 继续 or 中止                                           │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  Phase 2: RTSP URL Construction                                │
│  ├─ _build_rtsp_url()                                          │
│  ├─ 格式: rtsp://user:pass@ip:port/path                         │
│  ├─ 示例: rtsp://admin:123456@202.168.40.35:554/media/video1  │
│  └─ 密码在日志中自动脱敏 (***:***)                                │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  Phase 3: FFmpeg Process Launch                                │
│  ├─ subprocess.Popen() with DEVNULL                            │
│  ├─ TCP/UDP transport selection                                │
│  ├─ Timeout parameters (-stimeout 10s)                         │
│  ├─ Stream analysis (-analyzeduration, -probesize)            │
│  └─ PID tracking for cleanup                                   │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  Phase 4: Connection Monitoring                                │
│  ├─ FFmpeg process poll() (检测存活)                             │
│  ├─ Segment completion tracking                                │
│  ├─ Error pattern detection (stderr analysis)                  │
│  └─ Automatic retry on failure                                 │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  Phase 5: Graceful Shutdown                                    │
│  ├─ SIGTERM → terminate()                                      │
│  ├─ 10秒等待 → wait(timeout=10)                                 │
│  ├─ Force kill if needed → kill()                              │
│  └─ Cleanup resources                                          │
└─────────────────────────────────────────────────────────────────┘
```

### Key Parameters

```python
# Connection Timeouts (v5.2.0)
FFMPEG_TIMEOUT = 10000000           # Socket TCP timeout: 10s (microseconds)
FFMPEG_ANALYZEDURATION = 5000000    # Stream analysis: 5s (快速启动)
FFMPEG_PROBESIZE = 5000000          # Probe size: 5MB (快速识别流格式)

# Transport Options (v5.1.0)
FFMPEG_RTSP_TRANSPORT = "tcp"       # Default: TCP (可靠)
# Alternative: "udp"                 # Fallback: UDP (低延迟，可能丢包)

# Retry Strategy
RETRY_DELAY = 5                     # 失败后5秒重试
MAX_RETRIES = None                  # 无限重试 (直到用户中断)
```

### Network Quality Check Algorithm

**Code Location:** `ping_host()`, `check_network_quality()` (lines 250-360)

```python
def ping_host(host_ip, timeout=2, count=1):
    """
    跨平台ping实现 (Linux/macOS/Windows)

    Algorithm:
    1. 检测操作系统 (platform.system())
    2. 构建OS-specific ping命令
       - Windows: ping -n <count> -w <timeout_ms> <ip>
       - Linux/Mac: ping -c <count> -W <timeout_sec> <ip>
    3. 执行subprocess.run() with timeout
    4. 解析stdout获取RTT (正则表达式)
       - Windows: "Average = XXXms" or "time=XXXms"
       - Linux/Mac: "time=XX.X ms" or "rtt min/avg/max/mdev"
    5. 返回 (success, rtt_ms, error_msg)

    Time Complexity: O(timeout) - 最坏情况等待timeout秒
    Space Complexity: O(1) - 固定缓冲区
    """

def check_network_quality(host_ip, max_rtt_ms=500):
    """
    网络质量检查

    Algorithm:
    1. 调用 ping_host()
    2. 检查可达性 (success flag)
    3. 验证RTT阈值 (< 500ms)
    4. 返回健康状态 + 诊断消息

    Decision Tree:
    - ping失败 → 不健康 (中止录制)
    - RTT未知 → 健康 (继续录制)
    - RTT > 500ms → 不健康 (网络过慢)
    - RTT ≤ 500ms → 健康 (正常录制)
    """
```

### RTSP URL Password Redaction

**Code Location:** `_start_ffmpeg_segment()` line 480

```python
# 安全日志记录 - 密码脱敏
cmd_str = ' '.join(ffmpeg_cmd)
cmd_str_redacted = re.sub(
    r'rtsp://[^:]+:([^@]+)@',  # 匹配 rtsp://user:PASSWORD@
    r'rtsp://***:***@',         # 替换为 rtsp://***:***@
    cmd_str
)
self.logger.debug(f"FFmpeg command: {cmd_str_redacted}")

# 输入: rtsp://admin:123456@202.168.40.35:554/media/video1
# 输出: rtsp://***:***@202.168.40.35:554/media/video1
```

---

## Algorithm 2: Subprocess PIPE Deadlock Prevention (v5.3.0)

### Problem
长时间运行的FFmpeg进程在约155个片段后挂起，进程无响应，需要SIGKILL终止。

### Root Cause Analysis

```
subprocess.Popen() with PIPE:
┌─────────────────────────────────────────────────────────────────┐
│  Python Process                                                 │
│  ├─ Popen(stdout=PIPE, stderr=PIPE)                            │
│  └─ PIPE buffer: 64KB (Linux kernel limit)                     │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  FFmpeg Process                                                 │
│  ├─ 写入 stderr (进度信息, 每秒~500字节)                           │
│  ├─ 写入 stdout (metadata)                                      │
│  └─ 累积输出: 155 segments × 60s × 500B/s = ~4.65 MB           │
└─────────────────────────────────────────────────────────────────┘

Problem Timeline:
t=0s     - Segment 1 开始, PIPE缓冲 0 KB
t=60s    - Segment 1 完成, PIPE缓冲 ~30 KB
t=120s   - Segment 2 完成, PIPE缓冲 ~60 KB
...
t=9300s  - Segment 155 完成, PIPE缓冲 ~64 KB (满)
t=9300s+ - Segment 156 启动:
           FFmpeg尝试写入stderr → PIPE已满 → 阻塞
           Python调用Popen() → 等待FFmpeg启动 → 阻塞
           双向死锁 (Deadlock)
```

### Solution Algorithm

**Code Location:** `_start_ffmpeg_segment()` lines 494-498

```python
# v5.3.0 修复 - 使用 DEVNULL 替代 PIPE
ffmpeg_process = subprocess.Popen(
    ffmpeg_cmd,
    stdout=subprocess.DEVNULL,  # ✓ 丢弃输出, 无缓冲区限制
    stderr=subprocess.DEVNULL   # ✓ 丢弃错误, 防止死锁
)

# Trade-off Analysis:
# Before v5.3.0 (PIPE):
#   优点: 可以读取FFmpeg详细输出 (帧率, 码率, 错误信息)
#   缺点: 64KB缓冲区限制 → 155段后死锁 → 生产环境不可用
#
# After v5.3.0 (DEVNULL):
#   优点: 无缓冲区限制 → 无限段数 → 生产稳定
#   缺点: 丢失FFmpeg详细输出 → 调试能力下降
#
# Decision: 稳定性 > 调试便利性 (生产环境优先级)
```

### Diagnostic Logging (v5.3.0)

**Code Location:** `_start_ffmpeg_segment()` lines 490-501, `capture_video()` lines 734-772

```python
# [POPEN_TIMING] - 跟踪Popen()调用时长
self.last_popen_start_time = time.time()
self.logger.info(f"[POPEN_TIMING] Calling Popen() for segment {n}...")

ffmpeg_process = subprocess.Popen(...)  # ← 可能阻塞的调用

self.last_popen_duration = time.time() - self.last_popen_start_time
self.logger.info(f"[POPEN_TIMING] Popen() completed in {duration:.3f}s")

# 正常: <0.1s (立即返回)
# 异常: >5s (可能死锁前兆)

# [LOOP_TIMING] - 跟踪主循环迭代间隔
last_loop_time = time.time()
while is_capturing:
    loop_start = time.time()
    loop_gap = loop_start - last_loop_time
    self.logger.info(f"[LOOP_TIMING] Starting iteration {n} (gap: {gap:.2f}s)")

    # ... 处理当前段 ...

    last_loop_time = loop_start

# 正常间隔: ~60s (段时长)
# 异常间隔: >120s (可能卡在某个段)
```

---

## Algorithm 3: 60-Second Segmentation

### Why 60 Seconds?

| 因素 | 说明 |
|------|------|
| **故障恢复** | 单段失败只丢失60秒，不影响整体录制 |
| **FFmpeg稳定性** | 避免长时间运行的内存泄漏 (测试发现600秒有问题) |
| **快速重连** | WiFi断开后只丢失当前段，立即开始新段 |
| **文件管理** | 小文件便于上传、处理、删除 |
| **调试便利** | 可以精确定位问题发生时间 |

### Segmentation Algorithm

**Code Location:** `DirectFFmpegCapture.capture_video()` lines 679-858

```python
# 核心循环算法
def capture_video(self, duration_seconds, output_dir):
    """
    分段录制算法 - 时间片轮转策略

    Algorithm:
    1. 初始化会话状态
       - session_start_time = now
       - current_segment = 1
       - segments_created = []

    2. 创建日期子目录
       - 路径: output_dir/YYYYMMDD/camera_id/
       - 用途: 按日期组织视频文件

    3. 主循环 (while is_capturing):
       a. 检查总时长是否达标
          if (now - session_start_time) >= duration_seconds:
              break

       b. 计算当前段时长
          remaining = duration_seconds - elapsed
          segment_duration = min(60, remaining)  # 最后一段可能<60s

       c. 生成文件名
          - 第1段: camera_id_YYYYMMDD_HHMMSS.mp4
          - 第N段: camera_id_YYYYMMDD_HHMMSS_partN.mp4

       d. 启动FFmpeg (非阻塞)
          ffmpeg_process = _start_ffmpeg_segment(output_file, n)
          if process is None:
              break  # 启动失败, 终止录制

       e. 等待段完成 (阻塞)
          success = _wait_for_segment(ffmpeg_process, n)

       f. 验证文件创建
          if output_file.exists():
              记录 segment_info (文件名, 大小, 时长)
          else:
              警告 (文件未生成)

       g. 处理失败情况
          if not success:
              sleep(5)  # 5秒延迟防止快速重试
          current_segment += 1

    4. 清理与总结
       - 终止残留FFmpeg进程
       - 记录会话统计 (成功段, 失败段, 总大小, 码率)
       - 返回成功/失败标志

    Time Complexity: O(n) where n = duration_seconds / 60
    Space Complexity: O(n) for segments_created list
    """

    # 状态机图解
    """
    ┌──────────────┐
    │  INIT        │ session_start, segment=1
    └──────┬───────┘
           ↓
    ┌──────────────┐
    │  CHECK_TIME  │ elapsed >= target? → EXIT
    └──────┬───────┘
           ↓ No
    ┌──────────────┐
    │  CALC_DUR    │ min(60, remaining)
    └──────┬───────┘
           ↓
    ┌──────────────┐
    │  GEN_FILE    │ camera_id_timestamp[_partN].mp4
    └──────┬───────┘
           ↓
    ┌──────────────┐
    │  START_FFMPEG│ subprocess.Popen(...)
    └──────┬───────┘
           ↓
    ┌──────────────┐
    │  WAIT_SEG    │ process.wait() - 阻塞60秒
    └──────┬───────┘
           ↓
    ┌──────────────┐
    │  VERIFY_FILE │ exists? record : warn
    └──────┬───────┘
           ↓
    ┌──────────────┐
    │  NEXT_SEG    │ segment += 1
    └──────┬───────┘
           ↓
           └───────→ (loop back to CHECK_TIME)
    """
```

### Segment Wait Algorithm

**Code Location:** `_wait_for_segment()` lines 521-571

```python
def _wait_for_segment(self, ffmpeg_process, segment_number):
    """
    等待FFmpeg段完成并处理错误

    Algorithm:
    1. 记录开始时间 (segment_start)

    2. 阻塞等待FFmpeg退出
       return_code = ffmpeg_process.wait()
       # 阻塞直到:
       #   - FFmpeg正常退出 (60秒后, -t flag)
       #   - FFmpeg异常退出 (连接失败, 流错误)
       #   - 用户中断 (Ctrl+C)

    3. 计算实际时长
       segment_duration = now - segment_start

    4. 检查退出码
       if return_code == 0:
           success_count += 1
           log_success()
           return True
       else:
           failure_count += 1
           log_error_context()  # 完整状态快照
           return False

    5. 异常处理
       except Exception as e:
           failure_count += 1
           log_exception()
           return False

    Note: v5.3.0后无法读取stdout/stderr (DEVNULL)
          只能依靠exit code判断成功/失败
    """
```

### Filename Convention

```
videos/YYYYMMDD/camera_id/camera_id_YYYYMMDD_HHMMSS.mp4

示例 (18:30:00开始采集):
videos/20251213/camera_35/camera_35_20251213_183000.mp4  (18:30:00-18:31:00)
videos/20251213/camera_35/camera_35_20251213_183100.mp4  (18:31:00-18:32:00)
videos/20251213/camera_35/camera_35_20251213_183200.mp4  (18:32:00-18:33:00)
...

多段命名 (同一次启动产生多段):
camera_35_20251213_183000.mp4           (第1段, 无后缀)
camera_35_20251213_183000_part2.mp4     (第2段)
camera_35_20251213_183000_part3.mp4     (第3段)
```

### Automatic Rotation Logic

FFmpeg通过 `-t` 参数自动处理分段：

```bash
# FFmpeg命令示例
ffmpeg \
  -rtsp_transport tcp \
  -stimeout 10000000 \
  -i rtsp://admin:123456@202.168.40.35:554/media/video1 \
  -c:v copy \
  -c:a copy \
  -movflags +frag_keyframe+empty_moov \
  -t 60 \                              # ← 关键: 60秒后自动退出
  -y camera_35_20251213_183000.mp4

# 60秒后FFmpeg退出 (exit code 0)
# Python脚本检测到退出 → 立即启动下一段
```

---

## FFmpeg Reconnection Strategy

### Connection Parameters (v5.2.0 - 修正版)

```python
FFMPEG_TIMEOUT = 10000000        # Socket超时: 10秒 (微秒)
FFMPEG_ANALYZEDURATION = 5000000 # 流分析: 5秒 (微秒)
FFMPEG_PROBESIZE = 5000000       # 探测大小: 5MB
FFMPEG_RTSP_TRANSPORT = "tcp"    # TCP传输 (可靠性)
FFMPEG_STREAM_COPY = True        # Stream copy (无重新编码)

# v5.2.0 移除的参数 (RTSP不支持):
# FFMPEG_RECONNECT_ENABLED = True
# FFMPEG_RECONNECT_STREAMED = True
# FFMPEG_RECONNECT_DELAY_MAX = 5
```

### Connection Resilience

| 场景 | FFmpeg行为 | 系统响应 |
|------|-----------|---------|
| **RTSP连接超时** | `-stimeout 10s` 后退出 | 立即启动新段 (5秒延迟) |
| **网络抖动** | TCP自动重传 | 继续录制 (无感知) |
| **摄像头重启** | 连接失败 → 退出 | 重试新段 |
| **WiFi断开** | 当前段失败 | 下一段重新连接 |

### Error Recovery Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  Segment N 开始                                                  │
│  ├─ FFmpeg连接RTSP                                               │
│  ├─ 录制中... (0-60秒)                                            │
│  └─ 情况A: 正常完成 (60秒) → Segment N+1                          │
│  └─ 情况B: 连接失败 (<60秒) → 重试 Segment N+1                    │
└─────────────────────────────────────────────────────────────────┘
                           ↓
┌─────────────────────────────────────────────────────────────────┐
│  故障处理 (情况B)                                                 │
│  ├─ FFmpeg退出 (非0 exit code)                                   │
│  ├─ 记录错误日志 (errors.log)                                     │
│  ├─ 5秒延迟 (避免快速重试)                                         │
│  └─ 启动 Segment N+1                                             │
└─────────────────────────────────────────────────────────────────┘

间隙时间: ~5秒 (远小于旧版本的10-30秒)
```

---

## Algorithm 4: Multi-Threaded Parallel Capture

### Problem
同时从多个摄像头采集视频流，最大化硬件利用率，避免串行采集的时间浪费。

### Architecture

**Code Location:** `capture_all_cameras()` lines 959-1030, `DirectFFmpegCapture.start_capture_async()` lines 860-868

```python
# 并行采集算法
def capture_all_cameras(duration_seconds, output_dir, ...):
    """
    多线程并行采集策略

    Algorithm:
    1. 加载摄像头配置
       cameras = load_cameras_config()  # JSON文件
       filter enabled cameras (enabled=True)

    2. 创建采集对象 (每摄像头一个)
       for camera_id, config in cameras.items():
           capture = DirectFFmpegCapture(camera_id, config, ...)
           captures[camera_id] = capture
           _active_captures.append(capture)  # 全局注册 (信号处理)

    3. 启动后台线程 (非阻塞)
       for capture in captures.values():
           thread = capture.start_capture_async(duration, output_dir)
           threads.append(thread)

       # start_capture_async() 实现:
       def start_capture_async(self, duration, output_dir):
           thread = threading.Thread(
               target=self.capture_video,  # 目标函数
               args=(duration, output_dir),
               daemon=False  # 非守护线程 (等待完成)
           )
           thread.start()
           return thread

    4. 等待所有线程完成 (阻塞)
       for thread in threads:
           thread.join()  # 阻塞直到线程退出

    5. 记录完成状态
       log all captures complete

    Threading Model:
    ┌─────────────────────────────────────────────────────────────┐
    │  Main Thread                                                │
    │  ├─ Load config                                             │
    │  ├─ Create N capture objects                                │
    │  ├─ Start N threads (non-blocking)                          │
    │  └─ Join all threads (blocking)                             │
    └─────────────────────────────────────────────────────────────┘
                           ↓ spawn
    ┌─────────────────────────────────────────────────────────────┐
    │  Worker Thread 1 (camera_35)                                │
    │  └─ capture_video() → FFmpeg subprocess → MP4 files         │
    └─────────────────────────────────────────────────────────────┘
    ┌─────────────────────────────────────────────────────────────┐
    │  Worker Thread 2 (camera_22)                                │
    │  └─ capture_video() → FFmpeg subprocess → MP4 files         │
    └─────────────────────────────────────────────────────────────┘
    ┌─────────────────────────────────────────────────────────────┐
    │  Worker Thread N (camera_XX)                                │
    │  └─ capture_video() → FFmpeg subprocess → MP4 files         │
    └─────────────────────────────────────────────────────────────┘

    Time Complexity: O(max(T1, T2, ..., TN)) - 并行, 取最长耗时
    vs Serial: O(T1 + T2 + ... + TN) - 串行, 累加耗时
    Speedup: ~N倍 (假设摄像头数量 = N)
    """
```

### Concurrency Control & Thread Safety

| 资源类型 | 并发策略 | 保护机制 |
|---------|---------|---------|
| **输出目录** | 隔离 | 每摄像头独立子目录 (`videos/YYYYMMDD/camera_id/`) |
| **FFmpeg进程** | 隔离 | 每线程独立进程 (无共享状态) |
| **日志系统** | 共享 | Python `logging` 模块内置线程安全 (threading.Lock) |
| **全局列表** | 共享 | `_active_captures` 只在主线程和信号处理器访问 |
| **配置文件** | 只读 | `cameras_config.json` 加载后不修改 |

### Resource Isolation Strategy

```python
# 文件系统隔离
output_path = Path(output_dir) / date_str / camera_id
#                                  ^^^^^^^^   ^^^^^^^^^
#                                  日期分组    摄像头ID

# 示例 (2个摄像头并行):
# videos/20251213/camera_35/camera_35_20251213_183000.mp4  ← 线程1写入
# videos/20251213/camera_22/camera_22_20251213_183000.mp4  ← 线程2写入
# 无冲突: 不同目录

# 进程隔离
thread1: subprocess.Popen(['ffmpeg', ...])  # PID 12345
thread2: subprocess.Popen(['ffmpeg', ...])  # PID 12346
# 无冲突: 独立进程空间

# 日志隔离 (逻辑层面)
logger = get_camera_logger(camera_id)  # 返回 LoggerAdapter
# extra={'camera_id': camera_id} 自动注入
# 每条日志带 camera_id 前缀, 便于过滤
```

---

## Algorithm 5: Signal-Based Graceful Shutdown

### Problem
捕获系统信号 (SIGTERM/SIGINT)，安全终止所有采集线程和FFmpeg进程，避免文件损坏和资源泄漏。

### Algorithm Description

**Code Location:** `signal_handler()` lines 896-912, signal registration lines 914-916

```python
# 信号处理算法
def signal_handler(sig, frame):
    """
    优雅关闭策略

    Algorithm:
    1. 识别信号类型
       signal_name = "SIGTERM" if sig == SIGTERM else "SIGINT"

    2. 遍历所有活动采集对象
       for capture in _active_captures:
           capture.is_capturing = False  # 设置停止标志

    3. 各工作线程检测标志
       # 在 capture_video() 主循环中:
       while is_capturing:  # ← 标志变False后退出循环
           ...

    4. FFmpeg进程清理 (在finally块中)
       if ffmpeg_process and ffmpeg_process.poll() is None:
           ffmpeg_process.terminate()  # 发送SIGTERM
           try:
               ffmpeg_process.wait(timeout=10)  # 等待10秒
           except TimeoutExpired:
               ffmpeg_process.kill()  # 强制终止 (SIGKILL)

    5. 线程自然退出
       # main thread的join()调用会等待所有worker退出

    Shutdown Timeline:
    t=0s    - 用户按Ctrl+C (SIGINT)
    t=0.01s - signal_handler() 执行, 设置 is_capturing=False
    t=0.02s - 各工作线程在下一次循环检测到标志
    t=0-60s - 当前FFmpeg段完成 (最多等待60秒)
    t=60s   - FFmpeg自然退出, finally块执行
    t=60s   - 线程退出, join()返回
    t=60s   - 主线程退出, 程序结束

    Worst Case: 60秒 (当前段接近完成时收到信号)
    Best Case: <1秒 (段刚开始时收到信号, terminate()立即生效)
    """

# 全局注册表 (用于信号处理器访问)
_active_captures = []  # List[DirectFFmpegCapture]

# 注册信号处理器
signal.signal(signal.SIGTERM, signal_handler)  # systemd stop
signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
```

### Cleanup Sequence Diagram

```
User/System                Main Thread             Worker Threads           FFmpeg Processes
    |                          |                         |                         |
    | Ctrl+C (SIGINT)          |                         |                         |
    |------------------------->|                         |                         |
    |                          |                         |                         |
    |                  signal_handler()                  |                         |
    |                          |                         |                         |
    |                          | is_capturing = False    |                         |
    |                          |------------------------>|                         |
    |                          |                         |                         |
    |                          |                         | detect flag in loop     |
    |                          |                         |                         |
    |                          |                         | terminate()             |
    |                          |                         |------------------------>|
    |                          |                         |                         |
    |                          |                         |                  SIGTERM received
    |                          |                         |                         |
    |                          |                         | wait(timeout=10)        |
    |                          |                         |<------------------------|
    |                          |                         |                  exit(0)
    |                          |                         |                         |
    |                          |                         | thread exits            |
    |                          |<------------------------|                         |
    |                          |                         |                         |
    |                  join() returns                    |                         |
    |                          |                         |                         |
    |<-------------------------|                         |                         |
    |  program exits           |                         |                         |
```

---

## Algorithm 6: Memory Management for Long-Running Processes

### Problem
24/7长期运行系统，需要防止内存泄漏、控制内存使用，避免OOM (Out Of Memory) 杀进程。

### Memory Footprint Analysis

```python
# DirectFFmpegCapture 对象内存占用
class DirectFFmpegCapture:
    # 固定大小成员
    camera_id: str              # ~100 bytes
    config: dict                # ~500 bytes (JSON配置)
    rtsp_url: str               # ~200 bytes
    segment_duration: int       # 8 bytes
    is_capturing: bool          # 1 byte
    ffmpeg_process: Popen       # ~1 KB (进程句柄)
    logger: LoggerAdapter       # ~500 bytes

    # 动态大小成员
    segments_created: list      # O(n) where n = segments数量
    # 每segment: ~200 bytes (filename, size, duration)
    # 7.5小时 × 60段/小时 = 450段 → ~90 KB

    # 总计: ~95 KB per camera (7.5小时会话)
```

### Memory Management Strategy

| 策略 | 实现 | 效果 |
|------|------|------|
| **Stream Copy模式** | `-c:v copy` (不重新编码) | FFmpeg内存 <50MB (vs >500MB编码) |
| **DEVNULL输出** | `stdout/stderr=DEVNULL` | 无PIPE缓冲区累积 (v5.3.0) |
| **60秒分段** | FFmpeg进程定期重启 | 防止FFmpeg内存泄漏累积 |
| **有限segments_created** | 只保存元数据, 不缓存视频 | 线性增长, 7.5h ~90KB |
| **日志轮转** | RotatingFileHandler (10MB) | 日志不会无限增长 |
| **独立进程** | FFmpeg subprocess | 内存隔离, Python不受影响 |

### Memory Leak Prevention

```python
# v5.3.0 关键修复 - PIPE缓冲区累积
# Before:
ffmpeg_process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,  # ❌ 每段累积~30KB
    stderr=subprocess.PIPE   # ❌ 155段后64KB缓冲区满
)
# 内存泄漏: PIPE缓冲区在Python进程中累积, 永不释放

# After v5.3.0:
ffmpeg_process = subprocess.Popen(
    cmd,
    stdout=subprocess.DEVNULL,  # ✓ 直接丢弃, 无累积
    stderr=subprocess.DEVNULL   # ✓ 内核级处理, 无Python开销
)
# 内存稳定: DEVNULL由内核处理, 无用户空间内存占用
```

### FFmpeg Process Recycling

```python
# 60秒分段策略的内存优势
while is_capturing:
    # 启动新FFmpeg进程
    ffmpeg_process = subprocess.Popen([...])

    # 等待60秒或完成
    ffmpeg_process.wait()

    # FFmpeg进程退出 → 释放所有内存
    # 操作系统回收进程资源

    # 下一段启动新FFmpeg → 内存重置为初始状态
    # 避免长时间运行的内存泄漏累积

# vs 单进程长时间运行 (旧架构):
# - FFmpeg运行7.5小时 → 内存泄漏累积 → OOM
# - 需要复杂的内存监控和重启逻辑
```

### Disk Space Considerations

**Code Location:** 与 `monitoring/check_disk_space.py` 集成

```python
# 磁盘使用估算 (单摄像头, 2592x1944, H.264, 20fps)
bitrate = 8-12 Mbps  # 取决于场景复杂度
segment_size = bitrate × 60s = 60-90 MB/segment

# 7.5小时录制 (双时段: 11:30-14:00, 17:00-22:00)
segments_per_day = 7.5h × 60min/h = 450 segments
total_size_per_day = 450 × 75MB = ~33.75 GB/camera/day

# 多摄像头 (生产规划)
# 5 cameras × 33.75 GB/day = 168.75 GB/day

# 磁盘监控策略 (check_disk_space.py v2.0.0)
# - 智能预测: 测量录制速率 × 剩余时间
# - 主动清理: 预测不足时提前删除旧视频
# - 保护策略: 始终保留今天+昨天 (处理需要)
# - 原始视频: 处理后删除 (≥1天 + 已处理)
# - 处理后视频: 2天保留
# - 数据库: 永久保留
```

---

## Algorithm 7: Error Pattern Detection & Recovery

### Problem
自动识别FFmpeg输出中的错误模式，分类故障类型，选择合适的恢复策略。

### Error Detection Algorithm

**Code Location:** `_detect_error_patterns()` lines 619-658 (v5.3.0后不再使用，保留供参考)

```python
def _detect_error_patterns(self, stderr):
    """
    FFmpeg错误模式检测 (正则表达式)

    Algorithm:
    1. 定义错误模式字典
       error_patterns = {
           'connection': [(regex, description), ...],
           'authentication': [...],
           'stream': [...],
           'rtsp': [...]
       }

    2. 遍历所有模式
       for category, patterns in error_patterns.items():
           for pattern, description in patterns:
               if re.search(pattern, stderr, re.IGNORECASE):
                   log_error(category, description)
                   if category == 'connection':
                       total_reconnects += 1

    3. 返回诊断结果

    Pattern Examples:
    - Connection: "Connection refused", "Connection timed out"
    - Authentication: "401 Unauthorized", "403 Forbidden"
    - Stream: "Invalid data found", "Could not find codec"
    - RTSP: "RTSP.*error", "Invalid SDP"

    Note: v5.3.0后因DEVNULL无法读取stderr, 此函数不再调用
          但保留代码供未来调试模式使用
    """
```

### Recovery Strategy Matrix

| 错误类型 | 检测模式 | 恢复策略 | 重试间隔 |
|---------|---------|---------|---------|
| **连接超时** | `Connection timed out` | 重启新段 | 5秒 |
| **连接拒绝** | `Connection refused` | 重启新段 | 5秒 |
| **网络不可达** | `Network is unreachable` | 重启新段 | 5秒 |
| **认证失败** | `401 Unauthorized` | 记录错误, 继续重试 | 5秒 |
| **访问禁止** | `403 Forbidden` | 记录错误, 继续重试 | 5秒 |
| **流损坏** | `Invalid data found` | 重启新段 | 5秒 |
| **RTSP协议错误** | `RTSP.*error` | 重启新段 | 5秒 |
| **未知错误** | exit_code != 0 | 记录上下文, 重启新段 | 5秒 |

### Error Context Logging

**Code Location:** `_log_error_context()` lines 660-677

```python
def _log_error_context(self):
    """
    完整状态快照记录

    Algorithm:
    1. 记录分隔线 (便于日志查找)
    2. 记录完整状态:
       - Camera ID
       - RTSP URL (密码脱敏)
       - 当前段号
       - 会话运行时长
       - 连接尝试次数
       - 成功/失败段统计
       - 总重连次数
       - 上次成功连接时间
       - 段时长配置
    3. 记录分隔线

    Purpose: 故障诊断时提供完整上下文
    Output: errors.log文件
    """
```

---

## Algorithm 8: Structured Logging System (v5.0.0)

### Problem
生产环境需要分级、分类、可轮转的日志系统，支持快速诊断和长期存档。

### Logging Architecture

**Code Location:** `setup_logging()` lines 141-229, `get_camera_logger()` lines 232-243

```python
def setup_logging():
    """
    三层日志系统初始化

    Algorithm:
    1. 创建日志目录
       logs/video_capture/

    2. 配置根日志器
       root_logger.setLevel(DEBUG)  # 捕获所有级别

    3. 添加4个Handler:
       a. capture_handler (RotatingFileHandler)
          - 文件: capture.log
          - 级别: INFO+
          - 用途: 通用事件 (会话开始/结束, 段完成)
          - 轮转: 10MB, 5备份

       b. error_handler (RotatingFileHandler)
          - 文件: errors.log
          - 级别: WARNING+
          - 用途: 错误追踪
          - 轮转: 10MB, 5备份

       c. performance_handler (RotatingFileHandler)
          - 文件: performance.log
          - 级别: DEBUG+
          - 用途: 性能指标, 详细调试
          - 轮转: 10MB, 5备份

       d. console_handler (StreamHandler)
          - 输出: stdout
          - 级别: INFO+
          - 用途: 实时监控

    4. 设置日志格式
       FORMAT = '{timestamp} | {level} | {camera_id} | {component} | {message}'

    5. 返回根日志器

    Log Routing:
    ┌──────────────────────────────────────────────────────────┐
    │  Root Logger (DEBUG)                                     │
    └────────┬───────────────────────────────────┬─────────────┘
             ↓                                   ↓
    ┌────────────────────┐            ┌────────────────────┐
    │  DEBUG messages    │            │  WARNING+ messages │
    │  performance.log   │            │  errors.log        │
    └────────────────────┘            └────────────────────┘
             ↓
    ┌────────────────────┐
    │  INFO+ messages    │
    │  capture.log       │
    │  console (stdout)  │
    └────────────────────┘
    """

def get_camera_logger(camera_id):
    """
    获取带摄像头ID上下文的日志适配器

    Algorithm:
    1. 获取根日志器
       logger = logging.getLogger()

    2. 创建适配器 (自动注入上下文)
       adapter = LoggerAdapter(logger, {
           'camera_id': camera_id,
           'component': 'CAPTURE'
       })

    3. 返回适配器

    Usage:
    logger = get_camera_logger('camera_35')
    logger.info("Starting segment 1", extra={'component': 'FFMPEG_START'})
    # Output: 2025-12-13 18:30:15 | INFO | camera_35 | FFMPEG_START | Starting segment 1
    """
```

### Log Rotation Strategy

```python
# RotatingFileHandler 行为
handler = RotatingFileHandler(
    filename='capture.log',
    maxBytes=10485760,  # 10MB
    backupCount=5
)

# Rotation Timeline:
# capture.log         (当前, 0-10MB)
# capture.log.1       (备份1, 10MB)
# capture.log.2       (备份2, 10MB)
# capture.log.3       (备份3, 10MB)
# capture.log.4       (备份4, 10MB)
# capture.log.5       (备份5, 10MB)
# 总计: 60MB maximum

# 当 capture.log 达到10MB:
# 1. capture.log → capture.log.1 (重命名)
# 2. capture.log.1 → capture.log.2
# 3. capture.log.2 → capture.log.3
# 4. capture.log.3 → capture.log.4
# 5. capture.log.4 → capture.log.5
# 6. capture.log.5 → 删除 (超过backupCount)
# 7. 创建新 capture.log
```

---

## Summary: Complete Algorithm Coverage

### Algorithms Documented

1. **RTSP Connection Management** - 5阶段连接生命周期, 网络质量检查, 密码脱敏
2. **Subprocess PIPE Deadlock Prevention** - v5.3.0关键修复, DEVNULL替代PIPE
3. **60-Second Segmentation** - 时间片轮转, 状态机, 文件命名
4. **Multi-Threaded Parallel Capture** - 线程模型, 资源隔离, 并发控制
5. **Signal-Based Graceful Shutdown** - SIGTERM/SIGINT处理, 优雅关闭序列
6. **Memory Management** - 内存占用分析, 泄漏防止, 进程回收
7. **Error Pattern Detection** - 正则匹配, 分类恢复, 上下文日志
8. **Structured Logging System** - 三层日志, 轮转策略, 上下文注入

### Key Design Principles

| 原则 | 实现 | 效果 |
|------|------|------|
| **故障隔离** | 60秒分段 + 独立FFmpeg进程 | 单段失败不影响整体 |
| **资源隔离** | 线程独立目录 + 进程独立空间 | 无竞争条件 |
| **内存稳定** | DEVNULL + 进程回收 + 日志轮转 | 长期运行无泄漏 |
| **可观测性** | 结构化日志 + 上下文快照 | 快速诊断问题 |
| **自动恢复** | 无限重试 + 5秒延迟 | 自愈能力强 |
| **优雅关闭** | 信号处理 + 清理序列 | 无文件损坏 |

### Performance Characteristics

| 指标 | 值 | 说明 |
|------|---|------|
| **CPU使用** | ~5%/camera | Stream copy模式 |
| **内存使用** | ~150MB/camera | FFmpeg + Python |
| **磁盘I/O** | 60-90 MB/min | H.264编码 |
| **网络带宽** | 8-12 Mbps | RTSP流 |
| **并发能力** | 5+ cameras | 测试验证 |
| **可靠性** | 24/7运行 | v5.3.0验证 |

---

## Related Documentation

- **Video Processing**: [video_processing/CLAUDE.md](../video_processing/CLAUDE.md) - 视频处理管道
- **Deployment**: [deployment/CLAUDE.md](../deployment/CLAUDE.md) - Systemd集成
- **Orchestration**: [orchestration/CLAUDE.md](../orchestration/CLAUDE.md) - 多摄像头批处理
- **Monitoring**: [monitoring/CLAUDE.md](../monitoring/CLAUDE.md) - 磁盘空间监控
- **Database Sync**: [database_sync/CLAUDE.md](../database_sync/CLAUDE.md) - 数据库同步
- **Root**: [../../CLAUDE.md](../../CLAUDE.md) - 项目总览

---

**End of Video Capture Documentation v1.1.0**
