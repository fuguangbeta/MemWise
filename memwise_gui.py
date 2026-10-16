"""
MemWise v5.0.012 GUI —— 图形界面
系统托盘 + 全局热键 + 颜色状态 + 排除列表编辑 + 设置面板
"""

import os, sys, time, shutil, subprocess, threading, tempfile, tkinter as tk, queue
from collections import deque
from tkinter import ttk, font as tkfont
import ctypes
import ctypes.wintypes as w

# ── 无 UI 引擎（守护循环/ERIS/轮次数据/事件队列）+ 共享基础设施（路径/日志/配置单例/格式化）──
from core.engine import (
    base, CFG, STATE_FILE, _save_cfg,
    _log_write, _log_open, _log_close, _diag_log, _ERR,
    fmt_label, fmt_count, MemWiseEngine,
    _watchdog_path, _spawn_watchdog, _update_watchdog_daemon,
    read_watchdog_daemon, remove_watchdog, _install_crash_sink, _event_log,
    init_runtime,
)

from core import winapi
from core import update as _update
from core.backup import APP_VERSION
from core.learner import PareLearner as Learner
from core.learner import _is_system_core, _is_self_path  # 系统核心保护名单（进程排行终止保护等）/自身可执行路径（WS 硬上限守卫）
from core.judger import PareJudger as Judger
from core.cleaner import PareCleaner as Cleaner
from core.efis import EfisController
from core.sniffer import Sniffer
from core.icon_flat import FLAT_48_PNG, decode_png  # 任务栏扁平图标（内嵌 PNG，冷启动 exe 兼容）
from core.i18n import tr, tr_msg, set_language, LANGUAGES, get_language  # 界面语言
from core import backup  # 配置包：导出/导入/自动备份/恢复出厂（任务3，2026-09-06）
from core import config as _config_mod  # 配置读写组件可用性自检（2026-10-15）

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





def _normalize_proc_name(raw):
    """规范化程序名：去空格转小写，自动补 .exe 后缀（进程名统一格式）"""
    n = str(raw).strip().lower()
    if n and not n.endswith(".exe"):
        n += ".exe"
    return n


# ── 日志面板分组写入语义（2026-08-30）：组间 ≤7 接续 / >7 清屏，组内可超 7 完整呈现 ──
PANEL_MAX_LINES = 7  # 日志面板组间刷新阈值（行）

# ── 日志图标槽对齐（2026-09-11 用户要求：图标对图标、文字对文字）──
# 每条播报预留一个图标位：有图标则图标独占该位，无图标则该位留空，文字统一从同一起列开始。
# 采用「固定制表位」而非空格补齐——实测日志字体（Consolas 9，半角空格 7px）下各图标像素宽
# 差异很大（→ 7px、✓ 12px、⚡/⚠ 16px），用空格凑宽永远对不齐；制表位是绝对像素列，
# 与图标自身宽度、字形回退、DPI 无关，图标列与文字列都严格对齐。
# 仅在显示层生效：日志历史与文件日志仍保存中文原文（语言切换可完整重渲染，见 F51）。
_LOG_SLOT_PX = 19            # 图标位宽度下限（像素）；实际位宽 = max(下限, 最宽图标 + _LOG_ICON_GAP)
_LOG_ICON_GAP = 4            # 图标与文字之间的最小间隙（图标位宽 = 最宽图标 + 该间隙）
_LOG_ICON_PROBE = "→⚠⇒🎮↑↓✓⚡🔄🟢↻🔴❌✗🟠🟡📋⛨⚙☰📜📊🧠📈🚀🔥🕳🔍✅"
# ↑ 项目内实际用到的图标全集（2026-09-11 扫描源码得出）：图标位宽按其中最宽者定位。
_LOG_TAG = "logwrap"         # 换行悬挂缩进标签：续行也对齐到文字列
# 图标位里保留原字形的图标（2026-09-11 用户定稿）：勾叉（正确/错误）与方向箭头（升/降）含义明确；
# 其余行首图标都是纯象形装饰（📈⚡🧠🚀🔥📋🎮🔄🟢…），各字形大小/基线/字体回退不一，一律换成统一绘制的默认图标。
_LOG_ICON_KEEP = frozenset("✓✗✅❌↑↓")


def _log_is_icon(ch):
    """该字符是否作图标使用（决定它独占图标位）"""
    o = ord(ch)
    return (0x2190 <= o <= 0x21FF or 0x2600 <= o <= 0x27BF or 0x2B00 <= o <= 0x2BFF
            or 0x1F000 <= o <= 0x1FAFF or 0x2710 <= o <= 0x2718)


def _log_slot_px(text_widget):
    """图标位宽（像素）= max(下限, 最宽图标 + 最小间隙)；按面板实际字体实测，随字体/DPI 自适应"""
    try:
        f = tkfont.Font(font=text_widget.cget("font"))
        return int(max(_LOG_SLOT_PX, max(f.measure(c) for c in _LOG_ICON_PROBE) + _LOG_ICON_GAP))
    except Exception:
        return _LOG_SLOT_PX


def _log_tab_stop(text_widget):
    """制表位（像素）= 时间戳前缀宽 + 图标位宽（续行悬挂缩进、消息里散落的制表符都对齐到文字列）"""
    try:
        f = tkfont.Font(font=text_widget.cget("font"))
        return int(f.measure("[00:00:00] ") + _log_slot_px(text_widget))
    except Exception:
        return 77 + _log_slot_px(text_widget)  # 兜底：Consolas 9 @100% 实测前缀宽（11 字符 × 7px）


def _setup_log_widget(text_widget):
    """日志面板排版：图标位宽 + 默认图标 + 制表位 + 续行悬挂缩进（换行文字同样对齐文字列）。
    制表位用纯像素值（Tk 距离里的 "p" 是点不是像素，带单位会偏）。
    默认图标宽度 = 整个图标位（图样居中）：无图标行只放这一张图，文字即严格起于图标位末端。"""
    try:
        slot = _log_slot_px(text_widget)
        stop = _log_tab_stop(text_widget)
        text_widget._log_slot = slot
        text_widget._log_icon_img = _make_log_icon(slot)
        text_widget.configure(tabs=(stop,))
        text_widget.tag_configure(_LOG_TAG, lmargin2=stop)
    except Exception:
        pass


# ── 播报默认图标（2026-09-11 用户要求）：程序自绘「圈 + M」，纯黑描边 ──
# 18×14 像素（用户 2026-09-11 复核：图形很好但偏小 ⇒ 在有效范围内放满）：
# 高度 14 = 日志字体行高（Consolas 9 实测 linespace=14）⇒ **恰好不撑高行距**；
# 图标位 20px ⇒ 两侧各留 1px。圆环 1~3px、M 笔画 1px 且与圆环留 2~3px 空隙
# （笔画挤在一起 1× 下会糊成一团——前两版都放大核验过才定稿）；'#' 为黑像素，其余透明。
# 4× 超采样取阈值生成：边缘平滑、无锯齿。不使用系统 emoji（各字形大小/基线不一）。
_LOG_ICON_ROWS = (
    ".....#######......",
    "...###.....###....",
    "...##.......##....",
    "..##.#.....#.##...",
    "..##.#.....#.##...",
    ".##..###.###..##..",
    ".##..###.###..##..",
    ".##..#.###.#..##..",
    "..##.#..#..#.##...",
    "..##.#.....#.##...",
    "...###.....###....",
    "...###.....###....",
    ".....#######......",
    ".......###........",
)


def _make_log_icon(slot=None):
    """生成默认图标（Tk PhotoImage；透明底 + 黑色像素）。给 slot 时画在 slot 宽画布正中——
    这一张图即占满整个图标位，无图标行的文字列由此精确成立。失败返回 None（不影响面板）"""
    try:
        rows = _LOG_ICON_ROWS
        iw, ih = len(rows[0]), len(rows)
        w = max(iw, int(slot or iw))
        off = (w - iw) // 2
        img = tk.PhotoImage(width=w, height=ih)
        for y, row in enumerate(rows):
            for x, ch in enumerate(row):
                if ch == "#":
                    img.put("#000000", (x + off, y))
        return img
    except Exception:
        return None


def _log_fill_image(text_widget, width):
    """透明占位图（宽=给定像素，高=图标高）：把保留字形的图标补足到整个图标位宽。
    按宽度缓存在控件上——Tk 图像随 Python 对象回收，必须持续持有引用（否则文字会跳到图前）。"""
    if width <= 0:
        return None
    cache = getattr(text_widget, "_log_fill_cache", None)
    if cache is None:
        cache = {}
        text_widget._log_fill_cache = cache
    img = cache.get(width)
    if img is None:
        try:
            img = tk.PhotoImage(width=int(width), height=len(_LOG_ICON_ROWS))
        except Exception:
            return None
        cache[width] = img
    return img


def _log_advances(text_widget, measure=False):
    """保留字形图标的**真实排版推进宽**（像素）缓存 —— 占位图宽度必须精确，否则该行文字偏移。

    Tk 的 font.measure 对回退字形会偏大（2026-09-11 实测：✓ 报 12、实际排版 9；✗ 报 12、实际 10），
    故离屏实测：插「图标 ×2」，两次墨迹起点之差 ÷2（两次同一字形的左留白抵消 ⇒ 恰为推进宽）。

    measure=False（插入路径）：只读缓存，未测到就返回空 ⇒ 调用方用制表符/默认图标兜底，
      绝不在插入过程中驱动事件循环（否则会与面板刷新重入交错）。
    measure=True（启动后的预热回调）：真正实测一次（需窗口已映射），成功后全程复用。"""
    cache = getattr(text_widget, "_log_adv_cache", None)
    if not measure or (cache is not None and cache.get("ok")):
        return (cache or {}).get("adv") or {}
    try:
        font = text_widget.cget("font")
    except Exception:
        return {}
    adv, ok = {}, False
    top = None
    try:
        top = tk.Toplevel(text_widget)
        top.geometry("160x40+4000+4000")          # 屏幕外：需要已映射才量得到 bbox，但不闪窗
        t = tk.Text(top, font=font, height=1, width=20)
        t.pack()
        t.update_idletasks()
        top.update()                              # 新窗口要跑一次完整事件循环才映射（否则 bbox 全 None）
        for c in sorted(_LOG_ICON_KEEP):
            t.delete("1.0", "end")
            t.insert("1.0", c + c)
            t.update_idletasks()
            b0, b2 = t.bbox("1.0"), t.bbox("1.0 + 2c")
            if b0 and b2:
                adv[c] = int(round((b2[0] - b0[0]) / 2.0))
        ok = bool(adv)
    except Exception:
        ok = False
    finally:
        if top is not None:
            try:
                top.destroy()
            except Exception:
                pass
    if not ok:
        adv = {}      # 量不到就返回空 —— 调用方退回制表符跳位；**不用 measure 值**（它对回退字形偏大，
                      # 用它算占位图反而会把该行文字左移 2~3px），下次调用会重测
    text_widget._log_adv_cache = {"ok": ok, "adv": adv}
    return adv


def _insert_log_lines(text_widget, ts, msg, tag):
    """按物理行插入：图标位恒占满固定像素宽（默认图标，或保留字形的勾叉/箭头 + 透明占位补足），
    正文严格从图标位末端起列；首行带时间戳前缀，续行不带（续行用 lmargin2 悬挂缩进对齐文字列）。

    不靠制表符定位文字列——实测制表符在距制表位不足约 5px 时会退化成一个空格宽（2026-09-11
    日志实测：⚡⚠❌⚙ 这类 16px 宽图标正踩此边界，该行文字右移 7px）；改用「图标 + 精确宽度的
    透明占位图」，像素级精确，与字体/DPI/图标宽窄无关。"""
    img = getattr(text_widget, "_log_icon_img", None)
    slot = getattr(text_widget, "_log_slot", None) or _log_slot_px(text_widget)
    adv = _log_advances(text_widget)
    for k, line in enumerate(str(msg).split(chr(10))):
        head = ("[%s] " % ts) if k == 0 else ""
        icon = line[:1] if line[:1] in _LOG_ICON_KEEP else ""
        rest = line[1:] if icon else (line[1:] if line.startswith(chr(9)) else line)
        rest = rest[1:] if rest.startswith(chr(9)) else rest.lstrip()
        text_widget.insert("end", head, tag)
        if not icon:
            if img is not None:
                text_widget.image_create("end", image=img, align="center")    # 整位宽的默认图标
        elif icon in adv:
            text_widget.insert("end", icon, tag)
            fill = _log_fill_image(text_widget, slot - adv[icon])             # 精确占位图补足整位宽
            if fill is not None:
                text_widget.image_create("end", image=fill, align="center")
            else:
                text_widget.insert("end", chr(9), tag)
        else:
            # 窗口尚未映射、量不到真实推进宽：窄字形（勾叉/箭头）用制表符跳位；
            # 宽到跳不过去的（✅❌ 16px）宁可退化为默认图标，也不让该行文字错位
            try:
                _w = tkfont.Font(font=text_widget.cget("font")).measure(icon)
            except Exception:
                _w = 0
            if img is not None and _w > slot - 5:
                text_widget.image_create("end", image=img, align="center")
            else:
                text_widget.insert("end", icon + chr(9), tag)
        text_widget.insert("end", rest + chr(10), tag)


def _parse_delay_start(argv):
    """解析 `--delay-start N`（重启路径专用，见 core/backup.restart_application）。

    含义：在**任何初始化之前**睡眠 N 秒——给"正在退出的旧实例"留出释放单实例互斥
    （Global\\MemWise_SingleInstance）与清理 PyInstaller 临时目录的时间。
    为何不由父进程延迟：父进程 Popen 后立即退出（GUI 需马上关闭），而 `cmd /c timeout`
    在 stdin 为管道时立即失败、延迟静默消失（2026-10-15 实测）⇒ 改由新实例自己等待。
    非法/缺失一律视为 0（不影响正常启动路径），上限 30s 防误配卡死。
    """
    try:
        i = argv.index("--delay-start")
        return max(0.0, min(30.0, float(argv[i + 1])))
    except Exception:
        return 0.0


def _upd_reason_text(why):
    """更新失败原因码 → 用户可读中文（UI 文案；日志仍记原始码）。"""
    key = str(why or "").split(":")[0]
    return {
        "timeout": "网络超时",
        "connect_failed": "无法连接（网络受限或需要代理）",
        "send_failed": "请求发送失败",
        "recv_failed": "未收到响应",
        "bad_url": "地址无效",
        "open_failed": "无法初始化网络会话",
        "cancelled": "已取消",
        "sha256_mismatch": "更新包校验失败（哈希不符）",
        "size_mismatch": "更新包大小不符",
        "io_error": "写入文件失败",
        "not_pe": "更新包不是可执行文件（已丢弃）",
        "no_asset_url": "发布页未找到更新包",
        "spawn_helper_failed": "无法启动更新助手",
        "exception": "内部错误",
    }.get(key, ("服务器返回 %s" % key.split("_", 1)[1]) if key.startswith("http_") else ("未知原因（%s）" % why))


def _upd_log(base, msg):
    """更新助手写日志：**写到目标目录**的 data/memwise.log。

    助手自身是从 %TEMP% 运行的新版 exe，engine 的 base 会解析到 %TEMP% ⇒ 不能复用 engine 的日志路径。
    （日志历史只存中文原文，符合 F51：不在逻辑层翻译。）"""
    try:
        import datetime
        d = os.path.join(base, "data")
        os.makedirs(d, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        with open(os.path.join(d, "memwise.log"), "a", encoding="utf-8") as f:
            f.write("[%s][更新] %s\n" % (ts, msg))
    except Exception:
        pass


def _wait_pid_exit(pid, timeout):
    """等待进程退出（SYNCHRONIZE 句柄 + WaitForSingleObject）。进程不存在 ⇒ 视为已退出。"""
    try:
        h = winapi.OpenProcess(0x00100000, False, int(pid))   # SYNCHRONIZE
        if not h:
            return True
        try:
            return winapi.WaitForSingleObject(h, int(timeout * 1000)) == 0
        finally:
            winapi.CloseHandle(h)
    except Exception:
        return True


def _launch_app(target, minimized=False):
    """启动目标 exe（清理 PyInstaller 的 _MEI*/_PYI* 环境变量，防新版误用旧解包目录）。"""
    try:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("_MEI", "_PYI"))}
        argv = [target] + (["--minimized"] if minimized else [])
        return subprocess.Popen(argv, creationflags=0x08000000,   # CREATE_NO_WINDOW
                                cwd=os.path.dirname(os.path.abspath(target)), env=env)
    except Exception:
        return None


def _apply_update(argv):
    """更新助手：`--apply-update <目标exe> <旧PID> [--minimized]`。

    为什么要独立进程：运行中的 exe 文件被锁、**无法自替换**；助手由下载到的新版 exe 充任
    （拷到 %TEMP% 后启动），因此它本身就是新版代码。时序：
      ① 等旧实例退出（最多 60s）→ ② 复制旧 exe 为 .old（供回滚）
      → ③ MoveFileEx 一步原子替换 → ④ 启动新版（原参数）→ ⑤ 10s 内存活确认
      → ⑥ 失败则用 .old 还原并重启旧版（最坏结果：还是旧版在跑，不会更坏）
    日志写入目标目录 data/memwise.log；返回 0=成功（供测试断言）。"""
    _swapped = False    # 真实性加固（真机测试发现）：替换成功之后任何异常都必须尝试回滚
    try:
        rest = [a for a in argv[1:] if a != "--apply-update"]
        minimized = "--minimized" in rest
        rest = [a for a in rest if a != "--minimized"]
        if len(rest) < 2:
            return 2
        target, pid = os.path.abspath(rest[0]), int(rest[1])
        new_exe = sys.executable
        base = os.path.dirname(target)
        if not os.path.isfile(target) or not os.path.isfile(new_exe):
            return 2
        _upd_log(base, "更新助手启动：等待旧实例退出（PID %d）" % pid)
        if not _wait_pid_exit(pid, 120.0):     # 侧视补：守护/长清理周期下 60s 可能不够
            _upd_log(base, "\u7b49\u5f85\u8d85\u65f6\uff0c\u653e\u5f03\u66f4\u65b0\uff08\u65e7\u7248\u672c\u672a\u52a8\uff09")
            _launch_app(target, minimized)     # 关键：不能让用户"程序消失且没更新"
            return 3


        bak = target + ".old"   # 侧视修正误删后补回（真机测试抓到：备份步骤 NameError）

        def _rollback():
            """用 .old 还原旧版；失败必须显式留痕（此时只能靠用户手动改名，不能沉默）。"""
            if winapi.replace_file_atomic(bak, target):
                _upd_log(base, "已回滚到旧版")
                return True
            _upd_log(base, "⚠ 回滚失败：请手动把 %s 改名为 %s" % (os.path.basename(bak), os.path.basename(target)))
            return False
        try:
            shutil.copy2(target, bak)
        except Exception as _e:
            _upd_log(base, "备份失败（%r），放弃更新" % _e)
            _launch_app(target, minimized)
            return 4
        # 新版落地：**先复制到目标同目录**再"同卷一步换名"（2026-10-16 演练修正）：
        #   ① 直接 MoveFileEx(助手自身文件 → 目标) 会搬走运行中的镜像，且助手若在别的卷
        #      （%TEMP% 常在 C:，程序可能在 D:）时**跨卷 MoveFileEx 不是原子操作**；
        #   ② 先复制到目标同目录可保证同卷，MoveFileEx 才是真正的原子替换。
        stage = target + ".new"
        try:
            try:
                os.remove(stage)
            except Exception:
                pass
            shutil.copy2(new_exe, stage)
        except Exception as _e:
            _upd_log(base, "落盘新版本失败（%r），保留原版本" % _e)
            return 4
        # 侧视补：替换失败要重试——双杀软对"替换可执行文件"常有瞬时占用（曾见 Access denied 稍后即好）
        _ok_swap = False
        for _i in range(5):
            if winapi.replace_file_atomic(stage, target):
                _ok_swap = True
                break
            _upd_log(base, "替换第 %d 次未成功，1 秒后重试" % (_i + 1))
            time.sleep(1.0)
        if not _ok_swap:
            _upd_log(base, "替换失败（文件被占用或权限不足），保留原版本并重启旧版")
            try:
                os.remove(stage)
            except Exception:
                pass
            _launch_app(target, minimized)     # 早期失败也要把旧版拉起来，不能留"无人看护"状态
            return 5
        _swapped = True
        _upd_log(base, "已替换为新版（来源：%s）" % os.path.basename(new_exe))
        proc = _launch_app(target, minimized)
        if proc is None:
            _upd_log(base, "启动新版失败，回滚")
            _rollback()
            _launch_app(target, minimized)
            return 6
        time.sleep(10)
        if proc.poll() is None:
            _upd_log(base, "新版启动成功，更新完成")
            return 0
        _upd_log(base, "新版启动后立即退出（rc=%s），回滚到旧版" % proc.returncode)
        _rollback()
        _launch_app(target, minimized)
        return 7
    except Exception as _e:
        try:
            _upd_log(os.path.dirname(os.path.abspath(argv[2] if len(argv) > 2 else ".")), "更新助手异常：%r" % _e)
        except Exception:
            pass
        try:
            if _swapped:
                _upd_log(os.path.dirname(os.path.abspath(argv[2])) if len(argv) > 2 else ".",
                         "异常发生在替换之后，尝试回滚")
                _rollback()
                _launch_app(os.path.abspath(argv[2]), "--minimized" in argv)
        except Exception:
            pass
        return 9


def _update_housekeeping():
    """更新后清理（2026-10-16）：能执行到这里 ⇒ 当前版本启动正常，上一轮的 .old 备份已完成使命。

    只清理**我们自己的产物**：`<exe>.old`（旧版备份）、`<exe>.new`（替换中间文件）、
    `%TEMP%\\MemWise_*.exe[.part]`（下载/助手残留）。**绝不触碰任何用户文件**；
    任何一步失败都静默忽略（清理不是关键路径，不得影响启动）。"""
    try:
        exe = os.path.abspath(sys.executable)
        for p in (exe + ".old", exe + ".new"):
            try:
                # 侧视修正（2026-10-16）：只清理"早已完成使命"的备份（>15 分钟）。
                # 否则新版刚启动就把 .old 删了，而助手的 10s 存活确认尚未结束——
                # 一旦新版随即崩溃，回滚就无料可用（保护窗口必须覆盖确认窗口）。
                if os.path.isfile(p) and (time.time() - os.path.getmtime(p)) > 900:
                    os.remove(p)
            except Exception:
                pass
        try:
            import glob as _g
            import tempfile as _tf
            for p in (_g.glob(os.path.join(_tf.gettempdir(), "MemWise_*.exe"))
                      + _g.glob(os.path.join(_tf.gettempdir(), "MemWise_*.exe.part"))):
                try:
                    os.remove(p)
                except Exception:
                    pass
        except Exception:
            pass
    except Exception:
        pass


def _autostart_target_args(minimized=False):
    """管理员自启计划任务的目标与参数（frozen=exe 本体 / dev=pythonw+脚本引号）。

    模块级：设置面板（`_admin_task_args` 委托本函数）与**启动迁移**（旧任务自动重建）共用，
    杜绝两处构造漂移（2026-09-06 审查 F4 的同类理由）。
    """
    if getattr(sys, "frozen", False):
        target = sys.executable
        args = ""
    else:
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        target = pythonw if os.path.isfile(pythonw) else sys.executable
        args = '"%s"' % os.path.abspath(__file__)   # 引号：脚本路径含空格时计划任务仍可解析
    if minimized:
        args = (args + " --minimized") if args else "--minimized"
    return target, args


def _align_log_line(s):
    """把一行播报规整为「图标位 + 文字」（多行消息逐行处理；原前导空白收进图标位）。
    · 保留字形图标（勾叉/箭头）→ 该图标 + 制表
    · 纯象形图标（📈⚡🧠…）→ **丢弃**字形，改为图标位放默认图标（该行与无图标行同形）
    · 无图标 → 制表独占图标位
    图标位与文字列由 `_setup_log_widget` 按像素设定，故各图标宽窄不影响对齐。"""
    if not s:
        return s
    out = []
    for line in str(s).split("\n"):
        t = line.lstrip()
        if t and _log_is_icon(t[0]):
            body = t[1:].lstrip()
            out.append((t[0] + "\t" + body) if t[0] in _LOG_ICON_KEEP else ("\t" + body))
        else:
            out.append("\t" + t)
    return "\n".join(out)



def _msg_lines(msgs):
    """一组消息的实际渲染行数（内嵌换行的消息按多行计——"实际多少行就多少行"）"""
    return sum(m.count("\n") + 1 for m in msgs)

def _panel_needs_clear(cur_lines, group_lines):
    """组间刷新判定：累计 ≤7 接续显示；>7 清屏后整组输出"""
    return cur_lines + group_lines > PANEL_MAX_LINES


def _tree_font():
    """Treeview 实际使用的字体（取不到则退回 Tk 默认字体）——列宽实测用"""
    import tkinter.font as _tkf
    try:
        spec = ttk.Style().lookup("Treeview", "font")
        if spec:
            return _tkf.Font(font=spec)
    except Exception:
        pass
    try:
        return _tkf.nametofont("TkDefaultFont")
    except Exception:
        return _tkf.Font()


def _tree_measure_columns(cols, rows, pad=26, p90_cols=(), floor=0):
    """按表头与内容**实测宽度**算每列所需宽度。

    · `p90_cols` 里的列取内容宽度的 **90 分位**（而非最大值）——防个别超长进程名把列撑成"长条"
    · `floor` 为每列下限（保数值可读）；`pad` 为列内边距
    """
    f = _tree_font()
    out = []
    for i, c in enumerate(cols):
        w = f.measure(str(c))
        if rows:
            ws = sorted(f.measure(str(r[i])) for r in rows)
            j = min(len(ws) - 1, int(round(0.90 * (len(ws) - 1))))
            w = max(w, ws[j] if i in p90_cols else ws[-1])
        out.append(max(int(w + pad), floor))
    return out


def _tree_sort_by(tree, rows_by_iid, idx, reverse=True):
    """按第 idx 列重排（与进程排行同款 move 重排）。
    rows_by_iid 存**原始数值**，不按显示字符串排序（避免 "10" < "9" 这类误差）"""
    items = [(k, rows_by_iid[k][idx]) for k in tree.get_children("")]
    items.sort(key=lambda x: x[1].lower() if isinstance(x[1], str) else x[1], reverse=reverse)
    for pos, (k, _v) in enumerate(items):
        tree.move(k, "", pos)


def _tree_sort_toggle(state, cols, col):
    """点击表头：同一列再点则反向，换列默认降序；返回 (列索引, 是否降序)。
    按**列索引**而非显示名（语言切换后列名变化，按名判断会失效）"""
    idx = cols.index(col) if col in cols else 0
    if state.get("idx") == idx:
        state["rev"] = not state.get("rev", True)
    else:
        state["idx"], state["rev"] = idx, True
    return state["idx"], state["rev"]


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
        return None, None, tr_msg("无法识别")
    if not parts or not any(parts):
        return None, None, tr_msg("不能为空")
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
        return None, None, tr_msg("只能包含一个按键（修饰键 + 单字母或 F1-F24）")
    if not has_mod:
        return None, None, tr_msg("至少需要一个修饰键（ctrl/alt/shift）")
    if key is None:
        return None, None, tr_msg("缺少按键（单字母或 F1-F24）")
    return mods, key, None


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

# 资源管理器重启广播消息（2026-09-11 审查 F7）：explorer 崩溃/重启后未处理此消息，
# 托盘图标会永久消失（用户以为程序已退出）——必须在 wndproc 里识别并重挂
_Usr32.RegisterWindowMessageW.restype = w.UINT
_TASKBAR_CREATED = _Usr32.RegisterWindowMessageW("TaskbarCreated")


def _relaunch_elevated():
    """以管理员身份重启自身（2026-09-11 审查 F32）。返回 True = 已成功派生提权实例，
    调用方应立即让位退出；False = 用户取消 / 无法提权，调用方以受限模式继续。

    背景：打包清单为 asInvoker（PyInstaller 6.x 会用 uac_admin 参数改写清单里的执行级别，
    highestAvailable 无法表达），管理员账户不再自动弹 UAC ⇒ 在此显式请求提权，得到
    "优先管理员、失败降级标准"的语义。--elevated-retry 标记防止无限重启。"""
    try:
        if getattr(sys, "frozen", False):
            exe, params = sys.executable, ""
        else:
            pythonw = sys.executable.replace("python.exe", "pythonw.exe")
            exe = pythonw if os.path.isfile(pythonw) else sys.executable
            params = '"%s"' % os.path.abspath(__file__)
        # 过滤 --elevated-retry 与 --delay-start（连同其数值）：延迟只为让**旧实例**退出，
        # 提权副本是同一轮启动的延续，再睡一次只会让用户多等（2026-10-15）
        _skip_flags = ("--elevated-retry", "--delay-start")
        args, _it = [], iter(sys.argv[1:])
        for _a in _it:
            if _a in _skip_flags:
                if _a == "--delay-start":
                    next(_it, None)
                continue
            args.append(_a)
        tail = " ".join(('"%s"' % a) if " " in a else a for a in args)
        params = (params + " " + tail).strip()
        params = (params + " --elevated-retry").strip()
        ctypes.windll.shell32.ShellExecuteW.restype = ctypes.c_void_p
        r = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)
        return int(r or 0) > 32     # ShellExecuteW >32 = 成功
    except Exception:
        return False


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
        if msg == _TASKBAR_CREATED and _gui_ref is not None:
            _tray_action = 'readd'   # 资源管理器重启 → 由 Tk 轮询器安全重挂托盘图标
            return 0
        if msg == winapi.WM_TRAYICON and _gui_ref is not None:
            # LOWORD 解析（2026-08-30 审查）：legacy 格式 lParam=事件原值、v4 格式
            # HIWORD=uID——低字在两种格式下均为事件值，与托盘 ADD→SETVERSION（文档
            # 顺序，2026-08-30 修正）配套后无论 Shell 实际采用何种格式均正确
            ev = lp & 0xFFFF
            if ev in (0x201, 0x202, 0x203):
                _tray_action = 'left'
            elif ev in (0x205, 0x007B):
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
    """为任意 widget 添加鼠标悬停提示。
    整行范围提示用 add_widget 挂多个控件（Tk Enter/Leave 不冒泡，逐控件绑定），
    所有控件共享同一延迟回调与提示窗：快速滑动时后 Enter 取消前 Enter 的回调，
    不产生双提示；提示窗全局唯一（类属性），任意时刻至多一个悬浮提示"""
    _tip = None      # 当前提示窗
    _tips = []       # 2026-10-17：所有活着的提示窗。_show 前统一清空 ⇒ 机制上保证同屏至多一个

    def __init__(self, widget, text, delay=400):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._id = None
        # 延迟调度挂根窗口而非控件：控件级 after 的回调命令与 Tkinter 命令管理
        # 存在生命周期缺陷（命令被删但 _tclCommands 残留/id 复用覆盖），控件销毁时
        # deletecommand 二次删除抛 "can't delete Tcl command" 中断 destroy（曾致设置
        # 面板关闭时语言行被部分销毁）；root 从不销毁，命令生命周期干净
        self._root = widget._root()
        self._bind(widget)

    def add_widget(self, w):
        """把同一提示扩展到另一个控件（整行范围提示用）"""
        self._bind(w)

    def _bind(self, w):
        w.bind("<Enter>", self._enter, add="+")
        w.bind("<Leave>", self._leave, add="+")
        w.bind("<Button-1>", self._leave, add="+")   # 点击即隐藏（2026-10-16：此前点了按钮提示仍挡在那里）

    def _enter(self, e):
        self.widget = e.widget  # 定位跟随当前悬停控件
        if self._id:
            try:
                self._root.after_cancel(self._id)
            except Exception:
                pass
        self._id = self._root.after(self.delay, self._show)

    def _leave(self, e):
        if self._id:
            try:
                self._root.after_cancel(self._id)
            except Exception:
                pass
            self._id = None
        self._hide()

    @classmethod
    def _hide_all(cls):
        """销毁全部存活提示窗（2026-10-17：多实例各自的延迟回调可能同时触发，
        仅靠 _tip 单引用会出现同屏两个提示框——用户实测到"重影"）。"""
        for t in list(cls._tips):
            try:
                if t.winfo_exists():
                    t.destroy()
            except Exception:
                pass
        cls._tips = []
        cls._tip = None

    def _show(self):
        ToolTip._hide_all()   # 先清空所有已有提示窗（防同屏重影）
        if not self.widget.winfo_exists():
            return  # 窗口已销毁（after 回调残留）：跳过创建防 TclError
        # master 用控件所在顶层窗口而非控件本身：Toplevel 挂在行内控件路径下时，
        # 关闭窗口的递归销毁会二次删除其 Tcl 命令（can't delete Tcl command）导致
        # 销毁中断、窗口只销毁部分（曾见设置面板只剩语言行消失）
        sw, sh = self.widget.winfo_screenwidth(), self.widget.winfo_screenheight()
        # 自适应宽度（2026-10-16 用户反馈"用着不顺手"）：旧实现固定 wraplength=800，
        # 长文案会拉成一条横贯屏幕的大条并越过屏幕右缘被切掉 ⇒ 改为随屏幕宽度收窄换行。
        wrap = max(260, min(560, sw - 140))
        tip = tk.Toplevel(self.widget.winfo_toplevel())
        tip.withdraw()          # 先隐藏：量完尺寸再定位，避免在 (0,0) 闪一下
        tip.wm_overrideredirect(True)
        lbl = tk.Label(tip, text=self.text, justify="left",
                       bg="#2d2d2d", fg="#eee", font=("Microsoft YaHei UI", 9),
                       padx=8, pady=4, wraplength=wrap)
        lbl.pack()
        tip.update_idletasks()
        tw, th = tip.winfo_reqwidth(), tip.winfo_reqheight()
        wx, wy = self.widget.winfo_rootx(), self.widget.winfo_rooty()
        x = wx + 16
        y = wy + self.widget.winfo_height() + 4
        if y + th > sh - 8:                     # 下方放不下 ⇒ 翻到控件上方显示
            y = max(8, wy - th - 4)
        if x + tw > sw - 8:                     # 右侧越界 ⇒ 向左收边，保证完整可读
            x = max(8, sw - tw - 8)
        tip.wm_geometry(f"+{x}+{y}")
        tip.deiconify()
        self._tip = tip
        ToolTip._tips.append(tip)

    def _hide(self):
        if self._tip is not None:
            try:
                if self._tip.winfo_exists():
                    self._tip.destroy()
            except Exception:
                pass
            self._tip = None


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

        # 回调在找到目标窗口时返回 False（提前停表）——EnumWindows 返回值随之
        # 为 False，不可用于成功判断（2026-08-15 审查：原 `and found` 使激活分支恒不执行）
        ctypes.windll.user32.EnumWindows(_cb, 0)
        if found:
            hwnd = found[0]
            ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            ctypes.windll.user32.SetForegroundWindow(hwnd)
            return True
    except Exception:
        pass
    return False


class MemWiseGUI:
    def __init__(self):
        # 进程级初始化（DPI 感知 + 数据/配置目录预建，2026-09-11 审查 F38：
        # 不再由 `import core.engine` 触发副作用，改为入口显式调用）
        # 返回值 = 数据/配置目录可写性哨兵结果（2026-10-15 P4）：只读安装目录下必须提示用户
        self._writable = init_runtime()
        # 常驻崩溃现场（2026-08-30）：独立于「记录运行日志到文件」开关——默认关日志的
        # 分发用户崩溃后仍有 data/memwise_crash.log 可反馈（看门狗子进程不安装）
        _install_crash_sink()
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
        if _mutex_err in (0xB7, 5) and "--elevated-retry" in sys.argv:
            # 自我提权重启的竞态（2026-09-11 审查 F32）：旧实例正在退出，短暂重试接管互斥
            # （仅限本程序自身的提权重启路径，最多 4 秒；普通双开仍走下方即时退出分支）
            for _ in range(20):
                time.sleep(0.2)
                self._mutex = ctypes.windll.kernel32.CreateMutexW(None, False, SINGLE_MUTEX_NAME)
                _mutex_err = ctypes.windll.kernel32.GetLastError()
                if _mutex_err not in (0xB7, 5):
                    break
        if _mutex_err in (0xB7, 5):
            # mutex 冲突但本会话未找到窗口（残留句柄 / 启动早期竞态 / 另一用户会话）：
            # 防双开直接退出，但静默退出会让用户以为程序坏了 ⇒ 弹原生提示
            # （2026-09-11 审查 F8：跨用户会话场景下 EnumWindows 看不到他会话窗口，必然走到这里）
            if _mutex_err == 0xB7 or not self._mutex:
                self._mutex = None
                try:
                    ctypes.windll.user32.MessageBoxW(
                        None,
                        tr("程序已在其他用户会话中运行，本机同一时间只允许运行一个实例"),
                        "MemWise v5.0.012", 0x00000040)  # MB_ICONINFORMATION
                except Exception:
                    pass
                sys.exit(0)
            _log_write("诊断", "单实例互斥权限受限且无窗口，继续运行")

        # 优先以管理员权限启动（2026-09-11 审查 F32）：管理员账户未提权时显式请求提权，
        # 成功则让位退出（提权实例接管）；用户取消或标准账户 ⇒ 以受限模式继续并给提示。
        # --restored（崩溃自动恢复）不请求，避免恢复过程弹 UAC 打断用户。
        if (not winapi.is_elevated()) and winapi.is_admin() and "--restored" not in sys.argv:
            if _relaunch_elevated():
                try:
                    ctypes.windll.kernel32.CloseHandle(self._mutex)
                except Exception:
                    pass
                self._mutex = None
                sys.exit(0)
        
        # 崩溃恢复检测
        self._restored = "--restored" in sys.argv
        self._minimized_to_tray = False  # 显式初始化（--minimized 分支下方覆盖为 True）

        self.root = tk.Tk()
        self.root.withdraw()  # 先隐藏：居中定位后再统一显示，消除"默认位置闪现"
        self.root.title("MemWise v5.0.012")
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
        self._once_optimizing = False  # 守护运行中即时优化防重入（2026-08-15 审查）

        self.learner = Learner.load(STATE_FILE)
        jcfg = {"kp":CFG.get("kp",0.6),"ki":CFG.get("ki",0.15),"kd":CFG.get("kd",0.1),
                "target_usage":CFG.get("target_usage",60),"never":CFG.get("never",[]),
                "game_processes":CFG.get("game_processes",[]),
                "emergency_threshold":CFG.get("emergency_threshold",80),  # 高压让路/树阈值同口径（2026-09-11 S5）
                "efis_params":CFG.get("efis_params",{})}
        self.judger = Judger(self.learner, jcfg)
        self.cleaner = Cleaner(self.judger)
        self.efis = EfisController(STATE_FILE)
        # 启动按当前清理模式取参（2026-08-16 模式参数组：16 组中取 CFG 模式对应组，
        # 与守护周期末同步口径一致）
        self.efis.set_mode(CFG.get("clean_mode", "normal"))
        # 启动即用 EFIS 持久化参数对齐运行时消费方（config.yaml 可能滞后于 efis_state.json）
        self.judger.cfg["efis_params"] = self.efis.get_params()
        self.judger.sync_pid_from_cfg()  # 启动即按 EFIS 权威参数对齐 PID（config.yaml 快照可能滞后）
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
        # 更新检查状态（2026-10-16）：busy 防重入、st 为 data 侧运行态、prog 为进度弹窗句柄
        self._upd_busy = False
        self._upd_st = None
        self._upd_prog = None
        self._upd_cancel = False
        self._upd_downloading = False
        self._log_history = deque(maxlen=300)  # 日志原文缓存（语言切换时按新语言重渲染）
        self._last_msg = None  # 连续重复消息去重（2026-08-30：启动观察消息实测重复）
        self._mem_pct = 0

        self._build_ui()
        self._refresh_mem()
        self._setup_hotkey_and_tray()
        adm = "✓" if winapi.is_elevated() else "✗"
        self._log(f"MemWise v5.0.012 启动· 当前是否管理员权限:{adm}")
        if not winapi.is_elevated():
            # 全局必要提示（2026-09-11 审查 F32）：标准权限下缓存类清理不可用，必须让用户看见
            self._log("⚠ 当前为标准权限运行，系统缓存类清理不可用（需以管理员身份启动）")
        # 启动自检提示（2026-10-15 P4/P2）：只读安装目录或缺少配置读写组件时，配置与学习数据
        # 会静默失效（实测：save 返回 False / 只写 devnull，用户毫无感知）——必须让用户看见，
        # 并告知怎么修（移动位置 / 重新下载）。日志行即时可见，弹窗延迟到主循环后一次弹出。
        if not getattr(self, "_writable", True):
            # ⚠ F51：写进日志历史的必须是**中文原文**（显示层再翻译），此处不得包 tr()
            self._log("⚠ 程序所在目录不可写，配置与学习数据无法保存")
            self.root.after(1200, lambda: self._dark_message(
                tr("程序所在目录不可写"),
                tr("程序所在目录不可写，配置与学习数据都无法保存。请把程序移动到有写入权限的位置（例如用户目录）后重新启动。")))
        if getattr(_config_mod, "yaml", None) is None:
            self._log("⚠ 缺少配置读写组件，设置与学习数据将无法保存")
            self.root.after(1600, lambda: self._dark_message(
                tr("缺少配置读写组件"),
                tr("程序缺少配置读写组件，设置与学习数据都无法保存。请重新下载或重新安装程序。")))
        # 看门狗：spawn 子进程监控崩溃
        if not self._restored:
            _spawn_watchdog(self.engine.daemon_running)
        else:
            # 崩溃恢复提示（2026-09-11 审查 F31）：补上"如何彻底退出"，避免用户用任务管理器
            # 结束进程后被自动恢复、误以为程序无法关闭
            self._log("🔄 检测到上次崩溃，已自动恢复（如需彻底退出，请用托盘右键菜单的「退出」）")
            # 恢复守护模式（仅当崩溃前守护运行中；否则保持空闲，尊重用户意图）
            # 延迟触发，让窗口完全初始化后再启动
            self.root.after(800, self._maybe_restore_daemon)
        if winapi.is_elevated():
            winapi.enable_reduct_privileges()
        # 升级迁移（2026-08-15）：普通自启功能已移除，启动文件夹旧快捷方式
        # 幂等清理（防与管理员计划任务开机双启动）
        if CFG.get("auto_start_admin"):
            try:
                winapi.remove_auto_start("MemWise")
            except Exception:
                pass
            # 旧任务自动迁移（2026-10-15）：命令行时代创建的任务带「仅交流电启动 / 切电池即停 /
            # 72 小时执行上限」三项 schema 默认，笔记本用电池时表现为"勾了自启却没反应"。
            # 检测到就按新 XML 重建一次（用户不会想到要手动取消再勾选）；失败静默、不影响启动。
            try:
                if winapi.auto_start_admin_needs_fix("MemWise"):
                    _t, _a = _autostart_target_args(bool(CFG.get("auto_start_minimize", False)))
                    if winapi.set_auto_start_admin("MemWise", _t, _a):
                        self._log("开机自启动任务已更新（允许电池供电启动、不限运行时长）")
            except Exception:
                pass
        # 启动消息队列轮询（每 100ms 检查一次，主线程安全）
        # 启动后自动检查更新（用户开启 update_check 才联网；4 秒后等界面画完再查，避免与启动抢资源）
        if CFG.get("update_check", False) and getattr(sys, "frozen", False):
            self.root.after(4000, lambda: self._upd_check(manual=False))
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
                    fw = ctypes.windll.user32.FindWindowExW(None, None, "TkTopLevel", "MemWise v5.0.012")
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
        ok = winapi.tray_add(hwnd, TRAY_UID, hIcon, tr("MemWise — 智能内存看护"))
        if not ok:
            self._log("⚠ 托盘图标添加失败，重试...")
            time.sleep(0.5)
            ok = winapi.tray_add(hwnd, TRAY_UID, hIcon, tr("MemWise — 智能内存看护"))

    def _apply_hotkeys(self, initial=False, changed=None):
        """按配置重注册全部全局热键（统一入口：注销→逐项解析→冲突检测→逐个注册）。
        非法/冲突/被占用时本次使用默认值并提示，不写回 CFG（保留用户配置下次启动再试）；
        initial=True 为启动路径静默；changed=本次实际变更的配置键集合——仅这些键注册
        成功后报"已设为"（2026-08-30 审查 C5：原对全部键重复播报，未变更键也报）"""
        try:
            hwnd = int(self.root.winfo_id())
            changed = changed or set()
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
                    if not initial and hk["key"] in changed:
                        self._log(f"{hk['name']}热键已设为 {CFG.get(hk['key'], hk['default'])}")
                else:
                    self._log(f"⚠ {hk['name']}热键注册失败（可能被其他程序占用）: {CFG.get(hk['key'], hk['default'])}")
                    dm, dv, _ = _parse_hotkey(hk["default"])
                    winapi.register_hotkey(hwnd, hk["id"], dm, dv)
        except Exception:
            pass

    def _update_tray_status(self, pct):
        """根据内存使用率和守护状态更新托盘图标颜色（4档匹配内存条；
        百分比数字图标同样按档位着色——2026-08-30 审查：原恒绿色与四档承诺不符）"""
        if self.engine.daemon_running:
            if pct >= 90:
                _fb, _color, tip = "high", ICO_HIGH, tr_msg(f"🔴 守护中 {pct}% — 内存紧张")
            elif pct >= 75:
                _fb, _color, tip = "mid2", ICO_ORANGE, tr_msg(f"🟠 守护中 {pct}% — 内存偏高")
            elif pct >= 60:
                _fb, _color, tip = "mid", ICO_MID, tr_msg(f"🟡 守护中 {pct}% — 内存偏高")
            else:
                _fb, _color, tip = "low", ICO_LOW, tr_msg(f"🟢 守护中 {pct}% — 正常")
        else:
            if pct >= 90:
                _fb, _color, tip = "idle_high", ICO_HIGH, tr_msg(f"内存 {pct}% — 紧张")
            elif pct >= 75:
                _fb, _color, tip = "idle_mid2", ICO_ORANGE, tr_msg(f"内存 {pct}% — 偏高")
            elif pct >= 60:
                _fb, _color, tip = "idle_mid", ICO_MID, tr_msg(f"内存 {pct}% — 偏高")
            else:
                _fb, _color, tip = "idle", ICO_IDLE, tr_msg(f"内存 {pct}%")
        pct_icon_handle = winapi.create_tray_percent_icon(pct, color=_color)
        icon = pct_icon_handle or self._get_colored_icon(_fb, _color)
        # 释放旧图标防止 GDI 泄漏（长期运行崩溃根因）
        # 仅成功创建时轮换：失败（None）时保留旧句柄继续复用，避免句柄被丢弃泄漏
        try:
            if pct_icon_handle:
                prev = getattr(self, '_prev_pct_icon', None)
                if prev:
                    ctypes.windll.user32.DestroyIcon(prev)
                self._prev_pct_icon = pct_icon_handle
            elif getattr(self, '_prev_pct_icon', None):
                # 创建失败：旧百分数图标已不再复用，销毁防 GDI 泄漏（2026-08-15 审查）
                ctypes.windll.user32.DestroyIcon(self._prev_pct_icon)
                self._prev_pct_icon = None
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
                # TPM_RETURNCMD=0x0100 | TPM_RIGHTBUTTON=0x0002 | TPM_TOPALIGN=0x0000
                # （TOPALIGN=菜单在光标下方展开，Windows 常规；原 0x0020 实为 BOTTOMALIGN，2026-08-15 审查修正）
                cmd = um.TrackPopupMenu(hmenu, 0x0002 | 0x0100, pt.x, pt.y, 0, hwnd, None)
            finally:
                um.DestroyMenu(hmenu)  # 异常路径也销毁，防句柄泄漏
            # 执行操作
            if cmd == ID_SHOW:
                self._show_window()
            elif cmd == ID_EXIT:
                self.root.after(50, self._do_exit)
        except Exception:
            pass

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

    def _add_tip_row(self, row, txt):
        """整行范围提示：一个 ToolTip 实例挂载行内全部控件（标签+输入框都触发，
        共享同一延迟回调与提示窗，快速滑动不产生双提示）"""
        t = ToolTip(row, tr(txt))
        for _c in row.winfo_children():
            t.add_widget(_c)

    def _hk_display(self, key="hotkey"):
        """热键配置 → 显示文案（如 ctrl+shift+m → Ctrl+Shift+M）"""
        spec = CFG.get(key, "ctrl+shift+m" if key == "hotkey" else "ctrl+shift+g")
        return "+".join(p.capitalize() for p in str(spec).split("+"))

    def _build_ui(self):
        # 内存状态 (Canvas 彩色条)
        f = ttk.LabelFrame(self.root, text=tr("内存状态"), padding=8)
        f.pack(fill="x", padx=12, pady=(12,4))
        self.mem_canvas = tk.Canvas(f, height=22, bg="#eee", highlightthickness=0)
        self.mem_canvas.pack(fill="x", pady=(0,4))
        self.mem_bar_rect = self.mem_canvas.create_rectangle(0, 0, 0, 22, fill="#4caf50", width=0)
        self.mem_bar_text = self.mem_canvas.create_text(8, 11, anchor="w", text="--%", font=("Segoe UI", 9, "bold"), fill="#fff")
        self._add_tip(self.mem_canvas,
            "「内存条当前使用率」\n"
            "1. 代表色：\n"
            "  · 绿色 — 低于60%\n"
            "  · 黄色 — 60~74%\n"
            "  · 橙色 — 75~89%\n"
            "  · 红色 — 高于90%\n"
            "⚠ 长期处于紧张色说明物理内存不足")
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
            "「按当前选择的清理模式立即执行一次内存优化」\n"
            "1. 游戏模式下游戏进程受完全保护，其余进程将由进程决策优化\n"
            "2. 同时启动守护模式也会按当前的清理模式执行一次即时优化\n"
            f"⚠ 热键默认{self._hk_display('hotkey')}（可在设置 → 全局热键中更改）\n"
            "⚠ 若还同时处于游戏模式，会无视手动优化操作，避免影响流畅")
        self.btn_dae = ttk.Button(bf, text=tr("⛨ 守护"), command=self._on_daemon)
        self.btn_dae.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_dae,
            "「开启内存循环优化」\n"
            "1. 采用阶段性多次轻量压制与周期末全量收割\n"
            "2. 开启后会自动规划清理策略，根据系统状态持续优化调整\n"
            "3. 守护模式下有游戏自动检测，也可以手动开启游戏模式\n"
            "4. 内置崩溃监测，程序因意外崩溃后会自动尝试恢复\n"
            "5. 每个守护周期输出一轮优化结果（周期可在设置中调整）\n"
            "⚠ 缓存类清理需要管理员权限，否则无法生效\n"
            "⚠ 在full模式下会清理刚切走或正在工作的程序以最大释放")
        self.btn_stop = ttk.Button(bf, text=tr("▶ 停止"), command=self._stop_daemon, state="disabled")
        self.btn_stop.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_stop,
            "「停止守护模式」\n"
            "1. 停止后已学习的数据会自动保存，不会丢失")
        self.btn_excl = ttk.Button(bf, text=tr("⚙ 排除"), command=self._edit_exclusion_list)
        self.btn_excl.pack(side="left", padx=(0,6))
        self._add_tip(self.btn_excl,
            "「管理不被任何形式清理的进程」\n"
            "1. 可输入进程名如 chrome.exe，不带.exe后缀会自动补全\n"
            "2. 可点击进程名后选择删除，回归可被优化的行列\n"
            "3. 添加后该进程将被完全跳过\n"
            "⚠ 若不清楚目标程序的程序名，可在进程排行列表中查找\n"
            "⚠ 排除太多程序会明显降低释放效果\n"
            "⚠ 系统核心进程始终受自动保护，无论是否在排除列表中")
        self.btn_set = ttk.Button(bf, text=tr("☰ 设置"), command=self._open_settings)
        self.btn_set.pack(side="left")
        self._add_tip(self.btn_set,
            "「打开设置面板进行配置调整」\n"
            "1. 可配置的内容：\n"
            "  · 语言 — 中英文界面即时切换\n"
            "  · 启动 — 开机自启动、自动守护与托盘最小化\n"
            "  · 窗口与托盘 — 关闭按钮行为、托盘左键行为\n"
            "  · 清理 — 6 种操作独立开关与清理深度\n"
            "  · 游戏模式 — 管理游戏进程名单\n"
            "  · 守护 — 紧急阈值、守护清理间隔\n"
            "  · 日志 — 文件日志开关\n"
            "  · 更新 — 检查更新、自动下载替换与代理地址\n"
            "  · 全局热键 — 优化/游戏模式快捷键设置\n"
            "  · 重置 — 恢复默认设置与数据\n"
            "  · 配置传输 — 导出与导入配置包")
        self.btn_log = ttk.Button(bf, text=tr("📜 学习日志"), command=self._show_learn_log)
        self.btn_log.pack(side="left", padx=(6,0))
        self._add_tip(self.btn_log,
            "「每个进程的详细学习数据」\n"
            "1. 各列含义：\n"
            "  · 样本 — 已观察到的数据量，越多判断越可靠\n"
            "  · α / β — 历史成败的累计次数，决定可信度评分\n"
            "  · 可信度 — 越高越值得清理，综合了历史表现和预期收益\n"
            "  · 收益比 — 预期释放量(MB) vs 性能代价(PF)，性价比参考\n"
            "  · 偏差 — 内存用量的异常波动程度，越大越反常\n"
            "  · 趋势 — 内存增长斜率，正数表示内存在持续增长\n"
            "  · 泄漏 — 是否疑似内存泄漏（持续增长且清完很快回涨）\n"
            "  · 清理 — 累计被清理次数\n"
            "  · 试探成功 / 失败 — 试探性清理的成败次数")

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
            "「清理模式选择」\n"
            "1. 四模式摘要：\n"
            "  · quick — 仅系统级清理，几秒完成，几乎无感知\n"
            "                   适合：随手一点，不想有任何感知\n"
            "  · normal — 进程级 + 系统级清理，对日常使用影响较小\n"
            "                      适合：日常使用，兼顾效果与流畅\n"
            "  · deep — 追加系统级深度清扫与深层回收，清理更彻底\n"
            "                  适合：内存偏紧，接受短暂变慢\n"
            "  · full — 极限释放，尽最大可能腾出内存空间，包括刚切走或正在工作的程序内存\n"
            "               适合：内存告急，需要立刻腾出最多空间\n"
            "⚠ 优化按钮和守护模式共用此设置\n"
            "⚠ 切换后清理模式将在下一轮生效，无需重启")
        # 自动持久化清理模式选择
        def _on_mode_change(*args):
            global CFG
            new_mode = self.mode_var.get()
            last_mode = getattr(self, '_last_logged_mode', '')
            if new_mode != last_mode:
                self._log(f"后续周期的清理模式调整为：{new_mode}")
                self._last_logged_mode = new_mode
            CFG["clean_mode"] = new_mode
            _save_cfg()
        self.mode_var.trace_add("write", _on_mode_change)
        self.btn_game = ttk.Button(mf, text=tr("🎮 游戏模式"), command=self._on_toggle_game)
        self.btn_game.pack(side="left", padx=(6,0))
        self._add_tip(self.btn_game,
            "「游戏模式开关」\n"
            "1. 游戏进程受完全保护，不被触碰\n"
            "2. 非游戏进程被持续清理，为游戏腾出内存\n"
            "3. 跳过全系统缓存清理，避免拖慢磁盘\n"
            f"4. 热键默认{self._hk_display('game_hotkey')}（可在设置 → 全局热键中更改）\n"
            "⚠ 程序默认不识别任何游戏——需先在设置 → 游戏模式中添加进程名\n"
            "⚠ 按程序名自动识别运行中的实例，同名程序的所有实例都会被保护\n"
            "⚠ 若不清楚目标程序的程序名，可在进程排行列表中查找")
        self.btn_rank = ttk.Button(mf, text=tr("📊 进程排行"), command=self._show_process_rank)
        self.btn_rank.pack(side="left", padx=(6,0))
        self._add_tip(self.btn_rank,
            "「所有进程当前的排行」\n"
            "1. 按指定标度按一定顺序排列\n"
            "2. 打开期间自动刷新\n"
            "3. 点击列标题可切换排序方式")
        ttk.Label(mf, text="  ").pack(side="left")

        # 统计
        sf = ttk.LabelFrame(self.root, text=tr("统计"), padding=8)
        sf.pack(fill="x", padx=12, pady=4)
        self.lbl_sb = ttk.Label(sf, text=tr("系统杂项: ") + "0"); self.lbl_sb.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_sb,
            "「系统级清理操作的总次数」\n"
            "1. 包括：\n"
            "  · 待机缓存清空\n"
            "  · 脏页写回\n"
            "  · 文件缓存清除\n"
            "  · 卷缓存刷新\n"
            "  · 注册表缓存等\n"
            "⚠ 需要管理员权限才生效\n"
            "⚠ 清理后打开大文件可能短暂变慢")
        self.lbl_tr = ttk.Label(sf, text=tr("进程: ") + "0"); self.lbl_tr.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_tr,
            "「进程闲置内存清理的总次数」\n"
            "1. 对确认值得清理的进程，程序会让系统优先回收其闲置页面\n"
            "⚠ 数字大不一定释放得多——多次清理小进程也会累加\n"
            "⚠ 参考释放量与图表趋势更有意义")
        self.lbl_fr = ttk.Label(sf, text=tr("释放: ") + "0 MB"); self.lbl_fr.pack(side="left", padx=(0,14))
        self._add_tip(self.lbl_fr,
            "「本次启动后程序累计的内存释放总量」\n"
            "1. 包括：\n"
            "  · 进程闲置内存回收\n"
            "  · 系统缓存清理等\n"
            "⚠ 释放后可用内存会立即上涨，是为系统重新分配给活跃程序")
        self.lbl_lr = ttk.Label(sf, text=tr("已学习: ") + "0"); self.lbl_lr.pack(side="right")
        self._add_tip(self.lbl_lr,
            "「已学习的进程数量」\n"
            "1. 程序持续观察每个进程的内存情况，包括：\n"
            "  · 变化趋势\n"
            "  · 波动幅度\n"
            "  · 填充速度等\n"
            "⚠ 学习越久，后续的优化决策依据越充分\n"
            "⚠ 超过 7 天无活动的进程会被自动清除")

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
        _setup_log_widget(self.log)  # 图标位对齐 + 默认图标：固定像素图标位/制表位 + 续行悬挂缩进（F52）
        # 图标推进宽预热（窗口映射后实测一次；未测到前插入路径用制表符/默认图标兜底，不会错列）
        # ⚠ 必须经 self.root.after（MemWiseGUI 是 Tk 包装类，自身没有 after/after_idle —— 2026-09-11 启动即崩）
        self.root.after(150, lambda: _log_advances(self.log, measure=True))
        self.root.after(1200, lambda: _log_advances(self.log, measure=True))
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
            self.root.after(100, _set)
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
        # tooltip 绑整行（悬浮"界面语言:"标签或下拉框都触发——单个实例挂行内全部控件）
        self._add_tip_row(lang_row,
            "「选择界面语言」\n"
            "1. 可选择：\n"
            "  · 简体中文 — 默认\n"
            "  · English — 全英文\n"
            "⚠ 切换后立即生效")
        ttk.Label(langf, text=tr("（切换后立即生效）"), foreground="#888").pack(anchor="w", pady=(4,0))

        sf = ttk.LabelFrame(inner_frame, text=tr("启动"), padding=8)
        sf.pack(fill="x", padx=12, pady=(10,4))

        # 开机自启（2026-08-15 用户决策）：移除普通权限自启（快捷方式），只保留
        # 管理员权限自启（计划任务，登录时静默最高权限运行、无 UAC）——启动文件夹
        # 旧快捷方式由 on_autostart_admin 启用时及程序启动时幂等清理（防双启动）
        asa_var = tk.BooleanVar(value=CFG.get("auto_start_admin", False))

        def _admin_task_args():
            """管理员自启计划任务的目标与参数（委托模块级 _autostart_target_args）——
            参数随「开机自启动后最小化到托盘」勾选联动（2026-09-06 审查 F4：on_autostart_admin
            与 on_minimize 共用；2026-10-15 起启动迁移也复用同一构造，杜绝漂移）"""
            return _autostart_target_args(asm_var.get())

        def on_autostart_admin():
            en = asa_var.get()
            if en:
                target, task_args = _admin_task_args()
                ok = winapi.set_auto_start_admin("MemWise", target, task_args)
                if ok:
                    # 幂等清理旧版普通自启快捷方式残留（防与新计划任务开机双启动）
                    winapi.remove_auto_start("MemWise")
                    self._log("管理员权限开机自启已启用")
                else:
                    asa_var.set(False)
                    self._log("管理员权限自启设置失败（请以管理员身份运行一次本程序）")
            else:
                winapi.remove_auto_start_admin("MemWise")
                self._log("管理员权限开机自启已关闭")
            CFG["auto_start_admin"] = en if not en or ok else False
            _save_cfg()
        ttk.Checkbutton(sf, text=tr("以管理员权限开机自启动"), variable=asa_var,
                        command=on_autostart_admin).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1],
            "「管理员权限开机自启动」\n"
            "1. 通过 Windows 计划任务实现\n"
            "2. 以最高权限启动后受限的功能可完整执行\n"
            "⚠ 系统缓存类清理需要管理员权限\n"
            "⚠ 需先以管理员身份运行过一次本程序才能启用\n"
            "⚠ 笔记本使用电池供电时同样会启动")

        asd_var = tk.BooleanVar(value=CFG.get("auto_start_daemon", False))
        def on_auto_daemon():
            CFG["auto_start_daemon"] = asd_var.get()
            _save_cfg()
        ttk.Checkbutton(sf, text=tr("启动时自动开启守护"), variable=asd_var,
                        command=on_auto_daemon).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1],
            "「程序启动后立即自动进入守护模式」\n"
            "1. 无需手动点击守护按钮，程序自启动后即在后台运行\n"
            "2. 配合「开机自启动后最小化到托盘」使用效果更佳")

        asm_var = tk.BooleanVar(value=CFG.get("auto_start_minimize", False))
        def on_minimize():
            CFG["auto_start_minimize"] = asm_var.get()
            _save_cfg()
            # 联动重建（2026-09-06 审查 F4）：管理员自启已启用时立即按新参数更新计划任务——
            # 原实现只写配置，已安装任务的 --minimized 参数不变，重启后勾选不生效
            if CFG.get("auto_start_admin"):
                target, task_args = _admin_task_args()
                if winapi.set_auto_start_admin("MemWise", target, task_args):
                    self._log("开机自启动已按新的最小化设置更新")
                else:
                    # 重建失败（权限）回退勾选，保持配置与实际任务一致（与 on_autostart_admin 失败分支同语义）
                    asm_var.set(not asm_var.get())
                    CFG["auto_start_minimize"] = asm_var.get()
                    _save_cfg()
                    self._log("管理员权限自启设置失败（请以管理员身份运行一次本程序）")
        ttk.Checkbutton(sf, text=tr("开机自启动后最小化到托盘"), variable=asm_var,
                        command=on_minimize).pack(anchor="w", pady=(2,0))
        self._add_tip(sf.winfo_children()[-1],
            "「开机自启动后自动最小化到系统托盘」\n"
            "1. 勾选后开机自启动时仅在托盘区域显示图标\n"
            "2. 双击托盘图标恢复窗口，右键弹出菜单\n"
            "⚠ 手动启动程序不受影响，窗口正常显示\n"
            "⚠ 需搭配「以管理员权限开机自启动」使用")

        # ─── 窗口与托盘（2026-08-16 归类整理：关闭行为与托盘左键行为同属窗口/托盘
        # 交互域——点窗口 X、点托盘图标；原分居"关闭行为"与"触发与日志"两栏）───
        cbf = ttk.LabelFrame(inner_frame, text=tr("窗口与托盘"), padding=8)
        cbf.pack(fill="x", padx=12, pady=(10,4))
        ca_lbl = ttk.Label(cbf, text=tr("关闭按钮行为："))
        ca_lbl.pack(anchor="w")
        self._add_tip(ca_lbl, "「点击窗口关闭按钮时的行为」\n1. 选择行为：\n  · 最小化到托盘 — 隐藏到托盘继续守护\n  · 直接退出程序 — 退出并自动保存状态\n  · 每次询问 — 弹窗选择（默认）")
        self._close_var = tk.StringVar(value=CFG.get("close_action","ask"))
        def set_ca(v):
            global CFG
            CFG["close_action"]=v
            _save_cfg()
        tips_ca = {"minimize":"「最小化到托盘」\n1. 点击关闭按钮后程序隐藏到系统托盘\n2. 守护模式继续运行，双击托盘图标可恢复窗口",
                   "exit":"「直接退出程序」\n1. 点击关闭按钮后程序完全退出\n2. 所有状态自动保存",
                   "ask":"「每次询问」\n1. 点击关闭按钮后弹窗询问\n2. 可选择最小化或退出"}
        for v, lbl in [("minimize", tr("\u6700\u5c0f\u5316\u5230\u6258\u76d8")), ("exit", tr("\u76f4\u63a5\u9000\u51fa\u7a0b\u5e8f")), ("ask", tr("\u6bcf\u6b21\u8be2\u95ee"))]:
            rb = ttk.Radiobutton(cbf, text=lbl, variable=self._close_var, value=v, command=lambda x=v: set_ca(x))
            rb.pack(anchor="w")
            if v in tips_ca:
                self._add_tip(rb, tips_ca[v])
        ta_lbl = ttk.Label(cbf, text=tr("托盘左键行为："))
        ta_lbl.pack(anchor="w", pady=(6,0))
        # 索引映射（2026-08-14 审查：显示名翻译后反查中文键在英文界面恒失败回退 show——
        # 保存/初始值一律按索引取，语言无关）
        map_vals = [("显示窗口","show"),("一键清理","clean"),("无操作","none")]
        ta_combo = ttk.Combobox(cbf, values=[tr(k) for k,_ in map_vals], state="readonly", width=20)
        ta_combo.bind("<MouseWheel>", lambda e: "break")  # 禁用滚轮：只接受点击选择，防误改
        ta_cur = CFG.get("tray_left_action","show")
        ta_idx = next((i for i,(_,v) in enumerate(map_vals) if v == ta_cur), 0)
        ta_combo.current(ta_idx)
        ta_combo.pack(fill="x", pady=(0,6))
        self._add_tip(ta_combo, "「托盘左键单击行为」\n1. 选择行为：\n  · 显示窗口 — 恢复主界面（默认）\n  · 一键清理 — 立即执行优化\n  · 无操作 — 忽略点击\n⚠ 仅在窗口隐藏时生效，任务栏存在图标时锁定")
        def set_tray_act(e):
            global CFG
            idx = ta_combo.current()
            CFG["tray_left_action"] = map_vals[idx][1] if 0 <= idx < len(map_vals) else "show"
            _save_cfg()
        ta_combo.bind("<<ComboboxSelected>>", set_tray_act)

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
        self._add_tip(cb_ews, "「释放各个进程当前未使用的闲置内存」\n"
                      "⚠ 内存压力较大时也会清理前台进程\n"
                      "⚠ 切回被清理的后台程序时可能多几百毫秒加载\n"
                      "⚠ 系统会自动按需调回，程序可正常继续使用")
        cb_sb = ttk.Checkbutton(ops_frame, text=tr("待机缓存清理"), variable=sb_var,
                                command=lambda: toggle_op("standby", sb_var))
        cb_sb.pack(anchor="w")
        self._add_tip(cb_sb, "「清空系统已缓存但暂未使用的内存页」\n"
                      "1. 是优化操作释放量的主要来源之一\n"
                      "⚠ 需要管理员权限，否则无法正常生效\n"
                      "⚠ 清理后首次打开大文件可能短暂变慢")
        cb_mp = ttk.Checkbutton(ops_frame, text=tr("脏页写回"), variable=mp_var,
                                command=lambda: toggle_op("modified", mp_var))
        cb_mp.pack(anchor="w")
        self._add_tip(cb_mp, "「将已修改但未保存的缓存页写回磁盘后释放」\n"
                      "1. 写回后页面变为干净页，系统可回收重用\n"
                      "2. 每次系统级清理均执行，不受压力阈值限制\n"
                      "⚠ 少量磁盘写入，但对固态硬盘几乎无影响")
        cb_fc = ttk.Checkbutton(ops_frame, text=tr("系统文件缓存"), variable=fc_var,
                                command=lambda: toggle_op("filecache", fc_var))
        cb_fc.pack(anchor="w")
        self._add_tip(cb_fc, "「清空系统文件读取缓存」\n"
                      "1. 在指定的收割阶段执行\n"
                      "⚠ 会降低文件操作速度直到缓存重建\n"
                      "⚠ 文件缓存重建期间磁盘性能下降")
        cb_vc = ttk.Checkbutton(ops_frame, text=tr("卷缓存刷新"), variable=vl_var,
                                command=lambda: toggle_op("volume", vl_var))
        cb_vc.pack(anchor="w")
        self._add_tip(cb_vc, "「刷新各磁盘分区的写入缓存」\n"
                      "1. 刷新后相应内存可被系统回收重用\n"
                      "⚠ 需要管理员权限，否则无法正常生效\n"
                      "⚠ 每次刷新所有分区会短暂耗时但不丢失数据")
        cb_rg = ttk.Checkbutton(ops_frame, text=tr("注册表缓存清理"), variable=rg_var,
                                command=lambda: toggle_op("registry", rg_var))
        cb_rg.pack(anchor="w")
        self._add_tip(cb_rg, "「清空系统注册表的读写缓存」\n"
                      "1. 勾选后在守护模式下始终执行\n"
                      "⚠ 无磁盘读写操作，不中断正在运行的程序")
        # quick 模式下三个开关不适用（2026-09-11 审查 F6 的界面半边）：置灰 + 说明，
        # 避免用户"勾选了却没有执行"（quick 只执行待机缓存/脏页写回/注册表缓存三项）
        if CFG.get("clean_mode", "normal") == "quick":
            for _cb in (cb_ews, cb_fc, cb_vc):
                try:
                    _cb.state(["disabled"])
                except Exception:
                    pass
            ttk.Label(cf, text=tr("quick 模式下「释放进程闲置内存」「系统文件缓存」「卷缓存刷新」不执行"),
                      foreground="#888", wraplength=470, justify="left").pack(anchor="w")
        # ─── 清理深度（2026-08-16 归类整理：清理强度归"清理"栏，原在触发与日志栏）───
        passes_val = tk.IntVar(value=CFG.get("clean_passes", 4))
        def set_passes(v):
            global CFG
            CFG["clean_passes"] = int(float(v))
            _save_cfg()
        ps_lbl = ttk.Label(cf, text=tr("进程清理深度: ") + f"{passes_val.get()} " + tr("轮"), foreground="#555")
        ps_lbl.pack(anchor="w", pady=(6,0))
        self._add_tip(ps_lbl, "「每个进程反复清理的轮数」\n1. 可设置为 2~6 轮，默认 4 轮\n2. 越高持续释放能力越高，但耗时更长\n⚠ 欲降低本程序性能占用建议 2~3\n⚠ 对于更彻底的优化需求可设 5~6\n⚠ 程序会在进程已无更多可释放内存时自动提前结束")
        ps_sl = ttk.Scale(cf, from_=2, to=6, variable=passes_val, orient="horizontal",
                         command=lambda v: ps_lbl.config(text=tr("进程清理深度: ") + f"{int(float(v))} " + tr("轮")))
        ps_sl.bind("<ButtonRelease-1>", lambda e: set_passes(passes_val.get()))
        ps_sl.pack(fill="x", pady=(0,6))
        if CFG.get("clean_mode", "normal") == "quick":
            # quick 模式零进程清理 ⇒ 深度无消费（2026-10-15 实测：quick 下 _trim_process
            # 调用 0 次，滑杆可调但完全无作用）——与上面三个开关同款置灰 + 说明
            try:
                ps_sl.state(["disabled"])
            except Exception:
                pass
            ttk.Label(cf, text=tr("quick 模式下「进程清理深度」不适用"), foreground="#888",
                      wraplength=470, justify="left").pack(anchor="w")
        ttk.Label(cf, text=tr("（未勾选 = 不执行对应系统清理）"),
                  foreground="#888").pack(anchor="w")

        # ─── 游戏模式 ───
        gmf = ttk.LabelFrame(inner_frame, text=tr("游戏模式"), padding=8)
        gmf.pack(fill="x", padx=12, pady=4)
        gmf_btns = ttk.Frame(gmf); gmf_btns.pack(fill="x")
        manage_btn = ttk.Button(gmf_btns, text=tr("管理游戏进程"), command=self._manage_game_procs)
        manage_btn.pack(side="left", padx=(0,6))
        self._add_tip(manage_btn,
            "「管理游戏模式监测的游戏进程名」\n"
            "1. 可配置的内容：\n"
            "  · 查看 — 列出全部已配置游戏进程名\n"
            "  · 添加 — 单独输入或逗号分隔批量输入，如 xxx,xxxx\n"
            "  · 删除 — 选中后删除，写错/误加/不想要随时移除\n"
            "2. 不带.exe后缀自动补全，守护模式检测到后自动开启游戏保护\n"
            "⚠ 同名程序的所有实例都会被识别，不同名则需要手动添加")

        # ─── 守护（2026-08-16 归类整理：原"触发与日志"拆分，守护运行参数独立成栏）───
        gf = ttk.LabelFrame(inner_frame, text=tr("守护"), padding=8)
        gf.pack(fill="x", padx=12, pady=4)
        def set_emerg(v):
            global CFG
            CFG["emergency_threshold"] = int(float(v))
            _save_cfg()
        em_val = tk.IntVar(value=CFG.get("emergency_threshold", 80))
        em_lbl = ttk.Label(gf, text=tr("紧急触发阈值: ") + f"{em_val.get()}%", foreground="#555")
        self._add_tip(em_lbl, "「紧急清理阈值设定」\n1. 内存使用率达到此百分比时，跳过等待立即执行全量优化\n2. 范围 50-99%，默认 80%\n3. 降低可更及时响应，提高阈值可减少清理频率")
        em_lbl.pack(anchor="w")
        em_sl = ttk.Scale(gf, from_=50, to=99, variable=em_val, orient="horizontal",
                         command=lambda v: em_lbl.config(text=tr("紧急触发阈值: ") + f"{int(float(v))}%"))
        em_sl.bind("<ButtonRelease-1>", lambda e: set_emerg(em_val.get()))  # 拖动仅更新显示，松开才保存（防高频写盘）
        em_sl.pack(fill="x", pady=(0,6))
        gap_val = tk.IntVar(value=CFG.get("gap_seconds", 12))
        def set_gap(v):
            global CFG
            CFG["gap_seconds"] = int(float(v))
            _save_cfg()
        gp_lbl = ttk.Label(gf, text=tr("周期内轻量压制间隔: ") + f"{gap_val.get()} " + tr("秒"), foreground="#555")
        gp_lbl.pack(anchor="w", pady=(6,0))
        self._add_tip(gp_lbl, "「守护模式每轮周期内的轻量阶段频率」\n"
                         "1. 可设置为 8~20 秒，默认 12 秒\n"
                         "2. 用于控制周期内清理操作的密集程度\n"
                         "3. 间隔越短清理次数越多，但性能要求更大\n"
                         "⚠ 欲降低本程序性能占用建议 15~20\n"
                         "⚠ 对于更彻底的优化需求可设 8~10")
        gp_sl = ttk.Scale(gf, from_=8, to=20, variable=gap_val, orient="horizontal",
                         command=lambda v: gp_lbl.config(text=tr("周期内轻量压制间隔: ") + f"{int(float(v))} " + tr("秒")))
        gp_sl.bind("<ButtonRelease-1>", lambda e: set_gap(gap_val.get()))
        gp_sl.pack(fill="x", pady=(0,6))
        # ─── 守护周期（2026-09-11 审查 F24 新增）：真正的"多久收割一轮" ───
        # 原先 interval 只能改配置文件，而界面上的「守护清理间隔」实际是周期内压制间隔，
        # 用户极易误解 ⇒ 补一个真正的周期控件（10-3600 秒，与 config.load 钳制同域）
        iv_val = tk.IntVar(value=CFG.get("interval", 60))
        def set_iv(*_a):
            try:
                v = int(float(iv_val.get()))
            except (TypeError, ValueError):
                v = CFG.get("interval", 60)
            v = max(10, min(3600, v))
            CFG["interval"] = v
            iv_val.set(v)
            _save_cfg()
        iv_row = ttk.Frame(gf); iv_row.pack(fill="x", pady=(6,0))
        ttk.Label(iv_row, text=tr("守护周期: "), foreground="#555").pack(side="left")
        iv_sp = ttk.Spinbox(iv_row, from_=10, to=3600, increment=10, width=7, textvariable=iv_val,
                            command=set_iv)
        iv_sp.pack(side="left", padx=(2,2))
        ttk.Label(iv_row, text=tr("秒"), foreground="#555").pack(side="left")
        iv_sp.bind("<FocusOut>", set_iv)   # 手动输入：失焦或回车生效（与热键输入同款，防高频写盘）
        iv_sp.bind("<Return>", set_iv)
        self._add_tip_row(iv_row,
            "「完整收割周期」\n"
            "1. 在设定时间内做多次轻量压制以及一次最终完整收割\n"
            "2. 可设置为 10-3600 秒，默认 60 秒\n"
            "3. 周期越短响应越及时，越长越省资源")

        # ─── 日志（2026-08-16 归类整理：独立成栏）───
        lgf = ttk.LabelFrame(inner_frame, text=tr("日志"), padding=8)
        lgf.pack(fill="x", padx=12, pady=4)
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
        lg_cb = ttk.Checkbutton(lgf, text=tr("记录运行日志到文件"),
                                variable=lg_var, command=set_log)
        lg_cb.pack(anchor="w")
        self._add_tip(lg_cb, "「记录完整运行详情」\n"
                      "1. 将运行期间的全部信息写入日志文件（memwise.log/memwise.log.1）\n"
                      "2. 包括：\n"
                      "  · 每轮清理摘要\n"
                      "  · 界面日志消息\n"
                      "  · 启动/退出\n"
                      "  · 异常\n"
                      "  · 调参\n"
                      "  · 游戏模式切换等\n"
                      "⚠ 日志自动轮转保留最近两份，无需手动清理")

        # ── 更新（2026-10-16 新增，第 11 栏）：**默认不联网**，仅开启后启动时自动检查 ──
        self._build_update_section(inner_frame)

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
                old = CFG.get(hk["key"], hk["default"])
                CFG[hk["key"]] = spec
                _save_cfg()
                st.config(text=tr("已生效"))
                # 只报实际变更的键（2026-08-30 审查 C5：未变更键不再重复播报）
                self._apply_hotkeys(changed={hk["key"]} if spec != old else set())
            e.bind("<FocusOut>", commit)
            e.bind("<Return>", commit)
            tip = (f"「{hk['name']}全局快捷键」\n"
                   f"{'1. 按此组合：立即执行一次优化' if hk['action'] == 'hotkey' else '1. 按此组合：切换游戏模式（含确认弹窗）'}\n"
                   f"2. 格式：修饰键+按键，如 {hk['default']}\n"
                   "⚠ 至少包含一个修饰键（ctrl/alt/shift）\n"
                   "⚠ 不能与其他热键相同\n"
                   "⚠ 输入后点击其他位置或按回车生效，被占用时会提示")
            # 整行覆盖（Tk Enter/Leave 不冒泡——单个实例挂行内全部控件，快速滑动单提示）
            self._add_tip_row(row, tip)

        # ─── 重置（恢复出厂设置，2026-09-06 任务3）───
        rf = ttk.LabelFrame(inner_frame, text=tr("重置"), padding=8)
        rf.pack(fill="x", padx=12, pady=4)
        reset_btn = ttk.Button(rf, text=tr("恢复默认"), command=self._on_factory_reset)
        reset_btn.pack(anchor="w")
        self._add_tip(reset_btn,
            "「重置程序所有配置」\n"
            "1. 将程序所有配置、学习数据与调参结果等恢复为默认状态\n"
            "2. 确认后将重启程序以生效默认配置\n"
            "3. 当前配置会自动备份到程序数据目录，可供再次导入\n"
            "⚠ 此操作会清除所有使用数据，恢复前会再次确认防止误触\n"
            "⚠ 请确保守护模式未运行，否则无法重置")

        # ─── 配置传输（导出/导入配置包，2026-09-06 任务3）───
        xfer = ttk.LabelFrame(inner_frame, text=tr("配置传输"), padding=8)
        xfer.pack(fill="x", padx=12, pady=4)
        xfer_btns = ttk.Frame(xfer); xfer_btns.pack(fill="x")
        export_btn = ttk.Button(xfer_btns, text=tr("导出配置"), command=self._on_export_config)
        export_btn.pack(side="left", padx=(0,6))
        self._add_tip(export_btn,
            "「将当前配置导出」\n"
            "1. 将当前全部配置、学习数据与调参结果打包导出到数据目录\n"
            "2. 导出文件可用于本机恢复，也可分享给其他用户导入")
        import_btn = ttk.Button(xfer_btns, text=tr("导入配置"), command=self._on_import_config)
        import_btn.pack(side="left")
        self._add_tip(import_btn,
            "「导入配置包数据」\n"
            "1. 从配置包导入全部配置、学习数据与调参结果\n"
            "2. 支持本程序导出与自动备份生成的配置包\n"
            "3. 导入前可先备份当前状态，导入后将重启程序生效\n"
            "⚠ 请首先将配置文件包存入导入文件夹内\n"
            "⚠ 导入会覆盖当前全部数据，若想保留当前配置请备份\n"
            "⚠ 请确认文件来源可信，警惕被植入病毒等破坏性程序")

        # 关闭按钮行为：设置即时保存，无需独立保存按钮（save_and_close 已移除）
        # 关闭前释放下拉列表 popdown 的残留 grab（ttk Combobox 展开时 grab global 独占
        # 鼠标事件——展开后点关闭会被下拉吞掉一次；收起异常时 grab 残留致多次点击失效）
        def _close_settings_win():
            try:
                g = win.grab_current()
                if g is not None and g != win:
                    g.grab_release()
            except Exception:
                pass
            win.destroy()
        win.protocol("WM_DELETE_WINDOW", _close_settings_win)
        win.bind("<Escape>", lambda e: _close_settings_win())  # Esc 直接关闭（下拉展开时由 popdown 先消费收起）
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
            # 记录切换前日志面板可见行数（重建后 log 为空，重渲染需按切换前口径取历史；
            # end-1c 含隐式终止行偏置，减 1 得真实可见行数——与 _write_group 同口径）
            try:
                self._pre_switch_log_lines = max(0, int(self.log.index('end-1c').split('.')[0]) - 1)
            except Exception:
                self._pre_switch_log_lines = 0
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
            self._draw_chart()           # 图表标题/底部指标/悬浮因子随新语言重绘
            if self.engine.daemon_running:
                self.btn_dae.configure(state="disabled"); self.btn_stop.configure(state="normal")
                self.lbl_st["text"] = tr("守护运行中")
            elif self._optimizing:
                # 手动优化进行中切换语言：新按钮保持禁用态（防重入逻辑不变，视觉一致）
                self.btn_opt.configure(state="disabled")
            self._last_msg = None  # 重建后去重上下文清零（防跨语言首条消息被误去重）
            self._update_tray_status(getattr(self, '_mem_pct', 0) or 50)  # 托盘 tip 即时刷新
            self._log_op("语言已切换")
        except Exception as e:
            import sys; print(f"[MemWise] 语言切换异常: {e}", file=_ERR)
            try:
                # 尽力恢复界面：旧控件树已销毁，重建为新语言界面（2026-08-15 审查：
                # 原实现只打日志，界面实际已损坏，"已保留原界面"名不副实）
                self._build_ui()
                self._refresh_mem()
                self._upd_stats()
                self._log_op("语言已切换")
            except Exception:
                try:
                    self._log_op("语言切换失败，请重启程序")
                except Exception:
                    pass

    # ---- 恢复默认与配置传输（2026-09-06 任务3）----

    def _center_fit(self, win, min_w=None):
        """按内容实际请求尺寸居中显示（自适应：不留白过多也不显示不全）。
        构建完成后调用，替代固定宽高的 _center_geometry。"""
        win.update_idletasks()
        w = max(win.winfo_reqwidth(), min_w or 0)
        h = win.winfo_reqheight()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        parent = win.master
        try:
            px, py = parent.winfo_x(), parent.winfo_y()
            pw, ph = parent.winfo_width(), parent.winfo_height()
            if pw < 10:
                px = py = 0
                pw, ph = sw, sh
        except Exception:
            px = py = 0
            pw, ph = sw, sh
        cx = max(0, min(px + (pw - w) // 2, sw - w))
        cy = max(0, min(py + (ph - h) // 2, sh - h))
        win.geometry(f"{w}x{h}+{cx}+{cy}")

    def _dark_message(self, title, text, kind="info", extra=None):
        """暗色信息弹窗（单按钮"确定"；extra=(标签, 回调) 时在其左侧并行第二按钮，
        如导出提示的「打开其所在位置」）——程序风格统一（替代系统原生 messagebox）。
        kind: info / warning / error，影响图标与标题色。"""
        icon = {"info": "ℹ", "warning": "⚠", "error": "❌"}.get(kind, "ℹ")
        tfg = {"info": "#4aa3ff", "warning": "#ffb84d", "error": "#ff6b6b"}.get(kind, "#e0e0e0")
        dlg = tk.Toplevel(self.root)
        dlg.withdraw()
        self._apply_icon(dlg)
        dlg.title(title)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg="#1c1c1c")
        ttk.Style().configure("DarkMsg.TFrame", background="#1c1c1c")
        top = ttk.Frame(dlg, style="DarkMsg.TFrame")
        top.pack(fill="x", padx=18, pady=(16, 2))
        ttk.Label(top, text=icon, font=("Segoe UI Emoji", 18),
                  background="#1c1c1c", foreground=tfg).pack(side="left", padx=(0, 12))
        ttk.Label(top, text=title, font=("微软雅黑", 11, "bold"),
                  background="#1c1c1c", foreground="#e0e0e0").pack(side="left")
        ttk.Label(dlg, text=text, justify="left", wraplength=440,
                  background="#1c1c1c", foreground="#aaa").pack(padx=18, pady=(2, 4))
        btn_row = ttk.Frame(dlg, style="DarkMsg.TFrame")
        btn_row.pack(pady=(6, 14))
        # extra：单个 (标签, 回调) 或列表（更新失败需同时给「打开发布页」与「复制链接」）
        _extras = extra if isinstance(extra, list) else ([extra] if extra else [])
        for _lab, _cb in _extras:
            ttk.Button(btn_row, text=tr(_lab), command=_cb).pack(side="left", padx=6)
        ttk.Button(btn_row, text=tr("确认"), command=dlg.destroy).pack(side="left", padx=6)
        self._center_fit(dlg, min_w=430)
        dlg.deiconify()
        dlg.wait_window()

    def _confirm_reset_dialog(self, title, message, extra_info=None):
        """三按钮确认弹窗（取消 / 确认并备份 / 确认但不备份）——重置与导入共用。
        返回 None（取消）/ True（确认并备份）/ False（确认但不备份）"""
        dlg = tk.Toplevel(self.root)
        dlg.withdraw()  # 先隐藏，构建完成后按内容尺寸居中一次显示
        self._apply_icon(dlg)
        dlg.title(title)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.focus_set()
        dlg.grab_set()
        dlg.configure(bg="#1c1c1c")
        ttk.Label(dlg, text=title, font=("微软雅黑", 11, "bold"),
                  background="#1c1c1c", foreground="#e0e0e0").pack(pady=(18, 4))
        body = ttk.Label(dlg, text=message, justify="left", wraplength=480,
                         background="#1c1c1c", foreground="#aaa")
        body.pack(padx=16)
        if extra_info:
            ttk.Label(dlg, text=extra_info, justify="left", wraplength=480,
                      background="#1c1c1c", foreground="#6a6a6a").pack(padx=16, pady=(6, 0))
        result = {"value": None}
        btn = ttk.Frame(dlg, style="Dark.TFrame"); btn.pack(pady=14)
        ttk.Style().configure("Dark.TFrame", background="#1c1c1c")
        def _pick(v):
            result["value"] = v; dlg.destroy()
        ttk.Button(btn, text=tr("取消"), command=lambda: _pick(None)).pack(side="left", padx=6)
        ttk.Button(btn, text=tr("确认并备份"), command=lambda: _pick(True)).pack(side="left", padx=6)
        ttk.Button(btn, text=tr("确认但不备份"), command=lambda: _pick(False)).pack(side="left", padx=6)
        self._center_fit(dlg, min_w=500)
        dlg.deiconify()
        dlg.wait_window()
        return result["value"]

    def _confirm_dialog(self, title, message, icon="warning"):
        """两按钮暗色确认弹窗（确认/取消）——程序风格统一（替代系统原生 askyesno）。
        返回 True（确认）/ False（取消）。与 _confirm_reset_dialog 同视觉语言。"""
        dlg = tk.Toplevel(self.root)
        dlg.withdraw()
        self._apply_icon(dlg)
        dlg.title(title)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.focus_set()
        dlg.grab_set()
        dlg.configure(bg="#1c1c1c")
        ttk.Style().configure("DarkMsg.TFrame", background="#1c1c1c")
        ttk.Style().configure("Dark.TFrame", background="#1c1c1c")
        _ic = {"info": "ℹ", "warning": "⚠", "error": "❌"}.get(icon, "⚠")
        _tfg = {"info": "#4aa3ff", "warning": "#ffb84d", "error": "#ff6b6b"}.get(icon, "#ffb84d")
        top = ttk.Frame(dlg, style="DarkMsg.TFrame")
        top.pack(fill="x", padx=18, pady=(16, 2))
        ttk.Label(top, text=_ic, font=("Segoe UI Emoji", 18),
                  background="#1c1c1c", foreground=_tfg).pack(side="left", padx=(0, 12))
        ttk.Label(top, text=title, font=("微软雅黑", 11, "bold"),
                  background="#1c1c1c", foreground="#e0e0e0").pack(side="left")
        ttk.Label(dlg, text=message, justify="left", wraplength=440,
                  background="#1c1c1c", foreground="#aaa").pack(padx=18, pady=(2, 4))
        result = {"value": False}
        btn = ttk.Frame(dlg, style="Dark.TFrame"); btn.pack(pady=14)
        def _pick(v):
            result["value"] = v; dlg.destroy()
        ttk.Button(btn, text=tr("取消"), command=lambda: _pick(False)).pack(side="left", padx=6)
        ttk.Button(btn, text=tr("确认"), command=lambda: _pick(True)).pack(side="left", padx=6)
        self._center_fit(dlg, min_w=430)
        dlg.deiconify()
        dlg.wait_window()
        return result["value"]

    def _ask_string_dialog(self, title, prompt):
        """暗色单行输入弹窗（确认/取消，回车确认、Esc 取消）——程序风格统一
        （替代系统原生 askstring）。返回输入串（取消返回 None；空串原样返回，由调用方判空）"""
        dlg = tk.Toplevel(self.root)
        dlg.withdraw()
        self._apply_icon(dlg)
        dlg.title(title)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.focus_set()
        dlg.grab_set()
        dlg.configure(bg="#1c1c1c")
        ttk.Style().configure("DarkMsg.TFrame", background="#1c1c1c")
        ttk.Style().configure("Dark.TFrame", background="#1c1c1c")
        box = ttk.Frame(dlg, style="DarkMsg.TFrame")
        box.pack(fill="x", padx=18, pady=(16, 2))
        ttk.Label(box, text="⚠", font=("Segoe UI Emoji", 18),
                  background="#1c1c1c", foreground="#ffb84d").pack(side="left", padx=(0, 12))
        ttk.Label(box, text=title, font=("微软雅黑", 11, "bold"),
                  background="#1c1c1c", foreground="#e0e0e0").pack(side="left")
        ttk.Label(dlg, text=prompt, justify="left", wraplength=380,
                  background="#1c1c1c", foreground="#aaa").pack(padx=18, pady=(2, 4))
        ent = tk.Entry(dlg, width=30, bg="#2a2a2a", fg="#e0e0e0", insertbackground="#e0e0e0",
                       relief="flat", highlightthickness=1, highlightbackground="#444",
                       highlightcolor="#419EF3", font=("Microsoft YaHei", 10))
        ent.pack(padx=18, pady=(6, 2), ipady=4)
        result = {"value": None}
        def _ok(_e=None):
            result["value"] = ent.get(); dlg.destroy()
        def _cancel(_e=None):
            dlg.destroy()
        ent.bind("<Return>", _ok)
        ent.bind("<Escape>", _cancel)
        btn = ttk.Frame(dlg, style="Dark.TFrame"); btn.pack(pady=(6, 14))
        ttk.Button(btn, text=tr("取消"), command=_cancel).pack(side="left", padx=6)
        ttk.Button(btn, text=tr("确认"), command=_ok).pack(side="left", padx=6)
        self._center_fit(dlg, min_w=380)
        dlg.deiconify()
        ent.focus_set()
        dlg.wait_window()
        return result["value"]

    def _restart_with_new_config(self):
        """重启生效的统一收尾：事件留痕（crash 通道不受日志开关控制）+ 统一日志
        → 启动新实例（backup.restart_application 以 argv 直启，新实例带 --delay-start 3
        自行等待——期间当前实例完全退出、互斥锁与窗口随进程释放，新实例检查干净通过）
        → 移除托盘图标 → 立即优雅关闭自身：不保存任何状态（需要丢弃的正是旧
        状态，此路径无 save_state 钩子），句柄正常释放让 PyInstaller bootloader
        干净清理临时目录（延迟启动同时错开杀软对新旧实例的扫描窗口）"""
        _log_write("系统", tr("即将重启程序以生效新配置…"))
        _event_log("主动重启：重置/导入配置生效，程序退出以启动新实例")
        backup.restart_application()
        try:
            winapi.tray_remove(self.root.winfo_id(), TRAY_UID)
        except Exception:
            pass
        self.root.destroy()

    def _on_factory_reset(self):
        if self.engine.daemon_running:
            self._dark_message(tr("重置"),
                tr("守护模式运行中，无法恢复默认——请先停止守护"), kind="warning")
            return
        choice = self._confirm_reset_dialog(tr("恢复默认"),
            tr("确认将全部配置、学习数据与调参结果恢复为默认状态？\n"
               "选择\"确认并备份\"会先把当前状态保存为配置包（可供再次导入），"
               "选择\"确认但不备份\"将直接清除。"))
        if choice is None:
            return
        backup.reset_factory(backup=choice)
        self._restart_with_new_config()

    def _on_export_config(self):
        p, missing = backup.export_state("export")
        if p is None:
            self._dark_message(tr("导出配置"),
                tr("无法导出：程序尚未生成任何状态文件"), kind="error")
            return
        msg = tr_msg(f"配置包已导出: {p}")
        if missing:
            msg += "\n" + tr("缺少：") + "、".join(missing)
        msg += "\n" + tr("可在程序数据目录的 import_export 文件夹找到，也可导入恢复")

        def _open_pkg_folder():
            import subprocess
            # /select：资源管理器打开所在文件夹并选中该配置包（引号兼容路径空格）
            subprocess.Popen(f'explorer /select,"{p}"')
        self._dark_message(tr("导出配置"), msg, kind="info",
                           extra=("打开其所在位置", _open_pkg_folder))

    def _on_import_config(self):
        if self.engine.daemon_running:
            self._dark_message(tr("导入配置"),
                tr("守护模式运行中，无法导入配置——请先停止守护"), kind="warning")
            return
        idir = backup.import_export_dir()
        # 导入候选 = import_export 目录全部 zip（导出包/自动备份包/用户放入的包三合一）
        candidates = sorted(
            (os.path.join(idir, f) for f in (os.listdir(idir) if os.path.isdir(idir) else [])
             if f.lower().endswith(".zip")),
            key=os.path.getmtime, reverse=True)
        if not candidates:
            self._dark_message(tr("导入配置"),
                tr_msg(f"导入文件夹中没有配置包，请先将 .zip 配置包放入：\n{idir}"),
                kind="warning")
            return
        # 多包选择（显示文件名）
        picked = {"name": None}
        sel = tk.Toplevel(self.root)
        sel.withdraw()
        self._apply_icon(sel)
        sel.title(tr("选择配置包"))
        sel.resizable(False, False)
        sel.transient(self.root)
        sel.grab_set()
        sel.configure(bg="#1c1c1c")
        ttk.Label(sel, text=tr("导入文件夹中的配置包："), background="#1c1c1c",
                  foreground="#e0e0e0").pack(anchor="w", padx=14, pady=(14, 4))
        lb = tk.Listbox(sel, width=52, height=9, selectbackground="#419EF3",
                        activestyle="none")
        lb.pack(fill="both", expand=True, padx=14)
        for c in candidates:
            lb.insert("end", os.path.basename(c))
        lb.selection_set(0)
        def _ok():
            s = lb.curselection()
            if s:
                picked["name"] = candidates[s[0]]
            sel.destroy()
        bf = ttk.Frame(sel); bf.pack(pady=10)
        ttk.Button(bf, text=tr("确认"), command=_ok).pack(side="left", padx=6)
        ttk.Button(bf, text=tr("取消"), command=sel.destroy).pack(side="left", padx=6)
        self._center_fit(sel, min_w=460)
        sel.deiconify()
        sel.wait_window()
        if not picked["name"]:
            return
        pkg = picked["name"]  # 候选列表存完整路径（import_export 目录）
        manifest, errors = backup.validate_package(pkg)
        if errors:
            self._dark_message(tr("导入配置"), "\n".join(errors), kind="error")
            return
        src = tr("备份") if manifest.get("source") == "backup" else tr("导出")
        info = tr_msg(f"包来源：{src} · 导出时间：{manifest.get('exported_at', '')}"
                      f" · 程序版本：{manifest.get('app_version', '')}")
        choice = self._confirm_reset_dialog(tr("导入配置"),
            tr("确认导入该配置包？\n当前全部配置、学习数据与调参结果将被覆盖。\n"
               "选择\"确认并备份\"会先保存当前状态（可供再次导入）。"), extra_info=info)
        if choice is None:
            return
        try:
            _ok, _err = backup.import_state(pkg, backup=choice)
        except Exception as _e:
            # 校验与导入之间包可能被替换/杀软瞬时锁文件——失败必须有提示且不重启
            self._dark_message(tr("导入配置"), tr_msg(f"导入失败：{_e}"), kind="error")
            return
        if not _ok:
            self._dark_message(tr("导入配置"), _err, kind="error")
            return
        self._restart_with_new_config()

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
            # 弹窗标题/提示必须随界面语言（2026-08-15 审查：原未包 tr，英文界面残留中文，键已存在）
            name = self._ask_string_dialog(tr("添加排除"), tr("输入程序名（不带后缀自动补全）:"))
            if name:
                nm = _normalize_proc_name(name)
                if nm in never:
                    self._dark_message(tr("已存在"), tr_msg(f"「{nm}」已在排除列表中"), kind="warning")
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
            # 存**原始数值**（排序按数值而非显示字符串），显示时再格式化
            info_data.append((name, p.alpha, p.beta, p.total_samples,
                              float(p.thompson_theta), float(p.roi),
                              float(p.z_score), float(p.slope), bool(p.leak_suspect),
                              p.clean_count, p.probe_ok, p.probe_fail))
        if not info_data:
            self._dark_message(tr("学习日志"), tr("还没有学习到任何数据，先运行一会儿优化再来看"))
            return

        def _fmt_row(r):
            # α/β 两位小数（原始浮点会有十几位、列被撑宽且不可读）；趋势按 MB（原始为字节数）
            return (r[0], "%.2f" % r[1], "%.2f" % r[2], r[3], "%.2f" % r[4], "%.1f" % r[5],
                    "%.1f" % r[6], "%.1f" % (r[7] / (1 << 20)), tr("是") if r[8] else tr("否"),
                    r[9], r[10], r[11])

        win = tk.Toplevel(self.root)
        win.withdraw()  # 先隐藏，构建完成居中后一次显示
        self._apply_icon(win)
        win.title(tr_msg(f"学习日志 — {len(info_data)} 个进程"))
        win.transient(self.root)
        win.focus_set()
        win.lift()
        cols = (tr("进程"), "α", "β", tr("样本"), tr("可信度"), tr("收益比(MB/PF)"), tr("偏差"),
                tr("趋势"), tr("泄漏"), tr("清理"), tr("试探成功"), tr("试探失败"))
        rows = [_fmt_row(r) for r in info_data]
        # ① 列宽：进程列按内容宽度的 90 分位（防个别超长名把列撑成"长条"），其余列按实测最大值
        widths = _tree_measure_columns(cols, rows, p90_cols=(0,), floor=44)
        # ② 窗口宽按用户定稿 = 各列实测总宽的 0.6 倍；各列等比收敛，但**不低于不裁字的紧凑宽**
        _tight = _tree_measure_columns(cols, rows, pad=10, p90_cols=(0,))
        widths = [max(int(w * 0.6), t) for w, t in zip(widths, _tight)]
        _win_w = max(560, sum(widths) + 42)
        _cap = int(win.winfo_screenwidth() * 0.94)
        if _win_w > _cap:
            _win_w = _cap
        _center_geometry(win, _win_w, 650)
        # 口径说明（2026-09-26 用户反馈"看不懂"）：只加说明层，不改任何计算口径与列名；
        # 按语义分行书写 ⇒ 任何窗口宽度下都不会在句子中间折行
        ttk.Label(win, text=tr("怎么看这张表：只列出反馈 ≥2 次的进程。\n"
                               "α/β＝清理成功/失败的累积证据，样本＝反馈次数，"
                               "可信度＝据此抽样的优先分（越大越倾向清它）。\n"
                               "收益比＝每单位缺页代价换回的释放量；偏差＝释放表现的异常程度，"
                               "趋势＝近期走向；泄漏＝疑似只涨不落；清理/试探成功/试探失败＝历史次数"),
                  wraplength=max(560, min(max(560, _win_w - 34), sum(widths))), justify="left",
                  foreground="#555").pack(anchor="w", padx=12, pady=(10, 0))
        tree = ttk.Treeview(win, columns=cols, show="headings", height=20)
        for i, c in enumerate(cols):
            tree.heading(c, text=c, command=lambda _c=c: _click_sort(_c))
            tree.column(c, width=widths[i], anchor="w" if i == 0 else "center")
        vsb = ttk.Scrollbar(win, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(12, 4))
        vsb.pack(side="right", fill="y", pady=(12, 4))
        _row_by_iid = {}
        for r, disp in zip(info_data, rows):
            _row_by_iid[tree.insert("", "end", values=disp)] = r
        # 点击列头排序（2026-09-26 用户要求：与进程排行同款）——状态按**列索引**（语言无关）
        _sort_state = {"idx": None, "rev": True}

        def _click_sort(col):
            idx, rev = _tree_sort_toggle(_sort_state, cols, col)
            _tree_sort_by(tree, _row_by_iid, idx, reverse=rev)

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
                self._dark_message(tr("已存在"), tr_msg(f"以下进程已在名单中：\n{', '.join(dup)}"), kind="warning")
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
            if not self._confirm_dialog(tr("删除游戏进程"),
                    tr_msg(f"确定移除「{name}」吗？")):
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

        cols = (tr("进程"), tr("进程号"), tr("内存占用"), tr("工作集"), tr("CPU占用"), tr("上限 (MB)"), tr("学习"))
        tree = ttk.Treeview(win, columns=cols, show="headings", height=25)
        # 列配置按索引（不依赖显示名——语言切换后列名变化，按中文名判断会全部失效）
        for i, c in enumerate(cols):
            tree.heading(c, text=c, command=lambda _c=c: _sort_tree(_c))
            if i == 0:
                tree.column(c, width=250, anchor="w")      # 进程名列：靠左
            else:
                tree.column(c, width=[70, 120, 90, 70, 70, 60][i - 1], anchor="center")  # 其余列居中

        vsb = ttk.Scrollbar(win, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True, padx=(12,0), pady=(12,4))
        vsb.pack(side="right", fill="y", pady=(12,4))

        # 排序状态变量（默认按内存降序；列索引——2026-08-14 审查：语言切换后列名变化，
        # 按显示名 set 会 TclError（英文界面每 3s 一次），索引语言无关）
        _sort_col_idx = 2  # 0=进程 1=进程号 2=内存占用(提交) 3=工作集 4=CPU占用 5=上限 6=学习
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
                self._dark_message(tr("禁止终止"), tr("不能终止系统进程或自身"), kind="warning")
                return
            # 终止流程四弹窗统一程序暗色风格（2026-09-28 用户要求；替代系统原生 messagebox）
            ok = self._confirm_dialog(tr("终止进程"),
                tr_msg(f"确定要终止「{name}」(PID={pid}) 吗？\n\n该操作会强制结束进程，未保存的数据可能丢失。"))
            if ok:
                if winapi.terminate_process(pid):
                    self._dark_message(tr("已完成"), tr_msg(f"进程「{name}」已终止"))
                    _refresh()
                else:
                    self._dark_message(tr("失败"), tr_msg(f"无法终止进程「{name}」\n可能权限不足或进程已退出"), kind="error")

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

        _refresh_ms = 10000  # 自动刷新间隔（守护运行中读共享快照零额外采集；非守护低频自采）
        _first_refresh = True  # 首帧强制采集：打开即显示（2026-08-16 热补丁——原 viewable 检查
        # 在 withdraw 期跳过首帧（_refresh 先于 deiconify 调用），打开白屏且要等下个周期才有数据）

        def _refresh():
            nonlocal _first_refresh
            if not win.winfo_exists():
                return
            # 窗口最小化/隐藏时暂停采集（仅续期定时器）——首帧除外（打开时需立即显示数据）
            if not _first_refresh and not win.winfo_viewable():
                win.after(_refresh_ms, _refresh)
                return
            _first_refresh = False
            try:
                if self.engine.daemon_running:
                    # 守护运行中直接读守护线程共享快照（零额外采集，2026-08-15 审查）
                    snaps = getattr(self.engine, '_last_snaps', None) or self.sniffer.snapshot()
                else:
                    snaps = self.sniffer.snapshot()
            except Exception as e:
                import sys; print(f"[MemWise] _refresh sniffer error: {e}", file=_ERR)
                win.after(_refresh_ms, _refresh)
                return
            for item in tree.get_children():
                tree.delete(item)
            try:
                caps = CFG.get("ws_caps") or {}
                applied = getattr(self.engine, "_ws_cap_applied", {}) or {}
                for s in snaps:
                    commit_mb = s.priv / (1 << 20)
                    ws_col = f"{s.ws / (1 << 20):.0f} MB"
                    p = self.learner.get_profile(s.name)
                    # 已学习标记与学习日志同口径（≥2 样本，2026-08-30 审查：原 3 两处不一致）
                    learned = "✓" if p and p.total_samples >= 2 else ""
                    # 硬上限列：规则存在即显示（判定门按规则口径）；空 = 未钉
                    spath = getattr(s, "path", None)
                    norm = spath.lower().replace("/", "\\") if spath else ""
                    cap_cell = str(caps[norm]["mb"]) if norm in caps else ""
                    tree.insert("", "end", values=(
                        s.name, s.pid, f"{commit_mb:.0f} MB", ws_col,
                        f"{s.cpu:.1f}%", cap_cell, learned))
                # 应用用户选择的排序（列索引，语言无关）
                if _sort_col_idx is not None:
                    items = [(tree.set(k, cols[_sort_col_idx]), k) for k in tree.get_children("")]
                    items.sort(key=lambda x: _sort_key_c(x[0]), reverse=_sort_rev)
                    for i2, (_, k) in enumerate(items):
                        tree.move(k, "", i2)
            except Exception as e:
                import sys; print(f"[MemWise] _refresh data error: {e}", file=_ERR)
            win.after(_refresh_ms, _refresh)
            self.root.after(10, _restore_hover)

        _refresh()
        # ── 右键菜单：工作集硬上限（高级选项，设计 v2.4）──
        _rctx = {"pid": None, "path": None}
        _rmenu = tk.Menu(win, tearoff=0)

        def _rank_menu(event):
            row = tree.identify_row(event.y)
            if not row:
                return
            tree.selection_set(row)
            vals = tree.item(row, "values")
            try:
                _rctx["pid"] = int(vals[1])
            except (ValueError, TypeError):
                return
            _rctx["path"] = winapi.get_process_path(_rctx["pid"])
            has = bool(_rctx["path"]) and _rctx["path"].lower().replace("/", "\\") in (CFG.get("ws_caps") or {})
            _rmenu.entryconfig(0, state="normal" if not has else "disabled")
            _rmenu.entryconfig(1, state="normal" if has else "disabled")
            try:
                _rmenu.tk_popup(event.x_root, event.y_root)
            finally:
                _rmenu.grab_release()

        _rmenu.add_command(label=tr("设置工作集硬上限…"),
                           command=lambda: self._ws_cap_set_dialog(_rctx["pid"], _rctx["path"]))
        _rmenu.add_command(label=tr("解除工作集硬上限"),
                           command=lambda: self._ws_cap_clear_dialog(_rctx["path"]))
        _rmenu.add_separator()
        _rmenu.add_command(label=tr("管理规则…"), command=self._manage_ws_caps)
        tree.bind("<Button-3>", _rank_menu)
        win.deiconify()  # 全部控件就绪，居中后一次显示

    # ---- 工作集硬上限（高级选项，设计 v2.0-v2.5）----

    def _ws_cap_set_dialog(self, pid, path):
        """设置工作集硬上限：实况三行 + 输入 + 强制确认勾选（v2.4）。
        pid 实时复验（v2.1 R6：快照 PID 可能已被复用）。"""
        if not pid or not path:
            return
        path_now = winapi.get_process_path(pid)
        if not path_now or path_now.lower().replace("/", "\\") != path.lower().replace("/", "\\"):
            self._dark_message(tr("工作集硬上限"),
                               tr_msg(f"进程已退出或身份已变化（{path}）"), kind="warning")
            return
        base = path_now.rsplit("\\", 1)[-1]
        norm = path_now.lower().replace("/", "\\")
        if _is_self_path(path_now) or _is_system_core(base):
            self._dark_message(tr("工作集硬上限"), tr("不能对本程序或系统核心进程设置"), kind="warning")
            return
        if self.judger._is_system_path(path_now):
            self._dark_message(tr("工作集硬上限"), tr("系统目录下的进程不可设置"), kind="warning")
            return
        if base in (_normalize_proc_name(g) for g in (CFG.get("game_processes") or [])):
            self._dark_message(tr("工作集硬上限"), tr("不能对游戏名单中的程序设置"), kind="warning")
            return
        mem = winapi.get_process_memory(pid)
        ws_mb = (mem["ws"] >> 20) if mem else 0
        commit_mb = (mem["priv"] >> 20) if mem else 0
        caps = CFG.get("ws_caps") or {}
        rule = caps.get(norm)
        quota = winapi.get_process_ws_quota(pid)

        dlg = tk.Toplevel(self.root)
        dlg.withdraw()
        self._apply_icon(dlg)
        dlg.title(tr("工作集硬上限"))
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg="#1c1c1c")
        cap_now = tr("未设置") if rule is None else f"{rule['mb']} MB"
        ttk.Label(dlg, text=tr("工作集硬上限"), font=("微软雅黑", 11, "bold"),
                  background="#1c1c1c", foreground="#e0e0e0").pack(pady=(16, 2))
        # 动态拼接行（数值随进程变化）⇒ 必须换行，否则会被弹窗边界裁剪（2026-10-17 全界面巡检）
        ttk.Label(dlg, text=tr("工作集: ") + f"{ws_mb} MB · " + tr("提交内存: ") + f"{commit_mb} MB · "
                  + tr("上限: ") + cap_now, background="#1c1c1c", foreground="#aaa",
                  justify="left", wraplength=400).pack()
        row = ttk.Frame(dlg, style="Dark.TFrame"); row.pack(pady=(10, 2))
        ttk.Label(row, text=tr("上限（MB）："), background="#1c1c1c", foreground="#e0e0e0").pack(side="left")
        _default = max(256, ((ws_mb + 127) // 128) * 128)
        ent = ttk.Spinbox(row, from_=256, to=8192, increment=128, width=8)
        ent.set(_default); ent.pack(side="left", padx=(4, 0))
        ttk.Style().configure("DarkW.TCheckbutton", background="#1c1c1c", foreground="#ffb84d")
        ack_var = tk.BooleanVar(value=False)

        def _confirm():
            try:
                mb = max(256, min(8192, int(float(ent.get()))))
            except (TypeError, ValueError):
                return
            ok, reason, orig_max = winapi.set_ws_cap(pid, mb << 20)
            if not ok:
                self._dark_message(tr("工作集硬上限"), tr_msg(reason), kind="error")
                return
            CFG.setdefault("ws_caps", {})[norm] = {"mb": mb, "orig_max": int(orig_max)}
            _save_cfg()
            self.engine.ws_cap_rule_added(norm, int(orig_max), pid)
            self._log(f"⛨ 已设置工作集硬上限（{mb}MB）：{base}")
            dlg.destroy()
        btn = ttk.Frame(dlg, style="Dark.TFrame"); btn.pack(pady=(8, 14))
        btn_ok = ttk.Button(btn, text=tr("确认"), command=_confirm, state="disabled")
        btn_ok.pack(side="left", padx=6)
        ttk.Button(btn, text=tr("取消"), command=dlg.destroy).pack(side="left", padx=6)

        def _ack():
            btn_ok.state(["!disabled"] if ack_var.get() else ["disabled"])
        ttk.Checkbutton(dlg, style="DarkW.TCheckbutton", variable=ack_var, command=_ack,
                        text=tr("我了解这会使该程序在访问被换出的内存时变卡")).pack(pady=(6, 2))
        dlg.deiconify()
        self._center_fit(dlg, min_w=430)
        dlg.wait_window()

    def _ws_cap_clear_dialog(self, path):
        if not path:
            return
        norm = path.lower().replace("/", "\\")
        if not self._confirm_dialog(tr("解除工作集硬上限"),
                                    tr_msg(f"确定解除「{path}」的工作集硬上限？学习数据会重新开始。")):
            return
        caps = CFG.get("ws_caps") or {}
        if norm not in caps:
            return
        del caps[norm]
        _save_cfg()
        self.engine.ws_cap_rule_removed(norm)
        self._log(f"⛨ 已解除 {os.path.basename(path)} 的工作集硬上限（学习数据已重置）")
        # 目标未在运行时 disable 无从下手——如实提示残留边界（设计 §七）
        if not any(getattr(s, "path", None) and s.path.lower().replace("/", "\\") == norm
                   for s in self.sniffer.snapshot()):
            self._log("目标程序未在运行，重启后上限自动失效")

    def _manage_ws_caps(self):
        """规则管理窗口：列出/删除（添加入口=进程排行右键，设计 v2.4）。"""
        win = tk.Toplevel(self.root)
        win.withdraw()
        self._apply_icon(win)
        win.title(tr("工作集硬上限规则"))
        win.transient(self.root)
        win.grab_set()
        win.configure(bg="#1c1c1c")
        cols = (tr("程序路径"), tr("上限 (MB)"), tr("状态"))
        tree = ttk.Treeview(win, columns=cols, show="headings", height=10)
        tree.heading(cols[0], text=cols[0]); tree.column(cols[0], width=380, anchor="w")
        tree.heading(cols[1], text=cols[1]); tree.column(cols[1], width=90, anchor="center")
        tree.heading(cols[2], text=cols[2]); tree.column(cols[2], width=110, anchor="center")
        tree.pack(fill="both", expand=True, padx=12, pady=(12, 4))

        def _refresh():
            for i in tree.get_children():
                tree.delete(i)
            caps = CFG.get("ws_caps") or {}
            applied = getattr(self.engine, "_ws_cap_applied", {}) or {}
            for path, rule in sorted(caps.items()):
                if not os.path.isfile(path):
                    st = tr("路径不存在")
                elif applied.get(path):
                    st = tr("生效中")
                else:
                    st = tr("等待目标进程")
                tree.insert("", "end", values=(path, rule.get("mb"), st))

        def _del():
            sel = tree.selection()
            if not sel:
                return
            path = tree.item(sel[0], "values")[0]
            norm = path.lower().replace("/", "\\")
            if not self._confirm_dialog(tr("删除规则"), tr_msg(f"确定删除「{path}」的规则吗？")):
                return
            caps = CFG.get("ws_caps") or {}
            caps.pop(path, None)
            _save_cfg()
            self.engine.ws_cap_rule_removed(path)
            self._log(f"⛨ 已解除 {os.path.basename(path)} 的工作集硬上限（学习数据已重置）")
            # 目标未在运行时 disable 无从下手（无簿记 pid）——如实提示残留边界（设计 §七）
            if not any(getattr(s, "path", None) and s.path.lower().replace("/", "\\") == norm
                       for s in self.sniffer.snapshot()):
                self._log("目标程序未在运行，重启后上限自动失效")
            _refresh()
        btn = ttk.Frame(win, style="Dark.TFrame"); btn.pack(pady=(2, 4))
        ttk.Button(btn, text=tr("删除规则"), command=_del).pack(side="left", padx=4)
        ttk.Label(win, text=tr("在进程排行中右键可添加规则；上限作用于物理占用，提交内存不变"),
                  background="#1c1c1c", foreground="#888", wraplength=460).pack(pady=(0, 10))

        def _auto():
            """规则状态 5 秒自刷新（守护施加后 等待→生效 自动流转）"""
            if win.winfo_exists():
                _refresh()
                win.after(5000, _auto)
        _refresh()
        win.after(5000, _auto)
        self._center_fit(win, min_w=520)
        win.deiconify()

    # ---- 日志 / 状态 ----

    def _write_group(self, msgs, to_file=True):
        """分组原子写入日志面板（2026-08-30 分组语义，三种写入路径统一走此原语）：
        · 组 = 逻辑上同批的消息集合，一次清屏判断后整组输出，绝不逐行判断
          （防组内前半截被清屏自食——原逐行 _log 输出名单实测只剩最后 1-2 个）
        · 组行数按实际渲染行数计（内嵌换行的消息按多行计，"实际多少行就多少行"）
        · 组间规则：面板现有行数 + 组行数 ≤7 → 接续输出；>7 → 清屏后整组输出
        · 组内可超 7 行：大组（结果卡/守护批量）清屏后全部行完整呈现，不被阈值截断
        · 连续完全相同的单条消息跳过（2026-08-30：启动观察消息实测重复，去重守卫）
        历史缓存照常累积（语言切换重渲染源）；to_file=False 为纯显示模式
        （周期摘要/EFIS 消息已有 [清理]/[调参] 直写，避免双通道重复落盘）"""
        # 连续重复去重：单条消息与上一条完全相同则跳过
        if len(msgs) == 1 and msgs[0] == self._last_msg:
            return
        for m in msgs:
            self._log_history.append(m)
        self.log.configure(state="normal")
        try:
            # Tk Text 末尾恒有隐式终止行：end-1c 比可见行数大 1——减 1 得真实可见行数
            # （旧三路径各自带此偏置判断，阈值实际漂移 1 行；2026-08-30 统一修正）
            cur_lines = max(0, int(self.log.index('end-1c').split('.')[0]) - 1)
        except Exception:
            cur_lines = 0
        if _panel_needs_clear(cur_lines, _msg_lines(msgs)):
            self.log.delete("1.0", "end")
        for m in msgs:
            _insert_log_lines(self.log, time.strftime('%H:%M:%S'), _align_log_line(tr_msg(m)), _LOG_TAG)
        self.log.see("end")
        self.log.configure(state="disabled")
        self._last_msg = msgs[-1] if msgs else None
        if to_file and CFG.get("log_to_file"):
            for m in msgs:
                _log_write("界面", m)

    def _log_op(self, m):
        """即时事件（单行组）——分组语义见 _write_group"""
        self._write_group([m])

    def _log_batch(self, msgs, to_file=True):
        """批量组输出——分组语义见 _write_group"""
        self._write_group(msgs, to_file)

    def _log(self, m):
        """实时日志（单行组）——分组语义见 _write_group"""
        self._write_group([m])

    def _rerender_log(self):
        """语言切换后按新语言重渲染日志面板——按切换前可见行数取历史尾部
        （面板已重建为空，不能依赖当前行数；取多了上限 300 条历史缓存）"""
        try:
            cur_lines = getattr(self, '_pre_switch_log_lines', 0)
            if cur_lines <= 0:
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
                _insert_log_lines(self.log, time.strftime('%H:%M:%S'), _align_log_line(tr_msg(m)), _LOG_TAG)
            self.log.see("end")
            self.log.configure(state="disabled")
        except Exception:
            pass

    def _readd_tray(self):
        """资源管理器重启后重挂托盘图标（2026-09-11 审查 F7）。
        复用已缓存的 HICON（零新增 GDI 对象），随后按当前内存状态刷新颜色与提示。"""
        try:
            hwnd = int(self.root.winfo_id())
            if winapi.tray_add(hwnd, TRAY_UID, self._tray_icon_handle, tr("MemWise — 智能内存看护")):
                self._update_tray_status(getattr(self, '_mem_pct', 0) or 50)
        except Exception:
            pass

    # ══════════ 更新检查（2026-10-16 用户逐项定稿）══════════
    # **默认不联网**：仅当 CFG["update_check"] 开启（或用户点「检查更新」）才发起请求。
    # 流程：后台检查 → 弹窗（立即更新/稍后/跳过此版本）→ 下载（进度）→ SHA-256 校验
    #       → 5 秒倒计时 → 启动新版 exe 当"更新助手"（--apply-update）→ 本进程退出。
    # 失败：降级为提示 + 「打开发布页/复制链接」；自动检查失败只写日志（不打扰）。
    # 额外提醒（用户指定）：日志面板一行 + 设置面板「有新版本 vX」常驻状态行（弹窗是主提醒）。

    def _build_update_section(self, parent):
        """构建设置面板「更新」栏（2026-10-16；抽成方法便于回归用真实 Tk 构建一次）。

        ⚠ 血泪约束：**ttk.Frame / ttk.LabelFrame 不支持 `background=`**（`TclError: unknown option`）——
        2026-10-16 发布后事故：本栏原先给 ttk.Frame 传了 background，导致 `_open_settings` 一构建即抛异常，
        **设置按钮直接打不开**。回归只做静态断言所以漏掉了；现已改为"真实构建一次"的烟测（见 test_regression）。"""
        upf = ttk.LabelFrame(parent, text=tr("更新"), padding=8)
        upf.pack(fill="x", padx=12, pady=4)
        upd_var = tk.BooleanVar(value=CFG.get("update_check", False))
        upa_var = tk.BooleanVar(value=CFG.get("update_auto_apply", True))
        upd_proxy_var = tk.StringVar(value=CFG.get("update_proxy", ""))

        def _on_upd_toggle():
            CFG["update_check"] = upd_var.get()
            _save_cfg()
            if upd_var.get():
                self._upd_check(manual=True)      # 开启即立即查一次，给用户即时反馈

        def _on_upd_auto():
            CFG["update_auto_apply"] = upa_var.get()
            _save_cfg()

        def _on_upd_proxy(_e=None):
            CFG["update_proxy"] = upd_proxy_var.get().strip()
            _save_cfg()

        self.lbl_upd = ttk.Label(upf, text=self._upd_status_init(), foreground="#aaa")
        self.lbl_upd.pack(anchor="w")
        row_up = ttk.Frame(upf)
        row_up.pack(anchor="w", pady=(4, 0))
        btn_upd = ttk.Button(row_up, text=tr("检查更新"), command=lambda: self._upd_check(manual=True))
        btn_upd.pack(side="left")
        # 勾选框自成一行（2026-10-17 用户反馈：与按钮同排时文字被挤，且与下方开关的行式不一致）
        cb_upd = ttk.Checkbutton(upf, text=tr("启动时自动检查更新"), variable=upd_var,
                                 command=_on_upd_toggle)
        cb_upd.pack(anchor="w", pady=(2, 0))
        cb_auto = ttk.Checkbutton(upf, text=tr("发现新版本时自动下载并替换重启"), variable=upa_var,
                                  command=_on_upd_auto)
        cb_auto.pack(anchor="w", pady=(2, 0))
        row_px = ttk.Frame(upf)
        row_px.pack(anchor="w", pady=(2, 0), fill="x")
        lbl_px = ttk.Label(row_px, text=tr("代理地址"), foreground="#aaa")
        lbl_px.pack(side="left")
        ent_px = ttk.Entry(row_px, textvariable=upd_proxy_var, width=24)
        ent_px.pack(side="left", padx=(6, 0))
        ent_px.bind("<FocusOut>", _on_upd_proxy)
        # 提示独立成行（2026-10-16 用户反馈：与输入框同排会被面板宽度截断，只剩"(留空 ="）
        lbl_hint = ttk.Label(upf, text=tr("留空则自动使用系统代理"), foreground="#777")
        lbl_hint.pack(anchor="w", pady=(2, 0))
        # tooltip **按功能分发**（2026-10-17 用户反馈：全文案共享到每个位置"偏颇"、且同屏出现两个提示框）。
        # 两条纪律：①每个可交互控件挂**与自己相关**的提示 ②同一控件只挂一次（重复挂载是同屏重影的根因）
        self._add_tip(btn_upd,
            "「检查更新」\n"
            "1. 立即向官方发布渠道（GitHub）查询是否有更高版本\n"
            "2. 只读取版本号与下载信息，不发送设备信息\n"
            "⚠ 仅在点击时联网，平时不产生任何网络请求")
        self._add_tip(cb_upd,
            "「启动时自动检查更新」\n"
            "1. 开启后每次启动都会自动查询一次\n"
            "2. 手动检查不受此开关影响，随时可用\n"
            "⚠ 默认关闭，不开启时程序完全不联网")
        self._add_tip(cb_auto,
            "「发现新版本时自动下载并替换重启」\n"
            "1. 自动下载并校验更新包完整性，通过后才替换程序并重启\n"
            "2. 配置与学习数据原样保留\n"
            "⚠ 关闭时只给出提示，由你手动下载安装\n"
            "⚠ 校验不通过会自动放弃，保留当前版本")
        self._add_tip_row(row_px,
            "「代理地址」\n"
            "1. 一般留空即可，由系统自动选择合适的通道\n"
            "2. 仅在系统自动通道不可用时才需要填写")

    def _upd_status_init(self):
        """设置面板打开时的初始状态行（读运行态：上次检查/跳过版本 → 给一句人话）。"""
        st = self._upd_state()
        last = st.get("last_check") or 0
        if not last:
            return tr("尚未检查更新")
        import datetime as _dt
        return tr("上次检查：") + _dt.datetime.fromtimestamp(last).strftime("%Y-%m-%d %H:%M")


    def _upd_state(self):
        if self._upd_st is None:
            self._upd_st = _update.load_state(base)
        return self._upd_st

    def _upd_status(self, text):
        """设置面板状态行（不存在/已销毁则忽略——状态行只在设置窗口打开时存在）。"""
        try:
            lbl = getattr(self, "lbl_upd", None)
            if lbl is not None and lbl.winfo_exists():
                lbl["text"] = text
        except Exception:
            pass

    def _upd_check(self, manual=False):
        """发起检查。manual=True 为用户主动点按钮（忽略自动检查开关与节流）。"""
        if self._upd_busy:
            return
        if not getattr(sys, "frozen", False):
            if manual:
                self._dark_message(tr("检查更新"), tr("源码运行模式没有可替换的 exe，更新功能仅正式版可用"))
            return
        if not manual and not CFG.get("update_check", False):
            return
        self._upd_busy = True
        if manual:
            self._upd_status(tr("正在检查更新…"))
        threading.Thread(target=self._upd_worker, args=(manual,), daemon=True).start()

    def _upd_worker(self, manual):
        try:
            # 每次启动都检查（2026-10-16 用户定稿：不再按 7 天节流）；last_check 仍记录，
            # 供设置面板显示"上次检查"用。手动检查同样忽略任何节流。
            st = self._upd_state()
            info = _update.check_latest(proxy=(CFG.get("update_proxy") or "").strip() or None)
            st["last_check"] = time.time()
            _update.save_state(base, st)
            if not info.get("ok"):
                self._msg_queue.put(("upd_failed", {"manual": manual, "reason": info.get("reason") or "unknown"}))
            else:
                self._msg_queue.put(("upd_result", {"manual": manual, "info": info}))
        except Exception:
            self._msg_queue.put(("upd_failed", {"manual": manual, "reason": "exception"}))
        finally:
            self._upd_busy = False

    def _on_update_result(self, d):
        info = d.get("info") or {}
        manual = d.get("manual")
        tag = info.get("tag") or ""
        ver = info.get("version")
        if not _update.is_newer(tag, APP_VERSION):
            self._upd_status(tr("已是最新版本"))
            if manual:
                self._log("检查更新：已是最新版本（当前 v%s）" % APP_VERSION)
            return
        self._upd_status(tr("有新版本可用") + " " + tag)
        self._log("发现新版本 %s（当前 v%s）" % (tag, APP_VERSION))
        st = self._upd_state()
        if str(ver) == str(st.get("skip_version") or ""):
            return                      # 用户已"跳过此版本" ⇒ 不再弹窗（状态行与日志仍保留）
        if not CFG.get("update_auto_apply", True):
            self._dark_message(tr("发现新版本"),
                tr_msg("发现新版本 %s（当前 v%s，%.1f MB）。\n\n可在设置中开启「自动下载并替换」。"
                       % (tag, APP_VERSION, (info.get("size") or 0) / 1048576.0)),
                extra=(tr("打开发布页"), self._open_release_page))
            return
        # 侧视补（2026-10-16）：**没有校验信息就绝不自动装**——HTTPS 只保证链路，哈希才是锚；
        # 目录不可写/权限不足同样不下载（省一次 12MB 下载，也避免"装完才知道装不了"）。
        if not info.get("sha256"):
            self._dark_message(tr("发现新版本"),
                tr_msg("发现新版本 %s（当前 v%s）。\n\n此版本未提供校验信息，为安全起见不自动更新，请手动下载。"
                       % (tag, APP_VERSION)),
                kind="warning", extra=(tr("打开发布页"), self._open_release_page))
            return
        if not getattr(self, "_writable", True):
            self._dark_message(tr("发现新版本"),
                tr_msg("发现新版本 %s，但程序所在目录不可写，无法自动替换。\n\n请手动下载后覆盖安装。" % tag),
                kind="warning", extra=(tr("打开发布页"), self._open_release_page))
            return
        choice = self._choice_dialog(tr("发现新版本"), self._update_prompt_text(info),
                                     [(tr("立即更新"), "now"), (tr("稍后"), "later"), (tr("跳过此版本"), "skip")])
        if choice == "later" or choice is None:
            self._log("更新已推迟（下次启动仍会提示）")
            return
        if choice == "skip":
            st["skip_version"] = str(ver)
            _update.save_state(base, st)
            self._log("已跳过版本 %s（此后不再弹窗）" % tag)
            self._upd_status(tr("有新版本可用") + " " + tag)
            return
        self._start_download(info)

    def _update_prompt_text(self, info):
        tag = info.get("tag")
        mb = (info.get("size") or 0) / 1048576.0
        body = tr_msg("发现新版本 %s（当前 v%s，%.1f MB）" % (tag, APP_VERSION, mb))
        notes = (info.get("notes") or "").strip()
        if notes:
            body += "\n\n" + (notes[:360] + ("…" if len(notes) > 360 else ""))
        return body

    def _start_download(self, info):
        if self._upd_downloading:
            return                          # 侧视补：下载中禁止再次触发（防双下载/双进度窗）
        url = info.get("url")
        if not url:
            self._on_update_failed({"manual": True, "reason": "no_asset_url"})
            return
        # 文件名只保留安全字符（tag 来自远端，不直接拼进路径）
        _safe = "".join(c for c in str(info.get("tag") or "new").lstrip("v") if c.isalnum() or c in "._-") or "new"
        dest = os.path.join(tempfile.gettempdir(), "MemWise_%s.exe" % _safe)
        self._upd_cancel = False
        self._upd_downloading = True
        self._upd_prog = self._progress_dialog(info)
        self._log("开始下载更新 %s（%.1f MB）" % (info.get("tag"), (info.get("size") or 0) / 1048576.0))
        threading.Thread(target=self._download_worker, args=(info, url, dest), daemon=True).start()

    def _download_worker(self, info, url, dest):
        def _prog(done, total):
            self._msg_queue.put(("upd_progress", {"done": done, "total": total or (info.get("size") or 0)}))
        ok, why = _update.download(url, dest, sha256=info.get("sha256"), size=info.get("size"),
                                   proxy=(CFG.get("update_proxy") or "").strip() or None,
                                   progress=_prog, cancel=lambda: self._upd_cancel)
        if ok:
            self._msg_queue.put(("upd_ready", {"dest": dest, "tag": info.get("tag")}))
        else:
            self._msg_queue.put(("upd_failed", {"manual": True, "reason": why}))

    def _on_update_progress(self, d):
        if self._upd_prog is not None:
            try:
                self._upd_prog.set(d.get("done", 0), d.get("total", 0))
            except Exception:
                pass

    def _on_update_ready(self, d):
        self._upd_downloading = False
        if self._upd_prog is not None:
            try:
                self._upd_prog.close()
            except Exception:
                pass
            self._upd_prog = None
        dest, tag = d.get("dest"), d.get("tag")
        self._log("更新包校验通过（%s）" % tag)
        if not self._countdown_dialog(5):
            self._log("已取消重启，本次更新作废（下次启动仍会提示）")
            try:
                os.remove(dest)
            except Exception:
                pass
            return
        self._apply_and_exit(dest)

    def _apply_and_exit(self, dest):
        """启动新版 exe 作"更新助手"，随后本进程优雅退出（释放互斥与文件锁）。"""
        # 更新是用户的显式操作 ⇒ 重启后**把界面露出来**，不继承"最小化到托盘"
        # （此前会沿用本进程的 --minimized，用户更新完找不到窗口，2026-10-17 用户反馈）
        args = [dest, "--apply-update", os.path.abspath(sys.executable), str(os.getpid())]
        try:
            env = {k: v for k, v in os.environ.items() if not k.startswith(("_MEI", "_PYI"))}
            subprocess.Popen(args, creationflags=0x08000000,
                             cwd=os.path.dirname(os.path.abspath(sys.executable)), env=env)
        except Exception:
            self._on_update_failed({"manual": True, "reason": "spawn_helper_failed"})
            return
        self._log("即将重启完成更新…")
        try:
            remove_watchdog()   # 关键：先摘看门狗——否则它会把这次"退出"当崩溃并抢先拉起旧版
        except Exception:
            pass
        try:
            winapi.tray_remove(self.root.winfo_id(), TRAY_UID)
        except Exception:
            pass
        # 与 _do_exit 完全一致的优雅收尾（侧视修正 2026-10-16：原先只 destroy ⇒ 会丢未落盘的
        # 学习/ERIS 状态，且守护与清理线程被硬杀）。顺序：停守护与线程池 → 存配置 → 落状态 → 关窗。
        try:
            self.engine.shutdown()
        except Exception:
            pass
        try:
            _save_cfg()
            self.engine.save_state()
        except Exception:
            pass
        self.root.destroy()

    def _on_update_failed(self, d):
        manual, why = d.get("manual"), d.get("reason") or "unknown"
        self._upd_downloading = False
        if str(why).split(":")[0] == "cancelled":
            self._log("已取消更新")      # 侧视补：用户主动取消不该报「失败」
            return
        if self._upd_prog is not None:
            try:
                self._upd_prog.close()
            except Exception:
                pass
            self._upd_prog = None
        self._log("更新失败：%s" % why)
        if not manual:
            return                          # 自动检查失败：只留日志，不弹窗（用户指定"降级提示"仅限手动/下载阶段）
        self._upd_status(tr("更新检查失败"))
        self._dark_message(tr("更新失败"),
            tr_msg("更新失败：%s\n\n可手动前往官方发布页下载新版本。" % _upd_reason_text(why)),
            kind="warning",
            extra=[(tr("打开发布页"), self._open_release_page), (tr("复制链接"), self._copy_link)])

    def _open_release_page(self):
        try:
            ctypes.windll.shell32.ShellExecuteW(None, "open", _update.RELEASES_PAGE, None, None, 1)
        except Exception:
            pass

    def _copy_link(self):
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(_update.RELEASES_PAGE)
        except Exception:
            pass

    def _choice_dialog(self, title, text, options, kind="info"):
        """通用暗色多按钮弹窗（options=[(标签, 返回值)]）：返回被点中的值；关闭 ⇒ None。"""
        res = {"v": None}
        dlg = tk.Toplevel(self.root)
        dlg.withdraw()
        self._apply_icon(dlg)
        dlg.title(title)
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg="#1c1c1c")
        ttk.Style().configure("DarkUpd.TFrame", background="#1c1c1c")
        top = ttk.Frame(dlg, style="DarkUpd.TFrame")
        top.pack(fill="x", padx=18, pady=(16, 2))
        icon = {"info": "ℹ", "warning": "⚠", "error": "❌"}.get(kind, "ℹ")
        tfg = {"info": "#4aa3ff", "warning": "#ffb84d", "error": "#ff6b6b"}.get(kind, "#e0e0e0")
        ttk.Label(top, text=icon, font=("Segoe UI Emoji", 18), background="#1c1c1c",
                  foreground=tfg).pack(side="left", padx=(0, 12))
        ttk.Label(top, text=title, font=("微软雅黑", 11, "bold"), background="#1c1c1c",
                  foreground="#e0e0e0").pack(side="left")
        # 长正文（如发布说明）用只读可滚动文本：段落多时不会再让弹窗高过屏幕；
        # 短文本仍用 Label（居中与换行更自然）。（2026-10-17 用户要求可滚动查看完整说明）
        if len(text) > 220:
            holder = ttk.Frame(dlg, style="DarkUpd.TFrame")
            holder.pack(fill="x", padx=18, pady=(4, 6))
            body = tk.Text(holder, height=12, width=52, wrap="word", bd=0, highlightthickness=0,
                           background="#1c1c1c", foreground="#aaa", font=("微软雅黑", 9))
            sb = ttk.Scrollbar(holder, orient="vertical", command=body.yview)
            body.configure(yscrollcommand=sb.set)
            body.insert("1.0", text)
            body.configure(state="disabled")
            body.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
        else:
            ttk.Label(dlg, text=text, justify="left", wraplength=470, background="#1c1c1c",
                      foreground="#aaa").pack(padx=18, pady=(4, 6))
        row = ttk.Frame(dlg, style="DarkUpd.TFrame")
        row.pack(pady=(4, 14))

        def _pick(v):
            res["v"] = v
            try:
                dlg.destroy()
            except Exception:
                pass
        for label, value in options:
            ttk.Button(row, text=label, command=lambda v=value: _pick(v)).pack(side="left", padx=6)
        dlg.protocol("WM_DELETE_WINDOW", lambda: _pick(None))
        self._center_fit(dlg, min_w=470)
        dlg.deiconify()
        dlg.wait_window()
        return res["v"]

    def _progress_dialog(self, info):
        """下载进度弹窗（非模态，可取消）。返回带 set(done,total)/close() 的句柄。"""
        dlg = tk.Toplevel(self.root)
        dlg.withdraw()
        self._apply_icon(dlg)
        dlg.title(tr("正在下载更新"))
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.configure(bg="#1c1c1c")
        ttk.Label(dlg, text=tr("正在下载更新") + "  " + str(info.get("tag") or ""),
                  font=("微软雅黑", 11, "bold"), background="#1c1c1c",
                  foreground="#e0e0e0").pack(padx=18, pady=(16, 2))
        lbl = ttk.Label(dlg, text="0.0 / %.1f MB" % ((info.get("size") or 0) / 1048576.0),
                        background="#1c1c1c", foreground="#aaa")
        lbl.pack(padx=18, pady=(0, 6))
        cv = tk.Canvas(dlg, width=380, height=10, bg="#2a2a2a", highlightthickness=0)
        cv.pack(padx=18, pady=(0, 10))
        bar = cv.create_rectangle(0, 0, 0, 10, fill="#4aa3ff", width=0)

        def _cancel():
            self._upd_cancel = True
            self._log("已取消下载更新")
            try:
                dlg.destroy()
            except Exception:
                pass
        ttk.Button(dlg, text=tr("取消"), command=_cancel).pack(pady=(0, 14))
        self._center_fit(dlg, min_w=420)
        dlg.deiconify()
        holder = {"dlg": dlg}

        def _set(done, total):
            d = holder.get("dlg")
            if d is None or not d.winfo_exists():
                return
            total = total or 0
            frac = min(1.0, (done / total)) if total else 0.0
            cv.coords(bar, 0, 0, int(380 * frac), 10)
            lbl["text"] = ("%.1f / %.1f MB（%d%%）" % (done / 1048576.0, total / 1048576.0, int(frac * 100))
                           if total else "%.1f MB" % (done / 1048576.0))

        def _close():
            d = holder.get("dlg")
            holder["dlg"] = None
            if d is not None:
                try:
                    d.destroy()
                except Exception:
                    pass
        cls = type("_UpdProg", (), {})
        cls.set = staticmethod(_set)
        cls.close = staticmethod(_close)
        return cls

    def _countdown_dialog(self, seconds):
        """倒计时弹窗（默认 5 秒后继续；可取消或立即重启）。返回 True=继续更新。"""
        res = {"go": False}
        dlg = tk.Toplevel(self.root)
        dlg.withdraw()
        self._apply_icon(dlg)
        dlg.title(tr("即将重启完成更新"))
        dlg.resizable(False, False)
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.configure(bg="#1c1c1c")
        ttk.Style().configure("DarkUpd2.TFrame", background="#1c1c1c")
        ttk.Label(dlg, text=tr("即将重启完成更新"), font=("微软雅黑", 11, "bold"),
                  background="#1c1c1c", foreground="#4aa3ff").pack(padx=18, pady=(16, 4))
        cnt = ttk.Label(dlg, text="", background="#1c1c1c", foreground="#aaa",
                        justify="left", wraplength=430)   # 文案随守护状态变长 ⇒ 必须换行（2026-10-17 用户反馈被裁）
        cnt.pack(padx=18, pady=(0, 6))
        row = ttk.Frame(dlg, style="DarkUpd2.TFrame")
        row.pack(pady=(2, 14))

        _daemon_on = bool(getattr(self.engine, "daemon_running", False))

        def _go():
            res["go"] = True
            try:
                dlg.destroy()
            except Exception:
                pass

        def _tick(n):
            if not dlg.winfo_exists():
                return
            cnt["text"] = tr_msg("将在 %d 秒后自动重启完成更新" % n) + (tr("（守护会随重启短暂中断，随后自动恢复）") if _daemon_on else "")
            if n <= 0:
                _go()
                return
            dlg.after(1000, lambda: _tick(n - 1))
        ttk.Button(row, text=tr("立即重启"), command=_go).pack(side="left", padx=6)
        ttk.Button(row, text=tr("取消"), command=dlg.destroy).pack(side="left", padx=6)
        self._center_fit(dlg, min_w=430)
        dlg.deiconify()
        _tick(seconds)
        dlg.wait_window()
        return res["go"]

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
                elif action == 'readd':
                    self._readd_tray()   # 资源管理器重启：重挂托盘图标（2026-09-11 审查 F7）
        except Exception:
            pass
        # ── 消息队列 ──
        try:
            while True:
                action, args = self._msg_queue.get_nowait()
                if action == 'log': self._log(args)
                elif action == 'log_batch': self._log_batch(args)
                elif action == 'display_groups':
                    # 周期末打包整体（2026-08-30 修正）：所有子组合并为一个大整体做一次
                    # 清屏判定——大整体对外遵循组间规则（现有行数+总行数>7 → 清屏），
                    # 大整体内部零刷新、全部行完整输出；否则同周期内前几个组会被后组清掉
                    self._write_group([m for g in args for m in g], to_file=False)  # 仅显示：内容已有 [清理]/[调参] 直写落盘
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
                elif action == 'upd_result': self._on_update_result(args)
                elif action == 'upd_progress': self._on_update_progress(args)
                elif action == 'upd_ready': self._on_update_ready(args)
                elif action == 'upd_failed': self._on_update_failed(args)
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
            # after 链防叠加（2026-09-06 审查）：重入（语言切换/异常兜底再次调用本方法）
            # 先取消旧调度再排新，恒保持单条 2s 链——原实现每次调用叠加一条并行链，
            # 切 N 次语言后 N+1 条链同时刷新，开销随切换次数累积
            try:
                if getattr(self, "_refresh_mem_id", None):
                    self.root.after_cancel(self._refresh_mem_id)
            except Exception:
                pass
            self._refresh_mem_id = self.root.after(2000, self._refresh_mem)

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
        # Y 轴标注 & 网格
        for i, lbl_v in [(0, 0), (1, max_val//2), (2, max_val)]:
            if i == 0:
                lbl = "0"
            elif lbl_v >= 1000:
                # GB 段显示规则（2026-09-06 用户定稿）：换算值 ≥10 四舍五入取整
                # （10.0GB→10GB，防止一位小数多出的字符使十位/百位溢出标度区）；
                # <10 保留一位小数（5.3GB）。两个标度（一半/最高）同规则
                _gb_v = lbl_v / 1024.0
                lbl = f"{_gb_v:.0f}GB" if _gb_v >= 10 else f"{_gb_v:.1f}GB"
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
                over_100 = round(r_eff) >= 100          # 与显示值一致（四舍五入）
                cy = py1 - (min(e_val, 100.0) / 100.0) * ph
                r = 4
                if over_100:
                    dot_fill = "#D4A017"
                elif round(r_eff) <= 50:                 # 与显示值一致（消除'珊瑚点却无警告'）
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
                # 因子存原文、显示时翻译（切换语言后已存因子跟随当前语言）
                factor_str = "\n" + " ".join(tr_msg(f) if isinstance(f, str) else str(f)
                                             for f in factors[idx])
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
        if self._optimizing or getattr(self, '_once_optimizing', False):
            return
        if self.engine.daemon_running:
            # 守护运行中：按当前选择的清理模式执行一次即时优化（与守护周期经 exec_lock 串行）
            if self.cleaner.game_mode:
                self._log("游戏进行中，跳过手动清理以保障流畅")
                return
            self._once_optimizing = True  # 防连点排队多轮即时优化（_opt_done 统一复位）
            # 即时反馈（2026-08-30）：守护分支原点击后零提示，完成前数秒界面无响应痕迹
            self._log_op(f"⚡ 即时优化（{CFG.get('clean_mode', 'normal')}）已启动")
            self.lbl_st["text"] = tr("⚡ 即时优化中…")  # 下一守护周期 upd_ui 自动恢复
            self.engine.optimize_manual_once(CFG.get("clean_mode", "normal"),
                                             CFG.get("clean_operations"))
            return
        self._optimizing = True
        self.btn_opt.configure(state="disabled"); self.lbl_st["text"] = tr("优化中...")
        self._log_op(f"开始优化（{CFG.get('clean_mode', 'normal')}·三轮）…")
        self.engine.optimize_manual_async(CFG.get("clean_mode", "normal"),
                                          CFG.get("clean_operations"))

    def _opt_done(self, result):
        self._once_optimizing = False  # 即时优化完成/异常均发 opt_done，此处统一复位
        s = self.cleaner.summary()
        trimmed = [t for t in result.get("layer2", []) if t[1]]
        released = result.get("released", 0.0)
        net = result.get("net", 0)
        p0, p1 = result.get("pct0"), result.get("pct1")
        # 结果卡（2026-08-30）：单批次整卡替换面板——原逐行 _log 会被 7 行清屏阈值
        # 自食（实测 10 个名字最终只剩 1-2 个可见），整卡输出名单恒完整；
        # 名单按单进程释放量降序取头部（用户最关心谁被清得最多）+ 余量聚合行
        pct_str = f"（可用 {p0}%→{p1}%）" if p0 is not None and p1 is not None else ""
        # 释放量拆解（2026-09-11 用户定稿）：系统缓存与进程分列再给合计——否则第一行的大数字
        # 会被读成"下面这几条进程清出来的"，而系统缓存通道（待机/文件缓存等）才是大头。
        # 进程部分 = Layer2 成功项释放量求和，其余归系统级通道；两者之和恒等于 released。
        _proc_mb = min(released, sum(t[2] for t in result.get("layer2", []) if t[1]) / (1 << 20))
        _sys_mb = max(0.0, released - _proc_mb)
        card = [f"⚡ {result.get('mode', '')} 优化完成 · 系统缓存 {_sys_mb:.0f} MB"
                f" + 进程 {_proc_mb:.0f} MB = 共 {released:.0f} MB"
                f" · 净下降 {net / (1 << 20):.0f} MB{pct_str}"]
        by_freed = sorted(trimmed, key=lambda t: -t[2])
        for snap, _ok, freed, _reason in by_freed[:4]:
            card.append(f"  ✓ {snap.name} (PID={snap.pid}) {freed / (1 << 20):.0f} MB")
        if len(by_freed) > 4:
            card.append(f"✓ 其余 {len(by_freed) - 4} 个进程")
        elif not by_freed:
            card.append("没有找到值得清理的进程（全部受保护或无闲置内存）")
        self._log_batch(card, to_file=True)
        # 统计栏始终显示程序运行以来累计总量
        winapi.report_event("MemWise", tr_msg(f"GUI 优化: {s['freed_mb']}MB 释放, {len(trimmed)} 进程"))
        self._upd_stats()
        if self.engine.daemon_running:
            # 守护运行中的即时优化：按钮/状态栏由守护周期维护，只更新统计与日志
            return
        self._optimizing = False
        self.btn_opt.configure(state="normal")
        self.lbl_st["text"] = tr("就绪 · ") + self._hk_display()

    # ---- 守护 ----

    def _on_daemon(self, log_msg=None):
        if self.engine.daemon_running: return
        if self._optimizing:
            self._log_op("手动优化进行中，请等待完成后再启动守护")
            return
        if not self.engine.start_daemon():  # 含防双守护/CLI 互斥与周期基线/图表/ERIS 状态重置
            if getattr(self.engine, '_daemon_busy_cli', False):
                self._log_op("命令行守护模式运行中，无法开启界面守护")
            else:
                self._log_op("上一守护线程仍在收尾，请稍候再试")
            return
        self.btn_dae.configure(state="disabled"); self.btn_stop.configure(state="normal")
        self.lbl_st["text"] = tr("守护运行中")
        self._log_op(log_msg or "守护模式启动")  # 崩溃恢复路径传恢复文案（单条不重复；均为中文原文）
        _update_watchdog_daemon(True)  # 崩溃恢复时据此续守护

    def _upd_dae_ui(self, s, m, txt="🟢 守护中"):
        self.lbl_sb["text"] = tr("系统杂项: ") + fmt_count(s['standby'] + s.get('modified',0) + s.get('filecache',0) + s.get('registry',0) + s.get('volume',0))
        self.lbl_tr["text"] = tr("进程: ") + fmt_count(s['ws_trim'])
        fm = s['freed_mb']
        self.lbl_fr["text"] = tr("释放: ") + (f"{fm/1024.0:.1f}GB" if fm >= 1000 else f"{fm:.1f}MB")
        self._upd_learned()  # 守护中持续学习新进程，已学习数随周期刷新
        pct = m["pct"]
        # 四档与内存条/托盘口径一致（60/75/90，2026-08-15 审查：原三档 70/90 与托盘不一致）
        icon = "🟢" if pct < 60 else ("🟡" if pct < 75 else ("🟠" if pct < 90 else "🔴"))
        # 引擎载荷恒带图标前缀（历史格式）：剥掉后再前置四档图标，避免同屏双图标
        _body = tr(txt)
        if _body and _log_is_icon(_body[0]):
            _body = _body[1:].lstrip()
        self.lbl_st["text"] = f"{icon} {_body} {pct}%"

    def _stop_daemon(self):
        if not self.engine.daemon_running: return
        self._log_op("停止守护中..."); self.engine.stop_daemon()

    def _dae_stopped(self):
        _update_watchdog_daemon(False)  # 守护已停止：崩溃恢复不应续守护
        self.btn_dae.configure(state="normal"); self.btn_stop.configure(state="disabled")
        err = getattr(self.engine, '_dae_error', None)
        if err:
            self.lbl_st["text"] = tr("⚠ 守护异常")
            # 同批原子输出（2026-08-30 分组语义）：头行+详情一组——拆散时边界下面板
            # 恰满 6 行会让 ❌ 头行被滚动清掉、只剩详情
            self._log_batch(["❌ 守护异常，详见下方错误信息", f"🔍 {err}"])
            del self.engine._dae_error
        else:
            self.lbl_st["text"] = tr("就绪 · ") + self._hk_display(); self._log_op("守护已停止")
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
        """崩溃恢复：仅当 watchdog.json 记录崩溃前守护运行中才自动续守护。
        恢复提示单条合并（2026-08-30 审查 C2：原"守护模式启动"+"从崩溃中恢复"两条语义重叠）"""
        try:
            if read_watchdog_daemon():
                self._on_daemon(log_msg="🔄 从崩溃中恢复 — 守护模式已自动继续")
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
    # 更新助手分支：必须在**任何初始化之前**退出（不建 GUI、不取单实例互斥、不写运行态）
    if "--apply-update" in sys.argv:
        sys.exit(_apply_update(sys.argv))
    # 更新后清理（能跑到这里说明当前版本启动正常 ⇒ 上一轮的 .old 备份已完成使命）：
    # 只动我们自己的产物（<exe>.old / <exe>.new / %TEMP%/MemWise_*.exe[.part]），绝不触碰用户文件。
    _update_housekeeping()
    # 重启路径：先睡再初始化（必须在 init_runtime / 单实例互斥之前——否则会与
    # 尚未退出的旧实例抢互斥）。正常启动无该参数，行为零变化。
    _delay = _parse_delay_start(sys.argv)
    if _delay > 0:
        time.sleep(_delay)
    MemWiseGUI().run()
