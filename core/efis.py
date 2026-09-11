"""
E.F.I.S. v3 - 全程序智能调优大脑
因果诊断驱动，12 参数联动，覆盖优化管线全部 5 层
"""
import os, time, json
from collections import deque


PARAMS = {
    "deepen_theta":       {"min": 0.30, "max": 0.80, "default": 0.60, "step": 0.05},
    "layer3_agg_gate":    {"min": 0.30, "max": 0.70, "default": 0.60, "step": 0.05},
    "pid_kp":             {"min": 0.45, "max": 2.00, "default": 0.60, "step": 0.10},  # min 0.45：防漂移触底（0.30 时高压峰值 agg 仅 0.38，稳态豁免失效）
    "pid_kd":             {"min": 0.05, "max": 0.35, "default": 0.10, "step": 0.05},  # max 0.35：防漂移触顶（0.50 的 D 项振荡尖峰，90 分位失真）
    "target_usage":       {"min": 35,   "max": 65,   "default": 60,   "step": 2},
    "cooloff_base":       {"min": 60,   "max": 360,  "default": 360,  "step": 30},
    "learning_rate":      {"min": 0.10, "max": 0.90, "default": 0.50, "step": 0.05},  # EWMA 反馈学习率（λ）：接入 record_clean 的 gain/cost EWMA 主通道，fast/slow 趋势通道固定
    "composite_kalman_w": {"min": 0.10, "max": 0.50, "default": 0.30, "step": 0.05},
    "kalman_r":           {"min": 1.0,  "max": 20.0,  "default": 5.0,   "step": 1.0},
    "anchor_margin":      {"min": 0.05, "max": 0.30, "default": 0.15,  "step": 0.05},  # 稳态锚点抑制余量（P1-D：余量小=抑制更严/清理更多；余量大=更保守）
    # ── 活跃门（2026-09-11 审查 F22 新增）：原为硬编码常量，而这两个门是量化收益最大的单点
    #    （CPU 门在浏览器高峰/IDE 编译场景影响 18-26% 释放量、IO 门在下载/播放场景 4.9%），
    #    交给 EFIS 自适应才可能吃到上限。默认值与原常量逐字一致 ⇒ 行为零变化。──
    "cpu_gate":           {"min": 3.0,  "max": 25.0, "default": 8.0,   "step": 1.0},   # CPU 活跃门（%，占全机算力口径）
    "io_gate":            {"min": 1.0,  "max": 16.0, "default": 4.0,   "step": 1.0},   # IO 活跃门（MB/s）
}

WINDOW = 5
EVAL_INTERVAL = 5

# ── 模式×场景参数组（2026-08-16 用户定稿）：每个清理模式拥有独立参数组，
#    与场景维度叠加 = 4 模式 × 4 场景 = 16 组（懒创建），模式切换互不污染 ──
# deep/full 科学激进初始值（依据：四模式理论压缩实验——中压 45% 场景 deep 稳态
# 29-30%、full 22%，target 须低于稳态才持续施压；full 物理下限≈22%，35 为范围下限；
# 激进模式冷却更短、对新观测更敏感、反馈适应更快；其余无消费方逻辑/实验依据的
# 参数保持 PARAMS 默认，靠 EFIS 在各自组内自适应）
MODE_DEFAULTS = {
    "quick": {},
    "normal": {},
    "deep": {
        "target_usage": 45, "cooloff_base": 240, "kalman_r": 4.0,
        "learning_rate": 0.60, "pid_kp": 0.80, "deepen_theta": 0.50,
    },
    "full": {
        "target_usage": 35, "cooloff_base": 180, "kalman_r": 3.0,
        "learning_rate": 0.70,
    },
}

# 每模式参与调参的参数白名单（无消费方的参数不参与调参，防无效调参污染他模式）：
# quick 无进程参数消费不调；normal 全调；deep/full 恒触发 L3（gate 无消费）且跳过稳态锚点
# 抑制（anchor_margin 无消费）；full 全档深清（deepen_theta 无消费）。
# ⚠ 响应类参数（pid_kp/pid_kd/target_usage）在 gap 轻量阶段的 PID 输出真实生效
# （agg 强制 ≥0.8 仅作用于收割 optimize 分支）——full 必须保留调参（2026-08-16 实验实证）
MODE_TUNE_WHITELIST = {
    "quick": [],
    "normal": list(PARAMS.keys()),
    "deep": [k for k in PARAMS if k not in ("layer3_agg_gate", "anchor_margin")],
    "full": [k for k in PARAMS if k not in ("layer3_agg_gate", "anchor_margin", "deepen_theta")],
}


class EfisController:

    def __init__(self, state_path=None):
        self.state_path = state_path
        # 模式×场景参数组（懒创建）：mode_params[mode][scene] = {"params": {...}, "symptoms": {...}}
        # 每个清理模式独立演进，场景维度叠加（16 组），切换模式零污染（2026-08-16 用户定稿）
        self.mode_params = {}
        self.current_mode = "normal"
        self._window = deque(maxlen=WINDOW)
        self._cycle = 0
        self._adjust_log = []
        self.current_scene = "general"
        self._last_scene = None
        self._scene_stable = 0
        self.load()

    def _group(self, mode=None, scene=None):
        """取 (mode, scene) 参数组，懒创建（冷启动 = PARAMS 默认 + 模式激进初始值）。
        mode=None 回退当前模式（非"normal"——否则场景混合/调参会落到 normal 组，2026-08-16 修复）"""
        mode = mode if mode in MODE_TUNE_WHITELIST else self.current_mode
        scene = scene or self.current_scene
        g = self.mode_params.setdefault(mode, {}).setdefault(scene, {})
        if "params" not in g:
            base = {k: v["default"] for k, v in PARAMS.items()}
            base.update(MODE_DEFAULTS.get(mode, {}))
            g["params"] = base
            g["symptoms"] = {}
        return g

    @property
    def params(self):
        """当前生效参数（当前模式×当前场景组；property 兼容既有消费方）"""
        return self._group()["params"]

    @property
    def _symptoms(self):
        return self._group()["symptoms"]

    def set_mode(self, mode):
        """切换当前清理模式（模式参数组独立；模式切换清空评估窗口——不同模式的
        统计口径不可比，防旧模式数据污染新模式诊断）"""
        if mode not in MODE_TUNE_WHITELIST:
            mode = "normal"
        if mode != self.current_mode:
            self.current_mode = mode
            self._window.clear()
            self._cycle = 0
            self._last_scene = None
            self._scene_stable = 0

    def get_params(self, mode=None):
        """返回指定（或当前）模式当前场景的参数快照（浅拷贝，防外部修改污染组）"""
        return dict(self._group(mode)["params"])

    def _efis_state_path(self):
        """EFIS 状态文件路径 = 状态文件同目录下的 memwise_efis_state.json。
        2026-09-11 审查：原实现用 `state_path.replace("state.json", "efis_state.json")`——依赖
        文件名子串，一旦状态文件不叫 memwise_state.json（自定义/调试路径）就会推出错误路径并
        静默回退默认值（本次验收即因此暴露）。改为显式拼接，对真实路径行为逐字一致。"""
        return os.path.join(os.path.dirname(self.state_path), "memwise_efis_state.json")

    def load(self):
        if not self.state_path:
            return
        efis_path = self._efis_state_path()
        if not os.path.exists(efis_path):
            return
        try:
            with open(efis_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            efis = data.get("efis", {})
            version = efis.get("version", 3)
            if version >= 4:
                mp = efis.get("mode_params", {})
                for mode, scenes in mp.items():
                    if mode not in MODE_TUNE_WHITELIST or not isinstance(scenes, dict):
                        continue
                    for scene, g in scenes.items():
                        if not isinstance(g, dict) or not isinstance(g.get("params"), dict):
                            continue
                        group = self._group(mode, scene)
                        for k, v in g["params"].items():
                            if k in PARAMS:
                                lo, hi = PARAMS[k]["min"], PARAMS[k]["max"]
                                group["params"][k] = max(lo, min(hi, v))
                        sym = g.get("symptoms", {})
                        if isinstance(sym, dict):
                            group["symptoms"] = {k: v for k, v in sym.items() if isinstance(v, (int, float)) and v != 0}
                self.current_mode = efis.get("current_mode", "normal")
                if self.current_mode not in MODE_TUNE_WHITELIST:
                    self.current_mode = "normal"
                self.current_scene = efis.get("current_scene", "general")  # v4 补存（P10）：重启直接加载场景组
                self._cycle = efis.get("cycle_count", 0)
                self._adjust_log = efis.get("adjust_log", [])[-50:]
            else:
                # v3 迁移（2026-08-16）：旧全局 params → normal.general；旧场景参数 → normal 的
                # 4 个场景组；其余模式组用模式初始值（现有 normal 调参成果零丢失）
                old_params = efis.get("params", {})
                old_scenes = efis.get("scene_params", {})
                self.current_scene = efis.get("current_scene", "general")
                self._scene_stable = efis.get("scene_stable", 0)
                self._cycle = efis.get("cycle_count", 0)
                self._symptoms_legacy = {k: v for k, v in efis.get("symptoms", {}).items() if v != 0}
                self._adjust_log = efis.get("adjust_log", [])[-50:]
                # normal.general 用旧全局参数（合并旧症状）
                ng = self._group("normal", self.current_scene)
                for k, v in old_params.items():
                    if k in PARAMS:
                        lo, hi = PARAMS[k]["min"], PARAMS[k]["max"]
                        ng["params"][k] = max(lo, min(hi, v))
                ng["symptoms"].update(self._symptoms_legacy)
                # normal 各场景用旧场景参数（跳过 current_scene——该组以旧全局 params 为准，
                # 含场景混合后的当前生效值，2026-08-16 审查 P9：原实现被 scene_params 覆盖丢失成果）
                for scene, sp in old_scenes.items():
                    if scene == self.current_scene or not isinstance(sp, dict):
                        continue
                    g = self._group("normal", scene)
                    for k, v in sp.items():
                        if k in PARAMS:
                            lo, hi = PARAMS[k]["min"], PARAMS[k]["max"]
                            g["params"][k] = max(lo, min(hi, v))
            # 顶格症状清洗（沿用 v2.4 逻辑，逐组执行）
            for mode in list(self.mode_params.keys()):
                for scene, g in self.mode_params[mode].items():
                    syms = g.get("symptoms", {})
                    for k in list(syms.keys()):
                        base = k[:-1]
                        if base not in PARAMS:
                            syms.pop(k, None)
                            continue
                        if k.endswith("+") and g["params"].get(base, 0) >= PARAMS[base]["max"] - 1e-9:
                            syms.pop(k, None)
                        elif k.endswith("-") and g["params"].get(base, 0) <= PARAMS[base]["min"] + 1e-9:
                            syms.pop(k, None)
        except Exception:
            self.mode_params = {}
            self.current_mode = "normal"

    def save(self):
        if not self.state_path:
            return
        efis_path = self._efis_state_path()
        mp = {}
        for mode, scenes in self.mode_params.items():
            mp[mode] = {}
            for scene, g in scenes.items():
                mp[mode][scene] = {"params": dict(g["params"]), "symptoms": dict(g.get("symptoms", {}))}
        data = {"efis": {
            "version": 4,
            "mode_params": mp,
            "current_mode": self.current_mode,
            "current_scene": self.current_scene,
            "cycle_count": self._cycle,
            "adjust_log": self._adjust_log[-50:],
            "last_save": time.time(),
        }}
        # tmp 附加进程号（2026-09-06 审查 F3）：跨进程并发写退化为"最后写者胜"而非交错损坏
        tmp = f"{efis_path}.{os.getpid()}.tmp"
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
        elif any(b in n for n in names for b in ["chrome", "msedge", "firefox", "brave", "opera"]):
            scene = "browser"
        elif any(d in n for n in names for d in ["devenv", "code", "clion", "idea", "pycharm", "eclipse"]):
            scene = "development"
        else:
            scene = "general"
        if scene != self.current_scene:
            old_scene = self.current_scene
            self.current_scene = scene
            self._scene_stable = 0
            # 场景混合只作用于当前模式的场景组（2026-08-16：模式×场景 16 组并存）。
            # 混合基准 = 旧场景组当前值（current_scene 已更新，须显式取旧场景），
            # 目标 = 新场景组历史值 7:3（与旧全局版语义一致）
            old_group = self._group(scene=old_scene)["params"]
            new_group = self._group(scene=scene)["params"]
            blend = {}
            for k in PARAMS:
                blend[k] = (old_group.get(k, PARAMS[k]["default"]) * 0.7 +
                            new_group.get(k, PARAMS[k]["default"]) * 0.3)
            self._group(scene=scene)["params"] = blend
            self.save()
        else:
            self._scene_stable = min(self._scene_stable + 1, 10)

    def tick(self, stats):
        # 模式同步（幂等：engine 周期末已 set_mode；直接调 tick 的路径（测试/CLI）也正确）
        if stats.get("mode") in MODE_TUNE_WHITELIST:
            self.set_mode(stats["mode"])
        # 游戏态冻结（2026-08-30）：游戏周期的统计被设计性抑制主导（系统级操作跳过/
        # gap×1.5/试探禁用/仅非游戏进程可清），释放口径不具备调参归因意义——不进入
        # 任何参数组的评估窗口，防止学习器与保护意图对抗（如锚点自平衡在游戏期收紧
        # 余量=游戏期清更狠）。翻转周期整周期隔离：清空窗口，游戏退出后从干净起点
        # 重新累积；进程画像/树权重等全局面照常学习（与隔离规格哲学一致）
        if stats.get("game"):
            self._window.clear()
            return ""
        if not MODE_TUNE_WHITELIST.get(self.current_mode):
            return ""  # quick 模式无进程参数消费：不累积统计窗口、不做诊断（2026-08-16 审查 P11）
        self._window.append(stats)
        self._cycle += 1
        if self._cycle % EVAL_INTERVAL != 0 or len(self._window) < WINDOW:
            return ""
        diag = self._diagnose()
        if diag:
            n_before = len(self._adjust_log)
            # 模式调参白名单（2026-08-16）：本模式无消费方的参数不参与调参——
            # 防无效调参（如 full 的 PID 被 agg 覆盖、deep/full 的 L3 门恒无消费）
            diag = {k: v for k, v in diag.items() if k in MODE_TUNE_WHITELIST[self.current_mode]}
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
        # 活跃门自平衡（2026-09-11 审查 F22）：内存高于目标却清不动（每轮能清的进程数不足 1）
        # → 放宽门限，让更忙的进程也参与清理；清理失败偏多 → 收紧门限，少碰活跃进程以降低无谓 PF
        if mem_avg > target and trimmed_total < n:
            results["cpu_gate"] = +1
            results["io_gate"] = +1
        elif repeat_fail > max(trimmed_total * 0.05, 2):
            results["cpu_gate"] = -1
            results["io_gate"] = -1
        return results

    def _apply(self, diag):
        # 协方差监控：检测参数反向调整，冻结变动幅度较小的一方
        # 豁免：anchor_margin 的"-1"语义=收紧抑制=更激进（与 pid_kp+/target_usage+ 同向，符号相反
        # 但非补偿振荡）；cpu_gate/io_gate 是活跃准入量（放宽≠与 PID 反向调节）——一并排除防误冻结
        # （曾见抑制自平衡被 pid_kp 反向冻结失效）
        _no_freeze = ("anchor_margin", "cpu_gate", "io_gate")
        conflicting = {}
        for p1, d1 in diag.items():
            if d1 == 0 or p1 in _no_freeze: continue
            for p2, d2 in diag.items():
                if p2 <= p1 or d2 == 0 or p2 in _no_freeze: continue
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
                    "kalman_r":"卡尔曼噪声","anchor_margin":"锚点余量",
                    "cpu_gate":"CPU活跃门","io_gate":"IO活跃门"}
        last = self._adjust_log[-1]
        cn = PARAM_CN.get(last['param'], last['param'])
        return f"EFIS调整{cn}: {last['old']:.2f}→{last['new']:.2f}"
