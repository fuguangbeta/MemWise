# -*- coding: utf-8 -*-
"""轻量补间/缓动（无第三方依赖；供 GUI 动效使用）。

设计：每个 key 一条动画链，新目标从“当前值”重定向（不跳变、不叠加）；
调度交给调用方（Tk 的 after），本模块只管时间与曲线，便于单测。
"""
import time
import math


def cubic_bezier(x1, y1, x2, y2):
    """返回 y = f(x) 的三次贝塞尔求值（x 用 Newton 迭代反解 t，端点精确）。"""
    def _f(x):
        if x <= 0.0:
            return 0.0
        if x >= 1.0:
            return 1.0
        t = x
        for _ in range(8):
            # B(t) - x
            mt = 1.0 - t
            bx = (3.0 * mt * mt * t * x1 + 3.0 * mt * t * t * x2 + t * t * t)
            if abs(bx - x) < 1e-5:
                break
            # derivative
            dbx = (3.0 * mt * mt * x1 + 6.0 * mt * t * (x2 - x1) + 3.0 * t * t * (1.0 - x2))
            if abs(dbx) < 1e-6:
                break
            t -= (bx - x) / dbx
            t = max(0.0, min(1.0, t))
        mt = 1.0 - t
        return 3.0 * mt * mt * t * y1 + 3.0 * mt * t * t * y2 + t * t * t
    return _f


# 与参考动效（dsh-mounts）同曲线；EASE_IN 用于淡出
EASE_OUT = cubic_bezier(0.16, 1.0, 0.3, 1.0)
EASE_IN_OUT = cubic_bezier(0.83, 0.0, 0.17, 1.0)
EASE_IN = cubic_bezier(0.7, 0.0, 0.84, 0.0)
LINEAR = cubic_bezier(0.25, 0.25, 0.75, 0.75)


def ease_in_out_cos(p):
    """余弦 S 曲线：慢起、快中、慢收，峰值约 1.57× 平均速度。"""
    p = min(1.0, max(0.0, p))
    return 0.5 - 0.5 * math.cos(math.pi * p)


EASE_IN_OUT_COS = ease_in_out_cos


class Animator:
    """单链补间调度器：key 唯一，重定向从当前值继续。"""

    def __init__(self, schedule, cancel=None, frame_ms=16):
        self._schedule = schedule
        self._cancel = cancel
        self._frame = max(8, int(frame_ms))
        self._jobs = {}
        self._timer_id = None
        self._now = time.perf_counter

    def tween(self, key, target, duration_ms, ease, apply, start=None, on_done=None):
        now = self._now()
        job = self._jobs.get(key)
        cur = job["value"] if job else (float(start) if start is not None else float(target))
        self._jobs[key] = {
            "from": float(cur), "to": float(target), "t0": now,
            "dur": max(1.0, float(duration_ms)) / 1000.0, "ease": ease,
            "apply": apply, "value": float(cur), "done": on_done,
        }
        if self._timer_id is None:
            self._timer_id = self._schedule(self._frame, self._step)

    def _step(self):
        self._timer_id = None
        now = self._now()
        for key in list(self._jobs.keys()):
            job = self._jobs.get(key)
            if job is None:
                continue
            p = (now - job["t0"]) / job["dur"]
            if p >= 1.0:
                p = 1.0
            v = job["from"] + (job["to"] - job["from"]) * job["ease"](p)
            job["value"] = v
            try:
                job["apply"](v)
            except Exception:
                self._jobs.pop(key, None)
                continue
            if p >= 1.0:
                self._jobs.pop(key, None)
                try:
                    if job["done"]:
                        job["done"]()
                except Exception:
                    pass
        if self._jobs:
            self._timer_id = self._schedule(self._frame, self._step)

    def cancel(self, key):
        self._jobs.pop(key, None)

    def cancel_all(self):
        self._jobs.clear()
        if self._timer_id is not None and self._cancel:
            try:
                self._cancel(self._timer_id)
            except Exception:
                pass
        self._timer_id = None
