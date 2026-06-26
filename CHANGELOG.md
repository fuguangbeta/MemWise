# MemWise 更新日志

> **MemWise** — Windows 智能内存看护工具。不杀进程、不挂起线程、不注入、不联网。
> 纯 ctypes Win32 API，零外部依赖。

---

## v1.3 (2026年6月 — 当前)

> 迄今为止最大更新。涵盖全新 EFIS 效率反馈系统、学习系统深度重构、算法全面加速、数十项 Bug 修复与 UI/UX 改进。累计修改 30+ 处代码，涉及全部 8 个核心源文件。

---

### 🔥 新增：EFIS 效率反馈智能系统（全新，core/efis.py）

| 组件 | 文件名/位置 | 功能说明 |
|------|-----------|---------|
| **实验日志** | `efis.py:experiments` | 每次调参记录实验(timestamp/trigger_dim/changes/clean_eff_before) |
| **自动回滚** | `efis.py:_evaluate_previous_experiments` | 清理效率下降超过阈值(REVERT_THRESHOLD=3.0)→参数自动恢复 |
| **回滚冷却** | `efis.py:_revert_cooldown` | 被回滚过的方向 N 周期内不重试(REVERT_COOLDOWN=5) |
| **方向胜场计数器** | `efis.py:_direction_wins` | 连续 CONSECUTIVE_BOOST=3 次有效 → 步长翻倍 |
| **场景参数记忆** | `efis.py:scene_params` | game/browser/development/general 四场景独立参数，持久化 |
| **场景历史最优** | `efis.py:_scene_best` | 每个场景下达到最佳清理效率时的参数快照 |
| **窗口化评估** | `efis.py:_evaluate_previous_experiments` | eris_history 前后5周期波动>8%时跳过评估(排除混杂因素) |
| **相对步长** | `efis.py:_adjust_for_low_v2` | step = max(绝对值步长, 当前值×5%)，统一比例 |
| **历史最优回归** | `efis.py:_relax_for_high` | 高分时向场景历史最优(而非默认值)回归 10% |
| **清理效率控制** | `efis.py:_calc_clean_efficiency` | 用清理效率(释放MB×成功率)替化ERIS做评估信号 |
| **EFIS 持久化** | `efis.py:save/load` | 每 30tick 保存 experiments/scene_best/direction_wins 到 state.json |
| **场景冲突检测** | `efis.py:_cycle_changes` | 同一周期内不同维度反向调整同一参数时跳过冲突 |

---

### 🧠 学习系统重构 (core/learner.py)

#### 模块级常量变更

| 常量 | 旧值 | 新值 | 说明 |
|------|------|------|------|
| WINDOW | 30 | 20 | 趋势窗口缩小，更快适应新数据 |
| EWMA_LAMBDA | 0.5 | 0.5 | 不变 |
| Z_SCORE_THRESHOLD | 3.0 | 3.0（仍用于泄漏但阈值已改） | 泄漏检测改用双阈值 |
| MIN_SAMPLES | 3 | 3 | 不变 |
| TREND_SAMPLES | **6** | **3** | 趋势线采样数减半，预判清理 3 点(90s)即可检出趋势 |
| BETA_DECAY_RATE | 0.002 | 0.002（功能已改为时间遗忘） | 不再每 feed 衰减 |
| CTX_LR_BASE | **0.03** | **0.5** | 上下文学习率 ↑16.7 倍 |

#### Profile 类变更

| 变更 | 说明 |
|------|------|
| `__slots__` | 18→**24** 个：新增 `gain_ewma_fast`/`slow`、`cost_ewma_fast`/`slow`、`_grad_buffer`、`_grad_count` |
| `__init__` 新增属性 | 6 个新属性：增益/成本双 EWMA 各 2 个 + 梯度缓冲 2 个 |
| `feed()` Beta 衰减 | **移除**——不再每 tick 向 (α=2,β=1) 收缩，alpha 不再被锁在 2 附近 |
| `feed()` 泄漏检测 | Z>3.0+斜率>0.01+连续3tick → **Z>2.0+斜率>0.005+连续2tick** |
| `feed()` 轻度泄漏 | 新增：Z>1.5+斜率>0.002 → `leak_suspect = "mild"` |
| `_update_ctx_weights()` | 逐次更新 → **sign-based + 批量累积(2次)** |
| `record_clean()` | 新增**时间遗忘**：距上次反馈>1小时开始遗忘，每小时5%，最多50% |
| `record_clean()` 双EWMA | 新增 `gain_ewma_fast=0.6` / `gain_ewma_slow=0.1` 更新 |
| `gain_accelerating` 属性 | 新增：快速均值 > 慢速均值时返回 True，用于排序加速信号 |
| `to_dict()` | 新增导出 `gain_ewma_fast/slow/cost_ewma_fast/slow/grad_buffer/grad_count` |
| `from_dict()` | 新增恢复 6 个字段 |

#### PareLearner 类变更

| 变更 | 说明 |
|------|------|
| `__init__` | 新增 `_info_msgs = []`（日志消息队列） |
| `pop_info()` | 新增方法：取出并清空消息队列 |
| `thompson_score()` | 新增**好奇心奖励：`min(0.15, max(0, 分钟-10)×0.005)`** |
| `thompson_score()` | 新增**不确定性奖励：`max(0, 0.10 - conf×0.10)`** |
| `thompson_score()` 日志 | 好奇心>0.02 时输出 `🎲 {name} 好奇心+...` |
| `composite_score()` | θ×(0.5+0.3conf+0.2roi) → **0.6×θ + 0.4×min(1.0, bonus)** |
| `composite_score()` bonus | bonus = 0.5×conf + 0.3×roi + (0.2 if gain_accelerating) |
| `record_clean_result()` | 新增 `lr` 参数转发 |
| `record_probe_result()` | 新增 `lr` 参数转发 |

---

### ⚡ 判定器重构 (core/judger.py)

| 变更 | 旧值 | 新值 |
|------|------|------|
| `DEFAULT_KP` | 0.8 | **1.0** |
| `DEFAULT_KI` | 0.10 | 0.10（不变） |
| `DEFAULT_KD` | 0.15 | 0.15（不变） |
| `TARGET_USAGE` | 55.0% | **45.0%** |
| `__init__` | 无消息队列 | 新增 `_prev_agg = 0.0`、`_info_msgs = []` |
| `update_pressure()` | 仅返回 | **新增大幅变化日志**：change>0.25 时输出 `📈 内存X%(状态) 清理强度:旧→新` |
| `_agg_label()` | 无 | **新增**：<=0.01→极低/<=0.30→低/<=0.60→中/>0.60→高 |
| `_mem_label()` | 无 | **新增**：<40→充足/<60→正常/<80→偏高/>=80→紧张 |
| `can_trim()` WS门槛 | 10MB | **5MB** |
| `can_trim()` theta_gate | 硬编码 0.25 | **从 efis_params 读取，默认 0.18** |
| `can_trim()` 游戏模式θ | 硬编码 0.15 | **min(e_theta, 0.15)** |
| `can_trim()` 游戏模式CPU | 硬编码 2.0 | **max(e_cpu, 2.0)** |
| `can_trim()` 联合概率 | θ×(0.5+0.5×agg) | **纯 θ 比较(不再乘 agg 因子)** |
| `can_trim()` WS 基线 | 固定 1.3/1.2/1.15 | **× e_b_mul / 1.20** |
| `can_probe()` WS门槛 | 50MB | **30MB** |
| `mark_failed()` 冷却 | 硬编码 3600 | **从 efis_params 读取 cooloff_base** |
| `leak_suspect` 处理 | True/False | **True/"mild"均跳过冷却(truthy)** |

---

### 🧹 清理器变更 (core/cleaner.py)

| 变更 | 旧值 | 新值 |
|------|------|------|
| `_max_workers` | min(cpu_count, 8) | **min(cpu_count, 4)** |
| `GAME_PROCESSES` | ~80 个 | ~70 个（精简重复项） |
| `__init__` | 无 | **新增 `_info_msgs = []`** |
| `pop_info()` | 无 | **新增** |
| `_trim_process()` WS门槛 | 10MB | **5MB** |
| `_trim_process()` lr | 不传 | **传 `self._efis_lr()`** |
| `_probe_process()` lr | 不传 | **传 `self._efis_lr()`** |
| `_efis_lr()` | 不存在 | **新增：从 judger.cfg 读取 EFIS learning_rate** |
| `MAX_TRIM` | 30 | **50** |
| `_layer1_system()` 操作种类 | 4 种(standby/modified/filecache/compress) | **7 种(新增 registry/volume)** |
| `_layer1_system()` 频率门控 | **移除**（原 MIN_STANDBY_INTERVAL+可用内存门控） | 删除 |
| `_layer2_process()` 预判清理 | 无 | **新增增长斜率加分排序** |
| `_layer2_process()` 前台进程 | `set_memory_priority(pid, 5)`(值越界) | **删除该行，前台保持默认优先级** |
| `_layer3_deep()` | agg<0.6 时跳过 | **deep/full 无条件执行 + try/except 异常捕获** |
| `_layer3_deep()` | `as_completed` 只 `pass` | **`f.result()` + try/except** |
| `optimize()` docstring | quick=probe only | **quick=full probe+trim** |
| 游戏模式日志 | 无 | **`🎮 检测到游戏运行·切换到激进清理模式`** |
| 深度清理日志 | 无 | **`🔁 触发深度清理(清理强度:...)`** |
| `summary()` | 基础 | **不变** |

---

### ⚙️ 配置变更 (core/config.py)

| 参数 | 旧值 | 新值 |
|------|------|------|
| `kp` | 0.6 | **1.0** |
| `target_usage` | 60 | **45** |
| `clean_operations` | 不存在 | **新增：`["ws","standby","modified","filecache","volume","compress","registry"]`** |

---

### 📐 EFIS 默认参数变更 (core/efis.py)

| 参数 | 旧值(不存在) | v1.3 |
|------|------------|------|
| `theta_gate` | — | **0.18** (范围 0.10~0.50) |
| `cpu_gate` | — | **1.0** (范围 0.30~3.00) |
| `max_trim` | — | **50** (范围 5~80) |
| `cooloff_base` | — | **1200** (范围 1200~7200) |
| `ws_baseline_mul` | — | **1.20** (范围 1.05~1.50) |
| `learning_rate` | — | **0.3** (范围 0.01~0.50) |
| 保存频率 | — | 每 **30tick** |

---

### 🖥️ GUI 变更 (memwise_gui.py)

#### 导入与初始化

| 变更 | v1.2 | v1.3 |
|------|------|------|
| 模块导入 | 基础 | **新增 `queue`** |
| 窗口标题 | "MemWise v1.2" | **"MemWise v1.3"** |
| `__init__` | 基础 | **新增 `self._msg_queue = queue.Queue()`** |
| 消息队列启动 | 无 | **`_poll_msg_queue()` 每 100ms 轮询** |
| EFIS 控制器 | 无 | **新增 `self.efis = EfisController(STATE_FILE)`** |

#### ToolTip 类

| 变更 | 说明 |
|------|------|
| `font` | **Segoe UI → Microsoft YaHei UI**（解决中文渲染字体回退问题） |
| `wraplength` | **600 → 800** |

#### ERIS 几何平均

| 变更 | 说明 |
|------|------|
| 最小值保护 | 各维度 `max(value, 0.1)` → 避免单维度归零拉垮总分 |

#### 日志系统

| 变更 | v1.2 | v1.3 |
|------|------|------|
| `_log_should_clear()` | 不存在 | **新增：实时计算行数 vs 可见行数，仅溢出时清屏** |
| `_clear_log()` | 每次_log_op都清 | **保留，仅_log_should_clear返回True时调用** |
| `_log_op()` | 每次都清屏 | **仅 `_log_should_clear()` 返回 True 时才清** |
| `_log()` | 仅新周期时清屏 | **每次写入前检查 `_log_should_clear()`** |
| `_poll_msg_queue()` | 不存在 | **新增：主线程轮询 msg_queue，处理 log/log_op/efis/chart/upd_ui** |

#### 手动优化

| 变更 | v1.2 | v1.3 |
|------|------|------|
| `_opt_worker()` | 单轮优化 | **3 轮(首轮按模式+后两轮 deep)，累计释放量对比** |
| 日志输出 | `root.after(0, ...)` | **`_msg_queue.put(...)`** |
| 统计 | 单轮增量 | **`📊 三轮优化合计释放 X MB，可用内存 a%→b%`** |

#### 守护模式

| 变更 | v1.2 | v1.3 |
|------|------|------|
| 启动日志 | `root.after(0, ...)` | **`_msg_queue.put(('log_op', ...))`** |
| 动态tick | 固定 interval | **清强>0.8→10s, >0.5→20s, pct<40→60s, else 30s** |
| 动态tick日志 | 无 | **`⏱ 动态tick: Xs→Ys`** |
| EFIS 集成 | 无 | **完整 EFIS tick + 参数同步到 CFG 和 judger.cfg** |
| 算法日志 | 无 | **收集 learner.pop_info() / cleaner.pop_info() / judger._info_msgs → 日志区** |
| 所有 `root.after(0, ...)` | 从 daemon 线程直接调用 | **改为 `_msg_queue.put()` 由主线程轮询** |

#### 设置面板

| 变更 | 说明 |
|------|------|
| 卷缓存复选框 | **新增 `cb_vc`(text="卷缓存刷新", variable=vl_var)** |
| volume tooltip | **新增：刷新各卷写入缓存缓冲区的说明** |
| 清理模式 tooltip | 更新为 7 种操作列表 |
| 优化按钮 tooltip | 更新为 3 轮深度清理 |
| 守护按钮 tooltip | 更新 EFIS/学习系统/动态tick 说明 |
| 统计 tooltip | 更新为 7 种操作明细 |

---

### 🐛 修复清单

| # | 问题 | 根因 | 修复 |
|---|------|------|------|
| 1 | EFIS 参数调了白调 | 参数写入 `CFG` 字典，但 cleaner/judger 读取 `judger.cfg`(独立 jcfg 字典) | 同时写入 `CFG['efis_params']` 和 `self.judger.cfg['efis_params']` |
| 2 | Profile 守护崩溃 | 新增 `gain_ewma_fast/slow`、`cost_ewma_fast/slow`、`_grad_buffer`、`_grad_count` 未注册到 `__slots__` | 全部 6 个注册到 `__slots__` |
| 3 | ProcessSnapshot 守护崩溃 | `_growth_bonus` 未注册到 `__slots__` | 注册到 `ProcessSnapshot.__slots__` |
| 4 | 算法日志用户看不到 | 用 `print(..., file=sys.stderr)` 写到标准错误流，console=False 的 exe 中不可见 | 改用 `_info_msgs` 列表收集，GUI 守护循环调用 `_log()` 显示 |
| 5 | `set_memory_priority(pid, 5)` 无效 | 合法范围 0-4，值 5 被 Windows 静默忽略 | 删除前台进程的 API 调用(前台本就默认优先级) |
| 6 | BOM 字符残留 | PowerShell 写入文件带 U+FEFF | Python 脚本移除 BOM |
| 7 | Layer3 异常静默 | `as_completed` 循环只 `pass`，不调 `result()` | 改为 `f.result()` + try/except |
| 8 | 内存条残留 `.tmp` | 旧版清理 | 清理 stale 临时文件 |
| 9 | ToolTip 中文乱码 | Segoe UI 无中文 glyph，触发字体回退 | 改为 Microsoft YaHei UI |
| 10 | 日志每次清屏 | _log_op 强制 clear | 智能清屏(仅溢出时清) |
| 11 | `root.after` 从 daemon 线程调用 | tkinter 非线程安全 | 改为 queue.Queue + 主线程轮询 |

---

### 📝 新增/变更的算法日志

| 日志内容 | 触发条件 | 输出方式 |
|---------|---------|---------|
| `🎲 {name} 好奇心+{v:.2f}，总θ={b:.2f}→{r:.2f}` | 好奇心 > 0.02 | learner._info_msgs |
| `🕳️ 检测到{name}疑似内存泄漏(斜率{s:.3f},Z={z:.1f})` | 泄漏标记首次触发 | learner._info_msgs |
| `📈 内存{pct}%({状态}) 清理强度:{旧}→{新}` | aggressiveness 变化 > 0.25 | judger._info_msgs |
| `🎮 检测到游戏运行·切换到激进清理模式` | 游戏模式刚切换 | cleaner._info_msgs |
| `🔁 触发深度清理(清理强度:{标签})` | Layer3 执行 | cleaner._info_msgs |
| `⏱ 动态tick: {旧}s→{新}s` | tick间隔变化 | GUI _msg_queue |
| `📊 三轮优化合计释放 {v} MB，可用内存 {a}%→{b}%` | 手动优化完成 | GUI _msg_queue |
| EFIS 场景/调参/回滚/最优日志 | 已有(事件驱动) | EFIS.last_log |

---

## v1.2 (2026年6月)

> 学习系统初步成型 + 大量 Bug 修复。

### 修复

| 优先级 | 问题 | 解决方案 |
|:---:|------|----------|
| P0 | Thompson θ 双定义导致上下文增强完全失效 | 删除重复 θ 定义 |
| P0 | judger.py 缩进断裂导致死代码 | 重构缩进 |
| P1 | empty_standby 首次调用双重执行 NtSetSystemInformation | 检测是否已执行 |
| P1 | PID 控制器在 daemon 内外各更新一次 → 控制量翻倍 | optimize() 接受 aggressiveness 参数 |
| P1 | 内存优先级映射反向 | 低 θ 跳过，高 θ 设为 VERY_LOW |
| P1 | can_probe 不跳过前台进程 | 新增前台进程检查 |
| P2 | can_probe 无 θ 过滤 | 样本≥5 且 θ<0.2 时跳过 |
| P2 | purge_expired 冷却时间 +3600 冗余 | 改为 now |
| P2 | 守护模式下 CLI 与 GUI 清理路径不统一 | 统一走 cleaner.optimize() |
| P2 | 内存优先级永不刷新 | 每 30 tick 重新评估 |
| P3 | 测量用快照使用旧数据 | 改为实时读取 WS |
| P3 | normal 模式永不触发 Layer3 | aggressiveness≥0.6 时触发 |
| P3 | except:pass 静默吞噬异常 | 改为打印到 stderr |
| P3 | ThreadPool 永不关闭 | 添加 shutdown() |
| P3 | state.json 路径硬编码 | 统一到 core.config |

### 学习系统

- 上下文模型从 Probe 学习
- 置信度改用 Beta 分布标准差
- Beta 分布时间衰减
- 自适应学习率
- 失败计数逐渐遗忘

### 算法

- 复合评分排序 θ×(0.5+0.3×置信度+0.2×ROI)
- 自适应清理轮数(WS<50MB→2轮, 50~200MB→3轮, >200MB→4轮)
- Standby 频率门控(最小间隔 60s)
- 配置热加载
- 全屏游戏检测
- 游戏名单扩充至 80+
- 进程内存排行榜+单击终止
- 默认清理模式由 quick→normal
- state.json 过滤收紧至 7天/5样本

---

## v1.1 (2026年初)

### 主要新功能

- 游戏模式(80+游戏名单)
- 双次清理(自适应间隔 300ms)
- 配置统一到 core/config.py
- θ 缓存
- 画像自动清理(超30天)
- 四档颜色图标
- 守护模式完整分层清理(L1~L3)
- 操作过滤
- 30 进程上限
- GUI 居中/弹窗优化

---

## v1.0 (初始版本)

- EmptyWorkingSet 进程清理
- CLI 界面
- 基础配置
- 首次发布，建立核心架构

---

> [GitHub Releases](https://github.com/fuguangbeta/MemWise/releases) — 下载最新版本与历史发布
