"""
PARES Learner — Predictive Adaptive Reinforcement Engine
Thompson Sampling + 3x EWMA + Z-score + 趋势线
"""
import json, os, time, math, random
from .kalman import KalmanProfile
from .temporal import TemporalProfile
from .hippocampus import EpisodeMemory
from .prior import HierarchicalPrior
from .causal import CausalGraph
from .policy import PolicyVoter
from .meta import MetaCognition
from collections import deque

WINDOW = 20  # 趋势窗口大小
EWMA_LAMBDA = 0.5  # EWMA 衰减因子 (高=更快适应新数据)
Z_SCORE_THRESHOLD = 3.0  # Z-score 异常阈值
MIN_SAMPLES = 3  # 最小样本数 (更快对新进程做出决策)
TREND_SAMPLES = 3  # 趋势线使用的采样数（原6。缩短窗口让预判式清理更快响应）
BETA_DECAY_RATE = 0.002  # Beta 分布衰减率（每次 feed 向先验收缩）
# 1. 学习率↑10倍：从0.03→0.3（sign-based更新可承受更大的基础lr）
CTX_LR_BASE = 0.5  # 上下文权重基础学习率（原0.3，再↑让上下文修正更快见效）

SYSTEM_CORE = {
    "system", "system idle process", "registry", "smss", "csrss", "wininit",
    "winlogon", "services", "lsass", "svchost", "dwm", "fontdrvhost",
    "sihost", "taskhostw", "textinputhost", "ctfmon", "explorer",
    "searchhost", "searchindexer", "securityhealthservice",
    "securityhealthsystray", "defender", "msmpeng", "nissrv",
    "conhost", "dllhost", "shellexperiencehost", "startmenuexperiencehost",
    "runtimebroker", "backgroundtaskhost", "wmiprvse", "wudfhost",
    "audiodg", "spoolsv", "mpdefendercoreservice",
}

class Profile:
    """进程画像 — 每个进程一个"""
    __slots__ = ("name", "alpha", "beta", "_theta_cache", "_theta_dirty", "ws_deque",
                 "gain_ewma", "cost_ewma", "vol_ewma",
                 "gain_ewma_fast", "gain_ewma_slow",
                 "cost_ewma_fast", "cost_ewma_slow",
                 "ws_ewma_mu", "ws_ewma_sigma",
                 "last_ok", "ok_cnt", "fail_cnt",
                 "last_seen", "last_ws",
                 "probe_ok", "probe_fail",
                 "leak_suspect", "leak_tick_count",
                 "clean_count", "refill_ewma",
                 "_ctx_weights",
                 "_grad_buffer", "_grad_count",
                 "kalman", "temporal", "_curiosity_boost", "last_feedback_time")

    def __init__(self, name):
        self.name = name
        # Thompson Sampling — Beta(α, β) (先验偏向可清理)
        self.alpha = 2
        self.beta = 1
        self._theta_cache = None   # Thompson θ 缓存，同一 tick 内复用
        self._theta_dirty = True
        # 趋势窗口 (WS 用于回归)
        self.ws_deque = deque(maxlen=WINDOW)
        # EWMA 时间序列
        self.gain_ewma = 0.0      # 预期收益 (freed bytes)
        self.cost_ewma = 0.0      # 预期成本 (PF delta)
        # 双 EWMA：快速(λ=0.6)追踪短期变化，慢速(λ=0.1)追踪长期趋势
        self.gain_ewma_fast = 0.0
        self.gain_ewma_slow = 0.0
        self.cost_ewma_fast = 0.0
        self.cost_ewma_slow = 0.0
        self.vol_ewma = 0.0       # 波动率 (WS 变化率)
        # Z-score 基线
        self.ws_ewma_mu = 0.0
        self.ws_ewma_sigma = 0.0
        # 反馈
        self.last_ok = True
        self.ok_cnt = 0
        self.fail_cnt = 0
        self.last_seen = 0.0
        self.last_feedback_time = 0.0  # 上次被清理/试探的时间（好奇心计算用）
        self.last_ws = 0
        # Probe 计数器
        self.probe_ok = 0
        self.probe_fail = 0
        # 泄漏检测
        self.leak_suspect = False
        self.leak_tick_count = 0
        # 清理统计
        self.clean_count = 0
        self.refill_ewma = 0.0  # WS 再填充速率 (增长 bytes/s 的 EWMA)
        # 上下文 Thompson 权重: [bias, norm_ws, norm_vol, norm_pf, conf]
        self._ctx_weights = [0.0, 0.0, 0.0, 0.0, 0.0]
        # 批量梯度累积
        self._grad_buffer = [0.0] * 5
        self._grad_count = 0
        self.kalman = KalmanProfile()
        self._curiosity_boost = 1.0   # 卡尔曼连续值估计
        self.temporal = TemporalProfile()  # 时间槽画像

    def feed(self, ws):
        """喂入 WS 样本，更新 EWMA 和 Z-score 基线"""
        self.ws_deque.append(ws)
        self.last_seen = time.time()
        # 波动率 (WS 变化率)
        if self.last_ws > 0 and ws > 0:
            rate = abs(ws - self.last_ws) / max(self.last_ws, 1)
            self.vol_ewma = EWMA_LAMBDA * rate + (1 - EWMA_LAMBDA) * self.vol_ewma
        # refill_ewma: WS 增长速率 (bytes/s)，仅在 WS 增长时更新
        if self.last_ws > 0 and ws > self.last_ws:
            growth = (ws - self.last_ws) / max(time.time() - self.last_seen, 1)
            self.refill_ewma = EWMA_LAMBDA * growth + (1 - EWMA_LAMBDA) * self.refill_ewma
        self.temporal.feed(ws, time.time())
        self.last_ws = ws
        # EWMA 基线 (Z-score)
        if self.ws_ewma_mu == 0:
            self.ws_ewma_mu = float(ws)
            self.ws_ewma_sigma = float(ws) * 0.1  # 初始猜测
        else:
            delta = ws - self.ws_ewma_mu
            self.ws_ewma_mu = EWMA_LAMBDA * ws + (1 - EWMA_LAMBDA) * self.ws_ewma_mu
            self.ws_ewma_sigma = EWMA_LAMBDA * abs(delta) + (1 - EWMA_LAMBDA) * self.ws_ewma_sigma

        # 泄漏检测 (双阈值)
        if self.ws_ewma_sigma > 0:
            z = abs(ws - self.ws_ewma_mu) / max(self.ws_ewma_sigma, 1)
            # 检查是否持续增长
            if len(self.ws_deque) >= TREND_SAMPLES:
                slope = self._calc_slope()
                # 双阈值：Z>2.0+斜率>0.005 → 中等泄漏；Z>3.0+斜率>0.01 → 严重泄漏
                if slope > 0.005 and z > 2.0:
                    self.leak_tick_count += 1
                    if self.leak_tick_count >= 2:
                        self.leak_suspect = True
                        if self.leak_tick_count == 2:
                            self._info_msgs.append(f"🕳️ 检测到{self.name}疑似内存泄漏(斜率{slope:.3f},Z={z:.1f})")
                elif slope > 0.002 and z > 1.5:
                    # 轻度泄漏——标记但不跳过冷却
                    self.leak_suspect = "mild"
                else:
                    self.leak_tick_count = max(0, self.leak_tick_count - 1)
                    if self.leak_tick_count == 0:
                        self.leak_suspect = False
        else:
            self.leak_suspect = False

        # Beta 衰减已移至 record_clean 做时间感知遗忘（不再每feed衰减）
        # 不再在此处衰减alpha/beta

    def _calc_slope(self):
        """最小二乘法计算 WS 趋势斜率 (最近 TREND_SAMPLES 个点)"""
        n = min(len(self.ws_deque), TREND_SAMPLES)
        if n < 3:
            return 0.0
        xs = list(range(n))
        ys = list(self.ws_deque)[-n:]
        mx = sum(xs) / n
        my = sum(ys) / n
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = sum((x - mx) ** 2 for x in xs)
        return num / den if den else 0.0

    def _ctx_feature_vector(self):
        """计算 5 维上下文特征向量用于修正 θ"""
        # [1, norm_ws, norm_vol, norm_pf_ratio, confidence]
        ws = self.ws_deque[-1] if self.ws_deque else 0
        # WS sigmoid 归一化: 200MB 为中心点
        norm_ws = 1.0 / (1.0 + math.exp(-(ws / (200 << 20) - 1))) if ws > 0 else 0.5
        # 波动率 tanh 归一化
        norm_vol = math.tanh(self.vol_ewma * 10) if self.vol_ewma > 0 else 0.0
        # PF 成本/收益比
        gain = max(self.gain_ewma, 1)
        norm_pf = min(self.cost_ewma / gain, 2.0) if self.cost_ewma > 0 else 0.0
        return [1.0, norm_ws, norm_vol, norm_pf, self.confidence]

    @property
    def thompson_theta(self):
        """Thompson θ: Kalman 基线 + Beta 探索 + 上下文修正"""
        if not (self._theta_dirty or self._theta_cache is None):
            return self._theta_cache
        # Kalman 基线 (基于 ROI)
        k_freed, k_cost = self.kalman.predict()
        if k_freed > 0 or k_cost > 0:
            roi = self.kalman.roi
            kalman_base = 1.0 / (1.0 + math.exp(-3.0 * (roi - 0.5)))
        else:
            kalman_base = 0.35
        # Beta 探索噪声
        beta_sample = random.betavariate(max(self.alpha, 0.5), max(self.beta, 0.5))
        # 混合: 样本越多越依赖 Kalman
        mix = min(1.0, self.total_samples / 20.0)
        base = (1 - mix) * beta_sample + mix * kalman_base
        # 上下文修正
        feats = self._ctx_feature_vector()
        w_dot = sum(w * f for w, f in zip(self._ctx_weights, feats))
        correction = 1.0 / (1.0 + math.exp(-w_dot)) + 0.5
        self._theta_cache = max(0.01, min(0.99, base * correction))
        self._theta_dirty = False
        return self._theta_cache

    def _update_ctx_weights(self, ok, lr=None):
        """在线梯度下降更新上下文权重 — sign-based + 批量累积"""
        feats = self._ctx_feature_vector()
        base = random.betavariate(max(self.alpha, 0.5), max(self.beta, 0.5))
        w_dot = sum(w * f for w, f in zip(self._ctx_weights, feats))
        sig = 1.0 / (1.0 + math.exp(-w_dot))
        predict = base * (sig + 0.5)
        target = 1.0 if ok else 0.0
        error = predict - target
        if lr is None:
            lr = CTX_LR_BASE * (1.0 - self.confidence * 0.8)
        else:
            lr = lr * (0.5 + 0.5 * (1.0 - self.confidence))
        grad = 2 * error * base * sig * (1 - sig)
        for i in range(len(self._ctx_weights)):
            self._grad_buffer[i] += grad * feats[i]
        self._grad_count += 1
        if self._grad_count >= 2:  # 累积2次就更新（原5，加快上下文修正收敛）
            for i in range(len(self._ctx_weights)):
                avg_grad = self._grad_buffer[i] / self._grad_count
                step = lr * (0.3 * (1.0 if avg_grad > 0 else -1.0) + 0.7 * avg_grad / max(abs(avg_grad), 1e-8))
                self._ctx_weights[i] -= step
            self._grad_buffer = [0.0] * 5
            self._grad_count = 0
        self.kalman = KalmanProfile()
        self._curiosity_boost = 1.0   # 卡尔曼连续值估计
        self.temporal = TemporalProfile()  # 时间槽画像

    def record_clean(self, ok, freed=0, pf_delta=0, lr=None):
        """连续反馈记录清理结果 — 考虑释放质量和PF代价"""
        self.last_ok = ok
        self.last_feedback_time = time.time()
        
        # 时间感知遗忘：距离上次反馈超过1小时，alpha/beta向先验回归
        now = time.time()
        if self.last_seen > 0 and now - self.last_seen > 3600:
            hours_since = (now - self.last_seen) / 3600
            forget = min(0.5, hours_since * 0.05)
            if self.alpha > 2:
                self.alpha = 2 + (self.alpha - 2) * (1 - forget)
            if self.beta > 1:
                self.beta = 1 + (self.beta - 1) * (1 - forget)
            self._theta_dirty = True
        
        # 更新收益/成本 EWMA（无论成败都记录）
        if freed > 0:
            self.gain_ewma = EWMA_LAMBDA * freed + (1 - EWMA_LAMBDA) * self.gain_ewma
            self.gain_ewma_fast = 0.6 * freed + 0.4 * self.gain_ewma_fast
            self.gain_ewma_slow = 0.1 * freed + 0.9 * self.gain_ewma_slow
        if pf_delta >= 0:
            self.cost_ewma = EWMA_LAMBDA * pf_delta + (1 - EWMA_LAMBDA) * self.cost_ewma
            self.cost_ewma_fast = 0.6 * pf_delta + 0.4 * self.cost_ewma_fast
            self.cost_ewma_slow = 0.1 * pf_delta + 0.9 * self.cost_ewma_slow
        # 更新 Kalman (仅在有实际释放量时更新，防止零值把估计拉到0)
        if freed > 0:
            self.kalman.update(freed, max(0, pf_delta))
        
        if ok:
            self.ok_cnt += 1
            if self.fail_cnt > 0:
                self.fail_cnt = max(0, self.fail_cnt - 1)
            self.clean_count += 1
            # 连续反馈：根据释放效率调整 alpha 增量
            # 效率 = freed / max(pf_delta, 1) — 每 PF 释放了多少字节
            if freed > 0 and pf_delta >= 0:
                efficiency = freed / max(pf_delta + 1, 1)  # +1 防除零
                # 期望效率：历史 gain_ewma / max(cost_ewma, 1)
                expected = self.gain_ewma / max(self.cost_ewma + 1, 1)
                ratio = min(3.0, efficiency / max(expected * 0.5, 1))
                # alpha 增量 = 基础1 + 效率加成（0~2）
                bonus = max(0, ratio - 1) * 1.5
                self.alpha += 1 + min(2.0, bonus)
            else:
                self.alpha += 0.5  # 成功但没释放到内存 → 部分奖励
        else:
            self.fail_cnt += 1
            self.ok_cnt = 0
            self.beta += 1
        self._theta_dirty = True
        self._update_ctx_weights(ok, lr)

    def record_probe(self, ok, lr=None, freed=0):
        """记录微型试探结果 — 连续反馈"""
        self.last_feedback_time = time.time()
        # 试探也更新 Kalman (freed=0 也算观测)
        self.kalman.update(freed, 0)
        if ok:
            self.probe_ok += 1
            # 释放越多 → 奖励越多
            if freed > 0:
                ratio = min(3.0, freed / max(self.gain_ewma + 1, 1))
                self.alpha += 1 + min(2.0, (ratio - 1) * 1.5)
            else:
                self.alpha += 0.7  # 成功但没释放 → 部分奖励
        else:
            self.probe_fail += 1
            self.beta += 1
        self._theta_dirty = True
        self._update_ctx_weights(ok, lr)

    @property
    def total_samples(self):
        return len(self.ws_deque)

    @property
    def roi(self):
        """成本收益比"""
        cost = max(self.cost_ewma, 1)
        gain = max(self.gain_ewma, 0)
        return gain / cost if cost > 0 else 0.0

    @property
    def gain_accelerating(self):
        """收益是否在加速增长（快速均值 > 慢速均值）"""
        return self.gain_ewma_fast > self.gain_ewma_slow

    @property
    def z_score(self):
        """当前 WS 的 Z-score"""
        if self.ws_ewma_sigma <= 0 or not self.ws_deque:
            return 0.0
        current_ws = self.ws_deque[-1]
        return (current_ws - self.ws_ewma_mu) / max(self.ws_ewma_sigma, 1)

    @property
    def slope(self):
        """WS 趋势斜率 (正=增长)"""
        return self._calc_slope()

    @property
    def confidence(self):
        """Beta 分布置信度：基于标准差，样本越多、分布越尖，置信度越高"""
        total = self.alpha + self.beta
        if total <= 2:
            return 0.0
        # Beta 分布标准差衡量不确定性
        variance = (self.alpha * self.beta) / ((total ** 2) * (total + 1))
        std = math.sqrt(max(variance, 0.0))
        # Beta(1,1) 均匀分布时 std ≈ 0.289，此时置信度最低
        # std → 0 时置信度最高
        return max(0.0, min(1.0, 1.0 - std / 0.289))

    def to_dict(self):
        return {
            "name": self.name,
            "alpha": self.alpha, "beta": self.beta,
            "ws": list(self.ws_deque),
            "gain_ewma": self.gain_ewma, "cost_ewma": self.cost_ewma,
            "gain_ewma_fast": self.gain_ewma_fast, "gain_ewma_slow": self.gain_ewma_slow,
            "cost_ewma_fast": self.cost_ewma_fast, "cost_ewma_slow": self.cost_ewma_slow,
            "vol_ewma": self.vol_ewma,
            "ws_ewma_mu": self.ws_ewma_mu, "ws_ewma_sigma": self.ws_ewma_sigma,
            "last_ok": self.last_ok,
            "ok_cnt": self.ok_cnt, "fail_cnt": self.fail_cnt,
            "last_seen": self.last_seen,
            "last_feedback_time": self.last_feedback_time,
            "last_ws": self.last_ws,
            "probe_ok": self.probe_ok, "probe_fail": self.probe_fail,
            "leak_suspect": self.leak_suspect,
            "leak_tick_count": self.leak_tick_count,
            "clean_count": self.clean_count,
            "refill_ewma": self.refill_ewma,
            "ctx_weights": self._ctx_weights,
            "grad_buffer": self._grad_buffer,
            "grad_count": self._grad_count,
            "kalman": self.kalman.to_dict(),
            "temporal": self.temporal.to_dict(),
        }

    @classmethod
    def from_dict(cls, d):
        p = cls(d["name"])
        p.alpha = max(d.get("alpha", 1), 0.5)
        p.beta = max(d.get("beta", 1), 0.5)
        p._theta_cache = None
        p._theta_dirty = True
        p.ws_deque = deque(d.get("ws", []), maxlen=WINDOW)
        p.gain_ewma = d.get("gain_ewma", 0.0)
        p.cost_ewma = d.get("cost_ewma", 0.0)
        p.gain_ewma_fast = d.get("gain_ewma_fast", 0.0)
        p.gain_ewma_slow = d.get("gain_ewma_slow", 0.0)
        p.cost_ewma_fast = d.get("cost_ewma_fast", 0.0)
        p.cost_ewma_slow = d.get("cost_ewma_slow", 0.0)
        p.vol_ewma = d.get("vol_ewma", 0.0)
        p.ws_ewma_mu = d.get("ws_ewma_mu", 0.0)
        p.ws_ewma_sigma = d.get("ws_ewma_sigma", 0.0)
        p.last_ok = d.get("last_ok", True)
        p.ok_cnt = d.get("ok_cnt", 0)
        p.fail_cnt = d.get("fail_cnt", 0)
        p.last_seen = d.get("last_seen", 0.0)
        p.last_feedback_time = d.get("last_feedback_time", 0.0)
        p.last_ws = d.get("last_ws", 0)
        p.probe_ok = d.get("probe_ok", 0)
        p.probe_fail = d.get("probe_fail", 0)
        p.leak_suspect = d.get("leak_suspect", False)
        p.leak_tick_count = d.get("leak_tick_count", 0)
        p.clean_count = d.get("clean_count", 0)
        p.refill_ewma = d.get("refill_ewma", 0.0)
        p._ctx_weights = d.get("ctx_weights", [0.0, 0.0, 0.0, 0.0, 0.0])
        p._grad_buffer = d.get("grad_buffer", [0.0] * 5)
        p._grad_count = d.get("grad_count", 0)
        kalman_d = d.get("kalman")
        if kalman_d:
            p.kalman = KalmanProfile.from_dict(kalman_d)
        temporal_d = d.get("temporal")
        if temporal_d:
            p.temporal = TemporalProfile.from_dict(temporal_d)
        return p


class PareLearner:
    """PARES 学习器 — 管理所有进程画像"""
    def __init__(self):
        self.profiles = {}
        self.memory = EpisodeMemory()      # 情景记忆
        self.prior = HierarchicalPrior()   # 分层先验
        self.causal = CausalGraph()        # 因果图
        self.policy = PolicyVoter()        # 策略投票器
        self.meta = MetaCognition(self)    # 元认知监控
        self._meta_ready = True
        self._ctx = {}                     # 当前系统上下文
        self._info_msgs = []

    def set_context(self, mem_pct=50, is_fg=False, trimmed_cnt=0, total_attempts=0, agg=0.0):
        """设置当前系统上下文 (供 episode memory 使用)"""
        self._ctx = {
            "mem_pct": mem_pct,
            "fg": is_fg,
            "trimmed": trimmed_cnt,
            "total": total_attempts,
            "agg": agg,
        }
    
    def pop_info(self):
        """取出并清空日志消息"""
        msgs = self._info_msgs[:]
        self._info_msgs.clear()
        return msgs

    def get(self, name):
        key = name.lower()
        if key not in self.profiles:
            self.profiles[key] = Profile(key)
        return self.profiles[key]

    def feed(self, snaps):
        """喂入一批快照"""
        for s in snaps:
            self.get(s.name).feed(s.ws)

    # ── Thompson Sampling ──

    def thompson_score(self, name):
        """返回 Thompson θ ∈ [0,1]，越高越值得清理
        自适应好奇心 + 不确定性奖励 — 根据全局覆盖率动态调整"""
        key = name.lower()
        if key in SYSTEM_CORE:
            return 0.0
        p = self.profiles.get(key)
        if not p or p.total_samples < 2:
            return self.prior.initial_theta(key, self.profiles)

        # 历史记忆查询
        hist = self.memory.success_rate(key, mem_pct=self._ctx.get("mem_pct", 50), hours=12)
        base = p.thompson_theta

        # 情景记忆检索: 找到相似上下文的历史经验调整θ
        if hasattr(self, 'memory') and self.memory and p.total_samples >= 5:
            mem_hits = self.memory.retrieve(key)
            if mem_hits:
                best_ep = mem_hits[0][1]
                eff = best_ep.get('efficiency', 0)
                if eff > 0:
                    base = max(0.05, min(0.95, base + (eff - 0.3) * 0.15))

        # ── 自适应好奇心 ──
        last_fb = p.last_feedback_time
        mins_since = (time.time() - last_fb) / 60 if last_fb > 0 else 999
        
        # 全局探索覆盖率：最近1小时内被 probe/clean 过的进程比例
        now = time.time()
        recently_served = sum(1 for pp in self.profiles.values()
                             if pp.last_feedback_time > 0 and now - pp.last_feedback_time < 3600)
        total = max(len(self.profiles), 1)
        coverage = recently_served / total
        
        # 覆盖率低(<=30%) → 好奇心加速（系统需要探索更多）
        # 覆盖率高(>=70%) → 好奇心减速（系统已知足够）
        if coverage <= 0.3:
            rate = 0.012  # 快3倍
        elif coverage >= 0.7:
            rate = 0.003  # 减半
        else:
            rate = 0.006  # 默认
        
        curiosity = min(0.20, max(0, mins_since - 5) * rate)
        
        # 不确定性奖励：置信度低(样本少/结果不稳定)的进程给额外机会
        uncertainty = max(0, 0.12 - p.confidence * 0.12)
        
        result = min(0.99, base + curiosity * getattr(p, '_curiosity_boost', 1.0) + uncertainty)
        result = self.meta.adjust_theta(result)
        
        # 探索奖励：累计统计，每 tick 汇总输出一次
        total_bonus = curiosity + uncertainty
        if total_bonus > 0.08:
            pass
        return result

    # ── 成本收益 ──

    def get_roi(self, name):
        p = self.profiles.get(name.lower())
        return p.roi if p else 0.0

    def get_slope(self, name):
        p = self.profiles.get(name.lower())
        return p.slope if p else 0.0

    def get_volatility(self, name):
        p = self.profiles.get(name.lower())
        return p.vol_ewma if p else 0.0

    def is_leak_suspect(self, name):
        p = self.profiles.get(name.lower())
        return p.leak_suspect if p else False

    def get_confidence(self, name):
        p = self.profiles.get(name.lower())
        return p.confidence if p else 0.0

    def get_clean_count(self, name):
        p = self.profiles.get(name.lower())
        return p.clean_count if p else 0

    def get_profile(self, name):
        return self.profiles.get(name.lower())

    # ── 反饋 ──

    def record_clean_result(self, name, ok, freed=0, pf_delta=0, lr=None):
        p = self.profiles.get(name.lower())
        if p:
            p.record_clean(ok, freed, pf_delta, lr)
            # 存入情景记忆
            if freed > 0 or pf_delta > 0:
                self.memory.store(
                    name=name.lower(),
                    mem_pct=self._ctx.get("mem_pct", 50),
                    ws=p.last_ws,
                    is_fg=self._ctx.get("fg", False),
                    action="trim",
                    ok=ok, freed=freed, pf_delta=pf_delta,
                    trimmed_cnt=self._ctx.get("trimmed", 0),
                    total_att=self._ctx.get("total", 0),
                    agg=self._ctx.get("agg", 0.0),
                )

    def record_probe_result(self, name, ok, lr=None, freed=0):
        p = self.profiles.get(name.lower())
        if p:
            p.record_probe(ok, lr, freed)
            # 存入情景记忆
            self.memory.store(
                name=name.lower(),
                mem_pct=self._ctx.get("mem_pct", 50),
                ws=p.last_ws,
                is_fg=self._ctx.get("fg", False),
                action="probe",
                ok=ok, freed=freed, pf_delta=0,
                trimmed_cnt=self._ctx.get("trimmed", 0),
                total_att=self._ctx.get("total", 0),
                agg=self._ctx.get("agg", 0.0),
            )

    # ── 持久化 ──

    def self_check(self):
        """每 100 tick 检查预测准确性，动态调整学习率"""
        errors = []
        now = time.time()
        for name, p in self.profiles.items():
            if p.clean_count >= 5 and p.gain_ewma > 0:
                # 预测释放量 = θ × gain_ewma（期望值）
                predicted = p.thompson_theta * p.gain_ewma
                # 实际最近释放 = gain_ewma（EWMA已是最新估计）
                actual = p.gain_ewma
                err = abs(predicted - actual) / max(actual, 1)
                errors.append(err)
        
        if not errors:
            return
        
        avg_err = sum(errors) / len(errors)
        # 平均误差 > 30% → 学习太激进，降速
        if avg_err > 0.3:
            new_lr = CTX_LR_BASE * 0.8
            if new_lr != CTX_LR_BASE:
                import sys
                # print(f"[MemWise] ⚠ 预测偏差{avg_err:.0%}，学习率{CTX_LR_BASE:.3f}→{new_lr:.3f}", file=sys.stderr)
        # 平均误差 < 5% → 预测很准，允许加速
        elif avg_err < 0.05:
            new_lr = CTX_LR_BASE * 1.1
            if new_lr != CTX_LR_BASE:
                import sys
                # print(f"[MemWise] ✅ 预测精准({avg_err:.1%})，学习率保持{CTX_LR_BASE:.3f}", file=sys.stderr)

    def record_causal(self, name, freed, mem_pct, candidates):
        """Record causal observation"""
        self.causal.record(name.lower(), freed, mem_pct, candidates or [])
    
    def causal_compare(self, name, candidates, mem_pct=None):
        """Counterfactual: how much better than alternatives"""
        best_adv = 0
        for alt in (candidates or []):
            if alt.lower() == name.lower():
                continue
            adv = self.causal.advantage(name.lower(), alt.lower(), mem_pct)
            if adv > best_adv:
                best_adv = adv
        return best_adv
    
    def save(self, path):
        try:
            now = time.time()
            # 过滤：7天以上没见过且样本<5的低价值画像 ➔ 防止 state.json 膨胀
            cutoff = 86400 * 7
            filtered = {
                k: v for k, v in self.profiles.items()
                if now - v.last_seen < cutoff or v.total_samples >= 5
            }
            # 读取现有 state，保留其他组件（如 EFIS）的数据
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}
            existing.update({
                "version": 5,
                "saved_at": now,
                "profiles": {k: v.to_dict() for k, v in filtered.items()},
                "memory": self.memory.to_dict(),
                "causal": self.causal.to_dict(),
                "meta_bias": self.meta._theta_bias,
            })
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(existing, f, ensure_ascii=False)
            os.replace(tmp, path)
            return True
        except OSError:
            return False

    @classmethod
    def load(cls, path):
        learner = cls()
        if not path or not os.path.isfile(path):
            return learner
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            ver = data.get("version", 0)
            if ver >= 2:
                for k, v in data.get("profiles", {}).items():
                    learner.profiles[k] = Profile.from_dict(v)
            if ver >= 4:
                mem_data = data.get("memory")
                if mem_data:
                    learner.memory = EpisodeMemory.from_dict(mem_data)
            if ver >= 5:
                causal_data = data.get("causal")
                if causal_data:
                    learner.causal = CausalGraph.from_dict(causal_data)
        except Exception as e:
            import sys; print(f"[MemWise] 学习数据加载失败: {e}", file=sys.stderr)
        # 还原元认知偏差
        mb = data.get("meta_bias", 0)
        if mb != 0:
            learner.meta._theta_bias = mb
        return learner

    # ── 复合评分 ──

    def composite_score(self, name):
        """复合评分 = 60% θ + 40% bonus (置信度+ROI+加速)，bonus可拉升低θ进程"""
        p = self.profiles.get(name.lower())
        if not p or p.total_samples < MIN_SAMPLES:
            return 0.35  # 新进程默认中低分
        theta = p.thompson_theta
        conf = p.confidence
        roi = min(p.roi, 1.0)
        bonus = 0.5 * conf + 0.3 * roi + (0.2 if p.gain_accelerating else 0)
        # 加性混合：θ 占60%，bonus占40%
        return 0.6 * theta + 0.4 * min(1.0, bonus)

    def top_by_score(self, n=25):
        """按复合评分排序"""
        items = []
        for name, p in self.profiles.items():
            if p.total_samples < MIN_SAMPLES:
                continue
            score = self.composite_score(name)
            items.append((name, score, p.thompson_theta, p.roi, p.confidence, p))
        items.sort(key=lambda x: -x[1])  # 复合评分降序
        return items[:n]

    # ── 信息查询 ──

    def top(self, n=25):
        """按 ROI 排序，返回 (name, roi, theta, profile) 列表"""
        items = []
        for name, p in self.profiles.items():
            if p.total_samples < MIN_SAMPLES:
                continue
            items.append((name, p.roi, p.thompson_theta, p))
        items.sort(key=lambda x: -x[1])  # ROI 降序
        return items[:n]

    def top_by_theta(self, n=25):
        items = [(name, p.thompson_theta, p.roi, p)
                 for name, p in self.profiles.items() if p.total_samples >= MIN_SAMPLES]
        items.sort(key=lambda x: -x[1])
        return items[:n]
