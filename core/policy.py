"""
PolicyVoter — 五树投票决策引擎
替代阈值判断，综合 Kalman/记忆/因果/时机 投票
"""
import math

class PolicyVoter:
    """五树投票: 收益/代价/时机/紧迫/反事实"""
    
    def should_trim(self, name, ws, state, learner):
        """是否清理此进程 → (True/False, 理由)"""
        score = 0
        reasons = []
        
        # 树1: 预期收益 (Kalman)
        p = learner.profiles.get(name.lower())
        if p:
            k_freed, k_cost = p.kalman.predict()
            if k_freed > 50 << 20:
                score += 2
                reasons.append("收益高")
            elif k_freed > 10 << 20:
                score += 1
                reasons.append("收益中")
            else:
                score -= 1
                reasons.append("收益低")
            
            # 树2: 历史成功率 (情景记忆)
            sr = learner.memory.success_rate(name.lower(), state.get("mem_pct"), hours=24)
            if sr is not None:
                if sr > 0.6:
                    score += 2
                    reasons.append(f"历史成功率{sr:.0%}")
                elif sr > 0.3:
                    score += 1
                else:
                    score -= 1
                    reasons.append(f"历史成功率仅{sr:.0%}")
        else:
            score += 0  # 无数据, 中性
        
        # 树3: 时机 (Temporal)
        if hasattr(p, 'temporal'):
            if not p.temporal.is_active_hour():
                score -= 1
                reasons.append("非活跃时段")
            else:
                score += 1
                reasons.append("活跃时段")
        
        # 树4: 紧迫度 (内存压力)
        mem_pct = state.get("mem_pct", 50)
        mem_trend = state.get("mem_trend", 0)
        if mem_pct > 80:
            score += 2
            reasons.append("内存紧张")
        elif mem_pct > 65:
            score += 1
        elif mem_pct < 40:
            score -= 1
            reasons.append("内存充足")
        if mem_trend > 0.03:
            score += 1
            reasons.append("内存上升中")
        
        # 树5: 反事实优势 (因果图)
        adv = learner.causal_compare(name, state.get("candidates", []), mem_pct)
        if adv > 0:
            score += 1
            reasons.append(f"比替代方案好{adv/(1<<20):.0f}MB")
        elif adv < 0:
            score -= 1
            reasons.append(f"不如替代方案")
        
        return score >= 1, "; ".join(reasons[:3]) if reasons else ""
    
    def should_probe(self, name, ws, state, learner):
        """是否试探此进程 → (True/False, 理由)"""
        score = 0
        reasons = []
        
        p = learner.profiles.get(name.lower())
        
        # 树1: 信息价值 (不确定性越高越值得探)
        if p:
            uncertainty = 1.0 - p.kalman.confidence
            if uncertainty > 0.5:
                score += 2
                reasons.append("高不确定性")
            elif uncertainty > 0.3:
                score += 1
            else:
                score -= 1
                reasons.append("已充分了解")
            
            # 树2: 记忆空缺 (从未被试探过)
            if p.last_feedback_time == 0:
                score += 2
                reasons.append("从未试探")
        else:
            score += 1
            reasons.append("新进程")
        
        # 树3: 时机 (非活跃时段不浪费 probe)
        if hasattr(p, 'temporal') and p.temporal:
            if not p.temporal.is_active_hour():
                score -= 2
                reasons.append("非活跃时段")
        
        # 树4: 资源约束 (内存压力大时少probe)
        mem_pct = state.get("mem_pct", 50)
        if mem_pct > 80:
            score -= 1
            reasons.append("内存紧张,少试探")
        elif mem_pct < 50:
            score += 1
            reasons.append("内存充足,可探索")
        
        # 树5: 因果好奇 (从未作为反事实被评估过)
        all_candidates = state.get("candidates", [])
        if name.lower() not in [c.lower() for c in all_candidates[:5]]:
            score += 1
            reasons.append("未充分评估")
        
        return score >= 1, "; ".join(reasons[:3]) if reasons else ""
