"""
PARES Learner — Predictive Adaptive Reinforcement Engine
Thompson Sampling + 3x EWMA + Z-score + 趋势线
"""
import json, os, time, math, random
from .kalman import KalmanProfile
from .prior import HierarchicalPrior
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
                 "kalman", "last_feedback_time",
                 "_info_msgs", "timeout_count")

    def __init__(self, name, kalman_r=5.0):
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
        # 批量梯度累积
        self.kalman = KalmanProfile(r=kalman_r)
        self._info_msgs = []  # 泄漏检测等消息缓冲
        self.timeout_count = 0  # 超时累计（仅内存，不持久化）

    def feed(self, ws):
        """喂入 WS 样本，更新 EWMA 和 Z-score 基线"""
        self.ws_deque.append(ws)
        prev_seen = self.last_seen
        self.last_seen = time.time()
        # 波动率 (WS 变化率)
        if self.last_ws > 0 and ws > 0:
            rate = abs(ws - self.last_ws) / max(self.last_ws, 1)
            self.vol_ewma = EWMA_LAMBDA * rate + (1 - EWMA_LAMBDA) * self.vol_ewma
        # refill_ewma: WS 增长速率 (bytes/s)，仅在 WS 增长时更新
        if self.last_ws > 0 and ws > self.last_ws and prev_seen > 0:
            dt = max(time.time() - prev_seen, 1)
            growth = (ws - self.last_ws) / dt
            self.refill_ewma = EWMA_LAMBDA * growth + (1 - EWMA_LAMBDA) * self.refill_ewma
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
                # 双阈值：相对斜率（按进程WS缩放）>0.005 + Z>2.0 → 中等泄漏
                slope = self._calc_slope()
                ws_avg = sum(self.ws_deque) / max(len(self.ws_deque), 1)
                ws_scale = max(1.0, ws_avg / (1 << 20))  # 按 MB 缩放
                rel_slope = slope / ws_scale if ws_scale > 0 else 0.0
                if rel_slope > 0.005 and z > 2.0:
                    self.leak_tick_count += 1
                    if self.leak_tick_count >= 2:
                        self.leak_suspect = True
                        if self.leak_tick_count == 2:
                            self._info_msgs.append(f"🕳️ {self.name} 疑似内存持续增长，建议关注")
                elif rel_slope > 0.002 and z > 1.5:
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
        self._theta_cache = max(0.01, min(0.99, base))
        self._theta_dirty = False
        return self._theta_cache

    def record_clean(self, ok, freed=0, pf_delta=0, lr=None):
        """连续反馈记录清理结果 — 考虑释放质量和PF代价"""
        self.last_ok = ok
        prev_feedback = self.last_feedback_time
        self.last_feedback_time = time.time()
        
        # 时间感知遗忘：距离上次反馈（清理/试探）超过1小时，alpha/beta向先验回归
        now = time.time()
        if prev_feedback > 0 and now - prev_feedback > 3600:
            hours_since = (now - prev_feedback) / 3600
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
                # alpha 增量 = 基础1 + 效率加成（0~2），再按释放量对数缩放
                bonus = max(0, ratio - 1) * 1.5
                freed_mb = max(1, freed / (1 << 20))
                scale = 1.0 + min(1.5, math.log2(freed_mb + 1) / 6)
                self.alpha += scale * (1 + min(2.0, bonus))
            else:
                self.alpha += 0.5  # 成功但没释放到内存 → 部分奖励
        else:
            self.fail_cnt += 1
            self.ok_cnt = 0
            self.beta += 1
        self.alpha = min(self.alpha, 100)   # 防止 Alpha 无限膨胀导致 Thompson 退化
        self.beta = min(self.beta, 50)      # 同上
        # 软上限：超限后等比缩归，保持 α/β 比例不畸变
        if self.alpha > 80:
            ratio = self.beta / max(self.alpha, 1)
            self.alpha = int(self.alpha * 0.85)
            self.beta = max(1, int(self.alpha * ratio))
        self._theta_dirty = True

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
            "kalman": self.kalman.to_dict(),
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
        kalman_d = d.get("kalman")
        if kalman_d:
            p.kalman = KalmanProfile.from_dict(kalman_d)
        if p.kalman.x_freed == 0 and p.gain_ewma > 0:
            p.kalman.x_freed = p.gain_ewma
            p.kalman.p_freed = 50.0
        if p.kalman.x_cost == 0 and p.cost_ewma > 0:
            p.kalman.x_cost = p.cost_ewma
            p.kalman.p_cost = 50.0
        p._info_msgs = []  # 从磁盘恢复后初始化消息缓冲
        return p


class PareLearner:
    """PARES 学习器 — 管理所有进程画像"""
    def __init__(self):
        self.profiles = {}
        self.prior = HierarchicalPrior()   # 分层先验
        self.policy = PolicyVoter()        # 策略投票器
        self.meta = MetaCognition(self)    # 元认知监控
        self._meta_ready = True
        self._ctx = {}                     # 当前系统上下文
        self._info_msgs = []
        # 上下文修正查找表: 30桶 × 1 float，在线学习条件偏差
        self._ctx_corrections = {}         # {bucket_key: correction_ewma}
    
    @staticmethod
    def _ctx_bucket(mem_pct, is_fg, hour):
        """三维上下文 → 桶键 (5×2×3=30)"""
        mb = 0 if mem_pct < 30 else (1 if mem_pct < 50 else (2 if mem_pct < 70 else (3 if mem_pct < 85 else 4)))
        fb = 1 if is_fg else 0
        hb = 0 if hour < 6 else (1 if hour < 22 else 2)  # 深夜/活跃/普通
        return (mb, fb, hb)
    
    def ctx_correction(self, mem_pct, is_fg=False, hour=12):
        """获取当前上下文下的 Kalman 预测修正因子（freed, cost）"""
        v = self._ctx_corrections.get(self._ctx_bucket(mem_pct, is_fg, hour), (1.0, 1.0))
        return v if isinstance(v, tuple) else (v, 1.0)  # 兼容旧单值格式
    
    def record_ctx_correction(self, mem_pct, is_fg, hour, actual_freed, kalman_freed, actual_pf=0, kalman_cost=0):
        """每次 trim 后更新上下文修正 EWMA（freed + cost 双值）"""
        if kalman_freed <= 0:
            return
        key = self._ctx_bucket(mem_pct, is_fg, hour)
        fr = max(0.1, min(5.0, actual_freed / kalman_freed))
        cr = max(0.1, min(5.0, actual_pf / max(kalman_cost, 1))) if kalman_cost > 0 and actual_pf > 0 else 1.0
        old_f, old_c = self._ctx_corrections.get(key, (1.0, 1.0))
        if not isinstance(old_f, tuple):
            old_f, old_c = (old_f, 1.0)
        self._ctx_corrections[key] = (0.85 * old_f + 0.15 * fr, 0.85 * old_c + 0.15 * cr)

 
    def pop_info(self):
        """取出并清空日志消息（含 Learner 自身 + 各 Profile 消息）"""
        msgs = self._info_msgs[:]
        self._info_msgs.clear()
        # 收集各 Profile 的消息（如泄漏检测）
        for p in self.profiles.values():
            if hasattr(p, '_info_msgs') and p._info_msgs:
                msgs.extend(p._info_msgs)
                p._info_msgs.clear()
        return msgs

    def get(self, name):
        key = name.lower()
        if key not in self.profiles:
            self.profiles[key] = Profile(key, kalman_r=getattr(self, '_kalman_r', 5.0))
        return self.profiles[key]

    def feed(self, snaps):
        """喂入一批快照"""
        for s in snaps:
            self.get(s.name).feed(s.ws)

    # ── Thompson Sampling ──

    def thompson_score(self, name, mem_pct=None, is_fg=None):
        """t — mem_pct/is_fg 由调用方传入真实上下文，修正取实际桶；未传时回退 _ctx/默认值"""
        key = name.lower()
        if key in SYSTEM_CORE:
            return 0.0
        p = self.profiles.get(key)
        if not p or p.total_samples < 2:
            return self.prior.initial_theta(key, self.profiles)
        base = p.thompson_theta
        if mem_pct is None:
            mem_pct = self._ctx.get("mem_pct", 50)
        if is_fg is None:
            is_fg = self._ctx.get("is_fg", False)
        if hasattr(p, 'kalman') and p.kalman.x_freed > 0:
            f_corr, _ = self.ctx_correction(mem_pct, is_fg=is_fg, hour=time.localtime().tm_hour)
            base = max(0.01, min(0.99, base * max(0.3, min(3.0, f_corr))))
        uncertainty = max(0, 0.12 - p.confidence * 0.12)
        result = min(0.99, base + uncertainty)
        result = max(0.01, min(0.99, result))
        return result

    def get_roi(self, name):
        p = self.profiles.get(name.lower())
        return p.roi if p else 0.0

    def get_slope(self, name):
        p = self.profiles.get(name.lower())
        return p.slope if p else 0.0



    def get_confidence(self, name):
        p = self.profiles.get(name.lower())
        return p.confidence if p else 0.0



    def get_profile(self, name):
        return self.profiles.get(name.lower())

    # ── 持久化 ──

    def save(self, path):
        try:
            now = time.time()
            cutoff = 86400 * 7
            filtered = {
                k: v for k, v in self.profiles.items()
                if now - v.last_seen < cutoff or v.alpha != 2 or v.beta != 1
            }
            data = {
                "version": 4,
                "profiles": {k: v.to_dict() for k, v in filtered.items()},
            }
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, path)
            return True
        except Exception:
            return False

    @classmethod
    def load(cls, path):
        learner = cls()
        if not path or not os.path.isfile(path):
            return learner
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.get("profiles", {}).items():
                learner.profiles[k] = Profile.from_dict(v)
        except Exception:
            pass
        return learner

    # ── 反饋 ──

    def record_clean_result(self, name, ok, freed=0, pf_delta=0, lr=None):
        """记录清理结果 — 走完整清理反馈通道（收益/成本/清理计数）"""
        p = self.profiles.get(name.lower())
        if p:
            p.record_clean(ok, freed, pf_delta, lr)

    def record_probe_result(self, name, ok, lr=None, freed=0):
        """记录试探结果"""
        p = self.profiles.get(name.lower())
        if p:
            p.record_probe(ok, lr, freed)
