"""
MetaCognition — 元认知层
监控整个认知系统，自动发现并修复问题
"""
import time
import math
from collections import deque

class MetaCognition:
    """四维监控: 校准度 / 概念漂移 / 探索覆盖 / 后悔度"""
    
    def __init__(self, learner):
        self.learner = learner
        self.history = deque(maxlen=200)  # 每tick记录
        self._last_adjust = 0
        self._theta_bias = 0.0  # θ整体偏移修正
        self._last_sys_ok = 0  # 系统操作监控上次状态
    
    def tick(self, stats):
        """每 tick 调用"""
        now = time.time()
        self.history.append(stats)
        
        # 每 30 秒执行一次完整检查
        if now - self._last_adjust < 30:
            return
        self._last_adjust = now
        
        findings = []
        
        # ── 1. 校准度: 预测 vs 实际 ──
        if len(self.history) >= 5:
            # 从 learner 获取所有已清理进程的平均预测误差
            errors = []
            for name, p in self.learner.profiles.items():
                if p.clean_count >= 3 and p.gain_ewma > 0:
                    kalman_freed, _ = p.kalman.predict()
                    actual = p.gain_ewma
                    if actual > 0:
                        err = abs(kalman_freed - actual) / actual
                        errors.append(err)
            
            if errors:
                avg_err = sum(errors) / len(errors)
                if avg_err > 0.5:
                    count = 0
                    for p in self.learner.profiles.values():
                        if hasattr(p, 'kalman') and p.gain_ewma > 0:
                            p.kalman.q = min(5.0, p.kalman.q * 1.2)
                            p.kalman.p_freed = min(200, p.kalman.p_freed * 1.2)
                            p.kalman.x_freed = p.gain_ewma
                            count += 1
                    step = min(0.04, avg_err * 0.03)
                    self._theta_bias = max(-0.2, self._theta_bias - step)
                    findings.append(f"\u6821\u51c6: \u504f\u5dee{avg_err:.0%}>50%, \u5361\u5c14\u66fc\u91cd\u7f6e{count}\u4e2a, \u964d\u4f4e\u03b8\u7f6e\u4fe1")
                elif avg_err < 0.15:
                    for p in self.learner.profiles.values():
                        if hasattr(p, 'kalman') and p.kalman.q > 0.02:
                            p.kalman.q = max(0.02, p.kalman.q * 0.9)
                    step = min(0.03, (0.15 - avg_err) * 0.1)
                    self._theta_bias = min(0.2, self._theta_bias + step)
                    findings.append(f"\u6821\u51c6: \u504f\u5dee{avg_err:.0%}<15%, \u5361\u5c14\u66fc\u7cbe\u51c6, \u5956\u52b1\u03b8\u7f6e\u4fe1")
        
        # ── 2. 概念漂移: EWMA快慢速比 ──
        drifted = []
        for name, p in self.learner.profiles.items():
            if p.total_samples > 30:
                fast = p.gain_ewma_fast
                slow = p.gain_ewma_slow
                if slow > 0 and (fast > slow * 4.0 or fast < slow * 0.2):
                    drifted.append(name)
                    # 复位: 增大过程噪声, 让Kalman快速适应
                    p.kalman.q = 2.0
                    # Halve Beta confidence (only 20% of profiles max)
                    p.alpha = max(2, p.alpha * 0.7)
                    p.beta = max(1, p.beta * 0.7)
        
        if drifted:
            findings.append(f"漂移: {len(drifted)}个进程({','.join(drifted[:3])}...)已复位")
        
        # ── 3. 探索覆盖 ──
        total = max(len(self.learner.profiles), 1)
        never_tried = sum(1 for p in self.learner.profiles.values()
                         if p.last_feedback_time == 0)
        never_ratio = never_tried / total
        
        if never_ratio > 0.4:
            if never_tried != getattr(self, '_last_never_tried', -1):
                findings.append(f"探索: {never_tried}/{total}({never_ratio:.0%})从未试探,提高好奇心")
                self._last_never_tried = never_tried
            # 给所有未试探进程设置好奇心标记
            for p in self.learner.profiles.values():
                if p.last_feedback_time == 0:
                    p._curiosity_boost = 2.0
                    p.kalman.p_freed = min(p.kalman.p_freed, 50.0)
        
        # ── 4. 后悔度: 反事实优势累积 ──
        if hasattr(self.learner, 'causal') and self.learner.causal:
            pair_count = len(self.learner.causal._pairs)
            if pair_count > 20 and pair_count != getattr(self, '_last_pair_count', 0):
                findings.append(f"因果: 已学习{pair_count}对进程关系")
                self._last_pair_count = pair_count
        
        # ── 5. 系统操作监控: standby/modified/filecache ──
        cleaner = getattr(self.learner, '_cleaner_ref', None)
        if cleaner:
            s = cleaner.summary()
            sys_ok = s.get('standby', 0) + s.get('modified', 0) + s.get('filecache', 0)
            if sys_ok > 0 and hasattr(self, '_last_sys_ok') and self._last_sys_ok == 0:
                findings.append(f"系统清理已生效: 待机缓存={s['standby']} 已修改页={s['modified']} 文件缓存={s['filecache']}")
            self._last_sys_ok = sys_ok
        
        # ── 6. 学习率自校准 (每30s一次) ──
        self.learner.self_check()
        
        if findings:
            # 报告给 info_msgs
            for f in findings:
                self.learner._info_msgs.append(f"[元认知] {f}")
    
    def adjust_theta(self, base_theta):
        """对θ施加元认知校准"""
        return max(0.01, min(0.99, base_theta + self._theta_bias))
