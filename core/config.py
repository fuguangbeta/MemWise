"""共享配置 — 加载/保存 config.yaml，统一双方 CFG"""
import os, sys

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

DEFAULT_CFG = {
    "kp": 1.0, "ki": 0.15, "kd": 0.1, "target_usage": 45,
    "interval": 30, "never": [], "clean_mode": "normal",
    "auto_start": False, "auto_start_daemon": False,
    "auto_start_admin": False, "auto_start_minimize": False,
    "daemon_trim_every_ticks": 3, "scheduled_clean": None,
    "hotkey": "ctrl+shift+m", "game_processes": [],
    "clean_operations": ["ws", "standby", "modified", "filecache", "volume", "compress", "registry"],
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
    """加载 config.yaml，缺失字段用 DEFAULT_CFG 兜底"""
    d = DEFAULT_CFG.copy()
    if not os.path.isfile(CONFIG_PATH):
        return d
    try:
        if yaml:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                u = yaml.safe_load(f) or {}
        else:
            alt_path = CONFIG_PATH.replace(".yaml", ".json")
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

def save(cfg):
    """原子保存配置到 config.yaml（先写 tmp 再 rename，防止写半截崩溃）"""
    if not yaml:
        return
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        tmp = CONFIG_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
        os.replace(tmp, CONFIG_PATH)
    except Exception as e:
        import sys; print(f"[MemWise] 配置保存失败: {e}", file=sys.stderr)
