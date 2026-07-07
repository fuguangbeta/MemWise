"""
PARES Judger — PID 压力控制器 + Thompson Sampling 联合判定
"""
import time
from .learner import SYSTEM_CORE

def _mb(b):
    return b / (1 << 20)

# PID 默认参数
DEFAULT_KP = 1.0    # 比例系数 — 响应当前压力 (更积极)
DEFAULT_KI = 0.10   # 积分系数 — 消除稳态误差
DEFAULT_KD = 0.15   # 微分系数 — 抑制震荡 (快速升压时提前响应)
TARGET_USAGE = 45.0  # 目标内存使用率 (%) — 更低 → 更早开始清理
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
        """根据当前内存使用率计算 aggressiveness ∈ [0,1]"""
        now = time.time()
        dt = max(0.5, min(10.0, now - self._last_time))
        error = current_usage - self.target

        # P
        p_term = self.kp * error

        # I (带抗饱和)
        self._integral += error * dt
        self._integral = max(-self._windup_limit, min(self._windup_limit, self._integral))
        i_term = self.ki * self._integral

        # D
        d_term = self.kd * (error - self._prev_error) / dt if dt > 0 else 0.0

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
        self.pid = PidController(
            kp=config.get("kp", DEFAULT_KP),
            ki=config.get("ki", DEFAULT_KI),
            kd=config.get("kd", DEFAULT_KD),
            target=config.get("target_usage", TARGET_USAGE),
        )
        self.aggressiveness = 0.0
        self._prev_agg = 0.0
        self._last_mem_pct = 50
        self.cooldown = {}
        self._info_msgs = []
        self.pf_before = {}
        self._post_clean_ws = {}  # 进程清理后的 WS 基线
        self._post_clean_time = {}  # 基线设置时间戳（30分钟过期）
        self._probe_last_time = {}  # 进程上次 probe 时间（150s 间隔）

    # ── PID ──

    def _agg_label(self, v):
        if v <= 0.01: return "极低"
        if v <= 0.30: return "低"
        if v <= 0.60: return "中"
        return "高"

    def _mem_label(self, pct):
        if pct < 40: return "充足"
        if pct < 60: return "正常"
        if pct < 80: return "偏高"
        return "紧张"

    def update_pressure(self, mem_usage_pct):
        """根据内存压力更新 PID，返回当前 aggressiveness"""
        self.aggressiveness = self.pid.update(mem_usage_pct)
        if abs(self.aggressiveness - self._prev_agg) > 0.25:
            self._info_msgs.append(f"📈 内存{mem_usage_pct:.0f}%({self._mem_label(mem_usage_pct)}) 清理强度:{self._agg_label(self._prev_agg)}→{self._agg_label(self.aggressiveness)}")
        self._prev_agg = self.aggressiveness
        return self.aggressiveness

    # ── 决策 ──

    def can_trim(self, snap):
        """联合决策: PID × Thompson × 安全规则 (游戏模式下阈值更激进)"""
        name = snap.name.lower()

        # 安全规则 (不变)
        if name in SYSTEM_CORE:
            return False, "系统核心进程"

        never = self.cfg.get("never", [])
        if name in never or snap.pid in never:
            return False, "用户黑名单"

        is_fg = getattr(snap, "fg", False)

        # ── 游戏模式激进阈值 ──
        efis = self.cfg.get("efis_params", {})
        e_theta = efis.get("theta_gate", 0.18)
        e_cpu = efis.get("cpu_gate", 1.0)
        if self.game_mode and not is_fg:
            cpu_threshold = max(e_cpu, 2.0)
            joint_threshold = min(e_theta, 0.15)
            agg_threshold_fg = 0.8
        else:
            cpu_threshold = e_cpu
            joint_threshold = e_theta
            agg_threshold_fg = 0.6

        # foreground → 仅在高压时清理
        if is_fg:
            if self.aggressiveness < agg_threshold_fg:
                return False, "前台窗口"

        if snap.ws < 5 << 20:  # 5MB 以下不碰
            return False, "工作集太小"

        # ── WS 基线检查（替代旧冷却：判断是否已重新填满，不是干等时间）──
        now = time.time()
        baseline = self._post_clean_ws.get(name, 0)
        bl_time = self._post_clean_time.get(name, 0)
        if baseline > 0:
            # 基线超过30分钟 → 过期，允许重新清理
            if now - bl_time > 1800:
                pass
            else:
                # 动态阈值：小进程需更多相对增长，大进程少一些
                e_b_mul = efis.get("ws_baseline_mul", 1.20)
                if baseline < 200 << 20:
                    threshold = 1.3 * e_b_mul / 1.20
                elif baseline < 500 << 20:
                    threshold = 1.2 * e_b_mul / 1.20
                else:
                    threshold = 1.15 * e_b_mul / 1.20
                min_delta = 2 << 20  # 至少2MB
                if snap.ws < baseline * threshold or snap.ws - baseline < min_delta:
                    return False, f"WS未填满({_mb(snap.ws)}/{_mb(baseline * threshold)})"
        # ── 失败冷却检查（仅 mark_failed 设置的）──
        cd = self.cooldown.get(name, 0)
        if now < cd:
            return False, f"失败冷却中({int(cd-now)}s)"

        # ── WS 回弹覆盖 ──
        ws_override = False
        bl = self._post_clean_ws.get(snap.name.lower(), 0)
        if bl > 0 and snap.ws >= bl * 2.0:
            ws_override = True
            theta = 1.0
        else:
            theta = self.learner.thompson_score(name)
            if theta < joint_threshold:
                return False, f"θ不足({theta:.2f})"

        # ── 泄漏检测: 泄漏进程跳过冷却，高频尝试 ──
        if self.learner.is_leak_suspect(name):
            pass  # 泄漏进程不冷却

        # ── 系统目录进程: 需要高 θ 值 ──
        path = getattr(snap, "path", None)
        if path and self._is_system_path(path) and theta < 0.6:
            return False, "系统目录进程(概率不足)"

        # 策略投票: 综合 Kalman/记忆/因果/时机
        try:
            if hasattr(self, 'learner') and hasattr(self.learner, 'policy'):
                state = {"mem_pct": getattr(self, '_last_mem_pct', 50)}
                if ws_override:
                    ok, reason = True, "WS回弹覆盖"
                elif not self._post_clean_ws:
                    ok, reason = True, "首轮(无基线)"
                else:
                    ok, reason = self.learner.policy.should_trim(name, snap.ws, state, self.learner)
                if not ok:
                    return False, f"策略否决({reason})"
        except Exception as e:
            import sys; print(f"[MemWise] 策略投票异常: {e}", file=sys.stderr)
            return False, f"投票异常"
        return True, f"θ={theta:.2f}"

    def can_probe(self, snap):
        """是否可以对进程执行微型试探 — 按 WS 大小 + θ + 间隔"""
        name = snap.name.lower()
        if name in SYSTEM_CORE:
            return False
        # WS 门槛已移除
        # 前台进程不 probe，避免干扰
        if getattr(snap, "fg", False):
            return False
        # θ 过低且有足够样本时暂时跳过探测，但冷却后重新评估
        theta = self.learner.thompson_score(name)
        profile = self.learner.get_profile(name)
        if profile and profile.total_samples >= 5 and theta < 0.2:
            # 低θ进程并非永久禁止：超过 30 分钟未被 probe 则重新给机会
            last = self._probe_last_time.get(name, 0)
            if last > 0 and time.time() - last < 600:  # 10分钟冷却
                return False
            # 冷却已过 → 允许重新 probe
        # 动态 probe 间隔：根据候选进程数自动调整
        # 候选多 => 间隔短（快速覆盖），候选少 => 间隔长（稳中求进）
        dynamic_interval = getattr(self, '_probe_dynamic_interval', 120)
        last = self._probe_last_time.get(name, 0)
        if last > 0 and time.time() - last < dynamic_interval:
            return False
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

    def mark_failed(self, name, fail_count=1):
        """失败冷却: 失败次数越多，冷却越长"""
        name = name.lower()
        efis = self.cfg.get("efis_params", {})
        cooloff_base = efis.get("cooloff_base", 3600)
        cd = cooloff_base * min(8, fail_count)  # max 8h
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
        freed = max(0, ws_before - ws_after)
        # PF 成本：empty_ws 每轮 ~40 PF
        allowed_pf = max(50, int(50 * dt), freed // (1 << 20) * 10, passes * 40)
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

    @staticmethod
    def _is_system_path(path):
        if not path:
            return False
        p = path.lower()
        return any(p.startswith(prefix) for prefix in SYSTEM_DIR_PREFIXES)


    def reset_pid(self):
        """重置 PID 控制器"""
        self.pid.reset()
