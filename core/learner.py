"""
PARES Learner — Predictive Adaptive Reinforcement Engine
Thompson Sampling + 3x EWMA + Z-score + 趋势线
"""
import json, os, sys, time, math, random, threading
from .kalman import KalmanProfile
from .prior import HierarchicalPrior
from .policy import PolicyVoter
from .meta import MetaCognition
from .stable import StableAnchorStore
from .rebound import ReboundLearner
from collections import deque

WINDOW = 20  # 趋势窗口大小
EWMA_LAMBDA = 0.5  # EWMA 衰减因子 (高=更快适应新数据)；EFIS learning_rate 可逐进程覆盖
TREND_SAMPLES = 3  # 趋势线使用的采样数（原6。缩短窗口让预判式清理更快响应）
# 注：BETA_DECAY_RATE / CTX_LR_BASE 已随 Beta 衰减迁移至 record_clean 时间感知遗忘、上下文修正固定 0.15，此处不再保留常量
# 注：Z_SCORE_THRESHOLD / MIN_SAMPLES 死常量已于 2026-09-06 审查 F12 移除（零消费方；
# 泄漏检测用双阈值 0.005/2.0 与样本判定 2/5 均就地硬编码，未来启用时按需重定义）

# 持久化写锁（2026-08-30 审查）：守护 30s 周期保存、手动优化保存、GUI 退出保存可并发——
# 同一 tmp 路径双句柄交错写会损坏画像文件（实验实证 A/B 混写）；与 config._save_lock /
# engine._eris_save_lock 同款先例
_SAVE_LOCK = threading.Lock()

SYSTEM_CORE = {
    "system", "system idle process", "registry", "smss", "csrss", "wininit",
    "winlogon", "services", "lsass", "svchost", "dwm", "fontdrvhost",
    "sihost", "taskhostw", "textinputhost", "ctfmon", "explorer",
    "searchhost", "searchindexer", "securityhealthservice",
    "securityhealthsystray", "defender", "msmpeng", "nissrv",
    "conhost", "dllhost", "shellexperiencehost", "startmenuexperiencehost",
    "runtimebroker", "backgroundtaskhost", "wmiprvse", "wudfhost",
    "audiodg", "spoolsv", "mpdefendercoreservice",
    "memory compression",  # 系统压缩池组件（2026-08-14 审查发现不在保护名单，full 模式可能误清）
}
# 进程名来自 PROCESSENTRY32W.szExeFile（必带 .exe），派生带后缀集合供快照名直接比较
SYSTEM_CORE_EXE = {n + ".exe" for n in SYSTEM_CORE}

def _is_system_core(name):
    """快照进程名（可能带 .exe）是否系统核心保护名单成员（统一入口，勿再直接比较 SYSTEM_CORE）"""
    n = str(name or "").lower()
    if not n:
        return False
    return n in SYSTEM_CORE_EXE or n in SYSTEM_CORE


_SELF_EXE_PATH = None   # 模块级缓存：本程序可执行文件的规范化路径

def _is_self_path(path):
    """给定可执行路径是否为『本程序自身的可执行文件』（含看门狗子进程与多实例）。
    按规范化【完整路径】精确匹配——同名但不同路径的他人程序不受影响。
    用途（2026-09-11 审查 F48）：看门狗是同一 exe 的 --watchdog 子进程，主程序原先只按 PID
    排除自身，实测对看门狗累计清理 7,786 次 / 试探 50,186 次（零收益且挤占预算）。
    注：脚本方式运行时 sys.executable 为解释器路径，同解释器启动的其它进程也会被排除——
    这是冻结分发（唯一权威形态）下的精确语义，脚本态偏保守属可接受代价。"""
    global _SELF_EXE_PATH
    if _SELF_EXE_PATH is None:
        try:
            _SELF_EXE_PATH = os.path.normcase(os.path.abspath(sys.executable)) if sys.executable else ""
        except Exception:
            _SELF_EXE_PATH = ""
    if not _SELF_EXE_PATH or not path:
        return False
    try:
        return os.path.normcase(os.path.abspath(path)) == _SELF_EXE_PATH
    except Exception:
        return False


def _is_self_process(snap):
    """快照对应的进程是否为本程序自身（统一入口，与 _is_self_path 同判据）"""
    return _is_self_path(getattr(snap, "path", None))

class Profile:
    """进程画像 — 每个进程一个"""
    __slots__ = ("name", "alpha", "beta", "_theta_cache", "_theta_dirty", "ws_deque",
                 "gain_ewma", "cost_ewma",
                 "gain_ewma_fast", "gain_ewma_slow",
                 "ws_ewma_mu", "ws_ewma_sigma",
                 "ok_cnt", "fail_cnt",
                 "last_seen", "last_ws",
                 "probe_ok", "probe_fail", "probe_zero",
                 "leak_suspect", "leak_tick_count",
                 "clean_count", "refill_ewma",
                 "kalman", "last_feedback_time",
                 "last_foreground_at",  # 最后前台时间（前台历史冷却：刚切走不碰）
                 "_info_msgs", "timeout_count", "samples_total", "last_drift_at")

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
        # Z-score 基线
        self.ws_ewma_mu = 0.0
        self.ws_ewma_sigma = 0.0
        # 反馈
        self.ok_cnt = 0
        self.fail_cnt = 0
        self.last_seen = 0.0
        self.last_feedback_time = 0.0  # 上次被清理/试探的时间（好奇心计算用）
        self.last_foreground_at = 0.0  # 最后前台时间戳（0=从未在前台；前台历史冷却用）
        self.last_ws = 0
        # Probe 计数器
        self.probe_ok = 0
        self.probe_fail = 0
        self.probe_zero = 0  # 连续"试探成功但零释放"次数（零释放退避用，2026-09-11 审查 F48）
        # 泄漏检测
        self.leak_suspect = False
        self.leak_tick_count = 0
        # 清理统计
        self.clean_count = 0
        self.refill_ewma = 0.0  # WS 再填充速率 (增长 bytes/s 的 EWMA)
        # Kalman 连续值估计（EFIS 可调观测噪声 r）
        self.kalman = KalmanProfile(r=kalman_r)
        self._info_msgs = []  # 泄漏检测等消息缓冲
        self.timeout_count = 0  # 超时累计（仅内存，不持久化）
        self.samples_total = 0  # P05：累计观测次数（滑动窗 total_samples 只有 20，不能当累计用）
        self.last_drift_at = 0.0  # 上次概念漂移复位时间（防同一漂移每次 tick 反复削 α/β）

    def feed(self, ws, is_fg=False):
        """喂入 WS 样本，更新 EWMA 和 Z-score 基线；is_fg=True 记录最后前台时间（前台历史冷却）"""
        self.ws_deque.append(ws)
        self.samples_total += 1
        prev_seen = self.last_seen
        self.last_seen = time.time()
        if is_fg:
            self.last_foreground_at = time.time()
        # 波动率已并入 Z-score sigma（ws_ewma_sigma），vol_ewma 历史字段不再维护
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
                # 相对斜率：增长率 / 当前 WS 均值（无单位比率，0.005 = 0.5%/tick）
                rel_slope = slope / max(ws_avg, 1.0)
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
        # 观察样本改变 mix 混合权重（total_samples 爬坡）⇒ θ 缓存须跨 tick 失效；
        # 同 tick 内仍复用（生产时序 = 批量 feed 全部快照后再决策，见 engine._snap → optimize；
        # 曾缺此行致学习期进程 θ 冻结在首次抽样，2026-10-25 修正）
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
        # 缓存并钳制到 [0.01, 0.99]（上下文修正在 PareLearner.thompson_score 层）
        self._theta_cache = max(0.01, min(0.99, base))
        self._theta_dirty = False
        return self._theta_cache

    def _cap_ab(self):
        """P09：α/β 上界与软缩唯一实现（record_clean / record_probe 共用）。
        与 from_dict 的 100/50 上界一致，避免“运行期 182、重启后 100”的不一致。"""
        self.alpha = min(self.alpha, 100)
        self.beta = min(self.beta, 50)
        if self.alpha > 80:
            ratio = self.beta / max(self.alpha, 1)
            self.alpha = int(self.alpha * 0.85)
            self.beta = max(1, int(self.alpha * ratio))

    def record_clean(self, ok, freed=0, pf_delta=0, lr=None):
        """连续反馈记录清理结果 — 考虑释放质量和PF代价"""
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
        
        # 更新收益/成本 EWMA（无论成败都记录）；EFIS learning_rate 可覆盖全局 λ（lr 大=反馈适应更快）
        lam = lr if lr is not None else EWMA_LAMBDA
        lam = max(0.01, min(0.99, lam))
        if freed > 0:
            self.gain_ewma = lam * freed + (1 - lam) * self.gain_ewma
            self.gain_ewma_fast = 0.6 * freed + 0.4 * self.gain_ewma_fast
            self.gain_ewma_slow = 0.1 * freed + 0.9 * self.gain_ewma_slow
        if pf_delta >= 0:
            self.cost_ewma = lam * pf_delta + (1 - lam) * self.cost_ewma
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
            # （原"成功但零释放 → α += 0.5"已移除：见 record_probe 同款说明，2026-09-11 审查 F48）
        else:
            self.fail_cnt += 1
            self.ok_cnt = 0
            self.beta += 1
        self._cap_ab()   # P09：统一上限/软缩
        self._theta_dirty = True

    def record_probe(self, ok, lr=None, freed=0):
        """记录微型试探结果 — 连续反馈"""
        self.last_feedback_time = time.time()
        # 试探仅在确有释放时更新 Kalman（与 record_clean 同口径；0 观测会把预期释放拉向 0）
        if freed > 0:
            self.kalman.update(freed, 0)
        if ok:
            self.probe_ok += 1
            # 释放越多 → 奖励越多
            if freed > 0:
                self.probe_zero = 0
                ratio = min(3.0, freed / max(self.gain_ewma + 1, 1))
                self.alpha += 1 + min(2.0, (ratio - 1) * 1.5)
            else:
                # ⚠ 2026-09-11 审查 F48 修复：原对"成功但零释放"给 α += 0.7，对 WS≈0 的目标
                # 形成正反馈（越试 θ 越高 ⇒ 越容易被再试）。实测 373 个画像累计试探 207.6 万次、
                # 单个 2.9 MB 进程 18.1 万次、程序自身看门狗 5.0 万次。零释放只是"此处无收益"
                # 的信息，不构成"值得清"的证据 ⇒ 不再抬升 α，改为累计零释放计数驱动退避
                # （成本由退避控制，不削减对高价值目标的试探能力）
                self.probe_zero += 1
        else:
            self.probe_fail += 1
            self.beta += 1
        self._cap_ab()   # P09：探针路径此前无上限（实测 60 次后 α=182）
        self._theta_dirty = True

    @property
    def total_samples(self):
        return len(self.ws_deque)

    @property
    def roi(self):
        """成本收益比（MB/PF，与 KalmanProfile.roi 同量纲）"""
        cost = max(self.cost_ewma, 1)
        gain = max(self.gain_ewma, 0)
        return (gain / (1 << 20)) / cost if cost > 0 else 0.0

    @property
    def theta_discount(self):
        """失败折扣因子 ∈ [0.15, 1.0]（2026-11-11，决策面单一真源）。

        背景（实测）：样本满 20 后 thompson_theta 退化为 kalman_base，而 kalman 仅在
        freed>0 时更新 ⇒ "曾释放过、此后清不动"的进程预期释放与 θ 永不下降
        （60 次连续失败 θ 分毫不动）。

        ⚠ fail_cnt 的语义是「累计失败 − 成功次数」（record_clean 成功时 -1），**不等于**
        "当前清不动"。因此必须叠加连续成功回弹：ok_cnt 是连续成功数（失败即清零），
        连续成功 3 次即完全解除折扣 —— 只惩罚"最近仍在失败"的进程。
        实测 417 画像：fail_cnt>0 占 41%，若只看 fail_cnt 会把 17% 的进程长期压在 0.15×，
        其中包含刚成功过的（误伤）。加入回弹后仅惩罚真·近期失败者。
        """
        if self.fail_cnt <= 0:
            return 1.0
        k = float(min(self.fail_cnt, 6))
        if self.ok_cnt > 0:                       # 最近有成功 ⇒ 按连续成功数线性回弹
            k *= max(0.0, 1.0 - self.ok_cnt / 3.0)
        if k <= 0:
            return 1.0
        return max(0.15, 1.0 - 0.14 * k)

    @property
    def effective_freed(self):
        """预期释放量的可靠性加权值 = kalman.x_freed × theta_discount。
        theta_discount==1.0 时**逐位等于 kalman.x_freed**（新/健康进程零变化）。"""
        return self.kalman.x_freed * self.theta_discount

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
            "samples_total": self.samples_total,
            "last_drift_at": self.last_drift_at,
            "gain_ewma": self.gain_ewma, "cost_ewma": self.cost_ewma,
            "gain_ewma_fast": self.gain_ewma_fast, "gain_ewma_slow": self.gain_ewma_slow,
            "ws_ewma_mu": self.ws_ewma_mu, "ws_ewma_sigma": self.ws_ewma_sigma,
            "ok_cnt": self.ok_cnt, "fail_cnt": self.fail_cnt,
            "last_seen": self.last_seen,
            "last_feedback_time": self.last_feedback_time,
            "last_foreground_at": self.last_foreground_at,
            "last_ws": self.last_ws,
            "probe_ok": self.probe_ok, "probe_fail": self.probe_fail,
            "probe_zero": self.probe_zero,
            "leak_suspect": self.leak_suspect,
            "leak_tick_count": self.leak_tick_count,
            "clean_count": self.clean_count,
            "refill_ewma": self.refill_ewma,
            "kalman": self.kalman.to_dict(),
        }

    @classmethod
    def from_dict(cls, d):
        def _num(v, default=0.0):
            try:
                f = float(v)
            except (TypeError, ValueError):
                return default
            # 有限性守卫（与 policy 权重加载的 isfinite 同约定）：Infinity/NaN 来自状态
            # 文件介质损坏或手改——alpha=inf 会让 betavariate 无限循环挂死调用线程
            # （看门狗不触发、无自愈），int(inf) 的 OverflowError 会整条丢画像
            return f if math.isfinite(f) else default
        p = cls(str(d.get("name", "unknown")))
        # 上界对齐 record_clean 运行期软上限（100/50）：任何来源的毒值都到不了采样器
        p.alpha = max(0.5, min(100.0, _num(d.get("alpha", 1), 1)))
        p.beta = max(0.5, min(50.0, _num(d.get("beta", 1), 1)))
        p._theta_cache = None
        p._theta_dirty = True
        ws_raw = d.get("ws", [])
        p.ws_deque = deque([_num(x) for x in ws_raw if isinstance(x, (int, float))][-WINDOW:], maxlen=WINDOW)
        # P05：旧状态无 samples_total ⇒ 用窗口长度兜底（首启略低，但不会 0 造成漂移误判）
        p.samples_total = max(len(p.ws_deque), int(_num(d.get("samples_total", 0))))
        p.last_drift_at = max(0.0, _num(d.get("last_drift_at", 0.0)))
        p.gain_ewma = max(0.0, _num(d.get("gain_ewma", 0.0)))
        p.cost_ewma = max(0.0, _num(d.get("cost_ewma", 0.0)))
        p.gain_ewma_fast = max(0.0, _num(d.get("gain_ewma_fast", 0.0)))
        p.gain_ewma_slow = max(0.0, _num(d.get("gain_ewma_slow", 0.0)))
        p.ws_ewma_mu = _num(d.get("ws_ewma_mu", 0.0))
        p.ws_ewma_sigma = max(0.0, _num(d.get("ws_ewma_sigma", 0.0)))
        p.ok_cnt = max(0, int(_num(d.get("ok_cnt", 0))))
        p.fail_cnt = max(0, int(_num(d.get("fail_cnt", 0))))
        p.last_seen = _num(d.get("last_seen", 0.0))
        p.last_feedback_time = _num(d.get("last_feedback_time", 0.0))
        p.last_foreground_at = _num(d.get("last_foreground_at", 0.0))
        p.last_ws = max(0, int(_num(d.get("last_ws", 0))))
        p.probe_ok = max(0, int(_num(d.get("probe_ok", 0))))
        p.probe_fail = max(0, int(_num(d.get("probe_fail", 0))))
        p.probe_zero = max(0, int(_num(d.get("probe_zero", 0))))
        p.leak_suspect = bool(d.get("leak_suspect", False))
        p.leak_tick_count = max(0, int(_num(d.get("leak_tick_count", 0))))
        p.clean_count = max(0, int(_num(d.get("clean_count", 0))))
        p.refill_ewma = max(0.0, _num(d.get("refill_ewma", 0.0)))
        kalman_d = d.get("kalman")
        if isinstance(kalman_d, dict):
            try:
                p.kalman = KalmanProfile.from_dict(kalman_d)
            except Exception:
                pass
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
        self._ctx = {}                     # 当前系统上下文
        self._info_msgs = []
        # 稳态锚点存储（P1-D）：按可执行路径学习"应用自然稳态"，低于稳态抑制清理
        self.stable_anchors = StableAnchorStore()
        # 回弹学习（B 方案）：清后回填率 EWMA → 自动后退期（回弹高的应用不再重复白清）
        self.rebound = ReboundLearner()
    


 
    def pop_info(self):
        """取出并清空日志消息（含 Learner 自身 + 各 Profile 消息）"""
        msgs = self._info_msgs[:]
        self._info_msgs.clear()
        # 收集各 Profile 的消息（如泄漏检测）；dict() 快照迭代：手动优化线程可并发
        # 增键，直接迭代会 RuntimeError 击落守护线程（2026-08-30 审查，与 _compute_eris 同款防护）
        for p in dict(self.profiles).values():
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
            self.get(s.name).feed(s.ws, getattr(s, 'fg', False))

    # ── Thompson Sampling ──

    def thompson_score(self, name, mem_pct=None, is_fg=None):
        """t — mem_pct/is_fg 由调用方传入真实上下文，修正取实际桶；未传时回退 _ctx/默认值"""
        key = name.lower()
        if _is_system_core(key):
            return 0.0
        p = self.profiles.get(key)
        if not p or p.total_samples < 2:
            return self.prior.initial_theta(key, self.profiles)
        base = p.thompson_theta
        base *= p.theta_discount   # 失败折扣（2026-11-11，单一真源；健康进程恒为 1.0）
        if mem_pct is None:
            mem_pct = self._ctx.get("mem_pct", 50)
        if is_fg is None:
            is_fg = self._ctx.get("is_fg", False)
        uncertainty = max(0, 0.12 - p.confidence * 0.12)
        result = min(0.99, base + uncertainty)
        result = max(0.01, min(0.99, result))
        return result

    def get_profile(self, name):
        return self.profiles.get(name.lower())

    def top(self, n=25):
        """按 ROI 降序返回前 n 个有学习样本的进程 (name, roi, theta, profile)。
        CLI learn/profile 使用；无样本进程不参与排名。"""
        cands = [(name, p.roi, self.thompson_score(name), p)
                 for name, p in self.profiles.items() if p.total_samples >= 2]
        cands.sort(key=lambda x: x[1], reverse=True)
        return cands[:n]

    # ── 持久化 ──

    def save(self, path):
        with _SAVE_LOCK:
            try:
                now = time.time()
                cutoff = 86400 * 7
                # dict() 快照迭代（2026-09-06 审查 F2）：_SAVE_LOCK 只防 save 间并发，
                # 不防 get() 增键——快照防 RuntimeError 致该轮保存静默丢失
                filtered = {
                    k: v for k, v in dict(self.profiles).items()
                    if now - v.last_seen < cutoff or v.alpha != 2 or v.beta != 1
                }
                # 内存侧同口径淘汰（2026-09-11 审查 F26）：落盘过滤只作用在文件上，内存字典会
                # 无界增长（实测 200 条画像仅 0 条落盘）。判据与落盘完全一致 ⇒ 行为差为零
                # （这些画像重启后本就不复存在），只是把内存也一并释放。
                for _k in [k for k, v in dict(self.profiles).items()
                           if now - v.last_seen >= cutoff and v.alpha == 2 and v.beta == 1]:
                    self.profiles.pop(_k, None)
                data = {
                    "version": 4,
                    "profiles": {k: v.to_dict() for k, v in filtered.items()},
                    "stable_anchors": self.stable_anchors.to_dict(),
                    "rebound": self.rebound.to_dict(),
                }
                # tmp 附加进程号（2026-09-06 审查 F3）：进程内锁不跨进程——CLI daemon 与
                # GUI 并发保存时各写各的 tmp，os.replace 原子替换，退化为"最后写者胜"
                # 而非同 tmp 交错损坏
                tmp = f"{path}.{os.getpid()}.tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(data, f)
                os.replace(tmp, path)
                return True
            except Exception:
                return False

    @classmethod
    def load(cls, path):
        """加载画像：单个坏画像只跳过该条（不再整体丢弃），解析失败返回空学习器"""
        learner = cls()
        if not path or not os.path.isfile(path):
            return learner
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return learner
        profiles = data.get("profiles", {})
        if not isinstance(profiles, dict):
            return learner
        for k, v in profiles.items():
            if not isinstance(v, dict):
                continue
            try:
                learner.profiles[k] = Profile.from_dict(v)
            except Exception:
                continue  # 坏条目跳过，保留其余画像
        learner.stable_anchors = StableAnchorStore.from_dict(data.get("stable_anchors"))
        learner.rebound = ReboundLearner.from_dict(data.get("rebound"))
        # 旧状态里的 ctx_corrections / policy 字段（2026-11-08 / 2026-11-10 弃用）
        # 直接忽略——不报错、不写回
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
