"""
PARES Judger — PID 压力控制器 + Thompson Sampling 联合判定
"""
import time
import os, sys, random
from .learner import _is_system_core
from . import winapi
from .stable import EXPLORE_RATE
from .i18n import tr

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

def _system_path_prefixes():
    """系统目录前缀（动态获取，非硬编码 C 盘——换机器/系统盘非 C 盘时依然有效）"""
    if _system_path_prefixes._cache is not None:
        return _system_path_prefixes._cache
    prefixes = set()
    root = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    prefixes.add(root.lower() + "\\")
    for k in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        v = os.environ.get(k)
        if v:
            prefixes.add(v.lower() + "\\")
    _system_path_prefixes._cache = tuple(sorted(prefixes))
    return _system_path_prefixes._cache

_system_path_prefixes._cache = None


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
        self._game_pid_set = set()  # 当前检测到的游戏进程 PID 集合（精确保护）
        # 游戏模式参数覆盖（游戏本体由 PID 精确保护，前台/冷却与常规一致避免误伤）
        self._game_overrides = {
            "min_ws": 524288,     # 0.5MB（正常 1MB）
        }
        efis_cfg = config.get("efis_params", {})
        self.pid = PidController(
            kp=efis_cfg.get("pid_kp", config.get("kp", DEFAULT_KP)),
            ki=config.get("ki", DEFAULT_KI),
            kd=efis_cfg.get("pid_kd", config.get("kd", DEFAULT_KD)),
            target=efis_cfg.get("target_usage", config.get("target_usage", TARGET_USAGE)),
        )
        self.aggressiveness = 0.0
        self._last_mem_pct = 50
        self.cooldown = {}
        self.pf_before = {}
        self._post_clean_ws = {}  # 进程清理后的 WS 基线
        self._post_clean_time = {}  # 基线设置时间戳（20分钟填满判定窗口 / 1小时过期清理）
        self._probe_last_time = {}
        # ── P0-C 连续低活动确认：{name: (连续低活动轮数, 时间戳)} ──
        self._low_activity = {}
        # ── P1-E IO 活跃判定缓存：{pid: (累计IO字节, 时间戳)}（按需采样差分速率）──
        self._io_cache = {}
        # ── 手动优化标志（cleaner 每轮同步）：手动时跳过自动化保守门（前台冷却/连续确认/锚点抑制），
        #    保留实时安全门（CPU/IO 活跃——正在干活的程序手动也不清）──
        self._manual_mode = False
        # ── 锚点抑制计数（EFIS 自平衡诊断用：每轮被"稳态抑制"拦截的次数——
        #    抑制多但内存仍高 → EFIS 自动收紧抑制余量，保证压缩能力兜底）──
        self.suppress_cnt = 0
        # ── 清理模式严格度（cleaner 每轮同步）：模式决定"时间等待类"守卫的严格度——
        #    normal 标准 / deep 减半 / full 跳过（极限=不等、立即清）；
        #    "效率类"守卫（锚点/回弹）模式无关——极限≠白忙 ──
        self._mode_guard = "normal"

    # ── PID ──

    def _agg_label(self, v):
        if v <= 0.01: return tr("极低")
        if v < 0.40: return tr("低")
        if v < 0.60: return tr("中")
        return tr("高")

    def _mem_label(self, pct):
        if pct < 30: return tr("充裕")
        if pct < 60: return tr("正常")
        if pct < 80: return tr("偏高")
        return tr("极高")

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
        fg_gate = 0.35  # 前台非游戏程序保持保护（游戏全屏时前台即游戏，已被 PID 保护）
        min_ws_gate = self._game_overrides["min_ws"] if self.game_mode else (1 << 20)
        
        if is_fg:
            if self.aggressiveness < fg_gate:
                return False, "前台窗口"

        if snap.ws < min_ws_gate:
            return False, "工作集太小"

        # ── 前台/窗口冷却（P0-A + A 方案）：刚切走的进程不碰——有可见窗口 10 分钟
        #    （有窗口=用户可能随时切回），无窗口 5 分钟；deep 减半、full 跳过（极限=不等）；
        #    手动跳过（用户主动清理目标）；高压覆盖极端释放 ──
        now = time.time()
        _guard = getattr(self, "_mode_guard", "normal")
        if not is_fg and not self._manual_mode and self.aggressiveness < 0.8 and _guard != "full":
            p_fg = self.learner.get_profile(name)
            if p_fg and p_fg.last_foreground_at:
                _win = getattr(snap, 'has_visible', False)
                _cd = (600 if _win else 300)
                if _guard == "deep":
                    _cd //= 2
                if now - p_fg.last_foreground_at < _cd:
                    return False, "刚切走"

        # ── CPU 活跃门（P0-C）：正在干活的进程不清（单轮实时信号；手动同样生效——安全维度；
        #    full 模式放宽到 12%——极限释放允许更高活跃度的进程，MuseRAM Ultimate 同口径）──
        _cpu_gate = 12.0 if _guard == "full" else 8.0
        if (getattr(snap, "cpu", 0.0) or 0.0) >= _cpu_gate:
            return False, "CPU活跃"

        # ── IO 活跃门（P1-E）：IO 密集（下载/播放/写盘）进程不清（按需采样差分；手动同样生效）──
        if self._io_active(snap.pid):
            return False, "IO活跃"

        # ── 连续低活动确认（P0-C）：2 轮可靠低活动才可清（按 PID 键——同名多实例互不干扰；
        #    防瞬时脉冲误判；手动/高压跳过；full 模式跳过——极限=立即清）──
        if _guard != "full" and not self._manual_mode and self.aggressiveness < 0.8:
            _la = self._low_activity.get(snap.pid)
            if _la is None or _la[0] < 2:
                return False, "活动确认中"

        # ── WS 基线检查（替代旧冷却：判断是否已重新填满，不是干等时间）──
        # 判定窗口按回填速率动态化：慢回填拉长重评间隔（避免低效重复清），快回填保持灵敏；
        # 默认 1200s，范围 [120, 3600]；ws 已超基线时直接放行（不受窗口影响）
        baseline = self._post_clean_ws.get(name, 0)
        bl_time = self._post_clean_time.get(name, 0)
        if baseline > 0:
            window = 1200
            p_win = self.learner.get_profile(name)
            if p_win and p_win.refill_ewma > 0:
                remain = max(0, baseline - snap.ws)
                if remain > 0:
                    est = int(remain / p_win.refill_ewma * 3)  # 预计回填时间 ×3 裕量
                    window = max(120, min(3600, est))
                else:
                    window = 120
            if now - bl_time <= window:
                if snap.ws <= baseline:return False, f"WS未填满({_mb(snap.ws)}/{_mb(baseline)})"
        # ── 稳态锚点抑制（P1-D）：低于应用自然稳态+余量 → 清了也白清。
        #    手动/高压跳过；探索机制（EXPLORE_RATE 概率放行）保持 Thompson 学习闭环验证锚点──
        if not self._manual_mode and self.aggressiveness < 0.8:
            path_a = getattr(snap, "path", None)
            if path_a and self.learner.stable_anchors.should_suppress(
                    path_a, snap.ws, self.cfg.get("efis_params", {}).get("anchor_margin", 0.15)):
                if random.random() >= EXPLORE_RATE:
                    self.suppress_cnt += 1
                    return False, "稳态抑制"
        # ── 回弹自动后退（B 方案）：清后回填率高的组件进入后退期（不重复白清）；
        #    手动/高压跳过；EWMA 回落自动解除；探索放行（5%）保持数据流——
        #    防后退死锁：进程行为变化后探测清理产生新回弹数据，EWMA 快速回落解除 ──
        if not self._manual_mode and self.aggressiveness < 0.8:
            path_b = getattr(snap, "path", None)
            if path_b and self.learner.rebound.in_backoff(path_b, now):
                if random.random() >= EXPLORE_RATE:
                    return False, "回弹后退"
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

        # ── 模式价值底线（MuseRAM MinIdleScore 同构，独立于投票的干净梯度）：
        #    deep 0.12 / full 0.06 / normal 无——极限模式也保留极低价值底线，
        #    防完全无价值进程（θ≈0）白付 PF。ws_override 时 theta=1.0 不触发 ✅ ──
        _theta_floor = {"deep": 0.12, "full": 0.06}.get(_guard, 0.0)
        if _theta_floor and theta < _theta_floor:
            return False, "价值不足"

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
        cooloff_base = efis.get("cooloff_base", 300)
        cd = cooloff_base * min(4, fail_count)
        # 自适应冷却：快速回填（>256KB/s）的进程缩短冷却，普通回填保持基准
        if hasattr(self.learner, 'get_profile'):
            p = self.learner.get_profile(name)
            if p and hasattr(p, 'refill_ewma') and p.refill_ewma > (256 << 10):
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
        # 清理过期低活动计数（>30分钟未更新）
        for k in list(self._low_activity.keys()):
            if now - self._low_activity[k][1] > 1800:
                del self._low_activity[k]
        # 清理过期 IO 缓存（>60s 未采样）
        for k in list(self._io_cache.keys()):
            if now - self._io_cache[k][1] > 60:
                del self._io_cache[k]
        # 锚点过期（7 天无更新）
        try:
            self.learner.stable_anchors.purge_expired(now)
        except Exception:
            pass
        # 回弹观察过期 + 后退期到期清理（字典保留键值，到期由 in_backoff 判定）
        try:
            self.learner.rebound.purge_expired(now)
        except Exception:
            pass

    # ── P0-C 连续低活动确认 / P1-E IO 活跃 / P1-D 锚点喂样 ──

    def update_activity(self, snaps):
        """每轮更新连续低活动计数（按 PID 键——同名多实例进程互不干扰）：
        CPU<8% 连续 2 轮才可清（活跃即清零重来）。
        进程身份校验：创建时间变化（进程重启）→ 计数清零重新确认（防新实例继承旧计数）。
        同时每轮重置锚点抑制计数（GUI/CLI 口径统一；EFIS 周期末读最近一轮计数）"""
        self.suppress_cnt = 0
        now = time.time()
        for s in snaps:
            cpu = getattr(s, "cpu", 0.0) or 0.0
            create = getattr(s, "create", None)
            prev = self._low_activity.get(s.pid)
            if prev is not None and len(prev) >= 3 and prev[2] != create:
                prev = None  # 进程重启：旧计数作废，重新确认
            if cpu < 8.0:
                self._low_activity[s.pid] = (prev[0] + 1 if prev else 1, now, create)
            else:
                self._low_activity.pop(s.pid, None)

    def _io_active(self, pid):
        """IO 活跃判定（按需采样：读一次累计计数与缓存差分速率；首轮无基线不拦截）。
        实时安全门：与 CPU 活跃门一致，高压同样尊重——活跃进程清理无效且加剧卡顿"""
        io = winapi.get_process_io_counters(pid)
        if io is None:
            return False
        now = time.time()
        prev = self._io_cache.get(pid)
        self._io_cache[pid] = (io, now)
        if prev is None:
            return False
        dt = now - prev[1]
        if dt <= 0.1 or io < prev[0]:
            return False
        return (io - prev[0]) / dt > (4 << 20)

    def update_anchors(self, snaps, now=None):
        """喂锚点自然 WS 样本：排除清理后回填期（120s——回填不是自然稳态，防锚点被压低）；
        顺带驱动回弹观察（B 方案：比对快照 WS 结算回填率）"""
        now = now or time.time()
        exclude = {n for n, t in self._post_clean_time.items() if now - t < 120}
        self.learner.stable_anchors.feed(snaps, now, exclude)
        self.learner.rebound.observe(snaps, now)

    @staticmethod
    def _is_system_path(path):
        if not path:
            return False
        p = path.lower()
        return any(p.startswith(prefix) for prefix in _system_path_prefixes())




    def reset_pid(self):
        """重置 PID 控制器"""
        self.pid.reset()
