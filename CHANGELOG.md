# MemWise 更新日志

> **MemWise** — Windows 智能内存看护工具。不杀进程、不挂起线程、不注入、不联网。
> 纯 ctypes Win32 API，零外部依赖。

## v3.6.47 (2026年8月)

> v3.5.14 发布后的全量维护增量：全项目 36 项问题清单逐一核实与修复，并在实施中额外发现修复 3 项问题一并修复；专项将长期闲置的 `learning_rate` 参数以最科学方式接入反馈学习主通道并配套双向诊断规则。共 47 项维护，回归测试 44 → 69 项全绿。

### 系统保护与游戏模式

> 实测确认进程名来自进程快照必然带 `.exe` 后缀，而核心进程保护名单是无后缀集合——四个消费点全部用 `name in SYSTEM_CORE` 比较，`svchost.exe`/`explorer.exe`/`dwm.exe` 等系统进程实际可被清理、试探与降权；用户自定义游戏名单同理因运行管线缺键而永久不生效。

- 修复了系统核心进程保护名单全面失效——派生带后缀集合 `SYSTEM_CORE_EXE` 并新增统一入口 `_is_system_core()`（同时兼容带/不带后缀），`can_trim`/`can_probe`/`thompson_score`/Layer2 四处消费点全部替换
- 修复了用户自定义游戏进程名单永不生效——GUI/CLI 运行管线构造（`jcfg`）补 `game_processes` 键，守护热加载与管理窗口添加/删除即时同步运行时名单
- 修复了游戏模式手动关闭后自动检测永久失效——手动关闭即恢复自动检测

### 认知引擎与算法学习

> `learning_rate` 参数自引入以来仅在注释中标注「待专项实验」，全链路无消费方；本次以「反馈 EWMA 学习率」语义完成天花板级接入：参数域重定义为零回归（默认 0.50 = 原 `EWMA_LAMBDA`），并配套振荡/低效双向诊断规则。同期修复认知引擎多项量纲与收敛缺陷。

- 新增了 `learning_rate` 参数全链路接入：参数域 `0.10-0.90` 默认 `0.50`，接入 `record_clean` 收益/成本 EWMA 主通道（fast/slow 趋势通道保持固定防漂移），`_diagnose` 新增双向规则（系统振荡大→降以平滑反馈、稳定且低于目标但释放平庸→升以加速适应），调参日志补中文名「学习速率」
- 修复了 Kalman 估计被 probe 的 0 观测污染（`record_probe` 无条件更新 vs `record_clean` 仅 freed>0，实测预期释放被拉向 0 与真实相差 13 万倍）——统一为 freed>0 才更新
- 修复了 Kalman 长间隔乘性无界膨胀（`p ×= decay` 使增益 k→1、单次观测完全覆盖估计、丧失平滑）——移除乘性，标准 `(1-k)p + q·dt` 且上限 clamp 400
- 修复了泄漏检测相对斜率单位错误（slope 被按 MB 缩放实际放大 2^20 倍，条件几乎恒真导致系统性误报「疑似泄漏」）——改为 `slope / ws_avg` 无单位比率，与注释 0.5%/tick 一致
- 新增了 `PareLearner.top(n)`（CLI `learn` 命令此前必然 `AttributeError` 崩溃）——ROI 降序、样本≥2 过滤，返回 `(name, roi, theta, profile)` 与 CLI 解包严格匹配
- 优化了 `Profile.roi` 量纲统一为 MB/PF（与 `KalmanProfile.roi` 一致），CLI 表格与学习日志表头同步标注单位
- 修复了策略树5 peers 均值包含自身（高收益进程优势被自身抬高均值而低估）——`q is not p` 排除
- 修复了 ERIS 早期窗口（2-3 样本）归一化退化为 ±1 二值（冷启动虚假「🚀效率超常/⚠效率异常」污染趋势链）——分母改 p50×10% 相对尺度
- 修复了 ERIS 冷启动中位数 EWMA 虚高（从 0 起步仅含样本 15%，首 5 轮维度分被 clamp 到 130）——nL<5 用原始中位，EWMA 未收敛不参与
- 修复了 ERIS Q1 线性内插负索引回绕（nT=2 时 `T[-1]` 取到最大值、加权方向相反）——插值下界钳 0
- 修复了 `learner.load` 单个坏画像导致全部画像丢失（整循环裸 except）——逐条跳过坏条目，`from_dict`/Kalman 加载全面数值类型清洗（`_num` 保护）
- 修复了 EFIS 无实际调整时重播上一条调整记录（曾见 0.60→0.50 连续重播 11 轮）——仅在日志新增时播报
- 修复了 `efis.save` 非原子写与 tmp 残留（dump 在 try 外）——写入入 try、失败清理临时文件

### 守护与并发

> 守护线程的停止标志只在周期末分段睡眠中检查——点「停止」后旧线程仍会继续清理最长一整周期，期间再次启动守护即产生双线程并发清理；ERIS 图表线程在守护增键时直接迭代画像字典，存在 `RuntimeError` 崩溃风险。

- 修复了守护停止延迟最长一整周期（gap/harvest 三个内部循环不检查停止标志，停止后最多继续约 90 秒）——循环体全部加 `daemon_running` 检查
- 修复了守护停止后立即重启产生双守护线程并发（旧线程 harvest 与新建线程同时 optimize/feed/save）——启动前 `join(timeout=1.5)` 等待旧线程收尾
- 修复了单实例互斥在权限拒绝时双开（管理员实例运行时普通进程 `CreateMutexW` 返回 `ERROR_ACCESS_DENIED` 而非 `ALREADY_EXISTS`）——两种错误码均视为已有实例并激活旧窗口，无窗口时防双开退出
- 修复了守护线程直接读取 Tk 变量（`mode_var.get()` 非线程安全）——改读 `CFG["clean_mode"]` 配置镜像（界面切换已实时同步）
- 修复了守护线程全局 except 终止（EFIS/元认知 tick 任一异常即整线程死亡）——局部防护记录日志后继续循环
- 修复了 ERIS 计算迭代画像字典并发崩溃（守护线程随时 `get()` 增键）——迭代前 `list()` 快照

### 界面与设置

> 设置面板三处历史遗留：关闭按钮行为 tooltip 串绑到「每次询问」、日志开关 tooltip 双重绑定重叠、三个滑块拖动即高频全量写盘。

- 修复了设置面板「关闭按钮行为」tooltip 串绑（1206 行错位残留绑定，显示「每次询问」与实际不符）
- 修复了「记录运行日志到文件」tooltip 双重绑定重叠显示（1345 行残留旧绑定）
- 优化了清理操作标签文案「（留空 = 按模式自动选择）」→「（未勾选 = 不执行对应系统清理）」（与 `clean_operations` 勾选语义一致）
- 移除了统计栏 tooltip 中已删除的「内存压缩」残留文案（系统杂项/累计释放两处）
- 优化了设置面板三个滑块（紧急阈值/进程清理深度/守护清理间隔）拖动不再高频全量写盘——`command` 仅更新显示，`<ButtonRelease-1>` 松开才保存
- 移除了设置面板无绑定死代码 `save_and_close`

### 打包与健壮性

> PyInstaller 窗口模式（`console=False`）下 `sys.stderr` 为 `None`，异常路径 `print(file=sys.stderr)`/`print_exc()` 自身抛 `AttributeError`——最严重时手动优化异常后 `opt_done` 消息不入队，优化按钮永久禁用；本机实际被卡巴斯基拦截测试时捕获启动 `NameError`。

- 修复了打包窗口模式下 10 处异常输出自身崩溃（`_ERR = sys.stderr or open(os.devnull, "w")` 统一兜底：GUI 8 处 + config 2 处）
- 修复了看门狗 `watchdog.json` 非原子写（truncate+write vs 主进程 tmp+replace，并发可致半截 JSON、崩溃后不恢复）——统一 tmp+replace 原子协议
- 修复了日志目录与数据目录计算不一致（frozen 时日志在 exe 目录、状态在项目根；Program Files 部署日志静默失效）——统一 base 路径，看门狗状态文件同步
- 优化了 CLI 控制台 emoji 进度输出在 GBK 重定向时的 `UnicodeEncodeError`——`stdout.reconfigure(errors="replace")`
- 优化了 f-string 嵌套同引号语法（依赖 Python 3.12+，低版本解释器直接启动失败）——拆出中间变量
- 修复了配置浅拷贝共享列表污染 `DEFAULT_CFG`（`toggle_op` append 泄漏进默认值）——加载时列表深拷贝
- 修复了 `core/judger.py` stderr 兜底缺 `import os` 的启动 `NameError`（构建测试捕获，扫描确认其余文件无同类问题）

### 清理引擎

> 三层清理引擎三处边界问题：Layer3 深度层入口被 ws 开关单键门控（勾选 standby/modified 但取消 ws 时整个深度层跳过，与操作级开关语义冲突）；阶段 D 一次性提交无在途限制；滑动窗口分批提交在池线程卡死时无限空转。

- 修复了 Layer3 深度层入口门控错误——ws/standby/modified 任一勾选即执行（volume/filecache/registry 单独勾选不触发深度层，与「深度操作由 modified/standby 开关控制」设计一致）
- 优化了 Layer3 阶段 D 清理一次性提交堆积（几十个任务无在途限制拖垮线程池）——复用滑动窗口分批提交（在途限制 + 总预算 30s）
- 优化了滑动窗口分批提交在池线程卡死时的无限循环（每 4s 空转永不退出）——总预算（probe/trim 20s、默认 60s）超时丢弃剩余排队项，已提交任务自然完成
- 修复了 `cleaner.__init__` 死代码 `prev_freed`（依赖恒 False 的 `hasattr`，删除后残留引用致启动 `NameError`，冒烟测试捕获一并修复）
- 修复了 `get_parent_process_name` 手写字节偏移在 64 位下错位（父进程名匹配错乱，浏览器子进程树加分错配）——`PROCESSENTRY32W` 结构遍历（与 `enum_processes` 同源，32/64 位全兼容）

### 配置与周期

> 守护周期被硬编码 60 覆盖了配置键 `interval`——用户调整配置永不生效，且 GUI 与 CLI 守护行为不一致。

- 修复了 `interval` 配置键被守护硬编码覆盖（存在但永不生效）——守护周期改由配置驱动（默认 60），`DEFAULT_CFG` 同步为 60 保持现行为

### 测试与文档

> 回归测试存在两类失真：ERIS 归一化/因子选择是文件内复制的内联副本，与生产代码已产生行为分歧（`round(eff)>=100` vs `eff>=100`、窗口上限 50 vs 维级窗口）；4 处断言恒真（EFIS tick 字面量 `True`、PolicyVoter 仅构造、load 永不返回 None、top 同值排序）。

- 新增了 ERIS 纯函数核心 `core/eris.py`（`iqr_dim` 单维归一化 / `validate_state` 状态校验）——生产 `_compute_eris`/`_load_eris_ewma` 与回归测试共用同一实现，根除测试副本分歧
- 修复了回归测试恒真断言 4 处——替换为真实行为验证（EFIS 10 轮真实调参、PolicyVoter 高压通过/否决决策、ROI 有区分度排序）
- 新增了回归断言 20+ 项（保护名单派生集与带后缀命中、Kalman 有界/加载清洗、probe 0 观测不污染、ROI 量纲、learning_rate 快慢适应、load 坏画像容错、config 深拷贝、peers 排除自身、ERIS 冷启动/早期窗口/边界、父进程名 64 位）——回归 44 → 69 项全绿
- 更新了 README 两处（`learning_rate` 参数域 0.50/0.10-0.90 与已接入语义、`interval` 默认 60 与生效说明）
- 优化了核心注释口径（judger WS 基线「20 分钟判定窗口/1 小时过期」三处对齐；policy 五树框架明确 should_trim 用树 1/2/5、should_probe 用树 1/2/3/5、树 4 预留）
- 更新了项目记忆（memwise-overview：36 项修复知识、ERIS 纯函数、EFIS 口径、回归基线）

---

### 构建

- 版本号 v3.5.14 → v3.6.47（同步面：Mutex/窗口标题/FindWindowW/FindWindowExW/CLI/docstring/测试 docstring/README 标题，新 mutex 避免与旧版互斥冲突）
- 69 项回归测试全绿，零编译错误
