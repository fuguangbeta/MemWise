# -*- coding: utf-8 -*-
"""ReboundLearner — 组件回弹学习（B 方案，自动后退机制）

trim 后 120s 观察回填：回弹率（回填量/释放量）EWMA≥70% 且 ≥3 次 → 该组件自动进入
30 分钟后退期（不自动清理）；回弹率回落 <50% 自动解除（动态恢复，优于固定观察期）。
与 P1-D 稳定锚点互补：锚点管"低于稳态不清"，后退管"回弹率高但当前高于稳态"。
键 = 规范化可执行路径（与 StableAnchor 一致，P2 族聚合时自然升级为族键）。
注：suggest 建议通道（P2-G 预留）已于 2026-09-06 审查 F12 经用户批准移除（零调用方；
未来实现"回弹→保护建议"方向时按当时需求重新设计）。
"""
import time

OBSERVE_WINDOW = 120       # 回弹观察期（秒）
BACKOFF_SECONDS = 1800     # 自动后退期（30 分钟）
BACKOFF_THRESHOLD = 0.7    # 回弹率触发后退
RELEASE_THRESHOLD = 0.5    # 回弹率回落解除后退
MIN_COUNT = 3              # 最少采样次数（防单次偶发）
EWMA_LAMBDA = 0.3


def _key(path):
    """规范化可执行路径键（与 stable.StableAnchorStore 同规则）"""
    if not path:
        return None
    try:
        return path.strip().lower().replace("/", "\\")
    except Exception:
        return None


class ReboundLearner:
    def __init__(self):
        self.ewma = {}           # key -> 回弹率 EWMA
        self.count = {}          # key -> 采样次数
        self.backoff_until = {}  # key -> 后退截止时间戳
        self._pending = {}       # key -> (released, ws_after, until)

    def begin(self, path, released, ws_after, now):
        """trim 成功后开始回弹追踪（释放量>0 且路径可解析）"""
        key = _key(path)
        if not key or released <= 0 or ws_after <= 0:
            return
        self._pending[key] = (released, ws_after, now + OBSERVE_WINDOW)

    def observe(self, snaps, now):
        """每轮观察：快照 WS 与追踪基线比对 → 到期结算回弹率"""
        if not self._pending:
            return
        by_path = {}
        for s in snaps:
            k = _key(getattr(s, "path", None))
            if k:
                # 同路径多实例取最大 WS（与 stable 聚合同向保守）——末值覆盖会随快照
                # 实例顺序抖动，2026-08-30 实验：同数据不同顺序回弹率 0.21 vs 1.11
                prev = by_path.get(k)
                by_path[k] = s.ws if prev is None else max(prev, s.ws)
        for key in list(self._pending.keys()):
            released, ws_after, until = self._pending[key]
            ws_now = by_path.get(key)
            if ws_now is None:
                continue  # 进程不在快照（退出/暂停）——保留观察
            if now >= until:
                regained = max(0, ws_now - ws_after)
                self.record(key, released, regained, now)
                del self._pending[key]

    def record(self, key, released, regained, now):
        ratio = regained / max(released, 1)
        self.ewma[key] = EWMA_LAMBDA * ratio + (1 - EWMA_LAMBDA) * self.ewma.get(key, 0.3)
        self.count[key] = self.count.get(key, 0) + 1
        if self.ewma[key] >= BACKOFF_THRESHOLD and self.count[key] >= MIN_COUNT:
            self.backoff_until[key] = now + BACKOFF_SECONDS
        elif self.ewma[key] < RELEASE_THRESHOLD:
            self.backoff_until.pop(key, None)

    def in_backoff(self, path, now):
        key = _key(path)
        if not key:
            return False
        return self.backoff_until.get(key, 0) > now

    def purge_expired(self, now):
        for k in list(self._pending.keys()):
            if now > self._pending[k][2] + 60:
                del self._pending[k]

    def to_dict(self):
        return {
            "ewma": self.ewma,
            "count": self.count,
            "backoff_until": self.backoff_until,
        }

    @classmethod
    def from_dict(cls, d):
        r = cls()
        if not isinstance(d, dict):
            return r
        try:
            r.ewma = {str(k): float(v) for k, v in d.get("ewma", {}).items()
                      if isinstance(v, (int, float))}
            r.count = {str(k): max(0, int(v)) for k, v in d.get("count", {}).items()
                       if isinstance(v, (int, float))}
            r.backoff_until = {str(k): max(0.0, float(v)) for k, v in d.get("backoff_until", {}).items()
                               if isinstance(v, (int, float))}
            # 旧格式可能含 "suggested" 键（suggest 通道已于 2026-09-06 移除）——
            # 多余键静默忽略，旧状态文件读取零影响
        except Exception:
            pass
        return r
