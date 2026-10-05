"""共享配置 — 加载/保存 config.yaml，统一双方 CFG"""
import os, sys, threading

# frozen windowed 下 sys.stderr 为 None，统一兜底（防 print(file=sys.stderr) 自身崩溃）
_ERR = sys.stderr or open(os.devnull, "w", encoding="utf-8")

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
    "interval": 60, "never": [], "clean_mode": "normal",
    # auto_start（普通权限快捷方式自启）已于 2026-08-15 移除，仅保留管理员权限自启
    "auto_start_daemon": False,
    "auto_start_admin": False, "auto_start_minimize": False,
    "gap_seconds": 12, "clean_passes": 4,
    "hotkey": "ctrl+shift+m", "game_hotkey": "ctrl+shift+g", "game_processes": [],
    "clean_operations": ["ws", "standby", "modified", "volume", "registry"],
    "emergency_threshold": 80, "log_to_file": False,
    "close_action": "ask", "tray_left_action": "show",
    "emergency_abs_pct": 0,  # 紧急触发兜底：可用内存百分比阈值（0=禁用；使用率阈值调高时的保险）
    "language": "zh_CN",  # 界面语言（zh_CN=简体中文 / en=English）
    "ws_caps": {},  # 工作集硬上限规则（高级选项）：{规范化路径: {"mb":int, "orig_max":int}}
}

# 清理操作合法键（GUI 六开关全量映射）；历史遗留键（compress/combine 等旧版操作名）
# 无任何消费方——加载时白名单清洗，防止死配置残留（名不副实）
CLEAN_OPS_WHITELIST = {"ws", "standby", "modified", "filecache", "volume", "registry"}


def _norm_proc_name(raw):
    """进程名规范化：去空格转小写，自动补 .exe 后缀（与 GUI _normalize_proc_name、
    cleaner._get_user_game_procs 同款）。config.load 归一 never 黑名单用——保证手改配置
    与 GUI 写入的条目口径一致（4 处消费方直接 `name in never` 比较快照带 .exe 名，
    不规范化则无后缀条目排除静默失效）"""
    n = str(raw).strip().lower()
    if n and not n.endswith(".exe"):
        n += ".exe"
    return n


def get_state_path():
    """获取 memwise_state.json 路径（运行时数据统一在 data/ 目录），兼容 PyInstaller 打包"""
    if getattr(sys, "frozen", False):
        exe_dir = os.path.dirname(sys.executable)
        if os.path.basename(exe_dir).lower() == "dist":
            base = os.path.dirname(exe_dir)
        else:
            base = exe_dir
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "data", "memwise_state.json")

def load():
    """加载 config.yaml，缺失字段用 DEFAULT_CFG 兜底。
    exe 旁无配置时回退打包内模板（_MEIPASS），保证独立部署首次运行即有完整配置"""
    # 深拷贝列表/字典默认值：防消费方 append/赋值污染 DEFAULT_CFG（曾见 clean_operations 被 toggle_op 追加）
    d = {k: (list(v) if isinstance(v, list) else (dict(v) if isinstance(v, dict) else v))
         for k, v in DEFAULT_CFG.items()}
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
        # 顶层键白名单（2026-08-14 审查）：历史遗留键（daemon_trim_every_ticks/scheduled_clean 等）
        # 零消费方，加载即过滤防残留（下次 save 自动清除，防死配置名不副实）
        _wl = set(DEFAULT_CFG.keys()) | {"efis_params"}
        for _k in list(d.keys()):
            if _k not in _wl:
                del d[_k]
        # 列表键类型归一：yaml 空值（never: / null）解析为 None，消费方 `in` 判断会 TypeError
        # （曾致守护线程崩溃）；统一归一为空列表（clean_operations 保留默认集合并走白名单清洗）
        for _k in ("never", "game_processes"):
            if not isinstance(d.get(_k), list):
                d[_k] = []
        # never 黑名单规范化（2026-09-06 审查 F9）：手改配置的无后缀条目（如 chrome）也能
        # 精准匹配快照进程名；幂等——GUI 写回的已规范化条目零变化，空/None 条目剔除
        d["never"] = [n for n in (_norm_proc_name(x) for x in d["never"] if x and str(x).strip()) if n]
        # 工作集硬上限规则（高级选项）：键=规范化完整路径；mb 钳 256-65536；条目上限 16
        # （先全量校验再截断——有效条目优先于位置）；非法/越界/畸形条目整体剔除
        _wc = d.get("ws_caps")
        if not isinstance(_wc, dict):
            _wc = {}
        _clean = {}
        for _k, _v in _wc.items():
            try:
                _mb = int(float(_v.get("mb", 0)))
                _om = int(float(_v.get("orig_max", 0)))
            except (TypeError, ValueError, AttributeError):
                continue
            if isinstance(_k, str) and _k and 256 <= _mb <= 65536 and _om > 0:
                _clean[_k.strip().lower().replace("/", "\\")] = {"mb": _mb, "orig_max": _om}
        d["ws_caps"] = dict(list(_clean.items())[:16])
        # efis_params 类型校验（2026-08-15 审查）：畸形配置（列表/字符串）会致
        # Judger 构造 .get 崩溃（启动即崩）；内层数值键清洗——手改字符串会在
        # PidController 运行时 TypeError（守护异常），坏键删除回退默认
        if not isinstance(d.get("efis_params"), dict):
            d["efis_params"] = {}
        else:
            for _k in list(d["efis_params"]):
                try:
                    float(d["efis_params"][_k])
                except (TypeError, ValueError):
                    del d["efis_params"][_k]
        # 数值键范围钳制（2026-08-30 审查；2026-09-11 扩充）：GUI 滑块范围是唯一合法面，手改
        # 越界值会绕过全部门槛——已实证两例：emergency_threshold:0 → 每周期固定紧急 full；
        # emergency_abs_pct ≥100 → "可用率 ≤ ap" 恒真 → 同样每周期恒紧急 full（本次新增钳制）。
        # target_usage 是 EFIS 同名参数的兜底（EFIS 恒提供该键），按其边界 35-65 钳制。
        for _k, _lo, _hi in (("emergency_threshold", 50, 99), ("emergency_abs_pct", 0, 99),
                             ("clean_passes", 2, 6), ("interval", 10, 3600),
                             ("gap_seconds", 8, 20), ("target_usage", 35, 65)):
            try:
                _v = int(float(d.get(_k, DEFAULT_CFG[_k])))
            except (TypeError, ValueError):
                _v = DEFAULT_CFG[_k]
            d[_k] = max(_lo, min(_hi, _v))
        if not isinstance(d.get("clean_operations"), list):
            d["clean_operations"] = [k for k in DEFAULT_CFG["clean_operations"] if k in CLEAN_OPS_WHITELIST]
        else:
            d["clean_operations"] = [k for k in d["clean_operations"] if k in CLEAN_OPS_WHITELIST]
    except Exception as e:
        print(f"[MemWise] 配置加载失败: {e}", file=_ERR)
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
            # tmp 附加进程号（2026-09-06 审查 F3）：跨进程并发写退化为"最后写者胜"而非交错损坏
            tmp = f"{CONFIG_PATH}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
            os.replace(tmp, CONFIG_PATH)
        except Exception as e:
            print(f"[MemWise] 配置保存失败: {e}", file=_ERR)
