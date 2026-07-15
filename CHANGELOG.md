# MemWise 更新日志

> **MemWise** — Windows 智能内存看护工具。不杀进程、不挂起线程、不注入、不联网。
> 纯 ctypes Win32 API，零外部依赖。

---

## v1.8 (2026年7月)

> **统计数据完整性彻底修复** — `_layer1_memreduct` 新增系统级释放量追踪，一条 `avail` 差值测量覆盖 gap-fill、blitz、optimize 全部三条调用路径，填补了自 v1.7 引入 8 步内核管线以来系统级清理（`empty_all_working_sets`、standby purge、文件缓存清空等）的字节从未被计入 `freed_bytes` 的缺口。fast-track 从裸 `winapi.empty_ws()` 回退到已有的 `quick_retrim()`，恢复 per-process WS 差值字节追踪。至此全部 4 条释放路径完整覆盖，`cycle_freed` 数据首次与系统实际内存变化一致。
>
> **GUI 长期运行稳定性根治** — 修复托盘最小化后恢复窗口的白屏→黑线→卡顿→崩溃问题。根因为四层并发缺陷：(1) `<Configure>` 事件在 `deiconify` 时无防抖触发 3–5 次完整 ERIS 五维重算；(2) `_draw_chart` 无重入保护且异常后标志永锁；(3) withdraw 状态下 `_refresh_mem` 持续操作未映射 Canvas；(4) 嵌套事件循环中直接调用绘制。通过 Configure 120ms 防抖合并、`_drawing_chart` 重入保护+可见性检查+强制复位、`_show_window` 150ms 延迟渲染、`_refresh_mem` withdraw 拦截、`_dae_stopped` 100ms 延迟调度共五层防御根治。
>
> 累计修改 2 个核心文件（`cleaner.py` +7 行、`memwise_gui.py` +35/-4 行），README 全面审计修正 9 处（版本号、情景记忆/因果推理算法描述与代码对齐、配置项默认值修正 3 处、新增 freed_bytes 数据源说明、补充缺失配置项 2 处）。

---

### 📊 统计数据完整性 — 系统级释放首次计入统计

#### 背景：v1.7 的统计缺口

v1.7 重构了清理引擎的 Layer1 层，将旧的 `_layer1_atomic` + `_layer1_system`（含多段 sleep 的异步管线）替换为 `_layer1_memreduct(full=True/False)` 单一函数。该函数实现了对标 PHNT 标准的 8 步内核管线（`<10ms`，零 sleep），在守护模式的三种场景中被调用：

1. **gap-fill 内层循环**（`memwise_gui.py` L1871）：每 ~1 秒调用 `_layer1_memreduct(full=False)`，执行 7 步轻量系统级清理（standby purge、modified flush、文件/注册表/卷缓存清空），跳过 `empty_all_working_sets()` 系统级 WS 全清。目的是持续压制内存回弹，为 harvest 阶段的 optimize 积累收割空间。

2. **blitz 循环**（`memwise_gui.py` L1897）：主 pass 前最后一段持续调用 `_layer1_memreduct(full=False)`，同样 7 步轻量。

3. **optimize 内部**（`cleaner.py` L685/L690/L697/L703/L708）：harvest 和主 pass 的 `optimize()` 调用 `_layer1_memreduct(full=True)`，执行完整 8 步全量管线（含 `empty_all_working_sets()` 系统级全进程 WS 清空 + standby 全量收割）。

然而，`_layer1_memreduct` 内部**仅递增了操作计数器**（`stats["standby"] += 1`、`stats["compress"] += 1`、`stats["modified"] += 1`），**从未将释放的字节数计入 `stats["freed_bytes"]`**。这意味着三层清理管线中"效果最大"的系统级操作——特别是 `empty_all_working_sets()`（一次性清空全部进程的物理工作集，实测可释放 2–3GB）和 `empty_standby()`（清空系统备用内存列表）——的释放量在 v1.7 中完全缺失。

`_layer1_system`（`cleaner.py` L253–L278）虽然定义了与本次修复完全相同的 `mem_pre/mem_post` → `avail` 差值 → `freed_bytes` 累加逻辑，但该函数在 v1.7 管线重构后**已不再被任何 `optimize()` 分支调用**，成为了死代码。v1.7 中实际计入 `freed_bytes` 的仅有 `_trim_process`（Layer2 逐进程 WS 差值）和 `_probe_process`（微型试探 WS 差值）两条 per-process 级别路径，系统级释放完全遗漏。

#### 修复：`_layer1_memreduct` 内部添加 `avail` 差值测量

**修改位置**：`core/cleaner.py` L208（入口测量）、L226–L232（出口累加）

**实现逻辑**：

```
mem_pre = winapi.get_memory_status()        # ← 新增：入口测量系统可用内存
try:
    if full:
        winapi.empty_all_working_sets()      # 系统级全进程 WS 清空
    winapi.clear_system_file_cache_ex()      # 强制回收文件缓存
    winapi.flush_modified_pages()            # 脏页写回
    winapi.empty_standby()                   # Standby 全量清空
    winapi.purge_low_priority_standby()      # 低优先 Standby 清空
    winapi.flush_volume_cache()              # 卷缓存刷新
    winapi.clear_registry_cache()            # 注册表缓存清空
    winapi.clear_system_file_cache()         # 文件缓存最终清空
    # ... counters ...
    if mem_pre:                              # ← 新增：出口测量
        mem_post = winapi.get_memory_status()
        freed = mem_post["avail"] - mem_pre["avail"]
        if freed > 0:
            self.stats["freed_bytes"] += freed  # 累加系统级释放量
```

**设计选择**：`avail` 差值 vs per-process WS 差值。`_layer1_memreduct` 操作的是系统级资源（Standby List、文件缓存、注册表蜂巢缓存等），这些资源不属于任何单个进程，无法通过 per-process WS 测量。唯一可行的方法是在操作前后测量系统整体可用内存的变化（`GlobalMemoryStatusEx` → `ullAvailPhys`）。由于 7/8 步管线执行时间 `<10ms`，OS 后台活动在此窗口内的内存变化可忽略不计，测量精度足够。

**一处修复覆盖全部**：此修复不需要在每个调用点分别添加测量代码。`_layer1_memreduct` 是 gap-fill、blitz、optimize 三条路径的唯一入口，在函数内部统一测量后，三条路径的释放量自动全部计入。对比初次失败尝试（在 gap segment 外层 ~15 秒窗口测量，见下文），最终方案简洁且噪声可控。

#### 调用路径覆盖对照

| 调用路径 | 调用位置 | full 参数 | 操作内容 | 频率 | v1.7 | v1.8 |
|----------|---------|:---------:|---------|:----:|:----:|:----:|
| gap-fill 内层循环 | `memwise_gui.py` L1871 | `False` | 7 步轻量（无 WS 全清）| 每 ~1s，gap 持续 8–25s | ❌ | ✅ |
| blitz 循环 | `memwise_gui.py` L1897 | `False` | 7 步轻量（无 WS 全清）| 末段 2–3s 持续 | ❌ | ✅ |
| optimize("quick") | `cleaner.py` L685 | `True` | 8 步全量 | 几乎不触发 | ❌ | ✅ |
| optimize("normal") | `cleaner.py` L690 | `True` | 8 步全量 | harvest 每 ~15s | ❌ | ✅ |
| optimize("deep") | `cleaner.py` L697 | `True` | 8 步全量 | 用户手动选择 | ❌ | ✅ |
| optimize("full") | `cleaner.py` L703 | `True` | 8 步全量 | 紧急触发 | ❌ | ✅ |
| optimize(else) | `cleaner.py` L708 | `True` | 8 步全量 | 回退路径 | ❌ | ✅ |

#### fast-track：从裸 API 恢复到 `quick_retrim`

**修复**（`memwise_gui.py` L1872–L1874）：将 `winapi.empty_ws(ft_pid)` 裸 API 调用改为 `self.cleaner.quick_retrim(ft_pid)`，利用已有 WS 差值测量和 `freed_bytes` 累加。返回 0 时自动从 `_fast_track` 移除。

#### 修复后的 `freed_bytes` 完整累加链路

| # | 累加路径 | 测量方式 | 累加位置 | 覆盖的操作 |
|:--:|----------|---------|---------|-----------|
| 1 | `_layer1_memreduct()` | 系统 avail 前后差值 | `cleaner.py` L232 | 全部系统级操作 |
| 2 | `quick_retrim()` | 单进程 WS 前后差值 | `cleaner.py` L185 | fast-track 高回填进程修剪 |
| 3 | `_trim_process()` | 单进程 WS 前后差值 | `cleaner.py` L369 | Layer2 批量进程级 trim |
| 4 | `_probe_process()` | 单进程 WS 前后差值 | `cleaner.py` L309 | Layer2 微型试探 probe |

#### 第一版失败尝试

在 gap segment 外层（~15 秒窗口）通过 `avail` 差值测量 → 15 秒窗口捕获大量 OS 后台噪声 → 数据波动剧烈 → 已回退。最终方案将测量移入 `_layer1_memreduct` 内部（<10ms 窗口），实测数据平滑稳定（2.7GB→2.1GB→1.8GB→1.6GB→1.4GB 平滑递减）。

---

### 🔧 GUI 长期运行稳定性 — 四层并发缺陷根治

#### 问题现象

长期最小化到托盘后恢复窗口出现渐进式崩溃：首次恢复（白屏→黑线→卡顿→正常）→ 再次恢复（完全白屏→崩溃闪退）→ 右键菜单（首次正常→再次全白无反应）。

#### 根因分析

**根因一**：`<Configure>` 事件在 `deiconify` 时无防抖触发 3–5 次完整 ERIS 五维重算。

**根因二**：`_draw_chart` 无重入保护且异常后标志永锁，累积后 Tcl/Tk C 层崩溃。

**根因三**：withdraw 状态下 `_refresh_mem` 每 2 秒持续操作未映射 Canvas，长时间累积内部状态污染。

**根因四**：`_dae_stopped` 在嵌套事件循环中直接调用 `_draw_chart` 导致重入。

#### 修复方案：五层防御

**防御一**：Configure 120ms 防抖合并 — `_on_chart_configure` 使用 `after_cancel` + `after(120)` 合并快速事件为单次绘制。

**防御二**：`_draw_chart` 重入保护 + `winfo_viewable()` 可见性检查。

**防御三**：`_on_chart_configure` 每次调度前强制复位 `_drawing_chart`，切断异常锁死链路。

**防御四**：`_show_window` 添加 `update_idletasks()` + `after(150ms)` 延迟首次渲染。

**防御五**：`_refresh_mem` 添加 `winfo_viewable()` 检查，withdraw 时跳过 Canvas 操作。`_dae_stopped` 改为 `after(100)` 延迟绘制。

---

### 📝 文档更新

README.md 全面审计修正 9 处：版本号、情景记忆/因果推理算法描述对齐代码、配置项默认值修正 3 处（clean_mode/clean_operations/interval）、补充缺失配置项 2 处（emergency_threshold/clean_passes）、新增 freed_bytes 数据源说明、清理操作数量修正。

---

### ⚙ 构建

- 版本号 v1.7→v1.8：`memwise_gui.py` L2/L153/L219 三处同步更新
- `MemWise.spec` 入口脚本 `memwise_gui.py`，hiddenimports 含 `core.winapi/learner/judger/cleaner/efis/sniffer/config`
- PyInstaller 6.21.0 + Python 3.14.0
- 最终 exe 大小约 13.3 MB