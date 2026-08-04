"""
MetaCognition — 元认知层
监控整个认知系统，自动发现并修复问题
"""
import time
import math

class MetaCognition:
    """两维监控: 概念漂移 / 探索覆盖"""
    
    def __init__(self, learner):
        self.learner = learner
    
    def tick(self, stats):
        """每 tick 调用"""
        now = time.time()
        findings = []
        
        # ── 2. 概念漂移: EWMA快慢速比 ──
        drifted = []
        for name, p in self.learner.profiles.items():
            if p.total_samples > 30:
                fast = p.gain_ewma_fast
                slow = p.gain_ewma_slow
                if slow > 0 and (fast > slow * 4.0 or fast < slow * 0.2):
                    drifted.append(name)
                    p.kalman.q = 2.0
                    p.alpha = max(2, p.alpha * 0.7)
                    p.beta = max(1, p.beta * 0.7)
                    p._theta_dirty = True
        
        if drifted:
            findings.append(f"漂移: {len(drifted)}个进程({','.join(drifted[:3])}...)已复位")
        
        # ── 3. 探索覆盖 ──
        total = max(len(self.learner.profiles), 1)
        never_tried = sum(1 for p in self.learner.profiles.values()
                         if p.last_feedback_time == 0)
        never_ratio = never_tried / total
        
        if never_ratio > 0.4:
            if never_tried != getattr(self, '_last_never_tried', -1):
                findings.append(f"探索: {never_tried}/{total}（{never_ratio:.0%}）从未试探，加速探索")
                self._last_never_tried = never_tried

        return findings  # 返回列表，调用端逐条输出日志
    
