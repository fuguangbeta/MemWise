# MemWise 更新日志

> **MemWise** — Windows 智能内存看护工具。不杀进程、不挂起线程、不注入、不联网。
> 纯 ctypes Win32 API，零外部依赖。

---

## v1.7 (2026年7月 — 当前)

> 内核级优化能力跃升 + 架构安全加固 + 数据统计完整修复。NT API 操作码全部对齐 PHNT 标准，新增 8 步内核快速管线，系统级全进程 WS 清空配合 Standby 全量收割实现极致优化（实测可达 15%）。wndproc 彻底重写消除托盘崩溃（5 轮迭代），托盘、设置、Tooltip、日志、统计全面精修。累计修改 4 个核心文件、200+ 行，删除 6 个死函数/变量，新增 1 个管线函数，修正 NT API 操作码 17 处。

### 🔥 内核管线重写（操作码修正 + 8 步快速管线）

**NT API 操作码系统性偏移修正**（`winapi.py` 全局）：所有 `NtSetSystemInformation(80, info=X)` 的 X 值系统性偏移 +2。PHNT 标准 `SYSTEM_MEMORY_LIST_COMMAND` 枚举为 `MemoryCaptureAccessedBits=1, MemoryEmptyWorkingSets=2, MemoryFlushModifiedList=3, MemoryPurgeStandbyList=4, MemoryPurgeLowPriorityStandbyList=5, MemoryCommandMax=6`。但 `winapi.py` 中硬编码了 `empty_all_working_sets=4`（应为 2）、`flush_modified_pages=5`（应为 3）、`empty_standby=6`（应为 4，且超出 MemoryCommandMax 被内核拒绝）、`purge_low_priority_standby=7`（应为 5，同样被拒绝）。MemWise 最关键的 Standby 清空操作从一开始就从未真正执行成功过。涉及 17 处硬编码值全部修正为 PHNT 标准值 2/3/4/5。

| 函数 | 旧值 | 新值 (PHNT) | 对应枚举 | 状态 |
|------|:----:|:----:|------|:----:|
| `empty_all_working_sets` | 4 | **2** | MemoryEmptyWorkingSets | 旧值实际上是 MemoryPurgeStandbyList |
| `flush_modified_pages` | 5 | **3** | MemoryFlushModifiedList | 旧值实际上是 MemoryPurgeLowPriorityStandbyList |
| `empty_standby` | 6 | **4** | MemoryPurgeStandbyList | 旧值超出 MemoryCommandMax → 内核拒绝 |
| `empty_standby_low_priority` | 6 | — | — | 删除（与 purge 重复且值错误） |
| `purge_low_priority_standby` | 7 | **5** | MemoryPurgeLowPriorityStandbyList | 旧值超出范围 → 内核拒绝 |
| `combine_memory_lists` | 5 | **3** | MemoryFlushModifiedList | 旧值错误 |
| `trigger_memory_compression` | 7 | **5** | MemoryPurgeLowPriorityStandbyList | 旧值超出范围 → 内核拒绝 |
| `deep_compress` 四轮 | 5/6/4/6 | **3/4/2/4** | — | 含 2 个无效值 + 4 个 sleep(0.3) |
| `empty_standby_deep` 四轮 | 7/1/7/5 | **5/4/5/3** | — | 含 2 个无效值 + 值1=MemoryCaptureAccessedBits（无用）+ 2 个 sleep(0.3) |

**_layer1_memreduct — 8 步内核管线**（`cleaner.py` L201-238 新增）：删除旧的 `_layer1_atomic` 和 `_layer1_blitz`（后者从未被 `optimize()` 调用），重写为 `_layer1_memreduct(full=True/False)`。`full=True` 时执行完整 8 步连续调用（对标 PHNT 标准，零 sleep，<10ms）：MemoryEmptyWorkingSets(2) → SystemFileCacheInformationEx(0x15) → MemoryFlushModifiedList(3) → MemoryPurgeStandbyList(4) → MemoryPurgeLowPriorityStandbyList(5) → 卷缓存刷新 → 注册表缓存(81) → 文件缓存最终清空。`full=False`（轻量模式）跳过系统级 WS 全清，仅执行其余 7 步，用于 gap-fill 持续压制。入口处测量 `mem_pre/mem_post` 差值计入 `freed_bytes`，确保系统级释放被正确统计。

**管线激活**（`cleaner.py` `optimize()` L673-698）：所有四个 mode 分支的 Layer1 从旧 `_layer1_system`（含 0.2~1.75s sleep 的异步管线）替换为 `_layer1_memreduct`。执行顺序从"Layer1→Layer2"改为"Layer2→Layer1"，形成级联效应——Layer2 逐进程释放的 WS 页面进入 standby，Layer1 的 standby purge 一并收割。

**_layer1_system 残余 sleep 清除**（`cleaner.py` L258-277）：删除 `time.sleep(0.2)`（阶段2等待）和 `time.sleep(0.05)`（阶段3间隔）。`_progressive_compress` 删除后压缩路径统一使用简化后的 `deep_compress`。

**_layer3_deep 残余 sleep 清除**（`cleaner.py` L585-595）：删除 `time.sleep(2)` 和 `time.sleep(0.05)`。`_progressive_compress` 引用替换为 `deep_compress` 直接调用。`clean_standby_low` 引用从已删除的 `empty_standby_low_priority` 修正为 `purge_low_priority_standby`。

**deep_compress 简化**（`winapi.py` L654-666）：从 4 轮递进（每轮 0.3s sleep，含错误值 5/6/4/6，累计 1.2s）简化为单轮 flush(3)+purge(4) 双步，零 sleep。不再包含 `ULONG(1)`（MemoryCaptureAccessedBits，对内存释放无用）。

**empty_standby_deep 简化**（`winapi.py` L694-708）：从 4 轮递进（含 2 个无效值 7 + 无用的值 1 + 2 个 sleep(0.3)）简化为低优先(5)→全量(4)→冲刷脏页(3) 三轮，零 sleep。

**empty_standby 重写**（`winapi.py` L305-312）：删除旧的 `_EMPTY_STANDBY_METHOD` 模块级探测变量及 30 行的 fallback 链（尝试错误值 6 → 再次尝试 6 → 尝试 old_76 → EmptyWorkingSet(self)），改为直接调用 PHNT 标准值 4 的单行实现。

**self-EWS 清除**（`winapi.py` L649/L679/L729/L745）：删除 `flush_modified_pages`（L649）、`combine_memory_lists`（L679）、`clear_registry_cache`（L729）、`flush_volume_cache`（L745）共 4 处的 `EmptyWorkingSet(GetCurrentProcess())` 自清 fallback。`clear_registry_cache` 同步从 `buf=(w.ULONG*16)()` 修正为 `NtSetSystemInformation(81, None, 0)`（对标 PHNT 标准）。

### 🔥 WndProc 重写 — 托盘崩溃彻底修复（5 轮迭代）

**根因诊断**：`_wnd_proc` 是 Win32 窗口过程回调（`@WNDPROC` ctypes callback），在 Windows 消息泵层面被调用。Tcl/Tk 内部在消息分发期间不可重入。任何在 `_wnd_proc` 中直接或间接调用 Tkinter API 的操作都会触发 Tcl 内部状态损坏→硬崩溃（C 层 segfault，faulthandler 无法捕获，无 crash.log）。

**迭代过程**：
| 轮次 | 改动 | 结果 |
|:----:|------|:----:|
| 1 | 所有 Tkinter 调用改为 `root.after(0, ...)` 延迟 | 仍崩溃——`after()` 调度时需要访问 Tcl 定时器队列，同样触发重入 |
| 2 | 移除 `focus_force()`，增加 `withdrawn` 状态检测 | 仍崩溃——`after()` 本身仍被调用 |
| 3 | 增加 `WM_LBUTTONDOWN(0x201)` 支持、`_gui_ref is not None` 检查 | 仍崩溃——`_gui_ref.root` 访问仍在 wndproc 中 |
| 4 | 添加 `faulthandler` + `sys.excepthook` 诊断 | 仍崩溃且无日志——确认为硬崩溃 |
| 5 | **标志位架构**：零 Tkinter 调用 | **彻底修复** ✅ |

**最终方案**（`memwise_gui.py` L78-106）：`_wnd_proc` 仅设置模块级字符串标志 `_tray_action = 'left'|'right'|'hotkey'`（纯 Python 赋值，无任何 Tkinter 交互）。由已有的 `_poll_msg_queue` 定时器（每 100ms，在主线程 Tkinter 事件循环中）检查并安全分派到 `_on_tray_left_click`、`_show_tray_menu`、`_on_hotkey`。

**托盘左键完整支持**（`memwise_gui.py` L288-298）：新增 `_on_tray_left_click` 方法，在 Tkinter 上下文中处理所有逻辑——读取 `CFG["tray_left_action"]`，支持 show/clean/none 三种行为，状态检测覆盖 `"withdrawn"` 和 `"iconic"`。

**`_show_window` 加固**（`memwise_gui.py` L336-345）：仅当 `state in ("withdrawn", "iconic")` 时执行 `deiconify`，移除 `focus_force()`（已知 Windows 崩溃源）。

**热键安全化**（`memwise_gui.py` L100）：从直接调用 `_on_hotkey()` 改为设置 `_tray_action='hotkey'`，统一走标志位→轮询路径。

### 🔥 参数全局激进优化

| 参数 | 旧值 | 新值 | 文件/位置 |
|------|:----:|:----:|------|
| PID target_usage | 45% | **30%** | `judger.py` L14 TARGET_USAGE |
| 前台清理门槛 | agg≥0.6 | **agg≥0.35** | `judger.py` L130-132 can_trim |
| 失败冷却基数 | 3600s | **300s (5min)** | `judger.py` L229 cooloff_base |
| Layer3 触发门控 | agg≥0.6 | **agg≥0.3** | `cleaner.py` L682 optimize normal |
| deep 模式 Layer3 | agg≤0.6（反逻辑） | **始终执行** | `cleaner.py` L689 optimize deep |

**PF 反馈"先收后审"**（`cleaner.py` L382-399 `_trim_process`）：`freed_bytes` 在 `freed > 0` 时在 `with self._lock` 块最前端无条件计入，不受后续 `ok` 判定影响。`ok` 仅用于 Thompson 学习信号的正负向（`record_clean_result`）。PF 超标时已释放的字节不再丢失。

**self-PID 排除**（`cleaner.py` L457-462 `_layer2_process`）：新增 `import os; SELF_PID = os.getpid()`，遍历 snaps 时 `if s.pid == SELF_PID: continue`。防止系统级 WS 全清波及自身。

### 📊 数据统计完整修复

**_fast_track 初始化**（`cleaner.py` L82）：从 `_layer2_process` 内懒初始化（L548 `self._fast_track = set()`）移至 `__init__` 中显式初始化 `self._fast_track = set()`。修复守护启动时 gap-fill 循环在首次 `_layer2_process` 之前访问 `self.cleaner._fast_track` 导致的 `AttributeError` 崩溃。

**`cycle_freed` 数据源修复**（`memwise_gui.py` L1869-1872）：从 `net_freed`（`GlobalMemoryStatusEx` 惰性更新，始终返回 0）回退到差值法 `cur_freed - self._chart_last_freed`（`freed_bytes` 每笔操作累加）。日志、统计栏、图表三者同源一致。

**`net_freed` 死代码修复**（`cleaner.py` L658-698 `optimize()`）：所有 mode 分支原本提前 return，导致 L704-705 的 `mem_after_opt` / `net_freed` 赋值永远不可达。重构为 `_mk_result` 闭包在每个 return 前计算 `net_freed`。

**进程整理计数修复**（`memwise_gui.py` L1950）：日志从 `len(trimmed)`（仅 Layer2 返回结果）改为 `self._cycle_trimmed`（stats 差值 = Layer2 + Layer3 合计）。首轮不再出现日志 21 vs 统计栏 24 的不一致。

**统计栏千位格式化恢复**（`memwise_gui.py` L1282/L1968）：`_upd_stats` 和 `_upd_dae_ui` 中 `lbl_sb` 和 `lbl_tr` 从裸数值改回 `self._fmt_count()` 格式化（≥1000 显示 1.2k 等）。v1.6 引入后在管线重构中意外丢失。

**日志周期修正**（`memwise_gui.py` L1773/L1952）：`cycle_start` 从等待阶段后重新计时，`elapsed` 和尾 sleep 不再包含 60s 等待期。日志严格 60s 间隔输出，不再出现 116s 的不规则间隔。

### 🔧 持续优化架构细化

**轻量/全量分频**（`cleaner.py` L201 `_layer1_memreduct` + `memwise_gui.py` L1802/L1829/L1833）：gap-fill 和 blitz 循环使用 `_layer1_memreduct(full=False)`（仅 standby purge，不动 WS），harvest 和主 pass 的 optimize 使用 `_layer1_memreduct(full=True)`（全量 8 步）。消除每 1s 一次的空转式全量 WS 清空（进程来不及回填），仅在每 ~15s 的 harvest 和每 60s 的主 pass 执行有效收割。

**快车道消费**（`memwise_gui.py` L1803-1808）：gap-fill 循环中 new 消费 `self.cleaner._fast_track`，对高回填进程追加 `winapi.empty_ws(ft_pid)`。此前 `_fast_track` 在 `_layer2_process` 中创建但从未被消费（死字段）。

**紧急清理强化**（`memwise_gui.py` L1789-1792）：从使用旧 `agg` + 当前 mode 改为基于 `m_emerg` 实时计算 `agg_emerg` + `full` mode。

### 🔧 设置面板与 Tooltip 全面更新

**设置按钮 tooltip**（`memwise_gui.py` L444-459）：删除 5 处"默认开"字样。

**进程清理深度 tooltip**（`memwise_gui.py` L871/960）：从 Slider 控件（`ps_sl`）移至 Label 文字（`ps_lbl`），与紧急触发阈值的 tooltip 位置一致。Slider 控件保留不变。

**窗口高度**（`memwise_gui.py` L620）：设置窗口高度 700→600，居中计算同步修正（L619 700→600）。学习日志窗口居中计算同步修正（L995 700→650）。

**第二设置面板补充**（`memwise_gui.py` L938/L953）：托盘左键行为 ComboBox 和日志 Checkbutton 各新增 tooltip（与第一面板对称，之前遗漏）。

**Tooltip 十处内容重写**（`memwise_gui.py`）：
| 位置 | 旧内容关键词 | 新内容 |
|------|-------------|--------|
| 优化按钮 L379-388 | 两阶段异步管线、等待 0.3s、阶段1/3 | 8 步内核管线·<10ms·零等待 |
| 守护按钮 L392-413 | 持续满负载优化、学习系统 | 轻量持续+全量收割架构 |
| 模式选择 L484-499 | L1系统级封顶30%、L1含压缩 | 7/8 步管线描述 |
| 系统杂项统计 L527-534 | 渐进式压缩(三步异步链) | NtSetSystemInformation 内核调用 |
| EmptyWorkingSet L772-777 | 前台进程不会被清理、仅守护模式 | agg≥0.35 前台清理，删除仅守护模式限制 |
| Standby List L781-785 | 比单次多释放 5~10% | 配合全量收割 |
| Modified Page L789-793 | memory pressure > 0.1 触发 | 每次系统级清理均执行 |
| 内存压缩 L797-802 | 多轮渐进式(三步异步链)、pressure > 0.05 | 单轮 flush+purge 管线 |
| 系统文件缓存 L806-811 | pressure > 0.25 触发 | 每次系统级清理均执行 |

**"MemReduct / 对标 / 适配自"字样清除**：`memwise_gui.py` 4 处、`cleaner.py` 2 处、`winapi.py` 3 处，共 9 处全部替换为中性描述。

### 🔧 死代码与冗余清理

| 删除项 | 文件 | 说明 |
|--------|------|------|
| `_layer1_blitz` | `cleaner.py` L226-228 | 仅代理到 `_layer1_atomic`，从未被 `optimize()` 调用 |
| `_progressive_compress` | `cleaner.py` L204-209 | 代理到 `deep_compress`，调用处统一改用直接调用 |
| `empty_standby_low_priority` | `winapi.py` L635-643 | 与 `purge_low_priority_standby` 功能完全重复，且使用错误值 6 |
| `_try_empty_standby_new` | `winapi.py` L261-266 | 旧 `empty_standby` 探测 helper，含错误值 6，不再被引用 |
| `_try_empty_standby_old` | `winapi.py` L257-259 | 旧 `empty_standby` 探测 helper，使用过时 info class 76，不再被引用 |
| `_EMPTY_STANDBY_METHOD` | `winapi.py` L317 | 模块级探测缓存变量，随 `empty_standby` 重写一并删除 |

### 🔧 图表内存优化

`_chart_data` 和 `_eff_data` deque 从 maxlen=60 缩减到 20（`memwise_gui.py` L181/L189），降低 GUI 常驻内存。

### ⚙ 构建

- 版本号 v1.6→v1.7
- `--uac-admin`、`--icon assets/icon.ico`
- `--add-data "config/config.yaml;config"`
- PyInstaller 6.21.0 + Python 3.14.0
- 构建前 `taskkill /f /im MemWise.exe` + `Remove-Item dist/MemWise.exe -Force`
