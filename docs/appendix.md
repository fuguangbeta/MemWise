# 附录 · *Appendices*

本文件是 README 的技术附录，四个部分各自独立；从 README 里的链接可以直接跳到对应小节。

This file holds the technical appendices for the README. Each part stands alone, and the links in the README jump straight to the matching section.

---

<a id="a"></a>
## 附录 A：机制细节 · *How It Works Internally*

### 执行顺序

一次完整优化按三层推进。系统层按你勾选的操作依次执行：卷缓存冲刷、脏页写回、待机页回收、文件缓存钳制、注册表缓存清理；deep 与 full 还会做一次系统级工作集全清。进程层对通过判定的进程调用 EmptyWorkingSet，只回收它们当前用不到的物理页。深度层再对已确认空闲的进程做一轮系统回收，避免遗漏。

### 守护节奏

| 阶段 | 内容 |
|---|---|
| gap 段（8 到 20 秒自适应） | 只做轻量系统操作：默认注册表缓存，内存高压时追加待机页与脏页写回；不碰进程。游戏模式整体乘 1.5，最长约 30 秒。 |
| 收割段 | 按当前模式跑完整流程：进程闲置页、系统操作、深度聚合，以及 normal/deep 的停手期收尾。 |

**周期长度恒为设定值**（日志、图表与统计都按这个节拍输出）。回涨快时不再缩短周期，改为：① gap 段的全清间隔按内存压力分级（充裕 32 秒、偏紧 12 秒、短缺 6 秒），并按净留存率修正；② 距周期结束仍有余量且内存较周期初上涨时，在同一周期内追加一轮收割。检测到用户停手 5 秒，normal 补一次轻收尾、deep 做一次系统收尾，通常不到一秒。紧急阈值触发时立即插入一次 full，不等下一轮。

主进程意外退出后，看门狗会在数秒内重启并恢复崩溃前的守护状态；单实例互斥保证不会同时存在两个实例。

### 日志字段

高频行是编码行，首字段标识类型：

| 首字段 | 含义 |
|---|---|
| T1 | 每周期一行：时间、模式、内存、可用、耗时、整理进程、失败、试探、净释放、压力值、深度聚合、采样与投票、模式专属尾段、拦截原因、用户空闲秒数、前台进程与未变时长 |
| C | 每周期一行：本轮清理汇总、系统操作分项、释放最多的进程、拦截原因、内存与可用、效率五维原始值 |
| O | full 轮的系统操作明细：次数、合计释放、末次释放、耗时 |
| S | 启动时的设置快照 |
| R / L / P | 回涨状态、学习状态、试探统计 |

拦截原因用短码：core 系统核心进程、dir 系统目录概率不足、small 工作集太小、fg 刚切走、cool 失败冷却、io 磁盘活跃、rb 回涨不足。

### 界面实现口径

日志区每条消息固定占一个图标位，图标统一使用程序自绘的默认图标，正文原样保留。面板按组写入：组内完整显示，组与组之间按 7 行判定，新组放不下就先清旧内容，这也是它只显示"最近一组"的原因。

进程排行打开时即时采集一次，之后每 10 秒刷新；守护运行中直接复用守护线程的快照，不产生额外采样开销。图表与日志、统计栏同源，都用同一个释放累加器按轮次做差值，所以三处数字始终一致。

工作集上限作用于物理占用而非提交内存，规则最多 32 条；系统目录下的进程不允许设置。

### Execution order

One complete pass moves through three layers. The system layer runs the operations you enabled in order: volume cache flushing, dirty-page write-back, standby purging, file-cache clamping and registry cache clearing; deep and full also flush every process working set once. The process layer calls EmptyWorkingSet on processes that passed the checks, reclaiming only pages they are not using. The deep layer runs one more systematic pass over processes already confirmed idle.

### Guard rhythm

| Phase | Content |
|---|---|
| Gap (adaptive, 8 to 20 s) | Lightweight system work only: registry caches by default, plus standby and dirty pages under high pressure; no process work. Game Mode multiplies it by 1.5, up to about 30 s. |
| Harvest | The full pipeline in the current mode: idle process pages, system operations, deep aggregation, and the idle-time wrap-up for normal and deep. |

After two consecutive heavy-refill rounds the cycle shortens to min(configured, max(15, configured times 0.6)) and recovers when refill slows. After 5 seconds without input, normal adds a light wrap-up and deep a system wrap-up, usually under a second. An emergency threshold inserts an immediate full pass instead of waiting.

If the main process exits unexpectedly the watchdog restarts it within seconds and restores the previous Guard state; a single-instance mutex prevents duplicates.

### Log fields

High-frequency lines are encoded, and the first field identifies the type:

| Field | Meaning |
|---|---|
| T1 | One line per cycle: time, mode, memory, availability, duration, trimmed processes, failures, probes, net release, pressure, deep aggregation, sampling and voting, mode-specific tail, block reasons, idle seconds, foreground process and how long it has been unchanged |
| C | One line per cycle: cycle summary, per-operation system counts, top releasing processes, block reasons, memory and availability, five raw efficiency dimensions |
| O | System operation detail for full rounds: call count, total release, last release, elapsed time |
| S | Settings snapshot at startup |
| R / L / P | Refill state, learning state, probe statistics |

Block reasons use short codes: core for system-critical processes, dir for insufficient system-directory probability, small for a working set below the floor, fg for recently switched away, cool for failure cooldown, io for active disk I/O, rb for insufficient refill.

### Interface internals

Every log line reserves one icon slot; icons always use the program-drawn default icon and the text is kept as written. The panel writes in groups: a group appears in full, while the space between groups follows a seven-line rule, so a new group clears the old content first, which is why it shows only the most recent group.

Process Ranking samples once on open and refreshes every 10 seconds; while Guard runs it reuses the daemon snapshots and adds no sampling cost. The chart shares the same release accumulator as the log and the statistics row, using per-cycle differences, so the three always agree.

A working-set cap limits physical usage rather than commit memory, with up to 32 rules; processes under the system directory cannot be capped.

---

---

<a id="b"></a>
## 附录 B：决策与自适应 · *Decision Making and Adaptation*

每个进程都有一份画像，记录它的释放历史、代价与稳定性。清理一个进程之前，程序会依次判断：先过硬保护，再看它最近是否活跃、是否刚被清理过、上次清理是否划算、这次大概能拿回多少。

学习部分由四块组成。Thompson 采样给出"值得一试"的概率，随成功与失败更新；Kalman 滤波维护释放量的预测基线，用来判断结果是否符合预期；分层先验让新进程不必从零起步；三棵策略树分别从收益、压力与反事实角度投票，票数不足就拒绝。normal 的投票阈值是 0，deep 是 -1，full 是 -2，全负分仍然拒绝。

还有两个防抖机制。稳态锚点记录进程"清完又长回来"的自然基线，避免反复无效清理；回弹学习记录清理后的回填速度，回填快的进程被推迟。这两个机制在 deep 与 full 下不参与，因为这两个模式并不打算"省着清"。

EFIS 是参数自适应层，按本轮结果微调九个阈值类参数，并受上下限约束：

| 参数 | 默认 | 范围 | 作用 |
|---|---|---|---|
| deepen_theta | 0.60 | 0.30 到 0.80 | 进程深清档位的价值门槛 |
| layer3_agg_gate | 0.60 | 0.30 到 0.70 | normal 触发深度聚合的压力门槛 |
| pid_kp / pid_kd | 0.60 / 0.10 | 0.45 到 2.00 / 0.05 到 0.35 | 压力调节器的比例与微分系数 |
| target_usage | 60 | 30 到 65 | 调节器目标；模式默认 normal 50 / deep 40 / full 30 / extreme 20，full 下限 20 / extreme 15 |
| cooloff_base | 360 | 60 到 360 | 失败冷却基准秒数 |
| learning_rate | 0.50 | 0.10 到 0.90 | 反馈学习率 |
| composite_kalman_w | 0.30 | 0.10 到 0.50 | 预测与实测的合成权重 |
| kalman_r | 5.0 | 1 到 20 | 观测噪声 |
| anchor_margin | 0.15 | 0.05 到 0.30 | 稳态锚点抑制余量 |
| cpu_gate / io_gate | 8.0 / 4.0 | 3 到 25 / 1 到 16 | 活跃门：CPU 占比与磁盘 MB/s |

Each process carries a profile recording its release history, cost and stability. Before trimming a process, MemWise asks a series of questions. The hard protections come first, then whether the process has been active recently, whether it was trimmed moments ago, whether the last trim was worthwhile, and roughly how much this one would return.

Learning has four parts. Thompson sampling yields the probability that a process is worth trying, updated by success and failure; a Kalman filter keeps a predicted baseline for release volume so results can be judged against expectation; a hierarchical prior keeps new processes from starting at zero; and three policy trees vote from the angles of benefit, pressure and counterfactual, with insufficient votes rejecting the candidate. The threshold is 0 in normal, -1 in deep and -2 in full, and an all-negative score is still refused.

Two damping mechanisms sit on top. A stable-state anchor records the natural baseline a process returns to after trimming, avoiding futile repetition; rebound learning records how quickly memory refills, deferring fast refillers. Neither participates in deep, full or extreme, since those modes are not trying to clean sparingly.

EFIS adjusts nine threshold-type parameters from each cycle's outcome, within fixed bounds:

| Parameter | Default | Range | Purpose |
|---|---|---|---|
| deepen_theta | 0.60 | 0.30 to 0.80 | Value floor for deep per-process passes |
| layer3_agg_gate | 0.60 | 0.30 to 0.70 | Pressure gate for deep aggregation in normal |
| pid_kp / pid_kd | 0.60 / 0.10 | 0.45 to 2.00 / 0.05 to 0.35 | Proportional and derivative gains |
| target_usage | 60 | 30 to 65 | Controller target; mode defaults normal 50 / deep 40 / full 30 / extreme 20, with full floor 20 / extreme 15 |
| cooloff_base | 360 | 60 to 360 | Base failure cooldown, seconds |
| learning_rate | 0.50 | 0.10 to 0.90 | Feedback learning rate |
| composite_kalman_w | 0.30 | 0.10 to 0.50 | Blend of prediction and measurement |
| kalman_r | 5.0 | 1 to 20 | Observation noise |
| anchor_margin | 0.15 | 0.05 to 0.30 | Margin for stable-state suppression |
| cpu_gate / io_gate | 8.0 / 4.0 | 3 to 25 / 1 to 16 | Activity gates: CPU share and disk MB/s |

---

### 效率评分 · *Efficiency Scoring*

效率评分取五个维度、各维 0–140 分：**净优化量**（本轮内存净下降 ÷ 本轮总释放，衡量释放量里净留存下来的比例）、**优化代价**（进程清理释放量 ÷ 缺页代价，衡量划不划算）、**优化通畅**（整理成功 ÷ 尝试总数）、**试探命中**（试探合格 ÷ 试探总数）、**优化量**（本轮释放 ÷ 本机基线释放量）。各维原始值先取最近三轮的中位数平滑，再按**本机自标定后冻结的基线**换算：本机该维的 5%/25%/50%/75%/90% 分位分别对应 **20/35/50/65/80 分**，两端按斜率线性外推、上下限 0–140。因此 **50 分 = 本机该维常态中位**、**80 分 = 本机该维九成位**；效率值 = 有效维均分折算值 ÷ K × 100%，K 取自标定窗口自身的高分位——**100% 恒等于「本机典型高位」**，与机器型号、使用时段无关；某一维偏低时只要其他维更高，合计仍可过 100%。

每种清理模式各有一套标尺与自校准数据（同一维度在各模式间的口径与量级差异很大，例如「优化代价」与「优化量」在四种模式里并不在同一水平），校准数据按模式分别积累、互不污染。

**自标定基线（冻结后不再漂移）**：每台机器、每种清理模式在用满一段（跳过预热期约 200 轮、再积累约 300 轮）后，用**自己的分位**建立基线并**冻结**——因此同一个表现**永远得到同一个分数**，读数不随使用时段或当天做什么而变；标定期间先以出厂基准起步、随本机实测逐步收敛（不会出现极端读数），冻结后即稳定在本机水平。基线存放在 `memwise_eris_calib.json`：不随配置包导出（机器相关）、恢复默认时清除；删除该文件即重新自标定。**长期偏离自检**：若近 200 轮的读数中位与冻结时的期望值相差超过 15 个百分点（说明基线不再描述这台机器），自动重标一次并在日志诊断行留痕。**四种清理模式彼此独立**：各自持有刻度锚点、参与合成的维度、平滑窗口与冻结基线数据——切换模式不会把上一模式的数值带进新模式，也不会破坏另一个模式已积累的窗口（切换后的第一轮只提示"分析中"，从下一轮起用新模式自己的数据比较）。

影响因素（词条）判定：效率上升时，在"本轮分数也上升"的维度中取分数最高者报正面词条；效率下降时，在"本轮分数也下降"的维度中取分数最低者报负面词条；两轮变化不足 1 个百分点显示"相对平稳"；同一维度的正反两面不会在相邻两轮接连出现，避免同一信息正着说反着说来回复读。连续三轮同向时追加"🔥持续改善"/"⚠持续下滑"标签（仅在 50–100% 区间内）。前 3 轮为收敛期，显示"影响因素分析中…"；效率 ≥100% 折点显示金色并标注"🚀效率超常"，≤50% 显示珊瑚红并标注"⚠效率异常"。鼠标悬浮可查看真实数值及当轮主导因素；图表区域下方标注平均效率与关键统计指标。

A single unified freed-bytes accumulator feeds all displays. Per-cycle deltas are computed via cumulative differencing, keeping logs, the status bar, and the chart in lockstep. The X axis shows recent cycles (one bar per daemon cycle; the covered time span follows the adjustable cycle length).

The efficiency score spans five dimensions, each scored 0–140: **net optimization** (net memory drop ÷ total released this cycle — how much of what was freed stayed freed), **optimization cost** (process release ÷ page-fault cost — whether the round was worth it), **unobstructedness** (successful trims ÷ attempts), **probe hit rate** (qualified probes ÷ probes), and **optimization volume** (this cycle's release relative to this machine's baseline). Each raw value is first smoothed by a three-cycle median, then mapped against **this machine's own frozen baseline**, measured during self-calibration: the machine's 5th/25th/50th/75th/90th percentiles map to **20/35/50/65/80 points**, with linear tails clamped to 0–140. So **50 = this machine's normal median** and **80 = its 90th percentile**; the final score = the effective-dimension average ÷ K × 100%, where K is a high percentile of the calibration window itself — **100% always means this machine's typical high level**, independent of machine model or time of day. A weak dimension can be compensated by stronger ones; when only one dimension has data, the missing ones count as neutral 50 (a single dimension never decides the whole score alone).

Each cleaning mode has its own baseline and calibration data (the same dimension's scale differs markedly between modes — optimization cost and optimization volume are not on the same level across the four modes), so calibration accumulates per mode without cross-contamination.

Self-calibrated baseline (frozen, no drift) — after a mode has run enough cycles (skipping the about 200-cycle warm-up, then accumulating about 300 cycles), the program builds that mode's baseline from **this machine's own measured quantiles** and freezes it: the same behaviour **always** scores the same, unaffected by time of day or by what else you were doing. During calibration readings start from the factory baseline and converge to this machine's own measurements; no extreme readings appear, and the scale settles once frozen. The baseline lives in `memwise_eris_calib.json`: excluded from config packages (machine-specific) and cleared by factory reset — deleting that file triggers a fresh self-calibration. **Drift check**: if the median of the last 200 cycles deviates from the value recorded at freeze time by more than 15 points (the baseline no longer describes this machine), the program re-calibrates once and records it in the diagnostic log line. **The four cleaning modes are independent**: each keeps its own baseline, participating dimensions and smoothing windows. Switching modes never pulls one mode's values into another, and never discards what another mode has accumulated (the first cycle after a switch only reports "analysing", and comparisons resume from the next cycle).

Factor wording: when efficiency rises, the highest-scoring dimension among those that also rose this round reports its positive word; when it falls, the lowest-scoring dimension among those that also fell reports its negative word; a change under 1 point shows "relatively steady"; the two sides of the same dimension never appear on adjacent rounds, so the same fact is not restated in reverse right after being reported. Three consecutive same-direction rounds append a 🔥 sustained-improvement / ⚠ sustained-decline tag (within the 50–100% band only). The first 3 rounds show "analysing factors…"; ≥100% marks gold dots with 🚀 exceptional efficiency, ≤50% coral-red dots with ⚠ efficiency anomaly. Hover tooltips reveal true values and the dominant factors; below the chart: average efficiency and key statistics.

---

---

<a id="c"></a>
## 附录 C：文件结构 · *File Structure*

```
MemWise/
├─ MemWise.exe            程序本体（单文件）
├─ memwise.py             命令行入口
├─ memwise_gui.py         界面入口
├─ MemWise.spec           打包配置
├─ config/                配置（config.yaml）
├─ data/                  日志、学习数据与配置包
│  ├─ memwise.log         运行日志（可轮转）
│  ├─ memwise_crash.log   崩溃现场
│  ├─ memwise_state.json  学习数据
│  └─ import_export/      配置包导出、自动备份与待导入
├─ core/                  引擎实现
│  ├─ engine.py           守护循环、轮次数据、日志
│  ├─ cleaner.py          三层清理与模式分派
│  ├─ judger.py           候选判定与安全门
│  ├─ learner.py          画像、先验与学习
│  ├─ policy.py           三棵策略树
│  ├─ efis.py             参数自适应
│  ├─ eris.py             效率评分
│  └─ winapi.py           Windows 接口封装
├─ scripts/               开发与发布脚本
└─ assets/                图标
```

---

<a id="d"></a>
## 附录 D：构建与自检 · *Building and Self-Check*

运行期没有外部依赖，构建时才需要 Python 与 PyInstaller。打包命令是 python -m PyInstaller MemWise.spec --distpath dist --workpath build --noconfirm，产物为 dist 目录下的单文件 exe。代码自检用 scripts/test_regression.py，它覆盖清理梯度、判定门、界面文案与文档同步等静态与行为断言，改动前后都应当跑一遍。版本号以 core/backup.py 里的 APP_VERSION 为唯一来源，本地测试构建通过 BUILD_VERSION 追加 .beta 后缀，两者互不覆盖。

There are no runtime dependencies; Python and PyInstaller are only needed to build. The packaging command is python -m PyInstaller MemWise.spec --distpath dist --workpath build --noconfirm, producing a single executable in dist. Self-checks run through scripts/test_regression.py, which covers cleaning gradients, decision gates, interface wording and documentation sync as both static and behavioural assertions, and is worth running before and after any change. The version number has a single source of truth, APP_VERSION in core/backup.py; local test builds append a .beta suffix through BUILD_VERSION, and the two never overwrite each other.

---
