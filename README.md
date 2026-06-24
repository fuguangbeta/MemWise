# MemWise v1.0 — 智能内存看护

Windows 内存整理工具。不杀进程、不挂起线程、不改优先级、不注入、不联网。纯 ctypes Win32 API，零外部依赖。

---

## 能做什么

**进程级整理** — 对每个进程调用 `EmptyWorkingSet`，释放闲置物理页到 pagefile。Windows 按需自动调入，不影响正常运行。

**系统缓存清理** — 清空 Standby List / Modified Page List / 文件缓存。适用于内存不足时的快速回收。

**深度 Standby 清理** — 多轮递进式清理（低优先→全量→低优先→内存合并），比单次 Standby 多释放 5-10%。

**探针机制（Probe）** — 对评分不明确的进程先微型试探，有效才清理，避免误清。

**守护模式** — 后台持续运行，每 30 秒采集进程快照 → PID 控制器计算压力 → Thompson Sampling 评分 → 自动执行清理。

**双界面** — tkinter GUI（实时内存条/柱状图/操作日志）+ CLI（status/learn/optimize/daemon/profile）。

**系统托盘** — 关闭窗口自动最小化到托盘。右键菜单可恢复窗口或退出。图标颜色指示内存压力：钢蓝（空闲）、绿（低）、黄（中）、红（高）。

**全局热键** — Ctrl+Shift+M 一键调出窗口并执行优化。

**开机自启** — 两种模式：普通启动文件夹快捷方式 / 管理员 Scheduled Task。

**启动选项** — 可配置启动时自动开启守护、启动后自动最小化到托盘。

**设置面板** — 开关各类清理项、定时清理、清理模式选择（quick/normal/deep/full）。

**排除列表** — 添加不想被整理的程序。

---

## 数据

### 代码规模

| 模块 | 行数 | 职责 |
|------|------|------|
| memwise_gui.py | 863 | tkinter GUI + 守护线程编排 |
| memwise.py | 277 | CLI 入口 |
| core/winapi.py | 742 | 纯 ctypes Win32 绑定 |
| core/learner.py | 335 | Thompson Sampling + EWMA 学习引擎 |
| core/cleaner.py | 294 | 3 层清理编排 |
| core/judger.py | 209 | PID 控制器 + 9 层安全判定 |
| core/sniffer.py | 48 | 进程快照采集 |
| **总计** | **~2,768** | **~116 KB** |

### 释放效果

进程级整理对后台驻留进程效果明显：

| 进程类型 | 典型释放量 | 条件 |
|----------|-----------|------|
| 浏览器（chrome/edge） | 200–600 MB | 多标签页闲置后 |
| 开发工具（node/code） | 80–300 MB | 长时间运行构建后 |
| 通讯软件（wechat/qq） | 100–400 MB | 后台驻留中 |
| 文件资源管理器 | 30–100 MB | 文件夹导航累积 |
| **一次整理** | **300 MB – 2 GB** | 取决于运行的应用 |

系统缓存清理（Standby List）释放 1–4 GB，但缓存被清空后重访问会产生短暂磁盘 I/O。

### 评分系统

Thompson Sampling Beta(α, β)，α=2, β=1 先验：

| 条件 | 得分 | 说明 |
|------|------|------|
| 系统核心进程 | 0.0 | 30+ 进程列入白名单，永不清理 |
| 未知进程 / 采样 < 2 次 | 0.35 | 探针模式判定，不直接清理 |
| 有足够样本 | Beta(2,1) 采样 | 区间 (0,1)，越高越值得清理 |

学习引擎辅助指标：

| 指标 | 计算方式 | 用途 |
|------|---------|------|
| 收益 EWMA | 清理释放量的指数加权移动平均 | 预期收益 |
| 成本 EWMA | 页面错误增量的指数加权移动平均 | 预期成本 |
| 波动率 EWMA | 工作集变化率的指数加权移动平均 | 稳定性评估 |
| Z-score | 工作集偏离基线的标准差倍数 | 异常检测（阈值 3.0） |
| 趋势斜率 | 30 点工作集的最小二乘回归 | 泄漏检测 |
| ROI | 收益 EWMA / 成本 EWMA | 排序和优先级 |

### 安全拦截

9 层防护链按顺序判定，任一条件触发即拦截：

| 层级 | 拦截条件 | 目的 |
|------|---------|------|
| 1 | 进程名匹配 system/svchost/dwm 等 30+ 白名单 | 保系统稳定 |
| 2 | 用户配置的 never 排除列表 | 用户自定义排除 |
| 3 | 当前在前台 | 不干扰正在用的程序 |
| 4 | CPU ≥ 1.0% | 正在运行的不碰 |
| 5 | 工作集 < 30 MB | 太小没意义 |
| 6 | Thompson θ < 阈值（默认 0.80） | 评分不够不碰 |
| 7 | 距上次整理 < 300 秒 | 避免频繁整理 |
| 8 | 上次整理 page fault 异常增加 | 该进程不适用 |
| 9 | 系统目录下且 θ < 0.90 | 额外保护系统进程 |

### PID 控制参数

守护模式下，PID 控制器根据当前内存使用率实时调整清理强度：

| 参数 | 值 | 作用 |
|------|-----|------|
| kp | 0.8 | 比例响应当前压力 |
| ki | 0.10 | 消除稳态误差 |
| kd | 0.15 | 压力快速上升时提前响应 |
| 目标使用率 | 55% | 低于此值不主动清理 |
| 抗饱和窗口 | 20 | 积分项上限 |

### 学习引擎参数

| 参数 | 值 | 说明 |
|------|-----|------|
| 趋势窗口 | 30 点 | 工作集趋势回归使用 |
| EWMA λ | 0.5 | 衰减因子，越高适应越快 |
| Z-score 阈值 | 3.0 | 异常检测 |
| 最少样本 | 3 | top() 排序的参与门槛 |
| 先验分布 | Beta(2,1) | 偏向可清理，但需要实际证据 |

---

## 快速开始

```bash
# 从源码运行
pip install pyyaml          # 可选，不改配置可不装
python memwise_gui.py       # 启动图形界面
python memwise.py optimize  # CLI 一键整理
python memwise.py daemon    # CLI 守护模式
```

```bash
# 打包成单文件 exe
pip install pyinstaller
pyinstaller --onefile --noconsole --name MemWise --add-data "core;core" memwise_gui.py
```

打包后直接运行 `MemWise.exe`，无需 Python 环境。关闭窗口自动最小化到托盘。

---

## CLI 命令

| 命令 | 用途 |
|------|------|
| `status` | 系统内存状态概览 |
| `learn <分钟>` | 学习模式（只观察，不动手） |
| `optimize` | 标准优化（基于历史评分） |
| `optimize --quick` | 快速优化（基于当前特征） |
| `daemon` | 守护模式（Ctrl+C 退出） |
| `profile <pid>` | 查看进程画像 |
| `auto-start on\|off` | 开关普通开机自启 |
| `install-service` | 安装管理员 Scheduled Task（开机自启+最高权限） |
| `install-service remove` | 移除 Scheduled Task |
| `reset` | 恢复出厂设置 |

---

## 安全保证

### 不做

| 操作 | 原因 |
|------|------|
| 不杀进程 | 核心代码无 TerminateProcess |
| 不挂起线程 | 核心代码无 SuspendThread |
| 不改优先级 | 核心代码无 SetPriorityClass |
| 不注入 DLL | 无 CreateRemoteThread / LoadLibrary |
| 不改注册表 | 开机自启用快捷方式 + Scheduled Task |
| 不联网 | 无 socket / requests / urllib |
| 不读用户文件 | 不扫描文档/照片等个人文件 |

### 只做

1. **EmptyWorkingSet** — 让进程把闲置物理页换出到 pagefile
2. **EmptyStandbyList** — 回收文件缓存占用的空闲页
3. **写 memwise_state.json** — 存储学习数据，下次启动继续

---

## 项目结构

```
memwise/
├── memwise_gui.py          GUI 入口 (tkinter, 863 行)
├── MemWise.exe             打包好的单文件 exe
├── memwise.py              CLI 入口 (277 行)
├── core/
│   ├── winapi.py           Win32 API 纯 ctypes 绑定 (742 行)
│   ├── learner.py          Thompson Sampling + EWMA 学习引擎 (335 行)
│   ├── judger.py           PID 控制器 + 9 层安全判定 (209 行)
│   ├── cleaner.py          3 层清理编排 (294 行)
│   └── sniffer.py          进程快照采集 (48 行)
├── config/config.yaml      配置文件
├── assets/memwise.ico      应用图标
├── scripts/
│   ├── memwise.bat         CLI 快捷启动
│   ├── memwise_gui.bat     GUI 快捷启动
│   ├── build_exe.bat       打包脚本
│   └── _validate.py        21 项验证
└── README.md
```

---

## 许可证

MIT License

Copyright (c) 2026 fuguangbeta
