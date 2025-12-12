# Database Sync Documentation

**Version:** 1.0.0
**Last Updated:** 2025-12-13
**Purpose:** 本地SQLite数据库批量写入与Supabase云端同步策略

---

## Overview | 系统概述

本目录包含两个核心脚本，解决实时视频处理中的两大性能瓶颈：

1. **`batch_db_writer.py`** - 批量写入优化（100×性能提升）
2. **`sync_to_supabase.py`** - 增量云端同步（数据库记录only，不含媒体文件）

### Architecture Philosophy | 架构哲学

```
┌──────────────────────────────────────────────────────────────────┐
│         Edge Processing (RTX 3060 Local Machine)                 │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  [Video Processing] ──► [Batch Writer] ──► [SQLite Buffer]     │
│        5 FPS              100 records        24h retention       │
│                          per commit                              │
│                                                                  │
│                            ▼                                     │
│                                                                  │
│                    [Hourly Sync Job]                            │
│                    (Cron triggered)                             │
│                            │                                     │
└────────────────────────────┼────────────────────────────────────┘
                             │
                   Upload new records only
                   (last 2 hours window)
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────┐
│         Cloud Analytics (Supabase PostgreSQL)                    │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ASE_division_states  →  Permanent business analytics           │
│  ASE_table_states     →  Multi-location dashboards              │
│  ASE_sessions         →  Historical trend analysis              │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

**设计原则 (Design Principles):**
- **Local = Fast Transactional Buffer** (SQLite, 24h retention)
- **Cloud = Permanent Analytics Storage** (Supabase, 90 days)
- **No Media Sync** (Database records only, 媒体文件不上传)
- **Network Fault Tolerance** (断网自动重试，下次同步补上)

---

## Script 1: batch_db_writer.py

### Purpose | 用途

**Problem (问题):**
视频处理过程中每检测到一次状态变化就立即commit到数据库，导致：
- 45,000次状态变化 = 45,000次commit = 37分钟写入时间
- SQLite事务开销成为性能瓶颈
- 影响实时处理速度

**Solution (解决方案):**
内存缓冲区批量提交，100条记录一次commit：
- 45,000次状态变化 = 450次批量commit = 22秒写入时间
- **100× performance improvement (性能提升100倍)**

### Algorithm | 算法原理

#### Batch Write Strategy | 批量写入策略

```python
# 原始方式 (Naive Approach)
for state_change in detections:
    cursor.execute("INSERT INTO division_states ...")
    conn.commit()  # ❌ 每条记录commit一次 = 慢

# 批量优化 (Batch Optimization)
buffer = []
for state_change in detections:
    buffer.append(state_change_tuple)

    if len(buffer) >= BATCH_SIZE:  # Default: 100
        cursor.executemany("INSERT ...", buffer)
        conn.commit()  # ✅ 100条记录commit一次 = 快
        buffer.clear()

# 最后flush剩余记录
if buffer:
    cursor.executemany("INSERT ...", buffer)
    conn.commit()
```

#### Why It's 100× Faster | 为什么快100倍

**SQLite Transaction Overhead (事务开销):**

| Operation | Per-Record Commit | Batch Commit (100) |
|-----------|------------------|-------------------|
| **BEGIN transaction** | 45,000次 | 450次 |
| **Disk sync (fsync)** | 45,000次 | 450次 |
| **Journal operations** | 45,000次 | 450次 |
| **COMMIT transaction** | 45,000次 | 450次 |
| **Total time** | 37 minutes | 22 seconds |

**关键优化点:**
1. **Disk I/O reduction** - fsync是慢速操作，减少100倍调用
2. **Journal consolidation** - 一次事务写入多条记录
3. **Lock contention** - 减少数据库锁竞争

### Usage | 使用方法

```python
from batch_db_writer import BatchDatabaseWriter

# Initialize batch writer
db_writer = BatchDatabaseWriter(conn, batch_size=100)

# During video processing (在处理循环中)
for frame in video_frames:
    detections = detect_state_changes(frame)

    for div_state in division_state_changes:
        db_writer.add_division_state(
            session_id=session_id,
            camera_id=camera_id,
            location_id=location_id,
            frame_number=frame_number,
            timestamp_video=timestamp,
            timestamp_recorded=datetime.now(),
            state="GREEN",  # RED / YELLOW / GREEN
            walking_waiters=2,
            service_waiters=1,
            screenshot_path="/path/to/screenshot.jpg"
        )

    for table_state in table_state_changes:
        db_writer.add_table_state(
            session_id=session_id,
            camera_id=camera_id,
            location_id=location_id,
            frame_number=frame_number,
            timestamp_video=timestamp,
            timestamp_recorded=datetime.now(),
            table_id="T1",
            state="BUSY",  # IDLE / BUSY / CLEANING
            customers_count=4,
            waiters_count=0,
            screenshot_path="/path/to/screenshot.jpg"
        )

# At end of processing (处理结束时)
db_writer.flush_all()  # ⚠️ Critical: 提交剩余buffer中的记录
stats = db_writer.get_stats()
print(f"Total commits: {stats['total_commits']}")
```

### Configuration | 配置参数

```python
# Default configuration
BATCH_SIZE = 100  # Records per commit (每批提交的记录数)

# Tuning recommendations (调优建议):
# - Small batch (10-50): Lower memory, more commits
# - Medium batch (100-200): Balanced (recommended)
# - Large batch (500-1000): Higher memory, fewer commits
#   ⚠️ Large batches risk data loss if crash before flush
```

### Statistics Tracking | 统计信息

```python
stats = db_writer.get_stats()
# Returns:
{
    'total_division_inserts': 25000,   # 总division记录数
    'total_table_inserts': 20000,      # 总table记录数
    'total_commits': 450,               # 总提交次数
    'pending_division': 23,             # Buffer中待提交division
    'pending_table': 15,                # Buffer中待提交table
    'avg_batch_size': 100.0             # 平均每批记录数
}

db_writer.print_stats()  # Pretty print
```

### Critical Warning | 关键警告

⚠️ **MUST call `flush_all()` at end of processing**
如果处理过程中断（crash/kill）且未调用`flush_all()`，buffer中的记录会丢失！

**Best Practice:**
```python
try:
    # Video processing loop
    for frame in frames:
        db_writer.add_division_state(...)
finally:
    db_writer.flush_all()  # ✅ 确保所有记录写入
```

---

## Script 2: sync_to_supabase.py

### Purpose | 用途

**Problem (问题):**
本地SQLite数据库需要定期同步到Supabase云端，但：
- 不能每条记录都立即上传（网络开销大）
- 不能全量上传（重复数据，浪费流量）
- 需要处理网络故障和重试

**Solution (解决方案):**
增量同步策略 + 标记机制：
- **Hourly sync** - 每小时上传新记录（last 2 hours window）
- **Incremental upload** - 只上传`synced_to_cloud=0`的记录
- **Local cleanup** - 上传成功后删除24小时前的本地记录
- **Retry queue** - 网络故障时下次自动重试

### Sync Strategy | 同步策略

#### Two Sync Modes | 两种同步模式

**1. Hourly Sync (每小时增量同步)**

```bash
# Cron job (每小时触发)
0 * * * * python3 sync_to_supabase.py --mode hourly
```

```
Time Window: Last 2 hours (2小时窗口，有重叠保险)
Records: WHERE synced_to_cloud = 0 AND created_at >= NOW() - 2h
Purpose: 正常运营期间的实时同步
```

**2. Full Sync (全量同步 - 故障恢复)**

```bash
# Manual or after network outage (手动或网络恢复后)
python3 sync_to_supabase.py --mode full
```

```
Time Window: All unsynced (所有未同步记录)
Records: WHERE synced_to_cloud = 0
Purpose: 网络故障后补全缺失数据
```

#### Incremental Sync Algorithm | 增量同步算法

```
┌─────────────────────────────────────────────────────────────┐
│  Step 1: Query Unsynced Records (查询未同步记录)            │
├─────────────────────────────────────────────────────────────┤
│  SELECT * FROM division_states                              │
│  WHERE synced_to_cloud = 0                                  │
│    AND created_at >= NOW() - 2 hours  (hourly mode only)   │
└─────────────────────────────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 2: Upload in Batches (批量上传)                        │
├─────────────────────────────────────────────────────────────┤
│  BATCH_SIZE = 1000 records per batch                        │
│                                                              │
│  for batch in chunks(records, 1000):                        │
│      transformed = [transform(r) for r in batch]            │
│      supabase.table('ASE_division_states').insert(...)      │
│      mark_as_synced(batch)  # Update local DB               │
└─────────────────────────────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 3: Mark as Synced (标记已同步)                         │
├─────────────────────────────────────────────────────────────┤
│  UPDATE division_states                                      │
│  SET synced_to_cloud = 1                                    │
│  WHERE division_state_id IN (uploaded_ids)                  │
└─────────────────────────────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────┐
│  Step 4: Cleanup Old Synced Data (清理旧数据)               │
├─────────────────────────────────────────────────────────────┤
│  DELETE FROM division_states                                │
│  WHERE synced_to_cloud = 1                                  │
│    AND created_at < NOW() - 24 hours                        │
│                                                              │
│  Keeps 24h local buffer for safety (保留24小时本地缓冲)     │
└─────────────────────────────────────────────────────────────┘
```

### Data Transformation | 数据转换

#### SQLite → Supabase Schema Mapping

**Division States:**

```python
# SQLite Row (本地)
{
    'division_state_id': 12345,           # 本地主键 (不上传)
    'session_id': '20251213_143000_camera_35',
    'camera_id': 'camera_35',
    'location_id': 'mianyang_yebailinghotpot_1958commercialdistrict',
    'frame_number': 1500,
    'timestamp_video': 300.5,
    'timestamp_recorded': '2025-12-13 14:35:00',
    'state': 'GREEN',
    'walking_area_waiters': 2,
    'service_area_waiters': 1,
    'total_staff': 3,
    'screenshot_path': '/path/to/local/screenshot.jpg',  # 本地路径 (不上传)
    'synced_to_cloud': 0,                 # 同步标记 (不上传)
    'created_at': '2025-12-13 14:35:01'   # 本地创建时间 (不上传)
}

# Transformed for Supabase (云端)
{
    # division_state_id 由Supabase自动生成 (SERIAL)
    'session_id': '20251213_143000_camera_35',
    'camera_id': 'camera_35',
    'location_id': 'mianyang_yebailinghotpot_1958commercialdistrict',
    'frame_number': 1500,
    'timestamp_video': 300.5,
    'timestamp_recorded': '2025-12-13 14:35:00',
    'state': 'GREEN',
    'walking_area_waiters': 2,
    'service_area_waiters': 1,
    'total_staff': 3
    # screenshot_path 不包含在云端 (媒体文件不上传)
    # created_at 由Supabase自动填充
}
```

**Table States:**

```python
# SQLite → Supabase (similar structure)
{
    'session_id': '20251213_143000_camera_35',
    'camera_id': 'camera_35',
    'location_id': 'mianyang_yebailinghotpot_1958commercialdistrict',
    'frame_number': 1500,
    'timestamp_video': 300.5,
    'timestamp_recorded': '2025-12-13 14:35:00',
    'table_id': 'T1',
    'state': 'BUSY',
    'customers_count': 4,
    'waiters_count': 0
    # screenshot_path omitted (不上传截图路径)
}
```

**Key Points:**
- ✅ **Primary keys** - Supabase用SERIAL自动生成，不传local ID
- ❌ **Screenshots** - 路径不上传，媒体文件保留本地
- ❌ **Sync flags** - `synced_to_cloud`仅本地使用
- ✅ **Timestamps** - 业务时间戳正常上传

### Conflict Resolution | 冲突解决

#### Duplicate Prevention | 防止重复上传

**Scenario (场景):**
手动full sync + 定时hourly sync同时运行，可能重复上传

**Solution (解决方案):**

```python
# 1. Local flag prevents duplicate queries (本地标记防止重查)
WHERE synced_to_cloud = 0  # 已上传的记录不会再查询

# 2. Supabase unique constraints prevent duplicate inserts
# Supabase schema中的UNIQUE约束防止重复插入:
UNIQUE(session_id, camera_id, frame_number, table_id)  # Table states
UNIQUE(session_id, camera_id, frame_number)            # Division states

# 3. Error handling: Ignore duplicate key errors
try:
    supabase.table('ASE_division_states').insert(batch)
except Exception as e:
    if "duplicate key" in str(e):
        # Already uploaded, mark as synced (已存在，直接标记)
        mark_as_synced(batch)
    else:
        # Real error, log and retry later (真实错误，记录并重试)
        log_error(e)
```

#### Network Failure Handling | 网络故障处理

**Tolerance Strategy (容错策略):**

```
┌─────────────────────────────────────────────────────────────┐
│  Batch Upload with Per-Batch Error Handling                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  for i in range(0, len(records), BATCH_SIZE):              │
│      batch = records[i:i+BATCH_SIZE]                       │
│                                                             │
│      try:                                                   │
│          supabase.table(...).insert(batch)                 │
│          mark_as_synced(batch)  # ✅ 成功标记               │
│                                                             │
│      except NetworkError:                                  │
│          log_error(f"Batch {i} failed")                    │
│          continue  # ⚠️ 继续处理下一批，不全部失败          │
│                                                             │
│  Result:                                                    │
│  - Partial success: 部分批次成功上传                        │
│  - Failed batches: 保持synced_to_cloud=0                   │
│  - Next sync: 自动重试失败的记录                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Why Not Fail Fast? (为什么不立即失败)**
- 网络抖动可能只影响部分请求
- 成功上传的批次不需要重传（节省流量）
- 失败批次下次自动重试（最终一致性）

### Usage | 使用方法

#### Command Line

```bash
# Hourly sync (2-hour window, recommended for cron)
python3 sync_to_supabase.py --mode hourly

# Full sync (all unsynced records, after network outage)
python3 sync_to_supabase.py --mode full

# Dry run (test without actual upload)
python3 sync_to_supabase.py --mode hourly --dry-run
```

#### Environment Variables | 环境变量

```bash
# Required (必须配置)
export SUPABASE_URL="https://wdpeoyugsxqnpwwtkqsl.supabase.co"
export SUPABASE_ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

# Add to ~/.bashrc or /etc/environment
```

#### Cron Job Setup | 定时任务配置

```bash
# Hourly sync during operating + processing hours
# 每小时同步 (11:00 AM - 11:00 PM)
0 11-23 * * * cd /path/to/production/RTX_3060/scripts/database_sync && python3 sync_to_supabase.py --mode hourly >> /var/log/ase_sync.log 2>&1

# Full sync at 3 AM (catch any missed records)
# 凌晨3点全量同步（捕获遗漏记录）
0 3 * * * cd /path/to/production/RTX_3060/scripts/database_sync && python3 sync_to_supabase.py --mode full >> /var/log/ase_sync.log 2>&1
```

### Configuration | 配置参数

```python
# Database location
DB_PATH = PROJECT_ROOT / "db" / "detection_data.db"

# Upload batch size (上传批次大小)
BATCH_SIZE = 1000  # Records per HTTP request

# Local retention (本地保留期)
RETENTION_HOURS = 24  # Keep synced data for 24h before cleanup

# Time windows (时间窗口)
HOURLY_WINDOW = 2  # Hours (2小时重叠窗口)
```

### Monitoring | 监控

#### Sync Status Table | 同步状态表

```sql
-- Check recent sync operations (查看最近同步记录)
SELECT sync_type, last_sync_time, records_synced, status, error_message
FROM sync_status
ORDER BY last_sync_time DESC
LIMIT 10;

-- Example output:
┌──────────────────┬─────────────────────┬─────────────────┬─────────┬───────────────┐
│ sync_type        │ last_sync_time      │ records_synced  │ status  │ error_message │
├──────────────────┼─────────────────────┼─────────────────┼─────────┼───────────────┤
│ hourly           │ 2025-12-13 15:00:00 │ 2345           │ success │ NULL          │
│ hourly           │ 2025-12-13 14:00:00 │ 1987           │ success │ NULL          │
│ hourly           │ 2025-12-13 13:00:00 │ 2103           │ partial │ 2 batch errors│
│ full             │ 2025-12-13 03:00:00 │ 45678          │ success │ NULL          │
└──────────────────┴─────────────────────┴─────────────────┴─────────┴───────────────┘
```

#### Check Unsynced Records | 检查未同步记录

```sql
-- Count pending records (待上传记录数)
SELECT 'division_states' as table_name, COUNT(*) as pending_count
FROM division_states
WHERE synced_to_cloud = 0

UNION ALL

SELECT 'table_states', COUNT(*)
FROM table_states
WHERE synced_to_cloud = 0;

-- Example output:
┌──────────────────┬───────────────┐
│ table_name       │ pending_count │
├──────────────────┼───────────────┤
│ division_states  │ 234           │  # ⚠️ If large, check network/logs
│ table_states     │ 567           │
└──────────────────┴───────────────┘
```

#### Log Files | 日志文件

```bash
# View sync logs
tail -f /var/log/ase_sync.log

# Example log output:
# 2025-12-13 15:00:01 - ⏰ Hourly Sync Mode
# 2025-12-13 15:00:01 - 📍 Location: mianyang_yebailinghotpot_1958commercialdistrict
# 2025-12-13 15:00:02 - 📹 Syncing video metadata...
# 2025-12-13 15:00:02 -    No videos to sync
# 2025-12-13 15:00:03 - 🎬 Syncing sessions...
# 2025-12-13 15:00:03 -    ✅ Synced 3 sessions
# 2025-12-13 15:00:05 - 🔴🟡🟢 Syncing division states...
# 2025-12-13 15:00:05 -    Uploaded 1000/2345...
# 2025-12-13 15:00:07 -    Uploaded 2000/2345...
# 2025-12-13 15:00:08 -    ✅ Synced 2345 division state changes
# 2025-12-13 15:00:10 - 📊 Syncing table states...
# 2025-12-13 15:00:12 -    ✅ Synced 1987 table state changes
# 2025-12-13 15:00:13 - 🗑️  Cleaning up synced data older than 24h...
# 2025-12-13 15:00:13 -    Deleted 3456 division states
# 2025-12-13 15:00:13 -    Deleted 2789 table states
# 2025-12-13 15:00:14 - ✅ Sync completed successfully!
```

---

## Data Flow Summary | 数据流总结

### Complete Pipeline | 完整流程

```
┌────────────────────────────────────────────────────────────────┐
│  1. Video Processing (实时处理)                                 │
├────────────────────────────────────────────────────────────────┤
│  Process video at 5 FPS                                        │
│  Detect state changes (debounce: 1s)                           │
│  ├─► Division state change → BatchWriter.add_division_state() │
│  └─► Table state change → BatchWriter.add_table_state()       │
│                                                                 │
│  Performance: 3.24× real-time processing                       │
└────────────────────────────────────────────────────────────────┘
                          ▼ Auto-flush every 100 records
┌────────────────────────────────────────────────────────────────┐
│  2. Batch Database Write (批量写入)                             │
├────────────────────────────────────────────────────────────────┤
│  Buffer: In-memory queue (100 records)                         │
│  Commit: executemany() + conn.commit()                         │
│  Speed: 100× faster than per-record commits                    │
│                                                                 │
│  Result: division_states (synced_to_cloud = 0)                 │
│          table_states (synced_to_cloud = 0)                    │
└────────────────────────────────────────────────────────────────┘
                          ▼ Hourly (cron)
┌────────────────────────────────────────────────────────────────┐
│  3. Incremental Cloud Sync (增量云端同步)                        │
├────────────────────────────────────────────────────────────────┤
│  Query: WHERE synced_to_cloud = 0 AND created_at >= NOW()-2h  │
│  Upload: 1000 records per batch to Supabase                    │
│  Mark: SET synced_to_cloud = 1                                 │
│                                                                 │
│  Network failure: Continue with next batch (partial success)   │
│  Duplicate detection: Unique constraints prevent re-upload     │
└────────────────────────────────────────────────────────────────┘
                          ▼ After successful sync
┌────────────────────────────────────────────────────────────────┐
│  4. Local Cleanup (本地清理)                                     │
├────────────────────────────────────────────────────────────────┤
│  DELETE FROM division_states                                   │
│  WHERE synced_to_cloud = 1 AND created_at < NOW() - 24h       │
│                                                                 │
│  Result: SQLite database keeps 24h buffer only                 │
│          Supabase has permanent copy (90 days retention)       │
└────────────────────────────────────────────────────────────────┘
```

### Storage Lifecycle | 存储生命周期

| Time | Local SQLite | Supabase Cloud | Description |
|------|--------------|----------------|-------------|
| **T+0** | ✅ Written (synced=0) | ❌ Not yet | 实时处理写入本地 |
| **T+1h** | ✅ Exists (synced=1) | ✅ Uploaded | 每小时同步到云端 |
| **T+24h** | ❌ Deleted | ✅ Exists | 本地清理，云端保留 |
| **T+90d** | ❌ Deleted | ⚠️ Archive? | 云端可能归档或清理 |

**Key Insight (关键理解):**
本地SQLite是**24小时滚动缓冲区**，云端Supabase是**永久业务数据库**

---

## Performance Characteristics | 性能特征

### Batch Writer Performance | 批量写入性能

| Metric | Per-Record Commit | Batch Commit (100) | Improvement |
|--------|------------------|-------------------|-------------|
| **Total inserts** | 45,000 | 45,000 | - |
| **Total commits** | 45,000 | 450 | **100×** |
| **Disk syncs (fsync)** | 45,000 | 450 | **100×** |
| **Write time** | 37 minutes | 22 seconds | **100×** |
| **Throughput** | 20 records/sec | 2,045 records/sec | **100×** |

**Bottleneck Analysis:**
- ❌ **Before:** SQLite transaction overhead (fsync every record)
- ✅ **After:** Minimal transaction overhead (fsync every 100 records)

### Sync Performance | 同步性能

**Typical Hourly Sync (1 camera, 1 hour footage):**

```
Video processing: 1 hour footage → ~3,000 state changes
Batch upload: 3,000 records ÷ 1000 per batch = 3 HTTP requests
Network time: ~3-5 seconds total (stable network)
Database cleanup: ~1 second
Total sync time: <10 seconds
```

**Full Sync After 8-Hour Network Outage:**

```
Unsynced records: 8 hours × 3,000/hour = 24,000 records
Batch upload: 24,000 ÷ 1000 = 24 HTTP requests
Network time: ~30-40 seconds
Database cleanup: ~2 seconds
Total sync time: <60 seconds
```

**Network Bandwidth:**

```
Average record size: ~200 bytes (JSON payload)
Hourly upload: 3,000 records × 200 bytes = 600 KB
Daily upload: 7.5 hours × 600 KB = 4.5 MB/day/camera
Monthly upload: 4.5 MB × 30 days = 135 MB/month/camera

Conclusion: 网络流量极小，完全可接受
```

---

## Troubleshooting | 故障排查

### Issue 1: Batch Writer Not Flushing | 批量写入未提交

**Symptoms (症状):**
- 数据库中记录数少于预期
- 处理结束后buffer中有pending记录

**Diagnosis (诊断):**
```python
stats = db_writer.get_stats()
print(stats)
# {'pending_division': 45, 'pending_table': 23}  # ⚠️ Should be 0
```

**Solution (解决):**
```python
# Always call flush_all() at end
try:
    # Processing loop
    for frame in frames:
        db_writer.add_division_state(...)
finally:
    db_writer.flush_all()  # ✅ Critical
```

### Issue 2: Sync Fails with "Network Error" | 网络错误

**Symptoms (症状):**
```bash
# Log shows:
❌ Upload failed for batch 1: Network timeout
❌ Upload failed for batch 2: Connection refused
```

**Diagnosis (诊断):**
```bash
# Check network connectivity
ping supabase.co

# Check Supabase endpoint
curl https://wdpeoyugsxqnpwwtkqsl.supabase.co

# Check environment variables
echo $SUPABASE_URL
echo $SUPABASE_ANON_KEY
```

**Solution (解决):**
```bash
# 1. Network restored → automatic retry on next cron
# 2. Large backlog → manual full sync
python3 sync_to_supabase.py --mode full

# 3. Check unsynced count
sqlite3 ../db/detection_data.db "SELECT COUNT(*) FROM division_states WHERE synced_to_cloud = 0"
```

### Issue 3: Duplicate Key Error | 重复键错误

**Symptoms (症状):**
```
❌ Upload failed: duplicate key value violates unique constraint
```

**Diagnosis (诊断):**
```sql
-- Check if already in Supabase
SELECT * FROM ASE_division_states
WHERE session_id = '20251213_143000_camera_35'
  AND frame_number = 1500;
```

**Solution (解决):**
```bash
# This is usually safe to ignore (data already uploaded)
# Mark local records as synced:
python3 -c "
import sqlite3
conn = sqlite3.connect('../db/detection_data.db')
conn.execute('UPDATE division_states SET synced_to_cloud = 1 WHERE session_id = ?', ['20251213_143000_camera_35'])
conn.commit()
"
```

### Issue 4: Local Database Growing Too Large | 本地数据库膨胀

**Symptoms (症状):**
```bash
du -h ../db/detection_data.db
# 15G  # ⚠️ Should be < 1GB
```

**Diagnosis (诊断):**
```sql
-- Check unsynced count
SELECT
    COUNT(*) FILTER (WHERE synced_to_cloud = 0) as unsynced,
    COUNT(*) FILTER (WHERE synced_to_cloud = 1) as synced,
    COUNT(*) as total
FROM division_states;

-- Example problem output:
┌──────────┬─────────┬─────────┐
│ unsynced │ synced  │ total   │
├──────────┼─────────┼─────────┤
│ 234567   │ 1234567 │ 1469134 │  # ⚠️ Too many synced records not cleaned
└──────────┴─────────┴─────────┘
```

**Solution (解决):**
```bash
# 1. Force sync unsynced records
python3 sync_to_supabase.py --mode full

# 2. Force cleanup old synced records
sqlite3 ../db/detection_data.db <<EOF
DELETE FROM division_states WHERE synced_to_cloud = 1 AND created_at < datetime('now', '-24 hours');
DELETE FROM table_states WHERE synced_to_cloud = 1 AND created_at < datetime('now', '-24 hours');
VACUUM;  -- Reclaim disk space
EOF
```

---

## Best Practices | 最佳实践

### For Batch Writer | 批量写入

1. ✅ **Always flush at end** - Use try/finally to ensure flush
2. ✅ **Monitor buffer size** - Check stats periodically
3. ✅ **Use default batch size** - 100 records is well-tested
4. ❌ **Don't increase batch too much** - Risk data loss on crash
5. ✅ **Print stats on completion** - Helps debugging

### For Cloud Sync | 云端同步

1. ✅ **Use hourly sync** - Cron job for automated operation
2. ✅ **Keep 24h local buffer** - Safety margin for retries
3. ✅ **Monitor sync_status table** - Check for failures
4. ✅ **Run full sync after outages** - Catch up missed records
5. ❌ **Don't sync too frequently** - Hourly is optimal
6. ✅ **Use dry-run for testing** - Validate before production

### For Production | 生产环境

1. ✅ **Set environment variables** - SUPABASE_URL + KEY
2. ✅ **Enable cron logging** - Redirect to /var/log/ase_sync.log
3. ✅ **Monitor disk space** - Local DB should stay < 1GB
4. ✅ **Check Supabase dashboard** - Verify data arriving
5. ✅ **Implement alerts** - Notify if sync fails repeatedly

---

## Version History | 版本历史

**1.0.0** (2025-11-15)
- ✅ Initial implementation of batch_db_writer.py
- ✅ Initial implementation of sync_to_supabase.py
- ✅ 100× performance improvement for database writes
- ✅ Hourly incremental sync to Supabase
- ✅ Network fault tolerance with partial success
- ✅ 24-hour local buffer with automatic cleanup

---

## Related Documentation | 相关文档

- **Database Schema:** [/db/database_schema.sql](../../db/database_schema.sql)
- **Cloud Architecture:** [/db/CLAUDE.md](../../db/CLAUDE.md)
- **Video Processing:** [/scripts/video_processing/CLAUDE.md](../video_processing/CLAUDE.md)
- **Deployment Guide:** [/scripts/deployment/CLAUDE.md](../deployment/CLAUDE.md)

---

**Maintained By:** ASE Development Team
**Contact:** For sync issues or performance questions, check logs first: `/var/log/ase_sync.log`
