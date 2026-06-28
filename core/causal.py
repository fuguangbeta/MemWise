"""
CausalGraph — 因果图
从自然实验中学习清理决策的因果关系
"""
import time

class CausalGraph:
    """因果图：追踪"清理A vs 清理B"的相对效果"""
    
    def __init__(self):
        # {(proc_a, proc_b): [(timestamp, mem_pct, freed_a_delta)]}
        self._pairs = {}
    
    def record(self, cleaned_name, freed, mem_pct, candidates):
        """
        记录一次清理事件
        cleaned_name: 被清理的进程
        freed: 释放量(bytes)
        mem_pct: 当前内存%
        candidates: 本次所有候选进程名
        """
        now = time.time()
        for other in candidates:
            if other == cleaned_name:
                continue
            key = (cleaned_name, other)
            if key not in self._pairs:
                self._pairs[key] = []
            self._pairs[key].append((now, mem_pct, freed))
            # 最多保留50条做滑动窗口
            if len(self._pairs[key]) > 50:
                self._pairs[key] = self._pairs[key][-50:]
    
    def advantage(self, proc_a, proc_b, mem_pct=None, hours=24):
        """
        反事实查询: 清理A比清理B好多少(MB)?
        正数=清理A更好, 负数=清理B更好
        """
        key = (proc_a, proc_b)
        if key not in self._pairs:
            return 0
        
        cutoff = time.time() - hours * 3600
        relevant = [r for r in self._pairs[key] if r[0] > cutoff]
        
        if not relevant:
            return 0
        
        if mem_pct is not None:
            # 加权: 越接近当前内存%的记录权重越高
            total_w = 0
            weighted = 0
            for ts, mp, fr in relevant:
                w = max(0.01, 1.0 - abs(mp - mem_pct) / 30.0)
                weighted += fr * w
                total_w += w
            if total_w > 0:
                avg = weighted / total_w
            else:
                avg = sum(r[2] for r in relevant) / len(relevant)
        else:
            avg = sum(r[2] for r in relevant) / len(relevant)
        
        return avg
    
    def best_alternative(self, cleaned_name, candidates, mem_pct=None):
        """返回(最佳替代进程, 优势MB) — 如果选另一个会多释放多少"""
        best = None
        best_adv = 0
        for alt in candidates:
            if alt == cleaned_name:
                continue
            adv = self.advantage(alt, cleaned_name, mem_pct)
            if adv > best_adv:
                best_adv = adv
                best = alt
        return best, best_adv
    
    def to_dict(self):
        # 只保留可用数据
        return {"pairs": {str(k): v for k, v in self._pairs.items()}}
    
    @classmethod
    def from_dict(cls, d):
        g = cls()
        for key_str, records in d.get("pairs", {}).items():
            # key_str = "('proc_a', 'proc_b')"
            try:
                key = eval(key_str)
                if isinstance(key, tuple) and len(key) == 2:
                    g._pairs[key] = records
            except Exception as e:
                import sys; print(f"[MemWise] 推论加载损坏记录: {e}", file=sys.stderr)
        return g
