"""
MetaCognition — 元认知层
监控整个认知系统，自动发现并修复问题
"""
import time

class MetaCognition:
    """两维监控: 概念漂移 / 探索覆盖"""
    
    def __init__(self, learner):
        self.learner = learner
    
    def tick(self):
        """每 tick 调用（状态全部取自 learner 画像，无需外部统计输入）"""
        now = time.time()
        findings = []
        
        # ── 2. 概念漂移: EWMA快慢速比 ──
        # dict() 快照迭代：手动优化线程可并发增键，直接迭代会 RuntimeError（2026-08-30，
        # 与 learner.pop_info / engine._compute_eris 同款防护）
        drifted = []
        for name, p in dict(self.learner.profiles).items():
            # P05：total_samples 是 20 长滑动窗，永远到不了 30；改用累计 samples_total。
            # 同一漂移只复位一次/小时，防每 tick 反复削 α/β（复位本身不改变 EWMA 比值）。
            if p.samples_total > 30 and time.time() - p.last_drift_at > 3600:
                fast = p.gain_ewma_fast
                slow = p.gain_ewma_slow
                if slow > 0 and (fast > slow * 4.0 or fast < slow * 0.2):
                    drifted.append(name)
                    p.last_drift_at = time.time()
                    p.kalman.q = 2.0
                    p.alpha = max(2, p.alpha * 0.7)
                    p.beta = max(1, p.beta * 0.7)
                    p._theta_dirty = True
        
        if drifted:
            findings.append(f"漂移: {len(drifted)}个进程({','.join(drifted[:3])}...)已复位")
        
        # ── 3. 探索覆盖 ──
        # dict() 快照迭代（2026-09-06 审查 F2）：与上方漂移循环同款防护——直接迭代
        # values() 会因并发增键 RuntimeError 击落 meta.tick
        total = max(len(self.learner.profiles), 1)
        never_tried = sum(1 for p in dict(self.learner.profiles).values()
                         if p.last_feedback_time == 0)
        never_ratio = never_tried / total
        
        if never_ratio > 0.4:
            if never_tried != getattr(self, '_last_never_tried', -1):
                findings.append(f"探索: {never_tried}/{total}({never_ratio:.0%}) 从未试探，加速探索")
                self._last_never_tried = never_tried

        return findings  # 返回列表，调用端逐条输出日志
    
