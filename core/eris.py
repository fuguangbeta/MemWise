# -*- coding: utf-8 -*-
"""ERIS v6 效率评分 — 纯函数核心（生产 GUI 与回归测试共用，杜绝测试副本与生产分歧）"""
from collections import deque


def iqr_dim(raw, buf, p50_ewma, iqr_ewma, update_state=True):
    """单维 IQR 归一化 → 0-130 分（80 中性）。

    参数:
        raw: 本轮原始值
        buf: deque 窗口（maxlen 由调用方设定）
        p50_ewma: 中位数平滑值（λ=0.15）
        iqr_ewma: IQR 平滑值（λ=0.30，前 5 轮不积累）
        update_state: 是否把 raw 写入窗口并更新 EWMA（只读评估时 False）

    返回: (dim, p50_ewma_new, iqr_ewma_new)

    分支说明:
      nL>=4: trimmed IQR（去头尾各 1）+ 线性内插 Q1/Q3 + floor 尺度（p50*10% 与 iqr_ewma*20% 取大）
      nL=2/3: 以 p50*10% 为尺度（防以自身偏差为分母退化为 ±1 二值，曾致冷启动虚假「效率超常/异常」）
      nL<2: 中性 80
    """
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
        # Q1/Q3 线性内插 (n+1)*0.25/0.75（lo 下限 0，防 nT=2 时负索引回绕取到最大值）
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
        # 冷启动（<5 样本）用原始中位：EWMA 从 0 起步时只有 raw 的 15%，作基准会虚高到 clamp 上限
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
        # 冷启动同规则：样本 <5 时 EWMA 未收敛，用原始中位防虚高
        p50 = p50_raw if nL < 5 else (p50_ewma if p50_ewma > 0 else p50_raw)
        dim = 80.0 + 40.0 * (raw - p50) / max(p50 * 0.10, 0.01)
    else:
        dim = 80.0
        p50_raw = 0.0
    return max(1.0, min(130.0, dim)), p50_ewma, iqr_ewma


def validate_state(bufs, ewma_list, windows):
    """校验 ERIS 持久化状态结构（维度数/窗口上限/数值合法性）"""
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
