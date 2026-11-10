# MemWise 项目指令（AGENTS.md）

本文件是 MemWise 仓库工作区行为准则，每次会话注入。**只写稳定规则**：数字与状态一律现跑脚本或读 `workstate`。

> **适用范围**：本文件服务于作者本地的 AI 协作流程，其中引用的记忆库文件未随仓库分发。外部贡献者与外部 AI 助手请以 `README.md` 与 `LICENSE` 为准，代码改动请走 Pull Request；文中"维护者红线"不约束外部贡献者。

## 0. 启动门

进入项目：先调用 `skill("memwise")`，再读 `workstate.md`；预热轮按 `session-protocols` 例外。任务篇目由下表路由，按需读，不通读全库。

## 📚 知识库索引（13 篇 + MEMORY.md）

新窗口顺序：`skill` → workstate → memory-writing-rules → red-lines → session-protocols + project-overview → 按任务取用。

| 文件 | 何时读 |
|---|---|
| workstate.md | 压缩后第一件事：版本/任务/基线/发布状态 |
| pending-release-notes.md | 每次用户可见维护后追加 |
| memory-writing-rules.md | 写记忆前 |
| red-lines-and-work-ethics.md | 任何改动前（完整红线/伦理/证明记录六问） |
| session-protocols.md | 会话开头、压缩后 |
| doc-style-guide.md | 写文档/CHANGELOG/README、发布前核查 |
| tooltip-and-i18n.md | 改 UI 文案、翻译 |
| release-and-pr-workflow.md | 发布、PR、发布脚本与档案 |
| project-overview.md | 架构/目录/构建/日志排查 |
| optimization-specs.md | 改清理机制、模式参数 |
| learning-engine-specs.md | 改 EFIS 调参、ERIS |
| audit-archive.md | 追溯"为什么这么写" |
| environment-and-tools.md | MCP/Skills/环境与诊断 |

用户级规则见 `~/.dsh/AGENTS.md`。

## ⛔ 绝对红线（违反 = 事故）

1. **禁 git 回退/checkout 恢复**：不用 `git checkout --`、`git reset --hard`、`git revert` 恢复文件
2. **禁删除文件**：不删用户文件、`memwise.log`、旧版本发布资产
3. **禁牺牲功能**：不砍功能换实现、不草率弃用方法；改动最小化
4. **测试禁写真实状态文件**：`config/config.yaml`、`memwise_state.json`、`memwise_efis_state.json`、`memwise_eris_ewma.json`、`memwise_eris_calib.json`；验证用临时路径
5. **构建 exe 前确认 config 状态**（`MemWise.spec` 的 `datas=[]` 冷启动，不打包本机配置）
6. **发布新版本不动旧版本**：旧 tag / release / exe 资产原样保留，只建新 tag + release + 新 exe

完整红线、工作伦理与删码/删配置「证明记录六问」见 `red-lines-and-work-ethics.md`。

## 🔧 日常命令与指针

- **回归**：`python -B scripts\test_regression.py`；日常改动用回归验证，非必要不构建 exe。
- **构建**：回归全绿后 `python -B -m PyInstaller MemWise.spec --distpath dist --workpath build --noconfirm`（版本/图标加 `--clean`）；构建永不放进含管道的条件链。完整纪律（taskkill、cmd /c 引号坑、`datas=[]`、残留清理、禁删日志）见 `project-overview.md`。
- **发布**：流程 / RELEASE_ID / 版本 16 处同步 / 旧资产核验见 `release-and-pr-workflow.md`。
- **文案**：CHANGELOG（四式、25 字、升级注意事项）、README 逐字核查、8 面适配见 `doc-style-guide.md`；tooltip 与 i18n 见 `tooltip-and-i18n.md`。
- **GitHub**：无明确授权不 push；操作前确认 GitHub / Gitee；`release_*.py` 一律用文件编辑；commit message 隐私红线见 `release-and-pr-workflow.md`。
- **项目**：Windows 内存看护（Python 3.14 + 纯 ctypes，零第三方依赖，单 exe）；架构与模块见 `project-overview.md`。

## 环境注意（详见 environment-and-tools.md）

- shell 实为 PowerShell：禁内联复杂中文/引号，复杂逻辑写脚本文件。
- 卡巴斯基 + Defender：瞬时 Access denied 稍后重试。
- 项目根禁留临时文件；排查问题先看 `data/memwise.log`。
