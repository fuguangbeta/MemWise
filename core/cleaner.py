"""
PARES Cleaner — 3 层清理引擎
Layer 1: 系统级 (Standby/Modified/FileCache)
Layer 2: 进程级 (EmptyWorkingSet with Thompson/ROI/Probe)
Layer 3: 深度聚合 (高压力时重复执行)
"""
import time, concurrent.futures, threading, os, functools
from . import winapi
from .learner import _is_system_core

# ── 游戏进程名单（2026-08-11：默认不再内置，由用户自行配置——内置通用进程名
# （launcher/ac/ds/mc 等）会被常驻程序误匹配触发游戏模式；用户配置什么就识别什么，零误触发）──
GAME_PROCESSES = set()



class PareCleaner:
    """PARES 清理器 — 3 层引擎 + 游戏模式 + 内存优先级"""

    def __init__(self, judger):
        self.judger = judger
        self.game_mode = False
        self._game_mode_manual = False  # 用户手动设置过模式开关后，自动检测不再覆盖（直到再次手动切换/重启）
        self._manual_run = False  # 手动优化标志（_opt_worker 设置）：跳过自动化保守门，保留实时安全门
        self._low_pri_pids = set()
        self._mem_pri_set = set()  # 已设 MemoryPriority 的 PID（Nt 42 一次性特性：防重复无效调用）
        self._pri_refresh_counter = 0
        self._fast_track = set()  # 高回填率 PID，gap-fill 期间快速重清
        self._last_standby_time = 0
        self._lock = threading.Lock()
        self._max_workers = min(os.cpu_count() or 2, 8)
        self._probe_executor = concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="memwise-probe")
        self._trim_executor = concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="memwise-trim")
        self.stats = {
            "standby": 0, "modified": 0, "filecache": 0,
            "ws_trim": 0, "probe": 0,
            "skipped": 0, "failed_feedback": 0,
            "freed_bytes": 0,  # 新实例从 0 起（旧 prev_freed 依赖 hasattr(self,'stats') 恒 False，等价 0）
            "deepen_cnt": 0, "deepen_extra": 0,
            "layer3_ran": 0, "layer3_extra": 0,
        }
        self._info_msgs = []

    def pop_info(self):
        msgs = self._info_msgs[:]
        self._info_msgs.clear()
        return msgs

    def _stats_inc(self, key, amount=1):
        """线程安全统计累加。守护线程与手动轻量清理可能并发写 stats，
        无锁 `+=` 会因 read-modify-write 交错丢失更新（统计失真）"""
        with self._lock:
            self.stats[key] = self.stats.get(key, 0) + amount

    def pop_game_msgs(self):
        """实时提取游戏检测/退出消息（其余消息留给 pop_info 批量处理）"""
        game_msgs = [m for m in self._info_msgs if "🎮" in m]
        self._info_msgs = [m for m in self._info_msgs if "🎮" not in m]
        return game_msgs

    def __del__(self):
        try:
            self._probe_executor.shutdown(wait=False)
            self._trim_executor.shutdown(wait=False)
        except Exception:
            pass

    def shutdown(self):
        """安全关闭线程池"""
        self._probe_executor.shutdown(wait=False)
        self._trim_executor.shutdown(wait=False)

    # ── Layer 1: 系统级清理 ──

    def clean_modified_pages(self):
        ok = winapi.flush_modified_pages()
        if ok:
            self._stats_inc("modified")
        return ok

    def clear_file_cache(self):
        ok = winapi.clear_system_file_cache()
        if ok:
            self._stats_inc("filecache")
        return ok

    def _flush_volume_cache(self):
        ok = winapi.flush_volume_cache()
        if ok:
            self._stats_inc("volume")
        return ok

    def clean_deep_standby(self):
        """深度多轮 Standby 清理 — 比单次释放更多"""
        ok = winapi.empty_standby_deep()
        if ok:
            self._stats_inc("standby", 2)  # 多轮，计数加2
        return ok

    def quick_retrim(self, pid):
        """Fast trim for gap-fill; tracks release into freed_bytes.
        执行前复检（与 _trim_process 同款）：gap 期间用户可能切到该进程——低压前台拦截"""
        try:
            if self.judger.aggressiveness < 0.35 and winapi.get_foreground_pid() == pid:
                return 0
        except Exception:
            pass
        mem_pre = winapi.get_process_memory(pid)
        if not mem_pre:
            return 0
        if not winapi.empty_ws(pid):
            return 0
        time.sleep(0.1)
        mem_post = winapi.get_process_memory(pid)
        if mem_post:
            freed = max(0, mem_pre["ws"] - mem_post["ws"])
            self._stats_inc("freed_bytes", freed)
        return 1

    @staticmethod
    def _layer1_ops(ops_filter):
        """用户清理操作开关 → Layer1 内核操作集（键映射；None=全量）。
        开关优先：用户取消勾选的操作绝不执行；ws_all 仅由 full=True 调用方（deep/full）启用。"""
        if ops_filter is None:
            return None
        use = set()
        if "ws" in ops_filter:
            use.add("ws_all")  # 系统级全清 WS（仅 full=True 时实际执行）
        if "standby" in ops_filter:
            use.add("standby"); use.add("standby_low")
        if "modified" in ops_filter:
            use.add("modified")
        if "filecache" in ops_filter:
            use.add("filecache"); use.add("filecache_ex")
        if "volume" in ops_filter:
            use.add("volume")
        if "registry" in ops_filter:
            use.add("registry")
        return use

    def _layer1_memreduct(self, full=True, total_procs=0, game_mode=False, ops=None, clean_self=True):
        """系统级内核清理 — 无 sleep，<10ms
        
        full=True  : 全量（含系统级 WS 全清）
        full=False : 轻量（跳过 WS 全清）
        ops        : 启用的操作集合，None=全部。可用键: ws_all, filecache_ex, modified,
                     standby, standby_low, volume, registry, filecache
        total_procs: 当前快照进程总数
        game_mode  : 游戏模式时跳过 WS全清+文件缓存+卷冲刷
        """
        use = ops if ops is not None else {"ws_all","filecache_ex","modified","standby","standby_low","volume","registry","filecache"}
        # 逐操作测量释放量：每个系统操作前后各读一次，标量累加（>0 计入）——
        # filecache 用 SystemCache 字节差（直接反映文件缓存缩减，不受其他进程分配干扰）；
        # 其余操作无分项公开 API，沿用 avail 差（物理可用提升口径）
        freed_total = 0
        def _capture(fn, kind=None):
            nonlocal freed_total
            if kind == "filecache":
                pre = winapi.get_performance_info()
                if not fn():
                    return False
                post = winapi.get_performance_info()
                if pre and post:
                    freed_total += max(0, pre["system_cache"] - post["system_cache"])
                return True
            pre = winapi.get_memory_status()
            if not fn():
                return False
            post = winapi.get_memory_status()
            if pre and post:
                freed_total += max(0, post["avail"] - pre["avail"])
            return True
        try:
            if full and not game_mode and "ws_all" in use:
                if _capture(winapi.empty_all_working_sets):
                    if total_procs > 1:
                        self._stats_inc("ws_trim", max(0, total_procs - 1))
            if not game_mode and "filecache_ex" in use:
                winapi.clear_system_file_cache_ex()
            # 统计按 API 真实成功计数（权限不足时不再虚增）
            # 游戏模式：跳过 standby/脏页写回等磁盘干扰操作（只留注册表缓存与自身工作集）
            if not game_mode and "modified" in use and _capture(winapi.flush_modified_pages):
                self._stats_inc("modified")
            if not game_mode and "standby" in use and _capture(winapi.empty_standby):
                self._stats_inc("standby")
            if not game_mode and "standby_low" in use and _capture(winapi.purge_low_priority_standby):
                self._stats_inc("standby")
            if not game_mode and "volume" in use and _capture(winapi.flush_volume_cache):
                self._stats_inc("volume")
            if "registry" in use and _capture(winapi.clear_registry_cache):
                self._stats_inc("registry")
            if not game_mode and "filecache" in use and _capture(winapi.clear_system_file_cache, "filecache"):
                self._stats_inc("filecache")
            # 清自身工作集（~0.2s，释放 MemWise 自身占用的几十 MB；高频路径可传 clean_self=False 关闭）
            if clean_self:
                try: winapi.empty_ws(os.getpid())
                except Exception: pass
            if freed_total > 0:
                self._stats_inc("freed_bytes", freed_total)
            return True
        except Exception:
            return False

    # ── Layer 2: 进程级清理 ──

    def _probe_process(self, snap, learner):
        """微型试探 — 对不确定进程做轻量测试 (单次清理, ~0.2s 等待)"""
        pid, name = snap.pid, snap.name
        ws_before = snap.ws
        # 读取实时 PF 作为基线（不用快照的旧值；读取失败时无基线 → 无法判定副作用，视为有效观测）
        mem_before = winapi.get_process_memory(pid)
        pf_before = mem_before["pf"] if mem_before else None
        if not winapi.empty_ws(pid):
            return False, 0, 0
        # 单次清理后等待 PF 稳定（游戏模式减半加速）
        time.sleep(0.15 if self.game_mode else 0.2)
        mem = winapi.get_process_memory(pid)
        if mem is None:
            with self._lock:
                learner.record_probe_result(name, True, self._efis_lr(), ws_before)
                self.judger.mark_probed(name)
            return True, ws_before, 0
        ws_after = mem["ws"]
        pf_after = mem["pf"]
        pf_delta = max(0, pf_after - pf_before) if pf_before is not None else 0
        freed = max(0, ws_before - ws_after)
        # 允许的 PF：至少 120（EmptyWorkingSet 自身开销 ~30-50 PF），或每释放 1MB 允许 10 个 PF（同 trim 逻辑）
        # freed=0 时也视作有效观测（进程无可释放页本身就是信息）
        allowed_pf = max(120, int(freed / (1 << 20) * 10))
        ok = True if pf_before is None else pf_delta <= allowed_pf
        with self._lock:
            learner.record_probe_result(name, ok, self._efis_lr(), freed)
            self.judger.mark_probed(name)
            if ok and freed > 0:
                self.stats["freed_bytes"] += freed
            self.stats["probe"] += 1
        return ok, freed, pf_delta

    def _trim_process(self, snap, learner):
        """完整清理一个进程 (自适应多轮清理 + 反馈验证)"""
        pid, name = snap.pid, snap.name
        # ── 执行前复检（P0-B）：决策到执行间隔数秒，期间用户可能切过去/游戏可能启动/
        #    开始 IO 密集（下载/播放）。低压时前台拦截；游戏 PID 集绝对保护；IO 活跃拦截（防御纵深）──
        try:
            if self.judger.aggressiveness < 0.35 and winapi.get_foreground_pid() == pid:
                return False, 0, 0, "执行前转前台"
            if self.game_mode and pid in self.judger._game_pid_set:
                return False, 0, 0, "执行前游戏启动"
            if self.judger._io_active(pid):
                return False, 0, 0, "执行前IO活跃"
        except Exception:
            pass
        # 实时读取 WS，不用快照旧数据
        mem_before = winapi.get_process_memory(pid)
        ws_before = mem_before["ws"] if mem_before else snap.ws
        if ws_before < 1 << 20:
            return False, 0, 0, "WS太小"
        if mem_before:
            self.judger.record_pf_before(pid, mem_before["pf"])

        # 用户配置上限（先读取，超大进程档位直接以此为天花板）
        max_p = self.judger.cfg.get("clean_passes", 4)
        try: max_p = int(max_p)
        except (ValueError, TypeError): max_p = 4

        deepen = self.judger.cfg.get("efis_params", {}).get("deepen_theta", 0.6)
        theta = learner.thompson_score(name, mem_pct=getattr(self.judger, '_last_mem_pct', 50), is_fg=getattr(snap, 'fg', False))
        if getattr(self.judger, "_mode_guard", "normal") == "full":
            # full 模式：全档多轮深清（极限=每进程清到极限；轮间 3% 截断兜底防白等）
            passes = max_p; total_wait = 1.0 * (max_p / 4.0)
        elif ws_before > 200 << 20 or theta > deepen:
            # 天花板由用户设置决定，total_wait 等比缩放控制 PF
            passes = max_p; total_wait = 1.0 * (max_p / 4.0)
        elif ws_before > 50 << 20:
            passes = min(3, max_p); total_wait = 0.6
        elif theta < 0.15:
            passes = 1; total_wait = 0.3
        else:
            passes = min(2, max_p); total_wait = 0.4

        interval = self._trim_interval(learner, name, getattr(self.judger, "_last_mem_pct", 50))
        t_wait = interval * 0.5
        rounds_done = 0
        round_freed = []  # 首轮实际释放（低效轮截断判定基准）
        prev_ws_ck = ws_before

        for round_idx in range(passes):
            rounds_done = round_idx + 1
            if not winapi.empty_ws(pid):
                with self._lock:
                    if round_idx == 0:
                        self.stats["skipped"] += 1
                return False, 0, 0, "API失败"
            if round_idx < passes - 1:
                time.sleep(max(0.05, t_wait))
            # 轮间轻量测量：二轮起实际释放 < 首轮 3% 视为热页清理（回填不足），提前截断剩余轮
            # （EmptyWorkingSet 后几百 ms 内回填的是热页，再清收益低 PF 高；阈值 3% 兼顾慢回填进程）
            m_ck = winapi.get_process_memory(pid)
            if m_ck:
                freed_ck = max(0, prev_ws_ck - m_ck["ws"])
                if round_idx == 0:
                    round_freed.append(freed_ck)
                elif round_freed and freed_ck < max(1 << 20, round_freed[0] * 0.03):
                    break
                prev_ws_ck = m_ck["ws"]

        # 等待 PF 反馈测量（按实际执行轮数）
        elapsed = t_wait * max(0, rounds_done - 1)
        time.sleep(max(0.5, total_wait - elapsed))
        mem = winapi.get_process_memory(pid)
        if mem is None:
            with self._lock:
                learner.record_clean_result(name, True, freed=ws_before, lr=self._efis_lr())
                self.judger.mark_trimmed(name)
                self.stats["ws_trim"] += 1
            return True, ws_before, ws_before, "进程已退出"
        ws_after = mem["ws"]
        ok, freed, pf_delta = self.judger.check_feedback(
            pid, mem["pf"], ws_before, ws_after, passes
        )
        with self._lock:
            # 先收后审：内存释放量始终计入，PF 增长仅影响学习信号
            if freed > 0:
                self.stats["freed_bytes"] += freed
            learner.record_clean_result(name, ok, freed, pf_delta, self._efis_lr())
            if ok:
                self.judger.mark_trimmed(name, freed, ws_before, pf_delta, ws_after)
                self.stats["ws_trim"] += 1
                if passes >= 2:
                    self.stats["deepen_cnt"] += 1
                    self.stats["deepen_extra"] += freed
                # 回弹追踪（B 方案）：记录释放量与清理后 WS，后续快照轮观察回填
                learner.rebound.begin(getattr(snap, "path", None), freed, ws_after, time.time())
            else:
                # PF 超标：仅记录负面学习信号，不丢弃已释放的字节
                p = learner.get_profile(name)
                self.judger.mark_failed(name, p.fail_cnt if p else 1)
                self.stats["failed_feedback"] += 1
        if ok:
            # 在线权重学习：用本次 trim 的实际释放评价树
            if hasattr(snap, '_tree_scores') and hasattr(learner, 'policy'):
                learner.policy.update_weights_per_trim(snap._tree_scores, freed > 50 << 20)
            # 上下文修正学习：在线更新查找表
            if hasattr(learner, 'record_ctx_correction'):
                mem_pct = getattr(self.judger, '_last_mem_pct', 50)
                p = learner.get_profile(name)
                k_cost = p.kalman.x_cost if p and hasattr(p, 'kalman') else 0
                learner.record_ctx_correction(mem_pct, getattr(snap, 'fg', False),
                    time.localtime().tm_hour, freed, p.kalman.x_freed if p and hasattr(p, 'kalman') else ws_before,
                    pf_delta, k_cost)
            return True, freed, pf_delta, "完成"
        else:
            if hasattr(snap, '_tree_scores') and hasattr(learner, 'policy'):
                learner.policy.update_weights_per_trim(snap._tree_scores, False)
            return False, freed, pf_delta, "PF超标"

    def _efis_lr(self):
        """从 judger.cfg 读取 EFIS 调好的 learning_rate（learner 侧暂未启用，待专项实验）"""
        efis = self.judger.cfg.get("efis_params", {})
        return efis.get("learning_rate", None)

    def _get_user_game_procs(self):
        """合并游戏进程名单（用户自定义，统一规范化：小写 + 补 .exe 后缀——
        配置中无后缀条目（手改 config/旧数据）也能精准匹配快照进程名）"""
        extra = set()
        for n in self.judger.cfg.get("game_processes", []):
            n = str(n).strip().lower()
            if n and not n.endswith(".exe"):
                n += ".exe"
            extra.add(n)
        return GAME_PROCESSES | extra

    def _build_game_pid_set(self, snaps):
        """游戏 PID 集 = 名单匹配进程 ∪ 其全部子进程树（BFS）。
        反作弊/更新器/渲染子进程等一并绝对保护——游戏流畅性保护以进程树为单位"""
        all_games = self._get_user_game_procs()
        children_of = {}
        direct = set()
        for s in snaps:
            children_of.setdefault(s.parent, set()).add(s.pid)
            if s.name.lower() in all_games:
                direct.add(s.pid)
        result = set(direct)
        stack = list(direct)
        while stack:
            pid = stack.pop()
            for child in children_of.get(pid, ()):
                if child not in result:
                    result.add(child)
                    stack.append(child)
        return result

    def _is_user_game_running(self, snaps):
        """检测游戏运行——仅用户自定义名单匹配（2026-08-11：全屏窗口不再独立触发，
        视频/远程桌面等全屏误判会误启游戏模式；用户配置什么就识别什么）"""
        all_games = self._get_user_game_procs()
        for s in snaps:
            if s.name.lower() in all_games:
                return True
        return False

    # 每 tick 最多清理的进程数，防止串行 sleep 堆积超时
    def _trim_interval(self, learner, name, mem_pct):
        p = learner.get_profile(name)
        if not p or not hasattr(p, 'kalman') or p.kalman.x_freed <= 0:
            return 0.3
        target = 0.1 * p.kalman.x_freed
        rate = max(getattr(p, 'refill_ewma', 0), 10 << 10)
        base = min(target / rate, 2.0)
        pressure = 1.0 - 0.3 * (mem_pct / 100.0)
        return max(0.3, base * pressure)

    def _composite_score_v2(self, s, learner):
        """多维复合评分（θ/预期释放/WS/回弹/预期PF代价）——替代单维 θ 排序"""
        name = s.name.lower()
        theta = learner.thompson_score(name, mem_pct=getattr(self.judger, '_last_mem_pct', 50), is_fg=getattr(s, 'fg', False))
        p = learner.get_profile(name)
        x_freed = p.kalman.x_freed if p and hasattr(p.kalman, 'x_freed') else 0
        x_cost = p.kalman.x_cost if p and hasattr(p.kalman, 'x_cost') else 0
        # 上下文修正：与 thompson_score 保持一致
        if x_freed > 0 and hasattr(learner, 'ctx_correction'):
            f_corr, _ = learner.ctx_correction(
                getattr(self.judger, '_last_mem_pct', 50), is_fg=getattr(s, 'fg', False),
                hour=time.localtime().tm_hour)
            x_freed = x_freed * max(0.3, min(3.0, f_corr))
        ws = s.ws
        bl = self.judger._post_clean_ws.get(name, 0)
        regrowth = ws / max(bl, 1) if bl > 0 else 1.0
        kw = self.judger.cfg.get("efis_params", {}).get("composite_kalman_w", 0.3)
        tw = 0.6 - kw
        bonus = 0.0
        if ws > 500 << 20:
            bonus += 0.15
        return (tw * min(theta, 1.0) +
                kw * min(x_freed / (200 << 20), 1.0) +
                0.2 * min(ws / (500 << 20), 1.0) +
                0.2 * min(regrowth, 2.0) -
                0.15 * min(x_cost / 500.0, 1.0) +   # 预期 PF 代价惩罚：同等释放下低代价进程优先
                bonus)
    @staticmethod
    def _bounded_submit(executor, fn, items, max_inflight, per_task_timeout, idle_timeout=60.0):
        """滑动窗口分批提交：在途 ≤ max_inflight；超时判定基于任务的真实执行时长
        （排队等待不计时——排队任务保留在窗口直到开始执行，杜绝无辜进程排队超时被惩罚）。
        idle_timeout 无进展超时：仅当窗口长时间（默认 60s）既无任务完成也无任务开始时判定
        池线程卡死并放弃剩余项（防无限循环）；正常慢任务全程等待、零截断——v3.6.47 曾用
        总预算 20s 硬限导致每轮清理量被截断，恢复全量处理。
        返回 [(item, result)]；超时/异常任务的 result 为 None（任务自然跑完，结果丢弃）。"""
        out = []
        inflight = {}
        started = {}
        idx = 0
        n = len(items)
        last_progress = time.time()
        while idx < n or inflight:
            if time.time() - last_progress > idle_timeout:
                # 无进展超时（池卡死）：剩余未提交项标记超时，已提交任务交给线程池自然完成（不阻塞调用方）
                out.extend((item, None) for item in items[idx:])
                idx = n
                inflight.clear()
                break
            while idx < n and len(inflight) < max_inflight:
                item = items[idx]; idx += 1

                def _tracked(it=item):
                    started[it] = time.time()  # 入口打时间戳：区分执行中与排队
                    return fn(it)

                inflight[executor.submit(_tracked)] = item
            if not inflight:
                break
            done, not_done = concurrent.futures.wait(
                inflight, timeout=per_task_timeout,
                return_when=concurrent.futures.FIRST_COMPLETED)
            if done:
                last_progress = time.time()
            for f in done:
                item = inflight.pop(f)
                started.pop(item, None)
                try:
                    r = f.result()
                except Exception:
                    r = None
                out.append((item, r))
            if not_done:
                # 只标记"已开始且执行超预算"的任务；排队中的继续留在窗口（不计时）
                expired = [f for f in list(not_done)
                           if time.time() - started.get(inflight[f], time.time()) >= per_task_timeout]
                for f in expired:
                    item = inflight.pop(f)
                    started.pop(item, None)
                    out.append((item, None))
                    last_progress = time.time()
        return out

    def _layer2_process(self, snaps, learner):
        """进程级清理 — 游戏检测 + Thompson/ROI 选进程 + 内存优先级"""
        # 每轮同步手动标志 + 更新活动确认/锚点样本（can_trim 消费；手动优化跳过保守门）
        self.judger._manual_mode = self._manual_run
        self.judger.update_activity(snaps)
        self.judger.update_anchors(snaps)
        # ── 检测游戏模式 ──
        game_on = self._is_user_game_running(snaps)
        if self._game_mode_manual:
            # 手动模式：模式开关由用户持有，自动检测只做数据维护
            if game_on:
                self._game_gone_count = 0
                # 手动模式同样实时刷新保护集（含子进程树）——覆盖游戏期间后启动的子进程/新实例
                self.judger._game_pid_set = self._build_game_pid_set(snaps)
            elif not game_on and self.game_mode:
                # 游戏已退出：清空失效 PID 保护集（防 PID 复用误保护），模式保持手动开启
                self.judger._game_pid_set.clear()
        elif game_on and not self.game_mode:
            self._info_msgs.append("🎮 检测到游戏运行 · 启用 游戏模式")
            self.game_mode = True
            self.judger.game_mode = True
            self._game_gone_count = 0
        elif not game_on and self.game_mode:
            # 智能退出：连续2周期无游戏进程则退出
            self._game_gone_count = getattr(self, '_game_gone_count', 0) + 1
            if self._game_gone_count >= 2:
                self._info_msgs.append("🎮 游戏已退出 · 恢复正常模式")
                self.game_mode = False
                self.judger.game_mode = False
                self.judger._game_pid_set.clear()
                self._game_gone_count = 0
        else:
            self.game_mode = game_on
            self.judger.game_mode = game_on
            if game_on:
                self._game_gone_count = 0
        # 游戏运行期间每轮刷新 PID 保护集（覆盖游戏内后启动的子进程/新实例——含子进程树）
        if game_on:
            self.judger._game_pid_set = self._build_game_pid_set(snaps)

        candidates = []
        probe_list = []

        SELF_PID = os.getpid()
        for s in snaps:
            # 排除自身进程
            if s.pid == SELF_PID:
                continue
            # Trim 优先：能整理的不需要试探
            ok, reason = self.judger.can_trim(s)
            if ok:
                candidates.append(s)
            else:
                if self.judger.can_probe(s):
                    probe_list.append(s)
                self.stats["skipped"] += 1

        # ── 全局内存优先级 + EcoQoS ──
        # 对高价值大进程（θ≥0.5 且 WS≥100MB）设 VERY_LOW 内存优先级 + EcoQoS——
        # 只是提示 Windows 优先回收其页面，比 EmptyWorkingSet 更温和。
        # 两类标记均"每进程仅设置一次不可恢复"（Nt 直通特性）：30 tick 重评清空
        # 集合后重设，已设进程返回 ALREADY（幂等视为成功重建集合），新进程/新转
        # 后台的进程借此获得首次设置机会
        self._pri_refresh_counter += 1
        if self._pri_refresh_counter >= 30:
            self._low_pri_pids.clear()
            self._mem_pri_set.clear()
            self._pri_refresh_counter = 0
        _all_games = self._get_user_game_procs()  # 循环外取一次（并集构建开销）
        for s in snaps:
            # 游戏进程（含此前被降级的）：恢复默认优先级/EcoQoS，确保不被 OS 优先回收
            # （双通道语义：K32 可用机器上恢复真实生效；K32 失效机器上 Nt 通道一次性，
            # 对已设进程无效无害，对未设进程（名单跳过者）首次设 4 = 锁定默认——同为恢复意图）
            if self.game_mode and hasattr(self.judger, '_game_pid_set') and s.pid in self.judger._game_pid_set:
                if s.pid in self._low_pri_pids:
                    try:
                        winapi.set_eco_qos(s.pid, False)
                        winapi.set_memory_priority(s.pid, 4)
                    except Exception:
                        pass
                    self._low_pri_pids.discard(s.pid)
                continue
            if s.pid in self._low_pri_pids:
                continue
            name = s.name.lower()
            if _is_system_core(name) or name in self.judger.cfg.get("never", []):
                continue
            # 游戏名单进程跳过 EcoQoS 降级：Nt PowerThrottling 实测每进程一经设置即不可撤销
            # （二次设置恒 ALREADY_COMPLETE）——游戏运行时需保持默认节能状态，从源头避免被降级
            if name in _all_games:
                continue
            # 前台进程: 保持默认优先级（不需调用API，且不入 _low_pri_pids——
            # 入集合会被误判"已降级"而跳过后续重评，转后台后降级滞后数分钟）
            if getattr(s, "fg", False):
                winapi.set_eco_qos(s.pid, False)
                continue
            theta = learner.thompson_score(name, mem_pct=getattr(self.judger, '_last_mem_pct', 50), is_fg=getattr(s, 'fg', False))
            # EcoQoS + MemoryPriority 只对高价值大进程启用（θ≥0.5 且 WS≥100MB）：
            # ① EcoQoS 压缩池效应（压缩池计入"正在使用"）——全量启用实测使用率升高 4-8%；
            # ② MemoryPriority 双通道中 Nt 42 兜底"每进程仅设置一次不可恢复"——
            #    低置信/小进程在 K32 失效机器上不值得被永久降级
            #    （原 θ<0.5 两档在 K32 失效下从未生效，零损失收敛到高价值门槛）
            if theta >= 0.5 and s.ws >= (100 << 20):
                if winapi.set_eco_qos(s.pid, True):
                    self._low_pri_pids.add(s.pid)
                if winapi.set_memory_priority(s.pid, 0):
                    self._mem_pri_set.add(s.pid)
        # 清除已退出的 PID
        alive = {s.pid for s in snaps}
        self._low_pri_pids &= alive
        self._mem_pri_set &= alive

        # 动态 probe 间隔：候选多=>短间隔快速覆盖
        n_probe = len(probe_list)
        if n_probe > 30:
            self.judger._probe_dynamic_interval = 30
        elif n_probe > 10:
            self.judger._probe_dynamic_interval = 60
        else:
            self.judger._probe_dynamic_interval = 120

        # Probe — 滑动窗口并行（在途 ≤ 池×2，排队不计时；剩余进程下一轮重排后继续）
        probe_results = []
        if probe_list:
            fn = functools.partial(self._probe_process, learner=learner)
            for s, r in self._bounded_submit(self._probe_executor, fn, probe_list,
                                             max_inflight=self._max_workers * 2,
                                             per_task_timeout=4):
                if r is None:
                    ok, freed = False, 0
                    with self._lock:
                        self.stats["skipped"] += 1
                else:
                    ok, freed, _pf = r
                probe_results.append((s, ok, freed))

        # ── 预判式清理：对快速增长中的进程增加排序优先级 ──
        for s in candidates:
            p = learner.get_profile(s.name)
            if p and p.total_samples >= 5:
                slope = p.slope
                # 相对增长率 > 0.2%/tick（slope 单位字节/tick；原绝对值 0.002 字节/tick 几乎恒真，注释「快速增长」名不副实）
                if slope > s.ws * 0.002 and s.ws > 50 << 20:
                    s._growth_bonus = min(0.3, slope * 30)

        # ── 进程树感知：同一父进程的子进程批量排序 ──
        # 对 candidates 按父进程分组，同组内按 θ 降序
        # 浏览器(Chrome/Edge/Firefox)等有多子进程的应用优先批量清理
        # 父名用本轮快照 pid→name 映射（零额外系统调用——原逐进程
        # CreateToolhelp32Snapshot 全表扫描，浏览器 20+ 子进程时每轮重复开销大）
        pid2name = {s.pid: s.name for s in snaps}
        tree_bonus = {}
        for s in candidates:
            pname = s.name.lower()
            if any(b in pname for b in ["chrome", "msedge", "firefox", "brave", "opera", "electron"]):
                parent = pid2name.get(s.parent)
                if parent:
                    pn = parent.lower()
                    if pn not in tree_bonus:
                        tree_bonus[pn] = []
                    tree_bonus[pn].append(s)
        # 有多个子进程的父进程 → 子进程获得批量加分
        for pn, children in tree_bonus.items():
            if len(children) >= 3:
                for s in children:
                    now_bonus = getattr(s, '_growth_bonus', 0)
                    s._growth_bonus = now_bonus + 0.05  # 批量加分

        # Fast-track: high-refill PIDs for gap-fill re-trim
        self._fast_track = set()
        for s in candidates:
            p = learner.get_profile(s.name)
            if p and getattr(p, 'refill_ewma', 0) > 500 << 10:
                self._fast_track.add(s.pid)
        candidates.sort(key=lambda s: -self._composite_score_v2(s, learner) - getattr(s, '_growth_bonus', 0))
        results = []
        if candidates:
            fn = functools.partial(self._trim_process, learner=learner)
            # 并发平滑降级：高压（agg>0.6）全速 2×workers，低压力 1.5×（避免吞吐减半——
            # 使用率常态 <60% 时 agg≈0，恒 1× 会致每轮覆盖进程数减半）
            _agg = getattr(self.judger, 'aggressiveness', 0.5)
            max_inflight = int(self._max_workers * (1.5 + 0.5 * min(_agg / 0.6, 1.0)))
            for s, r in self._bounded_submit(self._trim_executor, fn, candidates,
                                             max_inflight=max_inflight,
                                             per_task_timeout=8):
                if r is None:
                    # 执行超时（排队不计时）：递增冷却 + Thompson 惩罚，与历史超时处理一致
                    ok, freed, pf_delta, reason = False, 0, 0, "超时"
                    with self._lock:
                        self.stats["skipped"] += 1
                        p = learner.get_profile(s.name.lower())
                        tc = getattr(p, 'timeout_count', 0) + 1 if p else 1
                        if p:
                            p.timeout_count = tc
                        # 递增冷却：超时次数越多冷却越长，最多 4 倍
                        self.judger.mark_failed(s.name.lower(), fail_count=tc)
                        # Thompson 惩罚：beta+1，Kalman q 提升以增加不确定性
                        learner.record_clean_result(s.name.lower(), ok=False)
                else:
                    ok, freed, pf_delta, reason = r
                results.append((s, ok, freed, reason))

        self._last_layer2_results = results
        return results, probe_results

    # ── Layer 3: 深度聚合 ──

    def _layer3_deep(self, snaps, learner, ops_filter=None):
        # 门控：Layer3 深度操作由 ws/standby/modified 驱动（volume/filecache/registry 单独勾选不触发深度层）
        if ops_filter is not None and not ({"ws", "standby", "modified"} & set(ops_filter)):
            return
        
        mem_before_layer3 = winapi.get_memory_status()
        self._stats_inc("layer3_ran")
        # 逐操作测量释放量（与 Layer1 同口径）：阶段 C 系统操作的释放量此前只进 layer3_extra，
        # 图表/统计栏的 freed_bytes 一直缺失这部分（每轮可能漏几百 MB）
        freed_l3 = 0
        def _capture(fn, kind=None):
            nonlocal freed_l3
            if kind == "filecache":
                # 同 Layer1 口径：SystemCache 字节差精确反映文件缓存缩减
                pre = winapi.get_performance_info()
                if not fn():
                    return False
                post = winapi.get_performance_info()
                if pre and post:
                    freed_l3 += max(0, pre["system_cache"] - post["system_cache"])
                return True
            pre = winapi.get_memory_status()
            if not fn():
                return False
            post = winapi.get_memory_status()
            if pre and post:
                freed_l3 += max(0, post["avail"] - pre["avail"])
            return True
        # 预处理：使用简化的 deep_compress（无 sleep 管线）；游戏模式跳过——
        # deep_compress 内部 flush_modified(3)+purge_standby(4)，与阶段 C 一样会打断游戏读盘
        if not self.game_mode:
            # 深度预处理由 modified/standby 开关共同控制（取消两者则不执行）
            if ops_filter is None or "modified" in ops_filter or "standby" in ops_filter:
                _capture(winapi.deep_compress)
            if ops_filter is None or "modified" in ops_filter:
                _capture(self.clean_modified_pages)
        # 内核操作已同步完成，无需等待

        # 阶段 C: 收前（游戏模式跳过——standby/压缩/文件缓存会打断游戏读盘）
        if not self.game_mode:
            if ops_filter is None or "standby" in ops_filter:
                # 单次深度清空（低优先+全量+脏页写回一次完成），替代重复的四次调用
                _capture(self.clean_deep_standby)
            if ops_filter is None or "volume" in ops_filter:
                _capture(self._flush_volume_cache)
            if ops_filter is None or "filecache" in ops_filter:
                _capture(self.clear_file_cache, "filecache")
                _capture(winapi.clear_system_file_cache_ex, "filecache")
        if freed_l3 > 0:
            self._stats_inc("freed_bytes", freed_l3)
        # Track Layer3 standby release（EFIS 诊断专用：Layer3 整体净增量）
        mem_after_standby = winapi.get_memory_status()
        if mem_before_layer3 and mem_after_standby:
            extra_mem = mem_after_standby["avail"] - mem_before_layer3["avail"]
            if extra_mem > 0:
                self._stats_inc("layer3_extra", extra_mem)  # bytes, consistent with deepen_extra

        # 阶段 D: WS 回弹率选进程 (skip already trimmed in Layer2)
        # 开关优先：用户取消 ws 勾选时阶段 D 不得清理进程（阶段 A-C 系统操作仍按开关执行）
        if ops_filter is not None and "ws" not in ops_filter:
            return
        # 复用滑动窗口分批提交（在途限制 + 总预算），防一次性 submit 堆积拖垮池
        layer2_pids = {t[0].pid for t in getattr(self, "_last_layer2_results", []) if t[1]}
        never = self.judger.cfg.get("never", []) or []
        d_candidates = []
        for s in snaps:
            if s.pid == os.getpid():
                continue  # 自身进程不清理（与 Layer2 同规则）
            if s.pid in layer2_pids:
                continue  # Already trimmed in Layer2, skip
            if self.game_mode and s.pid in getattr(self.judger, '_game_pid_set', set()):
                continue  # 游戏进程绝对保护，深度聚合同样不碰
            name_lower = s.name.lower()
            # 与 Layer2 同款硬守卫：系统核心/用户排除列表在深度聚合同样生效
            if _is_system_core(name_lower):
                continue
            if name_lower in never or s.pid in never:
                continue
            # 前台进程低压力不碰（与 can_trim 同规则——Layer2 有前台保护，深度聚合不得缺失）
            if getattr(s, 'fg', False) and getattr(self.judger, 'aggressiveness', 0.0) < 0.35:
                continue
            # 深度聚合同样要求连续空闲确认（D 方案：与 Layer2 同口径按 PID 键，防深清活跃程序；
            # 手动优化跳过——用户主动深清；full 模式跳过——极限=立即清）
            if not self.judger._manual_mode and getattr(self.judger, "_mode_guard", "normal") != "full":
                _la = self.judger._low_activity.get(s.pid)
                if _la is None or _la[0] < 2:
                    continue
            # 深度聚合同样执行 IO 活跃门（与 Layer2 同口径——CPU 低但 IO 密集的下载/播放进程不清）
            if self.judger._io_active(s.pid):
                continue
            bl = self.judger._post_clean_ws.get(name_lower, 0)
            if bl > 0 and s.ws >= bl * 2.0:
                d_candidates.append(s)
            elif bl == 0:
                theta = learner.thompson_score(name_lower, mem_pct=getattr(self.judger, '_last_mem_pct', 50), is_fg=getattr(s, 'fg', False))
                # θ 门槛模式化（与 Layer2 价值底线同构）：deep 0.12 / full 0.06 / 常规 0.5
                _theta_d = {"deep": 0.12, "full": 0.06}.get(getattr(self.judger, "_mode_guard", "normal"), 0.5)
                if theta > _theta_d:
                    d_candidates.append(s)
        if d_candidates:
            fn = functools.partial(self._trim_process, learner=learner)
            # 并发平滑降级（与 Layer2 同规则）
            _agg = getattr(self.judger, 'aggressiveness', 0.5)
            max_inflight = int(self._max_workers * (1.5 + 0.5 * min(_agg / 0.6, 1.0)))
            for _s, _r in self._bounded_submit(self._trim_executor, fn, d_candidates,
                                               max_inflight=max_inflight,
                                               per_task_timeout=8):
                pass  # 结果无需收集（与旧 as_completed 语义一致：只执行不统计）

    # ── 统一入口 ──

    def optimize(self, snaps, learner, mode="normal", operations=None, score_fn=None, aggressiveness=None, allow_layer3=True):
        """
        统一优化入口 — 已激活 8 步内核快速管线

        mode: quick|normal|deep|full
            quick  = layer1(7 步快速管线) + layer2(full probe+trim)
            normal = layer1(7 步) + layer2(full) + layer3(if agg>=0.3)
            deep   = layer1(8 步) + layer2 + layer3(always)
            full   = layer1(8 步) + layer2 + layer3 + extra standby

        operations: 可选列表，限制允许的清理操作，如 ["ws","standby","modified","filecache"]
        aggressiveness: 可选，预计算的 aggressiveness 值（daemon 模式避免 PID 双重更新）
        allow_layer3: 高频路径（gap-fill）传 False，Layer3 深度操作只在 harvest 执行
        注: standby 开关同时覆盖低优先与全量两级待机页回收
        """
        # 模式严格度同步：normal 标准 / deep 减半 / full 跳过时间等待守卫（极限=不等、立即清）
        self.judger._mode_guard = mode if mode in ("normal", "deep", "full") else "normal"
        mem_before_opt = winapi.get_memory_used_bytes()
        if aggressiveness is None:
            mem = winapi.get_memory_status()
            agg = self.judger.update_pressure(mem["pct"]) if mem else 0.5
        else:
            agg = aggressiveness
        ops_filter = set(operations) if operations else None
        run_ws = ops_filter is None or "ws" in ops_filter
        # 管线上下文：层间传递执行状态，避免重复工作
        pipeline_ctx = {"layer1_done": False, "layer2_trimmed": set()}
        self._pipeline_ctx = pipeline_ctx
        # Helper to build result with net_freed tracking
        def _mk_result(l2, probe):
            r = {"mode": mode, "aggressiveness": agg, "layer2": l2, "probe": probe}
            mem_after = winapi.get_memory_used_bytes()
            r["net_freed"] = max(0, mem_before_opt - mem_after)
            return r

        if mode == "quick":
            # 仅系统级轻量清理，不碰进程，零卡顿（用户勾选 ∩ 3 步轻量集，未勾选则跳过）
            use = {"standby", "modified", "registry"} & (ops_filter or set())
            if use:
                self._layer1_memreduct(full=False, ops=use)
            return _mk_result([], [])
        
        elif mode == "normal":
            # 完整进程 trim + 系统级清理（按用户开关映射；无文件缓存），游戏横扫
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            pipeline_ctx["layer2_trimmed"] = {r[0].name for r in l2_results if r[1]}
            # full=False：normal 不做系统级全清 WS（ws_all 仅 deep/full 启用）
            l1_ops = self._layer1_ops(ops_filter)
            if l1_ops is not None and not allow_layer3:
                # 高频路径（gap-fill）仅轻量操作：filecache/volume 留到 harvest——
                # 文件缓存/卷冲刷每 12s 执行会令磁盘缓存永远建不起来（性能灾难）
                l1_ops = l1_ops & {"standby", "standby_low", "modified", "registry"}
            self._layer1_memreduct(full=False, total_procs=len(snaps), game_mode=self.game_mode,
                                   ops=l1_ops)
            pipeline_ctx["layer1_done"] = True
            # Layer3 门槛由 EFIS layer3_agg_gate 自适应控制（无参数时兜底 0.3）；
            # 高频 gap-fill 路径传 allow_layer3=False，深度操作只在 harvest 执行
            if allow_layer3:
                _l3_gate = self.judger.cfg.get("efis_params", {}).get("layer3_agg_gate", 0.3)
                if agg >= _l3_gate:
                    self._layer3_deep(snaps, learner, ops_filter)
            return _mk_result(l2_results, probe_results)
        
        elif mode == "deep":
            # normal 基础 + 系统级全清 WS + 强制 Layer3（文件缓存/各操作按用户开关）
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            pipeline_ctx["layer2_trimmed"] = {r[0].name for r in l2_results if r[1]}
            l1_ops = self._layer1_ops(ops_filter)
            if l1_ops is not None and "ws_all" in l1_ops and not self._manual_run and agg < 0.4:
                # 系统级全清 WS 绕过进程级守卫（含前台/冷却/CPU）——自动模式下仅压力中等以上
                # 执行，防止"内存充裕时用户正在用的程序被全清"；手动（用户主动）不受限
                l1_ops = l1_ops - {"ws_all"}
            self._layer1_memreduct(full=True, total_procs=len(snaps), game_mode=self.game_mode,
                                   ops=l1_ops)
            pipeline_ctx["layer1_done"] = True
            self._layer3_deep(snaps, learner, ops_filter)
            return _mk_result(l2_results, probe_results)
        
        elif mode == "full":
            # deep 基础 + 进程回弹二轮 + 强制高 agg Layer3（各操作按用户开关）
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            pipeline_ctx["layer2_trimmed"] = {r[0].name for r in l2_results if r[1]}
            l1_ops = self._layer1_ops(ops_filter)
            if l1_ops is not None and "ws_all" in l1_ops and not self._manual_run and agg < 0.4:
                l1_ops = l1_ops - {"ws_all"}
            self._layer1_memreduct(full=True, total_procs=len(snaps), game_mode=self.game_mode,
                                   ops=l1_ops)
            pipeline_ctx["layer1_done"] = True
            self._layer3_deep(snaps, learner, ops_filter)
            agg = max(agg, 0.6)  # full 模式强制 agg ≥0.6，同步返回结果
            # 回弹二轮：对已修剪进程追加 WS 清空（与 Layer3 阶段 D 同款硬守卫——
            # 游戏 PID 树/系统核心/黑名单/自身/前台(低压力) 一律跳过：防御纵深，
            # 不依赖 Layer2 过滤的时序正确性，防未来逻辑变化致保护界限被破解）
            if pipeline_ctx["layer2_trimmed"]:
                never = self.judger.cfg.get("never", []) or []
                game_pids = getattr(self.judger, '_game_pid_set', set()) if self.game_mode else set()
                _agg = agg  # 局部 agg（daemon 传参模式下 judger.aggressiveness 是上一轮旧值）
                for s in snaps:
                    if s.pid == os.getpid() or s.pid in game_pids:
                        continue
                    name_l = s.name.lower()
                    if _is_system_core(name_l) or name_l in never or s.pid in never:
                        continue
                    if getattr(s, 'fg', False) and _agg < 0.35:
                        continue  # 前台进程低压力不碰（与 can_trim 同规则）
                    if s.name in pipeline_ctx["layer2_trimmed"] and s.ws >= (10 << 20):
                        try:
                            winapi.empty_ws(s.pid)
                        except Exception:
                            pass
            return _mk_result(l2_results, probe_results)

        else:
            # 未知模式防御：回退 normal 语义（原 else 无参全量 layer1 过激且名不副实）
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            self._layer1_memreduct(full=False, total_procs=len(snaps), game_mode=self.game_mode,
                                   ops=self._layer1_ops(ops_filter))
            return _mk_result(l2_results, probe_results)

    # ── 统计 ──

    def summary(self):
        s = self.stats.copy()
        s["freed_mb"] = round(s["freed_bytes"] / (1 << 20), 1)
        return s

    def reset_stats(self):
        prev_freed = self.stats.get("freed_bytes", 0) if hasattr(self, 'stats') else 0
        self.stats = {
            "standby": 0, "modified": 0, "filecache": 0,
            "ws_trim": 0, "probe": 0,
            "skipped": 0, "failed_feedback": 0,
            "freed_bytes": prev_freed,
            "deepen_cnt": 0, "deepen_extra": 0,
            "layer3_ran": 0, "layer3_extra": 0,
        }
        self.judger._post_clean_ws.clear()
        self.judger._post_clean_time.clear()
