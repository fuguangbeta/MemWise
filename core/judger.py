"""
PARES Judger — PID 压力控制器 + Thompson Sampling 联合判定
"""
import time
from .learner import SYSTEM_CORE

def _mb(b):
    return b / (1 << 20)

# PID 默认参数
DEFAULT_KP = 0.8    # 比例系数 — 响应当前压力 (更积极)
DEFAULT_KI = 0.10   # 积分系数 — 消除稳态误差
DEFAULT_KD = 0.15   # 微分系数 — 抑制震荡 (快速升压时提前响应)
TARGET_USAGE = 55.0  # 目标内存使用率 (%) — 更低 → 更早开始清理
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
        self.cooldown = {}
        self.pf_before = {}
        self._post_clean_ws = {}  # 进程清理后的 WS 基线
        self._post_clean_time = {}  # 基线设置时间戳（30分钟过期）
        self._probe_last_time = {}  # 进程上次 probe 时间（150s 间隔）

    # ── PID ──

    def update_pressure(self, mem_usage_pct):
        """根据内存压力更新 PID，返回当前 aggressiveness"""
        self.aggressiveness = self.pid.update(mem_usage_pct)
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
        if self.game_mode and not is_fg:
            # 非前台进程：CPU 阈值放宽、概率门槛降低
            cpu_threshold = 2.0
            joint_threshold = 0.15
            agg_threshold_fg = 0.8  # 前台保护收紧（游戏在前台更不易被清）
        else:
            cpu_threshold = 1.0
            joint_threshold = 0.25
            agg_threshold_fg = 0.6

        # foreground → 仅在高压时清理
        if is_fg:
            if self.aggressiveness < agg_threshold_fg:
                return False, "前台窗口"

        if snap.cpu >= cpu_threshold and self.aggressiveness < 0.8:
            return False, f"CPU活跃({snap.cpu:.1f}%)"

        if snap.ws < 10 << 20:  # 10MB 以下不碰
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
                if baseline < 200 << 20:
                    threshold = 1.3
                elif baseline < 500 << 20:
                    threshold = 1.2
                else:
                    threshold = 1.15
                min_delta = 20 << 20  # 至少20MB
                if snap.ws < baseline * threshold or snap.ws - baseline < min_delta:
                    return False, f"WS未填满({_mb(snap.ws)}/{_mb(baseline * threshold)})"
        # ── 失败冷却检查（仅 mark_failed 设置的）──
        cd = self.cooldown.get(name, 0)
        if now < cd:
            return False, f"失败冷却中({int(cd-now)}s)"

        # ── Thompson Sampling ──
        theta = self.learner.thompson_score(name)
        # 由 mode 和学习系统决定是否清理，不由当前内存压力二次削减
        if theta < joint_threshold:
            return False, f"θ不足({theta:.2f})"

        # ── 泄漏检测: 泄漏进程跳过冷却，高频尝试 ──
        if self.learner.is_leak_suspect(name):
            pass  # 泄漏进程不冷却

        # ── 系统目录进程: 需要高 θ 值 ──
        path = getattr(snap, "path", None)
        if path and self._is_system_path(path) and theta < 0.6:
            return False, "系统目录进程(概率不足)"

        return True, f"θ={theta:.2f}"

    def can_probe(self, snap):
        """是否可以对进程执行微型试探 — 按 WS 大小 + θ + 间隔"""
        name = snap.name.lower()
        if name in SYSTEM_CORE:
            return False
        if snap.ws < 50 << 20:  # 50MB 以下不 probe
            return False
        # 前台进程不 probe，避免干扰
        if getattr(snap, "fg", False):
            return False
        # θ 过低且有足够样本时跳过探测
        theta = self.learner.thompson_score(name)
        profile = self.learner.get_profile(name)
        if profile and profile.total_samples >= 5 and theta < 0.2:
            return False
        # 每个进程最多每 150s probe 一次
        last = self._probe_last_time.get(name, 0)
        if time.time() - last < 150:
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
        cd = 3600 * min(8, fail_count)  # max 8h
        self.cooldown[name] = time.time() + cd

    def mark_probed(self, name):
        """Probe 后记录时间戳（控制间隔）"""
        self._probe_last_time[name.lower()] = time.time()

    # ── PF 反馈 ──

    def record_pf_before(self, pid, pf):
        self.pf_before[pid] = (pf, time.time())

    def check_feedback(self, pid, pf_after, ws_before, ws_after):
        """检查清理效果，返回 (ok, freed, pf_delta)"""
        entry = self.pf_before.pop(pid, None)
        if entry is None:
            return True, ws_before, 0  # 没有基线，默认 ok
        pf_before, t_before = entry
        dt = max(1.0, time.time() - t_before)
        pf_delta = max(0, pf_after - pf_before)
        freed = max(0, ws_before - ws_after)
        # 如果 freed 够大，允许一定 PF 增加
        allowed_pf = max(50, int(50 * dt), freed // (1 << 20) * 10)
        ok = pf_delta < allowed_pf
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
