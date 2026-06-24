import time
from . import winapi

class ProcessSnapshot:
    __slots__ = ("pid","name","ws","pf","cpu","fg","path","ts")
    def __init__(self, pid, name, ws, pf, cpu, fg, path=None):
        self.pid=pid; self.name=name; self.ws=ws; self.pf=pf
        self.cpu=cpu; self.fg=fg; self.path=path; self.ts=time.time()

class Sniffer:
    def __init__(self, collect_path=True):
        self._prev_times = {}; self._prev_sys = None
        self._path_cache = {}; self._collect_path = collect_path

    def _purge_dead(self, alive_pids):
        alive = set(alive_pids)
        for pid in list(self._prev_times.keys()):
            if pid not in alive: self._prev_times.pop(pid, None); self._path_cache.pop(pid, None)

    def snapshot(self):
        sys_now = winapi.get_system_times()
        sys_delta = 0
        if sys_now and self._prev_sys:
            sys_delta = (sys_now["kernel"]+sys_now["user"]) - (self._prev_sys["kernel"]+self._prev_sys["user"])
        try: fg_pid = winapi.get_foreground_pid()
        except: fg_pid = 0
        procs = winapi.enum_processes()
        self._purge_dead(p for p,_,_ in procs)
        result = []
        for pid, name, _ in procs:
            mem = winapi.get_process_memory(pid)
            if not mem: continue
            now = winapi.get_process_times(pid)
            cpu = 0.0
            if now and sys_delta > 0 and pid in self._prev_times:
                prev = self._prev_times[pid]
                cpu = min(100.0, ((now["kernel"]+now["user"])-(prev["kernel"]+prev["user"]))/sys_delta*100.0)
            if now: self._prev_times[pid] = now
            path = None
            if self._collect_path:
                if pid in self._path_cache: path = self._path_cache[pid]
                else:
                    path = winapi.get_process_path(pid)
                    self._path_cache[pid] = path
            result.append(ProcessSnapshot(pid=pid, name=name, ws=mem["ws"], pf=mem["pf"],
                                          cpu=cpu, fg=(pid==fg_pid), path=path))
        self._prev_sys = sys_now
        return result
