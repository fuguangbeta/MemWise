# MemWise v1.8

## Windows 智能内存看护工具

MemWise 是一款纯 ctypes Win32 API 构建的 Windows 内存优化与实时守护工具。通过调用 Windows 底层内存管理 API（NtSetSystemInformation、EmptyWorkingSet、SetSystemFileCacheSize 等），对进程闲置工作集、系统 Standby List、Modified Page List、内存压缩等进行细化治理，在不终止进程、不挂起线程、不注入、不联网的前提下实现物理内存的释放与压缩。支持 GUI 和命令行两种使用方式，以单 exe 分发（约 13.3 MB），零外部依赖。

系统的核心价值在于"主动+持续"：在 Windows 自身内存压力感知机制启动之前，提前介入回收，并在守护模式下保持 60 秒间隔内零空闲的持续满载优化。同时通过 Thompson Sampling、Kalman 滤波、因果推理、五树投票等学习与决策机制，为每个进程建立独立画像，实现"知道哪个进程值得清、哪个清了反而更卡"的意图识别。

---

## 1. 运行模式

### 1.1 一键优化

点击主界面"优化"按钮（或按快捷键 Ctrl+Shift+M），程序执行单次完整的系统+进程深度清理，并输出累计释放量。适用于"感觉到卡了，临时清一下"的场景。每次手动优化执行 3 轮，累计来自 Layer1（8 步内核管线）、Layer2（进程闲置页）和 Layer3（深度回弹清洗）的释放量，最终显示对比优化前后的内存占用变化。

### 1.2 守护模式（推荐）

点击"守护"按钮启动，程序以 60 秒为日志/图表输出周期，在周期内执行零空闲持续优化。具体节奏为：

| 阶段 | 内容 |
|------|------|
| 自适应 gap | 根据上一轮每个进程的平均释放量自动调整间隔（8-25 秒），释放多则缩短、释放少则延长 |
| gap fill 轻量压制 | 持续执行 standby purge + modified flush + fast-track 修剪。轻量模式跳过系统级 WS 全清，留给主 pass 收割 |
| 多次 harvest | 周期内执行 2-3 次完整的 optimize pass（normal 模式），每次含 Layer2 进程修剪 + Layer1 轻量管线 |
| 主 pass 全量收割 | 末次 optimize 使用用户选定模式，Layer2 先行释放 → Layer1 全量 8 步管线（含系统级 WS 全清 + Standby 全量清空）→ Layer3 深度聚合 |

守护模式启动后，窗口可关闭/最小化到托盘（根据设置自动选择或询问），程序在系统托盘区域显示图标，右键可调出菜单。守护状态、累计释放量、系统杂项操作总次数、进程清理总次数等实时显示在主界面状态栏。日志区域实时输出算法诊断信息、优化量、EFIS 调参记录。图表区域以柱状图显示每轮释放量，折线显示效率评分。

### 1.3 命令行

程序同时提供命令行接口（`memwise.py`），支持 status（查看内存状态）、optimize（一键优化）、daemon（守护模式）、profile（查看进程画像）、learn（学习进程行为）等子命令。适合计划任务或脚本集成。

---

## 2. 三层清理引擎

### 2.1 Layer1 — 系统级内核清理

系统级清理通过调用 `NtSetSystemInformation` 等未文档化但广泛使用的 Windows 内部 API 实现，涵盖 8 种操作的独立开关。全部操作码已对齐 PHNT 标准（MemoryEmptyWorkingSets=2、MemoryFlushModifiedList=3、MemoryPurgeStandbyList=4、MemoryPurgeLowPriorityStandbyList=5），通过 8 步连续管线执行（无 sleep，<10ms）。

| 操作 | 配置键 | 默认 | Win32 API | 说明 |
|------|--------|:----:|-----------|------|
| 进程闲置页释放 | `ws` | 开 | `EmptyWorkingSet` | 释放非活跃物理页 |
| Standby List 清理 | `standby` | 开 | `NtSetSystemInformation(80, info=4)` | 清空系统缓存页 |
| Modified Page 写回 | `modified` | 开 | `NtSetSystemInformation(80, info=3)` | 脏页写回磁盘后回收 |
| 内存压缩触发 | `compress` | 开 | `NtSetSystemInformation(80, info=5)` | 触发 OS 内存压缩引擎 |
| 系统文件缓存 | `filecache` | 关 | `SetSystemFileCacheSize` | 清空文件系统缓存 |
| 卷缓存刷新 | `volume` | 开 | `CreateFileW+FlushFileBuffers` | 卷级别缓存刷新 |
| 注册表缓存 | `registry` | 开 | `NtSetSystemInformation(81)` | 清除注册表缓存页 |
| 内存合并 | `combine` | 关 | `NtSetSystemInformation(80, info=3)` | 触发系统合并相同物理页 |

---

## 系统要求

- Windows 10 20H1+ / Windows 11
- 管理员权限
- 无需安装任何第三方运行库

---

> [GitHub Releases](https://github.com/fuguangbeta/MemWise/releases) — 下载最新版本