# MemWise v1.3 — 智能内存看护

Windows 内存整理工具。**不杀进程、不挂起线程、不注入、不联网。**
纯 ctypes Win32 API，零外部依赖。

---

## 快速开始

```bash
pip install pyyaml          # 可选，不改配置可不装
python memwise_gui.py       # 启动图形界面
python memwise.py daemon    # CLI 守护模式
```

[下载 exe](https://github.com/fuguangbeta/MemWise/releases) → 即下即用，无需安装。

---

## 核心特性

| 特性 | 说明 |
|------|------|
| **3层清理引擎** | Layer1 系统级(7种操作)+Layer2 进程级(Thompson排序)+Layer3 深度重复 |
| **Thompson 学习** | 每个进程独立贝叶斯模型，成功/失败自动更新θ，越清越精准 |
| **EFIS 效率反馈** | 实验日志+自动回滚+场景记忆+窗口化评估，参数自我进化 |
| **PID 控制器** | 目标45%内存，动态调节力度，低压省资源高压快响应 |
| **预判式清理** | WS增长斜率检测，快速增长进程优先清理 |
| **探索奖励** | >10分钟未清理进程获得好奇心加分，冷门进程不被忽略 |
| **泄漏检测** | 双阈值(Z>2.0+斜率>0.005)，自动标记内存泄漏进程 |
| **游戏模式** | 自动检测70+游戏+全屏检测，后台激进清理前台更强保护 |
| **动态tick** | 高压10s快速响应，低压60s省电，自动切换 |

## 界面功能

- 内存彩色条（绿/黄/橙/红四档）
- 实时柱状图显示每轮释放量
- 进程排行+单击终止
- 守护模式日志+智能清屏
- 系统托盘图标（颜色指示内存状态）
- 全局热键 Ctrl+Shift+M
- 排除列表/设置面板

## 命令行

```
memwise.py status         查看内存状态
memwise.py learn [分钟]   学习进程行为
memwise.py optimize       一键优化
memwise.py daemon         守护模式
memwise.py profile <PID>  查看进程画像
```

## 系统要求

- Windows 10 20H1+ / Windows 11
- 管理员权限（缓存清理需要；进程清理不需要）

## 更新日志

详见 [CHANGELOG.md](CHANGELOG.md)

---

> [GitHub Releases](https://github.com/fuguangbeta/MemWise/releases) — 下载最新版本
