# MemWise v5.8.036

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

## 概述 · *Overview*

程序提供四种清理强度，差异体现为介入深度与代价。normal 回收进程闲置页与系统缓存，并依据内存压力逐步加深；deep 于用户空闲时执行额外的深度回收；full 以释放量为优先，接受由此产生的短暂重载延迟；extreme 在 full 基础上强制全部操作并清理系统/自身工作集，追求最低已用内存，但可能造成卡顿，且不承诺绝对稳定。默认模式为 normal。

守护模式以固定周期运行，默认周期 60 秒，周期长度不受内存波动影响——你在设置里填 60 秒，日志、图表与统计就都按 60 秒输出；周期内部再按内存压力调整动作密度。内存占用达到预设阈值时立即执行一次 full，不等待后续周期。程序为单一可执行文件，无第三方依赖，默认不联网、不安装驱动、不注册系统服务；运行期间不终止进程、不挂起线程、不注入代码。系统核心进程、排除项与程序自身不参与清理。

Four modes of cleaning intensity are provided, differing in intervention depth and cost. normal reclaims idle process pages and system caches and deepens as memory pressure rises; deep performs extra reclamation while the user is idle; full prioritises release volume and accepts the resulting brief reload delay; extreme additionally forces every operation and trims system/self working sets for the lowest used-memory figure, at the cost of possible stutter; absolute stability is not guaranteed. The default mode is normal.

Guard mode operates on a fixed cycle, 60 seconds by default, and the cycle length does not move with memory fluctuations — set 60 seconds and logs, chart and statistics all follow that beat; work density inside the cycle adapts to memory pressure. When memory usage reaches the configured threshold it executes a full pass immediately rather than waiting for a later cycle. The program is a single executable with no third-party dependencies; it is offline by default, installs no driver and registers no system service. During operation it terminates no process, suspends no thread and injects no code. System-critical processes, exclusions and MemWise itself are excluded from reclamation.

---

## 快速开始 · *Quick Start*

1. 自 [Releases](https://github.com/fuguangbeta/MemWise/releases) 获取 MemWise.exe，体积约 9.9 MB。
2. 将其置于可写目录（例如 D:/MemWise/）。目录不可写时，程序将提示配置与学习数据无法持久化。
3. 以管理员权限运行。待机缓存、脏页写回、文件缓存、卷缓存与注册表缓存等系统级操作需要管理员权限；标准权限下程序仍可运行，但上述能力不可用。
4. 托盘图标出现后程序进入常驻状态。需立即释放内存时，点击「优化」或使用全局热键（默认 Ctrl+Shift+M），程序按当前模式执行一次完整优化（三轮深度执行）；需持续维护时，点击「守护」。
5. 其余参数于「设置」中调整：清理模式、守护周期、紧急阈值、开机自启、托盘行为、语言、日志与更新。

1. Obtain MemWise.exe from Releases; the binary is about 9.9 MB.
2. Place it in a writable directory, for example D:/MemWise/. If the directory is read-only, the program reports that settings and learning data cannot be persisted.
3. Run it with administrator rights. System-level operations such as standby purging, dirty-page write-back, file-cache clamping, volume flushing and registry cache clearing require administrator privileges; under standard privileges the program still runs, with those capabilities unavailable.
4. Once the tray icon appears the program is resident. To release memory immediately, select Optimize or use the global hotkey (Ctrl+Shift+M by default), and the program performs one complete optimization in the current mode, three deep rounds. For continuous maintenance, select Guard.
5. All remaining parameters are adjusted in Settings: cleaning mode, guard cycle, emergency threshold, autostart, tray behaviour, language, logging and updates.

---

## 四种模式怎么选 · *Choosing a Mode*

四种模式在介入深度与代价之间取舍。被回收的页面在再次访问时需重新读入，这是固有的代价；模式决定该代价出现的频率与幅度。

| 模式 | 行为特征 | 适用场景 |
|---|---|---|
| **normal**（默认） | 回收进程闲置页与所选系统缓存，用户活跃时保持克制 | 日常使用；首次使用建议自该模式开始 |
| **deep** | 于用户空闲时增加一轮深度回收，释放量更高 | 内存长期偏紧，且不宜频繁手动优化 |
| **full** | 以释放量为优先，每轮执行完整流程；内存紧张时自动加密，宽裕时克制 | 启动大型程序前，或内存已接近上限 |
| **extreme** | 强制全部操作并清系统/自身工作集，追求最低已用内存；每次进入二次确认 | 只在意内存数字、接受卡顿/磁盘抖动的专家用户 |

模式由「清理模式」下拉框切换，下一周期生效。手动优化按当前模式执行；内存达到紧急阈值时，程序自动执行一次 full。游戏模式启用期间，磁盘类系统操作受到抑制，优先保障游戏流畅度。

The four modes trade intervention depth against cost. Reclaimed pages must be read back on their next access, which is the inherent cost; the mode determines how often and how deeply it is paid.

| Mode | Behaviour | Suitable for |
|---|---|---|
| **normal** (default) | Reclaims idle process pages and the selected system caches; restrained while the user is active | Everyday use; recommended as the starting mode |
| **deep** | Adds a deep pass while the user is idle, with higher release | Memory remains tight and frequent manual optimization is impractical |
| **full** | Prioritises release volume and runs the complete pipeline every cycle; denser under pressure, restrained when memory is ample | Before a large application, or when memory is close to its limit |
| **extreme** | Forces every operation and trims system/self working sets for the lowest used memory; confirmation on every entry | Expert users who care only about the number and accept stutter/disk churn |

The mode is switched in the Mode dropdown and takes effect from the next cycle. Manual optimization uses the current mode; when memory reaches the emergency threshold the program runs a full pass automatically. While Game Mode is enabled, disk-oriented system operations are suppressed and game smoothness takes priority.

---

## 守护模式 · *Guard Mode*

点击「守护」启动，点击「停止」终止。启动后关闭窗口不终止程序，程序驻留托盘，托盘图标指示当前内存占用。

回收在设定的周期内完成，周期长度始终等于你在设置里填写的值，日志与图表也按这个节拍输出。周期内部按内存压力调整动作密度：宽裕时克制，紧张时加密；距周期结束仍有余量且内存又涨回来时，会在同一周期内追加一轮。

内存达到紧急阈值时立即执行一次 full，不等后续周期。状态可通过三处观察：统计行（系统操作次数、进程清理次数、累计释放）、日志区的最近事件，以及图表中逐轮的释放柱与效率折线。

日常无需干预。建议将常用游戏进程名加入「设置 → 游戏模式」，游戏运行期间程序自动降低介入；守护周期、紧急阈值与关窗行为均可配置。机制细节见 [附录 A](docs/appendix.md#a)。

Guard is started with Guard and terminated with Stop. After startup, closing the window does not terminate the program; it remains in the tray, where the icon indicates current memory usage.

Reclamation completes inside the configured cycle, and the cycle length always equals the value in Settings; logs and the chart follow the same beat. Inside a cycle the density of work follows memory pressure: restrained when memory is ample, denser when it is tight, with an extra pass added inside the same cycle when time remains and memory has climbed back.

When memory reaches the configured threshold a full pass executes immediately rather than waiting for a later cycle. State is observable in three places: the statistics row (system operations, process trims, cumulative release), the recent events in the log area, and the per-cycle release bars and efficiency line in the chart.

No routine intervention is required. Adding frequently used game process names under Settings, Game Mode causes the program to reduce its intervention automatically while those games run; guard cycle, emergency threshold and close behaviour are configurable. Implementation details are given in [Appendix A](docs/appendix.md#a).

---

## 清理范围与保护边界 · *Scope and Protections*

执行范围：回收暂未使用的进程页面；清理可重建的系统缓存，包括待机缓存、文件缓存、卷缓存与注册表缓存；在 deep 与 full 下，对长期无活动的进程执行额外回收。

明确不执行：终止进程、挂起线程、注入代码、修改系统设置或注册表策略、安装驱动、注册系统服务。

保护范围：系统核心进程、排除列表中的程序、运行中的游戏及其子进程、程序自身。normal 与 deep 另避让当前活跃或刚切换走的程序；full 不判断活跃性，但上述保护仍然有效。extreme 是唯一例外：它会清理系统核心进程与程序自身的工作集，仅建议在明确知情后手动使用。

Scope of execution: reclaiming process pages not currently in use; clearing caches that can be rebuilt, including standby, file, volume and registry caches; and under deep and full, additional reclamation of processes that have been inactive for a long period.

Explicitly excluded: terminating processes, suspending threads, injecting code, modifying system settings or registry policy, installing drivers, and registering a system service.

Protected scope: system-critical processes, programs in the exclusion list, a running game and its child processes, and the program itself. normal and deep additionally avoid currently active programs and those recently switched away from; full does not assess activity, but the protections above remain in force. extreme is the sole exception: it trims system-critical processes and the program itself, and should only be used manually with explicit consent.

---

## 界面导览 · *Interface Tour*

主窗口由四个区域构成。

顶部为内存状态条，显示当前占用百分比，颜色随占用水平变化，右侧为对应数值。

其下为按钮行：优化（按当前模式执行一次完整优化）、守护与停止（后台常驻开关）、排除、设置、学习日志、游戏模式、进程排行。

再下为模式与统计：左侧为清理模式选择，右侧为本次运行以来的累计值（系统操作次数、进程清理次数、累计释放），最右为已学习进程数；该行按周期刷新。

底部为日志与图表。日志区显示最近事件，组内完整显示，组间仅保留最近一组；图表区每轮一根柱，柱高为该轮释放量，折线为效率评分，悬停可查看该轮数值与主导因素，图表下方为平均释放、峰值释放与平均效率。

进程排行窗口列出当前进程的内存占用、CPU 用量与学习状态，支持排序；右键可为指定进程设置工作集上限。学习日志窗口提供更细的画像数据：样本量、可信度、收益比、偏差、趋势、泄漏标记、清理次数与试探成败。设置面板分为十二栏：语言、显示、启动、窗口与托盘、清理、游戏模式、守护、日志、更新、重置、配置传输、全局热键。

The main window comprises four regions.

At the top, the memory status bar displays current usage as a percentage, with colour following the usage level and the corresponding value on the right.

Below it, the button row: Optimize (one complete optimization in the current mode), Guard and Stop (the background switch), Exclusions, Settings, Learning Log, Game Mode, and Process Ranking.

Next, mode and statistics: the cleaning-mode selector on the left, and on the right the cumulative values since launch (system operations, process trims, cumulative release), with the number of learned processes at the far right. The row refreshes per cycle.

At the bottom, logging and charting. The log area displays recent events, each group in full and only the most recent group retained between groups. The chart draws one bar per cycle, its height being that cycle's release, and a line for the efficiency score; hovering reveals the values and dominant factors for that round, with average release, peak release and average efficiency below.

The Process Ranking window lists current processes with memory usage, CPU usage and learning state, and supports sorting; right-clicking sets a working-set cap for the selected process. The Learning Log window provides more detailed profile data: sample count, confidence, benefit ratio, deviation, trend, leak flag, trim count and probe outcomes. Settings comprises twelve sections: Language, Display, Startup, Window and Tray, Cleaning, Game Mode, Guard, Logging, Update, Reset, Config Transfer, and Global Hotkeys.

---

## 日志 · *Logging*

文件日志默认关闭。于「设置 → 日志」中开启后，记录写入 data/memwise.log；文件达到容量上限后自动轮转，保留上一份历史。崩溃信息单独写入 data/memwise_crash.log。

通常无需关注；需确认执行情况或反馈问题时查阅。反馈时建议附最近一两百行日志、当时的清理模式与可复现问题的操作步骤。日志仅存储于本机，程序不上传任何内容。文件中的高密度短行采用压缩记录格式，字段含义见 [附录 A](docs/appendix.md#a)。

File logging is disabled by default. When enabled under Settings, Logging, records are written to data/memwise.log; the file rotates automatically once its capacity is reached, retaining the previous file. Crash information is written separately to data/memwise_crash.log.

It normally requires no attention; consult it to confirm what executed or when reporting an issue. A report should include the last one or two hundred lines, the cleaning mode in use, and reproducible steps. Logs are stored locally and nothing is uploaded. The dense short lines in the file are a compact record format, explained in [Appendix A](docs/appendix.md#a).

---

## 游戏模式 · *Game Mode*

于「设置 → 游戏模式」中添加游戏进程名后自动启用；亦可于主界面手动启用，手动状态持续至手动关闭。

启用期间：游戏进程树不参与清理；磁盘类系统操作跳过，以避免磁盘竞争；游戏之外的进程仍按当前模式回收闲置页；守护节奏放慢，以降低干扰。

**Extreme 是例外**：Extreme 不避让游戏，也不允许进入游戏模式；主界面游戏模式按钮点击只弹提示，自动检测不会启用游戏模式。

识别以进程名为准，同名进程全部覆盖，配置一次即可；游戏启动与退出实时识别，无需等待周期。

Adding a game's process name under Settings, Game Mode enables the mode automatically; it may also be enabled manually from the main window, and manual activation persists until disabled.

While enabled: the game process tree is not trimmed; disk-oriented system operations are skipped to avoid disk contention; processes outside the game still have their idle pages reclaimed in the current mode; and the guard rhythm slows to reduce interference.

**Extreme is the exception**: it does not avoid games and cannot enter Game Mode; clicking the Game Mode button only shows a notice, and automatic detection never enables it.

Detection is by process name and covers every process of the same name, so configuration is performed once. Game start and exit are recognised in real time, without waiting for a cycle.

---

## 安全边界 · *Safety Boundaries*

以下边界在 normal/deep/full 不随模式改变；Extreme 是唯一例外。

系统核心进程不参与清理，无论是否出现在排除列表中。排除列表中的程序及其同名进程不参与清理。游戏运行期间，游戏进程树完全保护（Extreme 除外）。程序不清理自身（Extreme 除外）。

normal 与 deep 避让当前活跃的程序：刚切换走的程序在一段时间内不处理，存在可见窗口时延长，内存压力升高时放宽；正在占用 CPU 或磁盘的程序同样避让。full 不判断活跃性，但硬保护仍然有效。

工作集上限仅限制物理占用，不改变提交内存；系统目录下的进程不允许设置。连续失败的任务进入递增冷却，成功后逐步恢复。

The following boundaries are stable across normal/deep/full; Extreme is the sole exception.

System-critical processes are excluded from reclamation, whether or not they appear in the exclusion list. Programs in the exclusion list, together with processes of the same name, are excluded. While a game runs, its process tree is fully protected (except in Extreme). The program does not trim itself (except in Extreme).

normal and deep avoid currently active programs: a program recently switched away from is left unprocessed for a period, extended while it has a visible window and relaxed under memory pressure; programs actively using CPU or disk are likewise avoided. full does not assess activity, but the hard protections remain in force.

A working-set cap limits physical usage only and does not change commit memory; processes under the system directory cannot be capped. Consecutively failing tasks enter an escalating cooldown and recover progressively after success.

---

## 命令行与自动化 · *Command Line and Automation*

同一个 exe 也提供命令行入口。常用子命令：

| 命令 | 作用 |
|---|---|
| status | 打印当前内存状态 |
| learn [分钟] | 观察并记录进程行为，默认 10 分钟 |
| optimize [--mode n|d|f|e] | 执行一次优化，可指定模式 |
| daemon [--mode n|d|f|e] | 以命令行方式运行守护 |
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
| daemon [--mode n|d|f|e] | Run Guard from the command line |
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
| clean_mode | normal | 清理模式：normal / deep / full / extreme |
| interval | 60 | 守护周期，10 到 3600 秒 |
| gap_seconds | 12 | 周期内两次轻量清理的间隔，8 到 20 秒 |
| clean_passes | 4 | 单个进程最多深清轮数，2 到 6；full/extreme 固定 6 轮 |
| clean_operations | ws、standby、modified、volume、registry | 六个系统操作开关；filecache 可另行勾选 |
| combine_enabled | true | 页合并开关，与六项解耦 |
| emergency_threshold | 80 | 紧急清理的使用率阈值，50 到 99 |
| emergency_abs_pct | 0 | 可用内存兜底阈值，0 表示关闭 |
| target_usage | 45 | 目标内存占用，用于判断清理力度 |
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
| clean_mode | normal | Cleaning mode: normal, deep, full or extreme |
| interval | 60 | Guard cycle, 10 to 3600 seconds |
| gap_seconds | 12 | Interval between light passes inside a cycle, 8 to 20 seconds |
| clean_passes | 4 | Maximum deep rounds per process, 2 to 6; full/extreme use 6 |
| clean_operations | ws, standby, modified, volume, registry | The six system operation switches; filecache can be added |
| combine_enabled | true | Page combining, independent of the six |
| emergency_threshold | 80 | Usage threshold for emergency cleaning, 50 to 99 |
| emergency_abs_pct | 0 | Available-memory floor, 0 disables it |
| target_usage | 45 | Target memory usage used to gauge intensity |
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

**开机自启未生效。** 自启使用管理员权限的登录计划任务，需要至少以管理员身份运行过一次程序才能建立；建立后可在任务计划程序里看到对应条目，确认它指向当前的 exe。

**提示目录不可写。** 程序需要在自己的目录里保存配置与学习数据。把它移到有写入权限的位置即可，例如用户目录或非系统盘。

**效率评分一开始显示"分析中"，或者长期在 50 分上下。** 评分用本机自己的分位做刻度，需要先预热再标定一段周期，之后才稳定；这是设计使然，不是异常。

**清理后内存占用再次上升。** 这是系统的正常工作方式：被回收的页面在对应程序再次访问时将被重新读入，缓存亦会重建。程序的判断依据是"这次回收划不划算"，不追求把占用压到某个数字。

**为什么周期长度不会因为内存变紧张而缩短。** 周期是你设定的观察与执行节拍，日志和图表都按它输出；内存紧张时程序在同一周期内加密处理，而不是改写节拍本身。

**日志区仅显示少量条目。** 面板按组显示：一组内完整显示，组与组之间按 7 行判定，新组放不下就先清旧内容。这样最近的一整组信息总是完整的，而不是无限滚动堆积。

**Autostart does not seem to work.** Autostart uses an administrator logon scheduled task, which requires MemWise to have been run as administrator at least once. The resulting entry can be located in Task Scheduler and confirmed to reference the current executable.

**It says the folder is not writable.** MemWise stores settings and learning data in its own folder. The program should be placed in a writable location, such as the user directory or a non-system drive.

**The efficiency score starts as "analysing", or hovers around 50 for a while.** The scale is built from this machine's own percentiles and needs a warm-up plus a calibration period before it settles. That is by design, not a fault.

**Memory climbs back after cleaning.** This follows from normal system behaviour: reclaimed pages are read back when the corresponding program accesses them again, and caches rebuild. MemWise evaluates whether reclamation is worthwhile rather than attempting to hold usage at a fixed number.

**Why the cycle length does not shrink when memory gets tight.** The cycle is the observation and execution beat you configured, and both the log and the chart follow it; when memory is tight the program works denser inside the same cycle rather than changing the beat itself.

**The log area only shows a few lines.** The panel writes in groups: each group is shown in full, while the space between groups follows a seven-line rule, so a new group clears the old content first instead of scrolling endlessly.

---

## 系统要求 · *System Requirements*

Windows 10 20H1 及以上或 Windows 11，64 位。管理员权限用于系统级操作；标准权限下程序可用，但这些操作不可用。程序所在目录需要可写。单文件 exe 约 9.9 MB，零第三方依赖，不需要安装运行库。

Windows 10 20H1 or later, or Windows 11, 64-bit. Administrator rights are needed for system-level operations; without them MemWise runs and those operations stay unavailable. The program folder must be writable. The single executable is about 9.9 MB with no third-party dependencies and no runtime to install.

---

## 隐私与数据 · *Privacy and Data*

默认不联网，也不做任何统计：程序里没有遥测、没有设备标识、没有账号。仅在启用「检查更新」后，程序才向 GitHub 读取版本号与更新包信息；启用后每次启动检查一次。请求由 GitHub 接收，对方能看到你的 IP，这是任何联网检查都无法回避的。

日志、配置与学习数据都保存在程序目录下的 data 目录，不会离开这台机器。更新包下载后会做 SHA-256 校验，校验不通过就放弃本次更新并保留当前版本。

Nothing goes online by default, and nothing is measured: no telemetry, no device identifier, no account. Only after Check for Updates is enabled does MemWise read version and package information from GitHub, once per startup. The request is received by GitHub, which can observe the client IP address; this is inherent to any online check.

Logs, settings and learning data live in the data folder next to the program and never leave the machine. Downloaded update packages are verified with SHA-256; a failed check abandons the update and keeps the current version.

---

## 附录 · *Appendices*

技术细节单独成文，点开即可查看：

- [附录 A：机制细节](docs/appendix.md#a)：执行顺序、守护节奏、日志字段、界面实现口径
- [附录 B：决策与自适应](docs/appendix.md#b)：认知引擎、EFIS 参数表、效率评分
- [附录 C：文件结构](docs/appendix.md#c)
- [附录 D：构建与自检](docs/appendix.md#d)

The technical detail lives in a separate file:

- [Appendix A: How It Works Internally](docs/appendix.md#a): execution order, guard rhythm, log fields, interface internals
- [Appendix B: Decision Making and Adaptation](docs/appendix.md#b): cognitive engine, EFIS parameters, efficiency scoring
- [Appendix C: File Structure](docs/appendix.md#c)
- [Appendix D: Building and Self-Check](docs/appendix.md#d)

---

> [GitHub Releases](https://github.com/fuguangbeta/MemWise/releases) — 下载最新版本 · *Download Latest Release*

---

## 支持与赞赏 · *Support & Appreciation*

如果你觉得 MemWise 帮上了忙，并且有充足的意愿和赞赏渠道支持这个小小的项目，可以扫一扫下方的微信赞赏码——赞赏本身比钞票面值更有意义！当然，你的使用与反馈本身就是对我最大的支持！

If MemWise has been helpful, and you have the willingness and means to appreciate this small project, feel free to scan the WeChat reward QR code below — the appreciation itself means more than the amount. Of course, your usage and feedback are already the greatest support.

<p align="center">
  <img src="assets/donate.png" width="240" alt="微信赞赏码 · WeChat Reward QR Code">
</p>
