"""
E.F.I.S. v3 - 全程序智能调优大脑
因果诊断驱动，9 参数联动，覆盖优化管线全部 5 层
"""
import os, time, json
from collections import deque


PARAMS = {
    "deepen_theta":       {"min": 0.30, "max": 0.80, "default": 0.60, "step": 0.05},
    "layer3_agg_gate":    {"min": 0.30, "max": 0.70, "default": 0.60, "step": 0.05},
    "pid_kp":             {"min": 0.30, "max": 2.00, "default": 0.60, "step": 0.10},
    "pid_kd":             {"min": 0.05, "max": 0.50, "default": 0.10, "step": 0.05},
    "target_usage":       {"min": 35,   "max": 65,   "default": 60,   "step": 2},
    "cooloff_base":       {"min": 60,   "max": 360,  "default": 360,  "step": 30},
    "learning_rate":      {"min": 0.10, "max": 0.90, "default": 0.50, "step": 0.05},  # EWMA 反馈学习率（λ）：接入 record_clean 的 gain/cost EWMA 主通道，fast/slow 趋势通道固定
    "composite_kalman_w": {"min": 0.10, "max": 0.50, "default": 0.30, "step": 0.05},
    "kalman_r":           {"min": 1.0,  "max": 20.0,  "default": 5.0,   "step": 1.0},
    "anchor_margin":      {"min": 0.05, "max": 0.30, "default": 0.15, "step": 0.05},  # 稳态锚点抑制余量（P1-D：余量小=抑制更严/清理更多；余量大=更保守）
}

WINDOW = 5
EVAL_INTERVAL = 5


class EfisController:

    def __init__(self, state_path=None):
        self.state_path = state_path
        self.params = {k: v["default"] for k, v in PARAMS.items()}
        self._window = deque(maxlen=WINDOW)
        self._cycle = 0
        self._last_adjust_cycle = 0  # ERIS 用：记录最近一次调参的周期号
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
            # 清理旧版残留的 0 值 symptoms（v2.4 用 =0 而非 pop）
            self._symptoms = {k: v for k, v in self._symptoms.items() if v != 0}
            # 顶格症状清洗：参数已到边界且症状方向与之矛盾时无调整空间，残留症状直接清除
            # （此前曾见 pid_kd+ 残留 264：参数顶格后该方向不再触发，清除逻辑永不执行）
            for k in list(self._symptoms.keys()):
                base = k[:-1]
                if base not in PARAMS:
                    self._symptoms.pop(k, None)
                    continue
                if k.endswith("+") and self.params.get(base, 0) >= PARAMS[base]["max"] - 1e-9:
                    self._symptoms.pop(k, None)
                elif k.endswith("-") and self.params.get(base, 0) <= PARAMS[base]["min"] + 1e-9:
                    self._symptoms.pop(k, None)
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
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, efis_path)
        except Exception:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

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
            n_before = len(self._adjust_log)
            self._apply(diag)
            self.save()
            if len(self._adjust_log) > n_before:
                return self._format_log()
        return ""  # 无实际调整不播报：顶格/症状未满/冲突冻结时不得重播旧记录（曾见 0.60→0.50 连续重播 11 轮）

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
        mode = w[-1].get("mode", "normal") if w else "normal"
        if mode == "normal":
            # 仅 normal 模式寻优（deep/full 无条件执行 Layer3，调 gate 无消费方会空转）
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
        elif mem_amp < 0.03 and mem_avg < target:
            # 振幅极小且内存低于目标 → 系统稳定，降低微分阻尼（原只有 +1 单向爬升）
            results["pid_kd"] = -1
        if mem_avg < target - 10:
            results["target_usage"] = -1
        elif mem_avg > target + 10 and trimmed_total > 0:
            results["target_usage"] = +1
        if cool_cnt > trimmed_total * 0.2:
            results["cooloff_base"] = -1
        elif repeat_fail > max(trimmed_total * 0.05, 2):
            results["cooloff_base"] = +1
        # 学习率（EWMA λ）：系统振荡大 → 降（平滑反馈，抑制 θ 抖动）；
        # 稳定 + 压力低于目标 + 释放平庸 → 升（加速适应行为变化）
        if mem_amp > 0.10 or (agg_change > 0.2 and pf_total / max(cycles_sec, 1) > 80):
            results["learning_rate"] = -1
        elif mem_amp < 0.04 and mem_avg < target and trimmed_total > 0 \
                and freed_total / max(trimmed_total, 1) < 60:
            results["learning_rate"] = +1
        if trimmed_total > 0 and freed_total / max(trimmed_total, 1) < 20:
            results["composite_kalman_w"] = -1
        elif trimmed_total > 0 and freed_total / max(trimmed_total, 1) > 100:
            # 平均每进程释放充足 → 回升 Kalman 权重（原只有 -1 单向下降）
            results["composite_kalman_w"] = +1
        # 锚点抑制自平衡（压缩能力兜底）：抑制拦截多但内存仍高于目标 → 收紧抑制余量
        # （多清）；无抑制且内存低于目标 → 放宽余量（更保守）。防"抑制过度压不下去"
        suppress_avg = sum(s.get("suppress_cnt", 0) for s in w) / n
        if suppress_avg > 0 and mem_avg > target:
            results["anchor_margin"] = -1
        elif suppress_avg == 0 and mem_avg < target - 5:
            results["anchor_margin"] = +1
        return results

    def _apply(self, diag):
        # 协方差监控：检测参数反向调整，冻结变动幅度较小的一方
        # anchor_margin 例外：其"-1"语义=收紧抑制=更激进，与 pid_kp+/target_usage+ 语义同向
        # （符号相反但非补偿振荡）——排除防误冻结（曾见抑制自平衡被 pid_kp 反向冻结失效）
        conflicting = {}
        for p1, d1 in diag.items():
            if d1 == 0 or p1 == "anchor_margin": continue
            for p2, d2 in diag.items():
                if p2 <= p1 or d2 == 0 or p2 == "anchor_margin": continue
                if (d1 > 0 and d2 < 0) or (d1 < 0 and d2 > 0):
                    # 反向调整 → 冻结 step 较小的
                    if PARAMS[p1]["step"] < PARAMS[p2]["step"]:
                        conflicting[p1] = 0
                    else:
                        conflicting[p2] = 0
        for p in conflicting:
            diag[p] = 0
        for param, direction in diag.items():
            if direction == 0:
                continue
            cfg = PARAMS[param]
            step = cfg["step"]
            cur = self.params[param]
            key = f"{param}{'+' if direction > 0 else '-'}"
            prev = self._symptoms.get(key, 0)
            # 参数已在该方向顶格：症状无调整空间，直接清除（防无界累积，曾见 pid_kd+ 涨到 264）
            if (direction > 0 and cur >= cfg["max"] - 1e-9) or (direction < 0 and cur <= cfg["min"] + 1e-9):
                self._symptoms.pop(key, None)
                continue
            if prev != 0 and (direction > 0) == (prev > 0):
                self._symptoms[key] = prev + (1 if direction > 0 else -1)
            else:
                self._symptoms[key] = 1 if direction > 0 else -1
                continue
            if abs(self._symptoms[key]) < 2:
                continue
            new_val = cur + direction * step
            new_val = max(cfg["min"], min(cfg["max"], new_val))
            if abs(new_val - cur) <= 0.001:
                # 已到参数边界，症状无调整空间：清除防无界累积（曾见 pid_kd+ 涨到 264）
                self._symptoms.pop(key, None)
                continue
            self._adjust_log.append({
                    "cycle": self._cycle, "param": param,
                    "old": cur, "new": new_val,
                    "reason": f"symptom_x{abs(self._symptoms[key])}",
                })
            self.params[param] = new_val
            self._symptoms.pop(key, None)  # 删除而非置0，防止dict无限膨胀
            self._last_adjust_cycle = self._cycle  # ERIS 用（当前 ERIS 走 _cycle+_adjust_log，字段保留兼容）
            # 内存中保留最近200条，防长期运行无限增长（持久化截取50条在save中）
            if len(self._adjust_log) > 200:
                self._adjust_log = self._adjust_log[-100:]

    def _format_log(self):
        if not self._adjust_log:
            return ""
        PARAM_CN = {"deepen_theta":"深度门槛","layer3_agg_gate":"深层清理","pid_kp":"响应速度",
                    "pid_kd":"抑制震荡","target_usage":"目标内存",
                    "cooloff_base":"失败冷却","composite_kalman_w":"卡尔曼权重",
                    "learning_rate":"学习速率",
                    "kalman_r":"卡尔曼噪声","anchor_margin":"锚点余量"}
        last = self._adjust_log[-1]
        cn = PARAM_CN.get(last['param'], last['param'])
        return f"EFIS调整{cn}: {last['old']:.2f}→{last['new']:.2f}"

    def get_params(self):
        return dict(self.params)
