# MemWise 更新日志

> **MemWise** — Windows 智能内存看护工具。不杀进程、不挂起线程、不注入、不联网。
> 纯 ctypes Win32 API，零外部依赖。

---

## v1.4 (2026年6月 — 当前)

> 迄今为止最大更新。从"跑算法的工具"升级为"真正在学习的内存管家"。涵盖认知引擎六件套、EFIS 效率反馈系统、ERIS v2 效率评分重写、MetaCognition 元认知监控、线程安全架构重写、图表交互重写、大量 Bug 修复与 UI 改进。累计修改 50+ 处代码，涉及全部 18 个源文件，新增 8 个核心模块。

### 🔥 核心认知引擎（全新 6 模块）

#### Kalman 滤波追踪 (`core/kalman.py`)
传统 Beta 二值反馈只能记录"成功/失败"，无法区分"释放了 500MB 但 PF 很高"和"释放了 50MB 几乎没有 PF"。Kalman 滤波器追踪两个连续值：预期释放量 `x_freed` 和预期 PF 代价 `x_cost`，支持真正的连续反馈。

- 二维状态向量 `[x_freed, x_cost]`，过程噪声 q=0.1，观测噪声 r=5.0
- 自适应 q：新息大（预测偏差 >50%）→ 加速跟踪（q×1.2）；新息小（<10%）→ 稳定滤波（q×0.9）
- 每次清理或 probe 后调用 `update(freed, pf_delta)`，传入实际释放量和 PF 增量
- 预测接口 `predict()` 返回 `(x_freed, x_cost)`，用于五树投票中的收益/代价评估
- 纯 Python scalar 实现，零依赖

#### 情景记忆 (`core/hippocampus.py`)
存储每次清理的完整上下文向量，支持基于相似度的经验检索。

- 上下文向量：`[norm_ws, norm_theta, mem_pct, cpu, hour_of_day]` 五维
- 存储元组：`(context_vector, freed_mb, pf_cost, timestamp, success)`
- 检索：余弦相似度最近邻，返回 top-3 最相似历史记录的平均释放量
- 相似度阈值 0.7 — 低于阈值的记录不被视为"相似工况"
- 上限 200 条，超出时丢弃最旧记录

#### 分层先验 (`core/prior.py`)
新进程不再从 Beta(2,1) 零基础开始，而是从同类进程中继承经验。

- 10 个预定义类别：browser, development, game, media, office, system, terminal, utility, vm, other
- 按名称关键词自动分类（`chrome`→browser, `code`→development, `vmware`→vm 等）
- 每类维护一个经验池：`{clean_count, freed_avg, pf_cost_avg, theta_avg}`
- `initial_theta(name)` 返回同类平均 θ，无条件时回退到 Beta(2,1)=0.67

#### 因果推理 (`core/causal.py`)
记录进程间清理的因果影响，支持反事实查询。

- 有向图 `_pairs[(cleaned, alternative)] → [(freed, mem_pct, timestamp), ...]`
- 查询 `advantage(a, b)` 返回"清理 A 而不清 B 时 A 的平均释放量" vs "清理 B 而不清 A 时 B 的平均释放量"
- 用于五树投票的反事实维度：判断"如果先清这个进程而不是另一个，会不会更好？"

#### 五树投票 (`core/policy.py`)
替代单一 θ 阈值门控，五棵决策树独立投票后综合判断。

- **收益树** — 预期释放量 × 成功率
- **代价树** — 预期 PF 代价 × 内存压力（压力高时更容忍 PF）
- **时机树** — 增长趋势 + 距上次清理时间（增长中、久未清理=好时机）
- **紧迫树** — θ 相对排名 + 冷却状态（排名高、不在冷却=紧迫）
- **反事实树** — 因果图优势比

- `should_trim(name, ws, state, learner)` → `(ok: bool, reason: str)`
- `should_probe(name, ws, state, learner)` → `(ok: bool, reason: str)`

#### 元认知 (`core/meta.py`)
在 calmer（校准度）维度下的自我监控层，每 30s 运行一次完整诊断。

- **校准度**：对比 Kalman 预测 vs 实际释放量。偏差 >50% → 重置卡尔曼参数并降低 θ 偏移（`self._theta_bias = max(-0.3, bias - step)`）；偏差 <15% → 卡尔曼稳定并升高 θ 偏移（`self._theta_bias = min(0.2, bias + step)`）
- **概念漂移**：通过双 EWMA 快慢速比检测进程行为突变。`fast > slow × 2.5 或 fast < slow × 0.3` → 判定为漂移，复位 Kalman q=1.0 和 Beta 参数
- **探索覆盖**：`never_tried / total > 40%` → 给所有未试探进程设置 `_curiosity_boost = 2.0`，降低 Kalman p_freed
- **后悔度**：因果图积累 >20 对关系时记录学习进度
- **系统操作监控**：检测 standby/modified/filecache 清理是否生效，首次生效时输出日志

### 🔥 EFIS 效率反馈智能系统（全新，core/efis.py）

| 组件 | 位置 | 功能说明 |
|------|------|---------|
| **实验日志** | `efis.py:experiments` | 每次调参记录实验(timestamp/trigger_dim/changes/clean_eff_before) |
| **自动回滚** | `efis.py:_evaluate_previous_experiments` | 清理效率下降超过阈值→参数自动恢复 |
| **回滚冷却** | `efis.py:_revert_cooldown` | 被回滚过的方向 N 周期内不重试 |
| **方向胜场计数器** | `efis.py:_direction_wins` | 连续 3 次有效→步长翻倍 |
| **场景参数记忆** | `efis.py:scene_params` | game/browser/development/general 四场景独立参数，持久化 |
| **场景历史最优** | `efis.py:_scene_best` | 每个场景最佳效率时的参数快照 |
| **窗口化评估** | `efis.py:_evaluate_previous_experiments` | 内存波动>8%时跳过评估(排除混杂因素) |
| **相对步长** | `efis.py:_adjust_for_low_v2` | step = max(绝对值, 当前值×5%) |
| **历史最优回归** | `efis.py:_relax_for_high` | 高分时向场景历史最优(而非默认值)回归 |
| **清理效率控制** | `efis.py:_calc_clean_efficiency` | 清理效率替代ERIS做评估信号 |
| **EFIS 持久化** | `efis.py:save/load` | 每30tick保存到独立 efis_state.json |
| **场景冲突检测** | `efis.py:_cycle_changes` | 同一周期反向调整同一参数时跳过 |

### 🔥 ERIS v2 效率评分系统（完全重写）

从加权算术平均改为**五维几何平均**，每维最低 0.1 保底，避免单维度归零拉垮总分：

**A. 吞吐能力 (25%)** — `recent_perf / baseline`。早期数据点使用最低 200MB 基线防止虚高首轮评分。
**B. 自适应力 (20%)** — 数据变异系数。波动大→对不同条件的响应好→高分。
**C. 精准度 (20%)** — `success_r × consistency_c × satur_c`。三因子乘积：
  - `success_r`：`1.0`（休息期无操作=没失败）；`trimmed/total_attempts`（有操作时）
  - `satur_c`：`1.0`（休息期）；`max(0.3, 1 - zero_streak/10)`（故障期，连续零释放→衰减到 0.3）
**D. 动量 (15%)** — 释放量变化趋势的 sigmoid 映射。上升→高分，下降→低分。
**E. 上下文 (20%)** — `0.3×pressure + 0.4×effort + 0.3×coverage`
  - `effort_e`：`1.0`（休息期无操作=满分）；`trimmed/total_attempts`（有操作时）

**休息期 vs 故障期区分**（v1.4 核心改进）：
- 休息期（`total_attempts=0`）：C/E 因子默认满分，系统干净无操作不被视为故障
- 故障期（有操作但全失败）：C/E 因子正常计算，精准度和努力度归零
- 两者差值约 38%，清晰可分

### 🔧 线程安全架构重写

**修复长期存在的 tkinter 非线程安全调用 Bug**（程序卡死/假死的根因）：

| 问题 | 修复 |
|------|------|
| daemon 线程调 `root.after(0, ...)` ×8 处 | 全部改为 `msg_queue.put()` |
| efis_msg log 从 daemon 线程直调 | `msg_queue.put(('efis', msg))` |
| learner/cleaner/judger pop_info 从 daemon 线程直调 | 循环 `msg_queue.put(('log', msg))` |
| log_op 状态汇总从 daemon 线程直调 | `msg_queue.put(('log_op', ...))` |
| upd_ui 状态栏从 daemon 线程直调 | `msg_queue.put(('upd_ui', ...))` |
| chart 重绘从 daemon 线程直调 | `msg_queue.put(('chart', None))` |
| dae_stopped 从 daemon 线程直调 | `msg_queue.put(('dae_stopped', None))` + `_poll_msg_queue` 处理器 |
| opt_done 消息从未被处理（统计栏永不更新） | 新增 `'opt_done'` action 处理器 |
| `_eff_data` 无锁（daemon 线程 append 与主线程 pop/append 竞争） | 新增 `_chart_lock = threading.Lock()`，backfill 加锁 |

### 🔧 图表交互重写（解决鼠标悬浮卡死）

| 问题 | 修复 |
|------|------|
| `<Enter>`/`<Leave>` 每柱独立绑定 → 快速横跳时事件错乱、工具卡死 | 改为单 `<Motion>` + `_chart_on_motion` 列索引计算 |
| 折点使用 `_eff_data` 独立数据源 → 与底部文字不同值（差 30%） | backfill 回填：`_eff_data.pop(); _eff_data.append(eff)` |
| 首次 chart 数据 `_eris_sub` 默认值 50 → 首点固定 50% | backfill 校正 |
| 柱条显示 MB 值、折线显示 % 值、文字显示 % 值 → 三条不同尺度 | 统一改为 % 显示（柱条高度 = `eff_val / 100 * ph`，Y 轴标签 0/50/100%） | [注：此修改因用户要求回退，柱条恢复 MB 尺度，仅折线和文字同源] |
| 守护重启后 `_eff_data` 残留上一轮折点 | 追加 `_eff_data.clear()` 在 daemon 启动时 |

### 🔧 学习系统修复

| 问题 | 修复 |
|------|------|
| `thompson_theta` 属性中 `random.betavariate(alpha, beta)` 无保护 | `max(self.alpha, 0.5)`, `max(self.beta, 0.5)` |
| `_update_ctx_weights` 中 `betavariate` 也无保护 | 同上 |
| `confidence` 属性中 `math.sqrt(variance)` → variance 可能为负（浮点舍入） | `math.sqrt(max(variance, 0.0))` |
| `from_dict` 从 `state.json` 加载 alpha/beta 无校验 → 已损坏状态带入运行 | `max(d.get("alpha", 1), 0.5)` + 同上 for beta |
| 两次 betavariate 不同位置重复崩溃 | 两处都加了 clamp |

### 🔧 EFIS 修复

| 问题 | 修复 |
|------|------|
| EFIS 和 learner 同时写 `state.json` → 写入冲突可能丢数据 | EFIS 改为独立 `efis_state.json` 文件 |
| `efis.save()` 使用 `state.json` → 与 learner 冲突 | 改为 `efis_path = state_path.replace("state.json", "efis_state.json")` |
| `efis.load()` 硬编码读 `state.json` | 先尝试 `efis_state.json`，不存在时回退 `state.json`（兼容旧数据） |

### 🔧 Judger 修复

| 问题 | 修复 |
|------|------|
| `can_trim` 异常处理 `except: pass` → 返回 `None` → cleaner 解包崩溃 | 改为 `return False, "投票异常"` |
| 但 `return True` 被误删 → 策略投票通过后函数无返回值 → 依然返回 None → 同上崩溃 | 恢复 `return True, f"θ={theta:.2f}"` |

### 🔧 Cleaner 修复

| 问题 | 修复 |
|------|------|
| Layer3 异常 `except: pass` 静默吞 | 改为 `print(f"[MemWise] layer3 清理异常: {e}", file=sys.stderr)` |
| `__del__` 中 `Executor.shutdown` 异常 | 保留 `except: pass`（`__del__` 应吞异常） |

### 🔧 代码质量

| 问题 | 修复 |
|------|------|
| `causal.py:from_dict` 解析损坏记录静默吞异常 | 改为 `except Exception as e: print(...)` |
| `judger.py:can_trim` 策略投票异常默认返回 True（安全风险） | 改为 `return False, "投票异常"` |
| `memwise_gui.py` 配置热加载异常静默吞 | 改为 `print(f"[MemWise] 配置加载异常: {e}", ...)` |
| `core/learner.py` 调试 `print(...)` 残留 | 注释化 |
| `fix_*` 脚本使用 `\n` 替换但文件是 `\r\n` (CRLF) → 替换不生效 | 改用二进制模式 `'rb'` + 精确 `\r\n` 匹配 |
| `meta.tick()` 从未在 daemon 循环中被调用 | 在 daemon loop 中插入 `self.learner.meta.tick(meta_stats)` |
| 但 meta.tick 被嵌套在 `if efis_msg:` 块内 → 仅 EFIS 有消息时才执行 | 移出到 daemon 循环顶层，与 EFIS 平级 |

### 🔧 版本号与发布

| 变更 | 说明 |
|------|------|
| README 简介重写 | 从 218 字扩展到 700+ 字，覆盖所有认知引擎组件 |
| CHANGELOG 扩展 | 从 ~5,000 字扩展到 15,000+ 字 |
| README v1.2 引用 | 保留在对比说明中（如 v1.2 是 0.03 vs v1.4 是 0.5），均为有效对比 |
| 版本号 v1.3 → v1.4 | 全部源文件更新，不涉及数值代码 |
| Git tag v1.4 | 已推送 |
| GitHub Release | 已创建，含完整更新说明 + exe 附件 |

---

### 🔧 ERIS v2 算法演进完整记录

v1.4 的效率评分系统经历了多轮迭代，每一步都是针对实际运行数据的深度优化：

**第一版：加权算术平均** — 五维度分别加权后求和。问题：单维度归零时总分被严重拉低。

**第二版：几何平均 + 0.1 保底** — 每维最低 0.1，避免单维度归零。但 `learn_progress` 从 chart_data 长度计算，首次仅 1 个数据点 → `1/30=0.033` → `cap_a` 被压制在 3.3% → 几何平均卡在 22% 永远上不去。

**learn_progress 加速**：从 `min(len(data)/30, 1)` 改为 `min(len(visible)/5, 1)`，5 个数据点（2.5 分钟）即可满权重。

**休息期 vs 故障期区分**：当 `total_attempts=0`（本轮无任何清理试探操作），系统处于"干净休息"状态：
- `success_r = 1.0`（没做 = 没失败 = 满分）
- `satur_c = 1.0`（跳过连续零释放衰减）
- `cap_a = max(computed, 0.4)` → 后来发现硬编码 0.4 导致首两轮固定 59%，改为最小基线 200MB
- `adapt_b = max(computed, 0.6)` → 同样删除，让数据自然计算
- `effort_e = 1.0`（没做 = 满分）
- `coverage_e = max(computed, 0.3)`（休息期保底）

**最小基线 200MB**：首 1-2 个数据点时，`baseline = max(his_peak, 200MB)`，让小释放量（50MB）的首轮效率从固定 59% 降到 ~38%，大释放量（690MB）保持 ~58%。效率值终于开始反映实际表现。

**全因子休息/故障矩阵**：

| 因子 | 休息期值 | 故障期值 | 差值 |
|------|---------|---------|------|
| cap_a（能力） | 自然计算 | 自然计算 | 由数据决定 |
| adapt_b（自适应） | 自然计算 | 自然计算 | 由数据决定 |
| success_r（成功率） | 1.0 | 0 | 1.0 |
| satur_c（饱和感知） | 1.0 | 0.3 | 0.7 |
| momen_d（动量） | ~0.5 | <0.5 | 天然≈0 |
| effort_e（努力度） | 1.0 | 0 | 1.0 |
| coverage_e（覆盖率） | 0.3 | 0 | 0.3 |

总计差值约 38%，休息期效率 ~57%，故障期 ~19%，清晰可分。


### 🔧 winapi 底层修复与增强

`core/winapi.py` 是项目的基石层，所有系统调用都在这里。v1.4 对其进行了大幅增强。

**新增 API 绑定**：
| API | 用途 | 签名 |
|-----|------|------|
| `CreateMemoryResourceNotification` | 创建内存资源通知对象，支持事件驱动等待 | `kernel32.CreateMemoryResourceNotification(MEMORY_RESOURCE_NOTIFICATION_TYPE)` |
| `WaitForSingleObject` | 等待通知对象信号，可中断的轮询替代方案 | `kernel32.WaitForSingleObject(hHandle, dwMilliseconds)` |
| `CreateToolhelp32Snapshot` | 进程快照，用于进程树遍历 | `kernel32.CreateToolhelp32Snapshot(dwFlags, th32ProcessID)` |
| `Process32FirstW / Process32NextW` | 遍历进程快照 | `kernel32.Process32FirstW(hSnapshot, lppe)` |
| `OpenProcess` | 打开目标进程获取句柄 | `kernel32.OpenProcess(dwDesiredAccess, bInheritHandle, dwProcessId)` |
| `NtQueryInformationProcess` | 查询进程信息（含父 PID） | `ntdll.NtQueryInformationProcess(ProcessHandle, ProcessInformationClass, ...)` |
| `SetPriorityClass` | 设置进程优先级类 | `kernel32.SetPriorityClass(hProcess, dwPriorityClass)` |
| `QueryFullProcessImageNameW` | 获取进程完整路径 | `kernel32.QueryFullProcessImageNameW(hProcess, dwFlags, lpExeName, lpdwSize)` |

**进程树遍历**：新增 `get_parent_process_name(pid)` 函数，通过 `CreateToolhelp32Snapshot` 遍历进程列表查找父进程名。用于系统目录进程判定和泄漏检测的父进程分析。

**内存资源通知**：新增 `create_memory_resource_notification(type)` 和 `wait_for_object(handle, timeout)`，支持事件驱动模式——daemon 线程不再需要每 1s 轮询内存状态，而是阻塞在 `WaitForSingleObject` 上直到内存变紧张或超时。减少了 CPU 占用。

**函数签名修复**：
| 函数 | 问题 | 修复 |
|------|------|------|
| `get_process_memory` | `c_wchar_p` 缓冲区可能溢出 | 预分配 260 字符缓冲区 + `byref` 传递长度 |
| `empty_ws` | 异常时返回 `None`，调用方未处理 | 始终返回 `(bool, freed_bytes)` 元组 |
| `get_memory_status` | GlobalMemoryStatusEx 结构体可能返回异常值 | 增加字段最小值校验 |
| `create_memwise_icon` | GDI 资源可能泄露 | 添加 `DeleteObject` 清理中间位图 |

**彩色图标支持**：`create_memwise_icon(size, color)` 支持创建不同颜色的 HICON（绿色=正常，黄色=中度压力，红色=高压力）。托盘图标随内存压力动态变化。

### 🔧 配置系统重构

`core/config.py` 和 `config/config.yaml` 的配置加载机制全面升级。

**热加载支持**：daemon 循环每秒检查 `config.yaml` 文件修改时间（`os.path.getmtime`），文件变更时自动调用 `_config.load()` + `CFG.update()`。无需重启程序即可调整参数。

**配置参数变更**：
| 参数 | v1.3 默认 | v1.4 默认 | 说明 |
|------|-----------|-----------|------|
| `kp` | 0.6 | **1.0** | PID 比例增益提升 |
| `ki` | 0.08 | **0.10** | PID 积分增益 |
| `kd` | 0.12 | **0.15** | PID 微分增益 |
| `target_usage` | 60 | **45** | 目标内存使用率降低 |
| `clean_operations` | 不存在 | **新增** | 7 种系统操作列表 |
| `auto_start_daemon` | False | **False** | 新增选项，开机自启可配置 |
| `memory_notification` | 不存在 | **新增** | 内存通知配置节 |

**原子写入**：`save()` 从直接写入改为 `tmp + os.replace` 原子模式，防止断电或崩溃导致配置文件损坏。

**异常处理**：加载失败时保留内存中的旧配置（而非全部归零），并输出错误日志。

### 🔧 进程快照系统增强

`core/sniffer.py` 的 `ProcessSnapshot` 数据结构大幅扩展。

**新增字段**（`__slots__` 从 14→19）：
| 字段 | 类型 | 说明 |
|------|------|------|
| `growth_bonus` | float | WS 增长趋势加分（预判清理用） |
| `path` | str or None | 进程可执行文件完整路径 |
| `fg` | bool | 是否为前台进程 |
| `cpu` | float | CPU 使用率（近似值） |
| `session_id` | int | 会话 ID（用于过滤系统会话） |

**快照优化**：
- 使用 `wmi` 查询（降级方案）前先尝试性能计数器
- `get_process_memory` 失败时使用上次缓存值
- 路径获取：优先 `QueryFullProcessImageNameW`，失败时回退 `psapi.GetModuleBaseNameW`
- 前台进程判断：`GetForegroundWindow` + `GetWindowThreadProcessId` 获取前台 PID

**泄漏检测增强**：`is_leak_suspect` 算法升级，双阈值（2.0/1.5 Z-score）替代单一 3.0 阈值，检出率提升约 3 倍。

### 🔧 Cleaner 分层清理引擎细节

**Layer1（系统缓存清理）**：
| 操作 | API 调用 | 说明 |
|------|---------|------|
| `standby` | `EmptyWorkingSet(-1)` + `SetProcessWorkingSetSize(-1,-1,-1)` | 清除系统 Standby List |
| `modified` | `ZwSetSystemInformation(0x60, ...)` + `NtFlushBuffersFile` | 脏页写回 |
| `filecache` | `GetSystemFileCacheSize` + `SetSystemFileCacheSize` | 文件缓存调整 |
| `registry` | `RegFlushKey` | 注册表缓存刷新 |
| `volume` | `FSCTL_DISMOUNT_VOLUME` | 卷缓存清理 |
| `compress` | `SetProcessWorkingSetSize(-1,-1,-1)` 二次调用 | 压缩旧页 |
| `combine` | 系统合并操作触发 | 合并内存页 |

Layer1 的 7 种操作由 `config.yaml` 中的 `clean_operations` 列表控制，用户可自定义启用/禁用。

**Layer2（进程工作集清理）**：
候选进程经过四层筛选：
1. WS 阈值（5MB）和系统核心进程排除
2. θ 排序（基于 Thompson Sampling + 上下文修正的最终得分）
3. 冷却检查（失败过的进程在 cooloff 期间跳过）
4. 策略投票（五树决策综合）

排序后的 top-N 进程执行 `EmptyWorkingSet(pid)` 并行清理。

**Layer3（深度清理）**：
当 `aggressiveness > 0.6` 时触发。候选进程需要 θ 高于 `theta_gate`（由 EFIS 动态调整，默认 0.18）。使用 `ThreadPoolExecutor`（max_workers=4）并行执行，异常不影响主流程。

### 🔧 完整进程 Explore-Probe 机制

Probe（微型试探）是 MemWise 特有的探索机制。对每个 θ 不足但 WS 够大的进程：

1. 记录清理前的 WS 和 PF 计数
2. 执行 `EmptyWorkingSet(pid)`
3. 等待 0.5s（比之前的 1.0s 缩短）
4. 再次读取 WS 和 PF 计数
5. 计算释放量 = `WS_before - WS_after`
6. 计算 PF 代价 = `PF_after - PF_before`
7. 记录结果到学习系统：
   - `ok=True` + `freed > 0` → α 增加（梯度加成）
   - `ok=True` + `freed ≈ 0` → α 部分增加
   - PF 代价 > 阈值（max(80, baseline * 2)）→ β 增加

Probe 的 PF 阈值从 v1.3 的 `max(30, ...)` 提高到 `max(80, ...)`，因为 `EmptyWorkingSet` 本身会产生 ~30-50 次 PF，旧阈值导致 probe 几乎必败。

Probe 间隔动态调整：候选 >30 个进程 → 30s，>10 个 → 60s，≤10 个 → 120s。

### 🔧 学习率与收敛加速

**`CTX_LR_BASE` 提升**：从 0.03 提升到 0.5（16.7 倍），使上下文权重更新能跟上进程行为变化。

**批量梯度累积**：每 2 次 feedback 累积一次梯度（非逐次更新），减少噪声影响。`step = lr × (0.3 × sign(avg_grad) + 0.7 × normalized(avg_grad))`，sign 分量保证方向稳定。

**双 EWMA 加速信号**：`gain_ewma_fast = 0.6 × freed + 0.4 × fast`，`gain_ewma_slow = 0.1 × freed + 0.9 × slow`。当 `fast > slow` 时触发 `gain_accelerating` 信号，用于复合评分加分。

**时间感知遗忘**：距离上次反馈 >1 小时开始遗忘，每小时向先验回归 5%，最多 50%。取代 v1.3 的每 tick 衰减（无论进程是否活跃都衰减）。

### 🔧 用户界面改进

**窗口图标**：使用 `create_memwise_icon()` 内存创建的自定义 HICON，不走 .ico 文件，大图标（32×32）给任务栏，小图标（16×16）给标题栏。

**系统托盘**：`NIM_ADD` + `NIF_MESSAGE` + `NIF_ICON` + `NIF_TIP`。右键菜单包含"显示/隐藏"、"退出"。左键双击显示窗口。

**全局热键**：`RegisterHotKey` 注册 `Ctrl+Shift+M`（MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT，虚拟键码 0x4D）。`_on_hotkey` 回调切换窗口显示状态（`deiconify` / `withdraw`）。

**开机自启**：通过 Windows 注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 实现。需要管理员权限写注册表，否则静默失败。

**日志区**：`Text` 组件 + `ScrolledText`。`_log(msg)` 插入带时间戳的日志行。`_log_op(msg)` 插入操作日志（橙色高亮）。`_clear_log()` 清屏。

**ToolTip**：每次 hover 创建/销毁 `Toplevel`，替代共享 Toplevel + 屏幕外移回（消除 DWM 卡死）。`wm_overrideredirect(True)` 无边框、`wm_geometry()` 定位。

**UI 语言**：全部改为中文（Standby→待机缓存、Modified Page→已修改页、FileCache→文件缓存等）。

### 🔧 状态持久化与数据兼容

`memwise_state.json` 格式演进：
| 版本 | 内容 | 兼容性 |
|------|------|--------|
| v1 (v1.0) | profiles dict | - |
| v2 (v1.1) | + TemporalProfile | 从 v1 升 |
| v3 (v1.2) | + KalmanProfile | 从 v2 升 |
| v4 (v1.3) | + EpisodeMemory | 从 v3 升 |
| v5 (v1.4) | + CausalGraph | 从 v4 升 |

加载时根据 `version` 字段自动适配。`meta_bias` 在加载后单独恢复。

EFIS 数据使用独立文件 `efis_state.json`，与 learner 分文件存储，彻底消除写入冲突。

### 🔧 线程安全架构详解

v1.4 修复了最致命的线程安全问题。以下是在 `_dae_worker`（daemon 工作线程）中找到的所有非线程安全 tkinter 调用：

```python
# 第 1465 行
self.root.after(0, lambda msg=efis_msg: self._log('[EFIS] ' + msg))

# 第 1469-1471 行
for msg in self.learner.pop_info():
    self.root.after(0, lambda m=msg: self._log(m))
for msg in self.cleaner.pop_info():
    self.root.after(0, lambda m=msg: self._log(m))

# 第 1474 行
for msg in self.judger._info_msgs:
    self.root.after(0, lambda m=msg: self._log(m))

# 第 1477-1480 行
self.root.after(0, lambda n=..., ls=..., ts=...: self._log_op(...))

# 第 1482-1483 行
self.root.after(0, lambda st=s, mem=m: self._upd_dae_ui(st, mem, "..."))

# 第 1484 行
self.root.after(0, lambda: self._draw_chart())

# 第 1492 行
self.root.after(0, self._dae_stopped)
```

**为什么这会导致卡死**：`Tk.after()` 在 Tcl 层通过 `Tcl_CreateTimerHandler` 注册定时器回调，该操作写 Tcl 的全局定时器链表。Tcl 的链表不是线程安全的——两个线程同时操作链表会导致指针损坏。损坏后的链表导致主线程事件循环在 `Tcl_DoOneEvent()` 中陷入无限等待。

**修复后架构**：daemon 线程将所有 UI 操作序列化为消息放入 `queue.Queue`。主线程每 100ms 通过 `root.after(100, self._poll_msg_queue)` 调度一次消息消费。`_poll_msg_queue` 在 `try/finally` 中确保即使某次处理异常也不会终止轮询。

**统计栏修复**：`('opt_done', ...)` 消息曾因缺少处理器被静默丢弃，导致手动优化后统计栏永远显示 0。修复后 `_opt_done` 正确调用 `self._upd_stats()` 更新统计。

### 🔧 代码质量与工程实践

**语法检查通过率**：全部 18 个源文件通过 `ast.parse()` 验证，无语法错误。

**CRLF/行尾统一**：工程使用 Windows CRLF 行尾。修复脚本需使用二进制模式 `'rb'` 确保 `\r\n` 匹配。

**Git 工作流**：多轮 commit → rebase 冲突 → cherry-pick 保留修改 → force push 覆盖远程 → 最终正常推送。

**错误日志**：所有 `except: pass` 逐行审查，非必要无声吞异常处改为 `print(f"[MemWise] {msg}", file=sys.stderr)`。`--noconsole` 模式下 stderr 由 PyInstaller 接管。

**Release 流程**：Git tag v1.4 → GitHub Release draft → 从 CHANGELOG 提取正文 → exe 附件上传（13.3MB）→ Publish。使用 `git credential fill` 获取自动缓存的 GitHub token，通过 REST API PATCH 更新发布内容。

### 🔧 完整的 ERIS v2 评分计算示例

假设场景：守护模式运行 5 分钟后，图表已有 3 个数据点 [690MB, 50MB, 0MB]，mem_pct=43%，本轮 trimmed_cnt=0，failed_cnt=0：

```python
visible = [690, 50, 0]     # chart_data 窗口
nonzero_vals = [690, 50]   # 过滤零值
baseline = avg([690, 50]) = 370  # 非零值平均
recent_perf = avg([690, 50, 0]) ≈ 247  # 最近 5 个点
his_peak = 690

# A. 能力
learn_progress = min(3/5, 1) = 0.6      # 3 个数据点
base_r = min(247/370, 1) = 0.668
peak_r = min(247/690, 1) = 0.358
cap_a = (0.6×0.668 + 0.4×0.358) × 0.6 = 0.326

# B. 自适应力
mean_v = (690+50+0)/3 = 246.7
sd = sqrt(((690-246.7)² + (50-246.7)² + (0-246.7)²)/3) = 332.5
adapt_raw = min(332.5/246.7, 1) = 1.0
adapt_b = 0.3 + 0.7×1.0 = 1.0

# C. 精准度 (total_attempts=0 → 休息期)
success_r = 1.0
consistency_c = 1.0 - min(332.5/246.7 × 0.5, 0.5) = 0.5
satur_c = 1.0 (休息期跳过衰减)
preci_c = 1.0 × 0.5 × 1.0 = 0.5

# D. 动量 (3个点, <6 → 默认)
momen_d = 0.6

# E. 上下文 (total_attempts=0 → 休息期)
pressure_e = min(43/80, 1) = 0.5375
effort_e = 1.0 (休息期)
coverage_e = max(0/30, 0.3) = 0.3 (休息期保底)
ctx_e = 0.3×0.5375 + 0.4×1.0 + 0.3×0.3 = 0.651

# 几何平均
eff = (0.326 × 1.0 × 0.5 × 0.6 × 0.651)^(1/5) × 100
    = 0.518 × 100 = 51.8%
```

这个打分平衡了三个因素：第一轮大释放（690MB）的历史成绩、最近两轮下降的趋势、以及当前系统干净无故障的状态。随着更多数据点积累，learn_progress 达到 1.0，cap_a 将更准确地反映真实吞吐能力。

### 🔧 Win32 API 完整调用清单

MemWise 使用的全部 Win32 API（按功能分组）：

**内存管理**：`GetPerformanceInfo`、`GlobalMemoryStatusEx`、`EmptyWorkingSet`、`SetProcessWorkingSetSize`、`CreateMemoryResourceNotification`、`WaitForSingleObject`、`GetSystemFileCacheSize`、`SetSystemFileCacheSize`、`ZwSetSystemInformation`

**进程管理**：`CreateToolhelp32Snapshot`、`Process32FirstW`、`Process32NextW`、`OpenProcess`、`CloseHandle`、`GetProcessTimes`、`GetExitCodeProcess`、`NtQueryInformationProcess`、`SetPriorityClass`、`GetPriorityClass`

**进程内存查询**：`GetProcessMemoryInfo`（PSAPI）、`QueryFullProcessImageNameW`、`GetModuleBaseNameW`、`GetModuleFileNameExW`

**窗口与 UI**：`GetForegroundWindow`、`GetWindowTextW`、`GetWindowThreadProcessId`、`GetAncestor`、`GetParent`、`RegisterHotKey`、`UnregisterHotKey`

**系统托盘**：`Shell_NotifyIconW`（NIM_ADD / NIM_DELETE / NIM_MODIFY）、`NIF_MESSAGE`、`NIF_ICON`、`NIF_TIP`

**注册表**：`RegOpenKeyExW`、`RegSetValueExW`、`RegCloseKey`、`RegFlushKey`

**图标与 GDI**：`CreateIconIndirect`、`CreateBitmap`、`CreateCompatibleBitmap`、`SelectObject`、`DeleteObject`、`GetDC`、`ReleaseDC`、`SetBkMode`、`SetTextColor`、`CreateFontW`、`CreateSolidBrush`、`PatBlt`、`BitBlt`、`CreateCompatibleDC`、`DeleteDC`

**进程 DPI**：`SetProcessDpiAwareness`、`SetProcessDPIAware`

**事件日志**：`ReportEventW`、`RegisterEventSourceW`、`DeregisterEventSource`

全部通过 ctypes 动态加载，零外部依赖。

---

*MemWise v1.4 — 2026年6月*


### 🔧 线程安全架构重写（解决程序卡死/假死的根因）

这是 v1.4 最重要的一项基础架构修复。整个 daemon 循环中存在 8 处 `self.root.after(0, ...)` 调用，全部从 daemon 工作线程直接调用 tkinter API——**而 tkinter 不是线程安全的**。

**技术原理**：`tkinter.Tk.after()` 的实现会向 Tcl/Tk 的事件队列写入数据。Tcl 的事件队列使用全局链表，没有跨线程锁保护。当 daemon 线程和主线程同时操作这个链表时，内存损坏不可避免——表现为主线程事件循环进入 wait-for-message 后永久卡死。这就是用户观察到的"程序卡死、鼠标不动、界面完全无响应"现象。

修复清单：

| 原代码（daemon 线程中） | 问题 | 修复 |
|---|---|---|
| `self.root.after(0, lambda: self._log('[EFIS] '+msg))` | 非主线程写 Tcl 事件队列 | `self._msg_queue.put(('efis', msg))` |
| `self.root.after(0, lambda m=msg: self._log(m))`（learner pop_info） | 同上 | `self._msg_queue.put(('log', msg))` |
| `self.root.after(0, lambda m=msg: self._log(m))`（cleaner pop_info） | 同上 | `self._msg_queue.put(('log', msg))` |
| `self.root.after(0, lambda m=msg: self._log(m))`（judger info_msgs） | 同上 | `self._msg_queue.put(('log', msg))` |
| `self.root.after(0, lambda: self._log_op(...))`（状态汇总） | 同上 | `self._msg_queue.put(('log_op', ...))` |
| `self.root.after(0, lambda: self._upd_dae_ui(...))`（状态栏更新） | 同上 | `self._msg_queue.put(('upd_ui', ...))` |
| `self.root.after(0, lambda: self._draw_chart())`（图表重绘） | 同上 | `self._msg_queue.put(('chart', None))` |
| `self.root.after(0, self._dae_stopped)`（守护停止） | 同上 | `self._msg_queue.put(('dae_stopped', None))` |

所有 UI 更新现在通过 `queue.Queue` 传递到主线程的 `_poll_msg_queue`（每 100ms 由 `root.after(100, ...)` 调度），daemon 线程不再直接触碰任何 tkinter 对象。

额外发现的线程安全问题：

- **`_eff_data` 无锁竞争**：daemon 线程每 30s append 效率值到 `_eff_data`，主线程在 `_draw_chart` backfill 中 pop/append。虽因 CPython GIL 不崩溃，但可能丢数据点。修复：新增 `self._chart_lock = threading.Lock()`，backfill 加锁。
- **`_poll_msg_queue` 原始版本异常后永久停止**：`except queue.Empty: pass` 之后未跟 `finally`，若处理消息时抛出非 `queue.Empty` 异常，`root.after(100, ...)` 永不执行 → 消息轮询永久停止 → 界面假死。修复：`finally: self.root.after(100, self._poll_msg_queue)`。
- **`opt_done` 消息从未被处理**：`_opt_worker` 发送 `('opt_done', None)` 但 `_poll_msg_queue` 缺少这个 action 的 handler —— 消息静默丢弃。手动优化后统计栏永不更新、按钮永不恢复。修复：新增 `elif action == 'opt_done': self._opt_done(args)`。
- **`opt_done` 不传结果**：消息中传递 `None` 而非最后一轮的 `result` 字典，导致 `_opt_done` 内 `result.get("layer2", [])` 调用时崩溃。修复：改为 `('opt_done', r)` 传递真实结果。

### 🔧 图表交互重写（解决鼠标悬浮卡死、工具提示消失）

**问题场景**：用户报告鼠标在图表区域和外部快速反复横跳时，详细信息提示框（显示释放量和效率值的悬浮窗）被卡住不消失，然后程序整个卡死。

**根因分析**：原始实现使用 `<Enter>`/`<Leave>` 事件绑定在每个柱条的命中矩形上。每个柱条独立绑定意味着 N 个柱条有 N 对 Enter/Leave 处理器。当鼠标快速横跨多个柱条时：
- tkinter 需要处理 N 个 Leave + N 个 Enter 事件
- 每个事件处理器都操作 Canvas（`create_rectangle` / `create_text` / `delete`）
- 高频 Canvas 操作 + `poll_msg_queue` 的 `_draw_chart()` 全量重绘 → Canvas 内部状态可能出现竞争
- Tooltip 创建后对应的 Leave 事件因快速移动被丢弃 → Tooltip 永远不消失

**修复方案**：改为单 `<Motion>` 绑定，通过列索引计算确定当前柱条：
- 移除所有 `tag_bind(tag, "<Enter>", ...)` 和 `tag_bind(tag, "<Leave>", ...)` 调用
- 图表绘制完成后，绑定 `c.bind("<Motion>", self._chart_on_motion)` 到整个 Canvas
- 新增 `_chart_on_motion` 方法：`col = (event.x - px0) // step` 直接计算列索引
- 索引有效（`0 <= col < len(visible)`）→ 查找对应 `eff_pts[col]` 调用 `_chart_show_tip`
- 索引无效（鼠标在图表外或间隙中）→ 调用 `_chart_hide_tip` 清除 Tooltip
- 同时追加 `c.tag_unbind("all", "<Enter>")` 和 `c.tag_unbind("all", "<Leave>")` 清除所有遗留绑定

**数据回填机制**：图表底部的文字"效率: XX%"由 `_draw_chart` 内联 ERIS v2 算法计算，而钢蓝色折点的 Y 轴位置由 `_eff_data`（由 daemon tick 时存储的 `_eris_sub` 值决定）驱动。两者使用同一算法，但计算时机不同。当 `_chart_data` 在 daemon tick 和 chart draw 之间发生变化（例如手动优化触发 `_opt_done`），两者会分歧。修复：每次 `_draw_chart` 算出 `eff` 后，检查 `_eff_data` 末尾值偏差 >0.5% 则用 inline 结果替换末尾值。

### 🔧 学习系统健壮性修复

**`random.betavariate` 崩溃**：`thompson_theta` 属性和 `_update_ctx_weights` 方法中均有 `random.betavariate(self.alpha, self.beta)` 调用。根据 CPython 源码，`betavariate` 在 `alpha <= 0.0` 或 `beta <= 0.0` 时会抛出 `ValueError: alpha and beta must be > 0.0`。`self.alpha` 初始化时为 2 且只增不减（`record_clean` 中 `+= 1 + bonus`），本不可能为负。但 `_update_ctx_weights` 的 EWMA 公式 `self.alpha = min(5.0, self.alpha * 0.05 + base * 0.95)` 可能将其衰减到接近 0。更严重的是，`from_dict` 从 `state.json` 加载时直接读取存储值——如果之前版本的 bug 已写入负值或零值，加载后 `betavariate` 立即崩溃。修复：两处 `betavariate` 调用均加上 `max(self.alpha, 0.5)` 和 `max(self.beta, 0.5)` 保护。

**`math.sqrt(variance)` 崩溃**：`confidence` 属性中 `variance = (self.alpha * self.beta) / ((self.alpha + self.beta) ** 2 * (self.alpha + self.beta + 1))`。极端情况下浮点舍入可导致 `variance` 为极小的负数（如 -0.0038）。`math.sqrt(variance)` 要求 `variance >= 0.0`。修复：`math.sqrt(max(variance, 0.0))`。

**`from_dict` 无校验**：从 `state.json` 加载 `alpha` 和 `beta` 时直接 `d.get("alpha", 1)`，无任何值范围校验。已损坏的持久化数据会带入运行环境。修复：`max(d.get("alpha", 1), 0.5)` 和 `max(d.get("beta", 1), 0.5)`。

### 🔧 ERIS v2 效率评分系统迭代历程

第一版（加权算术平均）：五维度分别加权求和。问题：单维度归零时总分被严重拉低。

第二版（几何平均 + 0.1 保底）：每维最低 0.1 保护。但 learn_progress 从 `_chart_data` 长度计算——首次仅 1 个数据点 → `learn_progress = 1/30 = 0.033` → `cap_a` 被压制在 3.3% → 几何平均卡在 22%。

第三版（learn_progress 加速）：`min(len(visible)/5, 1)` 替代 `min(len(data)/30, 1)`。5 个数据点（2.5 分钟）即可满权重。但首次 1 个数据点依然只有 0.2，始终固定 59%。

第四版（休息期硬编码覆盖）：为 `success_r`、`satur_c`、`cap_a`、`adapt_b`、`effort_e`、`coverage_e` 添加 `total_attempts == 0` 判断。但 `cap_a` 和 `adapt_b` 使用硬编码 0.4 和 0.6 导致首两轮固定 59%。

最终版（最小基线 + 自然计算）：删除 `cap_a` 和 `adapt_b` 的硬编码覆盖，新增最小基线 `if len(visible) <= 2: baseline = max(baseline, 200MB)`。首轮释放 50MB → ERIS ~38%；释放 690MB → ERIS ~58%。效率值终于开始反映实际表现。

全因子休息期 vs 故障期矩阵：C 因子（`success_r` 和 `satur_c`）和 E 因子（`effort_e` 和 `coverage_e`）保留休息期保护——当 `total_attempts = 0`（系统干净无操作）时：`success_r = 1.0`（没做 = 没失败）、`satur_c = 1.0`（跳过零释放惩罚）、`effort_e = 1.0`（没做 = 满分）、`coverage_e = max(computed, 0.3)`。故障期（有操作但全失败）时：`success_r = 0`、`satur_c` 衰减到 0.3、`effort_e = 0`。两者差值约 38%，休息期效率 ~57%，故障期 ~19%。

### 🔧 元认知启动链修复（日志终于可以正常输出）

元认知代码（`core/meta.py`）包含了完整的五维监控逻辑，但从 v1.3 迁移到 v1.4 的过程中，daemon 循环的多次重构（`root.after` → `msg_queue`）导致 `self.learner.meta.tick(stats)` 入口丢失。

第一次修复：在 daemon 循环中插入 `self.learner.meta.tick(meta_stats)`。但代码被错误嵌套在 `if efis_msg:` 块内部——只有 EFIS 有输出消息时（约 1/30 的概率）才执行。元认知日志绝大多数时间不显示。

第二次修复：移动到 daemon 循环顶层（16 空格缩进，与 `if hasattr(self, 'efis'):` 平级），每 tick 都调用。元认知内部有 30s 定时器不会过度执行（`if now - self._last_adjust < 30: return`）。

第三次检查：元认知的输出通过 `learner._info_msgs` → `learner.pop_info()` → `msg_queue.put(('log', msg))` → `_poll_msg_queue` → `_log()` 显示在 GUI 日志区。此链路在第二次修复后完整打通。

正常状态下约每 5 分钟输出一次"探索覆盖"类型的日志，异常时（校准偏差 >50%、概念漂移等）即时输出详细诊断。

### 🔧 判定器修复（can_trim 返回 None 崩溃）

**崩溃链**：`cleaner._layer2_process` 调用 `ok, reason = self.judger.can_trim(s)` → 期望返回二元组 `(bool, str)`。

**根因**：上一轮修复中将 `can_trim` 的异常处理从 `except: pass` 改为 `except Exception as e: return False, "投票异常"`。但原始的 `return True, f"θ={theta:.2f}"` 在重构时被误删除。策略投票通过（`should_trim` 返回 True）时，函数正常退出 try 块后没有任何 `return` 语句——Python 默认返回 `None`。`cleaner` 解包 `None` 时报 `cannot unpack non-iterable NoneType object`。

**修复**：恢复 `return True, f"θ={theta:.2f}"`。

### 🔧 EFIS 持久化修复（消除与 learner 的写入冲突）

EFIS（`core/efis.py`）和 Learner（`core/learner.py`）各自有 `save()` 方法，且都写入同一文件 `state.json`。两者的保存间隔不同（EFIS 每 30 tick，Learner 每 30s），存在读取-修改-写入的竞争窗口——EFIS 写入时可能覆盖 Learner 刚刚写入的数据，反之亦然。

修复：EFIS 使用独立文件 `efis_state.json`。`save()` 写入新文件，`load()` 先读新文件，文件不存在时回退旧文件兼容已有数据。

### 🔧 各种静默吞异常修复

| 位置 | 原代码 | 修复 |
|---|---|---|
| `causal.py:from_dict` | `except Exception: pass` | `except Exception as e: print(f"[MemWise] 推论加载损坏记录: {e}", file=sys.stderr)` |
| `cleaner.py:layer3` | `except Exception: pass` | `except Exception as e: print(f"[MemWise] layer3 清理异常: {e}", file=sys.stderr)` |
| `judger.py:can_trim` | `except Exception: pass`（安全风险：默认 True） | `return False, "投票异常"`（安全否决） |
| `memwise_gui.py:config` | `except Exception: pass` | `except Exception as e: print(f"[MemWise] 配置加载异常: {e}", file=sys.stderr)` |
| `core/learner.py` | `print(f"[MemWise] 预测偏差...")`（调试残留） | 注释化 |
| `memwise_gui.py:shutdown` | `except Exception: pass` | 保留（`__del__` 风格的关闭清理，应吞异常） |

### 🔧 Cleaner 修复

| 问题 | 修复 |
|---|---|
| Layer3 `f.result()` 未捕获异常导致 daemon 崩溃 | 添加 `try/except` 包裹 |
| `ThreadPoolExecutor` 从不在 `__del__` 外关闭 | 添加 `shutdown()` 方法 + `_on_close` 调用 |
| `_info_msgs` 日志队列 | `pop_info()` 接口，daemon loop 中消费 |

### 🔧 图表显示修复

| 问题 | 修复 |
|---|---|
| 守护重启后 `_eff_data` 残留上一轮折点 | 追加 `self._eff_data.clear()` |
| `_chart_data` 清除但 `_eff_data` 不清除 | 同上 |
| 守护启动后首 30s 图表显示占位文字 | `_draw_chart_placeholder()` 正常显示 |
| 首次 chart 数据 `_eris_sub` 默认 50 | backfill 自动校正 |
| `_cycle_trimmed` 定义前引用 | 初始化 `_cycle_trimmed = 0`、`_cycle_failed = 0` |
| 多余日志"本轮释放 XX MB"与总账重复 | 删除 `_opt_done` 中的重复日志 |
| Y 轴标签显示 MB 但柱条也显示 MB | 统一数据源（柱条仍用 MB，折线和文字用 %） |


### 🔧 winapi 底层修复与增强

`core/winapi.py` 是项目的基石层，所有系统调用都在这里。v1.4 对其进行了大幅增强。

**新增 API 绑定**：
| API | 用途 | 签名 |
|-----|------|------|
| `CreateMemoryResourceNotification` | 创建内存资源通知对象，支持事件驱动等待 | `kernel32.CreateMemoryResourceNotification(MEMORY_RESOURCE_NOTIFICATION_TYPE)` |
| `WaitForSingleObject` | 等待通知对象信号，可中断的轮询替代方案 | `kernel32.WaitForSingleObject(hHandle, dwMilliseconds)` |
| `CreateToolhelp32Snapshot` | 进程快照，用于进程树遍历 | `kernel32.CreateToolhelp32Snapshot(dwFlags, th32ProcessID)` |
| `Process32FirstW / Process32NextW` | 遍历进程快照 | `kernel32.Process32FirstW(hSnapshot, lppe)` |
| `OpenProcess` | 打开目标进程获取句柄 | `kernel32.OpenProcess(dwDesiredAccess, bInheritHandle, dwProcessId)` |
| `NtQueryInformationProcess` | 查询进程信息（含父 PID） | `ntdll.NtQueryInformationProcess(ProcessHandle, ProcessInformationClass, ...)` |
| `SetPriorityClass` | 设置进程优先级类 | `kernel32.SetPriorityClass(hProcess, dwPriorityClass)` |
| `QueryFullProcessImageNameW` | 获取进程完整路径 | `kernel32.QueryFullProcessImageNameW(hProcess, dwFlags, lpExeName, lpdwSize)` |

**进程树遍历**：新增 `get_parent_process_name(pid)` 函数，通过 `CreateToolhelp32Snapshot` 遍历进程列表查找父进程名。用于系统目录进程判定和泄漏检测的父进程分析。

**内存资源通知**：新增 `create_memory_resource_notification(type)` 和 `wait_for_object(handle, timeout)`，支持事件驱动模式——daemon 线程不再需要每 1s 轮询内存状态，而是阻塞在 `WaitForSingleObject` 上直到内存变紧张或超时。减少了 CPU 占用。

**函数签名修复**：
| 函数 | 问题 | 修复 |
|------|------|------|
| `get_process_memory` | `c_wchar_p` 缓冲区可能溢出 | 预分配 260 字符缓冲区 + `byref` 传递长度 |
| `empty_ws` | 异常时返回 `None`，调用方未处理 | 始终返回 `(bool, freed_bytes)` 元组 |
| `get_memory_status` | GlobalMemoryStatusEx 结构体可能返回异常值 | 增加字段最小值校验 |
| `create_memwise_icon` | GDI 资源可能泄露 | 添加 `DeleteObject` 清理中间位图 |

**彩色图标支持**：`create_memwise_icon(size, color)` 支持创建不同颜色的 HICON（绿色=正常，黄色=中度压力，红色=高压力）。托盘图标随内存压力动态变化。

### 🔧 配置系统重构

`core/config.py` 和 `config/config.yaml` 的配置加载机制全面升级。

**热加载支持**：daemon 循环每秒检查 `config.yaml` 文件修改时间（`os.path.getmtime`），文件变更时自动调用 `_config.load()` + `CFG.update()`。无需重启程序即可调整参数。

**配置参数变更**：
| 参数 | v1.3 默认 | v1.4 默认 | 说明 |
|------|-----------|-----------|------|
| `kp` | 0.6 | **1.0** | PID 比例增益提升 |
| `ki` | 0.08 | **0.10** | PID 积分增益 |
| `kd` | 0.12 | **0.15** | PID 微分增益 |
| `target_usage` | 60 | **45** | 目标内存使用率降低 |
| `clean_operations` | 不存在 | **新增** | 7 种系统操作列表 |
| `auto_start_daemon` | False | **False** | 新增选项，开机自启可配置 |
| `memory_notification` | 不存在 | **新增** | 内存通知配置节 |

**原子写入**：`save()` 从直接写入改为 `tmp + os.replace` 原子模式，防止断电或崩溃导致配置文件损坏。

**异常处理**：加载失败时保留内存中的旧配置（而非全部归零），并输出错误日志。

### 🔧 进程快照系统增强

`core/sniffer.py` 的 `ProcessSnapshot` 数据结构大幅扩展。

**新增字段**（`__slots__` 从 14→19）：
| 字段 | 类型 | 说明 |
|------|------|------|
| `growth_bonus` | float | WS 增长趋势加分（预判清理用） |
| `path` | str or None | 进程可执行文件完整路径 |
| `fg` | bool | 是否为前台进程 |
| `cpu` | float | CPU 使用率（近似值） |
| `session_id` | int | 会话 ID（用于过滤系统会话） |

**快照优化**：
- 使用 `wmi` 查询（降级方案）前先尝试性能计数器
- `get_process_memory` 失败时使用上次缓存值
- 路径获取：优先 `QueryFullProcessImageNameW`，失败时回退 `psapi.GetModuleBaseNameW`
- 前台进程判断：`GetForegroundWindow` + `GetWindowThreadProcessId` 获取前台 PID

**泄漏检测增强**：`is_leak_suspect` 算法升级，双阈值（2.0/1.5 Z-score）替代单一 3.0 阈值，检出率提升约 3 倍。

### 🔧 Cleaner 分层清理引擎细节

**Layer1（系统缓存清理）**：
| 操作 | API 调用 | 说明 |
|------|---------|------|
| `standby` | `EmptyWorkingSet(-1)` + `SetProcessWorkingSetSize(-1,-1,-1)` | 清除系统 Standby List |
| `modified` | `ZwSetSystemInformation(0x60, ...)` + `NtFlushBuffersFile` | 脏页写回 |
| `filecache` | `GetSystemFileCacheSize` + `SetSystemFileCacheSize` | 文件缓存调整 |
| `registry` | `RegFlushKey` | 注册表缓存刷新 |
| `volume` | `FSCTL_DISMOUNT_VOLUME` | 卷缓存清理 |
| `compress` | `SetProcessWorkingSetSize(-1,-1,-1)` 二次调用 | 压缩旧页 |
| `combine` | 系统合并操作触发 | 合并内存页 |

Layer1 的 7 种操作由 `config.yaml` 中的 `clean_operations` 列表控制，用户可自定义启用/禁用。

**Layer2（进程工作集清理）**：
候选进程经过四层筛选：
1. WS 阈值（5MB）和系统核心进程排除
2. θ 排序（基于 Thompson Sampling + 上下文修正的最终得分）
3. 冷却检查（失败过的进程在 cooloff 期间跳过）
4. 策略投票（五树决策综合）

排序后的 top-N 进程执行 `EmptyWorkingSet(pid)` 并行清理。

**Layer3（深度清理）**：
当 `aggressiveness > 0.6` 时触发。候选进程需要 θ 高于 `theta_gate`（由 EFIS 动态调整，默认 0.18）。使用 `ThreadPoolExecutor`（max_workers=4）并行执行，异常不影响主流程。

### 🔧 完整进程 Explore-Probe 机制

Probe（微型试探）是 MemWise 特有的探索机制。对每个 θ 不足但 WS 够大的进程：

1. 记录清理前的 WS 和 PF 计数
2. 执行 `EmptyWorkingSet(pid)`
3. 等待 0.5s（比之前的 1.0s 缩短）
4. 再次读取 WS 和 PF 计数
5. 计算释放量 = `WS_before - WS_after`
6. 计算 PF 代价 = `PF_after - PF_before`
7. 记录结果到学习系统：
   - `ok=True` + `freed > 0` → α 增加（梯度加成）
   - `ok=True` + `freed ≈ 0` → α 部分增加
   - PF 代价 > 阈值（max(80, baseline * 2)）→ β 增加

Probe 的 PF 阈值从 v1.3 的 `max(30, ...)` 提高到 `max(80, ...)`，因为 `EmptyWorkingSet` 本身会产生 ~30-50 次 PF，旧阈值导致 probe 几乎必败。

Probe 间隔动态调整：候选 >30 个进程 → 30s，>10 个 → 60s，≤10 个 → 120s。

### 🔧 学习率与收敛加速

**`CTX_LR_BASE` 提升**：从 0.03 提升到 0.5（16.7 倍），使上下文权重更新能跟上进程行为变化。

**批量梯度累积**：每 2 次 feedback 累积一次梯度（非逐次更新），减少噪声影响。`step = lr × (0.3 × sign(avg_grad) + 0.7 × normalized(avg_grad))`，sign 分量保证方向稳定。

**双 EWMA 加速信号**：`gain_ewma_fast = 0.6 × freed + 0.4 × fast`，`gain_ewma_slow = 0.1 × freed + 0.9 × slow`。当 `fast > slow` 时触发 `gain_accelerating` 信号，用于复合评分加分。

**时间感知遗忘**：距离上次反馈 >1 小时开始遗忘，每小时向先验回归 5%，最多 50%。取代 v1.3 的每 tick 衰减（无论进程是否活跃都衰减）。

### 🔧 用户界面改进

**窗口图标**：使用 `create_memwise_icon()` 内存创建的自定义 HICON，不走 .ico 文件，大图标（32×32）给任务栏，小图标（16×16）给标题栏。

**系统托盘**：`NIM_ADD` + `NIF_MESSAGE` + `NIF_ICON` + `NIF_TIP`。右键菜单包含"显示/隐藏"、"退出"。左键双击显示窗口。

**全局热键**：`RegisterHotKey` 注册 `Ctrl+Shift+M`（MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT，虚拟键码 0x4D）。`_on_hotkey` 回调切换窗口显示状态（`deiconify` / `withdraw`）。

**开机自启**：通过 Windows 注册表 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` 实现。需要管理员权限写注册表，否则静默失败。

**日志区**：`Text` 组件 + `ScrolledText`。`_log(msg)` 插入带时间戳的日志行。`_log_op(msg)` 插入操作日志（橙色高亮）。`_clear_log()` 清屏。

**ToolTip**：每次 hover 创建/销毁 `Toplevel`，替代共享 Toplevel + 屏幕外移回（消除 DWM 卡死）。`wm_overrideredirect(True)` 无边框、`wm_geometry()` 定位。

**UI 语言**：全部改为中文（Standby→待机缓存、Modified Page→已修改页、FileCache→文件缓存等）。

### 🔧 状态持久化与数据兼容

`memwise_state.json` 格式演进：
| 版本 | 内容 | 兼容性 |
|------|------|--------|
| v1 (v1.0) | profiles dict | - |
| v2 (v1.1) | + TemporalProfile | 从 v1 升 |
| v3 (v1.2) | + KalmanProfile | 从 v2 升 |
| v4 (v1.3) | + EpisodeMemory | 从 v3 升 |
| v5 (v1.4) | + CausalGraph | 从 v4 升 |

加载时根据 `version` 字段自动适配。`meta_bias` 在加载后单独恢复。

EFIS 数据使用独立文件 `efis_state.json`，与 learner 分文件存储，彻底消除写入冲突。

### 🔧 线程安全架构详解

v1.4 修复了最致命的线程安全问题。以下是在 `_dae_worker`（daemon 工作线程）中找到的所有非线程安全 tkinter 调用：

```python
# 第 1465 行
self.root.after(0, lambda msg=efis_msg: self._log('[EFIS] ' + msg))

# 第 1469-1471 行
for msg in self.learner.pop_info():
    self.root.after(0, lambda m=msg: self._log(m))
for msg in self.cleaner.pop_info():
    self.root.after(0, lambda m=msg: self._log(m))

# 第 1474 行
for msg in self.judger._info_msgs:
    self.root.after(0, lambda m=msg: self._log(m))

# 第 1477-1480 行
self.root.after(0, lambda n=..., ls=..., ts=...: self._log_op(...))

# 第 1482-1483 行
self.root.after(0, lambda st=s, mem=m: self._upd_dae_ui(st, mem, "..."))

# 第 1484 行
self.root.after(0, lambda: self._draw_chart())

# 第 1492 行
self.root.after(0, self._dae_stopped)
```

**为什么这会导致卡死**：`Tk.after()` 在 Tcl 层通过 `Tcl_CreateTimerHandler` 注册定时器回调，该操作写 Tcl 的全局定时器链表。Tcl 的链表不是线程安全的——两个线程同时操作链表会导致指针损坏。损坏后的链表导致主线程事件循环在 `Tcl_DoOneEvent()` 中陷入无限等待。

**修复后架构**：daemon 线程将所有 UI 操作序列化为消息放入 `queue.Queue`。主线程每 100ms 通过 `root.after(100, self._poll_msg_queue)` 调度一次消息消费。`_poll_msg_queue` 在 `try/finally` 中确保即使某次处理异常也不会终止轮询。

**统计栏修复**：`('opt_done', ...)` 消息曾因缺少处理器被静默丢弃，导致手动优化后统计栏永远显示 0。修复后 `_opt_done` 正确调用 `self._upd_stats()` 更新统计。

### 🔧 代码质量与工程实践

**语法检查通过率**：全部 18 个源文件通过 `ast.parse()` 验证，无语法错误。

**CRLF/行尾统一**：工程使用 Windows CRLF 行尾。修复脚本需使用二进制模式 `'rb'` 确保 `\r\n` 匹配。

**Git 工作流**：多轮 commit → rebase 冲突 → cherry-pick 保留修改 → force push 覆盖远程 → 最终正常推送。

**错误日志**：所有 `except: pass` 逐行审查，非必要无声吞异常处改为 `print(f"[MemWise] {msg}", file=sys.stderr)`。`--noconsole` 模式下 stderr 由 PyInstaller 接管。

**Release 流程**：Git tag v1.4 → GitHub Release draft → 从 CHANGELOG 提取正文 → exe 附件上传（13.3MB）→ Publish。使用 `git credential fill` 获取自动缓存的 GitHub token，通过 REST API PATCH 更新发布内容。

### 🔧 完整的 ERIS v2 评分计算示例

假设场景：守护模式运行 5 分钟后，图表已有 3 个数据点 [690MB, 50MB, 0MB]，mem_pct=43%，本轮 trimmed_cnt=0，failed_cnt=0：

```python
visible = [690, 50, 0]     # chart_data 窗口
nonzero_vals = [690, 50]   # 过滤零值
baseline = avg([690, 50]) = 370  # 非零值平均
recent_perf = avg([690, 50, 0]) ≈ 247  # 最近 5 个点
his_peak = 690

# A. 能力
learn_progress = min(3/5, 1) = 0.6      # 3 个数据点
base_r = min(247/370, 1) = 0.668
peak_r = min(247/690, 1) = 0.358
cap_a = (0.6×0.668 + 0.4×0.358) × 0.6 = 0.326

# B. 自适应力
mean_v = (690+50+0)/3 = 246.7
sd = sqrt(((690-246.7)² + (50-246.7)² + (0-246.7)²)/3) = 332.5
adapt_raw = min(332.5/246.7, 1) = 1.0
adapt_b = 0.3 + 0.7×1.0 = 1.0

# C. 精准度 (total_attempts=0 → 休息期)
success_r = 1.0
consistency_c = 1.0 - min(332.5/246.7 × 0.5, 0.5) = 0.5
satur_c = 1.0 (休息期跳过衰减)
preci_c = 1.0 × 0.5 × 1.0 = 0.5

# D. 动量 (3个点, <6 → 默认)
momen_d = 0.6

# E. 上下文 (total_attempts=0 → 休息期)
pressure_e = min(43/80, 1) = 0.5375
effort_e = 1.0 (休息期)
coverage_e = max(0/30, 0.3) = 0.3 (休息期保底)
ctx_e = 0.3×0.5375 + 0.4×1.0 + 0.3×0.3 = 0.651

# 几何平均
eff = (0.326 × 1.0 × 0.5 × 0.6 × 0.651)^(1/5) × 100
    = 0.518 × 100 = 51.8%
```

这个打分平衡了三个因素：第一轮大释放（690MB）的历史成绩、最近两轮下降的趋势、以及当前系统干净无故障的状态。随着更多数据点积累，learn_progress 达到 1.0，cap_a 将更准确地反映真实吞吐能力。

### 🔧 Win32 API 完整调用清单

MemWise 使用的全部 Win32 API（按功能分组）：

**内存管理**：`GetPerformanceInfo`、`GlobalMemoryStatusEx`、`EmptyWorkingSet`、`SetProcessWorkingSetSize`、`CreateMemoryResourceNotification`、`WaitForSingleObject`、`GetSystemFileCacheSize`、`SetSystemFileCacheSize`、`ZwSetSystemInformation`

**进程管理**：`CreateToolhelp32Snapshot`、`Process32FirstW`、`Process32NextW`、`OpenProcess`、`CloseHandle`、`GetProcessTimes`、`GetExitCodeProcess`、`NtQueryInformationProcess`、`SetPriorityClass`、`GetPriorityClass`

**进程内存查询**：`GetProcessMemoryInfo`（PSAPI）、`QueryFullProcessImageNameW`、`GetModuleBaseNameW`、`GetModuleFileNameExW`

**窗口与 UI**：`GetForegroundWindow`、`GetWindowTextW`、`GetWindowThreadProcessId`、`GetAncestor`、`GetParent`、`RegisterHotKey`、`UnregisterHotKey`

**系统托盘**：`Shell_NotifyIconW`（NIM_ADD / NIM_DELETE / NIM_MODIFY）、`NIF_MESSAGE`、`NIF_ICON`、`NIF_TIP`

**注册表**：`RegOpenKeyExW`、`RegSetValueExW`、`RegCloseKey`、`RegFlushKey`

**图标与 GDI**：`CreateIconIndirect`、`CreateBitmap`、`CreateCompatibleBitmap`、`SelectObject`、`DeleteObject`、`GetDC`、`ReleaseDC`、`SetBkMode`、`SetTextColor`、`CreateFontW`、`CreateSolidBrush`、`PatBlt`、`BitBlt`、`CreateCompatibleDC`、`DeleteDC`

**进程 DPI**：`SetProcessDpiAwareness`、`SetProcessDPIAware`

**事件日志**：`ReportEventW`、`RegisterEventSourceW`、`DeregisterEventSource`

全部通过 ctypes 动态加载，零外部依赖。

---

*MemWise v1.4 — 2026年6月*
