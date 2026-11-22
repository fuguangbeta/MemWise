# MemWise v5.6.025

[![版本](https://img.shields.io/github/v/release/fuguangbeta/MemWise?label=%E7%89%88%E6%9C%AC&color=blue)](https://github.com/fuguangbeta/MemWise/releases) ![平台](https://img.shields.io/badge/%E5%B9%B3%E5%8F%B0-Windows%2010%20%7C%2011-0078D4) ![依赖](https://img.shields.io/badge/%E4%BE%9D%E8%B5%96-%E9%9B%B6%E7%AC%AC%E4%B8%89%E6%96%B9-4CAF50) [![许可](https://img.shields.io/github/license/fuguangbeta/MemWise?label=%E8%AE%B8%E5%8F%AF)](https://github.com/fuguangbeta/MemWise/blob/main/LICENSE) [![Star](https://img.shields.io/github/stars/fuguangbeta/MemWise?label=Star&color=yellow)](https://github.com/fuguangbeta/MemWise/stargazers) [![总下载](https://img.shields.io/github/downloads/fuguangbeta/MemWise/total?label=%E6%80%BB%E4%B8%8B%E8%BD%BD&color=2ea44f)](https://github.com/fuguangbeta/MemWise/releases)

## 关于本工具 · *About This Tool*

MemWise 是一个运行在 Windows 用户态的内存整理工具。它的工作方式并不复杂：借助系统公开的内存管理接口，在内存吃紧时，把进程暂时不用的页面和系统缓存回收回来，让正在使用的程序有更充裕的空间。

在 Windows 上，内存管理本身是系统一直在做的事情——压缩、缓存、换页，自有其成熟的机制。MemWise 并不试图取代这些机制，也不对系统做任何修改。它只是在用户需要时，让回收发生得更主动一些、更可控一些。因此，你可以把它理解为一个"手动 + 定时"的补充，而不是一套额外的内存体系。

也正因为如此，有几件事需要提前说明。

MemWise 释放的是"暂时用不到的内存"，它不能让物理内存凭空变多。如果一台机器的内存确实不够用，最根本的解决办法仍然是增加内存。本工具的意义在于，在无法立即升级硬件、或运行大型程序前需要快速腾出空间的时候，提供一个立即可用的选择。内存长期充裕的机器，其实并不需要这类工具——保持系统的默认管理，往往就是最好的状态。

回收的页面在被程序再次使用时需要重新加载，这通常表现为一瞬间的轻微延迟；清理系统缓存后，首次访问大文件也可能稍有变慢。这是内存管理本身的性质，并非工具的缺陷，也不会影响数据安全与程序稳定性。所有操作都可以在设置中单独关闭，你可以根据自己对流畅度的要求自行取舍。

MemWise 不随意终止进程、不挂起线程、不注入代码，也默认不访问网络。它仅使用 Windows 公开的 API，代码以 MIT 许可完全开源。

MemWise 只有在你主动开启「检查更新」后，它才会向官方发布渠道（GitHub）读取版本号与更新包信息，不发送任何设备信息、不含任何标识符、不做任何统计。开启后它还能自动下载并校验（SHA-256）新版本、替换程序并自动重启，配置与学习数据原样保留；网络不可用时降级为提示，并给出官方发布页地址。需要说明的是，请求由 GitHub 接收，因此对方可见你的 IP——这是任何联网检查都无法回避的事实。

如果你正在为内存紧张而困扰，希望这个工具能帮上一点忙；也欢迎在使用中提出意见，让它变得更好。

**需要额外声明的是：** MemWise 永久免费，没有任何付费版本，也没有任何付费渠道。如果你是在某个下载站或商家处付费获得的，那不是作者的行为——这个工具始终可以在这里免费获取。遇到这类情况，请及时申请退款，并到 Releases 页面重新下载。

MemWise is a user-mode memory tidying tool for Windows. Its approach is simple: through the system's public memory-management interfaces, it reclaims idle process pages and system caches when memory runs tight, leaving more room for the programs you are actually using.

Memory management on Windows is something the system already does — compression, caching, and paging have their own mature mechanisms. MemWise does not try to replace them, nor does it modify the system in any way. It simply makes reclamation more proactive and more controllable, on your schedule. Think of it as a manual and scheduled supplement, not a separate memory system of its own.

A few things are worth saying plainly.

What MemWise frees is memory that is not being used right now. It cannot make physical memory larger than it is. If a machine genuinely does not have enough RAM, adding memory remains the fundamental solution. The value of this tool lies in the moments when an upgrade is not immediately possible, or when you want to make room quickly before running something large. Machines with abundant memory rarely need such tools — leaving the system's defaults alone is often the best state.

Reclaimed pages are reloaded the next time a program needs them, usually as a momentary, barely noticeable delay; the first access to a large file after cache clearing may also be slightly slower. This follows from the nature of memory management itself — it is not a flaw of the tool, and it affects neither data safety nor program stability. Every operation can be disabled individually in Settings, so you can decide for yourself how it balances with your need for smoothness.

MemWise terminates no processes, suspends no threads, and injects no code, and by default it does not touch the network either. It uses only public Windows APIs, and the source is fully open under the MIT license.

MemWise reads the version number and update package information from the official release channel (GitHub) only after you enable "Check for Updates". It sends no device information, carries no identifier, and performs no analytics. Once enabled, it can also download a new version, verify it with SHA-256, replace the program and restart it automatically, keeping your settings and learning data intact; when the network is unavailable it degrades to a notice with the official release page address. One honest note: the request is received by GitHub, so the other side can see your IP — that is unavoidable for any online update check.

If memory pressure has been troubling you, I hope this tool helps a little; and if you have suggestions along the way, they would be most welcome.

**One more thing worth stating plainly:** MemWise is free, permanently — no paid edition and no paid channel of any kind. If you paid a download site or a reseller for it, that is not the author's doing; the tool is always available here at no cost. In such a case, please request a refund and download it again from the Releases page.

---

## 30 秒了解 · *In 30 Seconds*

MemWise 做的事很具体：在内存还没紧张之前，把暂时用不到的进程页面和系统缓存收回来。它没有自己的内存体系，也不改动 Windows 的管理方式，只是把"回收"这件事提前一点、做得更可控一点。

它提供四种力度。quick 只碰低优先待机页和注册表缓存，几乎感觉不到；normal 在此基础上清理进程闲置页，并在压力升高时加深；deep 会更主动，但只在你不操作电脑的时候做重活；full 是全力模式，允许短暂的重新加载延迟。默认是 normal。

守护模式按周期运行，默认 60 秒一轮；内存达到你设定的紧急阈值时，会立刻执行一次 full，不等下一轮。程序是单个 exe，零第三方依赖，默认不联网，不装驱动，也不常驻系统服务。它不终止进程、不挂起线程、不注入代码，系统核心进程、你排除的程序以及它自己，永远不会被清理。

MemWise does something specific: it reclaims process pages that are not in use right now, together with system caches, before memory actually becomes tight. It has no memory system of its own and does not change how Windows manages memory; it only makes reclamation happen a little earlier and under your control.

Four intensities are available. quick touches only low-priority standby pages and registry caches, which is close to imperceptible; normal also releases idle process pages and goes deeper as pressure rises; deep is more assertive but does its heavy work while you are away from the keyboard; full is all-out and accepts a brief reload delay. The default is normal.

Guard runs in cycles, 60 seconds by default. When memory reaches the emergency threshold you set, a full pass runs immediately instead of waiting for the next cycle. MemWise is a single executable with no third-party dependencies: offline by default, no driver, no background service. It terminates no processes, suspends no threads and injects no code, and system-critical processes, your exclusions and MemWise itself are never trimmed.

---

## 快速开始 · *Quick Start*

1. 从 [Releases](https://github.com/fuguangbeta/MemWise/releases) 下载 MemWise.exe，约 9.9 MB。
2. 放到可写目录（例如 D:/MemWise/）。如果放在只读位置，程序会直接告诉你配置与学习数据无法保存。
3. 双击运行。建议以管理员身份启动：待机缓存、脏页写回、文件缓存、卷冲刷、注册表缓存这些系统级操作需要管理员权限；以标准权限运行时程序仍可用，只是这些能力不可用。
4. 托盘出现图标后，它已经在后台待命。要临时腾内存，点"优化"或按全局热键（默认 Ctrl+Shift+M），程序按当前模式跑一次完整优化（三轮深度执行）；要长期看护，点"守护"。
5. 其余设置都在"设置"面板里：清理模式、守护周期、紧急阈值、开机自启、托盘行为、语言、日志与更新。

1. Download MemWise.exe from Releases; it is about 9.9 MB.
2. Put it in a writable folder, for example D:/MemWise/. In a read-only location the program tells you directly that settings and learning data cannot be saved.
3. Run it. Administrator rights are recommended, because standby purging, dirty-page flushing, file-cache clamping, volume flushing and registry cache clearing are system-level operations; under standard rights MemWise still works, those capabilities simply stay unavailable.
4. Once the tray icon appears, MemWise is already waiting in the background. To free memory now, press Optimize or the global hotkey (Ctrl+Shift+M by default) and it runs one complete optimization in the current mode, three deep rounds. For long-term care, press Guard.
5. The rest lives in Settings: cleaning mode, guard cycle, emergency threshold, autostart, tray behaviour, language, logging and updates.

---

## 四种模式怎么选 · *Choosing a Mode*

四种模式的差别只在代价大小。回收的页面被再次访问时要重新读回内存，这份延迟躲不开；模式决定它出现得多频繁、有多深。

| 模式 | 做什么 | 代价 | 适合 |
|---|---|---|---|
| **quick** | 低优先待机页与注册表缓存，不碰进程 | 几乎为零 | 常驻办公、低配机、不希望被打断 |
| **normal**（默认） | 进程闲置页，加上你勾选的系统操作；压力升高时加深；停手 5 秒做一次轻收尾 | 小 | 绝大多数日常场景 |
| **deep** | 强制深度聚合；内存中高压时做系统级全清；停手期做系统收尾 | 中等，且有界 | 内存偏紧但仍在用电脑 |
| **full** | 每轮跑完整流程：不等活跃门、每进程最大轮数、回弹二轮、系统收尾与页合并 | 较高，表现为短暂重载延迟 | 开大程序之前，或内存长期不够 |

在"清理模式"下拉框里切换，下一周期生效。手动优化按你当前选的模式执行，紧急清理则始终是 full。游戏模式激活时，涉及磁盘的系统操作会被抑制，力度自动降低，先把流畅让出来。

The four modes differ only in how much cost they accept. Reclaimed pages have to be read back when they are used again, and that delay cannot be avoided; the mode decides how often and how deeply it is paid.

| Mode | What it does | Cost | Best for |
|---|---|---|---|
| **quick** | Low-priority standby pages and registry caches, no process work | Practically zero | Always-on office work, low-end machines, no interruptions |
| **normal** (default) | Idle process pages plus the system operations you enable; deeper under pressure; a light wrap-up after 5 s idle | Small | The vast majority of everyday use |
| **deep** | Forced deep aggregation; system-wide flush at moderate-to-high usage; system wrap-up while idle | Moderate and bounded | Memory is tight but you still use the PC |
| **full** | The complete pipeline every cycle: no activity waiting, maximum rounds per process, a rebound second pass, system wrap-up and page combining | Higher, felt as a brief reload delay | Before a large program, or when memory stays tight |

Switch modes in the Mode dropdown and the change applies from the next cycle. Manual optimization uses the mode you have selected; emergency cleaning always runs full. While Game Mode is active, disk-oriented system operations are suppressed and intensity drops, giving smoothness priority.

---

## 守护模式怎么跑 · *How Guard Runs*

守护按周期工作，周期默认 60 秒，可在设置中调到 10 至 3600 秒。一个周期分两段：前半段是间隔式轻压制，后半段是一次完整收割。

| 阶段 | 内容 |
|---|---|
| gap 段（8 到 20 秒自适应） | 只做轻量系统操作，不碰进程。默认清注册表缓存；内存高压时追加待机页与脏页写回。游戏模式整体乘 1.5，最长约 30 秒。 |
| 收割段 | 按当前模式跑完整流程：进程闲置页、你勾选的系统操作、深度聚合，以及停手期的收尾。 |

触发与保护都在这一层：内存达到紧急阈值（默认 80%）时立即跑一次 full；如果配置了可用内存绝对兜底（默认关闭），可用内存过低时同样触发。连续两轮出现明显回涨时，周期会缩短到 min(设定值, max(15, 设定值乘 0.6))，回涨放缓后自动恢复。检测到你连续 5 秒没有输入，normal 会补一次轻收尾、deep 会做一次系统收尾，通常不到一秒。

主进程意外退出时，看门狗会在数秒内把它拉起来，并恢复崩溃前的守护状态；单实例互斥保证不会同时跑两个实例。关闭窗口默认进入托盘，也可以在设置里改成询问或直接退出。

Guard works in cycles, 60 seconds by default and adjustable from 10 to 3600 seconds. Each cycle has two halves: intermittent light suppression first, then one full harvest.

| Phase | What happens |
|---|---|
| Gap (adaptive, 8 to 20 s) | Lightweight system work only, no process work. Registry caches by default, plus standby pages and dirty-page flushing under high pressure. Game Mode multiplies it by 1.5, up to about 30 s. |
| Harvest | The full pipeline in the current mode: idle process pages, the system operations you enabled, deep aggregation, and the idle-time wrap-up. |

Triggering and protection live here: at the emergency threshold (80% by default) a full pass runs immediately; if the optional absolute available-memory floor is configured, it triggers on that too. After two consecutive heavy-refill rounds the cycle shortens to min(configured, max(15, configured times 0.6)) and recovers when refill slows. After 5 seconds without input, normal adds a light wrap-up and deep performs a system wrap-up, usually in under a second.

If the main process exits unexpectedly, the watchdog restarts it within seconds and restores the previous Guard state; a single-instance mutex prevents two copies from running. Closing the window sends it to the tray by default, and Settings can change that to asking or exiting.

---

## 它清什么，不清什么 · *What It Reclaims, and What It Leaves Alone*

所有动作都走 Windows 公开接口，分三层。第一层是系统级：清空低优先待机列表、写回已修改页、钳制文件缓存、冲刷卷缓存、清注册表缓存，以及（在 deep/full 下）系统级清空所有进程的工作集。第二层是进程级：对筛选后的进程调用 EmptyWorkingSet，只回收它当前用不到的物理页。第三层是深度聚合：在内存偏紧时，对已经确认空闲的进程再做一轮系统性回收。

会做的事：回收闲置物理页、清掉可重建的缓存、在你不用电脑时做更彻底的一轮。
不会做的事：结束进程、挂起线程、注入代码、修改系统设置或注册表策略、安装驱动、常驻系统服务。

六个系统操作可以逐个开关，取消勾选即完全不执行。页合并是独立开关，与这六项解耦。所有进程操作都受同一组安全门约束：系统核心进程、你的排除列表、游戏进程树、本程序自身、前台正在使用的程序，都不会被处理。

Everything goes through public Windows interfaces and is organised in three layers. The system layer empties low-priority standby lists, flushes modified pages, clamps the file cache, flushes volumes, clears registry caches and, under deep and full, flushes every process working set system-wide. The process layer calls EmptyWorkingSet on selected processes, reclaiming only pages they are not using right now. The deep layer runs a further systematic pass over processes already confirmed idle when memory is tight.

What it does: reclaims idle physical pages, clears caches that can be rebuilt, and goes further while you are away from the keyboard. What it never does: end processes, suspend threads, inject code, change system settings or registry policy, install drivers, or run a background service.

Each of the six system operations can be toggled independently; unchecking one means it is never performed. Page combining has its own switch, independent of the six. Every process action passes the same safety gates: system-critical processes, your exclusion list, game process trees, MemWise itself, and the program you are currently using are left alone.

---

## 界面导览 · *Interface Tour*

主窗口只有四块：内存状态条、按钮行（优化、守护、停止、排除、设置、学习日志、游戏模式、进程排行）、清理模式与统计行、日志与图表区域。统计行从左到右是系统操作次数、进程清理次数、累计释放量，右端是已学习进程数；它按周期更新，因为这几个数字本身就是周期增量。

日志区每条消息固定占一个图标位，正文从同一列开始；图标统一使用程序自绘的默认图标，正文里的文字原样保留。面板按"组"写入：一组内的多行完整显示，不会截断；组与组之间按 7 行判定，新的一组装不下就先清旧内容，不会把新组接在旧组后面越堆越多。

图表区每根柱子对应一个守护周期，柱高是本轮释放量；折线是效率评分，悬停可看到当轮真实数值与主导因素。图表下方是平均释放、峰值释放与平均效率。

进程排行窗口打开时即时采集一次，之后每 10 秒刷新；守护运行中直接复用守护线程的快照，不额外采样。右键可给某个程序设置工作集硬上限，把它持续钉在你设定的物理占用之下，随时可解除，最多 32 条。学习日志窗口按进程列出学习数据：样本量、可信度、收益比、偏差、趋势、泄漏标记、清理次数与试探成败。

设置面板分十二栏：语言、显示、启动、窗口与托盘、清理、游戏模式、守护、日志、更新、重置、配置传输、全局热键。

The main window has four parts: the memory bar, the button row (Optimize, Guard, Stop, Exclusions, Settings, Learning Log, Game Mode, Process Ranking), the mode and statistics row, and the log and chart area. The statistics row reads, from left to right, system operation count, process trim count and cumulative release, with the number of learned processes at the right end; it updates per cycle, because those numbers are per-cycle increments.

Every log line reserves one icon slot and the text starts in the same column; icons always use the program-drawn default icon, while text inside the message is left exactly as written. The panel writes in groups: a group of several lines is shown in full and never truncated, while the space between groups follows a seven-line rule, so a new group clears the old content first instead of piling up behind it.

In the chart, each bar is one guard cycle and its height is the release of that cycle; the line is the efficiency score, with tooltips showing the true values and dominant factors. Below the chart are average release, peak release and average efficiency.

The Process Ranking window samples once on open and refreshes every 10 seconds; while Guard runs it reuses the daemon snapshots and adds no sampling cost. Right-clicking a program sets a working-set hard cap that keeps its physical usage below a value you choose, can be cleared at any time, and supports up to 32 rules. The Learning Log window lists per-process learning data: sample count, confidence, benefit ratio, deviation, trend, leak flag, trim count and probe outcomes.

Settings has twelve sections: Language, Display, Startup, Window and Tray, Cleaning, Game Mode, Guard, Logging, Update, Reset, Config Transfer, and Global Hotkeys.

### 图表与效率评分 · *Charting and Efficiency Scoring*

效率评分取五个维度、各维 0–140 分：**净优化量**（本轮内存净下降 ÷ 本轮总释放，衡量释放量里净留存下来的比例）、**优化代价**（进程清理释放量 ÷ 缺页代价，衡量划不划算）、**优化通畅**（整理成功 ÷ 尝试总数）、**试探命中**（试探合格 ÷ 试探总数）、**优化量**（本轮释放 ÷ 本机基线释放量）。**quick 模式只参与「净优化量」与「优化量」两维**——该模式不做进程清理，另三维没有作用面，按中性 50 计入以免单维独大（见下段）。各维原始值先取最近三轮的中位数平滑，再按**本机自标定后冻结的基线**换算：本机该维的 5%/25%/50%/75%/90% 分位分别对应 **20/35/50/65/80 分**，两端按斜率线性外推、上下限 0–140。因此 **50 分 = 本机该维常态中位**、**80 分 = 本机该维九成位**；效率值 = 有效维均分折算值 ÷ K × 100%，K 取自标定窗口自身的高分位——**100% 恒等于「本机典型高位」**，与机器型号、使用时段无关；某一维偏低时只要其他维更高，合计仍可过 100%。

每种清理模式各有一套标尺与自校准数据（同一维度在各模式间的口径与量级差异很大，例如「优化代价」与「优化量」在四种模式里并不在同一水平），校准数据按模式分别积累、互不污染。

**自标定基线（冻结后不再漂移）**：每台机器、每种清理模式在用满一段（跳过预热期约 200 轮、再积累约 300 轮）后，用**自己的分位**建立基线并**冻结**——因此同一个表现**永远得到同一个分数**，读数不随使用时段或当天做什么而变；标定期间先以出厂基准起步、随本机实测逐步收敛（不会出现极端读数），冻结后即稳定在本机水平。基线存放在 `memwise_eris_calib.json`：不随配置包导出（机器相关）、恢复默认时清除；删除该文件即重新自标定。**长期偏离自检**：若近 200 轮的读数中位与冻结时的期望值相差超过 15 个百分点（说明基线不再描述这台机器），自动重标一次并在日志诊断行留痕。**四种清理模式彼此独立**：各自持有刻度锚点、参与合成的维度、平滑窗口与冻结基线数据——切换模式不会把上一模式的数值带进新模式，也不会破坏另一个模式已积累的窗口（切换后的第一轮只提示"分析中"，从下一轮起用新模式自己的数据比较）。

影响因素（词条）判定：效率上升时，在"本轮分数也上升"的维度中取分数最高者报正面词条；效率下降时，在"本轮分数也下降"的维度中取分数最低者报负面词条；两轮变化不足 1 个百分点显示"相对平稳"；同一维度的正反两面不会在相邻两轮接连出现，避免同一信息正着说反着说来回复读。连续三轮同向时追加"🔥持续改善"/"⚠持续下滑"标签（仅在 50–100% 区间内）。前 3 轮为收敛期，显示"影响因素分析中…"；效率 ≥100% 折点显示金色并标注"🚀效率超常"，≤50% 显示珊瑚红并标注"⚠效率异常"。鼠标悬浮可查看真实数值及当轮主导因素；图表区域下方标注平均效率与关键统计指标。

A single unified freed-bytes accumulator feeds all displays. Per-cycle deltas are computed via cumulative differencing, keeping logs, the status bar, and the chart in lockstep. The X axis shows recent cycles (one bar per daemon cycle; the covered time span follows the adjustable cycle length).

The efficiency score spans five dimensions, each scored 0–140: **net optimization** (net memory drop ÷ total released this cycle — how much of what was freed stayed freed), **optimization cost** (process release ÷ page-fault cost — whether the round was worth it), **unobstructedness** (successful trims ÷ attempts), **probe hit rate** (qualified probes ÷ probes), and **optimization volume** (this cycle's release relative to this machine's baseline). **Under quick mode only net optimization and volume participate**, because quick mode trims no processes; the other three count as a neutral 50 so no single dimension dominates. Each raw value is first smoothed by a three-cycle median, then mapped against **this machine's own frozen baseline**, measured during self-calibration: the machine's 5th/25th/50th/75th/90th percentiles map to **20/35/50/65/80 points**, with linear tails clamped to 0–140. So **50 = this machine's normal median** and **80 = its 90th percentile**; the final score = the effective-dimension average ÷ K × 100%, where K is a high percentile of the calibration window itself — **100% always means this machine's typical high level**, independent of machine model or time of day. A weak dimension can be compensated by stronger ones; when only one dimension has data, the missing ones count as neutral 50 (a single dimension never decides the whole score alone).

Each cleaning mode has its own baseline and calibration data (the same dimension's scale differs markedly between modes — optimization cost and optimization volume are not on the same level across the four modes), so calibration accumulates per mode without cross-contamination.

Self-calibrated baseline (frozen, no drift) — after a mode has run enough cycles (skipping the about 200-cycle warm-up, then accumulating about 300 cycles), the program builds that mode's baseline from **this machine's own measured quantiles** and freezes it: the same behaviour **always** scores the same, unaffected by time of day or by what else you were doing. During calibration readings start from the factory baseline and converge to this machine's own measurements; no extreme readings appear, and the scale settles once frozen. The baseline lives in `memwise_eris_calib.json`: excluded from config packages (machine-specific) and cleared by factory reset — deleting that file triggers a fresh self-calibration. **Drift check**: if the median of the last 200 cycles deviates from the value recorded at freeze time by more than 15 points (the baseline no longer describes this machine), the program re-calibrates once and records it in the diagnostic log line. **The four cleaning modes are independent**: each keeps its own baseline, participating dimensions and smoothing windows. Switching modes never pulls one mode's values into another, and never discards what another mode has accumulated (the first cycle after a switch only reports "analysing", and comparisons resume from the next cycle).

Factor wording: when efficiency rises, the highest-scoring dimension among those that also rose this round reports its positive word; when it falls, the lowest-scoring dimension among those that also fell reports its negative word; a change under 1 point shows "relatively steady"; the two sides of the same dimension never appear on adjacent rounds, so the same fact is not restated in reverse right after being reported. Three consecutive same-direction rounds append a 🔥 sustained-improvement / ⚠ sustained-decline tag (within the 50–100% band only). The first 3 rounds show "analysing factors…"; ≥100% marks gold dots with 🚀 exceptional efficiency, ≤50% coral-red dots with ⚠ efficiency anomaly. Hover tooltips reveal true values and the dominant factors; below the chart: average efficiency and key statistics.

---

## 日志与可观测性 · *Logs and Observability*

文件日志默认关闭，在"设置 → 日志"里打开后写入 data/memwise.log；单文件写满会自动轮转，旧的保存为 memwise.log.1，只保留一份，不会无限增长。崩溃现场单独写入 data/memwise_crash.log。

文件里的高频行是编码行，不是给人读的散文，这是刻意的：同样的字节能装下更多周期，出问题时能回溯更久。读懂它只需要知道首字段：

| 首字段 | 含义 |
|---|---|
| T1 | 每周期一行：时间、模式、内存、可用、耗时、整理进程、失败、试探、净释放、压力值、深度聚合、采样与投票、模式专属尾段、拦截原因、用户空闲秒数、前台进程与未变时长 |
| C | 每周期一行：本轮清理汇总、系统操作分项、释放最多的进程、拦截原因、内存与可用、效率五维原始值 |
| O | full 轮的系统操作明细：次数、合计释放、末次释放、耗时（同轮重复调用可据此判定） |
| S | 启动时的设置快照：模式、周期、间隔、紧急阈值、深度、操作集、日志、语言 |
| R / L / P | 回涨状态、学习状态、试探统计 |

拦截原因用短码表示，例如 core 是系统核心进程、dir 是系统目录概率不足、small 是工作集太小、fg 是刚切走、cool 是失败冷却、io 是磁盘活跃、rb 是回涨不足。

需要反馈问题时，附上最近一两百行日志、当时用的模式，以及能复现的操作即可。日志只写在本机，程序不会上传任何内容。

File logging is off by default. When enabled in Settings, MemWise writes to data/memwise.log and rotates automatically once the file is full, keeping one previous file as memwise.log.1, so it never grows without bound. Crash details go to data/memwise_crash.log.

The high-frequency lines in the file are encoded rather than prose, deliberately: the same bytes hold more cycles, which means more history when something goes wrong. Reading them only requires knowing the first field:

| Field | Meaning |
|---|---|
| T1 | One line per cycle: time, mode, memory, availability, duration, trimmed processes, failures, probes, net release, pressure, deep aggregation, sampling and voting, mode-specific tail, block reasons, user idle seconds, foreground process and how long it has been unchanged |
| C | One line per cycle: the cycle summary, per-operation system counts, top releasing processes, block reasons, memory and availability, and the five raw efficiency dimensions |
| O | System operation detail for full rounds: call count, total release, last release, elapsed time |
| S | Settings snapshot at startup: mode, cycle, gap, emergency threshold, depth, operation set, logging, language |
| R / L / P | Refill state, learning state, probe statistics |

Block reasons use short codes: core for system-critical processes, dir for insufficient system-directory probability, small for a working set below the floor, fg for recently switched away, cool for failure cooldown, io for active disk I/O, rb for insufficient refill.

When reporting a problem, include the last one or two hundred log lines, the mode you were using, and steps that reproduce it. Logs stay on your machine; nothing is uploaded.

---

## 游戏模式 · *Game Mode*

游戏模式由你配置的进程名触发，程序没有内置任何游戏名单。名单匹配的是进程名，同名进程会全部受到保护；每个游戏进程树内的子进程同样受保护。也可以在界面上手动开启，手动开启后一直有效，直到你手动关闭。

开启期间做四件事：游戏进程树完全不清理；文件缓存、卷冲刷、系统级全清这类涉及磁盘的系统操作跳过；对非游戏进程仍按当前模式做正常的闲置页回收，让游戏之外的背景程序把内存让出来；守护节奏整体放慢 1.5 倍，降低磁盘与 CPU 竞争。游戏启动和退出的检测是实时的，没有确认周期。

Game Mode is triggered by process names you configure; no game list is built in. Matching is by process name, and every process sharing that name is protected, as is every child process inside that game's process tree. You can also switch it on manually, and manual activation stays in effect until you turn it off.

While it is active, four things happen: the game process trees are never trimmed; disk-oriented system operations such as file-cache clamping, volume flushing and system-wide flushes are skipped; other processes are still trimmed in the current mode so background programs give memory back to the game; and the guard rhythm slows by a factor of 1.5 to reduce disk and CPU contention. Game start and exit are detected in real time, with no confirmation period.

---

## 安全边界 · *Safety Boundaries*

有几条边界是不随模式变化的。

系统核心进程不会被清理，无论它是否出现在你的排除列表里。你在排除列表里写下的程序名不会被清理，同名进程全部生效。游戏进程树在游戏模式期间完全保护。MemWise 自身的进程永远不会清理自己。工作集小于 1 MB 的进程不参与。

前台正在使用的程序受额外保护：normal 与 deep 下，刚切走的程序在一段时间内不清理，有可见窗口时更久，内存高压时自动放宽；正在占用 CPU 或磁盘的程序在这两个模式下也不会被清理。full 跳过活跃判断，但仍然受上面那些硬保护约束。

工作集硬上限只作用于物理占用，不改变提交内存；系统目录下的进程不允许设置。失败的任务会进入递增冷却（最多四倍间隔），成功恢复后自动衰减。

Some boundaries do not change with the mode.

System-critical processes are never trimmed, whether or not they appear in your exclusion list. Process names in your exclusion list are never trimmed, and the rule covers every process with that name. Game process trees are fully protected while Game Mode is active. MemWise never trims itself. Processes with a working set below 1 MB are not touched.

The program you are using gets extra protection: in normal and deep, a program you just switched away from is left alone for a while, longer when it still has a visible window and relaxed under memory pressure; programs actively using CPU or disk are also left alone in those two modes. full skips the activity judgement but still obeys every hard protection above.

A working-set hard cap affects physical usage only and never changes commit memory; processes under the system directory cannot be capped. Repeated failures enter an escalating cooldown, up to four times the base interval, and decay after a successful recovery.

---

## 命令行与自动化 · *Command Line and Automation*

同一个 exe 也提供命令行入口。常用子命令：

| 命令 | 作用 |
|---|---|
| status | 打印当前内存状态 |
| learn [分钟] | 观察并记录进程行为，默认 10 分钟 |
| optimize [--mode q|n|d|f] | 执行一次优化，可指定模式 |
| daemon [--mode q|n|d|f] | 以命令行方式运行守护 |
| profile <pid> | 查看某个进程的详细画像 |
| export [--config-only] / import | 导出、导入配置包；加 --config-only 时不带学习数据 |
| service | 安装或移除管理员权限的登录计划任务 |
| reset | 恢复出厂设置 |

命令行与界面共用同一份配置与学习数据，同一时刻只有一个实例在跑，避免两边同时清理互相干扰。

The same executable also offers a command-line entry point:

| Command | Purpose |
|---|---|
| status | Print the current memory state |
| learn [minutes] | Observe and record process behaviour, 10 minutes by default |
| optimize [--mode q|n|d|f] | Run one optimization, optionally in a given mode |
| daemon [--mode q|n|d|f] | Run Guard from the command line |
| profile <pid> | Show the detailed profile of one process |
| export [--config-only] / import | Export or import a configuration package; --config-only leaves learning data out |
| service | Install or remove the administrator logon scheduled task |
| reset | Restore factory settings |

The command line and the window share one set of settings and learning data, and only one instance runs at a time, so the two paths never clean over each other.

---

## 配置项 · *Configuration*

配置文件是 config/config.yaml，程序在启动时读取，改完重启生效；界面上的改动会即时写回该文件。

| 键 | 默认值 | 说明 |
|---|---|---|
| clean_mode | normal | 清理模式：quick / normal / deep / full |
| interval | 60 | 守护周期，10 到 3600 秒 |
| gap_seconds | 12 | 周期内的压制间隔，8 到 20 秒 |
| clean_passes | 4 | 单个进程最多深清轮数，2 到 6 |
| clean_operations | ws、standby、modified、volume、registry | 六个系统操作开关；filecache 可另行勾选 |
| combine_enabled | true | 页合并开关，与六项解耦 |
| emergency_threshold | 80 | 紧急清理的使用率阈值，50 到 99 |
| emergency_abs_pct | 0 | 可用内存兜底阈值，0 表示关闭 |
| target_usage | 45 | 调节器的目标占用 |
| hotkey / game_hotkey | ctrl+shift+m / ctrl+shift+g | 全局热键 |
| game_processes | 空 | 游戏进程名列表，同名进程全部保护 |
| close_action | ask | 关窗行为：ask / minimize / exit |
| tray_left_action | show | 托盘左键：show / clean |
| auto_start_admin | false | 管理员权限开机自启 |
| auto_start_minimize | false | 开机自启后直接最小化到托盘 |
| log_to_file | false | 是否写文件日志 |
| language | zh_CN | 界面语言：zh_CN / en |
| ui_animation | true | 界面动效 |
| update_check | false | 是否检查更新 |
| update_auto_apply | true | 检查到新版本后是否自动下载替换 |
| update_proxy | 空 | 更新代理，留空使用系统代理 |
| ws_caps | 空 | 工作集硬上限规则，最多 32 条 |

The configuration file is config/config.yaml. It is read at startup, so manual edits take effect after a restart; changes made in the interface are written back immediately.

| Key | Default | Meaning |
|---|---|---|
| clean_mode | normal | Cleaning mode: quick, normal, deep or full |
| interval | 60 | Guard cycle, 10 to 3600 seconds |
| gap_seconds | 12 | Suppression interval inside a cycle, 8 to 20 seconds |
| clean_passes | 4 | Maximum deep rounds per process, 2 to 6 |
| clean_operations | ws, standby, modified, volume, registry | The six system operation switches; filecache can be added |
| combine_enabled | true | Page combining, independent of the six |
| emergency_threshold | 80 | Usage threshold for emergency cleaning, 50 to 99 |
| emergency_abs_pct | 0 | Available-memory floor, 0 disables it |
| target_usage | 45 | Controller target usage |
| hotkey / game_hotkey | ctrl+shift+m / ctrl+shift+g | Global hotkeys |
| game_processes | empty | Game process names; every process with the same name is protected |
| close_action | ask | Close behaviour: ask, minimize or exit |
| tray_left_action | show | Tray left click: show or clean |
| auto_start_admin | false | Administrator autostart at logon |
| auto_start_minimize | false | Start minimized to tray on autostart |
| log_to_file | false | Write the file log |
| language | zh_CN | Interface language: zh_CN or en |
| ui_animation | true | Interface animations |
| update_check | false | Check for updates |
| update_auto_apply | true | Download and replace automatically when a new version exists |
| update_proxy | empty | Update proxy; empty uses the system proxy |
| ws_caps | empty | Working-set hard cap rules, up to 32 |

---

## 常见问题 · *Frequently Asked Questions*

**开机自启没有生效。** 自启使用管理员权限的登录计划任务，需要至少以管理员身份运行过一次程序才能建立；建立后可在任务计划程序里看到对应条目，确认它指向当前的 exe。

**提示目录不可写。** 程序需要在自己的目录里保存配置与学习数据。把它移到有写入权限的位置即可，例如用户目录或非系统盘。

**效率评分一开始显示"分析中"，或者长期在 50 分上下。** 评分用本机自己的分位做刻度，需要先预热再标定一段周期，之后才稳定；这是设计使然，不是异常。

**清理完内存又涨回去了。** 这是系统的正常工作方式：被回收的页面在你再次使用某个程序时会被重新读入，缓存也会重建。程序的判断依据是"这次回收划不划算"，不追求把占用压到某个数字。

**日志区只有几行。** 面板按组显示：一组内完整显示，组与组之间按 7 行判定，新组放不下就先清旧内容。这样最近的一整组信息总是完整的，而不是无限滚动堆积。

**Autostart does not seem to work.** Autostart uses an administrator logon scheduled task, which requires having run MemWise as administrator at least once. Afterwards you can find the entry in Task Scheduler and confirm it points at the current executable.

**It says the folder is not writable.** MemWise stores settings and learning data in its own folder. Move it somewhere writable, such as your user directory or a non-system drive.

**The efficiency score starts as "analysing", or hovers around 50 for a while.** The scale is built from this machine's own percentiles and needs a warm-up plus a calibration period before it settles. That is by design, not a fault.

**Memory climbs back after cleaning.** That is how the system works: reclaimed pages are read back when you use a program again, and caches rebuild. MemWise asks whether reclaiming is worthwhile; it does not try to hold usage at a particular number.

**The log area only shows a few lines.** The panel writes in groups: each group is shown in full, while the space between groups follows a seven-line rule, so a new group clears the old content first instead of scrolling endlessly.

---

## 系统要求 · *System Requirements*

Windows 10 20H1 及以上或 Windows 11，64 位。管理员权限用于系统级操作；标准权限下程序可用，但这些操作不可用。程序所在目录需要可写。单文件 exe 约 9.9 MB，零第三方依赖，不需要安装运行库。

Windows 10 20H1 or later, or Windows 11, 64-bit. Administrator rights are needed for system-level operations; without them MemWise runs and those operations stay unavailable. The program folder must be writable. The single executable is about 9.9 MB with no third-party dependencies and no runtime to install.

---

## 隐私与数据 · *Privacy and Data*

默认不联网，也不做任何统计：程序里没有遥测、没有设备标识、没有账号。只有在你打开"检查更新"之后，它才会向 GitHub 读取版本号与更新包信息；开启后每次启动都会检查一次。请求由 GitHub 接收，对方能看到你的 IP，这是任何联网检查都无法回避的。

日志、配置与学习数据都保存在程序目录下的 data 目录，不会离开这台机器。更新包下载后会做 SHA-256 校验，校验不通过就放弃本次更新并保留当前版本。

Nothing goes online by default, and nothing is measured: no telemetry, no device identifier, no account. Only after you enable "Check for updates" does MemWise read version and package information from GitHub, and then it checks once per startup. The request is received by GitHub, which can see your IP; that is unavoidable for any online check.

Logs, settings and learning data live in the data folder next to the program and never leave the machine. Downloaded update packages are verified with SHA-256; a failed check abandons the update and keeps the current version.

---

## 附录 A：决策与自适应 · *Appendix A: Decision Making and Adaptation*

每个进程都有一份画像，记录它的释放历史、代价与稳定性。清理一个进程之前，程序会依次判断：先过硬保护，再看它最近是否活跃、是否刚被清理过、上次清理是否划算、这次大概能拿回多少。

学习部分由四块组成。Thompson 采样给出"值得一试"的概率，随成功与失败更新；Kalman 滤波维护释放量的预测基线，用来判断结果是否符合预期；分层先验让新进程不必从零起步；三棵策略树分别从收益、压力与反事实角度投票，票数不足就拒绝。normal 的投票阈值是 0，deep 是 -1，full 是 -2，全负分仍然拒绝。

还有两个防抖机制。稳态锚点记录进程"清完又长回来"的自然基线，避免反复无效清理；回弹学习记录清理后的回填速度，回填快的进程被推迟。这两个机制在 deep 与 full 下不参与，因为这两个模式并不打算"省着清"。

EFIS 是参数自适应层，按本轮结果微调九个阈值类参数，并受上下限约束：

| 参数 | 默认 | 范围 | 作用 |
|---|---|---|---|
| deepen_theta | 0.60 | 0.30 到 0.80 | 进程深清档位的价值门槛 |
| layer3_agg_gate | 0.60 | 0.30 到 0.70 | normal 触发深度聚合的压力门槛 |
| pid_kp / pid_kd | 0.60 / 0.10 | 0.45 到 2.00 / 0.05 到 0.35 | 压力调节器的比例与微分系数 |
| target_usage | 60 | 35 到 65 | 调节器的目标占用 |
| cooloff_base | 360 | 60 到 360 | 失败冷却基准秒数 |
| learning_rate | 0.50 | 0.10 到 0.90 | 反馈学习率 |
| composite_kalman_w | 0.30 | 0.10 到 0.50 | 预测与实测的合成权重 |
| kalman_r | 5.0 | 1 到 20 | 观测噪声 |
| anchor_margin | 0.15 | 0.05 到 0.30 | 稳态锚点抑制余量 |
| cpu_gate / io_gate | 8.0 / 4.0 | 3 到 25 / 1 到 16 | 活跃门：CPU 占比与磁盘 MB/s |

Each process carries a profile recording its release history, cost and stability. Before trimming a process, MemWise asks a series of questions. The hard protections come first, then whether the process has been active recently, whether it was trimmed moments ago, whether the last trim was worthwhile, and roughly how much this one would return.

Learning has four parts. Thompson sampling yields the probability that a process is worth trying, updated by success and failure; a Kalman filter keeps a predicted baseline for release volume so results can be judged against expectation; a hierarchical prior keeps new processes from starting at zero; and three policy trees vote from the angles of benefit, pressure and counterfactual, with insufficient votes rejecting the candidate. The threshold is 0 in normal, -1 in deep and -2 in full, and an all-negative score is still refused.

Two damping mechanisms sit on top. A stable-state anchor records the natural baseline a process returns to after trimming, avoiding futile repetition; rebound learning records how quickly memory refills, deferring fast refillers. Neither participates in deep or full, since those modes are not trying to clean sparingly.

EFIS adjusts nine threshold-type parameters from each cycle's outcome, within fixed bounds:

| Parameter | Default | Range | Purpose |
|---|---|---|---|
| deepen_theta | 0.60 | 0.30 to 0.80 | Value floor for deep per-process passes |
| layer3_agg_gate | 0.60 | 0.30 to 0.70 | Pressure gate for deep aggregation in normal |
| pid_kp / pid_kd | 0.60 / 0.10 | 0.45 to 2.00 / 0.05 to 0.35 | Proportional and derivative gains |
| target_usage | 60 | 35 to 65 | Controller target usage |
| cooloff_base | 360 | 60 to 360 | Base failure cooldown, seconds |
| learning_rate | 0.50 | 0.10 to 0.90 | Feedback learning rate |
| composite_kalman_w | 0.30 | 0.10 to 0.50 | Blend of prediction and measurement |
| kalman_r | 5.0 | 1 to 20 | Observation noise |
| anchor_margin | 0.15 | 0.05 to 0.30 | Margin for stable-state suppression |
| cpu_gate / io_gate | 8.0 / 4.0 | 3 to 25 / 1 to 16 | Activity gates: CPU share and disk MB/s |

---

## 附录 B：文件结构 · *Appendix B: File Structure*

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

## 附录 C：构建与自检 · *Appendix C: Building and Self-Check*

运行期没有外部依赖，构建时才需要 Python 与 PyInstaller。打包命令是 python -m PyInstaller MemWise.spec --distpath dist --workpath build --noconfirm，产物为 dist 目录下的单文件 exe。代码自检用 scripts/test_regression.py，它覆盖清理梯度、判定门、界面文案与文档同步等静态与行为断言，改动前后都应当跑一遍。版本号以 core/backup.py 里的 APP_VERSION 为唯一来源，本地测试构建通过 BUILD_VERSION 追加 .beta 后缀，两者互不覆盖。

There are no runtime dependencies; Python and PyInstaller are only needed to build. The packaging command is python -m PyInstaller MemWise.spec --distpath dist --workpath build --noconfirm, producing a single executable in dist. Self-checks run through scripts/test_regression.py, which covers cleaning gradients, decision gates, interface wording and documentation sync as both static and behavioural assertions, and is worth running before and after any change. The version number has a single source of truth, APP_VERSION in core/backup.py; local test builds append a .beta suffix through BUILD_VERSION, and the two never overwrite each other.

---

> [GitHub Releases](https://github.com/fuguangbeta/MemWise/releases) — 下载最新版本 · *Download Latest Release*

---

## 支持与赞赏 · *Support & Appreciation*

如果你觉得 MemWise 帮上了忙，并且有充足的意愿和赞赏渠道支持这个小小的项目，可以扫一扫下方的微信赞赏码——赞赏本身比钞票面值更有意义！当然，你的使用与反馈本身就是对我最大的支持！

If MemWise has been helpful, and you have the willingness and means to appreciate this small project, feel free to scan the WeChat reward QR code below — the appreciation itself means more than the amount. Of course, your usage and feedback are already the greatest support.

<p align="center">
  <img src="assets/donate.png" width="240" alt="微信赞赏码 · WeChat Reward QR Code">
</p>
