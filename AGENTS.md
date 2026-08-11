# MemWise 项目指令（AGENTS.md）

本文件是 ZCode 在 MemWise 仓库工作的行为准则。完整知识库在 `.zcode/memory/`（26 篇），按需读取；本文件为必须遵守的核心红线。

## 项目速览
Windows 内存看护工具（Python 3.14 + 纯 ctypes Win32 API，零第三方依赖，单 exe）。GUI 入口 `memwise_gui.py`，CLI `memwise.py`。当前版本 v3.7.09（已发布，Release id 365290958）。核心模块在 `core/`（cleaner 三层清理 / judger 决策 / kalman / learner / policy 五树 / efis / eris / winapi / config）。

## ⛔ 绝对红线（违反 = 事故）
1. **禁 git 回退/checkout 恢复**：任何情况下不用 `git checkout --`、`git reset --hard`、`git revert` 恢复文件
2. **禁删除文件**：不删用户文件、不删 memwise.log、不删旧版本发布资产
3. **禁牺牲功能**：不砍功能换实现，不草率弃用方法；所有改动最小化
4. **测试禁写真实状态文件**：`config/config.yaml`、`memwise_state.json`、`memwise_efis_state.json`、`memwise_eris_ewma.json` 是真实数据——验证必须用临时路径/临时文件
5. **构建 exe 前必须确认 config 状态**（MemWise.spec datas=[] 冷启动，不打包本机 config.yaml）
6. **发布新版本绝不修改/删除旧版本**：旧 tag、release、exe 资产一律保留原样，只创建新 tag + release + 新 exe

## 测试与构建
- 回归：`python -B scripts\test_v2.6.py`（69 项断言，-B 避 pyc 缓存锁；本机注册表已设 PYTHONPYCACHEPREFIX）
- 语法检查：`compile()` 或 py_compile；日常修改用回归测试验证，**非必要不构建 exe**（用户成本偏好）
- 构建：`cmd /c "taskkill /f /im MemWise.exe >nul 2>&1 & cd /d D:\我的文件\memwise && pyinstaller MemWise.spec --distpath dist --workpath build --noconfirm 2>&1"`（版本/图标变更加 `--clean`）
- 构建后清理 dist 残留（watchdog.json 等运行时文件），**禁删 memwise.log**

## 发布流程（完整版见 .zcode/memory/github-release-workflow.md）
分步：git push main（最快）→ release_tag.py（API 建 tag + release，幂等可重跑）→ release_upload.py 上传 exe（走 uploads.github.com，改 RELEASE_ID）→ release_body.py 自动读 CHANGELOG（PATCH body）。**旧版本 5 个 release 资产逐一核验完好**。网络 502 直接重跑脚本。

## 更新日志规范（完整版见 .zcode/memory/changelog-style-guide.md）
标题 `## vX.X (年·月)` + `>` 概要；小节 `###` 先 `>` 叙述段（可稍详细）再条列；条目动词四式（修复了/新增了/优化了/移除了），**只说解决了什么问题，禁源码细节/函数名/API**；增量口径不保留旧版本；release body 与 CHANGELOG 逐字一致。

## 全局适配（8 面）
一次功能改动后同步：实现 / 文案（tooltip 六规则：纯中文零英文三段式）/ CLI / 配置 / 文档（README 双语）/ 测试 / 版本（13 处同步面）/ 记忆。

## GitHub 操作
- 账号 fuguangbeta；**无明确授权不 push**
- 仓库操作前先确认 GitHub 还是 Gitee
- 改 release_*.py 一律用文件编辑（禁 PowerShell 管道写脚本，曾截断文件）
- token 读取：环境变量 GITHUB_TOKEN 或项目根 `.gh_token`（**禁在脚本硬编码**）
- PR 处理：全程辅助用户（审查→中文讲人话→建议→用户确认后执行）；PR 合并 ≠ 发布

## 环境注意
- bash 工具实为 PowerShell：禁特殊字符内联 `python -c`（反引号/中文会被转义破坏），复杂逻辑写脚本文件
- Steam++ 加速器是 GitHub 连接硬依赖：**禁止停加速器直连**（10061），重启后需 ≥10s 稳定
- 卡巴斯基+Defender 双杀软：瞬时 Access denied 是拦截，稍后重试
- 项目根保持整洁：临时调试文件禁止遗留根目录

## 其他（见 .zcode/memory/）
- tooltip-rules.md、readme-style-guide.md、eris-factor-output-rules.md、eris-iqr-v5-formula.md、global-adaptation.md、pr-handling-workflow.md、mc-*（小说设定）
