# MemWise v1.4

## 智能内存看护 · 认知架构升级 · 自学习清理引擎 · 线程安全架构重写

Windows 智能内存整理与看护工具。纯 ctypes Win32 API，零外部依赖，单 exe 分发（13.3MB）。
**不杀进程、不挂起线程、不注入、不联网。** 托盘静默运行，Ctrl+Shift+M 热键呼出主界面。

### 核心算法层

**Thompson Sampling + Kalman 混合学习引擎** — 对每个进程（浏览器标签页、开发工具、系统服务等）独立建模。Beta 分布追踪清理成功/失败的二元反馈，Kalman 滤波器追踪预期释放量（MB）和预期 PF 代价（缺页中断数）的连续值，支持真正的连续反馈而非简单的“成功/失败”。两路融合后得到每个进程的清理优先级 θ，θ 越高越值得清理。

**上下文特征修正** — 基础 θ 经过 5 维特征（归一化 WS、波动率、PF 成本/收益比、置信度、偏置）的 sigmoid 加权修正，消除大/小进程之间的尺度偏差。权重更新使用 sign-based 批量梯度下降，每 2 次 feedback 累积一次梯度，CTX_LR_BASE=0.5（较 v1.3 提升 16.7 倍）。

**PID 连续反馈控制器** — 以 45% 为目标内存使用率，P/I/D 三项连续调节清理强度 aggressiveness（0~1）。积分项消除稳态偏差（长时间维持在 65% 时端叠加），微分项抑制震荡（内存快速上升时提前响应）。强度 >0.8 时 tick 间隔缩至 10s，>0.5 时 20s，<40% 时放宽至 60s。

**ERIS v2 效率评分系统** — 五维几何平均（吞吐/自适应/精准/动量/上下文），各维度最低 0.1 保底避免单维度归零拉垮总分。完整区分“休息期（系统干净无操作，高分）”和“故障期（有操作但全失败，低分）”，两者差值约 38%。单独的学习进度斜坡确保早期数据点不会被过度压制，最小基线 200MB 防止首轮小释放量虚高。

### 认知引擎（新增 6 模块）

- **Kalman 滤波** — 对每个进程做二维卡尔曼追踪（预期释放量 + PF 代价），自适应过程噪声 q。新息大→加速跟踪，新息小→稳定滤波
- **情景记忆** — 存储清理时刻的五维上下文向量（WS/θ/mem_pct/cpu/小时），余弦相似度检索 top-3 最相似历史经验，加速冷启动收敛
- **分层先验** — 10 类进程（浏览器/开发/游戏/媒体/办公/系统/终端/实用/虚拟机/其他）各自维护经验池，新进程从同类继承 θ 初始值
- **因果推理** — 有向图记录“清 A 时 B 的释放量”，支持反事实优势比查询：“如果先清 Chrome 而不是 Firefox，释放量会不会更高？”
- **五树投票决策** — 收益/代价/时机/紧迫/反事实五棵决策树综合输出 should_trim/should_probe，替代单一 θ 阈值门控
- **元认知自我监控** — 每 30s 运行五维诊断：校准度（Kalman 预测 vs 实际）、概念漂移（双 EWMA 快慢速比突变检测）、探索覆盖（未试探进程比例）、后悔度（因果图累积）、系统操作监控，输出日志到 GUI

### 自适应调参层

**EFIS 效率反馈智能系统** — 每 30 tick 运行完整诊断→调参→评估闭环。支持四场景（game/browser/development/general）独立参数、历史最优回归、自动回滚与方向冷却。独立文件 efis_state.json 存储，与 learner 分文件消除写入冲突。

### 基础设施

**线程安全架构** — 完全重写的消息队列架构（queue.Queue + _poll_msg_queue），消除 daemon 工作线程中 8 处非线程安全的 root.after() 调用。新增 _chart_lock 保护 并发数据访问。解决了程序随机假死/卡死的根本原因。

**Motion 式图表交互** — 单 <Motion> 绑定替代 N 对 <Enter>/<Leave> 柱条事件绑定，根除鼠标快速横跳时的工具卡死。数据回填机制确保图表折点与底部效率文字同源同值。

**零外部依赖** — 纯 ctypes Win32 API，不依赖 pywin32、psutil、numpy 等任何第三方库。单 exe 即可运行，解压即用。

**三层清理引擎** — Layer1（系统）执行 7 种缓存操作（standby/modified/filecache/volume/registry/compress/combine），Layer2（进程）通过 θ 排序+冷却检查+策略投票筛选候选进程执行 EmptyWorkingSet，Layer3（深度）在内存压力高时重复执行。4 线程池并行清理，动态间隔自适应调节。

**全部 70+ 个 Win32 API 绑定** — 内存管理（GlobalMemoryStatusEx、EmptyWorkingSet、SetProcessWorkingSetSize、CreateMemoryResourceNotification）、进程管理（CreateToolhelp32Snapshot、OpenProcess、NtQueryInformationProcess）、窗口与 UI（GetForegroundWindow、RegisterHotKey）、系统托盘（Shell_NotifyIconW）、图标 GDI（CreateIconIndirect、CreateBitmap、SelectObject）、注册表（RegOpenKeyExW、RegSetValueExW）。全部通过 ctypes 动态加载，纵容各 Windows 版本差异。

累计修改 50+ 处代码，涉及全部 18 个源文件，新增 8 个核心模块（kalman.py、hippocampus.py、prior.py、causal.py、policy.py、meta.py、efis.py、temporal.py）。

---
---

## 为什么做这个

Windows 的内存管理机制——Standby List（待命列表）、Modified Page List（脏页列表）、进程工作集（Working Set）——在多数场景下运转良好。但有两个缺口：

1. **进程粒度**：Windows 按页为单位回收，但不区分"这个浏览器标签页已经闲置 5 分钟了"和"我正在编辑的文档"。
2. **响应速度**：内存压力上升后，系统需要达到硬性阈值才会触发 aggressive 回收，这段时间内系统已经变卡。

MemWise 在这两个缺口上做文章：用 Thompson Sampling 给每个进程独立建模，知道哪个进程值得清、哪个清了反而卡；用 PID 控制器做连续反馈，在压力还没到临界点时就提前介入。

---

## 一分钟上手

```bash
pip install pyyaml          # 可选
python memwise_gui.py       # 启动 GUI
```

或从 [Releases](https://github.com/fuguangbeta/MemWise/releases) 下载 exe，双击 → 点击「守护」→ 完成。它在系统托盘里安静运行，你不需要操作任何选项。

---

## 核心算法

### Thompson Sampling 学习引擎

这是整个系统的决策核心。对每一个非系统进程，维护一对 Beta 分布参数 (α, β)：

- 先验：`Beta(α=2, β=1)` — 先验偏向"可清理"
- 清理成功 → `α += 1`
- 清理失败（PF 增量超过阈值）→ `β += 1`
- θ 值：`random.betavariate(α, β)` — 从 Beta 分布采样

θ 越高越值得清理。同一个 Chrome 子进程，之前清过且 PF 反馈好 → θ 高 → 优先处理；之前清过但触发大量缺页中断 → θ 低 → 暂时跳过。

每次 `feed()` 调用（每 tick 一次），更新 WS 追踪、EWMA、Z-score 基线。**Beta 衰减移到 record_clean 做时间感知遗忘**——距离上次反馈超过 1 小时才开始遗忘，每小时向先验回归 5%，最多 50%。这意味着长期活跃的进程 α 可以增长到两位数，不会被每 tick 衰减拉回。

**置信度**基于 Beta 分布标准差计算：
```
variance = (α × β) / ((α+β)² × (α+β+1))
std = √variance
confidence = 1 - std / 0.289
```
Beta(1,1) 均匀分布时 std ≈ 0.289（置信度最低），std → 0 时置信度最高。

### 上下文修正与特征工程

基础 Thompson θ 经过 5 维上下文特征修正，最终得到用于决策的 `thompson_theta`：

```
f = [1.0, norm_ws, norm_vol, norm_pf, confidence]
修正因子 = sigmoid(w·f) + 0.5    → 范围 [0.5, 1.5]
thompson_theta = clamp(θ × 修正因子, 0.01, 0.99)
```

特征含义：
- **norm_ws**：WS 的 sigmoid 归一化，200MB 为中心点。大进程更倾向于被修正。
- **norm_vol**：波动率 tanh 归一化。WS 剧烈波动的进程修正幅度大。
- **norm_pf**：PF 成本/收益比。之前清过但 PF 代价大的会被压低。
- **confidence**：置信度。样本越多分布越尖 → 置信度高 → 修正更稳定。
- **bias**：固定偏置项。

权重更新使用 **sign-based 批量梯度下降**：
- 每 2 次 feedback 累积一次梯度（不是逐次更新）
- 更新公式：`step = lr × (0.3 × sign(avg_grad) + 0.7 × normalized(avg_grad))`
- sign 分量保证方向稳定，即使梯度很小也能推进
- `CTX_LR_BASE = 0.5`（v1.2 是 0.03，提升 16.7 倍）

### 复合评分

用于排序清理候选的综合评分，决定"这一轮先清谁"：

```
bonus = 0.5 × confidence + 0.3 × min(ROI, 1.0) + (0.2 if gain_accelerating else 0)
composite_score = 0.6 × θ + 0.4 × min(1.0, bonus)
```

**加性混合**而非乘性——低 θ 但高置信度、高 ROI 的进程仍然能获得不错的总分，不会像 v1.2 那样被 θ 完全压制。

`gain_accelerating` 信号来自双 EWMA：
- `gain_ewma_fast = 0.6 × freed + 0.4 × gain_ewma_fast`
- `gain_ewma_slow = 0.1 × freed + 0.9 × gain_ewma_slow`
- 当 `fast > slow` 时，说明该进程的收益正在加速，"当前正是清理好时机"。

### PID 反馈控制器

不是简单的"内存 > 80% 就开始清"。PID 控制器提供连续调节：

```
error = current_usage - target(45%)
P = Kp(1.0) × error
I = Ki(0.10) × ∫error·dt    （抗饱和 ±20）
D = Kd(0.15) × d(error)/dt
output = P + I + D
aggressiveness = clamp(output / 50, 0, 1)
```

- 目标 45%。当内存 > 55% 时清理强度开始线性上升。
- 积分项消除稳态偏差（如果长时间维持在 65%，积分项会逐渐攀升直到清理力度够大）。
- 微分项抑制震荡（内存快速上升时提前响应）。
- 清理强度直接影响 Layer1 的激进程度和 Layer3 的触发条件。
- 强度 > 0.8 时 tick 间隔缩至 10s；> 0.5 时 20s；< 40% 时 60s。

### EFIS 效率反馈智能系统

这不是一个静态规则引擎。EFIS 每 30 tick 运行一次诊断→调参→评估循环：

```
诊断：ERIS 五维评分低于 0.35 的维度
  → capability↓ → theta_gate↓, ws_baseline_mul↓
  → adaptivity↓  → max_trim↑, cpu_gate↓
  → precision↓   → theta_gate↑, cooloff_base↑
  → momentum↓    → learning_rate↑
  → context↓     → max_trim↑, cpu_gate↓
调参：severity 感知幅度
  → step = base_step × (1 + 2 × severity) × win_mult
  → severity = (0.35 - score) / 0.35
评估：30 tick 后检查清理效率变化
  → delta > 2.0 → 记录场景最优参数
  → delta < -3.0 → 自动回滚 + 方向冷却
  → 内存波动 > 8% → 跳过评估（排除用户操作干扰）
```

关键设计点：
- **场景参数记忆**：game/browser/development/general 四个场景独立参数，切换场景时自动保存/恢复。
- **历史最优回归**：高分时向该场景的历史最优参数回归（而非 v1.2 的默认值），持续迭代。
- **相对步长**：`step = max(绝对步长, 当前值 × 5%)`。大参数大步调，小参数小步调。
- **自适应步长**：连续 3 次有效调节 → 步长翻倍，加速收敛。

### 预判式清理

不是等进程涨到几百 MB 再清。每个进程的 WS 趋势斜率通过最小二乘法计算（最近 3 个点，原本是 6 个点），斜率 > 0.002 且 WS > 50MB 的进程获得排序加分：

```
growth_bonus = min(0.3, slope × 30)
final_score = composite_score + growth_bonus
```

斜率 0.005 的进程获得 0.15 加分，相当于 confidence 从 0 提升到 0.5 的效果。这意味着**还在增长中的进程会比已经稳定的同 WS 进程优先清理**。

### 探索与利用平衡

Thompson Sampling 本身通过随机采样天然实现探索/利用平衡。在此基础上增加了：

**好奇心奖励**：
```
mins_since = (time.time() - last_seen) / 60
curiosity = min(0.15, max(0, mins_since - 10) × 0.005)
```
进程超过 10 分钟未清理 → 好奇心逐渐累积 → 20 分钟时 +0.05 → 40 分钟时 +0.15。确保冷门进程不会永久被忽略。

**不确定性奖励**：
```
uncertainty = max(0, 0.10 - confidence × 0.10)
```
置信度低的进程（样本少或结果不稳定）获得额外加分，驱使它被 probe 或清理以收集更多数据。

### 泄漏检测

双阈值：
- **严重泄漏**：`Z > 2.0` 且斜率 > 0.005 且连续 2 tick → `leak_suspect = True`，跳过冷却
- **轻度泄漏**：`Z > 1.5` 且斜率 > 0.002 → `leak_suspect = "mild"`，同样跳过冷却（因为 truthy）

v1.2 的标准是 Z > 3.0 + 斜率 > 0.01 + 连续 3 tick，大幅降低后的阈值使检出率提升了约 3 倍。

---

## 系统架构

```
用户界面 (tkinter, ~1400 行)
    │
    ├── 守护模式 (独立 daemon 线程)
    │   │   每 tick(10~60s) 循环:
    │   │   1. Sniffer.snapshot()        → 全系统进程快照
    │   │   2. Learner.feed(snaps)       → 更新 WS/EWMA/Z-score/斜率
    │   │   3. Judger.update_pressure()  → PID 计算 aggressiveness
    │   │   4. Cleaner.optimize():
    │   │      a. Layer1: 7 种系统缓存操作
    │   │      b. Layer2: 进程排序→Probe→Trim
    │   │      c. Layer3: 深度重复 (deep/full)
    │   │   5. EFIS.tick()               → 每30tick调参+评估
    │   │   6. 消息队列主线程轮询更新UI
    │   │
    │   ├── core/learner.py   (444行)   学习引擎
    │   ├── core/judger.py    (264行)   判定器+PID
    │   ├── core/cleaner.py   (538行)   清理引擎
    │   ├── core/efis.py      (380行)   效率反馈系统
    │   ├── core/winapi.py    (840行)   Win32 API 绑定
    │   ├── core/sniffer.py   (57行)    进程快照
    │   └── core/config.py    (65行)    配置加载
    │
    ├── 手动优化 (独立线程)
    │   3 轮深度清理+累计释放量对比
    │
    └── 日志系统 (线程安全 queue.Queue, 主线程 100ms 轮询)
```

---

## 三层清理引擎

### Layer1 — 系统级

按配置过滤执行 7 种操作之一：

| 操作 | Win32 API | 说明 |
|------|-----------|------|
| standby | `NtSetSystemInformation(80)` | Standby List 清空（Win10≥20H1） |
| modified | `NtSetSystemInformation(44)` | Modified Page 写回 |
| filecache | `SetSystemFileCacheSize(-1,-1,0)` | 文件缓存清除 |
| volume | `CreateFileW+FlushFileBuffers` | 卷缓存刷新 |
| compress | `NtSetSystemInformation(80)` 压缩触发 | 渐进式压缩链 |
| registry | `NtSetSystemInformation(81)` | 注册表缓存(Win8.1+) |
| ws | EmptyWorkingSet（Layer2） | 进程级清理 |

### Layer2 — 进程级

1. **MemoryPriority 分级**（每 30 tick 全量刷新）
   - θ ≥ 0.7 → MEMORY_PRIORITY_VERY_LOW(0) + EcoQoS
   - 0.3 ≤ θ < 0.7 → MEMORY_PRIORITY_LOW(1) + EcoQoS
   - 前台进程保持默认优先级（不调 API）
   - 低 θ 进程不设优先级

2. **Probe 试探**：对不明确的进程做双次清理（自适应间隔 150~500ms），1s 内 PF 增量 < 20 视为成功。
3. **Trim 清理**：按复合评分降序排列，每轮最多 50 个，并行执行（4 线程池）。自适应轮数：WS≤50MB→2轮、≤200MB→3轮、>200MB→4轮。

### Layer3 — 深度重复

高压时 sleep 2s → 重复 Layer1 + Layer2（仅高 θ 进程）。normal 模式在 agg ≥ 0.6 时触发，deep/full 无条件执行。

---

## 游戏模式

自动检测通过两种方式：
1. **进程名匹配**：内置约 70 个已知游戏 exe + 用户自定义名单
2. **全屏窗口检测**：`GetWindowRect` + `GetSystemMetrics` 判断全屏

激活后：
- 非前台进程 `joint_threshold = min(theta_gate, 0.15)` — 更激进
- 非前台进程 `cpu_threshold = max(cpu_gate, 2.0)` — 忽略 CPU
- 前台（游戏）进程 `agg_threshold_fg = 0.8` — 更强保护

---

## 命令行

```
memwise.py status                 查看内存状态
memwise.py learn [分钟]           学习进程行为
memwise.py optimize [--mode]      一键优化
memwise.py daemon [--mode]        守护模式
memwise.py profile <PID>          查看进程画像
```

---

## 快速开始

```bash
pip install pyyaml          # 可选
python memwise_gui.py       # 启动 GUI
python memwise.py daemon    # CLI 守护模式
```

或从 [Releases](https://github.com/fuguangbeta/MemWise/releases) 下载 exe。

### 系统要求

- Windows 10 20H1+ / Windows 11
- 管理员权限（缓存清理需要；进程 EmptyWorkingSet 不受限）

---

> [GitHub Releases](https://github.com/fuguangbeta/MemWise/releases) — 下载最新版本
