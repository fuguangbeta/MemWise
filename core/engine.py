"""
MemWise 无 UI 引擎 —— 守护循环 / ERIS / 轮次数据 / 事件队列 / 看门狗
与展示层（tkinter GUI）解耦：GUI 只消费 events 与数据快照。
本文件为纯搬移（原 memwise_gui.py 内逻辑逐行迁移，不改行为），仅一处设计变更：
ERIS 计算时机从"图表渲染时"改为"轮次数据产生时"（消除渲染时序耦合，见 _push_round）。
"""

import os, sys, time, threading, queue, concurrent.futures, datetime, atexit, ctypes, subprocess
from collections import deque

# ── 数据/资源路径（与原 GUI 同规则：exe 旁；dist 目录特判上移）──
# 进程级副作用（DPI 感知 + 目录预建）改为显式调用 init_runtime()（2026-09-11 审查 F38）：
# 原先在 import 时执行 ⇒ 任何 `import core.engine`（例如 CLI 只想取守护互斥名/常量）都会
# 设置进程 DPI 并创建目录，使"库导入"变成有副作用的初始化。现在由入口显式触发。
def init_runtime():
    """进程级初始化：DPI 感知 + 数据/配置目录预建 + 旧根目录数据一次性迁移。
    必须在任何状态文件读写之前调用（GUI __init__ 首行 / CLI main 首段）；幂等。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    _migrate_runtime_data()
    _cleanup_stale_tmp()


def _cleanup_stale_tmp():
    """清掉数据/配置目录里中断的原子写残留（*.tmp 与旧版命名的 *.import-tmp）——
    2026-09-26 实测发现 `data/memwise_state.json.<pid>.tmp` 0 字节残留（写盘中断）。
    只删**超过 10 分钟**的残留（活跃进程自己的临时文件不可能这么久），逐个记诊断。"""
    try:
        import glob as _glob, time as _time
        # data/ 是状态文件原子写的落点；config/ 是导入配置包 tmp 的落点；
        # *.import-tmp 是旧版命名在升级用户机器上的残留——三者同属一份清理契约
        for f in (_glob.glob(os.path.join(base, "data", "*.tmp"))
                  + _glob.glob(os.path.join(base, "data", "*.import-tmp"))
                  + _glob.glob(os.path.join(base, "config", "*.tmp"))
                  + _glob.glob(os.path.join(base, "config", "*.import-tmp"))):
            try:
                if _time.time() - os.path.getmtime(f) > 600:
                    os.remove(f)
                    _diag_log("清理中断写入残留: %s" % os.path.basename(f))
            except Exception:
                pass
    except Exception:
        pass

if getattr(sys, "frozen", False):
    exe_dir = os.path.dirname(sys.executable)
    # exe 在 dist 目录下时，用项目根目录做数据目录，与脚本共用状态文件
    if os.path.basename(exe_dir).lower() == "dist":
        base = os.path.dirname(exe_dir)
    else:
        base = exe_dir
else:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base not in sys.path:
    sys.path.insert(0, base)

# ═══ 看门狗（进程级，UI 无关）：崩溃自动重启 + 守护状态记录 ═══
DAEMON_MUTEX_NAME = "Global\\MemWise_Daemon"  # 守护本体互斥（2026-09-06 审查 F3：
# 防 CLI daemon 与 GUI 守护并发——双进程同时写同一状态文件，进程内锁不跨进程会交错
# 损坏画像唯一副本；GUI 查看与手动优化不受影响，mutex 仅在守护运行期间持有）


def _watchdog_path():
    """看门狗状态文件路径：运行时数据统一在 data/ 目录（base/data，dist 部署时在项目根 data/；
    主进程与 watchdog 子进程同 exe → 同路径）"""
    return os.path.join(base, "data", "watchdog.json")


def _migrate_runtime_data():
    """启动即预建数据/配置目录（新机器冷启动自动建目录）+ 一次性迁移旧根目录运行时数据 → data/。
    目录规划：config/ 配置、data/ 运行时数据（state×3/watchdog/日志）、core/ 引擎、scripts/ 工具"""
    try:
        os.makedirs(os.path.join(base, "data"), exist_ok=True)
        os.makedirs(os.path.join(base, "config"), exist_ok=True)
        # 配置包目录（2026-09-06 任务3）：导出/自动备份/待导入三合一，启动即预建
        # （曾另建空壳 data/import/——全仓零消费方，导入只扫 import_export，2026-09-10 移除）
        os.makedirs(os.path.join(base, "data", "import_export"), exist_ok=True)
        for name in ("memwise_state.json", "memwise_efis_state.json", "memwise_eris_ewma.json",
                     "watchdog.json", "memwise.log", "memwise.log.1"):
            src = os.path.join(base, name)
            dst = os.path.join(base, "data", name)
            if os.path.isfile(src) and not os.path.isfile(dst):
                os.replace(src, dst)
    except Exception:
        pass


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
                    # 非 frozen 必须指向 GUI 入口（engine.py 无主流程，重启即退=崩溃恢复失效）
                    _cmd = [exe, os.path.join(base, "memwise_gui.py"), "--restored"]
                p = subprocess.Popen(_cmd,
                    startupinfo=si, creationflags=0x08000008,  # CREATE_NO_WINDOW | DETACHED_PROCESS
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # 更新 watchdog.json 为新 PID（保留崩溃前的守护状态，供恢复分支判断）；tmp+replace 原子写，与主进程协议一致
                # tmp 附加进程号（2026-09-06 审查 F3）：主进程 _update_watchdog_daemon 与
                # 看门狗子进程可能并发更新此文件，各写各的 tmp 防交错损坏
                _wd_tmp = f"{wd_path}.{os.getpid()}.tmp"
                with open(_wd_tmp, "w", encoding="utf-8") as f:
                    json.dump({"pid": p.pid, "ts": now, "crash_count": len(crash_history),
                               "daemon": d.get("daemon", False)}, f)
                os.replace(_wd_tmp, wd_path)
            except Exception:
                continue
    _watchdog_loop()
    sys.exit(0)


def _spawn_watchdog(daemon_flag=False):
    """启动看门狗子进程 — 监控主程序崩溃并自动重启（UI 无关；daemon_flag 为当前守护状态）"""
    try:
        wd_path = _watchdog_path()
        import json
        with open(wd_path, "w", encoding="utf-8") as f:
            json.dump({"pid": os.getpid(), "ts": time.time(), "crash_count": 0,
                       "daemon": daemon_flag}, f)
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


def _update_watchdog_daemon(flag):
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
        # tmp 附加进程号（2026-09-06 审查 F3）：与看门狗子进程的写入互不交错
        tmp = f"{p}.{os.getpid()}.tmp"
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


def read_watchdog_daemon():
    """读 watchdog.json 的守护标志（崩溃恢复判断）"""
    try:
        import json
        with open(_watchdog_path(), "r", encoding="utf-8") as f:
            return bool(json.load(f).get("daemon", False))
    except Exception:
        return False


def remove_watchdog():
    """正常退出时删除 watchdog.json（通知看门狗停止监视）"""
    try:
        p = _watchdog_path()
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


from core import winapi
from core.i18n import set_language, tr  # 界面语言（tr 多数由各算法模块独立导入，引擎自用同为 tr）
from core.config import load as _load_cfg
from core.config import get_state_path
import core.config as _config
from core.learner import _is_system_core, _is_self_path
from core.judger import PareJudger as _JudgerCls  # 仅用于静态守卫方法（_is_system_path）

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

# 常驻崩溃现场 fd（_install_crash_sink 接管；None=未安装，统一日志兜底 faulthandler）
_CRASH_FD = None

# atexit 一次性注册标志（2026-09-11 审查 F27）：日志开关反复"关→开"时原先每次都注册一个
# 退出钩子（实测 1→2→3→4 累积）；同一幂等函数多注册无功能害处但属无界累积，故只注册一次
_ATEXIT_REGISTERED = False


def _log_ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _migrate_old_logs(path):
    """首启迁移：旧 memwise_crash.log 并入统一日志（**幂等**；旧 memwise.log 即日志本体，append 天然连续）。

    2026-09-26 实测修正：原实现依赖"改名成 .imported"防重复，但本机那条改名一直失败（文件被占用，
    异常被吞），于是同一段崩溃文本被重复并入 26 次。现改为**以 .imported 的已有内容为进度标记**：
    只并入新增部分，并在并入后把标记写全——即使改名持续失败也不会重复。
    """
    try:
        p = os.path.join(_LOG_DIR, "memwise_crash.log")
        if not (os.path.exists(p) and os.path.getsize(p) > 0):
            return
        with open(p, "r", encoding="utf-8", errors="ignore") as f:
            data = f.read()
        if not data.strip():
            return
        m = p + ".imported"
        done = ""
        try:
            if os.path.exists(m):
                with open(m, "r", encoding="utf-8", errors="ignore") as f:
                    done = f.read()
        except Exception:
            done = ""
        # 只在确有新增内容时并入（崩溃日志被轮转/覆盖 ⇒ 长度回退视为全新内容）
        delta = data if (not done or len(data) < len(done)) else data[len(done):]
        if delta.strip():
            with open(path, "a", encoding="utf-8") as f:
                f.write(f"\n──── 迁移自 memwise_crash.log ────\n{delta.rstrip()}\n")
        # 进度标记：写全并改名（改名失败也不影响幂等——标记内容已写全）
        try:
            with open(m, "w", encoding="utf-8") as f:
                f.write(data)
            if os.path.exists(p):
                os.replace(p, p + ".imported")
        except Exception:
            pass
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
            if _CRASH_FD is None:  # 崩溃现场 fd 优先（_install_crash_sink 已接管时不重绑）
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
    global _LOG_FD, _LOG_DIR, _ATEXIT_REGISTERED
    if _LOG_FD is not None or "--watchdog" in sys.argv:
        return
    _LOG_DIR = os.environ.get("MEMWISE_LOG_DIR") or os.path.join(base, "data")
    path = os.path.join(_LOG_DIR, "memwise.log")
    try:
        _migrate_old_logs(path)  # 旧 crash log 并入（若存在），旧 memwise.log 继续 append
        # 重试打开（2026-09-11 实测两次"开启失败 ⇒ 整场无文件日志"）：杀软在进程更替瞬间
        # 会短暂占用文件（本仓库环境注意项里就有"瞬时 Access denied"），单次 open 失败就放弃
        # 代价太大 ⇒ 退避重试 3 次
        _LOG_FD = None
        for _try in range(3):
            try:
                _LOG_FD = open(path, "a", encoding="utf-8", buffering=1)
                break
            except Exception:
                if _try == 2:
                    raise
                time.sleep(0.25)
        import faulthandler
        if _CRASH_FD is None:  # 崩溃现场 fd 优先（_install_crash_sink 已接管时不重绑）
            try:
                faulthandler.enable(_LOG_FD, all_threads=True)
            except Exception:
                pass
        # 未捕获异常钩子由 _install_crash_sink 统一安装（写 memwise_crash.log + 此处统一日志）
        if not _ATEXIT_REGISTERED:   # 只注册一次（2026-09-11 审查 F27）
            atexit.register(_log_close)
            _ATEXIT_REGISTERED = True
        _log_write("启动", f"MemWise v4.7.010 启动 · PID {os.getpid()} · 参数:{' '.join(sys.argv[1:]) or '无'}")
        try:
            _ops = ",".join(CFG.get("clean_operations") or []) or "(空)"
            _log_write("启动", "生效设置: 模式 %s · 守护周期 %ss · 压制间隔 %ss · 紧急阈值 %s%% · "
                               "清理深度 %s · 操作[%s] · 日志落盘 %s · 语言 %s · 排除 %d 项 · 游戏 %d 项"
                      % (CFG.get("clean_mode", "normal"), CFG.get("interval", 60),
                         CFG.get("gap_seconds", 12), CFG.get("emergency_threshold", 80),
                         CFG.get("clean_passes", 4), _ops, bool(CFG.get("log_to_file")),
                         CFG.get("language", "zh_CN"), len(CFG.get("never") or []),
                         len(CFG.get("game_processes") or [])))
        except Exception:
            pass
        # 环境画像（跨机器归因第一手证据）：仅在日志开启路径执行 ⇒ 关日志用户零开销；
        # K32 通道态决定运行期回收行为语义（可用=可反复设置/恢复；失效=Nt 一次性直通）
        try:
            _mp_ok, _eco_ok = winapi.probe_k32_channels()
            _log_write("启动", "环境: Windows build %d · K32 内存优先级通道 %s · K32 节能标记通道 %s"
                       % (winapi.get_os_build(),
                          "可用" if _mp_ok else "回退Nt直通",
                          "可用" if _eco_ok else "回退Nt直通"))
        except Exception:
            pass
    except Exception as _e:
        _LOG_FD = None
        # 开启失败必须留痕（2026-09-11 实测：某次启动统一日志未开成 ⇒ 整场无文件日志，
        # 而"日志开关"本身就是写日志的闸门 ⇒ 失败后再无任何线索；当晚真机再次复现）。
        # 走崩溃通道（不受开关控制），并带上异常原文，便于下一次一眼定位。
        try:
            _event_log("统一日志开启失败（本次运行不会写 memwise.log，请重启程序）：%r" % (_e,))
        except Exception:
            pass


# ── 常驻崩溃现场（2026-08-30 审查）：独立于「记录运行日志到文件」开关 ──
# GitHub 单 exe 分发用户默认关日志，此前崩溃后零现场无法报障。faulthandler 与
# 未捕获异常始终写入 data/memwise_crash.log（2MB×1 轮转；下次启动经 _migrate_old_logs
# 并入统一日志后改名 .imported，不残留）。看门狗子进程与回归测试不调用本函数。
def _install_crash_sink():
    global _CRASH_FD
    if _CRASH_FD is not None or "--watchdog" in sys.argv:
        return
    try:
        d = os.environ.get("MEMWISE_LOG_DIR") or _LOG_DIR or os.path.join(base, "data")
        path = os.path.join(d, "memwise_crash.log")
        try:
            if os.path.exists(path) and os.path.getsize(path) > _LOG_MAX:
                old = path + ".1"
                if os.path.exists(old):
                    os.remove(old)
                os.replace(path, old)
        except Exception:
            pass
        _CRASH_FD = open(path, "a", encoding="utf-8", buffering=1)
        import faulthandler
        try:
            faulthandler.enable(_CRASH_FD, all_threads=True)
        except Exception:
            pass

        def _crash_hook(et, ev, tb):
            import traceback
            try:
                _CRASH_FD.write("未捕获异常\n" + "".join(traceback.format_exception(et, ev, tb)) + "\n")
                _CRASH_FD.flush()
            except Exception:
                pass
            _log_write("异常", "未捕获异常（现场已写入 memwise_crash.log）")
            sys.__excepthook__(et, ev, tb)
        sys.excepthook = _crash_hook
        atexit.register(_close_crash_sink)
    except Exception:
        _CRASH_FD = None


def _close_crash_sink():
    global _CRASH_FD
    if _CRASH_FD is not None:
        try:
            _CRASH_FD.close()
        except Exception:
            pass
        _CRASH_FD = None


def _diag_log(msg):
    """诊断日志：写入统一运行日志"""
    _log_write("诊断", msg)


def _event_log(msg):
    """重启/退出类事件的持久痕迹（2026-09-06 任务3）：写入崩溃现场通道——
    不受「记录运行日志到文件」开关控制，保证 os._exit 类主动退出在任何
    设置下都留有记录；下次启动经 _migrate_old_logs 并入统一日志。"""
    global _CRASH_FD
    try:
        if _CRASH_FD is not None:
            _CRASH_FD.write(f"[{_log_ts()}][系统] {msg}\n")
            _CRASH_FD.flush()
    except Exception:
        pass


# ── 配置/状态路径（模块级单例：引擎与展示层共享同一 CFG/STATE_FILE）──
STATE_FILE = get_state_path()
CFG = _load_cfg()
set_language(CFG.get("language", "zh_CN"))  # 界面语言加载（设置面板可即时切换）
_CFG_SNAPSHOT = dict(CFG)  # 配置变更日志基线（_save_cfg 输出 旧→新 diff）

def _save_cfg():
    """保存配置并记录变更（[配置] 类别：逐键 旧→新；供只凭日志定位设置问题）"""
    global _CFG_SNAPSHOT
    try:
        changed = []
        for k, v in CFG.items():
            if k not in _CFG_SNAPSHOT:
                changed.append(f"{k}=新增")
            elif _CFG_SNAPSHOT[k] != v:
                _ov, _nv = _CFG_SNAPSHOT[k], v
                if isinstance(_nv, (dict, list)) or isinstance(_ov, (dict, list)):
                    changed.append(f"{k} 已更新")     # 大结构不倾倒（2026-09-11：曾整段打印 efis_params）
                else:
                    changed.append(f"{k} {_ov}→{_nv}")
        for k in _CFG_SNAPSHOT:
            if k not in CFG:
                changed.append(f"{k}=移除")
        if changed:
            _log_write("配置", "; ".join(changed)[:400])
        _CFG_SNAPSHOT = dict(CFG)
    except Exception:
        pass
    _config.save(CFG)


# ── 数值格式化（展示层与引擎日志共用；单一来源，逐字对齐原 GUI）──
def fmt_label(v):
    if abs(v) >= 1000:
        return f"{v/1024.0:.1f}GB"
    return f"{v:.1f}MB"


def fmt_count(n):
    if n >= 1000:
        return f"{n/1000.0:.1f}k"
    return str(n)


# ── ERIS/守护辅助（纯函数，逐字对齐原 GUI 实现）──
def _prof_theta_mean(learner):
    """画像 Thompson θ 均值（≥2 样本才参与）。dict() 快照迭代：手动优化线程可并发
    增键，直接迭代会 RuntimeError 击落守护线程（2026-08-30，与 _compute_eris 同款防护）"""
    ps = [p for p in dict(learner.profiles).values() if p.total_samples >= 2]
    return sum(p.thompson_theta for p in ps) / len(ps) if ps else 0.3


def _prof_theta_above(learner):
    """θ>0.6 画像占比（快照迭代同上）"""
    ps = [p for p in dict(learner.profiles).values() if p.total_samples >= 2]
    return sum(1 for p in ps if p.thompson_theta > 0.6) / len(ps) if ps else 0.0


def _drain_pf_delta(judger):
    """清零并返回本轮 PF 增量（跨周期清零，防污染诊断窗口）。
    与 check_feedback 的锁内累加同锁：无锁读-清会与 trim 池并发交错丢更新（2026-08-15 审查）"""
    with judger._lock:
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
    # 防御性自检（2026-09-11 审查 F3）：ap ≥ 100 时"可用率 ≤ ap"恒真 ⇒ 每周期恒紧急 full。
    # 配置层已钳制到 0-99，这里再兜一层：即便配置被绕过也绝不进入恒触发。
    if 0 < ap <= 99 and m.get("total") and m.get("avail"):
        return m["avail"] / m["total"] * 100 <= ap
    return False


# ════════════════════════════════════════════════════════════════
# MemWiseEngine —— 无 UI 引擎
# ════════════════════════════════════════════════════════════════
class MemWiseEngine:
    """守护循环 / ERIS / 轮次数据 / 事件队列——不依赖任何 UI 框架。

    事件队列 events（queue.Queue）：动作元组与原 GUI 消息队列格式一致——
    ('log', msg) / ('display_groups', [组, …]) / ('log_batch', [lines]) / ('log_op', msg) /
    ('chart', None) / ('upd_ui', (s, m, txt)) / ('opt_done', result) / ('dae_stopped', None)
    ——展示层消费端零改动复用。
    """

    def __init__(self, learner, judger, cleaner, efis, sniffer, state_file):
        self.learner = learner
        self.judger = judger
        self.cleaner = cleaner
        self.efis = efis
        self.sniffer = sniffer
        self._state_file = state_file

        # 事件队列（展示层消费）
        self.events = queue.Queue()

        # 守护状态
        self._running = False
        self._thread = None
        self._dae_error = None
        self._pending_harvest = None
        # 守护互斥 mutex 句柄（Global\MemWise_Daemon，守护运行期间持有；
        # _daemon_busy_cli 供展示层区分"CLI 占用"与"旧线程收尾中"两种启动失败）
        self._daemon_mutex = None
        self._daemon_busy_cli = False
        # harvest 专用独立线程池（与 trim 池彻底隔离——防池内嵌套死锁，见 _dae_worker）
        self._harvest_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="memwise-harvest")

        # 柱图状态
        self._chart_data = deque(maxlen=60)
        self._chart_last_freed = 0.0
        self._prev_trim_count = 0
        self._prev_fail_count = 0
        self._eff_data = deque(maxlen=60)          # 效率折线数据
        self._eff_factors = deque(maxlen=60)       # 效率主导因子
        self._chart_lock = threading.Lock()
        self._chart_cycle_meta = deque(maxlen=60)  # 每轮元数据(seq,trimmed,failed,mem_pct,failed_weight,partial)
        self._chart_bar_seq = 0                    # 全局轮次序列号（守护递增）

        # ERIS 状态（分位数窗/平滑/趋势/防振荡）
        self._eris_lock = threading.Lock()
        self._eris_save_lock = threading.Lock()    # ERIS 状态持久化互斥锁（守护线程与退出线程可能并发写）
        # ── ERIS v7 状态（2026-09-11 用户定稿：五维绝对标尺 + N=3 平滑 + Σ÷K）──
        from collections import deque as _dq
        from core.eris import SMOOTH_N as _SN
        from core.eris import new_calib as _new_calib
        self._eris_calib = _new_calib()  # ② 自校准状态（独立文件持久化，缺文件=冷启动）
        # 平滑窗**按清理模式分桶**（2026-09-11，用户要求四模式互不污染）：各模式维度量级不同，
        # 混用一个窗会把上一模式的原始值带进新模式的中位数；分桶后切回原模式还能接上原有窗口。
        self._eris_hist_by_mode = {}     # {模式: [每维 deque]}
        self._eris_hist_mode = None      # 上一轮 ERIS 所用的模式（切换即重置"上一轮"基线）
        # （quick 的"惯常系统级释放量"基准已由 ERIS v9 自标定基线取代，旧 deque 字段随之移除）
        self._eris_prev_scores = None    # 上轮五维分（词条同向判定）
        self._eris_last_word = None   # 上轮词条 (维度, 方向)：相邻两轮同维正负不复读（2026-09-26 用户规定）
        self._eris_prev_eff = None       # 上轮效率（平稳/趋势判定）
        self._eris_trend = []            # 方向序列（含 <2 的轮次，±1/0；极性轮 99/-99 打断）
        self._cycle_pf = 0               # 本周期 PF 增量（副作用维）
        self._cycle_probe = (0, 0)       # 本周期 试探(成功, 总数)（试探维）
        self._last_eris_game_mode = None
        self._load_eris_state()  # 在 daemon 首次调用 _compute_eris 前完成加载

        # 周期基线/去重状态
        self._cycle_trimmed = 0
        self._cycle_failed = 0
        self._failed_weight = 0.5
        self._last_sys_ops = 0
        self._last_l3_ran = 0
        self._last_l3_extra = 0
        self._prev_deepen_cnt = 0    # deepen 计数上一周期值（周期增量基准，2026-09-28 审查）
        self._prev_deepen_extra = 0
        self._cfg_mtime = 0
        self._last_agg_peak = None
        self._last_pressure_mem = ''
        self._last_pressure_chg = ''
        self._last_deep_triggered = False
        self._emergency_done_cycle = False
        # 回弹驱动（C 方案，2026-08-14）：harvest 后 WS 基线 + 释放量，供 full 模式 gap 回填率判断
        self._last_harvest_ws = None
        self._last_harvest_freed = 0
        # 共享最近快照（2026-08-15 审查）：进程排行窗口在守护运行中零额外采集直接读取
        self._last_snaps = []
        self._refill_hot = False   # 跨周期：是否处于回涨快状态（状态翻转去重，2026-08-14）
        self._refill_cycle = False # 本周期是否触发过回涨快（周期末判定）
        self._refill_total = 0     # 最新回涨量（进入回涨快时展示）
        # ── 工作集硬上限（高级选项，设计 v2.1-v2.5）：簿记与锁 ──
        self._ws_cap_lock = threading.Lock()
        self._ws_cap_applied = {}   # {规范化路径: {pid: orig_max}}（解除凭它；跨重启丢失即回退规则存储值）
        self._ws_cap_fail = {}      # {规范化路径: 连续失败次数（≥3 降频至每 10 周期）}
        self._ws_cap_announced = set()  # 已播报过的路径（每规则仅首条）

    # ── 守护生命周期 ──
    @property
    def daemon_running(self):
        return self._running

    def start_daemon(self):
        """启动守护（含周期基线/图表/ERIS 状态重置；防双守护）"""
        if self._running:
            return False
        # 防双守护：旧线程若仍存活（停止后短暂收尾），等待其退出
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)
            if self._thread.is_alive():
                return False
        # 命令行守护互斥（2026-09-06 审查 F3）：CLI daemon（service/手动）运行中拒绝开启；
        # GUI 不开守护时不占坑——mutex 仅在守护运行期间持有（_dae_worker finally 释放）
        if self._daemon_mutex is None:
            self._daemon_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, DAEMON_MUTEX_NAME)
            if ctypes.windll.kernel32.GetLastError() in (0xB7, 5):
                self._daemon_mutex = None
                self._daemon_busy_cli = True
                return False
        self._daemon_busy_cli = False
        s = self.cleaner.summary()
        self._chart_last_freed = float(s['freed_mb'])
        self._prev_trim_count = s['ws_trim']
        self._prev_fail_count = s.get('failed_feedback', 0)
        self._chart_data.clear()
        self._eff_data.clear()
        self._eff_factors.clear()
        self._chart_cycle_meta.clear()
        self._chart_bar_seq = 0
        self._load_eris_state()  # 恢复 ERIS 状态
        self._last_sys_ops = 0
        self._prev_deepen_cnt = 0
        self._prev_deepen_extra = 0
        self._cycle_trimmed = 0
        self._cycle_failed = 0
        self._cycle_freed_mb = 0.0       # 本周期净释放（MB；quick 的系统级释放由此扣掉进程部分）
        self._cycle_avail_start = 0.0    # 本周期起点可用内存（净留存率维的分子基准）
        self._cycle_net_drop_mb = 0.0    # 本周期净下降（收割后定稿，v9「净优化量」维读取）
        self._last_harvest_ws = None
        self._last_harvest_freed = 0
        # 回弹状态机跨周期字段一并重置（2026-08-14 审查：仅重置 harvest 两字段时，
        # _refill_hot 残留会致新守护首周期误报"↻ 内存回涨已放缓"）
        self._refill_hot = False
        self._refill_cycle = False
        self._refill_total = 0
        self._last_snaps = []  # 新守护周期从空开始（排行窗口按 daemon_running 切换数据源）
        self._running = True
        self._thread = threading.Thread(target=self._dae_worker, daemon=True)
        self._thread.start()
        return True

    def stop_daemon(self):
        """请求停止（分段睡眠使守护即时生效）"""
        self._running = False

    def join_daemon(self, timeout=2.0):
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

    # ── 数据快照（展示层读取）──
    def chart_snapshot(self):
        """图表数据快照：(data, meta, eff_data, eff_factors) 锁内拷贝"""
        with self._chart_lock:
            return (list(self._chart_data), list(self._chart_cycle_meta),
                    list(self._eff_data), list(self._eff_factors))

    def _snap(self):
        """快照 + 喂学习器 + 缓存共享快照（守护/手动路径统一入口；
        进程排行窗口守护运行中直接读 _last_snaps，零额外采集）"""
        snaps = self.sniffer.snapshot()
        self.learner.feed(snaps)
        self._last_snaps = snaps
        return snaps

    # ── 收尾 ──
    def save_state(self):
        try:
            self.learner.save(self._state_file)
        except Exception:
            pass
        self._save_eris_state()

    def shutdown(self):
        """停止守护并释放资源（退出流程用）"""
        self._running = False
        self.join_daemon(timeout=2)
        try:
            self.cleaner.shutdown()
        except Exception:
            pass
        try:
            self._harvest_executor.shutdown(wait=False)
        except Exception:
            pass

    # ── 手动优化（数据产生属引擎；展示层只做按钮编排）──
    def optimize_manual_async(self, mode, ops):
        threading.Thread(target=self._opt_worker, args=(mode, ops), daemon=True).start()

    def optimize_manual_once(self, mode, ops):
        """守护运行中的手动即时优化：按当前模式执行单轮完整优化。
        与守护周期经 cleaner._exec_lock 串行（持锁期间设 _manual_run，
        守护周期 optimize 等待锁后 _manual_run 已复位，互不污染）"""
        threading.Thread(target=self._opt_worker_once, args=(mode, ops), daemon=True).start()

    def _opt_worker(self, mode, ops):
        with self.cleaner._exec_lock:
            self.cleaner._manual_run = True  # 手动优化：跳过自动化保守门（前台冷却/连续确认/锚点抑制），保留实时安全门（CPU/IO 活跃）
            # 按调用时模式取参（2026-08-16 模式参数组）：手动优化用该模式自己的参数，
            # 不受守护周期末同步的"当前模式"影响；策略树权重同步同一模式（审查 P6）
            self.judger.cfg["efis_params"] = self.efis.get_params(mode)
            self.judger.sync_pid_from_cfg()  # 手动优化按本次模式参数驱动 PID
            self.learner.policy.set_mode(mode)
            try:
                snaps = []
                for i in range(3):
                    snaps = self._snap()
                    if i < 2: time.sleep(2)
                # 启动信息打包（2026-08-30 分组语义）：观察到+候选预览同批原子输出
                start_lines = [f"观察到 {len(snaps)} 个进程"]
                try:
                    # 候选预览按手动优化口径评估（manual + 本次模式）：与随后实际执行同口径，
                    # 否则会沿用守护周期遗留的保守门（刚切走/活动确认/稳态抑制/回弹后退 + 旧模式门），
                    # 出现"有清理却没有候选行"或候选与实际名单对不上的混乱（2026-09-11 F53）
                    preview = [s.name for s in snaps if self.judger.can_trim(s, manual=True, guard=mode)[0]]
                    if preview:
                        shown = '、'.join(preview[:5]) + ('…' if len(preview) > 5 else '')
                        start_lines.append(f"📋 本次将评估 {len(preview)} 个进程：{shown}")
                except Exception:
                    pass
                self.events.put(('log_batch', start_lines))
                m0 = winapi.get_memory_status()
                all_l2 = []; all_probe = []
                total_net = 0
                freed0 = self.cleaner.summary()['freed_mb']  # 释放量基线（标量总和口径）
                for round_idx in range(3):
                    if round_idx == 0:
                        r = self.cleaner.optimize(snaps, self.learner, mode, operations=ops)
                    else:
                        snaps = self._snap()
                        r = self.cleaner.optimize(snaps, self.learner, mode, operations=ops)
                    all_l2.extend(r.get("layer2", []))
                    all_probe.extend(r.get("probe", []))
                    total_net += r.get("net_freed", 0)
                    # 过程节拍（2026-08-30）：长清理拆为可见节拍，消灭轮间静默
                    self.events.put(('log', f"第 {round_idx + 1}/3 轮完成 · 本轮释放 {r.get('net_freed', 0) / (1 << 20):.0f} MB"))
                    if round_idx < 2:
                        time.sleep(2)
                self.learner.save(self._state_file)
                m1 = winapi.get_memory_status()
                freed1 = self.cleaner.summary()['freed_mb']
                released = max(0.0, freed1 - freed0)  # 三轮释放量标量总和
                # 结果卡由展示层 _opt_done 单批次整卡输出（唯一摘要源，面板/文件零重复）
                self.events.put(('opt_done', {
                    "mode": mode, "layer2": all_l2, "probe": all_probe,
                    "released": released, "net": total_net,
                    "pct0": m0['pct'] if m0 else None, "pct1": m1['pct'] if m1 else None}))
            except Exception:
                import traceback; traceback.print_exc(file=_ERR)
                self.events.put(('log', "⚠ 手动优化异常，已自动恢复"))
                self.events.put(('opt_done', {
                    "mode": mode, "layer2": [], "probe": [],
                    "released": 0.0, "net": 0, "pct0": None, "pct1": None}))
            finally:
                self.cleaner._manual_run = False

    def _opt_worker_once(self, mode, ops):
        """守护运行中即时优化的执行体：单轮快照+单轮 optimize（守护周期互斥见调用方注释）"""
        with self.cleaner._exec_lock:
            self.cleaner._manual_run = True
            self.judger.cfg["efis_params"] = self.efis.get_params(mode)  # 按调用时模式取参
            self.judger.sync_pid_from_cfg()  # 手动优化按本次模式参数驱动 PID
            self.learner.policy.set_mode(mode)  # 树权重同模式（审查 P6）
            try:
                snaps = self._snap()
                # 候选预览（2026-08-30 与三轮版对齐）：点击后告知将清理范围
                try:
                    # 候选预览按手动优化口径评估（manual + 本次模式）：与随后实际执行同口径，
                    # 否则会沿用守护周期遗留的保守门（刚切走/活动确认/稳态抑制/回弹后退 + 旧模式门），
                    # 出现"有清理却没有候选行"或候选与实际名单对不上的混乱（2026-09-11 F53）
                    preview = [s.name for s in snaps if self.judger.can_trim(s, manual=True, guard=mode)[0]]
                    if preview:
                        shown = '、'.join(preview[:5]) + ('…' if len(preview) > 5 else '')
                        self.events.put(('log', f"📋 本次将评估 {len(preview)} 个进程：{shown}"))
                except Exception:
                    pass
                m0 = winapi.get_memory_status()
                freed0 = self.cleaner.summary()['freed_mb']
                r = self.cleaner.optimize(snaps, self.learner, mode, operations=ops)
                self.learner.save(self._state_file)
                m1 = winapi.get_memory_status()
                freed1 = self.cleaner.summary()['freed_mb']
                released = max(0.0, freed1 - freed0)
                # 结果卡由展示层 _opt_done 单批次整卡输出（唯一摘要源，面板/文件零重复）
                self.events.put(('opt_done', {
                    "mode": mode, "layer2": r.get("layer2", []), "probe": r.get("probe", []),
                    "released": released, "net": r.get("net_freed", 0),
                    "pct0": m0['pct'] if m0 else None, "pct1": m1['pct'] if m1 else None}))
            except Exception:
                import traceback; traceback.print_exc(file=_ERR)
                self.events.put(('log', "⚠ 即时优化异常，已自动恢复"))
                self.events.put(('opt_done', {
                    "mode": mode, "layer2": [], "probe": [],
                    "released": 0.0, "net": 0, "pct0": None, "pct1": None}))
            finally:
                self.cleaner._manual_run = False

    # ── 守护线程（逐行搬移自原 GUI，行为不变）──
    def _dae_worker(self):
        h_low = None
        try:
            # 创建内存通知对象（事件驱动取代轮询；HIGH 通知无消费方——只 wait LOW，不创建浪费句柄）
            h_low = winapi.create_memory_resource_notification(
                winapi.MEMORY_RESOURCE_NOTIFICATION_TYPE_LOW)
            use_event_driver = h_low is not None
            if not use_event_driver:
                # 机器级永久特征（通知对象不可用 ⇒ 守护改轮询等待）⇒ crash 通道一次性留痕
                try:
                    _event_log("系统环境: 内存资源通知对象不可用，守护改用轮询等待（功能不受影响，等待粒度退化为 1 秒）")
                except Exception:
                    pass

            interval = CFG.get("interval", 60)  # 与 DEFAULT_CFG 一致（原 30 系历史默认值残留）
            last_cfg_check = 0
            last_save = 0
            startup_logged = False
            overtime_debt = 0  # 累计超时债务（秒），下一轮 deadline 中扣除

            while self._running:
                tick_start = time.time()
                # 60s 完整周期从等待开始计（pre_wait 计入周期，防长期漂移）
                cycle_start = tick_start

                # 收尾上一轮超时的 harvest（尽力等待，避免双份 trim 叠加）
                ph = self._pending_harvest
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
                        if not self._running:
                            return
                        ret = winapi.wait_for_object(h_low, 1000)
                        if ret == "signaled":
                            break
                else:
                    for _ in range(pre_wait):
                        if not self._running:
                            return
                        time.sleep(1)

                # 60s 周期从工作阶段继续计算（等待已计入 cycle_start）
                m = winapi.get_memory_status()
                if not m: time.sleep(interval); continue
                self._cycle_avail_start = m["avail"]   # 周期起点可用内存（净留存率维分子基准）
                snaps = self._snap()

                learned = len(self.learner.profiles)

                self._cycle_log_groups = []  # 本周期末分组输出缓存（每项一个逻辑组，2026-08-30）
                # 工作集硬上限施加（幂等 syscall；五守卫+降频见方法体；播报入周期批）
                self._apply_ws_caps(snaps)
                efis_msg = None  # 本周期 EFIS 调参消息（并入周期批输出）
                # 启动观察消息即时输出（用户定稿：及时反馈，不打包延迟）
                if not startup_logged:
                    self.events.put(('log', f"🧠 观察到 {len(snaps)} 个进程 · 已有 {learned} 个画像"))
                    startup_logged = True
                self._refill_cycle = False  # 周期内触发标记（周期末状态机判定）
                agg_first = self.judger.aggressiveness
                agg_max = agg_first  # 本轮峰值
                layer3_ran_start = self.cleaner.summary().get("layer3_ran", 0)
                deep_triggered = False  # 本轮是否触发过深度清理
                self._emergency_done_cycle = False  # 本轮是否已触发紧急清理（周期内去重）
                # 游戏态冻结判定（2026-08-30）：本周期内游戏任意时刻开启 → 本周期统计
                # 不进入 EFIS 评估（翻转周期整周期隔离，防游戏期统计污染参数组）
                game_seen = self.cleaner.game_mode

                # 清理
                mode = CFG.get("clean_mode", "normal")  # 读 CFG 镜像：tk 变量非线程安全，daemon 线程不触碰 Tk 对象
                # 模式参数组同步（2026-08-16）：EFIS 调参与策略树权重按模式隔离，周期开始即对齐
                self.efis.set_mode(mode)
                self.learner.policy.set_mode(mode)
                # 消费源即时同步（审查 P4）：模式切换后首个周期即用新模式参数，
                # 不等周期末调参（原实现首周期沿用上一模式参数）
                self.judger.cfg["efis_params"] = self.efis.get_params()
                self.judger.sync_pid_from_cfg()  # 响应类参数随模式组切换即时进 PID
                agg = self.judger.update_pressure(m['pct'])
                ops = CFG.get("clean_operations")
                # 连续优化循环：deadline + 多次 optimize + gap fill + blitz
                m_emerg = winapi.get_memory_status()
                if m_emerg and _emergency_active(m_emerg):
                    _saved_efis = self.judger.cfg.get("efis_params")
                    self.judger.cfg["efis_params"] = self.efis.get_params("full")  # 紧急 full 用 full 组参数（审查 P5）
                    agg_emerg = self.judger.update_pressure(m_emerg["pct"])
                    self.cleaner.optimize(snaps, self.learner, "full", operations=ops, aggressiveness=agg_emerg)
                    if _saved_efis is not None:
                        self.judger.cfg["efis_params"] = _saved_efis
                    self._cycle_log_groups.append(["⚠ 紧急触发清理(full模式)"])
                    self._emergency_done_cycle = True
                interval = CFG.get("interval", 60)  # 周期由配置驱动（默认 60s，原硬编码 60 使配置键失效）
                deadline = time.time() + interval - 3 - overtime_debt
                l2_all = []; probe_all = []
                gap_base = max(8, min(20, CFG.get("gap_seconds", 12)))
                gap = gap_base
                if self.cleaner.game_mode:
                    gap = gap_base * 1.5  # 游戏模式：降低操作密度，减少对磁盘I/O的竞争
                prev_per_proc = 0.0
                while time.time() < deadline - 6 and self._running:
                    gap_end = min(time.time() + gap, deadline - 6)
                    snap_skip = 0
                    while time.time() < gap_end and self._running:
                        # 快照降频：每3s采集一次（节省~20% CPU/功耗，进程列表在gap期间变化极小）
                        if snap_skip <= 0:
                            snaps = self._snap()
                            snap_skip = 6
                            # 回弹驱动（C 方案，2026-08-14）：full 模式回填率 >60% → gap 立即收紧，
                            # 提前进入收割（回弹越猛压得越密；net_freed≤32MB 的微小轮跳过判断）
                            if mode == "full" and self._last_harvest_freed > (32 << 20) \
                                    and self._last_harvest_ws is not None:
                                _ws_now = sum(getattr(s, 'ws', 0) for s in snaps)
                                _refill = max(0, _ws_now - self._last_harvest_ws)
                                if _refill > self._last_harvest_freed * 0.6:
                                    gap = max(8.0, gap - 4)
                                    self._refill_cycle = True  # 周期内触发标记
                                    self._refill_total = _refill  # 最新回涨量
                            # 游戏模式：快照后实时检测启动/退出（检测零开销），
                            # 周期内启动又退出时，两条日志按序进入周期末打包通道
                            game_now = self.cleaner._is_user_game_running(snaps)
                            if game_now:
                                game_seen = True  # 本周期游戏曾开启（冻结判定）
                            if self.cleaner._game_mode_manual:
                                # 手动模式：实时刷新 PID 保护集（含子进程树），不自动切换模式
                                if game_now:
                                    self.cleaner.judger._game_pid_set = self.cleaner._build_game_pid_set(snaps)
                            elif not self.cleaner.game_mode and game_now:
                                self.cleaner.game_mode = True
                                self.cleaner.judger.game_mode = True
                                self.cleaner.judger._game_pid_set = self.cleaner._build_game_pid_set(snaps)
                                self._cycle_log_groups.append(["🎮 检测到游戏运行 · 启用 游戏模式"])
                            elif self.cleaner.game_mode and not game_now:
                                # 实时退出（2026-09-06 用户定稿：实时监测，游戏模式随游戏
                                # 启停即时生效，无确认周期；原"连续 2 周期确认"在 gap 快照
                                # 节奏下实为 2×3s，与本意不符）
                                self.cleaner.game_mode = False
                                self.cleaner.judger.game_mode = False
                                self.cleaner.judger._game_pid_set.clear()
                                self._cycle_log_groups.append(["🎮 游戏已退出 · 恢复正常模式"])
                            # 高频压制梯度：registry 零磁盘干扰，游戏模式同样执行（游戏流畅只禁磁盘类操作）；
                            # deep/full 追加系统级持续清（standby/脏页零 PF 成本——缓存重建后立即回收，
                            # 可用内存持续高位，抑制"压缩后回弹"）；游戏模式恒 registry（流畅优先）
                            if self.cleaner.game_mode:
                                ops_gap = {"registry"}
                            elif mode == "full":
                                ops_gap = {"registry", "standby", "standby_low", "modified"}
                            elif mode == "deep":
                                ops_gap = {"registry", "standby", "modified"}
                            else:
                                ops_gap = {"registry"}
                            self.cleaner._layer1_memreduct(full=False, ops=ops_gap, clean_self=False)
                            if mode != "quick":
                                # fast_track 重清限流：每循环最多 5 个（0.1s 测速 × 5 ≈ 循环间隔；
                                # 成功者移队尾轮转覆盖全池）——full 池扩大后防循环拖慢
                                for ft_pid in list(self.cleaner._fast_track)[:5]:
                                    if ft_pid in self.cleaner.judger._game_pid_set:
                                        self.cleaner._fast_track.pop(ft_pid, None)
                                        continue
                                    # 带回记录时的创建时间做身份复检（PID 复用防护，2026-09-11 审查 F12）
                                    if not self.cleaner.quick_retrim(ft_pid, self.cleaner._fast_track.get(ft_pid)):
                                        self.cleaner._fast_track.pop(ft_pid, None)
                                    else:
                                        # 成功者移到队尾：下轮轮转后续成员，全池覆盖（2026-09-26 审查
                                        # F3：dict 插入序稳定，恒成功的高回填进程原会永久占住前 5 位，
                                        # 池尾成员整轮不被覆盖）；取局部引用防与手动优化每轮重建的重绑竞态
                                        _ft_map = self.cleaner._fast_track
                                        if ft_pid in _ft_map:
                                            _ft_map[ft_pid] = _ft_map.pop(ft_pid)
                        snap_skip -= 1
                        m2 = winapi.get_memory_status()
                        if m2:
                            agg = self.judger.update_pressure(m2["pct"]); m = m2
                            agg_max = max(agg_max, agg)
                            # 周期内紧急即时响应：内存飙到阈值立即 full 清理（不等下一周期），每周期至多一次
                            if _emergency_active(m2) and not self._emergency_done_cycle:
                                self._emergency_done_cycle = True
                                self._cycle_log_groups.append(["⚠ 周期内紧急触发清理(full模式)"])
                                _saved_efis = self.judger.cfg.get("efis_params")
                                self.judger.cfg["efis_params"] = self.efis.get_params("full")  # 紧急 full 用 full 组参数（审查 P5）
                                self.cleaner.optimize(snaps, self.learner, "full",
                                                      operations=ops, aggressiveness=agg)
                                if _saved_efis is not None:
                                    self.judger.cfg["efis_params"] = _saved_efis
                                m2 = winapi.get_memory_status()
                                if m2:
                                    m = m2
                                    agg = self.judger.update_pressure(m2["pct"])
                                    agg_max = max(agg_max, agg)
                        # 节奏控制：0.5s 间隔保持高频温和压制，杜绝忙循环空转烧 CPU
                        time.sleep(0.5)
                    # gap-fill 天花板：quick 保持 quick，其余统一用 normal（deep/full 的重操作留给 harvest）
                    gap_fill_mode = "quick" if mode == "quick" else "normal"
                    # 游戏模式同样执行：optimize 内部对游戏进程树绝对保护、跳过磁盘干扰系统操作，
                    # 非游戏进程持续积极清理为游戏腾出内存（游戏流畅只依赖 PID 保护与磁盘操作跳过）
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
                            # 上界收敛到配置文档区间 8-20（2026-09-11 审查 F10）：原 25 会越出
                            # 用户可设范围（UI 明示 8~20 秒），设 20 的用户被意外改成 25
                            gap = min(20.0, gap + 3)
                    prev_per_proc = per_proc
                while time.time() < deadline - 4 and self._running:
                    if mode != "quick":
                        # 尾段轻压制同 gap 梯度：full 含 standby/脏页持续清，deep 含 standby/脏页
                        if self.cleaner.game_mode:
                            ops_tail = {"registry"}
                        elif mode == "full":
                            ops_tail = {"registry", "standby", "standby_low", "modified"}
                        elif mode == "deep":
                            ops_tail = {"registry", "standby", "modified"}
                        else:
                            ops_tail = {"registry"}
                        self.cleaner._layer1_memreduct(full=False, ops=ops_tail, clean_self=False)
                    time.sleep(1.5)
                # harvest：每轮完整收割（游戏进程由 PID 保护、系统缓存由 game_mode 跳过，
                # 非游戏进程清理不影响游戏流畅；图表每轮保持真实数据）
                if not self._running:
                    break
                # harvest 独立 1 线程池执行：与 trim 池彻底隔离——
                # 原提交到 _trim_executor 池内嵌套（harvest 占线程 + 内部 _bounded_submit 再向同池提交）：
                # 1 核机器 max_workers=1 死锁致 harvest 永久超时；多核时排队时间计入 30s 超时误判 partial
                # 回涨状态机（2026-08-14 定稿，2026-09-26 前移）：进入回涨快提示一次 → 持续静默 →
                # 回落提示恢复。判据（_refill_cycle/_refill_total）在本周期轮询阶段即已定稿，故这里
                # 先于本轮强度决策求值——F1 与播报读同一次判定，且回涨量配的除数是上一轮释放量。
                if self._refill_cycle:
                    if not self._refill_hot:
                        _rate = int(round(self._refill_total / max(self._last_harvest_freed, 1) * 100))
                        self._cycle_log_groups.append(
                            [f"↻ 内存回涨较快，仅上轮收割后即回涨{_rate}% · 将持续收紧收割节奏直到放缓"])
                    self._refill_hot = True
                else:
                    if self._refill_hot:
                        self._cycle_log_groups.append(["↻ 内存回涨已放缓，试探性恢复正常收割节奏"])
                    self._refill_hot = False
                # F1 压力自适应（2026-09-26 用户定稿）：内存宽裕 + 上轮回涨快 ⇒ full 模式轻量轮。
                # 占用回升到阈值或回涨放缓立即恢复全强度；手动优化与紧急 full 不走此路径（各自全强度）。
                # 本轮是否轻量不单独播报——回涨快慢由上面状态机统一播报，同一信号不两个时点各说一次
                _lite = self.cleaner.is_lite_round(mode, getattr(self.judger, "_last_mem_pct", 100),
                                                   self._refill_hot)
                harvest_future = self._harvest_executor.submit(
                    self.cleaner.optimize, snaps, self.learner, mode,
                    operations=ops, aggressiveness=agg, lite=_lite)
                result = None
                try:
                    result = harvest_future.result(timeout=30)
                except concurrent.futures.TimeoutError:
                    self._pending_harvest = harvest_future  # 下轮开头收尾，避免任务叠加
                    result = {"mode": mode, "aggressiveness": agg, "layer2": [], "probe": [],
                              "net_freed": 0, "_partial": True}
                    self._cycle_log_groups.append(["⏱ harvest 超时(30s)·跳过本轮诊断"])
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
                if self.cleaner.game_mode:
                    game_seen = True  # 收割期 _layer2_process 可能翻转游戏态（冻结判定覆盖）
                agg_max = max(agg_max, agg)  # 捕获全量模式强制的 agg 峰值
                # 回弹驱动基线（C 方案）：记录 harvest 后总 WS 与释放量，供下一周期 gap 回填率判断
                self._last_harvest_freed = max(result.get("net_freed", 0), 0)
                try:
                    _hs = self._snap()
                    self._last_harvest_ws = sum(getattr(s, 'ws', 0) for s in _hs)
                except Exception:
                    self._last_harvest_ws = None
                # harvest 后刷新内存状态：日志/图表/EFIS 输入用最新值（harvest 最长 30s，旧值会滞后一轮）
                m_fresh = winapi.get_memory_status()
                if m_fresh:
                    m = m_fresh
                # 净留存率维分子（v9 dim0 重定义 2026-09-27）：本轮净下降 = 周期末可用 − 周期初可用
                # （总释放由 _cycle_freed_mb 承载；两侧同为全局口径，比值 = 释放量里净留存的比例）
                self._cycle_net_drop_mb = max(0.0, float(m["avail"] - self._cycle_avail_start)) / (1 << 20)
                l2_all.extend(result.get("layer2", []))
                probe_all.extend(result.get("probe", []))
                l2_results = l2_all
                probe_results = probe_all
                # 进程清理释放量（MB）：ERIS「优化代价」维的分子
                try:
                    _det = []
                    for _t in (l2_results or []):
                        if len(_t) >= 4 and _t[1] and _t[2]:
                            _pr = self.learner.get_profile(getattr(_t[0], "name", ""))
                            _g = float(getattr(_pr, "gain_ewma", 0) or 0)
                            if _g > 0:
                                _det.append((float(_t[2]), _g))
                    self._cycle_proc_mb = sum(f for f, _g in _det) / (1 << 20)   # 进程清理释放量（MB）
                except Exception:
                    pass
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
                # 配置热加载：每 5 秒检查一次 config.yaml 是否变更
                if now - last_cfg_check > 5:
                    last_cfg_check = now
                    try:
                        mtime = os.path.getmtime(_config.CONFIG_PATH)
                        if mtime != self._cfg_mtime:
                            self._cfg_mtime = mtime
                            fresh = _config.load()  # 单次读取复用（原连续两次读盘，2026-08-30）
                            _log_old = bool(CFG.get("log_to_file"))
                            CFG.update(fresh)
                            # 日志开关 fd 同步（与 CLI F16 同语义）：_log_write 受开关与句柄
                            # 双闸，手改 config.yaml 的开关在守护运行中也要即时开/关文件
                            _log_new = bool(CFG.get("log_to_file"))
                            if _log_new != _log_old:
                                (_log_open if _log_new else _log_close)()
                            # 同步 judger 运行配置（排除列表/游戏名单/清理深度/EFIS 参数守护期间即时生效）
                            self.judger.cfg["never"] = CFG.get("never", [])
                            self.judger.cfg["game_processes"] = CFG.get("game_processes", [])
                            self.judger.cfg["clean_passes"] = CFG.get("clean_passes", 4)
                            # 紧急阈值同步（2026-09-11 S5）：高压让路判据与策略树阈值同口径
                            self.judger.cfg["emergency_threshold"] = CFG.get("emergency_threshold", 80)
                            # EFIS 参数以状态文件为权威（审查 P3）：config.yaml 的 efis_params 是
                            # 上次调参的模式快照,热加载回灌会覆盖当前模式组——改为直接从 EFIS 取
                            self.judger.cfg["efis_params"] = self.efis.get_params()
                            self.judger.sync_pid_from_cfg()
                    except Exception as e:
                        import sys; print(f"[MemWise] 配置加载异常: {e}", file=_ERR)
                if now - last_save > 30:
                    last_save = now
                    # 学习状态摘要（2026-09-11）：画像/锚点/回退/抑制/探索 + 当前 EFIS 参数与分组
                    try:
                        _lr = self.learner
                        _prof = len(_lr.profiles)
                        _anch = len(getattr(_lr.stable_anchors, "anchors", {}) or {})
                        _back = len(getattr(_lr.rebound, "ewma", {}) or {})
                        _sup = getattr(self.judger, "suppress_cnt", 0)
                        _lb = getattr(self.judger, "learner", None)
                        _pw = []
                        try:
                            _pw = ["%.2f" % w for w in _lr.policy._weights()]
                        except Exception:
                            pass
                        _ep = {}
                        try:
                            _ep = self.efis.get_params(CFG.get("clean_mode", "normal")) or {}
                        except Exception:
                            pass
                        _key = ("target_usage", "pid_kp", "pid_kd", "learning_rate", "anchor_margin",
                                "cpu_gate", "io_gate", "deepen_theta", "cooloff_base")
                        _ps = " ".join("%s=%s" % (k, _ep.get(k)) for k in _key if k in _ep)
                        try:
                            from core import eris as _E9
                            _m9 = CFG.get("clean_mode", "normal")
                            if _E9.calibrated(self._eris_calib, _m9):
                                _eb = "已标定 K=%.0f" % _E9.k_value(self._eris_calib, _m9)
                                if _E9.recalib_count(self._eris_calib, _m9):
                                    _eb += " 重标%d" % _E9.recalib_count(self._eris_calib, _m9)
                            else:
                                # 两段显示：bucket_n 含 200 轮预热（预热期同样递增）——
                                # 旧实现直接对 300 取 min，第 300~500 轮恒显「300/300」
                                _n9 = _E9.bucket_n(self._eris_calib, _m9)
                                _warm9 = min(_n9, _E9.CALIB_SKIP)
                                _cal9 = min(max(0, _n9 - _E9.CALIB_SKIP), _E9.CALIB_N)
                                _eb = "预热 %d/%d · 标定 %d/%d" % (_warm9, _E9.CALIB_SKIP,
                                                                   _cal9, _E9.CALIB_N)
                        except Exception:
                            _eb = "?"
                        _log_write("诊断", "学习状态: 画像 %d · 锚点 %d · 回退 %d · 稳态抑制计数 %d · "
                                           "策略权重[%s] · 当前参数 %s · 模式 %s · 效率基线 %s"
                                   % (_prof, _anch, _back, _sup, " ".join(_pw), _ps,
                                      CFG.get("clean_mode", "normal"), _eb))
                        # 试探结果构成（2026-09-26 实测缺口：日志侧成功率与画像侧口径不同，
                        # 分不清"缺页超预算"与"未完成/超时"）⇒ 分桶累计，便于据此定策
                        try:
                            _st = getattr(self.cleaner, "stats", {}) or {}
                            _pt = int(_st.get("probe", 0) or 0)
                            _pf = int(_st.get("probe_pf_fail", 0) or 0)
                            _pi = int(_st.get("probe_incomplete", 0) or 0)
                            _log_write("诊断", "试探统计: 累计 %d · 合格 %d · 缺页超预算 %d · 未完成/超时 %d"
                                       % (_pt, max(0, _pt - _pf - _pi), _pf, _pi))
                        except Exception:
                            pass
                    except Exception:
                        pass
                    self.judger.purge_expired()
                    self.learner.save(self._state_file)
                    self._save_eris_state()  # ERIS 分位数窗随周期保存：运行中崩溃（watchdog 重启）不丢
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
                self._cycle_probe = (probe_ok, len(probe_results or []))

                # 累计图表数据 — 每轮必定推送，chart_accum 即本轮净释放
                cur_freed = float(s['freed_mb'])
                cycle_freed = cur_freed - self._chart_last_freed
                self._chart_last_freed = cur_freed
                chart_accum = max(0.0, cycle_freed)
                # 每轮必定推送一个柱，零释放轮也占位，图表与日志严格一一对应
                # ⚠ 时序（2026-09-11 修正）：本周期口径数据必须先备齐再推——否则 ERIS 用到的是
                #   上一轮的 PF 与本轮释放量（旧实现 PF 在推送之后才更新 ⇒ [效率] 行慢一拍）
                self._cycle_freed_mb = chart_accum
                pf_delta_cycle = _drain_pf_delta(self.judger)
                self._cycle_pf = float(pf_delta_cycle or 0)
                self._push_round(chart_accum, m["pct"], harvest_partial, game_seen)
                # Layer3 周期增量基线（累计口径会让诊断误判"持续触发"，导致 gate 持续爬升）
                l3_ran_cur = s.get('layer3_ran', 0)
                l3_extra_cur = s.get('layer3_extra', 0)
                l3_ran_delta = max(0, l3_ran_cur - self._last_l3_ran)
                l3_extra_delta = max(0, l3_extra_cur - self._last_l3_extra)
                self._last_l3_ran = l3_ran_cur
                self._last_l3_extra = l3_extra_cur
                # deepen 周期增量（2026-09-28 审查）：cleaner.stats 的 deepen 计数永不重置，
                # 原样传入会让 EFIS 的 waste 判定退化为终身均值——与 layer3 同口径按周期增量
                _dp_cnt_cur = s.get('deepen_cnt', 0)
                _dp_extra_cur = s.get('deepen_extra', 0)
                deepen_cnt_delta = max(0, _dp_cnt_cur - self._prev_deepen_cnt)
                deepen_extra_delta = max(0, _dp_extra_cur - self._prev_deepen_extra)
                self._prev_deepen_cnt = _dp_cnt_cur
                self._prev_deepen_extra = _dp_extra_cur
                if not harvest_partial:
                    stats = {
                        'mem_pct': m['pct'],
                        'mode': mode,
                        'game': game_seen,  # 游戏态冻结判定（efis.tick 据此清窗并跳过调参）
                        'trimmed_cnt': self._cycle_trimmed,
                        'failed_cnt': self._cycle_failed,
                        'total_attempts': self._cycle_trimmed + self._cycle_failed,
                        'cycle_freed': cycle_freed,
                        # ── EFIS 诊断输入全量补齐（11 字段，调参分支获得真实数据）──
                        'theta_mean': _prof_theta_mean(self.learner),
                        'theta_above_06': _prof_theta_above(self.learner),
                        'agg': agg,
                        'pf_delta': pf_delta_cycle,
                        'cycle_duration': max(1.0, time.time() - cycle_start),
                        'deepen_cnt': deepen_cnt_delta,
                        'deepen_extra': deepen_extra_delta,
                        'layer3_ran': l3_ran_delta,
                        'layer3_extra': l3_extra_delta,
                        # list() 快照迭代（2026-09-28 审查）：straggler trim 线程（_bounded_submit
                        # 超时任务自然跑完）可能并发 mark_failed 增键，裸迭代会 RuntimeError 击落守护线程
                        'cooldown_cnt': sum(1 for t in list(self.judger.cooldown.values()) if t > time.time()),
                        'repeat_fail': len(failed),
                        'suppress_cnt': self.judger.suppress_cnt,  # 锚点抑制拦截数（EFIS 自平衡诊断；每轮由 update_activity 重置）
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
                        self.judger.sync_pid_from_cfg()  # 调参成果即时进 PID（此前延迟到重启）
                        self.judger.cfg['clean_passes'] = CFG.get('clean_passes', 4)
                        _save_cfg()  # EFIS 调参落盘：重启后消费方与引擎参数一致
                        _log_write("调参", efis_msg)  # 调参决策入统一日志
                        # 同步 Kalman 超参数到 learner（2026-08-14 审查：新画像 + 已有画像
                        # 一并更新——参数"配置可调"对全体生效，防名不副实）
                        _kr = params.get('kalman_r', 5.0)
                        self.learner._kalman_r = _kr
                        # list() 快照迭代（2026-09-06 审查 F2）：手动优化线程可并发增键，
                        # 直接迭代会 RuntimeError 击落守护线程（无局部兜底）
                        for _p in list(self.learner.profiles.values()):
                            _p.kalman.r = _kr
                    # 调参消息显示并入周期末分组批（cycle_groups 组装处），不再独立推送

                # 元认知（harvest 超时时跳过，避免零数据污染诊断）
                if not harvest_partial:
                    meta_findings = []
                    try:
                        meta_findings = self.learner.meta.tick()
                    except Exception as e:
                        _log_write("异常", f"元认知异常: {e!r}")
                    if meta_findings:
                        for finding in meta_findings:
                            self._cycle_log_groups.append([finding])

                # ── 收集并显示算法日志消息 ──
                # 游戏检测消息改走批量通道，防被 _log_batch 清屏擦除
                for msg in self.cleaner.pop_game_msgs():
                    # 文件侧由周期末 [界面] 兜底循环单写（2026-09-28 审查：此处再写 [决策]
                    # 会同条双行——同一条游戏启停消息在 memwise.log 出现两次）
                    self._cycle_log_groups.append([msg])
                for msg in self.learner.pop_info():
                    self._cycle_log_groups.append([msg])
                for msg in self.cleaner.pop_info():
                    self._cycle_log_groups.append([msg])

                deep_triggered = self.cleaner.summary().get("layer3_ran", 0) > layer3_ran_start
                # 合并压力+深度清理日志（与上一周期峰值比较，仅变化时输出）
                agg_peak = agg_max
                mem_str = self.judger._mem_label(m['pct'])
                a_cur_raw = self.judger._agg_label(agg_peak)
                # 单字标签（高/中/低）必须在此精确翻译：显示层片段替换的门槛是 2 字，
                # 单字只认精确匹配，否则英文界面下残留中文（2026-09-26 用户报告）
                a_cur = tr(a_cur_raw)
                last_peak = self._last_agg_peak
                last_mem = self._last_pressure_mem
                if last_peak is None:
                    change_str = a_cur  # 首轮直接显示
                elif a_cur_raw == self.judger._agg_label(last_peak):
                    change_str = tr(f"维持{a_cur_raw}")
                else:
                    change_str = f"{tr(self.judger._agg_label(last_peak))}→{a_cur}"
                deep_changed = deep_triggered != self._last_deep_triggered
                if last_mem != mem_str or change_str != self._last_pressure_chg or deep_changed:
                    deep_str = " · 已触发深度清理" if deep_triggered else ""
                    self._cycle_log_groups.append(
                        [f"📈 内存 {m['pct']:.0f}%（{mem_str}）· 清理强度：{change_str}{deep_str}"])
                    self._last_pressure_mem = mem_str
                    self._last_pressure_chg = change_str
                    self._last_agg_peak = agg_peak
                    self._last_deep_triggered = deep_triggered
                # 周期汇总：文件侧由 [清理] 直写（毫秒时间戳+独立类别）；GUI 仅显示不重复落盘
                summary_line = (f"本轮优化 {fmt_label(cycle_freed)} · 净释放 {fmt_label(getattr(self, '_cycle_net_drop_mb', 0.0))} · "
                                f"系统杂项 {fmt_count(cycle_standby)} · "
                                f"整理 {fmt_count(self._cycle_trimmed)} 进程 · "
                                f"试探 {len(probe_results)} ({probe_ok}成功)")
                # 模式切换标注（2026-09-11 用户定稿 + 当晚措辞修正）：只在与上一周期模式不同时，把
                # 「 · 后续模式：xx→xx」追加到**当行**日常字段末尾——用"后续模式"明确表示**下一周期起**
                # 生效（本轮实际执行仍是旧模式），避免被误读为"本轮已切换"；未切换则只输出日常字段
                _cur_mode = getattr(self.cleaner, "_last_mode", None) or CFG.get("clean_mode", "normal")
                if getattr(self, "_last_logged_mode", None) not in (None, _cur_mode):
                    summary_line += " · 后续模式：%s→%s" % (self._last_logged_mode, _cur_mode)
                self._last_logged_mode = _cur_mode
                if CFG.get("log_to_file"):
                    _log_write("清理", summary_line)
                    # 明细行（2026-09-11 用户要求"日志要能定位问题"）：系统操作计数 + 释放前三 +
                    # 本轮判定拦截原因统计（为什么某些进程没被清理）
                    try:
                        _ops = "待机 %s · 修改页 %s · 文件缓存 %s · 卷 %s · 注册表 %s" % (
                            s.get("standby", 0), s.get("modified", 0), s.get("filecache", 0),
                            s.get("volume", 0), s.get("registry", 0))
                        _top = sorted([t for t in (l2_results or []) if len(t) >= 3 and t[1]],
                                      key=lambda t: -t[2])[:3]
                        _top_s = ", ".join("%s %.0fMB" % (getattr(t[0], "name", "?"), t[2] / (1 << 20))
                                           for t in _top) or "无"
                        _rs = getattr(self.cleaner, "_cycle_reasons", {}) or {}
                        _rs_s = ", ".join("%s %d" % (k, v) for k, v in
                                          sorted(_rs.items(), key=lambda kv: -kv[1])[:8]) or "无"
                        _log_write("清理", "明细: %s · 释放前三 %s · 拦截[%s] · 内存 %d%%(可用 %.1fGB)"
                                   % (_ops, _top_s, _rs_s, (m or {}).get("pct", 0),
                                      ((m or {}).get("avail", 0) or 0) / (1 << 30)))
                    except Exception:
                        pass
                # 回涨状态机已前移到本轮强度决策之前（2026-09-26）——此处不再重复判定/播报
                # 周期末分组输出（2026-08-30）：汇总/调参/压力/游戏/紧急等各自成组，
                # 展示层逐组原子写入（组间 ≤7 接续 / >7 清屏；组内可超 7 完整呈现）。
                # 曾见 summary 先入队、log_batch 后入队时被后者的清屏抹掉——分组化后同批
                # 各组在同一事件内顺序写入，队列竞争不再可能
                cycle_groups = [[summary_line]]
                if efis_msg:
                    cycle_groups.append(["[EFIS] " + efis_msg])  # 周期成果同批（[调参] 已直写文件）
                cycle_groups += self._cycle_log_groups
                self.events.put(('display_groups', cycle_groups))
                if CFG.get("log_to_file"):
                    # 各组内容（压力/游戏/决策等）直写 [界面]，与 [清理] 分开，去重保持
                    for g in self._cycle_log_groups:
                        for msg in g:
                            _log_write("界面", msg)
                # 状态栏（累计数据）
                self.events.put(('upd_ui', (s, m, "🟢 守护中")))
                self.events.put(('chart', None))
                elapsed = time.time() - cycle_start
                # 周期补偿：超时累积债务，下一轮 deadline 中扣除；提前完成则还债
                if elapsed > interval:
                    overtime_debt = min(30, overtime_debt + (elapsed - interval))
                else:
                    overtime_debt = max(0, overtime_debt - (interval - elapsed))
                # 分段睡眠：停止守护即时生效（不阻塞最长一个周期）
                remaining = max(0.5, interval - elapsed)
                while remaining > 0 and self._running:
                    time.sleep(min(0.5, remaining))
                    remaining -= 0.5
                if not self._running:
                    return  # 停止守护后立即退出，不提交多余回调
        except Exception as e:
            import traceback
            self._dae_error = f"{e}\n{traceback.format_exc()}"
            self._running = False
        finally:
            try:
                if h_low:
                    winapi.close_handle(h_low)
            except Exception:
                pass
            # 释放守护互斥 mutex（守护线程结束即放行 CLI daemon）
            if self._daemon_mutex is not None:
                try:
                    ctypes.windll.kernel32.CloseHandle(self._daemon_mutex)
                except Exception:
                    pass
                self._daemon_mutex = None
            self.events.put(('dae_stopped', None))

    # ── 工作集硬上限（高级选项，设计 v2.1-v2.5）──

    def _apply_ws_caps(self, snaps):
        """对 Active 规则的活 PID 施加/维持工作集硬上限（幂等 syscall）。

        五守卫：本程序自身 / 系统核心 / 游戏 PID 树 / 系统目录 / 规则数（config 层）。
        连续失败 ≥3 次的规则降频至每 10 周期重试一次（v2.3 重试风暴防护）。
        全程持 _ws_cap_lock：与 GUI 增删串行（v2.1 R1/R2）；判定层读无锁 frozenset。
        cap 一经设置即持续到解除或目标退出（配额属目标进程），无需每轮重设——
        簿记只记未施加的新 PID。"""
        rules = CFG.get("ws_caps") or {}
        if not isinstance(rules, dict):
            rules = {}
        by_path = {}
        for s in snaps:
            p = getattr(s, "path", None)
            if p:
                by_path.setdefault(p.lower().replace("/", "\\"), []).append(s.pid)
        self._ws_cap_tick = getattr(self, "_ws_cap_tick", 0) + 1
        game_pids = getattr(self.judger, "_game_pid_set", set()) or set()
        with self._ws_cap_lock:
            self.judger.set_capped_paths(rules.keys())
            for path, rule in rules.items():
                pids = by_path.get(path) or []
                if not pids:
                    continue
                if _is_self_path(path) or _JudgerCls._is_system_path(path):
                    continue  # 自身/系统目录（B1 守卫；手改配置也拦在这里）
                fail = self._ws_cap_fail.get(path, 0)
                if fail >= 3 and self._ws_cap_tick % 10 != 0:
                    continue  # 重试风暴降频（v2.3）
                applied = self._ws_cap_applied.setdefault(path, {})
                for pid in pids:
                    if pid in applied or pid in game_pids:
                        continue  # 已施加 / 游戏 PID 树守卫
                    ok, reason, orig_max = winapi.set_ws_cap(pid, int(rule.get("mb", 0)) << 20)
                    if ok:
                        applied[pid] = orig_max
                        self._ws_cap_fail.pop(path, None)
                        if path not in self._ws_cap_announced:
                            self._ws_cap_announced.add(path)
                            _bname = path.rsplit("\\", 1)[-1]
                            self._cycle_log_groups.append(
                                [f"⛨ 已设置工作集硬上限（{rule.get('mb')}MB）：{_bname}"])
                    else:
                        self._ws_cap_fail[path] = fail + 1
                        if fail + 1 == 3 and path not in self._ws_cap_announced:
                            self._ws_cap_announced.add(path)
                            _bname = path.rsplit("\\", 1)[-1]
                            self._cycle_log_groups.append(
                                [f"⛨ 工作集硬上限设置失败（{reason}）：{_bname}"])

    def ws_cap_rule_added(self, path, orig_max, pid=None):
        """GUI 设置成功后的接线：判定快照与簿记刷新（锁内；配置由调用方先写好）。"""
        with self._ws_cap_lock:
            self.judger.set_capped_paths((CFG.get("ws_caps") or {}).keys())
            if pid is not None and orig_max:
                self._ws_cap_applied.setdefault(path, {})[pid] = orig_max

    def ws_cap_rule_removed(self, path):
        """GUI 删除规则：先对簿记内活 PID 解除（disable+还原 per-pid orig_max），
        再清簿记/失败计数/锚点/回弹（B5：cap 期间学到的假稳态不可留），最后刷新判定快照。"""
        with self._ws_cap_lock:
            applied = self._ws_cap_applied.pop(path, {})
            for pid, orig in applied.items():
                try:
                    winapi.clear_ws_cap(pid, orig)
                except Exception:
                    pass
            self._ws_cap_fail.pop(path, None)
            self._ws_cap_announced.discard(path)
            self.judger.set_capped_paths((CFG.get("ws_caps") or {}).keys())
            self.learner.stable_anchors.anchors.pop(path, None)
            for _d in (self.learner.rebound.ewma, self.learner.rebound.count,
                       self.learner.rebound.backoff_until, self.learner.rebound.last_record):
                _d.pop(path, None)

    # ── 轮次推送（图表数据产生时即算 ERIS——原渲染时计算，消除渲染时序耦合）──
    def _push_round(self, chart_accum, mem_pct, harvest_partial, game_seen=None):
        self._chart_bar_seq += 1
        # 本轮真实清理模式（含 quick；未清理过则取配置模式）——分桶/锚点/K 全按它取
        _mode = getattr(self.cleaner, "_last_mode", None) or CFG.get("clean_mode", "normal")
        from core import eris as _E
        _k = _E.k_value(self._eris_calib, _mode)   # 冻结基线 K（自标定期总分 p92，日志可见）
        with self._chart_lock:
            self._chart_data.append(chart_accum)
            self._chart_cycle_meta.append((self._chart_bar_seq, self._cycle_trimmed,
                self._cycle_failed, mem_pct, self._failed_weight, harvest_partial))
        # ERIS：数据产生时逐点计算（原逻辑在图表渲染时按 seq 增量处理——等价：每轮一点一次计算）
        try:
            _pk, _pt = getattr(self, "_cycle_probe", (0, 0))
            result = self._compute_eris(list(self._chart_data), self._cycle_trimmed,
                                        self._cycle_failed, mem_pct, self._failed_weight,
                                        probe_ok=_pk, probe_total=_pt, update_state=True,
                                        game_run=game_seen)
            self._eff_data.append(result["total"])
            self._eff_factors.append(result.get("factors", ["冷启动"]))
            # [效率] 逐轮落盘（2026-09-11 用户反馈"日志看不到效率值"）：效率/词条/五维分数/原始值/校准进度
            try:
                    _log_write("效率", "效率 %.0f%% · %s · 分[%s] · 原[%s] · 输入[整理 %s 失败 %s 试探 %s/%s PF %s] · 有效[%s] · K %.0f · 校准 n=%s · 模式 %s%s" % (
                        result.get("total", 0.0),
                        " ".join(result.get("factors", [])[:2]),
                        " ".join("%.0f" % x for x in result.get("scores", [])),
                        " ".join(("-" if x is None else "%.4g" % x) for x in result.get("raws", [])),
                        self._cycle_trimmed, self._cycle_failed,
                        (self._cycle_probe or (0, 0))[0], (self._cycle_probe or (0, 0))[1],
                        getattr(self, "_cycle_pf", 0),
                        ",".join(str(j) for j in (result.get("valid") or [])) or "无",
                        _k,
                        self._eris_calib.get("modes", {}).get(_mode, {}).get("n", "?"),
                        _mode, " · 游戏" if getattr(self, "_last_eris_game_mode", False) else ""))
            except Exception:
                pass
        except Exception:
            self._eff_data.append(80.0)
            self._eff_factors.append(["计算异常"])

    # ── ERIS v6：IQR分位数归一化五维加权和（80±40×(raw−p50)/IQR，trimmed IQR + 维级窗口）──
    # ── ERIS v7：五维绝对标尺（四锚点分段线性 + N=3 平滑 + Σ÷K；设计见记忆 learning-engine-specs §B4）──
    def _eris_hist_for(self, mode):
        """取该模式的平滑窗（按需创建）：四模式各持一份，互不带偏。
        调用方持 `_eris_lock`（`_compute_eris` 内）或处于单线程初始化期（`_load_eris_state`）——
        本方法自身不加锁（`threading.Lock` 不可重入，重复加锁会死锁）。"""
        from core.eris import new_hist as _new_hist
        h = self._eris_hist_by_mode.get(mode)
        if h is None:
            h = _new_hist()
            self._eris_hist_by_mode[mode] = h
        return h

    def _compute_eris(self, data, trimmed_cnt, failed_cnt, mem_pct, failed_weight=0.5,
                      probe_ok=0, probe_total=0, update_state=True, game_run=None):
        """返回 {"total": 效率%, "factors": [...]}（接口与 v6 一致，展示层无需改动）。
        词条：效率升 → "本轮分数上升"的维中取最高分者报正面；降 → "本轮分数下降"的维中取最低分者报负面；
        |Δ效率| < 1 → 相对平稳（趋势仍按真实方向记录，不再打断连续链）；同一维正负两面不作相邻两轮重复（词条层抑制，2026-09-26 用户规定）。"""
        from core import eris as E
        # 实际生效模式（优先取本轮 optimize 的真实模式：紧急轮等会走 full，必须让分桶学真值）
        _mode = getattr(self.cleaner, "_last_mode", None) or CFG.get("clean_mode", "normal")
        if not data:
            return {"total": 0.0, "factors": ["冷启动"]}
        # ── 五维原始量（v9：全部有界比值、越大越好；无数据一律 None ⇒ 记中性 50）──
        _proc_mb = float(getattr(self, "_cycle_proc_mb", 0.0) or 0.0)        # 本周期**进程清理**释放量（优化代价维分子）
        _net_mb = float(getattr(self, "_cycle_net_drop_mb", 0.0) or 0.0)     # 本周期净下降（周期末可用 − 周期初可用）
        _freed_mb = float(getattr(self, "_cycle_freed_mb", 0.0) or 0.0)      # 本周期总释放（全部通道）
        # ① 净优化量 = 净下降 ÷ 总释放：释放量里净留存下来的比例（2026-09-27 重定义：
        #    旧口径"进程释放÷(进程释放+全机回涨)"分子分母世界不同 ⇒ 恒贴 0，实机日志实证）
        #    净下降 ≤ 0（外部需求吞没释放，不可归因）⇒ 记无数据，该轮由其余四维归一承担
        raw1 = (_net_mb / _freed_mb) if (_freed_mb > 0 and _net_mb > 0) else None
        # ② 优化代价 = 进程释放 MB ÷ 缺页代价（每单位代价换回多少）
        _pf = float(getattr(self, "_cycle_pf", 0) or 0)
        raw2 = (_proc_mb / _pf) if (_pf > 0 and _proc_mb > 0) else None
        # ③ 优化通畅 = 成功 ÷（成功 + 失败）：无任何尝试 ⇒ 无数据
        _att = int(trimmed_cnt) + int(failed_cnt)
        raw3 = (float(trimmed_cnt) / _att) if _att > 0 else None
        # ④ 试探命中 = 试探合格 ÷ 试探总数
        raw4 = (float(probe_ok) / float(probe_total)) if probe_total else None
        # ⑤ 优化量 = 本轮释放 MB（与日志「本轮释放」同口径；基线换算在 ERIS 内按冻结基线完成）
        raw5 = float(getattr(self, "_cycle_freed_mb", 0.0) or 0.0) or None
        raws = [raw1, raw2, raw3, raw4, raw5]
        _nodata = [r is None for r in raws]
        # 跟踪器只学"该模式参与合成的维"（其余维不喂，避免用不到的数据把分位带偏）；
        # 游戏轮次照常算分但不喂（游戏态清理行为与常态不同，混入会拉偏分位）
        _decl = E.MODE_VALID_DIMS.get(_mode, E.MODE_VALID_DIMS["normal"])
        _skip_track = [(_nodata[j] or (j not in _decl)) for j in range(5)]
        # 游戏轮判定按"整周期 game_seen"（2026-09-28 审查）：周期内游戏任意时刻开启即整轮
        # 不喂标定（与 EFIS 的 game_seen 口径一致）——原用 push 时刻的瞬时 game_mode，
        # 游戏"周期内开过又退出"的轮次会漏判进标定窗口；game_run=None（直接调用/测试）回退瞬时值
        _game = bool(getattr(self.cleaner, "game_mode", False)) if game_run is None else bool(game_run)
        self._last_eris_game_mode = _game
        # ── 平滑 → 赋分 → 效率 → 词条/趋势 ──
        with self._eris_lock:
            # 模式切换 ⇒ 先重置"上一轮"基线（分数/效率/趋势序列都是按模式尺度比较的，
            # 跨模式比较会冒出虚假的升降/持续改善）：切换后的**第一个周期**回归"分析中"，
            # 下一轮起用新模式自己的数据比较。平滑窗与冻结基线都按模式分桶，不受切换影响。
            if self._eris_hist_mode is not None and self._eris_hist_mode != _mode:
                self._eris_prev_scores = None
                self._eris_last_word = None   # 上轮词条 (维度, 方向)：相邻两轮同维正负不复读（2026-09-26 用户规定）
                self._eris_prev_eff = None
                self._eris_trend = []
            self._eris_hist_mode = _mode
            _hist = self._eris_hist_for(_mode)
            sm = [(None if _nodata[j] else E.smooth3_append(_hist[j], raws[j]))
                  for j in range(5)]
            scores, self._eris_calib = E.calibrate_and_score(sm, self._eris_calib,
                                                              update=update_state, skip=_skip_track,
                                                              mode=_mode, game=_game)
            _valid = E.valid_dims(_mode, _nodata)
            _T = E.total_of(scores, valid=_valid, mode=_mode)          # 有效维均分折算值（0~700）
            _k = E.k_value(self._eris_calib, _mode)                    # 冻结基线 K（自标定期总分 p92）
            eff = (_T / _k * 100.0) if _k > 0 else 0.0
            prev_scores, prev_eff = self._eris_prev_scores, self._eris_prev_eff
            _avoid = getattr(self, "_eris_last_word", None)   # 相邻抑制：上轮 (维度, 方向)
            trend_val = 0
            if prev_eff is None or len(data) <= 3:
                factors = ["影响因素分析中…"]
                self._eris_last_word = None
            elif round(eff) >= E.SUPER_TH:   # 与显示值一致（用户看到 ≥100% 才判超常）
                j = E.pick_factor(scores, prev_scores, True, avoid=_avoid)
                if j is None:
                    j = max(range(5), key=lambda i: scores[i])
                factors = [E.DIM_WORDS[j][0], "🚀效率超常"]
                self._eris_last_word = (j, True)
                trend_val = 99
            elif round(eff) <= E.WARN_TH:    # 与显示值一致（用户看到 ≤50% 才判异常）
                j = E.pick_factor(scores, prev_scores, False, avoid=_avoid)
                if j is None:
                    j = min(range(5), key=lambda i: scores[i])
                factors = [E.DIM_WORDS[j][1], "⚠效率异常"]
                self._eris_last_word = (j, False)
                trend_val = -99
            else:
                delta = eff - prev_eff
                trend_val = 1 if delta > 0 else (-1 if delta < 0 else 0)
                if abs(delta) < 1.0:
                    factors = ["相对平稳"]
                    self._eris_last_word = None   # 本轮未报维度 ⇒ 抑制链断开
                else:
                    up = delta > 0
                    j = E.pick_factor(scores, prev_scores, up, avoid=_avoid)
                    if j is None:
                        diffs = [scores[i] - (prev_scores[i] if prev_scores else 0.0) for i in range(5)]
                        j = max(range(5), key=lambda i: abs(diffs[i]))
                        up = diffs[j] >= 0
                    factors = [E.DIM_WORDS[j][0] if up else E.DIM_WORDS[j][1]]
                    self._eris_last_word = (j, up)
                    if len(self._eris_trend) >= 2 and self._eris_trend[-1] == self._eris_trend[-2] == trend_val:
                        factors.append("🔥持续改善" if trend_val > 0 else "⚠持续下滑")
            if update_state:
                self._eris_trend.append(trend_val)
                if len(self._eris_trend) > 10:
                    self._eris_trend = self._eris_trend[-10:]
                self._eris_prev_scores = scores
                self._eris_prev_eff = eff
        return {"total": eff, "factors": factors, "scores": scores, "raws": sm, "valid": list(_valid)}
    def _save_eris_state(self):
        with self._eris_save_lock:
            try:
                import json, os
                from core.eris import ERIS_STATE_V as _SV
                payload = {"v": _SV,
                           # 平滑窗按清理模式分桶（v8）：模式间量级不同，混窗会互相带偏
                           "hist_by_mode": {m: [list(h) for h in hs]
                                            for m, hs in getattr(self, "_eris_hist_by_mode", {}).items()},
                           "prev_scores": getattr(self, "_eris_prev_scores", None),
                           "prev_eff": getattr(self, "_eris_prev_eff", None),
                           "trend": list(getattr(self, "_eris_trend", []))}
                root = os.path.dirname(self._state_file)
                path = os.path.join(root, "memwise_eris_ewma.json")
                tmp = f"{path}.{os.getpid()}.tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(payload, f)
                os.replace(tmp, path)
                # ② 校准数据独立成文件（不进配置包、恢复默认单独清除，见记忆 §B5）
                try:
                    cpath = os.path.join(root, "memwise_eris_calib.json")
                    ctmp = f"{cpath}.{os.getpid()}.tmp"
                    with open(ctmp, "w", encoding="utf-8") as f:
                        json.dump(getattr(self, "_eris_calib", {}), f)
                    os.replace(ctmp, cpath)
                except Exception:
                    pass
            except Exception:
                pass

    def _load_eris_state(self):
        """加载 ERIS 状态（当前 schema 见 `core.eris.ERIS_STATE_V`）。
        · v8：平滑窗按清理模式分桶（`hist_by_mode`）——逐桶读取，坏桶跳过
        · v7：单桶扁平 `hist` 迁移进**当前配置模式**的桶（最多 3 个样本，取近值即可，不重要的取舍）
        · v6 及更早（分位数窗）：忽略并重建（文件保留不删）
        会话隔离：prev_scores/prev_eff/trend 每次 daemon 启动重置，仅平滑窗跨重启保留。"""
        from core.eris import SMOOTH_N as _SN, ERIS_STATE_V as _SV
        try:
            if getattr(self, "_eris_hist_by_mode", None) and any(
                    any(h) for h in self._eris_hist_by_mode.values()):        # 热重启：窗内数据保留
                self._eris_prev_scores = None
                self._eris_last_word = None   # 上轮词条 (维度, 方向)：相邻两轮同维正负不复读（2026-09-26 用户规定）
                self._eris_prev_eff = None
                self._eris_trend = []
                self._eris_hist_mode = None
                return
        except Exception:
            pass
        self._eris_hist_by_mode = {}

        def _pull(seq, hist):
            for v in list(seq)[-_SN:]:
                if isinstance(v, (int, float)):
                    hist.append(float(v))

        try:
            import json, os
            path = os.path.join(os.path.dirname(self._state_file), "memwise_eris_ewma.json")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload, dict) and payload.get("v") == _SV:
                    for m, hs in (payload.get("hist_by_mode") or {}).items():
                        if not isinstance(m, str) or not isinstance(hs, list) or len(hs) != 5:
                            continue
                        hist = self._eris_hist_for(m)
                        for j, one in enumerate(hs):
                            if isinstance(one, list):
                                _pull(one, hist[j])
                elif isinstance(payload, dict) and payload.get("v") == 7:
                    # v7 单桶 ⇒ 迁入当前模式（读引擎模块级 CFG；未被 init_runtime 注入时按 normal）
                    h = payload.get("hist")
                    if isinstance(h, list) and len(h) == 5:
                        _m = (globals().get("CFG") or {}).get("clean_mode", "normal")
                        if _m not in ("quick", "normal", "deep", "full"):
                            _m = "normal"
                        hist = self._eris_hist_for(_m)
                        for j, one in enumerate(h):
                            if isinstance(one, list):
                                _pull(one, hist[j])
        except Exception:
            pass
        self._eris_prev_scores = None
        self._eris_last_word = None   # 上轮词条 (维度, 方向)：相邻两轮同维正负不复读（2026-09-26 用户规定）
        self._eris_prev_eff = None
        self._eris_trend = []
        self._eris_hist_mode = None      # 首轮建立基线，不算"切换"（不触发基线重置）
        # ② 自校准状态（独立文件；缺失/损坏/版本不符 ⇒ 冷启动，恢复默认后即此状态）
        try:
            import json as _json, os as _os
            from core.eris import new_calib as _new_calib, calib_valid as _calib_valid
            _cpath = _os.path.join(_os.path.dirname(self._state_file), "memwise_eris_calib.json")
            _cal = None
            if _os.path.exists(_cpath):
                with open(_cpath, "r", encoding="utf-8") as _f:
                    _cal = _json.load(_f)
            self._eris_calib = _cal if (_cal and _calib_valid(_cal)) else _new_calib()
        except Exception:
            from core.eris import new_calib as _new_calib
            self._eris_calib = _new_calib()
