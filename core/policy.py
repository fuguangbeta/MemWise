"""
PolicyVoter — 五树投票决策引擎
替代阈值判断，综合 Kalman/记忆/因果/时机 投票
"""
import math
import time

class PolicyVoter:
    """五树投票框架: 收益/代价/时机/紧迫/反事实 · 在线权重学习
    should_trim 启用树 1(收益)/2(压力)/5(反事实)；should_probe 用树 1(信息价值)/2(记忆空缺)/3(资源约束)/5(因果好奇)
    树 4(紧迫) 预留空实现（加权恒 0，不影响决策）"""
    
    def __init__(self):
        self._tree_weights = [1.0] * 5  # 五棵树初始等权重（normal 组，兼容旧引用）
        self._mode_weights = {"normal": [1.0] * 5}  # 模式隔离权重组（2026-08-16 用户定稿：
        # 树权重=各决策树预测可靠度，与模式力度强相关——deep/full 激进时压力树权重变化大，
        # 跨模式共享会使 A 模式的权重学习污染 B 模式决策；场景维度与树权重弱相关，4 组即可）
        self.current_mode = "normal"

    def set_mode(self, mode):
        """切换当前模式（权重组懒创建，模式间零污染）"""
        if mode not in ("quick", "normal", "deep", "full"):
            mode = "normal"
        self.current_mode = mode
        self._mode_weights.setdefault(mode, [1.0] * 5)

    def _weights(self):
        return self._mode_weights.setdefault(self.current_mode, [1.0] * 5)

    def _apply_weights(self, scores):
        """将权重应用于各树得分（加权求和，保持总分范围不变）"""
        total_w = sum(abs(w) for w in self._weights())
        if total_w == 0:
            return scores
        norm = 5.0 / total_w  # 归一化到 [0, 5]
        return [s * self._weights()[i] * norm for i, s in enumerate(scores)]

    def update_weights_per_trim(self, scores, success):
        """每进程粒度的在线权重学习——直接调节当前模式的各树权重（有界 ±2，慢速 0.05 收敛）。
        正贡献+成功 / 负贡献+失败 → 该树权重上升（预测可靠）；
        正贡献+失败 / 负贡献+成功 → 该树权重下降（预测被证伪）。
        权重可为负：负权重树的贡献在总分中反向计入，使学习真正影响决策。"""
        direction = 1.0 if success else -1.0
        w = self._weights()
        for i, contrib in enumerate(scores):
            if contrib == 0:
                continue
            delta = direction * (1.0 if contrib > 0 else -1.0) * 0.05
            w[i] = max(-2.0, min(2.0, w[i] + delta))

    def should_trim(self, name, ws, state, learner, threshold=0):
        """是否清理此进程 → (True/False, 理由, 各树贡献)
        threshold: 投票通过阈值（模式梯度：normal=0 标准 / deep=-1 略宽 / full=-2 大幅放宽但保留
        最低价值底线——全负分仍拒绝，防完全无意义清理）"""
        scores = [0] * 5  # 每棵树独立计分
        reasons = []
        k_freed = 0.0

        # 树1: 预期收益 (Kalman，含上下文修正)
        p = learner.profiles.get(name.lower())
        if p:
            k_freed, k_cost = p.kalman.predict()
            if hasattr(learner, 'ctx_correction'):
                f_corr, c_corr = learner.ctx_correction(
                    state.get("mem_pct", 50), is_fg=state.get("is_fg", False),
                    hour=time.localtime().tm_hour)
                k_freed = k_freed * max(0.3, min(3.0, f_corr))
                k_cost  = k_cost  * max(0.3, min(3.0, c_corr))
            if k_freed > 50 << 20:
                scores[0] += 2
                reasons.append("收益高")
            elif k_freed > 10 << 20:
                scores[0] += 1
                reasons.append("收益中")

        # 树2: 内存压力与趋势
        mem_pct = state.get("mem_pct", 50)
        mem_trend = state.get("mem_trend", 0)
        if mem_pct > 80:
            scores[1] += 2
            reasons.append("内存紧张")
        elif mem_pct > 65:
            scores[1] += 1
        elif mem_pct < 30:
            scores[1] -= 1
            reasons.append("内存充足")
        if mem_trend > 0.03:
            scores[1] += 1
            reasons.append("内存上升中")

        # 树5: 反事实优势 — 与其他有画像进程的平均预期释放对比（排除自身，防均值被自己抬高）
        # list() 快照迭代（2026-09-06 审查 F2）：can_trim 在守护线程调用，手动优化线程可
        # 并发增键——有投票段 try 兜底但会误拒该进程，快照根除
        if p and k_freed > 0:
            peers = [q.kalman.x_freed for q in list(learner.profiles.values())
                     if q is not p and q.kalman.x_freed > 0]
            if peers:
                adv_mb = (k_freed - sum(peers) / len(peers)) / (1 << 20)
                if adv_mb > 50:
                    scores[4] += 2
                    reasons.append(f"预测优势{adv_mb:.0f}MB")
                elif adv_mb > 20:
                    scores[4] += 1

        # 加权求和决策：权重由 update_weights_per_trim 在线学习（可为负），使学习真正影响投票；
        # threshold 由模式梯度传入（normal 0 / deep -1 / full -2）
        weighted = self._apply_weights(scores)
        return sum(weighted) >= threshold, "; ".join(reasons[:3]) if reasons else "", list(scores)

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
        
        # 树3: 资源约束 (内存压力大时少probe)（框架预留编号：树1/2 为信息价值与记忆空缺）
        mem_pct = state.get("mem_pct", 50)
        if mem_pct > 80:
            score -= 1
            reasons.append("内存紧张,少试探")
        elif mem_pct < 50:
            score += 1
            reasons.append("内存充足,可探索")
        
        # 树5: 因果好奇 (近期未被评估的进程值得再探)
        pt = state.get("probe_last_time", {})
        last_p = pt.get(name.lower(), 0)
        if last_p == 0 or time.time() - last_p > 1800:
            score += 1
            reasons.append("未充分评估")
        
        return score >= 1, "; ".join(reasons[:3]) if reasons else ""
