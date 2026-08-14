# -*- coding: utf-8 -*-
"""StableAnchor — 组件稳态锚点学习（P1-D 效率核心）

学习"应用自然稳态 WS"，当前 WS 低于稳态+余量 → 抑制清理（清了也白清）。
超越 MuseRAM 的设计（其用中位数+三重聚类实现代际迁移）：
- Kalman 自适应跟踪（复用 KalmanProfile）：稳态平滑、漂移快速跟踪，无需显式聚类
- 启动签名隔离实例：新启动 → 新锚点（防旧实例稳态污染新实例判断）
- 置信门控：p 收敛且样本足够才激活抑制（防冷启动误抑制）
- 键 = 规范化可执行路径：跨启动/跨版本稳定；P2 族聚合时自然升级为目录键
抑制非永久：探索机制（EXPLORE_RATE 概率放行验证清理）保持 Thompson 学习闭环不断验证锚点。
"""
import time
from .kalman import KalmanProfile

MIN_SAMPLES = 5          # 锚点激活最少样本数
CONFIDENCE_GATE = 0.7    # Kalman 置信度门（p 收敛才激活）
RELATIVE_MARGIN = 0.15   # 相对余量（锚点×15%）
ABSOLUTE_MARGIN = 32 << 20  # 绝对余量 32MB
EXPLORE_RATE = 0.05      # 探索概率：抑制并非永久，周期性验证清理保持学习闭环
MAX_AGE = 86400 * 7      # 锚点 7 天无更新过期（对齐 learner 画像口径）


class StableAnchor:
    """单组件稳态锚点"""

    __slots__ = ("launch_sig", "k", "generation", "samples", "confirmed",
                 "last_seen", "last_ws")

    def __init__(self, launch_sig=""):
        self.launch_sig = launch_sig
        self.k = KalmanProfile()      # 稳态 WS 跟踪（x=稳态，p=置信度）
        self.generation = 0           # 代际（新启动实例/漂移迁移递增）
        self.samples = 0
        self.confirmed = False
        self.last_seen = 0.0
        self.last_ws = 0

    def feed(self, ws, launch_sig, now):
        """喂入自然 WS 样本（调用方保证排除清理后回填期样本）"""
        if launch_sig != self.launch_sig:
            # 新启动实例 → 新锚点（旧代保留在持久化中作参考）
            self.launch_sig = launch_sig
            self.generation += 1
            self.k = KalmanProfile()
            self.samples = 0
            self.confirmed = False
        self.k.update(ws, 0)
        self.samples += 1
        self.last_seen = now
        self.last_ws = ws
        if self.samples >= MIN_SAMPLES and self.k.confidence > CONFIDENCE_GATE:
            self.confirmed = True

    def should_suppress(self, ws, relative_margin=None):
        """当前 WS ≤ 锚点×余量+32MB → 抑制。置信未达或锚点未收敛不抑制（防误伤）。
        relative_margin 由 EFIS 参数驱动（anchor_margin），None 用常量默认"""
        if not self.confirmed or self.k.x_freed <= 0:
            return False
        margin = RELATIVE_MARGIN if relative_margin is None else max(0.0, min(0.5, float(relative_margin)))
        limit = self.k.x_freed * (1.0 + margin) + ABSOLUTE_MARGIN
        return ws <= limit

    def to_dict(self):
        return {
            "launch_sig": self.launch_sig,
            "kalman": self.k.to_dict(),
            "generation": self.generation,
            "samples": self.samples,
            "confirmed": self.confirmed,
            "last_seen": self.last_seen,
            "last_ws": self.last_ws,
        }

    @classmethod
    def from_dict(cls, d):
        a = cls()
        if not isinstance(d, dict):
            return a
        a.launch_sig = str(d.get("launch_sig", ""))
        kd = d.get("kalman")
        if isinstance(kd, dict):
            try:
                a.k = KalmanProfile.from_dict(kd)
            except Exception:
                a.k = KalmanProfile()
        try:
            a.generation = max(0, int(d.get("generation", 0)))
            a.samples = max(0, int(d.get("samples", 0)))
            a.confirmed = bool(d.get("confirmed", False))
            a.last_seen = max(0.0, float(d.get("last_seen", 0.0)))
            a.last_ws = max(0, int(d.get("last_ws", 0)))
        except Exception:
            pass
        return a


class StableAnchorStore:
    """锚点集合：按规范化可执行路径索引，跨启动学习（进程退出锚点保留）"""

    def __init__(self):
        self.anchors = {}

    @staticmethod
    def _key(path):
        if not path:
            return None
        try:
            return path.strip().lower().replace("/", "\\")
        except Exception:
            return None

    @staticmethod
    def _launch_sig(key, create_ns):
        """启动签名：路径|创建时间（区分同一路径的不同实例；无创建时间退化 path|0）"""
        return f"{key}|{create_ns or 0}"

    def feed(self, snaps, now, exclude_names):
        """批量喂入自然 WS 样本；exclude_names: 清理后回填期内的进程名（不进入锚点）。

        同轮聚合（2026-08-14 审查修复）：同一路径的多实例（chrome/edge 子进程等）逐个 feed 时，
        启动签名（路径|创建时间）交替导致锚点每轮重置——samples 卡 1，稳态抑制对多进程应用
        永久失效。现按路径聚合：WS 取最大（该路径最坏稳态，保守方向）、签名取最老实例
        （create 最小，主进程常驻则签名稳定）；真重启（最老实例退出/重开）仍触发新代隔离。"""
        by_key = {}
        for s in snaps:
            name = s.name.lower()
            if name in exclude_names:
                continue
            key = self._key(getattr(s, "path", None))
            ws = getattr(s, "ws", 0) or 0
            if not key or ws <= 0:
                continue
            create = getattr(s, "create", None) or 0
            cur = by_key.get(key)
            if cur is None or ws > cur[0]:
                by_key[key] = (ws, create)
            elif cur[1] == 0 and create:
                by_key[key] = (cur[0], create)
        for key, (ws, create) in by_key.items():
            sig = self._launch_sig(key, create)
            a = self.anchors.get(key)
            if a is None:
                a = StableAnchor(sig)
                self.anchors[key] = a
            a.feed(ws, sig, now)

    def should_suppress(self, path, ws, relative_margin=None):
        key = self._key(path)
        if not key or ws <= 0:
            return False
        a = self.anchors.get(key)
        return bool(a) and a.should_suppress(ws, relative_margin)

    def purge_expired(self, now):
        for k in list(self.anchors.keys()):
            if now - self.anchors[k].last_seen > MAX_AGE:
                del self.anchors[k]

    def to_dict(self):
        return {k: v.to_dict() for k, v in self.anchors.items()}

    @classmethod
    def from_dict(cls, d):
        store = cls()
        if isinstance(d, dict):
            for k, v in d.items():
                try:
                    store.anchors[str(k)] = StableAnchor.from_dict(v)
                except Exception:
                    continue
        return store
