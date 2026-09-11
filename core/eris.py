# -*- coding: utf-8 -*-
"""ERIS v7 效率评分 — 纯函数核心（生产与回归共用，杜绝测试副本与生产分歧）

v7 设计（2026-09-11 用户主导定稿，见记忆 learning-engine-specs §B4）：
  · 五维各 0~100 分（可超常溢出至 140），**不是为了评价绝对完美，而是以"长期实测可达到的理想"为 100 分**
  · 赋分 = 四锚点分段线性：p10→20 / p50→50 / p90→80 / p99→110，之外按段斜率延伸（下限 0、上限 140）
  · 锚点为**一次冻结的标尺**（长期实测分位），不做滚动归一化 ⇒ 分数是固定标尺上的读数：
    50 分 = 该维历史中位水平；100 分 = 突破历史高位；引擎变强则整体上移（超常可 >100）
  · 效率值 = Σ(五维分) ÷ K × 100，K = 实测总分分布 p90（冻结）⇒ 100% = 五维同时处于历史高位
  · 每维原始值先做 N=3 滚动中位（压测量噪声；实测抖动降 50~77%、方向翻转率 63%→50%）
  · 词条：效率升 → 在"本轮分数上升"的维中取最高分者报正面词条；
          效率降 → 在"本轮分数下降"的维中取最低分者报负面词条（无防振荡/防垄断硬规则）
"""
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
DIM_ANCHORS = [
    [0.319025, 0.341208, 0.349051, 0.352497],
    [0.858544, 0.990660, 1.036130, 1.101300],
    [1.176470, 2.000000, 2.750000, 3.500000],
    [0.0178382, 0.0298446, 0.0887109, 0.3430170],
    [0.281690, 0.356083, 0.409556, 0.453988],
]
# 副作用维长尾（p99/p50 ≈ 65 倍）：进入映射前先取对数
LOG_DIMS = (3,)

EFF_K = 290.1         # 总分分布 p90（2026-09-11 实测：该点恰为 100%）
# 极性阈值：超常 = 效率分布 p90（= K 定义处，约一成轮次）；异常固定 50%（用户 2026-09-11 定稿：
# 不要求必有一成预警，只要 0~50% 理论可达；新标尺下 50% 命中约 2%）
SUPER_TH = 100.0
WARN_TH = 50.0


def smooth3_append(hist, raw):
    """滚动中位：把 raw 追加进 hist（长度 ≤ SMOOTH_N），返回当前窗口的中位值"""
    hist.append(raw)
    v = sorted(hist)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def dim_score(raw, anchors, log_scale=False):
    """四锚点分段线性赋分：p10→20 / p50→50 / p90→80 / p99→110，之外按段斜率延伸。
    log_scale=True 时先对 raw 与锚点取自然对数（处理长尾维度）。"""
    import math
    if log_scale:
        try:
            raw = math.log(max(float(raw), 1e-9))
            anchors = [math.log(max(float(a), 1e-9)) for a in anchors]
        except Exception:
            return 50.0
    x0, x1, x2, x3 = (float(a) for a in anchors)
    pts = [(x0, 20.0), (x1, 50.0), (x2, 80.0), (x3, 110.0)]
    try:
        if raw <= x0:
            k = (50.0 - 20.0) / (x1 - x0) if x1 > x0 else 0.0
            return max(SCORE_FLOOR, 20.0 + k * (raw - x0))
        for i in range(3):
            xa, ya = pts[i]
            xb, yb = pts[i + 1]
            if raw <= xb:
                if xb <= xa:
                    return ya
                return ya + (yb - ya) * (raw - xa) / (xb - xa)
        k = (110.0 - 80.0) / (x3 - x2) if x3 > x2 else 0.0
        return min(SCORE_CAP, 110.0 + k * (raw - x3))
    except Exception:
        return 50.0


def scores_of(raws, anchors=None, log_dims=LOG_DIMS):
    """五维原始值 → 五维分数（长度对齐 DIM_ANCHORS）"""
    A = anchors or DIM_ANCHORS
    return [dim_score(raws[j], A[j], log_scale=(j in log_dims)) for j in range(len(A))]


def efficiency(scores, K=None):
    """总分 → 效率百分比（100% = 联合理想 K 分）"""
    k = float(K or EFF_K)
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
    """ERIS v7 运行状态（仅需：每维滚动窗 + 上轮五维分 + 上轮效率 + 趋势方向序列）"""
    return {
        "hist": [deque(maxlen=SMOOTH_N) for _ in DIM_ANCHORS],
        "prev_scores": None,
        "prev_eff": None,
        "trend": [],
        "prev_factor_dim": -1,
        "prev_factor_pos": None,
    }

# ══════════════════════════════════════════════════════════════════════
# v6 旧核心（IQR 自归一化）—— 引擎尚未切换，暂时保留以保证仓库可用；
# v7 引擎切换完成并回归通过后移除（设计依据见记忆 learning-engine-specs §B4）
# ══════════════════════════════════════════════════════════════════════

def iqr_dim(raw, buf, p50_ewma, iqr_ewma, update_state=True):
    """单维 IQR 归一化 → 0-130 分（80 中性）。分支：nL>=4 trimmed IQR；nL=2/3 p50*10% 尺度；nL<2 中性 80"""
    if update_state:
        buf.append(raw)
    L = sorted(list(buf))
    nL = len(L)
    if nL >= 4:
        T = L[1:-1]
        nT = len(T)
        if nT % 2 == 0:
            p50_raw = (T[nT // 2 - 1] + T[nT // 2]) / 2.0
        else:
            p50_raw = T[nT // 2]
        h25 = (nT + 1) * 0.25
        lo25 = max(0, int(h25) - 1)
        hi25 = min(lo25 + 1, nT - 1)
        frac25 = h25 - int(h25)
        q1 = T[lo25] * (1 - frac25) + T[hi25] * frac25
        h75 = (nT + 1) * 0.75
        lo75 = max(0, int(h75) - 1)
        hi75 = min(lo75 + 1, nT - 1)
        frac75 = h75 - int(h75)
        q3 = T[lo75] * (1 - frac75) + T[hi75] * frac75
        actual_iqr = q3 - q1
        if update_state:
            p50_ewma = 0.15 * p50_raw + 0.85 * p50_ewma
        p50 = p50_raw if nL < 5 else (p50_ewma if p50_ewma > 0 else p50_raw)
        if update_state and actual_iqr > 0 and nL >= 5:
            iqr_ewma = 0.30 * actual_iqr + 0.70 * iqr_ewma
        floor_iqr = max(p50_raw * 0.10, iqr_ewma * 0.20)
        iqr = max(actual_iqr, floor_iqr, 0.01)
        dim = 80.0 + 40.0 * (raw - p50) / iqr
    elif nL >= 2:
        p50_raw = L[nL // 2]
        if update_state:
            p50_ewma = 0.15 * p50_raw + 0.85 * p50_ewma
        p50 = p50_raw if nL < 5 else (p50_ewma if p50_ewma > 0 else p50_raw)
        dim = 80.0 + 40.0 * (raw - p50) / max(p50 * 0.10, 0.01)
    else:
        dim = 80.0
        p50_raw = 0.0
    return max(1.0, min(130.0, dim)), p50_ewma, iqr_ewma


def validate_state(bufs, ewma_list, windows):
    """校验 v6 ERIS 持久化状态结构（维度数/窗口上限/数值合法性）"""
    import math
    if not isinstance(bufs, list) or not isinstance(ewma_list, list):
        return False
    if len(bufs) != len(windows) or len(ewma_list) != len(windows):
        return False
    for j, (b, w) in enumerate(zip(bufs, windows)):
        if not isinstance(b, (list, deque)):
            return False
        if len(b) > w:
            return False
        for v in b:
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                return False
        if not isinstance(ewma_list[j], (int, float)) or not math.isfinite(ewma_list[j]) or ewma_list[j] < 0:
            return False
    return True
