"""
PARES Judger — PID 压力控制器 + Thompson Sampling 联合判定
"""
import time
import os, sys
from .learner import _is_system_core

# frozen windowed 下 sys.stderr 为 None，统一兜底（防异常路径 print 自身崩溃）
_ERR = sys.stderr or open(os.devnull, "w", encoding="utf-8")

def _mb(b):
    return b / (1 << 20)

# PID 默认参数
DEFAULT_KP = 1.0    # 比例系数 — 响应当前压力 (更积极)
DEFAULT_KI = 0.10   # 积分系数 — 消除稳态误差
DEFAULT_KD = 0.15   # 微分系数 — 抑制震荡 (快速升压时提前响应)
TARGET_USAGE = 30.0  # 目标内存使用率 (%) — 对标 MemReduct 极致优化
DT = 5.0             # 控制周期 (秒，匹配 daemon tick)

SYSTEM_DIR_PREFIXES = ("c:\\windows\\", "c:\\program files\\", "c:\\program files (x86)\\")


class PidController:
    """PID 连续反馈控制器"""

    def __init__(self, kp=DEFAULT_KP, ki=DEFAULT_KI, kd=DEFAULT_KD, target=TARGET_USAGE):
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.target = target
        self._integral = 0.0
        self._prev_error = 0.0
        self._last_time = time.time()
        self._windup_limit = 20.0  # 抗饱和

    def update(self, current_usage):
        """根据当前内存使用率计算 aggressiveness ∈ [0,1] · 三区增益调度"""
        now = time.time()
        dt = max(0.5, min(10.0, now - self._last_time))
        error = current_usage - self.target
        
        # 三区增益调度：低/中/高压使用不同的响应强度
        if current_usage < 40:
            zone_kp, zone_kd = 0.3, 0.05
        elif current_usage < 75:
            zone_kp, zone_kd = self.kp, self.kd
        else:
            zone_kp, zone_kd = min(2.0, self.kp * 1.5), min(0.20, self.kd * 1.5)

        # P
        p_term = zone_kp * error

        # I (带抗饱和)
        self._integral += error * dt
        self._integral = max(-self._windup_limit, min(self._windup_limit, self._integral))
        i_term = self.ki * self._integral

        # D
        d_term = zone_kd * (error - self._prev_error) / dt if dt > 0 else 0.0

        # 输出
        output = p_term + i_term + d_term
        self._prev_error = error
        self._last_time = now

        # 归一化到 [0, 1]
        aggressiveness = max(0.0, min(1.0, output / 50.0))
        return aggressiveness

    def reset(self):
        self._integral = 0.0
        self._prev_error = 0.0
        self._last_time = time.time()


class PareJudger:
    """PARES 判定器 — PID + Thompson 联合决策 + 游戏模式激进阈值"""

    def __init__(self, learner, config):
        self.learner = learner
        self.cfg = config
        self.game_mode = False
        self._game_proc_set = set()  # 当前检测到的游戏进程名集合
        self._game_pid_set = set()  # 当前检测到的游戏进程 PID 集合（精确保护）
        # 游戏模式参数覆盖（游戏本体由 PID 精确保护，前台/冷却与常规一致避免误伤）
        self._game_overrides = {
            "fg_gate": 0.35,      # 前台非游戏程序保持保护（游戏全屏时前台即游戏，已被 PID 保护）
            "min_ws": 524288,     # 0.5MB（正常 1MB）
            "cooloff_base": 300,  # 与常规一致：失败进程不快速重试（避免反复清同一批）
        }
        efis_cfg = config.get("efis_params", {})
        self.pid = PidController(
            kp=efis_cfg.get("pid_kp", config.get("kp", DEFAULT_KP)),
            ki=config.get("ki", DEFAULT_KI),
            kd=efis_cfg.get("pid_kd", config.get("kd", DEFAULT_KD)),
            target=efis_cfg.get("target_usage", config.get("target_usage", TARGET_USAGE)),
        )
        self.aggressiveness = 0.0
        self._prev_agg = 0.0
        self._last_mem_pct = 50
        self.cooldown = {}
        self._info_msgs = []
        self.pf_before = {}
        self._post_clean_ws = {}  # 进程清理后的 WS 基线
        self._post_clean_time = {}  # 基线设置时间戳（20分钟填满判定窗口 / 1小时过期清理）
        self._probe_last_time = {}

    # ── PID ──

    def _agg_label(self, v):
        if v <= 0.01: return "极低"
        if v < 0.40: return "低"
        if v < 0.60: return "中"
        return "高"

    def _mem_label(self, pct):
        if pct < 30: return "充裕"
        if pct < 60: return "正常"
        if pct < 80: return "偏高"
        return "极高"

    def update_pressure(self, mem_usage_pct):
        """根据内存压力更新 PID，返回当前 aggressiveness；同时维护 30s 采样内存趋势（供策略树2）"""
        self._last_mem_pct = mem_usage_pct
        now = time.time()
        t_prev = getattr(self, '_mem_trend_t', 0.0)
        v_prev = getattr(self, '_mem_trend_v', None)
        if v_prev is None:
            self._mem_trend_v = mem_usage_pct
            self._mem_trend_t = now
            self._mem_trend = 0.0
        elif now - t_prev >= 30:
            raw = (mem_usage_pct - v_prev) / 100.0
            self._mem_trend = 0.5 * raw + 0.5 * getattr(self, '_mem_trend', 0.0)
            self._mem_trend_v = mem_usage_pct
            self._mem_trend_t = now
        # 同步真实上下文给 learner（thompson_score 参数化后作为兜底源）
        try:
            self.learner._ctx["mem_pct"] = mem_usage_pct
        except Exception:
            pass
        self.aggressiveness = self.pid.update(mem_usage_pct)
        self._prev_agg = self.aggressiveness
        return self.aggressiveness

    # ── 决策 ──

    def can_trim(self, snap):
        """联合决策: PID × Thompson × 安全规则 (游戏模式下阈值更激进)"""
        name = snap.name.lower()

        # ── 游戏模式：游戏进程绝对保护（按实际检测 PID，精确到实例）──
        if self.game_mode and snap.pid in self._game_pid_set:
            return False, "游戏进程(保护)"
        
        # 安全规则 (不变)
        if _is_system_core(name):
            return False, "系统核心进程"

        never = self.cfg.get("never", [])
        if name in never or snap.pid in never:
            return False, "用户黑名单"

        is_fg = getattr(snap, "fg", False)

        # 游戏模式参数覆盖
        fg_gate = self._game_overrides["fg_gate"] if self.game_mode else 0.35
        min_ws_gate = self._game_overrides["min_ws"] if self.game_mode else (1 << 20)
        
        efis = self.cfg.get("efis_params", {})
        if is_fg:
            if self.aggressiveness < fg_gate:
                return False, "前台窗口"

        if snap.ws < min_ws_gate:
            return False, "工作集太小"

        # ── WS 基线检查（替代旧冷却：判断是否已重新填满，不是干等时间）──
        # 判定窗口 1200s（20 分钟）：期间 WS 未填满则不重复清理；窗口过后重新评估（基线本身 1 小时后过期清理）
        now = time.time()
        baseline = self._post_clean_ws.get(name, 0)
        bl_time = self._post_clean_time.get(name, 0)
        if baseline > 0 and now - bl_time <= 1200:
            if snap.ws <= baseline:return False, f"WS未填满({_mb(snap.ws)}/{_mb(baseline)})"
        # ── 失败冷却检查（仅 mark_failed 设置的）──
        cd = self.cooldown.get(name, 0)
        if now < cd: return False, f"失败冷却中({int(cd-now)}s)"

        # ── WS 回弹覆盖 ──
        ws_override = False
        bl = self._post_clean_ws.get(snap.name.lower(), 0)
        if bl > 0 and snap.ws >= bl * 2.0:
            ws_override = True
            theta = 1.0
        else:
            theta = self.learner.thompson_score(name, mem_pct=getattr(self, '_last_mem_pct', 50), is_fg=is_fg)

        # ── 系统目录进程: 需要高 θ 值 ──
        path = getattr(snap, "path", None)
        if path and self._is_system_path(path) and theta < 0.3:return False, "系统目录进程(概率不足)"

        # 策略投票: 综合 Kalman/记忆/因果/时机
        try:
            if hasattr(self, 'learner') and hasattr(self.learner, 'policy'):
                state = {"mem_pct": getattr(self, '_last_mem_pct', 50), "is_fg": getattr(snap, 'fg', False),
                         "mem_trend": getattr(self, '_mem_trend', 0.0)}
                if ws_override:
                    ok, reason = True, "WS回弹覆盖"
                elif not self._post_clean_ws:
                    ok, reason = True, "首轮(无基线)"
                else:
                    ok, reason, _scores = self.learner.policy.should_trim(name, snap.ws, state, self.learner)
                    snap._tree_scores = _scores  # 挂到快照上，供 _trim_process 评价
                if not ok:
                    return False, f"策略否决({reason})"
        except Exception as e:
            print(f"[MemWise] 策略投票异常: {e}", file=_ERR)
            return False, f"投票异常"
        return True, f"θ={theta:.2f}"

    def can_probe(self, snap):
        """是否可以对进程执行微型试探 — 按 WS 大小 + θ + 间隔"""
        name = snap.name.lower()
        if _is_system_core(name):return False
        # 游戏模式：不试探（流畅优先，只做确定性清理）
        if self.game_mode:
            return False
        # 用户黑名单：不参与试探性清理
        never = self.cfg.get("never", [])
        if name in never or snap.pid in never:
            return False
        # WS 门槛已移除
        # 前台进程不 probe，避免干扰
        if getattr(snap, "fg", False):return False
        # θ 过低且有足够样本时暂时跳过探测，但冷却后重新评估
        theta = self.learner.thompson_score(name, mem_pct=getattr(self, '_last_mem_pct', 50), is_fg=getattr(snap, "fg", False))
        profile = self.learner.get_profile(name)
        if profile and profile.total_samples >= 5 and theta < 0.2:
            # 低θ进程并非永久禁止：超过 10 分钟（600s）未被 probe 则重新给机会
            last = self._probe_last_time.get(name, 0)
            if last > 0 and time.time() - last < 600:return False
            # 冷却已过 → 允许重新 probe
        # 动态 probe 间隔：根据候选进程数自动调整
        # 策略加速：高分进程缩短探测间隔
        boost = 1.0
        if hasattr(self, 'learner') and hasattr(self.learner, 'policy'):
            state = {"mem_pct": getattr(self, '_last_mem_pct', 50), "mem_trend": getattr(self, '_mem_trend', 0.0),
                     "probe_last_time": self._probe_last_time}
            ok, _ = self.learner.policy.should_probe(name, snap.ws, state, self.learner)
            boost = 0.3 if ok else 1.0
        dynamic_interval = int(getattr(self, '_probe_dynamic_interval', 120) * boost)
        last = self._probe_last_time.get(name, 0)
        if last > 0 and time.time() - last < dynamic_interval:return False
        return True

    # ── 冷却管理 ──

    def mark_trimmed(self, name, freed=0, ws_before=0, pf_delta=0, ws_after=0):
        """记录 WS 基线 — 替代旧冷却。不设时间锁，下次 tick 靠数据判断是否值得再清。
        ws_after=0 时（进程已退出）不记录基线"""
        name = name.lower()
        now = time.time()
        # 清理后 WS 基线 + 时间戳
        if ws_after > 0:
            self._post_clean_ws[name] = ws_after
            self._post_clean_time[name] = now
        elif name in self._post_clean_ws:
            del self._post_clean_ws[name]
            self._post_clean_time.pop(name, None)
        # 超时计数衰减：成功清理 1 次，timeout_count -1
        p = self.learner.get_profile(name)
        if p and hasattr(p, 'timeout_count') and p.timeout_count > 0:
            p.timeout_count -= 1

    def mark_failed(self, name, fail_count=1):
        """失败冷却: 超时/失败次数越多，冷却越长（最多 4 倍）"""
        name = name.lower()
        efis = self.cfg.get("efis_params", {})
        cooloff_base = efis.get("cooloff_base", self._game_overrides["cooloff_base"] if self.game_mode else 300)
        cd = cooloff_base * min(4, fail_count)
        # 自适应冷却：回填快的进程缩短冷却，回填慢的保持或延长
        if hasattr(self.learner, 'get_profile'):
            p = self.learner.get_profile(name)
            if p and hasattr(p, 'refill_ewma') and p.refill_ewma > 50:
                ratio = min(5.0, p.refill_ewma / 100.0)
                cd = max(60, cd / ratio)
        self.cooldown[name] = time.time() + cd

    def mark_probed(self, name):
        """Probe 后记录时间戳（控制间隔）"""
        self._probe_last_time[name.lower()] = time.time()

    # ── PF 反馈 ──

    def record_pf_before(self, pid, pf):
        self.pf_before[pid] = (pf, time.time())

    def check_feedback(self, pid, pf_after, ws_before, ws_after, passes=2):
        """检查清理效果，返回 (ok, freed, pf_delta)"""
        entry = self.pf_before.pop(pid, None)
        if entry is None:
            return True, ws_before, 0
        pf_before, t_before = entry
        dt = max(1.0, time.time() - t_before)
        pf_delta = max(0, pf_after - pf_before)
        self.pf_delta_total = getattr(self, "pf_delta_total", 0) + pf_delta
        freed = max(0, ws_before - ws_after)
        # PF 成本：empty_ws 每轮 ~40 PF
        allowed_pf = max(120, int(50 * dt), int(freed / (1 << 20) * 10), passes * 40)
        ok = pf_delta <= allowed_pf
        return ok, freed, pf_delta

    def purge_expired(self):
        now = time.time()
        for k in list(self.cooldown.keys()):
            if self.cooldown[k] < now:
                del self.cooldown[k]
        # 清理过期 WS 基线（>1小时）
        for k in list(self._post_clean_time.keys()):
            if now - self._post_clean_time[k] > 3600:
                del self._post_clean_ws[k]
                del self._post_clean_time[k]
        # 清理过期 PF 缓存
        for k in list(self.pf_before.keys()):
            if now - self.pf_before[k][1] > 60:
                del self.pf_before[k]
        # 清理过期试探时间戳（>30分钟无活动的进程）
        for k in list(self._probe_last_time.keys()):
            if now - self._probe_last_time[k] > 1800:
                del self._probe_last_time[k]

    @staticmethod
    def _is_system_path(path):
        if not path:
            return False
        p = path.lower()
        return any(p.startswith(prefix) for prefix in SYSTEM_DIR_PREFIXES)




    def reset_pid(self):
        """重置 PID 控制器"""
        self.pid.reset()
