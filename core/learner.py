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
    __slots__ = ("name", "alpha", "beta", "ws_deque",
                 "gain_ewma", "cost_ewma", "vol_ewma",
                 "ws_ewma_mu", "ws_ewma_sigma",
                 "last_ok", "ok_cnt", "fail_cnt",
                 "last_seen", "last_ws",
                 "probe_ok", "probe_fail",
                 "leak_suspect", "leak_tick_count",
                 "clean_count")

    def __init__(self, name):
        self.name = name
        # Thompson Sampling — Beta(α, β) (先验偏向可清理)
        self.alpha = 2
        self.beta = 1
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

    def feed(self, ws):
        """喂入 WS 样本，更新 EWMA 和 Z-score 基线"""
        self.ws_deque.append(ws)
        self.last_seen = time.time()
        # 波动率 (WS 变化率)
        if self.last_ws > 0 and ws > 0:
            rate = abs(ws - self.last_ws) / max(self.last_ws, 1)
            self.vol_ewma = EWMA_LAMBDA * rate + (1 - EWMA_LAMBDA) * self.vol_ewma
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

    def record_clean(self, ok, freed=0, pf_delta=0):
        """记录清理结果 → 更新 Beta 分布 + EWMA"""
        self.last_ok = ok
        if ok:
            self.ok_cnt += 1
            self.fail_cnt = 0
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

    def record_probe(self, ok):
        """记录微型试探结果"""
        if ok:
            self.probe_ok += 1
            self.alpha += 1
        else:
            self.probe_fail += 1
            self.beta += 1

    @property
    def total_samples(self):
        return len(self.ws_deque)

    @property
    def thompson_theta(self):
        """Thompson Sampling: 从 Beta(α, β) 采样"""
        return random.betavariate(self.alpha, self.beta)

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
        """Thompson 置信度: 分布越尖越高"""
        total = self.alpha + self.beta
        return min(1.0, total / 50.0) if total > 2 else 0.0

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
        }

    @classmethod
    def from_dict(cls, d):
        p = cls(d["name"])
        p.alpha = d.get("alpha", 1)
        p.beta = d.get("beta", 1)
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
            data = {
                "version": 3,
                "saved_at": time.time(),
                "profiles": {k: v.to_dict() for k, v in self.profiles.items()},
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
        except Exception:
            pass
        return learner

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
