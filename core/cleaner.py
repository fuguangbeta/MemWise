"""
PARES Cleaner — 3 层清理引擎
Layer 1: 系统级 (Standby/Modified/FileCache/Combine)
Layer 2: 进程级 (EmptyWorkingSet with Thompson/ROI/Probe)
Layer 3: 深度聚合 (高压力时重复执行)
"""
import time
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
    "honkai3rd.exe", "honkai impact 3rd.exe",
    "genshinimpact.exe", "genshin impact.exe",
    "star rail.exe", "hkrpg.exe",
    "zzz.exe", "zenless zone zero.exe",
    "eurotrucks2.exe", "ats.exe",
}

class PareCleaner:
    """PARES 清理器 — 3 层引擎 + 游戏模式 + 内存优先级"""

    def __init__(self, judger):
        self.judger = judger
        self.game_mode = False
        self._low_pri_pids = set()  # 已设低内存优先级的 PID，避免重复 API 调用
        self.stats = {
            "standby": 0, "modified": 0, "filecache": 0,
            "combine": 0, "ws_trim": 0, "probe": 0,
            "skipped": 0, "failed_feedback": 0,
            "freed_bytes": 0,
        }

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

    def _layer1_system(self, aggressiveness, ops_filter=None):
        """
        系统级清理 — 根据 aggressiveness + ops_filter 选择执行哪些操作
        ops_filter: None = 全部, 集合如 {"standby","modified","filecache"}
        """
        ops = []
        has_sb = ops_filter is None or "standby" in ops_filter
        has_mp = ops_filter is None or "modified" in ops_filter
        has_fc = ops_filter is None or "filecache" in ops_filter

        if has_sb and aggressiveness > 0.05:
            ops.append(("standby_low", self.clean_standby_low))
        if has_sb and aggressiveness > 0.2:
            ops.append(("standby", self.clean_standby))
        if has_sb and aggressiveness > 0.25:
            ops.append(("deep_standby", self.clean_deep_standby))
        if has_mp and aggressiveness > 0.3:
            ops.append(("modified", self.clean_modified_pages))
        if has_sb and aggressiveness > 0.5:
            ops.append(("combine", self.clean_combine_lists))
        if has_fc and aggressiveness > 0.5:
            ops.append(("filecache", self.clear_file_cache))

        results = {}
        for name, fn in ops:
            results[name] = fn()
        return results

    # ── Layer 2: 进程级清理 ──

    def _probe_process(self, snap, learner):
        """微型试探 — 对不确定进程做轻量测试 (双次清理, 1s 等待)"""
        pid, name = snap.pid, snap.name
        ws_before = snap.ws
        if not winapi.empty_ws(pid):
            return False, 0, 0
        # 二次清理：间隔 300ms 再清一次，捕获进程主动释放的页
        time.sleep(0.3)
        winapi.empty_ws(pid)
        time.sleep(0.7)
        mem = winapi.get_process_memory(pid)
        if mem is None:
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
        learner.record_probe_result(name, ok)
        self.judger.mark_probed(name)
        if ok and freed > 0:
            self.stats["freed_bytes"] += freed
        self.stats["probe"] += 1
        return ok, freed, pf_delta

    def _trim_process(self, snap, learner):
        """完整清理一个进程 (双次清理, 3s 等待 + 反馈验证)"""
        pid, name = snap.pid, snap.name
        ws_before = snap.ws
        self.judger.record_pf_before(pid, snap.pf)
        if not winapi.empty_ws(pid):
            self.stats["skipped"] += 1
            return False, 0, 0, "API失败"
        # 二次清理：间隔 300ms 再清一次，捕获进程主动释放的页
        time.sleep(0.3)
        winapi.empty_ws(pid)
        time.sleep(2.7)
        mem = winapi.get_process_memory(pid)
        if mem is None:
            learner.record_clean_result(name, True)
            self.judger.mark_trimmed(name)
            self.stats["ws_trim"] += 1
            return True, ws_before, 0, "进程已退出"
        ws_after = mem["ws"]
        ok, freed, pf_delta = self.judger.check_feedback(
            pid, mem["pf"], ws_before, ws_after
        )
        learner.record_clean_result(name, ok, freed, pf_delta)
        if ok:
            self.judger.mark_trimmed(name, freed, ws_before)
            self.stats["ws_trim"] += 1
            if freed > 0:
                self.stats["freed_bytes"] += freed
            return True, freed, pf_delta, "完成"
        else:
            self.judger.mark_failed(name, learner.get_profile(name).fail_cnt if learner.get_profile(name) else 1)
            self.stats["failed_feedback"] += 1
            return False, freed, pf_delta, "PF超标"

    def _get_user_game_procs(self):
        """合并内置游戏名单 + 用户自定义的游戏进程"""
        extra = set()
        for n in self.judger.cfg.get("game_processes", []):
            extra.add(n.lower())
        return GAME_PROCESSES | extra

    def _is_user_game_running(self, snaps):
        """检测游戏运行（内置名单 + 用户自定义）"""
        all_games = self._get_user_game_procs()
        return any(s.name.lower() in all_games for s in snaps)

    # 每 tick 最多清理的进程数，防止串行 sleep 堆积超时
    MAX_TRIM = 30

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

        # ── 游戏模式下：将非游戏后台进程内存优先级设低 ──
        if game_on:
            all_games = self._get_user_game_procs()
            for s in snaps:
                if s.pid in self._low_pri_pids:
                    continue
                name = s.name.lower()
                if (name not in all_games and name not in SYSTEM_CORE
                        and name not in self.judger.cfg.get("never", [])):
                    if winapi.set_memory_priority(s.pid, 0):
                        self._low_pri_pids.add(s.pid)
            # 清除已退出的 PID
            alive = {s.pid for s in snaps}
            self._low_pri_pids &= alive

        # 先执行 Probe (微型试探)
        probe_results = []
        for s in probe_list[:10]:  # 每轮最多 10 个 probe
            ok, freed, pf_delta = self._probe_process(s, learner)
            probe_results.append((s, ok, freed))

        # 再执行完整清理 — 按 Thompson θ 排序，有限额，防止串行 sleep 堆积
        candidates.sort(key=lambda s: -learner.thompson_score(s.name))
        candidates = candidates[:self.MAX_TRIM]
        results = []
        for s in candidates:
            ok, freed, pf_delta, reason = self._trim_process(s, learner)
            results.append((s, ok, freed, reason))

        return results, probe_results

    # ── Layer 3: 深度聚合 ──

    def _layer3_deep(self, snaps, learner, aggressiveness, ops_filter=None):
        """
        深度模式 — 高压力时重复执行
        第一次: layer1 + layer2
        第二次 (if high pressure): sleep 5s → layer1 again + layer2 again
        """
        if aggressiveness < 0.6 or (ops_filter is not None and "ws" not in ops_filter):
            return  # 压力不够或禁用了 WS 清理

        time.sleep(5)

        # 系统级再来一遍
        self._layer1_system(aggressiveness, ops_filter)

        # 进程级再来一遍 (只选高 ROI 的)
        for s in snaps:
            theta = learner.thompson_score(s.name)
            if theta > 0.7:
                self._trim_process(s, learner)

    # ── 统一入口 ──

    def optimize(self, snaps, learner, mode="normal", operations=None, score_fn=None):
        """
        统一优化入口

        mode: quick|normal|deep|full
            quick  = layer2(probe only) + standby_low
            normal = layer1(mild) + layer2(full)
            deep   = layer1(aggressive) + layer2 + layer3
            full   = layer1(all) + layer2 + layer3 + extra standby

        operations: 可选列表，限制允许的清理操作，如 ["ws","standby","modified","filecache"]
        """
        mem = winapi.get_memory_status()
        agg = self.judger.update_pressure(mem["pct"]) if mem else 0.5
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
                time.sleep(3)
                self.clean_standby()
                self._layer3_deep(snaps, learner, agg, ops_filter)
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
            "combine": 0, "ws_trim": 0, "probe": 0,
            "skipped": 0, "failed_feedback": 0,
            "freed_bytes": 0,
        }
