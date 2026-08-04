"""
PARES Cleaner — 3 层清理引擎
Layer 1: 系统级 (Standby/Modified/FileCache)
Layer 2: 进程级 (EmptyWorkingSet with Thompson/ROI/Probe)
Layer 3: 深度聚合 (高压力时重复执行)
"""
import time, concurrent.futures, threading, os, functools
from . import winapi
from .learner import _is_system_core

# ── 常见游戏进程名单（自动检测用）──
GAME_PROCESSES = {
    # Valve / Source
    "cs2.exe", "csgo.exe", "dota2.exe", "tf2.exe", "left4dead2.exe",
    "hl2.exe", "portal2.exe", "teamfortress2.exe",
    # Riot
    "valorant.exe", "league of legends.exe", "lol.exe", "leagueclient.exe",
    # Blizzard
    "wow.exe", "world of warcraft.exe", "overwatch.exe", "hearthstone.exe",
    "diablo3.exe", "diablo4.exe", "diablo ii.exe", "d2r.exe",
    "starcraft.exe", "sc2.exe", "heroes of the storm.exe",
    # Epic / Unreal
    "rocketleague.exe", "fortnite.exe", "fortniteclient.exe",
    # EA
    "bf1.exe", "bf2042.exe", "battlefield.exe", "fifa.exe",
    "fc24.exe", "fc25.exe", "madden.exe", "sims4.exe",
    # Ubisoft
    "forhonor.exe", "rainbowsix.exe", "r6.exe", "ghostrecon.exe",
    "far cry.exe", "farcry6.exe", "assassins creed.exe", "ac.exe",
    # Rockstar
    "gta5.exe", "gtav.exe", "rdr2.exe", "launcher.exe",
    # Bethesda
    "skyrim.exe", "skyrimse.exe", "fallout4.exe", "starfield.exe",
    # FromSoftware
    "eldenring.exe", "sekiro.exe", "dark souls.exe", "ds.exe",
    # CD Projekt
    "cyberpunk2077.exe", "witcher3.exe", "w3.exe",
    # Other AAA / popular
    "minecraft.exe", "javaw.exe",  # MC launcher
    "cities.exe", "cities skylines.exe", "cities2.exe",  # 都市天际线 1/2
    "monsterhunterworld.exe", "mhw.exe",
    "streetfighter6.exe", "sf6.exe", "tekken8.exe",
    "cod.exe", "call of duty.exe", "warzone.exe",
    "apex_legends.exe", "apex legends.exe",
    "destiny2.exe", "pathofexile.exe", "poe.exe",
    "guild wars 2.exe", "gw2.exe", "finalfantasyxiv.exe", "ffxiv.exe",
    "lost ark.exe", "lostaek.exe",
    # miHoYo / HoYoverse
    "honkai3rd.exe", "honkai impact 3rd.exe", "bh3.exe",
    "genshinimpact.exe", "genshin impact.exe", "yuanshen.exe",
    "star rail.exe", "hkrpg.exe",
    "zzz.exe", "zenless zone zero.exe",
    # 国产游戏
    "wuxia.exe", "guijian.exe", "xianjian.exe", "pal5.exe", "pal5q.exe", "pal6.exe",
    "jianwang3.exe", "jx3.exe", "jxsan.exe", "jxs.exe",
    "wuying.exe", "yunding.exe",
    "nba2k.exe", "nba2konline.exe",
    "cf.exe", "crossfire.exe",
    "dnf.exe", "dnfchina.exe",
    "lol.exe",  # duplicate but explicit
    # Steam / general
    "eurotrucks2.exe", "ats.exe",
    "terraria.exe", "stardew valley.exe",
    "hades.exe", "dead cells.exe",
    "rimworld.exe", "factorio.exe",
    # UWP / Xbox
    "forza horizon 4.exe", "forza horizon 5.exe", "forza.exe",
    "halo infinite.exe", "halo.exe",
    "gears 5.exe", "gears.exe",
    "mc.exe", "minecraftuwp.exe",
}



class PareCleaner:
    """PARES 清理器 — 3 层引擎 + 游戏模式 + 内存优先级"""

    def __init__(self, judger):
        self.judger = judger
        self.game_mode = False
        self._game_mode_manual = False  # 用户手动设置过模式开关后，自动检测不再覆盖（直到再次手动切换/重启）
        self._low_pri_pids = set()
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
            self.stats["modified"] += 1
        return ok

    def clear_file_cache(self):
        ok = winapi.clear_system_file_cache()
        if ok:
            self.stats["filecache"] += 1
        return ok

    def _flush_volume_cache(self):
        ok = winapi.flush_volume_cache()
        if ok:
            self.stats["volume"] = self.stats.get("volume", 0) + 1
        return ok

    def clean_deep_standby(self):
        """深度多轮 Standby 清理 — 比单次释放更多"""
        ok = winapi.empty_standby_deep()
        if ok:
            self.stats["standby"] += 2  # 多轮，计数加2
        return ok

    def quick_retrim(self, pid):
        """Fast trim for gap-fill; tracks release into freed_bytes."""
        mem_pre = winapi.get_process_memory(pid)
        if not mem_pre:
            return 0
        if not winapi.empty_ws(pid):
            return 0
        time.sleep(0.1)
        mem_post = winapi.get_process_memory(pid)
        if mem_post:
            freed = max(0, mem_pre["ws"] - mem_post["ws"])
            self.stats["freed_bytes"] += freed
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
        # 逐操作测量释放量：每个系统操作前后各读一次 avail，标量累加（>0 计入）——
        # 替代函数级始末差（净变化会漏计：操作释放的同时其他进程分配会吞掉释放量）
        freed_total = 0
        def _capture(fn):
            nonlocal freed_total
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
                        self.stats["ws_trim"] += max(0, total_procs - 1)
            if not game_mode and "filecache_ex" in use:
                winapi.clear_system_file_cache_ex()
            # 统计按 API 真实成功计数（权限不足时不再虚增）
            # 游戏模式：跳过 standby/脏页写回等磁盘干扰操作（只留注册表缓存与自身工作集）
            if not game_mode and "modified" in use and _capture(winapi.flush_modified_pages):
                self.stats["modified"] = self.stats.get("modified", 0) + 1
            if not game_mode and "standby" in use and _capture(winapi.empty_standby):
                self.stats["standby"] += 1
            if not game_mode and "standby_low" in use and _capture(winapi.purge_low_priority_standby):
                self.stats["standby"] += 1
            if not game_mode and "volume" in use and _capture(winapi.flush_volume_cache):
                self.stats["volume"] = self.stats.get("volume", 0) + 1
            if "registry" in use and _capture(winapi.clear_registry_cache):
                self.stats["registry"] = self.stats.get("registry", 0) + 1
            if not game_mode and "filecache" in use and _capture(winapi.clear_system_file_cache):
                self.stats["filecache"] = self.stats.get("filecache", 0) + 1
            # 清自身工作集（~0.2s，释放 MemWise 自身占用的几十 MB；高频路径可传 clean_self=False 关闭）
            if clean_self:
                try: winapi.empty_ws(os.getpid())
                except Exception: pass
            if freed_total > 0:
                self.stats["freed_bytes"] += freed_total
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
        if ws_before > 200 << 20 or theta > deepen:
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

        for round_idx in range(passes):
            if not winapi.empty_ws(pid):
                with self._lock:
                    if round_idx == 0:
                        self.stats["skipped"] += 1
                return False, 0, 0, "API失败"
            if round_idx < passes - 1:
                time.sleep(max(0.05, t_wait))

        # 等待 PF 反馈测量
        elapsed = interval * 0.5 * (passes - 1)
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
        """合并内置游戏名单 + 用户自定义的游戏进程"""
        extra = set()
        for n in self.judger.cfg.get("game_processes", []):
            extra.add(n.lower())
        return GAME_PROCESSES | extra

    def _is_user_game_running(self, snaps):
        """检测游戏运行（内置名单 + 用户自定义 + 全屏窗口检测）"""
        all_games = self._get_user_game_procs()
        game_procs = set()
        for s in snaps:
            if s.name.lower() in all_games:
                game_procs.add(s.name.lower())
        if game_procs:
            self.judger._game_proc_set = game_procs
            return True
        # 全屏检测：前台窗口覆盖全屏且非已知系统窗口 → 视为游戏
        try:
            if winapi.is_foreground_fullscreen():
                return True
        except Exception:
            pass
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
        """四维复合评分（替代单维 θ 排序）"""
        name = s.name.lower()
        theta = learner.thompson_score(name, mem_pct=getattr(self.judger, '_last_mem_pct', 50), is_fg=getattr(s, 'fg', False))
        p = learner.get_profile(name)
        x_freed = p.kalman.x_freed if p and hasattr(p.kalman, 'x_freed') else 0
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
                0.2 * min(regrowth, 2.0) +
                bonus)
    @staticmethod
    def _bounded_submit(executor, fn, items, max_inflight, per_task_timeout, total_budget=60.0):
        """滑动窗口分批提交：在途 ≤ max_inflight；超时判定基于任务的真实执行时长
        （排队等待不计时——排队任务保留在窗口直到开始执行，杜绝无辜进程排队超时被惩罚）。
        total_budget 总预算：池线程卡死时防止无限循环（超预算丢弃剩余排队项，已提交任务自然完成）。
        返回 [(item, result)]；超时/异常任务的 result 为 None（任务自然跑完，结果丢弃）。"""
        out = []
        inflight = {}
        started = {}
        idx = 0
        n = len(items)
        deadline = time.time() + total_budget
        while idx < n or inflight:
            if time.time() > deadline:
                # 总预算耗尽：剩余未提交项直接标记超时，已提交任务交给线程池自然完成（不阻塞调用方）
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
        return out

    def _layer2_process(self, snaps, learner):
        """进程级清理 — 游戏检测 + Thompson/ROI 选进程 + 内存优先级"""
        # ── 检测游戏模式 ──
        game_on = self._is_user_game_running(snaps)
        if self._game_mode_manual:
            # 手动模式：模式开关由用户持有，自动检测只做数据维护
            if game_on:
                self._game_gone_count = 0
            elif not game_on and self.game_mode:
                # 游戏已退出：清空失效 PID 保护集（防 PID 复用误保护），模式保持手动开启
                self.judger._game_pid_set.clear()
                self.judger._game_proc_set.clear()
        elif game_on and not self.game_mode:
            self._info_msgs.append("🎮 检测到游戏运行 · 启用 游戏模式")
            self.judger._game_proc_set = getattr(self.judger, '_game_proc_set', set())
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
                self.judger._game_proc_set.clear()
                self.judger._game_pid_set.clear()
                self._game_gone_count = 0
        else:
            self.game_mode = game_on
            self.judger.game_mode = game_on
            if game_on:
                self._game_gone_count = 0
        # 游戏运行期间每轮刷新 PID 保护集（覆盖游戏内后启动的子进程/新实例）
        if game_on:
            all_games = self._get_user_game_procs()
            self.judger._game_pid_set = {s.pid for s in snaps if s.name.lower() in all_games}

        candidates = []
        probe_list = []

        import os
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

        # ── 全局 3 层内存优先级 + EcoQoS ──
        # 所有非系统非黑名单进程，按 θ 分 3 层设 MemoryPriority + EcoQoS。
        # 这比 EmptyWorkingSet 更温和——只是提示 Windows 优先/延后回收。
        # 每 30 tick 全部重新评估一次，确保优先级始终与最新 θ 匹配
        self._pri_refresh_counter += 1
        if self._pri_refresh_counter >= 30:
            self._low_pri_pids.clear()
            self._pri_refresh_counter = 0
        for s in snaps:
            # 游戏进程（含此前被降级的）：恢复默认优先级/EcoQoS，确保不被 OS 优先回收
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
            # 前台进程: 保持默认优先级（不需调用API）
            if getattr(s, "fg", False):
                winapi.set_eco_qos(s.pid, False)
                self._low_pri_pids.add(s.pid)
                continue
            # 游戏进程分支已提前处理（恢复默认优先级），此处不再重复
            theta = learner.thompson_score(name, mem_pct=getattr(self.judger, '_last_mem_pct', 50), is_fg=getattr(s, 'fg', False))
            if theta >= 0.3:
                level = 0   # VERY_LOW for proven processes
            else:
                level = 1   # LOW for all else (OS reclaims proactively)
            if winapi.set_memory_priority(s.pid, level):
                winapi.set_eco_qos(s.pid, True)
                self._low_pri_pids.add(s.pid)
        # 清除已退出的 PID
        alive = {s.pid for s in snaps}
        self._low_pri_pids &= alive

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
                                             per_task_timeout=4, total_budget=20):
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
                if slope > 0.002 and s.ws > 50 << 20:
                    s._growth_bonus = min(0.3, slope * 30)

        # ── 进程树感知：同一父进程的子进程批量排序 ──
        # 对 candidates 按父进程分组，同组内按 θ 降序
        # 浏览器(Chrome/Edge/Firefox)等有多子进程的应用优先批量清理
        tree_bonus = {}
        for s in candidates:
            pname = s.name.lower()
            if any(b in pname for b in ["chrome", "msedge", "firefox", "brave", "opera", "electron"]):
                parent = winapi.get_parent_process_name(s.pid)
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
            for s, r in self._bounded_submit(self._trim_executor, fn, candidates,
                                             max_inflight=self._max_workers * 2,
                                             per_task_timeout=8, total_budget=20):
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

    def _layer3_deep(self, snaps, learner, aggressiveness, ops_filter=None):
        # 门控：Layer3 深度操作由 ws/standby/modified 驱动（volume/filecache/registry 单独勾选不触发深度层）
        if ops_filter is not None and not ({"ws", "standby", "modified"} & set(ops_filter)):
            return
        
        mem_before_layer3 = winapi.get_memory_status()
        self.stats["layer3_ran"] += 1
        # 逐操作测量释放量（与 Layer1 同口径）：阶段 C 系统操作的释放量此前只进 layer3_extra，
        # 图表/统计栏的 freed_bytes 一直缺失这部分（每轮可能漏几百 MB）
        freed_l3 = 0
        def _capture(fn):
            nonlocal freed_l3
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
                _capture(self.clear_file_cache)
                _capture(winapi.clear_system_file_cache_ex)
        if freed_l3 > 0:
            self.stats["freed_bytes"] += freed_l3
        # Track Layer3 standby release（EFIS 诊断专用：Layer3 整体净增量）
        mem_after_standby = winapi.get_memory_status()
        if mem_before_layer3 and mem_after_standby:
            extra_mem = mem_after_standby["avail"] - mem_before_layer3["avail"]
            if extra_mem > 0:
                self.stats["layer3_extra"] += extra_mem  # bytes, consistent with deepen_extra

        # 阶段 D: WS 回弹率选进程 (skip already trimmed in Layer2)
        # 复用滑动窗口分批提交（在途限制 + 总预算），防一次性 submit 堆积拖垮池
        layer2_pids = {t[0].pid for t in getattr(self, "_last_layer2_results", []) if t[1]}
        d_candidates = []
        for s in snaps:
            if s.pid in layer2_pids:
                continue  # Already trimmed in Layer2, skip
            if self.game_mode and s.pid in getattr(self.judger, '_game_pid_set', set()):
                continue  # 游戏进程绝对保护，深度聚合同样不碰
            name_lower = s.name.lower()
            bl = self.judger._post_clean_ws.get(name_lower, 0)
            if bl > 0 and s.ws >= bl * 2.0:
                d_candidates.append(s)
            elif bl == 0:
                theta = learner.thompson_score(name_lower, mem_pct=getattr(self.judger, '_last_mem_pct', 50), is_fg=getattr(s, 'fg', False))
                if theta > 0.5:
                    d_candidates.append(s)
        if d_candidates:
            fn = functools.partial(self._trim_process, learner=learner)
            for _s, _r in self._bounded_submit(self._trim_executor, fn, d_candidates,
                                               max_inflight=self._max_workers * 2,
                                               per_task_timeout=8, total_budget=30):
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
        mem_before_opt = winapi.get_memory_used_bytes()
        if aggressiveness is None:
            mem = winapi.get_memory_status()
            agg = self.judger.update_pressure(mem["pct"]) if mem else 0.5
        else:
            agg = aggressiveness
        ops_filter = set(operations) if operations else None
        run_ws = ops_filter is None or "ws" in ops_filter
        # 管线上下文：层间传递执行状态，避免重复工作
        pipeline_ctx = {"layer1_done": False, "layer2_trimmed": set(), "layer1_freed": 0}
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
            self._layer1_memreduct(full=False, total_procs=len(snaps), game_mode=self.game_mode,
                                   ops=self._layer1_ops(ops_filter))
            pipeline_ctx["layer1_done"] = True
            # Layer3 门槛由 EFIS layer3_agg_gate 自适应控制（无参数时兜底 0.3）；
            # 高频 gap-fill 路径传 allow_layer3=False，深度操作只在 harvest 执行
            if allow_layer3:
                _l3_gate = self.judger.cfg.get("efis_params", {}).get("layer3_agg_gate", 0.3)
                if agg >= _l3_gate:
                    self._layer3_deep(snaps, learner, agg, ops_filter)
            return _mk_result(l2_results, probe_results)
        
        elif mode == "deep":
            # normal 基础 + 系统级全清 WS + 强制 Layer3（文件缓存/各操作按用户开关）
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            pipeline_ctx["layer2_trimmed"] = {r[0].name for r in l2_results if r[1]}
            self._layer1_memreduct(full=True, total_procs=len(snaps), game_mode=self.game_mode,
                                   ops=self._layer1_ops(ops_filter))
            pipeline_ctx["layer1_done"] = True
            self._layer3_deep(snaps, learner, agg, ops_filter)
            return _mk_result(l2_results, probe_results)
        
        elif mode == "full":
            # deep 基础 + 进程回弹二轮 + 强制高 agg Layer3（各操作按用户开关）
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            pipeline_ctx["layer2_trimmed"] = {r[0].name for r in l2_results if r[1]}
            self._layer1_memreduct(full=True, total_procs=len(snaps), game_mode=self.game_mode,
                                   ops=self._layer1_ops(ops_filter))
            pipeline_ctx["layer1_done"] = True
            self._layer3_deep(snaps, learner, max(agg, 0.6), ops_filter)
            agg = max(agg, 0.6)  # full 模式强制 agg ≥0.6，同步返回结果
            # 回弹二轮：对已修剪进程追加 WS 清空
            if pipeline_ctx["layer2_trimmed"]:
                for s in snaps:
                    if s.name in pipeline_ctx["layer2_trimmed"] and s.ws >= (10 << 20):
                        try:
                            winapi.empty_ws(s.pid)
                        except Exception:
                            pass
            return _mk_result(l2_results, probe_results)

        else:
            self._layer1_memreduct()
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
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
