# -*- coding: utf-8 -*-
"""ERIS v8 效率评分 — 纯函数核心（生产与回归共用，杜绝测试副本与生产分歧）

v8 设计（2026-09-11 用户定稿：**不设绝对标尺、对照近几十轮、四模式互不污染**，见记忆 §B4/§B6）：
  · 五维各 0~140 分；**锚点 = 本机该维近几十轮的滚动分位**（不再是冻结的绝对标尺）
    - 每模式×每维跟踪 q10/q50/q90（非对称 EWMA，两速：暖机快、稳态慢）+ 样本数
    - 冷启动用**实测种子**初始化（`SEED_Q_BY_MODE`，取自本机四模式实跑 29~63 轮）⇒ 第一轮即落在合理位置
    - 四段锚点由三个稳健分位**推导**，不再估 p99（小样本下 p99 就是最大值，天然抖）：
        x0 = q50 − 下段宽，x1 = q50，x2 = q50 + 上段宽，x3 = x2 + 上段宽  → 20/50/80/110 分
      段宽下限（相对总跨度 SEG_FRAC）+ 跨度下限（相对中位 SPAN_FLOOR_REL、对数维 SPAN_FLOOR_LOG）
      ⇒ 杜绝"退化段（如 p99=p90、上段宽 0.0005）⇒ 一点噪声跳满量程"
    - **预热收缩**：某维样本 < WARM_N 时分数按 w=n/WARM_N 向中性 50 收缩 ⇒ 冷启动/新模式也不会出极端读数
  · 效率 = 有效维均值 × 5 ÷ K × 100；**K 也是滚动量**（该模式总分 p90 的 EWMA 估计，带种子）
    ⇒ 100% 恒等于"本模式近期高位"，超常/异常各约一成，与机器、模式无关
  · 有效维 = 模式声明维 ∩ 有数据维；只剩一维时改用声明维为池、缺数据维按中性 50 计入（防单维独担 5 倍放大）
  · 每维原始值先做 N=3 滚动中位（压测量噪声）；词条按"本轮分数变化方向"选维（升取最高、降取最低）
  · 游戏轮次照常算分但**不喂跟踪器**（游戏态清理行为与常态不同，混入会拉偏分位）

  与 v7 的差异（一次底层替换，不是补丁）：删除了"冻结锚点 + 中心/跨度校正 + 淡入 + 双向限幅"整层——
  滚动分位本身就是自适应的，不需要在冻结标尺上再打补丁。代价（用户已知并接受）：分数含义从
  "距历史高位的绝对位置"变为"距近期自身水平的位置"，**绝对水平看日志里的五维原始值**。

  自校准数据独立存放（`memwise_eris_calib.json`）：不随配置包导出、恢复默认时清除；
  删除该文件即回到出厂种子状态（可回退、可复现）。效率值**只用于展示**，不参与清理与调参决策
  ⇒ 不存在"分数→行为→分数"的自激回路。
"""
import math
from collections import deque

SMOOTH_N = 3          # 每维原始值的滚动中位窗口
SCORE_FLOOR = 0.0     # 维度分下限
SCORE_CAP = 140.0     # 维度分上限（超常溢出区）
ERIS_STATE_V = 8      # 平滑窗文件 schema：8 = 按清理模式分桶（模式间量级不同，混用会互相带偏）；
                      # 7 = 单桶扁平 hist（加载时迁移进当前模式桶）；≤6 = 分位数窗旧格式（忽略重建）
CALIB_STATE_V = 4     # 校准文件 schema：4 = 滚动分位 [q10,q50,q90,n] + 滚动 K[值,样本]
                      # + K 的滚动窗口与自愈标记（2026-09-12）；3 = 无自愈字段（加载即弃）；
                      # 1/2 = 旧"冻结表 + 中心/跨度校正"结构（语义已废弃，加载时丢弃重建）

# ── 滚动锚点参数 ──
SPAN_FLOOR_REL = 0.10    # 线性维跨度下限 = 10%×|中位|：预测精准实测跨度仅 2.5%、且近似双峰 ⇒
                         # 不设下限就会把 ±2% 的正常抖动放大成满量程（实测 0/140 两极跳）；
                         # 10% 意味着"±5% 以内的抖动只在中段移动、超过约 10% 才算超常/异常"
WARM_MODE_N = 8          # 模式级预热：该模式样本 < WARM_MODE_N 轮时，总分向中性（五维各 50 对应值）收缩
SPAN_FLOOR_LOG = 0.25    # 对数维（副作用）跨度下限（log 单位 ≈ 28% 相对变化）
SEG_FRAC = 0.15          # 每段宽度下限（相对总跨度）⇒ 防退化段
WARM_N = 5               # 预热收缩样本数：某维样本 < WARM_N 时分数向中性 50 收缩
CALIB_ALPHA_FAST = 0.08  # 暖机步长（前 CALIB_FAST_N 轮）
CALIB_ALPHA = 0.03       # 稳态步长（q50 再乘 Q_ALPHA_MULT[1] ⇒ 时间常数 ≈ 17~33 轮 ≈ "近几十轮"）
# 位置与尺度分离（2026-09-11 实测发现）：中位跟得快（机器行为缓慢漂移时跟得住，不产生
# 系统性低分），两侧分位跟得慢（尺度要稳，否则分数被噪声带着抖）——漂移下的滞后 = 速率/步长
Q_ALPHA_MULT = (1.0, 2.0, 1.0)   # q10 / q50 / q90 的步长倍数
CALIB_FAST_N = 30        # 暖机轮数（每模式独立计数）
# K（该模式"总分 p90"＝100% 那条线）：**滚动窗口分位**，不是 EWMA——
# 2026-09-12 实测：EWMA 在"总分持续上移"时有长期滞后（α=0.02、q=0.90 ⇒ 上行步长仅 1.8%/轮
# ⇒ deep 87 轮只追平 71%，超常率虚高 32%）；改窗口后滞后只有半个窗口、且天然自愈
# （换机器、行为变化、旧种子不准都会在 ≤K_WIN 轮内被本机数据纠正，无需任何人工重标）
K_WIN = 40               # K 的滚动窗口（近 40 轮总分）：窗口分位的滞后 ≈ 半窗 ⇒ 40 轮
                         # 在"机器持续变好期"只带来约 7% 读数偏高（60 轮时约 10~15%）
K_SEED_N = 30            # 种子权重：随窗口填满线性淡出（窗口满时种子影响为 0）

# ── 五维词条（顺序即维度索引；统一四字、正负对应）──
DIM_WORDS = [
    ("↑预测精准", "↓预测偏差"),
    ("↑释放彻底", "↓释放不全"),
    ("↑清理畅通", "↓清理受阻"),
    ("↑副作用低", "↓副作用高"),
    ("↑试探高效", "↓试探低效"),
]

# 副作用维长尾（p99/p50 ≈ 65 倍 ⇒ 进入滚动分位前先取对数）
LOG_DIMS = (3,)

# ── 冷启动种子：每维 [q10, q50, q90]（顺序：0 预测精准 / 1 释放彻底 / 2 清理畅通 / 3 副作用(对数) / 4 试探高效）──
# 来源：2026-09-12 本机 v4.5.063 会话实测分位（quick 113 / normal 101 / deep 87 / full 75 轮，原始值为 N=3 平滑后）
# 说明：种子只决定"第一轮落在哪里"，之后由滚动分位自己长；换机器/机器行为漂移都能自适应。
#   · quick 的 1 维 = 系统级释放比（由本机 quick 日志的 本轮释放 ÷ 惯常释放 重建）
#   · quick 的 0/2/4 维在该模式下不参与（无数据，取 normal 值占位，不生效）
#   · quick 的 3 维暂无实测（quick 不做进程清理、历史 PF 恒 0）⇒ 借 full 的实测三元组作先验
SEED_Q_BY_MODE = {
    "normal": [[0.3553, 0.367, 0.3948],
               [0.7814, 1.007, 1.143],
               [0.8571, 2.0, 3.5],
               [0.002741, 0.007652, 0.01774],
               [0.6667, 0.7255, 0.7561]],
    "deep":   [[0.4004, 0.4129, 0.4155],
               [0.9334, 1.01, 1.186],
               [1.364, 1.857, 2.455],
               [0.001435, 0.002421, 0.00441],
               [0.6545, 0.7234, 0.7789]],
    "full":   [[0.394, 0.4038, 0.4149],
               [0.7747, 0.9192, 1.091],
               [20.57, 26.27, 33.11],
               [0.0001307, 0.0003005, 0.001387],
               [0.5345, 0.6176, 0.6522]],
    "quick":  [[0.3553, 0.367, 0.3948],
               [0.6975, 1.0, 1.664],
               [0.8571, 2.0, 3.5],
               [0.002741, 0.007652, 0.01774],
               [0.6667, 0.7255, 0.7561]],
}
# K 种子 = 该模式**总分 p90** 的实测值（设计定义：100% ≡ 本模式近期高位 ⇒ 超常约一成）
# 来源：2026-09-11 本机实跑日志回放（预热 8 轮后统计：quick n=21 → 280 / normal n=20 → 330 /
#      deep 360 / full 316；quick 257（单维 + 中性维稀释））
#      运行时：前 150 轮快速追赶 + 满 40 轮用本机实测 p90 自愈重播一次 ⇒ 真值由本机数据决定
SEED_K_BY_MODE = {"quick": 257.0, "normal": 390.0, "deep": 360.0, "full": 316.0}

# 极性阈值：超常 = 效率 ≥100%（K 的滚动定义处 ⇒ 约一成轮次）；异常 = ≤50%
SUPER_TH = 100.0
WARN_TH = 50.0

# 各模式"有效维度"（2026-09-12 定稿）：quick 声明 (1, 3) —— 实际只有 1 维＝**系统级释放彻底**
# 有数据（该模式不做进程清理 ⇒ 进程口径的四维无作用面；dim3 恒记无数据、以中性 50 参与合成，
# 作用是把单维权重稀释回合理动态范围）。原计划的"系统级副作用"维经实测否决：
# 快照 PF 字段 266 进程仅 1 个非零、系统级 PF 又被无关活动淹没 ⇒ 测不出清理代价（见记忆 §B6）
MODE_VALID_DIMS = {
    "quick": (1, 3),
    "normal": (0, 1, 2, 3, 4),
    "deep": (0, 1, 2, 3, 4),
    "full": (0, 1, 2, 3, 4),
}


def seeds_for(mode=None):
    """该模式的种子分位三元组表（未知模式回退 normal）"""
    return SEED_Q_BY_MODE.get(mode or "normal", SEED_Q_BY_MODE["normal"])


def k_seed(mode=None):
    """该模式的 K 种子（未知模式回退 normal）"""
    return SEED_K_BY_MODE.get(mode or "normal", SEED_K_BY_MODE["normal"])


def valid_dims(mode=None, nodata=None):
    """该模式的有效维度索引（去掉无数据维）"""
    dims = MODE_VALID_DIMS.get(mode or "normal", MODE_VALID_DIMS["normal"])
    if nodata:
        dims = tuple(j for j in dims if not (j < len(nodata) and nodata[j]))
    return dims


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


def span_of(triple, log_scale=False):
    """该维的**正则化跨度**：max(q90−q10, 跨度下限)。下限防"噪声放大成满量程"——
    线性维按中位的 SPAN_FLOOR_REL 比例、对数维用绝对 SPAN_FLOOR_LOG。"""
    q10, q50, q90 = (triple[0], triple[1], triple[2])
    floor = SPAN_FLOOR_LOG if log_scale else SPAN_FLOOR_REL * max(abs(q50), 1e-9)
    return max(q90 - q10, floor, 1e-12)


def ladder(q10, q50, q90, log_scale=False):
    """由 q10/q50/q90 推导四段锚点（→ 20/50/80/110 分），带段宽与跨度下限。

    · 110 分点不再估 p99（小样本下 p99 即最大值，最抖）⇒ 取"q90 之上再走一个上段宽"
    · 段宽下限 = SEG_FRAC×正则化跨度（`span_of`）⇒ 退化分布（如上段宽 0.0005）不再
      把一点噪声放大成满量程
    """
    span = span_of((q10, q50, q90), log_scale)
    lo = max(q50 - q10, SEG_FRAC * span)
    hi = max(q90 - q50, SEG_FRAC * span)
    x2 = q50 + hi
    return [q50 - lo, q50, x2, x2 + max(hi, SEG_FRAC * span)]


def _score_u(u, au):
    """标尺空间四锚点分段线性：20/50/80/110，之外按段斜率延伸，钳制 [0, 140]"""
    try:
        x0, x1, x2, x3 = (float(a) for a in au)
    except Exception:
        return 50.0
    pts = [(x0, 20.0), (x1, 50.0), (x2, 80.0), (x3, 110.0)]
    try:
        if u <= x0:
            gap = max(x1 - x0, (x2 - x0) * 0.25, 1e-12)   # 深段行程下限（防一步归零）
            return max(SCORE_FLOOR, 20.0 - 30.0 * (x0 - u) / gap)
        for i in range(3):
            xa, ya = pts[i]
            xb, yb = pts[i + 1]
            if u <= xb:
                return ya + (yb - ya) * (u - xa) / (xb - xa) if xb > xa else ya
        k = (110.0 - 80.0) / (x3 - x2) if x3 > x2 else 0.0
        return min(SCORE_CAP, 110.0 + k * (u - x3))
    except Exception:
        return 50.0


def ladder_of(triple, log_scale=False):
    """原始单位三元组 → 四段锚点（对数维先取对数，供 dim_score/回归/自检共用）"""
    a, b, c = (_u(triple[0], log_scale), _u(triple[1], log_scale), _u(triple[2], log_scale))
    return ladder(a, b, c, log_scale)


def dim_score(raw, triple, log_scale=False):
    """单维赋分（用给定分位三元组的"冷口径"，不做滚动跟踪）——种子自检与回归使用"""
    u = _u(raw, log_scale)
    if u is None:
        return 50.0
    return _score_u(u, ladder_of(triple, log_scale))


def total_of(scores, valid=None, mode=None):
    """有效维均分后折算回五维尺度（0~700 尺度）；K 除它 ×100 即效率百分比。

    · 有效维 = 传入的 valid（模式声明 ∩ 有数据）
    · 只剩一维有效时，池改用该模式的**声明维**（缺数据维按中性 50 计入）——
      既避免"单一维独担 5 倍权重"把效率推到 0%/240%，又保留合理的动态范围
      （实测：若用全部五维为池，quick 的四维中性会把动态压扁到 63% 轮次判"平稳"）
    · 无有效维（含 valid 为空元组）⇒ 五维中性
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
    """效率百分比 = 有效维均分折算值 ÷ K × 100（K = 该模式总分的滚动 p90 估计）"""
    k = float(K if K else k_seed(mode))
    if k <= 0:
        return 0.0
    return total_of(scores, valid=valid, mode=mode) / k * 100.0


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


def new_hist():
    """每维一个滚动中位窗（SMOOTH_N 长）——**按清理模式各持一份**（见 ERIS_STATE_V 说明）"""
    return [deque(maxlen=SMOOTH_N) for _ in DIM_WORDS]


def new_state():
    """ERIS 运行状态容器（每维滚动窗 + 上轮五维分 + 上轮效率 + 趋势方向序列）。"""
    return {
        "hist": new_hist(),
        "prev_scores": None,
        "prev_eff": None,
        "trend": [],
    }


# ══════════════════════════════════════════════════════════════════════
# 滚动分位锚点：q10/q50/q90（非对称 EWMA，两速）+ 滚动 K（总分 p90）
# ══════════════════════════════════════════════════════════════════════

def new_calib():
    """校准状态容器（v3：按模式分桶；每维 [q10,q50,q90,n]，另有滚动 K [值,样本数]）"""
    return {"v": CALIB_STATE_V, "modes": {}}


def _bucket(calib, mode):
    """取该模式的桶；旧 schema（v1/v2"冻结表+校正"或更早）**就地重建**——
    锚点语义已从"冻结标尺 + 中心/跨度校正"换成"滚动分位 + 种子"，旧数据无意义"""
    try:
        if not isinstance(calib, dict):
            calib = new_calib()
        if calib.get("v") != CALIB_STATE_V:
            calib.clear()
            calib.update({"v": CALIB_STATE_V, "modes": {}})
    except Exception:
        calib = new_calib()
    return calib.setdefault("modes", {}).setdefault(mode, _fresh_bucket())


def _fresh_bucket():
    return {"n": 0, "init": False,
            "dims": [[0.0, 0.0, 0.0, 0] for _ in DIM_WORDS],
            "k": [0.0, 0], "kt": []}


def _seed_dims(mode):
    """种子三元组 → 桶内 [q10,q50,q90,n]（n=0 表示只有种子、尚无实测样本）"""
    out = []
    for j, tri in enumerate(seeds_for(mode)[:len(DIM_WORDS)]):
        log_j = j in LOG_DIMS
        a, b, c = (_u(tri[0], log_j), _u(tri[1], log_j), _u(tri[2], log_j))
        out.append([a, b, c, 0])
    return out


def calib_valid(calib):
    """校验持久化结构（版本/维度数/每维四分位与样本数/滚动 K）"""
    try:
        if not isinstance(calib, dict) or calib.get("v") != CALIB_STATE_V:
            return False
        modes = calib.get("modes")
        if not isinstance(modes, dict):
            return False
        for one in modes.values():
            if not isinstance(one, dict):
                return False
            dims = one.get("dims")
            if not isinstance(dims, list) or len(dims) != len(DIM_WORDS):
                return False
            for o in dims:
                if not isinstance(o, list) or len(o) != 4:
                    return False
                for v in o[:3]:
                    if not isinstance(v, (int, float)) or not math.isfinite(v):
                        return False
                if not isinstance(o[3], int) or o[3] < 0:
                    return False
            k = one.get("k")
            if not isinstance(k, list) or len(k) != 2:
                return False
            if not isinstance(k[0], (int, float)) or not math.isfinite(k[0]):
                return False
            if not isinstance(k[1], int) or k[1] < 0:
                return False
            if not isinstance(one.get("n", 0), int) or one.get("n", 0) < 0:
                return False
            kt = one.get("kt", [])
            if not isinstance(kt, list) or len(kt) > K_WIN:
                return False
            if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in kt):
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


def _alpha_now(bucket, alpha=None):
    a = CALIB_ALPHA if alpha is None else alpha
    if int(bucket.get("n", 0)) < CALIB_FAST_N:
        a = max(a, CALIB_ALPHA_FAST)
    return a


def calibrate_and_score(raws, calib, update=True, alpha=None, skip=None, mode=None, game=False):
    """滚动分位锚点赋分：返回 (五维分数, 校准状态)。

    · 每维跟踪 q10/q50/q90（非对称 EWMA，两速）+ 样本数；**种子**来自 SEED_Q_BY_MODE
    · 赋分锚点由三个分位推导（`ladder`）；样本 < WARM_N 时分数向中性 50 收缩
    · `game=True`（游戏轮次）照常算分但**不更新**跟踪器与样本数（游戏态分布不同，不污染分位）
    · `skip[j]=True`（该维本轮无数据）同样不更新，分数记中性
    """
    _m = mode or "normal"
    bucket = _bucket(calib, _m)
    dims = bucket.get("dims")
    if not isinstance(dims, list) or len(dims) != len(DIM_WORDS):
        dims = _seed_dims(_m)
        bucket["dims"] = dims
    if not bucket.get("init"):
        dims = _seed_dims(_m)                 # 首轮用种子播种（而非首个观测）
        bucket["dims"] = dims
        bucket["init"] = True
    a_now = _alpha_now(bucket, alpha)
    n_dim = min(len(raws), len(DIM_WORDS))
    scores = []
    for j in range(len(DIM_WORDS)):
        st = dims[j]
        log_j = j in LOG_DIMS
        no_data = bool(skip and j < len(skip) and skip[j]) or j >= n_dim or raws[j] is None
        if no_data:
            scores.append(50.0)
            continue
        u = _u(raws[j], log_j)
        if u is None:
            scores.append(50.0)
            continue
        s = _score_u(u, ladder(st[0], st[1], st[2], log_j))
        n = int(st[3])
        w = 1.0 if WARM_N <= 0 else min(1.0, n / float(WARM_N))
        scores.append(w * s + (1.0 - w) * 50.0)          # 预热收缩（样本不足 ⇒ 偏中性）
        if update and not game:
            st[0] = _q_step(st[0], u, a_now * Q_ALPHA_MULT[0], 0.10)
            st[1] = _q_step(st[1], u, a_now * Q_ALPHA_MULT[1], 0.50)
            st[2] = _q_step(st[2], u, a_now * Q_ALPHA_MULT[2], 0.90)
            st[3] = n + 1
    if update and not game:
        bucket["n"] = int(bucket.get("n", 0)) + 1
    return scores, calib


def k_value(calib, mode=None):
    """该模式当前的滚动 K（总分 p90 估计）；未初始化则用 K 种子"""
    try:
        bucket = _bucket(calib, mode or "normal")
        k = float(bucket.get("k", [0.0, 0])[0])
        if k > 0:
            return k
    except Exception:
        pass
    return float(k_seed(mode))


def bucket_n(calib, mode=None):
    """该模式已累计的轮数（模式级预热收缩用）"""
    try:
        return int(_bucket(calib, mode or "normal").get("n", 0))
    except Exception:
        return 0


def warmup_total(total, n_mode):
    """模式级预热收缩：分布尚未建立时把总分向中性（五维各 50 ⇒ 250）收缩。

    与"每维预热收缩"同源（统计上的收缩估计），作用是结构性杜绝新模式/新机器的效率尖峰
    （否则一个远超种子的原始值会先顶出 200%+ 的读数，要等 K 追上来才回落）。"""
    if WARM_MODE_N <= 0:
        return total
    w = min(1.0, max(0, int(n_mode)) / float(WARM_MODE_N))
    return w * total + (1.0 - w) * (50.0 * len(DIM_WORDS))


def k_update(calib, mode, total, update=True, game=False):
    """用本轮"有效维均分折算值"更新滚动 K（p90 目标）。

    · 种子按 K_SEED_N 折算成先验权重：窗口未满时与种子混合，权重随窗口填满线性淡出
    · **不用 EWMA**：实测（2026-09-12）EWMA 在"总分持续上移"时有长期滞后（α=0.02、q=0.90
      ⇒ 上行步长仅 1.8%/轮 ⇒ deep 87 轮只追平 71%、超常率虚高 32%）；窗口版滞后只有半个窗口，
      且天然自愈——换机器、行为漂移、出厂种子不准，都会在 ≤K_WIN 轮内被本机数据纠正
    """
    if not update or game:
        return
    try:
        bucket = _bucket(calib, mode or "normal")
        k = bucket.get("k") or [0.0, 0]
        if not isinstance(k, list) or len(k) != 2:
            k = [0.0, 0]
            bucket["k"] = k
        kt = bucket.get("kt")
        if not isinstance(kt, list):
            kt = []
            bucket["kt"] = kt
        kt.append(float(total))
        if len(kt) > K_WIN:
            del kt[0]
        sv = sorted(kt)
        win = sv[min(len(sv) - 1, int(round(0.90 * (len(sv) - 1))))]
        seed = float(k_seed(mode))
        w = K_SEED_N * max(0.0, 1.0 - len(kt) / float(K_WIN))     # 种子影响随窗口填满淡出
        k[0] = (len(kt) * win + w * seed) / (len(kt) + w) if (len(kt) + w) > 0 else seed
        k[1] = len(kt)
    except Exception:
        pass
