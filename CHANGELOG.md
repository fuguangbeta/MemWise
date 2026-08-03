# MemWise 更新日志

> **MemWise** — Windows 智能内存看护工具。不杀进程、不挂起线程、不注入、不联网。
> 纯 ctypes Win32 API，零外部依赖。

## v3.4.19 (2026年8月)

> v3.3.10 发布后的维护增量：清理操作开关全面生效并移除两个实测无效的伪功能；守护链路可靠性加固（崩溃恢复续守护/停止即时/harvest 与 trim 排队防叠加防误罚）；日志去重与 EFIS 诊断播报修正；主窗口与任务栏图标修复。共 19 项维护，回归测试 37 项全绿。

### 清理操作与伪功能移除

> 系统级清理此前按模式硬编码操作集，设置面板开关形同虚设；「内存压缩触发」「内存合并」经实测（Win11 26100 内核拒绝 opcode 7/9/11 与页合并控制接口 172）为伪功能，原实现分别与待机缓存清理、脏页写回重复执行。

- 修复了系统级清理无视设置面板开关的问题（`_layer1_ops` 键映射：开关优先，quick/normal/deep/full 与守护中即时清理全部按勾选执行；normal 改 `full=False` 杜绝误触发系统级全清 WS）
- 移除了「内存压缩触发」开关（实测系统无手动压缩 API，原为低优先待机清理重复调用；连带移除 `trigger_memory_compression`/`clean_compress` 及统计键）
- 移除了「内存合并」开关（实测页合并控制接口不存在，原为脏页写回重复调用；连带移除 `combine_memory_lists`/`clean_combine_lists` 及统计键）
- 优化了 Layer3 深度预处理归属（`deep_compress` 由 modified/standby 开关共同控制，默认行为不变）

---

### 守护链路可靠性

> 崩溃恢复后守护不自动续跑、停止守护最长延迟 60 秒、harvest 超时任务与下一轮清理叠加、trim/probe 排队任务超时被误罚、图表全零释放轮除零崩溃——守护链路五处缺陷本轮集中修复。

- 修复了崩溃恢复后守护模式不自动续跑（`watchdog.json` 的 `daemon` 标志在守护启动/停止时同步，此前恒 false；`os.replace` 加 3 次重试抗杀软瞬时锁）
- 修复了停止守护最长延迟 60 秒（周期末睡眠改 0.5s 分段 + `daemon_running` 即时检查）
- 修复了 harvest 超时任务与下一轮清理叠加（超时 future 挂 `_pending_harvest`，下轮开头尽力收尾）
- 修复了 trim/probe 排队任务超时被误罚（`_bounded_submit` 滑动窗口分批，超时判定基于任务真实执行时长，排队不计时；异常任务降级不再炸穿优化流程）
- 修复了图表全零释放轮除零崩溃（`max_val` 保护，零释放轮正常渲染占位柱）
- 修复了进程排行 CPU 列按字符串排序（`_sort_key_c` 支持 `%` 数值解析）
- 优化了主界面初始化结构（learner/judger/UI 构建从 `after(100)` 回调错挂移回 `__init__`，消除半初始化空窗）

---

### 认知决策与诊断

> 试探决策树5「因果好奇」因 `candidates` 从未传入恒加分；EFIS 无调整轮重复播报上次调参记录造成"反复调参"假象；顶格参数的历史症状残留无限累积。

- 修复了试探决策树5"因果好奇"恒加分失效（改按 `_probe_last_time` 近期未评估真实判定）
- 修复了 EFIS 无调整轮重复播报上次调参记录（`_format_log` 移入 `if diag` 内）
- 修复了 EFIS 顶格症状残留累积（`load()` 清洗顶格/未知参数症状，清除 `pid_kd+` 264 类历史残留）

---

### 日志与界面

> 周期摘要与 EFIS 消息经"直写 + 批量"双通道各落盘一次形成重复；主窗口/任务栏图标在窗口映射后失效显示默认图标。

- 修复了运行日志双通道重复落盘（周期摘要/[EFIS] 消息只保留 `[清理]`/`[调参]` 直写一条，GUI 日志区改纯显示 `_log_batch(to_file=False)`）
- 修复了主窗口/任务栏图标失效（映射前同步设置 + HICON 幂等缓存零泄漏 + 映射后兜底 + `SWP_FRAMECHANGED` 强制刷新）
- 移除了 8 处无调用方死代码（`PolicyVoter.update_weights`、`trim_batch`、`get_process_private_ws`、`load_app_icon`、`clean_standby`、`clean_standby_low`、`_clear_registry_cache`、`_layer1_light`）
- 修正了五处过时注释与 docstring（ERIS v6 公式 40/维级窗口、probe PF 阈值 120、can_probe 冷却 10 分钟、meta 两维、learner 旧 Thompson 注释）

---

### 构建

- 版本号 v3.3.10 → v3.4.19（Mutex/窗口标题/CLI/README/测试同步，新 mutex 避免与旧版互斥冲突）
- 发布版 exe = 冷启动默认配置（`datas=[]` 不打包本机 config.yaml，首次运行回退 `DEFAULT_CFG`）
- README 全量同步（2.1 节开关优先语义、操作表删两行、模式表注记、设置面板 6 开关、配置默认值，中英双语）
- PyInstaller 6.21.0，Python 3.14.0
- 37 项回归测试全绿，零编译错误
