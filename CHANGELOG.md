# MemWise 更新日志

> **MemWise** — Windows 智能内存看护工具。不杀进程、不挂起线程、不注入、不联网。
> 纯 ctypes Win32 API，零外部依赖。

## v3.1.5 (2026年8月)

> v3.0.1 发布后的维护增量：实测发现每轮优化量（200-500MB）与内存实际波动（5%+ 来回震荡）严重不符，对统计链路全面审查后确认两处结构性遗漏——Layer3 阶段 C 的系统释放量完全未计入图表数据源；系统操作按函数级 avail 始末差计释放量，操作释放的同时被其他进程分配吞减，净变化口径系统性低估。本轮以"每个小操作释放量的标量总和"为口径重构统计链路，并确立"释放量 + 净下降"双指标分工制。共 5 项维护，回归测试 37 项全绿。

---

### 统计链路重构：每轮优化量回归真实

- **逐操作测量**：`_layer1_memreduct` 每个系统操作（ws_all/modified/standby/standby_low/volume/registry/compress/filecache）操作前后各读一次 avail，>0 标量累加进 `freed_bytes`——替代函数级一次始末差（净变化会吞减释放量：操作释放的同时其他进程分配即被抵销）
- **Layer3 释放接入**：`_layer3_deep` 预处理与阶段 C（deep_compress/脏页写回/deep_standby/卷缓存/文件缓存/内存合并）逐操作测量并累加进 `freed_bytes`——此前每轮数百 MB 只进 `layer3_extra`（EFIS 诊断专用），图表/统计栏/周期日志完全缺失；`layer3_extra` 保留供 EFIS 判断 Layer3 价值
- **双指标分工制**：明确"释放量"（`freed_bytes` 差分 = 所有小操作标量总和）为主指标、"净下降"（`net_freed` = 内存真实变化）为附注——手动优化与 CLI 文案统一为"合计释放 X MB · 内存净下降 Y MB"，图表/日志/统计栏/CLI 口径一致
- **死代码清理**：`cycle_freed_total`（累计无消费）、`total_freed`（中间量未显示）、`opt_done` 死字段（freed/net 从未被消费）删除

---

### 构建

- 版本号 v3.0.1 → v3.1.5（Mutex/窗口标题/CLI/README/测试同步，新 mutex 避免与旧版互斥冲突）
- 发布版 exe = 冷启动默认配置（`datas=[]` 不打包本机 config.yaml，首次运行回退 `DEFAULT_CFG`）
- PyInstaller 6.21.0，Python 3.14.0，产物约 13.3 MB（`dist/MemWise.exe`）
- 37 项回归测试全绿，全项目零编译错误
