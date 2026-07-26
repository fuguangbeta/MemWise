# MemWise 更新日志

> **MemWise** — Windows 智能内存看护工具。不杀进程、不挂起线程、不注入、不联网。
> 纯 ctypes Win32 API，零外部依赖。

---

## v2.6 (2026年7月)

> 本轮的主题是"只留一条线"——将效率引擎从 daemon/chart 双重计算彻底重构为单线渲染驱动，根除困扰用户的因子词条混乱问题。同时打通了持久化的完整校验链路，修复了 5 个会导致 AttributeError 崩溃或数据静默丢失的阻塞性 bug，并为极性区间 (≥100% / ≤60%) 设计了独立的效率标签体系。

---

### ERIS 单线重构

v2.5 及之前所有版本中，ERIS 效率评分在 daemon 线程和 chart 渲染中各算一次：daemon 负责更新分位数窗和因子状态，chart 负责读取并显示。两套调用参数不完全对齐，中间没有任何同步机制——这是因子词条"长时间必定混乱"的根本原因。

本轮将 ERIS 彻底重构为单线驱动：

- **daemon 不再调用 `_compute_eris`**：守护线程只负责收集原始数据（释放量、trim 计数、fail 计数、内存百分比），以柱形为单位存入 `_chart_data` 和 `_chart_cycle_meta`，两数组在同一把锁内原子追加
- **chart 渲染成为唯一 ERIS 入口**：`_do_draw_chart` 在处理过程中遍历未进入分位数窗的新图表点，逐点调用 `_compute_eris(update_state=True)` 更新分位数窗、效率值、因子状态，结果填入 `_eff_data` 和 `_eff_factors`
- **单次锁快照对齐**：`data`/`total_points`/`meta_list` 三个变量在同一 `with self._chart_lock` 内一次性读取，消除了此前分两次加锁导致的竞态窗口
- **`_eris_lock` 线程互斥**：IQR 分位数窗的读写由独立锁保护，daemon 无法再污染 ERIS 状态
- **每轮必推柱形**：不再依赖 ≥60 秒计时窗口（此前周期略短于 60 秒时累积跳过一轮导致柱形合并），改为每轮必定推送
- **单点失败不阻塞**：ERIS 处理循环内加 `try/except` 兜底，单个数据点的计算异常用中心值 80 替代，保证 `_chart_eris_processed` 永远递增

---

### 影响因素词条算法重写

因子词条的判定逻辑此前存在三个长期未被发现的错误，叠加后导致"正面出负面、陡变出平稳、平稳出陡变"的混乱现象：

- **防振荡三支不统一**：≥100 和 ≤60 分支的防振荡条件与中性分支自相矛盾——极性分支使用了"同向压制"而非记忆规则规定的"反向压制"，导致效率持续 ≥100 时同一维度每两轮被错误跳到次优维度
- **"相对平稳"不更新防振荡状态**：在平稳期 `_eris_prev_factor_dim` 和 `_eris_prev_factor_pos` 保持旧值不更新，平稳期越长方向残留越久，后续活跃期误判概率越大——修复为平稳期重置 `factor_dim=-1, factor_pos=None`
- **极性分支污染趋势数组**：≥100 时追加 `+1`、≤60 时追加 `-1` 到趋势数组，三连极值后跌落正常范围时，中性分支误判为"持续改善/下滑"——修复为极性分支追加 99/-99 标记值并加强值域守卫（`last_val in (+1, -1)`）

此外新增极性区间独立标签体系：`eff ≥ 100` 时必定追加"🚀效率超常"，`eff ≤ 60` 时必定追加"⚠效率异常"，取代原本在此区间从不输出的"持续改善/下滑"标签。

效率折线前三轮虚线判定也从此前的局部可见索引修正为全局绝对索引，与折点逻辑统一。

---

### 持久化校验体系

所有由运行产生的持久化数据文件补齐了完整的加载校验与降级路径：

- **`memwise_eris_ewma.json`**：加载时严格校验——5 维 × ≤50 元素，每个值必须是有限实数，iqr_ewma 必须是非负有限值。任何一项不通过 → 静默丢弃、冷启动。保存改为原子写入（tmp → replace）
- **`memwise_state.json`**：加载失败或数据损坏 → 返回空 Learner（非 None），防止后续 AttributeError
- **`memwise_efis_state.json`**：旧版残留的 0 值 `_symptoms` 加载时自动过滤清除。`_symptoms` 触发后改为 `pop` 而非 `=0`，防止 dict 无限膨胀。`_adjust_log` 内存中超过 200 条时截留 100 条
- **跨会话隔离**：`_eris_prev`、`_eris_prev_factor_dim`、`_eris_prev_factor_pos`、`_eris_ewma_trend` 在每次 daemon 启动时强制重置，防止旧会话数据污染新会话的因子判定
- **`_probe_last_time`**：新增 30 分钟过期清理，防止进程名 dict 无限膨胀

---

### Bug 修复汇总

本轮修复了多个会导致崩溃或数据丢失的阻塞性问题：

- **`Profile._info_msgs` 未初始化**：`__slots__` 声明了但 `__init__` 和 `from_dict` 均未赋值，泄漏检测触发 `append` 时抛出 `AttributeError` 崩溃——已在两处补齐初始化
- **`timeout_count` 不在 `__slots__`**：新增属性未声明，赋值时 `AttributeError` 崩溃——已加入 `__slots__` 并在 `__init__` 初始化为 0
- **`self._trim_executor` 访问错误**：GUI 类无此属性，应为 `self.cleaner._trim_executor`——已修正
- **harvest `result` 未预初始化**：`concurrent.futures.TimeoutError` 之外的异常会导致 `result` 未赋值，后续访问抛出 `NameError`——已添加 `result = None` 预初始化 + 双重异常捕获 + None 检查
- **泄漏检测消息静默丢失**：`PareLearner.pop_info()` 只收集 Learner 自身消息，各 Profile 的 `_info_msgs` 从未被收集——修复为遍历 `self.profiles.values()` 收集并清空
- **紧急触发日志跨线程调用 Tkinter**：`self._log()` 直接从 daemon 线程操作 Tkinter Text widget，长时间运行后 widget 内部状态被破坏导致消息顺序混乱——改为通过 `_msg_queue` 分发
- **`interval` 变量不一致**：deadline 基于 CFG 的 `interval=30` 计算而超时判断基于后来覆盖的 `interval=60`，导致 deadline 仅 27 秒且超时债务计算完全错误——统一为 60 秒，提前到 deadline 之前设置

---

### 时序超时防御体系

守护周期面临的最坏情况——某个进程在内核态 `EmptyWorkingSet` 卡死不返回——此前没有任何保护。本轮建立了覆盖全链路的超时防线：

- **单进程 trim 8 秒 / probe 4 秒硬超时**：`future.result(timeout=8/4)`，超时后跳过该进程、标记失败、Thompson 惩罚，不阻塞后续进程队列
- **harvest optimize 30 秒硬超时**：每轮最后一次全量收割用独立线程执行 + 30 秒超时包装，超时后返回 `_partial` 标记，gap-fill 阶段累积的成果仍正常计入
- **周期补偿机制**：`overtime_debt` 追踪累计超时秒数（上限 30 秒），下一轮 deadline 自动扣除。提前完成则债务递减，两轮内回归 60 秒节奏
- **超时后跳过 EFIS/MetaCognition 诊断**：harvest 超时产生的零数据不污染自适应调参，效率值正常显示（零值真实反映超时影响）

---

### 超时正向反馈闭环

超时不只防御，更让 Learner 从中学习：

- **递增冷却**：`timeout_count`（仅内存不持久化）记录超时次数，`mark_failed(fail_count=tc)` 冷却倍数从 1× 递增至 4×。成功清理后 `mark_trimmed` 自动衰减计数
- **Thompson 惩罚**：超时进程执行 `record_clean_result(ok=False)`，beta+1 降低 θ，Kalman 过程噪声 q 提升增加不确定性估计
- 同时保留 `can_trim` 判定——超时进程只是冷却更长、θ 更低，不会被永久拉黑，仍有机会在后续轮次重新尝试

---

### 构建

- 版本号 v2.5 → v2.6
- PyInstaller 6.21.0，Python 3.14.0
- 产物约 12.7 MB
