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

模式决定它多久动手一次、动多深。用起来的感觉大致是这样的：

| 模式 | 用起来是什么感觉 | 适合什么时候 |
|---|---|---|
| **quick** | 后台几乎不动手，只在系统本来就要丢缓存时顺手收一点 | 一直开着、不想被打扰，或机器配置不高 |
| **normal**（默认） | 平时该清的清，你在用程序时不动 | 日常使用，第一次用就从这里开始 |
| **deep** | 你离开键盘的间隙会多收一轮，力度更大 | 内存长期偏紧，又不想每次手动点优化 |
| **full** | 一次拿回最多，代价是随后打开程序可能慢一拍 | 开大程序之前，或内存已经告急 |

在「清理模式」下拉框里切换，下一轮生效。点「优化」时按当前选中的模式跑一次；内存达到紧急阈值时，程序会自己用 full 处理一次，不等下一轮。游戏模式激活期间它会主动让路，把流畅留给你正在玩的游戏。

The mode decides how often and how deeply it acts. In practice they feel like this:

| Mode | What it feels like | When to use it |
|---|---|---|
| **quick** | It barely acts in the background, only taking cache the system was going to drop anyway | Keep it running without being disturbed, or on modest hardware |
| **normal** (default) | It cleans as needed and stays out of the way while you use your programs | Everyday use; start here on your first run |
| **deep** | It takes one more pass while you are away from the keyboard | Memory stays tight and you would rather not press Optimize yourself |
| **full** | It takes back the most it can, at the cost of a slightly slower next launch of your apps | Before opening something large, or when memory is already short |

Switch in the Mode dropdown and it applies from the next cycle. Pressing Optimize runs one pass in the mode you selected; when memory reaches the emergency threshold MemWise runs a full pass on its own instead of waiting. While Game Mode is active it steps back and leaves smoothness to the game.

---

## 守护模式怎么用 · *Using Guard*

点「守护」开始，点「停止」结束。开启后窗口关掉也不会退出，它会留在托盘里继续工作，托盘图标显示当前内存档位。

它在你不用电脑的空隙里回收内存；内存达到你在设置里定的阈值时，会立刻处理一次，不等下一轮。你能看到的是三处：统计行在涨（系统操作次数、进程清理次数、累计释放），日志区显示最近发生了什么，图表每轮多一根柱子，柱高是这一轮拿回的释放量。

需要你做的事很少。把常玩的游戏进程名加进「设置 → 游戏模式」，玩游戏时它会自动让路；周期长短、紧急阈值、关窗行为都在设置里。它自己的机制细节（间隔怎么定、两段节奏怎么排）见 [附录 A](docs/appendix.md#a)。

Press Guard to start and Stop to finish. With Guard running, closing the window keeps it alive in the tray, where the icon shows the current memory tier.

It reclaims memory in the gaps while you are not using the PC, and when memory reaches the threshold you set it acts immediately instead of waiting for the next round. Three places show what it is doing: the statistics row grows (system operations, process trims, cumulative release), the log area shows what just happened, and the chart gains one bar per cycle whose height is that cycle's release.

There is very little for you to do. Add the games you play under Settings, Game Mode, so it steps aside while you play; cycle length, emergency threshold and close behaviour all live in Settings. The mechanics behind it (how the interval is set, how the two phases are arranged) are in [Appendix A](docs/appendix.md#a).

---

## 它会清什么，不会动什么 · *What It Reclaims, and What It Leaves Alone*

会做的：把暂时用不到的进程页面还给系统；清掉可以重建的系统缓存，比如待机缓存、文件缓存、卷缓存和注册表缓存；在 deep 和 full 下，对一段时间没有活动的程序再多收一轮。

不会做的：结束进程、挂起线程、注入代码、修改系统设置或注册表策略、安装驱动、常驻系统服务。

不会碰的：系统核心进程、你在排除列表里写下的程序、正在玩的游戏及其子进程、MemWise 自己。normal 和 deep 下还会避开你正在使用、或刚切走的程序；full 不判断活跃，但上面那些硬保护照旧。

What it does: hands pages back to the system when a process is not using them; clears caches that can be rebuilt, such as standby, file, volume and registry caches; and under deep and full, takes one more pass over programs that have been quiet for a while.

What it never does: end processes, suspend threads, inject code, change system settings or registry policy, install drivers, or run a background service.

What it never touches: system-critical processes, the programs you listed as exclusions, the game you are playing and its child processes, and MemWise itself. Under normal and deep it also avoids programs you are using or have just switched away from; full skips the activity check but keeps every hard protection above.

---

## 界面导览 · *Interface Tour*

主窗口从上到下是几块固定的东西。

最上面是内存状态条，显示当前占用百分比，颜色随档位变化，右边还有一枚醒目的数字。

按钮行依次是：优化（按当前模式跑一次完整优化）、守护与停止（后台常驻的开关）、排除（不想被清理的程序名单）、设置、学习日志、游戏模式（手动开关）、进程排行。

再往下左边是清理模式下拉框，右边是统计行：系统操作次数、进程清理次数、累计释放量，右端是已学习进程数。这三个数字是本次运行以来的累计值，按周期刷新。

日志区显示最近发生的事，一组内完整显示，组与组之间只保留最近的一组，所以它看起来总是"当前这几条"，而不是无限滚动。

图表区每根柱子对应一轮，柱高是本轮释放量；折线是效率评分，鼠标悬停能看到当轮的真实数值和主导因素；图表下方是平均释放、峰值释放与平均效率。

进程排行会列出当前所有进程的占用、CPU 与学习情况，按需排序，右键可以对某个程序设置工作集上限。学习日志则更细：样本量、可信度、收益比、偏差、趋势、是否疑似泄漏、清理次数与试探成败。

设置面板分十二栏：语言、显示、启动、窗口与托盘、清理、游戏模式、守护、日志、更新、重置、配置传输、全局热键。

The main window is a few fixed blocks, top to bottom.

At the top is the memory bar: current usage in percent, with a colour that follows the tier, and a matching number on the right.

The button row reads Optimize (one complete pass in the current mode), Guard and Stop (the background switch), Exclusions (programs you do not want touched), Settings, Learning Log, Game Mode (a manual switch) and Process Ranking.

Below that, the mode dropdown sits on the left and the statistics row on the right: system operations, process trims and cumulative release, with the number of learned processes at the far right. Those three numbers accumulate since this run started and refresh per cycle.

The log area shows what just happened. A group of lines appears in full, and only the most recent group is kept between groups, so it always reads as "these few lines right now" rather than an endless scroll.

In the chart, each bar is one cycle and its height is that cycle's release; the line is the efficiency score, and hovering shows the true values and dominant factors for that round. Below the chart are average release, peak release and average efficiency.

Process Ranking lists every process with its memory, CPU and learning state, sortable as needed, and right-clicking a program lets you set a working-set cap. Learning Log goes deeper: sample count, confidence, benefit ratio, deviation, trend, suspected leak, trim count and probe outcomes.

Settings has twelve sections: Language, Display, Startup, Window and Tray, Cleaning, Game Mode, Guard, Logging, Update, Reset, Config Transfer, and Global Hotkeys.

---

## 日志 · *Logging*

文件日志默认关闭。在「设置 → 日志」里打开后，它会把运行过程写进 data/memwise.log，文件写满后自动轮转，只保留上一份，不会一直变大。崩溃现场单独写在 data/memwise_crash.log。

平时不用管它。想确认它究竟做了什么、或者要反馈问题时再打开看一眼就够。需要反馈时，附上最近一两百行日志、当时用的模式、以及能复现问题的操作步骤，通常就能定位。

日志只写在这台机器上，程序不会上传任何内容。日志文件里那些看起来像乱码的短行是刻意压缩过的记录格式，字段含义见 [附录 A](docs/appendix.md#a)。

File logging is off by default. Enable it under Settings, Logging, and it writes to data/memwise.log, rotating once the file is full so it never grows without bound. Crash details go to data/memwise_crash.log.

Normally you can ignore it. Open it when you want to confirm what happened or when you are reporting a problem. For a report, include the last one or two hundred lines, the mode you were using, and the steps that reproduce the issue, which is usually enough to pin it down.

Logs stay on this machine; nothing is uploaded. The terse, code-like lines in the file are a deliberately compact record format, and their fields are explained in [Appendix A](docs/appendix.md#a).

---

## 游戏模式 · *Game Mode*

在「设置 → 游戏模式」里填上游戏进程名就会自动生效，也可以在主界面手动开关，手动开启后一直有效，直到你关掉它。

开启后的表现：游戏本身和它的子进程完全不清理；涉及磁盘的系统操作跳过，不抢磁盘；游戏之外的背景程序照常把闲置内存让出来；整体节奏放慢一些，减少干扰。

它按进程名识别，同名的进程都会受保护，所以填一次即可，不必每次开局都设置。游戏的启动与退出是实时识别的，不需要等一个周期。

Add the process names of your games under Settings, Game Mode, and it activates automatically; you can also toggle it manually from the main window, and manual activation stays until you turn it off.

While active: the game and its child processes are never trimmed; disk-oriented system operations are skipped so the disk is not contended; background programs outside the game still hand back their idle memory; and the overall rhythm slows down to reduce interference.

Detection is by process name, and every process sharing that name is protected, so you configure it once rather than before each session. Game start and exit are recognised in real time, with no cycle to wait for.

---

## 安全边界 · *Safety Boundaries*

有几条边界不随模式变化。

系统核心进程永远不清理，无论它在不在你的排除列表里。你写进排除列表的程序不清理，同名的全部生效。游戏运行期间，游戏进程树完全保护。MemWise 不会清理自己。

normal 与 deep 还会避开你正在使用的程序：刚切走的程序在一段时间内不动，有可见窗口时更久，内存高压时自动放宽；正在占用 CPU 或磁盘的程序也不动。full 跳过活跃判断，但上面那些硬保护依然有效。

工作集上限只限制物理占用，不改变提交内存，系统目录下的进程不允许设置。反复失败的任务会进入递增冷却，成功后自动衰减。

Some boundaries never change with the mode.

System-critical processes are never trimmed, whether or not they appear in your exclusions. Programs in your exclusion list are never trimmed, and every process with the same name is covered. While a game runs, its process tree is fully protected. MemWise never trims itself.

normal and deep also avoid the program you are using: one you just switched away from is left alone for a while, longer when it still has a visible window and relaxed under memory pressure, and programs actively using CPU or disk are left alone too. full skips the activity check but every hard protection above still applies.

A working-set cap limits physical usage only and never changes commit memory; processes under the system directory cannot be capped. Repeatedly failing tasks enter an escalating cooldown that decays after a success.

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

## 支持与赞赏 · *Support & Appreciation*

如果你觉得 MemWise 帮上了忙，并且有充足的意愿和赞赏渠道支持这个小小的项目，可以扫一扫下方的微信赞赏码——赞赏本身比钞票面值更有意义！当然，你的使用与反馈本身就是对我最大的支持！

If MemWise has been helpful, and you have the willingness and means to appreciate this small project, feel free to scan the WeChat reward QR code below — the appreciation itself means more than the amount. Of course, your usage and feedback are already the greatest support.

<p align="center">
  <img src="assets/donate.png" width="240" alt="微信赞赏码 · WeChat Reward QR Code">
</p>
