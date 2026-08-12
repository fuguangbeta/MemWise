import time
import threading
from . import winapi

class ProcessSnapshot:
    __slots__ = ("pid","name","ws","pf","priv","cpu","fg","path","parent","create","has_visible","_growth_bonus","_tree_scores")
    def __init__(self, pid, name, ws, pf, priv, cpu, fg, path=None, parent=0, create=None, has_visible=False):
        self.pid=pid; self.name=name; self.ws=ws; self.pf=pf; self.priv=priv
        self.cpu=cpu; self.fg=fg; self.path=path; self.parent=parent; self.create=create
        self.has_visible=has_visible

class Sniffer:
    def __init__(self, collect_path=True):
        # 跨线程互斥：守护线程（周期快照）与 GUI 线程（进程排行刷新）可能并发
        # 调用 snapshot——_prev_times/_prev_sys/_path_cache 无锁交错会导致 CPU% 基线错乱
        self._lock = threading.Lock()
        self._prev_times = {}; self._prev_sys = None
        self._path_cache = {}; self._collect_path = collect_path
        self._win_cache = None  # (时间戳, 可见窗口 PID 集)——窗口状态变化慢，30s 缓存降枚举开销

    def snapshot(self):
        with self._lock:
            return self._snapshot_locked()

    def _purge_dead(self, alive_pids):
        alive = set(alive_pids)
        for pid in list(self._prev_times.keys()):
            if pid not in alive: self._prev_times.pop(pid, None); self._path_cache.pop(pid, None)
        # 限制路径缓存大小，防止长期运行膨胀（上限需高于常见进程数，避免每轮删-建抖动）
        if len(self._path_cache) > 512:
            for pid in list(self._path_cache.keys())[:128]:
                self._path_cache.pop(pid, None)
                self._prev_times.pop(pid, None)

    def _visible_pids(self):
        """可见窗口 PID 集（30s 缓存；枚举失败返回空集——has_visible 全 False，冷却退化为 300s）"""
        now = time.time()
        if self._win_cache and now - self._win_cache[0] < 30:
            return self._win_cache[1]
        pids = winapi.enum_visible_window_pids()
        self._win_cache = (now, pids)
        return pids

    def _snapshot_locked(self):
        sys_now = winapi.get_system_times()
        sys_delta = 0
        if sys_now and self._prev_sys:
            sys_delta = (sys_now["kernel"]+sys_now["user"]) - (self._prev_sys["kernel"]+self._prev_sys["user"])
        try: fg_pid = winapi.get_foreground_pid()
        except: fg_pid = 0
        procs = winapi.enum_processes()
        self._purge_dead(p for p,_,_ in procs)
        visible_pids = self._visible_pids()  # 窗口状态 30s 缓存（每快照一次集合查找）
        result = []
        # 批量获取：内存 + CPU 时间 + 创建时间一次系统调用（避免逐进程 OpenProcess，快照开销 ↓~90%）
        bulk = winapi.get_all_processes_memory()
        for pid, name, parent in procs:
            mem = bulk.get(pid) or winapi.get_process_memory(pid)
            if not mem:
                # 即使无法读取内存信息，也加入列表（进程排行等场景需要完整列表）
                result.append(ProcessSnapshot(pid=pid, name=name, ws=0, pf=0, priv=0,
                                              cpu=0.0, fg=(pid==fg_pid), path=None, parent=parent))
                continue
            now = None
            if mem.get("kernel") is not None:
                now = {"kernel": mem["kernel"], "user": mem["user"], "create": mem.get("create")}
            else:
                # 回退路径（bulk 失败逐进程读）：无创建时间，PID 复用检测降级
                t = winapi.get_process_times(pid)
                if t:
                    now = {"kernel": t["kernel"], "user": t["user"], "create": None}
            cpu = 0.0
            if now and sys_delta > 0 and pid in self._prev_times:
                prev = self._prev_times[pid]
                # PID 复用防护：创建时间不同 → 旧基线作废（首帧 CPU 归 0，防旧进程时间差虚高）
                if now.get("create") is not None and prev.get("create") != now["create"]:
                    prev = None
                if prev:
                    cpu = min(100.0, ((now["kernel"]+now["user"])-(prev["kernel"]+prev["user"]))/sys_delta*100.0)
            if now: self._prev_times[pid] = now
            path = None
            if self._collect_path:
                if pid in self._path_cache: path = self._path_cache[pid]
                else:
                    path = winapi.get_process_path(pid)
                    self._path_cache[pid] = path
            result.append(ProcessSnapshot(pid=pid, name=name, ws=mem["ws"], pf=mem["pf"], priv=mem.get("priv",0),
                                          cpu=cpu, fg=(pid==fg_pid), path=path, parent=parent,
                                          create=now.get("create") if now else None,
                                          has_visible=pid in visible_pids))
        self._prev_sys = sys_now
        return result
