"""
PARES Learner — Predictive Adaptive Reinforcement Engine
Thompson Sampling + 3x EWMA + Z-score + 趋势线
"""
import json, os, time, math, random
from collections import deque

WINDOW = 30  # 趋势窗口大小
EWMA_LAMBDA = 0.5  # EWMA 衰减因子 (高=更快适应新数据)
Z_SCORE_THRESHOLD = 3.0  # Z-score 异常阈值
MIN_SAMPLES = 3  # 最小样本数 (更快对新进程做出决策)
TREND_SAMPLES = 6  # 趋势线使用的采样数
BETA_DECAY_RATE = 0.002  # Beta 分布衰减率（每次 feed 向先验收缩）
CTX_LR_BASE = 0.03  # 上下文权重基础学习率

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
                 "ws_ewma_mu", "ws_ewma_sigma",
                 "last_ok", "ok_cnt", "fail_cnt",
                 "last_seen", "last_ws",
                 "probe_ok", "probe_fail",
                 "leak_suspect", "leak_tick_count",
                 "clean_count", "refill_ewma",
                 "_ctx_weights")

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
        self.vol_ewma = 0.0       # 波动率 (WS 变化率)
        # Z-score 基线
        self.ws_ewma_mu = 0.0
        self.ws_ewma_sigma = 0.0
        # 反馈
        self.last_ok = True
        self.ok_cnt = 0
        self.fail_cnt = 0
        self.last_seen = 0.0
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
        self.last_ws = ws
        # EWMA 基线 (Z-score)
        if self.ws_ewma_mu == 0:
            self.ws_ewma_mu = float(ws)
            self.ws_ewma_sigma = float(ws) * 0.1  # 初始猜测
        else:
            delta = ws - self.ws_ewma_mu
            self.ws_ewma_mu = EWMA_LAMBDA * ws + (1 - EWMA_LAMBDA) * self.ws_ewma_mu
            self.ws_ewma_sigma = EWMA_LAMBDA * abs(delta) + (1 - EWMA_LAMBDA) * self.ws_ewma_sigma

        # 泄漏检测 (连续 Z>3)
        if self.ws_ewma_sigma > 0:
            z = abs(ws - self.ws_ewma_mu) / max(self.ws_ewma_sigma, 1)
            # 检查是否持续增长
            if len(self.ws_deque) >= TREND_SAMPLES:
                slope = self._calc_slope()
                if slope > 0.01 and z > Z_SCORE_THRESHOLD:
                    self.leak_tick_count += 1
                    if self.leak_tick_count >= 3:  # 连续 3 tick
                        self.leak_suspect = True
                else:
                    self.leak_tick_count = max(0, self.leak_tick_count - 1)
                    if self.leak_tick_count == 0:
                        self.leak_suspect = False
        else:
            self.leak_suspect = False

        # Beta 衰减：每次 feed 轻微向先验 (α=2, β=1) 收缩
        # 忘记旧观测，适应进程行为变化；活跃进程衰减快，自然更新
        if self.alpha > 2 or self.beta > 1:
            self.alpha += (2 - self.alpha) * BETA_DECAY_RATE
            self.beta += (1 - self.beta) * BETA_DECAY_RATE
            self._theta_dirty = True

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
        """Thompson Sampling × 上下文修正: Beta(α,β) × σ(w·f)
        同一 tick 内缓存复用"""
        if not (self._theta_dirty or self._theta_cache is None):
            return self._theta_cache
        base = random.betavariate(self.alpha, self.beta)
        # 上下文修正: sigmoid 加权
        feats = self._ctx_feature_vector()
        w_dot = sum(w * f for w, f in zip(self._ctx_weights, feats))
        # clip 修正因子到 [0.5, 1.5] 避免过度偏离
        correction = 1.0 / (1.0 + math.exp(-w_dot)) + 0.5  # range [0.5, 1.5]
        self._theta_cache = max(0.01, min(0.99, base * correction))
        self._theta_dirty = False
        return self._theta_cache

    def _update_ctx_weights(self, ok):
        """在线梯度下降更新上下文权重，学习率随置信度自适应"""
        feats = self._ctx_feature_vector()
        base = random.betavariate(self.alpha, self.beta)
        w_dot = sum(w * f for w, f in zip(self._ctx_weights, feats))
        sig = 1.0 / (1.0 + math.exp(-w_dot))
        predict = base * (sig + 0.5)
        target = 1.0 if ok else 0.0
        error = predict - target
        # 自适应学习率：置信度高时微调，置信度低时大步探索
        lr = CTX_LR_BASE * (1.0 - self.confidence * 0.8)
        # sigmoid derivative: sig * (1 - sig)
        grad = 2 * error * base * sig * (1 - sig)
        for i in range(len(self._ctx_weights)):
            self._ctx_weights[i] -= lr * grad * feats[i]

    def record_clean(self, ok, freed=0, pf_delta=0):
        """记录清理结果 → 更新 Beta 分布 + EWMA + 上下文权重"""
        self.last_ok = ok
        if ok:
            self.ok_cnt += 1
            # 遗忘：成功时逐渐减少失败计数，不让一次失败永久影响 θ
            if self.fail_cnt > 0:
                self.fail_cnt = max(0, self.fail_cnt - 1)
            self.alpha += 1
            self.clean_count += 1
            # 更新收益/成本 EWMA
            if freed > 0:
                self.gain_ewma = EWMA_LAMBDA * freed + (1 - EWMA_LAMBDA) * self.gain_ewma
            if pf_delta >= 0:
                self.cost_ewma = EWMA_LAMBDA * pf_delta + (1 - EWMA_LAMBDA) * self.cost_ewma
        else:
            self.fail_cnt += 1
            self.ok_cnt = 0
            self.beta += 1
        self._theta_dirty = True
        self._update_ctx_weights(ok)

    def record_probe(self, ok):
        """记录微型试探结果"""
        if ok:
            self.probe_ok += 1
            self.alpha += 1
        else:
            self.probe_fail += 1
            self.beta += 1
        self._theta_dirty = True
        self._update_ctx_weights(ok)

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
        std = math.sqrt(variance)
        # Beta(1,1) 均匀分布时 std ≈ 0.289，此时置信度最低
        # std → 0 时置信度最高
        return max(0.0, min(1.0, 1.0 - std / 0.289))

    def to_dict(self):
        return {
            "name": self.name,
            "alpha": self.alpha, "beta": self.beta,
            "ws": list(self.ws_deque),
            "gain_ewma": self.gain_ewma, "cost_ewma": self.cost_ewma,
            "vol_ewma": self.vol_ewma,
            "ws_ewma_mu": self.ws_ewma_mu, "ws_ewma_sigma": self.ws_ewma_sigma,
            "last_ok": self.last_ok,
            "ok_cnt": self.ok_cnt, "fail_cnt": self.fail_cnt,
            "last_seen": self.last_seen,
            "last_ws": self.last_ws,
            "probe_ok": self.probe_ok, "probe_fail": self.probe_fail,
            "leak_suspect": self.leak_suspect,
            "leak_tick_count": self.leak_tick_count,
            "clean_count": self.clean_count,
            "refill_ewma": self.refill_ewma,
            "ctx_weights": self._ctx_weights,
        }

    @classmethod
    def from_dict(cls, d):
        p = cls(d["name"])
        p.alpha = d.get("alpha", 1)
        p.beta = d.get("beta", 1)
        p._theta_cache = None
        p._theta_dirty = True
        p.ws_deque = deque(d.get("ws", []), maxlen=WINDOW)
        p.gain_ewma = d.get("gain_ewma", 0.0)
        p.cost_ewma = d.get("cost_ewma", 0.0)
        p.vol_ewma = d.get("vol_ewma", 0.0)
        p.ws_ewma_mu = d.get("ws_ewma_mu", 0.0)
        p.ws_ewma_sigma = d.get("ws_ewma_sigma", 0.0)
        p.last_ok = d.get("last_ok", True)
        p.ok_cnt = d.get("ok_cnt", 0)
        p.fail_cnt = d.get("fail_cnt", 0)
        p.last_seen = d.get("last_seen", 0.0)
        p.last_ws = d.get("last_ws", 0)
        p.probe_ok = d.get("probe_ok", 0)
        p.probe_fail = d.get("probe_fail", 0)
        p.leak_suspect = d.get("leak_suspect", False)
        p.leak_tick_count = d.get("leak_tick_count", 0)
        p.clean_count = d.get("clean_count", 0)
        p.refill_ewma = d.get("refill_ewma", 0.0)
        p._ctx_weights = d.get("ctx_weights", [0.0, 0.0, 0.0, 0.0, 0.0])
        return p


class PareLearner:
    """PARES 学习器 — 管理所有进程画像"""
    def __init__(self):
        self.profiles = {}

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
        """返回 Thompson θ ∈ [0,1]，越高越值得清理"""
        key = name.lower()
        if key in SYSTEM_CORE:
            return 0.0
        p = self.profiles.get(key)
        if not p or p.total_samples < 2:
            return 0.35  # 不明确 → 低分 (probe 判定)
        return p.thompson_theta

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

    def record_clean_result(self, name, ok, freed=0, pf_delta=0):
        p = self.profiles.get(name.lower())
        if p:
            p.record_clean(ok, freed, pf_delta)

    def record_probe_result(self, name, ok):
        p = self.profiles.get(name.lower())
        if p:
            p.record_probe(ok)

    # ── 持久化 ──

    def save(self, path):
        try:
            now = time.time()
            # 过滤：7天以上没见过且样本<5的低价值画像 ➔ 防止 state.json 膨胀
            cutoff = 86400 * 7
            filtered = {
                k: v for k, v in self.profiles.items()
                if now - v.last_seen < cutoff or v.total_samples >= 5
            }
            data = {
                "version": 3,
                "saved_at": now,
                "profiles": {k: v.to_dict() for k, v in filtered.items()},
            }
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
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
        except Exception as e:
            import sys; print(f"[MemWise] 学习数据加载失败: {e}", file=sys.stderr)
        return learner

    # ── 复合评分 ──

    def composite_score(self, name):
        """复合评分 = θ × (置信度 + ROI)，选择更精准"""
        p = self.profiles.get(name.lower())
        if not p or p.total_samples < MIN_SAMPLES:
            return 0.35  # 新进程默认中低分
        theta = p.thompson_theta
        conf = p.confidence
        roi = min(p.roi, 1.0)  # 截断 ROI 防极端值
        # θ 占主体，置信度和 ROI 做调节
        return theta * (0.5 + 0.3 * conf + 0.2 * roi)

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
