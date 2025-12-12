# Scripts Documentation Index

**Version:** 1.3.0
**Last Updated:** 2025-12-13

This file serves as an index to detailed documentation for each script directory.

---

## Documentation Structure

```
scripts/
├── CLAUDE.md                    # This file - documentation index
├── STRUCTURE.md                 # Directory organization and navigation guide
│
├── video_processing/
│   └── CLAUDE.md               # Processing pipeline, debounce, cross-segment handling
│
├── deployment/
│   └── CLAUDE.md               # Systemd, cron jobs, configuration wizard
│
├── video_capture/
│   └── CLAUDE.md               # RTSP采集算法, 60秒分段, 多线程并发, 内存管理
│
├── orchestration/
│   └── CLAUDE.md               # (TODO) GPU scaling, queue management, scheduling
│
├── database_sync/
│   └── CLAUDE.md               # (TODO) Batch writes, Supabase sync
│
├── monitoring/
│   └── CLAUDE.md               # (TODO) Disk prediction, GPU monitoring
│
├── maintenance/
│   └── CLAUDE.md               # (TODO) Cleanup policies, retention
│
└── (other directories)         # See STRUCTURE.md for details
```

---

## Quick Links

| Directory | Documentation | Key Topics |
|-----------|---------------|------------|
| **video_processing/** | [CLAUDE.md](video_processing/CLAUDE.md) | 60秒分段处理、首帧buffer机制、Debounce、跨片段状态连续性 |
| **deployment/** | [CLAUDE.md](deployment/CLAUDE.md) | Systemd服务、Cron任务、配置向导、数据库迁移 |
| **video_capture/** | [CLAUDE.md](video_capture/CLAUDE.md) | RTSP连接管理、60秒分段算法、多线程并发、PIPE死锁修复 |
| **All directories** | [STRUCTURE.md](STRUCTURE.md) | 目录结构、脚本索引、常用工作流 |

---

## Key Concepts by Topic

### Video Capture System

See [video_capture/CLAUDE.md](video_capture/CLAUDE.md):
- **RTSP连接管理** - 5阶段连接生命周期、网络质量检查、密码脱敏
- **60秒分段录制** - 时间片轮转、自动文件命名、FFmpeg -t参数
- **PIPE死锁修复** - v5.3.0关键修复，DEVNULL替代PIPE防止155段后挂起
- **多线程并发采集** - 资源隔离、线程安全、N倍加速
- **信号优雅关闭** - SIGTERM/SIGINT处理、FFmpeg进程清理
- **内存管理策略** - Stream copy、进程回收、日志轮转、24/7稳定运行
- **结构化日志系统** - 三层日志文件、自动轮转、上下文注入

### Video Processing Pipeline

See [video_processing/CLAUDE.md](video_processing/CLAUDE.md):
- **60秒分段处理** - 故障恢复、FFmpeg稳定性
- **首帧重复处理** - 1秒buffer填充debounce，不写数据库
- **Debounce机制** - 状态变化需要1秒稳定期
- **跨片段状态处理** - 无假状态变化，数据库只记录真正变化
- **WiFi断连处理** - 通过数据库时间戳倒推缺失时段

### Deployment & Operations

See [deployment/CLAUDE.md](deployment/CLAUDE.md):
- **一键部署** - `sudo ./deploy.sh`
- **配置向导算法** - 预检查、摄像头测试、ROI绘制、健康验证
- **Per-camera ROI** - 每个摄像头独立ROI配置 (camera_XX_roi.json)
- **Systemd服务** - 自动重启、开机启动、日志集成
- **Cron任务** - 双时段录制、午夜处理、凌晨清理、每日重启
- **数据库迁移** - Schema v2.0.0, location_id, backfill算法
- **摄像头管理** - CRUD操作、RTSP连接测试、IP验证
- **ROI缩放算法** - 分辨率自适应坐标缩放

### Database & Cloud Sync

See root [db/CLAUDE.md](../db/CLAUDE.md):
- **SQLite本地存储** - 状态变化、会话记录
- **Supabase云同步** - 每小时增量同步
- **数据保留策略** - 数据库永久保留

---

## Adding Documentation

When adding new documentation:

1. **Feature-specific docs** - Create `CLAUDE.md` in the relevant directory
2. **Update this index** - Add link to Quick Links table
3. **Update STRUCTURE.md** - Add to directory reference if new scripts added
4. **Update root CLAUDE.md** - Add to Documentation Structure section if significant

---

## Version History

- **1.3.0** (2025-12-13): Added video_capture/CLAUDE.md with 8 core algorithms documented
- **1.2.0** (2025-12-13): Updated deployment section with comprehensive algorithm details
- **1.1.0** (2025-12-13): Added deployment/CLAUDE.md, updated structure
- **1.0.0** (2025-12-13): Initial creation, index for video_processing documentation
