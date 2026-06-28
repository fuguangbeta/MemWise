"""
E.F.I.S. 效率反馈智能系统 v2 — ERIS 五维诊断 -> 自适应调参 -> 实验日志+回滚+场景自适应
"""
import os
import time
import math
import json

DEFAULT_PARAMS = {
    "theta_gate": 0.18,
    "cpu_gate": 1.0,
    "max_trim": 50,
    "cooloff_base": 1200,
    "ws_baseline_mul": 1.20,
    "learning_rate": 0.3,
}

PARAM_LIMITS = {
    "theta_gate":      {"min": 0.10, "max": 0.50, "step": 0.02},
    "cpu_gate":        {"min": 0.30, "max": 3.00, "step": 0.10},
    "max_trim":        {"min": 5,    "max": 80,   "step": 5},
    "cooloff_base":    {"min": 1200, "max": 7200, "step": 300},
    "ws_baseline_mul": {"min": 1.05, "max": 1.50, "step": 0.03},
    "learning_rate":   {"min": 0.01, "max": 0.50, "step": 0.02},
}

DIAGNOSIS_MAP = {
    "capability": {"theta_gate": -1, "ws_baseline_mul": -1},
    "adaptivity": {"max_trim": 1, "cpu_gate": -1},
    "precision":  {"theta_gate": 1, "cooloff_base": 1},
    "momentum":   {"learning_rate": 1},
    "context":    {"max_trim": 1, "cpu_gate": -1},
}

REVERT_THRESHOLD = 3.0
REVERT_EVAL_TICKS = 30
CONSECUTIVE_BOOST = 3
REVERT_COOLDOWN = 5


class EfisController:

    def __init__(self, state_path=None):
        self.state_path = state_path
        self.params = dict(DEFAULT_PARAMS)
        self.eris_history = []
        self.last_save_time = 0
        self._last_efis_time = 0
        self.last_log = ""
        self.experiments = []
        self._direction_wins = {}
        self._revert_cooldown = {}
        self._clean_eff_history = []
        self.scene_params = {}
        self.current_scene = "general"
        self._last_scene = None
        self._scene_best = {}
        self.load()

    def load(self):
        """Load from efis_state.json (fallback to old state.json)"""
        if not self.state_path:
            return
        efis_path = self.state_path.replace("state.json", "efis_state.json")
        load_path = efis_path if os.path.exists(efis_path) else self.state_path
        try:
            with open(load_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            efis = data.get("efis", {})
            for k, v in efis.get("params", {}).items():
                if k in self.params:
                    self.params[k] = v
            self.eris_history = efis.get("history", [])
            self.last_save_time = efis.get("last_save", 0)
            self.experiments = efis.get("experiments", [])
            self.scene_params = efis.get("scene_params", {})
            self._direction_wins = efis.get("direction_wins", {})
            self._clean_eff_history = efis.get("clean_eff_history", [])
            self._scene_best = efis.get("scene_best", {})
            self.current_scene = efis.get("current_scene", "general")
            self._last_scene = efis.get("last_scene", self.current_scene)
            days_since = (time.time() - self.last_save_time) / 86400
            if days_since > 3:
                decay = min(1.0, (days_since - 3) * 0.05)
                for k in self.params:
                    d = DEFAULT_PARAMS[k]
                    self.params[k] = self.params[k] * (1 - decay) + d * decay
        except Exception:
            self.params = dict(DEFAULT_PARAMS)

    def save(self):
        """Save to efis_state.json (separate from learner, zero race)"""
        efis_path = self.state_path.replace("state.json", "efis_state.json")
        self.scene_params[self.current_scene] = dict(self.params)
        data = {
            "efis": {
                "params": self.params,
                "history": self.eris_history[-200:],
                "last_save": time.time(),
                "experiments": self.experiments[-100:],
                "scene_params": self.scene_params,
                "direction_wins": self._direction_wins,
                "clean_eff_history": self._clean_eff_history[-200:],
                "scene_best": self._scene_best,
                "current_scene": self.current_scene,
                "last_scene": self._last_scene,
            }
        }
        tmp = efis_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, efis_path)

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
            self.scene_params.setdefault(scene, dict(self.params))
            if scene in self._scene_best:
                best = self._scene_best[scene]
                for k in self.params:
                    self.params[k] = best.get(k, self.params.get(k))
            else:
                self.params = dict(self.scene_params.get(scene, DEFAULT_PARAMS))
            self.save()

    def tick(self, eris_components, stats):
        now = time.time()
        if now - self._last_efis_time < 300:
            return ""
        self._last_efis_time = now
        eris_total = eris_components.get("total", 50.0)
        self.eris_history.append(eris_total)
        clean_eff = self._calc_clean_efficiency(stats)
        self._clean_eff_history.append(clean_eff)
        self._evaluate_previous_experiments(self.experiments)
        logs = []
        for dim_name in DIAGNOSIS_MAP:
            dim_score = eris_components.get(dim_name, 0.5)
            if dim_score < 0.4:
                self._adjust_for_low_v2(dim_name, logs)
            elif dim_score > 0.75:
                self._relax_for_high(dim_name)
        self.save()
        return self.last_log

    def _calc_clean_efficiency(self, stats):
        if not stats:
            return 0.0
        trimmed = stats.get("trimmed_cnt", 0)
        freed = stats.get("cycle_freed", 0)
        attempts = stats.get("total_attempts", 0) or 1
        return (freed / attempts) if trimmed > 0 else 0.0

    def _evaluate_previous_experiments(self, experiments):
        if len(experiments) < 2:
            return
        last = experiments[-1]
        if last.get("reverted", False):
            return
        if len(self.eris_history) < 1:
            return
        eris_now = self.eris_history[-1]
        eris_before = last.get("eris_before", eris_now)
        drop = (eris_before - eris_now) / max(eris_before, 1)
        if drop > (REVERT_THRESHOLD / 100.0):
            for k, v in last.get("changes", {}).items():
                self.params[k] = v.get("old", self.params.get(k))
                self._revert_cooldown[k] = REVERT_COOLDOWN
            last["reverted"] = True
            self.last_log = f"EFIS回滚: {last.get('trigger_dim','?')}维度 下降{drop:.0%}"

    def _adjust_for_low_v2(self, dim_name, logs):
        for param, direction in DIAGNOSIS_MAP.get(dim_name, {}).items():
            if param in self._revert_cooldown and self._revert_cooldown[param] > 0:
                self._revert_cooldown[param] -= 1
                continue
            limits = PARAM_LIMITS.get(param, {})
            step = limits.get("step", 0.01)
            cur = self.params.get(param, limits.get("min", 0))
            step = max(step, cur * 0.05)
            new_val = cur + direction * step
            new_val = max(limits.get("min", new_val), min(limits.get("max", new_val), new_val))
            if abs(new_val - cur) > 0.001:
                changes = {param: {"old": cur, "new": new_val}}
                self.experiments.append({
                    "timestamp": time.time(),
                    "trigger_dim": dim_name,
                    "changes": changes,
                    "eris_before": self.eris_history[-1] if self.eris_history else 50,
                    "clean_efficiency_before": self._clean_eff_history[-1] if self._clean_eff_history else 0,
                    "reverted": False,
                })
                self.params[param] = new_val
                win_key = f"{param}+" if direction > 0 else f"{param}-"
                self._direction_wins[win_key] = self._direction_wins.get(win_key, 0) + 1
                if self._direction_wins[win_key] >= CONSECUTIVE_BOOST:
                    self._direction_wins[win_key] = 0
                    boosted = cur + direction * step * 2
                    self.params[param] = max(limits.get("min", boosted),
                                             min(limits.get("max", boosted), boosted))
                logs.append(f"{param} {direction:+}")

    def _relax_for_high(self, dim_name):
        for param, direction in DIAGNOSIS_MAP.get(dim_name, {}).items():
            limits = PARAM_LIMITS.get(param, {})
            cur = self.params.get(param, limits.get("min", 0))
            default_val = DEFAULT_PARAMS.get(param, cur)
            revert_step = abs(cur - default_val) * 0.1
            if revert_step < limits.get("step", 0.01):
                continue
            new_val = cur - direction * revert_step
            new_val = max(limits.get("min", new_val), min(limits.get("max", new_val), new_val))
            if abs(new_val - cur) > 0.001:
                self.params[param] = new_val

    def get_params(self):
        return dict(self.params)
