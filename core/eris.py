# -*- coding: utf-8 -*-
"""ERIS v9 效率评分 — 冻结基线 + 分位映射（纯函数核心；生产与回归共用，杜绝测试副本与生产分歧）

v9 设计（2026-09-26 用户定稿，整体替换 v8 的"滚动分位 + 四锚点分段"）：
  · **参照 = 冻结的本机基线**：每个模式**跳过前 CALIB_SKIP 轮（学习预热期）**后累积 CALIB_N 轮，
    期满实测该模式每维的 p05/p25/p50/p75/p90 并**冻结**写入 calib 文件；此后同一原始值**永远**
    得同一分——读数不再随时间/使用时段漂移（用户要求：效率不该管"几点用"），也不再"同值异分"。
  · **映射 = 分位曲线**：p05/p25/p50/p75/p90 → 20/35/50/65/80，两端按局部斜率线性外推、钳 [0,140]。
    单调、无退化段、无"深段过窄一步归零"。窄分布维（跨度 < MIN_REL_SPAN×中位）按该下限展宽，
    防"微变即满量程"（实测本机四维跨度 19%~367%）。
  · **五维全部有界比值、越大越好**（都为优化本身服务）：
      0 ↑净优化量高  本轮净下降 ÷ 本轮总释放           释放留得住吗（净存下的比例）
      1 ↑优化代价低  进程释放 MB ÷ 缺页代价          每单位代价换回多少（划不划算）
      2 ↑优化高通畅  成功 ÷（成功 + 失败）           被阻塞得少吗
      3 ↑试探命中高  试探合格 ÷ 试探总数             探索有效吗
      4 ↑优化量可观  本轮释放 ÷ 基线释放量           清得多吗
  · **K = 自标定期总分 p92**（固定值 ⇒ 100% ≡ 本机典型高位，超常/异常率与日期无关）。
    实测（本机两周 1670 轮 full 回放）：平均 74.0、超常 6.2%、异常 7.2%、平均环比 |Δ| 6.2 分。
  · 长期偏离自检（**自指检验，不用固定带**）：冻结时记录窗口内总分中位对应的读数（期望中位），
    之后把近 LONG_WIN 轮的中位与之比较，偏差 > LONG_TOL 个百分点即重标一次并留痕——
    既能在冻结后一个窗口内发现"标定窗口不典型"（读数常年偏低/偏高），也能兜住机器永久性改变。
    删 calib 文件即回到出厂种子、重新标定。
  · 无数据维记中性 50，并按模式**声明维**稀释（防单维独大）；游戏轮次照常算分、不喂标定。
  · 相对 v8 删除的机制（不留残留）：滚动分位 EWMA 跟踪（Q_ALPHA_MULT/CALIB_ALPHA*/
    CALIB_FAST_N）、四锚点 ladder/段宽下限 SEG_FRAC/跨度下限 SPAN_FLOOR*/深段 gap、对数维
    LOG_DIMS、滚动 K 窗口（K_WIN/K_SEED_N）、预热收缩与滚动 K 更新。
  · 效率值**只用于展示**，不参与清理与调参决策 ⇒ 无"分数→行为→分数"自激回路。
"""
from collections import deque
import math

SMOOTH_N = 3          # 每维原始值的滚动中位窗口（压测量噪声）
SCORE_FLOOR = 0.0     # 维度分下限
SCORE_CAP = 140.0     # 维度分上限（超常溢出区）
ERIS_STATE_V = 8      # 平滑窗文件 schema：8 = 按清理模式分桶（8 起结构未变，v9 沿用）
CALIB_STATE_V = 5     # 校准文件 schema：5 = 冻结基线（每模式每维五点 + K）+ 标定窗口 + 漂移看护
                      # ≤4 = 旧"滚动分位/冻结表"语义（已废弃，加载时丢弃重建为种子）

# ── 标定与映射参数 ──
CALIB_SKIP = 200         # 标定前跳过轮数：前 200 轮是学习预热期（实测④试探成功率中位 0.443，
                         # 稳态仅 0.25；③⑤亦不同）⇒ 混入会把基线带偏
CALIB_N = 300            # 标定窗口轮数（跳过预热期后累积；实测窗口内各维中位与长期值差 <10%）
K_QUANTILE = 0.92        # K = 标定窗口总分该分位点。离线回放三分位对比（本机两周 1670 轮）：
                         #   p90 → 平均 79.6 / 超常 14.3% / 异常 3.1%
                         #   p92 → 平均 ~77   / 超常 ~12%  / 异常 ~5%   ← 取此：均值稳在 70~80、
                         #   p95 → 平均 72.7 / 超常 8.8%  / 异常 11.4%     异常"基本没有"、超常"偶尔"
                         # （目标来自用户 2026-09-26：平均 70~80、偶尔超长、基本没什么异常）
LONG_WIN = 200           # 偏离自检的滚动窗口（轮）：窗口满即判定（实测该窗口下两周数据零误报）
LONG_TOL = 15.0          # 容忍度（效率百分点）：窗口内总分中位与冻结时期望中位之差超过它 ⇒ 重标
                         # 实测标定：12 会因"某段持续偏糟的日子"（偏差约 13 分）误报 1 次；
                         # 15 零误报，而"标定窗口不典型"这类真问题偏差 30 分以上 ⇒ 仍能抓住
MIN_REL_SPAN = 0.80      # 基线相对跨度下限（实测扫描 0.30/0.45/0.60/0.80 后取值）：
                         # 展宽越小分布越尖（异常率 9.8%），越大越平（0.80 ⇒ 异常 7.2%、超常 6.2%、
                         # 平均 74.0、平均|Δ| 6.2、标定前后几乎无跳变 75.4/73.4）⇒ 取 0.80
                         # 目的：让"异常/超常"只在真实偏离时触发（用户目标：基本没什么异常）
PROVISIONAL_SPAN = 0.80  # 未标定模式（种子期）的展宽：种子较粗 ⇒ 映射放宽，早期读数偏中性而不尖
LIVE_MIN = 30            # 标定期临时基线开始掺入「窗口实测分位」的最小样本数
LIVE_FULL = 150          # 掺入比例到 1.0 的样本数（此后完全用窗口实测 ⇒ 与冻结值一致、不跳变）
                         # 动机（2026-09-26 实测）：出厂种子会因**程序自身行为变化**而过期
                         # （本机新构建的缺页中位 175 vs 旧 11,000~33,000，差 100 倍）——
                         # 靠窗口自校正比手改种子更稳，也消除冻结瞬间的跳变
Q_ANCHORS = (0.05, 0.25, 0.50, 0.75, 0.90)
SCORE_ANCHORS = (20.0, 35.0, 50.0, 65.0, 80.0)

# ── 五维词条（顺序即维度索引；正负对应；2026-09-26 用户定稿为「优化」口径）──
DIM_WORDS = [
    ("↑净优化量高", "↓净优化量低"),
    ("↑优化代价低", "↓优化代价高"),
    ("↑优化高通畅", "↓优化受阻碍"),
    ("↑试探命中高", "↓试探命中低"),
    ("↑优化量可观", "↓优化量偏少"),
]

# 各模式声明维（无数据维按中性 50 参与稀释；quick 不做进程清理 ⇒ 只有"留住/规模"两维有作用面）
MODE_VALID_DIMS = {
    "quick": (0, 4),
    "normal": (0, 1, 2, 3, 4),
    "deep": (0, 1, 2, 3, 4),
    "full": (0, 1, 2, 3, 4),
}

# ── 出厂种子：每维五点基线 [p05,p25,p50,p75,p90]（顺序：0 净优化量 / 1 优化代价 / 2 优化通畅 / 3 试探命中 / 4 优化量）──
# 来源（full 为本机实测，2026-09-26 由 1670 轮日记回放测得）：
#   1 优化代价 / 2 优化通畅 / 3 试探命中 / 4 优化量 = 直接实测分位；
#   0 净优化量 = 净留存率口径（释放以系统级待机回收为大头、净留存为其中一部分；2026-09-27
#     维度重定义后按实机观察估值，未冻结期读数偏中性、由自标定收敛到本机分布）；
#   其余模式本机无数据 ⇒ 借用 full 值作先验（自标定 200 轮内会被本机实测覆盖，种子只影响开局读数）。
SEED_BASE_BY_MODE = {
    "full": [[0.03, 0.07, 0.12, 0.18, 0.28],
             [0.000162, 0.000471, 0.00108, 0.00224, 0.00413],
             [0.826, 0.963, 0.972, 0.980, 0.984],
             [0.121, 0.198, 0.264, 0.340, 0.415],
             [358.0, 754.0, 1024.0, 1638.0, 2355.0]],
}
# K 种子（种子期用；标定期满会被本机实测取代）。校准依据：使种子期的读数水平与冻结后一致
# （离线回放：SEED_K=320 时种子期均值 89.6、冻结后 69.0 ⇒ 取 370 令两段都在 75 上下，消除跳变）
SEED_K = 370.0

# 极性阈值：超常 = 效率 ≥100%（K 的定义处）；异常 = ≤50%
SUPER_TH = 100.0
WARN_TH = 50.0


def seeds_for(mode=None):
    """该模式的种子五点基线（未知模式回退 full 实测值）"""
    t = SEED_BASE_BY_MODE.get(mode or "full") or SEED_BASE_BY_MODE["full"]
    return [list(x) for x in t]


def k_seed(mode=None):
    return SEED_K


def valid_dims(mode=None, nodata=None):
    """该模式的有效维（去掉无数据维）"""
    dims = MODE_VALID_DIMS.get(mode or "normal", MODE_VALID_DIMS["normal"])
    if nodata:
        dims = tuple(j for j in dims if not (j < len(nodata) and nodata[j]))
    return dims


def smooth3_append(hist, raw):
    """滚动中位：把 raw 追加进 hist（长度 ≤ SMOOTH_N），返回当前窗口的中位值"""
    hist.append(raw)
    v = sorted(hist)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2.0


def new_hist():
    """每维一个滚动中位窗（SMOOTH_N 长）——**按清理模式各持一份**（模式间量级不同）"""
    return [deque(maxlen=SMOOTH_N) for _ in DIM_WORDS]


def new_state():
    """ERIS 运行状态容器（每维滚动窗 + 上轮五维分 + 上轮效率 + 趋势方向序列）。"""
    return {"hist": new_hist(), "prev_scores": None, "prev_eff": None, "trend": []}


def widen(base, scale=0.0):
    """围绕中位展宽五点基线：把跨度拉到 ≥ max(MIN_REL_SPAN, scale)×|中位|（保持单调与形状）。

    窄分布维（实测"优化通畅"p05→p90 仅 19% 相对跨度）若按原样映射，微小的正常波动就会占满
    20~80 分 —— 展宽后读数更稳、更贴近"只有真实变化才动分"。
    """
    b = [float(x) for x in base]
    mid = b[2]
    span = b[4] - b[0]
    need = max(MIN_REL_SPAN, scale) * abs(mid)
    if span <= 0:
        return [mid * 0.7, mid * 0.85, mid, mid * 1.15, mid * 1.3] if mid > 0 else [-0.3, -0.15, 0.0, 0.15, 0.3]
    if need <= span:
        return b
    f = need / span
    return [mid + (x - mid) * f for x in b]


def score_of(x, base):
    """五点分位映射：p05/p25/p50/p75/p90 → 20/35/50/65/80；两端线性外推，钳 [0,140]"""
    if x is None or not base or len(base) < 5:
        return 50.0
    b = base
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 50.0
    if b[4] <= b[0]:
        return 50.0
    if x <= b[0]:
        _d = b[1] - b[0]
        if _d <= 0:
            _d = b[4] - b[0]   # 退化基线（相邻分位相等）：按整体跨度取斜率，防微越界即触底/顶格
        return max(SCORE_FLOOR, SCORE_ANCHORS[0] - (b[0] - x) / max(_d, 1e-12) * 15.0)
    if x >= b[4]:
        _d = b[4] - b[3]
        if _d <= 0:
            _d = b[4] - b[0]
        return min(SCORE_CAP, SCORE_ANCHORS[4] + (x - b[4]) / max(_d, 1e-12) * 15.0)
    for k in range(4):
        if x <= b[k + 1]:
            span = b[k + 1] - b[k]
            return SCORE_ANCHORS[k] + (SCORE_ANCHORS[k + 1] - SCORE_ANCHORS[k]) * (x - b[k]) / span if span > 0 else SCORE_ANCHORS[k]
    return 50.0


def _quantile(sorted_vals, p):
    n = len(sorted_vals)
    if n <= 0:
        return 0.0
    return sorted_vals[min(n - 1, max(0, int(round(p * (n - 1)))))]


def _live_mix(bucket):
    """窗口实测的掺入比例：< LIVE_MIN 个样本用种子，LIVE_FULL 后完全用实测"""
    n = len(bucket.get("win") or [])
    if n < LIVE_MIN:
        return 0.0
    return min(1.0, (n - LIVE_MIN) / float(max(1, LIVE_FULL - LIVE_MIN)))


def _provisional_dims(bucket, mode):
    """标定期临时基线：种子打底，随窗口积累逐步换成**窗口自身的实测分位**
    ⇒ 出厂种子过期时读数偏差会在标定窗口内自行收敛（且冻结瞬间不跳变）"""
    seeds = [widen(seeds_for(mode)[j], PROVISIONAL_SPAN) for j in range(len(DIM_WORDS))]
    w = _live_mix(bucket)
    if w <= 0:
        return seeds
    out = []
    for j in range(len(DIM_WORDS)):
        vals = sorted(v for row in (bucket.get("win") or []) for v in [row[j]] if v is not None)
        if len(vals) < LIVE_MIN:
            out.append(seeds[j])
            continue
        live = widen([_quantile(vals, p) for p in Q_ANCHORS])
        out.append([seeds[j][k] * (1.0 - w) + live[k] * w for k in range(5)])
    return out


def _live_k(bucket, mode, dims):
    """标定期临时 K：种子与「窗口总分 p90」按同一比例混合"""
    w = _live_mix(bucket)
    if w <= 0:
        return k_seed(mode), w
    tots = []
    for row in (bucket.get("win") or []):
        nod = [v is None for v in row]
        sc = [50.0 if row[j] is None else score_of(row[j], dims[j]) for j in range(len(DIM_WORDS))]
        tots.append(total_of(sc, valid=valid_dims(mode, nod), mode=mode))
    if len(tots) < LIVE_MIN:
        return k_seed(mode), w
    live = _quantile(sorted(tots), K_QUANTILE)
    return (k_seed(mode) * (1.0 - w) + live * w), w


def _freeze(win, mode=None):
    """标定窗口（[[五维 raws]…]）→ 冻结基线：每维五点（含窄维展宽）+ K（总分 p92）"""
    dims = []
    for j in range(len(DIM_WORDS)):
        vals = sorted(v for row in win for v in [row[j]] if v is not None)
        if len(vals) < 5:
            dims.append(widen(seeds_for(mode)[j], PROVISIONAL_SPAN))
            continue
        dims.append(widen([_quantile(vals, p) for p in Q_ANCHORS]))
    tots = []
    decl = MODE_VALID_DIMS.get(mode or "normal", MODE_VALID_DIMS["normal"])
    for row in win:
        sc = [50.0 if row[j] is None else score_of(row[j], dims[j]) for j in range(len(DIM_WORDS))]
        nod = [row[j] is None for j in range(len(DIM_WORDS))]
        tots.append(total_of(sc, valid=valid_dims(mode, nod), mode=mode))
    st_tots = sorted(tots)
    k = _quantile(st_tots, K_QUANTILE) if len(st_tots) >= 5 else k_seed(mode)
    if k <= 0:
        k = k_seed(mode)
    # 期望中位效率：冻结时窗口内总分中位对应的读数——日后用它检验"基线是否还描述这台机器"
    med = (_quantile(st_tots, 0.50) / k * 100.0) if st_tots else 0.0
    return {"dims": dims, "k": k, "med": med}


def new_calib():
    """校准状态容器（按模式分桶）"""
    return {"v": CALIB_STATE_V, "modes": {}}


def _fresh_bucket():
    return {"n": 0, "win": [], "base": None, "tot": [], "recalib": 0}


def _bucket(calib, mode):
    """取该模式的桶；旧 schema（≤4：滚动分位/冻结表/中心跨度校正）**就地重建**——
    锚点语义已换成"冻结基线"，旧数据无意义（与 v8→v9 的迁移同款处理）"""
    try:
        if not isinstance(calib, dict):
            calib = new_calib()
        if calib.get("v") != CALIB_STATE_V:
            calib.clear()
            calib.update({"v": CALIB_STATE_V, "modes": {}})
    except Exception:
        calib = new_calib()
    return calib.setdefault("modes", {}).setdefault(mode, _fresh_bucket())


def calib_valid(calib):
    """校验持久化结构（版本 / 每模式：n、标定窗口、冻结基线、总分看护窗、重标计数）"""
    try:
        if not isinstance(calib, dict) or calib.get("v") != CALIB_STATE_V:
            return False
        modes = calib.get("modes")
        if not isinstance(modes, dict):
            return False
        for one in modes.values():
            if not isinstance(one, dict):
                return False
            if not isinstance(one.get("n", 0), int) or one.get("n", 0) < 0:
                return False
            win = one.get("win", [])
            if not isinstance(win, list) or len(win) > CALIB_N:
                return False
            for row in win:
                if not isinstance(row, list) or len(row) != len(DIM_WORDS):
                    return False
                if not all(v is None or (isinstance(v, (int, float)) and v == v
                                          and math.isfinite(v)) for v in row):
                    return False
            tot = one.get("tot", [])
            if not isinstance(tot, list) or len(tot) > LONG_WIN:
                return False
            b = one.get("base")
            if b is not None:
                if not isinstance(b, dict) or not isinstance(b.get("dims"), list):
                    return False
                if len(b["dims"]) != len(DIM_WORDS):
                    return False
                for d in b["dims"]:
                    if not isinstance(d, list) or len(d) != 5:
                        return False
                    if not all(isinstance(v, (int, float)) and v == v and math.isfinite(v) for v in d):
                        return False
                k = b.get("k")
                if not isinstance(k, (int, float)) or not (k > 0) or not math.isfinite(k):
                    return False
                if not isinstance(b.get("med", 0.0), (int, float)) or not math.isfinite(b.get("med", 0.0)):
                    return False
            if not isinstance(one.get("recalib", 0), int) or one.get("recalib", 0) < 0:
                return False
        return True
    except Exception:
        return False


def baseline_of(calib, mode=None):
    """该模式当前基线：已标定 ⇒ 冻结基线；未标定 ⇒ 种子（按 PROVISIONAL_SPAN 放宽）"""
    m = mode or "normal"
    try:
        b = _bucket(calib, m).get("base")
        if isinstance(b, dict) and isinstance(b.get("dims"), list) and len(b["dims"]) == len(DIM_WORDS):
            return b
    except Exception:
        pass
    bucket = _bucket(calib, m)
    dims = _provisional_dims(bucket, m)
    k, _w = _live_k(bucket, m, dims)
    return {"dims": dims, "k": k}


def calibrate_and_score(raws, calib, update=True, skip=None, mode=None, game=False):
    """赋分主入口：返回 (五维分数, 校准状态)。

    · 已标定 ⇒ 直接用冻结基线映射；未标定 ⇒ 用放宽的种子映射，并在 update 时累积标定窗口
    · 标定窗口满 CALIB_N ⇒ 冻结基线（每维五点，含窄维展宽）+ K（总分 p92）写入并持久化
    · `game=True` 照常算分但不累积；`skip[j]=True`（该维本轮无数据）记中性 50 且不累积
    · 偏离自检：近 LONG_WIN 轮总分中位与冻结时期望中位偏差 > LONG_TOL ⇒ 清空基线重标一次
      （recalib+1，诊断行可见）
    """
    _m = mode or "normal"
    bucket = _bucket(calib, _m)
    n_dim = min(len(raws), len(DIM_WORDS))
    nodata = [(bool(skip and j < len(skip) and skip[j])) or j >= n_dim or raws[j] is None
              for j in range(len(DIM_WORDS))]
    base = bucket.get("base")
    if isinstance(base, dict):
        dims = base["dims"]
    else:
        dims = _provisional_dims(bucket, _m)   # 种子 → 窗口实测渐进接管（种子过期也能收敛）
    scores = [50.0 if nodata[j] else score_of(raws[j], dims[j]) for j in range(len(DIM_WORDS))]
    if update and not game:
        bucket["n"] = int(bucket.get("n", 0)) + 1
        if not isinstance(base, dict):
            win = bucket.get("win")
            if not isinstance(win, list):
                win = []
                bucket["win"] = win
            if int(bucket.get("n", 0)) > CALIB_SKIP and len(win) < CALIB_N:
                win.append([None if nodata[j] else raws[j] for j in range(len(DIM_WORDS))])
                if len(win) >= CALIB_N:
                    bucket["base"] = _freeze(win, _m)
                    bucket["win"] = []            # 冻结后释放窗口（文件不随轮次增长）
        else:
            tot = bucket.get("tot")
            if not isinstance(tot, list):
                tot = []
                bucket["tot"] = tot
            tot.append(sum(scores))
            if len(tot) > LONG_WIN:
                del tot[0]
            # 自指检验（2026-09-26 修正）：与"冻结时的期望中位"比，不再用固定的 35~85 带——
            # 固定带太钝：基线本身不准（标定窗口不典型）时读数会常年停在带内、永不纠正
            if len(tot) >= LONG_WIN:
                med_eff = sorted(tot)[len(tot) // 2] / float(base.get("k") or k_seed(_m)) * 100.0
                exp = float(base.get("med") or 0.0)
                if exp > 0 and abs(med_eff - exp) > LONG_TOL:
                    bucket["base"] = None         # 基线不再描述这台机器 ⇒ 重标一次
                    bucket["win"] = []
                    bucket["tot"] = []
                    bucket["recalib"] = int(bucket.get("recalib", 0)) + 1
    return scores, calib


def k_value(calib, mode=None):
    """该模式当前的 K（冻结值；未标定用种子）"""
    b = baseline_of(calib, mode or "normal")
    try:
        k = float(b.get("k") or 0.0)
        if k > 0:
            return k
    except Exception:
        pass
    return k_seed(mode)


def bucket_n(calib, mode=None):
    """该模式累计的有效轮数（日志与诊断用）"""
    try:
        return int(_bucket(calib, mode or "normal").get("n", 0))
    except Exception:
        return 0


def calibrated(calib, mode=None):
    """该模式是否已完成自标定（诊断用）"""
    try:
        return isinstance(_bucket(calib, mode or "normal").get("base"), dict)
    except Exception:
        return False


def recalib_count(calib, mode=None):
    """该模式的重标次数（诊断用）"""
    try:
        return int(_bucket(calib, mode or "normal").get("recalib", 0) or 0)
    except Exception:
        return 0


def total_of(scores, valid=None, mode=None):
    """有效维均分后折算回五维尺度（0~700）；K 除它 ×100 即效率百分比。

    · 有效维 = 传入的 valid（模式声明 ∩ 有数据）
    · 只剩一维有效时改用该模式的**声明维**为池（缺数据维按中性 50）⇒ 防单维独担 5 倍放大
    · 无有效维 ⇒ 五维中性
    """
    idx = list(valid) if valid else list(range(len(scores)))
    idx = [j for j in idx if 0 <= j < len(scores)]
    if not idx:
        return 50.0 * len(scores)
    if len(idx) < 2:
        decl = [j for j in MODE_VALID_DIMS.get(mode or "normal", MODE_VALID_DIMS["normal"])
                if 0 <= j < len(scores)]
        idx = decl if len(decl) >= 2 else list(range(len(scores)))
    return sum(scores[j] for j in idx) / len(idx) * len(scores)


def efficiency(scores, K=None, mode=None, valid=None):
    """效率百分比 = 折算总分 ÷ K × 100（K = 该模式自标定期总分 p92）"""
    k = float(K if K else k_seed(mode))
    if k <= 0:
        return 0.0
    return total_of(scores, valid=valid, mode=mode) / k * 100.0


def pick_factor(scores, prev_scores, up, avoid=None):
    """词条维度选择：升 → 本轮上升维中最高分者；降 → 本轮下降维中最低分者。
    `avoid=(维度索引, 上轮该维报的方向)`：排除"同一维且本轮方向与上轮相反"的维度，
    避免同一维度正负两面在相邻两轮来回跳（2026-09-26 用户规定，此前只约定未落码）；
    排除后若无候选 ⇒ 返回 None，由调用方兜底（宁可同维连报，也不改口径掩盖）。
    返回维度索引；无候选（含并列未变化）返回 None（由调用方兜底）。"""
    if not prev_scores or len(prev_scores) != len(scores):
        return None
    cand = [j for j in range(len(scores)) if (scores[j] > prev_scores[j]) == bool(up)
            and scores[j] != prev_scores[j]]
    if avoid and bool(avoid[1]) != bool(up):
        cand = [j for j in cand if j != avoid[0]]
    if not cand:
        return None
    return max(cand, key=lambda j: scores[j]) if up else min(cand, key=lambda j: scores[j])
