# MemWise v1.6

## Windows 智能内存看护工具

MemWise 是一款纯 ctypes Win32 API 构建的 Windows 内存优化与实时守护工具。通过调用 Windows 底层内存管理 API，对进程闲置工作集、系统 Standby List、Modified Page List、内存压缩等进行细化治理，在不终止进程、不挂起线程、不注入、不联网的前提下实现物理内存的释放与压缩。支持 GUI 和命令行两种使用方式，以单 exe 分发（约 13.3 MB），零外部依赖。

系统的核心价值在于"主动+持续"：在 Windows 自身内存压力感知机制启动之前，提前介入回收，并在守护模式下保持 60 秒间隔内零空闲的持续满载优化。同时通过 Thompson Sampling、Kalman 滤波、因果推理、五树投票等学习与决策机制，为每个进程建立独立画像，实现"知道哪个进程值得清、哪个清了反而更卡"的意图识别。

---

## 1. 运行模式

### 1.1 一键优化

点击主界面"优化"按钮（或按快捷键 Ctrl+Shift+M），程序执行单次完整的系统+进程深度清理，并输出累计释放量。适用于"感觉到卡了，临时清一下"的场景。每次手动优化执行 3 轮，累计来自 Layer1（系统缓存）、Layer2（进程闲置页）、Layer3（深度回弹清洗）和 probe（探测试探）的释放量，最终显示对比优化前后的内存占用变化。

### 1.2 守护模式（推荐）

点击"守护"按钮启动，程序以 60 秒为日志/图表输出周期，在周期内执行零空闲持续优化。具体节奏为：

| 阶段 | 内容 |
|------|------|
| 自适应 gap | 根据上一轮每个进程的平均释放量自动调整间隔（8-25 秒），释放多则缩短、释放少则延长 |
| 多次 optimize | 周期内执行 2-3 次完整的优化 pass，每次包含 Layer1 + Layer2（内层用 normal 模式），末次 pass 用 deep 模式追加 Layer3 |
| gap fill 持续运行 | 在 optimize 之间持续执行压缩+脏页写回+快车道修剪+压力更新，不碰 standby，留给末次主 pass 收割 |

守护模式启动后，窗口可关闭/最小化到托盘（根据设置自动选择或询问），程序在系统托盘区域显示图标，右键可调出菜单。守护状态、累计释放量、系统杂项操作总次数、进程清理总次数等实时显示在主界面状态栏。日志区域实时输出算法诊断信息、优化量、EFIS 调参记录。图表区域以柱状图显示每轮释放量，折线显示效率评分。

### 1.3 命令行

程序同时提供命令行接口（`memwise.py`），支持 status（查看内存状态）、optimize（一键优化）、daemon（守护模式）、profile（查看进程画像）、learn（学习进程行为）等子命令。适合计划任务或脚本集成。

---

## 2. 三层清理引擎

### 2.1 Layer1 — 系统级缓存清理

系统级清理通过调用 `NtSetSystemInformation` 等未文档化但广泛使用的 Windows 内部 API 实现，涵盖 8 种缓存操作的独立开关：

| 操作 | 配置键 | 默认 | Win32 API | 说明 |
|------|--------|:----:|-----------|------|
| 进程闲置页释放 | `ws` | 开 | `EmptyWorkingSet` | 释放非活跃物理页，是唯一不需要管理员的进程级操作 |
| Standby List 清理 | `standby` | 开 | `NtSetSystemInformation(80, info=1,4)` | 清空系统缓存页，低优先先清再全清，最后 deep 三轮 |
| Modified Page 写回 | `modified` | 开 | `NtSetSystemInformation(44)` | 脏页写回磁盘后回收，配合 standby 收割 |
| 内存压缩触发 | `compress` | 开 | `NtSetSystemInformation(80, info=6)` | 触发 OS 内存压缩引擎，压缩后可释放物理页 |
| 系统文件缓存 | `filecache` | 关 | `SetSystemFileCacheSize(-1,-1,0)` | 清空文件系统缓存，会降低文件操作速度直到重建 |
| 卷缓存刷新 | `volume` | 关 | `CreateFileW+FlushFileBuffers` | 卷级别缓存刷新 |
| 注册表缓存 | `registry` | 关 | `NtSetSystemInformation(81)` | 清除注册表缓存页 |
| 内存合并 | `combine` | 关 | `NtSetSystemInformation(80, info=5)` | 触发系统合并相同物理页 |

守护模式下的 gap fill 期间仅执行压缩+脏页写回（`_layer1_light`），standby 留给主 pass 在积累整个 gap 后一次性收割，最大化单次效果。主 pass 的 `_layer1_system` 通过"两阶段异步管线"（触发→0.3s 等待 OS 处理→统一收割）完成全量操作。主 pass 末轮使用 `deep_compress` 四轮递进压缩（flush→compress→standby→compress，每轮 0.3s 间隔），实现远超单次压缩的释放效果。

### 2.2 Layer2 — 进程级闲置页释放

对每个非系统进程调用 `EmptyWorkingSet`，释放其物理内存中的非活跃页。决策链路：

1. **`can_trim` 安全过滤**：排除系统核心进程（csrss、smss、wininit 等用户自定义黑名单中的进程）、前台窗口保护（压力低时跳过）、WS < 1 MB 的微小进程、WS 基线检查（上一轮清理后 WS 无增长则不重复清理）、失败冷却检查（PF 超标后进入冷却期）、系统路径门槛检查（`C:\Windows\`、`C:\Program Files\` 下的进程要求 θ > 0.3）

2. **策略投票**（五树决策）：收益树（预期释放量×成功率）、代价树（预期 PF 代价×内存压力）、时机树（增长趋势+距上次清理时间）、紧迫树（θ 相对排名+冷却状态）、反事实树（因果图优势比）。总分 ≥ 0 即通过（不设硬性门槛）

3. **复合评分排序**（`_composite_score_v2`）：θ、Kalman x_freed、WS 大小、WS 回弹率四维加权，EFIS 可调 `composite_kalman_w` 权重

4. **并行执行**：4 线程池 `ThreadPoolExecutor`，按评分降序提交

5. **自适应 Pass 数**：大进程（WS>200 MB 或 θ>EFIS deepen_theta）→ 4 pass, 1.0s；默认 → 3 pass, 0.6s；低 θ（θ<0.15）→ 1 pass, 0.3s

6. **PF 反馈验证**（`check_feedback`）：对比清理前后 PF 计数，超过 `allowed_pf = max(120, 自由PF, 释放量×10MB, passes×60)` 则判定为失败

### 2.3 Layer3 — 深度重复清理

仅 deep 模式末次 optimize 执行。依次为：

- **压缩 + 脏页写回**：调用 `deep_compress` 四轮递进
- **全量 Standby List 收割**：低优先→全量→deep 三层
- **文件缓存 / 卷缓存 / 注册表 / 内存合并**（按设置）
- **WS 回弹率筛选**：从 Layer2 未清理的进程中选出 `当前WS / 上次清理后WS >= 1.5` 的高回弹进程，追加一次清理
- **layer3_extra 追踪**：通过压缩/standby 前后 `avail` 差值（bytes）自动记录深度清理的净增量，用于 EFIS 判断 Layer3 的价值

### 2.4 持续优化架构

守护模式的核心架构改造：

```
deadline = now + interval - 3
while time.time() < deadline:
    optimize(normal)           # 完整 Layer1+Layer2, 无 Layer3
    gap 自适应调整              # 根据上轮 per-process 释放量
    gap fill:                  # 3 秒窗口内满载:
        _layer1_light(agg)     #   快速压缩+脏页（不碰 standby）
        快车道修剪              #   高回填进程高频 quick_retrim
        快照刷新+压力更新       #   实时读取系统内存状态
    
# 末次
optimize(deep)                 # 完整 Layer1+Layer2+Layer3
输出日志+图表
```

- **自适应 gap**：每轮后计算 `realse_per_proc`，与上一轮比对，决定 gap 缩放（8s 到 25s）。首次 gap = 15s
- **快车道**：`_layer2_process` 在每轮排序前遍历候选进程，将 `refill_ewma > 500KB/s` 的进程 PID 记录到 `self._fast_track`；gap fill 期间每轮从 `_fast_track` 中取出最多 10 个 PID 调用 `quick_retrim(pid)`（单次 `empty_ws` + 0.1s 等待，左右 WS 差值计入 freed_bytes）
- **数据累加**：所有 sub-pass + gap fill + 快车道的释放量全部汇入 `freed_bytes`，确保 60 秒周期的最终输出汇总了一切操作的释放总量

---

## 3. 认知引擎（六模块）

### 3.1 Thompson Sampling（Beta-Bernoulli）

对每个进程维护一对 Beta 分布 (α, β)。每次清理成功后 α+=1，失败后 β+=1。采样得到的 θ ∈ [0,1] 表示"该进程在当前知识状态下值得清理的概率"。

- **先验**：Beta(α=2, β=1)，偏向"可清理"，相当于已经"虚拟成功 1 次"
- **时间遗忘**：距离上次 feedback >1 小时开始，每小时向先验回归 3%，最多 30%（减少历史数据对当前状态的滞后影响）
- **置信度**：基于 Beta 分布标准差计算，用于策略投票中的权重调节

### 3.2 Kalman 二维滤波

追踪每个进程的两个连续值，比 Beta 更能捕捉释放量和 PF 代价的实际量级。

- 状态：`[x_freed(MB), x_cost(PF)]`
- 观测噪声 r = 固定，过程噪声 q 由 meta 每 30 秒校准
- 每次清理后调用 `update(actual_freed, actual_pf_delta)`
- `predict()` 返回 `(x_freed, x_cost)`，用于复合评分
- v1.5 遗留 bug 曾导致所有进程的 `x_freed` 被重置为零；v1.6 在加载时自动从 `gain_ewma` 种子恢复

### 3.3 情景记忆

存储每次清理时刻的五维上下文向量 `[norm_ws, norm_theta, mem_pct, cpu, hour]`，支持余弦相似度检索 top-3 最相似历史经验。新进程通过记忆加速冷启动收敛。上限 200 条，超出时丢弃最旧记录。相似度阈值 0.7。

### 3.4 分层先验

10 个预定义类别（browser/development/game/media/office/system/terminal/utility/vm/other），按进程名关键词自动分类。新进程从同类经验池继承初始 θ，避免从 Beta(2,1) 零基础开始。

### 3.5 因果推理

有向图记录"清 A 时 B 的释放量"。支持反事实优势比查询，作为五树投票中"反事实维度"的输入。键统一使用小写进程名，每对仅存最新一条（新覆盖旧）。仅作为决策奖励（纯加分），不会惩罚数据不足的进程。

### 3.6 五树投票策略

替代单一 θ 门槛的多维综合决策：

- **收益树**：预期释放量 × 成功率
- **代价树**：预期 PF 代价 × 内存压力
- **时机树**：增长趋势 + 距上次清理时间
- **紧迫树**：θ 相对排名 + 冷却状态
- **反事实树**：因果图优势比

总分 ≥ 0 通过（不设硬性门槛，不因"不够好"而放过）。Probe 试探同步使用五树投票，高分进程探测间隔缩短到 30%，低分进程正常间隔——纯加速不拦截。

---

## 4. 元认知自我监控

每 30 秒运行一次完整诊断：

- **校准度**：对比 Kalman 预测 vs 实际释放。偏差 >50% → 重置卡尔曼参数并降低 θ 置信；偏差 <15% → 卡尔曼稳定并奖励 θ 置信
- **概念漂移**：双 EWMA 快慢速比检测进程行为突变（阈值 4.0×/0.2×）。漂移时温和调整 Beta 和 Kalman 参数（避免过度重置）
- **探索覆盖**：统计从未被试探的进程比例，超过 40% 时适度提高好奇心
- **学习率自校准**（`self_check`）：每 30s 检查所有进程的预测误差，误差 >30% 降低上下文学习率，误差 <10% 恢复学习率
- **因果对追踪**：仅在因果对数量变化时向用户报告

---

## 5. EFIS v3 全程序智能调参

EFIS（Efficiency Feedback Intelligent System）已升级为覆盖全程序 5 层、9 参数的智能调参大脑。

**参数一览**：

| 参数 | 默认值 | 范围 | 控制的内容 |
|------|:----:|:----:|------|
| `deepen_theta` | 0.60 | 0.30-0.80 | θ 超过此值→trim 升级到 4 pass |
| `layer3_agg_gate` | 0.60 | 0.30-0.90 | 压力低于此值→触发 Layer3 深度清理 |
| `pid_kp` | 0.60 | 0.30-2.00 | PID 比例增益——对内存偏差的响应速度 |
| `pid_kd` | 0.10 | 0.05-0.50 | PID 微分增益——抑制震荡 |
| `target_usage` | 60% | 35-65% | PID 目标内存占用百分比 |
| `interval_high` | 10s | 5-20s | 高压时（agg>0.8）的日志/图表输出间隔 |
| `cooloff_base` | 360s | 60-360s | 失败冷却基数（实际冷却 = cooloff_base × 失败次数，最多×2） |
| `learning_rate` | 0.30 | 0.05-0.40 | 上下文特征权重的学习速度 |
| `composite_kalman_w` | 0.30 | 0.10-0.50 | 复合评分中 Kalman 分量 vs Thompson 分量的权重 |

**诊断方式**：取消原有的 ERIS 代理指标映射（5 维中 2 维为死维），改为每个参数配备专属的因果症状规则。如 `deepen_waste` 检查 2-pass 进程的平均额外释放量是否低于 10MB；`layer3_extra` 检查 Layer3 每轮平均释放是否低于 50MB；`pid_kp` 检查内存振幅和 PF 速率是否异常。症状持续 ≥2 周期后触发调参，防止噪声误调。

**场景记忆**：支持 game/browser/development/general 四个场景独立参数记忆。场景切换时 70% 当前参数 + 30% 场景历史参数平滑过渡，避免切换瞬间的参数跳跃。场景由进程名关键词自动检测。

**文件与加载**：独立文件 `efis_state.json`（与 learner 的 `memwise_state.json` 分离）。加载时自动跳过已废弃参数（`theta_gate`、`ws_baseline_mul`、`cpu_gate`、`max_trim`），新参数缺失时取默认值。`save()` 通过 `临时文件.write + os.replace` 原子化写入，防止写一半崩溃导致配置损坏。

---

## 6. 内存优先级管理

系统通过调用 `NtSetInformationProcess(ProcessMemoryPriority)` + `SetProcessInformation(EcoQoS)` 向 OS 传递偏好级别：

- **所有非系统、非前台进程**：LOW 内存优先级 + EcoQoS 启用
- **θ > 0.3 的高价值进程**：VERY_LOW（系统最优先回收其物理页）

这一机制的作用在于"减少回填速度"：被设定 LOW 优先级的进程在访问已换出页面时，系统会优先从 Standby List 或压缩池中提供零页，而不是分配新的物理页。这是操作系统层面的被动优化，不消耗额外 CPU 或 I/O。

---

## 7. 游戏模式

通过进程名匹配（内置约 70 个已知游戏 exe + 用户自定义名单）和全屏窗口检测（`GetWindowRect` + `GetSystemMetrics`，含类名过滤排除浏览器假全屏）自动激活。

激活后效果：非前台进程 WS 准入降至 2 MB，probe 间隔压缩到 0.15s，min_delta 降至 1 MB。前台（游戏）进程加强保护（`agg_threshold_fg = 0.6`），全屏类名过滤排除 Chrome_WidgetWin_1、MozillaWindowClass、PPTFrameClass 等非游戏全屏窗口。

---

## 8. 图表与效率评分

每轮（60 秒）推送一柱到柱状图，与日志同步输出。柱高为该轮累计释放量（MB），X 轴显示最近的约 60 轮数据。折线为 ERIS 效率评分（0-100），五维几何平均计算。`overflow_bonus` 0.20 权重，避免首轮 1GB+ 大释放量将效率虚推至 100%。鼠标悬浮显示具体数值。图表区域下方标注统计栏：当前物理内存占用百分比及彩色进度条（绿<60%、黄60-74%、橙75-89%、红≥90%）、累计释放量（自动换算 GB/MB）、系统杂项总次数（K 单位缩写）、进程清理总次数（K 单位缩写）。

---

## 9. 进程排行

点击"进程排行"按钮弹出独立窗口，显示所有活跃进程的快照。排序列包括：进程名、PID、物理内存（WorkingSet，与任务管理器的"工作集"列对齐）、CPU 占用（%）、学习数据（θ、ROI、清理次数、EWMA、refill_ewma 等）。每 2 秒自动刷新，底部显示"共 N 个进程"。

内存数据的采集优先使用 `NtQuerySystemInformation(SystemProcessInformation=5)` 一口返回所有进程的工作集和私有内存值，无需对每个进程执行 `OpenProcess`。此 API 可绕过某些安全软件的进程保护机制（如 Kaspersky），确保全量覆盖。

---

## 10. 学习日志

点击"学习日志"按钮弹出独立窗口，按复合评分降序显示所有已学习 ≥2 轮的进程的完整画像数据：θ 值、ROI、Kalman x_freed、gain_ewma、refill_ewma、vol_ewma、清理次数、成功率等。支持排序和滚动浏览。

---

## 11. 设置面板

设置面板提供以下可配置项，所有更改即时保存至 `config/config.yaml`，重启后生效：

**启动设置**：
- 开机自启：创建/删除启动文件夹快捷方式（非注册表方式）
- 管理员权限启动：创建/删除 Windows Scheduled Task（以最高权限运行）
- 启动时自动开启守护：程序打开后无需手动点击守护按钮
- 启动后最小化到托盘：程序窗口不显示，仅留托盘图标

**关闭按钮行为**（设置面板内，位于"启动后最小化到托盘"下方）：
- 最小化到托盘：点击 X 隐藏到托盘，守护模式继续运行
- 直接退出程序：点击 X 完全退出，自动保存所有状态
- 每次询问：弹窗选择（默认）

**清理操作**：8 种操作独立开关（默认 ws/standby/compress/modified 开，其余关）。可实现"只清进程不清系统缓存"或"全开"等组合。

**清理模式**：下拉框选择 quick / normal / deep / full（默认 deep）。

---

## 12. 日志系统

主界面右侧为日志区域。每轮（60 秒）输出本轮释放量、系统杂项操作次数、整理的进程数、试探/成功数、已学习画像数、总样本数。在输出周期之间，算法诊断消息（元认知校准、概念漂移、EFIS 调参、因果统计、深度清理触发等）被累积到缓冲区，于日志输出时一并显示。

**清屏机制**：每轮在输出第一条消息前检查"本轮前已有行数 + 本轮新增行数 > 7"，若成立则清屏再输出本轮全部消息，否则直接追加到旧日志下方。确保每条日志用户至少可见一整轮（60 秒）。

算法消息中部分仅在状态变化时输出（如因果对关系数、探索覆盖率、Layer3 清理强度），减少重复刷屏。

---

## 13. 命令行工具

```bash
python memwise.py [command] [options]
```

| 命令 | 说明 |
|------|------|
| `status` | 查看当前物理内存使用率、总可用量等 |
| `learn [分钟]` | 采集并学习进程内存行为 |
| `optimize [-m MODE]` | 单次优化（支持 quick/normal/deep/full） |
| `daemon [-m MODE]` | CLI 守护模式 |
| `profile <PID>` | 查看指定进程的完整学习画像 |

---

## 14. 配置项

`config/config.yaml` 完整配置项：

| 键 | 类型 | 默认值 | 说明 |
|------|------|:------|------|
| `clean_mode` | str | `"deep"` | 清理模式 |
| `clean_operations` | list | `[ws,standby,compress,modified]` | 启用的操作 |
| `auto_start` | bool | `false` | 开机自启 |
| `auto_start_admin` | bool | `false` | 管理员权限开机自启 |
| `auto_start_daemon` | bool | `false` | 启动后自动守护 |
| `auto_start_minimize` | bool | `false` | 启动后最小化 |
| `close_action` | str | `"ask"` | 关闭按钮行为 |
| `interval` | int | `60` | 日志/图表周期（秒） |
| `hotkey` | str | `"ctrl+shift+m"` | 热键 |
| `never` | list | `[]` | 排除列表（进程名或 PID） |
| `game_processes` | list | `[]` | 自定义游戏 exe 名 |
| `efis_params` | dict | 9 参数默认值 | EFIS 参数 |

---

## 15. 文件结构

```
MemWise/
├── memwise_gui.py              # GUI 主程序，约 1800 行
├── memwise.py                  # CLI 命令行入口
├── config/config.yaml          # 配置文件（自动持久化）
├── memwise_state.json          # 学习数据文件（自动保存/加载）
├── memwise_efis_state.json     # EFIS 状态文件
├── CHANGELOG.md                # 更新日志
├── README.md                   # 本文件
├── assets/icon.ico             # 程序图标
├── core/
│   ├── cleaner.py              # 三层清理引擎 + 持续优化
│   ├── learner.py              # Thompson Sampling + Kalman + 特征学习
│   ├── judger.py               # 判定器 + PID 控制器
│   ├── efis.py                 # EFIS v3 全程序智能调参
│   ├── meta.py                 # 元认知自我监控
│   ├── policy.py               # 五树投票策略
│   ├── causal.py               # 因果推理图
│   ├── kalman.py               # Kalman 滤波器
│   ├── temporal.py             # 时序画像
│   ├── hippocampus.py          # 情景记忆
│   ├── prior.py                # 分层先验
│   ├── winapi.py               # Win32 API 绑定（70+ 函数）
│   ├── sniffer.py              # 进程快照采集
│   └── config.py               # 配置加载/保存
└── scripts/
    └── _validate.py            # 构建验证脚本
```

---

## 系统要求

- Windows 10 20H1+ / Windows 11（部分缓存操作依赖较新版本）
- 管理员权限（缓存清理需要；进程 EmptyWorkingSet 不受限制）
- 无需安装任何第三方运行库

---

> [GitHub Releases](https://github.com/fuguangbeta/MemWise/releases) — 下载最新版本
