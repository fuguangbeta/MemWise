# MemWise 更新日志

> **MemWise** — Windows 智能内存看护工具。不杀进程、不挂起线程、不注入、不联网。
> 纯 ctypes Win32 API，零外部依赖。

---

## v1.3 (2026年6月 — 当前)

> 迄今为止最大更新。涵盖全新 EFIS 效率反馈系统、学习系统深度重构、算法全面加速、数十项 Bug 修复与 UI/UX 改进。累计修改 30+ 处代码，涉及全部 8 个核心源文件。

---

### 🔥 新增：EFIS 效率反馈智能系统（全新，core/efis.py）

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
| **EFIS 持久化** | `efis.py:save/load` | 每30tick保存到state.json |
| **场景冲突检测** | `efis.py:_cycle_changes` | 同一周期反向调整同一参数时跳过 |

---

### 学习系统重构 (core/learner.py)

#### 常量

| 常量 | 旧 | 新 | 说明 |
|------|----|----|------|
| WINDOW | 30 | 20 | 窗口缩小 |
| TREND_SAMPLES | 6 | **3** | 预判清理加速 |
| CTX_LR_BASE | 0.03 | **0.5** | 学习率↑17倍 |

#### Profile

| 变更 | 说明 |
|------|------|
| `__slots__` 18→24 | 新增6个slot属性 |
| `feed()` Beta衰减 | **移除**，改为record_clean时间遗忘 |
| `feed()` 泄漏检测旧 | Z>3+斜率>0.01+连续3tick |
| `feed()` 泄漏检测新 | Z>2+斜率>0.005+连续2tick + mild(Z>1.5+斜率>0.002) |
| `_update_ctx_weights` | sign-based + 批量累积2次 |
| `record_clean` 时间遗忘 | >1h开始遗忘，5%/h，最多50% |
| `record_clean` 双EWMA | 新增fast/slow更新 |
| `gain_accelerating` | 新增属性：快速>慢速时True |
| `to_dict/from_dict` | 新增6个字段持久化 |

#### PareLearner

| 变更 | 说明 |
|------|------|
| `_info_msgs` + `pop_info()` | 算法日志队列 |
| `thompson_score` 好奇心 | min(0.15, max(0, 分钟-10)×0.005) |
| `thompson_score` 不确定性 | max(0, 0.10 - conf×0.10) |
| `composite_score` 旧 | θ×(0.5+0.3conf+0.2roi) |
| `composite_score` 新 | 0.6θ + 0.4×min(1.0, bonus) |
| `record_clean_result/probe_result` | 新增lr参数转发 |

---

### 判定器 (core/judger.py)

| 参数 | 旧 | 新 |
|------|----|----|
| DEFAULT_KP | 0.8 | **1.0** |
| TARGET_USAGE | 55% | **45%** |
| trim WS门槛 | 10MB | **5MB** |
| probe WS门槛 | 50MB | **30MB** |
| theta_gate默认 | 0.25 | **0.18** |
| 联合概率 | θ×(0.5+0.5×agg) | 纯θ比较 |
| mark_failed冷却 | 硬编码3600 | 从efis_params读取 |
| WS基线 | 固定倍数 | ×efis_params/1.20 |
| `_prev_agg` + `_agg_label` | 无 | **新增** |
| `_mem_label` | 无 | **新增** |
| `update_pressure`日志 | 无 | change>0.25时输出 |

---

### 清理器 (core/cleaner.py)

| 参数 | 旧 | 新 |
|------|----|----|
| _max_workers | min(cpu,8) | min(cpu,4) |
| MAX_TRIM | 30 | **50** |
| trim WS门槛 | 10MB | **5MB** |
| 前台 set_memory_priority(pid,5) | 有(越界) | **删除** |
| _layer1_system | 4种操作 | **7种(新增registry/volume)** |
| _layer1_system频率门控 | 有 | **移除** |
| _layer2_process预判 | 无 | **增长斜率加分排序** |
| _layer3_deep | agg<0.6跳过 | **deep/full无条件+try/except** |
| _efis_lr() | 无 | **新增** |
| _info_msgs + pop_info() | 无 | **新增** |

---

### 配置 (core/config.py)

| 参数 | 旧 | 新 |
|------|----|----|
| kp | 0.6 | **1.0** |
| target_usage | 60 | **45** |
| clean_operations | 不存在 | **新增:7种操作** |

---

### EFIS默认参数 (core/efis.py)

| 参数 | 默认 | 范围 |
|------|------|------|
| theta_gate | **0.18** | 0.10~0.50 |
| max_trim | **50** | 5~80 |
| cooloff_base | **1200** | 1200~7200 |
| learning_rate | **0.3** | 0.01~0.50 |
| 保存频率 | **每30tick** | — |

---

### GUI (memwise_gui.py)

| 变更 | 旧 | 新 |
|------|----|----|
| 模块导入 | 基础 | 新增queue |
| 窗口标题 | v1.2 | **v1.3** |
| `_msg_queue` | 无 | **新增+_poll_msg_queue(100ms)** |
| EFIS集成 | 无 | **完整EFIS** |
| ToolTip字体 | Segoe UI | **Microsoft YaHei UI** |
| wraplength | 600 | **800** |
| ERIS几何平均 | 无保护 | **各维度max(0.1)** |
| _log_should_clear() | 无 | **新增** |
| _log_op/_log | 每次/周期清屏 | **智能清屏** |
| _poll_msg_queue | 无 | **新增** |
| _opt_worker | 单轮 | **3轮+累计释放** |
| 守护模式动态tick | 固定interval | **10/20/30/60s** |
| 守护EFIS同步 | 无 | **同步judger.cfg** |
| 卷缓存设置 | 无 | **新增cb_vc** |

---

### 修复清单

| 问题 | 修复 |
|------|------|
| EFIS参数写入CFG但未写入judger.cfg | 同时写入两个字典 |
| Profile.__slots__漏注册6属性崩溃 | 注册到__slots__ |
| ProcessSnapshot.__slots__漏注册_growth_bonus崩溃 | 注册到__slots__ |
| print(stderr)日志用户不可见 | 改为_info_msgs队列→GUI |
| set_memory_priority(pid,5)越界 | 删除前台API调用 |
| BOM字符(U+FEFF)残留 | 清除 |
| Layer3异常静默(pass) | f.result()+try/except |
| ToolTip中文乱码 | Segoe UI→YaHei UI |
| 每次清屏刷掉历史 | 仅溢出时清 |
| root.after从daemon线程调用 | queue+主线程轮询 |

---

### 新增/变更的算法日志

| 日志内容 | 触发条件 | 输出方式 |
|---------|---------|---------|
| `🎲 {name} 好奇心+{v:.2f}` | 好奇心 > 0.02 | learner._info_msgs |
| `🕳️ 检测到{name}疑似内存泄漏` | 泄漏标记首次触发 | learner._info_msgs |
| `📈 内存{pct}%({状态}) 清理强度:{旧}→{新}` | aggressiveness 变化 > 0.25 | judger._info_msgs |
| `🎮 检测到游戏运行` | 游戏模式刚切换 | cleaner._info_msgs |
| `🔁 触发深度清理(清理强度:{标签})` | Layer3 执行 | cleaner._info_msgs |
| `⏱ 动态tick: {旧}s→{新}s` | tick间隔变化 | GUI _msg_queue |
| `📊 三轮优化合计释放 {v} MB` | 手动优化完成 | GUI _msg_queue |

---

## v1.2 (2026年6月)

> 学习系统初步成型 + 大量 Bug 修复。

### 修复

| 优先级 | 问题 | 解决方案 |
|:---:|------|----------|
| P0 | Thompson θ 双定义 | 删除重复定义 |
| P0 | judger.py 缩进断裂死代码 | 重构缩进 |
| P1 | empty_standby 双重执行 | 检测已执行直接返回 |
| P1 | PID 双重更新 | optimize() 统一入口 |
| P1 | 内存优先级反向 | 修正方向 |
| P1 | can_probe 不跳过程序进程 | 新增检查 |
| P2 | can_probe 无 θ 过滤 | ≥5样本且θ<0.2跳过 |
| P2 | purge_expired +3600冗余 | 改为now |
| P2 | CLI/GUI 路径不统一 | 统一走 optimize() |
| P2 | 内存优先级永不刷新 | 每30tick重评 |
| P3 | 快照用旧数据 | 实时读取WS |
| P3 | normal 永不触发 Layer3 | agg≥0.6触发 |
| P3 | except:pass | 打印stderr |
| P3 | ThreadPool 永不关闭 | 添加shutdown() |
| P3 | state.json 路径硬编码 | 统一到config |

---

## v1.1 (2026年初)

- 游戏模式(80+游戏名单)
- 双次清理
- 配置统一
- θ 缓存
- 画像自动清理

---

## v1.0 (初始版本)

- EmptyWorkingSet 进程清理
- CLI 界面
- 首次发布

---

## 以往版本速览

### v1.2
Thompson Sampling 学习系统、PID 控制器、游戏模式(80+游戏)、配置热加载、15 项 Bug 修复

### v1.1
游戏模式、双次清理、配置统一到 core/config、θ 缓存、画像自动清理

### v1.0
EmptyWorkingSet 进程清理、CLI 界面、首次发布

---

> [GitHub Releases](https://github.com/fuguangbeta/MemWise/releases) — 下载最新版本与历史发布
