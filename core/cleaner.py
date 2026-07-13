"""
PARES Cleaner — 3 层清理引擎
Layer 1: 系统级 (Standby/Modified/FileCache/Combine)
Layer 2: 进程级 (EmptyWorkingSet with Thompson/ROI/Probe)
Layer 3: 深度聚合 (高压力时重复执行)
"""
import time, concurrent.futures, threading, os
from . import winapi
from .learner import SYSTEM_CORE

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
        self._low_pri_pids = set()
        self._pri_refresh_counter = 0
        self._fast_track = set()  # 高回填率 PID，gap-fill 期间快速重清
        self._last_standby_time = 0
        self._lock = threading.Lock()
        self._max_workers = min(os.cpu_count() or 2, 4)
        self._probe_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="memwise-probe")
        self._trim_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="memwise-trim")
        prev_freed = self.stats.get("freed_bytes", 0) if hasattr(self, 'stats') else 0
        self.stats = {
            "standby": 0, "modified": 0, "filecache": 0,
            "compress": 0, "combine": 0, "ws_trim": 0, "probe": 0,
            "skipped": 0, "failed_feedback": 0,
            "freed_bytes": prev_freed,
            "deepen_cnt": 0, "deepen_extra": 0,
            "layer3_ran": 0, "layer3_extra": 0,
        }
        self._info_msgs = []

    def pop_info(self):
        msgs = self._info_msgs[:]
        self._info_msgs.clear()
        return msgs

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

    def clean_standby(self):
        ok = winapi.empty_standby()
        if ok:
            self.stats["standby"] += 1
        return ok

    def clean_standby_low(self):
        ok = winapi.purge_low_priority_standby()
        if ok:
            self.stats["standby"] += 1
        return ok

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

    def clean_compress(self):
        ok = winapi.trigger_memory_compression()
        if ok:
            self.stats["compress"] += 1
        return ok

    def clean_combine_lists(self):
        ok = winapi.combine_memory_lists()
        if ok:
            self.stats["combine"] += 1
        return ok

    def _clear_registry_cache(self):
        ok = winapi.clear_registry_cache()
        if ok:
            self.stats["registry"] = self.stats.get("registry", 0) + 1
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
            self.stats["combine"] += 1
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

    def _layer1_light(self, aggressiveness):
        """Lightweight system ops for gap fill: compress + modified, no standby"""
        try:
            if aggressiveness > 0.4:
                winapi.deep_compress()
            else:
                winapi.trigger_memory_compression()
            winapi.flush_modified_pages()
            self.stats["compress"] = self.stats.get("compress", 0) + 1
            self.stats["modified"] = self.stats.get("modified", 0) + 1
        except Exception:
            pass

    def _layer1_memreduct(self, full=True):
        """系统级内核清理 — 无 sleep，<10ms
        
        full=True : 全量 8 步（含系统级 WS 全清），主 pass 使用
        full=False: 轻量 7 步（跳过 WS 全清），gap-fill 持续压制用
        
        操作码对齐 PHNT 标准。
        """
        try:
            # 轻量模式跳过系统级 WS 全清（留给主 pass 做一次性深度收割）
            if full:
                winapi.empty_all_working_sets()
            mem_pre = winapi.get_memory_used_bytes()
            winapi.clear_system_file_cache_ex()
            winapi.flush_modified_pages()
            winapi.empty_standby()
            winapi.purge_low_priority_standby()
            winapi.flush_volume_cache()
            winapi.clear_registry_cache()
            winapi.clear_system_file_cache()
            mem_post = winapi.get_memory_used_bytes()
            sys_freed = max(0, mem_pre - mem_post)
            if sys_freed > 0:
                self.stats["freed_bytes"] += sys_freed
            self.stats["standby"] += 1
            self.stats["compress"] += 1
            self.stats["modified"] = self.stats.get("modified", 0) + 1
            return True
        except Exception:
            return False

    def _layer1_system(self, aggressiveness, ops_filter=None):
        """
        系统级清理 — 两阶段异步管线
        阶段 1: 触发异步操作（压缩+脏页写回，零阻塞）
        阶段 2: 等待 0.3s 让 OS 处理异步操作
        阶段 3: 收割（全部 standby 类操作统一回收）
        """
        # 注意：不调用 empty_all_working_sets（系统级全清会把自己 page out）
        has_sb = ops_filter is None or "standby" in ops_filter
        has_mp = ops_filter is None or "modified" in ops_filter
        has_fc = ops_filter is None or "filecache" in ops_filter
        has_cp = ops_filter is None or "compress" in ops_filter
        has_reg = ops_filter is None or "registry" in ops_filter
        has_vol = ops_filter is None or "volume" in ops_filter

        self._last_standby_time = time.time()
        mem_pre_sys = winapi.get_memory_status()

        # 阶段 1: 触发异步操作
        if has_cp:
            winapi.deep_compress()  # 简化后的单轮压缩管线，无 sleep
        if has_mp:
            self.clean_modified_pages()

        # 阶段 2: 内核操作已同步完成，无需等待

        # 阶段 3: 收割（全部回收）
        if has_reg:
            self._clear_registry_cache()
        if has_sb:
            winapi.purge_low_priority_standby()
            self.clean_standby_low()
            self.clean_standby()
            self.clean_deep_standby()
        if has_vol:
            self._flush_volume_cache()
        if has_sb:
            self.clean_combine_lists()
        # Track system-level release
        if mem_pre_sys:
            mem_post_sys = winapi.get_memory_status()
            sys_freed = (mem_post_sys["avail"] - mem_pre_sys["avail"]) if mem_post_sys else 0
            if sys_freed > 0:
                self.stats["freed_bytes"] += sys_freed
        if has_fc:
            self.clear_file_cache()
            winapi.clear_system_file_cache_ex()

    # ── Layer 2: 进程级清理 ──

    def _probe_process(self, snap, learner):
        """微型试探 — 对不确定进程做轻量测试 (单次清理, ~0.2s 等待)"""
        pid, name = snap.pid, snap.name
        ws_before = snap.ws
        # 读取实时 PF 作为基线（不用快照的旧值）
        mem_before = winapi.get_process_memory(pid)
        pf_before = mem_before["pf"] if mem_before else snap.pf
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
        pf_delta = max(0, pf_after - pf_before)
        freed = max(0, ws_before - ws_after)
        # 允许的 PF：至少 30，或每释放 1MB 允许 10 个 PF（同 trim 逻辑）
        # Probe 本身会产生 ~30-50 PF（EmptyWorkingSet 的开销）
        # freed=0 时也视作有效观测（进程无可释放页本身就是信息）
        allowed_pf = max(120, freed // (1 << 20) * 10)
        ok = pf_delta <= allowed_pf
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
        self.judger.record_pf_before(pid, mem_before["pf"] if mem_before else snap.pf)

        # Restored pass counts: 4/3/2 (like old v1.6) with compressed waits
        deepen = self.judger.cfg.get("efis_params", {}).get("deepen_theta", 0.6)
        theta = learner.thompson_score(name)
        if ws_before > 200 << 20 or theta > deepen:
            passes = 4; total_wait = 1.0
        elif ws_before > 50 << 20:
            passes = 3; total_wait = 0.6
        elif theta < 0.15:
            passes = 1; total_wait = 0.3
        else:
            passes = 2; total_wait = 0.4
        # 用户配置上限
        max_p = self.judger.cfg.get("efis_params", {}).get("clean_passes", 4)
        try: max_p = int(max_p)
        except: max_p = 4
        passes = min(passes, max_p)

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
                # 记录因果
                if hasattr(learner, 'record_causal'):
                    learner.record_causal(name, freed,
                        getattr(self.judger, '_last_mem_pct', 50),
                        [s.name for s in getattr(self, '_last_candidates', [])])
            learner.record_clean_result(name, ok, freed, pf_delta, self._efis_lr())
            if ok:
                self.judger.mark_trimmed(name, freed, ws_before, pf_delta, ws_after)
                self.stats["ws_trim"] += 1
                if passes >= 2:
                    self.stats["deepen_cnt"] += 1
            else:
                # PF 超标：仅记录负面学习信号，不丢弃已释放的字节
                p = learner.get_profile(name)
                self.judger.mark_failed(name, p.fail_cnt if p else 1)
                self.stats["failed_feedback"] += 1
        if ok:
            return True, freed, pf_delta, "完成"
        else:
            return False, freed, pf_delta, "PF超标"

    def _efis_lr(self):
        """从 judger.cfg 读取 EFIS 调好的 learning_rate"""
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
        if any(s.name.lower() in all_games for s in snaps):
            return True
        # 全屏检测：前台窗口覆盖全屏且非已知系统窗口 → 视为游戏
        try:
            return winapi.is_foreground_fullscreen()
        except Exception:
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
        theta = learner.thompson_score(name)
        p = learner.get_profile(name)
        x_freed = p.kalman.x_freed if p and hasattr(p.kalman, 'x_freed') else 0
        ws = s.ws
        bl = self.judger._post_clean_ws.get(name, 0)
        regrowth = ws / max(bl, 1) if bl > 0 else 1.0
        kw = self.judger.cfg.get("efis_params", {}).get("composite_kalman_w", 0.3)
        tw = 0.6 - kw
        return (tw * min(theta, 1.0) +
                kw * min(x_freed / (200 << 20), 1.0) +
                0.2 * min(ws / (500 << 20), 1.0) +
                0.2 * min(regrowth, 2.0))
    def _layer2_process(self, snaps, learner):
        """进程级清理 — 游戏检测 + Thompson/ROI 选进程 + 内存优先级"""
        # ── 检测游戏模式 ──
        game_on = self._is_user_game_running(snaps)
        if game_on and not self.game_mode:
            self._info_msgs.append("🎮 检测到游戏运行·切换到激进清理模式")
        self.game_mode = game_on
        self.judger.game_mode = game_on

        candidates = []
        probe_list = []
        self._last_candidates = candidates  # 供因果记录使用

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
            if s.pid in self._low_pri_pids:
                continue
            name = s.name.lower()
            if name in SYSTEM_CORE or name in self.judger.cfg.get("never", []):
                continue
            # 前台进程: 保持默认优先级（不需调用API）
            if getattr(s, "fg", False):
                winapi.set_eco_qos(s.pid, False)
                self._low_pri_pids.add(s.pid)
                continue
            theta = learner.thompson_score(name)
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

        # Probe — 并行执行（时间预算制，剩余进程下一轮重排后继续）
        probe_results = []
        if probe_list:
            fut = {self._probe_executor.submit(self._probe_process, s, learner): s for s in probe_list}
            for f in concurrent.futures.as_completed(fut):
                s = fut[f]
                ok, freed, pf_delta = f.result()
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

        self.judger._last_candidates = [s.name for s in candidates]
        # Fast-track: high-refill PIDs for gap-fill re-trim
        self._fast_track = set()
        for s in candidates:
            p = learner.get_profile(s.name)
            if p and getattr(p, 'refill_ewma', 0) > 500 << 10:
                self._fast_track.add(s.pid)
        candidates.sort(key=lambda s: -self._composite_score_v2(s, learner) - getattr(s, '_growth_bonus', 0))
        trimmed_skipped = 0
        results = []
        if candidates:
            fut = {self._trim_executor.submit(self._trim_process, s, learner): s for s in candidates}
            for f in concurrent.futures.as_completed(fut):
                s = fut[f]
                ok, freed, pf_delta, reason = f.result()
                results.append((s, ok, freed, reason))

        self._last_layer2_results = results
        return results, probe_results

    # ── Layer 3: 深度聚合 ──

    def _layer3_deep(self, snaps, learner, aggressiveness, ops_filter=None):
        if ops_filter is not None and "ws" not in ops_filter:
            return
        
        mem_before_layer3 = winapi.get_memory_status()
        self.stats["layer3_ran"] += 1
        agg_label = '极低' if aggressiveness <= 0.01 else ('低' if aggressiveness <= 0.30 else ('中' if aggressiveness <= 0.60 else '高'))
        if agg_label != getattr(self, '_last_layer3_agg', ''):
            self._info_msgs.append(f"🔁 触发深度清理(清理强度:{agg_label})")
            self._last_layer3_agg = agg_label

        # 预处理：使用简化的 deep_compress（无 sleep 管线）
        if ops_filter is None or "compress" in ops_filter:
            winapi.deep_compress()
        if ops_filter is None or "modified" in ops_filter:
            self.clean_modified_pages()
        # 内核操作已同步完成，无需等待

        # 阶段 C: 收前
        if ops_filter is None or "standby" in ops_filter:
            winapi.purge_low_priority_standby()
            self.clean_standby_low()
            self.clean_standby()
            self.clean_deep_standby()
        if ops_filter is None or "volume" in ops_filter:
            self._flush_volume_cache()
        if ops_filter is None or "filecache" in ops_filter:
            self.clear_file_cache()
            winapi.clear_system_file_cache_ex()
        if ops_filter is None or "standby" in ops_filter:
            self.clean_combine_lists()
        # Track Layer3 standby release
        mem_after_standby = winapi.get_memory_status()
        if mem_before_layer3 and mem_after_standby:
            extra_mem = mem_after_standby["avail"] - mem_before_layer3["avail"]
            if extra_mem > 0:
                self.stats["layer3_extra"] += extra_mem  # bytes, consistent with deepen_extra

        # 阶段 D: WS 回弹率选进程 (skip already trimmed in Layer2)
        layer2_pids = {t[0].pid for t in getattr(self, "_last_layer2_results", []) if t[1]}
        pids_trimmed = set()
        futs = {}
        for s in snaps:
            if s.pid in layer2_pids:
                continue  # Already trimmed in Layer2, skip
            name_lower = s.name.lower()
            bl = self.judger._post_clean_ws.get(name_lower, 0)
            if bl > 0 and s.ws >= bl * 1.5:
                if s.pid not in pids_trimmed:
                    pids_trimmed.add(s.pid)
                    futs[s.pid] = self._trim_executor.submit(self._trim_process, s, learner)
            elif bl == 0:
                theta = learner.thompson_score(name_lower)
                if theta > 0.5:
                    if s.pid not in pids_trimmed:
                        pids_trimmed.add(s.pid)
                        futs[s.pid] = self._trim_executor.submit(self._trim_process, s, learner)

        # 并行等待所有 layer3 trim
        for f in concurrent.futures.as_completed(futs.values()):
            try:
                f.result()
            except Exception as e:
                import sys; print(f"[MemWise] layer3 清理异常: {e}", file=sys.stderr)

    # ── 统一入口 ──

    def optimize(self, snaps, learner, mode="normal", operations=None, score_fn=None, aggressiveness=None):
        """
        统一优化入口 — 已激活 8 步内核快速管线

        mode: quick|normal|deep|full
            quick  = layer1(7 步快速管线) + layer2(full probe+trim)
            normal = layer1(7 步) + layer2(full) + layer3(if agg>=0.3)
            deep   = layer1(8 步) + layer2 + layer3(always)
            full   = layer1(8 步) + layer2 + layer3 + extra standby

        operations: 可选列表，限制允许的清理操作，如 ["ws","standby","modified","filecache"]
        aggressiveness: 可选，预计算的 aggressiveness 值（daemon 模式避免 PID 双重更新）
        """
        mem_before_opt = winapi.get_memory_used_bytes()
        if aggressiveness is None:
            mem = winapi.get_memory_status()
            agg = self.judger.update_pressure(mem["pct"]) if mem else 0.5
        else:
            agg = aggressiveness
        ops_filter = set(operations) if operations else None
        run_ws = ops_filter is None or "ws" in ops_filter
        # Helper to build result with net_freed tracking
        def _mk_result(l2, probe):
            r = {"mode": mode, "aggressiveness": agg, "layer2": l2, "probe": probe}
            mem_after = winapi.get_memory_used_bytes()
            r["net_freed"] = max(0, mem_before_opt - mem_after)
            return r

        if mode == "quick":
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            if agg > 0.1:
                self._layer1_memreduct()
            return _mk_result(l2_results, probe_results)

        elif mode == "normal":
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            self._layer1_memreduct()
            if agg >= 0.3:
                self._layer3_deep(snaps, learner, agg, ops_filter)
            return _mk_result(l2_results, probe_results)

        elif mode == "deep":
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            self._layer1_memreduct()
            self._layer3_deep(snaps, learner, agg, ops_filter)
            return _mk_result(l2_results, probe_results)

        elif mode == "full":
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            self._layer1_memreduct()
            self._layer3_deep(snaps, learner, max(agg, 0.5), ops_filter)
            return _mk_result(l2_results, probe_results)

        else:
            self._layer1_memreduct()
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            return _mk_result(l2_results, probe_results)
    def trim_batch(self, snaps, learner):
        """给 daemon 用的轻量批量整理"""
        results, _ = self._layer2_process(snaps, learner)
        return results

    # ── 统计 ──

    def summary(self):
        s = self.stats.copy()
        s["freed_mb"] = round(s["freed_bytes"] / (1 << 20), 1)
        return s

    def reset_stats(self):
        prev_freed = self.stats.get("freed_bytes", 0) if hasattr(self, 'stats') else 0
        self.stats = {
            "standby": 0, "modified": 0, "filecache": 0,
            "compress": 0, "combine": 0, "ws_trim": 0, "probe": 0,
            "skipped": 0, "failed_feedback": 0,
            "freed_bytes": prev_freed,
            "deepen_cnt": 0, "deepen_extra": 0,
            "layer3_ran": 0, "layer3_extra": 0,
        }
        self.judger._post_clean_ws.clear()
        self.judger._post_clean_time.clear()
