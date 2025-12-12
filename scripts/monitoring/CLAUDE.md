# Monitoring System Documentation

**Version:** 1.0.0
**Last Updated:** 2025-12-13
**Location:** `/scripts/monitoring/`

---

## Overview 概述

监控系统包含四个核心脚本，负责系统健康检查、磁盘空间预测性管理、GPU温度监控和9层诊断分析。

**Core Components:**
- **check_disk_space.py** - 智能磁盘空间监控与预测性清理
- **monitor_gpu.py** - GPU温度和利用率监控
- **system_health.py** - 基础系统健康检查
- **comprehensive_health_check.py** - 9层全面诊断系统

---

## 1. Intelligent Disk Space Monitor 智能磁盘空间监控

**File:** `check_disk_space.py` v2.1.0
**Purpose:** 预测性磁盘空间管理，基于实时使用速率预测未来空间需求

### Algorithm Architecture 算法架构

```
┌─────────────────────────────────────────────────────────────┐
│  PREDICTIVE DISK SPACE MANAGEMENT ALGORITHM                 │
└─────────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
        ▼                 ▼                 ▼
  ┌──────────┐     ┌──────────┐     ┌──────────┐
  │  MEASURE │     │ PREDICT  │     │ CLEANUP  │
  │  SPEED   │────▶│  USAGE   │────▶│ PROACTIVE│
  └──────────┘     └──────────┘     └──────────┘
```

### 1.1 Prediction Algorithm 预测算法

**Step 1: Active Recording Detection 检测活跃录制**

```python
# 检查录制进程
pgrep -f capture_rtsp_streams

# 计算剩余录制时间
Recording Schedule: 11:00 AM - 9:00 PM (10 hours)
Remaining Hours = END_HOUR - Current_Hour - (Current_Minute / 60)

Example:
  Current time: 2:30 PM (14:30)
  Remaining = 21 - 14 - 0.5 = 6.5 hours
```

**Step 2: Disk Usage Speed Measurement 磁盘使用速率测量**

```python
# 30秒观测期
OBSERVATION_SECONDS = 30

# 测量前后磁盘使用量
Initial_Used_GB = get_disk_usage() at t0
Final_Used_GB = get_disk_usage() at t0+30s

# 计算速率
Delta_GB = Final_Used_GB - Initial_Used_GB
GB_per_second = Delta_GB / 30
GB_per_hour = GB_per_second × 3600

Example Output:
  Initial used: 1245.678 GB
  Final used: 1245.735 GB
  Delta: 0.057 GB in 30s
  Rate: 6.84 GB/hour
```

**Step 3: Space Prediction 空间预测**

```python
# 预测至录制结束所需空间
Predicted_Usage_GB = GB_per_hour × Remaining_Hours

# 安全边界（20%额外空间）
Safety_Margin_GB = Predicted_Usage_GB × 0.2

# 推荐空余空间
Recommended_Free_GB = Predicted_Usage_GB + Safety_Margin_GB

# 预测结束时剩余空间
Current_Free_GB = get_disk_usage()
Predicted_Free_GB = Current_Free_GB - Predicted_Usage_GB

Example:
  Usage rate: 6.84 GB/hour
  Remaining hours: 6.5 hours
  Expected usage: 44.46 GB
  Safety margin: 8.89 GB
  Recommended free: 53.35 GB
  Current free: 120 GB
  Predicted free at end: 75.54 GB → SAFE ✅
```

**Step 4: Status Classification 状态分类**

```python
if Predicted_Free_GB > Safety_Margin_GB:
    Status = "✅ SAFE"
    # 有足够空间 + 安全边界
elif Predicted_Free_GB > 0:
    Status = "⚠️ TIGHT"
    # 足够但无安全边界，建议清理
else:
    Status = "🚨 CRITICAL"
    # 空间不足，录制期间会耗尽
```

### 1.2 Smart Cleanup Logic 智能清理逻辑

**Three-Phase Cleanup 三阶段清理策略**

```
Phase 1: Screenshots        Phase 2: Raw Videos       Phase 3: Processed Videos
  Retention: 30 days          Retention: 2 days         Retention: 2 days
  Location: db/screenshots/   Location: videos/         Location: results/
  ↓                          ↓                         ↓
Delete if age > 30 days      Delete if age >= 2 days   Delete if age > 2 days
  (Independent of disk)        (Unconditional)          (Age-based only)
```

**Phase 2 Detail: Raw Video Cleanup 原始视频清理详解**

```python
# v2.1.0 Logic (2025-11-20)
for date_folder in videos/:
    age_days = get_date_age_days(date_folder)

    if age_days == 0:
        # 今天 - 正在录制，跳过
        SKIP "Still recording"

    elif age_days >= 2:
        # >= 2天 - 无条件删除（确保硬件健康）
        DELETE "Hardware health policy"
        # 原因：防止损坏/失败视频无限累积

    else:
        # < 2天 - 保留
        KEEP "Within retention period"

# v2.1.0 Breaking Change:
# - Old: age > 2 AND processed → Delete
# - New: age >= 2 (unconditional) → Delete
# - 移除"已处理检查"，确保定期清理
```

**Cleanup Trigger Logic 清理触发逻辑**

```python
# 当前检查
if Current_Free_GB < MIN_SPACE_GB:
    Trigger = "Current shortage"
    Target = max(MIN_SPACE_GB, Recommended_Free_GB)

# 预测检查（更主动）
elif Prediction_Available and Predicted_Free_GB < Safety_Margin_GB:
    Trigger = "Predicted shortage"
    Target = Recommended_Free_GB
    # 提前清理，避免录制期间空间不足

else:
    Status = "HEALTHY"
    No cleanup needed
```

### 1.3 Configuration Parameters 配置参数

```python
# Disk Space Thresholds 磁盘空间阈值
MIN_SPACE_GB = 150                    # 最小要求空间（实际78GB/天 + buffer）
ESTIMATED_VIDEO_SIZE_PER_DAY_GB = 80  # 每日视频大小估算

# Recording Schedule 录制时间表
RECORDING_START_HOUR = 11             # 11:00 AM
RECORDING_END_HOUR = 21               # 9:00 PM (21:00)
OBSERVATION_SECONDS = 30              # 速率观测时长

# Retention Policies 数据保留策略
SCREENSHOTS_RETENTION_DAYS = 30       # 截图保留30天
RAW_VIDEO_RETENTION_DAYS = 2          # 原始视频最多2天
PROCESSED_VIDEO_RETENTION_DAYS = 2    # 处理视频保留2天
# 数据库：永久保留（Never deleted）
```

### 1.4 Exit Codes 退出码

```python
0 = HEALTHY        # 空间充足，预测安全
1 = WARNING        # 空间低于阈值或预测不足（但可清理）
2 = CRITICAL       # 无法存储1天视频（手动干预）
```

### 1.5 Usage Examples 使用示例

```bash
# 基础检查（默认）
python3 check_disk_space.py --check

# 预测模式（显示详细预测）
python3 check_disk_space.py --predict

# 自动清理（基于预测）
python3 check_disk_space.py --cleanup

# 干运行（测试不删除）
python3 check_disk_space.py --cleanup --dry-run

# 禁用预测（仅基础检查）
python3 check_disk_space.py --check --no-prediction

# 自定义阈值
python3 check_disk_space.py --cleanup --min-space 200
```

### 1.6 Output Interpretation 输出解读

```
DISK USAGE SPEED MEASUREMENT
======================================================================
📊 Observing disk usage for 30 seconds...
   Initial used: 1245.678 GB
   Waiting 30s...
   Final used: 1245.735 GB
   Delta: 0.057 GB in 30.0s
   Rate: 6.84 GB/hour (0.001900 GB/s)
======================================================================

SPACE PREDICTION
======================================================================
Current Status:
   Free space now: 120.0 GB
   Usage rate: 6.84 GB/hour
   Remaining hours: 6.5 hours

Predictions:
   Expected usage: 44.5 GB
   Safety margin (20%): 8.9 GB
   Recommended free: 53.4 GB
   Predicted free at end: 75.5 GB

Status: ✅ SAFE
   Sufficient space for remaining recordings with safety margin
======================================================================
```

---

## 2. GPU Health Monitor GPU健康监控

**File:** `monitor_gpu.py` v1.0.0
**Purpose:** 监控NVIDIA GPU温度、利用率和显存使用

### 2.1 Monitoring Metrics 监控指标

```python
# Query nvidia-smi
nvidia-smi --query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total,name

# Metrics Collected:
- Temperature (°C)       # GPU核心温度
- Utilization (%)        # GPU计算利用率
- Memory Used (MB)       # 显存已用
- Memory Total (MB)      # 显存总量
- GPU Name               # GPU型号
```

### 2.2 Temperature Thresholds 温度阈值

```python
# Default Alert: 80°C
if Temperature >= THRESHOLD:
    Status = "🔥 HOT"
    Exit_Code = 1
elif Temperature >= THRESHOLD - 10:
    Status = "⚠️ WARM"
    Exit_Code = 0
else:
    Status = "✅ COOL"
    Exit_Code = 0

# Production Thresholds (RTX 3060):
# - 60-70°C: Normal operation (处理视频时)
# - 70-80°C: Warm but acceptable
# - 80-85°C: Hot, check cooling
# - >85°C: Critical, reduce load
```

### 2.3 Usage Examples 使用示例

```bash
# 单次检查
python3 monitor_gpu.py

# 持续监控（每30秒）
python3 monitor_gpu.py --watch 30

# 自定义温度阈值
python3 monitor_gpu.py --alert 85
```

### 2.4 Output Format 输出格式

```
[2025-12-13 14:30:45]
GPU: NVIDIA GeForce RTX 3060
Temperature:  71°C ⚠️ WARM
Utilization:  73%
Memory:       5234MB / 12288MB (42.6%)
```

### 2.5 Exit Codes 退出码

```python
0 = Temperature OK
1 = Temperature >= threshold (alert)
2 = GPU not available (nvidia-smi not found)
```

---

## 3. System Health Check 系统健康检查

**File:** `system_health.py` v1.0.0
**Purpose:** 快速检查生产部署的基础健康状态

### 3.1 Health Checks 健康检查项

```python
# 1. Directories 目录检查
Required: videos/, results/, db/, models/, scripts/, logs/
Status: ✅ All exist or ❌ Missing

# 2. Models 模型检查
Required:
  - models/yolov8m.pt
  - models/waiter_customer_classifier.pt
Status: ✅ All present or ❌ Missing

# 3. Config Files 配置文件检查
Required:
  - scripts/config/cameras_config.json
  - scripts/config/table_region_config.json
Status: ⚠️ Missing (will be created on first run)

# 4. Disk Space 磁盘空间检查
Delegates to: check_disk_space.py --check
Status: ✅ Healthy or ⚠️ Low space

# 5. GPU 检查
Delegates to: monitor_gpu.py
Status: ✅ Healthy or ❌ Not available
```

### 3.2 Usage 使用

```bash
# 完整健康检查
python3 system_health.py

# 输出示例
======================================================================
SYSTEM HEALTH CHECK
======================================================================

Checking Directories...
✅ All required directories exist

Checking Models...
✅ All models present

Checking Config Files...
⚠️  Missing config: cameras_config.json (will be created on first run)

Checking Disk Space...
✅ STATUS: HEALTHY (Free space > 150GB)

Checking GPU...
✅ COOL

======================================================================
SUMMARY
======================================================================
Directories          ✅ PASS
Models               ✅ PASS
Config Files         ✅ PASS
Disk Space           ✅ PASS
GPU                  ✅ PASS

======================================================================
✅ SYSTEM HEALTHY - Ready for production
```

### 3.3 Exit Codes 退出码

```python
0 = All checks passed (system healthy)
1 = One or more checks failed (review failures)
```

---

## 4. Comprehensive Health Check 9层全面诊断

**File:** `comprehensive_health_check.py` v1.0.0
**Purpose:** 生产环境9层深度诊断分析

### 4.1 Nine-Level Diagnostic Architecture 9层诊断架构

```
┌─────────────────────────────────────────────────────────────────┐
│  RESTAURANT SURVEILLANCE SYSTEM DIAGNOSTIC HIERARCHY            │
└─────────────────────────────────────────────────────────────────┘
                            │
    ┌───────────────────────┼───────────────────────┐
    ▼                       ▼                       ▼
┌─────────┐           ┌─────────┐           ┌─────────┐
│ Level 1 │           │ Level 4 │           │ Level 7 │
│ Restart │──────────▶│Monitor  │──────────▶│ Capture │
│  Time   │           │  Health │           │Operations│
└─────────┘           └─────────┘           └─────────┘
    │                       │                       │
    ▼                       ▼                       ▼
┌─────────┐           ┌─────────┐           ┌─────────┐
│ Level 2 │           │ Level 5 │           │ Level 8 │
│Maintain │──────────▶│Orchestra│──────────▶│Process  │
│  Level  │           │  tion   │           │Pipeline │
└─────────┘           └─────────┘           └─────────┘
    │                       │                       │
    ▼                       ▼                       ▼
┌─────────┐           ┌─────────┐           ┌─────────┐
│ Level 3 │           │ Level 6 │           │ Level 9 │
│ Deploy  │──────────▶│  Time   │──────────▶│Database │
│  ment   │           │  Sync   │           │  I/O    │
└─────────┘           └─────────┘           └─────────┘
```

### 4.2 Diagnostic Levels Detail 诊断层详解

#### Level 1: Restart Time Analysis 重启时间分析

**检查项:**
- 系统最后启动时间 (uptime -s)
- 系统运行时长（小时）
- 服务启动时间（PID文件修改时间）
- 服务运行时长
- 近期重启次数 (last reboot)

**警告条件:**
```python
if System_Uptime < 24 hours:
    Warning: "System restarted recently"
```

**输出示例:**
```json
{
  "status": "HEALTHY",
  "system_last_boot": "2025-12-10T06:30:00",
  "system_uptime_hours": 82.5,
  "service_start": "2025-12-10T07:00:00",
  "service_uptime_hours": 82.0,
  "recent_reboots": 1
}
```

#### Level 2: Maintenance Level Assessment 维护级别评估

**检查项:**
- Systemd服务启用状态 (systemctl is-enabled)
- 启动日志大小 (logs/startup.log)
- 启动日志最后更新时间

**指标:**
```python
systemd_service_enabled: bool
startup_log_size_mb: float
startup_log_age_hours: float
```

**输出示例:**
```json
{
  "status": "HEALTHY",
  "systemd_service_enabled": true,
  "startup_log_size_mb": 2.34,
  "startup_log_age_hours": 82.0
}
```

#### Level 3: Deployment Level Verification 部署级别验证

**检查项:**
- 摄像头配置数量 (cameras_config.json)
- 启用摄像头数量
- 人物检测模型存在性 (yolov8m.pt)
- 分类模型存在性 (waiter_customer_classifier.pt)
- ROI配置状态 (table_region_config.json)

**关键问题检测:**
```python
if not models_ok:
    Critical: "YOLO models missing from deployment"
```

**输出示例:**
```json
{
  "status": "HEALTHY",
  "cameras_configured": 10,
  "cameras_enabled": 10,
  "person_model_present": true,
  "classifier_model_present": true,
  "roi_configuration": "CONFIGURED"
}
```

#### Level 4: Monitoring Level Health 监控级别健康

**检查项:**
- 服务日志活跃度 (surveillance_service.log < 1小时)
- 日志中的健康检查记录
- 捕获进程运行状态 (pgrep capture_rtsp_streams)
- 处理进程运行状态 (pgrep batch_process_videos)
- 日志报告的状态

**警告条件:**
```python
if Log_Age > 60 minutes:
    Warning: "Monitoring logs not updating"
```

**输出示例:**
```json
{
  "status": "HEALTHY",
  "monitoring_active": true,
  "capture_process_running": true,
  "processing_process_running": false,
  "reported_capture_status": true,
  "reported_processing_status": false
}
```

#### Level 5: Orchestration Status 编排状态

**检查项:**
- 监控服务进程运行 (pgrep surveillance_service.py)
- 进程详情 (ps -p PID)
- 僵尸进程检测 (ps aux | grep defunct)

**关键问题检测:**
```python
if not service_running:
    Critical: "Surveillance service not running"

if zombie_count > 0:
    Warning: "Found N zombie processes"
```

**输出示例:**
```json
{
  "status": "HEALTHY",
  "surveillance_service_running": true,
  "service_details": "12345  1  2-04:30:15 python3 surveillance_service.py",
  "zombie_processes": 0
}
```

#### Level 6: Time Synchronization Check 时间同步检查

**检查项:**
- NTP同步状态 (timedatectl)
- NTP服务活跃状态
- 系统时区

**警告条件:**
```python
if not NTP_Synchronized:
    Warning: "NTP time synchronization not active"
```

**输出示例:**
```json
{
  "status": "HEALTHY",
  "ntp_synchronized": true,
  "ntp_service_active": true,
  "timezone": "Asia/Shanghai"
}
```

#### Level 7: Video Capture Operations 视频捕获操作

**检查项:**
- 今日视频数量 (videos/YYYYMMDD/camera_XX/)
- 今日视频总大小
- 活跃录制状态（最新文件 < 15分钟）
- 摄像头连接状态（推断）
- 是否应该在录制（根据时间段）

**录制时段判断:**
```python
# 午间时段：11:00-14:00
# 晚间时段：17:00-22:00
Current_Hour = datetime.now().hour
Should_Capture = (11 <= Current_Hour < 14) or (17 <= Current_Hour < 22)
```

**关键问题检测:**
```python
if Should_Capture and not Actively_Recording:
    Critical: "Camera should be capturing but no recent files detected"
```

**输出示例:**
```json
{
  "status": "HEALTHY",
  "today_video_count": 145,
  "today_total_size_gb": 45.2,
  "actively_recording": true,
  "latest_file_age_minutes": 2.3,
  "camera_connected": true,
  "should_be_capturing": true
}
```

#### Level 8: Video Processing Pipeline 视频处理管道

**检查项:**
- 最新处理日志 (logs/processing_*.log)
- 完成任务数 (Completed: N)
- 失败任务数 (Failed: N)
- 成功率 (Success rate: X%)
- moov atom错误数（损坏视频）
- 结果文件数量 (results/)

**状态分类:**
```python
if Success_Rate >= 80%:
    Status = "HEALTHY"
elif Success_Rate >= 50%:
    Status = "WARNING"
else:
    Status = "CRITICAL"
```

**关键问题检测:**
```python
if Moov_Errors > 10:
    Critical: "High number of corrupted video files (N moov atom errors)"

if Success_Rate == 0 and Total_Jobs > 0:
    Critical: "Video processing failing for all files"
```

**输出示例:**
```json
{
  "status": "HEALTHY",
  "last_processing_completed": 120,
  "last_processing_failed": 8,
  "success_rate_percent": 93.75,
  "last_log_age_minutes": 15.3,
  "moov_atom_errors": 3,
  "processed_results_count": 567
}
```

#### Level 9: Database I/O Audit 数据库I/O审计

**检查项:**
- 数据库文件大小 (detection_data.db)
- 数据库功能性（可连接查询）
- 会话记录数 (sessions表)
- Division状态变化数 (division_states表)
- Table状态变化数 (table_states表)
- Supabase配置状态（环境变量）
- 今日上传错误数 (errors_*.log)

**警告条件:**
```python
if not Supabase_Configured:
    Warning: "Supabase credentials not configured - cloud sync disabled"

if Session_Count == 0:
    Warning: "No processing sessions recorded in database"
```

**输出示例:**
```json
{
  "status": "HEALTHY",
  "database_size_mb": 234.56,
  "database_functional": true,
  "sessions_recorded": 456,
  "division_state_changes": 12345,
  "table_state_changes": 67890,
  "supabase_configured": true,
  "upload_errors_today": 0
}
```

### 4.3 Overall Status Determination 整体状态判定

```python
# 汇总所有层级状态
Level_Statuses = [level["status"] for level in all_levels]

# 判定逻辑
if "CRITICAL" in Level_Statuses or Critical_Issues > 0:
    Overall = "CRITICAL"
elif "ERROR" in Level_Statuses:
    Overall = "ERROR"
elif "WARNING" in Level_Statuses or Warnings > 0:
    Overall = "DEGRADED"
else:
    Overall = "HEALTHY"
```

### 4.4 Automated Recommendations 自动建议

```python
# 视频损坏问题
if "moov atom" errors detected:
    Recommend: "Investigate capture script signal handling and file finalization"

# Supabase未配置
if not Supabase_Configured:
    Recommend: "Configure SUPABASE_URL and SUPABASE_ANON_KEY for cloud backup"

# 处理成功率低
if Success_Rate < 50%:
    Recommend: "Check video corruption, model availability, GPU memory"

# 磁盘空间建议
Always:
    Recommend: "Run: python3 scripts/monitoring/check_disk_space.py --check"
```

### 4.5 Usage 使用

```bash
# 运行完整诊断
python3 comprehensive_health_check.py

# 输出包括：
# 1. 实时进度（每个层级检查）
# 2. 详细报告（终端打印）
# 3. JSON文件（logs/health_report_YYYYMMDD_HHMMSS.json）
```

### 4.6 Report Format 报告格式

**Terminal Output:**
```
================================================================================
RESTAURANT SURVEILLANCE SYSTEM - COMPREHENSIVE HEALTH CHECK
================================================================================
Timestamp: 2025-12-13T14:30:00

Running Level 1: Restart Time Analysis...
Running Level 2: Maintenance Assessment...
...

================================================================================
EXECUTIVE SUMMARY
================================================================================
Overall Status: DEGRADED
Timestamp: 2025-12-13T14:30:00

================================================================================
LEVEL-BY-LEVEL ASSESSMENT
================================================================================

✓ 1 Restart Time: HEALTHY
  - system_last_boot: 2025-12-10T06:30:00
  - system_uptime_hours: 82.5
  ...

⚠ 4 Monitoring Health: WARNING
  - monitoring_active: false
  - last_update: 2 hours ago
  ...

================================================================================
CRITICAL ISSUES
================================================================================
✗ Surveillance service not running

================================================================================
WARNINGS
================================================================================
⚠ Monitoring logs not updating (last update >1h ago)
⚠ Found 2 zombie processes

================================================================================
RECOMMENDATIONS
================================================================================
1. Run disk space monitoring: python3 scripts/monitoring/check_disk_space.py
2. Configure Supabase credentials for cloud backup
...

================================================================================
END OF HEALTH REPORT
================================================================================

Report saved to: logs/health_report_20251213_143000.json
```

**JSON Output:**
```json
{
  "timestamp": "2025-12-13T14:30:00",
  "overall_status": "DEGRADED",
  "levels": {
    "1_restart_time": { ... },
    "2_maintenance": { ... },
    ...
  },
  "critical_issues": [
    "Surveillance service not running"
  ],
  "warnings": [
    "Monitoring logs not updating"
  ],
  "recommendations": [
    "Run disk space monitoring: ..."
  ]
}
```

---

## 5. Automation Integration 自动化集成

### 5.1 Cron Jobs Cron任务集成

```bash
# Hourly disk space check (changed from 2-hour to 1-hour for better prediction)
0 * * * * /usr/bin/python3 /path/to/scripts/monitoring/check_disk_space.py --cleanup >> /path/to/logs/disk_monitor.log 2>&1

# Daily health check
0 6 * * * /usr/bin/python3 /path/to/scripts/monitoring/system_health.py >> /path/to/logs/daily_health.log 2>&1

# Weekly comprehensive diagnostic
0 3 * * 0 /usr/bin/python3 /path/to/scripts/monitoring/comprehensive_health_check.py >> /path/to/logs/weekly_diagnostic.log 2>&1
```

### 5.2 Systemd Integration Systemd集成

```bash
# Pre-start health check in systemd service
ExecStartPre=/usr/bin/python3 /path/to/scripts/monitoring/system_health.py

# Post-start GPU monitoring
ExecStartPost=/usr/bin/python3 /path/to/scripts/monitoring/monitor_gpu.py
```

### 5.3 Alert Integration 告警集成

```bash
# Email alert on critical disk space
if [ $? -eq 2 ]; then
    echo "CRITICAL: Disk space critically low" | mail -s "Surveillance Alert" admin@example.com
fi

# Telegram/Slack webhook notification
curl -X POST https://api.telegram.org/bot.../sendMessage \
  -d chat_id=... \
  -d text="GPU temperature critical: 87°C"
```

---

## 6. Performance Characteristics 性能特征

### 6.1 Execution Times 执行时间

```python
check_disk_space.py:
  - Basic check: ~0.5s
  - With prediction: ~30.5s (30s observation)
  - Full cleanup: 1-5 minutes (depends on file count)

monitor_gpu.py:
  - Single check: ~0.1s
  - Watch mode: continuous

system_health.py:
  - Full check: ~2-3s

comprehensive_health_check.py:
  - Full diagnostic: ~10-15s
```

### 6.2 Resource Usage 资源使用

```python
CPU: < 1% (除了文件遍历期间)
Memory: < 50MB
Disk I/O: 读取密集（遍历文件树）
Network: 无（除非配置告警）
```

---

## 7. Troubleshooting 故障排查

### 7.1 Common Issues 常见问题

**Problem: Prediction shows "too low to predict"**
```
原因：录制未开始或磁盘使用速率极低
解决：正常现象，录制开始后会有准确预测
```

**Problem: "Cannot store even 1 day of videos"**
```
原因：磁盘严重不足
解决：
  1. 手动删除旧视频：rm -rf videos/20251201/
  2. 检查处理结果是否可删除：rm -rf results/20251201/
  3. 增加磁盘容量
```

**Problem: GPU not available**
```
原因：nvidia-smi未安装或GPU驱动问题
解决：
  1. 检查驱动：nvidia-smi
  2. 重新安装驱动：sudo apt install nvidia-driver-XXX
  3. Mac系统上正常（无NVIDIA GPU）
```

**Problem: Comprehensive check shows all ERROR**
```
原因：Base directory路径硬编码不匹配
解决：修改comprehensive_health_check.py中的base_dir变量
```

### 7.2 Debug Mode 调试模式

```bash
# Dry run cleanup (不删除文件)
python3 check_disk_space.py --cleanup --dry-run

# Verbose output
python3 check_disk_space.py --predict  # 显示详细预测

# Test single level in comprehensive check
# (编辑脚本，注释掉其他check_level_X()调用)
```

---

## 8. Best Practices 最佳实践

### 8.1 Monitoring Strategy 监控策略

```
每小时 (Hourly):
  ├─ check_disk_space.py --cleanup  # 预测性清理
  └─ monitor_gpu.py                 # GPU温度检查

每天 (Daily):
  ├─ system_health.py               # 基础健康检查
  └─ Disk usage trend analysis      # 磁盘使用趋势

每周 (Weekly):
  └─ comprehensive_health_check.py  # 深度诊断

每月 (Monthly):
  └─ Review health report JSONs     # 审查历史报告
```

### 8.2 Alert Thresholds 告警阈值

```python
# Disk Space
WARNING:  < 150GB or prediction shows shortage
CRITICAL: < 80GB (1 day capacity)

# GPU Temperature
WARNING:  70-80°C
CRITICAL: > 80°C

# Processing Success Rate
WARNING:  50-80%
CRITICAL: < 50%

# Video Capture
WARNING:  Latest file > 15 minutes old (during recording hours)
CRITICAL: No files in recording window
```

### 8.3 Maintenance Schedule 维护计划

```
每天:
  - 查看磁盘空间状态
  - 检查GPU温度日志

每周:
  - 审查comprehensive health报告
  - 清理30天前截图
  - 验证数据库大小增长

每月:
  - 审查磁盘使用趋势
  - 优化保留策略
  - 更新监控阈值（如需要）
```

---

## 9. Integration with Main System 主系统集成

### 9.1 Called by Surveillance Service 被监控服务调用

```python
# surveillance_service.py 在启动前检查
result = subprocess.run([
    sys.executable,
    PROJECT_DIR / "scripts/monitoring/system_health.py"
])
if result.returncode != 0:
    logger.error("Pre-flight health check failed")
    # 继续启动或退出（根据配置）
```

### 9.2 Called by Deployment Scripts 被部署脚本调用

```bash
# deploy.sh
echo "Running pre-deployment health check..."
python3 scripts/monitoring/system_health.py
if [ $? -ne 0 ]; then
    echo "Health check failed, aborting deployment"
    exit 1
fi
```

### 9.3 Log File Locations 日志文件位置

```
logs/
├── disk_monitor.log           # Disk space检查日志
├── gpu_monitor.log            # GPU监控日志
├── daily_health.log           # 每日健康检查
├── health_report_*.json       # 综合诊断JSON报告
└── startup.log                # 服务启动日志（被Level 2读取）
```

---

## 10. Version History 版本历史

### check_disk_space.py

- **v2.1.0** (2025-11-20): 原始视频>=2天无条件删除，移除"已处理"检查
- **v2.0.0** (2025-11-16): 添加智能预测、30秒速率观测、主动清理
- **v1.0.0**: 基础磁盘空间检查和清理

### monitor_gpu.py

- **v1.0.0** (2025-11-14): 初始版本，nvidia-smi查询和温度告警

### system_health.py

- **v1.0.0** (2025-11-14): 5项基础健康检查

### comprehensive_health_check.py

- **v1.0.0** (2025-11-20): 9层诊断系统，JSON报告输出

---

## 11. Future Enhancements 未来增强

### Planned Features 计划功能

```
1. Machine Learning Prediction 机器学习预测
   - 基于历史数据预测磁盘使用模式
   - 异常检测（突然的使用激增）

2. Network Monitoring 网络监控
   - RTSP连接质量监控
   - 网络带宽使用
   - Packet loss检测

3. Advanced GPU Metrics GPU高级指标
   - GPU memory fragmentation
   - CUDA kernel execution time
   - Power consumption tracking

4. Automated Remediation 自动修复
   - 自动重启失败服务
   - 自动清理临时文件
   - 自动调整处理并发度

5. Dashboard Integration 仪表板集成
   - Grafana可视化
   - 实时告警面板
   - 历史趋势图表
```

---

## 12. API Reference API参考

### check_disk_space.py

```python
# Functions
get_disk_usage(path) -> dict
  # Returns: {total_gb, used_gb, free_gb, used_percent}

measure_disk_usage_speed(observation_seconds) -> dict
  # Returns: {gb_per_hour, gb_per_second, initial_used_gb, final_used_gb, delta_gb}

predict_space_needed(usage_rate_gb_per_hour, remaining_hours) -> dict
  # Returns: {predicted_usage_gb, predicted_free_gb, safe, status, message}

smart_cleanup(target_free_gb, dry_run=False) -> float
  # Returns: GB freed

# CLI Arguments
--check              # Check only (default)
--cleanup            # Check and cleanup
--predict            # Show predictions
--min-space N        # Custom threshold (GB)
--dry-run            # Simulate cleanup
--no-prediction      # Disable prediction
```

### monitor_gpu.py

```python
# Functions
check_nvidia_smi() -> bool
get_gpu_stats() -> dict
  # Returns: {temperature, utilization, memory_used, memory_total, memory_percent, name}

print_gpu_status(stats, temp_threshold) -> int
  # Returns: Exit code (0=ok, 1=hot, 2=no GPU)

# CLI Arguments
--watch SECONDS      # Continuous monitoring
--alert TEMP         # Custom temperature threshold
```

### system_health.py

```python
# Functions
check_disk_space() -> bool
check_gpu() -> bool
check_directories() -> bool
check_models() -> bool
check_configs() -> bool

# No CLI arguments (runs all checks)
```

### comprehensive_health_check.py

```python
# Class: SurveillanceHealthChecker
__init__()
check_level_1_restart_time()
check_level_2_maintenance()
check_level_3_deployment()
check_level_4_monitoring()
check_level_5_orchestration()
check_level_6_time_sync()
check_level_7_video_capture()
check_level_8_processing_pipeline()
check_level_9_database_io()
determine_overall_status()
generate_recommendations()
run_full_diagnostic() -> dict
print_report()

# Report Structure
{
  "timestamp": str,
  "overall_status": str,  # HEALTHY/DEGRADED/ERROR/CRITICAL
  "levels": {
    "1_restart_time": { ... },
    ...
  },
  "critical_issues": [str],
  "warnings": [str],
  "recommendations": [str]
}
```

---

## Summary 总结

监控系统提供四层监控能力：

1. **Intelligent Disk Management** - 预测性磁盘空间管理，30秒速率观测 + 未来空间预测
2. **GPU Health Tracking** - 实时GPU温度、利用率、显存监控
3. **Basic System Health** - 快速5项健康检查（目录、模型、配置、磁盘、GPU）
4. **Comprehensive Diagnostics** - 9层深度诊断，覆盖从系统重启到数据库I/O

**Key Innovations:**
- 预测性清理（提前清理，避免录制期间空间不足）
- 智能保留策略（数据库永久，视频2天，截图30天）
- 多层诊断架构（9个层级，全面覆盖系统健康）
- 自动建议生成（根据诊断结果提供可操作建议）

**Production Ready:**
- Cron集成（每小时磁盘检查，每日健康检查）
- Systemd集成（启动前健康检查）
- 告警机制（退出码 + 日志 + 可选邮件/Telegram）
- 干运行模式（测试不影响生产）
