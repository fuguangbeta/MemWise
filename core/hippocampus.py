"""
EpisodeMemory — 情景记忆
记住每次清理/试探的完整上下文，支持相似性检索
"""
import time
import math
from collections import deque

class EpisodeMemory:
    """情景记忆：存储和检索历史清理/试探情景"""
    
    def __init__(self, maxlen=2000):
        self.episodes = deque(maxlen=maxlen)
        self._name_index = {}  # name → [episode_indices]
    
    def store(self, name, mem_pct, ws, is_fg, action, ok, freed, pf_delta,
              trimmed_cnt=0, total_att=0, agg=0.0):
        """保存一次情景
        args: 进程信息 + 系统状态 + 行动 + 结果
        """
        now = time.localtime()
        episode = {
            "ts": time.time(),
            "hour": now.tm_hour,
            "dow": now.tm_wday,
            "name": name,
            "mem_pct": mem_pct,
            "ws": ws,
            "fg": is_fg,
            "action": action,      # "trim", "probe", "priority"
            "ok": ok,
            "freed": freed,
            "pf": pf_delta,
            "trimmed": trimmed_cnt,
            "total": total_att,
            "agg": agg,
        }
        idx = len(self.episodes)
        self.episodes.append(episode)
        # 按名称索引
        if name not in self._name_index:
            self._name_index[name] = deque(maxlen=100)
        self._name_index[name].append(idx)
    
    def retrieve(self, name=None, mem_pct=None, top_k=5):
        """检索最相关情景
        name: 指定进程名 (None=所有)
        mem_pct: 当前内存%, 用于相似度加权
        returns: [(similarity, episode), ...]
        """
        candidates = []
        
        if name and name in self._name_index:
            # 优先同名进程
            indices = list(self._name_index[name])
            candidates = [self.episodes[i] for i in indices if i < len(self.episodes)]
        
        if len(candidates) < top_k:
            # 不足时补充最近情景
            extra = [e for e in self.episodes if e["name"] != name]
            candidates.extend(extra[-(top_k * 2):])
        
        if not candidates:
            return []
        
        # 相似度评分: 综合 mem_pct 差 + 时间衰减 + 名称匹配
        scored = []
        for ep in candidates[:top_k * 3]:
            sim = 0.5  # 基础分
            if mem_pct is not None:
                mem_diff = abs(ep["mem_pct"] - mem_pct)
                sim += 0.3 * max(0, 1 - mem_diff / 30)
            if name and ep["name"] == name:
                sim += 0.4  # 同名进程加成
            # 时间衰减: 越近越相关
            hours_ago = (time.time() - ep["ts"]) / 3600
            sim += 0.2 * max(0, 1 - hours_ago / 24)
            scored.append((sim, ep))
        
        scored.sort(key=lambda x: -x[0])
        return scored[:top_k]
    
    def success_rate(self, name, mem_pct=None, hours=24):
        """返回同名进程在指定时间内的成功率"""
        cutoff = time.time() - hours * 3600
        relevant = [e for e in self.episodes
                   if e["name"] == name and e["ts"] > cutoff]
        if not relevant:
            return None
        ok_count = sum(1 for e in relevant if e["ok"])
        return ok_count / len(relevant)
    
    def to_dict(self):
        return {
            "episodes": list(self.episodes),
        }
    
    @classmethod
    def from_dict(cls, d):
        m = cls()
        episodes = d.get("episodes", [])
        for ep in episodes:
            m.episodes.append(ep)
            name = ep.get("name")
            if name:
                if name not in m._name_index:
                    m._name_index[name] = deque(maxlen=100)
                m._name_index[name].append(len(m.episodes) - 1)
        return m
