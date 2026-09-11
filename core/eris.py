# -*- coding: utf-8 -*-
"""ERIS v7 效率评分 — 纯函数核心（生产与回归共用，杜绝测试副本与生产分歧）

v7 设计（2026-09-11 用户主导定稿，见记忆 learning-engine-specs §B4）：
  · 五维各 0~100 分（可超常溢出至 140），以"长期实测可达到的理想"为 100 分
  · 赋分 = 四锚点分段线性：p10→20 / p50→50 / p90→80 / p99→110，之外按段斜率延伸（下限 0、上限 140）
  · 锚点为**一次冻结的标尺**：50 分 = 该维历史中位，100 分 = 突破历史高位
  · 效率值 = Σ(五维分) ÷ K × 100，K = 实测总分分布 p90（冻结）
  · 每维原始值先做 N=3 滚动中位（压测量噪声）
  · 词条：升 → "本轮分数上升"的维中取最高分者报正面；降 → "本轮分数下降"的维中取最低分者报负面

② 自校准（2026-09-11 用户定稿，天花板级实现）：
  · 动机：锚点是本机实测标尺，换机器会整体错位（严重时让"最高/最低分维"常年固定 ⇒ 词条不再轮换）
  · 做法：代码里的 DIM_ANCHORS/EFF_K 永远是**冷启动基准**；运行中用每维 q10/q50/q90 的
    慢速 EWMA 分位估计（α=CALIB_ALPHA ⇒ 时间常数约 100 轮）做**中心 + 跨度**双向校正，
    把本机原始值映射到冷启动标尺的坐标系后再计分
  · 三重约束（缺一不可）：①**淡入**（前 blend_n 轮按 n/blend_n 线性生效，冷启动首轮即可用、无突跳）
    ②**限幅**（中心最多偏移半个冷启动跨度；跨度比限制在 [0.7, 1.4]）——限幅同时保证
    "引擎持续变好时分数仍能突破 100%"（进步可见性不被自校准吃掉）
    ③**独立存储**（校准数据单独文件、不进配置包、恢复默认显式清除）——见记忆 §B5

  自校准只影响"取数"，不改标尺形状；删除校准文件即回到已知良好的冷启动状态（可回退、可复现）。
"""
import math
from collections import deque

SMOOTH_N = 3          # 每维原始值的滚动中位窗口
SCORE_FLOOR = 0.0     # 维度分下限
SCORE_CAP = 140.0     # 维度分上限（超常溢出区）

# ── 五维词条（顺序即维度索引；统一四字、正负对应）──
DIM_WORDS = [
    ("↑预测精准", "↓预测偏差"),
    ("↑释放彻底", "↓释放不全"),
    ("↑清理畅通", "↓清理受阻"),
    ("↑副作用低", "↓副作用高"),
    ("↑试探高效", "↓试探低效"),
]

# ── 冻结锚点（每维 [p10, p50, p90, p99] 原始值 → 20/50/80/110 分）──
# 来源：2026-09-11 标定（受控长跑 45 轮 N=3 平滑序列；维度 5 用历史日志 1344 轮）
# 顺序：0 预测精准 / 1 释放彻底(释放÷惯常释放) / 2 清理畅通(成功率比) / 3 副作用(释放MB÷PF，对数维) / 4 试探高效
NORMAL = [
    [0.319025, 0.341208, 0.349051, 0.352497],   # 0 预测精准
    [0.858544, 0.990660, 1.036130, 1.101300],   # 1 释放彻底
    [1.176470, 2.000000, 2.750000, 3.500000],   # 2 清理畅通
    [0.0178382, 0.0298446, 0.0887109, 0.3430170],  # 3 副作用（对数维）
    [0.281690, 0.356083, 0.409556, 0.453988],   # 4 试探高效
]
FULL = [
    [0.2746, 0.2937, 0.3005, 0.3034],      # 0 预测精准（full：预测基于常态样本，误差更大）
    [0.6701, 0.7732, 0.8087, 0.8596],      # 1 释放彻底
    [32.12, 54.60, 75.08, 95.55],          # 2 清理畅通（full 成功远多于失败 ⇒ 比值量级完全不同）
    [0.03036, 0.05079, 0.1510, 0.5838],    # 3 副作用（对数维）
    [0.3955, 0.5000, 0.5751, 0.6375],      # 4 试探高效（full 模式样本少，后续由自校准细化）
]
# 按清理模式分别标定（2026-09-11 用户定稿）：模式间同一维度的量级差异极大（如"清理畅通"在
# full 下是 normal 的 10~20 倍），共用一套必然被顶到分数上限 ⇒ 按模式分套；deep/quick 样本
# 不足，先以 normal 起步，由**按模式分桶的自校准**在使用中细化。
DEEP = [
    [0.296813, 0.317454, 0.324775, 0.327948],
    [0.764322, 0.88193, 0.922415, 0.98045],
    [16.6482, 28.3, 38.915, 49.525],
    [0.024099, 0.040317, 0.119855, 0.463409],
    [0.338595, 0.428041, 0.492328, 0.545744],
]
DIM_ANCHORS_BY_MODE = {
    "normal": NORMAL,
    "deep": DEEP,
    "quick": [list(a) for a in NORMAL],
    "full": FULL,
}
EFF_K_BY_MODE = {"normal": 290.1, "deep": 315.0, "quick": 290.1, "full": 341.0}
DIM_ANCHORS = DIM_ANCHORS_BY_MODE["normal"]      # 兼容别名（normal 模式）
EFF_K = EFF_K_BY_MODE["normal"]


# 副作用维长尾（p99/p50 ≈ 65 倍）：进入映射前先取对数
LOG_DIMS = (3,)

# 极性阈值：超常 = 效率分布 p90（= K 定义处，约一成轮次）；异常固定 50%（用户定稿：
# 不要求必有一成预警，只要 0~50% 理论可达）
SUPER_TH = 100.0
WARN_TH = 50.0

# ── ② 自校准参数 ──
CALIB_ALPHA = 0.01                 # 稳态每轮步长（时间常数 ≈ 100 轮，抗单轮噪声）
CALIB_ALPHA_FAST = 0.03            # 暖机期步长（时间常数 ≈ 33 轮 ⇒ 新机器约 1~2 小时归位）
CALIB_FAST_N = 200                 # 暖机期轮数（此后转稳态慢速）
CALIB_SPREAD_N = 200               # 跨度校正淡入轮数：暖机期只用中心校正，避免两项互相抵消
CALIB_BLEND_N = 100                # 淡入轮数（前 N 轮线性生效）
CALIB_SHIFT_MAX = 0.5              # 中心位移限幅（相对冷启动 p10-p90 跨度）
CALIB_SCALE_RANGE = (0.70, 1.40)   # 跨度比限幅（双向）


def anchors_for(mode=None):
    """该清理模式的锚点（未知模式回退 normal）"""
    return DIM_ANCHORS_BY_MODE.get(mode or "normal", DIM_ANCHORS_BY_MODE["normal"])


def k_for(mode=None):
    """该清理模式的联合理想总分（100% 对应处）"""
    return EFF_K_BY_MODE.get(mode or "normal", EFF_K_BY_MODE["normal"])


def _u(x, log_scale=False):
    """原始值 → 标尺空间值（对数维取自然对数）；None 表示"无数据"（返回 None，由调用方中性处理）"""
    if x is None:
        return None
    try:
        v = float(x)
    except Exception:
        return 0.0
    if not math.isfinite(v):
        return 0.0
    return math.log(max(v, 1e-12)) if log_scale else v


def smooth3_append(hist, raw):
    """滚动中位：把 raw 追加进 hist（长度 ≤ SMOOTH_N），返回当前窗口的中位值"""
    hist.append(raw)
    v = sorted(hist)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def _score_u(u, au):
    """标尺空间四锚点分段线性：20/50/80/110，之外按段斜率延伸，钳制 [0, 140]"""
    try:
        x0, x1, x2, x3 = (float(a) for a in au)
    except Exception:
        return 50.0
    pts = [(x0, 20.0), (x1, 50.0), (x2, 80.0), (x3, 110.0)]
    try:
        if u <= x0:
            k = (50.0 - 20.0) / (x1 - x0) if x1 > x0 else 0.0
            return max(SCORE_FLOOR, 20.0 + k * (u - x0))
        for i in range(3):
            xa, ya = pts[i]
            xb, yb = pts[i + 1]
            if u <= xb:
                return ya + (yb - ya) * (u - xa) / (xb - xa) if xb > xa else ya
        k = (110.0 - 80.0) / (x3 - x2) if x3 > x2 else 0.0
        return min(SCORE_CAP, 110.0 + k * (u - x3))
    except Exception:
        return 50.0


def dim_score(raw, anchors, log_scale=False):
    """单维赋分（冷启动口径，不做自校准；回归测试与冷启动路径共用）"""
    return _score_u(_u(raw, log_scale), [_u(a, log_scale) for a in anchors])


def anchors_center_span(anchors, log_scale=False):
    """冷启动锚点在标尺空间的中位与跨度（p90−p10）"""
    au = [_u(a, log_scale) for a in anchors]
    return au[1], max(au[2] - au[0], 1e-9)


def scores_of(raws, anchors=None, log_dims=LOG_DIMS, mode=None):
    """五维原始值 → 五维分数（冷启动口径，不做自校准）"""
    A = anchors or anchors_for(mode)
    return [dim_score(raws[j], A[j], log_scale=(j in log_dims)) for j in range(len(A))]


def efficiency(scores, K=None, mode=None):
    """总分 → 效率百分比（100% = 该模式的联合理想总分）"""
    k = float(K or k_for(mode))
    return (sum(scores) / k * 100.0) if k > 0 else 0.0


def pick_factor(scores, prev_scores, up):
    """词条维度选择：升 → 本轮上升维中最高分者；降 → 本轮下降维中最低分者。
    返回维度索引；无候选（含并列未变化）返回 None（由调用方兜底）。"""
    if not prev_scores or len(prev_scores) != len(scores):
        return None
    cand = [j for j in range(len(scores)) if (scores[j] > prev_scores[j]) == bool(up)
            and scores[j] != prev_scores[j]]
    if not cand:
        return None
    return max(cand, key=lambda j: scores[j]) if up else min(cand, key=lambda j: scores[j])


def new_state():
    """ERIS v7 运行状态（每维滚动窗 + 上轮五维分 + 上轮效率 + 趋势方向序列）"""
    return {
        "hist": [deque(maxlen=SMOOTH_N) for _ in DIM_ANCHORS],
        "prev_scores": None,
        "prev_eff": None,
        "trend": [],
    }


# ══════════════════════════════════════════════════════════════════════
# ② 自校准：冷启动标尺 + 长周期爬行（中心 + 跨度；淡入 + 限幅；可回退）
# ══════════════════════════════════════════════════════════════════════

def new_calib():
    """校准状态容器（v2：按模式分桶；文件缺失即冷启动）"""
    return {"v": 2, "modes": {}}


def _bucket(calib, mode):
    """取该模式的校准桶（v1 旧结构自动迁入 normal 桶）"""
    if calib.get("v") != 2:
        old = {"n": int(calib.get("n", 0)), "init": bool(calib.get("init")),
               "dims": calib.get("dims") if isinstance(calib.get("dims"), list)
               else [[0.0, 0.0, 0.0] for _ in DIM_ANCHORS]}
        calib.clear()
        calib.update({"v": 2, "modes": {"normal": old}})
    return calib.setdefault("modes", {}).setdefault(
        mode, {"n": 0, "init": False, "dims": [[0.0, 0.0, 0.0] for _ in DIM_ANCHORS]})


def calib_valid(calib):
    """校验持久化结构（版本/维度数/每维三分位/数值合法性）"""
    try:
        if not isinstance(calib, dict):
            return False
        if calib.get("v") == 1:                     # 旧结构（单桶）兼容
            dims = calib.get("dims")
            if not isinstance(dims, list) or len(dims) != len(DIM_ANCHORS):
                return False
            n = calib.get("n", 0)
            if not isinstance(n, int) or n < 0:
                return False
            return all(isinstance(o, list) and len(o) == 3 and
                       all(isinstance(v, (int, float)) and math.isfinite(v) for v in o) for o in dims)
        if calib.get("v") != 2:
            return False
        modes = calib.get("modes")
        if not isinstance(modes, dict):
            return False
        for one in modes.values():
            if not isinstance(one, dict):
                return False
            dims = one.get("dims")
            if not isinstance(dims, list) or len(dims) != len(DIM_ANCHORS):
                return False
            for o in dims:
                if not isinstance(o, list) or len(o) != 3:
                    return False
                for v in o:
                    if not isinstance(v, (int, float)) or not math.isfinite(v):
                        return False
            n = one.get("n", 0)
            if not isinstance(n, int) or n < 0:
                return False
        return True
    except Exception:
        return False


def _q_step(est, u, alpha, q):
    """非对称 EWMA 分位跟踪：收敛到 **q 分位**（q=0.5 即对称中位）。

    平衡条件：样本高于估计的比例 p 满足 p·up = (1−p)·dn ⇒ p = 1−q ⇒
    估计落在"上方仅占 (1−q)"的位置，即 q 分位。故 up = α·q、dn = α·(1−q)。
    对离群稳健（单轮步长有界）：α 小 ⇒ 慢速爬行。"""
    up = alpha * q
    dn = alpha * (1.0 - q)
    return est + (up if u > est else dn) * (u - est)


def calibrate_and_score(raws, calib, blend_n=CALIB_BLEND_N, update=True, alpha=None,
                        skip=None, mode=None):
    """② 冷启动 + 长周期自校准：返回 (五维分数, 校准状态)。

    · 每维维护 q10/q50/q90 分位估计，**暖机期用较大步长、之后转慢**（两段速率：
      n < CALIB_FAST_N 用 CALIB_ALPHA_FAST，之后用 CALIB_ALPHA）——新机器约 1~2 小时归位，
      长期又不会被单轮噪声带动（对照实测：单用慢速时 45 轮内几乎无校正）
    · 校正：u' = m_cold + shift + (u − q50) × (span_cold / span_local)
      shift = clamp(q50 − m_cold, ±0.5×span_cold)；跨度比 clamp 到 [0.70, 1.40]
    · 淡入：w = min(1, n/blend_n)，u_use = (1−w)·u + w·u' ⇒ 冷启动首轮即用、无突跳
    · 播种：首轮用冷启动锚点填充 q10/q50/q90（而非首个观测）⇒ 暖机期校正恒等，
      不会出现"跨度被低估 ⇒ 校正比放大 ⇒ 曲线被自抬"的暂态偏差
    · 不改变标尺形状（锚点仍是 DIM_ANCHORS）；删除校准数据即回到冷启动
    """
    # 按模式分桶（2026-09-11）：各模式的分布不同 ⇒ 校准数据必须分模式存储，互不污染
    _m = mode or "normal"
    bucket = _bucket(calib, _m)
    dims = bucket.get("dims")
    if not isinstance(dims, list) or len(dims) != len(DIM_ANCHORS):
        dims = [[0.0, 0.0, 0.0] for _ in DIM_ANCHORS]
        bucket["dims"] = dims
    init = bool(bucket.get("init"))
    a_now = CALIB_ALPHA if alpha is None else alpha
    if int(bucket.get("n", 0)) < CALIB_FAST_N:
        a_now = max(a_now, CALIB_ALPHA_FAST)
    n_dim = min(len(raws), len(DIM_ANCHORS))
    for j in range(n_dim):
        if skip and skip[j]:
            continue                      # 无数据维：不更新分位跟踪器（防被占位值污染）
        u = _u(raws[j], j in LOG_DIMS)
        if u is None:
            continue
        st = dims[j]
        if not init:
            # 用冷启动锚点播种（而非首个观测）：暖机期校正恒等 ⇒ 不会出现"跨度被低估 ⇒
            # 校正比放大 ⇒ 曲线被自抬"的暂态偏差（2026-09-11 对照实测发现并修正）
            au = [_u(a, j in LOG_DIMS) for a in anchors_for(_m)[j]]
            st[0], st[1], st[2] = au[0], au[1], au[2]
        elif update:
            st[0] = _q_step(st[0], u, a_now, 0.10)
            st[1] = _q_step(st[1], u, a_now, 0.50)
            st[2] = _q_step(st[2], u, a_now, 0.90)
    if update:
        bucket["init"] = True
        bucket["n"] = int(bucket.get("n", 0)) + 1
    w = min(1.0, int(bucket.get("n", 0)) / float(blend_n)) if blend_n else 1.0
    scores = []
    for j in range(len(DIM_ANCHORS)):
        if (skip and skip[j]) or j >= n_dim or raws[j] is None:
            scores.append(50.0)                # 无数据/维度不足 ⇒ 中性 50 分（不进映射）
            continue
        log_j = j in LOG_DIMS
        u = _u(raws[j], log_j)
        st = dims[j]
        m_cold, span_cold = anchors_center_span(anchors_for(_m)[j], log_j)
        lim = CALIB_SHIFT_MAX * span_cold
        shift = max(-lim, min(lim, st[1] - m_cold))
        lo, hi = CALIB_SCALE_RANGE
        ratio = max(lo, min(hi, span_cold / max(st[2] - st[0], 1e-9)))
        # 跨度校正随样本量淡入（暖机期只用中心校正）：否则中心跟踪器的滞后会让
        # "相对中心项"反向抵消中心校正（2026-09-11 对照实测发现）
        w_sp = min(1.0, int(calib.get("n", 0)) / float(CALIB_SPREAD_N)) if CALIB_SPREAD_N else 1.0
        ratio = 1.0 + (ratio - 1.0) * w_sp
        u_cal = m_cold + shift + (u - st[1]) * ratio
        u_use = u if w <= 0.0 else (1.0 - w) * u + w * u_cal
        scores.append(_score_u(u_use, [_u(a, log_j) for a in anchors_for(_m)[j]]))
    return scores, calib
