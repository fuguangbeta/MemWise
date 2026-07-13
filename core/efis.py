"""
E.F.I.S. v3 - 全程序智能调优大脑
因果诊断驱动，9 参数联动，覆盖优化管线全部 5 层
"""
import os, time, json
from collections import deque


PARAMS = {
    "deepen_theta":       {"min": 0.30, "max": 0.80, "default": 0.60, "step": 0.05},
    "layer3_agg_gate":    {"min": 0.30, "max": 0.90, "default": 0.60, "step": 0.05},
    "pid_kp":             {"min": 0.30, "max": 2.00, "default": 0.60, "step": 0.10},
    "pid_kd":             {"min": 0.05, "max": 0.50, "default": 0.10, "step": 0.05},
    "target_usage":       {"min": 35,   "max": 65,   "default": 60,   "step": 2},
    "interval_high":      {"min": 5,    "max": 20,   "default": 10,   "step": 2},
    "cooloff_base":       {"min": 60,   "max": 360,  "default": 360,  "step": 30},
    "learning_rate":      {"min": 0.05, "max": 0.40, "default": 0.30, "step": 0.02},
    "composite_kalman_w": {"min": 0.10, "max": 0.50, "default": 0.30, "step": 0.05},
}

WINDOW = 5
EVAL_INTERVAL = 5


class EfisController:

    def __init__(self, state_path=None):
        self.state_path = state_path
        self.params = {k: v["default"] for k, v in PARAMS.items()}
        self._window = deque(maxlen=WINDOW)
        self._cycle = 0
        self._symptoms = {}
        self._last_params = dict(self.params)
        self._adjust_log = []
        self.scene_params = {}
        self.current_scene = "general"
        self._last_scene = None
        self._scene_stable = 0
        self.load()

    def load(self):
        if not self.state_path:
            return
        efis_path = self.state_path.replace("state.json", "efis_state.json")
        if not os.path.exists(efis_path):
            return
        try:
            with open(efis_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            efis = data.get("efis", {})
            for k, v in efis.get("params", {}).items():
                if k in self.params:
                    lo, hi = PARAMS[k]["min"], PARAMS[k]["max"]
                    self.params[k] = max(lo, min(hi, v))
            self.scene_params = efis.get("scene_params", {})
            for sp in self.scene_params.values():
                for k in list(sp.keys()):
                    if k not in PARAMS:
                        del sp[k]
                    else:
                        lo, hi = PARAMS[k]["min"], PARAMS[k]["max"]
                        sp[k] = max(lo, min(hi, sp[k]))
            self.current_scene = efis.get("current_scene", "general")
            self._scene_stable = efis.get("scene_stable", 0)
            self._cycle = efis.get("cycle_count", 0)
            self._symptoms = efis.get("symptoms", {})
        except Exception:
            self.params = {k: v["default"] for k, v in PARAMS.items()}

    def save(self):
        if not self.state_path:
            return
        efis_path = self.state_path.replace("state.json", "efis_state.json")
        self.scene_params[self.current_scene] = dict(self.params)
        data = {"efis": {
            "version": 3,
            "params": self.params,
            "scene_params": self.scene_params,
            "current_scene": self.current_scene,
            "cycle_count": self._cycle,
            "symptoms": self._symptoms,
            "scene_stable": self._scene_stable,
            "adjust_log": self._adjust_log[-50:],
            "last_save": time.time(),
        }}
        tmp = efis_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        for _ in range(3):
            try:
                if os.path.exists(efis_path):
                    os.remove(efis_path)
                os.rename(tmp, efis_path)
                break
            except PermissionError:
                time.sleep(0.1)

    def detect_scene(self, snaps, fore_fullscreen, mem_pct):
        names = [s.name.lower() for s in snaps]
        if fore_fullscreen and mem_pct > 60:
            scene = "game"
        elif any(b in names for b in ["chrome", "msedge", "firefox", "brave", "opera"]):
            scene = "browser"
        elif any(d in names for d in ["devenv", "code", "clion", "idea", "pycharm", "eclipse"]):
            scene = "development"
        else:
            scene = "general"
        if scene != self.current_scene:
            self._last_scene = self.current_scene
            self.current_scene = scene
            self._scene_stable = 0
            self.scene_params.setdefault(scene, dict(self.params))
            saved = self.scene_params.get(scene, {})
            blend = {}
            for k in PARAMS:
                blend[k] = (self.params.get(k, PARAMS[k]["default"]) * 0.7 +
                            saved.get(k, PARAMS[k]["default"]) * 0.3)
            self.params = blend
            self.save()
        else:
            self._scene_stable = min(self._scene_stable + 1, 10)

    def tick(self, stats):
        self._window.append(stats)
        self._cycle += 1
        if self._cycle % EVAL_INTERVAL != 0 or len(self._window) < WINDOW:
            return ""
        diag = self._diagnose()
        if diag:
            self._apply(diag)
            self.save()
        return self._format_log()

    def _diagnose(self):
        w = list(self._window)
        n = len(w)
        mem_avg = sum(s["mem_pct"] for s in w) / n
        mem_hi = max(s["mem_pct"] for s in w)
        mem_lo = min(s["mem_pct"] for s in w)
        mem_amp = (mem_hi - mem_lo) / max(mem_avg, 1)
        freed_total = sum(s.get("cycle_freed", 0) for s in w)
        pf_total = sum(s.get("pf_delta", 0) for s in w)
        trimmed_total = sum(s.get("trimmed_cnt", 0) for s in w)
        cycles_sec = sum(s.get("cycle_duration", 30) for s in w)
        deepen_cnt = sum(s.get("deepen_cnt", 0) for s in w)
        deepen_extra = sum(s.get("deepen_extra", 0) for s in w)
        deepen_waste = (deepen_cnt > 0 and deepen_extra / max(deepen_cnt, 1) < 10 << 20)  # 10MB avg extra
        layer3_ran = sum(1 for s in w if s.get("layer3_ran"))
        layer3_extra = sum(s.get("layer3_extra", 0) for s in w)
        cool_cnt = sum(s.get("cooldown_cnt", 0) for s in w)
        repeat_fail = sum(s.get("repeat_fail", 0) for s in w)
        theta_mean = sum(s.get("theta_mean", 0.3) for s in w) / n
        theta_above = sum(s.get("theta_above_06", 0) for s in w) / n
        agg_mean = sum(s.get("agg", 0.5) for s in w) / n
        agg_change = sum(abs(s.get("agg", 0.5) - agg_mean) for s in w) / n
        results = {}
        target = self.params.get("target_usage", 60)
        if deepen_waste and deepen_cnt > 0:
            results["deepen_theta"] = +1
        elif theta_above < 0.15 and mem_avg > target:
            results["deepen_theta"] = -1
        if layer3_ran < n * 0.1 and mem_avg > target:
            results["layer3_agg_gate"] = -1
        elif layer3_ran >= n * 0.9 and layer3_extra / max(layer3_ran, 1) < 50 << 20:
            results["layer3_agg_gate"] = +1
        if mem_amp > 0.10 or (agg_change > 0.2 and pf_total / max(cycles_sec, 1) > 80):
            results["pid_kp"] = -1
        elif mem_avg > target + 5 and trimmed_total > 0:
            results["pid_kp"] = +1
        if mem_amp > 0.08:
            results["pid_kd"] = +1
        if mem_avg < target - 10:
            results["target_usage"] = -1
        elif mem_avg > target + 10 and trimmed_total > 0:
            results["target_usage"] = +1
        if pf_total / max(cycles_sec / 60, 1) > 100:
            results["interval_high"] = +1
        elif mem_avg > target and freed_total / max(cycles_sec / 60, 1) < 500:
            results["interval_high"] = -1
        if cool_cnt > trimmed_total * 0.2:
            results["cooloff_base"] = -1
        elif repeat_fail > max(trimmed_total * 0.05, 2):
            results["cooloff_base"] = +1
        theta_osc = sum(abs(s.get("theta_mean", 0.3) - theta_mean) for s in w) / n
        if theta_osc > 0.15:
            results["learning_rate"] = -1
        if trimmed_total > 0 and freed_total / max(trimmed_total, 1) < 20:
            results["composite_kalman_w"] = -1
        return results

    def _apply(self, diag):
        for param, direction in diag.items():
            if direction == 0:
                continue
            cfg = PARAMS[param]
            step = cfg["step"]
            cur = self.params[param]
            key = f"{param}{'+' if direction > 0 else '-'}"
            prev = self._symptoms.get(key, 0)
            if prev > 0 and (direction > 0) == (prev > 0):
                self._symptoms[key] = prev + 1
            else:
                self._symptoms[key] = 1 if direction > 0 else -1
                continue
            if abs(self._symptoms[key]) < 2:
                continue
            new_val = cur + direction * step
            new_val = max(cfg["min"], min(cfg["max"], new_val))
            if abs(new_val - cur) > 0.001:
                self._adjust_log.append({
                    "cycle": self._cycle, "param": param,
                    "old": cur, "new": new_val,
                    "reason": f"symptom_x{abs(self._symptoms[key])}",
                })
                self.params[param] = new_val
                self._symptoms[key] = 0

    def _format_log(self):
        if not self._adjust_log:
            return ""
        PARAM_CN = {"deepen_theta":"深度门槛","layer3_agg_gate":"深层清理","pid_kp":"响应速度",
                    "pid_kd":"抑制震荡","target_usage":"目标内存","interval_high":"高压间隔",
                    "cooloff_base":"失败冷却","learning_rate":"学习率","composite_kalman_w":"卡尔曼权重"}
        last = self._adjust_log[-1]
        cn = PARAM_CN.get(last['param'], last['param'])
        return f"EFIS调整{cn}: {last['old']:.2f}→{last['new']:.2f}"

    def get_params(self):
        return dict(self.params)
