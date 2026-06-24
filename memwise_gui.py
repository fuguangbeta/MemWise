"""
MemWise v1.0 GUI —— 图形界面
系统托盘 + 全局热键 + 颜色状态 + 排除列表编辑 + 设置面板
"""

import os, sys, time, threading, tkinter as tk
from collections import deque
from tkinter import ttk, simpledialog, messagebox
import ctypes
import ctypes.wintypes as w

try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    try: ctypes.windll.user32.SetProcessDPIAware()
    except: pass

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
from core.sniffer import Sniffer

STATE_FILE = os.path.join(base, "memwise_state.json")
CONFIG_FILE = os.path.join(base, "config", "config.yaml")

try:
    import yaml
    def _load_cfg():
        d = {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"interval":30,"never":[],
             "clean_mode":"normal","auto_start":False,
             "auto_start_daemon":False,"auto_start_admin":False,
             "auto_start_minimize":False}
        if not os.path.isfile(CONFIG_FILE): return d
        try:
            with open(CONFIG_FILE) as f: u = yaml.safe_load(f) or {}
            d.update(u); return d
        except: return d
    CFG = _load_cfg()
except ImportError:
    CFG = {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"interval":30,"never":[],
           "clean_mode":"normal","auto_start":False,
           "auto_start_daemon":False,"auto_start_admin":False,
           "auto_start_minimize":False}

def _save_cfg():
    """保存 CFG 到 config.yaml"""
    try:
        import yaml
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            yaml.dump(CFG, f, default_flow_style=False, allow_unicode=True)
    except:
        pass

# 托盘和热键常量
HOTKEY_ID = 9001
TRAY_UID = 1
GWLP_WNDPROC = -4
WM_HOTKEY = 0x0312
# 图标颜色名常量 — 传给 create_memwise_icon
ICO_IDLE = (70, 130, 180)     # 钢蓝 — 空闲
ICO_LOW  = (60, 160, 60)      # 绿   — 守护低压力
ICO_MID  = (200, 180, 40)     # 黄   — 守护中压力
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
                       bg="#2d2d2d", fg="#eee", font=("Segoe UI", 9),
                       padx=8, pady=4, wraplength=320)
        lbl.pack()

    def _hide(self):
        if self._tw:
            self._tw.destroy(); self._tw = None


class MemWiseGUI:
    def __init__(self):
        global _gui_ref
        _gui_ref = self

        self.root = tk.Tk()
        self.root.title("MemWise v1.0")
        self.root.geometry("1060x700")
        self.root.resizable(True, False)

        # 窗口和托盘都用默认图标
        self._custom_hicon = None
        self._icon_cache = {}  # name -> HICON

        self.learner = Learner.load(STATE_FILE)
        jcfg = {"kp":CFG.get("kp",0.6),"ki":CFG.get("ki",0.15),"kd":CFG.get("kd",0.1),
                "target_usage":CFG.get("target_usage",60),"never":CFG.get("never",[])}
        self.judger = Judger(self.learner, jcfg)
        self.cleaner = Cleaner(self.judger)
        self.sniffer = Sniffer()
        self.daemon_running = False; self.daemon_thread = None
        self._tray_icon_handle = None
        self._minimized_to_tray = False
        # 柱图状态
        self._chart_data = deque(maxlen=60)
        self._chart_last_freed = 0.0
        self._new_cycle = False  # 守护模式下每周期首次 _log 自动清屏
        self._mem_pct = 0

        self._build_ui()
        self._refresh_mem()
        self._setup_hotkey_and_tray()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if CFG.get("auto_start_daemon"):
            self.root.after(300, self._on_daemon)
        if CFG.get("auto_start_minimize"):
            self.root.after(800, self._minimize_to_tray)

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
        """根据内存使用率和守护状态更新托盘图标颜色"""
        if self.daemon_running:
            if pct > 85:
                icon = self._get_colored_icon("high", ICO_HIGH)
                tip = f"🔴 守护中 {pct}% — 内存紧张"
            elif pct > 70:
                icon = self._get_colored_icon("mid", ICO_MID)
                tip = f"🟡 守护中 {pct}% — 内存偏高"
            else:
                icon = self._get_colored_icon("low", ICO_LOW)
                tip = f"🟢 守护中 {pct}% — 正常"
        else:
            if pct > 85:
                icon = self._get_colored_icon("idle_high", ICO_HIGH)
                tip = f"内存 {pct}% — 紧张"
            elif pct > 70:
                icon = self._get_colored_icon("idle_mid", ICO_MID)
                tip = f"内存 {pct}% — 偏高"
            else:
                icon = self._get_colored_icon("idle", ICO_IDLE)
                tip = f"内存 {pct}%"
        self._tray_icon_handle = icon
        winapi.tray_modify(self.root.winfo_id(), TRAY_UID, icon, f"MemWise — {tip}")

    def _show_tray_menu(self):
        """右键托盘菜单 — 弹出操作菜单"""
        menu = tk.Menu(self.root, tearoff=False)
        menu.add_command(label="显示窗口", command=self._show_window)
        menu.add_separator()
        menu.add_command(label="退出", command=self._do_exit)
        try:
            x, y = self.root.winfo_pointerxy()
        except:
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
            "内存条颜色显示压力，绿色代表空闲，红色代表紧张，"
            "如果一直红色说明内存不够用，考虑加内存条或者关掉一些程序")
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
            "一键释放内存，程序会自动判断哪些进程可以清理、清理到什么程度，"
            "内存越紧张就清得越狠。注意清理系统缓存需要管理员权限，"
            "深度清理后打开大文件可能会慢几秒钟，这是正常的")
        self.btn_dae = ttk.Button(bf, text="▶ 守护", command=self._on_daemon)
        self.btn_dae.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_dae,
            "让程序在后台一直跑，自动监控内存，"
            "内存占用高的时候会自动清理，低的时候就不动。"
            "刚开始的几分钟只是观察不动手。"
            "所有操作会实时写入日志框，方便查看每一步在做什么。"
            "注意如果不是管理员运行，系统缓存的清理不会生效，"
            "但进程级的清理不受影响")
        self.btn_stop = ttk.Button(bf, text="■ 停止", command=self._stop_daemon, state="disabled")
        self.btn_stop.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_stop,
            "停止后台的自动清理，"
            "之前学到的程序行为数据会自动保存，下次启动接着用")
        self.btn_excl = ttk.Button(bf, text="⚙ 排除", command=self._edit_exclusion_list)
        self.btn_excl.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_excl,
            "在这里添加不想被清理的程序，比如你正在用的浏览器或者开发工具，"
            "加了之后这个程序就不会被整理。"
            "注意如果加太多程序在排除列表里，释放内存的效果会变差")
        self.btn_set = ttk.Button(bf, text="☰ 设置", command=self._open_settings)
        self.btn_set.pack(side="left")
        self._add_tip(self.btn_set,
            "打开详细设置面板，可以单独开关每种清理操作"
            "（EmptyWorkingSet、Standby List、Modified Page、系统文件缓存），"
            "以及设置定时清理时间。清理模式在主界面下拉框切换")
        self.btn_log = ttk.Button(bf, text="学习日志", command=self._show_learn_log)
        self.btn_log.pack(side="left", padx=(6,0))
        self._add_tip(self.btn_log,
            "查看每个程序的学习数据，包括清理次数、置信度、"
            "内存走势等信息，方便判断程序的行为是否正常")

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
            "选不同的清理力度，quick最轻最快，normal适中，"
            "deep和full会彻底清理系统缓存，释放更多内存，"
            "但full做完后打开大文件会慢一会，因为缓存被清空了")
        ttk.Label(mf, text="  ").pack(side="left")

        # 统计
        sf = ttk.LabelFrame(self.root, text="统计", padding=8)
        sf.pack(fill="x", padx=12, pady=4)
        self.lbl_sb = ttk.Label(sf, text="Standby: 0"); self.lbl_sb.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_sb,
            "系统缓存的清理次数，这个需要管理员权限才能生效，"
            "清理之后打开大文件可能会慢一点因为缓存没了")
        self.lbl_tr = ttk.Label(sf, text="进程: 0"); self.lbl_tr.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_tr,
            "整理了多少次进程，这个数字大不代表释放得多，"
            "因为小进程整理很多次也会计数")
        self.lbl_fr = ttk.Label(sf, text="释放: 0 MB"); self.lbl_fr.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_fr,
            "总共释放了多少内存，注意释放之后系统会重新分配给其他程序用，"
            "所以可用内存不会一直往上涨")
        self.lbl_lr = ttk.Label(sf, text="已学习: 0"); self.lbl_lr.pack(side="right")
        self._add_tip(self.lbl_lr,
            "程序一直在观察每个进程的内存使用习惯，"
            "学得越久判断越准，电脑上出现过的进程都会留下记录，"
            "不会自动删除")

        # 日志 — 上半文本 + 下半实时柱图
        lf = ttk.LabelFrame(self.root, text="日志", padding=4)
        lf.pack(fill="both", expand=True, padx=12, pady=(4,12))

        # 下半：柱图 Canvas（守护模式下显示实时优化柱图）
        self.chart_canvas = tk.Canvas(lf, height=140, bg="#1e1e1e", highlightthickness=0)
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
        win.geometry("420x430")
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

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
                winapi.set_auto_start("MemWise", target, args, wd)
                self._log("开机自启已启用")
            else:
                winapi.remove_auto_start("MemWise")
                self._log("开机自启已关闭")
            CFG["auto_start"] = en
            _save_cfg()
        ttk.Checkbutton(sf, text="开机自启", variable=ast_var,
                        command=on_autostart).pack(anchor="w")
        self._add_tip(sf.winfo_children()[-1],
            "开机时自动启动本程序（启动文件夹快捷方式，不碰注册表）")

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
                ok = winapi.set_auto_start_admin("MemWise", target, args)
                if ok:
                    # 关掉普通自启避免冲突
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
            CFG["auto_start_admin"] = en
            _save_cfg()
        ttk.Checkbutton(sf, text="管理员权限启动", variable=asa_var,
                        command=on_autostart_admin).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1],
            "通过计划任务以最高权限开机启动，清理更彻底（需先以管理员身份运行一次）")

        asd_var = tk.BooleanVar(value=CFG.get("auto_start_daemon", False))
        def on_auto_daemon():
            CFG["auto_start_daemon"] = asd_var.get()
            _save_cfg()
        ttk.Checkbutton(sf, text="启动时自动开启守护", variable=asd_var,
                        command=on_auto_daemon).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1],
            "程序启动后立即自动进入守护模式，无需手动点「守护」按钮")

        asm_var = tk.BooleanVar(value=CFG.get("auto_start_minimize", False))
        def on_minimize():
            CFG["auto_start_minimize"] = asm_var.get()
            _save_cfg()
        ttk.Checkbutton(sf, text="启动后最小化到托盘", variable=asm_var,
                        command=on_minimize).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1],
            "程序启动成功后将窗口最小化到系统托盘，只在图标显示")

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

        ops_frame = ttk.Frame(cf); ops_frame.pack(fill="x")
        ttk.Checkbutton(ops_frame, text="EmptyWorkingSet", variable=ws_var,
                        command=lambda: toggle_op("ws", ws_var)).pack(anchor="w")
        ttk.Checkbutton(ops_frame, text="Standby List 清理", variable=sb_var,
                        command=lambda: toggle_op("standby", sb_var)).pack(anchor="w")
        ttk.Checkbutton(ops_frame, text="Modified Page 写回", variable=mp_var,
                        command=lambda: toggle_op("modified", mp_var)).pack(anchor="w")
        ttk.Checkbutton(ops_frame, text="系统文件缓存", variable=fc_var,
                        command=lambda: toggle_op("filecache", fc_var)).pack(anchor="w")
        ttk.Label(ops_frame, text="（留空 = 按模式自动选择）",
                  foreground="#888").pack(anchor="w")

        mode_frame = ttk.Frame(cf); mode_frame.pack(fill="x", pady=(6,0))
        ttk.Label(mode_frame, text="模式:").pack(side="left")
        mode_cb = ttk.Combobox(mode_frame, textvariable=self.mode_var, width=10,
                                values=["quick","normal","deep","full"], state="readonly")
        mode_cb.pack(side="left", padx=(4,12))

        def save_and_close():
            CFG["clean_mode"] = self.mode_var.get()
            win.destroy()
        ttk.Button(win, text="关闭", command=save_and_close).pack(pady=10)

    def _edit_exclusion_list(self):
        win = tk.Toplevel(self.root)
        win.title("进程排除列表")
        win.geometry("360x320")
        win.transient(self.root)
        win.grab_set()

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
        win.geometry("820x500")
        win.transient(self.root)
        win.grab_set()
        cols = ("进程", "α", "β", "样本", "可信度", "收益比", "偏差", "趋势", "泄漏", "清理", "试探OK", "试探失败")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=20)
        for c in cols:
            tree.heading(c, text=c)
            if c in ("进程",):
                tree.column(c, width=180)
            elif c in ("α","β","样本","清理","试探OK","试探失败"):
                tree.column(c, width=55, anchor="center")
            elif c in ("可信度","收益比","偏差","趋势"):
                tree.column(c, width=65, anchor="center")
            else:
                tree.column(c, width=60, anchor="center")
        vsb = ttk.Scrollbar(win, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(12,0), pady=(12,4))
        vsb.pack(side="right", fill="y", pady=(12,4))
        for row in info_data:
            tree.insert("", "end", values=row)
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=8)



    # ---- 日志 / 状态 ----

    def _clear_log(self):
        """清空日志区域"""
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def _log_op(self, m):
        """记录新操作（先清屏再追加）"""
        self._clear_log()
        self._new_cycle = False
        self.log.configure(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {m}\n"); self.log.see("end")
        self.log.configure(state="disabled")

    def _log(self, m):
        """追加日志行（不清屏） — 守护模式下自动检测新周期清屏"""
        self.log.configure(state="normal")
        if self._new_cycle:
            self.log.delete("1.0", "end")
            self._new_cycle = False
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {m}\n"); self.log.see("end")
        self.log.configure(state="disabled")

    def _upd_learned(self):
        self.lbl_lr.config(text=f"已学习: {len(self.learner.profiles)}")

    def _refresh_mem(self):
        m = winapi.get_memory_status()
        if m:
            pct = m["pct"]
            # 更新彩色条
            cw = self.mem_canvas.winfo_width() or 400
            bar_w = max(1, int(cw * pct / 100))
            color = "#4caf50" if pct < 50 else ("#ff9800" if pct < 80 else ("#f44336" if pct > 90 else "#ffc107"))
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
        """在 Canvas 上绘制固定宽度滚动柱图"""
        c = self.chart_canvas
        if not c.winfo_width() or not c.winfo_height():
            return
        c.delete("all")
        data = list(self._chart_data)
        if not data:
            self._draw_chart_placeholder()
            return
        cw = c.winfo_width(); ch = 140
        pad_left = 50; pad_right = 10; pad_top = 10; pad_bottom = 25
        px0 = pad_left; px1 = cw - pad_right
        py0 = pad_top; py1 = ch - pad_bottom
        pw = px1 - px0; ph = py1 - py0
        max_val = max(data)
        if max_val <= 0:
            # 全零数据也保持时间轴可见
            max_val = 1
        # Y 轴标注 & 网格
        for i, lbl in [(0, "0"), (1, f"{max_val//2:.0f}"), (2, f"{max_val:.0f}")]:
            y = py1 - int(i * ph / 2)
            c.create_line(px0 - 3, y, px0, y, fill="#555")
            c.create_text(px0 - 6, y, text=f"{lbl}MB", anchor="e",
                          fill="#aaa", font=("Consolas", 8))
            if i > 0:
                c.create_line(px0, y, px1, y, fill="#2a2a2a", dash=(2, 4))
        # 固定宽度柱条，从左到右排列，放不下时向左滚动
        step = self.BAR_W + self.BAR_GAP
        max_fit = pw // step
        visible = data[-max_fit:] if len(data) > max_fit else data
        offset = len(data) - len(visible)  # 被左边挤掉的个数
        for i, v in enumerate(visible):
            bh = max(1, int(v / max_val * ph))
            x0 = px0 + i * step; x1 = x0 + self.BAR_W; y0 = py1 - bh
            if v > 0:
                ratio = v / max_val
                color = "#4caf50" if ratio < 0.3 else ("#ff9800" if ratio < 0.7 else "#f44336")
                c.create_rectangle(x0, y0, x1, py1, fill=color, outline="", width=0)
            else:
                # 零值柱用 1px 暗线保持时间轴连续
                c.create_rectangle(x0, py1 - 1, x1, py1, fill="#555", outline="", width=0)
        # 坐标轴
        c.create_line(px0, py0, px0, py1, fill="#666")
        c.create_line(px0, py1, px1, py1, fill="#666")
        # 标题
        c.create_text(px0 + pw//2, 3, text=f"每次清理释放 (峰值 {max_val:.0f} MB)",
                      anchor="n", fill="#ccc", font=("微软雅黑", 9))

    # ---- 优化 ----

    def _on_optimize(self):
        self.btn_opt.configure(state="disabled"); self.lbl_st["text"] = "优化中..."
        self._log_op("开始优化...")
        threading.Thread(target=self._opt_worker, daemon=True).start()

    def _opt_worker(self):
        mode = self.mode_var.get()
        snaps = []
        for i in range(3):
            snaps = self.sniffer.snapshot(); self.learner.feed(snaps)
            if i < 2: time.sleep(2)
        self.root.after(0, lambda: self._log(f"观察到 {len(snaps)} 个进程"))
        result = self.cleaner.optimize(snaps, self.learner, mode)
        self.learner.save(STATE_FILE)
        self.root.after(0, self._opt_done, result)

    def _opt_done(self, result):
        s = self.cleaner.summary()
        trimmed = [t for t in result.get("layer2", []) if t[1]]
        # 本次优化增量（从 result 中汇总，非累计）
        inc_freed = sum(t[2] for t in trimmed) + sum(p[2] for p in result.get("probe", []) if p[1])
        inc_mb = inc_freed / (1 << 20)
        self._log(f"本轮释放 {inc_mb:.1f} MB · 整理 {len(trimmed)} 个 · Probe {len(result.get('probe',[]))}")
        for snap, ok, freed, reason in trimmed[:10]:
            self._log(f"  ✓ {snap.name} (PID={snap.pid}) {freed/(1<<20):.0f}MB — {reason}")
        # 统计栏始终显示程序运行以来累计总量
        winapi.report_event("MemWise", f"GUI 优化: {s['freed_mb']}MB 释放, {len(trimmed)} 进程")
        self._upd_stats()
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
        self._chart_data.clear()
        self.daemon_thread = threading.Thread(target=self._dae_worker, daemon=True)
        self.daemon_thread.start()

    def _dae_worker(self):
        try:
            tick = 0; interval = CFG.get("interval",30)
            while self.daemon_running:
                tick += 1; m = winapi.get_memory_status()
                if not m: time.sleep(interval); continue
                snaps = self.sniffer.snapshot(); self.learner.feed(snaps)

                # 学习统计
                total_samples = sum(p.total_samples for p in self.learner.profiles.values())
                learned = len(self.learner.profiles)

                if tick == 1:
                    self.root.after(0, lambda n=len(snaps), p=learned:
                        self._log_op(f"🧠 守护启动 · 观察到 {n} 个进程 · 已有 {p} 个画像"))
                # 标记新守护周期 — 下次 _log 自动清屏
                self._new_cycle = True

                # 每周期全量清理（无视 agg 阈值，系统级 + 进程级 + 试探同步进行）
                self.cleaner.clean_deep_standby()
                self.cleaner.clean_modified_pages()
                self.cleaner.clear_file_cache()
                l2_results, probe_results = self.cleaner._layer2_process(snaps, self.learner)
                s = self.cleaner.summary()
                self.learner.save(STATE_FILE)
                trimmed = [(snap, ok, freed, reason) for snap, ok, freed, reason in l2_results if ok]
                probe_ok = sum(1 for _, ok, _ in probe_results if ok)

                # 本轮释放增量（非累计）
                cur_freed = float(s['freed_mb'])
                cycle_freed = cur_freed - self._chart_last_freed
                self._chart_last_freed = cur_freed
                self._chart_data.append(max(0.0, cycle_freed))  # 始终追加保持时间轴连续

                self.root.after(0, lambda n=len(trimmed),ls=learned,ts=total_samples,pt=len(probe_results),po=probe_ok,mem=m,cf=cycle_freed:
                    self._log_op(
                        f"本轮释放 {cf:.1f} MB · 整理 {n} 进程 · "
                        f"画像 {ls} 个 · 样本 {ts} · 试探 {pt} ({po}成功) · 内存 {mem['pct']}%"))
                # 状态栏（累计数据）
                self.root.after(0, lambda st=s,mem=m:
                    self._upd_dae_ui(st, mem, "🟢 守护中"))
                self.root.after(0, self._draw_chart)
                time.sleep(interval)
        except Exception as e:
            import traceback
            self._dae_error = f"{e}\n{traceback.format_exc()}"
            self.daemon_running = False
        finally:
            self.root.after(0, self._dae_stopped)

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
        choice.grab_set()
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
        except: pass
        try: self.learner.save(STATE_FILE)
        except: pass
        self.root.destroy()

    def run(self): self.root.mainloop()

if __name__ == "__main__":
    MemWiseGUI().run()
