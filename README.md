# MemWise v2.1

## Windows 智能内存看护工具 · *Intelligent Memory Custodian*

MemWise 是一款纯 ctypes Win32 API 构建的 Windows 内存优化与实时守护工具。通过调用 Windows 底层内存管理 API（NtSetSystemInformation、EmptyWorkingSet、SetSystemFileCacheSize 等），对进程闲置工作集、系统 Standby List、Modified Page List、内存压缩等进行细化治理，在不终止进程、不挂起线程、不注入、不联网的前提下实现物理内存的释放与压缩。支持 GUI 和命令行两种使用方式，以单 exe 分发（约 13.3 MB），零外部依赖。

*Built entirely on ctypes Win32 API with zero third-party dependencies, MemWise reclaims physical memory through disciplined management of idle working sets, standby lists, modified page lists, and memory compression — all without terminating processes, suspending threads, injecting code, or touching the network. Distributed as a single 13.3 MB executable.*


系统的核心价值在于"主动+持续"：在 Windows 自身内存压力感知机制启动之前提前介入回收，并在守护模式下保持 60 秒间隔内零空闲的持续优化。同时通过 Thompson Sampling、Kalman 滤波、泄漏检测、情景记忆、分层先验、五树投票等学习与决策机制，为每个进程建立独立画像，在最大化释放效率的同时抑制缺页副作用。

*MemWise intercepts memory pressure before Windows initiates its own reclamation, maintaining uninterrupted optimization at 60-second intervals in daemon mode. A cognitive engine combining Thompson Sampling, Kalman filtering, leak detection, episodic memory, hierarchical priors, and five-tree policy voting builds independent behavioral profiles per process, maximizing release efficiency while minimizing page-fault side effects.*

程序内嵌了轻量看门狗机制，可在意外崩溃后自动恢复运行状态，并为自身内存占用与运行功耗设立了严格的自律约束。

*An embedded watchdog subprocess restores daemon state within seconds of an unexpected crash. The program also enforces strict limits on its own memory footprint and power consumption.*

---

## 1. 运行模式 · *Operating Modes*

### 1.1 一键优化 · *One-Click Optimization*

点击主界面"优化"按钮（或按快捷键 Ctrl+Shift+M），程序执行单次完整的系统+进程深度清理，并输出累计释放量。每次手动优化执行 3 轮，累计来自 Layer1（8 步内核管线）、Layer2（进程闲置页）和 Layer3（深度回弹清洗）的释放量，最终显示对比优化前后的内存占用变化。

*Triggered via the Optimize button or Ctrl+Shift+M. Runs three consecutive passes spanning all three pipeline layers — Layer 1 kernel-level reclamation, Layer 2 per-process idle page release, and Layer 3 deep rebound cleaning — and displays the before-and-after memory delta.*

### 1.2 守护模式（推荐）· *Daemon Mode (Recommended)*

点击"守护"按钮启动，程序以 60 秒为日志/图表输出周期，在周期内执行零空闲持续优化。具体节奏为：

| 阶段 | 内容 |
|------|------|
| 自适应 gap | 根据上一轮每个进程的平均释放量自动调整间隔（8-25 秒），释放多则缩短、释放少则延长 |
| gap fill 轻量压制 | 持续执行 standby purge + modified flush + fast-track 修剪。轻量模式跳过系统级 WS 全清，留给主 pass 收割 |
| 多次 harvest | 周期内执行 2-3 次完整的 optimize pass（normal 模式），每次含 Layer2 进程修剪 + Layer1 轻量管线 |
| 主 pass 全量收割 | 末次 optimize 使用用户选定模式，Layer2 先行释放 → Layer1 全量 8 步管线（含系统级 WS 全清 + Standby 全量清空）→ Layer3 深度聚合 |

*Operates in 60-second log/chart cycles with uninterrupted optimization. An adaptive gap timer (8–25s) dynamically adjusts based on per-process release rates. Each cycle alternates between lightweight suppression — standby purge, modified flush, and fast-track re-trim without a system-wide WS clear — and full harvesting passes that cascade Layer 2 releases into a complete eight-step Layer 1 pipeline, followed by Layer 3 deep aggregation.*

守护模式启动后，窗口可关闭/最小化到托盘（根据设置自动选择或询问），程序在系统托盘区域显示实时内存占用图标，右键可调出菜单。守护状态、累计释放量、系统操作总次数、进程清理总次数等实时显示在主界面状态栏。日志区域实时输出算法诊断信息、优化量、EFIS 调参记录。图表区域以柱状图显示每轮释放量，折线显示效率评分。

*The window can be closed or minimized to the system tray. A real-time memory-usage icon appears in the notification area with a right-click context menu. The status bar displays daemon state, cumulative freed memory, system operation counters, and process trim counts. The log panel streams algorithmic diagnostics, optimization metrics, and EFIS tuning records, while the chart area renders per-cycle release bars overlaid with an ERIS efficiency line.*

程序内嵌看门狗子进程，主进程意外崩溃后可在数秒内自动重启并恢复守护状态。

*A watchdog subprocess automatically restores daemon state within seconds of an unexpected crash. A single-instance mutex prevents conflicts between recovered and manually launched instances.*

### 1.3 命令行 · *Command Line*

程序同时提供命令行接口（`memwise.py`），支持 status（查看内存状态）、optimize（一键优化）、daemon（守护模式）、profile（查看进程画像）、learn（学习进程行为）等子命令。

*A CLI is available via `memwise.py`, supporting status, optimize, daemon, profile, and learn subcommands.*

---

## 2. 三层清理引擎 · *Three-Layer Cleaning Engine*

### 2.1 Layer1 — 系统级内核清理 · *System-Level Kernel Reclamation*

系统级清理通过调用 `NtSetSystemInformation` 等 Windows 内部 API 实现，涵盖 8 种操作的独立开关。全部操作码已对齐 PHNT 标准（MemoryEmptyWorkingSets=2、MemoryFlushModifiedList=3、MemoryPurgeStandbyList=4、MemoryPurgeLowPriorityStandbyList=5），通过 8 步连续管线执行（零 sleep，<10ms）。

*System-level operations use NtSetSystemInformation and related internal Windows APIs, with all operation codes aligned to the PHNT standard enumeration values. The complete eight-step pipeline executes as a contiguous sequence with zero deliberate sleep and sub-10ms total latency.*

| 操作 | 配置键 | 默认 | Win32 API | 说明 |
|------|--------|:----:|-----------|------|
| 进程闲置页释放 | `ws` | 开 | `EmptyWorkingSet` | 释放非活跃物理页，是唯一不需要管理员的进程级操作 |
| Standby List 清理 | `standby` | 开 | `NtSetSystemInformation(80, info=4)` | 清空系统缓存页，配合系统级 WS 全清实现深度收割 |
| Modified Page 写回 | `modified` | 开 | `NtSetSystemInformation(80, info=3)` | 脏页写回磁盘后回收，配合 standby 收割 |
| 内存压缩触发 | `compress` | 开 | `NtSetSystemInformation(80, info=5)` | 触发 OS 内存压缩引擎，压缩后可释放物理页 |
| 系统文件缓存 | `filecache` | 关 | `SetSystemFileCacheSize` | 清空文件系统缓存，会降低文件操作速度直到重建 |
| 卷缓存刷新 | `volume` | 开 | `CreateFileW+FlushFileBuffers` | 卷级别缓存刷新 |
| 注册表缓存 | `registry` | 开 | `NtSetSystemInformation(81)` | 清除注册表缓存页 |
| 内存合并 | `combine` | 关 | `NtSetSystemInformation(80, info=3)` | 触发系统合并相同物理页 |

守护模式下的 gap fill 期间使用轻量管线（跳过系统级 WS 全清），只做 standby purge + modified flush，留给主 pass 在积累整个 gap 后一次性全量收割。为控制功耗，卷缓存冲刷等重量级操作仅在 optimize 全量收割阶段执行。

*During gap-fill phases, a lightweight pipeline skips the system-wide WS clear, performing only standby purge and modified flush. Heavyweight operations such as volume cache flushing are deferred to the full-harvest optimize pass to conserve power.*

### 2.2 Layer2 — 进程级闲置页释放 · *Per-Process Idle Page Reclamation*

对每个非自身进程调用 `EmptyWorkingSet`，释放其物理内存中的非活跃页。决策链路：

*Invokes EmptyWorkingSet on non-self processes to release idle physical pages. The decision pipeline follows:*

1. **安全过滤 · Safety Gate**：排除系统核心进程、前台窗口保护（压力达到阈值时放开）、工作集过小的微小进程、WS 基线检查（上一轮清理后 WS 无增长则不重复清理）、失败冷却检查 · *Excludes system-core processes, foreground windows, tiny processes, baseline-checked processes, and processes in failure cooldown*

2. **策略投票（五树决策）· Five-Tree Policy Vote**：Kalman 预测收益、历史记忆验证、时序活跃度判断、Kalman 反事实优势、复合评分加权。总分 ≥ 0 即通过（不设硬性门槛）· *Kalman-predicted gain, historical success verification, temporal activity judgment, counterfactual advantage, and composite weighting — soft pass threshold of total score ≥ 0*

3. **复合评分排序 · Composite Score Ranking**：θ、Kalman 预期释放量、WS 大小、WS 回弹率四维加权，EFIS 可调权重 · *Four-dimensional weighted ranking with EFIS-tunable weights*

4. **PID 增益调度 · PID Gain Scheduling**：根据当前内存压力自动分三区调节响应强度——低压（<40%）保守、中压（40–75%）标准、高压（>75%）激进 · *Three-zone scheduling: conservative below 40%, standard at 40–75%, aggressive above 75%*

5. **并行执行 · Parallel Execution**：4 线程池，按评分降序提交 · *Four-worker thread pool in descending score order*

6. **自适应 Pass 数 · Adaptive Pass Count**：大进程（WS>200 MB 或 θ 超阈值）→ 4 pass；默认 → 3 pass；低 θ → 1 pass · *Large processes: 4 passes; default: 3; low-θ: 1 pass*

7. **PF 反馈（先收后审）· PF Feedback (Collect-First, Judge-Later)**：对比清理前后缺页计数。释放量无条件计入统计，缺页仅用作 Thompson 学习信号的正负向判定 · *Freed bytes always counted; PF excess only affects the learning signal*

### 2.3 Layer3 — 深度重复清理 · *Deep Iterative Reclamation*

deep 模式末次 optimize 及 full 模式全程执行。依次为：

- 压缩 + 脏页写回 · *Compression + dirty page flush*
- 全量 Standby List 收割（低优先→全量→冲刷脏页三层）· *Full standby reclamation in three tiers*
- 文件缓存 / 卷缓存 / 注册表 / 内存合并（按设置）· *File, volume, and registry cache plus page combining as configured*
- WS 回弹率筛选：从 Layer2 未清理的进程中选出高回弹进程追加一次清理 · *High-rebound process selection from Layer 2 bypasses for additional trim*
- 深度清理净增量追踪，用于 EFIS 判断 Layer3 的价值 · *Net delta tracking for EFIS to evaluate Layer 3 effectiveness*

*Executed during the final optimize pass in deep mode and throughout full mode: compression + dirty page flush; full standby reclamation in three tiers; file, volume, and registry cache plus page combining as configured; high-rebound process selection from Layer 2 bypasses for additional trim; and net delta tracking for EFIS to evaluate Layer 3 effectiveness.*

### 2.4 持续优化架构 · *Continuous Optimization Architecture*

守护模式的每个 60 秒周期内，在 deadline 驱动下交替执行轻量压制与全量收割。自适应 gap 根据每轮的单位进程释放量变化率自动收敛至 8-25 秒。高回填进程通过 fast-track 标记在压制阶段获得高频修剪，全量收割阶段再执行完整的系统级管线。为降低运行功耗，快照采集在压制阶段适度降频，不影响 Learner 的 EWMA 画像精度。

*Each 60-second daemon cycle alternates between lightweight suppression and full harvesting under deadline-driven scheduling. The adaptive gap converges to 8–25 seconds based on per-process release rate changes. Fast-tracked high-refill processes receive frequent light trims during suppression; the complete pipeline executes during the harvesting phase. Snapshot frequency is moderately reduced during suppression to lower power consumption, with no impact on Learner EWMA fidelity.*

---

## 3. 认知引擎 · *Cognitive Engine*

### 3.1 Thompson Sampling (Beta-Bernoulli)

对每个进程维护一对 Beta 分布 (α, β)。每次清理成功后 α+=1，失败后 β+=1。采样得到的 θ ∈ [0,1] 表示该进程在当前知识状态下值得清理的倾向。

*Each process maintains a conjugate Beta distribution. Success increments α; failure increments β. The sampled θ represents the process's estimated cleanup desirability under current knowledge.*

- **先验 · Prior**：Beta(α=2, β=1)，偏乐观，相当于已经观察到 1 次成功
- **软上限 · Soft Cap**：α 超过阈值后等比缩归，保持 α/β 比例不畸变，防止长期运行后探索能力退化
- **对数缩放学习率 · Log-Scaled Learning Rate**：α 增量按释放量对数缩放——释放 500MB 的学习速度是释放 5MB 的约两倍，使大释放量产生更强的正反馈
- **时间遗忘 · Temporal Decay**：距离上次反馈超过 1 小时后，每小时向先验回归 3%，避免历史数据对当前状态的滞后影响
- **置信度 · Confidence**：基于 Beta 分布标准差计算，用于策略投票中的权重调节

### 3.2 Kalman 滤波器 · *Kalman Filter*

为每个进程维护两个独立的标量卡尔曼滤波器，分别追踪预期释放量（bytes）和预期的缺页代价，比 Beta 更能捕捉连续值的实际量级和不确定性。

*Two independent scalar Kalman filters per process track expected freed bytes and expected page-fault cost, capturing continuous magnitudes and uncertainties more effectively than Beta alone.*

- 自适应过程噪声：根据新息大小动态调整跟踪速度与稳定性的平衡 · *Adaptive process noise adjusts tracking speed vs. stability based on innovation magnitude*
- 时间衰减：长时间未观测的估计值协方差异步膨胀，保证重新遇到该进程时能快速收敛 · *Stale covariance asynchronously inflates after extended idle periods for rapid re-convergence*
- 观测噪声纳入 EFIS 自动调参范围，系统可根据实际预测误差自动寻优 · *Observation noise is exposed as an EFIS-tunable parameter for autonomous optimization against actual prediction error*

预测值在进入决策前经过在线学习的上下文修正——基于内存压力、前台状态和时段的三维查找表，自动学习当前条件下的实际释放量与 Kalman 基线的偏差比例，使 LP (低压) 和 HP (高压) 场景下的估值精确度大幅提升。

*Before entering the decision pipeline, Kalman predictions pass through an online-learned context correction layer — a three-dimensional lookup table indexed by memory pressure, foreground status, and time-of-day, which automatically learns the deviation ratio between actual freed bytes and the Kalman baseline under each condition.*

### 3.3 内存泄漏检测 · *Memory Leak Detection*

系统对每个进程维护工作集的 Z-score 基线与趋势斜率。当工作集持续偏离历史均值超过两个标准差，且相对增长斜率超过阈值时，判定为疑似内存泄漏。判定后的进程在守护周期中获得优先清理，同时其 Kalman 不确定性被调高以增加后续观测的权重。泄漏阈值根据进程自身的工作集大小自动缩放——大进程敏感度更高，小进程避免误报。

*Each process maintains a Z-score baseline and trend slope over its working set history. When the WS persistently exceeds two standard deviations above the historical mean with a relative growth slope exceeding the threshold, the system flags a suspected leak. Flagged processes receive prioritized cleanup in subsequent daemon cycles, and their Kalman uncertainty is elevated. The leak threshold scales automatically with the process's own working set size.*

### 3.4 情景记忆 · *Episodic Memory*

存储每次清理与试探的完整上下文 episode，包含时间戳、进程标识、工作集大小、系统内存占用率、动作类型、结果与释放量等十余项字段。以定长双端队列滚动存储。基于时间戳的持久映射实现 O(1) 检索，消除双端队列淘汰导致的索引漂移。检索时使用加权相似度评分，综合考量内存压力相似度、同名进程加成和时间衰减。支持按时间窗口查询同名进程的历史成功率。新进程通过分层先验获得同类进程的平均初始倾向，加速冷启动。

*Each cleanup or probe stores a full-context episode with over a dozen fields — timestamp, process identity, working set size, system memory percentage, action type, outcome, and freed bytes. A fixed-length deque provides bounded rolling storage. A persistent timestamp-based map enables O(1) retrieval immune to deque index drift. Retrieval uses weighted similarity scoring that combines memory-pressure proximity, same-name affinity, and temporal decay. Time-windowed historical success rates can be queried per process name. New processes receive an initial θ inherited from their category's hierarchical prior, accelerating cold-start convergence.*

### 3.5 分层先验 · *Hierarchical Prior*

十余个预定义类别按进程名关键词自动分类。新进程从同类经验池继承初始 θ，避免从零基础开始。

*Over a dozen predefined categories auto-classify processes by name keyword. New processes inherit the average θ of their category, avoiding a cold start from the default prior.*

### 3.6 五树投票策略 · *Five-Tree Policy Voting*

替代单一门槛的多维综合决策：

*A multi-dimensional decision model replaces single-threshold gating:*

- **Kalman 预测树 · Kalman Prediction Tree**：预期释放量与预期代价的比值，权重最高
- **历史记忆树 · Historical Memory Tree**：同压力下的历史成功率，情景记忆验证
- **时序时机树 · Temporal Timing Tree**：基于 24 小时时间槽的活跃度判断
- **反事实预测树 · Counterfactual Prediction Tree**：Kalman 预测的释放量差值——清理该进程相比最优替代进程的预期优势
- **复合评分树 · Composite Scoring Tree**：Kalman 置信度与 WS 趋势的综合加权

每棵树的权重通过在线学习自动调整——以每进程的实际清理结果为反馈信号，有效树的权重自然上升。总分 ≥ 0 通过（不设硬性门槛）。

*Tree weights are continuously tuned through online learning, using each trim outcome as feedback. Effective trees increase in relative weight over time. The soft pass threshold is a total score ≥ 0.*

---

## 4. 元认知自我监控 · *Meta-Cognitive Self-Monitoring*

每 5 个周期运行一次完整诊断（约 5 分钟），逐画像独立评估：

*A comprehensive diagnostic cycle runs every 5 cycles (~5 minutes), evaluating each profile independently:*

- **校准度 · Calibration**：每个画像独立对比 Kalman 预测与实际释放。偏差越大衰减越多——仅对不准确的画像渐进调整，精准的画像不受影响，替代旧版全局平均重置
- **概念漂移 · Concept Drift**：双 EWMA 快慢速比检测进程行为突变。漂移时温和调整 Beta 和 Kalman 参数
- **探索覆盖 · Exploration Coverage**：统计从未被试探的进程比例，超过阈值时适度提高探索倾向
- **学习率自校准 · Learning Rate Self-Calibration**：检查所有进程的预测误差，动态调整上下文权重学习率

---

## 5. EFIS v3 全程序智能调参 · *System-Wide Intelligent Parameter Tuning*

EFIS（Efficiency Feedback Intelligent System）是全程序覆盖的 10 参数闭环调参引擎。

*EFIS is a 10-parameter closed-loop tuning engine spanning the entire system.*

**参数一览 · Parameter Overview**：

| 参数 | 默认值 | 范围 | 控制的内容 |
|------|:----:|:----:|------|
| `deepen_theta` | 0.60 | 0.30-0.80 | 大进程 trim 升级门槛 |
| `layer3_agg_gate` | 0.60 | 0.30-0.90 | 深度聚合触发阈值 |
| `pid_kp` | 0.60 | 0.30-2.00 | PID 比例增益（对内存偏差的响应速度） |
| `pid_kd` | 0.10 | 0.05-0.50 | PID 微分增益（抑制震荡） |
| `target_usage` | 30% | 25-65% | PID 控制目标内存占用百分比 |
| `interval_high` | 10s | 5-20s | 高压时的日志输出间隔 |
| `cooloff_base` | 300s | 60-360s | 失败冷却基准时长 |
| `learning_rate` | 0.30 | 0.05-0.40 | 上下文特征权重学习速率 |
| `composite_kalman_w` | 0.30 | 0.10-0.50 | 复合评分中 Kalman 分量的权重 |
| `kalman_r` | 5.0 | 1.0-20.0 | 卡尔曼观测噪声——值越大对新观测越不敏感 |

**诊断方式 · Diagnosis**：每个参数配备专属的症状规则，基于滑动窗口内的释放效率、缺页速率、内存振幅等多维指标综合评估。症状须持续达到确认周期后才触发调整，防止单次噪声误调。参数调整步长经过约束，不会剧烈震荡。协方差监控层在检测到两个参数反向调整时冻结步长较小的一方，防止补偿性震荡。

*Each parameter has dedicated symptom rules evaluated over sliding windows of release efficiency, PF rate, and memory amplitude. Adjustments require symptom persistence across a confirmation interval to prevent noise-induced false positives. Step magnitudes are bounded. A covariance monitor detects opposing adjustment signals between parameter pairs and freezes the one with the smaller step size to prevent compensatory oscillation.*

**场景记忆 · Scene Memory**：支持多种场景独立参数记忆，场景切换时通过平滑插值过渡。场景由进程名关键词自动检测。

*Scene-specific parameter sets are maintained with smooth interpolation during transitions. Scene detection is driven by process-name keyword matching.*

**持久化 · Persistence**：独立状态文件，加载时自动跳过已废弃参数，新参数缺失时取默认值。写入采用原子化操作，防止中途崩溃导致配置损坏。

*An independent state file with atomic write semantics (tmp-then-replace). Deprecated parameters are silently skipped on load; missing new parameters default to their factory values.*

---

## 6. 内存优先级管理 · *Memory Priority Management*

系统通过调用 `NtSetInformationProcess(ProcessMemoryPriority)` + `SetProcessInformation(EcoQoS)` 向 OS 传递偏好级别：所有非系统、非前台进程标记为 LOW 内存优先级并启用 EcoQoS，高价值进程进一步降级。被标记的进程在访问已换出页面时，系统会优先从 Standby List 或压缩池中提供零页而非分配新物理页。这是操作系统层面的被动优化，不消耗额外 CPU 或 I/O。

*Non-system, non-foreground processes are marked LOW memory priority with EcoQoS enabled via NtSetInformationProcess and SetProcessInformation. High-value processes are further demoted. Tagged processes receive zero-pages from the standby list or compression pool rather than fresh physical allocations when accessing paged-out pages — a passive OS-level optimization with zero CPU or I/O overhead.*

---

## 7. 游戏模式 · *Game Mode*

通过进程名匹配（内置已知游戏清单 + 用户自定义名单）和全屏窗口检测（含类名过滤排除浏览器等伪全屏窗口）自动激活，也可通过主界面按钮或 Ctrl+Shift+G 手动切换。

激活后实施三层天花板保护：

- **进程级绝对保护**：游戏进程及其子进程的 PID 被实时追踪。`EmptyWorkingSet` 扫荡、内存优先级降权、`can_trim` 判定对所有匹配进程自动跳过，游戏 WS 完全不受触碰 · *Game PIDs and children are tracked in real time — WS sweeps, priority demotion, and can_trim gating all auto-skip matched processes*
- **系统级操作抑制**：`empty_all_working_sets`、文件缓存清空、卷缓存冲刷全部跳过，仅保留 standby/registry 清理和脏页写回。消除磁盘 I/O 与游戏读盘竞争 · *System-wide WS clear, file cache clear, and volume flush are all suppressed; only standby/registry cleanup and modified-page flush continue*
- **非游戏极致释放**：全部非游戏进程工作集清空（不受 `can_trim` 门槛限制），内存优先级统一降为 VERY_LOW，操作系统优先回收其页面供游戏使用 · *Every non-game process is swept unconditionally and demoted to VERY_LOW priority*
- **操作频率自适应**：gap 间隔从常规 15s 拉长至 22s，降低守护周期对系统的干预密度 · *Gap interval extended from 15s to 22s to reduce daemon intervention density*

退出检测为即时模式——游戏进程消失后在下一个探测周期立即恢复常规参数。

*Auto-activated via process-name matching plus full-screen detection, or toggled manually from the UI or Ctrl+Shift+G. When active, a triple-layer ceiling protection engages: (1) Per-process absolute protection — game PIDs and their children are tracked in real time, exempt from WS sweeps, memory-priority demotion, and can_trim gating. (2) System-level operation suppression — empty_all_working_sets, file cache clear, and volume flush are skipped; only standby/registry cleanup and modified-page flush continue. (3) Non-game extreme release — every non-game process is swept unconditionally and demoted to VERY_LOW priority, maximizing reclaimable physical memory. The gap interval extends to 22s to reduce daemon intervention density. Exit detection is immediate — regular parameters resume on the next probe cycle after the game process disappears.*

---

## 8. 图表与效率评分 · *Charting & Efficiency Scoring*

图表数据源为统一的释放量累加器——所有操作的释放量统一汇入，通过累计差值法计算每轮增量，不依赖惰性更新的系统 API。日志、统计栏、图表三者同源一致。X 轴显示最近的轮次数据，折线为 ERIS 效率评分（0-100），五维几何平均计算。鼠标悬浮可查看详细数值。图表区域下方标注彩色内存占用进度条、累计释放量、系统操作总次数和进程清理总次数。

*A single unified freed-bytes accumulator feeds all displays. Per-cycle deltas are computed via cumulative differencing — independent of the lazily-updated system API — keeping logs, the status bar, and the chart in lockstep. The chart renders recent-cycle bars overlaid with an ERIS five-dimensional geometric-mean efficiency line (0–100). Hover tooltips reveal exact values. A color-coded memory bar, cumulative freed total, system operation counter, and process trim counter are displayed below.*

---

## 9. 进程排行 · *Process Ranking*

点击"进程排行"按钮弹出独立窗口，显示所有活跃进程的快照。排序列包括进程名、PID、物理内存（WorkingSet）、CPU 占用率、以及学习画像数据。每 2 秒自动刷新。

*A standalone window displays a live snapshot of all active processes ranked by working set, with columns for name, PID, physical memory, CPU%, and learned profile data. Refreshes every 2 seconds.*

内存数据的采集优先使用内核批量查询接口，无需对每个进程执行 `OpenProcess`，可绕过安全软件的进程保护机制。

*Memory data is collected via a kernel bulk-query API that requires no per-process OpenProcess, bypassing security-software process protection.*

---

## 10. 学习日志 · *Learning Log*

点击"学习日志"按钮弹出独立窗口，按复合评分降序显示所有已学习进程的完整画像数据：θ 值、ROI、Kalman 预测值、EWMA、回弹率、清理次数、成功率等。支持排序和滚动浏览。

*A standalone window displays the complete profile of every learned process — θ, ROI, Kalman predictions, EWMA values, refill rate, clean count, and success rate — sorted by descending composite score with sortable columns and scroll navigation.*

---

## 11. 设置面板 · *Settings Panel*

设置面板提供以下可配置项，所有更改即时保存，重启后生效：

*All changes are saved immediately and take effect on restart:*

**启动设置 · Startup**：开机自启（快捷方式）、管理员权限启动（计划任务）、启动时自动开启守护、启动后最小化到托盘。

*Auto-start with Windows (shortcut), elevated auto-start (scheduled task), auto-enable daemon on launch, start minimized to tray.*

**关闭按钮行为 · Close Behavior**：最小化到托盘（守护继续运行）、直接退出程序、每次询问（默认）。

*Minimize to tray (daemon continues), exit immediately, or ask each time (default).*

**清理操作 · Operations**：7 种操作独立开关：ws、standby、modified、compress、volume、registry、combine。前六项默认开启，内存合并默认关闭。

*Seven independent toggles: ws, standby, modified, compress, volume, registry, combine. The first six default on; combine defaults off.*

**游戏模式 · Game Mode**：管理自定义游戏进程名单（添加/查看），支持逗号分隔批量输入与大小写无关匹配。主界面设有独立开关按钮，也可通过 Ctrl+Shift+G 热键一键切换。

*Manage custom game process entries (add/view), with comma-separated batch input and case-insensitive matching. A dedicated toggle button on the main UI and the Ctrl+Shift+G hotkey provide one-click game mode switching.*

**清理模式 · Mode**：下拉框选择 quick / normal / deep / full（默认 normal）。

*Dropdown selection: quick, normal, deep, or full (default: normal).*

**触发与日志 · Trigger & Logging**：紧急触发阈值（50-99%，默认 80%）、托盘左键行为、文件日志开关、进程清理深度（2-6 pass，默认 4）。

*Emergency trigger threshold (50–99%, default 80%), tray left-click action, file-log toggle, cleaning depth (2–6 pass, default 4).*

---

## 12. 日志系统 · *Logging System*

主界面右侧为日志区域。每轮输出本轮释放量、系统操作次数、整理进程数、试探/成功数等关键指标。在输出周期之间，算法诊断消息（元认知校准、概念漂移、EFIS 调参、深度清理触发等）被累积到缓冲区，于日志输出时一并显示。清屏机制保证每条日志用户至少可见一整轮。

*A right-side log panel outputs per-cycle key metrics — freed amount, system operation count, trimmed process count, and probe success rate. Between-cycle diagnostic messages (meta-cognitive calibration, concept drift, EFIS tuning, deep-clean triggers) are buffered and flushed with the next log round. A screen-clearing policy ensures each round of messages remains visible for at least one full cycle.*

---

## 13. 命令行工具 · *Command-Line Tools*

```
python memwise.py [command] [options]
```

| 命令 | 说明 |
|------|------|
| `status` | 查看当前物理内存使用状态 |
| `learn [分钟]` | 采集并学习进程内存行为 |
| `optimize [-m MODE]` | 单次优化（支持 quick/normal/deep/full） |
| `daemon [-m MODE]` | CLI 守护模式 |
| `profile <PID>` | 查看指定进程的完整学习画像 |

---

## 14. 配置项 · *Configuration*

`config/config.yaml` 完整配置项：

| 键 | 类型 | 默认值 | 说明 |
|------|------|:------|------|
| `clean_mode` | str | `"normal"` | 清理模式 |
| `clean_operations` | list | `[ws,standby,modified,volume,compress,registry]` | 启用的操作 |
| `auto_start` | bool | `false` | 开机自启 |
| `auto_start_admin` | bool | `false` | 管理员权限开机自启 |
| `auto_start_daemon` | bool | `false` | 启动后自动守护 |
| `auto_start_minimize` | bool | `false` | 启动后最小化 |
| `close_action` | str | `"ask"` | 关闭按钮行为 |
| `interval` | int | `30` | 日志/图表周期（秒） |
| `emergency_threshold` | int | `80` | 紧急触发阈值（%） |
| `clean_passes` | int | `4` | 最大清理轮数 |
| `tray_left_action` | str | `"show"` | 托盘左键行为 |
| `hotkey` | str | `"ctrl+shift+m"` | 热键 |
| `never` | list | `[]` | 排除列表（进程名或 PID） |
| `game_processes` | list | `[]` | 自定义游戏 exe 名 |
| `efis_params` | dict | 10 参数默认值 | EFIS 参数 |

---

## 15. 文件结构 · *File Structure*

```
MemWise/
├── memwise_gui.py              # GUI 主程序 · GUI Application
├── memwise.py                  # CLI 命令行入口 · CLI Entry Point
├── config/config.yaml          # 配置文件（自动持久化）· Configuration
├── memwise_state.json          # 学习数据文件（自动保存/加载）· Learned State
├── memwise_efis_state.json     # EFIS 状态文件 · EFIS State
├── watchdog.json               # 看门狗标记文件（自动管理）· Watchdog Marker
├── CHANGELOG.md                # 更新日志 · Changelog
├── README.md                   # 本文件 · This File
├── assets/icon.ico             # 程序图标 · Application Icon
├── core/
│   ├── cleaner.py              # 三层清理引擎 + 持续优化 · Cleaning Engine
│   ├── learner.py              # Thompson Sampling + Kalman + 特征学习 · Cognitive Learner
│   ├── judger.py               # 判定器 + PID 控制器 · Judger + PID
│   ├── efis.py                 # EFIS v3 全程序智能调参 · EFIS Parameter Tuner
│   ├── meta.py                 # 元认知自我监控 · Meta-Cognitive Monitor
│   ├── policy.py               # 五树投票策略 · Policy Voter
│   ├── kalman.py               # Kalman 滤波器 · Kalman Filter
│   ├── temporal.py             # 时序画像 · Temporal Profiler
│   ├── hippocampus.py          # 情景记忆 · Episodic Memory
│   ├── prior.py                # 分层先验 · Hierarchical Prior
│   ├── winapi.py               # Win32 API 绑定（70+ 函数）· Win32 API Bindings
│   ├── sniffer.py              # 进程快照采集 · Process Snapshot Collector
│   └── config.py               # 配置加载/保存 · Configuration Loader
└── scripts/
    └── _validate.py            # 构建验证脚本 · Build Validator
```

---

## 系统要求 · *System Requirements*

- Windows 10 20H1+ / Windows 11（部分缓存操作依赖较新版本）
- 管理员权限（缓存清理需要；进程 EmptyWorkingSet 不受限制）
- 无需安装任何第三方运行库

*Windows 10 20H1+ or Windows 11. Administrator elevation required for cache operations; per-process EmptyWorkingSet has no elevation requirement. No third-party runtime dependencies.*

---

> [GitHub Releases](https://github.com/fuguangbeta/MemWise/releases) — 下载最新版本 · *Download Latest Release*