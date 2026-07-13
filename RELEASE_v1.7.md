## v1.7 — 内核管线重写 + 操作码修正 + 架构加固

### 内核管线重写
- NT API 操作码全部修正为 PHNT 标准 (2/3/4/5)，修正 17 处硬编码
- 新增 8 步内核快速管线，零 sleep，&lt;10ms
- 系统级 MemoryEmptyWorkingSets + Standby 全量收割，实测可达 15%

### 架构安全加固
- WndProc 重写为标志位架构，彻底消除托盘崩溃（5 轮迭代）
- 移除所有 self-EmptyWorkingSet 回退逻辑

### 参数优化
- PID target 45%→30%，前台门槛 0.6→0.35，冷却 3600s→300s
- PF 反馈"先收后审"，self-PID 排除

### 数据统计修复
- cycle_freed 同源一致，net_freed 死代码修复
- 进程计数 Layer2+Layer3 合计，日志周期严格 60s
- 统计栏千位格式化恢复

### 设置与 UI
- 10 处 Tooltip 全面更新，设置窗口 700→600
- 6 个死函数/变量删除

[完整更新日志](https://github.com/fuguangbeta/MemWise/blob/main/CHANGELOG.md)
