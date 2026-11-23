# 参与 MemWise

感谢你愿意花时间。这份文档只讲三件事：怎么跑起来、改动要遵守什么、怎么提交。

## 运行与自检

- 环境：Windows 10 20H1 及以上或 Windows 11，64 位；Python 3.12+（仅开发/打包需要）。
- 运行：`python memwise_gui.py`（界面）或 `python memwise.py status`（命令行）。
- 自检：`python -B scripts\test_regression.py`，改动前后都应跑一遍，要求全绿。
- 打包：`python -B -m PyInstaller MemWise.spec --distpath dist --workpath build --noconfirm`。

## 改动约束

- **零第三方依赖**：运行期只用 Python 标准库与 `ctypes` 调用的 Windows API，不接受新增依赖。
- **不改变系统**：不装驱动、不注册服务、不修改系统设置或注册表策略；所有清理走公开 API。
- **不牺牲用户可控**：每一项清理操作都必须能在设置里单独关闭；默认值改动要在说明里写清。
- **文案与实现同步**：改行为要同步 README 对应章节；改界面文案要同步英文翻译。
- **不提交运行数据**：`data/`、`config/config.yaml`、日志与配置包不进仓库。

## 提交与 PR

- 一个 PR 只做一件事；说明里写清"解决了什么问题"，不必写实现细节。
- 涉及清理逻辑的改动，请附上你观察到的行为变化（例如某模式下每轮释放量的变化）。
- 不要改版本号、CHANGELOG 与发布产物——这些由维护者统一处理。
