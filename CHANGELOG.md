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

---

*MemWise v1.4 — 2026年6月*
