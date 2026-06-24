"""
PARES Cleaner — 3 层清理引擎
Layer 1: 系统级 (Standby/Modified/FileCache/Combine)
Layer 2: 进程级 (EmptyWorkingSet with Thompson/ROI/Probe)
Layer 3: 深度聚合 (高压力时重复执行)
"""
import time
from . import winapi


class PareCleaner:
    """PARES 清理器 — 3 层引擎"""

    def __init__(self, judger):
        self.judger = judger
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

    def _layer1_system(self, aggressiveness):
        """系统级清理 — 根据 aggressiveness 选择执行哪些操作"""
        ops = []

        # 内存压力越高，清理越多（阈值下调，更积极）
        if aggressiveness > 0.05:
            ops.append(("standby_low", self.clean_standby_low))
        if aggressiveness > 0.2:
            ops.append(("standby", self.clean_standby))
        if aggressiveness > 0.25:
            ops.append(("deep_standby", self.clean_deep_standby))
        if aggressiveness > 0.3:
            ops.append(("modified", self.clean_modified_pages))
        if aggressiveness > 0.5:
            ops.append(("combine", self.clean_combine_lists))
        if aggressiveness > 0.5:
            ops.append(("filecache", self.clear_file_cache))

        results = {}
        for name, fn in ops:
            results[name] = fn()
        return results

    # ── Layer 2: 进程级清理 ──

    def _probe_process(self, snap, learner):
        """微型试探 — 对不确定进程做轻量测试 (1s 等待)"""
        pid, name = snap.pid, snap.name
        ws_before = snap.ws
        if not winapi.empty_ws(pid):
            return False, 0, 0
        time.sleep(1)
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
        """完整清理一个进程 (3s 等待 + 反馈验证)"""
        pid, name = snap.pid, snap.name
        ws_before = snap.ws
        self.judger.record_pf_before(pid, snap.pf)
        if not winapi.empty_ws(pid):
            self.stats["skipped"] += 1
            return False, 0, 0, "API失败"
        time.sleep(3)
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

    def _layer2_process(self, snaps, learner):
        """进程级清理 — Thompson + ROI 选进程"""
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

        # 先执行 Probe (微型试探)
        probe_results = []
        for s in probe_list[:10]:  # 每轮最多 10 个 probe
            ok, freed, pf_delta = self._probe_process(s, learner)
            probe_results.append((s, ok, freed))

        # 再执行完整清理
        results = []
        for s in candidates:
            ok, freed, pf_delta, reason = self._trim_process(s, learner)
            results.append((s, ok, freed, reason))

        return results, probe_results

    # ── Layer 3: 深度聚合 ──

    def _layer3_deep(self, snaps, learner, aggressiveness):
        """
        深度模式 — 高压力时重复执行
        第一次: layer1 + layer2
        第二次 (if high pressure): sleep 5s → layer1 again + layer2 again
        """
        if aggressiveness < 0.6:
            return  # 压力不够，不做深度

        time.sleep(5)

        # 系统级再来一遍
        self._layer1_system(aggressiveness)

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
        """
        # 1. 获取当前 aggressiveness
        mem = winapi.get_memory_status()
        agg = self.judger.update_pressure(mem["pct"]) if mem else 0.5

        if mode == "quick":
            # Quick: 系统低负载清理 + Probe 试探
            if agg > 0.1:
                self._layer1_system(min(agg, 0.3))
            l2_results, probe_results = self._layer2_process(snaps, learner)
            return {
                "mode": mode,
                "aggressiveness": agg,
                "layer2": l2_results,
                "probe": probe_results,
            }

        elif mode == "normal":
            # Normal: layer1(中等) + layer2(完整)
            self._layer1_system(agg)
            l2_results, probe_results = self._layer2_process(snaps, learner)
            return {
                "mode": mode,
                "aggressiveness": agg,
                "layer2": l2_results,
                "probe": probe_results,
            }

        elif mode == "deep":
            # Deep: layer1 + layer2 + layer3(深度)
            self._layer1_system(agg)
            l2_results, probe_results = self._layer2_process(snaps, learner)
            self._layer3_deep(snaps, learner, agg)
            return {
                "mode": mode,
                "aggressiveness": agg,
                "layer2": l2_results,
                "probe": probe_results,
            }

        elif mode == "full":
            # Full: layer1(全开) + layer2 + 额外 standby + layer3
            self._layer1_system(max(agg, 0.7))
            l2_results, probe_results = self._layer2_process(snaps, learner)
            time.sleep(3)
            self.clean_standby()
            self._layer3_deep(snaps, learner, agg)
            # 第一遍完成后再做一轮 standby
            self.clean_standby_low()
            return {
                "mode": mode,
                "aggressiveness": agg,
                "layer2": l2_results,
                "probe": probe_results,
            }

        else:
            # Fallback
            self._layer1_system(agg)
            l2_results, probe_results = self._layer2_process(snaps, learner)
            return {
                "mode": mode,
                "aggressiveness": agg,
                "layer2": l2_results,
                "probe": probe_results,
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
