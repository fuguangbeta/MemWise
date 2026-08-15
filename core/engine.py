"""
MemWise 无 UI 引擎 —— 守护循环 / ERIS / 轮次数据 / 事件队列 / 看门狗
与展示层（tkinter GUI）解耦：GUI 只消费 events 与数据快照。
本文件为纯搬移（原 memwise_gui.py 内逻辑逐行迁移，不改行为），仅一处设计变更：
ERIS 计算时机从"图表渲染时"改为"轮次数据产生时"（消除渲染时序耦合，见 _push_round）。
"""

import os, sys, time, threading, math, queue, concurrent.futures, datetime, atexit, ctypes, subprocess
from collections import deque

# ── 数据/资源路径（与原 GUI 同规则：exe 旁；dist 目录特判上移）──
try:
    ctypes_shcore = __import__("ctypes")
    try:
        ctypes_shcore.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes_shcore.windll.user32.SetProcessDPIAware()
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
    res_dir = sys._MEIPASS                       # 资源文件（只读，打包内嵌）
else:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    res_dir = base
if base not in sys.path:
    sys.path.insert(0, base)

# ═══ 看门狗（进程级，UI 无关）：崩溃自动重启 + 守护状态记录 ═══
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
        for name in ("memwise_state.json", "memwise_efis_state.json", "memwise_eris_ewma.json",
                     "watchdog.json", "memwise.log", "memwise.log.1"):
            src = os.path.join(base, name)
            dst = os.path.join(base, "data", name)
            if os.path.isfile(src) and not os.path.isfile(dst):
                os.replace(src, dst)
    except Exception:
        pass


_migrate_runtime_data()


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
                with open(wd_path + ".tmp", "w", encoding="utf-8") as f:
                    json.dump({"pid": p.pid, "ts": now, "crash_count": len(crash_history),
                               "daemon": d.get("daemon", False)}, f)
                os.replace(wd_path + ".tmp", wd_path)
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
from core.eris import iqr_dim, validate_state  # ERIS 纯函数核心（与回归测试共用）
from core.i18n import tr, set_language  # 界面语言
from core.config import load as _load_cfg
from core.config import get_state_path
import core.config as _config

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
        # 完成标记：改名防下次启动重复并入（2026-08-14 审查：原无标记，每次启动重复 append）
        try:
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
    _LOG_DIR = os.environ.get("MEMWISE_LOG_DIR") or os.path.join(base, "data")
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
        _log_write("启动", f"MemWise v4.1.080 启动 · PID {os.getpid()} · 参数:{' '.join(sys.argv[1:]) or '无'}")
    except Exception:
        _LOG_FD = None


def _diag_log(msg):
    """诊断日志：写入统一运行日志"""
    _log_write("诊断", msg)


# ── 配置/状态路径（模块级单例：引擎与展示层共享同一 CFG/STATE_FILE）──
STATE_FILE = get_state_path()
CFG = _load_cfg()
set_language(CFG.get("language", "zh_CN"))  # 界面语言加载（设置面板可即时切换）

def _save_cfg():
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
    """画像 Thompson θ 均值（≥2 样本才参与）"""
    ps = [p for p in learner.profiles.values() if p.total_samples >= 2]
    return sum(p.thompson_theta for p in ps) / len(ps) if ps else 0.3


def _prof_theta_above(learner):
    """θ>0.6 画像占比"""
    ps = [p for p in learner.profiles.values() if p.total_samples >= 2]
    return sum(1 for p in ps if p.thompson_theta > 0.6) / len(ps) if ps else 0.0


def _drain_pf_delta(judger):
    """清零并返回本轮 PF 增量（跨周期清零，防污染诊断窗口）"""
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


# ════════════════════════════════════════════════════════════════
# MemWiseEngine —— 无 UI 引擎
# ════════════════════════════════════════════════════════════════
class MemWiseEngine:
    """守护循环 / ERIS / 轮次数据 / 事件队列——不依赖任何 UI 框架。

    事件队列 events（queue.Queue）：动作元组与原 GUI 消息队列格式一致——
    ('log', msg) / ('display', [lines]) / ('log_batch', [lines]) / ('log_op', msg) /
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
        self._chart_eris_last_seq = -1             # 最后进入ERIS的轮次序列号（废弃：解耦后 ERIS 在 _push_round 每轮全量计算，字段保留不删）
        self._chart_bar_seq = 0                    # 全局轮次序列号（守护递增）

        # ERIS 状态（分位数窗/平滑/趋势/防振荡）
        self._eris_lock = threading.Lock()
        self._eris_save_lock = threading.Lock()    # ERIS 状态持久化互斥锁（守护线程与退出线程可能并发写）
        self._eris_bufs = None
        self._eris_p50_ewma = [0.0] * 5
        self._eris_iqr_ewma = [0.0] * 5
        self._eris_ewma_trend = []
        self._eris_prev = None
        self._eris_prev_factor_dim = -1
        self._eris_prev_factor_pos = None
        self._last_eris_game_mode = None
        self._load_eris_ewma()  # 在 daemon 首次调用 _compute_eris 前完成加载

        # 周期基线/去重状态
        self._cycle_trimmed = 0
        self._cycle_failed = 0
        self._failed_weight = 0.5
        self._last_sys_ops = 0
        self._last_l3_ran = 0
        self._last_l3_extra = 0
        self._cfg_mtime = 0
        self._last_agg_peak = None
        self._last_pressure_mem = ''
        self._last_pressure_chg = ''
        self._last_deep_triggered = False
        self._emergency_done_cycle = False
        # 回弹驱动（C 方案，2026-08-14）：harvest 后 WS 基线 + 释放量，供 full 模式 gap 回填率判断
        self._last_harvest_ws = None
        self._last_harvest_freed = 0
        self._refill_hot = False   # 跨周期：是否处于回涨快状态（状态翻转去重，2026-08-14）
        self._refill_cycle = False # 本周期是否触发过回涨快（周期末判定）
        self._refill_total = 0     # 最新回涨量（进入回涨快时展示）

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
        s = self.cleaner.summary()
        self._chart_last_freed = float(s['freed_mb'])
        self._prev_trim_count = s['ws_trim']
        self._prev_fail_count = s.get('failed_feedback', 0)
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
        self._last_harvest_ws = None
        self._last_harvest_freed = 0
        # 回弹状态机跨周期字段一并重置（2026-08-14 审查：仅重置 harvest 两字段时，
        # _refill_hot 残留会致新守护首周期误报"↻ 内存回涨已放缓"）
        self._refill_hot = False
        self._refill_cycle = False
        self._refill_total = 0
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

    # ── 收尾 ──
    def save_state(self):
        try:
            self.learner.save(self._state_file)
        except Exception:
            pass
        self._save_eris_ewma()

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
            try:
                snaps = []
                for i in range(3):
                    snaps = self.sniffer.snapshot(); self.learner.feed(snaps)
                    if i < 2: time.sleep(2)
                self.events.put(('log', f"观察到 {len(snaps)} 个进程"))
                # 候选预览（轻量版）：日志告知将清理范围（复用 can_trim，零新逻辑）
                try:
                    preview = [s.name for s in snaps if self.judger.can_trim(s)[0]]
                    if preview:
                        shown = '、'.join(preview[:5]) + ('…' if len(preview) > 5 else '')
                        self.events.put(('log', f"📋 将清理 {len(preview)} 个进程候选：{shown}"))
                except Exception:
                    pass
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
                self.learner.save(self._state_file)
                m1 = winapi.get_memory_status()
                freed1 = self.cleaner.summary()['freed_mb']
                released = max(0.0, freed1 - freed0)  # 三轮释放量标量总和
                pct_str = f"，可用内存 {m0['pct']}%→{m1['pct']}%" if m0 and m1 else ""
                self.events.put(('log', f"📊 三轮优化合计释放 {released:.1f} MB · 内存净下降 {total_net/(1<<20):.1f} MB{pct_str}"))
                self.events.put(('log_op', f"优化完成 · 三轮合计释放 {released:.1f} MB（净下降 {total_net/(1<<20):.1f} MB）"))
                self.events.put(('opt_done', {
                    "mode": mode, "layer2": all_l2, "probe": all_probe}))
            except Exception:
                import traceback; traceback.print_exc(file=_ERR)
                self.events.put(('log', "⚠ 手动优化异常，已自动恢复"))
                self.events.put(('opt_done', {
                    "mode": mode, "layer2": [], "probe": []}))
            finally:
                self.cleaner._manual_run = False

    def _opt_worker_once(self, mode, ops):
        """守护运行中即时优化的执行体：单轮快照+单轮 optimize（守护周期互斥见调用方注释）"""
        with self.cleaner._exec_lock:
            self.cleaner._manual_run = True
            try:
                snaps = self.sniffer.snapshot(); self.learner.feed(snaps)
                m0 = winapi.get_memory_status()
                freed0 = self.cleaner.summary()['freed_mb']
                r = self.cleaner.optimize(snaps, self.learner, mode, operations=ops)
                self.learner.save(self._state_file)
                m1 = winapi.get_memory_status()
                freed1 = self.cleaner.summary()['freed_mb']
                released = max(0.0, freed1 - freed0)
                trimmed = [t for t in r.get("layer2", []) if t[1]]
                pct_str = f"，可用内存 {m0['pct']}%→{m1['pct']}%" if m0 and m1 else ""
                self.events.put(('log', f"⚡ 即时优化（{mode}）完成 · 清理 {len(trimmed)} 个进程 · 释放 {released:.1f} MB{pct_str}"))
                self.events.put(('log_op', f"即时优化完成 · 释放 {released:.1f} MB"))
                self.events.put(('opt_done', {
                    "mode": mode, "layer2": r.get("layer2", []), "probe": r.get("probe", [])}))
            except Exception:
                import traceback; traceback.print_exc(file=_ERR)
                self.events.put(('log', "⚠ 即时优化异常，已自动恢复"))
                self.events.put(('opt_done', {
                    "mode": mode, "layer2": [], "probe": []}))
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
                snaps = self.sniffer.snapshot(); self.learner.feed(snaps)

                total_samples = sum(p.total_samples for p in self.learner.profiles.values())
                learned = len(self.learner.profiles)

                if not startup_logged:
                    self.events.put(('log', f"🧠 观察到 {len(snaps)} 个进程 · 已有 {learned} 个画像"))
                    startup_logged = True
                self._cycle_log_buffer = []  # 本轮周期末批量输出缓存
                self._refill_cycle = False  # 周期内触发标记（周期末状态机判定）
                agg_first = self.judger.aggressiveness
                agg_max = agg_first  # 本轮峰值
                layer3_ran_start = self.cleaner.summary().get("layer3_ran", 0)
                deep_triggered = False  # 本轮是否触发过深度清理
                self._emergency_done_cycle = False  # 本轮是否已触发紧急清理（周期内去重）

                # 清理
                mode = CFG.get("clean_mode", "normal")  # 读 CFG 镜像：tk 变量非线程安全，daemon 线程不触碰 Tk 对象
                agg = self.judger.update_pressure(m['pct'])
                ops = CFG.get("clean_operations")
                # 连续优化循环：deadline + 多次 optimize + gap fill + blitz
                m_emerg = winapi.get_memory_status()
                if m_emerg and _emergency_active(m_emerg):
                    agg_emerg = self.judger.update_pressure(m_emerg["pct"])
                    self.cleaner.optimize(snaps, self.learner, "full", operations=ops, aggressiveness=agg_emerg)
                    self.events.put(('log', "⚠ 紧急触发清理(full模式)"))
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
                            snaps = self.sniffer.snapshot(); self.learner.feed(snaps)
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
                            if self.cleaner._game_mode_manual:
                                # 手动模式：实时刷新 PID 保护集（含子进程树），不自动切换模式
                                if game_now:
                                    self.cleaner.judger._game_pid_set = self.cleaner._build_game_pid_set(snaps)
                            elif not self.cleaner.game_mode and game_now:
                                self.cleaner.game_mode = True
                                self.cleaner.judger.game_mode = True
                                self.cleaner.judger._game_pid_set = self.cleaner._build_game_pid_set(snaps)
                                self.cleaner._game_gone_count = 0  # 退出计数重置（与 _layer2_process 同口径）
                                self._cycle_log_buffer.append("🎮 检测到游戏运行 · 启用 游戏模式")
                            elif self.cleaner.game_mode and not game_now:
                                # 2 周期确认退出（2026-08-14 审查：原立即退出与 _layer2_process
                                # 的"连续2周期"口径不一致且会抖动——游戏进程瞬间消失
                                # （反作弊/更新器重启）立即退出又启用；统一计数确认）
                                self.cleaner._game_gone_count = getattr(self.cleaner, '_game_gone_count', 0) + 1
                                if self.cleaner._game_gone_count >= 2:
                                    self.cleaner.game_mode = False
                                    self.cleaner.judger.game_mode = False
                                    self.cleaner.judger._game_pid_set.clear()
                                    self.cleaner._game_gone_count = 0
                                    self._cycle_log_buffer.append("🎮 游戏已退出 · 恢复正常模式")
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
                                # set 无序轮转自然覆盖全池）——full 池扩大后防循环拖慢
                                for ft_pid in list(self.cleaner._fast_track)[:5]:
                                    if ft_pid in self.cleaner.judger._game_pid_set:
                                        self.cleaner._fast_track.discard(ft_pid)
                                        continue
                                    if not self.cleaner.quick_retrim(ft_pid):
                                        self.cleaner._fast_track.discard(ft_pid)
                        snap_skip -= 1
                        m2 = winapi.get_memory_status()
                        if m2:
                            agg = self.judger.update_pressure(m2["pct"]); m = m2
                            agg_max = max(agg_max, agg)
                            # 周期内紧急即时响应：内存飙到阈值立即 full 清理（不等下一周期），每周期至多一次
                            if _emergency_active(m2) and not self._emergency_done_cycle:
                                self._emergency_done_cycle = True
                                self._cycle_log_buffer.append("⚠ 周期内紧急触发清理(full模式)")
                                self.cleaner.optimize(snaps, self.learner, "full",
                                                      operations=ops, aggressiveness=agg)
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
                            gap = min(25.0, gap + 3)
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
                harvest_future = self._harvest_executor.submit(
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
                # 回弹驱动基线（C 方案）：记录 harvest 后总 WS 与释放量，供下一周期 gap 回填率判断
                self._last_harvest_freed = max(result.get("net_freed", 0), 0)
                try:
                    _hs = self.sniffer.snapshot()
                    self._last_harvest_ws = sum(getattr(s, 'ws', 0) for s in _hs)
                except Exception:
                    self._last_harvest_ws = None
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
                        if mtime != self._cfg_mtime:
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
                    self.learner.save(self._state_file)
                    self._save_eris_ewma()  # ERIS 分位数窗随周期保存：运行中崩溃（watchdog 重启）不丢
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
                self._push_round(chart_accum, m["pct"], harvest_partial)
                # 每周期无条件清零 PF 计数（harvest 超时/游戏降频周期也丢弃，防跨周期污染诊断窗口）
                pf_delta_cycle = _drain_pf_delta(self.judger)
                # Layer3 周期增量基线（累计口径会让诊断误判"持续触发"，导致 gate 持续爬升）
                l3_ran_cur = s.get('layer3_ran', 0)
                l3_extra_cur = s.get('layer3_extra', 0)
                l3_ran_delta = max(0, l3_ran_cur - self._last_l3_ran)
                l3_extra_delta = max(0, l3_extra_cur - self._last_l3_extra)
                self._last_l3_ran = l3_ran_cur
                self._last_l3_extra = l3_extra_cur
                if not harvest_partial:
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
                        self.judger.cfg['clean_passes'] = CFG.get('clean_passes', 4)
                        _save_cfg()  # EFIS 调参落盘：重启后消费方与引擎参数一致
                        _log_write("调参", efis_msg)  # 调参决策入统一日志
                        # 同步 Kalman 超参数到 learner（2026-08-14 审查：新画像 + 已有画像
                        # 一并更新——参数"配置可调"对全体生效，防名不副实）
                        _kr = params.get('kalman_r', 5.0)
                        self.learner._kalman_r = _kr
                        for _p in self.learner.profiles.values():
                            _p.kalman.r = _kr
                    if efis_msg:
                        self.events.put(('display', ['[EFIS] ' + efis_msg]))  # 仅显示：[调参] 已直写落盘

                # 元认知（harvest 超时时跳过，避免零数据污染诊断）
                if not harvest_partial:
                    meta_findings = []
                    try:
                        meta_findings = self.learner.meta.tick()
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

                deep_triggered = self.cleaner.summary().get("layer3_ran", 0) > layer3_ran_start
                # 合并压力+深度清理日志（与上一周期峰值比较，仅变化时输出）
                agg_peak = agg_max
                mem_str = self.judger._mem_label(m['pct'])
                a_cur = self.judger._agg_label(agg_peak)
                last_peak = self._last_agg_peak
                last_mem = self._last_pressure_mem
                if last_peak is None:
                    change_str = a_cur  # 首轮直接显示
                elif a_cur == self.judger._agg_label(last_peak):
                    change_str = f"维持{a_cur}"
                else:
                    change_str = f"{self.judger._agg_label(last_peak)}→{a_cur}"
                deep_changed = deep_triggered != self._last_deep_triggered
                if last_mem != mem_str or change_str != self._last_pressure_chg or deep_changed:
                    deep_str = " · 已触发深度清理" if deep_triggered else ""
                    self._cycle_log_buffer.append(
                        f"📈 内存 {m['pct']:.0f}%（{mem_str}）· 清理强度：{change_str}{deep_str}")
                    self._last_pressure_mem = mem_str
                    self._last_pressure_chg = change_str
                    self._last_agg_peak = agg_peak
                    self._last_deep_triggered = deep_triggered
                # 周期汇总：文件侧由 [清理] 直写（毫秒时间戳+独立类别）；GUI 仅显示不重复落盘
                summary_line = (f"本轮释放 {fmt_label(cycle_freed)} · 系统杂项 {fmt_count(cycle_standby)} · "
                                f"整理 {fmt_count(self._cycle_trimmed)} 进程 · "
                                f"试探 {len(probe_results)} ({probe_ok}成功)")
                if CFG.get("log_to_file"):
                    _log_write("清理", summary_line)
                # 回涨状态机播报（2026-08-14 定稿）：进入回涨快提示一次 → 持续静默 → 回落提示恢复
                if self._refill_cycle:
                    if not self._refill_hot:
                        _rate = int(round(self._refill_total / max(self._last_harvest_freed, 1) * 100))
                        self._cycle_log_buffer.append(
                            f"↻ 内存回涨较快，仅上轮收割后即回涨{_rate}% · 将持续收紧收割节奏直到放缓")
                    self._refill_hot = True
                else:
                    if self._refill_hot:
                        self._cycle_log_buffer.append("↻ 内存回涨已放缓，试探性恢复正常收割节奏")
                    self._refill_hot = False
                # GUI 日志区：summary 与本轮 buffer 一次打包显示（同一清屏判定）。
                # 曾见 summary 先入队、log_batch 后入队时被后者的清屏抹掉——第二轮周期末统计日志缺失根因
                batch_display = [summary_line] + list(self._cycle_log_buffer)
                self.events.put(('display', batch_display))
                if CFG.get("log_to_file"):
                    # buffer 内容（压力/游戏/决策等）直写 [界面]，与 [清理] 分开，去重保持
                    for msg in self._cycle_log_buffer:
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
            self.events.put(('dae_stopped', None))

    # ── 轮次推送（图表数据产生时即算 ERIS——原渲染时计算，消除渲染时序耦合）──
    def _push_round(self, chart_accum, mem_pct, harvest_partial):
        self._chart_bar_seq += 1
        with self._chart_lock:
            self._chart_data.append(chart_accum)
            self._chart_cycle_meta.append((self._chart_bar_seq, self._cycle_trimmed,
                self._cycle_failed, mem_pct, self._failed_weight, harvest_partial))
        # ERIS：数据产生时逐点计算（原逻辑在图表渲染时按 seq 增量处理——等价：每轮一点一次计算）
        try:
            result = self._compute_eris(list(self._chart_data), self._cycle_trimmed,
                                        self._cycle_failed, mem_pct, self._failed_weight,
                                        update_state=True)
            self._eff_data.append(result["total"])
            self._eff_factors.append(result.get("factors", [tr("冷启动")]))
        except Exception:
            self._eff_data.append(80.0)
            self._eff_factors.append([tr("计算异常")])

    # ── ERIS v6：IQR分位数归一化五维加权和（80±40×(raw−p50)/IQR，trimmed IQR + 维级窗口）──
    def _compute_eris(self, data, trimmed_cnt, failed_cnt, mem_pct, failed_weight=0.5, probe_ok=0, probe_total=0, update_state=True):
        """返回 {"total": eff, "factors": ["↑预测精准","↓PF偏高"]}"""
        if not data:
            return {"total": 0, "factors": [tr("冷启动")]}
        visible = list(data)
        learner = self.learner
        profiles = learner.profiles
        cycle_freed = visible[-1] if visible else 1

        # ── 分位数窗初始化 / 趋势列表初始化 ──
        # 窗口长度按维度特异性分配：raw2(释放)需要长窗应对幂律，raw4(EFIS)短窗够用
        _WINDOWS = [25, 25, 20, 8, 20]
        if not hasattr(self, '_eris_bufs') or self._eris_bufs is None:
            self._eris_bufs = [deque(maxlen=_WINDOWS[j]) for j in range(5)]
            self._eris_p50_ewma = [0.0] * 5  # p50 平滑（λ=0.15）
        if not hasattr(self, '_eris_iqr_ewma') or not self._eris_iqr_ewma:
            self._eris_iqr_ewma = [0.0] * 5
        if not hasattr(self, '_eris_ewma_trend') or not self._eris_ewma_trend:
            self._eris_ewma_trend = []

        # ── 维度1 raw: Kalman 预测精准度 ──
        # 迭代前快照：daemon 线程可能随时 get() 增键，直接迭代会 RuntimeError（dictionary changed size）；
        # dict() 拷贝在 GIL 下原子完成
        profiles_snapshot = list(dict(profiles).values())
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
        efis = self.efis
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
                cur_gm = getattr(self.cleaner, 'game_mode', False)
                last_gm = self._last_eris_game_mode
                if last_gm is not None and cur_gm != last_gm:
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

        dim_pairs = [(tr("↑预测精准"), tr("↓预测偏差")), (tr("↑释放改善"), tr("↓释放退步")),
                     (tr("↑副作用低"), tr("↓副作用高")), (tr("↑参数稳定"), tr("↓频繁调参")),
                     (tr("↑覆盖广泛"), tr("↓覆盖狭窄"))]

        # ── 因子选择（含防振荡：同维正负不来回跳）──
        prev = self._eris_prev
        prev_f_dim = self._eris_prev_factor_dim
        prev_f_pos = self._eris_prev_factor_pos
        if len(visible) <= 3:
            factors = [tr("影响因素分析中…")]
        elif round(eff) >= 100:
            best_i = max(range(5), key=lambda i: abs(dims[i] - 80.0))
            factors = [dim_pairs[best_i][0]]
            # 防振荡：同维+上一轮方向不是True（即上次是负面或未记录）→ 跳到候选2
            if prev_f_dim == best_i and prev_f_pos is not None and prev_f_pos is not True:
                ranked = sorted(range(5), key=lambda i: abs(dims[i] - 80.0), reverse=True)
                best_i = ranked[1] if len(ranked) > 1 else best_i
                factors = [dim_pairs[best_i][0]]
            factors.append(tr("🚀效率超常"))
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
            factors.append(tr("⚠效率异常"))
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
                    factors.append(tr("🔥持续改善"))
                elif last_val == -1:
                    factors.append(tr("⚠持续下滑"))
        else:
            factors = [tr("相对平稳")]
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

    # ── ERIS 分位数窗持久化（原子写入；守护线程与退出线程可能并发写，加锁防 tmp 交错截断）──
    def _save_eris_ewma(self):
        with self._eris_save_lock:
            try:
                import json, os
                bufs = getattr(self, '_eris_bufs', None)
                if bufs and any(bufs):
                    data = {"bufs": [list(b) for b in bufs],
                            "iqr_ewma": getattr(self, "_eris_iqr_ewma", [0.0]*5),
                            "p50_ewma": getattr(self, "_eris_p50_ewma", [0.0]*5)}
                    path = os.path.join(os.path.dirname(self._state_file), "memwise_eris_ewma.json")
                    tmp = path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        json.dump(data, f)
                    os.replace(tmp, path)
            except Exception:
                pass

    def _load_eris_ewma(self):
        """加载 ERIS 分位数窗（热重启保留/冷启动重建），严格校验"""
        # 若已有数据（热重启：daemon 重开但程序未退出），保留不重建
        if getattr(self, '_eris_bufs', None) and any(self._eris_bufs):
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
            path = os.path.join(os.path.dirname(self._state_file), "memwise_eris_ewma.json")
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
