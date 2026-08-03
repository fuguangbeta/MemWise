"""共享配置 — 加载/保存 config.yaml，统一双方 CFG"""
import os, sys, threading

try:
    import yaml
except ImportError:
    yaml = None

if getattr(sys, "frozen", False):
    _exe_dir = os.path.dirname(sys.executable)
    if os.path.basename(_exe_dir).lower() == "dist":
        _base = os.path.dirname(_exe_dir)
    else:
        _base = _exe_dir
    CONFIG_PATH = os.path.join(_base, "config", "config.yaml")
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.yaml")

# 打包内初始模板（PyInstaller _MEIPASS）：exe 旁无配置时作为首次运行兜底来源
_TEMPLATE_PATH = None
if getattr(sys, "frozen", False):
    try:
        _t = os.path.join(sys._MEIPASS, "config", "config.yaml")
        if os.path.isfile(_t):
            _TEMPLATE_PATH = _t
    except Exception:
        pass

DEFAULT_CFG = {
    "kp": 1.0, "ki": 0.15, "kd": 0.1, "target_usage": 45,
    "interval": 30, "never": [], "clean_mode": "normal",
    "auto_start": False, "auto_start_daemon": False,
    "auto_start_admin": False, "auto_start_minimize": False,
    "daemon_trim_every_ticks": 3, "scheduled_clean": None,
    "gap_seconds": 12, "clean_passes": 4,
    "hotkey": "ctrl+shift+m", "game_hotkey": "ctrl+shift+g", "game_processes": [],
    "clean_operations": ["ws", "standby", "modified", "volume", "registry"],
}


def get_state_path():
    """获取 memwise_state.json 路径，兼容 PyInstaller 打包"""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        if os.path.basename(exe_dir).lower() == "dist":
            base = os.path.dirname(exe_dir)
        else:
            base = exe_dir
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "memwise_state.json")

def load():
    """加载 config.yaml，缺失字段用 DEFAULT_CFG 兜底。
    exe 旁无配置时回退打包内模板（_MEIPASS），保证独立部署首次运行即有完整配置"""
    d = DEFAULT_CFG.copy()
    path = CONFIG_PATH
    if not os.path.isfile(path) and _TEMPLATE_PATH:
        path = _TEMPLATE_PATH
    if not os.path.isfile(path):
        return d
    try:
        if yaml:
            with open(path, "r", encoding="utf-8") as f:
                u = yaml.safe_load(f) or {}
        else:
            alt_path = path.replace(".yaml", ".json")
            if os.path.isfile(alt_path):
                import json
                with open(alt_path, "r", encoding="utf-8") as f:
                    u = json.load(f)
            else:
                return d
        d.update(u)
    except Exception as e:
        import sys; print(f"[MemWise] 配置加载失败: {e}", file=sys.stderr)
    return d

# 写锁：EFIS 调参（daemon 线程）与 GUI 设置（主线程）可能并发写同一 tmp 文件，加锁防交错损坏
_save_lock = threading.Lock()

def save(cfg):
    """原子保存配置到 config.yaml（先写 tmp 再 rename，防止写半截崩溃）"""
    if not yaml:
        return
    with _save_lock:
        try:
            os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
            os.replace(tmp, CONFIG_PATH)
        except Exception as e:
            import sys; print(f"[MemWise] 配置保存失败: {e}", file=sys.stderr)
