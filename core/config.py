"""共享配置 — 加载/保存 config.yaml，统一双方 CFG"""
import os, sys

try:
    import yaml
except ImportError:
    yaml = None

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(BASE_DIR, "config", "config.yaml")

DEFAULT_CFG = {
    "kp": 0.6, "ki": 0.15, "kd": 0.1, "target_usage": 60,
    "interval": 30, "never": [], "clean_mode": "normal",
    "auto_start": False, "auto_start_daemon": False,
    "auto_start_admin": False, "auto_start_minimize": False,
    "daemon_trim_every_ticks": 3, "scheduled_clean": None,
    "hotkey": "ctrl+shift+m", "game_processes": [],
}

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
    except Exception:
        pass
    return d

def save(cfg):
    """保存配置到 config.yaml"""
    if not yaml:
        return
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
    except Exception:
        pass
