# MemWise 更新日志

> **MemWise** — Windows 智能内存看护工具。不杀进程、不挂起线程、不注入、不联网。
> 纯 ctypes Win32 API，零外部依赖。

---

## v1.6 (2026年7月 — 当前)

> 优化引擎架构级重构 + 全系统 Bug 修复 + UI/UX 全面升级。从"周期性单次 optimize+休眠"进化为"60s 周期内自适应 gap 多次 optimize + gap fill 持续满载"的终极架构，搭配 EFIS v3 全程序智能调优大脑。累计修复 Bug 35+，新增/重构功能 60+，涉及全部核心模块，修改行数超过 2000。

### 🔥 持续优化引擎（架构级重构）

**从"等-清-等"到"满载持续"**。`_dae_worker` 内新增死线循环（`deadline = now + interval - 3`），在到达死线之前反复执行 `optimize()`。死线设于周期开始时固定一次，不随压力动态重设，确保每轮准时输出日志/图表。

**自适应 gap**（`memwise_gui.py` 守护循环内）：每轮 `optimize()` 完毕后获取 `realse / trimmed` 比值，对比上一轮同指标。上升 >30% 说明回填快→gap 缩短 2s（最少 8s），下降 >30% 说明回填慢→gap 拉长 3s（最多 25s）。gap 期间执行压缩+脏页写回+快照刷新，不碰 standby，留给下轮 `optimize()` 收割。默认 gap=15s。

**gap fill**：新增 `_layer1_light(aggressiveness)` 方法（`cleaner.py` L187-202）。仅调用 `trigger_memory_compression()` + `clean_modified_pages()`，压入 `stats["compress"]` 和 `stats["freed_bytes"]`。不调 `clean_standby` / `clean_deep_standby`，防止频繁清空 standby 导致压缩无物可压。每轮 gap fill 伴随快照刷新（`sniffer.snapshot()`）和压力更新（`judger.update_pressure()`）。

**快车道系统**（`cleaner.py` L173-178 `quick_retrim` + `_layer2_process` L488-494 `_fast_track`）：`_layer2_process` 在排序前遍历候选进程，将 `refill_ewma > 500KB/s` 的 PID 记录到 `self._fast_track`。gap fill 期间每轮取出最多 10 个 PID 调用 `quick_retrim(pid)`——单次 `empty_ws` + 0.1s 等待 + ws 前后测量差值记入 `freed_bytes`。进程失效时从 `_fast_track` 移除。

**深度压缩**（`winapi.py` L514-545 `deep_compress`）：替代原 `trigger_memory_compression` 单次调用的 4 轮递进序列——flush(2)→compress(6)→standby(4)→compress(6)，每轮 0.3s 间隔。`_progressive_compress` 调用 `deep_compress`，仅在主 pass 的 `_layer1_system` 和末轮 `_layer3_deep` 中触发。gap fill 的 `_layer1_light` 使用快速单次压缩（直接调 `trigger_memory_compression`），不与 standby 竞争。

### 📊 数据收集与统计（全量标量累加）

**进程退出**：`_trim_process` 中 `mem is None` 分支原来 `freed=0`（`ws_before` 被丢弃）。改为 `freed=ws_before`，同时 `learner.record_clean_result` 传入 `freed=ws_before`。进程退出时整份工作集被 OS 回收的量全数计入。

**Layer1 系统释放**：`_layer1_system` 开头 `mem_pre_sys = winapi.get_memory_status()`，standby 收割后 `mem_post_sys`，`sys_freed = post.avail - pre.avail`，正数记入 `freed_bytes`。`_layer1_light` 同样以 `avail` 差值计入。系统缓存（standby/modified/compress/filecache/volume/registry/combine）全部纳入。

**gap fill 计数**：`_layer1_light` 中 `stats["compress"]` 递增，解决 gap fill 压缩"做了但没计数"的问题。

**`quick_retrim` 计数**：通过 `mem_pre.ws - mem_post.ws` 差值记入 `freed_bytes`。

**总原则**：`freed_bytes` 是纯标量（只增不减），所有入口均有 `max(0, ...)` 保护，回弹不扣分。`cycle_freed` = `cur_freed_mb - prev_freed_mb`，精确等于 60s 窗口内所有 sub-pass + gap fill + 快车道的总释放量。

### 🔥 优化参数全局放松（使更多进程可被清理）

| 参数 | 旧值 | 新值 | 文件/位置 |
|------|:----:|:----:|------|
| θ 门槛 | 0.18 门槛阻止 | **完全移除** | `judger.py` can_trim L191-195 |
| 策略投票门槛 | ≥1 | **≥0** | `policy.py` should_trim L74 |
| 卡尔曼 Tree 低分 | 得分 −1 | **0（中性）** | `policy.py` L17-18 |
| 冷却乘数 | 8（最长 48min） | **2（最长 12min）** | `judger.py` mark_failed L238 |
| 系统路径 θ 门槛 | θ<0.6 | **θ<0.3** | `judger.py` can_trim L164 |
| 积极性惩罚门槛 | mem<40% | **mem<30%** | `policy.py` L42 |
| min_ws | 5MB | **1MB** | `judger.py` L134 |
| WS 基线 | `snap.ws < baseline * 1.05` | **`snap.ws <= baseline`**（任何增长即允许）| `judger.py` L142 |
| PF 地板 | 50 | **120** | `judger.py` check_feedback L252 |
| per-pass PF | 40 | **60** | 同上 |
| Pass 数（大/中/小） | 3/2/1 | **4/3/2**（恢复旧版）| `cleaner.py` _trim_process L270-276 |
| total_wait（大/中/小） | 1.5/1.0/0.3s | **1.0/0.6/0.3s** | 同上 |

**内存优先级**（`cleaner.py` L421-443）：从仅 `θ >= 0.3` 的进程设 LOW → **所有非系统、非前台进程均设 LOW**。`θ >= 0.3` 设 VERY_LOW。OS 主动回收物理页，不在每轮空转中浪费 CPU。

**probe 基线**（`cleaner.py` L290-293）：probe 成功后不再调用 `mark_trimmed` 设置 WS 基线。原先 probe 成功后设基线 → 下轮被 `snap.ws <= baseline` 阻挡，导致大量进程被从 trim 路径逐出。

### 🔥 EFIS v3 — 全程序智能调优大脑

**`efis.py` 重写**（~250 行→~220 行，净减少但更高效）。
- **参数**：旧（`theta_gate`☠️, `cooloff_base`✅, `ws_baseline_mul`☠️, `learning_rate`✅）→ 新（`deepen_theta`, `layer3_agg_gate`, `pid_kp`, `pid_kd`, `target_usage`, `interval_high`, `cooloff_base`, `learning_rate`, `composite_kalman_w`），死参 2→0，总参数 4→9。
- **诊断**：移除 ERIS 代理指标 → 每参数有专用因果症状规则。`deepen_waste` 检查 2-pass 额外释放除以进程数是否 < 10MB。`layer3_extra` 检查每轮平均释放。`pid_kp` 检查 `agg_change > 0.2` 且 PF 超标。
- **DIAGNOSIS_MAP**：5 维→3 维（`capability`/`precision`/`momentum`），死维 `adaptivity`/`context` 删除，从 30% 有效→100% 有效。
- **持久化**：`_cycle` / `_symptoms` 通过 `save()` / `load()` 跨重启保持，避免每次冷启从零学习。
- **连接**：`deepen_theta` 接入 `_trim_process`（`cleaner.py` L306-310），`layer3_agg_gate` 接入 `optimize()` deep/normal 分支（L599-604），`pid_kp/kd/target_usage` 接入 `PidController`（`judger.py` L83-89），`composite_kalman_w` 接入 `_composite_score_v2`（`cleaner.py` L377-380）。
- **死参过滤**：`load()` / `detect_scene` / `_direction_wins` 中扩展死参过滤列表到 `cpu_gate, max_trim, theta_gate, ws_baseline_mul`，`gui.py` 注入 `CFG` / `judger.cfg` 时同样过滤，防止死参泄露回 `config.yaml`。
- **数据文件**：`efis_state.json` 重置为 v3 格式（9 参数默认值），`memwise_state.json` 中旧 `efis` 键清除。

### 🔥 Meta-Cognition 深化

**`self_check` 激活**（`learner.py` L579-601→`meta.py` L70）：原定义为死代码（从未调用），现挂入 `meta.tick()` 每 30s 运行一次。对比所有 `clean_count >= 5` 进程的预测释放量 `thompson_theta * gain_ewma` 与实际释放量 `gain_ewma`，误差 >30% 降 `CTX_LR_BASE`（乘 0.8），误差 <10% 提 `CTX_LR_BASE`（乘 1.2），精准时提回。

**卡尔曼 q 温和调节**（`meta.py` L49-59）：衰减 0.5→0.9（防 2 分钟溃缩至下限），增长 1.5→1.2（防指数爆炸）。下限 0.01→0.02（0.02 仍有 2% 创新增益，不完全冻结）。

**θ_bias 对称化**（`meta.py` L53-61）：负向最大值 -0.3→-0.2，步长 0.05→0.04。与正向 +0.2 对称，消除长期负漂。

**概念漂移阈值放宽**（`meta.py` L68-76）：EWMA 比率 2.5×/0.3×→4.0×/0.2×。漂移时 Beta 减半 0.5→0.7，Kalman q 重置值 1.0→2.0。漂移影响的进程从 20%→5%。

**日志精准化**（`meta.py` L55,L62）：高误差→"卡尔曼重置X个, 降低θ置信"，低误差→"卡尔曼精准, 奖励θ置信"。去数字去歧义。"探索"数量变化时才输出（`_last_never_tried` 跟踪），"因果"对数变化时才输出（`_last_pair_count` 跟踪）。

### 🔥 因果系统修复

**致命 bug — 大小写不一致**（`causal.py` L22-34）：`record()` 存原始大小写键 `("Chrome.exe", "Edge.exe")`，`learner.causal_compare()` 查 `.lower()` 键 `("chrome.exe", "edge.exe")`——永远对不上。5000+ 对因果数据全程作废。修复：`record()` 中先 `lower()` 再存键。

**接入策略投票**（`policy.py` L66-73 + `judger.py` L168）：Tree 5 `state.get("candidates", [])` 原先永远空列表 → 因果分数永远 0。现 `judger._last_candidates` 从 `cleaner._layer2_process` 每轮同步完整候选列表。Tree 5 因果 `advantage > 50MB` +2 分，`>20MB` +1 分，低分中性（纯奖励不惩罚）。

**单条覆盖 + 查询简化**（`causal.py` L28-31 + L31-44）：每对存储从列表→最新单条（新覆盖旧），`advantage()` 从加权平均→单值直接返回。`advantage` 尺寸从 O(50log50)→O(1)。

**死代码**：`best_alternative`（从未调用）删除。旧因果数据（`memwise_state.json` 中 `causal` 键）清除。

### 🔥 策略投票

**`should_probe` 接入 `can_probe`**（`judger.py` L206-214）：`can_probe` 末尾调用 `self.learner.policy.should_probe()`，得分高→`boost = 0.3`（探测间隔缩短到 30%），得分低→`boost = 1.0`（正常间隔）。纯加速不拦截——安全过滤后所有进程都会 probed。

**DIAG 残留清除**（`policy.py` L74,L124）：`should_trim` 和 `should_probe` 中 `return True, f"DIAG:score=..."` 为早期测试代码，改回 `return score >= 0, ...` 和 `return score >= 1, ...`。

### 🔧 核心 Bug 修复

| 优先级 | 问题 | 修复 | 文件/位置 |
|:------:|------|------|------|
| P0 | `_update_ctx_weights` 末尾 `self.kalman = KalmanProfile()` 等三行每次重置 kalman/temporal/curiosity | 删除三行 | `leaner.py` L221-223 |
| P0 | 卡尔曼数据全为零（bug 清空），但 gain_ewma 完好 | `from_dict` 中 `gain_ewma > 0` 且 `x_freed == 0` 时 seed `x_freed = gain_ewma` | `learner.py` L397-404 |
| P0 | `refill_ewma` 计算用错时间差——`last_seen` 先被覆盖为 now 后被除 | 保存 `prev_seen = self.last_seen` 再更新 | `learner.py` L98-107 |
| P0 | `_last_mem_pct` 永远为 50（从来只在 `__init__` 赋值） | `update_pressure` 开头 `self._last_mem_pct = mem_usage_pct` | `judger.py` L97 |
| P0 | `_composite_score_v2` 权重和 `tw=1.0-kw`→`tw=0.6-kw`（求和原为 1.4） | 修复为 `0.6 - kw`，确保 θ+Kalman+WS+Regrowth 始终和为 1.0 | `cleaner.py` L378 |
| P0 | `_layer1_light` gap fill 调了 `_progressive_compress`→`deep_compress`（1.2s含standby） | 改为直接调 `trigger_memory_compression`（快速单次无standby） | `cleaner.py` L190 |
| P1 | `layer3_extra` 减法反向 `before.avail - after.avail` → 恒负 | 改为 `after.avail - before.avail`，且存 bytes 统一单位 | `cleaner.py` L536-539 |
| P1 | `deepen_theta` EFIS调了但不生效——`_trim_process`仍用硬编码0.6 | 改为 `self.judger.cfg.get('efis_params',{}).get('deepen_theta',0.6)` | `cleaner.py` L306 |
| P1 | `_last_layer3` 未初始化→守护启动崩溃 | 在 `_on_daemon` 初始化 `self._last_layer3 = 0` | `gui.py` L1419 |
| P1 | `prev_interval` 引用残留→NameError | 删除动态间隔残留的 `if interval != prev_interval` | `gui.py` L1526 |
| P1 | deadline 在循环内重置→永不结束 | 循环前设一次 `deadline = now + interval - 3`，动态间隔移至循环后 | `gui.py` L1477-1520 |
| P2 | 首轮图表不显示（`last_chart_ts` 初始为 now，首轮无 chart push） | `last_chart_ts = time.time() - 30` | `gui.py` L1443 |
| P2 | `_cycle_buf` 在 `__init__` 中未初始化→启动日志崩溃 | 在 `__init__` 中 `self._cycle_buf = []` | `gui.py` L122 |
| P2 | `config.yaml` 在 PyInstaller 临时目录→重启被覆盖 | `CONFIG_PATH` 修正为 `config/` 子目录（与 `get_state_path()` 同级） | `config.py` L9-14 |
| P2 | yaml 模块 PyInstaller 未强制包含→保存静默失败 | 构建命令新增 `--hidden-import yaml` |
| P3 | `get_parent_process_name` 异常时 snapshot 句柄泄漏 | `finally: CloseHandle` | `winapi.py` L418-422 |
| P3 | `trigger_memory_compression` 失败后误调 `EmptyWorkingSet(GetCurrentProcess())` 清自己的 WS | 删除错误后备逻辑 | `winapi.py` L508-510 |
| P3 | 多个 `return False` 被 regex 删除 diagnostic 计数时意外合并到同一行 | 逐行恢复断行 | 多文件 |

### 🔧 图表与日志

**日志清屏规则**：每轮 `cycle_begin` 记录当前行数 `_cycle_prev_lines`。`_log_op` 在插入末尾后检查 `prev + len(_cycle_buf) > 7`→清屏+重新输出本轮全部，≤7→保留全部。`_log` 只追加不清屏。`_log_op` 达死线时一次性输出。

**图表同步**：每轮推 `cycle_freed` 到 `_chart_data`（不再 30s 累积），与日志同步输出。

**日志精准化**：EFIS 日志全中文化（9 参数中文名映射表）。因果对数/探索数/Layer3 强度仅在变化时输出。`overflow_bonus` 0.30→0.25→0.15→0.20。

**统计栏**：`系统杂项` 和 `进程` 超 999 自动 K 格式（如 1.3k）。

### 🔧 托盘与窗口

**NOTIFYICONDATA**：guid 保留但 hBalloon 移除（sizeof=968），遮罩位图从 `CreateBitmap(..., None)`（未初始化随机位）改为全零字节数组初始化。

**`NIM_SETVERSION(4)` 先于 `NIM_ADD`**：MSDN 要求版本设置在前，之前放后面导致图标行为异常。

**`_show_window`**：从 `self.root.deiconify()` 改为 `ShowWindow(SW_RESTORE)` + `SetForegroundWindow` Win32 API——解决 tkinter deiconify 在某些 Windows 版本失效的问题。

**托盘菜单**：最终方案为原始模式——`menu.post()` + `root.after(200)` + `root.update()` + `root.grab_release()`。期间尝试过 `tk_popup`、`after(0)` 延迟、`lambda` 闭包、实例变量等全部无效，最终恢复原始模式成功。

### 🔧 设置页面

**新增控件**（`gui.py` `_open_settings`）：
- 关闭按钮行为：3 个 RadioButton（最小化到托盘/直接退出程序/每次询问），`close_var` 绑 `CFG["close_action"]`，`set_ca` 含 `global CFG` + `_save_cfg()`
- 注册表缓存清理 + 内存合并：2 个 Checkbutton，`toggle_op("registry")` / `toggle_op("combine")`，均含 tooltip

**持久化**：通过 `_save_cfg()` 在所有勾选项的 `command` 回调中调用。`CONFIG_PATH` 修正到项目根目录 `config/` 子目录（与 `memwise_state.json` 同级），`save()` 新增 `os.makedirs` 确保目录存在。

**布局**：窗口高度 500→640，控件顺序重排（启动→关闭按钮→守护→最小化→清理）。设置按钮 tooltip 更新至 8 种操作默认值。

### 🔧 进程排行

**全量进程覆盖**（`winapi.py` L380-411 `get_all_processes_memory`）：通过 `NtQuerySystemInformation(SystemProcessInformation=5)` 批量获取所有进程的 WS/私有内存，绕过 `OpenProcess` 保护，Kaspersky 等受保护进程全面覆盖。

**内存列对齐**：`priv`→`ws` 对齐任务管理器"详细信息"列。

**UI 优化**：树高度 25→35，刷新 3s→2s，底部新增总数标签（"共 N 个进程"）。

### 🔧 Tooltip 全面精修

15 处 tooltip 更新：守护按钮（60s 固定间隔、PID 自适应、持续优化/自适应间隔/快车道说明、θ 门槛删除）、优化按钮（递进压缩、4 种默认缓存、快车道）、设置面板（8 种操作默认值）、Standby（多轮递进）、压缩（4 轮递进）、统计栏（守护持续计数说明）、关闭按钮行为（3 个 radio 独立 tip）。过时描述全部删除。

### 🔧 死代码清理

删除 10 个从未调用的函数：`_adaptive_interval`、`_probe_interval` (`cleaner.py`)、`set_context`、`top_by_score`、`top_by_theta`、`get_volatility`、`get_clean_count` (`learner.py`)、`load_std_icon`、`load_icon_from_file` (`winapi.py`)、`best_alternative` (`causal.py`)。`_rs` 诊断计数器随用随删。

### ⚙ 构建

- 全部 v1.5→v1.6
- `--uac-admin`、`--icon assets/icon.ico`
- `--add-data "config/config.yaml;config"`
- `--hidden-import win32api --hidden-import yaml`
- 构建前 `taskkill /f /im MemWise.exe` + `Remove-Item -Recurse -Force build`
