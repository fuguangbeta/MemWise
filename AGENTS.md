# MemWise 项目指令（AGENTS.md）

本文件是 ZCode 在 MemWise 仓库工作的行为准则，每次会话注入。**开始工作前先读知识库索引**；涉及发布/规范细节时读取对应记忆文件。

## 项目速览
Windows 内存看护工具（Python 3.14 + 纯 ctypes Win32 API，零第三方依赖，单 exe）。GUI 入口 `memwise_gui.py`，CLI `memwise.py`。当前版本 v3.8.40（已发布，Release id 368440903，exe 13324922 B）。核心模块 `core/`：cleaner（三层清理）/ judger（决策冷却）/ kalman / learner（Pareto 画像）/ policy（五树投票）/ efis（EFIS v6 调参）/ eris（ERIS v6 效率评分）/ winapi / config / icon_flat。测试 `scripts/test_v2.6.py`（71 项）。发布脚本 `scripts/release_*.py`（本地工具，gitignore 不上传）。

## 📚 知识库索引（工作前必读）
项目记忆在 `~/.zcode/cli/memories/projects/memwise/memory/`（14 篇，按需读取）：

| 文件 | 内容 | 何时读 |
|---|---|---|
| memwise-overview.md | 项目百科：版本链/3层清理/6开关/认知引擎/图标/冷启动 | 理解项目架构 |
| project-build-info.md | 构建命令/状态文件/日志排查/图标三处解耦/环境 | 构建、排查 |
| absolute-red-lines.md | ⛔ 全部红线 + 重事故案例 | 任何改动前 |
| github-release-workflow.md | 完整发布流程 + 教训 | 发布时 |
| changelog-style-guide.md | 更新日志规范（用户视角） | 写更新日志时 |
| pr-handling-workflow.md | PR 全程辅助流程 | 处理 PR 时 |
| readme-style-guide.md | README 双语修正规范 | 改 README 时 |
| tooltip-rules.md | tooltip 六规则 | 改 UI 文案时 |
| global-adaptation.md | 8 面全局适配定义 | 任何功能改动后 |
| eris-iqr-v5-formula.md / eris-factor-output-rules.md | ERIS 公式与输出规则 | 改 ERIS 时 |
| root-directory-cleanliness.md | 根目录整洁偏好 | 收尾时 |
| current-mcp-and-skills.md | MCP/Skills 清单 | 环境相关 |

用户级记忆（全局规则/偏好）：`~/.claude/memory/MEMORY.md`；用户级指令：`~/.zcode/AGENTS.md`。

## ⛔ 绝对红线（违反 = 事故）
1. **禁 git 回退/checkout 恢复**：任何情况下不用 `git checkout --`、`git reset --hard`、`git revert` 恢复文件
2. **禁删除文件**：不删用户文件、不删 memwise.log、不删旧版本发布资产
3. **禁牺牲功能**：不砍功能换实现，不草率弃用方法；所有改动最小化
4. **测试禁写真实状态文件**：`config/config.yaml`、`memwise_state.json`、`memwise_efis_state.json`、`memwise_eris_ewma.json` 是真实数据——验证必须用临时路径/临时文件
5. **构建 exe 前必须确认 config 状态**（MemWise.spec datas=[] 冷启动，不打包本机 config.yaml）
6. **发布新版本绝不修改/删除旧版本**：旧 tag、release、exe 资产一律保留原样，只创建新 tag + release + 新 exe

## 🔧 工具使用手册（MCP 已配置 5 个）
- **filesystem**：`D:\我的文件` 根的文件读写
- **github**：仓库操作（token 已配在 env）。**注意**：GitHub 连接依赖 Steam++ 加速器，禁止停加速器直连（10061）；502/超时直接重试
- **memory**：知识图谱记忆
- **sequential-thinking**：复杂问题分步推理
- **codegraph**：代码索引（`codegraph index` 手动更新）
- 发布脚本：`scripts/release_tag.py`（建 tag+release，幂等）→ `release_upload.py`（上传 exe，改 RELEASE_ID）→ `release_body.py`（自动读 CHANGELOG 更新 body）——token 读环境变量 GITHUB_TOKEN 或项目根 `.gh_token`（禁硬编码、禁上传）

## 测试与构建
- 回归：`python -B scripts\test_v2.6.py`（71 项断言，-B 避 pyc 缓存锁；本机已设 PYTHONPYCACHEPREFIX）
- 语法检查：`compile()`；日常修改用回归验证，**非必要不构建 exe**（用户成本偏好）
- 构建：`cmd /c "taskkill /f /im MemWise.exe >nul 2>&1 & cd /d D:\我的文件\memwise && pyinstaller MemWise.spec --distpath dist --workpath build --noconfirm 2>&1"`（版本/图标变更加 `--clean`）
- 构建后清理 dist 残留（watchdog.json 等运行时文件），**禁删 memwise.log**

## 发布流程（完整细节读 github-release-workflow.md）
1. 修改完成 → 71 项回归全绿 → 更新 CHANGELOG（用户视角规范）
2. `git add -A && git commit && git push origin main`（最快）
3. 版本号变更时同步 13 处（gui 7/memwise 2/README 1/test 3）+ 构建 exe（--clean）
4. 改 `release_tag.py` 版本号 → 运行（建 tag+release，拿新 release id）
5. 改 `release_upload.py` RELEASE_ID → 运行（上传 exe）
6. `release_body.py` 自动同步 body → **验证旧版本 5 个 release 资产逐一核验完好**
7. 发布前 `git status` 检查 untracked（防隐私文件误提交）

## 更新日志规范（详见 changelog-style-guide.md）
标题 `## vX.X (年·月)` + `>` 概要；小节 `###` 先 `>` 叙述段（可稍详细）再条列；条目动词四式（修复了/新增了/优化了/移除了），**只说解决了什么问题，禁源码细节/函数名/API**；增量口径不保留旧版本；**已发布版本后不追加维护项——积累到 pending-release-notes 记忆，下次发布新版本时全面编写**；release body 与 CHANGELOG 逐字一致。

## 全局适配（8 面）
一次功能改动后同步：实现 / 文案（tooltip 六规则：纯中文零英文三段式）/ CLI / 配置 / 文档（README 双语）/ 测试 / 版本（13 处同步面）/ 记忆。

## GitHub 操作
- 账号 fuguangbeta；**无明确授权不 push**；仓库操作前先确认 GitHub 还是 Gitee
- 改 release_*.py 一律用文件编辑（禁 PowerShell 管道写脚本，曾截断文件）
- PR 处理：全程辅助用户（审查→中文讲人话→建议→用户确认后执行）；PR 合并 ≠ 发布；小修复攒批发布、大功能升版本

## 环境注意
- bash 工具实为 PowerShell：禁特殊字符内联 `python -c`（反引号/中文会被转义破坏），复杂逻辑写脚本文件
- 卡巴斯基+Defender 双杀软：瞬时 Access denied 是拦截，稍后重试
- 项目根保持整洁：临时调试文件禁止遗留根目录
- 排查问题优先看 `memwise.log`（MEMWISE_LOG_DIR 可覆盖，2MB×2 轮转）
