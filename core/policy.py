"""
PolicyVoter — 五树投票决策引擎
替代阈值判断，综合 Kalman/记忆/因果/时机 投票
"""
import time

from .winapi import memory_scale

# ── 树 1 / 树 5 的「显著收益」绝对线（分类 B：语义与物理内存规模相关，见 cleaner 同区注释）──
# 2026-10-15 实验：固定绝对值下，同一相对表现的判定会随机器规模漂移（本机 S=1 行为不变）。
# P21：按 S=物理内存/16GiB 缩放——64GB 机上 50MB 仅 0.08%，不缩放的 +2 几乎对所有人成立，
# 投票失去区分度；S=1（本机 16GB 档）时逐位等于旧常量。
_S = memory_scale()
TREE1_HIGH = int((50 << 20) * _S)      # 树1：预期释放 > 此值 → +2（收益高）
TREE1_MID = int((10 << 20) * _S)       # 树1：> 此值 → +1（收益中）
TREE5_ADV_HIGH_MB = max(1, int(round(50 * _S)))     # 树5：相对同类均值优势 > 此 MB → +2
TREE5_ADV_MID_MB = max(1, int(round(20 * _S)))      # 树5：> 此 MB → +1

class PolicyVoter:
    """五树投票框架：收益/代价/时机/紧迫/反事实（**实际启用 3 棵树**）

    - should_trim：树 1(收益)/2(压力)/5(反事实) 计分，**等权求和**后与模式阈值比较
      （normal 0 / deep -1 / full -2）。
    - should_probe：信息价值/记忆空缺/资源约束/因果好奇四路计分。
    - 树 3(时机)/树 4(紧迫)：**预留**——scores[2]/scores[3] 从不赋值（恒 0），不影响决策。
      命名与注释按此口径，勿再宣称「五树全部生效」。
    - **2026-11-10 移除在线权重学习**：417 画像实测，学习后 normal 通过率 0%、full 92% 但
      只覆盖 26% 预测释放（高收益进程被负权重否决，低收益通过）；等权下 normal 通过 29%、
      覆盖 93% 预测释放。权重学习从未产生正收益，反而把投票学成反向选择，故整体弃用。
    """
    
    def __init__(self):
        self.current_mode = "normal"

    def set_mode(self, mode):
        """切换当前模式（仅影响日志与阈值语义，无权重状态）"""
        if mode not in ("quick", "normal", "deep", "full"):
            mode = "normal"
        self.current_mode = mode

    @staticmethod
    def _emergency_of(state):
        """用户设定的紧急触发阈值（缺省 80，非法回退）——树阈值与用户配置同口径
        （2026-09-11 审查 F21：原树2/树3 硬编码 80/65，与可配置的紧急阈值矛盾）"""
        try:
            v = float(state.get("emergency", 80))
            return v if v > 0 else 80.0
        except (TypeError, ValueError):
            return 80.0

    def should_trim(self, name, ws, state, learner, threshold=0):
        """是否清理此进程 → (True/False, 理由, 各树贡献)
        threshold: 投票通过阈值（模式梯度：normal=0 标准 / deep=-1 略宽 / full=-2 大幅放宽但保留
        最低价值底线——全负分仍拒绝，防完全无意义清理）"""
        scores = [0] * 5  # 每棵树独立计分
        reasons = []
        k_freed = 0.0

        # 树1: 预期收益（Kalman 原始预测；ctx 修正层 2026-11-08 移除——实测 MAE 负收益）
        p = learner.profiles.get(name.lower())
        if p:
            k_freed, k_cost = p.kalman.predict()
            k_freed = p.effective_freed   # 2026-11-11：树1 用可靠性加权值（连续失败即折扣）
            if k_freed > TREE1_HIGH:
                scores[0] += 2
                reasons.append("收益高")
            elif k_freed > TREE1_MID:
                scores[0] += 1
                reasons.append("收益中")

        # 树2: 内存压力与趋势
        # 阈值随用户设定的紧急阈值（2026-09-11 审查 F21）：达到阈值=紧张(+2)；接近阈值
        # （阈值×80%，默认 64，与原 65 基本一致）=偏紧(+1)；<30% 充足(-1)
        mem_pct = state.get("mem_pct", 50)
        mem_trend = state.get("mem_trend", 0)
        _em = self._emergency_of(state)
        if mem_pct >= _em:
            scores[1] += 2
            reasons.append("内存紧张")
        elif mem_pct >= _em * 0.8:
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
            peers = [q.effective_freed for q in list(learner.profiles.values())
                     if q is not p and q.effective_freed > 0]
            if peers:
                adv_mb = (k_freed - sum(peers) / len(peers)) / (1 << 20)
                if adv_mb > TREE5_ADV_HIGH_MB:
                    scores[4] += 2
                    reasons.append(f"预测优势{adv_mb:.0f}MB")
                elif adv_mb > TREE5_ADV_MID_MB:
                    scores[4] += 1

        # 等权求和（2026-11-10）：三棵启用树直接相加，与旧「全 1 权重」逐位一致；
        # threshold 由模式梯度传入（normal 0 / deep -1 / full -2）
        return sum(scores) >= threshold, "; ".join(reasons[:3]) if reasons else "", list(scores)

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
        if mem_pct >= self._emergency_of(state):
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
