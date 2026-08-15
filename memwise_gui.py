"""
MemWise v4.1.080 GUI —— 图形界面
系统托盘 + 全局热键 + 颜色状态 + 排除列表编辑 + 设置面板
"""

import os, sys, time, threading, tkinter as tk, math, queue, subprocess, concurrent.futures, datetime, atexit
from collections import deque
from tkinter import ttk, simpledialog, messagebox
import ctypes
import ctypes.wintypes as w

# ── 无 UI 引擎（守护循环/ERIS/轮次数据/事件队列）+ 共享基础设施（路径/日志/配置单例/格式化）──
from core.engine import (
    base, res_dir, CFG, STATE_FILE, _save_cfg,
    _log_write, _log_open, _log_close, _diag_log, _ERR,
    fmt_label, fmt_count, MemWiseEngine,
    _watchdog_path, _spawn_watchdog, _update_watchdog_daemon,
    read_watchdog_daemon, remove_watchdog,
)

from core import winapi
from core.learner import PareLearner as Learner
from core.learner import _is_system_core  # 系统核心保护名单（进程排行终止保护等）
from core.judger import PareJudger as Judger
from core.cleaner import PareCleaner as Cleaner
from core.efis import EfisController
from core.sniffer import Sniffer
from core.icon_flat import FLAT_48_PNG, decode_png  # 任务栏扁平图标（内嵌 PNG，冷启动 exe 兼容）
from core.eris import iqr_dim, validate_state  # ERIS 纯函数核心（与回归测试共用）
from core.i18n import tr, tr_msg, translate_all, set_language, LANGUAGES, get_language  # 界面语言

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
            return None, None, tr_msg(f"无法识别按键「{p}」（需 ctrl/alt/shift + 单字母或 F1-F24）")
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

def _emergency_active(m):
    """紧急触发判定：使用率≥阈值，或可用百分比≤绝对阈值（emergency_abs_pct，默认 0=禁用——
    配置弹性：用户把使用率阈值调高时，可用内存过低仍兜底触发）"""
    if not m:
        return False
    if m.get("pct", 0) >= CFG.get("emergency_threshold", 80):
        return True
    ap = CFG.get("emergency_abs_pct", 0) or 0
    if ap > 0 and m.get("total") and m.get("avail"):
        return m["avail"] / m["total"] * 100 <= ap
    return False


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


@WNDPROC
def _wnd_proc(hwnd, msg, wp, lp):
    """Win32 窗口过程回调 — 零 Tkinter 调用，仅设置 _tray_action 标志"""
    global _gui_ref, _tray_action
    try:
        # 系统关机确认阶段（WM_ENDSESSION）：立即删除 watchdog.json，防止看门狗误判并报错弹窗。
        # 不在询问阶段（WM_QUERYENDSESSION）删除——关机可能被其他程序取消，删早会使看门狗失效
        if msg == 0x0016 and wp:  # WM_ENDSESSION（wParam 非 0 才是真结束——关机被取消时保留看门狗）
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
        if not self.widget.winfo_exists():
            return  # 窗口已销毁（after 回调残留）：跳过创建防 TclError
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


SINGLE_MUTEX_NAME = "Global\\MemWise_SingleInstance"


def _activate_existing_instance():
    """枚举顶层窗口，激活标题以「MemWise v」开头的既有实例（跨版本兼容——
    FindWindowW 精确标题随版本号失效，升级后旧实例窗口找不到无法激活）"""
    try:
        EnumProc = ctypes.WINFUNCTYPE(w.BOOL, w.HANDLE, w.LPARAM)
        found = []

        @EnumProc
        def _cb(hwnd, lparam):
            try:
                buf = ctypes.create_unicode_buffer(256)
                ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
                if buf.value.startswith("MemWise v"):
                    found.append(hwnd)
                    return False  # 找到即停
            except Exception:
                pass
            return True

        if ctypes.windll.user32.EnumWindows(_cb, 0) and found:
            hwnd = found[0]
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


class MemWiseGUI:
    def __init__(self):
        if CFG.get("log_to_file"):
            _log_open()  # 统一日志：按「记录运行日志到文件」开关开启（关=完全不写）
        global _gui_ref
        _gui_ref = self

        # 新旧版本彻底互斥：启动时无条件检查是否已有 MemWise 窗口运行。
        # 旧版本 mutex 名带版本号（Global\MemWise_vX.Y.Z_...），固定名 mutex 检测不到
        # 旧版实例——仅靠 mutex 无法阻止"旧版运行中启动新版"，补窗口存在性检查后
        # 跨版本全互斥（找到即激活旧窗口并退出）
        if _activate_existing_instance():
            self._mutex = None
            sys.exit(0)
        # 单实例检测 — 已有实例运行则激活后退出
        # Global\ 命名空间：管理员实例运行时普通进程 CreateMutexW 返回 ERROR_ACCESS_DENIED(5)
        # 而非 ALREADY_EXISTS(0xB7)——两者均视为已有实例，防双守护/双看门狗并发
        # mutex 名固定不带版本号：版本升级后新旧实例互斥（原带版本号可双实例并存）
        self._mutex = ctypes.windll.kernel32.CreateMutexW(None, False, SINGLE_MUTEX_NAME)
        _mutex_err = ctypes.windll.kernel32.GetLastError()
        if _mutex_err in (0xB7, 5):
            # mutex 冲突但窗口未找到（残留句柄或启动早期竞态）：防双开，直接退出
            if _mutex_err == 0xB7 or not self._mutex:
                self._mutex = None
                sys.exit(0)
            _log_write("诊断", "单实例互斥权限受限且无窗口，继续运行")
        
        # 崩溃恢复检测
        self._restored = "--restored" in sys.argv
        self._minimized_to_tray = False  # 显式初始化（--minimized 分支下方覆盖为 True）

        self.root = tk.Tk()
        self.root.withdraw()  # 先隐藏：居中定位后再统一显示，消除"默认位置闪现"
        self.root.title("MemWise v4.1.080")
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
        # CFG 同步同一来源：否则守护热加载（mtime 变化）会把 config.yaml 旧值覆盖回 judger.cfg
        CFG["efis_params"] = self.efis.get_params()
        # kalman_r 同步：新画像的 Kalman 观测噪声与 EFIS 调参结果一致（原只在调参轮生效，重启后回默认）；
        # 已有画像同样更新（2026-08-14 审查：EFIS 参数表"配置可调"应对全体画像生效，防名不副实）
        _kr = self.efis.get_params().get('kalman_r', 5.0)
        self.learner._kalman_r = _kr
        for _p in self.learner.profiles.values():
            _p.kalman.r = _kr
        self.sniffer = Sniffer()
        # ── 无 UI 引擎（守护循环/ERIS/轮次数据/事件队列全部移入 engine.py）──
        self.engine = MemWiseEngine(self.learner, self.judger, self.cleaner, self.efis,
                                    self.sniffer, STATE_FILE)
        self.daemon_thread = None  # 仅保留兼容引用（引擎线程在 engine 内）
        self._tray_icon_handle = None
        # 注意：_minimized_to_tray 已在上方初始化（--minimized/auto_start_minimize 分支），此处不得重复赋值覆盖
        # 消息队列 = 引擎事件队列（动作格式完全复用——消费端 _poll_msg_queue 零改动）
        self._msg_queue = self.engine.events
        self._log_history = deque(maxlen=300)  # 日志原文缓存（语言切换时按新语言重渲染）
        self._mem_pct = 0

        self._build_ui()
        self._refresh_mem()
        self._setup_hotkey_and_tray()
        adm = "✓" if winapi.is_elevated() else "✗"
        self._log(f"MemWise v4.1.080 启动· 当前是否管理员权限:{adm}")
        # 看门狗：spawn 子进程监控崩溃
        if not self._restored:
            _spawn_watchdog(self.engine.daemon_running)
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
                    fw = ctypes.windll.user32.FindWindowExW(None, None, "TkTopLevel", "MemWise v4.1.080")
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
        if self.engine.daemon_running:
            if pct >= 90:
                icon = pct_icon_handle or self._get_colored_icon("high", ICO_HIGH)
                tip = tr_msg(f"🔴 守护中 {pct}% — 内存紧张")
            elif pct >= 75:
                icon = pct_icon_handle or self._get_colored_icon("mid2", ICO_ORANGE)
                tip = tr_msg(f"🟠 守护中 {pct}% — 内存偏高")
            elif pct >= 60:
                icon = pct_icon_handle or self._get_colored_icon("mid", ICO_MID)
                tip = tr_msg(f"🟡 守护中 {pct}% — 内存偏高")
            else:
                icon = pct_icon_handle or self._get_colored_icon("low", ICO_LOW)
                tip = tr_msg(f"🟢 守护中 {pct}% — 正常")
        else:
            if pct >= 90:
                icon = self._get_colored_icon("idle_high", ICO_HIGH)
                tip = tr_msg(f"内存 {pct}% — 紧张")
            elif pct >= 75:
                icon = self._get_colored_icon("idle_mid2", ICO_ORANGE)
                tip = tr_msg(f"内存 {pct}% — 偏高")
            elif pct >= 60:
                icon = self._get_colored_icon("idle_mid", ICO_MID)
                tip = tr_msg(f"内存 {pct}% — 偏高")
            else:
                icon = self._get_colored_icon("idle", ICO_IDLE)
                tip = tr_msg(f"内存 {pct}%")
        # 释放旧图标防止 GDI 泄漏（长期运行崩溃根因）
        # 仅成功创建时轮换：失败（None）时保留旧句柄继续复用，避免句柄被丢弃泄漏
        try:
            if pct_icon_handle:
                prev = getattr(self, '_prev_pct_icon', None)
                if prev:
                    ctypes.windll.user32.DestroyIcon(prev)
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
            um.AppendMenuW(hmenu, 0x00000000, ID_SHOW, tr("显示窗口"))
            um.AppendMenuW(hmenu, 0x00000800, 0, None)  # MF_SEPARATOR
            um.AppendMenuW(hmenu, 0x00000000, ID_EXIT, tr("退出"))
            # 获取鼠标位置
            pt = wt.POINT()
            um.GetCursorPos(ctypes.byref(pt))
            # 前置窗口（TrackPopupMenu 要求）
            um.SetForegroundWindow(hwnd)
            # 弹出菜单（阻塞直到选择或取消）
            try:
                cmd = um.TrackPopupMenu(hmenu, 0x0020 | 0x0002 | 0x0100, pt.x, pt.y, 0, hwnd, None)
            finally:
                # TPM_RETURNCMD=0x0100 | TPM_RIGHTBUTTON=0x0002 | TPM_TOPALIGN=0x0000
                um.DestroyMenu(hmenu)  # 异常路径也销毁，防句柄泄漏
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
        dlg.title(tr("游戏模式"))
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.focus_set()
        dlg.grab_set()
        dlg.configure(bg="#1c1c1c")
        _center_geometry(dlg, 400, 180)
        ttk.Label(dlg, text=tr_msg(f"确认{action}游戏模式？"), font=("微软雅黑", 11, "bold"),
                  background="#1c1c1c", foreground="#e0e0e0").pack(pady=(18, 2))
        desc1 = tr_msg("启用后将对游戏进程实施完全保护，" if game else "关闭后将恢复正常清理策略，")
        desc2 = tr_msg("非游戏进程将被持续清理以腾出内存。" if game else "游戏进程不再受额外保护。")
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
        ttk.Button(btn_frame, text=tr("确认"), command=on_yes).pack(side="left", padx=6)
        ttk.Button(btn_frame, text=tr("取消"), command=on_no).pack(side="left", padx=6)
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
        else:
            # 立即构建游戏 PID 保护集（等下一轮快照会有 ≤3s 无保护窗口期）
            try:
                snaps = self.sniffer.snapshot()
                self.cleaner.judger._game_pid_set = self.cleaner._build_game_pid_set(snaps)
            except Exception:
                pass
        _log_write("决策", f"游戏模式手动{'启用' if game else '关闭'}")
        if game:
            self._log("🎮 游戏模式已手动启用 · 游戏进程受保护")
        else:
            self._log("🎮 游戏模式已手动关闭 · 恢复正常清理")
            self.cleaner.judger._game_pid_set.clear()
    # ---- UI 构建 ----

    def _add_tip(self, w, txt):
        ToolTip(w, tr(txt))  # tooltip 统一翻译（原文即 key——未命中回退中文）

    def _hk_display(self, key="hotkey"):
        """热键配置 → 显示文案（如 ctrl+shift+m → Ctrl+Shift+M）"""
        spec = CFG.get(key, "ctrl+shift+m" if key == "hotkey" else "ctrl+shift+g")
        return "+".join(p.capitalize() for p in str(spec).split("+"))

    def _interval_display(self):
        """守护周期显示文案（配置驱动，默认 60）"""
        return int(CFG.get("interval", 60))

    def _build_ui(self):
        # 内存状态 (Canvas 彩色条)
        f = ttk.LabelFrame(self.root, text=tr("内存状态"), padding=8)
        f.pack(fill="x", padx=12, pady=(12,4))
        self.mem_canvas = tk.Canvas(f, height=22, bg="#eee", highlightthickness=0)
        self.mem_canvas.pack(fill="x", pady=(0,4))
        self.mem_bar_rect = self.mem_canvas.create_rectangle(0, 0, 0, 22, fill="#4caf50", width=0)
        self.mem_bar_text = self.mem_canvas.create_text(8, 11, anchor="w", text="--%", font=("Segoe UI", 9, "bold"), fill="#fff")
        self._add_tip(self.mem_canvas,
            "内存条颜色指示当前内存使用率：\n"
            "  · 绿色 — 低于60%\n"
            "  · 黄色 — 60~74%\n"
            "  · 橙色 — 75~89%\n"
            "  · 红色 — 高于90%\n"
            "长期处于紧张色说明物理内存不足\n"
            "建议关闭部分程序或考虑增加内存")
        info = ttk.Frame(f); info.pack(fill="x")
        self.lbl_total = ttk.Label(info, text=tr("总: ") + "-- GB"); self.lbl_total.pack(side="left", padx=(0,12))
        self.lbl_used = ttk.Label(info, text=tr("已用: ") + "-- GB"); self.lbl_used.pack(side="left", padx=(0,12))
        self.lbl_avail = ttk.Label(info, text=tr("可用: ") + "-- GB"); self.lbl_avail.pack(side="left", padx=(0,12))
        self.lbl_pct = ttk.Label(info, text="--%"); self.lbl_pct.pack(side="right")

        # 按钮
        bf = ttk.Frame(self.root); bf.pack(fill="x", padx=12, pady=6)
        self.btn_opt = ttk.Button(bf, text=tr("⚡ 优化"), command=self._on_optimize)
        self.btn_opt.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_opt,
            "按当前选择的清理模式立即执行一次内存优化\n"
            "游戏模式下游戏进程受完全保护，其余进程将由进程决策优化\n"
            "\n"
            "同时启动守护模式也会按当前的清理模式执行一次即时优化\n"
            "（若还同时处于游戏模式，会无视手动优化操作，避免影响流畅）")
        self.btn_dae = ttk.Button(bf, text=tr("⛨ 守护"), command=self._on_daemon)
        self.btn_dae.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_dae,
            "开启内存循环优化，约将每分钟整理一轮内存优化结果\n"
            "\n"
            "采用阶段性多次轻量压制与周期末全量收割：\n"
            "  · 轻量阶段 — 高频温和，以系统级清理为主\n"
            "  · 收割阶段 — 按选择的清理模式进行进程内存的释放\n"
            "\n"
            "开启后会自动规划清理策略，根据系统状态持续优化调整\n"
            "守护模式下有游戏自动检测，也可以手动开启游戏模式\n"
            "内置崩溃监测，程序因意外崩溃后会自动尝试恢复\n"
            "\n"
            "⚠ 缓存类清理需要管理员权限，否则无法生效\n"
            "⚠ 在full模式下会清理刚切走或正在工作的程序以最大释放")
        self.btn_stop = ttk.Button(bf, text=tr("▶ 停止"), command=self._stop_daemon, state="disabled")
        self.btn_stop.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_stop,
            "停止守护模式（若未开启点击无效）\n"
            "停止后已学习的数据会自动保存，持久提供参考，不会丢失")
        self.btn_excl = ttk.Button(bf, text=tr("⚙ 排除"), command=self._edit_exclusion_list)
        self.btn_excl.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_excl,
            "在这里管理不被任何形式清理的进程\n"
            "可输入进程名如 chrome.exe，不带.exe后缀会自动补全\n"
            "也可点击进程名后选择删除，回归可被优化的行列\n"
            "（若不清楚目标程序的程序名，可在进程排行列表中查找）\n"
            "\n"
            "添加后该进程将被完全跳过：\n"
            "  · 不释放其闲置内存\n"
            "  · 不设低内存优先级\n"
            "  · 不参与试探性清理\n"
            "适合添加：浏览器、开发工具、播放器\n"
            "\n"
            "⚠ 排除太多程序会明显降低释放效果\n"
            "⚠ 系统核心进程始终受自动保护，无论是否在排除列表中")
        self.btn_set = ttk.Button(bf, text=tr("☰ 设置"), command=self._open_settings)
        self.btn_set.pack(side="left")
        self._add_tip(self.btn_set,
            "打开设置面板进行配置调整\n"
            "\n"
            "可配置的内容：\n"
            "  语言 — 中英文界面即时切换\n"
            "  启动 — 开机自启、管理员权限启动、启动时自动守护、最小化到托盘、关闭行为\n"
            "  清理操作 — 6 种操作独立开关\n"
            "  触发与日志 — 紧急阈值、守护间隔、托盘行为、文件日志、清理深度\n"
            "  游戏模式 — 管理游戏进程名单\n"
            "  全局热键 — 优化/游戏模式快捷键设置")
        self.btn_log = ttk.Button(bf, text=tr("📜 学习日志"), command=self._show_learn_log)
        self.btn_log.pack(side="left", padx=(6,0))
        self._add_tip(self.btn_log,
            "查看每个进程的详细学习数据\n"
            "这些数据用于判断哪些进程值得优先清理\n"
            "\n"
            "各列含义：\n"
            "  · 样本 — 已观察到的数据量，越多判断越可靠\n"
            "  · α / β — 历史成功与失败的累计次数，决定可信度评分\n"
            "  · 可信度 — 越高越值得清理，综合了历史表现和预期收益\n"
            "  · 收益比 — 预期释放量(MB) vs 性能代价(PF)，性价比参考\n"
            "  · 偏差 — 内存用量的异常波动程度，越大越反常\n"
            "  · 趋势 — 内存增长斜率，正数表示内存在持续增长\n"
            "  · 泄漏 — 是否疑似内存泄漏（持续增长且清完很快回涨）\n"
            "  · 清理 — 累计被清理次数\n"
            "  · 试探成功 — 试探性清理的成功次数\n"
            "  · 试探失败 — 试探性清理的失败次数")

        # 状态文字单独放一行，避免按钮被挤出
        self.lbl_st = ttk.Label(bf, text=tr("就绪 · ") + self._hk_display())
        self.lbl_st.pack(side="bottom", fill="x")

        # 模式选择
        mf = ttk.Frame(self.root); mf.pack(fill="x", padx=12, pady=(0,6))
        ttk.Label(mf, text=tr("清理模式:")).pack(side="left")
        self.mode_var = tk.StringVar(value=CFG.get("clean_mode", "normal"))
        self.mode_combo = ttk.Combobox(mf, textvariable=self.mode_var, width=12,
                                        values=["quick","normal","deep","full"], state="readonly")
        self.mode_combo.bind("<MouseWheel>", lambda e: "break")  # 禁用滚轮：只接受点击选择，防误改
        self.mode_combo.pack(side="left", padx=(4,0))
        self._add_tip(self.mode_combo,
            "选择清理力度，优化按钮和守护模式共用此设置：\n"
            "\n"
            "  · quick — 仅系统级清理，几秒完成，几乎无感知\n"
            "                   适合：随手一点，不想有任何感知\n"
            "\n"
            "  · normal — 进程级 + 系统级清理，对日常使用影响较小\n"
            "                      适合：日常使用，兼顾效果与流畅\n"
            "\n"
            "  · deep — 追加系统级深度清扫与深层回收，清理更彻底\n"
            "                  适合：内存偏紧，接受短暂变慢\n"
            "\n"
            "  · full — 极限释放，尽最大可能腾出内存空间，包括刚切走或正在工作的程序内存\n"
            "               适合：内存告急，需要立刻腾出最多空间\n"
            "\n"
            "⚠ 切换后清理模式将在下一轮生效，无需重启")
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
        self.btn_game = ttk.Button(mf, text=tr("🎮 游戏模式"), command=self._on_toggle_game)
        self.btn_game.pack(side="left", padx=(6,0))
        self._add_tip(self.btn_game,
            "手动开启或关闭游戏模式\n"
            "\n"
            "开启后：\n"
            "  · 游戏进程受完全保护，不被触碰\n"
            "  · 非游戏进程被持续清理，为游戏腾出内存\n"
            "  · 跳过全系统缓存清理，避免拖慢磁盘\n"
            "  · 为游戏腾出更多可用内存\n"
            "\n"
            f"热键：{self._hk_display('game_hotkey')}（可在设置 → 全局热键中更改）\n"
            "⚠ 程序默认不识别任何游戏——需先在设置 → 游戏模式中添加进程名\n"
            "⚠ 按程序名自动识别运行中的实例，同名程序的所有实例都会被保护\n"
            "⚠ 常用辅助程序（语音、游戏平台）若受影响，可加入排除列表")
        self.btn_rank = ttk.Button(mf, text=tr("📊 进程排行"), command=self._show_process_rank)
        self.btn_rank.pack(side="left", padx=(6,0))
        self._add_tip(self.btn_rank,
            "查看当前所有进程包括内存占用在内的排行\n"
            "\n"
            "按内存占用从大到小排列，打开时即时采集\n"
            "快速定位哪些进程最占内存\n"
            "关闭窗口后重新打开可获取最新数据\n"
            "\n"
            "点击列标题可切换排序方式")
        ttk.Label(mf, text="  ").pack(side="left")

        # 统计
        sf = ttk.LabelFrame(self.root, text=tr("统计"), padding=8)
        sf.pack(fill="x", padx=12, pady=4)
        self.lbl_sb = ttk.Label(sf, text=tr("系统杂项: ") + "0"); self.lbl_sb.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_sb,
            "系统级清理操作的总次数\n"
            "\n"
            "包括待机缓存清空、脏页写回、文件缓存清除、卷缓存刷新、注册表缓存等\n"
            "\n"
            "⚠ 需要管理员权限才生效\n"
            "⚠ 清理后打开大文件可能短暂变慢")
        self.lbl_tr = ttk.Label(sf, text=tr("进程: ") + "0"); self.lbl_tr.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_tr,
            "进程闲置内存清理的总次数\n"
            "\n"
            "每成功清理一个进程计 1 次（含多轮深度清理）\n"
            "对确认值得清理的进程，程序会让系统优先回收其闲置页面\n"
            "\n"
            "⚠ 数字大不一定释放得多——多次清理小进程也会累加\n"
            "⚠ 参考释放量与图表趋势更有意义")
        self.lbl_fr = ttk.Label(sf, text=tr("释放: ") + "0 MB"); self.lbl_fr.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_fr,
            "所有轮次累计的内存释放总量\n"
            "\n"
            "包括进程闲置内存回收、系统缓存清理等所有操作释放的总和\n"
            "释放后可用内存会立即上涨，但系统很快会重新分配给活跃程序\n"
            "这是正常的内存管理行为，守护运行时若需准确参考可查看下方图表区域")
        self.lbl_lr = ttk.Label(sf, text=tr("已学习: ") + "0"); self.lbl_lr.pack(side="right")
        self._add_tip(self.lbl_lr,
            "已学习的进程数量\n"
            "\n"
            "程序持续观察每个进程的内存使用习惯\n"
            "包括变化趋势、波动幅度、填充速度等\n"
            "学习越久，后续的优化决策依据越充分\n"
            "超过 7 天无活动的进程会被自动清除")

        # 日志 — 上半文本 + 下半实时柱图
        lf = ttk.LabelFrame(self.root, text=tr("日志"), padding=4)
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
        win.title(tr("MemWise 设置"))
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
        # ─── 语言（独立栏目，置顶）───
        langf = ttk.LabelFrame(inner_frame, text=tr("语言"), padding=8)
        langf.pack(fill="x", padx=12, pady=(10,4))
        lang_row = ttk.Frame(langf); lang_row.pack(fill="x")
        ttk.Label(lang_row, text=tr("界面语言:")).pack(side="left")
        lang_var = tk.StringVar(value=LANGUAGES.get(CFG.get("language", "zh_CN"), LANGUAGES["zh_CN"]))  # 显示名（代码不在选项列表中会直接显示代码）
        lang_combo = ttk.Combobox(lang_row, textvariable=lang_var, state="readonly", width=16,
                                  values=list(LANGUAGES.values()))
        lang_combo.pack(side="left", padx=(6,0))
        lang_combo.bind("<MouseWheel>", lambda e: "break")  # 禁用滚轮防误改
        lang_combo.bind("<<ComboboxSelected>>", lambda e: self._switch_language(
            "zh_CN" if lang_var.get() == LANGUAGES["zh_CN"] else "en"))
        # tooltip 绑整行（悬浮"界面语言:"标签或下拉框都触发——Tk Enter/Leave 不冒泡，逐控件绑定）
        self._add_tip(lang_row,
            "选择界面语言，切换后立即生效（守护与统计数据不受影响）\n"
            "\n"
            "  · 简体中文 — 默认\n"
            "  · English — 全界面切换为英文\n"
            "\n"
            "⚠ 程序界面内语言可完全切换，但运行日志文件(memwise.log/memwise1.log)保留原始语言")
        for _c in lang_row.winfo_children():
            self._add_tip(_c, "选择界面语言，切换后立即生效（守护与统计数据不受影响）\n"
                          "\n"
                          "  · 简体中文 — 默认\n"
                          "  · English — 全界面切换为英文\n"
                          "\n"
                          "⚠ 程序界面内语言可完全切换，但运行日志文件(memwise.log/memwise1.log)保留原始语言")
        ttk.Label(langf, text=tr("（切换后立即生效）"), foreground="#888").pack(anchor="w", pady=(4,0))

        sf = ttk.LabelFrame(inner_frame, text=tr("启动"), padding=8)
        sf.pack(fill="x", padx=12, pady=(10,4))

        ast_var = tk.BooleanVar(value=CFG.get("auto_start", False))
        def on_autostart():
            en = ast_var.get()
            if getattr(sys, "frozen", False):
                target = sys.executable; args = ""; wd = os.path.dirname(sys.executable)
            else:
                pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                target = pythonw if os.path.isfile(pythonw) else sys.executable
                args = f'"{os.path.abspath(__file__)}"'; wd = base  # 引号：脚本路径含空格时快捷方式仍可解析
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
        ttk.Checkbutton(sf, text=tr("开机自启"), variable=ast_var,
                        command=on_autostart).pack(anchor="w")
        self._add_tip(sf.winfo_children()[-1],
            "开机时自动启动本程序\n"
            "\n"
            "路径为启动文件夹快捷方式\n"
            "  · 不修改注册表\n"
            "  · 普通用户权限启动，优化能力受限\n"
            "  · 如需管理员权限请勾下面的「管理员权限启动」\n"
            "\n"
            "⚠ 取消勾选后会自动删除启动文件夹快捷方式残留")

        asa_var = tk.BooleanVar(value=CFG.get("auto_start_admin", False))
        def on_autostart_admin():
            en = asa_var.get()
            if getattr(sys, "frozen", False):
                target = sys.executable; args = ""; wd = os.path.dirname(sys.executable)
            else:
                pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                target = pythonw if os.path.isfile(pythonw) else sys.executable
                args = f'"{os.path.abspath(__file__)}"'; wd = base  # 引号：脚本路径含空格时快捷方式仍可解析
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
        ttk.Checkbutton(sf, text=tr("管理员权限启动"), variable=asa_var,
                        command=on_autostart_admin).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1],
            "以管理员权限开机自启动\n"
            "\n"
            "通过 Windows 计划任务实现\n"
            "系统缓存类清理需要管理员权限\n"
            "以最高权限启动后受限的功能可完整执行\n"
            "\n"
            "⚠ 需先以管理员身份运行过一次本程序才能启用\n"
            "⚠ 启用后会替换普通开机自启，二者无法同时启用")

        asd_var = tk.BooleanVar(value=CFG.get("auto_start_daemon", False))
        def on_auto_daemon():
            CFG["auto_start_daemon"] = asd_var.get()
            _save_cfg()
        ttk.Checkbutton(sf, text=tr("启动时自动开启守护"), variable=asd_var,
                        command=on_auto_daemon).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1],
            "程序启动后立即自动进入守护模式\n"
            "\n"
            "无需手动点击守护按钮，程序一打开就在后台运行\n"
            "约每分钟输出一轮优化结果，同时持续自动调整优化策略\n"
            "配合「启动后最小化到托盘」使用效果更佳")

        asm_var = tk.BooleanVar(value=CFG.get("auto_start_minimize", False))
        def on_minimize():
            CFG["auto_start_minimize"] = asm_var.get()
            _save_cfg()
        ttk.Checkbutton(sf, text=tr("启动后最小化到托盘"), variable=asm_var,
                        command=on_minimize).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1], "程序启动后自动最小化到系统托盘\n\n主窗口不显示，只在托盘区域显示图标\n双击托盘图标恢复窗口，右键弹出菜单\n适合搭配「启动时自动守护」使用，实现开机静默运行")

        ca_lbl = ttk.Label(sf, text=tr("关闭按钮行为："))
        ca_lbl.pack(anchor="w", pady=(8,0))
        self._add_tip(ca_lbl, "点击窗口关闭按钮时的行为：\n  · 最小化到托盘 — 隐藏到托盘继续守护\n  · 直接退出程序 — 退出并自动保存状态\n  · 每次询问 — 弹窗选择（默认）")
        self._close_var = tk.StringVar(value=CFG.get("close_action","ask"))
        def set_ca(v):
            global CFG
            CFG["close_action"]=v
            _save_cfg()
        tips_ca = {"minimize":"点击关闭按钮后程序隐藏到系统托盘\n守护模式继续运行，双击托盘图标可恢复窗口",
                   "exit":"点击关闭按钮后程序完全退出，守护模式停止\n所有状态自动保存",
                   "ask":"点击关闭按钮后弹窗询问\n可选择最小化或退出（默认行为）"}
        for v, lbl in [("minimize", tr("\u6700\u5c0f\u5316\u5230\u6258\u76d8")), ("exit", tr("\u76f4\u63a5\u9000\u51fa\u7a0b\u5e8f")), ("ask", tr("\u6bcf\u6b21\u8be2\u95ee"))]:
            rb = ttk.Radiobutton(sf, text=lbl, variable=self._close_var, value=v, command=lambda x=v: set_ca(x))
            rb.pack(anchor="w")
            if v in tips_ca:
                self._add_tip(rb, tips_ca[v])

        # ─── 清理设置 ───
        cf = ttk.LabelFrame(inner_frame, text=tr("清理"), padding=8)
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
        cb_ews = ttk.Checkbutton(ops_frame, text=tr("释放进程闲置内存"), variable=ws_var,
                                  command=lambda: toggle_op("ws", ws_var))
        cb_ews.pack(anchor="w")
        self._add_tip(cb_ews, "释放各个进程当前未使用的闲置内存\n"
                      "内存压力较大时也会清理前台进程\n"
                      "\n"
                      "⚠ 切回被清理的后台程序时可能多几百毫秒加载\n"
                      "⚠ 系统会自动按需调回，程序可正常继续使用")
        cb_sb = ttk.Checkbutton(ops_frame, text=tr("待机缓存清理"), variable=sb_var,
                                command=lambda: toggle_op("standby", sb_var))
        cb_sb.pack(anchor="w")
        self._add_tip(cb_sb, "清空系统已缓存但暂未使用的内存页\n"
                      "是优化操作释放量的主要来源之一\n"
                      "\n"
                      "⚠ 需要管理员权限，否则无法正常生效\n"
                      "⚠ 清理后首次打开大文件可能短暂变慢")
        cb_mp = ttk.Checkbutton(ops_frame, text=tr("脏页写回"), variable=mp_var,
                                command=lambda: toggle_op("modified", mp_var))
        cb_mp.pack(anchor="w")
        self._add_tip(cb_mp, "将已修改但未保存的缓存页写回磁盘后释放\n"
                      "写回后页面变为干净页，系统可回收重用\n"
                      "每次系统级清理均执行，不受压力阈值限制\n"
                      "\n"
                      "⚠ 少量磁盘写入，对固态硬盘几乎无影响")
        cb_fc = ttk.Checkbutton(ops_frame, text=tr("系统文件缓存"), variable=fc_var,
                                command=lambda: toggle_op("filecache", fc_var))
        cb_fc.pack(anchor="w")
        self._add_tip(cb_fc, "清空系统文件读取缓存\n"
                      "会降低文件操作速度直到缓存重建\n"
                      "在指定的收割阶段执行\n"
                      "\n"
                      "⚠ 谨慎使用——文件缓存重建期间磁盘性能下降")
        cb_vc = ttk.Checkbutton(ops_frame, text=tr("卷缓存刷新"), variable=vl_var,
                                command=lambda: toggle_op("volume", vl_var))
        cb_vc.pack(anchor="w")
        self._add_tip(cb_vc, "刷新各磁盘分区的写入缓存，释放占用的内存\n"
                      "写入缓存是系统暂存磁盘写入的区域\n"
                      "刷新后相应内存可被系统回收重用\n"
                      "\n"
                      "⚠ 需要管理员权限，否则无法正常生效\n"
                      "⚠ 每次刷新所有分区会短暂耗时但不丢失数据")
        cb_rg = ttk.Checkbutton(ops_frame, text=tr("注册表缓存清理"), variable=rg_var,
                                command=lambda: toggle_op("registry", rg_var))
        cb_rg.pack(anchor="w")
        self._add_tip(cb_rg, "清空系统注册表的读写缓存\n"
                      "无磁盘读写操作，不中断正在运行的程序\n"
                      "守护模式下始终执行，取消勾选后完全跳过")
        # ─── 游戏模式 ───
        gmf = ttk.LabelFrame(inner_frame, text=tr("游戏模式"), padding=8)
        gmf.pack(fill="x", padx=12, pady=4)
        gmf_btns = ttk.Frame(gmf); gmf_btns.pack(fill="x")
        manage_btn = ttk.Button(gmf_btns, text=tr("管理游戏进程"), command=self._manage_game_procs)
        manage_btn.pack(side="left", padx=(0,6))
        self._add_tip(manage_btn,
            "管理游戏模式监测的游戏进程名\n"
            "\n"
            "可配置的内容：\n"
            "  · 查看 — 列出全部已配置游戏进程名\n"
            "  · 添加 — 单独输入或逗号分隔批量输入，如 xxx,xxxx\n"
            "  · 删除 — 选中后删除，写错/误加/不想要随时移除\n"
            "\n"
            "不带.exe后缀自动补全，守护模式检测到后自动开启游戏保护\n"
            "\n"
            "⚠ 同名程序的所有实例都会被识别")
        ttk.Label(ops_frame, text=tr("（未勾选 = 不执行对应系统清理）"),
                  foreground="#888").pack(anchor="w")

        # ─── 紧急触发阈值 & 托盘行为 & 日志 ───
        ef2 = ttk.LabelFrame(inner_frame, text=tr("触发与日志"), padding=8)


        ef2.pack(fill="x", padx=12, pady=4)
        def set_emerg(v):
            global CFG
            CFG["emergency_threshold"] = int(float(v))
            _save_cfg()
        em_val = tk.IntVar(value=CFG.get("emergency_threshold", 80))
        em_lbl = ttk.Label(ef2, text=tr("紧急触发阈值: ") + f"{em_val.get()}%", foreground="#555")
        self._add_tip(em_lbl, "内存使用率达到此百分比时，跳过等待立即执行全量优化\n范围 50-99%，默认 80%\n降低可更及时响应，提高阈值可减少清理频率")
        em_lbl.pack(anchor="w")
        em_sl = ttk.Scale(ef2, from_=50, to=99, variable=em_val, orient="horizontal",
                         command=lambda v: em_lbl.config(text=tr("紧急触发阈值: ") + f"{int(float(v))}%"))
        em_sl.bind("<ButtonRelease-1>", lambda e: set_emerg(em_val.get()))  # 拖动仅更新显示，松开才保存（防高频写盘）
        em_sl.pack(fill="x", pady=(0,6))
        ta_lbl = ttk.Label(ef2, text=tr("托盘左键行为："))
        ta_lbl.pack(anchor="w")
        # 索引映射（2026-08-14 审查：显示名翻译后反查中文键在英文界面恒失败回退 show——
        # 保存/初始值一律按索引取，语言无关）
        map_vals = [("显示窗口","show"),("一键清理","clean"),("无操作","none")]
        ta_combo = ttk.Combobox(ef2, values=[tr(k) for k,_ in map_vals], state="readonly", width=20)
        ta_combo.bind("<MouseWheel>", lambda e: "break")  # 禁用滚轮：只接受点击选择，防误改
        ta_cur = CFG.get("tray_left_action","show")
        ta_idx = next((i for i,(_,v) in enumerate(map_vals) if v == ta_cur), 0)
        ta_combo.current(ta_idx)
        ta_combo.pack(fill="x", pady=(0,6))
        self._add_tip(ta_combo, "托盘左键单击行为：\n  · 显示窗口 — 恢复主界面（默认）\n  · 一键清理 — 立即执行优化\n  · 无操作 — 忽略点击\n\n⚠ 仅在窗口隐藏时生效，任务栏存在图标（窗口显示）时锁定")
        def set_tray_act(e):
            global CFG
            idx = ta_combo.current()
            CFG["tray_left_action"] = map_vals[idx][1] if 0 <= idx < len(map_vals) else "show"
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
        lg_cb = ttk.Checkbutton(ef2, text=tr("记录运行日志到文件"),
                                variable=lg_var, command=set_log)
        lg_cb.pack(anchor="w")
        self._add_tip(lg_cb, "开启后，运行期间的全部信息写入日志文件（memwise.log/memwise1.log）：\n"
                      "每轮清理摘要、界面日志消息、启动/退出、异常、调参、游戏模式切换等\n"
                      "日志自动轮转保留最近两份，无需手动清理")
        passes_val = tk.IntVar(value=CFG.get("clean_passes", 4))
        def set_passes(v):
            global CFG
            CFG["clean_passes"] = int(float(v))
            _save_cfg()
        ps_lbl = ttk.Label(ef2, text=tr("进程清理深度: ") + f"{passes_val.get()} " + tr("轮"), foreground="#555")
        ps_lbl.pack(anchor="w", pady=(6,0))
        self._add_tip(ps_lbl, "每个进程反复清理的轮数（2~6，默认 4）\n越高释放越彻底，但耗时越长\n欲降低本程序性能占用建议 2~3\n对于更彻底的优化需求可设 5~6")
        ps_sl = ttk.Scale(ef2, from_=2, to=6, variable=passes_val, orient="horizontal",
                         command=lambda v: ps_lbl.config(text=tr("进程清理深度: ") + f"{int(float(v))} " + tr("轮")))
        ps_sl.bind("<ButtonRelease-1>", lambda e: set_passes(passes_val.get()))
        ps_sl.pack(fill="x", pady=(0,6))

        gap_val = tk.IntVar(value=CFG.get("gap_seconds", 12))
        def set_gap(v):
            global CFG
            CFG["gap_seconds"] = int(float(v))
            _save_cfg()
        gp_lbl = ttk.Label(ef2, text=tr("守护清理间隔: ") + f"{gap_val.get()} " + tr("秒"), foreground="#555")
        gp_lbl.pack(anchor="w", pady=(6,0))
        self._add_tip(gp_lbl, "守护模式每轮周期内的轻量阶段频率（8~20 秒，默认 12）\n"
                         "用于控制周期内清理操作的密集程度\n"
                         "间隔越短，同周期内清理次数越多，释放效果越彻底\n"
                         "但对性能的消耗也越高\n"
                         "欲降低本程序性能占用建议 15~20\n"
                         "对于更彻底的优化需求可设 8~10")
        gp_sl = ttk.Scale(ef2, from_=8, to=20, variable=gap_val, orient="horizontal",
                         command=lambda v: gp_lbl.config(text=tr("守护清理间隔: ") + f"{int(float(v))} " + tr("秒")))
        gp_sl.bind("<ButtonRelease-1>", lambda e: set_gap(gap_val.get()))
        gp_sl.pack(fill="x", pady=(0,6))

        # ─── 全局热键（独立栏，汇总所有热键） ───
        hkf = ttk.LabelFrame(inner_frame, text=tr("全局热键"), padding=8)
        hkf.pack(fill="x", padx=12, pady=4)
        ttk.Label(hkf, text=tr("格式：修饰键+按键\n如 ctrl+shift+m / alt+f1 / shift+f5"),
                  foreground="#888").pack(anchor="w")
        for hk in HOTKEYS:
            row = ttk.Frame(hkf); row.pack(fill="x", pady=(4,0))
            ttk.Label(row, text=f"{tr(hk['name'])}：", width=12).pack(side="left")
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
                        st.config(text=tr_msg(f"与「{hk2['name']}」冲突"))
                        return
                CFG[hk["key"]] = spec
                _save_cfg()
                st.config(text=tr("已生效"))
                self._apply_hotkeys()
            e.bind("<FocusOut>", commit)
            e.bind("<Return>", commit)
            tip = (f"{hk['name']}全局快捷键\n\n"
                   f"按此组合：{'立即执行一次优化' if hk['action'] == 'hotkey' else '切换游戏模式（含确认弹窗）'}\n"
                   f"格式：修饰键+按键，如 {hk['default']}\n\n"
                   "⚠ 至少包含一个修饰键（ctrl/alt/shift）\n"
                   "⚠ 不能与其他热键相同\n"
                   "⚠ 输入后点击其他位置或按回车生效，被占用时会提示")
            # 整行覆盖（Tk Enter/Leave 不冒泡——标签+输入框各自绑定，悬浮任何位置都触发）
            self._add_tip(row, tip)
            for _c in row.winfo_children():
                self._add_tip(_c, tip)

        # 关闭按钮行为：设置即时保存，无需独立保存按钮（save_and_close 已移除）
        win.deiconify()  # 全部控件就绪，居中后一次显示

    def _switch_language(self, lang):
        """语言即时切换：保存配置 → 设置字典 → 重建 UI 层。
        daemon 线程/统计/图表数据全在实例属性——重建不动；消息队列重建后继续消费零丢失；
        失败回退原界面（try/except 全包裹）"""
        try:
            if lang == get_language():
                return
            CFG["language"] = lang
            _save_cfg()
            set_language(lang)
            # Tk 内置消息框按钮语言（是/否/确定/取消）跟随语言（msgcat locale）
            try:
                self.root.tk.call("::msgcat::mclocale", "en_US" if lang == "en" else "zh_CN")
            except Exception:
                pass
            # 关闭所有弹窗（设置/排除/排行等——旧语言界面）
            for w in list(self.root.winfo_children()):
                if isinstance(w, tk.Toplevel):
                    try: w.destroy()
                    except Exception: pass
            # 重建主窗口控件树（旧 after 链自动失效——destroy 后回调访问新控件树安全）
            for child in list(self.root.winfo_children()):
                try: child.destroy()
                except Exception: pass
            self._build_ui()
            self._refresh_mem()          # 重启 2s 刷新链（新控件树）
            self._upd_stats()
            self._rerender_log()         # 历史日志按新语言重渲染（原文缓存）
            if self.engine.daemon_running:
                self.btn_dae.configure(state="disabled"); self.btn_stop.configure(state="normal")
                self.lbl_st["text"] = tr("守护运行中")
            self._update_tray_status(getattr(self, '_mem_pct', 0) or 50)  # 托盘 tip 即时刷新
            self._log_op(tr("语言已切换"))
        except Exception as e:
            import sys; print(f"[MemWise] 语言切换异常: {e}", file=_ERR)
            try:
                self._log_op(tr("语言切换失败，已保留原界面"))
            except Exception:
                pass

    def _edit_exclusion_list(self):
        win = tk.Toplevel(self.root)
        win.withdraw()  # 先隐藏，构建完成居中后一次显示
        self._apply_icon(win)
        win.title(tr("进程排除列表"))
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
                    messagebox.showwarning(tr("已存在"), tr_msg(f"「{nm}」已在排除列表中"), parent=win)
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
        ttk.Button(bf, text=tr("+ 添加"), command=add_excl).pack(side="left", padx=(0,6))
        ttk.Button(bf, text=tr("− 删除"), command=remove_excl).pack(side="left")

        def close_excl():
            CFG["never"] = list(never)
            _save_cfg()
            win.destroy()
        ttk.Button(win, text=tr("关闭"), command=close_excl).pack(pady=8)
        win.deiconify()  # 全部控件就绪，居中后一次显示

    def _show_learn_log(self):
        info_data = []
        # dict() 拷贝在 GIL 下原子完成：守护线程可能随时增键，直接迭代 items() 会 RuntimeError
        for name, p in sorted(dict(self.learner.profiles).items()):
            if p.total_samples < 2:
                continue
            info_data.append((name, p.alpha, p.beta, p.total_samples,
                              f"{p.thompson_theta:.2f}", f"{p.roi:.1f}",
                              f"{p.z_score:.1f}", f"{p.slope:.0f}",
                              tr("是") if p.leak_suspect else tr("否"),
                              p.clean_count, p.probe_ok, p.probe_fail))
        if not info_data:
            messagebox.showinfo(tr("学习日志"), tr("还没有学习到任何数据，先运行一会儿优化再来看"), parent=self.root)
            return
        win = tk.Toplevel(self.root)
        win.withdraw()  # 先隐藏，构建完成居中后一次显示
        self._apply_icon(win)
        win.title(tr_msg(f"学习日志 — {len(info_data)} 个进程"))
        win.transient(self.root)
        win.focus_set()
        win.lift()
        _center_geometry(win, 1000, 650)
        cols = (tr("进程"), "α", "β", tr("样本"), tr("可信度"), tr("收益比(MB/PF)"), tr("偏差"), tr("趋势"), tr("泄漏"), tr("清理"), tr("试探成功"), tr("试探失败"))
        tree = ttk.Treeview(win, columns=cols, show="headings", height=20)
        # 列配置按索引（不依赖显示名——语言切换后列名变化，按中文名判断会失效）
        for i, c in enumerate(cols):
            tree.heading(c, text=c)
            if i == 0:
                tree.column(c, width=200, anchor="w")  # 进程列靠左
            elif i in (1, 2, 3, 9, 10, 11):           # α/β/样本/清理/试探成功/试探失败
                tree.column(c, width=65, anchor="center")
            elif i in (4, 5, 6, 7):                    # 可信度/收益比/偏差/趋势
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
        """一体化游戏进程管理：列出/添加/删除游戏进程条目"""
        win = tk.Toplevel(self.root)
        win.withdraw()  # 先隐藏，构建完成居中后一次显示
        self._apply_icon(win)
        win.title(tr("游戏进程管理"))
        win.resizable(True, True)
        win.transient(self.root)
        win.focus_set()
        win.lift()
        _center_geometry(win, 460, 480)

        games = [g for g in (CFG.get("game_processes", []) or [])]

        # ── 游戏进程列表 ──
        ttk.Label(win, text=tr("游戏进程（可添加/删除）：")).pack(anchor="w", padx=12, pady=(12,2))
        listf = ttk.Frame(win); listf.pack(fill="both", expand=True, padx=12)
        lb = tk.Listbox(listf, width=46, height=8, font=("Microsoft YaHei", 10),
                        selectbackground="#419EF3", activestyle="none")
        scroll = ttk.Scrollbar(listf, orient="vertical", command=lb.yview)
        lb.configure(yscrollcommand=scroll.set)
        lb.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        for g in games:
            lb.insert("end", g)
        if not games:
            ttk.Label(win, text=tr("尚未配置游戏进程——添加进程名后，游戏模式才会自动识别并保护"),
                      foreground="#888").pack(anchor="w", padx=12)

        # ── 添加区 ──
        addf = ttk.Frame(win); addf.pack(fill="x", padx=12, pady=(6,0))
        ttk.Label(addf, text=tr("逗号分隔，不带后缀自动补全")).pack(anchor="w")
        row = ttk.Frame(win); row.pack(fill="x", padx=12, pady=(2,6))
        entry = ttk.Entry(row, width=22)
        entry.pack(side="left")

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
                messagebox.showwarning(tr("已存在"), tr_msg(f"以下进程已在名单中：\n{', '.join(dup)}"), parent=win)
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
            info.config(text=tr_msg(f"已配置 {len(lb.get(0, 'end'))} 款游戏进程"))
        ttk.Button(row, text=tr("添加"), command=add).pack(side="left", padx=(6,0))
        entry.bind("<Return>", lambda e: add())
        entry.focus_set()

        # ── 删除区 ──
        delf = ttk.Frame(win); delf.pack(fill="x", padx=12, pady=(0,4))
        def remove():
            sel = lb.curselection()
            if not sel:
                return
            name = lb.get(sel[0])
            if not messagebox.askyesno(tr("删除游戏进程"),
                    tr_msg(f"确定移除「{name}」吗？"), parent=win):
                return
            lb.delete(sel[0])
            cur = CFG.get("game_processes", []) or []
            CFG["game_processes"] = [g for g in cur if g.lower() != name.lower()]
            _save_cfg()
            # 同步 judger 运行时名单
            self.judger.cfg["game_processes"] = list(CFG["game_processes"])
            info.config(text=tr_msg(f"已配置 {len(lb.get(0, 'end'))} 款游戏进程"))
        ttk.Button(delf, text=tr("删除选中"), command=remove).pack(side="left")

        # ── 配置状态展示 ──
        info = ttk.Label(win, text=tr_msg(f"已配置 {len(games)} 款游戏进程"),
                         foreground="#888")
        info.pack(anchor="w", padx=12, pady=(4,2))
        win.deiconify()  # 全部控件就绪，居中后一次显示

    def _show_process_rank(self):
        """弹出进程内存占用排行榜"""
        win = tk.Toplevel(self.root)
        win.withdraw()  # 先隐藏，构建完成居中后一次显示
        self._apply_icon(win)
        win.title(tr("进程内存排行"))
        win.resizable(True, True)
        win.transient(self.root)
        win.focus_set()
        win.lift()
        _center_geometry(win, 900, 650)

        cols = (tr("进程"), tr("进程号"), tr("内存占用"), tr("CPU占用"), tr("学习"))
        tree = ttk.Treeview(win, columns=cols, show="headings", height=25)
        # 列配置按索引（不依赖显示名——语言切换后列名变化，按中文名判断会全部失效）
        for i, c in enumerate(cols):
            tree.heading(c, text=c, command=lambda _c=c: _sort_tree(_c))
            if i == 0:
                tree.column(c, width=250, anchor="w")      # 进程名列：靠左
            else:
                tree.column(c, width=[70, 120, 70, 60][i - 1], anchor="center")  # 其余列居中

        vsb = ttk.Scrollbar(win, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(12,0), pady=(12,4))
        vsb.pack(side="right", fill="y", pady=(12,4))

        # 排序状态变量（默认按内存降序；列索引——2026-08-14 审查：语言切换后列名变化，
        # 按显示名 set 会 TclError（英文界面每 3s 一次），索引语言无关）
        _sort_col_idx = 2  # 0=进程 1=进程号 2=内存占用 3=CPU占用 4=学习
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
            nonlocal _sort_col_idx, _sort_rev
            idx = cols.index(col) if col in cols else 2  # 点击传当前语言列名 → 索引
            if _sort_col_idx == idx:
                _sort_rev = not _sort_rev
            else:
                _sort_col_idx = idx
                _sort_rev = True
            items = [(tree.set(k, cols[_sort_col_idx]), k) for k in tree.get_children("")]
            items.sort(key=lambda x: _sort_key_c(x[0]), reverse=_sort_rev)
            for i2, (_, k) in enumerate(items):
                tree.move(k, "", i2)

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
            # 保护系统进程、自身与核心保护名单（svchost/explorer/dwm 等同样禁止终止，防误杀系统进程）
            if pid <= 4 or pid == os.getpid() or _is_system_core(name):
                messagebox.showwarning(tr("禁止终止"), tr("不能终止系统进程或自身"), parent=win)
                return
            ok = messagebox.askyesno(tr("终止进程"),
                tr_msg(f"确定要终止「{name}」(PID={pid}) 吗？\n\n该操作会强制结束进程，未保存的数据可能丢失。"),
                icon="warning", parent=win)
            if ok:
                if winapi.terminate_process(pid):
                    messagebox.showinfo(tr("已完成"), tr_msg(f"进程「{name}」已终止"), parent=win)
                    _refresh()
                else:
                    messagebox.showerror(tr("失败"), tr_msg(f"无法终止进程「{name}」\n可能权限不足或进程已退出"), parent=win)

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
                # 应用用户选择的排序（列索引，语言无关）
                if _sort_col_idx is not None:
                    items = [(tree.set(k, cols[_sort_col_idx]), k) for k in tree.get_children("")]
                    items.sort(key=lambda x: _sort_key_c(x[0]), reverse=_sort_rev)
                    for i2, (_, k) in enumerate(items):
                        tree.move(k, "", i2)
            except Exception as e:
                import sys; print(f"[MemWise] _refresh data error: {e}", file=_ERR)
            win.after(3000, _refresh)
            win.after(10, _restore_hover)

        _refresh()
        win.deiconify()  # 全部控件就绪，居中后一次显示


    # ---- 日志 / 状态 ----

    def _log_op(self, m):
        # 显示层翻译（tr_msg）；原文入历史缓存（切换语言时重渲染）；日志文件保留原文（诊断一致性）
        self._log_history.append(m)
        self.log.configure(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {tr_msg(m)}\n"); self.log.see("end")
        self.log.configure(state="disabled")
        if CFG.get("log_to_file"):
            _log_write("界面", m)

    def _log_batch(self, msgs, to_file=True):
        """周期末批量输出：当前行数+批量>7则清旧，再逐条输出。
        to_file=False 为纯显示模式（周期摘要/EFIS 消息已有 [清理]/[调参] 直写，避免双通道重复落盘）"""
        for m in msgs:
            self._log_history.append(m)
        self.log.configure(state="normal")
        try:
            cur_lines = int(self.log.index('end-1c').split('.')[0])
        except Exception:
            cur_lines = 0
        if cur_lines + len(msgs) > 7:
            self.log.delete("1.0", "end")
        for m in msgs:
            self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {tr_msg(m)}\n")
        self.log.see("end")
        self.log.configure(state="disabled")
        if to_file and CFG.get("log_to_file"):
            for m in msgs:
                _log_write("界面", m)

    def _log(self, m):
        """实时日志：>7行则清旧再输出"""
        self._log_history.append(m)
        self.log.configure(state="normal")
        try:
            cur_lines = int(self.log.index('end-1c').split('.')[0])
        except Exception:
            cur_lines = 0
        if cur_lines > 7:
            self.log.delete("1.0", "end")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {tr_msg(m)}\n"); self.log.see("end")
        self.log.configure(state="disabled")
        if CFG.get("log_to_file"):
            _log_write("界面", m)

    def _rerender_log(self):
        """语言切换后按新语言重渲染日志面板——只重渲染切换前可见的行数
        （与 _log/_log_batch 的清旧口径一致，避免把全部历史缓存倾倒出来）"""
        try:
            try:
                cur_lines = int(self.log.index('end-1c').split('.')[0])
            except Exception:
                cur_lines = 0
            if cur_lines <= 0:
                return
            msgs = list(self._log_history)[-cur_lines:]
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            for m in msgs:
                self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {tr_msg(m)}\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        except Exception:
            pass

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
        self.lbl_lr.config(text=tr("已学习: ") + str(len(self.learner.profiles)))

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
                        self.lbl_total["text"] = tr("总: ") + f"{m['total']/(1<<30):.1f}G"
                        self.lbl_used["text"] = tr("已用: ") + f"{m['used']/(1<<30):.1f}G"
                        self.lbl_avail["text"] = tr("可用: ") + f"{m['avail']/(1<<30):.1f}G"
                        self.lbl_pct["text"] = f"{pct}%"
                except Exception as e:
                    import sys; print(f"[MemWise] _refresh_mem UI异常: {e}", file=_ERR)
        finally:
            self.root.after(2000, self._refresh_mem)

    def _upd_stats(self):
        s = self.cleaner.summary()
        self.lbl_sb["text"] = tr("系统杂项: ") + fmt_count(s['standby'] + s.get('modified',0) + s.get('filecache',0) + s.get('registry',0) + s.get('volume',0))
        self.lbl_tr["text"] = tr("进程: ") + fmt_count(s['ws_trim'])
        fm = s['freed_mb']
        self.lbl_fr["text"] = tr("释放: ") + (f"{fm/1024.0:.1f}GB" if fm >= 1000 else f"{fm:.1f}MB")
        self._upd_learned()

    # ---- 柱图 ----

    def _draw_chart_placeholder(self):
        """显示占位文本（无数据时）"""
        c = self.chart_canvas
        c.delete("all")
        cw = c.winfo_width() or 400
        c.create_text(cw//2, 70, text=tr("启动守护模式后显示实时优化图表"),
                      fill="#888", font=("微软雅黑", 10))



    BAR_W = 14   # 每柱宽度 px
    BAR_GAP = 3  # 柱间距 px

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
        c.delete("all")  # 先清空画布：防占位文字残留与重复绘制污染（解耦批次误删，2026-08-14 修复）
        data, meta_list, eff_data_view, eff_factors_view = self.engine.chart_snapshot()
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
        failed_weight = getattr(self.engine, "_failed_weight", 0.5)
        # 当前显示使用最新 eff/factors（供悬浮提示与底部指标）
        eff_list = list(eff_data_view)
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
        eff_data = list(eff_data_view)
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
        factors_all = list(eff_factors_view)
        f_visible = factors_all[-len(visible):] if len(factors_all) > len(visible) else factors_all
        n_f = min(len(f_visible), len(visible))
        self._chart_motion_factors = f_visible[-n_f:] if n_f else []
        # 收割标记也对齐到可见柱（与 visible 等长，供悬浮提示如实标注）
        partial_all = [m[5] if len(m) > 5 else False for m in meta_list]
        p_all = partial_all[-len(visible):] if len(partial_all) > len(visible) else partial_all
        self._chart_motion_partial = list(p_all)
        self._chart_motion_px0 = px0
        self._chart_motion_step = step
        self._chart_motion_bar_w = self.BAR_W
        # 坐标轴
        c.create_line(px0, py0, px0, py1, fill="#666")
        c.create_line(px0, py1, px1, py1, fill="#666")
        # 标题 — 居中在顶部黑色区域，不与图表重叠
        c.create_text(px0 + pw//2, 10, text=tr("本次优化 ") + fmt_label(latest),
                      anchor="center", fill="#ccc", font=("微软雅黑", 9))
        # 底部三指标
        metrics_y = ch - 6
        avg_eff = sum(eff_data) / len(eff_data) if eff_data else 50
        avg_eff_text = f"{avg_eff:.0f}%"
        c.create_text(px0 + pw//2, metrics_y,
                      text=tr("平均 ") + fmt_label(avg_val) + tr("    最高 ") + fmt_label(peak_val) + tr("    平均效率 ") + avg_eff_text,
                      anchor="s", fill="#aaa", font=("Consolas", 8))
        # 单一 Motion 绑定（替代多柱 Enter/Leave，消除事件竞争）
        c.tag_unbind("all", "<Enter>")
        c.tag_unbind("all", "<Leave>")
        c.bind("<Motion>", self._chart_on_motion)
        c.bind("<Leave>", self._chart_hide_tip)

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
        text_full = tr_msg(f"释放 {fmt_label(freed_mb)}\n效率 {eff_pct:.0f}%{factor_str}{partial_note}")
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
        if self.engine.daemon_running:
            # 守护运行中：按当前选择的清理模式执行一次即时优化（与守护周期经 exec_lock 串行）
            if self.cleaner.game_mode:
                self._log("游戏进行中，跳过手动清理以保障流畅")
                return
            self.engine.optimize_manual_once(CFG.get("clean_mode", "normal"),
                                             CFG.get("clean_operations"))
            return
        self._optimizing = True
        self.btn_opt.configure(state="disabled"); self.lbl_st["text"] = tr("优化中...")
        self._log_op(tr("开始优化..."))
        self.engine.optimize_manual_async(CFG.get("clean_mode", "normal"),
                                          CFG.get("clean_operations"))

    def _opt_done(self, result):
        s = self.cleaner.summary()
        trimmed = [t for t in result.get("layer2", []) if t[1]]
        for snap, ok, freed, reason in trimmed[:10]:
            self._log(f"  ✓ {snap.name} (PID={snap.pid}) {freed/(1<<20):.0f}MB — {reason}")
        # 统计栏始终显示程序运行以来累计总量
        winapi.report_event("MemWise", f"GUI 优化: {s['freed_mb']}MB 释放, {len(trimmed)} 进程")
        self._upd_stats()
        if self.engine.daemon_running:
            # 守护运行中的即时优化：按钮/状态栏由守护周期维护，只更新统计与日志
            return
        self._optimizing = False
        self.btn_opt.configure(state="normal")
        self.lbl_st["text"] = tr("就绪 · ") + self._hk_display()

    # ---- 守护 ----

    def _on_daemon(self):
        if self.engine.daemon_running: return
        if self._optimizing:
            self._log_op("手动优化进行中，请等待完成后再启动守护")
            return
        if not self.engine.start_daemon():  # 含防双守护与周期基线/图表/ERIS 状态重置
            self._log_op("上一守护线程仍在收尾，请稍候再试")
            return
        self.btn_dae.configure(state="disabled"); self.btn_stop.configure(state="normal")
        self.lbl_st["text"] = tr("守护运行中"); self._log_op(tr("守护模式启动"))
        _update_watchdog_daemon(True)  # 崩溃恢复时据此续守护

    def _upd_dae_ui(self, s, m, txt="🟢 守护中"):
        self.lbl_sb["text"] = tr("系统杂项: ") + fmt_count(s['standby'] + s.get('modified',0) + s.get('filecache',0) + s.get('registry',0) + s.get('volume',0))
        self.lbl_tr["text"] = tr("进程: ") + fmt_count(s['ws_trim'])
        fm = s['freed_mb']
        self.lbl_fr["text"] = tr("释放: ") + (f"{fm/1024.0:.1f}GB" if fm >= 1000 else f"{fm:.1f}MB")
        self._upd_learned()  # 守护中持续学习新进程，已学习数随周期刷新
        pct = m["pct"]
        icon = "🟢" if pct < 70 else ("🟡" if pct < 90 else "🔴")
        self.lbl_st["text"] = f"{icon} {tr(txt)} {pct}%"

    def _stop_daemon(self):
        if not self.engine.daemon_running: return
        self._log_op("停止守护中..."); self.engine.stop_daemon()

    def _dae_stopped(self):
        _update_watchdog_daemon(False)  # 守护已停止：崩溃恢复不应续守护
        self.btn_dae.configure(state="normal"); self.btn_stop.configure(state="disabled")
        err = getattr(self.engine, '_dae_error', None)
        if err:
            self.lbl_st["text"] = "⚠ 守护异常"
            self._log_op(tr("❌ 守护异常，详见下方错误信息"))
            self._log(f"🔍 {err}")
            del self.engine._dae_error
        else:
            self.lbl_st["text"] = tr("就绪 · ") + self._hk_display(); self._log_op(tr("守护已停止"))
        self.engine.save_state(); self._upd_stats(); self.root.after(100, self._draw_chart)

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
        tk.Label(choice, text=tr("点击关闭按钮后的操作："), font=("微软雅黑", 11)).pack(pady=(20, 15))
        result = ["minimize"]
        def pick_minimize():
            result[0] = "minimize"; choice.destroy()
        def pick_exit():
            result[0] = "exit"; choice.destroy()
        bf = ttk.Frame(choice)
        bf.pack(pady=5)
        ttk.Button(bf, text=tr("最小化到托盘"), width=20, command=pick_minimize).pack(side="left", padx=10)
        ttk.Button(bf, text=tr("退出程序"), width=20, command=pick_exit).pack(side="left", padx=10)
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
            if read_watchdog_daemon():
                self._on_daemon()
                self._log_op("🔄 从崩溃中恢复 — 守护模式已自动继续")
        except Exception:
            pass

    def _do_exit(self):
        """直接退出（无确认）"""
        _log_write("系统", "程序退出")
        # 通知看门狗正常退出
        remove_watchdog()
        try: winapi.tray_remove(self.root.winfo_id(), TRAY_UID)
        except Exception:
            pass
        # 引擎收尾：停止守护 + cleaner/harvest 池 + 状态落盘（learner + ERIS）
        self.engine.shutdown()
        _save_cfg()
        self.engine.save_state()
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
