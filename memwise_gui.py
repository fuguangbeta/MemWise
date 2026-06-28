"""
MemWise v1.4 GUI —— 图形界面
系统托盘 + 全局热键 + 颜色状态 + 排除列表编辑 + 设置面板
"""

import os, sys, time, threading, tkinter as tk, math, queue
from collections import deque
from tkinter import ttk, simpledialog, messagebox
import ctypes
import ctypes.wintypes as w

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

from core.config import load as _load_cfg
from core.config import get_state_path
import core.config as _config

def _save_cfg():
    _config.save(CFG)

STATE_FILE = get_state_path()
CFG = _load_cfg()

# 托盘和热键常量
HOTKEY_ID = 9001
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

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_void_p, w.HANDLE, w.UINT, ctypes.c_void_p, ctypes.c_void_p)

@WNDPROC
def _wnd_proc(hwnd, msg, wp, lp):
    global _gui_ref
    if msg == winapi.WM_TRAYICON and _gui_ref:
        if lp == 0x205:  # WM_RBUTTONUP → 右键菜单
            _gui_ref._show_tray_menu()
        elif lp in (0x202, 0x203):  # WM_LBUTTONUP / DBLCLK
            _gui_ref._show_window()
        return 0
    if msg == WM_HOTKEY and wp == HOTKEY_ID and _gui_ref:
        _gui_ref._on_hotkey()
        return 0
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


class MemWiseGUI:
    def __init__(self):
        global _gui_ref
        _gui_ref = self

        self.root = tk.Tk()
        self.root.title("MemWise v1.4")
        # --minimized 模式：立即隐藏窗口，不等 800ms，避免开机闪烁
        if "--minimized" in sys.argv:
            self.root.withdraw()
            self._minimized_to_tray = True
        self.root.geometry("1060x700")
        self.root.resizable(True, False)
        self.root.update_idletasks()
        cx = (self.root.winfo_screenwidth() - 1060) // 2
        cy = (self.root.winfo_screenheight() - 700) // 2
        self.root.geometry(f"1060x700+{cx}+{cy}")

        # 窗口图标 — 用 MemWise 自定义 HICON（直接内存创建，不走 .ico 文件）
        # 托盘已用 create_memwise_icon() 验证可行，此处直接发 WM_SETICON
        try:
            # 生成大图标(32x32)给任务栏，小图标(16x16)给标题栏
            big_h = winapi.create_memwise_icon(32)
            sml_h = winapi.create_memwise_icon(16)
            # 通过 tkinter 内部句柄获取顶级窗口 HWND
            hwnd = None
            try:
                hwnd = ctypes.windll.user32.GetAncestor(
                    ctypes.windll.user32.GetParent(self.root.winfo_id()), 2)
            except Exception:
                pass
            if not hwnd:
                hwnd = self.root.winfo_id()
            if big_h:
                ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 1, big_h)  # WM_SETICON ICON_BIG
            if sml_h:
                ctypes.windll.user32.SendMessageW(hwnd, 0x0080, 0, sml_h)  # WM_SETICON ICON_SMALL
        except Exception:
            pass

        self._custom_hicon = None
        self._icon_cache = {}  # name -> HICON
        self._optimizing = False  # 防止并发优化

        self.learner = Learner.load(STATE_FILE)
        jcfg = {"kp":CFG.get("kp",0.6),"ki":CFG.get("ki",0.15),"kd":CFG.get("kd",0.1),
                "target_usage":CFG.get("target_usage",60),"never":CFG.get("never",[])}
        self.judger = Judger(self.learner, jcfg)
        self.cleaner = Cleaner(self.judger)
        self.efis = EfisController(STATE_FILE)
        self.sniffer = Sniffer()
        self.daemon_running = False; self.daemon_thread = None
        self._tray_icon_handle = None
        self._minimized_to_tray = False
        # 柱图状态
        self._chart_data = deque(maxlen=60)
        self._chart_last_freed = 0.0
        self._prev_trim_count = 0
        self._prev_fail_count = 0
        self._mem_pct_for_chart = 0
        self._new_cycle_event = threading.Event()
        self._msg_queue = queue.Queue()  # 线程安全消息队列
        self._mem_pct = 0
        self._eff_data = deque(maxlen=60)  # 效率折线数据
        self._chart_lock = threading.Lock()
        self._eris_sub = {"total": 50}  # 初始效率值（首个chart点用）

        self._build_ui()
        self._refresh_mem()
        self._setup_hotkey_and_tray()
        # 启动消息队列轮询（每 100ms 检查一次，主线程安全）
        self._poll_msg_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if CFG.get("auto_start_daemon"):
            if "--minimized" in sys.argv:
                self._on_daemon()  # 自启动：立即守护，不等待
            else:
                self.root.after(300, self._on_daemon)

    # ---- 窗口过程 + 热键 + 托盘 ----

    def _get_colored_icon(self, name, color):
        """缓存获取或创建指定颜色的 HICON"""
        if name not in self._icon_cache:
            self._icon_cache[name] = winapi.create_memwise_icon(32, color)
        return self._icon_cache[name]

    def _setup_hotkey_and_tray(self):
        global _orig_wndproc
        hwnd = int(self.root.winfo_id())
        # 子类化窗口过程
        _orig_wndproc = winapi.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(_wnd_proc, ctypes.c_void_p))
        # 注册热键 Ctrl+Shift+M
        winapi.register_hotkey(hwnd, HOTKEY_ID, winapi.MOD_CONTROL | winapi.MOD_SHIFT | winapi.MOD_NOREPEAT, ord('M'))
        hIcon = self._get_colored_icon("idle", ICO_IDLE)
        self._tray_icon_handle = hIcon
        ok = winapi.tray_add(hwnd, TRAY_UID, hIcon, "MemWise — 智能内存看护")
        if not ok:
            self._log("⚠ 托盘图标添加失败，重试...")
            import time; time.sleep(0.5)
            ok = winapi.tray_add(hwnd, TRAY_UID, hIcon, "MemWise — 智能内存看护")

    def _update_tray_status(self, pct):
        """根据内存使用率和守护状态更新托盘图标颜色（4档匹配内存条）"""
        if self.daemon_running:
            if pct >= 90:
                icon = self._get_colored_icon("high", ICO_HIGH)
                tip = f"🔴 守护中 {pct}% — 内存紧张"
            elif pct >= 75:
                icon = self._get_colored_icon("mid2", ICO_ORANGE)
                tip = f"🟠 守护中 {pct}% — 内存偏高"
            elif pct >= 60:
                icon = self._get_colored_icon("mid", ICO_MID)
                tip = f"🟡 守护中 {pct}% — 内存偏高"
            else:
                icon = self._get_colored_icon("low", ICO_LOW)
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
        self._tray_icon_handle = icon
        winapi.tray_modify(self.root.winfo_id(), TRAY_UID, icon, f"MemWise — {tip}")

    def _show_tray_menu(self):
        """右键托盘菜单 — 弹出操作菜单"""
        if not self.root.winfo_exists():
            return
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="显示窗口", command=self._show_window)
        menu.add_separator()
        menu.add_command(label="退出", command=self._do_exit)
        try:
            x, y = self.root.winfo_pointerxy()
        except Exception:
            x = y = 0
        menu.post(x, y)
        self.root.after(200, lambda: menu.focus_set() if menu.winfo_exists() else None)

    def _minimize_to_tray(self):
        self.root.withdraw()
        self._minimized_to_tray = True

    def _show_window(self):
        self.root.deiconify()
        self.root.lift()
        self._minimized_to_tray = False

    def _on_hotkey(self):
        """Ctrl+Shift+M → 执行一键优化"""
        self._show_window()
        self._on_optimize()

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
            "  • 绿(<60%) 空闲·健康\n"
            "  • 黄(60~74%) 注意·可考虑清理\n"
            "  • 橙(75~89%) 偏高·建议清理\n"
            "  • 红(≥90%) 紧张·内存不够用了\n"
            "\n"
            "如果一直红色说明物理内存不足，考虑加内存条或关掉一些程序。\n"
            "守护模式下蓝色(空闲·无压力)表示内存低于55%无需操作。")
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
            "⚡ 一键释放内存（3轮深度清理）\n"
            "\n"
            "跑3轮：首轮按当前模式，后两轮深度模式补刀，合计释放量。\n"
            "\n"
            "  • 7种系统缓存清理(Standby/Modified/FileCache/Volume/压缩等)\n"
            "  • 进程EmptyWorkingSet释放闲置页+Thompson评分排序\n"
            "  • 预判式清理(增长进程优先)+探索冲动(冷门进程再评估)\n"
            "\n"
            "⚠ 缓存清理需管理员权限\n"
            "⚠ deep/full清standby后打开大文件可能慢几秒")
        self.btn_dae = ttk.Button(bf, text="▶ 守护", command=self._on_daemon)
        self.btn_dae.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_dae,
            "▶ 后台守护模式（10~60s自适应循环）\n"
            "\n"
            "PID目标45% → Thompson评分 → EFIS自动调参，全自动运行。\n"
            "\n"
            "学习系统：\n"
            "  • Thompson α/β贝叶斯更新 + 上下文5维修正 + 双EWMA \n"
            "  • 预判清理(增长进程优先) + 探索奖励(>10min触发) \n"
            "  • 泄漏检测双阈值 + Beta时间遗忘(>1h无反馈遗忘)\n"
            "\n"
            "EFIS自动调参(每30tick)：\n"
            "  • 实验日志+回滚(效果差自动恢复)\n"
            "  • 场景参数记忆(游戏/开发/浏览/通用互不干扰)\n"
            "  • 窗口化评估(内存波动>8%跳过混杂因素)\n"
            "\n"
            "游戏模式：自动检测70+游戏+全屏检测\n"
            "  后台进程θ门槛降至0.15激进清理，游戏本身更强保护\n"
            "\n"
            "⚠ 缓存清理需管理员权限\n"
            "⚠ 进程级EmptyWorkingSet和内存优先级不受管理员限制")
        self.btn_stop = ttk.Button(bf, text="■ 停止", command=self._stop_daemon, state="disabled")
        self.btn_stop.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_stop,
            "■ 停止后台自动清理\n"
            "\n"
            "停止守护模式后，已采集的学习数据(Thompson画像/refill_ewma/清理历史)\n"
            "会自动保存到 memwise_state.json，下次启动接着用，不会丢失。\n"
            "守护期间累积的统计(清理次数/释放量)会保留在界面上。")
        self.btn_excl = ttk.Button(bf, text="⚙ 排除", command=self._edit_exclusion_list)
        self.btn_excl.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_excl,
            "⚙ 进程排除列表\n"
            "\n"
            "在这里添加不想被清理的程序(输入进程名如 chrome.exe)。\n"
            "添加后该进程将被跳过：\n"
            "  · 不做EmptyWorkingSet\n"
            "  · 不设低内存优先级/EcoQoS\n"
            "  · 不参与Probe试探\n"
            "\n"
            "适合添加：正在用的浏览器、开发工具、IDE、播放器\n"
            "\n"
            "⚠ 注意：排除太多程序会明显降低释放效果\n"
            "⚠ 排除不影响安全白名单(系统进程自动保护)")
        self.btn_set = ttk.Button(bf, text="☰ 设置", command=self._open_settings)
        self.btn_set.pack(side="left")
        self._add_tip(self.btn_set,
            "☰ 打开详细设置面板\n"
            "\n"
            "设置项包括：\n"
            "  启动：开机自启(普通快捷方式) / 管理员权限启动(Scheduled Task)\n"
            "        / 启动时自动守护 / 启动后最小化到托盘\n"
            "  清理：单独开关每种操作——\n"
            "    · EmptyWorkingSet(进程闲置页释放)\n"
            "    · Standby List清理(系统缓存)\n"
            "    · Modified Page写回(脏页刷盘)\n"
            "    · 内存压缩触发(紧缩压缩存储)\n"
            "    · 系统文件缓存(谨慎使用)\n"
            "\n"
            "清理模式在主界面下拉框切换(quick/normal/deep/full)\n"
            "留空=按模式自动选择操作")
        self.btn_log = ttk.Button(bf, text="学习日志", command=self._show_learn_log)
        self.btn_log.pack(side="left", padx=(6,0))
        self._add_tip(self.btn_log,
            "📊 查看每个进程的详细学习数据\n"
            "\n"
            "核心指标：\n"
            "  · θ (Thompson评分 0~1) — 越高越值得清理\n"
            "     上下文增强Thompson：Beta×σ(w·f)，5维特征评分\n"
            "  · α/β — Beta分布参数，控制探索vs利用平衡\n"
            "  · ROI — 收益EWMA/成本EWMA，预期性价比\n"
            "  · z-score — 工作集标准差偏离，>3.0为异常\n"
            "  · 趋势斜率 — 30点最小二乘回归，正数=内存增长\n"
            "  · 泄漏嫌疑 — 持续2倍增长超过5个采样点\n"
            "  · refill_ewma — WS再填充速率，影响冷却和双次间隔\n"
            "  · 清理历史 — clean_count/probe_ok/probe_fail\n"
            "\n"
            "这些数据帮您判断哪些进程值得清理、哪些清完很快又涨回来")

        # 状态文字单独放一行，避免按钮被挤出
        self.lbl_st = ttk.Label(bf, text="就绪 · Ctrl+Shift+M")
        self.lbl_st.pack(side="bottom", fill="x")

        # 模式选择
        mf = ttk.Frame(self.root); mf.pack(fill="x", padx=12, pady=(0,6))
        ttk.Label(mf, text="清理模式:").pack(side="left")
        self.mode_var = tk.StringVar(value=CFG.get("clean_mode", "normal"))
        self.mode_combo = ttk.Combobox(mf, textvariable=self.mode_var, width=12,
                                        values=["quick","normal","deep","full"], state="readonly")
        self.mode_combo.pack(side="left", padx=(4,0))
        self._add_tip(self.mode_combo,
            "选不同的清理力度，守护和优化按钮共用此设置：\n"
            "\n"
            "  quick(快速) — L1系统级封顶30% + 进程EmptyWorkingSet\n"
            "    适合：只是想快速释放一点，不想有卡顿感\n"
            "\n"
            "  normal(标准) — L1含压缩+Modified写回 + 进程清理\n"
            "    适合：日常使用，兼顾效果和流畅度\n"
            "\n"
            "  deep(深度) — L1开满 + 进程清理 + Layer3深度重复\n"
            "    适合：内存偏紧时需要多释放一些\n"
            "\n"
            "  full(全量) — L1全开 + 进程+standby+压缩+多轮深度\n"
            "    适合：内存严重不足时最大释放\n"
            "\n"
            
            "默认清理操作(7种)：\n"
            "· ws EmptyWorkingSet\n"
            "· standby Standby缓存\n"
            "· modified 脏页写回\n"
            "· compress 内存压缩\n"
            "· filecache 文件缓存\n"
            "· volume 卷缓存\n"
            "· registry 注册表缓存\n"
            "\n"
            "⚠ deep/full会清Standby缓存，打开大文件可能慢几秒\n"
            "⚠ 模式切换后守护模式即时生效，无需重启")
        self.btn_rank = ttk.Button(mf, text="进程排行", command=self._show_process_rank)
        self.btn_rank.pack(side="left", padx=(6,0))
        self._add_tip(self.btn_rank,
            "📊 查看当前所有进程的内存占用排行\n"
            "\n"
            "按内存占用从大到小排列：\n"
            "  · 实时刷新当前快照数据\n"
            "  · 快速定位哪些进程最占内存\n"
            "\n"
            "点击标题列可切换排序方式")
        ttk.Label(mf, text="  ").pack(side="left")

        # 统计
        sf = ttk.LabelFrame(self.root, text="统计", padding=8)
        sf.pack(fill="x", padx=12, pady=4)
        self.lbl_sb = ttk.Label(sf, text="Standby: 0"); self.lbl_sb.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_sb,
            "系统缓存清理总次数(7种操作)\n"
            "\n"
            "包括：Standby清空/低优先Standby/Modified Page写回/内存压缩触发\n"
            "文件缓存清除/卷缓存刷新/注册表缓存(Win8.1+)\n"
            "渐进式压缩(三步异步链)会计入压缩和Standby\n"
            "\n"
            "⚠ 需要管理员权限才生效\n"
            "⚠ 清理后打开大文件可能慢一会儿(缓存重建)")
        self.lbl_tr = ttk.Label(sf, text="进程: 0"); self.lbl_tr.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_tr,
            "进程EmptyWorkingSet清理总次数\n"
            "\n"
            "每对一个进程做一次双次清理(含自适应间隔)计1次\n"
            "清理前还会对该进程设内存优先级+EcoQoS\n"
            "\n"
            "⚠ 数字大不一定释放得多——多次清小进程也会计数\n"
            "⚠ 参考释放量(MB)更有意义")
        self.lbl_fr = ttk.Label(sf, text="释放: 0 MB"); self.lbl_fr.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_fr,
            "累计释放内存总量(MB)\n"
            "\n"
            "包括所有清理操作释放的内存：\n"
            "  · 进程EmptyWorkingSet + 内存优先级/EcoQoS回收\n"
            "  · Standby/Modified Page/文件缓存清理\n"
            "  · 内存压缩+渐进式压缩(三步异步链)\n"
            "\n"
            "释放后可用内存会立即上涨，但系统很快会重新分配\n"
            "给活跃程序使用，这是正常的内存管理行为\n"
            "参考柱状图可看到每次清理的实时释放量")
        self.lbl_lr = ttk.Label(sf, text="已学习: 0"); self.lbl_lr.pack(side="right")
        self._add_tip(self.lbl_lr,
            "已学习的进程画像数\n"
            "\n"
            "程序持续观察每个进程的内存使用习惯：\n"
            "  · EWMA基线(Z-score)/波动率/趋势斜率\n"
            "  · refill_ewma再填充速率\n"
            "  · 上下文增强Thompson(5维特征评分)\n"
            "\n"
            "样本越多，θ评分越准确。\n"
            "超过30天无活跃+样本<10的低价值画像自动清理\n"
            "防止state.json无限膨胀")

        # 日志 — 上半文本 + 下半实时柱图
        lf = ttk.LabelFrame(self.root, text="日志", padding=4)
        lf.pack(fill="both", expand=True, padx=12, pady=(4,12))

        # 下半：柱图 Canvas（守护模式下显示实时优化柱图）
        self.chart_canvas = tk.Canvas(lf, height=200, bg="#1e1e1e", highlightthickness=0)
        self.chart_canvas.pack(side="bottom", fill="x")
        self.chart_canvas.bind("<Configure>", lambda e: self._draw_chart())
        # 占位
        self._draw_chart_placeholder()

        # 上半：文本日志
        self.log = tk.Text(lf, height=8, font=("Consolas",9), state="disabled", bg="#f5f5f5")
        sc = ttk.Scrollbar(lf, command=self.log.yview); self.log.configure(yscrollcommand=sc.set)
        sc.pack(side="right", fill="y"); self.log.pack(fill="both", expand=True)

        self._upd_learned()

    # ---- 设置对话框 ----

    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("MemWise 设置")
        win.geometry("520x500")
        win.resizable(False, False)
        win.transient(self.root)
        win.focus_set()
        win.lift()
        win.update_idletasks()
        cx = self.root.winfo_x() + (self.root.winfo_width() - 520) // 2
        cy = self.root.winfo_y() + (self.root.winfo_height() - 500) // 2
        win.geometry(f"520x500+{cx}+{cy}")

        # ─── 启动设置 ───
        sf = ttk.LabelFrame(win, text="启动", padding=8)
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
                winapi.set_auto_start("MemWise", target, args + " --minimized" if args else "--minimized", wd)
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
                ok = winapi.set_auto_start_admin("MemWise", target, args + " --minimized" if args else "--minimized")
                if ok:
                    winapi.remove_auto_start("MemWise")
                    ast_var.set(True)
                    CFG["auto_start"] = True
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
            "通过Windows计划任务以最高权限(管理员)开机启动\n"
            "\n"
            "优势：\n"
            "  · 系统缓存清理(Standby/文件缓存)需要管理员权限\n"
            "  · 以最高权限启动后，所有清理操作都能完整执行\n"
            "\n"
            "前提：\n"
            "  · 需先以管理员身份运行一次本程序\n"
            "  · 非管理员时设置会失败\n"
            "\n"
            "⚠ 启用后会替换普通开机自启(二选一)")

        asd_var = tk.BooleanVar(value=CFG.get("auto_start_daemon", False))
        def on_auto_daemon():
            CFG["auto_start_daemon"] = asd_var.get()
            _save_cfg()
        ttk.Checkbutton(sf, text="启动时自动开启守护", variable=asd_var,
                        command=on_auto_daemon).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1],
            "程序启动后立即自动进入守护模式\n"
            "\n"
            "无需手动点击「守护」按钮，程序一打开就在后台运行。\n"
            "每30秒自动检查内存，按当前模式执行分层清理。\n"
            "配合「启动后最小化到托盘」使用效果更佳。")

        asm_var = tk.BooleanVar(value=CFG.get("auto_start_minimize", False))
        def on_minimize():
            CFG["auto_start_minimize"] = asm_var.get()
            _save_cfg()
        ttk.Checkbutton(sf, text="启动后最小化到托盘", variable=asm_var,
                        command=on_minimize).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1],
            "程序启动后自动最小化到系统托盘\n"
            "\n"
            "窗口不显示，只在托盘区域显示图标。\n"
            "双击托盘图标恢复窗口，右键弹出菜单。\n"
            "适合搭配「启动时自动守护」使用，实现开机静默运行。")

        # ─── 清理设置 ───
        cf = ttk.LabelFrame(win, text="清理", padding=8)
        cf.pack(fill="x", padx=12, pady=8)

        def toggle_op(op_name, var):
            if var.get():
                CFG.setdefault("clean_operations", [])
                if op_name not in CFG["clean_operations"]:
                    CFG["clean_operations"].append(op_name)
            else:
                if CFG.get("clean_operations"):
                    CFG["clean_operations"] = [o for o in CFG["clean_operations"] if o != op_name]

        ops = CFG.get("clean_operations", []) or []
        ws_var = tk.BooleanVar(value=not ops or "ws" in ops)
        sb_var = tk.BooleanVar(value=not ops or "standby" in ops)
        mp_var = tk.BooleanVar(value="modified" in ops)
        fc_var = tk.BooleanVar(value="filecache" in ops)
        vl_var = tk.BooleanVar(value="volume" in ops)
        cp_var = tk.BooleanVar(value="compress" in ops or not ops)

        ops_frame = ttk.Frame(cf); ops_frame.pack(fill="x")
        cb_ews = ttk.Checkbutton(ops_frame, text="EmptyWorkingSet", variable=ws_var,
                                  command=lambda: toggle_op("ws", ws_var))
        cb_ews.pack(anchor="w")
        self._add_tip(cb_ews, "对非前台、非排除的进程调用 EmptyWorkingSet，释放闲置物理页到 pagefile。\n"
                      "前台进程和排除列表中的不会被清理。\n"
                      "清理前还会对该进程设内存优先级+EcoQoS（仅守护模式下）。\n"
                      "\n"
                      "⚠ 切回被清理的后台程序时可能多几百毫秒加载（页面从 pagefile 调回）\n"
                      "⚠ 但系统按需自动调回，不影响程序正常运行")
        cb_sb = ttk.Checkbutton(ops_frame, text="Standby List 清理", variable=sb_var,
                                command=lambda: toggle_op("standby", sb_var))
        cb_sb.pack(anchor="w")
        self._add_tip(cb_sb, "清空系统的 Standby 缓存页(Windows 缓存的最近读取数据)，释放大量内存。\n"
                      "低优先 Standby 清理+渐进式压缩链，比单次多释放 5~10%。\n"
                      "\n"
                      "⚠ 需要管理员权限\n"
                      "⚠ 清理后首次打开大文件可能慢一会儿(缓存重建)")
        cb_mp = ttk.Checkbutton(ops_frame, text="Modified Page 写回", variable=mp_var,
                                command=lambda: toggle_op("modified", mp_var))
        cb_mp.pack(anchor="w")
        self._add_tip(cb_mp, "将已修改的脏页写回磁盘，释放其占用的物理内存。\n"
                      "写回后页面变为干净页，系统可回收重用。\n"
                      "memory pressure > 0.1 即触发，阈值较低更积极。\n"
                      "\n"
                      "⚠ 少量磁盘写入，对 SSD 几乎无影响")
        cb_cp = ttk.Checkbutton(ops_frame, text="内存压缩触发", variable=cp_var,
                                command=lambda: toggle_op("compress", cp_var))
        cb_cp.pack(anchor="w")
        self._add_tip(cb_cp, "主动触发 Windows 内置内存压缩，将已压缩的存储页进一步紧缩。\n"
                      "多轮渐进式压缩(三步异步链)，比单次多释放更多压缩页。\n"
                      "纯操作系统级操作，零副作用。\n"
                      "memory pressure > 0.05 即触发\n"
                      "\n"
                      "⚠ 不增加 CPU 负担，Windows 自动管理解压时机")
        cb_fc = ttk.Checkbutton(ops_frame, text="系统文件缓存", variable=fc_var,
                                command=lambda: toggle_op("filecache", fc_var))
        cb_fc.pack(anchor="w")
        self._add_tip(cb_fc, "清空系统文件缓存（SetSystemFileCacheSize）。\n"
                      "会降低文件操作速度直到缓存重建。\n"
                      "memory pressure > 0.25 触发，仅在真正需要时开启。\n"
                      "\n"
                      "⚠ 谨慎使用——文件缓存重建期间磁盘性能下降\n"
                      "⚠ 适合内存严重不足(>85%)且刚用完大文件的场景")
        cb_vc = ttk.Checkbutton(ops_frame, text="卷缓存刷新", variable=vl_var,
                                command=lambda: toggle_op("volume", vl_var))
        cb_vc.pack(anchor="w")
        self._add_tip(cb_vc, "刷新各卷(如C:、D:)的写入缓存缓冲区，释放被占用的物理内存页。\n"
                      "通过 CreateFileW+FlushFileBuffers 实现。\n"
                      "\n"
                      "⚠ 每次刷新所有NTFS卷，约耗时50~200ms\n"
                      "⚠ 磁盘繁忙时可能稍慢，但不丢失数据")
        ttk.Label(ops_frame, text="（留空 = 按模式自动选择）",
                  foreground="#888").pack(anchor="w")

        def save_and_close():
            CFG["clean_mode"] = self.mode_var.get()
            _save_cfg()
            win.destroy()

    def _edit_exclusion_list(self):
        win = tk.Toplevel(self.root)
        win.title("进程排除列表")
        win.geometry("460x460")
        win.resizable(False, False)
        win.transient(self.root)
        win.focus_set()
        win.lift()
        win.update_idletasks()
        cx = self.root.winfo_x() + (self.root.winfo_width() - 460) // 2
        cy = self.root.winfo_y() + (self.root.winfo_height() - 460) // 2
        win.geometry(f"460x460+{cx}+{cy}")

        lb = tk.Listbox(win, width=40, height=12)
        lb.pack(fill="both", expand=True, padx=12, pady=(12,4))
        never = CFG.get("never", []) or []
        for n in never: lb.insert("end", n)

        def add_excl():
            name = simpledialog.askstring("添加排除", "输入进程名 (如 chrome.exe):", parent=win)
            if name:
                lb.insert("end", name)
                if name not in never: never.append(name)
        def remove_excl():
            sel = lb.curselection()
            if sel:
                name = lb.get(sel[0])
                lb.delete(sel[0])
                if name in never: never.remove(name)

        bf = ttk.Frame(win); bf.pack(fill="x", padx=12, pady=4)
        ttk.Button(bf, text="+ 添加", command=add_excl).pack(side="left", padx=(0,6))
        ttk.Button(bf, text="− 删除", command=remove_excl).pack(side="left")

        def save_and_close():
            CFG["never"] = never
            _save_cfg()
            win.destroy()
        ttk.Button(win, text="关闭", command=save_and_close).pack(pady=8)

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
        win.title(f"学习日志 — {len(info_data)} 个进程")
        win.geometry("1000x650")
        win.transient(self.root)
        win.focus_set()
        win.lift()
        win.update_idletasks()
        cx = self.root.winfo_x() + (self.root.winfo_width() - 1000) // 2
        cy = self.root.winfo_y() + (self.root.winfo_height() - 650) // 2
        win.geometry(f"1000x650+{cx}+{cy}")
        cols = ("进程", "α", "β", "样本", "可信度", "收益比", "偏差", "趋势", "泄漏", "清理", "试探OK", "试探失败")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=20)
        for c in cols:
            tree.heading(c, text=c)
            if c in ("进程",):
                tree.column(c, width=200)
            elif c in ("α","β","样本","清理","试探OK","试探失败"):
                tree.column(c, width=65, anchor="center")
            elif c in ("可信度","收益比","偏差","趋势"):
                tree.column(c, width=75, anchor="center")
            else:
                tree.column(c, width=70, anchor="center")
        vsb = ttk.Scrollbar(win, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(12,0), pady=(12,4))
        vsb.pack(side="right", fill="y", pady=(12,4))
        for row in info_data:
            tree.insert("", "end", values=row)


    # ---- 进程内存排行 ----

    def _show_process_rank(self):
        """弹出进程内存占用排行榜"""
        win = tk.Toplevel(self.root)
        win.title("进程内存排行")
        win.geometry("900x650")
        win.resizable(True, True)
        win.transient(self.root)
        win.focus_set()
        win.lift()
        win.update_idletasks()
        cx = (win.winfo_screenwidth() - 900) // 2
        cy = (win.winfo_screenheight() - 650) // 2
        win.geometry(f"900x650+{cx}+{cy}")

        cols = ("进程", "PID", "内存", "CPU", "学习")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=25)
        for c in cols:
            tree.heading(c, text=c, command=lambda _c=c: _sort_tree(_c))
            if c in ("进程",):
                tree.column(c, width=250)
            elif c == "PID":
                tree.column(c, width=70, anchor="center")
            elif c == "CPU":
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
        _sort_col = "内存"
        _sort_rev = True

        def _sort_key_c(v):
            """排序键提取：支持 "X MB" 格式转数字"""
            v = v.strip()
            if v.endswith(" MB"):
                v = v[:-3]
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

        tree.bind("<<TreeviewSelect>>", _on_item_click)

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
                import sys; print(f"[MemWise] _refresh sniffer error: {e}", file=sys.stderr)
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
                import sys; print(f"[MemWise] _refresh data error: {e}", file=sys.stderr)
            win.after(3000, _refresh)
            win.after(10, _restore_hover)

        _refresh()


    # ---- 日志 / 状态 ----

    def _log_should_clear(self, extra_lines=1):
        """判断继续输出是否会溢出日志界面"""
        try:
            line_count = int(self.log.index('end-1c').split('.')[0])
            if line_count <= 1:
                return False
            dli = self.log.dlineinfo("1.0")
            if dli:
                line_height = dli[3]
            else:
                import tkinter.font as tkfont
                f = tkfont.Font(font=self.log['font'])
                line_height = f.metrics('linespace')
            visible_height = self.log.winfo_height()
            visible_lines = max(3, visible_height // line_height)
            return line_count + extra_lines > visible_lines
        except Exception:
            return False

    def _clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _log_op(self, m):
        self._new_cycle_event.clear()
        self.log.configure(state="normal")
        if self._log_should_clear():
            self.log.delete("1.0", "end")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {m}\n"); self.log.see("end")
        self.log.configure(state="disabled")

    def _log(self, m):
        self.log.configure(state="normal")
        if self._new_cycle_event.is_set():
            if self._log_should_clear():
                self.log.delete("1.0", "end")
            self._new_cycle_event.clear()
        elif self._log_should_clear():
            self.log.delete("1.0", "end")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {m}\n"); self.log.see("end")
        self.log.configure(state="disabled")

    def _poll_msg_queue(self):
        try:
            while True:
                action, args = self._msg_queue.get_nowait()
                if action == 'log': self._log(args)
                elif action == 'log_op': self._log_op(args)
                elif action == 'efis': self._log('[EFIS] ' + args)
                elif action == 'chart': self._draw_chart()
                elif action == 'upd_ui': self._upd_dae_ui(*args)
                elif action == 'opt_done': self._opt_done(args)
                elif action == 'dae_stopped': self._dae_stopped()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_msg_queue)

    def _upd_learned(self):
        self.lbl_lr.config(text=f"已学习: {len(self.learner.profiles)}")

    def _refresh_mem(self):
        m = winapi.get_memory_status()
        if m:
            pct = m["pct"]
            # 更新彩色条
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
            self._mem_pct = pct
            self._update_tray_status(pct)
        self.root.after(2000, self._refresh_mem)

    def _upd_stats(self):
        s = self.cleaner.summary()
        self.lbl_sb["text"] = f"Standby: {s['standby']}"
        self.lbl_tr["text"] = f"进程: {s['ws_trim']}"
        self.lbl_fr["text"] = f"释放: {s['freed_mb']} MB"
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

    def _draw_chart(self):
        """在 Canvas 上绘制固定宽度滚动柱图 + 统计指标"""
        c = self.chart_canvas
        if not c.winfo_width() or not c.winfo_height():
            return
        c.delete("all")
        data = list(self._chart_data)
        if not data:
            self._draw_chart_placeholder()
            return
        cw = c.winfo_width(); ch = 200
        pad_left = 50; pad_right = 10; pad_top = 20; pad_bottom = 46
        px0 = pad_left; px1 = cw - pad_right
        py0 = pad_top; py1 = ch - pad_bottom
        pw = px1 - px0; ph = py1 - py0
        max_val = max(data)
        latest = data[-1] if data else 0
        if max_val <= 0:
            max_val = 1
        step = self.BAR_W + self.BAR_GAP
        max_fit = pw // step
        visible = data[-max_fit:] if len(data) > max_fit else data
        recent_n = min(5, len(visible))
        recent_perf = sum(visible[-recent_n:]) / recent_n if recent_n > 0 else 0
        avg_val = sum(visible) / len(visible) if visible else 0
        peak_val = max_val
        mem_pct = getattr(self, "_mem_pct_for_chart", 50)
        pressure = 0.3 + 0.7 * (mem_pct / 100.0)
        trimmed_cnt = getattr(self, "_cycle_trimmed", 0)
        failed_cnt = getattr(self, "_cycle_failed", 0)
        total_attempts = trimmed_cnt + failed_cnt
        his_peak = max(visible) if visible else 1
        
        # ── ERIS: 五维几何平均效率评分 ──
        
        # 共用：基线
        nonzero_vals = [v for v in visible if v > 0]
        if len(nonzero_vals) >= 3:
            baseline = sum(nonzero_vals[-10:]) / min(len(nonzero_vals[-10:]), 10)
        else:
            baseline = his_peak
        baseline = max(baseline, 5.0)
        # 前2个数据点时用最小基线区分释放量大小
        if len(visible) <= 2:
            baseline = max(baseline, 200 << 20)
        
        # ── A. 能力 (0~1) ──
        base_r = min(recent_perf / baseline, 1.0)
        peak_r = min(recent_perf / max(his_peak, 1), 1.0)
        # 学习进度：前30周期线性增长
        learn_progress = min(len(visible) / 5.0, 1.0)
        cap_a = (0.6 * base_r + 0.4 * peak_r) * learn_progress
        
        # ── B. 自适应力 (0~1) ──
        # 用数据本身的波动推断：高低值越分散→可能在不同条件下都有产出
        if len(visible) >= 3:
            mean_v = sum(visible) / len(visible)
            sd = (sum((v - mean_v)**2 for v in visible) / len(visible))**0.5
            # 变异系数高 = 产出波动大 = 对不同条件有不同响应
            adapt_raw = min(sd / max(mean_v, 1), 1.0)
            adapt_b = 0.3 + 0.7 * adapt_raw
        else:
            adapt_b = 0.6
        
        # ── C. 精准度 (0~1) ──
        success_r = 1.0 if total_attempts == 0 else trimmed_cnt / total_attempts
        if len(visible) >= 3:
            cv = (sum((v - mean_v)**2 for v in visible) / len(visible))**0.5 / max(mean_v, 1)
            consistency_c = 1.0 - min(cv * 0.5, 0.5)
        else:
            consistency_c = 0.8
        # 连续零释放感知（休息期 skip：无操作不算故障）
        if total_attempts == 0:
            satur_c = 1.0
        else:
            zero_streak = 0
            for v in reversed(visible):
                if v == 0:
                    zero_streak += 1
                else:
                    break
            satur_c = max(0.3, 1.0 - zero_streak / 10.0)
        preci_c = success_r * consistency_c * satur_c
        
        # ── D. 动量 (0~1) ──
        if len(visible) >= 6:
            n = min(6, len(visible))
            ys = visible[-n:]
            xs = list(range(n))
            xm = sum(xs) / n; ym = sum(ys) / n
            numer = sum((x - xm) * (y - ym) for x, y in zip(xs, ys))
            denom = sum((x - xm)**2 for x in xs)
            slope = numer / denom if denom > 0 else 0
            rel_gain = slope / max(ym, 1) if ym > 0 else 0
            # sigmoid 映射到 0~1
            momen_d = 1.0 / (1.0 + math.exp(-rel_gain * 5.0))
        else:
            momen_d = 0.6
        
        # ── E. 上下文 (0~1) ──
        pressure_e = min(mem_pct / 80.0, 1.0)
        effort_e = 1.0 if total_attempts == 0 else min(trimmed_cnt / total_attempts, 1.0)
        coverage_e = max(min(trimmed_cnt / 30.0, 1.0), 0.3) if total_attempts == 0 else min(trimmed_cnt / 30.0, 1.0)
        ctx_e = 0.3 * pressure_e + 0.4 * effort_e + 0.3 * coverage_e
        
        # ── 保护几何平均：任一维度不低于 0.1，避免单维度归零拉垮总分 ──
        safe_cap = max(cap_a, 0.1)
        safe_ada = max(adapt_b, 0.1)
        safe_pre = max(preci_c, 0.1)
        safe_mon = max(momen_d, 0.1)
        safe_ctx = max(ctx_e, 0.1)
        eff = (safe_cap * safe_ada * safe_pre * safe_mon * safe_ctx) ** (1.0 / 5.0) * 100.0
        eff = max(0.0, min(100.0, eff))
        eff_text = f"{eff:.0f}%"
        self._eris_sub = {
            "capability": cap_a, "adaptivity": adapt_b, "precision": preci_c,
            "momentum": momen_d, "context": ctx_e, "total": eff,
        }
        # 回填 _eff_data 末尾，使折点与底部文字同值
        if self._eff_data:
            last_list = list(self._eff_data)
            if last_list and abs(last_list[-1] - eff) > 0.5:
                with self._chart_lock:
                    self._eff_data.pop()
                    self._eff_data.append(eff)
        # Y 轴标注 & 网格
        for i, lbl in [(0, "0"), (1, f"{max_val//2:.0f}"), (2, f"{max_val:.0f}")]:
            y = py1 - int(i * ph / 2)
            c.create_line(px0 - 3, y, px0, y, fill="#555")
            c.create_text(px0 - 6, y, text=f"{lbl}MB", anchor="e",
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
            coords = []
            for i, e_val in enumerate(eff_pts):
                cx = px0 + i * step2 + self.BAR_W // 2
                cy = py1 - (e_val / 100.0) * ph
                coords.extend([cx, cy])
                # 折点圆（奶白描边，显示在柱子上方）
                r = 4
                c.create_oval(cx - r, cy - r, cx + r, cy + r,
                              outline="#FFF8E0", width=1, fill="#4488CC", tags="eff_dot")
            if len(coords) >= 4:
                c.create_line(*coords, fill="#4488CC", width=2, smooth=False, tags="eff_line")

        # ── 鼠标悬浮提示 ──
        for i, v in enumerate(visible):
            tag = f"barhit_{i}"
            x0 = px0 + i * step
            x1 = x0 + self.BAR_W
            c.create_rectangle(x0, py0, x1, py1,
                               fill="", outline="", tags=tag)
            eff_val = eff_pts[i] if eff_pts and i < len(eff_pts) else 50

        # 存储当前可见数据供 Motion handler 使用
        self._chart_motion_visible = list(visible)
        self._chart_motion_eff = list(eff_pts) if eff_pts else []
        self._chart_motion_px0 = px0
        self._chart_motion_step = step
        # 坐标轴
        c.create_line(px0, py0, px0, py1, fill="#666")
        c.create_line(px0, py1, px1, py1, fill="#666")
        # 标题 — 居中在顶部黑色区域，不与图表重叠
        c.create_text(px0 + pw//2, 10, text=f"本次优化 {latest:.0f} MB",
                      anchor="center", fill="#ccc", font=("微软雅黑", 9))
        # 底部三指标
        metrics_y = ch - 6
        c.create_text(px0 + pw//2, metrics_y,
                      text=f"平均 {avg_val:.0f} MB    最高 {peak_val:.0f} MB    效率 {eff_text}",
                      anchor="s", fill="#aaa", font=("Consolas", 8))
        # 单一 Motion 绑定（替代多柱 Enter/Leave，消除事件竞争）
        c.tag_unbind("all", "<Enter>")
        c.tag_unbind("all", "<Leave>")
        c.bind("<Motion>", self._chart_on_motion)
    # ── 图表悬浮提示 ──

    def _chart_show_tip(self, event, freed_mb, eff_pct, idx):
        c = self.chart_canvas
        self._chart_hide_tip(None)
        x = event.x
        # 限制 tooltip 不超出左右边界
        cw = c.winfo_width() or 400
        x = max(66, min(cw - 66, x))
        tip_y0 = 22
        c.create_rectangle(x - 60, tip_y0 - 8, x + 60, tip_y0 + 28,
                           fill="#2d2d2d", outline="#4488CC", width=1,
                           tags="chart_tip")
        c.create_text(x, tip_y0 + 10,
                      text=f"释放 {freed_mb:.1f} MB\n效率 {eff_pct:.0f}%",
                      fill="#eee", font=("Consolas", 8),
                      justify="center", tags="chart_tip")

    def _chart_hide_tip(self, event):
        self.chart_canvas.delete("chart_tip")

    def _chart_on_motion(self, event):
        """单一 Motion 悬浮处理：计算列索引，不再依赖多个 Enter/Leave 绑定"""
        visible = getattr(self, '_chart_motion_visible', [])
        if not visible:
            return
        px0 = getattr(self, '_chart_motion_px0', 0)
        step = getattr(self, '_chart_motion_step', 17)
        col = (event.x - px0) // step
        if 0 <= col < len(visible):
            eff_data = getattr(self, '_chart_motion_eff', [])
            eff_val = eff_data[col] if col < len(eff_data) else 50
            self._chart_show_tip(event, visible[col], eff_val, col)
        else:
            self._chart_hide_tip(None)

    # ---- 优化 ----

    def _on_optimize(self):
        if self._optimizing:
            return
        self._optimizing = True
        self.btn_opt.configure(state="disabled"); self.lbl_st["text"] = "优化中..."
        self._log_op("开始优化...")
        threading.Thread(target=self._opt_worker, daemon=True).start()

    def _opt_worker(self):
        mode = self.mode_var.get()
        snaps = []
        for i in range(3):
            snaps = self.sniffer.snapshot(); self.learner.feed(snaps)
            if i < 2: time.sleep(2)
        self._msg_queue.put(('log', f"观察到 {len(snaps)} 个进程"))
        m0 = winapi.get_memory_status()
        total_freed = 0
        for round_idx in range(3):
            if round_idx == 0:
                r = self.cleaner.optimize(snaps, self.learner, mode)
            else:
                snaps = self.sniffer.snapshot(); self.learner.feed(snaps)
                r = self.cleaner.optimize(snaps, self.learner, "deep")
            total_freed += sum(t[2] for t in r.get("layer2", []) if t[1])
            total_freed += sum(p[2] for p in r.get("probe", []) if p[1])
            if round_idx < 2:
                time.sleep(2)
        self.learner.save(STATE_FILE)
        m1 = winapi.get_memory_status()
        self._msg_queue.put(('log', f"📊 三轮优化合计释放 {total_freed/(1<<20):.1f} MB，可用内存 {m0['pct']}%→{m1['pct']}%"))
        self._msg_queue.put(('log_op', f"优化完成 · 三轮合计释放 {total_freed/(1<<20):.1f} MB"))

        self._msg_queue.put(('opt_done', r))
    def _opt_done(self, result):
        s = self.cleaner.summary()
        trimmed = [t for t in result.get("layer2", []) if t[1]]
        # 本次优化增量（从 result 中汇总，非累计）
        inc_freed = sum(t[2] for t in trimmed) + sum(p[2] for p in result.get("probe", []) if p[1])
        inc_mb = inc_freed / (1 << 20)
        for snap, ok, freed, reason in trimmed[:10]:
            self._log(f"  ✓ {snap.name} (PID={snap.pid}) {freed/(1<<20):.0f}MB — {reason}")
        # 统计栏始终显示程序运行以来累计总量
        winapi.report_event("MemWise", f"GUI 优化: {s['freed_mb']}MB 释放, {len(trimmed)} 进程")
        self._upd_stats()
        self._optimizing = False
        self.btn_opt.configure(state="normal")
        if self.daemon_running:
            self._chart_last_freed = float(s['freed_mb'])
            self.lbl_st["text"] = "🟢 守护中 · 手动优化完成"
        else:
            self.lbl_st["text"] = "就绪 · Ctrl+Shift+M"

    # ---- 守护 ----

    def _on_daemon(self):
        if self.daemon_running: return
        self.daemon_running = True
        self.btn_dae.configure(state="disabled"); self.btn_stop.configure(state="normal")
        self.lbl_st["text"] = "守护运行中"; self._log_op("守护模式启动")
        s = self.cleaner.summary()
        self._chart_last_freed = float(s['freed_mb'])
        self._prev_trim_count = s['ws_trim']
        self._prev_fail_count = s['failed_feedback']
        self._chart_data.clear()
        self._eff_data.clear()
        self.daemon_thread = threading.Thread(target=self._dae_worker, daemon=True)
        self.daemon_thread.start()

    def _dae_worker(self):
        try:
            # 创建内存通知对象（事件驱动取代轮询）
            h_low = winapi.create_memory_resource_notification(
                winapi.MEMORY_RESOURCE_NOTIFICATION_TYPE_LOW)
            h_high = winapi.create_memory_resource_notification(
                winapi.MEMORY_RESOURCE_NOTIFICATION_TYPE_HIGH)
            use_event_driver = (h_low is not None and h_high is not None)
            
            interval = CFG.get("interval",30)
            last_efis_time = 0
            last_cfg_check = 0
            last_pri_refresh = 0
            last_save = 0
            last_chart_ts = time.time()
            chart_accum = 0
            startup_logged = False
            
            while self.daemon_running:
                tick_start = time.time()
                
                # 事件驱动等待：内存变化或超时
                if use_event_driver:
                    # 可中断等待：每 1 秒检查 daemon_running
                    for _ in range(interval):
                        if not self.daemon_running:
                            return
                        ret = winapi.wait_for_object(h_low, 1000)
                        if ret == "signaled":
                            break
                else:
                    for _ in range(interval):
                        if not self.daemon_running:
                            return
                        time.sleep(1)
                
                m = winapi.get_memory_status()
                if not m: time.sleep(interval); continue
                snaps = self.sniffer.snapshot(); self.learner.feed(snaps)

                total_samples = sum(p.total_samples for p in self.learner.profiles.values())
                learned = len(self.learner.profiles)

                if not startup_logged:
                    self._msg_queue.put(('log', f"🧠 观察到 {len(snaps)} 个进程 · 已有 {learned} 个画像"))
                    startup_logged = True
                self._new_cycle_event.set()

                # 清理
                mode = self.mode_var.get()
                agg = self.judger.update_pressure(m['pct'])
                ops = CFG.get("clean_operations")
                result = self.cleaner.optimize(snaps, self.learner, mode, operations=ops, aggressiveness=agg)
                l2_results = result.get("layer2", [])
                probe_results = result.get("probe", [])
                agg = result.get("aggressiveness", agg)
                
                # 动态间隔
                prev_interval = interval
                if agg > 0.8:
                    interval = 10
                elif agg > 0.5:
                    interval = 20
                elif m['pct'] < 40:
                    interval = 60
                else:
                    interval = 30
                if interval != prev_interval:
                    self._msg_queue.put(('log', f"⏱ 清理间隔: {prev_interval}s→{interval}s"))
                s = self.cleaner.summary()
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
                    except Exception as e:
                        import sys; print(f"[MemWise] 配置加载异常: {e}", file=sys.stderr)
                if now - last_save > 30:
                    last_save = now
                    self.judger.purge_expired()
                    self.learner.save(STATE_FILE)
                trimmed = [(snap, ok, freed, reason) for snap, ok, freed, reason in l2_results if ok]
                probe_ok = sum(1 for _, ok, _ in probe_results if ok)

                # 累计图表数据（每 30s 记录一次总量）
                cur_freed = float(s['freed_mb'])
                cycle_freed = cur_freed - self._chart_last_freed
                self._chart_last_freed = cur_freed
                chart_accum += max(0.0, cycle_freed)
                if now - last_chart_ts >= 30:
                    self._chart_data.append(chart_accum)
                    self._eff_data.append(self._eris_sub.get('total', 50))
                    chart_accum = 0.0
                    last_chart_ts = now
                cur_trim = s['ws_trim']
                cur_fail = s['failed_feedback']
                self._cycle_trimmed = cur_trim - self._prev_trim_count
                self._cycle_failed = cur_fail - self._prev_fail_count
                self._mem_pct_for_chart = m['pct']
                self._prev_trim_count = cur_trim
                self._prev_fail_count = cur_fail  # 始终追加保持时间轴连续

                # EFIS 效率反馈（每 30 tick）
                if hasattr(self, 'efis'):
                    eris = getattr(self, '_eris_sub', {})
                    stats = {
                        'mem_pct': m['pct'],
                        'trimmed_cnt': self._cycle_trimmed,
                        'failed_cnt': self._cycle_failed,
                        'total_attempts': self._cycle_trimmed + self._cycle_failed,
                        'cycle_freed': cycle_freed,
                        'snaps': snaps,
                        'fore_fullscreen': winapi.is_foreground_fullscreen(),
                    }
                    efis_msg = self.efis.tick(eris, stats)
                    if efis_msg:
                        params = self.efis.get_params()
                        # 同步 EFIS 参数到 CFG 和 judger.cfg
                        # judger.cfg 才是 cleaner/judger 读取 efis_params 的来源
                        CFG['efis_params'] = params
                        self.judger.cfg['efis_params'] = params
                    if efis_msg:
                        self._msg_queue.put(('efis', efis_msg))

                # 元认知
                meta_stats = {
                    'mem_pct': m['pct'],
                    'trimmed_cnt': self._cycle_trimmed,
                    'failed_cnt': self._cycle_failed,
                    'total_attempts': self._cycle_trimmed + self._cycle_failed,
                    'cycle_freed': cycle_freed,
                    'snaps': snaps,
                    'fore_fullscreen': winapi.is_foreground_fullscreen(),
                }
                self.learner.meta.tick(meta_stats)

                # ── 收集并显示算法日志消息 ──
                for msg in self.learner.pop_info():
                    self._msg_queue.put(('log', msg))
                for msg in self.cleaner.pop_info():
                    self._msg_queue.put(('log', msg))
                if hasattr(self.judger, '_info_msgs') and self.judger._info_msgs:
                    for msg in self.judger._info_msgs:
                        self._msg_queue.put(('log', msg))
                    self.judger._info_msgs.clear()

                self._msg_queue.put(('log_op',
                        f"本轮释放 {cycle_freed:.1f} MB · 整理 {len(trimmed)} 进程 · "
                        f"画像 {learned} 个 · 样本 {total_samples} · 试探 {len(probe_results)} ({probe_ok}成功) · 内存 {m['pct']}%"))
                # 状态栏（累计数据）
                self._msg_queue.put(('upd_ui', (s, m, "🟢 守护中")))
                self._msg_queue.put(('chart', None))
                elapsed = time.time() - tick_start
                time.sleep(max(0.5, interval - elapsed))
                if not self.daemon_running:
                    return  # 停止守护后立即退出，不提交多余回调
        except Exception as e:
            import traceback
            self._dae_error = f"{e}\n{traceback.format_exc()}"
            self.daemon_running = False
        finally:
            self._msg_queue.put(('dae_stopped', None))

    def _upd_dae_ui(self, s, m, txt="🟢 守护中"):
        self.lbl_sb["text"] = f"Standby: {s['standby']}"
        self.lbl_tr["text"] = f"进程: {s['ws_trim']}"
        self.lbl_fr["text"] = f"释放: {s['freed_mb']} MB"
        pct = m["pct"]
        icon = "🟢" if pct < 70 else ("🟡" if pct < 90 else "🔴")
        self.lbl_st["text"] = f"{icon} {txt} {pct}%"

    def _stop_daemon(self):
        if not self.daemon_running: return
        self._log_op("停止守护中..."); self.daemon_running = False

    def _dae_stopped(self):
        self.daemon_running = False
        self.btn_dae.configure(state="normal"); self.btn_stop.configure(state="disabled")
        err = getattr(self, '_dae_error', None)
        if err:
            self.lbl_st["text"] = "⚠ 守护异常"
            self._log_op(f"❌ 守护异常，详见下方错误信息")
            self._log(f"🔍 {err}")
            del self._dae_error
        else:
            self.lbl_st["text"] = "就绪 · Ctrl+Shift+M"; self._log_op("守护已停止")
        self.learner.save(STATE_FILE); self._upd_stats(); self._draw_chart()

    # ---- 窗口事件 ----

    def _on_close(self):
        """窗口关闭按钮 — 弹出选择框：最小化到托盘 or 退出"""
        choice = tk.Toplevel(self.root)
        choice.title("MemWise")
        choice.geometry("360x150")
        choice.resizable(False, False)
        choice.transient(self.root)
        choice.focus_set()
        choice.lift()
        # 居中于主窗口
        choice.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - 360) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - 150) // 2
        choice.geometry(f"360x150+{x}+{y}")

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
        self.root.wait_window(choice)

        if result[0] == "minimize":
            self._minimized_to_tray = True
            self.root.withdraw()
            self._log_op("🔄 程序已最小化到系统托盘（双击托盘图标恢复）")
        else:
            self._do_exit()

    def _do_exit(self):
        """直接退出（无确认）"""
        self.daemon_running = False
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
        self.root.destroy()

    def run(self): self.root.mainloop()

if __name__ == "__main__":
    MemWiseGUI().run()
