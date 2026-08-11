# MemWise v3.8.40

## 关于本工具 · *About This Tool*

MemWise 是一个运行在 Windows 用户态的内存整理工具。它的工作方式并不复杂：借助系统公开的内存管理接口，在内存吃紧时，把进程暂时不用的页面和系统缓存回收回来，让正在使用的程序有更充裕的空间。

在 Windows 上，内存管理本身是系统一直在做的事情——压缩、缓存、换页，自有其成熟的机制。MemWise 并不试图取代这些机制，也不对系统做任何修改。它只是在用户需要时，让回收发生得更主动一些、更可控一些。因此，你可以把它理解为一个"手动 + 定时"的补充，而不是一套额外的内存体系。

也正因为如此，有几件事需要提前说明。

MemWise 释放的是"暂时用不到的内存"，它不能让物理内存凭空变多。如果一台机器的内存确实不够用，最根本的解决办法仍然是增加内存。本工具的意义在于，在无法立即升级硬件、或运行大型程序前需要快速腾出空间的时候，提供一个立即可用的选择。内存长期充裕的机器，其实并不需要这类工具——保持系统的默认管理，往往就是最好的状态。

回收的页面在被程序再次使用时需要重新加载，这通常表现为一瞬间的轻微延迟；清理系统缓存后，首次访问大文件也可能稍有变慢。这是内存管理本身的性质，并非工具的缺陷，也不会影响数据安全与程序稳定性。所有操作都可以在设置中单独关闭，你可以根据自己对流畅度的要求自行取舍。

MemWise 不随意终止进程、不挂起线程、不注入代码、不访问网络，也没有任何附带组件。它仅使用 Windows 公开的 API，代码完全开源。

由于不联网，MemWise 自身无法做到自动更新。当新版本发布时，需要用户自行前往 Releases 页面查看与下载。这算是不联网带来的一个小小不便——不过相应地，程序自始至终不会与任何服务器通信，个人设备在使用上毫无泄露数据顾虑。

如果你正在为内存紧张而困扰，希望这个工具能帮上一点忙；也欢迎在使用中提出意见，让它变得更好。

*MemWise is a user-mode memory tidying tool for Windows. Its approach is simple: through the system's public memory-management interfaces, it reclaims idle process pages and system caches when memory runs tight, leaving more room for the programs you are actually using.*

*Memory management on Windows is something the system already does — compression, caching, and paging have their own mature mechanisms. MemWise does not try to replace them, nor does it modify the system in any way. It simply makes reclamation more proactive and more controllable, on your schedule. Think of it as a manual and scheduled supplement, not a separate memory system of its own.*

*A few things are worth saying plainly.*

*What MemWise frees is memory that is not being used right now. It cannot make physical memory larger than it is. If a machine genuinely does not have enough RAM, adding memory remains the fundamental solution. The value of this tool lies in the moments when an upgrade is not immediately possible, or when you want to make room quickly before running something large. Machines with abundant memory rarely need such tools — leaving the system's defaults alone is often the best state.*

*Reclaimed pages are reloaded the next time a program needs them, usually as a momentary, barely noticeable delay; the first access to a large file after cache clearing may also be slightly slower. This follows from the nature of memory management itself — it is not a flaw of the tool, and it affects neither data safety nor program stability. Every operation can be disabled individually in Settings, so you can decide for yourself how it balances with your need for smoothness.*

*MemWise terminates no processes, suspends no threads, injects no code, and touches no network, with no bundled components. It uses only public Windows APIs, and the source is fully open.*

*Since MemWise does not connect to the network, it cannot update itself. When a new version is released, users will need to visit the Releases page and download it themselves. This is a small inconvenience of being offline — in return, the program never communicates with any server, so it can be used on personal devices without any concern about data leakage.*

*If memory pressure has been troubling you, I hope this tool helps a little; and if you have suggestions along the way, they would be most welcome.*

---

## Windows 智能内存看护工具 · *Intelligent Memory Custodian*

MemWise 是一款纯 ctypes Win32 API 构建的 Windows 内存优化与实时守护工具。通过调用 Windows 底层内存管理 API（NtSetSystemInformation、EmptyWorkingSet、SetSystemFileCacheSize 等），对进程闲置工作集、系统待机列表、已修改页列表等进行细化治理，在不终止进程、不挂起线程、不注入、不联网的前提下实现物理内存的释放与回收。支持 GUI 和命令行两种使用方式，以单 exe 分发（约 12.7 MB），零外部依赖。

*Built entirely on ctypes Win32 API with zero third-party dependencies, MemWise reclaims physical memory through disciplined management of idle working sets, standby lists, and modified page lists — all without terminating processes, suspending threads, injecting code, or touching the network. Distributed as a single ~12.7 MB executable.*


系统的核心价值在于"主动+持续"：在 Windows 自身内存压力感知机制启动之前提前介入回收，并在守护模式下保持 60 秒间隔内零空闲的持续优化。同时通过 Thompson Sampling、Kalman 滤波、分层先验、五树投票框架等学习与决策机制，为每个进程建立独立画像，在最大化释放效率的同时抑制缺页副作用。

*MemWise intercepts memory pressure before Windows initiates its own reclamation, maintaining uninterrupted optimization at 60-second intervals in daemon mode. A cognitive engine combining Thompson Sampling, Kalman filtering, hierarchical priors, and five-tree policy voting (3 active) builds independent behavioral profiles per process, maximizing release efficiency while minimizing page-fault side effects.*

程序内嵌了轻量看门狗机制，可在意外崩溃后自动恢复运行状态，并为自身内存占用与运行功耗设立了严格的自律约束。

*An embedded watchdog subprocess restores daemon state within seconds of an unexpected crash. The program also enforces strict limits on its own memory footprint and power consumption.*

---

## 1. 运行模式 · *Operating Modes*

### 1.1 一键优化 · *One-Click Optimization*

点击主界面"优化"按钮（或按全局热键，默认 Ctrl+Shift+M，可在设置 → 触发与日志 → 全局热键中自定义），程序按当前选择的清理模式执行单次优化，并输出累计释放量。四种模式从快速（3 步系统轻扫）到全量（8 步 + 进程回弹二轮）梯度递增，最终显示对比优化前后的内存占用变化。

*Triggered via the Optimize button or the global hotkey (default Ctrl+Shift+M, customizable in Settings → Triggers & Logging → Global Hotkey). Runs a single optimization pass in the currently selected cleaning mode — from quick (3-step lightweight sweep) to full (8-step pipeline with a rebound second round) — and displays the before-and-after memory delta.*

### 1.2 守护模式（推荐）· *Daemon Mode (Recommended)*

点击"守护"按钮启动，程序以 60 秒为日志/图表输出周期，在周期内执行零空闲持续优化。具体节奏为：

| 阶段 | 内容 |
|------|------|
| 自适应 gap | 根据上一轮每个进程的平均释放量自动调整间隔（8-20 秒基准，自适应上限 25 秒），释放多则缩短、释放少则延长 |
| gap fill 轻量压制 | 高频阶段仅执行注册表缓存清理（零磁盘影响）；standby 与脏页写回由 gap 末 optimize 统一执行——缓存有累积时间，单次释放量更大 |
| 多次 harvest | 周期内执行 2-3 次完整的 optimize pass（normal 模式），每次含 Layer2 进程修剪 + Layer1 管线（高频 gap 阶段不触发深度聚合） |
| 主 pass 全量收割 | 末次 optimize 使用用户选定模式，Layer2 先行释放 → Layer1 对应管线（normal 5 步 / deep 8 步 / full 8 步+回弹二轮）→ Layer3 深度聚合 |

*Operates in 60-second log/chart cycles with uninterrupted optimization. An adaptive gap timer (8–25s) dynamically adjusts based on per-process release rates. High-frequency suppression touches only the registry cache (zero disk impact); standby and dirty-page flush are batched into each gap-end optimize pass so the cache accumulates before each purge, yielding larger per-pass releases. Full harvesting passes follow the user-selected mode: 5 steps for normal, 8 steps for deep, 8 steps plus a process-level rebound second round for full. Deep aggregation (Layer 3) runs only in the final harvest pass.*

守护模式启动后，窗口可关闭/最小化到托盘（根据设置自动选择或询问），程序在系统托盘区域显示实时内存占用图标，右键可调出菜单。守护状态、累计释放量、系统操作总次数、进程清理总次数等实时显示在主界面状态栏。日志区域输出算法诊断信息与优化量（周期末打包，游戏检测实时推送）。图表区域以柱状图显示每轮释放量，折线显示效率评分。超时进程通过递增冷却机制（×1~4）自动降频，成功恢复后自动衰减。内存占用达到紧急阈值（默认 80%）时，立即跳过等待执行一次极限模式（full）清理。

*The window can be closed or minimized to the system tray. A real-time memory-usage icon appears in the notification area with a right-click context menu. The status bar displays daemon state, cumulative freed memory, system operation counters, and process trim counts. Algorithmic diagnostics and optimization metrics are buffered per cycle and flushed in batches, while game-detection messages appear immediately. The chart area renders per-cycle release bars overlaid with an ERIS efficiency line. Timed-out processes are throttled by an escalating cooldown (×1~4) that decays after successful recovery. When memory usage reaches the emergency threshold (default 80%), an immediate full-mode cleaning is triggered without waiting.*

程序内嵌看门狗子进程，主进程意外崩溃后可在数秒内自动重启，并恢复崩溃前的运行状态——守护运行中则自动续守护，空闲中则保持空闲；单实例互斥锁防止恢复实例与手动启动实例冲突。

*A watchdog subprocess automatically restores daemon state within seconds of an unexpected crash. A single-instance mutex prevents conflicts between recovered and manually launched instances.*

### 1.3 命令行 · *Command Line*

程序同时提供命令行接口（`memwise.py`），支持 status（查看内存状态）、optimize（一键优化）、daemon（守护模式）、profile（查看进程画像）、learn（学习进程行为）、auto-start（开机自启开关）、service（计划任务服务安装/移除）、reset（恢复出厂设置）等子命令。

*A CLI is available via `memwise.py`, supporting status, optimize, daemon, profile, learn, auto-start, service, and reset subcommands.*

---

## 2. 三层清理引擎 · *Three-Layer Cleaning Engine*

### 2.1 Layer1 — 系统级内核清理 · *System-Level Kernel Reclamation*

系统级清理通过调用 `NtSetSystemInformation` 等 Windows 内部 API 实现，涵盖 6 种操作的独立开关。全部操作码已对齐 PHNT 标准（MemoryEmptyWorkingSets=2、MemoryFlushModifiedList=3、MemoryPurgeStandbyList=4、MemoryPurgeLowPriorityStandbyList=5）。**开关优先**：设置面板中取消勾选的操作在任何模式下都不执行；勾选的操作映射为对应内核调用（`standby` 含低优先与全量两级、`filecache` 含双通道清空、`ws` 在 deep/full 下含系统级全清 WS），零 sleep，<10ms。

*System-level operations use NtSetSystemInformation and related internal Windows APIs, with all operation codes aligned to the PHNT standard enumeration values. The six settings-panel toggles are authoritative: an operation deselected in Settings is never executed in any mode; each selected toggle maps to its kernel calls (standby covers the low-priority and full purge tiers, filecache covers both clear channels, ws includes the system-wide working-set flush under deep/full). Zero deliberate sleep, sub-10ms total latency.*

| 操作 | 配置键 | 默认 | Win32 API | 说明 |
|------|--------|:----:|-----------|------|
| 进程闲置页释放 | `ws` | 开 | `EmptyWorkingSet` | 释放非活跃物理页，是唯一不需要管理员的进程级操作 · *Release idle physical pages; the only operation that does not require elevation* |
| Standby List 清理 | `standby` | 开 | `NtSetSystemInformation(80, info=4)` | 清空系统缓存页 · *Purge the system cache page list* |
| Modified Page 写回 | `modified` | 开 | `NtSetSystemInformation(80, info=3)` | 脏页写回磁盘后回收 · *Flush dirty pages to disk before reclaiming* |
| 系统文件缓存 | `filecache` | 关 | `SetSystemFileCacheSize` | 清空文件系统缓存，会降低文件操作速度直到重建 · *Clear the file system cache; reduces file I/O performance until cache rebuilds* |
| 卷缓存刷新 | `volume` | 开 | `CreateFileW+FlushFileBuffers` | 卷级别缓存刷新 · *Per-volume write buffer flush* |
| 注册表缓存 | `registry` | 开 | `NtSetSystemInformation(81)` | 清除注册表缓存页 · *Clear registry cache pages* |

守护模式下的高频阶段仅执行注册表缓存清理（零磁盘影响），standby 与脏页写回由 gap 末 optimize 统一执行——缓存有累积时间，单次释放量更大。为控制功耗，卷缓存冲刷等重量级操作仅在 optimize 全量收割阶段执行。

*High-frequency suppression touches only the registry cache (zero disk impact); standby and dirty-page flush are batched into each gap-end optimize pass so the cache accumulates before each purge, and heavyweight operations such as volume flush run only during full-harvest passes.*

四种清理模式的操作梯度由轻到重：

| 模式 | WS全清 | 进程trim | 文件缓存 | Layer3 | 操作数 | 适用场景 |
|------|:--:|:--:|:--:|:--:|:--:|------|
| quick | ❌ | ❌ | ❌ | ❌ | 3步 | 临时快速释放，零感知 |
| normal | ❌ | ✅ | ❌* | 高压触发 | 5步 | 日常极致优化，无副作用 |
| deep | ✅ | ✅ | ✅* | 始终 | 8步 | 重度使用后深度清扫 |
| full | ✅ | ✅ | ✅* | 强制 | 8步+回弹二轮 | 极限释放 |

* 系统级 WS 全清仅 deep/full 执行；「系统文件缓存」需在设置中勾选（勾选后任意模式均执行）；各模式实际操作数随开关勾选变化（开关优先）。

*Mode gradient (quick→full): 3 ops, zero perceptible impact — 5 ops, daily no-side-effect — 8 ops, deep post heavy use — 8 ops + rebound second round, maximum release. System-wide WS flush runs only in deep/full; the File Cache toggle enables that operation in any mode (toggles are authoritative).*

### 2.2 Layer2 — 进程级闲置页释放 · *Per-Process Idle Page Reclamation*

对每个非自身进程调用 `EmptyWorkingSet`，释放其物理内存中的非活跃页。决策链路：

*Invokes EmptyWorkingSet on non-self processes to release idle physical pages. The decision pipeline follows:*

1. **安全过滤 · Safety Gate**：排除系统核心进程、前台窗口保护（压力达到阈值时放开）、工作集过小的微小进程、WS 基线检查（上一轮清理后 WS 无增长则不重复清理）、失败冷却检查 · *Excludes system-core processes, foreground windows, tiny processes, baseline-checked processes, and processes in failure cooldown*

2. **策略投票（三树决策）· Three-Tree Policy Vote**：Kalman 预期收益、内存压力与趋势、反事实优势（对比全体画像均值）。各树贡献经在线学习的权重加权（权重可为负，按清理结果持续调节预测可靠度），加权总分 ≥ 0 即通过（不设硬性门槛）· *Kalman-predicted gain, memory-pressure and trend, and counterfactual advantage over the profile average — contributions weighted by online-learned per-tree weights (can be negative), soft pass threshold of weighted total ≥ 0*

3. **复合评分排序 · Composite Score Ranking**：θ、Kalman 预期释放量、WS 大小、WS 回弹率、预期 PF 代价（低代价优先）五维加权，EFIS 可调权重 · *Five-dimensional weighted ranking — θ, Kalman expected gain, WS size, regrowth rate, and expected PF cost (lower cost ranks first) — with EFIS-tunable weights*

4. **PID 增益调度 · PID Gain Scheduling**：根据当前内存压力自动分三区调节响应强度——低压（<40%）保守、中压（40–75%）标准、高压（>75%）激进 · *Three-zone scheduling: conservative below 40%, standard at 40–75%, aggressive above 75%*

5. **并行执行 · Parallel Execution**：最多 8 线程池（按 CPU 核数自适应），按评分降序提交 · *Up to 8-worker thread pool (CPU-core-adaptive), in descending score order*

6. **自适应 Pass 数 · Adaptive Pass Count**：大进程（WS>200 MB 或 θ 超阈值）→ 用户设定上限（默认 4）；中进程 → 3；低 θ → 1。天花板由设置面板 `clean_passes` 直接决定 · *Large processes: user-configured ceiling (default 4); mid: 3 pass; low-θ: 1 pass. The ceiling is directly set by the clean_passes slider*

7. **PF 反馈（先收后审）· PF Feedback (Collect-First, Judge-Later)**：对比清理前后缺页计数。释放量无条件计入统计，缺页仅用作 Thompson 学习信号的正负向判定 · *Freed bytes always counted; PF excess only affects the learning signal*

### 2.3 Layer3 — 深度重复清理 · *Deep Iterative Reclamation*

deep 模式末次 optimize 及 full 模式全程执行。依次为：

- 深度待机回收预处理（脏页写回 + 待机清空）· *Deep standby prepass (dirty page flush + standby purge)*
- 全量 Standby List 收割（低优先→全量→冲刷脏页三层）· *Full standby reclamation in three tiers*
- 文件缓存 / 卷缓存 / 注册表（按设置）· *File, volume, and registry cache as configured*
- WS 回弹率筛选：从 Layer2 未清理的进程中选出高回弹进程追加一次清理 · *High-rebound process selection from Layer 2 bypasses for additional trim*
- 深度清理净增量追踪，用于 EFIS 判断 Layer3 的价值 · *Net delta tracking for EFIS to evaluate Layer 3 effectiveness*

*Executed during the final optimize pass in deep mode and throughout full mode, with deep standby prepass, full standby reclamation, cache operations as configured, high-rebound process re-trim, and net-delta tracking for EFIS evaluation.*

### 2.4 持续优化架构 · *Continuous Optimization Architecture*

守护模式的每个 60 秒周期内，在 deadline 驱动下交替执行轻量压制与全量收割。自适应 gap 根据每轮的单位进程释放量变化率自动收敛至 8-20 秒（游戏模式 ×1.5 拉长），用户可通过设置面板调节基准间隔（默认 12 秒）。高回填进程通过 fast-track 标记在压制阶段获得高频修剪，全量收割阶段再执行完整的系统级管线。守护周期有完整的超时保护体系——单进程 8 秒、单次 harvest 30 秒硬超时，超时后周期补偿机制自动在下一轮追回。

*Each 60-second daemon cycle alternates between lightweight suppression and full harvesting under deadline-driven scheduling. The adaptive gap converges to 8–20 seconds (×1.5 in game mode) based on per-process release rate changes, with a user-configurable base interval (default 12s) in the settings panel. Fast-tracked high-refill processes receive frequent light trims during suppression; the complete pipeline executes during the harvesting phase. A comprehensive timeout defense — 8s per-process, 30s per-harvest — with automatic cycle compensation prevents any single operation from stalling the daemon.*

---

## 3. 认知引擎 · *Cognitive Engine*

### 3.1 Thompson Sampling (Beta-Bernoulli) · *Thompson Sampling*

对每个进程维护一对 Beta 分布 (α, β)。清理成功后 α 增量按释放量对数缩放（释放越多学习越快），失败后 β+=1。采样得到的 θ ∈ [0,1] 表示该进程在当前知识状态下值得清理的倾向。

*Each process maintains a conjugate Beta distribution. Success increments α with a magnitude scaled logarithmically by freed volume — larger releases produce faster learning — while failure increments β by one. The sampled θ represents the process's estimated cleanup desirability under current knowledge.*

- **先验 · Prior**：Beta(α=2, β=1)，偏乐观，相当于已经观察到 1 次成功
- **软上限 · Soft Cap**：α 超过阈值后等比缩归，保持 α/β 比例不畸变，防止长期运行后探索能力退化
- **对数缩放学习率 · Log-Scaled Learning Rate**：α 增量按释放量对数缩放——释放 500MB 的学习速度是释放 5MB 的约两倍，使大释放量产生更强的正反馈
- **时间遗忘 · Temporal Decay**：距离上次反馈超过 1 小时后，每小时向先验回归 5%（上限 50%），避免历史数据对当前状态的滞后影响
- **置信度 · Confidence**：基于 Beta 分布标准差计算，用于策略投票中的权重调节

### 3.2 Kalman 滤波器 · *Kalman Filter*

为每个进程维护两个独立的标量卡尔曼滤波器，分别追踪预期释放量（bytes）和预期的缺页代价，比 Beta 更能捕捉连续值的实际量级和不确定性。

*Two independent scalar Kalman filters per process track expected freed bytes and expected page-fault cost, capturing continuous magnitudes and uncertainties more effectively than Beta alone.*

- 自适应过程噪声：根据新息大小动态调整跟踪速度与稳定性的平衡 · *Adaptive process noise adjusts tracking speed vs. stability based on innovation magnitude*
- 时间衰减：长时间未观测的估计值协方差有界增长（上限 400），保证重新遇到该进程时能快速收敛且不被单次观测完全覆盖 · *Stale covariance grows with a hard cap (400) after extended idle periods for rapid re-convergence without letting a single observation fully overwrite the estimate*
- 观测噪声作为 EFIS 参数开放配置（`kalman_r`，1.0-20.0），可通过界面/配置调整对新观测的敏感度 · *Observation noise is exposed as an EFIS parameter (kalman_r, 1.0-20.0) tunable via UI/config to control sensitivity to new observations*

预测值在进入决策前经过在线学习的上下文修正——基于内存压力、前台状态和时段的三维查找表，自动学习当前条件下的实际释放量与 Kalman 基线的偏差比例，使 LP (低压) 和 HP (高压) 场景下的估值精确度大幅提升。

*Before entering the decision pipeline, Kalman predictions pass through an online-learned context correction layer — a three-dimensional lookup table indexed by memory pressure, foreground status, and time-of-day, which automatically learns the deviation ratio between actual freed bytes and the Kalman baseline under each condition.*

### 3.3 内存泄漏检测 · *Memory Leak Detection*

系统对每个进程维护工作集的 Z-score 基线与趋势斜率。当工作集持续偏离历史均值超过两个标准差，且相对增长斜率超过阈值时，判定为疑似内存泄漏并在诊断日志中提示。泄漏数据仅作观察记录，不参与清理决策。阈值根据进程自身的工作集大小自动缩放——大进程敏感度更高，小进程避免误报。

*Each process maintains a Z-score baseline and trend slope over its working set history. When the WS persistently exceeds two standard deviations above the historical mean, the system logs a diagnostic alert. Leak data is for observation only and does not affect cleaning decisions.*

### 3.4 分层先验 · *Hierarchical Prior*

10 个预定义类别按进程名关键词自动分类。新进程从同类经验池继承初始 θ，避免从零基础开始。

*Ten predefined categories auto-classify processes by name keyword. New processes inherit the average θ of their category, avoiding a cold start from the default prior.*

### 3.5 五树投票框架（启用 3 树）· *Five-Tree Policy Voting (3 Active)*

替代单一门槛的多维综合决策：

*A multi-dimensional decision model replaces single-threshold gating:*

- **收益树 · Gain Tree**：Kalman 预期释放量（经上下文修正），权重最高
- **压力树 · Pressure Tree**：内存占用与趋势——高于 65% 加分、低于 30% 减分
- **反事实树 · Counterfactual Tree**：Kalman 预期释放量对比全体画像均值——高于均值 50MB 加分、20MB 小加分
- **在线权重学习 · Online Weight Learning**：每轮清理后按"预测贡献 × 实际结果"调节各树权重（有界 ±2）——正贡献+成功升权重、正贡献+失败降权重、负贡献+成功降权重（可为负），使投票随经验收敛

加权总分 ≥ 0 通过（不设硬性门槛）。*Weighted total ≥ 0 passes (no hard threshold).*

---

## 4. 元认知自我监控 · *Meta-Cognitive Self-Monitoring*

每个守护周期运行一次完整诊断，逐画像独立评估：

*A diagnostic cycle runs every daemon tick, evaluating:*

- **概念漂移 · Concept Drift**：双 EWMA 快慢速比检测进程行为突变。漂移时重置 Kalman 过程噪声，加速适应新行为模式 · *Dual EWMA fast/slow ratio detects sudden process behavior changes, resetting Kalman process noise to accelerate adaptation*
- **探索覆盖 · Exploration Coverage**：统计从未被试探的进程比例，超阈值时加速未试探进程的探索频率 · *Monitors never-probed process ratio and accelerates probe frequency when coverage is low*

---

## 5. EFIS v3 全程序智能调参 · *System-Wide Intelligent Parameter Tuning*

EFIS（Efficiency Feedback Intelligent System）是全程序覆盖的闭环调参引擎，8 参数自动寻优（`deepen_theta`/`layer3_agg_gate`/`pid_kp`/`pid_kd`/`target_usage`/`cooloff_base`/`learning_rate`/`composite_kalman_w`）+ `kalman_r` 配置可调。

*EFIS is a 9-parameter closed-loop tuning engine spanning the entire system.*

**参数一览 · Parameter Overview**：

| 参数 | 默认值 | 范围 | 控制的内容 |
|------|:----:|:----:|------|
| `deepen_theta` | 0.60 | 0.30-0.80 | 大进程 trim 升级门槛 |
| `layer3_agg_gate` | 0.60 | 0.30-0.70 | 深度聚合触发阈值（仅 normal 模式寻优） |
| `pid_kp` | 0.60 | 0.30-2.00 | PID 比例增益（对内存偏差的响应速度） |
| `pid_kd` | 0.10 | 0.05-0.50 | PID 微分增益（抑制震荡） |
| `target_usage` | 60% | 35-65% | PID 控制目标内存占用百分比 |
| `cooloff_base` | 360s | 60-360s | 失败冷却基准时长 |
| `learning_rate` | 0.50 | 0.10-0.90 | EWMA 反馈学习率（接入收益/成本 EWMA：振荡大降、稳定低效升） |
| `composite_kalman_w` | 0.30 | 0.10-0.50 | 复合评分中 Kalman 分量的权重 |
| `kalman_r` | 5.0 | 1.0-20.0 | 卡尔曼观测噪声——值越大对新观测越不敏感 |

**诊断方式 · Diagnosis**：每个参数配备专属的症状规则，基于滑动窗口内的释放效率、缺页速率、内存振幅等多维指标综合评估。症状须持续达到确认周期后才触发调整，防止单次噪声误调。参数调整步长经过约束，不会剧烈震荡。协方差监控层在检测到两个参数反向调整时冻结步长较小的一方，防止补偿性震荡。

*Each parameter has dedicated symptom rules evaluated over sliding windows of release efficiency, PF rate, and memory amplitude. Adjustments require symptom persistence across a confirmation interval to prevent noise-induced false positives. Step magnitudes are bounded. A covariance monitor detects opposing adjustment signals between parameter pairs and freezes the one with the smaller step size to prevent compensatory oscillation.*

**持久化 · Persistence**：独立状态文件，写入采用原子化操作，防止中途崩溃导致配置损坏。

**场景自适应 · Scene Adaptation**：守护周期内自动检测运行场景（游戏/浏览器/开发/常规），场景切换时按 7:3 混合新场景参数并持久化，各场景独立调参互不干扰。

*An independent state file with atomic write semantics (tmp-then-replace). Deprecated parameters are silently skipped on load; missing new parameters default to their factory values.*

---

## 6. 内存优先级管理 · *Memory Priority Management*

系统通过 `NtSetInformationProcess` 直通向 OS 传递偏好级别：对高价值大进程（学习评分高且内存占用大）启用 EcoQoS 节能标记——系统会更积极回收其物理内存页；游戏名单进程保持默认节能状态以确保游戏流畅。内存优先级（ProcessMemoryPriority）在支持的 Windows 版本上按学习评分分层尽力设置。这是操作系统层面的被动优化，不消耗额外 CPU 或 I/O。

*High-value large processes (high learning score, large memory footprint) receive EcoQoS power-throttling hints via direct NtSetInformationProcess calls, so the OS reclaims their physical pages first; game-list processes stay at the default state for smooth gaming. Memory priority is applied on a tiered best-effort basis where supported. A passive OS-level optimization with zero CPU or I/O overhead.*

---

## 7. 游戏模式 · *Game Mode*

通过进程名匹配（内置已知游戏清单 + 用户自定义名单）和全屏窗口检测（含类名过滤排除浏览器等伪全屏窗口）自动激活，也可通过主界面按钮或 Ctrl+Shift+G 手动切换（含确认弹窗防误触）。手动设置的模式持续生效，自动检测不再覆盖，直到用户再次手动切换或程序重启；游戏运行期间 PID 保护集仍实时刷新。

激活后实施三层天花板保护：

- **进程级绝对保护**：游戏进程及其全部子进程树（反作弊、更新器等）的 PID 被实时追踪，`EmptyWorkingSet` 清理、内存优先级降权、`can_trim`/`can_probe` 判定对所有匹配进程自动跳过，游戏工作集完全不受触碰 · *Game PIDs and their entire descendant process trees (anti-cheat, updaters, etc.) are tracked in real time — WS trims, priority demotion, and can_trim/can_probe gating all auto-skip matched processes*
- **系统级操作抑制**：standby 清空、脏页写回、文件缓存清空、卷缓存冲刷在游戏模式全部跳过，仅保留注册表缓存清理——零磁盘 I/O，消除游戏读盘竞争 · *Standby purge, dirty-page flush, file-cache clear, and volume flush are all suppressed in game mode; only registry-cache cleanup remains — zero disk I/O, eliminating read contention with the game*
- **非游戏智能释放**：非游戏进程按智能评分持续清理（受门槛约束，前台窗口与排除列表受保护），内存优先级降为低优先，操作系统优先回收其页面供游戏使用 · *Non-game processes are continuously cleaned by intelligent scoring (gated by thresholds; foreground and excluded processes are protected) and demoted to low memory priority so the OS reclaims their pages for the game first*
- **操作频率自适应**：gap 间隔从常规 12s 拉长至 18s（游戏模式自动 ×1.5），降低守护周期对系统的干预密度 · *Gap interval extended from 12s to 18s (auto ×1.5 in game mode) to reduce daemon intervention density*

退出检测为即时模式，恢复运行中已调优的参数。常规参数不受游戏模式切换影响。

*Auto-activated via process-name matching plus full-screen detection, or toggled manually from the UI or Ctrl+Shift+G with a confirmation dialog. Manual mode persists until toggled again or restart; the PID protection set keeps refreshing in real time during gameplay, while exit detection is immediate and regular parameters resume on the next cycle.*

---

## 8. 图表与效率评分 · *Charting & Efficiency Scoring*

图表数据源为统一的释放量累加器——所有操作的释放量统一汇入，通过累计差值法计算每轮增量，不依赖惰性更新的系统 API。日志、统计栏、图表三者同源一致。X 轴显示最近的轮次数据，折线为 ERIS v6 效率评分（0–100%+，上不封顶）。ERIS 以 IQR 分位数归一化五个维度——预测精准度、释放效率、副作用控制、参数收敛度、探索完备度——每个维度以自身特异性滚动窗（释放效率 25 轮、参数收敛 8 轮、其余 20 轮）的中位数和四分位距(IQR)为基准，经 trimmed IQR 去极值与内插分位，通过 80 + 40×(raw−p50)/IQR（scale=40）将原始值映射为独立分数，释放效率维度经对数压缩，五个加权求和后得到最终效率分。游戏模式切换时自动重置受影响维度的分位数窗。分数真实反映算法引擎相对于自身常态的运转质量。前 3 轮收敛期折线及折点以虚线标示；效率 >100% 时折点显示金色、<60% 时显示珊瑚红色以示警戒。因子取自各维相对 IQR 中心(80)的偏离度——效率上升取正面偏离最大者，下降取负面偏离最大者；±2% 内波动显示相对平稳。效率 ≥100% 时追加"🚀效率超常"标签，≤60% 时追加"⚠效率异常"标签。"🔥持续改善"/"⚠持续下滑"标签仅在正常范围（60-100）内且最近三连轮次同向时触发，设有极性区间连续性保护。同维正负设有防振荡保护，平稳期自动重置防振荡状态防止方向残留。鼠标悬浮可查看真实数值及当轮主导因素。图表区域下方标注平均效率与关键统计指标。

*A single unified freed-bytes accumulator feeds all displays. Per-cycle deltas are computed via cumulative differencing — independent of the lazily-updated system API — keeping logs, the status bar, and the chart in lockstep. The chart renders recent-cycle bars overlaid with the ERIS v6 efficiency line (0–100%+, uncapped). ERIS employs IQR quantile normalization across five dimensions — prediction accuracy, release efficiency, side-effect control, parameter convergence, and exploration completeness — each with its own dimension-specific rolling window (25 cycles for release efficiency, 8 for parameter convergence, 20 for the rest), trimmed-IQR outlier removal, interpolated quantiles, EWMA-smoothed medians, and a log-compressed release-efficiency raw. Scores map via 80 + 40×(raw−p50)/IQR (scale=40) and are weighted-summed into the final efficiency score. Affected quantile windows auto-reset on game-mode transitions. The score genuinely reflects engine performance relative to its own norm. The first 3 data points render as dashed lines/dots during convergence; golden dots mark scores above 100%, coral-red dots warn below 60%. Factor selection uses each dimension's deviation from the IQR center (80) — rising efficiency picks the largest positive deviation, falling picks the largest negative; ±2% fluctuation shows as relatively stable. Scores ≥100% append a 🚀 efficiency-exceptional tag, ≤60% a ⚠ efficiency-abnormal tag; 🔥 sustained-improvement / ⚠ sustained-decline tags trigger only within the normal range (60–100) on three consecutive same-direction cycles, with polarity-continuity protection. Anti-oscillation guards prevent same-dimension flip-flopping, and stable periods auto-reset anti-oscillation state. Hover tooltips reveal true values and the dominant factors. Below the chart: average efficiency and key statistics.*

---

## 9. 进程排行 · *Process Ranking*

点击"进程排行"按钮弹出独立窗口，显示所有活跃进程的快照。排序列包括进程名、进程号、私有内存、CPU 占用、以及学习画像数据。每 3 秒自动刷新。

*A standalone window displays a live snapshot of all active processes, with columns for name, PID, private memory, CPU usage, and learned profile data. Refreshes every 3 seconds.*

内存数据的采集优先使用内核批量查询接口，无需对每个进程执行 `OpenProcess`，可绕过安全软件的进程保护机制。

*Memory data is collected via a kernel bulk-query API that requires no per-process OpenProcess, bypassing security-software process protection.*

---

## 10. 学习日志 · *Learning Log*

点击"学习日志"按钮弹出独立窗口，按进程名排序显示所有已学习进程的画像数据：α/β（历史成功与失败累计，决定可信度）、样本数、可信度（θ）、收益比（MB/PF）、偏差（Z-score）、趋势（内存增长斜率）、泄漏标记、清理/试探成功/试探失败次数。支持滚动浏览。

*A standalone window lists every learned process's full profile — α/β (cumulative successes/failures driving confidence), sample count, θ confidence, ROI (MB/PF), Z-score deviation, WS trend slope, leak flag, and clean/probe success and failure counts — sorted by process name with scroll navigation.*

---

## 11. 设置面板 · *Settings Panel*

设置面板提供以下可配置项，所有更改即时保存；守护运行中排除列表、清理操作、清理深度、全局热键即时生效，其余重启后生效：

*All changes are saved immediately. During daemon operation, the exclusion list, cleaning operations, cleaning depth, and global hotkeys take effect instantly; other changes apply on the next restart.*

**启动设置 · Startup**：开机自启（快捷方式）、管理员权限启动（计划任务）、启动时自动开启守护、启动后最小化到托盘。

*Auto-start with Windows (shortcut), elevated auto-start (scheduled task), auto-enable daemon on launch, start minimized to tray.*

**关闭按钮行为 · Close Behavior**：最小化到托盘（守护继续运行）、直接退出程序、每次询问（默认）。

*Minimize to tray (daemon continues), exit immediately, or ask each time (default).*

**清理操作 · Operations**：6 种操作独立开关：ws、standby、modified、filecache、volume、registry。除系统文件缓存默认关闭外，其余默认开启。

*Six independent toggles: ws, standby, modified, filecache, volume, registry. All default on except the system file cache.*

**游戏模式 · Game Mode**：管理自定义游戏进程名单（一体化窗口：列出/添加/删除，逗号分隔批量输入、重复项提示、删除带确认，内置名单只读展示）。主界面设有独立开关按钮，也可通过 Ctrl+Shift+G 热键一键切换。

*Manage custom game process entries (add/view), with comma-separated batch input and case-insensitive matching. A dedicated toggle button on the main UI and the Ctrl+Shift+G hotkey provide one-click game mode switching.*

**触发与日志 · Trigger & Logging**：紧急触发阈值（50-99%，默认 80%）、守护清理间隔（8-20 秒，默认 12）、托盘左键行为、文件日志开关、进程清理深度（2-6 pass，默认 4；超大进程的 pass 数直接以此为准，其余档位不受影响）。

**全局热键 · Global Hotkeys**：独立栏汇总所有快捷键——手动优化（默认 `ctrl+shift+m`）与游戏模式开关（默认 `ctrl+shift+g`），各自独立配置。格式校验（至少一个修饰键 + 单字母/F1-F24）、双键冲突检测、注册占用提示（被其他程序占用时本次使用默认值），修改即时生效。

*Emergency trigger threshold (50–99%, default 80%), daemon clean interval (8-20s, default 12s), tray left-click action, file-log toggle, and cleaning depth (2–6 pass, default 4; large-process ceiling directly follows this value, other tiers unaffected). Global hotkeys — manual optimize (default ctrl+shift+m) and game-mode toggle (default ctrl+shift+g) — are independently configurable with format validation (at least one modifier + a letter or F1-F24), conflict detection, and busy-key fallback, taking effect instantly.*

---

## 12. 日志系统 · *Logging System*

主界面右侧为日志区域。每轮输出本轮释放量、系统操作次数、整理进程数、试探/成功数等关键指标。周期内的算法诊断消息（元认知校准、概念漂移、EFIS 调参等）被缓冲至周期末，与压力强度日志和汇总行批量输出——当前面板行数+批量条数>7 时自动清旧再显示。游戏检测/退出消息实时推送，按钮点击等交互消息走即时通道。

*The log panel outputs per-cycle key metrics — freed amount, system operation count, trimmed process count, and probe success rate. Intra-cycle diagnostic messages (meta-cognitive calibration, concept drift, EFIS tuning, deep-clean triggers) are buffered and flushed at cycle end together with the summary line. When the combined line count of the existing panel plus the new batch exceeds seven, old content is cleared before output, ensuring every message in the batch remains visible for at least one full cycle. Real-time messages (button clicks, game detection) continue to appear immediately.*

**统一运行日志 · Unified Runtime Log**：除界面日志外，程序在可执行文件目录维护统一日志 `memwise.log`，由设置中「记录运行日志到文件」开关总控——开启后按时间线记录运行期间全部有价值信息（启动/退出、每轮清理摘要、游戏模式决策、EFIS 调参、配置保存、未捕获异常与崩溃现场、诊断信息），关闭则不写任何日志。每条带毫秒时间戳与类别标签（`[启动][清理][决策][调参][配置][异常][系统][诊断][界面]`）。容量 2MB×2 份轮转（`memwise.log.1` 保留最近两份，自动删除最旧），线程安全写入不交错，运行时切换开关即时生效。旧版 `memwise_crash.log` 在首次开启时自动并入，历史现场不丢失。

*Besides the on-screen panel, MemWise maintains a unified runtime log `memwise.log` next to the executable, controlled by the 「log to file」toggle in Settings — when enabled, it records every valuable event along a single timeline (startup/shutdown, per-cycle cleanup summaries, game-mode decisions, EFIS tuning, config saves, uncaught exceptions and crash dumps, diagnostics); when disabled, nothing is written. Each line carries a millisecond timestamp and a category tag (`[启动][清理][决策][调参][配置][异常][系统][诊断][界面]`). The file rotates at 2 MB with two generations (`memwise.log.1`), deleting the oldest automatically; writes are thread-safe and the toggle takes effect immediately at runtime. Legacy `memwise_crash.log` content is merged in on first enable, so no history is lost.*

---

## 13. 命令行工具 · *Command-Line Tools*

```
python memwise.py [command] [options]
```

| 命令 | 说明 |
|------|------|
| `status` | 查看当前物理内存使用状态 |
| `learn [分钟]` | 采集并学习进程内存行为 |
| `optimize [--mode MODE]` | 单次优化（支持 quick/normal/deep/full） |
| `daemon [--mode MODE]` | CLI 守护模式 |
| `profile <PID>` | 查看指定进程的完整学习画像 |
| `auto-start on\|off` | 开机自启（启动文件夹快捷方式） |
| `service [remove]` | 安装/移除计划任务服务（系统启动自动运行，需管理员） |
| `reset` | 恢复出厂设置（备份并移除配置与画像） |

*Commands: status — memory overview; learn [minutes] — observe and learn process behavior; optimize [--mode MODE] — run one optimization pass (quick/normal/deep/full); daemon [--mode MODE] — CLI daemon mode; profile <PID> — per-process learning profile; auto-start on|off — startup-folder shortcut; service [remove] — scheduled-task service (requires administrator); reset — factory reset (backs up config and profile).*

---

## 14. 配置项 · *Configuration*

`config/config.yaml` 完整配置项：

| 键 | 类型 | 默认值 | 说明 |
|------|------|:------|------|
| `clean_mode` | str | `"normal"` | 清理模式 |
| `clean_operations` | list | `[ws,standby,modified,volume,registry]` | 启用的操作 |
| `kp` | float | `1.0` | PID 比例系数（`efis_params.pid_kp` 优先） |
| `ki` | float | `0.15` | PID 积分系数 |
| `kd` | float | `0.1` | PID 微分系数（`efis_params.pid_kd` 优先） |
| `target_usage` | int | `45` | PID 控制目标内存占用（%，`efis_params.target_usage` 优先） |
| `auto_start` | bool | `false` | 开机自启 |
| `auto_start_admin` | bool | `false` | 管理员权限开机自启 |
| `auto_start_daemon` | bool | `false` | 启动后自动守护 |
| `auto_start_minimize` | bool | `false` | 启动后最小化 |
| `close_action` | str | `"ask"` | 关闭按钮行为 |
| `interval` | int | `60` | 守护周期（秒；daemon 按此调度日志/图表与收割节奏） |
| `gap_seconds` | int | `12` | 守护清理间隔（秒） |
| `emergency_threshold` | int | `80` | 紧急触发阈值（%） |
| `clean_passes` | int | `4` | 进程清理深度（2-6） |
| `tray_left_action` | str | `"show"` | 托盘左键行为 |
| `log_to_file` | bool | `false` | 记录运行日志到文件 |
| `hotkey` | str | `"ctrl+shift+m"` | 手动优化热键 |
| `game_hotkey` | str | `"ctrl+shift+g"` | 游戏模式开关热键 |
| `never` | list | `[]` | 排除列表（进程名或 PID） |
| `game_processes` | list | `[]` | 自定义游戏 exe 名 |
| `efis_params` | dict | 9 参数默认值 | EFIS 参数 |

*Full configuration lives in config/config.yaml; the defaults above mirror DEFAULT_CFG. `efis_params` holds the nine EFIS parameters, each with its own default/range as listed in Section 5; `target_usage` is overridden by `efis_params.target_usage` when present.*

---

## 15. 文件结构 · *File Structure*

```
MemWise/
├── memwise_gui.py              # GUI 主程序 · GUI Application
├── memwise.py                  # CLI 命令行入口 · CLI Entry Point
├── config/config.yaml          # 配置文件（自动持久化）· Configuration
├── memwise_eris_ewma.json     # ERIS IQR 分位数窗持久化 · ERIS Quantile Window Persistence
├── memwise_state.json          # 学习数据文件（自动保存/加载）· Learned State
├── memwise_efis_state.json     # EFIS 状态文件 · EFIS State
├── watchdog.json               # 看门狗标记文件（自动管理）· Watchdog Marker
├── CHANGELOG.md                # 更新日志 · Changelog
├── README.md                   # 本文件 · This File
├── assets/icon.ico             # 程序图标 · Application Icon
├── assets/icons/               # 图标源文件（母版/扁平成品 PNG）· Icon Sources
├── core/
│   ├── cleaner.py              # 三层清理引擎 + 持续优化 · Cleaning Engine
│   ├── learner.py              # Thompson Sampling + Kalman + 特征学习 · Cognitive Learner
│   ├── judger.py               # 判定器 + PID 控制器 · Judger + PID
│   ├── efis.py                 # EFIS v3 全程序智能调参 · EFIS Parameter Tuner
│   ├── meta.py                 # 元认知自我监控 · Meta-Cognitive Monitor
│   ├── policy.py               # 五树投票策略（启用 3 树）· Policy Voter (5-tree, 3 active)
│   ├── kalman.py               # Kalman 滤波器 · Kalman Filter
│   ├── prior.py                # 分层先验 · Hierarchical Prior
│   ├── winapi.py               # Win32 API 绑定（70+ 函数）· Win32 API Bindings
│   ├── sniffer.py              # 进程快照采集 · Process Snapshot Collector
│   ├── icon_flat.py            # 任务栏扁平图标内嵌 PNG（base64）· Flat Icon Data
│   ├── eris.py                 # ERIS 效率评分纯函数（生产/测试共用）· ERIS Pure Functions
│   └── config.py               # 配置加载/保存 · Configuration Loader
├── scripts/
│   └── test_v2.6.py             # 回归测试（71 项断言）· Regression Suite
```

---

## 系统要求 · *System Requirements*

- Windows 10 20H1+ / Windows 11（部分缓存操作依赖较新版本）
- 管理员权限（缓存清理需要；进程 EmptyWorkingSet 不受限制）
- 无需安装任何第三方运行库

*Windows 10 20H1+ or Windows 11. Administrator elevation required for cache operations; per-process EmptyWorkingSet has no elevation requirement. No third-party runtime dependencies.*

---

> [GitHub Releases](https://github.com/fuguangbeta/MemWise/releases) — 下载最新版本 · *Download Latest Release*

---

## 支持与赞赏 · *Support & Appreciation*

如果你觉得 MemWise 帮上了忙，并且有充足的意愿和赞赏渠道支持这个小小的项目，可以扫一扫下方的微信赞赏码——赞赏本身比钞票面值更有意义！当然，你的使用与反馈本身就是对我最大的支持！

*If MemWise has been helpful, and you have the willingness and means to appreciate this small project, feel free to scan the WeChat reward QR code below — the appreciation itself means more than the amount. Of course, your usage and feedback are already the greatest support.*

<p align="center">
  <img src="assets/donate.png" width="240" alt="微信赞赏码 · WeChat Reward QR Code">
</p>
