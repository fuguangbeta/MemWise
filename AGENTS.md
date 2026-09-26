# MemWise 项目指令（AGENTS.md）

本文件是 MemWise 仓库工作区行为准则，每次会话注入。**开始工作前先读知识库索引**；涉及发布/规范细节时读取对应记忆文件。

## 项目速览
Windows 内存看护工具（Python 3.14 + 纯 ctypes Win32 API，零第三方依赖，单 exe）。GUI 入口 `memwise_gui.py`，CLI `memwise.py`。当前版本 v4.6.020（已构建，未发布）。核心模块 `core/`：cleaner（三层清理）/ judger（决策冷却）/ kalman / learner（Pareto 画像）/ policy（五树投票）/ efis（EFIS 参数自适应）/ eris（ERIS v9 冻结基线效率评分）/ winapi / config / icon_flat / stable / rebound / i18n / backup（配置包导出/导入/恢复默认）/ **engine（无 UI 引擎，2026-08-14 解耦）**。测试 `scripts/test_regression.py`（**504 项**）。发布脚本 `scripts/release_*.py`（本地工具，gitignore 不上传）。

## 📚 知识库索引（工作前必读）
项目记忆在项目记忆目录（路径见用户级指令，**14 篇内容文件 + MEMORY.md 索引**——2026-09-10 全量归纳后的结构，按需读取）：

**新窗口阅读顺序**：workstate（现场）→ memory-writing-rules（怎么记）→ red-lines-and-work-ethics（怎么干）→ session-protocols + project-overview（项目是什么）→ 按任务取用下表其余文件。

| 文件 | 内容 | 何时读 |
|---|---|---|
| workstate.md | ⚡ 现场锚点：版本状态/当前任务/最近决策/回归基线 504/发布流程 | 压缩后**第一件事** |
| pending-release-notes.md | 待发布更新日志积累区（版本号第三位=累计条目数） | 每次维护后立即追加 |
| memory-writing-rules.md | **记忆怎么写**：结构/何时写/何时不写/单一权威源/索引维护/删除标准 | 写记忆前 |
| red-lines-and-work-ethics.md | ⛔ 全部红线 + 工作伦理（先确认/当面提/禁弃用/六问/隐私/根目录） | 任何改动前 |
| session-protocols.md | 预热轮 / L0 路由 / 长期维护运行纪律 | 会话开头、压缩后 |
| doc-style-guide.md | 8 面适配 + CHANGELOG 规范 + README 逐字核查铁律 + 免责声明 | 写文档、写更新日志、发布前核查 |
| tooltip-and-i18n.md | tooltip 八规则 + 定稿流程 + 中英术语表 + i18n 教训 | 改 UI 文案、翻译 |
| release-and-pr-workflow.md | 发布全流程 + RELEASE_ID 铁律 + 事故教训 + PR 辅助 + 全版本发布档案 | 发布、处理 PR |
| project-overview.md | 项目百科+构建：架构/目录/三层清理/冷启动/spec 压缩/构建纪律/日志排查 | 理解项目、构建、排查 |
| optimization-specs.md | 四模式梯度权威表 + API 通道实验 + 22% 物理极限 + 持续压缩 | 改清理机制、改模式 |
| learning-engine-specs.md | EFIS 分组调参（4 组/白名单/冻结）+ ERIS 公式与输出规则 | 改调参、改 ERIS |
| audit-archive.md | 审查与事故档案（历次审查结论/误报澄清/不修清单/未决残留） | 追溯"为什么这么写" |
| environment-and-tools.md | MCP（含 tier 键教训）/ Skills / ZCode 配置与日志诊断 | 环境相关、MCP 排查 |
| roadmap.md | 未实施的候选优化方向（进程族聚合/应用规则引擎/保护建议 UI） | 规划新功能时 |

用户级记忆与指令见用户环境配置（全局规则/偏好）。

## ⛔ 绝对红线（违反 = 事故）
1. **禁 git 回退/checkout 恢复**：任何情况下不用 `git checkout --`、`git reset --hard`、`git revert` 恢复文件
2. **禁删除文件**：不删用户文件、不删 memwise.log、不删旧版本发布资产
3. **禁牺牲功能**：不砍功能换实现，不草率弃用方法；所有改动最小化
4. **测试禁写真实状态文件**：`config/config.yaml`、`memwise_state.json`、`memwise_efis_state.json`、`memwise_eris_ewma.json` 是真实数据——验证必须用临时路径/临时文件
5. **构建 exe 前必须确认 config 状态**（MemWise.spec datas=[] 冷启动，不打包本机 config.yaml）
6. **发布新版本绝不修改/删除旧版本**：旧 tag、release、exe 资产一律保留原样，只创建新 tag + release + 新 exe

（完整红线、工作伦理与重事故案例见 red-lines-and-work-ethics.md；删码/删配置候选必过其中"证明记录六问"）

## 🔧 工具使用手册（MCP：项目级 2 个 + 内建 3 个）
- **codegraph**（项目 `.mcp.json`）：代码索引（`codegraph index` 手动更新）。⚠ server 配置禁带 `tier` 键——会被配置校验拒绝整个跳过（2026-09-06 教训）
- **github**（项目 `.mcp.json`）：仓库操作（token 已配在 env）。**注意**：GitHub 连接依赖 Steam++ 加速器，禁止停加速器直连（10061）；502/超时直接重试
- **内建**：computer-use（桌面控制）/ node_repl / web_reader
- 发布脚本：`scripts/release_tag.py`（建 tag+release，幂等）→ `release_upload.py`（上传 exe，改 RELEASE_ID）→ `release_body.py`（自动读 CHANGELOG 更新 body）——token 读环境变量 GITHUB_TOKEN 或项目根 `.gh_token`（禁硬编码、禁上传）
- 完整环境清单（MCP 配置真身与三处一致性 / ⛔ tier 键教训 / ZCode 日志诊断）见 environment-and-tools.md

## 测试与构建
- 回归：`python -B scripts\test_regression.py`（**504 项断言**，-B 避 pyc 缓存锁；本机已设 PYTHONPYCACHEPREFIX）
- 语法检查：`compile()`；日常修改用回归验证，**非必要不构建 exe**（用户成本偏好）
- 构建：`MSYS_NO_PATHCONV=1 taskkill /f /im MemWise.exe` + `python -B -m PyInstaller MemWise.spec --distpath dist --workpath build --noconfirm`（cmd /c 包装引号解析失败已多次复现，勿再用；版本/图标变更加 `--clean`）
- **构建永不放进含管道的条件链**（管道尾命令退出码 0 会使 `&&` 不短路，坏源码照样打包）；回归全绿确认后才准构建
- 构建后清理 dist 残留（watchdog.json 等运行时文件）与根目录 `nul` 残留（PyInstaller/Python 3.14 副作用），**禁删 memwise.log**

## 发布流程（完整细节读 release-and-pr-workflow.md）
1. 修改完成 → **504 项回归全绿** → 更新 CHANGELOG（用户视角规范，见 doc-style-guide.md）
2. `git add -A && git commit && git push origin main`（最快）
3. 版本号变更时同步 **16 处 / 8 文件**（memwise 2 / gui 4 / engine 1 / i18n 4【两个版本键各含键+值】/ backup APP_VERSION 1 / test docstring 1 / README 1 / AGENTS 1，2026-09-06 实测口径；CHANGELOG 属内容不计）+ 构建 exe（--clean）
4. 改 `release_tag.py` 版本号 → 运行（建 tag+release，拿新 release id）
5. 改 `release_upload.py` RELEASE_ID → 运行（上传 exe）
6. `release_body.py` 自动同步 body → **验证全部旧版本 release 资产逐一核验完好**
7. 发布前 `git status` 检查 untracked（防隐私文件误提交）

## 更新日志规范（详见 doc-style-guide.md）
标题 `## vX.X (年·月)` + `>` 概要；小节 `###` 先 `>` 叙述段（可稍详细）再条列；条目动词四式（修复了/新增了/优化了/移除了），**只说解决了什么问题，禁源码细节/函数名/API**；增量口径不保留旧版本（**写新版章节时必须同步删除旧版文字说明**——发布脚本取 `CHANGELOG[idx:]` 到文件末尾作 release body，留旧章节会连带发出去）；**已发布版本后不追加维护项——积累到 pending-release-notes 记忆，下次发布新版本时全面编写**；release body 与 CHANGELOG 逐字一致。

## 全局适配（8 面，详见 doc-style-guide.md）
一次功能改动后同步：实现 / 文案（tooltip 八规则：纯中文零英文三段式，功能按键名加「」）/ CLI / 配置 / 文档（README 双语）/ 测试 / 版本（15 处同步面）/ 记忆（写法见 memory-writing-rules.md）。

## GitHub 操作
- 账号 fuguangbeta；**无明确授权不 push**；仓库操作前先确认 GitHub 还是 Gitee
- 改 release_*.py 一律用文件编辑（禁 PowerShell 管道写脚本，曾截断文件）
- PR 处理：全程辅助用户（审查→中文讲人话→建议→用户确认后执行）；PR 合并 ≠ 发布；小修复攒批发布、大功能升版本
- **commit message 隐私红线（2026-08-11 用户指示）**：只描述项目内变更；禁止出现工具链/IDE 名、防御性措施、忽略规则、工作区结构等"项目之外"信息——公开历史可被任何人查看

## 环境注意
- bash 工具实为 PowerShell：禁特殊字符内联 `python -c`（反引号/中文会被转义破坏），复杂逻辑写脚本文件
- 卡巴斯基+Defender 双杀软：瞬时 Access denied 是拦截，稍后重试
- 项目根保持整洁：临时调试文件禁止遗留根目录
- 排查问题优先看 `data/memwise.log`（MEMWISE_LOG_DIR 可覆盖，2MB×2 轮转；崩溃现场 `data/memwise_crash.log` 常驻）
