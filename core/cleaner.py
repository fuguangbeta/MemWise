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
        self._low_pri_pids = set()  # 已设低内存优先级的 PID，避免重复 API 调用
        self._pri_refresh_counter = 0  # 优先级刷新计数器，每 30 tick 全部重新评估
        self._last_standby_time = 0  # 上次 Standby 清理时间，防止过于频繁
        self._lock = threading.Lock()
        self._max_workers = min(os.cpu_count() or 4, 8)
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=self._max_workers, thread_name_prefix="memwise")
        self.stats = {
            "standby": 0, "modified": 0, "filecache": 0,
            "compress": 0, "combine": 0, "ws_trim": 0, "probe": 0,
            "skipped": 0, "failed_feedback": 0,
            "freed_bytes": 0,
        }

    def __del__(self):
        try:
            self._executor.shutdown(wait=False)
        except Exception:
            pass

    def shutdown(self):
        """安全关闭线程池"""
        self._executor.shutdown(wait=False)

    # ── Layer 1: 系统级清理 ──

    def clean_standby(self):
        ok = winapi.empty_standby()
        if ok:
            self.stats["standby"] += 1
        return ok

    def clean_standby_low(self):
        ok = winapi.empty_standby_low_priority()
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

    def clean_deep_standby(self):
        """深度多轮 Standby 清理 — 比单次释放更多"""
        ok = winapi.empty_standby_deep()
        if ok:
            self.stats["standby"] += 2  # 多轮，计数加2
            self.stats["combine"] += 1
        return ok

    def _progressive_compress(self):
        """多轮渐进式压缩：触发压缩→等待→低优先Standby→等待→Standby全量
        Windows 内存压缩是异步的，触发后需要时间完成压缩页面的移动，
        然后 Standby 清理才能回收压缩存储释放的物理页。"""
        if not winapi.trigger_memory_compression():
            return False
        self.stats["compress"] += 1
        time.sleep(0.5)
        # 低优先 standby 回收压缩释放的页（更温和）
        winapi.empty_standby_low_priority()
        self.stats["standby"] += 1
        time.sleep(0.3)
        # 全量 standby 再回收一轮
        winapi.empty_standby()
        self.stats["standby"] += 1
        return True

    def _layer1_system(self, aggressiveness, ops_filter=None):
        """
        系统级清理 — 根据 ops_filter 选择执行哪些操作（不由内存压力决定力度）
        ops_filter: None = 全部, 集合如 {"standby","modified","filecache","compress"}
        由上层 mode（quick/normal/deep/full）控制调用此方法时传入的 ops_filter。
        """
        ops = []
        has_sb = ops_filter is None or "standby" in ops_filter
        has_mp = ops_filter is None or "modified" in ops_filter
        has_fc = ops_filter is None or "filecache" in ops_filter
        has_cp = ops_filter is None or "compress" in ops_filter

        now = time.time()
        # 按 ops_filter 执行全部允许的操作，力度由 mode 决定，不由内存压力决定
        if has_cp:
            if aggressiveness > 0.4:
                ops.append(("progressive_compress", self._progressive_compress))
            else:
                ops.append(("compress", self.clean_compress))
        if has_sb:
            ops.append(("standby_low", self.clean_standby_low))
            ops.append(("standby", self.clean_standby))
            ops.append(("deep_standby", self.clean_deep_standby))
        if has_mp:
            ops.append(("modified", self.clean_modified_pages))
        if has_sb:
            ops.append(("combine", self.clean_combine_lists))
        if has_fc:
            ops.append(("filecache", self.clear_file_cache))

        if ops:
            self._last_standby_time = now
            results = {}
            for name, fn in ops:
                results[name] = fn()
            return results
        return {}

    # ── Layer 2: 进程级清理 ──

    def _probe_process(self, snap, learner):
        """微型试探 — 对不确定进程做轻量测试 (双次清理, ~1s 等待)"""
        pid, name = snap.pid, snap.name
        ws_before = snap.ws
        if not winapi.empty_ws(pid):
            return False, 0, 0
        # 二次清理：自适应间隔，捕获进程主动释放的页
        interval = self._adaptive_interval(learner, name)
        time.sleep(interval)
        winapi.empty_ws(pid)
        time.sleep(1.0 - interval)  # 保持总等待 ~1s
        mem = winapi.get_process_memory(pid)
        if mem is None:
            with self._lock:
                learner.record_probe_result(name, True)
                self.judger.mark_probed(name)
            return True, ws_before, 0
        ws_after = mem["ws"]
        pf_after = mem["pf"]
        pf_before = snap.pf
        pf_delta = max(0, pf_after - pf_before)
        freed = max(0, ws_before - ws_after)
        # 1s 内 PF 增量少于 20 就算成功
        ok = pf_delta < 20
        with self._lock:
            learner.record_probe_result(name, ok)
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
        if ws_before < 10 << 20:
            return False, 0, 0, "WS太小"
        self.judger.record_pf_before(pid, mem_before["pf"] if mem_before else snap.pf)

        # 自适应轮数：大进程更多清理次数
        if ws_before > 200 << 20:
            passes = 4
            total_wait = 4.0
        elif ws_before > 50 << 20:
            passes = 3
            total_wait = 3.5
        else:
            passes = 2
            total_wait = 2.5

        interval = self._adaptive_interval(learner, name)
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
                learner.record_clean_result(name, True)
                self.judger.mark_trimmed(name)
                self.stats["ws_trim"] += 1
            return True, ws_before, 0, "进程已退出"
        ws_after = mem["ws"]
        ok, freed, pf_delta = self.judger.check_feedback(
            pid, mem["pf"], ws_before, ws_after
        )
        with self._lock:
            learner.record_clean_result(name, ok, freed, pf_delta)
            if ok:
                self.judger.mark_trimmed(name, freed, ws_before, pf_delta, ws_after)
                self.stats["ws_trim"] += 1
                if freed > 0:
                    self.stats["freed_bytes"] += freed
            else:
                p = learner.get_profile(name)
                self.judger.mark_failed(name, p.fail_cnt if p else 1)
                self.stats["failed_feedback"] += 1
        if ok:
            return True, freed, pf_delta, "完成"
        else:
            return False, freed, pf_delta, "PF超标"

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
    MAX_TRIM = 30

    def _adaptive_interval(self, learner, name):
        """根据进程 refill rate 自适应双次清理间隔
        refill 快 → 短间隔 (更快捕获二次释放)
        refill 慢 → 长间隔 (更温和)"""
        p = learner.get_profile(name)
        if not p or p.refill_ewma <= 0:
            return 0.3  # 默认 300ms
        # refill_ewma > 1MB/s = 快 → 150ms
        if p.refill_ewma > 1 << 20:
            return 0.15
        # refill_ewma < 100KB/s = 慢 → 500ms
        if p.refill_ewma < 100 << 10:
            return 0.5
        return 0.3

    def _layer2_process(self, snaps, learner):
        """进程级清理 — 游戏检测 + Thompson/ROI 选进程 + 内存优先级"""
        # ── 检测游戏模式 ──
        game_on = self._is_user_game_running(snaps)
        self.game_mode = game_on
        self.judger.game_mode = game_on

        candidates = []
        probe_list = []

        for s in snaps:
            # Probe 候选
            if self.judger.can_probe(s):
                probe_list.append(s)
                continue

            ok, reason = self.judger.can_trim(s)
            if ok:
                candidates.append(s)
            else:
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
            # 前台进程: 正常优先级，不设 EcoQoS
            if getattr(s, "fg", False):
                winapi.set_memory_priority(s.pid, 5)
                winapi.set_eco_qos(s.pid, False)
                self._low_pri_pids.add(s.pid)
                continue
            theta = learner.thompson_score(name)
            if theta >= 0.7:
                level = 0   # MEMORY_PRIORITY_VERY_LOW — θ高，系统优先回收其物理页
            elif theta >= 0.3:
                level = 1   # MEMORY_PRIORITY_LOW
            else:
                continue    # θ低，保持正常优先级
            if winapi.set_memory_priority(s.pid, level):
                winapi.set_eco_qos(s.pid, True)
                self._low_pri_pids.add(s.pid)
        # 清除已退出的 PID
        alive = {s.pid for s in snaps}
        self._low_pri_pids &= alive

        # Probe — 并行执行
        probe_results = []
        if probe_list:
            fut = {self._executor.submit(self._probe_process, s, learner): s for s in probe_list[:10]}
            for f in concurrent.futures.as_completed(fut):
                s = fut[f]
                ok, freed, pf_delta = f.result()
                probe_results.append((s, ok, freed))

        # 完整清理 — 按复合评分排序，有限额，并行执行
        candidates.sort(key=lambda s: -learner.composite_score(s.name))
        candidates = candidates[:self.MAX_TRIM]
        results = []
        if candidates:
            fut = {self._executor.submit(self._trim_process, s, learner): s for s in candidates}
            for f in concurrent.futures.as_completed(fut):
                s = fut[f]
                ok, freed, pf_delta, reason = f.result()
                results.append((s, ok, freed, reason))

        return results, probe_results

    # ── Layer 3: 深度聚合 ──

    def _layer3_deep(self, snaps, learner, aggressiveness, ops_filter=None):
        """
        深度模式 — 高压力时重复执行
        第一次: layer1 + layer2
        第二次 (if high pressure): sleep 5s → layer1 again + layer2 again
        """
        if ops_filter is not None and "ws" not in ops_filter:
            return  # 禁用了 WS 清理

        time.sleep(2)

        # 系统级再来一遍
        self._layer1_system(aggressiveness, ops_filter)

        # 进程级再来一遍 — 并行 (只选高 ROI 的)
        high_theta = [s for s in snaps if learner.thompson_score(s.name) > 0.7]
        if high_theta:
            fut = {self._executor.submit(self._trim_process, s, learner): s for s in high_theta}
            for f in concurrent.futures.as_completed(fut):
                pass  # 结果不重要，side-effect 驱动

    # ── 统一入口 ──

    def optimize(self, snaps, learner, mode="normal", operations=None, score_fn=None, aggressiveness=None):
        """
        统一优化入口

        mode: quick|normal|deep|full
            quick  = layer2(probe only) + standby_low
            normal = layer1(mild) + layer2(full)
            deep   = layer1(aggressive) + layer2 + layer3
            full   = layer1(all) + layer2 + layer3 + extra standby

        operations: 可选列表，限制允许的清理操作，如 ["ws","standby","modified","filecache"]
        aggressiveness: 可选，预计算的 aggressiveness 值（daemon 模式避免 PID 双重更新）
        """
        if aggressiveness is None:
            mem = winapi.get_memory_status()
            agg = self.judger.update_pressure(mem["pct"]) if mem else 0.5
        else:
            agg = aggressiveness
        ops_filter = set(operations) if operations else None
        run_ws = ops_filter is None or "ws" in ops_filter

        if mode == "quick":
            if agg > 0.1:
                self._layer1_system(min(agg, 0.3), ops_filter)
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            return {"mode": mode, "aggressiveness": agg, "layer2": l2_results, "probe": probe_results}

        elif mode == "normal":
            self._layer1_system(agg, ops_filter)
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            if agg >= 0.6:
                self._layer3_deep(snaps, learner, agg, ops_filter)
            return {"mode": mode, "aggressiveness": agg, "layer2": l2_results, "probe": probe_results}

        elif mode == "deep":
            self._layer1_system(agg, ops_filter)
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            self._layer3_deep(snaps, learner, agg, ops_filter)
            return {"mode": mode, "aggressiveness": agg, "layer2": l2_results, "probe": probe_results}

        elif mode == "full":
            self._layer1_system(max(agg, 0.7), ops_filter)
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            if ops_filter is None or "standby" in ops_filter:
                self.clean_standby()
                self._layer3_deep(snaps, learner, agg, ops_filter)
                self.clean_compress()
                self.clean_standby_low()
            return {"mode": mode, "aggressiveness": agg, "layer2": l2_results, "probe": probe_results}

        else:
            self._layer1_system(agg, ops_filter)
            l2_results, probe_results = self._layer2_process(snaps, learner) if run_ws else ([], [])
            return {"mode": mode, "aggressiveness": agg, "layer2": l2_results, "probe": probe_results,
            }

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
        self.stats = {
            "standby": 0, "modified": 0, "filecache": 0,
            "compress": 0, "combine": 0, "ws_trim": 0, "probe": 0,
            "skipped": 0, "failed_feedback": 0,
            "freed_bytes": 0,
        }
