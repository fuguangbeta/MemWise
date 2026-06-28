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