"""
MemWise v3.5.14 GUI —— 图形界面
系统托盘 + 全局热键 + 颜色状态 + 排除列表编辑 + 设置面板
"""

import os, sys, time, threading, tkinter as tk, math, queue, subprocess, concurrent.futures, datetime, atexit
from collections import deque
from tkinter import ttk, simpledialog, messagebox
import ctypes
import ctypes.wintypes as w

# ── 统一运行日志：单一时间线、线程安全、2MB×2 轮转 ──
# 记录运行期间全部有价值信息（生命周期/清理/决策/调参/配置/异常/系统/诊断）
# 看门狗（--watchdog）为独立进程，不混入主程序日志
_LOG_LOCK = threading.Lock()
_LOG_FD = None
_LOG_DIR = None
_LOG_MAX = 2 * 1024 * 1024  # 2MB/份
# frozen windowed（console=False）下 sys.stderr 为 None，print(file=_ERR) 自身抛 AttributeError
# （曾致 _opt_worker 异常路径崩溃、opt_done 不入队、优化按钮永久禁用）——统一兜底到 devnull
_ERR = sys.stderr or open(os.devnull, "w", encoding="utf-8")


def _log_ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _migrate_old_logs(path):
    """首启迁移：旧 memwise_crash.log 并入统一日志（仅一次；旧 memwise.log 即日志本体，append 天然连续）"""
    try:
        p = os.path.join(_LOG_DIR, "memwise_crash.log")
        if not (os.path.exists(p) and os.path.getsize(p) > 0):
            return
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            data = f.read()
        if not data.strip():
            return
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n──── 迁移自 memwise_crash.log ────\n{data.rstrip()}\n")
    except Exception:
        pass


def _log_rotate():
    """锁内调用：memwise.log → memwise.log.1（删除最旧），重开 fd 并重绑 faulthandler"""
    global _LOG_FD
    try:
        p0 = os.path.join(_LOG_DIR, "memwise.log")
        p1 = os.path.join(_LOG_DIR, "memwise.log.1")
        if _LOG_FD is not None:
            try:
                _LOG_FD.close()
            except Exception:
                pass
        if os.path.exists(p1):
            os.remove(p1)
        os.replace(p0, p1)
        _LOG_FD = open(p0, "a", encoding="utf-8", buffering=1)
        import faulthandler
        try:
            faulthandler.enable(_LOG_FD, all_threads=True)
        except Exception:
            pass
    except Exception:
        pass


def _log_write(cat, msg):
    """线程安全写入一行：[时间] [类别] 内容；受「记录运行日志到文件」开关总控（关=不写），超上限自动轮转"""
    cfg = globals().get('CFG')
    if cfg is None or not cfg.get('log_to_file') or _LOG_FD is None:
        return
    try:
        with _LOG_LOCK:
            try:
                if _LOG_FD.tell() > _LOG_MAX:
                    _log_rotate()
            except Exception:
                pass
            _LOG_FD.write(f"[{_log_ts()}][{cat}] {msg}\n")
            _LOG_FD.flush()
    except Exception:
        pass


def _log_close():
    """退出时关闭日志 fd（atexit 兜底）"""
    global _LOG_FD
    with _LOG_LOCK:
        if _LOG_FD is not None:
            try:
                _LOG_FD.close()
            except Exception:
                pass
            _LOG_FD = None


def _log_open():
    """按开关打开统一日志（幂等；主进程；看门狗跳过）；关闭状态不调用"""
    global _LOG_FD, _LOG_DIR
    if _LOG_FD is not None or "--watchdog" in sys.argv:
        return
    _LOG_DIR = os.environ.get("MEMWISE_LOG_DIR") or base
    path = os.path.join(_LOG_DIR, "memwise.log")
    try:
        _migrate_old_logs(path)  # 旧 crash log 并入（若存在），旧 memwise.log 继续 append
        _LOG_FD = open(path, "a", encoding="utf-8", buffering=1)
        import faulthandler
        faulthandler.enable(_LOG_FD, all_threads=True)

        def _crash_hook(et, ev, tb):
            import traceback
            _log_write("异常", "未捕获异常\n" + "".join(traceback.format_exception(et, ev, tb)))
            sys.__excepthook__(et, ev, tb)
        sys.excepthook = _crash_hook
        atexit.register(_log_close)
        _log_write("启动", f"MemWise v3.5.14 启动 · PID {os.getpid()} · 参数:{' '.join(sys.argv[1:]) or '无'}")
    except Exception:
        _LOG_FD = None


# 注意：_log_open 由 GUI __init__ 调用（CFG 就绪后按开关决定是否开启）


def _diag_log(msg):
    """诊断日志：写入统一运行日志"""
    _log_write("诊断", msg)

try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try: ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

if getattr(sys, "frozen", False):
    exe_dir = os.path.dirname(sys.executable)
    # exe 在 dist 目录下时，用项目根目录做数据目录，与脚本共用状态文件
    if os.path.basename(exe_dir).lower() == "dist":
        base = os.path.dirname(exe_dir)
    else:
        base = exe_dir
    res_dir = sys._MEIPASS                       # 资源文件（只读，打包内嵌）
else:
    base = os.path.dirname(os.path.abspath(__file__))
    res_dir = base
sys.path.insert(0, base)

from core import winapi
from core.learner import PareLearner as Learner
from core.judger import PareJudger as Judger
from core.cleaner import PareCleaner as Cleaner
from core.efis import EfisController
from core.sniffer import Sniffer
from core.icon_flat import FLAT_48_PNG, decode_png  # 任务栏扁平图标（内嵌 PNG，冷启动 exe 兼容）
from core.eris import iqr_dim, validate_state  # ERIS 纯函数核心（与回归测试共用）

# ── user32 图标/窗口句柄 API：必须声明 64 位位宽，否则 HICON 句柄被 c_int 截断 → WM_SETICON 静默失效（v3.4.19 图标失效根因）──
_Usr32 = ctypes.windll.user32
_Usr32.SendMessageW.restype = ctypes.c_void_p
_Usr32.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
_Usr32.SetClassLongPtrW.restype = ctypes.c_void_p
_Usr32.SetClassLongPtrW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
_Usr32.GetAncestor.restype = ctypes.c_void_p
_Usr32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
_Usr32.GetParent.restype = ctypes.c_void_p
_Usr32.GetParent.argtypes = [ctypes.c_void_p]
_Usr32.SetWindowPos.restype = ctypes.c_int
_Usr32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]

from core.config import load as _load_cfg
from core.config import get_state_path
import core.config as _config

def _save_cfg():
    _config.save(CFG)


def _normalize_proc_name(raw):
    """规范化程序名：去空格转小写，自动补 .exe 后缀（进程名统一格式）"""
    n = str(raw).strip().lower()
    if n and not n.endswith(".exe"):
        n += ".exe"
    return n


def _center_geometry(win, w, h, parent=None):
    """一次性定位窗口到父窗口中央（首次出现即居中，零闪烁），并钳制在屏幕内。
    替代"先默认位置弹出再移动"的两步 geometry，消除闪现与卡顿时不居中的问题"""
    parent = parent if parent is not None else win.master
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    try:
        px, py = parent.winfo_x(), parent.winfo_y()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        if pw < 10:  # 父窗口尚未布局时退化为屏幕居中
            px = py = 0; pw, ph = sw, sh
    except Exception:
        px = py = 0; pw, ph = sw, sh
    cx = px + (pw - w) // 2
    cy = py + (ph - h) // 2
    cx = max(0, min(cx, sw - w))
    cy = max(0, min(cy, sh - h))
    win.geometry(f"{w}x{h}+{cx}+{cy}")


def _parse_hotkey(spec):
    """解析 'ctrl+shift+m' / 'alt+f1' 格式热键 → (modifiers, vk, error)
    严格校验：至少一个修饰键（ctrl/alt/shift）+ 有效按键（单字母/F1-F24）；
    error 非空表示非法（不返回默认值，由调用方决定回退策略）"""
    mods = winapi.MOD_NOREPEAT
    key = None
    has_mod = False
    try:
        parts = [x.strip().lower() for x in str(spec).split("+")]
    except Exception:
        return None, None, "无法识别"
    if not parts or not any(parts):
        return None, None, "不能为空"
    key_count = 0
    for p in parts:
        if p in ("ctrl", "control"):
            mods |= winapi.MOD_CONTROL; has_mod = True
        elif p == "alt":
            mods |= winapi.MOD_ALT; has_mod = True
        elif p == "shift":
            mods |= winapi.MOD_SHIFT; has_mod = True
        elif len(p) == 1 and p.isalpha():
            key = ord(p.upper()); key_count += 1
        elif p.startswith("f") and p[1:].isdigit() and 1 <= int(p[1:]) <= 24:
            key = 0x70 + int(p[1:]) - 1; key_count += 1
        else:
            return None, None, f"无法识别按键「{p}」（需 ctrl/alt/shift + 单字母或 F1-F24）"
    if key_count > 1:
        return None, None, "只能包含一个按键（修饰键 + 单字母或 F1-F24）"
    if not has_mod:
        return None, None, "至少需要一个修饰键（ctrl/alt/shift）"
    if key is None:
        return None, None, "缺少按键（单字母或 F1-F24）"
    return mods, key, None


# ── EFIS 诊断输入辅助（守护周期构造 stats 用，全部现成数据零新增采集）──
def _prof_theta_mean(learner):
    ps = [p for p in learner.profiles.values() if p.total_samples >= 2]
    return sum(p.thompson_theta for p in ps) / len(ps) if ps else 0.3

def _prof_theta_above(learner):
    ps = [p for p in learner.profiles.values() if p.total_samples >= 2]
    return sum(1 for p in ps if p.thompson_theta > 0.6) / len(ps) if ps else 0.0

def _drain_pf_delta(judger):
    v = getattr(judger, "pf_delta_total", 0)
    judger.pf_delta_total = 0
    return v

STATE_FILE = get_state_path()
CFG = _load_cfg()

# 托盘和热键常量
HOTKEY_ID = 9001
GAME_HOTKEY_ID = 9002

# 全局热键注册表（统一管理，未来新增热键只需登记一行）
# name=显示名, key=配置键, default=默认值, id=热键 ID, action=触发动作（_wnd_proc 分发）
HOTKEYS = [
    {"name": "手动优化", "key": "hotkey", "default": "ctrl+shift+m", "id": HOTKEY_ID, "action": "hotkey"},
    {"name": "游戏模式开关", "key": "game_hotkey", "default": "ctrl+shift+g", "id": GAME_HOTKEY_ID, "action": "game"},
]
TRAY_UID = 1
GWLP_WNDPROC = -4
WM_HOTKEY = 0x0312
# 图标颜色名常量 — 传给 create_memwise_icon
ICO_IDLE = (70, 130, 180)     # 钢蓝 — 空闲
ICO_LOW  = (60, 160, 60)      # 绿   — 守护低压力
ICO_MID  = (200, 180, 40)     # 黄   — 守护中压力
ICO_ORANGE = (220, 140, 0)    # 橙   — 守护偏高压力
ICO_HIGH = (200, 60, 60)      # 红   — 守护高压力

# 全局引用 (供窗口过程回调使用)
_gui_ref = None
_orig_wndproc = None

# 托盘事件标志 — wndproc 仅设置此标志，由 Tkinter 轮询器安全处理
_tray_action = None  # 'left' | 'right' | 'hotkey' | None

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_void_p, w.HANDLE, w.UINT, ctypes.c_void_p, ctypes.c_void_p)


def _watchdog_path():
    """看门狗状态文件路径：与数据/日志目录一致（base，dist 部署时在项目根；主进程与 watchdog 子进程同 exe → 同路径）"""
    return os.path.join(base, "watchdog.json")

@WNDPROC
def _wnd_proc(hwnd, msg, wp, lp):
    """Win32 窗口过程回调 — 零 Tkinter 调用，仅设置 _tray_action 标志"""
    global _gui_ref, _tray_action
    try:
        # 系统关机/注销：立即删除 watchdog.json，防止看门狗误判并报错弹窗
        if msg in (0x0011, 0x0016):  # WM_QUERYENDSESSION / WM_ENDSESSION
            try:
                wd = _watchdog_path()
                if os.path.exists(wd):
                    os.remove(wd)
            except Exception:
                pass
            return winapi.CallWindowProcW(_orig_wndproc, hwnd, msg, wp, lp)
        if msg == winapi.WM_TRAYICON and _gui_ref is not None:
            if lp in (0x201, 0x202, 0x203):
                _tray_action = 'left'
            elif lp in (0x205, 0x007B):
                _tray_action = 'right'
            return 0
        if msg == WM_HOTKEY and wp == HOTKEY_ID and _gui_ref is not None:
            _tray_action = 'hotkey'
            return 0
        if msg == WM_HOTKEY and wp == GAME_HOTKEY_ID and _gui_ref is not None:
            _tray_action = 'game'
            return 0
    except Exception:
        pass
    return winapi.CallWindowProcW(_orig_wndproc, hwnd, msg, wp, lp)


# ---- Tooltip 辅助类 ----

class ToolTip:
    """为任意 widget 添加鼠标悬停提示"""
    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._tw = None
        self._id = None
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Leave>", self._leave, add="+")

    def _enter(self, e):
        self._id = self.widget.after(self.delay, self._show)

    def _leave(self, e):
        if self._id:
            self.widget.after_cancel(self._id); self._id = None
        self._hide()

    def _show(self):
        if self._tw: return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self._tw = tk.Toplevel(self.widget)
        self._tw.wm_overrideredirect(True)
        self._tw.wm_geometry(f"+{x}+{y}")
        lbl = tk.Label(self._tw, text=self.text, justify="left",
                       bg="#2d2d2d", fg="#eee", font=("Microsoft YaHei UI", 9),
                       padx=8, pady=4, wraplength=800)
        lbl.pack()

    def _hide(self):
        if self._tw:
            self._tw.destroy(); self._tw = None


# ═══ 看门狗入口 — 无 GUI，纯监控 + 崩溃重启 ═══
if "--watchdog" in sys.argv:
    wd_path = _watchdog_path()
    _ = __name__  # noqa
    def _watchdog_loop():
        import json
        exe = sys.executable
        crash_history = []  # [(timestamp, ...)]
        while True:
            time.sleep(5)
            # 系统正在关机？立即退出，不做任何重启尝试
            if ctypes.windll.user32.GetSystemMetrics(0x2000):  # SM_SHUTTINGDOWN
                break
            if not os.path.exists(wd_path):
                break
            try:
                with open(wd_path, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                continue
            pid = d.get("pid", 0)
            if pid <= 0:
                continue
            # 检查父进程是否存活（OpenProcess 失败=进程对象已销毁=已死，走重启路径）
            h = ctypes.windll.kernel32.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
            if not h:
                alive = False
            else:
                alive = ctypes.windll.kernel32.WaitForSingleObject(h, 0) != 0  # WAIT_OBJECT_0=0
                ctypes.windll.kernel32.CloseHandle(h)
            if alive:
                continue
            # 父进程已死 → 检查崩溃计数
            now = time.time()
            crash_history = [t for t in crash_history if now - t < 180]
            crash_history.append(now)
            if len(crash_history) >= 3:
                try: os.remove(wd_path)
                except Exception: pass
                break
            # 重启前再次确认文件仍在（防止 wndproc 在检测死亡和重启之间删除）
            if not os.path.exists(wd_path):
                break
            # 重启
            try:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= 0x00000001  # STARTF_USESHOWWINDOW
                si.wShowWindow = 0        # SW_HIDE
                # DETACHED_PROCESS + 错误重定向：抑制关机时的 C 层错误弹窗
                if getattr(sys, "frozen", False):
                    _cmd = [exe, "--restored"]
                else:
                    _cmd = [exe, os.path.abspath(__file__), "--restored"]
                p = subprocess.Popen(_cmd,
                    startupinfo=si, creationflags=0x08000008,  # CREATE_NO_WINDOW | DETACHED_PROCESS
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # 更新 watchdog.json 为新 PID（保留崩溃前的守护状态，供恢复分支判断）；tmp+replace 原子写，与主进程协议一致
                with open(wd_path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump({"pid": p.pid, "ts": now, "crash_count": len(crash_history),
                               "daemon": d.get("daemon", False)}, f)
                os.replace(wd_path + ".tmp", wd_path)
            except Exception:
                continue
    _watchdog_loop()
    sys.exit(0)


SINGLE_MUTEX_NAME = "Global\\MemWise_v3.5.14_SingleInstance"


class MemWiseGUI:
    def __init__(self):
        if CFG.get("log_to_file"):
            _log_open()  # 统一日志：按「记录运行日志到文件」开关开启（关=完全不写）
        global _gui_ref
        _gui_ref = self

        # 单实例检测 — 已有实例运行则激活后退出
        # Global\ 命名空间：管理员实例运行时普通进程 CreateMutexW 返回 ERROR_ACCESS_DENIED(5)
        # 而非 ALREADY_EXISTS(0xB7)——两者均视为已有实例，防双守护/双看门狗并发
        self._mutex = ctypes.windll.kernel32.CreateMutexW(None, False, SINGLE_MUTEX_NAME)
        _mutex_err = ctypes.windll.kernel32.GetLastError()
        if _mutex_err in (0xB7, 5):
            # 激活已有窗口（0xB7 权威；5 且句柄空时以窗口存在性兜底验证）
            hwnd = ctypes.windll.user32.FindWindowW(None, "MemWise v3.5.14")
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
                self._mutex = None
                sys.exit(0)
            if _mutex_err == 0xB7 or not self._mutex:
                # mutex 已存在但窗口找不到（残留句柄）或权限拒绝无窗口：防双开，直接退出
                self._mutex = None
                sys.exit(0)
            _log_write("诊断", "单实例互斥权限受限且无窗口，继续运行")
        
        # 崩溃恢复检测
        self._restored = "--restored" in sys.argv
        self._minimized_to_tray = False  # 显式初始化（--minimized 分支下方覆盖为 True）

        self.root = tk.Tk()
        self.root.withdraw()  # 先隐藏：居中定位后再统一显示，消除"默认位置闪现"
        self.root.title("MemWise v3.5.14")
        # --minimized 参数（仅开机自启携带）：保持隐藏；手动启动不最小化到托盘
        if "--minimized" in sys.argv:
            self._minimized_to_tray = True
        self.root.resizable(True, False)
        _center_geometry(self.root, 1060, 700)

        # 窗口图标 — 用 MemWise 自定义 HICON（直接内存创建，不走 .ico 文件）
        # winfo_id 是 Tk 的 client 窗口，标题栏图标必须发给 wrapper 顶层；
        # 窗口层级在 mainloop 后才完整，故延迟 100ms 设置（过早 GetParent 返回 0 导致图标失效）
        self.root.after(100, self._set_main_window_icon)

        # ── 主界面初始化（原错挂在 _set_main_window_icon 的 after 回调内，移回 __init__ 保证确定性）──
        self._custom_hicon = None
        self._icon_cache = {}  # name -> HICON
        self._optimizing = False  # 防止并发优化

        self.learner = Learner.load(STATE_FILE)
        jcfg = {"kp":CFG.get("kp",0.6),"ki":CFG.get("ki",0.15),"kd":CFG.get("kd",0.1),
                "target_usage":CFG.get("target_usage",60),"never":CFG.get("never",[]),
                "game_processes":CFG.get("game_processes",[]),
                "efis_params":CFG.get("efis_params",{})}
        self.judger = Judger(self.learner, jcfg)
        self.cleaner = Cleaner(self.judger)
        self.efis = EfisController(STATE_FILE)
        # 启动即用 EFIS 持久化参数对齐运行时消费方（config.yaml 可能滞后于 efis_state.json）
        self.judger.cfg["efis_params"] = self.efis.get_params()
        # kalman_r 同步：新画像的 Kalman 观测噪声与 EFIS 调参结果一致（原只在调参轮生效，重启后回默认）
        self.learner._kalman_r = self.efis.get_params().get('kalman_r', 5.0)
        self.sniffer = Sniffer()
        self.daemon_running = False; self.daemon_thread = None
        self._tray_icon_handle = None
        # 注意：_minimized_to_tray 已在上方初始化（--minimized/auto_start_minimize 分支），此处不得重复赋值覆盖
        # 柱图状态
        self._chart_data = deque(maxlen=60)
        self._chart_last_freed = 0.0
        self._prev_trim_count = 0
        self._prev_fail_count = 0
        self._msg_queue = queue.Queue()  # 线程安全消息队列
        self._mem_pct = 0
        self._eff_data = deque(maxlen=60)  # 效率折线数据
        self._eff_factors = deque(maxlen=60)  # 效率主导因子
        self._chart_lock = threading.Lock()
        self._eris_lock = threading.Lock()  # ERIS 分位数窗读写互斥锁
        self._chart_cycle_meta = deque(maxlen=60)  # 每轮元数据(seq,trimmed,failed,mem_pct,failed_weight,partial)
        self._chart_eris_last_seq = -1  # 最后进入ERIS的轮次序列号（替代绝对索引，防maxlen边界bug）
        self._chart_bar_seq = 0  # 全局轮次序列号（daemon递增）
        self._load_eris_ewma()  # 在 daemon 或 chart 首次调用 _compute_eris 前完成加载

        self._build_ui()
        self._refresh_mem()
        self._setup_hotkey_and_tray()
        adm = "✓" if winapi.is_elevated() else "✗"
        self._log(f"MemWise v3.5.14 启动· 当前是否管理员权限:{adm}")
        # 看门狗：spawn 子进程监控崩溃
        if not self._restored:
            self._spawn_watchdog()
        else:
            self._log("🔄 检测到上次崩溃，已自动恢复")
            # 恢复守护模式（仅当崩溃前守护运行中；否则保持空闲，尊重用户意图）
            # 延迟触发，让窗口完全初始化后再启动
            self.root.after(800, self._maybe_restore_daemon)
        if winapi.is_elevated():
            winapi.enable_reduct_privileges()
        # 启动消息队列轮询（每 100ms 检查一次，主线程安全）
        self._poll_msg_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if CFG.get("auto_start_daemon"):
            if "--minimized" in sys.argv:
                self._on_daemon()  # 自启动：立即守护，不等待
            else:
                self.root.after(300, self._on_daemon)

    def _set_main_window_icon(self):
        """设置主窗口图标到顶层 wrapper（标题栏），client 双设兜底。
        幂等：HICON 首次创建后缓存复用（重复调用零 GDI 泄漏）；供映射后重设兜底"""
        try:
            if not hasattr(self, '_icon_big_h') or not self._icon_big_h:
                # 任务栏专用：simple_flat_48 扁平成品（PNG 解码 → CreateIconIndirect 同动态通道）；失败回退动态立体渲染
                try:
                    pw, ph, rgba = decode_png(FLAT_48_PNG)
                    self._icon_big_h = winapi.create_hicon_from_rgba(pw, ph, rgba)
                except Exception as exc:
                    self._icon_big_h = None
                    _diag_log(f"扁平图标解码异常: {exc!r}")
                if not self._icon_big_h:
                    _diag_log("扁平图标加载失败，回退动态渲染")
                    self._icon_big_h = winapi.create_memwise_icon(48, (88, 88, 100), force_large=True, sharpen=True)
                self._icon_sml_h = winapi.create_memwise_icon(16)
            big_h = self._icon_big_h
            sml_h = self._icon_sml_h
            if not big_h or not sml_h:
                _diag_log(f"主图标生成失败 big={big_h} sml={sml_h}")
                return
            wid = int(self.root.winfo_id())
            # wrapper = client 的父/祖先（标题栏所在）；GetAncestor 失败时退化到自身
            top = ctypes.windll.user32.GetAncestor(wid, 2) or ctypes.windll.user32.GetParent(wid) or wid
            # 启动早期 wrapper 可能尚未创建（GetAncestor 返回自身）：FindWindowExW 找隐藏 TkTopLevel（withdrawn 亦可）
            if not top or top == wid:
                try:
                    fw = ctypes.windll.user32.FindWindowExW(None, None, "TkTopLevel", "MemWise v3.5.14")
                    if fw:
                        top = fw
                except Exception:
                    pass
            for t in (top, wid):
                if not t:
                    continue
                ctypes.windll.user32.SendMessageW(t, 0x0080, 1, big_h)   # WM_SETICON ICON_BIG
                ctypes.windll.user32.SendMessageW(t, 0x0080, 0, sml_h)   # WM_SETICON ICON_SMALL
            # 类图标：设到顶层类（TkTopLevel），所有弹窗自动继承
            ctypes.windll.user32.SetClassLongPtrW(top, -14, big_h)
            ctypes.windll.user32.SetClassLongPtrW(top, -34, sml_h)
            _check = _Usr32.SendMessageW(top, 0x007F, 1, 0)
            # 强制重绘边框：任务栏按钮图标可能不随 WM_SETICON 主动刷新（SWP_FRAMECHANGED）
            _Usr32.SetWindowPos(top, 0, 0, 0, 0, 0,
                                0x0001 | 0x0002 | 0x0004 | 0x0020)  # NOSIZE|NOMOVE|NOZORDER|FRAMECHANGED
            _diag_log(f"主图标: top={top} wid={wid} 自检一致:{int(_check or 0) == int(big_h or 0)}")
        except Exception as e:
            _diag_log(f"主图标设置异常: {e!r}")

    # ---- 窗口过程 + 热键 + 托盘 ----

    def _get_colored_icon(self, name, color):
        """缓存获取或创建指定颜色的 HICON"""
        if name not in self._icon_cache:
            self._icon_cache[name] = winapi.create_memwise_icon(32, color, shadow=False, gradient=0.12)
        return self._icon_cache[name]

    def _setup_hotkey_and_tray(self):
        global _orig_wndproc
        hwnd = int(self.root.winfo_id())
        # 子类化窗口过程
        _orig_wndproc = winapi.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(_wnd_proc, ctypes.c_void_p))
        # 注册全部全局热键（统一入口：解析/冲突/占用检测，失败提示不阻断运行）
        self._apply_hotkeys(initial=True)
        hIcon = self._get_colored_icon("idle", ICO_IDLE)
        self._tray_icon_handle = hIcon
        ok = winapi.tray_add(hwnd, TRAY_UID, hIcon, "MemWise — 智能内存看护")
        if not ok:
            self._log("⚠ 托盘图标添加失败，重试...")
            time.sleep(0.5)
            ok = winapi.tray_add(hwnd, TRAY_UID, hIcon, "MemWise — 智能内存看护")

    def _apply_hotkeys(self, initial=False):
        """按配置重注册全部全局热键（统一入口：注销→逐项解析→冲突检测→逐个注册）。
        非法/冲突/被占用时本次使用默认值并提示，不写回 CFG（保留用户配置下次启动再试）；
        initial=True 为启动路径，静默细节差异"""
        try:
            hwnd = int(self.root.winfo_id())
            for hk in HOTKEYS:
                winapi.unregister_hotkey(hwnd, hk["id"])
            # 逐项解析（非法 → 本次用默认）
            pairs = []
            for hk in HOTKEYS:
                spec = CFG.get(hk["key"], hk["default"])
                mods, vk, err = _parse_hotkey(spec)
                if err:
                    self._log(f"⚠ {hk['name']}热键配置无效（{err}），本次使用默认 {hk['default']}")
                    mods, vk, _ = _parse_hotkey(hk["default"])
                pairs.append([hk, mods, vk])
            # 冲突检测（后注册者本次用默认）
            for i in range(len(pairs)):
                for j in range(i + 1, len(pairs)):
                    if pairs[i][1] == pairs[j][1] and pairs[i][2] == pairs[j][2]:
                        self._log(f"⚠ {pairs[j][0]['name']}热键与{pairs[i][0]['name']}冲突，本次使用默认 {pairs[j][0]['default']}")
                        pairs[j][1], pairs[j][2], _ = _parse_hotkey(pairs[j][0]["default"])
            # 逐个注册
            for hk, mods, vk in pairs:
                if winapi.register_hotkey(hwnd, hk["id"], mods, vk):
                    if not initial:
                        self._log(f"{hk['name']}热键已设为 {CFG.get(hk['key'], hk['default'])}")
                else:
                    self._log(f"⚠ {hk['name']}热键注册失败（可能被其他程序占用）: {CFG.get(hk['key'], hk['default'])}")
                    dm, dv, _ = _parse_hotkey(hk["default"])
                    winapi.register_hotkey(hwnd, hk["id"], dm, dv)
        except Exception:
            pass

    def _update_tray_status(self, pct):
        """根据内存使用率和守护状态更新托盘图标颜色（4档匹配内存条）"""
        pct_icon_handle = winapi.create_tray_percent_icon(pct)
        if self.daemon_running:
            if pct >= 90:
                icon = pct_icon_handle or self._get_colored_icon("high", ICO_HIGH)
                tip = f"🔴 守护中 {pct}% — 内存紧张"
            elif pct >= 75:
                icon = pct_icon_handle or self._get_colored_icon("mid2", ICO_ORANGE)
                tip = f"🟠 守护中 {pct}% — 内存偏高"
            elif pct >= 60:
                icon = pct_icon_handle or self._get_colored_icon("mid", ICO_MID)
                tip = f"🟡 守护中 {pct}% — 内存偏高"
            else:
                icon = pct_icon_handle or self._get_colored_icon("low", ICO_LOW)
                tip = f"🟢 守护中 {pct}% — 正常"
        else:
            if pct >= 90:
                icon = self._get_colored_icon("idle_high", ICO_HIGH)
                tip = f"内存 {pct}% — 紧张"
            elif pct >= 75:
                icon = self._get_colored_icon("idle_mid2", ICO_ORANGE)
                tip = f"内存 {pct}% — 偏高"
            elif pct >= 60:
                icon = self._get_colored_icon("idle_mid", ICO_MID)
                tip = f"内存 {pct}% — 偏高"
            else:
                icon = self._get_colored_icon("idle", ICO_IDLE)
                tip = f"内存 {pct}%"
        # 释放旧图标防止 GDI 泄漏（长期运行崩溃根因）
        try:
            if pct_icon_handle and hasattr(self, '_prev_pct_icon'):
                ctypes.windll.user32.DestroyIcon(self._prev_pct_icon)
            self._prev_pct_icon = pct_icon_handle
        except Exception:
            pass
        self._tray_icon_handle = icon
        winapi.tray_modify(self.root.winfo_id(), TRAY_UID, icon, f"MemWise — {tip}")

    def _on_tray_left_click(self):
        """托盘左键单击 — 在 Tkinter 事件循环中安全处理"""
        try:
            state = self.root.state()
            if self._minimized_to_tray or state in ("iconic", "withdrawn"):
                act = CFG.get("tray_left_action", "show")
                if act == "clean":
                    self._on_optimize()
                elif act == "show":
                    self._show_window()
        except Exception:
            pass

    def _show_tray_menu(self):
        """右键托盘菜单 — Win32 原生弹出菜单"""
        if not self.root.winfo_exists():
            return
        try:
            import ctypes, ctypes.wintypes as wt
            um = ctypes.windll.user32
            hwnd = self.root.winfo_id()
            # 创建菜单
            hmenu = um.CreatePopupMenu()
            ID_SHOW = 1001
            ID_EXIT = 1002
            um.AppendMenuW(hmenu, 0x00000000, ID_SHOW, "显示窗口")
            um.AppendMenuW(hmenu, 0x00000800, 0, None)  # MF_SEPARATOR
            um.AppendMenuW(hmenu, 0x00000000, ID_EXIT, "退出")
            # 获取鼠标位置
            pt = wt.POINT()
            um.GetCursorPos(ctypes.byref(pt))
            # 前置窗口（TrackPopupMenu 要求）
            um.SetForegroundWindow(hwnd)
            # 弹出菜单（阻塞直到选择或取消）
            cmd = um.TrackPopupMenu(hmenu, 0x0020 | 0x0002 | 0x0100, pt.x, pt.y, 0, hwnd, None)
            # TPM_RETURNCMD=0x0100 | TPM_RIGHTBUTTON=0x0002 | TPM_TOPALIGN=0x0000
            um.DestroyMenu(hmenu)
            # 执行操作
            if cmd == ID_SHOW:
                self._show_window()
            elif cmd == ID_EXIT:
                self.root.after(50, self._do_exit)
        except Exception:
            pass

    def _minimize_to_tray(self):
        self.root.withdraw()
        self._minimized_to_tray = True

    def _show_window(self):
        """恢复主窗口 — 在 Tkinter 事件循环中安全调用"""
        try:
            # 先隐藏 → 重新居中 → 显示（恢复位置可能被系统重置，避免错位闪烁）
            self.root.withdraw()
            _center_geometry(self.root, 1060, 700)
            # 图标必须早于窗口映射就绪：任务栏按钮在首次映射时缓存图标，此后 WM_SETICON 不刷新按钮
            # （标题栏会刷新、任务栏不会——v3.4.19 --minimized/自启场景任务栏立绘根因）
            self._set_main_window_icon()
            self.root.deiconify()
            if self.root.state() == "iconic":
                self.root.deiconify()
            self.root.lift()
            self._minimized_to_tray = False
            # 先完成映射（wrapper 创建）再设置图标：deiconify 前 wrapper 不存在，设置会落到 client 无效
            self.root.update_idletasks()
            # 图标重设：--minimized/托盘期间窗口未映射，wrapper 未创建；恢复后必须重设到 wrapper（幂等缓存句柄零泄漏）
            # 否则标题栏回退 Tk 默认黑色羽毛、任务栏回退 exe 资源立体图标（v3.4.19 重启自启场景根因）
            self._set_main_window_icon()
            self.root.after(150, self._set_main_window_icon)
            # 触发 <Configure> → _on_chart_configure(50ms) 自动渲染
            self.root.update_idletasks()
            # 兜底：极端情况下 <Configure> 未触发，500ms 后强制绘制
            self._drawing_chart = False
            if self._chart_redraw_id is not None:
                self.root.after_cancel(self._chart_redraw_id)
            self._chart_redraw_id = self.root.after(500, self._draw_chart)
        except Exception as e:
            import sys; print(f"[MemWise] _show_window 异常: {e}", file=_ERR)

    def _on_hotkey(self):
        """Ctrl+Shift+M → 执行一键优化"""
        self._show_window()
        self._on_optimize()

    def _on_toggle_game(self):
        """Ctrl+Shift+G → 手动切换游戏模式"""
        game = not self.cleaner.game_mode
        action = "启用" if game else "关闭"
        # 自定义确认弹窗
        dlg = tk.Toplevel(self.root)
        dlg.withdraw()  # 先隐藏，构建完成居中后一次显示
        self._apply_icon(dlg)
        dlg.title("游戏模式")
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.focus_set()
        dlg.grab_set()
        dlg.configure(bg="#1c1c1c")
        _center_geometry(dlg, 400, 180)
        ttk.Label(dlg, text=f"确认{action}游戏模式？", font=("微软雅黑", 11, "bold"),
                  background="#1c1c1c", foreground="#e0e0e0").pack(pady=(18, 2))
        desc1 = "启用后将对游戏进程实施绝对保护，" if game else "关闭后将恢复正常清理策略，"
        desc2 = "非游戏进程将被激进清理以腾出内存。" if game else "游戏进程不再受额外保护。"
        ttk.Label(dlg, text=desc1,
                  background="#1c1c1c", foreground="#aaa").pack()
        ttk.Label(dlg, text=desc2,
                  background="#1c1c1c", foreground="#aaa").pack()
        btn_frame = ttk.Frame(dlg, style="Dark.TFrame"); btn_frame.pack(pady=12)
        s = ttk.Style()
        s.configure("Dark.TFrame", background="#1c1c1c")
        result = {"value": False}
        def on_yes():
            result["value"] = True; dlg.destroy()
        def on_no():
            dlg.destroy()
        ttk.Button(btn_frame, text="确认", command=on_yes).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="取消", command=on_no).pack(side="left", padx=6)
        dlg.deiconify()
        dlg.wait_window()
        if not result["value"]:
            return
        self.cleaner.game_mode = game
        self.cleaner.judger.game_mode = game
        self.cleaner._game_mode_manual = True  # 手动设置后模式由用户持有，自动检测不再覆盖
        if not game:
            # 手动关闭后恢复自动检测（与 tooltip「自动检测或手动开启」语义一致）
            self.cleaner._game_mode_manual = False
        _log_write("决策", f"游戏模式手动{'启用' if game else '关闭'}")
        if game:
            self._log("🎮 游戏模式已手动启用 · 游戏进程受保护")
        else:
            self._log("🎮 游戏模式已手动关闭 · 恢复正常清理")
            self.cleaner.judger._game_proc_set.clear()
            self.cleaner.judger._game_pid_set.clear()
    # ---- UI 构建 ----

    def _add_tip(self, w, txt):
        ToolTip(w, txt)

    def _build_ui(self):
        # 内存状态 (Canvas 彩色条)
        f = ttk.LabelFrame(self.root, text="内存状态", padding=8)
        f.pack(fill="x", padx=12, pady=(12,4))
        self.mem_canvas = tk.Canvas(f, height=22, bg="#eee", highlightthickness=0)
        self.mem_canvas.pack(fill="x", pady=(0,4))
        self.mem_bar_rect = self.mem_canvas.create_rectangle(0, 0, 0, 22, fill="#4caf50", width=0)
        self.mem_bar_text = self.mem_canvas.create_text(8, 11, anchor="w", text="--%", font=("Segoe UI", 9, "bold"), fill="#fff")
        self._add_tip(self.mem_canvas,
            "内存条颜色指示当前物理内存使用率：\n"
            "  · 绿色 — 低于 60%，内存充裕\n"
            "  · 黄色 — 60~74%，建议关注\n"
            "  · 橙色 — 75~89%，偏高，建议清理\n"
            "  · 红色 — 90% 以上，内存紧张\n"
            "\n"
            "长期处于红色说明物理内存不足\n"
            "建议关闭部分程序或考虑增加内存。")
        info = ttk.Frame(f); info.pack(fill="x")
        self.lbl_total = ttk.Label(info, text="总: -- GB"); self.lbl_total.pack(side="left", padx=(0,12))
        self.lbl_used = ttk.Label(info, text="已用: -- GB"); self.lbl_used.pack(side="left", padx=(0,12))
        self.lbl_avail = ttk.Label(info, text="可用: -- GB"); self.lbl_avail.pack(side="left", padx=(0,12))
        self.lbl_pct = ttk.Label(info, text="--%"); self.lbl_pct.pack(side="right")

        # 按钮
        bf = ttk.Frame(self.root); bf.pack(fill="x", padx=12, pady=6)
        self.btn_opt = ttk.Button(bf, text="⚡ 优化", command=self._on_optimize)
        self.btn_opt.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_opt,
            "⚡ 按当前选择的清理模式立即执行一次优化\n"
            "\n"
            "四种力度由轻到重：\n"
            "  · quick — 仅系统级清理，零卡顿，适合随手一点\n"
            "  · normal — 进程级 + 系统级清理，日常使用无副作用\n"
            "  · deep — 追加文件缓存清理和深层重复回收\n"
            "  · full — 极限释放，关闭大量程序后效果最好\n"
            "\n"
            "进程级清理由智能评分引擎决定优先清理谁，\n"
            "并通过清理前后的缺页变化来验证效果。\n"
            "游戏模式下游戏进程受绝对保护，其余进程被持续智能清理。\n"
            "\n"
            "守护运行中点击：改为即时执行一次轻量系统清理\n"
            "（游戏进行中会跳过，保障流畅）\n"
            "\n"
            "⚠ 缓存类清理需要管理员权限\n"
            "⚠ deep/full 清文件缓存后，打开大文件可能短暂变慢")
        self.btn_dae = ttk.Button(bf, text="⛨ 守护", command=self._on_daemon)
        self.btn_dae.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_dae,
            "⛨ 后台守护模式，每 60 秒输出一轮清理结果\n"
            "\n"
            "持续交替执行轻量压制与全量收割：\n"
            "  · 轻量阶段 — 系统级清理，高频温和，不影响使用\n"
            "  · 收割阶段 — 按你选的清理模式全力释放进程内存\n"
            "\n"
            "内置自适应调参，自动根据系统状态调整清理策略。\n"
            "游戏模式自动检测或手动开启，保护游戏性能。\n"
            "程序意外崩溃后自动恢复。\n"
            "\n"
            "⚠ 缓存类清理需要管理员权限\n"
            "⚠ 进程级清理无需管理员权限即可生效")
        self.btn_stop = ttk.Button(bf, text="▶ 停止", command=self._stop_daemon, state="disabled")
        self.btn_stop.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_stop,
            "▶ 停止后台自动清理\n"
            "\n"
            "停止后已学习的数据（各进程的行为画像、清理历史、释放量统计）\n"
            "会自动保存，下次启动继续使用，不会丢失。\n"
            "守护期间累积的统计数字会保留在界面上。")
        self.btn_excl = ttk.Button(bf, text="⚙ 排除", command=self._edit_exclusion_list)
        self.btn_excl.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_excl,
            "⚙ 进程排除列表\n"
            "\n"
            "在这里添加不想被清理的程序（输入程序名如 chrome，不带后缀自动补全）。\n"
            "添加后该进程将被完全跳过：\n"
            "  · 不释放其闲置内存\n"
            "  · 不设低内存优先级\n"
            "  · 不参与试探性清理\n"
            "\n"
            "适合添加：正在用的浏览器、开发工具、播放器\n"
            "\n"
            "⚠ 排除太多程序会明显降低释放效果\n"
            "⚠ 系统核心进程始终受自动保护，不受排除列表影响")
        self.btn_set = ttk.Button(bf, text="☰ 设置", command=self._open_settings)
        self.btn_set.pack(side="left")
        self._add_tip(self.btn_set,
            "☰ 打开详细设置面板\n"
            "\n"
            "可配置的内容：\n"
            "  清理操作 — 8 种操作独立开关\n"
            "  触发与日志 — 紧急阈值、守护间隔、托盘行为、文件日志、清理深度\n"
            "  游戏模式 — 管理自定义游戏进程名单\n"
            "  关闭行为 — 窗口关闭时最小化或退出\n"
            "\n"
            "清理模式在主界面下拉框切换（quick / normal / deep / full）")
        self.btn_log = ttk.Button(bf, text="📜 学习日志", command=self._show_learn_log)
        self.btn_log.pack(side="left", padx=(6,0))
        self._add_tip(self.btn_log,
            "📜 查看每个进程的详细学习数据\n"
            "\n"
            "各列含义：\n"
            "  · α / β — 历史成功与失败的累计次数，决定可信度评分\n"
            "  · 可信度 — 越高越值得清理，综合了历史表现和预期收益\n"
            "  · 收益比 — 预期释放量(MB) vs 性能代价(PF)，性价比参考\n"
            "  · 偏差 — 内存用量的异常波动程度，越大越反常\n"
            "  · 趋势 — 内存增长斜率，正数表示内存在持续增长\n"
            "  · 泄漏 — 是否疑似内存泄漏（持续增长且清完很快回涨）\n"
            "  · 清理 — 累计被清理次数 / 试探成功 / 试探失败\n"
            "\n"
            "这些数据帮你判断哪些进程值得清理、哪些清完很快又涨回来")

        # 状态文字单独放一行，避免按钮被挤出
        self.lbl_st = ttk.Label(bf, text="就绪 · Ctrl+Shift+M")
        self.lbl_st.pack(side="bottom", fill="x")

        # 模式选择
        mf = ttk.Frame(self.root); mf.pack(fill="x", padx=12, pady=(0,6))
        ttk.Label(mf, text="清理模式:").pack(side="left")
        self.mode_var = tk.StringVar(value=CFG.get("clean_mode", "normal"))
        self.mode_combo = ttk.Combobox(mf, textvariable=self.mode_var, width=12,
                                        values=["quick","normal","deep","full"], state="readonly")
        self.mode_combo.bind("<MouseWheel>", lambda e: "break")  # 禁用滚轮：只接受点击选择，防误改
        self.mode_combo.pack(side="left", padx=(4,0))
        self._add_tip(self.mode_combo,
            "选择清理力度，优化按钮和守护模式共用此设置：\n"
            "\n"
            "  quick — 仅系统级清理，几秒完成，零卡顿\n"
            "    适合：随手一点，不想有任何感知\n"
            "\n"
            "  normal — 进程级 + 系统级清理，日常使用无副作用\n"
            "    适合：日常使用，兼顾效果与流畅\n"
            "\n"
            "  deep — 追加文件缓存清理和深层重复回收\n"
            "    适合：内存偏紧，接受文件打开短暂变慢\n"
            "\n"
            "  full — 极限释放，关闭大量程序后效果最好\n"
            "    适合：清出极限空间\n"
            "\n"
            "⚠ 切换后守护模式即时生效，无需重启")
        # 自动持久化清理模式选择
        def _on_mode_change(*args):
            global CFG
            new_mode = self.mode_var.get()
            last_mode = getattr(self, '_last_logged_mode', '')
            if new_mode != last_mode:
                self._log(f"调整清理模式为：{new_mode}")
                self._last_logged_mode = new_mode
            CFG["clean_mode"] = new_mode
            _save_cfg()
        self.mode_var.trace_add("write", _on_mode_change)
        self.btn_game = ttk.Button(mf, text="🎮 游戏模式", command=self._on_toggle_game)
        self.btn_game.pack(side="left", padx=(6,0))
        self._add_tip(self.btn_game,
            "🎮 手动开启或关闭游戏模式\n"
            "\n"
            "开启后：\n"
            "  · 游戏进程受绝对保护，不被触碰\n"
            "  · 非游戏进程被持续智能清理，为游戏腾出内存\n"
            "  · 跳过全系统缓存清理，避免拖慢磁盘\n"
            "  · 最大化游戏可用内存\n"
            "\n"
            "热键：Ctrl+Shift+G（可在设置 → 全局热键中更改）\n"
            "⚠ 游戏进程名需先在设置 → 游戏模式中添加\n"
            "⚠ 按程序名自动识别运行中的实例，同名程序的所有实例都会被保护\n"
            "⚠ 常用辅助程序（语音、游戏平台）若受影响，可加入排除列表")
        self.btn_rank = ttk.Button(mf, text="📊 进程排行", command=self._show_process_rank)
        self.btn_rank.pack(side="left", padx=(6,0))
        self._add_tip(self.btn_rank,
            "📊 查看当前所有进程的内存占用排行\n"
            "\n"
            "按内存占用从大到小排列，实时快照。\n"
            "快速定位哪些进程最占内存。\n"
            "\n"
            "点击列标题可切换排序方式")
        ttk.Label(mf, text="  ").pack(side="left")

        # 统计
        sf = ttk.LabelFrame(self.root, text="统计", padding=8)
        sf.pack(fill="x", padx=12, pady=4)
        self.lbl_sb = ttk.Label(sf, text="系统杂项: 0"); self.lbl_sb.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_sb,
            "系统级清理操作的总次数\n"
            "\n"
            "包括：待机缓存清空、脏页写回、文件缓存清除、\n"
            "卷缓存刷新、注册表缓存等。\n"
            "\n"
            "⚠ 需要管理员权限才生效\n"
            "⚠ 清理后打开大文件可能短暂变慢")
        self.lbl_tr = ttk.Label(sf, text="进程: 0"); self.lbl_tr.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_tr,
            "进程闲置内存清理的总次数\n"
            "\n"
            "每成功清理一个进程计 1 次（含多轮深度清理）。\n"
            "清理前还会降低该进程的内存优先级。\n"
            "\n"
            "⚠ 数字大不一定释放得多——多次清理小进程也会累加\n"
            "⚠ 参考释放量（MB）更有意义")
        self.lbl_fr = ttk.Label(sf, text="释放: 0 MB"); self.lbl_fr.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_fr,
            "累计释放内存总量\n"
            "\n"
            "包括进程闲置内存回收、系统缓存清理等\n"
            "所有操作释放的总和。\n"
            "\n"
            "释放后可用内存会立即上涨，但系统很快会\n"
            "重新分配给活跃程序——这是正常的内存管理行为。\n"
            "参考下方柱状图可看到每轮的实时释放量。")
        self.lbl_lr = ttk.Label(sf, text="已学习: 0"); self.lbl_lr.pack(side="right")
        self._add_tip(self.lbl_lr,
            "已学习的进程数量\n"
            "\n"
            "程序持续观察每个进程的内存使用习惯，\n"
            "包括变化趋势、波动幅度、填充速度等。\n"
            "\n"
            "学习越久，清理决策越精准。\n"
            "超过 7 天无活动的进程会被自动清除。")

        # 日志 — 上半文本 + 下半实时柱图
        lf = ttk.LabelFrame(self.root, text="日志", padding=4)
        lf.pack(fill="both", expand=True, padx=12, pady=(4,12))

        # 下半：柱图 Canvas（守护模式下显示实时优化柱图）
        self.chart_canvas = tk.Canvas(lf, height=200, bg="#1e1e1e", highlightthickness=0)
        self.chart_canvas.pack(side="bottom", fill="x")
        self._chart_redraw_id = None  # debounce ID
        self._drawing_chart = False   # re-entrancy guard
        self.chart_canvas.bind("<Configure>", self._on_chart_configure)
        # 占位
        self._draw_chart_placeholder()

        # 上半：文本日志
        self.log = tk.Text(lf, height=8, font=("Consolas",9), state="disabled", bg="#f5f5f5")
        sc = ttk.Scrollbar(lf, command=self.log.yview); self.log.configure(yscrollcommand=sc.set)
        sc.pack(side="right", fill="y"); self.log.pack(fill="both", expand=True)

        self._upd_learned()

    # ---- 设置对话框 ----

    def _apply_icon(self, win):
        """弹窗窗口图标：延迟到层级完整后设置到顶层 wrapper（winfo_id 是 client 窗口）。
        类图标由主窗口设置一次，所有弹窗自动继承。"""
        try:
            wid = int(win.winfo_id())
            if not hasattr(self, '_dlg_icon_sml'):
                self._dlg_icon_sml = winapi.create_memwise_icon(16)
                self._dlg_icon_big = winapi.create_memwise_icon(32)
            sml_h = self._dlg_icon_sml
            big_h = self._dlg_icon_big
            if not sml_h and not big_h:
                return
            def _set():
                try:
                    top = ctypes.windll.user32.GetAncestor(wid, 2) or ctypes.windll.user32.GetParent(wid) or wid
                    if big_h:
                        ctypes.windll.user32.SendMessageW(top, 0x0080, 1, big_h)
                    if sml_h:
                        ctypes.windll.user32.SendMessageW(top, 0x0080, 0, sml_h)
                except Exception:
                    pass
            win.after(100, _set)
        except Exception:
            pass

    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.withdraw()  # 先隐藏，构建完成居中后一次显示
        self._apply_icon(win)
        win.title("MemWise 设置")
        win.resizable(False, True)
        win.transient(self.root)
        win.focus_set()
        win.lift()
        _center_geometry(win, 520, 600)

        # # ─── 启动设置 ───
        canvas = tk.Canvas(win, width=502, highlightthickness=0)
        scrollbar_v = ttk.Scrollbar(win, orient="vertical", command=canvas.yview)
        inner_frame = ttk.Frame(canvas, width=502)
        canvas.create_window((0, 0), window=inner_frame, anchor="nw", tags="inner")
        canvas.configure(yscrollcommand=scrollbar_v.set)
        canvas.bind("<Configure>", lambda e: canvas.itemconfig("inner", width=e.width))
        inner_frame.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        def _mw(event): canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _mw))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar_v.pack(side="right", fill="y")
        sf = ttk.LabelFrame(inner_frame, text="启动", padding=8)
        sf.pack(fill="x", padx=12, pady=(10,4))

        ast_var = tk.BooleanVar(value=CFG.get("auto_start", False))
        def on_autostart():
            en = ast_var.get()
            if getattr(sys, "frozen", False):
                target = sys.executable; args = ""; wd = os.path.dirname(sys.executable)
            else:
                pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                target = pythonw if os.path.isfile(pythonw) else sys.executable
                args = os.path.abspath(__file__); wd = base
            if en:
                winapi.set_auto_start("MemWise", target, args + (" --minimized" if asm_var.get() else "") if args else ("--minimized" if asm_var.get() else ""), wd)
                # 互斥：启用普通自启时移除管理员自启任务（避免开机双启动）
                winapi.remove_auto_start_admin("MemWise")
                CFG["auto_start_admin"] = False
                asa_var.set(False)
                self._log("开机自启已启用")
            else:
                winapi.remove_auto_start("MemWise")
                self._log("开机自启已关闭")
            CFG["auto_start"] = en
            _save_cfg()
        ttk.Checkbutton(sf, text="开机自启", variable=ast_var,
                        command=on_autostart).pack(anchor="w")
        self._add_tip(sf.winfo_children()[-1],
            "开机时自动启动本程序\n"
            "\n"
            "方式：启动文件夹快捷方式\n"
            "  · 不修改注册表，安全无残留\n"
            "  · 普通用户权限启动\n"
            "  · 如需管理员权限请勾下面的「管理员权限启动」\n"
            "\n"
            "⚠ 取消勾选后会自动删除快捷方式")

        asa_var = tk.BooleanVar(value=CFG.get("auto_start_admin", False))
        def on_autostart_admin():
            en = asa_var.get()
            if getattr(sys, "frozen", False):
                target = sys.executable; args = ""; wd = os.path.dirname(sys.executable)
            else:
                pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                target = pythonw if os.path.isfile(pythonw) else sys.executable
                args = os.path.abspath(__file__); wd = base
            if en:
                ok = winapi.set_auto_start_admin("MemWise", target, args + (" --minimized" if asm_var.get() else "") if args else ("--minimized" if asm_var.get() else ""))
                if ok:
                    winapi.remove_auto_start("MemWise")
                    # 语义：管理员自启替换普通自启，普通自启配置如实置关
                    ast_var.set(False)
                    CFG["auto_start"] = False
                    self._log("管理员权限开机自启已启用")
                else:
                    asa_var.set(False)
                    self._log("管理员权限自启设置失败（请以管理员身份运行一次本程序）")
            else:
                winapi.remove_auto_start_admin("MemWise")
                CFG["auto_start"] = ast_var.get()
                self._log("管理员权限开机自启已关闭")
            CFG["auto_start_admin"] = en if not en or ok else False
            _save_cfg()
        ttk.Checkbutton(sf, text="管理员权限启动", variable=asa_var,
                        command=on_autostart_admin).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1],
            "以最高权限自动开机启动\n"
            "\n"
            "通过 Windows 计划任务实现。\n"
            "系统缓存类清理需要管理员权限，以最高权限启动后\n"
            "所有清理操作都能完整执行。\n"
            "\n"
            "需先以管理员身份运行过一次本程序才能启用。\n"
            "\n"
            "⚠ 启用后会替换普通开机自启，两者只能选一个")

        asd_var = tk.BooleanVar(value=CFG.get("auto_start_daemon", False))
        def on_auto_daemon():
            CFG["auto_start_daemon"] = asd_var.get()
            _save_cfg()
        ttk.Checkbutton(sf, text="启动时自动开启守护", variable=asd_var,
                        command=on_auto_daemon).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1],
            "程序启动后立即自动进入守护模式\n"
            "\n"
            "无需手动点击守护按钮，程序一打开就在后台运行。\n"
            "每 60 秒输出一轮结果，持续自动优化。\n"
            "配合启动后最小化到托盘使用效果更佳。")

        asm_var = tk.BooleanVar(value=CFG.get("auto_start_minimize", False))
        def on_minimize():
            CFG["auto_start_minimize"] = asm_var.get()
            _save_cfg()
        ttk.Checkbutton(sf, text="启动后最小化到托盘", variable=asm_var,
                        command=on_minimize).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1], "程序启动后自动最小化到系统托盘\n\n窗口不显示，只在托盘区域显示图标。\n双击托盘图标恢复窗口，右键弹出菜单。\n适合搭配\u300c启动时自动守护\u300d使用，实现开机静默运行。")

        ca_lbl = ttk.Label(sf, text="关闭按钮行为：")
        ca_lbl.pack(anchor="w", pady=(8,0))
        self._add_tip(ca_lbl, "点击窗口关閉按鈕时的行为：\n· 最小化到托盘 — 隐藏到托盘继续守护\n· 直接退出程序 — 完全退出自动保存\n· 每次询问 — 弹窗选择（默认）")
        self._close_var = tk.StringVar(value=CFG.get("close_action","ask"))
        def set_ca(v):
            global CFG
            CFG["close_action"]=v
            _save_cfg()
        tips_ca = {"minimize":"\u70b9\u51fb\u5173\u95ed\u6309\u94ae\u540e\u7a0b\u5e8f\u9690\u85cf\u5230\u7cfb\u7edf\u6258\u76d8\uff0c\n\u5b88\u62a4\u6a21\u5f0f\u7ee7\u7eed\u8fd0\u884c\u3002\u53cc\u51fb\u6258\u76d8\u56fe\u6807\u53ef\u6062\u590d\u7a97\u53e3\u3002",
                   "exit":"\u70b9\u51fb\u5173\u95ed\u6309\u94ae\u540e\u7a0b\u5e8f\u5b8c\u5168\u9000\u51fa\uff0c\u5b88\u62a4\u6a21\u5f0f\u505c\u6b62\u3002\n\u6240\u6709\u72b6\u6001\u81ea\u52a8\u4fdd\u5b58\u3002",
                   "ask":"\u70b9\u51fb\u5173\u95ed\u6309\u94ae\u540e\u5f39\u7a97\u8be2\u95ee\uff0c\n\u53ef\u9009\u62e9\u6700\u5c0f\u5316\u6216\u9000\u51fa\uff08\u9ed8\u8ba4\u884c\u4e3a\uff09\u3002"}
        for v, lbl in [("minimize","\u6700\u5c0f\u5316\u5230\u6258\u76d8"),("exit","\u76f4\u63a5\u9000\u51fa\u7a0b\u5e8f"),("ask","\u6bcf\u6b21\u8be2\u95ee")]:
            rb = ttk.Radiobutton(sf, text=lbl, variable=self._close_var, value=v, command=lambda x=v: set_ca(x))
            rb.pack(anchor="w")
            if v in tips_ca:
                self._add_tip(rb, tips_ca[v])

        # ─── 清理设置 ───
        cf = ttk.LabelFrame(inner_frame, text="清理", padding=8)
        cf.pack(fill="x", padx=12, pady=8)

        def toggle_op(op_name, var):
            if var.get():
                if "clean_operations" not in CFG:
                    CFG["clean_operations"] = []
                if op_name not in CFG["clean_operations"]:
                    CFG["clean_operations"].append(op_name)
            else:
                if CFG.get("clean_operations"):
                    CFG["clean_operations"] = [o for o in CFG["clean_operations"] if o != op_name]
            _save_cfg()

        ops = CFG.get("clean_operations", []) or []
        ws_var = tk.BooleanVar(value="ws" in ops)
        sb_var = tk.BooleanVar(value="standby" in ops)
        mp_var = tk.BooleanVar(value="modified" in ops)
        fc_var = tk.BooleanVar(value="filecache" in ops)
        vl_var = tk.BooleanVar(value="volume" in ops)
        rg_var = tk.BooleanVar(value="registry" in ops)

        ops_frame = ttk.Frame(cf); ops_frame.pack(fill="x")
        cb_ews = ttk.Checkbutton(ops_frame, text="释放进程闲置内存", variable=ws_var,
                                  command=lambda: toggle_op("ws", ws_var))
        cb_ews.pack(anchor="w")
        self._add_tip(cb_ews, "释放各个进程当前未使用的闲置内存。\n"
                      "内存压力较大时也会清理前台进程。\n"
                      "\n"
                      "⚠ 切回被清理的后台程序时可能多几百毫秒加载\n"
                      "⚠ 系统会自动按需调回，不影响程序正常运行")
        cb_sb = ttk.Checkbutton(ops_frame, text="待机缓存清理", variable=sb_var,
                                command=lambda: toggle_op("standby", sb_var))
        cb_sb.pack(anchor="w")
        self._add_tip(cb_sb, "清空系统已缓存但暂未使用的内存页，释放量较大。\n"
                      "\n"
                      "⚠ 需要管理员权限\n"
                      "⚠ 清理后首次打开大文件可能短暂变慢")
        cb_mp = ttk.Checkbutton(ops_frame, text="脏页写回", variable=mp_var,
                                command=lambda: toggle_op("modified", mp_var))
        cb_mp.pack(anchor="w")
        self._add_tip(cb_mp, "将已修改但未保存的缓存页写回磁盘后释放。\n"
                      "写回后页面变为干净页，系统可回收重用。\n"
                      "每次系统级清理均执行，不受压力阈值限制。\n"
                      "\n"
                      "⚠ 少量磁盘写入，对固态硬盘几乎无影响")
        cb_fc = ttk.Checkbutton(ops_frame, text="系统文件缓存", variable=fc_var,
                                command=lambda: toggle_op("filecache", fc_var))
        cb_fc.pack(anchor="w")
        self._add_tip(cb_fc, "清空系统文件读取缓存。\n"
                      "会降低文件操作速度直到缓存重建。\n"
                      "每次系统级清理均执行，确保最大释放效果。\n"
                      "\n"
                      "⚠ 谨慎使用——文件缓存重建期间磁盘性能下降\n"
                      "⚠ 适合内存严重不足(>85%)且刚用完大文件的场景")
        cb_vc = ttk.Checkbutton(ops_frame, text="卷缓存刷新", variable=vl_var,
                                command=lambda: toggle_op("volume", vl_var))
        cb_vc.pack(anchor="w")
        self._add_tip(cb_vc, "刷新各磁盘分区的写入缓存，释放占用的内存。\n"
                      "\n"
                      "写入缓存是系统暂存磁盘写入的区域，\n"
                      "刷新后相应内存可被系统回收重用。\n"
                      "\n"
                      "⚠ 需要管理员权限\n"
                      "⚠ 每次刷新所有分区，短暂耗时但不丢失数据")
        cb_rg = ttk.Checkbutton(ops_frame, text="注册表缓存清理", variable=rg_var,
                                command=lambda: toggle_op("registry", rg_var))
        cb_rg.pack(anchor="w")
        self._add_tip(cb_rg, "清空系统注册表的读写缓存。\n"
                      "\n"
                      "无磁盘读写操作，不影响任何程序运行。\n"
                      "守护模式下始终执行，取消勾选后完全跳过。")
                # ─── 关闭按钮行为 ───
        # ─── 游戏模式 ───
        gmf = ttk.LabelFrame(inner_frame, text="游戏模式", padding=8)
        gmf.pack(fill="x", padx=12, pady=4)
        gmf_btns = ttk.Frame(gmf); gmf_btns.pack(fill="x")
        manage_btn = ttk.Button(gmf_btns, text="管理游戏进程", command=self._manage_game_procs)
        manage_btn.pack(side="left", padx=(0,6))
        self._add_tip(manage_btn,
            "管理需要识别的游戏程序名\n"
            "\n"
            "在一个窗口内完成：\n"
            "  · 查看 — 列出全部自定义条目\n"
            "  · 添加 — 逗号分隔批量输入，如 cities, stellaris\n"
            "  · 删除 — 选中后删除，写错/误加/不想要随时移除\n"
            "\n"
            "不带后缀会自动补全，改动即时保存，守护模式检测到后自动开启游戏保护。\n"
            "内置名单为程序自带，不可修改。\n"
            "\n"
            "⚠ 同名程序的所有实例都会被识别")
        ttk.Label(ops_frame, text="（未勾选 = 不执行对应系统清理）",
                  foreground="#888").pack(anchor="w")

        # ─── 紧急触发阈值 & 托盘行为 & 日志 ───
        ef2 = ttk.LabelFrame(inner_frame, text="触发与日志", padding=8)


        ef2.pack(fill="x", padx=12, pady=4)
        def set_emerg(v):
            global CFG
            CFG["emergency_threshold"] = int(float(v))
            _save_cfg()
        em_val = tk.IntVar(value=CFG.get("emergency_threshold", 80))
        em_lbl = ttk.Label(ef2, text=f"紧急触发阈值: {em_val.get()}%", foreground="#555")
        self._add_tip(em_lbl, "内存使用率达到此百分比时，跳过等待立即执行全量优化。\n范围 50-99%，默认 80%。\n降低可更及时响应，提高可减少清理频率。")
        em_lbl.pack(anchor="w")
        em_sl = ttk.Scale(ef2, from_=50, to=99, variable=em_val, orient="horizontal",
                         command=lambda v: em_lbl.config(text=f"紧急触发阈值: {int(float(v))}%"))
        em_sl.bind("<ButtonRelease-1>", lambda e: set_emerg(em_val.get()))  # 拖动仅更新显示，松开才保存（防高频写盘）
        em_sl.pack(fill="x", pady=(0,6))
        ta_lbl = ttk.Label(ef2, text="托盘左键行为：")
        ta_lbl.pack(anchor="w")
        map_vals = {"显示窗口":"show","一键清理":"clean","无操作":"none"}
        ta_combo = ttk.Combobox(ef2, values=list(map_vals.keys()), state="readonly", width=20)
        ta_combo.bind("<MouseWheel>", lambda e: "break")  # 禁用滚轮：只接受点击选择，防误改
        ta_cur = {v:k for k,v in map_vals.items()}.get(CFG.get("tray_left_action","show"), "显示窗口")
        ta_combo.set(ta_cur)
        ta_combo.pack(fill="x", pady=(0,6))
        self._add_tip(ta_combo, "托盘左键单击行为：\n· 显示窗口 — 恢复主界面（默认）\n· 一键清理 — 立即执行优化\n· 无操作 — 忽略点击")
        def set_tray_act(e):
            global CFG
            CFG["tray_left_action"] = map_vals.get(ta_combo.get(), "show")
            _save_cfg()
        ta_combo.bind("<<ComboboxSelected>>", set_tray_act)
        lg_var = tk.BooleanVar(value=CFG.get("log_to_file", False))
        def set_log():
            global CFG
            CFG["log_to_file"] = lg_var.get()
            _save_cfg()
            # 开关即时生效：开 → 打开统一日志；关 → 关闭并停止写入
            if lg_var.get():
                _log_open()
            else:
                _log_close()
        lg_cb = ttk.Checkbutton(ef2, text="记录运行日志到文件",
                                variable=lg_var, command=set_log)
        lg_cb.pack(anchor="w")
        self._add_tip(lg_cb, "开启后，运行期间的全部信息写入日志文件（memwise.log）：\n"
                      "每轮清理摘要、界面日志消息、启动/退出、异常、调参、游戏模式切换等。\n"
                      "关闭则不记录任何日志。日志自动轮转保留最近两份，无需手动清理。")
        passes_val = tk.IntVar(value=CFG.get("clean_passes", 4))
        def set_passes(v):
            global CFG
            CFG["clean_passes"] = int(float(v))
            _save_cfg()
        ps_lbl = ttk.Label(ef2, text=f"进程清理深度: {passes_val.get()} 轮", foreground="#555")
        ps_lbl.pack(anchor="w", pady=(6,0))
        self._add_tip(ps_lbl, "每个进程反复清理的轮数（2~6，默认 4）。\n越高释放越彻底，但耗时越长。\n低配电脑建议 2~3，高性能可设 5~6。")
        ps_sl = ttk.Scale(ef2, from_=2, to=6, variable=passes_val, orient="horizontal",
                         command=lambda v: ps_lbl.config(text=f"进程清理深度: {int(float(v))} 轮"))
        ps_sl.bind("<ButtonRelease-1>", lambda e: set_passes(passes_val.get()))
        ps_sl.pack(fill="x", pady=(0,6))

        gap_val = tk.IntVar(value=CFG.get("gap_seconds", 12))
        def set_gap(v):
            global CFG
            CFG["gap_seconds"] = int(float(v))
            _save_cfg()
        gp_lbl = ttk.Label(ef2, text=f"守护清理间隔: {gap_val.get()} 秒", foreground="#555")
        gp_lbl.pack(anchor="w", pady=(6,0))
        self._add_tip(gp_lbl, "守护模式每轮周期内的清理频率（8~20 秒，默认 12）。\n"
                         "用于控制周期内清理操作的密集程度。\n"
                         "间隔越短，同周期内清理次数越多，释放效果越彻底，\n"
                         "但对性能的消耗也越高。\n"
                         "低配电脑建议 15~20，高性能可设 8~10。")
        gp_sl = ttk.Scale(ef2, from_=8, to=20, variable=gap_val, orient="horizontal",
                         command=lambda v: gp_lbl.config(text=f"守护清理间隔: {int(float(v))} 秒"))
        gp_sl.bind("<ButtonRelease-1>", lambda e: set_gap(gap_val.get()))
        gp_sl.pack(fill="x", pady=(0,6))

        # ─── 全局热键（独立栏，汇总所有热键） ───
        hkf = ttk.LabelFrame(inner_frame, text="全局热键", padding=8)
        hkf.pack(fill="x", padx=12, pady=4)
        ttk.Label(hkf, text="格式：修饰键+按键，如 ctrl+shift+m / alt+f1 / shift+f5",
                  foreground="#888").pack(anchor="w")
        for hk in HOTKEYS:
            row = ttk.Frame(hkf); row.pack(fill="x", pady=(4,0))
            ttk.Label(row, text=f"{hk['name']}：", width=12).pack(side="left")
            e = ttk.Entry(row, width=22)
            e.insert(0, CFG.get(hk["key"], hk["default"]))
            e.pack(side="left")
            st = ttk.Label(row, text="", foreground="#c00"); st.pack(side="left", padx=(6,0))
            def commit(event=None, hk=hk, e=e, st=st):
                spec = e.get().strip().lower()
                mods, vk, err = _parse_hotkey(spec)
                if err:
                    st.config(text=err)  # 非法：标红提示，不保存（保留旧值）
                    return
                for hk2 in HOTKEYS:  # 冲突检测
                    if hk2 is hk:
                        continue
                    m2, v2, _ = _parse_hotkey(CFG.get(hk2["key"], hk2["default"]))
                    if m2 == mods and v2 == vk:
                        st.config(text=f"与「{hk2['name']}」冲突")
                        return
                CFG[hk["key"]] = spec
                _save_cfg()
                st.config(text="已生效")
                self._apply_hotkeys()
            e.bind("<FocusOut>", commit)
            e.bind("<Return>", commit)
            tip = (f"{hk['name']}全局快捷键\n\n"
                   f"按此组合：{'立即执行一次优化' if hk['action'] == 'hotkey' else '切换游戏模式（含确认弹窗）'}\n"
                   f"格式：修饰键+按键，如 {hk['default']}\n\n"
                   "⚠ 至少包含一个修饰键（ctrl/alt/shift）\n"
                   "⚠ 不能与其他热键相同\n"
                   "⚠ 输入后点击其他位置或按回车生效，被占用时会提示")
            self._add_tip(e, tip)

        # 关闭按钮行为：设置即时保存，无需独立保存按钮（save_and_close 已移除）
        win.deiconify()  # 全部控件就绪，居中后一次显示

    def _edit_exclusion_list(self):
        win = tk.Toplevel(self.root)
        win.withdraw()  # 先隐藏，构建完成居中后一次显示
        self._apply_icon(win)
        win.title("进程排除列表")
        win.resizable(False, True)
        win.transient(self.root)
        win.focus_set()
        win.lift()
        _center_geometry(win, 460, 460)

        lb = tk.Listbox(win, width=40, height=12)
        lb.pack(fill="both", expand=True, padx=12, pady=(12,4))
        never = CFG.get("never", []) or []
        for n in never: lb.insert("end", n)

        def add_excl():
            name = simpledialog.askstring("添加排除", "输入程序名（不带后缀自动补全）:", parent=win)
            if name:
                nm = _normalize_proc_name(name)
                if nm in never:
                    messagebox.showwarning("已存在", f"「{nm}」已在排除列表中", parent=win)
                    return
                lb.insert("end", nm)
                never.append(nm)
                CFG["never"] = list(never)
                _save_cfg()
        def remove_excl():
            sel = lb.curselection()
            if sel:
                name = lb.get(sel[0])
                lb.delete(sel[0])
                if name in never:
                    never.remove(name)
                    CFG["never"] = list(never)
                    _save_cfg()

        bf = ttk.Frame(win); bf.pack(fill="x", padx=12, pady=4)
        ttk.Button(bf, text="+ 添加", command=add_excl).pack(side="left", padx=(0,6))
        ttk.Button(bf, text="− 删除", command=remove_excl).pack(side="left")

        def close_excl():
            CFG["never"] = list(never)
            _save_cfg()
            win.destroy()
        ttk.Button(win, text="关闭", command=close_excl).pack(pady=8)
        win.deiconify()  # 全部控件就绪，居中后一次显示

    def _show_learn_log(self):
        info_data = []
        for name, p in sorted(self.learner.profiles.items()):
            if p.total_samples < 2:
                continue
            info_data.append((name, p.alpha, p.beta, p.total_samples,
                              f"{p.thompson_theta:.2f}", f"{p.roi:.1f}",
                              f"{p.z_score:.1f}", f"{p.slope:.0f}",
                              "是" if p.leak_suspect else "否",
                              p.clean_count, p.probe_ok, p.probe_fail))
        if not info_data:
            messagebox.showinfo("学习日志", "还没有学习到任何数据，先运行一会儿优化再来看", parent=self.root)
            return
        win = tk.Toplevel(self.root)
        win.withdraw()  # 先隐藏，构建完成居中后一次显示
        self._apply_icon(win)
        win.title(f"学习日志 — {len(info_data)} 个进程")
        win.transient(self.root)
        win.focus_set()
        win.lift()
        _center_geometry(win, 1000, 650)
        cols = ("进程", "α", "β", "样本", "可信度", "收益比(MB/PF)", "偏差", "趋势", "泄漏", "清理", "试探成功", "试探失败")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=20)
        for c in cols:
            tree.heading(c, text=c)
            if c in ("进程",):
                tree.column(c, width=200)
            elif c in ("α","β","样本","清理","试探成功","试探失败"):
                tree.column(c, width=65, anchor="center")
            elif c in ("可信度","收益比(MB/PF)","偏差","趋势"):
                tree.column(c, width=75, anchor="center")
            else:
                tree.column(c, width=70, anchor="center")
        vsb = ttk.Scrollbar(win, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(12,0), pady=(12,4))
        vsb.pack(side="right", fill="y", pady=(12,4))
        for row in info_data:
            tree.insert("", "end", values=row)
        win.deiconify()  # 全部控件就绪，居中后一次显示


    # ---- 进程内存排行 ----

    def _manage_game_procs(self):
        """一体化游戏进程管理：列出/添加/删除自定义条目，内置名单只读展示"""
        win = tk.Toplevel(self.root)
        win.withdraw()  # 先隐藏，构建完成居中后一次显示
        self._apply_icon(win)
        win.title("游戏进程管理")
        win.resizable(True, True)
        win.transient(self.root)
        win.focus_set()
        win.lift()
        _center_geometry(win, 460, 480)

        import core.cleaner as _cm
        builtin = sorted(_cm.GAME_PROCESSES)
        games = [g for g in (CFG.get("game_processes", []) or [])]

        # ── 自定义条目列表 ──
        ttk.Label(win, text="自定义游戏进程（可添加/删除）：").pack(anchor="w", padx=12, pady=(12,2))
        listf = ttk.Frame(win); listf.pack(fill="both", expand=True, padx=12)
        lb = tk.Listbox(listf, width=46, height=8, font=("Microsoft YaHei", 10),
                        selectbackground="#419EF3", activestyle="none")
        scroll = ttk.Scrollbar(listf, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=scroll.set)
        lb.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for g in games:
            lb.insert("end", g)

        # ── 添加区 ──
        addf = ttk.Frame(win); addf.pack(fill="x", padx=12, pady=6)
        entry = ttk.Entry(addf, width=32)
        entry.pack(side="left")
        ttk.Label(addf, text="逗号分隔，不带后缀自动补全").pack(side="left", padx=(6,0))

        def add():
            raw = [_normalize_proc_name(n) for n in entry.get().split(",") if n.strip()]
            if not raw:
                return
            existing = [n.lower() for n in (CFG.get("game_processes", []) or [])]
            new_names = []
            dup = []
            for n in raw:
                if n in existing:
                    dup.append(n)
                else:
                    new_names.append(n)
            if dup:
                messagebox.showwarning("已存在", f"以下进程已在名单中：\n{', '.join(dup)}", parent=win)
            if not new_names:
                entry.delete(0, "end")
                return
            CFG["game_processes"] = existing + new_names
            _save_cfg()
            # 同步 judger 运行时名单（守护检测即刻生效）
            self.judger.cfg["game_processes"] = list(CFG["game_processes"])
            for n in new_names:
                lb.insert("end", n)
            entry.delete(0, "end")
            info.config(text=f"自定义 {len(lb.get(0, 'end'))} 款 · 内置 {len(builtin)} 款（内置不可修改）")
        ttk.Button(addf, text="添加", command=add).pack(side="left", padx=(6,0))
        entry.bind("<Return>", lambda e: add())
        entry.focus_set()

        # ── 删除区 ──
        delf = ttk.Frame(win); delf.pack(fill="x", padx=12, pady=(0,4))
        def remove():
            sel = lb.curselection()
            if not sel:
                return
            name = lb.get(sel[0])
            if not messagebox.askyesno("删除游戏进程",
                    f"确定从自定义名单中移除「{name}」吗？\n\n内置名单不受影响。", parent=win):
                return
            lb.delete(sel[0])
            cur = CFG.get("game_processes", []) or []
            CFG["game_processes"] = [g for g in cur if g.lower() != name.lower()]
            _save_cfg()
            # 同步 judger 运行时名单
            self.judger.cfg["game_processes"] = list(CFG["game_processes"])
            info.config(text=f"自定义 {len(lb.get(0, 'end'))} 款 · 内置 {len(builtin)} 款（内置不可修改）")
        ttk.Button(delf, text="删除选中", command=remove).pack(side="left")

        # ── 内置名单只读展示 ──
        info = ttk.Label(win, text=f"自定义 {len(games)} 款 · 内置 {len(builtin)} 款（内置不可修改）",
                         foreground="#888")
        info.pack(anchor="w", padx=12, pady=(4,2))
        bf2 = ttk.Frame(win); bf2.pack(fill="x", padx=12, pady=(0,12))
        lbl_builtin = tk.Text(bf2, height=4, width=56, font=("Microsoft YaHei", 9),
                              state="disabled", wrap="word", bg="#f5f5f5")
        lbl_builtin.pack(fill="both")
        lbl_builtin.configure(state="normal")
        lbl_builtin.insert("end", "  " + ", ".join(builtin[:25]))
        if len(builtin) > 25:
            lbl_builtin.insert("end", f"  ... 及其他 {len(builtin) - 25} 款")
        lbl_builtin.configure(state="disabled")
        win.deiconify()  # 全部控件就绪，居中后一次显示

    def _show_process_rank(self):
        """弹出进程内存占用排行榜"""
        win = tk.Toplevel(self.root)
        win.withdraw()  # 先隐藏，构建完成居中后一次显示
        self._apply_icon(win)
        win.title("进程内存排行")
        win.resizable(True, True)
        win.transient(self.root)
        win.focus_set()
        win.lift()
        _center_geometry(win, 900, 650)

        cols = ("进程", "进程号", "内存占用", "CPU占用", "学习")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=25)
        for c in cols:
            tree.heading(c, text=c, command=lambda _c=c: _sort_tree(_c))
            if c in ("进程",):
                tree.column(c, width=250)
            elif c == "进程号":
                tree.column(c, width=70, anchor="center")
            elif c == "CPU占用":
                tree.column(c, width=70, anchor="center")
            elif c == "学习":
                tree.column(c, width=60, anchor="center")
            else:
                tree.column(c, width=120, anchor="e")

        vsb = ttk.Scrollbar(win, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(12,0), pady=(12,4))
        vsb.pack(side="right", fill="y", pady=(12,4))

        # 排序状态变量（默认按内存降序）
        _sort_col = "内存占用"
        _sort_rev = True

        def _sort_key_c(v):
            """排序键提取：支持 "X MB"/"X%" 格式转数字"""
            v = v.strip()
            if v.endswith(" MB"):
                v = v[:-3]
            elif v.endswith("%"):
                v = v[:-1]
            try:
                return float(v)
            except ValueError:
                return v.lower()

        def _sort_tree(col):
            nonlocal _sort_col, _sort_rev
            if _sort_col == col:
                _sort_rev = not _sort_rev
            else:
                _sort_col = col
                _sort_rev = True
            items = [(tree.set(k, col), k) for k in tree.get_children("")]
            items.sort(key=lambda x: _sort_key_c(x[0]), reverse=_sort_rev)
            for idx, (_, k) in enumerate(items):
                tree.move(k, "", idx)

        def _on_item_click(event):
            """点击进程行 → 弹窗确认后终止进程"""
            sel = tree.selection()
            if not sel:
                return
            item = sel[0]
            vals = tree.item(item, "values")
            if not vals or len(vals) < 2:
                return
            name = vals[0]
            pid_str = vals[1]
            try:
                pid = int(pid_str)
            except (ValueError, TypeError):
                return
            import os
            # 保护系统进程和自身
            if pid <= 4 or pid == os.getpid():
                messagebox.showwarning("禁止终止", "不能终止系统进程或自身", parent=win)
                return
            ok = messagebox.askyesno("终止进程",
                f"确定要终止「{name}」(PID={pid}) 吗？\n\n该操作会强制结束进程，未保存的数据可能丢失。",
                icon="warning", parent=win)
            if ok:
                if winapi.terminate_process(pid):
                    messagebox.showinfo("已完成", f"进程「{name}」已终止", parent=win)
                    _refresh()
                else:
                    messagebox.showerror("失败", f"无法终止进程「{name}」\n可能权限不足或进程已退出", parent=win)

        tree.bind("<Double-1>", _on_item_click)  # 单击仅选中，双击才询问终止（防误触）

        # 鼠标悬浮高亮
        tree.tag_configure("hover", background="#3a3a3a")
        _cur_hover = None

        def _on_motion(event):
            nonlocal _cur_hover
            item = tree.identify_row(event.y)
            if item != _cur_hover:
                if _cur_hover:
                    tree.item(_cur_hover, tags=())
                if item:
                    tree.item(item, tags=("hover",))
                _cur_hover = item

        def _on_leave(event):
            nonlocal _cur_hover
            if _cur_hover:
                tree.item(_cur_hover, tags=())
                _cur_hover = None

        tree.bind("<Motion>", _on_motion)
        tree.bind("<Leave>", _on_leave)

        def _restore_hover():
            """刷新后恢复鼠标悬浮高亮"""
            nonlocal _cur_hover
            try:
                y = win.winfo_pointery() - tree.winfo_rooty()
                item = tree.identify_row(y)
                if item:
                    tree.item(item, tags=("hover",))
                    _cur_hover = item
            except Exception:
                pass

        def _refresh():
            if not win.winfo_exists():
                return
            for item in tree.get_children():
                tree.delete(item)
            try:
                snaps = self.sniffer.snapshot()
            except Exception as e:
                import sys; print(f"[MemWise] _refresh sniffer error: {e}", file=_ERR)
                win.after(3000, _refresh)
                return
            try:
                for s in snaps:
                    ws_mb = s.priv / (1 << 20)
                    p = self.learner.get_profile(s.name)
                    learned = "✓" if p and p.total_samples >= 3 else ""
                    tree.insert("", "end", values=(
                        s.name, s.pid, f"{ws_mb:.0f} MB",
                        f"{s.cpu:.1f}%", learned))
                # 应用用户选择的排序
                if _sort_col:
                    items = [(tree.set(k, _sort_col), k) for k in tree.get_children("")]
                    items.sort(key=lambda x: _sort_key_c(x[0]), reverse=_sort_rev)
                    for idx, (_, k) in enumerate(items):
                        tree.move(k, "", idx)
            except Exception as e:
                import sys; print(f"[MemWise] _refresh data error: {e}", file=_ERR)
            win.after(3000, _refresh)
            win.after(10, _restore_hover)

        _refresh()
        win.deiconify()  # 全部控件就绪，居中后一次显示


    # ---- 日志 / 状态 ----

    def _log_op(self, m):
        self.log.configure(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {m}\n"); self.log.see("end")
        self.log.configure(state="disabled")
        if CFG.get("log_to_file"):
            _log_write("界面", m)

    def _log_batch(self, msgs, to_file=True):
        """周期末批量输出：当前行数+批量>7则清旧，再逐条输出。
        to_file=False 为纯显示模式（周期摘要/EFIS 消息已有 [清理]/[调参] 直写，避免双通道重复落盘）"""
        self.log.configure(state="normal")
        try:
            cur_lines = int(self.log.index('end-1c').split('.')[0])
        except Exception:
            cur_lines = 0
        if cur_lines + len(msgs) > 7:
            self.log.delete("1.0", "end")
        for m in msgs:
            self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {m}\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        if to_file and CFG.get("log_to_file"):
            for m in msgs:
                _log_write("界面", m)

    def _log(self, m):
        """实时日志：>7行则清旧再输出"""
        self.log.configure(state="normal")
        try:
            cur_lines = int(self.log.index('end-1c').split('.')[0])
        except Exception:
            cur_lines = 0
        if cur_lines > 7:
            self.log.delete("1.0", "end")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {m}\n"); self.log.see("end")
        self.log.configure(state="disabled")
        if CFG.get("log_to_file"):
            _log_write("界面", m)

    def _poll_msg_queue(self):
        # ── 托盘事件 — 从 wndproc 标志安全分发（零 Tkinter 调用于 wndproc）──
        global _tray_action
        try:
            action = _tray_action
            if action is not None:
                _tray_action = None
                if action == 'left':
                    self._on_tray_left_click()
                elif action == 'right':
                    self._show_tray_menu()
                elif action == 'hotkey':
                    self._on_hotkey()
                elif action == 'game':
                    self._on_toggle_game()
        except Exception:
            pass
        # ── 消息队列 ──
        try:
            while True:
                action, args = self._msg_queue.get_nowait()
                if action == 'log': self._log(args)
                elif action == 'log_batch': self._log_batch(args)
                elif action == 'display': self._log_batch(args, to_file=False)  # 仅显示：内容已有 [清理]/[调参] 直写落盘
                elif action == 'log_op': self._log_op(args)
                elif action == 'chart':
                    self._drawing_chart = False  # 异常恢复：防止标志永锁
                    if self._chart_redraw_id is not None:
                        self.root.after_cancel(self._chart_redraw_id)
                        self._chart_redraw_id = None
                    self._draw_chart()
                elif action == 'upd_ui': self._upd_dae_ui(*args)
                elif action == 'opt_done': self._opt_done(args)
                elif action == 'dae_stopped': self._dae_stopped()
        except queue.Empty:
            pass
        except Exception:
            import traceback; traceback.print_exc(file=_ERR)
        finally:
            self.root.after(100, self._poll_msg_queue)

    def _upd_learned(self):
        self.lbl_lr.config(text=f"已学习: {len(self.learner.profiles)}")

    def _refresh_mem(self):
        try:
            m = winapi.get_memory_status()
            if m:
                pct = m["pct"]
                self._mem_pct = pct
                # 托盘图标每5s更新一次（GDI渲染管线功耗大，降低频率省电~8%）
                now_ts = time.time()
                if now_ts - getattr(self, '_last_tray_update', 0) >= 5:
                    self._update_tray_status(pct)
                    self._last_tray_update = now_ts
                # Canvas/Label 操作仅在窗口可见时执行
                try:
                    if self.root.winfo_viewable():
                        cw = self.mem_canvas.winfo_width() or 400
                        bar_w = max(1, int(cw * pct / 100))
                        color = "#4caf50" if pct < 60 else ("#ffc107" if pct < 75 else ("#ff9800" if pct < 90 else "#f44336"))
                        self.mem_canvas.coords(self.mem_bar_rect, 0, 0, bar_w, 22)
                        self.mem_canvas.itemconfig(self.mem_bar_rect, fill=color)
                        self.mem_canvas.itemconfig(self.mem_bar_text, text=f"{pct}%")
                        self.lbl_total["text"] = f"总: {m['total']/(1<<30):.1f}G"
                        self.lbl_used["text"] = f"已用: {m['used']/(1<<30):.1f}G"
                        self.lbl_avail["text"] = f"可用: {m['avail']/(1<<30):.1f}G"
                        self.lbl_pct["text"] = f"{pct}%"
                except Exception as e:
                    import sys; print(f"[MemWise] _refresh_mem UI异常: {e}", file=_ERR)
        finally:
            self.root.after(2000, self._refresh_mem)

    def _upd_stats(self):
        s = self.cleaner.summary()
        self.lbl_sb["text"] = f"系统杂项: {self._fmt_count(s['standby'] + s.get('modified',0) + s.get('filecache',0) + s.get('registry',0) + s.get('volume',0))}"
        self.lbl_tr["text"] = f"进程: {self._fmt_count(s['ws_trim'])}"
        fm = s['freed_mb']
        self.lbl_fr["text"] = f"释放: {fm/1024.0:.1f}GB" if fm >= 1000 else f"释放: {fm:.1f}MB"
        self._upd_learned()

    # ---- 柱图 ----

    def _draw_chart_placeholder(self):
        """显示占位文本（无数据时）"""
        c = self.chart_canvas
        c.delete("all")
        cw = c.winfo_width() or 400
        c.create_text(cw//2, 70, text="启动守护模式后显示实时优化图表",
                      fill="#888", font=("微软雅黑", 10))



    BAR_W = 14   # 每柱宽度 px
    BAR_GAP = 3  # 柱间距 px

    def _compute_eris(self, data, trimmed_cnt, failed_cnt, mem_pct, failed_weight=0.5, probe_ok=0, probe_total=0, update_state=True):
        """ERIS v6: IQR分位数归一化五维加权和（80±40×(raw−p50)/IQR，trimmed IQR + 维级窗口）。
        维级窗口 [25,25,20,8,20]，均值~80%，可破100%，可破60%。
        返回 {"total": eff, "factors": ["↑预测精准","↓PF偏高"]}"""
        if not data:
            return {"total": 0, "factors": ["冷启动"]}
        visible = list(data)
        learner = self.learner
        profiles = learner.profiles
        cycle_freed = visible[-1] if visible else 1
        
        # ── 分位数窗初始化 / 趋势列表初始化 ──
        # 窗口长度按维度特异性分配：raw2(释放)需要长窗应对幂律，raw4(EFIS)短窗够用
        _WINDOWS = [25, 25, 20, 8, 20]
        if not hasattr(self, '_eris_bufs'):
            from collections import deque
            self._eris_bufs = [deque(maxlen=_WINDOWS[j]) for j in range(5)]
            self._eris_p50_ewma = [0.0] * 5  # p50 平滑（λ=0.15）
        if not hasattr(self, '_eris_iqr_ewma'):
            self._eris_iqr_ewma = [0.0] * 5
        if not hasattr(self, '_eris_ewma_trend'):
            self._eris_ewma_trend = []
        
        # ── 维度1 raw: Kalman 预测精准度 ──
        # 迭代前快照：daemon 线程可能随时 get() 增键，直接迭代会 RuntimeError（dictionary changed size）
        profiles_snapshot = list(profiles.values())
        kalman_errors = []
        for p in profiles_snapshot:
            if p.clean_count < 1 and p.total_samples < 1:
                continue
            if p.gain_ewma <= 0:
                continue
            k_freed, _ = p.kalman.predict()
            if k_freed > 0:
                kalman_errors.append(abs(k_freed - p.gain_ewma) / p.gain_ewma)
        if kalman_errors:
            raw1 = 1.0 - sorted(kalman_errors)[len(kalman_errors)//2]
        else:
            raw1 = 0.50
        
        # ── 维度2 raw: 单进程释放效率 (MB/trim) — log10 压缩幂律分布 ──
        trimmed_n = max(trimmed_cnt, 1)
        raw2 = math.log10(max(1.0, cycle_freed / trimmed_n))
        
        # ── 维度3 raw: 副作用控制 (trim+1)/(fail+1) ──
        raw3 = (trimmed_cnt + 1.0) / max(failed_cnt + 1.0, 1.0)
        
        # ── 维度4 raw: EFIS 参数稳定度 ──
        efis = getattr(self, 'efis', None)
        if efis:
            cycle = getattr(efis, '_cycle', 0)
            adjust_log = getattr(efis, '_adjust_log', [])
            recent_adjusts = sum(1 for a in adjust_log[-15:] if a.get("cycle", 0) > cycle - 15)
            raw4 = max(0.0, 1.0 - recent_adjusts / 5.0)
        else:
            raw4 = 0.50
        
        # ── 维度5 raw: 探索完备度 ──
        never_tried = sum(1 for p in profiles_snapshot if p.clean_count == 0 and p.last_feedback_time == 0)
        raw5 = 1.0 - never_tried / max(len(profiles_snapshot), 1)
        
        raws = [raw1, raw2, raw3, raw4, raw5]
        
        # ── 游戏模式切换检测：重置受影响维度的分位数窗（防虚高/低谷）──
        # ── IQR 归一化 v6: trimmed IQR + 内插分位 + p50平滑 + 幂律压缩 + 维级窗口 ──
        with self._eris_lock:
            if update_state:
                cur_gm = getattr(getattr(self, 'cleaner', None), 'game_mode', False)
                last_gm = getattr(self, '_last_eris_game_mode', None)
                if last_gm is not None and cur_gm != last_gm:
                    from collections import deque
                    self._eris_bufs[1] = deque(maxlen=_WINDOWS[1])
                    self._eris_bufs[2] = deque(maxlen=_WINDOWS[2])
                    # 用当前 raw 预填充 p50，避免切换后首轮从中性 80 起步
                    self._eris_p50_ewma[1] = raws[1]
                    self._eris_p50_ewma[2] = raws[2]
                self._last_eris_game_mode = cur_gm
            
            dims = []
            for j in range(5):
                # 纯函数核心（core.eris.iqr_dim，与回归测试共用同一实现）
                dim, _p50, _iqr = iqr_dim(
                    raws[j], self._eris_bufs[j],
                    self._eris_p50_ewma[j], self._eris_iqr_ewma[j],
                    update_state=update_state)
                self._eris_p50_ewma[j] = _p50
                self._eris_iqr_ewma[j] = _iqr
                dims.append(dim)
        
        weights = [0.25, 0.25, 0.20, 0.15, 0.15]
        eff = sum(d * w for d, w in zip(dims, weights))
        eff = max(0.0, eff)
        
        dim_pairs = [("↑预测精准","↓预测偏差"), ("↑释放改善","↓释放退步"),
                     ("↑副作用低","↓副作用高"), ("↑参数稳定","↓频繁调参"),
                     ("↑覆盖广泛","↓覆盖狭窄")]
        
        # ── 因子选择（含防振荡：同维正负不来回跳）──
        prev = getattr(self, '_eris_prev', None)
        prev_f_dim = getattr(self, '_eris_prev_factor_dim', -1)
        prev_f_pos = getattr(self, '_eris_prev_factor_pos', None)
        if len(visible) <= 3:
            factors = ["影响因素分析中…"]
        elif round(eff) >= 100:
            best_i = max(range(5), key=lambda i: abs(dims[i] - 80.0))
            factors = [dim_pairs[best_i][0]]
            # 防振荡：同维+上一轮方向不是True（即上次是负面或未记录）→ 跳到候选2
            if prev_f_dim == best_i and prev_f_pos is not None and prev_f_pos is not True:
                ranked = sorted(range(5), key=lambda i: abs(dims[i] - 80.0), reverse=True)
                best_i = ranked[1] if len(ranked) > 1 else best_i
                factors = [dim_pairs[best_i][0]]
            factors.append("🚀效率超常")
            if update_state:
                # 99 标记极性轮，打断趋势连续性
                self._eris_ewma_trend.append(99)
                self._eris_prev_factor_dim = best_i
                self._eris_prev_factor_pos = True
        elif round(eff) <= 60:
            best_i = max(range(5), key=lambda i: abs(dims[i] - 80.0))
            factors = [dim_pairs[best_i][1]]
            # 防振荡：同维+上一轮方向不是False（即上次是正面或未记录）→ 跳到候选2
            if prev_f_dim == best_i and prev_f_pos is not None and prev_f_pos is not False:
                ranked = sorted(range(5), key=lambda i: abs(dims[i] - 80.0), reverse=True)
                best_i = ranked[1] if len(ranked) > 1 else best_i
                factors = [dim_pairs[best_i][1]]
            factors.append("⚠效率异常")
            if update_state:
                # -99 标记极性轮，打断趋势连续性
                self._eris_ewma_trend.append(-99)
                self._eris_prev_factor_dim = best_i
                self._eris_prev_factor_pos = False
        elif prev and isinstance(prev, dict) and "eff" in prev and abs(eff - prev["eff"]) >= 2.0:
            is_pos = eff > prev["eff"]
            best_i = max(range(5), key=lambda i: abs(dims[i] - 80.0))
            factors = [dim_pairs[best_i][0]] if is_pos else [dim_pairs[best_i][1]]
            # 防振荡：同维+方向与上次反转 → 跳到候选2
            if prev_f_dim == best_i and prev_f_pos is not None and prev_f_pos != (factors[0].startswith("↑")):
                ranked = sorted(range(5), key=lambda i: abs(dims[i] - 80.0), reverse=True)
                best_i = ranked[1] if len(ranked) > 1 else ranked[0]
                factors = [dim_pairs[best_i][0]] if factors[0].startswith("↑") else [dim_pairs[best_i][1]]
            if update_state:
                is_pos = factors[0].startswith("↑")
                self._eris_ewma_trend.append(1 if is_pos else -1)
                self._eris_prev_factor_dim = best_i
                self._eris_prev_factor_pos = is_pos
            if len(self._eris_ewma_trend) >= 3 and len(set(self._eris_ewma_trend[-3:])) == 1:
                last_val = self._eris_ewma_trend[-1]
                if last_val == 1:
                    factors.append("🔥持续改善")
                elif last_val == -1:
                    factors.append("⚠持续下滑")
        else:
            factors = ["相对平稳"]
            if update_state:
                self._eris_ewma_trend.append(0)
                # 平稳期重置防振荡状态：旧方向不应影响后续活跃期的判断
                self._eris_prev_factor_dim = -1
                self._eris_prev_factor_pos = None
        if update_state and len(self._eris_ewma_trend) > 10:
            self._eris_ewma_trend = self._eris_ewma_trend[-10:]
        
        if update_state:
            self._eris_prev = {"eff": eff, "dims": dims}
        return {"total": eff, "factors": factors}

    def _on_chart_configure(self, event):
        """防抖：合并短时间内的多次 Configure 事件，延迟 120ms 统一重绘"""
        if self._chart_redraw_id is not None:
            self.root.after_cancel(self._chart_redraw_id)
        # 强制复位：如果上次绘制异常退出导致 _drawing_chart 未复位，此处恢复
        self._drawing_chart = False
        self._chart_redraw_id = self.root.after(50, self._draw_chart)

    def _draw_chart(self):
        """在 Canvas 上绘制固定宽度滚动柱图 + 统计指标"""
        self._chart_redraw_id = None
        if self._drawing_chart:
            return  # 嵌套事件循环触发二次进入，跳过避免 delete("all") 踩踏
        c = self.chart_canvas
        self._drawing_chart = True
        try:
            self._do_draw_chart()
        except Exception as e:
            import sys, traceback
            print(f"[MemWise] 图表渲染异常: {e}", file=_ERR)
            # 同时输出到日志面板，便于 EXE 环境下诊断
            try:
                self._log(f"⚠ 图表异常: {e}")
            except Exception:
                pass
        finally:
            self._drawing_chart = False

    def _do_draw_chart(self):
        c = self.chart_canvas
        c.delete("all")
        with self._chart_lock:
            data = list(self._chart_data)
            total_points = len(data)
            meta_list = list(self._chart_cycle_meta)
        if not data:
            self._draw_chart_placeholder()
            return
        cw = c.winfo_width(); ch = 200
        pad_left = 50; pad_right = 10; pad_top = 20; pad_bottom = 46
        px0 = pad_left; px1 = cw - pad_right
        py0 = pad_top; py1 = ch - pad_bottom
        pw = px1 - px0; ph = py1 - py0
        step = self.BAR_W + self.BAR_GAP
        max_fit = pw // step
        visible = data[-max_fit:] if len(data) > max_fit else data
        latest = visible[-1] if visible else 0
        max_val = max(visible) if visible else 1
        if max_val <= 0:
            max_val = 1  # 全零释放轮：按 0 高占位柱渲染，避免除零
        avg_val = sum(visible) / len(visible) if visible else 0
        peak_val = max_val
        failed_weight = getattr(self, "_failed_weight", 0.5)
        
        # ── ERIS 单线入口：处理未进入分位数窗的新图表点，更新状态 + 填充 _eff_data/_eff_factors ──
        # data/total_points/meta_list 已在上面同一把锁内获取，不再重复加锁
        # 用序列号定位新点：找到 meta 中 seq > _chart_eris_last_seq 的项，从那里开始处理
        last_seq = self._chart_eris_last_seq
        # 每点是否收割未完成（供悬浮提示如实标注；partial 周期同样真实进 ERIS）
        partial_all = [meta_list[i][5] if len(meta_list[i]) > 5 else False for i in range(total_points)]
        for idx in range(total_points):
            seq, t, f, mp, fw, partial = meta_list[idx]
            if seq <= last_seq:
                continue
            try:
                chunk = data[:idx+1]
                result = self._compute_eris(chunk, t, f, mp, fw, update_state=True)
                self._eff_data.append(result["total"])
                if not hasattr(self, '_eff_factors'):
                    self._eff_factors = deque(maxlen=60)
                self._eff_factors.append(result.get("factors", ["冷启动"]))
                last_seq = seq
            except Exception:
                self._eff_data.append(80.0)
                if not hasattr(self, '_eff_factors'):
                    self._eff_factors = deque(maxlen=60)
                self._eff_factors.append(["计算异常"])
                last_seq = seq
        self._chart_eris_last_seq = last_seq

        # 当前显示使用最新 eff/factors（供悬浮提示与底部指标）
        eff_list = list(self._eff_data)
        eff = eff_list[-1] if eff_list else 50
        # Y 轴标注 & 网格
        for i, lbl_v in [(0, 0), (1, max_val//2), (2, max_val)]:
            if i == 0:
                lbl = "0"
            elif lbl_v >= 1000:
                lbl = f"{lbl_v/1024.0:.1f}GB"
            else:
                lbl = f"{lbl_v:.0f}MB"
            y = py1 - int(i * ph / 2)
            c.create_line(px0 - 3, y, px0, y, fill="#555")
            c.create_text(px0 - 6, y, text=lbl, anchor="e",
                          fill="#aaa", font=("Consolas", 8))
            if i > 0:
                c.create_line(px0, y, px1, y, fill="#2a2a2a", dash=(2, 4))
        # 柱条（保护标题区：柱条顶部不低于 y=20）
        for i, v in enumerate(visible):
            bh = max(1, int(v / max_val * ph))
            x0 = px0 + i * step; x1 = x0 + self.BAR_W
            y0 = min(py1, max(py0 + 8, py1 - bh))  # 顶部留 8px 黑边保护标题
            if v > 0:
                ratio = v / max_val
                color = "#4caf50" if ratio < 0.3 else ("#ff9800" if ratio < 0.7 else "#f44336")
                c.create_rectangle(x0, y0, x1, py1, fill=color, outline="", width=0)
            else:
                c.create_rectangle(x0, py1 - 1, x1, py1, fill="#555", outline="", width=0)

        # ── 效率折线（钢蓝色，叠加在柱状图上方）──
        eff_data = list(self._eff_data)
        eff_pts = []
        if eff_data:
            eff_visible = eff_data[-len(visible):] if len(eff_data) > len(visible) else eff_data
            step2 = self.BAR_W + self.BAR_GAP
            # 补齐较短的情况
            n_pts = min(len(eff_visible), len(visible))
            eff_pts = eff_visible[-n_pts:]
            # 全局索引：前3个数据点永久虚线
            eff_start_idx = len(eff_data) - n_pts
            # 折线：全局前3个数据点(索引0,1,2)间线段虚线，其余实线
            if n_pts >= 2:
                # early_end_local = 全局索引2在可见窗口中的局部位置
                early_end_local = 2 - eff_start_idx
                if early_end_local >= 1:
                    # 虚线: 从点0到点early_end_local（最多到点2）
                    dash_end = min(early_end_local, n_pts - 1)
                    dash_coords = []
                    for i in range(dash_end + 1):
                        cx = px0 + i * step2 + self.BAR_W // 2
                        cy = py1 - (min(eff_pts[i], 100.0) / 100.0) * ph
                        dash_coords.extend([cx, cy])
                    if len(dash_coords) >= 4:
                        c.create_line(*dash_coords, fill="#4488CC", width=2,
                                      smooth=False, dash=(4, 3), tags="eff_line")
                    # 实线: 从dash_end开始，与虚线终点重叠保证连续
                    solid_start = dash_end
                    if n_pts > solid_start + 1:
                        solid_coords = []
                        for i in range(solid_start, n_pts):
                            cx = px0 + i * step2 + self.BAR_W // 2
                            cy = py1 - (min(eff_pts[i], 100.0) / 100.0) * ph
                            solid_coords.extend([cx, cy])
                        if len(solid_coords) >= 4:
                            c.create_line(*solid_coords, fill="#4488CC", width=2,
                                          smooth=False, tags="eff_line")
                else:
                    # 早期点已全部滚出屏幕，全部实线
                    solid_coords = []
                    for i in range(n_pts):
                        cx = px0 + i * step2 + self.BAR_W // 2
                        cy = py1 - (min(eff_pts[i], 100.0) / 100.0) * ph
                        solid_coords.extend([cx, cy])
                    if len(solid_coords) >= 4:
                        c.create_line(*solid_coords, fill="#4488CC", width=2,
                                      smooth=False, tags="eff_line")
            # 再画折点
            for i, e_val in enumerate(eff_pts):
                cx = px0 + i * step2 + self.BAR_W // 2
                r_eff = round(e_val)  # 与显示(.0f)一致的整数判定：99.6 显示"100%"→金色、60.4 显示"60%"→珊瑚红
                over_100 = r_eff >= 100
                cy = py1 - (min(e_val, 100.0) / 100.0) * ph
                r = 4
                if over_100:
                    dot_fill = "#D4A017"
                elif r_eff <= 60:
                    dot_fill = "#FF6B6B"
                else:
                    dot_fill = "#4488CC"
                orig_idx = eff_start_idx + i
                is_early = orig_idx < 3
                if is_early:
                    c.create_oval(cx - r, cy - r, cx + r, cy + r,
                                  outline="", fill=dot_fill, tags="eff_dot")
                    for seg_start in range(0, 360, 60):
                        c.create_arc(cx - r - 1, cy - r - 1, cx + r + 1, cy + r + 1,
                                     start=seg_start, extent=45, style="arc",
                                     outline="#FFF8E0", width=1, dash=(3, 3), tags="eff_dot")
                else:
                    c.create_oval(cx - r, cy - r, cx + r, cy + r,
                                  outline="#FFF8E0", width=1, fill=dot_fill, tags="eff_dot")

        # ── 鼠标悬浮提示（单一 Motion 命中，无需逐柱命中区对象）──

        # 存储当前可见数据供 Motion handler 使用
        self._chart_motion_visible = list(visible)
        self._chart_motion_eff = list(eff_pts) if eff_pts else []
        # 因子也对齐到可见柱：取与 visible 等长的尾部切片
        factors_all = list(getattr(self, '_eff_factors', deque())) if hasattr(self, '_eff_factors') else []
        f_visible = factors_all[-len(visible):] if len(factors_all) > len(visible) else factors_all
        n_f = min(len(f_visible), len(visible))
        self._chart_motion_factors = f_visible[-n_f:] if n_f else []
        # 收割标记也对齐到可见柱（与 visible 等长，供悬浮提示如实标注）
        p_all = partial_all[-len(visible):] if len(partial_all) > len(visible) else partial_all
        self._chart_motion_partial = list(p_all)
        self._chart_motion_px0 = px0
        self._chart_motion_step = step
        self._chart_motion_bar_w = self.BAR_W
        # 坐标轴
        c.create_line(px0, py0, px0, py1, fill="#666")
        c.create_line(px0, py1, px1, py1, fill="#666")
        # 标题 — 居中在顶部黑色区域，不与图表重叠
        c.create_text(px0 + pw//2, 10, text=f"本次优化 {self._fmt_label(latest)}",
                      anchor="center", fill="#ccc", font=("微软雅黑", 9))
        # 底部三指标
        metrics_y = ch - 6
        avg_eff = sum(eff_data) / len(eff_data) if eff_data else 50
        avg_eff_text = f"{avg_eff:.0f}%"
        c.create_text(px0 + pw//2, metrics_y,
                      text=f"平均 {self._fmt_label(avg_val)}    最高 {self._fmt_label(peak_val)}    平均效率 {avg_eff_text}",
                      anchor="s", fill="#aaa", font=("Consolas", 8))
        # 单一 Motion 绑定（替代多柱 Enter/Leave，消除事件竞争）
        c.tag_unbind("all", "<Enter>")
        c.tag_unbind("all", "<Leave>")
        c.bind("<Motion>", self._chart_on_motion)
        c.bind("<Leave>", self._chart_hide_tip)

    def _save_eris_ewma(self):
        """持久化 ERIS IQR 分位数窗（原子写入）"""
        try:
            import json, os
            bufs = getattr(self, '_eris_bufs', None)
            if bufs and any(bufs):
                data = {"bufs": [list(b) for b in bufs],
                        "iqr_ewma": getattr(self, "_eris_iqr_ewma", [0.0]*5),
                        "p50_ewma": getattr(self, "_eris_p50_ewma", [0.0]*5)}
                path = os.path.join(os.path.dirname(STATE_FILE), "memwise_eris_ewma.json")
                tmp = path + ".tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.replace(tmp, path)
        except Exception:
            pass
    
    def _load_eris_ewma(self):
        """加载 ERIS 分位数窗（热重启保留/冷启动重建），严格校验"""
        # 若已有数据（热重启：daemon 重开但程序未退出），保留不重建
        if hasattr(self, '_eris_bufs') and any(self._eris_bufs):
            self._eris_prev = None
            self._eris_prev_factor_dim = -1
            self._eris_prev_factor_pos = None
            self._eris_ewma_trend = []
            self._last_eris_game_mode = getattr(getattr(self, 'cleaner', None), 'game_mode', False)
            return
        _WINDOWS = [25, 25, 20, 8, 20]
        loaded_ok = False
        try:
            import json, os
            from collections import deque
            path = os.path.join(os.path.dirname(STATE_FILE), "memwise_eris_ewma.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and isinstance(data.get("bufs"), list) and len(data["bufs"]) == 5:
                    bufs_raw = data["bufs"]
                    iqr_ewma = data.get("iqr_ewma", [0.0]*5)
                    p50_ewma = data.get("p50_ewma", [0.0]*5)
                    if (isinstance(iqr_ewma, list) and len(iqr_ewma) == 5 and
                        isinstance(p50_ewma, list) and len(p50_ewma) == 5):
                        # 校验逻辑与回归测试共用 core.eris.validate_state（防测试副本与生产分歧）
                        if validate_state(bufs_raw, iqr_ewma, _WINDOWS) and validate_state(bufs_raw, p50_ewma, _WINDOWS):
                            self._eris_bufs = [deque(b, maxlen=_WINDOWS[j]) for j, b in enumerate(bufs_raw)]
                            self._eris_iqr_ewma = [float(v) for v in iqr_ewma]
                            self._eris_p50_ewma = [float(v) for v in p50_ewma]
                            loaded_ok = True
        except Exception:
            pass
        if not loaded_ok:
            from collections import deque
            self._eris_bufs = [deque(maxlen=_WINDOWS[j]) for j in range(5)]
            self._eris_iqr_ewma = [0.0] * 5
            self._eris_p50_ewma = [0.0] * 5
        # 重置因子状态
        self._eris_prev = None
        self._eris_prev_factor_dim = -1
        self._eris_prev_factor_pos = None
        self._eris_ewma_trend = []
        self._last_eris_game_mode = getattr(getattr(self, 'cleaner', None), 'game_mode', False)

    # ── 图表悬浮提示 ──

    def _chart_show_tip(self, x, freed_mb, eff_pct, idx):
        c = self.chart_canvas
        self._chart_hide_tip(None)
        # 限制 tooltip 不超出左右边界
        cw = c.winfo_width() or 400
        x = max(66, min(cw - 66, x))
        tip_y0 = 22
        factor_str = ""
        if hasattr(self, '_chart_motion_factors'):
            factors = getattr(self, '_chart_motion_factors', [])
            if idx < len(factors) and factors[idx]:
                factor_str = "\n" + " ".join(factors[idx])
        # 收割未完成周期如实标注（效率与因子仍按真实数据计算）
        partial_note = ""
        partials = getattr(self, '_chart_motion_partial', [])
        if idx < len(partials) and partials[idx]:
            partial_note = "\n本轮收割未完成"
        # 先画文字获取包围盒
        text_full = f"释放 {self._fmt_label(freed_mb)}\n效率 {eff_pct:.0f}%{factor_str}{partial_note}"
        tid = c.create_text(x, tip_y0 + 20,
                      text=text_full,
                      fill="#eee", font=("Consolas", 8),
                      justify="center", tags="chart_tip_text")
        # 自适应蓝框（包围盒 + 边距）
        bbox = c.bbox(tid)
        if bbox:
            px_margin = 8; py_margin = 6
            c.create_rectangle(bbox[0] - px_margin, bbox[1] - py_margin,
                               bbox[2] + px_margin, bbox[3] + py_margin,
                               fill="#2d2d2d", outline="#4488CC", width=1,
                               tags="chart_tip_rect")
            c.tag_lower("chart_tip_rect", tid)
        # 合并标签便于统一删除
        c.addtag_withtag("chart_tip", "chart_tip_rect")
        c.addtag_withtag("chart_tip", "chart_tip_text")

    def _fmt_label(self, v):
        if abs(v) >= 1000:
            return f"{v/1024.0:.1f}GB"
        return f"{v:.1f}MB"

    def _fmt_count(self, n):
        if n >= 1000:
            return f"{n/1000:.1f}k"
        return str(n)

    def _chart_hide_tip(self, event):
        self.chart_canvas.delete("chart_tip")

    def _chart_on_motion(self, event):
        """单一 Motion 悬浮处理：计算列索引，列不变跳过重绘"""
        visible = getattr(self, '_chart_motion_visible', [])
        if not visible:
            return
        px0 = getattr(self, '_chart_motion_px0', 0)
        step = getattr(self, '_chart_motion_step', 17)
        col = (event.x - px0) // step
        if col == getattr(self, '_last_hover_col', -1):
            return  # 同一列，不重复重绘
        if 0 <= col < len(visible):
            self._last_hover_col = col
            eff_data = getattr(self, '_chart_motion_eff', [])
            eff_val = eff_data[col] if col < len(eff_data) else 50
            # 计算柱条中心 x，tooltip 固定居中于此
            cx = px0 + int(col * step + getattr(self, '_chart_motion_bar_w', 8) // 2)
            self._chart_show_tip(cx, visible[col], eff_val, col)
        else:
            self._last_hover_col = -1
            self._chart_hide_tip(None)

    # ---- 优化 ----

    def _on_optimize(self):
        if self._optimizing:
            return
        if self.daemon_running:
            # 守护运行中：一键清理转为即时轻量系统清理（游戏进行中跳过，不打断游戏）
            if self.cleaner.game_mode:
                self._log("游戏进行中，跳过手动清理以保障流畅")
                return
            threading.Thread(target=self._opt_quick_light, daemon=True).start()
            return
        self._optimizing = True
        self.btn_opt.configure(state="disabled"); self.lbl_st["text"] = "优化中..."
        self._log_op("开始优化...")
        threading.Thread(target=self._opt_worker, daemon=True).start()

    def _opt_quick_light(self):
        """守护运行中的即时轻量清理（无进程决策，避免与守护周期竞态）"""
        if getattr(self, '_quick_light_running', False):
            return
        self._quick_light_running = True
        try:
            if self.cleaner.game_mode:
                return
            ops = set(CFG.get("clean_operations") or [])
            use = {"standby", "standby_low", "modified", "registry"} & ops
            if use:
                self.cleaner._layer1_memreduct(full=False, ops=use, clean_self=False)
            m = winapi.get_memory_status()
            self._msg_queue.put(('log', f"⚡ 已执行即时轻量清理（可用内存 {m['pct'] if m else '?'}%）"))
        except Exception:
            import traceback; traceback.print_exc(file=_ERR)
        finally:
            self._quick_light_running = False

    def _opt_worker(self):
        mode = self.mode_var.get()
        ops = CFG.get("clean_operations")
        try:
            snaps = []
            for i in range(3):
                snaps = self.sniffer.snapshot(); self.learner.feed(snaps)
                if i < 2: time.sleep(2)
            self._msg_queue.put(('log', f"观察到 {len(snaps)} 个进程"))
            m0 = winapi.get_memory_status()
            all_l2 = []; all_probe = []
            total_net = 0
            freed0 = self.cleaner.summary()['freed_mb']  # 释放量基线（标量总和口径）
            for round_idx in range(3):
                if round_idx == 0:
                    r = self.cleaner.optimize(snaps, self.learner, mode, operations=ops)
                else:
                    snaps = self.sniffer.snapshot(); self.learner.feed(snaps)
                    r = self.cleaner.optimize(snaps, self.learner, mode, operations=ops)
                all_l2.extend(r.get("layer2", []))
                all_probe.extend(r.get("probe", []))
                total_net += r.get("net_freed", 0)
                if round_idx < 2:
                    time.sleep(2)
            self.learner.save(STATE_FILE)
            m1 = winapi.get_memory_status()
            freed1 = self.cleaner.summary()['freed_mb']
            released = max(0.0, freed1 - freed0)  # 三轮释放量标量总和
            pct_str = f"，可用内存 {m0['pct']}%→{m1['pct']}%" if m0 and m1 else ""
            self._msg_queue.put(('log', f"📊 三轮优化合计释放 {released:.1f} MB · 内存净下降 {total_net/(1<<20):.1f} MB{pct_str}"))
            self._msg_queue.put(('log_op', f"优化完成 · 三轮合计释放 {released:.1f} MB（净下降 {total_net/(1<<20):.1f} MB）"))
            self._msg_queue.put(('opt_done', {
                "mode": mode, "layer2": all_l2, "probe": all_probe}))
        except Exception:
            import traceback; traceback.print_exc(file=_ERR)
            self._msg_queue.put(('log', "⚠ 手动优化异常，已自动恢复"))
            self._msg_queue.put(('opt_done', {
                "mode": mode, "layer2": [], "probe": []}))

    def _opt_done(self, result):
        s = self.cleaner.summary()
        trimmed = [t for t in result.get("layer2", []) if t[1]]
        for snap, ok, freed, reason in trimmed[:10]:
            self._log(f"  ✓ {snap.name} (PID={snap.pid}) {freed/(1<<20):.0f}MB — {reason}")
        # 统计栏始终显示程序运行以来累计总量
        winapi.report_event("MemWise", f"GUI 优化: {s['freed_mb']}MB 释放, {len(trimmed)} 进程")
        self._upd_stats()
        self._optimizing = False
        self.btn_opt.configure(state="normal")
        self.lbl_st["text"] = "就绪 · Ctrl+Shift+M"

    # ---- 守护 ----

    def _on_daemon(self):
        if self.daemon_running: return
        if self._optimizing:
            self._log_op("手动优化进行中，请等待完成后再启动守护")
            return
        self.daemon_running = True
        # 防双守护：旧线程若仍存活（停止后短暂收尾），等待其退出再启动新线程
        if self.daemon_thread and self.daemon_thread.is_alive():
            self.daemon_thread.join(timeout=1.5)
            if self.daemon_thread.is_alive():
                self._log_op("上一守护线程仍在收尾，请稍候再试")
                self.daemon_running = False
                return
        self.btn_dae.configure(state="disabled"); self.btn_stop.configure(state="normal")
        self.lbl_st["text"] = "守护运行中"; self._log_op("守护模式启动")
        s = self.cleaner.summary()
        self._chart_last_freed = float(s['freed_mb'])
        self._prev_trim_count = s['ws_trim']
        self._prev_fail_count = s['failed_feedback']
        self._chart_data.clear()
        self._eff_data.clear()
        self._eff_factors.clear()
        self._chart_cycle_meta.clear()
        self._chart_eris_last_seq = -1
        self._chart_bar_seq = 0
        self._load_eris_ewma()  # 恢复 EWMA 基线
        self._last_sys_ops = 0
        self._cycle_trimmed = 0
        self._cycle_failed = 0
        self.daemon_thread = threading.Thread(target=self._dae_worker, daemon=True)
        self.daemon_thread.start()
        self._update_watchdog_daemon(True)  # 崩溃恢复时据此续守护

    def _dae_worker(self):
        h_low = h_high = None
        try:
            # 创建内存通知对象（事件驱动取代轮询）
            h_low = winapi.create_memory_resource_notification(
                winapi.MEMORY_RESOURCE_NOTIFICATION_TYPE_LOW)
            h_high = winapi.create_memory_resource_notification(
                winapi.MEMORY_RESOURCE_NOTIFICATION_TYPE_HIGH)
            use_event_driver = (h_low is not None and h_high is not None)
            
            interval = CFG.get("interval",30)
            last_cfg_check = 0
            last_save = 0
            startup_logged = False
            overtime_debt = 0  # 累计超时债务（秒），下一轮 deadline 中扣除
            
            while self.daemon_running:
                tick_start = time.time()
                # 60s 完整周期从等待开始计（pre_wait 计入周期，防长期漂移）
                cycle_start = tick_start

                # 收尾上一轮超时的 harvest（尽力等待，避免双份 trim 叠加）
                ph = getattr(self, '_pending_harvest', None)
                if ph is not None:
                    try:
                        if not ph.done():
                            ph.result(timeout=5)
                    except Exception:
                        pass
                    self._pending_harvest = None
                
                # 事件驱动等待：内存变化或超时（仅短等待，由 deadline 控制总周期）
                pre_wait = max(3, interval // 15)
                if use_event_driver:
                    for _ in range(pre_wait):
                        if not self.daemon_running:
                            return
                        ret = winapi.wait_for_object(h_low, 1000)
                        if ret == "signaled":
                            break
                else:
                    for _ in range(pre_wait):
                        if not self.daemon_running:
                            return
                        time.sleep(1)
                
                # 60s 周期从工作阶段继续计算（等待已计入 cycle_start）
                m = winapi.get_memory_status()
                if not m: time.sleep(interval); continue
                snaps = self.sniffer.snapshot(); self.learner.feed(snaps)

                total_samples = sum(p.total_samples for p in self.learner.profiles.values())
                learned = len(self.learner.profiles)

                if not startup_logged:
                    self._msg_queue.put(('log', f"🧠 观察到 {len(snaps)} 个进程 · 已有 {learned} 个画像"))
                    startup_logged = True
                self._cycle_log_buffer = []  # 本轮周期末批量输出缓存
                agg_first = self.judger.aggressiveness
                agg_max = agg_first  # 本轮峰值
                layer3_ran_start = self.cleaner.summary().get("layer3_ran", 0)
                deep_triggered = False  # 本轮是否触发过深度清理

                # 清理
                mode = CFG.get("clean_mode", "normal")  # 读 CFG 镜像：tk 变量非线程安全，daemon 线程不触碰 Tk 对象
                agg = self.judger.update_pressure(m['pct'])
                ops = CFG.get("clean_operations")
                # 连续优化循环：deadline + 多次 optimize + gap fill + blitz
                m_emerg = winapi.get_memory_status()
                if m_emerg and m_emerg.get("pct", 0) >= CFG.get("emergency_threshold", 80):
                    agg_emerg = self.judger.update_pressure(m_emerg["pct"])
                    self.cleaner.optimize(snaps, self.learner, "full", operations=ops, aggressiveness=agg_emerg)
                    self._msg_queue.put(('log', "⚠ 紧急触发清理(full模式)"))
                interval = CFG.get("interval", 60)  # 周期由配置驱动（默认 60s，原硬编码 60 使配置键失效）
                deadline = time.time() + interval - 3 - overtime_debt
                l2_all = []; probe_all = []
                gap_base = max(8, min(20, CFG.get("gap_seconds", 12)))
                gap = gap_base
                if self.cleaner.game_mode:
                    gap = gap_base * 1.5  # 游戏模式：降低操作密度，减少对磁盘I/O的竞争
                prev_per_proc = 0.0
                while time.time() < deadline - 6 and self.daemon_running:
                    gap_end = min(time.time() + gap, deadline - 6)
                    snap_skip = 0
                    while time.time() < gap_end and self.daemon_running:
                        # 快照降频：每3s采集一次（节省~20% CPU/功耗，进程列表在gap期间变化极小）
                        if snap_skip <= 0:
                            snaps = self.sniffer.snapshot(); self.learner.feed(snaps)
                            snap_skip = 6
                            # 游戏模式：快照后实时检测启动/退出（检测零开销），
                            # 周期内启动又退出时，两条日志按序进入周期末打包通道
                            game_now = self.cleaner._is_user_game_running(snaps)
                            if self.cleaner._game_mode_manual:
                                # 手动模式：实时刷新 PID 保护集，不自动切换模式
                                if game_now:
                                    self.cleaner.judger._game_pid_set = {
                                        s.pid for s in snaps if s.name.lower() in self.cleaner._get_user_game_procs()}
                            elif not self.cleaner.game_mode and game_now:
                                self.cleaner.game_mode = True
                                self.cleaner.judger.game_mode = True
                                self.cleaner.judger._game_proc_set = set()
                                self.cleaner.judger._game_pid_set = {
                                    s.pid for s in snaps if s.name.lower() in self.cleaner._get_user_game_procs()}
                                self._cycle_log_buffer.append("🎮 检测到游戏运行 · 启用 游戏模式")
                            elif self.cleaner.game_mode and not game_now:
                                self.cleaner.game_mode = False
                                self.cleaner.judger.game_mode = False
                                self.cleaner.judger._game_proc_set.clear()
                                self.cleaner.judger._game_pid_set.clear()
                                self._cycle_log_buffer.append("🎮 游戏已退出 · 恢复正常模式")
                            # 高频压制只做注册表缓存（零磁盘 I/O）；standby/脏页写回由 gap 末
                            # optimize 与 harvest 统一清理——standby 需要累积时间才有释放量，
                            # 高频清空只会让文件缓存持续失效并反复写盘
                            if not self.cleaner.game_mode:
                                self.cleaner._layer1_memreduct(full=False, ops={"registry"}, clean_self=False)
                                if mode != "quick":
                                    for ft_pid in list(self.cleaner._fast_track):
                                        if not self.cleaner.quick_retrim(ft_pid):
                                            self.cleaner._fast_track.discard(ft_pid)
                        snap_skip -= 1
                        m2 = winapi.get_memory_status()
                        if m2:
                            agg = self.judger.update_pressure(m2["pct"]); m = m2
                            agg_max = max(agg_max, agg)
                        # 节奏控制：0.5s 间隔保持高频温和压制，杜绝忙循环空转烧 CPU
                        time.sleep(0.5)
                    # gap-fill 天花板：quick 保持 quick，其余统一用 normal（deep/full 的重操作留给 harvest）
                    gap_fill_mode = "quick" if mode == "quick" else "normal"
                    if self.cleaner.game_mode:
                        # 游戏模式：gap 期间不清理（避免周期性缺页卡顿），只维持周期节奏
                        result = {"mode": gap_fill_mode, "aggressiveness": agg, "layer2": [], "probe": [], "net_freed": 0}
                    else:
                        result = self.cleaner.optimize(snaps, self.learner, gap_fill_mode, operations=ops, aggressiveness=agg, allow_layer3=False)
                    agg = result.get("aggressiveness", agg)
                    l2_all.extend(result.get("layer2", []))
                    probe_all.extend(result.get("probe", []))
                    trimmed_n = len([t for t in result.get("layer2", []) if t[1]])
                    # gap 自适应：纯进程释放口径（系统级释放不稀释每进程收益）
                    release = sum(t[2] for t in result.get("layer2", []) if t[1])
                    per_proc = release / max(trimmed_n, 1)
                    if prev_per_proc > 0 and trimmed_n > 0:
                        if per_proc > prev_per_proc * 1.3:
                            gap = max(8.0, gap - 2)
                        elif per_proc < prev_per_proc * 0.7:
                            gap = min(25.0, gap + 3)
                    prev_per_proc = per_proc
                while time.time() < deadline - 4 and self.daemon_running:
                    if mode != "quick" and not self.cleaner.game_mode:
                        self.cleaner._layer1_memreduct(full=False, ops={"registry"}, clean_self=False)
                    time.sleep(1.5)
                # harvest：每轮完整收割（游戏进程由 PID 保护、系统缓存由 game_mode 跳过，
                # 非游戏进程清理不影响游戏流畅；图表每轮保持真实数据）
                if not self.daemon_running:
                    break
                harvest_future = self.cleaner._trim_executor.submit(
                    self.cleaner.optimize, snaps, self.learner, mode,
                    operations=ops, aggressiveness=agg)
                result = None
                try:
                    result = harvest_future.result(timeout=30)
                except concurrent.futures.TimeoutError:
                    self._pending_harvest = harvest_future  # 下轮开头收尾，避免任务叠加
                    result = {"mode": mode, "aggressiveness": agg, "layer2": [], "probe": [],
                              "net_freed": 0, "_partial": True}
                    self._cycle_log_buffer.append("⏱ harvest 超时(30s)·跳过本轮诊断")
                except Exception:
                    self._pending_harvest = harvest_future
                    result = {"mode": mode, "aggressiveness": agg, "layer2": [], "probe": [],
                              "net_freed": 0, "_partial": True}
                if result is None:
                    result = {"mode": mode, "aggressiveness": agg, "layer2": [], "probe": [],
                              "net_freed": 0, "_partial": True}
                harvest_partial = result.get("_partial", False)
                agg = result.get("aggressiveness", agg)
                self.judger.aggressiveness = agg  # 同步入 judger，下一周期 agg_first 正确
                agg_max = max(agg_max, agg)  # 捕获全量模式强制的 agg 峰值
                # harvest 后刷新内存状态：日志/图表/EFIS 输入用最新值（harvest 最长 30s，旧值会滞后一轮）
                m_fresh = winapi.get_memory_status()
                if m_fresh:
                    m = m_fresh
                l2_all.extend(result.get("layer2", []))
                probe_all.extend(result.get("probe", []))
                l2_results = l2_all
                probe_results = probe_all
                s = self.cleaner.summary()
                # 计算本周期 delta
                cur_trim = s['ws_trim']
                cur_fail = s.get('failed_feedback', 0)
                self._cycle_trimmed = cur_trim - self._prev_trim_count
                self._cycle_failed = cur_fail - self._prev_fail_count
                cycle_standby = (s.get("standby",0) + s.get("modified",0) + s.get("filecache",0)
                                 + s.get("registry",0) + s.get("volume",0)) - self._last_sys_ops
                self._last_sys_ops = (s.get("standby",0) + s.get("modified",0) + s.get("filecache",0)
                                     + s.get("registry",0) + s.get("volume",0))
                self._prev_trim_count = cur_trim
                self._prev_fail_count = cur_fail
                now = time.time()
                # 配置热加载：每秒检查一次 config.yaml 是否变更
                if now - last_cfg_check > 5:
                    last_cfg_check = now
                    try:
                        mtime = os.path.getmtime(_config.CONFIG_PATH)
                        if mtime != getattr(self, "_cfg_mtime", 0):
                            self._cfg_mtime = mtime
                            _config.load()
                            CFG.update(_config.load())
                            # 同步 judger 运行配置（排除列表/游戏名单/清理深度/EFIS 参数守护期间即时生效）
                            self.judger.cfg["never"] = CFG.get("never", [])
                            self.judger.cfg["game_processes"] = CFG.get("game_processes", [])
                            self.judger.cfg["clean_passes"] = CFG.get("clean_passes", 4)
                            self.judger.cfg["efis_params"] = CFG.get("efis_params", {})
                    except Exception as e:
                        import sys; print(f"[MemWise] 配置加载异常: {e}", file=_ERR)
                if now - last_save > 30:
                    last_save = now
                    self.judger.purge_expired()
                    self.learner.save(STATE_FILE)
                trimmed = [(snap, ok, freed, reason) for snap, ok, freed, reason in l2_results if ok]
                failed = [r for r in l2_results if not r[1]]
                ratios = []
                for r in failed:
                    snap = r[0]
                    p = self.learner.get_profile(snap.name)
                    if p and hasattr(p.kalman, 'x_freed') and p.kalman.x_freed > 0:
                        ratio = r[2] / max(p.kalman.x_freed, 1.0)  # 实际/预期
                        ratios.append(min(ratio, 1.0))
                    else:
                        ratios.append(0.5)  # 无画像或预期为零，默认半值
                self._failed_weight = sum(ratios) / len(ratios) if ratios else 0.5
                probe_ok = sum(1 for _, ok, _ in probe_results if ok)

                # 累计图表数据 — 每轮必定推送，chart_accum 即本轮净释放
                cur_freed = float(s['freed_mb'])
                cycle_freed = cur_freed - self._chart_last_freed
                self._chart_last_freed = cur_freed
                chart_accum = max(0.0, cycle_freed)
                # 每轮必定推送一个柱，零释放轮也占位，图表与日志严格一一对应
                self._chart_bar_seq += 1
                with self._chart_lock:
                    self._chart_data.append(chart_accum)
                    self._chart_cycle_meta.append((self._chart_bar_seq, self._cycle_trimmed,
                        self._cycle_failed, m["pct"], getattr(self, "_failed_weight", 0.5), harvest_partial))
                # 每周期无条件清零 PF 计数（harvest 超时/游戏降频周期也丢弃，防跨周期污染诊断窗口）
                pf_delta_cycle = _drain_pf_delta(self.judger)
                # Layer3 周期增量基线（累计口径会让诊断误判"持续触发"，导致 gate 持续爬升）
                l3_ran_cur = s.get('layer3_ran', 0)
                l3_extra_cur = s.get('layer3_extra', 0)
                l3_ran_delta = max(0, l3_ran_cur - getattr(self, '_last_l3_ran', 0))
                l3_extra_delta = max(0, l3_extra_cur - getattr(self, '_last_l3_extra', 0))
                self._last_l3_ran = l3_ran_cur
                self._last_l3_extra = l3_extra_cur
                if hasattr(self, 'efis') and not harvest_partial:
                    # 场景检测（game/browser/development/general）先于调参诊断
                    try:
                        self.efis.detect_scene(snaps, winapi.is_foreground_fullscreen(), m['pct'])
                    except Exception as e:
                        _log_write("异常", f"EFIS 场景检测异常: {e!r}")
                    stats = {
                        'mem_pct': m['pct'],
                        'mode': mode,
                        'trimmed_cnt': self._cycle_trimmed,
                        'failed_cnt': self._cycle_failed,
                        'total_attempts': self._cycle_trimmed + self._cycle_failed,
                        'cycle_freed': cycle_freed,
                        'snaps': snaps,
                        'fore_fullscreen': winapi.is_foreground_fullscreen(),
                        # ── EFIS 诊断输入全量补齐（11 字段，调参分支获得真实数据）──
                        'theta_mean': _prof_theta_mean(self.learner),
                        'theta_above_06': _prof_theta_above(self.learner),
                        'agg': agg,
                        'pf_delta': pf_delta_cycle,
                        'cycle_duration': max(1.0, time.time() - cycle_start),
                        'deepen_cnt': s.get('deepen_cnt', 0),
                        'deepen_extra': s.get('deepen_extra', 0),
                        'layer3_ran': l3_ran_delta,
                        'layer3_extra': l3_extra_delta,
                        'cooldown_cnt': sum(1 for t in self.judger.cooldown.values() if t > time.time()),
                        'repeat_fail': len(failed),
                    }
                    try:
                        efis_msg = self.efis.tick(stats)
                    except Exception as e:
                        _log_write("异常", f"EFIS 调参异常: {e!r}")
                        efis_msg = None
                    if efis_msg:
                        params = self.efis.get_params()
                        # 同步 EFIS 参数到 CFG 和 judger.cfg
                        # judger.cfg 才是 cleaner/judger 读取 efis_params 的来源
                        CFG['efis_params'] = params
                        self.judger.cfg['efis_params'] = params
                        self.judger.cfg['clean_passes'] = CFG.get('clean_passes', 4)
                        _save_cfg()  # EFIS 调参落盘：重启后消费方与引擎参数一致
                        _log_write("调参", efis_msg)  # 调参决策入统一日志
                        # 同步 Kalman 超参数到 learner
                        if hasattr(self, 'learner'):
                            self.learner._kalman_r = params.get('kalman_r', 5.0)
                    if efis_msg:
                        self._msg_queue.put(('display', ['[EFIS] ' + efis_msg]))  # 仅显示：[调参] 已直写落盘

                # 元认知（harvest 超时时跳过，避免零数据污染诊断）
                if not harvest_partial:
                    meta_stats = {
                        'mem_pct': m['pct'],
                        'trimmed_cnt': self._cycle_trimmed,
                        'failed_cnt': self._cycle_failed,
                        'total_attempts': self._cycle_trimmed + self._cycle_failed,
                        'cycle_freed': cycle_freed,
                        'snaps': snaps,
                        'fore_fullscreen': winapi.is_foreground_fullscreen(),
                    }
                    meta_findings = []
                    try:
                        meta_findings = self.learner.meta.tick(meta_stats)
                    except Exception as e:
                        _log_write("异常", f"元认知异常: {e!r}")
                    if meta_findings:
                        for finding in meta_findings:
                            self._cycle_log_buffer.append(finding)

                # ── 收集并显示算法日志消息 ──
                # 游戏检测消息改走批量通道，防被 _log_batch 清屏擦除
                for msg in self.cleaner.pop_game_msgs():
                    self._cycle_log_buffer.append(msg)
                for msg in self.learner.pop_info():
                    self._cycle_log_buffer.append(msg)
                for msg in self.cleaner.pop_info():
                    self._cycle_log_buffer.append(msg)
                if hasattr(self.judger, '_info_msgs') and self.judger._info_msgs:
                    for msg in self.judger._info_msgs:
                        self._cycle_log_buffer.append(msg)
                    self.judger._info_msgs.clear()

                # 周期日志（已并入统一日志常开落盘，此处旧逻辑移除）

                deep_triggered = self.cleaner.summary().get("layer3_ran", 0) > layer3_ran_start
                # 合并压力+深度清理日志（与上一周期峰值比较，仅变化时输出）
                agg_peak = agg_max
                mem_str = self.judger._mem_label(m['pct'])
                a_cur = self.judger._agg_label(agg_peak)
                last_peak = getattr(self, '_last_agg_peak', None)
                last_mem = getattr(self, '_last_pressure_mem', '')
                if last_peak is None:
                    change_str = a_cur  # 首轮直接显示
                elif a_cur == self.judger._agg_label(last_peak):
                    change_str = f"维持{a_cur}"
                else:
                    change_str = f"{self.judger._agg_label(last_peak)}→{a_cur}"
                deep_changed = deep_triggered != getattr(self, '_last_deep_triggered', False)
                if last_mem != mem_str or change_str != getattr(self, '_last_pressure_chg', '') or deep_changed:
                    deep_str = " · 已触发深度清理" if deep_triggered else ""
                    self._cycle_log_buffer.append(
                        f"📈 内存 {m['pct']:.0f}%（{mem_str}）· 清理强度：{change_str}{deep_str}")
                    self._last_pressure_mem = mem_str
                    self._last_pressure_chg = change_str
                    self._last_agg_peak = agg_peak
                    self._last_deep_triggered = deep_triggered
                # 周期汇总：文件侧由 [清理] 直写（毫秒时间戳+独立类别）；GUI 仅显示不重复落盘
                summary_line = (f"本轮释放 {self._fmt_label(cycle_freed)} · 系统杂项 {self._fmt_count(cycle_standby)} · "
                                f"整理 {self._fmt_count(self._cycle_trimmed)} 进程 · "
                                f"试探 {len(probe_results)} ({probe_ok}成功)")
                if CFG.get("log_to_file"):
                    _log_write("清理", summary_line)
                # GUI 日志区：summary 与本轮 buffer 一次打包显示（同一清屏判定）。
                # 曾见 summary 先入队、log_batch 后入队时被后者的清屏抹掉——第二轮周期末统计日志缺失根因
                batch_display = [summary_line] + list(self._cycle_log_buffer)
                self._msg_queue.put(('display', batch_display))
                if CFG.get("log_to_file"):
                    # buffer 内容（压力/游戏/决策等）直写 [界面]，与 [清理] 分开，去重保持
                    for m in self._cycle_log_buffer:
                        _log_write("界面", m)
                # 状态栏（累计数据）
                self._msg_queue.put(('upd_ui', (s, m, "🟢 守护中")))
                self._msg_queue.put(('chart', None))
                elapsed = time.time() - cycle_start
                # 周期补偿：超时累积债务，下一轮 deadline 中扣除；提前完成则还债
                if elapsed > interval:
                    overtime_debt = min(30, overtime_debt + (elapsed - interval))
                else:
                    overtime_debt = max(0, overtime_debt - (interval - elapsed))
                # 分段睡眠：停止守护即时生效（不阻塞最长一个周期）
                remaining = max(0.5, interval - elapsed)
                while remaining > 0 and self.daemon_running:
                    time.sleep(min(0.5, remaining))
                    remaining -= 0.5
                if not self.daemon_running:
                    return  # 停止守护后立即退出，不提交多余回调
        except Exception as e:
            import traceback
            self._dae_error = f"{e}\n{traceback.format_exc()}"
            self.daemon_running = False
        finally:
            try:
                if h_low:
                    winapi.close_handle(h_low)
                if h_high:
                    winapi.close_handle(h_high)
            except Exception:
                pass
            self._msg_queue.put(('dae_stopped', None))

    def _upd_dae_ui(self, s, m, txt="🟢 守护中"):
        self.lbl_sb["text"] = f"系统杂项: {self._fmt_count(s['standby'] + s.get('modified',0) + s.get('filecache',0) + s.get('registry',0) + s.get('volume',0))}"
        self.lbl_tr["text"] = f"进程: {self._fmt_count(s['ws_trim'])}"
        fm = s['freed_mb']
        self.lbl_fr["text"] = f"释放: {fm/1024.0:.1f}GB" if fm >= 1000 else f"释放: {fm:.1f}MB"
        pct = m["pct"]
        icon = "🟢" if pct < 70 else ("🟡" if pct < 90 else "🔴")
        self.lbl_st["text"] = f"{icon} {txt} {pct}%"

    def _stop_daemon(self):
        if not self.daemon_running: return
        self._log_op("停止守护中..."); self.daemon_running = False

    def _dae_stopped(self):
        self.daemon_running = False
        self._update_watchdog_daemon(False)  # 守护已停止：崩溃恢复不应续守护
        self.btn_dae.configure(state="normal"); self.btn_stop.configure(state="disabled")
        err = getattr(self, '_dae_error', None)
        if err:
            self.lbl_st["text"] = "⚠ 守护异常"
            self._log_op(f"❌ 守护异常，详见下方错误信息")
            self._log(f"🔍 {err}")
            del self._dae_error
        else:
            self.lbl_st["text"] = "就绪 · Ctrl+Shift+M"; self._log_op("守护已停止")
        self.learner.save(STATE_FILE); self._save_eris_ewma(); self._upd_stats(); self.root.after(100, self._draw_chart)

    # ---- 窗口事件 ----

    def _on_close(self):
        """窗口关闭 — 根据设置决定行为"""
        mode = CFG.get("close_action", "ask")
        if mode == "minimize":
            self._minimized_to_tray = True
            self.root.withdraw()
            return
        if mode == "exit":
            self._do_exit()
            return
        # ask mode: 弹窗询问
        choice = tk.Toplevel(self.root)
        choice.withdraw()  # 先隐藏，构建完成居中后一次显示
        self._apply_icon(choice)
        choice.title("MemWise")
        choice.resizable(False, False)
        choice.transient(self.root)
        choice.focus_set()
        choice.lift()
        _center_geometry(choice, 360, 150)
        tk.Label(choice, text="点击关闭按钮后的操作：", font=("微软雅黑", 11)).pack(pady=(20, 15))
        result = ["minimize"]
        def pick_minimize():
            result[0] = "minimize"; choice.destroy()
        def pick_exit():
            result[0] = "exit"; choice.destroy()
        bf = ttk.Frame(choice)
        bf.pack(pady=5)
        ttk.Button(bf, text="最小化到托盘", width=20, command=pick_minimize).pack(side="left", padx=10)
        ttk.Button(bf, text="退出程序", width=20, command=pick_exit).pack(side="left", padx=10)
        choice.protocol("WM_DELETE_WINDOW", pick_minimize)
        choice.deiconify()  # 全部控件就绪，居中后一次显示
        self.root.wait_window(choice)
        if result[0] == "minimize":
            self._minimized_to_tray = True
            self.root.withdraw()
        else:
            self._do_exit()

    def _maybe_restore_daemon(self):
        """崩溃恢复：仅当 watchdog.json 记录崩溃前守护运行中才自动续守护"""
        try:
            import json
            with open(_watchdog_path(), "r", encoding="utf-8") as f:
                d = json.load(f)
            if d.get("daemon", False):
                self._on_daemon()
                self._log_op("🔄 从崩溃中恢复 — 守护模式已自动继续")
        except Exception:
            pass

    def _update_watchdog_daemon(self, flag):
        """同步 watchdog.json 的守护标志（守护启动/停止时更新，崩溃恢复据此判断）。
        os.replace 偶发被杀软瞬时锁文件：重试 3 次，仍失败则清理 tmp 放弃（不影响主功能）"""
        try:
            import json
            p = _watchdog_path()
            if not os.path.isfile(p):
                return
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
            d["daemon"] = flag
            tmp = p + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(d, f)
            for _ in range(3):
                try:
                    os.replace(tmp, p)
                    return
                except OSError:
                    time.sleep(0.2)
            try:
                os.remove(tmp)
            except Exception:
                pass
        except Exception:
            pass

    def _spawn_watchdog(self):
        """启动看门狗子进程 — 监控主程序崩溃并自动重启"""
        try:
            wd_path = _watchdog_path()
            import json
            with open(wd_path, "w", encoding="utf-8") as f:
                json.dump({"pid": os.getpid(), "ts": time.time(), "crash_count": 0,
                           "daemon": self.daemon_running}, f)
            si = subprocess.STARTUPINFO()
            si.dwFlags |= 0x00000001  # STARTF_USESHOWWINDOW
            si.wShowWindow = 0        # SW_HIDE
            if getattr(sys, "frozen", False):
                _cmd = [sys.executable, "--watchdog"]
            else:
                _cmd = [sys.executable, os.path.abspath(__file__), "--watchdog"]
            subprocess.Popen(_cmd,
                startupinfo=si, creationflags=0x08000000)  # CREATE_NO_WINDOW
        except Exception:
            pass

    def _do_exit(self):
        """直接退出（无确认）"""
        _log_write("系统", "程序退出")
        # 通知看门狗正常退出
        try:
            wd_path = _watchdog_path()
            if os.path.exists(wd_path):
                os.remove(wd_path)
        except Exception:
            pass
        self.daemon_running = False
        # 等待 daemon 线程退出（避免销毁窗口后线程访问已销毁控件）
        try:
            if getattr(self, 'daemon_thread', None) and self.daemon_thread.is_alive():
                self.daemon_thread.join(timeout=2)
        except Exception:
            pass
        try: winapi.tray_remove(self.root.winfo_id(), TRAY_UID)
        except Exception:
            pass
        try: self.cleaner.shutdown()
        except Exception:
            pass
        _save_cfg()
        try: self.learner.save(STATE_FILE)
        except Exception:
            pass
        try: self._save_eris_ewma()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        # 全部启动路径先设图标（映射前/隐藏期；wrapper 未创建时幂等，后续重设）
        self._set_main_window_icon()
        if not self._minimized_to_tray:
            self.root.deiconify()  # 首次映射即已居中，零闪烁
            # 同步重设：wrapper 在首次映射时创建，按钮图标在映射瞬间缓存，
            # 必须在按钮创建后立即重设 + SWP_FRAMECHANGED（窗口已映射才生效）刷新任务栏
            self.root.update_idletasks()
            self._set_main_window_icon()
            # 兜底：映射完成后重设（幂等，缓存复用零泄漏）
            self.root.after(150, self._set_main_window_icon)
        self.root.mainloop()

if __name__ == "__main__":
    MemWiseGUI().run()
