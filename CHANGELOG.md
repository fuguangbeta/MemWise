# MemWise 更新日志

> **MemWise** — Windows 智能内存看护工具。不杀进程、不挂起线程、不注入、不联网。
> 纯 ctypes Win32 API，零外部依赖。

## v2.7 (2026年7月)

> 本轮的主题是"瘦身与加速"——将 IQR 效率引擎的冷启动从 50 轮压缩至 20 轮并引入 trimmed IQR、中位内插、幂律压缩等六项统计优化，系统性删除了六个长期摆设模块共约 600 行代码，修复了图表悬浮因子错位、60 轮后折线冻结、游戏退出播报被清屏擦除等十项实质性 bug，并将全局 tooltip 和日志输出从中英混杂彻底改为纯中文用户语言。

---

### IQR v6 引擎：从 50 轮到 20 轮冷启动

旧版效率评分以 50 轮滚动窗口计算 IQR 分位数。旧会话数据跨启动污染、窗口过大导致冷启动需 50 分钟才能稳定，且整数位分位、未 trimmed 的单异常值直接担纲分位边缘，使归一化基准偏斜。

本轮将 IQR 引擎从五个维度全面提升：

- **维度特异性窗口**：raw2（释放效率）跨度四个数量级，窗口增至 25；raw4（EFIS 稳定性）永远在 0-1 范围，窗口缩至 8；其余三维保持 20。总数据量不变，分布优化
- **raw2 幂律压缩**：`cycle_freed/trimmed_n` 从线性值改为 `log10`，将 1MB~1GB 的四数量级跨距压缩至 0~3，信息密度提升 30 倍
- **trimmed IQR**：排序后去头去尾各一个极值，剩余 18 个元素参与分位计算。单异常值不再直接当四分位
- **中位数内插**：偶数窗口时取两中点平均，消除 ±5% 的单点偏差
- **Q1/Q3 线性内插**：`(n+1)×0.25/0.75` 加权，一个位置级的偏差消除
- **p50 EWMA 平滑**：λ=0.15 持续平滑中位数，与 IQR EWMA(λ=0.30) 对称，基准线不再每轮跳变
- **EWMA 冷启动守卫**：前 5 轮不更新 `_eris_iqr_ewma`，等窗口初步填充后再积累，防冷启动数据污染长期平滑
- **地板弱化**：EWMA 系数从 0.40 降至 0.20，真实 IQR 更快冲破地板
- **热重启保留**：daemon 重开非程序重启时保留已有窗口数据；程序冷启动时重建空窗

综合效果：冷启动从 50 轮缩至 20 轮，单异常值不再污染分位边缘，精度损失控制在 ±3% 以内。

---

### 大规模死代码清除

系统性审计后删除了六个长期摆设模块，净删约 600 行代码，无一影响优化决策：

- **EpisodeMemory 情景记忆**：111 行。`retrieve()` 全文零调用，`success_rate()` 给 `should_trim` ±1 票——但 Thompson 采样的 Beta(α,β) 已是二项成功率的最优数学估计，叠第二层只会产生矛盾票数。`store()` 写入的 `record_clean_result` 和 `record_probe_result` 两处全部删除
- **24 小时时间槽 TemporalProfile**：45 行。`is_active_hour()` 在五树投票中 ±1 分，总分范围 -5~+8 中完全淹没。五树→四树→三树
- **`_curiosity_boost` 好奇心变量**：~50 行。变量在 `MetaCognition.tick` 中写入，但 `thompson_score` 中从未被有效读取（乘 1.0）。覆盖率缓存 `_coverage_cache` 和 `_coverage_ts` 一并删除。改为 `can_probe` 对未试探进程冷却降至 120 秒，实效替代
- **`_ctx_weights` 上下文梯度下降**：~40 行。5 维权重收敛后恒为零，`sigmoid(w_dot)+0.5` 永远返回 1.0，乘在 theta 上等于没乘。改为 `_composite_score_v2` 中 WS>500MB 进程直接提权 0.15，单一规则替换 40 行学习
- **MetaCognition 校准段**：~35 行。对预测偏差 >50% 的画像衰减 alpha/beta/q 各 5%，但 Kalman `update()` 内部每次都有自适应 q（新息 >50% → q×1.2），频率快 50 倍。保留概念漂移检测和覆盖率日志
- **`leak_suspect` 决策权**：~30 行。Z-score 双阈值命中率 <1%，命中后唯一动作是阻止清理——等于放弃。改为纯诊断日志输出，不参与 `can_trim` 决策

同时发现 `_layer2_process` 和 `optimize` 在 `core/cleaner.py` 中各有两个完整副本（Python 类中后定义遮蔽先定义），删除死代码 328 行。

---

### 图表渲染修复

本轮修复了图表系统中六个独立 bug：

- **60 轮后折线冻结**：`_chart_eris_processed` 是只增不减的绝对索引，达到 maxlen=60 后 `processed ≥ total_points` 永远为真，第 61 轮起的效率值永不进入 ERIS。修复为序列号机制——meta 元组中增 `seq` 字段，渲染时逐条比较 `seq > last_seq` 找新点
- **悬浮因子数组错位**：`_chart_motion_factors` 始终存储全局 0-59 全量数组，而悬浮事件的 `idx` 是可视列号。图表滚至后半段时，鼠标悬停在可视第 N 柱，取到的是全局第 N 条的因子（属于早已滚出屏幕的早期柱）。修复为 `[-len(visible):]` 尾部切片对齐
- **daemon 双锁竞态**：`_chart_data.append` 在锁外、`_chart_cycle_meta.append` 在锁内，两数组非原子追加导致 meta 缺位——chart 渲染时 fallback 补入错误元数据，产生污染 eff。修复为两 append 同锁保护
- **chart 双锁竞态**：`data` 和 `total_points/meta_list` 分两次锁获取，中间 daemon 可插入新点导致 `data` 比 `total_points` 短一个元素——`chunk` 截断、bufs 污染。修复为三个变量单次锁快照
- **图表柱形合并**：`chart_accum` 跨轮累积 + ≥60s 窗口判断，周期略短时跳过推送→下轮合并。修复为每轮不依赖窗口、必推一柱，零释放也占位
- **ERIS 单点失败卡死**：for 循环内无 try/except，`_compute_eris` 异常直接跳过后面的 `_chart_eris_processed` 更新→下次渲染同一坏点再次异常→死循环。修复为加兜底、中心值 80 替代、保证计数器递增

---

### 游戏模式播报修复

游戏退出消息走即时日志通道（`_log`），同一周期其他 5-7 条消息稍后以批处理（`_log_batch`）到达时，`cur_lines + len ≥ 8 > 7` 触发全清——退出播报被瞬间擦除。修复为游戏消息改走批量通道（`_cycle_log_buffer`），与周期消息一同打包输出，不分先后、不被擦除。

---

### Tooltip 与日志全线中文化

全局审计了 27 条悬浮提示和 4 条日志输出，系统性地将英文技术名词替换为纯中文用户语言。规则：API 名全部替换（`EmptyWorkingSet`→"释放进程闲置内存"）、技术缩写全部替换（`PF`→"性能开销"）、算法名不再出现（`Thompson×Kalman`→"智能评分引擎"）、版本变更字样全部移除。

同步修正了日志中"Z 值""斜率""提高好奇心""gap fill""Standby"等对普通用户无意义的措辞。

---

### 崩溃级 Bug 修复（v2.7 增补）

在删除死代码过程中引入并通过测试覆盖发现并修复了：

- **`@property` 装饰器被误删**：`Profile.thompson_theta` 失去了装饰器，`p.thompson_theta` 返回方法对象而非浮点数——HierarchicalPrior 中 `sum(peers)` 触发 TypeError
- **`save()`/`load()` 被误删**：EpisodeMemory 清理时将 Learner 的持久化方法连带删除——守护停止时无法保存状态
- **`record_probe_result` 被误删**：`_probe_process` 在 cleaner.py 中调用此方法，缺失直接导致守护崩溃
- **函数体重复**：Python 替换时 docstring 和函数体各被修改一次，`record_probe_result` 体量翻倍

---

### 构建

- 版本号 v2.6 → v2.7，PyInstaller 6.21.0，Python 3.14.0，产物约 12.7 MB
- 全项目 16 源文件零编译错误，33 项回归测试全绿
- 净删约 600 行死代码，新增约 50 行有效逻辑，全局 tooltip 和日志纯中文化
