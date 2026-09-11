# -*- coding: utf-8 -*-
"""配置包：导出 / 导入 / 自动备份 / 恢复出厂（包格式 v1）

单文件 ZIP 包（根目录平铺）：状态文件 + manifest.json 清单。
manifest = {"format_version": 1, "app_version": ..., "source": "export"|"backup",
            "exported_at": ..., "files": [实际打包的状态文件名]}
导入校验链：manifest 可解析 → format_version 支持（未知版本拒绝——为未来格式
演进扫清地基）→ files 与 ZIP 实际内容双向精确 diff（多/少/名不符全拒并列出
差异清单）→ 逐文件解析校验 → 落位（写 files + 删预期集外——完整复刻导出方状态）。
供 GUI（设置面板 配置传输/重置 栏）与 CLI（export/import/reset）共用。
所有面向用户的串经 tr/tr_msg 翻译（英文界面零残留）。
"""
import json, os, sys, time, zipfile, subprocess

try:
    import yaml
except ImportError:
    yaml = None

from core.i18n import tr, tr_msg

PACKAGE_VERSION = 1
APP_VERSION = "4.5.043"  # 版本同步面之一（manifest 记录用）

_STATE_NAMES = ("config.yaml", "memwise_state.json",
                "memwise_efis_state.json", "memwise_eris_ewma.json")
# ② ERIS 自校准数据：**刻意不进配置包**（机器相关，跨机迁移会把曲线置于错误位置），
# 但恢复默认必须清除（属"学习到的标尺"）——见记忆 learning-engine-specs §B5
_CALIB_NAME = "memwise_eris_calib.json"


def _data_root(base=None):
    """数据目录根（base 供测试注入临时目录）"""
    if base is not None:
        return base
    from core.config import get_state_path
    return os.path.dirname(get_state_path())


def _state_paths(base=None):
    """四个状态文件 → {标准文件名: 绝对路径}（config.yaml 位于数据根的兄弟 config/ 目录）"""
    root = _data_root(base)
    return {
        "config.yaml": os.path.join(root, "..", "config", "config.yaml"),
        "memwise_state.json": os.path.join(root, "memwise_state.json"),
        "memwise_efis_state.json": os.path.join(root, "memwise_efis_state.json"),
        "memwise_eris_ewma.json": os.path.join(root, "memwise_eris_ewma.json"),
    }


def import_export_dir(base=None):
    """配置包统一目录（用户定名 import_export）：导出包、自动备份包、
    待导入的包三合一——导出/备份生成于此，导入也扫描此目录"""
    return os.path.join(_data_root(base), "import_export")


def _now_stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def export_state(source="export", base=None):
    """打包当前状态文件 → packages/ 下 ZIP 包，返回 (路径, 缺失未打包列表)。
    路径为 None 表示无任何状态文件可打包。不存在的文件跳过，
    manifest.files 忠实记录实际内容（导入端按其完整复刻）。"""
    paths = _state_paths(base)
    files = {n: p for n, p in paths.items() if os.path.isfile(p)}
    if not files:
        return None, sorted(paths.keys())
    pkg_dir = import_export_dir(base)
    os.makedirs(pkg_dir, exist_ok=True)
    prefix = "MemWise_Export_" if source == "export" else "MemWise_Backup_"
    pkg_path = os.path.join(pkg_dir, f"{prefix}{_now_stamp()}.zip")
    manifest = {
        "format_version": PACKAGE_VERSION,
        "app_version": APP_VERSION,
        "source": source,
        "exported_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": sorted(files.keys()),
    }
    with zipfile.ZipFile(pkg_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, p in sorted(files.items()):
            zf.write(p, arcname=name)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    return pkg_path, sorted(set(paths.keys()) - set(files.keys()))


BACKUP_KEEP = 10   # 自动备份包保留个数（2026-09-11 审查 F29）


def _prune_backups(pkg_dir):
    """只保留最近 BACKUP_KEEP 个自动备份包：原先每次重置/导入都新增一个包且永不清理 ⇒
    磁盘无界增长（包内含画像 JSON，单个可达数百 KB~数 MB）。
    仅清理 MemWise_Backup_*（程序自动产物）；MemWise_Export_* 是用户主动导出资产，一律不动。"""
    try:
        bs = sorted((f for f in os.listdir(pkg_dir) if f.startswith("MemWise_Backup_")), reverse=True)
        for f in bs[BACKUP_KEEP:]:
            os.remove(os.path.join(pkg_dir, f))
    except Exception:
        pass


def create_backup(base=None):
    """当前状态打包为 Backup 包（重置/导入前自动备份），返回包路径。
    生成后按 BACKUP_KEEP 保留最近若干个（2026-09-11 审查 F29）"""
    p, _ = export_state("backup", base=base)
    _prune_backups(import_export_dir(base))
    return p


def validate_package(pkg_path):
    """校验配置包 → (manifest 或 None, 错误列表)。错误列表非空即拒绝，
    每条为用户可读原因（显示层经 tr_msg 翻译，已是目标语言）。"""
    errors = []
    if not os.path.isfile(pkg_path):
        return None, [tr("配置包不存在")]
    try:
        zf = zipfile.ZipFile(pkg_path)
    except Exception:
        return None, [tr("配置包缺少清单文件或已损坏")]
    manifest = None
    try:
        with zf:
            names = zf.namelist()
            if "manifest.json" not in names:
                return None, [tr("配置包缺少清单文件或已损坏")]
            try:
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            except Exception:
                return None, [tr("配置包缺少清单文件或已损坏")]
            if not isinstance(manifest, dict):
                return None, [tr("配置包缺少清单文件或已损坏")]
            fv = manifest.get("format_version")
            if not isinstance(fv, int) or fv < 1:
                return None, [tr("配置包缺少清单文件或已损坏")]
            if fv > PACKAGE_VERSION:
                return manifest, [tr_msg(f"配置包版本较新（{fv}），请先升级程序")]
            expected = manifest.get("files")
            if not isinstance(expected, list) or not expected \
                    or not all(isinstance(x, str) for x in expected):
                return manifest, [tr("配置包缺少清单文件或已损坏")]
            actual = sorted(n for n in names if n != "manifest.json")
            extra = sorted(set(actual) - set(expected))
            missing = sorted(set(expected) - set(actual))
            if extra or missing:
                parts = []
                if missing:
                    parts.append(tr("缺少：") + "、".join(missing))
                if extra:
                    parts.append(tr("多出：") + "、".join(extra))
                return manifest, [tr("配置包内容不符") + "（" + "；".join(parts) + "）"]
            for name in expected:
                data = zf.read(name)
                ok = True
                if name.endswith(".json"):
                    try:
                        json.loads(data.decode("utf-8"))
                    except Exception:
                        ok = False
                elif name.endswith(".yaml") or name.endswith(".yml"):
                    try:
                        if yaml:
                            yaml.safe_load(data.decode("utf-8"))
                    except Exception:
                        ok = False
                if not ok:
                    errors.append(tr_msg(f"文件 {name} 无法解析（可能已损坏）"))
    except Exception:
        return None, [tr("配置包缺少清单文件或已损坏")]
    return manifest, errors


def import_state(pkg_path, backup=True, base=None):
    """导入配置包 → (True, "") 或 (False, 错误串)。
    backup=True 先把当前状态打包为 Backup 包（可供再次导入恢复）。
    落位 = 按 manifest.files 写入 + 删除预期四文件中包内没有的
    （完整复刻导出方状态——导出方没有的文件，导入方也不保留）。
    仅落盘不刷新内存态，重启后生效（调用方负责重启）。"""
    manifest, errors = validate_package(pkg_path)
    if errors:
        return False, "\n".join(errors)
    if backup:
        create_backup(base=base)
    with zipfile.ZipFile(pkg_path) as zf:
        for name in manifest["files"]:
            target = _state_paths(base).get(name)
            if not target:
                continue  # manifest 声明了当前程序不认识的文件名（format_version 已挡，防御）
            data = zf.read(name)
            tmp = f"{target}.import-tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, target)
    for name, target in _state_paths(base).items():
        if name not in manifest["files"] and os.path.isfile(target):
            os.remove(target)
    return True, ""


def reset_factory(backup=True, base=None):
    """恢复出厂：可选备份当前状态 → 删除四个状态文件（重启后全默认冷启动）。
    返回 (True, 备份包路径或 "")。仅落盘，调用方负责重启生效。"""
    bak = create_backup(base=base) if backup else None
    for p in _state_paths(base).values():
        if os.path.isfile(p):
            os.remove(p)
    # ② 自校准数据单独清除（不在 _STATE_NAMES 中，故此处显式处理）
    try:
        cp = os.path.join(_data_root(base), _CALIB_NAME)
        if os.path.isfile(cp):
            os.remove(cp)
    except Exception:
        pass
    return True, bak or ""


def restart_application():
    """删除 watchdog.json（防看门狗把主动重启误判为崩溃而 --restored 抢跑），
    经 cmd 延迟 3 秒启动新程序进程——延迟期内当前实例完全退出（单实例互斥锁
    与窗口随进程释放），新实例启动时单实例检查干净通过，不会被"激活旧实例"
    路径误杀（实测：并行启动会被单实例机制拒绝致程序直接关闭）。调用方随后
    立即优雅关闭自身——重置/导入场景不得保存任何状态（需要丢弃的正是旧状态），
    句柄正常释放让 PyInstaller bootloader 干净清理临时目录。"""
    try:
        from core.engine import _watchdog_path
        wd = _watchdog_path()
        if os.path.exists(wd):
            os.remove(wd)
    except Exception:
        pass
    # 清除 PyInstaller bootloader 环境变量（_MEI*/_PYI*）：子进程继承会导致新实例
    # 误用旧解包目录 → "Failed to import encodings module" 启动失败（实测实证）
    env = {k: v for k, v in os.environ.items() if not k.startswith(("_MEI", "_PYI"))}
    if getattr(sys, "frozen", False):
        target = f'start "" "{sys.executable}"'
    else:
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        py = pythonw if os.path.isfile(pythonw) else sys.executable
        gui = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                           "memwise_gui.py")
        target = f'start "" "{py}" "{gui}"'
    # 工作目录显式指向程序位置（防继承旧实例的 _MEI 临时目录导致占用与清理竞争）
    cwd = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
        else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    subprocess.Popen(
        f'cmd /c timeout /t 3 /nobreak >nul & {target}',
        creationflags=0x08000000, env=env, cwd=cwd)  # CREATE_NO_WINDOW
