# MemWise 更新日志

> **MemWise** — Windows 智能内存看护工具。不杀进程、不挂起线程、不注入、不联网。
> 纯 ctypes Win32 API，零外部依赖。

## v3.5.14 (2026年8月)

> v3.4.19 发布后的维护增量：图标体系三处解耦（任务栏/标题栏平面、桌面/资源管理器立绘）并修复多层失效根因（句柄截断、托盘恢复时序、exe 资源图标机制）；清理图标测试遗留死代码与死配置键。共 14 项维护，回归测试 37 项全绿。

### 图标体系三处解耦

> 实测证明 Win11 任务栏按钮图标取自 exe 资源图标，`WM_SETICON` 对任务栏按钮完全无效（红色注入实验：按钮不随窗口图标变化）——此前窗口图标链路只能管标题栏，任务栏图标一直回退 exe 资源立绘图标。

- 优化了任务栏按钮图标为平面图标：exe 资源图标改为混合多尺寸 ICO，`16/24/32/48` 帧用平面图、`64/128/256` 帧用立绘图，explorer 按请求尺寸就近取帧（任务栏 40px 取 48 帧平面、桌面 60px 取 64 帧立绘）
- 修复了桌面/资源管理器图标被平面化（立绘帧保留在 `64/128/256`，桌面大图标与快捷方式不受影响）
- 修复了标题栏图标回退 Tk 默认黑色羽毛（窗口图标链路独立生效，与资源图标解耦）

### 窗口图标链路根因修复

> 图标失效共三层根因：GDI+ 生成的 HICON 句柄经 ctypes 默认 `c_int`（32 位）传参被截断导致 `WM_SETICON` 静默失败；`--minimized` 自启/托盘恢复场景 wrapper 窗口从未被设置图标；启动早期 wrapper 未创建时 `GetAncestor` 返回自身。

- 修复了 GDI+ HICON 句柄截断（改 PNG zlib 解码 → BGRA → `CreateDIBSection` + `CreateIconIndirect`，与动态渲染同通道；新增 `core/icon_flat.py` 内嵌 PNG，exe 冷启动零外部文件）
- 修复了 user32 图标/窗口 API 句柄位宽（`SendMessageW`/`SetClassLongPtrW`/`GetAncestor`/`FindWindowExW`/`SetWindowPos` 全量声明 64 位 `c_void_p`）
- 修复了 `--minimized` 自启/托盘恢复场景图标未设置（`_show_window` 在 `deiconify` 前设置图标，任务栏按钮在首次映射时缓存图标，此后 `WM_SETICON` 不再刷新按钮）
- 修复了启动早期 wrapper 不可寻（`GetAncestor` 退化时用 `FindWindowExW` 按类名 `TkTopLevel` 兜底查找隐藏窗口）
- 优化了普通启动映射后同步重设（`deiconify` → `update_idletasks` → 立即重设 + `SWP_FRAMECHANGED`，窗口已映射时才真正刷新）

### 行为与配置

> 手动启动被错误最小化到托盘；卷缓存 tooltip 残缺；两个历史死配置键无任何消费方。

- 修复了手动启动最小化到托盘（`auto_start_minimize` 仅开机自启联动 `--minimized` 参数，双击启动正常显示窗口）
- 补全了卷缓存刷新 tooltip 残缺内容（原 `"⚠ "` 空结尾）
- 移除了死配置键 `daemon_trim_every_ticks`/`scheduled_clean`（零消费方，文档本就不承认）

### 清理与构建

> 图标测试阶段遗留 GDI+ 解码实现（`create_hicon_from_png` + GDI+ 绑定）在通道切换后零调用者，属死代码；图标生成源文件（`simple_flat_*.png`、`icon_original_stereo.ico`）保留供再生成。

- 移除了 GDI+ 死代码（`create_hicon_from_png` 及 `_gdiplus` 绑定，零调用方；`_com_vtbl_call`/`_ole32` 仍被快捷方式 COM 使用故保留）
- 版本号 v3.4.19 → v3.5.14（Mutex/窗口标题/FindWindowW/FindWindowExW/CLI/README/测试同步，新 mutex 避免与旧版互斥冲突）
- 37 项回归测试全绿，零编译错误
