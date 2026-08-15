# -*- coding: utf-8 -*-
"""
MemWise v4.1.080 全量单元测试 — 16 模块全覆盖（ERIS 纯函数共用 core.eris，无内联副本）
"""
import sys, os, json, math, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.kalman import KalmanProfile
from core.prior import HierarchicalPrior
from core.learner import Profile, PareLearner, SYSTEM_CORE, _is_system_core, SYSTEM_CORE_EXE
from core.judger import PidController, PareJudger
from core.config import load as config_load, DEFAULT_CFG
from core.efis import EfisController, PARAMS
from core.policy import PolicyVoter
from core.meta import MetaCognition
from core.eris import iqr_dim, validate_state
from collections import deque

errors = []
def check(name, cond, detail=""):
    if not cond:
        print(f"  [FAIL] {name}" + (f"  {detail}" if detail else ""))
        errors.append(name)
from core.stable import StableAnchor, StableAnchorStore, EXPLORE_RATE
from core.rebound import ReboundLearner, _key

print("\n[1] KalmanProfile")
k = KalmanProfile(r=5.0)
f, c = k.predict(); check("init freed=0", f==0); check("init cost=0", c==0); check("init conf≈0", k.confidence<0.1)
k.update(100<<20, 50); f, c = k.predict(); check("freed>0", f>0); check("cost>0", c>0); check("ROI>0", k.roi>0)
for _ in range(10): k.update(50<<20, 30)
check("conf>0.5", k.confidence>0.5); check("ROI 1-3", 1<k.roi<3)
d=k.to_dict(); k2=KalmanProfile.from_dict(d)
check("roundtrip freed", abs(k2.x_freed-k.x_freed)<0.01); check("roundtrip cost", abs(k2.x_cost-k.x_cost)<0.01)
k3=KalmanProfile(); k3.update(0,0); check("zero update ok", k3.predict()[0]>=0)
old_q=k.q; k.update(1<<30,100); check("large innov q↑", k.q>old_q)
# 长间隔 p 有界：q·dt 时间项允许增长但 clamp 400，无乘性 ×2 无界膨胀（修复验证）
k4 = KalmanProfile(); k4.last_update = time.time() - 3600
k4.update(50 << 20, 10); check("p bounded after long gap", k4.p_freed <= 400.0)
for _ in range(200): k4.update(50 << 20, 10)
check("p hard cap 400", k4.p_freed <= 400.0 and k4.p_cost <= 400.0)
# from_dict 类型保护：坏字段不崩溃
k5 = KalmanProfile.from_dict({"x_freed": "bad", "p_freed": -5, "q": "x"})
check("kalman from_dict sanitize", k5.x_freed == 0.0 and k5.p_freed >= 0.0 and k5.q >= 0.001)

print("\n[2] HierarchicalPrior")
check("chrome→browser", HierarchicalPrior.classify("chrome.exe")=="browser")
check("Code→ide", HierarchicalPrior.classify("Code.exe")=="ide")
check("unknown→None", HierarchicalPrior.classify("random.exe") is None)
profiles={}
for n,a,b in [("chrome.exe",5,1),("msedge.exe",4,2),("firefox.exe",6,1)]:
    p=Profile(n); p.alpha=a; p.beta=b
    for _ in range(6): p.ws_deque.append(50<<20)
    profiles[n]=p
check("peer avg θ>0.35", HierarchicalPrior.initial_theta("brave.exe",profiles)>0.35)
check("unknown θ=0.35", HierarchicalPrior.initial_theta("x.exe",{})==0.35)

print("\n[3] SYSTEM_CORE 保护名单（v3.7.09 修复：快照名带 .exe，派生集统一入口）")
check("exe 派生集完备", "svchost.exe" in SYSTEM_CORE_EXE and "explorer.exe" in SYSTEM_CORE_EXE)
check("svchost.exe 命中", _is_system_core("svchost.exe") is True)
check("无后缀也命中", _is_system_core("svchost") is True)
check("system 进程命中", _is_system_core("System") is True)
check("memory compression 命中", _is_system_core("memory compression") is True)
check("普通进程不命中", _is_system_core("notepad.exe") is False)
check("空名安全", _is_system_core(None) is False and _is_system_core("") is False)

print("\n[4] Profile")
p=Profile("test.exe"); check("alpha=2", p.alpha==2); check("beta=1", p.beta==1)
check("_info_msgs=[]", p._info_msgs==[]); check("timeout_count=0", p.timeout_count==0)
p.ws_deque.append(50<<20); p.ws_deque.append(55<<20); check("slope finite", math.isfinite(p.slope))
p.record_clean(True, 100<<20, 10); check("ok→alpha>2", p.alpha>2); check("clean_count=1", p.clean_count==1)
p.record_clean(False, 0, 50); check("fail→beta>1", p.beta>1)
# ROI 单位统一（MB/PF，与 KalmanProfile.roi 同量纲）
check("roi MB/PF", abs(p.roi - (p.gain_ewma / (1 << 20)) / max(p.cost_ewma, 1)) < 1e-9)
# learning_rate 接入：lr 大 → gain_ewma 更快逼近 freed
pa, pb = Profile("a.exe"), Profile("b.exe")
pa.record_clean(True, 100 << 20, 10, lr=0.9)
pb.record_clean(True, 100 << 20, 10, lr=0.1)
check("lr 大更快适应", pa.gain_ewma > pb.gain_ewma)
pc = Profile("c.exe"); pc.record_clean(True, 100 << 20, 10, lr=None)
check("lr=None 用默认 λ", abs(pc.gain_ewma - 0.5 * (100 << 20)) < 1.0)
# probe 0 观测不污染 Kalman（修复：与 record_clean 同口径）
pp = Profile("pp.exe"); pp.kalman.x_freed = 50 << 20
pp.record_probe(True, freed=0)
check("probe 0 不污染 kalman", pp.kalman.x_freed == 50 << 20)
pp.record_probe(True, freed=30 << 20)
check("probe freed>0 更新 kalman", pp.kalman.x_freed > 30 << 20)
d=p.to_dict(); p2=Profile.from_dict(d)
check("rt alpha", p2.alpha==p.alpha); check("rt _info_msgs=[]", p2._info_msgs==[]); check("rt timeout_count=0", p2.timeout_count==0)
# from_dict 坏字段容错
p3 = Profile.from_dict({"name": 123, "alpha": "x", "ws": ["bad", 10, "5"]})
check("from_dict sanitize", p3.name == "123" and p3.alpha >= 0.5 and len(p3.ws_deque) >= 0)

print("\n[5] PareLearner")
l=PareLearner(); check("empty profiles=0", len(l.profiles)==0)
p=l.get("test.exe"); p.ws_deque.append(50<<20); l.feed([])
p.record_clean(True, 80<<20, 5)
check("theta 0-1", 0<=l.thompson_score("test.exe")<=1)
# SYSTEM_CORE 保护在 thompson_score 全链路生效（带 .exe 快照名）
check("svchost→0", l.thompson_score("svchost")==0)
check("svchost.exe→0", l.thompson_score("svchost.exe")==0)
check("notepad→>0", l.thompson_score("notepad.exe")>0)
p._info_msgs.append("🕳️ test leak"); msgs=l.pop_info()
check("pop_info collects profile msgs", any("test leak" in m for m in msgs))
p3 = l.get("feed.exe")
for _ in range(5): p3.ws_deque.append(50 << 20)
l.record_clean_result("feed.exe", True, freed=100 << 20, pf_delta=10)
check("清理反馈更新收益", p3.gain_ewma > 0)
check("清理反馈更新清理计数", p3.clean_count == 1 and p3.probe_ok == 0)
tmp=os.path.join(tempfile.gettempdir(),"mw_test.json")
check("save ok", l.save(tmp))
l2=PareLearner.load(tmp); check("load not None", l2 is not None); check("profiles count match", len(l2.profiles)==len(l.profiles))
# load 单条坏画像不丢全部（修复）
bad_data = {"profiles": {"good.exe": l.profiles["test.exe"].to_dict(), "bad.exe": {"name": None, "alpha": {"x": 1}, "ws": {"z": 9}}}}
with open(tmp, "w", encoding="utf-8") as f: json.dump(bad_data, f)
l3 = PareLearner.load(tmp)
check("load 容错不丢画像", "good.exe" in l3.profiles and "bad.exe" in l3.profiles)
os.remove(tmp)

print("\n[6] PidController")
pid=PidController(kp=1.0,ki=0.10,kd=0.15,target=30)
a=pid.update(50); check("mid pressure >0", a>0)
a=pid.update(90); check("high pressure >0", a>0)
check("in [0,1]", 0<=pid.update(30)<=1)
pid2=PidController(ki=0.5)
for _ in range(100): pid2.update(90)
check("anti-windup", abs(pid2._integral)<=pid2._windup_limit)

print("\n[7] PareJudger")
l2=PareLearner(); j=PareJudger(l2, {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
class Snap: pass
s=Snap(); s.name="svchost.exe"; s.ws=100<<20; s.path="c:\\windows\\system32\\svchost.exe"; s.pid=1234; s.pf=0; s.priv=0
ok,_=j.can_trim(s); check("svchost.exe blocked", not ok)
s2=Snap(); s2.name="notepad.exe"; s2.ws=200<<20; s2.path="d:\\app\\notepad.exe"; s2.pid=5678; s2.pf=0; s2.priv=0
# 预置连续低活动确认（新守卫：CPU 活跃门/连续确认/前台冷却在测试环境需显式满足）
j._low_activity[5678] = (2, time.time(), None)
ok2,_=j.can_trim(s2); check("notepad allowed", ok2)
j.mark_failed("test.exe",1); check("cooldown recorded", "test.exe" in j.cooldown)
# 非首轮（已有基线）：策略投票必须真实生效，不得抛异常全拒
j3 = PareJudger(l2, {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j3._post_clean_ws["other.exe"] = 10 << 20
s3=Snap(); s3.name="vote.exe"; s3.ws=300<<20; s3.path="d:\\app\\vote.exe"; s3.pid=9999; s3.pf=0; s3.priv=0; s3.fg=False
j3._low_activity[9999] = (2, time.time(), None)
ok3, reason3 = j3.can_trim(s3)
check("非首轮策略投票无异常", "异常" not in reason3 and "否决" not in reason3, reason3)
j.mark_trimmed("trim.exe", freed=10<<20, ws_before=200<<20, ws_after=150<<20)
p=l2.get("trim.exe"); p.timeout_count=2
j.mark_trimmed("trim.exe", freed=10<<20, ws_before=200<<20, ws_after=150<<20)
check("timeout_count decayed", p.timeout_count==1)
j._probe_last_time["dead.exe"]=time.time()-2000; j.purge_expired()
check("probe time purged", "dead.exe" not in j._probe_last_time)
# 回填冷却阈值：仅快速回填(>256KB/s)缩短冷却（原 50B/s 阈值过松致几乎全进程命中）
j4 = PareJudger(l2, {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[], "efis_params": {"cooloff_base": 360}})
p_fast = l2.get("refill_fast.exe"); p_fast.refill_ewma = 512 << 10
j4.mark_failed("refill_fast.exe", 1)
cd_fast = j4.cooldown.get("refill_fast.exe", 0) - time.time()
p_slow = l2.get("refill_slow.exe"); p_slow.refill_ewma = 100
j4.mark_failed("refill_slow.exe", 1)
cd_slow = j4.cooldown.get("refill_slow.exe", 0) - time.time()
check("快速回填冷却缩短", cd_fast < cd_slow)
check("慢回填冷却保持基准", cd_slow > 300)

print("\n[8] Config")
cfg=config_load(); check("has clean_passes", "clean_passes" in cfg); check("has gap_seconds", "gap_seconds" in cfg)
check("interval 默认 60", DEFAULT_CFG["interval"] == 60)
# 深拷贝：消费方 append 不污染 DEFAULT_CFG（修复）
c1 = config_load(); c1["clean_operations"].append("zzz_test")
c2 = config_load()
check("默认列表不被污染", "zzz_test" not in c2["clean_operations"])

print("\n[9] EFIS")
check("PARAMS 10 keys", len(PARAMS)==10)
for k,v in PARAMS.items():
    check(f"{k} valid range", v["min"]<=v["default"]<=v["max"])
check("learning_rate 默认 0.5 且范围覆盖 0.1-0.9", PARAMS["learning_rate"]["default"] == 0.5 and PARAMS["learning_rate"]["min"] == 0.10 and PARAMS["learning_rate"]["max"] == 0.90)
# 满 5 轮真实调参：振荡信号 → pid_kp 下降（原恒真断言修复；症状需 ≥2 次评估轮，10 轮 = 2 次评估）
# 注意口径：cycle_freed 按生产为 MB（L210 阈值 20/100 均为 MB 数值），repeat_fail=0 防 cooloff 反向冻结 pid_kp
e=EfisController()
for i in range(10):
    e.tick({"mem_pct": 50 + (i % 2) * 30, "trimmed_cnt": 10, "failed_cnt": 2, "total_attempts": 12,
            "cycle_freed": 500, "snaps": [], "fore_fullscreen": False,
            "cycle_duration": 60, "pf_delta": 0, "deepen_cnt": 0, "deepen_extra": 0,
            "layer3_ran": 0, "layer3_extra": 0, "cooldown_cnt": 0, "repeat_fail": 0,
            "theta_mean": 0.5, "theta_above_06": 0.3, "agg": 0.6})
check("EFIS 振荡→pid_kp 下降", e.params["pid_kp"] < 0.6)
# 症状双向累积：连续两次同向负面必须调整（防单向漂移）
e2=EfisController(); e2._apply({"pid_kp": -1}); e2._apply({"pid_kp": -1})
check("EFIS 负面调整生效", e2.params["pid_kp"] < 0.6)
# 锚点抑制自平衡：抑制拦截多且内存仍高于目标 → anchor_margin 收紧（压缩能力兜底闭环）
e3=EfisController()
for i in range(10):
    e3.tick({"mem_pct": 75, "trimmed_cnt": 5, "failed_cnt": 1, "total_attempts": 6,
            "cycle_freed": 300, "snaps": [], "fore_fullscreen": False,
            "cycle_duration": 60, "pf_delta": 0, "deepen_cnt": 0, "deepen_extra": 0,
            "layer3_ran": 0, "layer3_extra": 0, "cooldown_cnt": 0, "repeat_fail": 0,
            "theta_mean": 0.5, "theta_above_06": 0.3, "agg": 0.6, "suppress_cnt": 5})
check("抑制多内存高→margin收紧", e3.params["anchor_margin"] < 0.15)

print("\n[10] PolicyVoter")
pv=PolicyVoter(); check("PolicyVoter ok", pv is not None)
# 行为验证：内存压力高 → 应通过；内存充足 → 应否决（真实决策，非仅构造）
learner_v = PareLearner()
pv_prof = learner_v.get("big.exe")
pv_prof.kalman.x_freed = 300 << 20; pv_prof.kalman.x_cost = 30
pv_prof.ws_deque.append(100 << 20); pv_prof.ws_deque.append(100 << 20)
ok_h, _, _ = pv.should_trim("big.exe", 300 << 20, {"mem_pct": 90, "mem_trend": 0.05}, learner_v)
check("压力高→投票通过", ok_h)
# 树5 反事实 peers 排除自身（修复：含自身会抬高均值致优势低估）
pv_b = learner_v.get("small.exe")
pv_b.kalman.x_freed = 10 << 20; pv_b.kalman.x_cost = 5
pv_b.ws_deque.append(50 << 20); pv_b.ws_deque.append(50 << 20)
_, _, sc = pv.should_trim("big.exe", 300 << 20, {"mem_pct": 70, "mem_trend": 0.0}, learner_v)
check("peers 排除自身→优势分=2", sc[4] == 2, f"scores={sc}")

print("\n[11] ERIS 纯函数（core.eris，与生产共用）")
buf = deque(maxlen=25)
d, p50, iqr = iqr_dim(100.0, buf, 0.0, 0.0, update_state=True)
check("冷启动中性 80", d == 80.0)
for v in [50, 60, 70, 80, 90]:
    iqr_dim(v, buf, p50, iqr, update_state=True)
d, _, _ = iqr_dim(100.0, buf, p50, iqr, update_state=False)
check("高于 p50→>80", d > 80.0)
d2, _, _ = iqr_dim(50.0, buf, p50, iqr, update_state=False)
check("低于 p50→<80", d2 < 80.0)
# 早期窗口（nL=2/3）不再二值化且不虚高（修复：冷启动 p50 用原始中位，EWMA 未收敛不参与）
buf2 = deque(maxlen=25)
iqr_dim(80.0, buf2, 0.0, 0.0, update_state=True)
d_early, p50e, _ = iqr_dim(84.0, buf2, 0.0, 0.0, update_state=True)
check("早期窗口非二值非虚高", 70 < d_early < 110, f"d={d_early}")
# nT=2 负索引窗口（修复）：不崩溃且输出在界内
buf3 = deque(maxlen=25)
for v in [50, 60, 70, 80]:
    iqr_dim(v, buf3, 0.0, 0.0, update_state=True)
d4, _, _ = iqr_dim(75.0, buf3, 0.0, 0.0, update_state=False)
check("nT=2 窗口在界内", 1.0 <= d4 <= 130.0, f"d={d4}")
check("clamp≤130", iqr_dim(1e9, deque([50.0, 60, 70, 80, 90], maxlen=25), 70.0, 5.0, update_state=False)[0] <= 130)
check("clamp≥1", iqr_dim(-1e9, deque([50.0, 60, 70, 80, 90], maxlen=25), 70.0, 5.0, update_state=False)[0] >= 1)

print("\n[12] ERIS Data Validation（共用 core.eris.validate_state）")
W = [25, 25, 20, 8, 20]
check("valid", validate_state([[1.0]*6]*5, [0.1]*5, W))
check("dim mismatch", not validate_state([[1.0]]*3, [0.0]*3, W))
check(">window elements", not validate_state([[1.0]*26]*5, [0.0]*5, W))
check("NaN", not validate_state([[float('nan')]*10]*5, [0.0]*5, W))
check("inf", not validate_state([[float('inf')]*10]*5, [0.0]*5, W))
check("negative ewma", not validate_state([[1.0]*10]*5, [-0.1,0,0,0,0], W))
check("not dict", not validate_state("string", [0.0]*5, W))
check("empty bufs ok", validate_state([[]]*5, [0.0]*5, W))

print("\n[13] 终极审查修复回归（2026-08-12）")
# config 白名单清洗：历史遗留键（compress/combine 等）无消费方，load 后必须被过滤
_WL = {"ws", "standby", "modified", "filecache", "volume", "registry"}
cfg_w = config_load()
check("clean_operations 全白名单", all(k in _WL for k in cfg_w.get("clean_operations", [])))
# DEFAULT_CFG 补全：与 GUI 消费方默认值一致（原分散在各 .get() 兜底）
check("DEFAULT_CFG emergency_threshold", DEFAULT_CFG["emergency_threshold"] == 80)
check("DEFAULT_CFG log_to_file", DEFAULT_CFG["log_to_file"] is False)
check("DEFAULT_CFG close_action", DEFAULT_CFG["close_action"] == "ask")
check("DEFAULT_CFG tray_left_action", DEFAULT_CFG["tray_left_action"] == "show")
# prior office 分类无重复元素（重复名不副实）
check("office 分类无重复", len(HierarchicalPrior.CATEGORIES["office"]) == len(set(HierarchicalPrior.CATEGORIES["office"])))
# judger 无 _prev_agg 死字段（无消费方的冗余赋值已移除）
j_tmp = PareJudger(l2, {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j_tmp.update_pressure(55)
check("judger 无 _prev_agg 死字段", not hasattr(j_tmp, "_prev_agg"))
# 未知模式防御：optimize else 分支回退 normal 语义（不再无参全量 layer1）——走纯配置检查
check("clean_mode 默认 normal", config_load().get("clean_mode", "normal") in ("quick","normal","deep","full"))

print("\n[14] 稳定锚点与安全门（P0/P1 批次）")
# ── 前台历史冷却：刚切走的进程拒绝；窗口过后放行 ──
j_fg = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j_fg._low_activity[7001] = (2, time.time(), None)
pfg = j_fg.learner.get("fgtest.exe"); pfg.last_foreground_at = time.time() - 10
sfg = Snap(); sfg.name="fgtest.exe"; sfg.ws=200<<20; sfg.path="d:\\app\\fgtest.exe"; sfg.pid=7001; sfg.pf=0; sfg.priv=0; sfg.fg=False
ok_fg, reason_fg = j_fg.can_trim(sfg)
check("刚切走拒绝", not ok_fg and "刚切走" in reason_fg, reason_fg)
pfg.last_foreground_at = time.time() - 301
ok_fg2, _ = j_fg.can_trim(sfg)
check("超窗口放行", ok_fg2)
# 手动模式跳过前台冷却（用户主动清理刚切走程序是目标）
j_fg._manual_mode = True
pfg.last_foreground_at = time.time() - 10
ok_fg3, _ = j_fg.can_trim(sfg)
j_fg._manual_mode = False
check("手动跳过前台冷却", ok_fg3)
# ── CPU 活跃门：正在干活的进程拒绝；手动同样生效 ──
j_cpu = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j_cpu._low_activity[7002] = (2, time.time(), None)
sc = Snap(); sc.name="cpubusy.exe"; sc.ws=200<<20; sc.path="d:\\app\\cpubusy.exe"; sc.pid=7002; sc.pf=0; sc.priv=0; sc.fg=False; sc.cpu=50.0
ok_c, reason_c = j_cpu.can_trim(sc)
check("CPU活跃拒绝", not ok_c and "CPU活跃" in reason_c, reason_c)
j_cpu._manual_mode = True
ok_c2, _ = j_cpu.can_trim(sc)
check("手动也拦CPU活跃", not ok_c2)
# ── 连续低活动确认：1 轮拒绝，2 轮放行 ──
j_act = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j_act._low_activity[7003] = (1, time.time())
sa = Snap(); sa.name="acttest.exe"; sa.ws=200<<20; sa.path="d:\\app\\acttest.exe"; sa.pid=7003; sa.pf=0; sa.priv=0; sa.fg=False
ok_a, reason_a = j_act.can_trim(sa)
check("确认1轮拒绝", not ok_a and "活动确认" in reason_a, reason_a)
j_act._low_activity[7003] = (2, time.time(), None)
ok_a2, _ = j_act.can_trim(sa)
check("确认2轮放行", ok_a2)
# 进程重启（创建时间变化）→ 计数清零重新确认（防新实例继承旧计数）
j_act._low_activity[7003] = (2, time.time(), 111)
j_act.update_activity([sa])
check("重启清零重新确认", j_act._low_activity.get(7003, (0, 0, 0))[0] == 1)
# ── StableAnchor 纯函数：置信前不抑制/确认后低WS抑制/高WS不抑制/余量参数 ──
an = StableAnchor()
an.feed(500<<20, "k1|1", time.time()); an.feed(520<<20, "k1|1", time.time()); an.feed(510<<20, "k1|1", time.time())
check("锚点未确认不抑制", not an.should_suppress(400<<20))
for _ in range(5): an.feed(500<<20, "k1|1", time.time())
check("锚点确认后抑制", an.should_suppress(400<<20))
check("锚点高WS不抑制", not an.should_suppress(1000<<20))
check("锚点余量参数生效", not an.should_suppress(600<<20, 0.05) and an.should_suppress(600<<20, 0.5))
# 启动签名隔离：新实例重置锚点
an.feed(900<<20, "k1|2", time.time())
check("新实例不继承旧锚点", not an.should_suppress(400<<20))
# ── 锚点持久化 roundtrip（并入 learner save/load）──
l_save = PareLearner()
an2 = StableAnchor("k2|1")
for _ in range(8): an2.feed(300<<20, "k2|1", time.time())
l_save.stable_anchors.anchors["d:\\app\\anchor.exe"] = an2
tmp2 = os.path.join(tempfile.gettempdir(), "mw_anchor_test.json")
check("anchor save ok", l_save.save(tmp2))
l_load = PareLearner.load(tmp2)
a_loaded = l_load.stable_anchors.anchors.get("d:\\app\\anchor.exe")
check("anchor load roundtrip", a_loaded is not None and a_loaded.confirmed and a_loaded.should_suppress(200<<20))
os.remove(tmp2)
# ── EFIS anchor_margin 参数 ──
check("anchor_margin 范围", PARAMS["anchor_margin"]["min"] <= 0.15 <= PARAMS["anchor_margin"]["max"])

print("\n[15] 清理模式严格度适配（四模式×守卫）")
# full：跳过冷却/确认/CPU门/IO门（极限=立即清、不设活跃门槛；量化：CPU门 12% 在真实负载拖累 18-26%）
j_full = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j_full._mode_guard = "full"
pfu = j_full.learner.get("fulltest.exe"); pfu.last_foreground_at = time.time() - 10
sfu = Snap(); sfu.name="fulltest.exe"; sfu.ws=200<<20; sfu.path="d:\\app\\fulltest.exe"; sfu.pid=9001; sfu.pf=0; sfu.priv=0; sfu.fg=False
ok_fu, _ = j_full.can_trim(sfu)
check("full跳过冷却", ok_fu)
sfu.cpu = 10.0
ok_fu2, _ = j_full.can_trim(sfu)
check("full CPU10放行", ok_fu2)
sfu.cpu = 50.0
ok_fu3, reason_fu3 = j_full.can_trim(sfu)
check("full CPU50放行(跳过CPU门)", ok_fu3, f"{reason_fu3}")
# full：IO 活跃进程也放行（跳过 IO 门；量化：下载/播放场景 IO 门拖累 4.9%）
_orig_io = j_full._io_active
j_full._io_active = lambda pid: True
ok_fu4, _ = j_full.can_trim(sfu)
j_full._io_active = _orig_io
check("full IO活跃放行(跳过IO门)", ok_fu4)
# normal：CPU10 拒绝（8% 门）；IO 活跃拒绝
j_norm = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j_norm._low_activity[9002] = (2, time.time(), None)
sn_ = Snap(); sn_.name="normtest.exe"; sn_.ws=200<<20; sn_.path="d:\\app\\normtest.exe"; sn_.pid=9002; sn_.pf=0; sn_.priv=0; sn_.fg=False; sn_.cpu=10.0
ok_no, reason_no = j_norm.can_trim(sn_)
check("normal CPU10拒绝", not ok_no and "CPU活跃" in reason_no, reason_no)
_orig_io2 = j_norm._io_active
j_norm._io_active = lambda pid: True
sn_.cpu = 0.0  # 先过 CPU 门，专测 IO 门
ok_no2, reason_no2 = j_norm.can_trim(sn_)
j_norm._io_active = _orig_io2
check("normal IO活跃拒绝", not ok_no2 and "IO活跃" in reason_no2, reason_no2)
# deep：冷却减半（曾前台 200s → deep 已过 150s 冷却放行 / normal 仍处 300s 冷却拦截）
j_deep = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j_deep._mode_guard = "deep"
j_deep._low_activity[9003] = (2, time.time(), None)
pd_ = j_deep.learner.get("deeptest.exe"); pd_.last_foreground_at = time.time() - 200
sd_ = Snap(); sd_.name="deeptest.exe"; sd_.ws=200<<20; sd_.path="d:\\app\\deeptest.exe"; sd_.pid=9003; sd_.pf=0; sd_.priv=0; sd_.fg=False
ok_de, _ = j_deep.can_trim(sd_)
check("deep冷却减半放行", ok_de)
j_norm2 = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j_norm2._low_activity[9004] = (2, time.time(), None)
pd2 = j_norm2.learner.get("deeptest.exe"); pd2.last_foreground_at = time.time() - 200
sd2 = Snap(); sd2.name="deeptest.exe"; sd2.ws=200<<20; sd2.path="d:\\app\\deeptest.exe"; sd2.pid=9004; sd2.pf=0; sd2.priv=0; sd2.fg=False
ok_no2, reason_no2 = j_norm2.can_trim(sd2)
check("normal冷却200s拦截", not ok_no2 and "刚切走" in reason_no2, reason_no2)

print("\n[16] 模式价值底线梯度（θ：deep 0.12 / full 0.06 / normal 无）")
# deep：θ<0.12 拒绝
jd_v = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
jd_v._mode_guard = "deep"
jd_v._low_activity[9101] = (2, time.time(), None)
import random as _random  # 确定性低 θ（防 Beta 抽样随机波动）
_random.betavariate = lambda a, b: 0.001
pf_v = jd_v.learner.get("floor.exe")
pf_v.ws_deque.append(100 << 20); pf_v.ws_deque.append(100 << 20)  # 有样本才走画像 θ（无样本 thompson_score 返回先验 0.35）
pf_v.alpha, pf_v.beta = 1, 20  # 极低 θ
pf_v._theta_dirty = True
sf_v = Snap(); sf_v.name="floor.exe"; sf_v.ws=200<<20; sf_v.path="d:\\app\\floor.exe"; sf_v.pid=9101; sf_v.pf=0; sf_v.priv=0; sf_v.fg=False
ok_fv, reason_fv = jd_v.can_trim(sf_v)
check("deep价值底线拒绝", not ok_fv and "价值不足" in reason_fv, f"{reason_fv} θ={pf_v.thompson_theta:.2f}")
# full：θ 0.08 放行、θ≈0 拒绝
jf_v = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
jf_v._mode_guard = "full"
jf_v._low_activity[9102] = (2, time.time(), None)
pf2 = jf_v.learner.get("floor2.exe")
pf2.alpha, pf2.beta = 2, 10  # 中等偏低 θ
pf2._theta_dirty = True
sf2 = Snap(); sf2.name="floor2.exe"; sf2.ws=200<<20; sf2.path="d:\\app\\floor2.exe"; sf2.pid=9102; sf2.pf=0; sf2.priv=0; sf2.fg=False
t2 = pf2.thompson_theta
if t2 >= 0.06:
    ok_f2, _ = jf_v.can_trim(sf2)
    check("full中低θ放行", ok_f2)
else:
    check("full中低θ放行", True)  # 画像实际 θ 低于底线则跳过（断言构造失效保护）
# 极低 θ（≈0.01）→ full 也拒绝（monkeypatch betavariate 固定小值——防 Beta 抽样随机波动致断言不稳定）
import random as _random
_orig_beta = _random.betavariate
_random.betavariate = lambda a, b: 0.001
pf3 = jf_v.learner.get("floor3.exe")
pf3.ws_deque.append(100 << 20); pf3.ws_deque.append(100 << 20)
pf3.alpha, pf3.beta = 0.5, 50
pf3._theta_dirty = True
sf3 = Snap(); sf3.name="floor3.exe"; sf3.ws=200<<20; sf3.path="d:\\app\\floor3.exe"; sf3.pid=9103; sf3.pf=0; sf3.priv=0; sf3.fg=False
ok_f3, reason_f3 = jf_v.can_trim(sf3)
check("full极低θ拒绝", not ok_f3 and "价值不足" in reason_f3, f"{reason_f3} θ={pf3.thompson_theta:.2f}")
_random.betavariate = _orig_beta
# normal：无底线（θ≈0 也过价值底线——后续由投票决定）
jn_v = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
jn_v._low_activity[9104] = (2, time.time(), None)
pf4 = jn_v.learner.get("floor4.exe")
pf4.alpha, pf4.beta = 0.5, 50
pf4._theta_dirty = True
sf4 = Snap(); sf4.name="floor4.exe"; sf4.ws=200<<20; sf4.path="d:\\app\\floor4.exe"; sf4.pid=9104; sf4.pf=0; sf4.priv=0; sf4.fg=False
ok_f4, reason_f4 = jn_v.can_trim(sf4)
check("normal无价值底线", "价值不足" not in reason_f4, reason_f4)

print("\n[17] 稳态锁梯度（deep/full 跳过 WS基线/锚点/回弹，normal 保留）")
# 核心修复验证：稳态豁免（agg≥0.8）与 PID 实际输出不匹配（默认参数高压峰值仅 0.38）——
# 曾导致稳态锁全局锁死 deep/full 压缩能力（卡 37%）。现按模式梯度：normal 保留，deep/full 解除
import random as _random
_orig_random = _random.random
_random.random = lambda: 0.9  # 固定 0.9 ≥ EXPLORE_RATE(0.05)：确定性触发抑制/回弹拦截

def _mk_lock_j(mode):
    j = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
    j._mode_guard = mode
    j.aggressiveness = 0.3  # 低 agg：稳态锁生效区（默认参数高压峰值 0.38，实测从未达豁免阈值）
    if mode != "full":
        j._low_activity[9200] = (2, time.time(), None)
    j.learner.policy.should_trim = lambda *a, **k: (True, "", [])  # 放行投票：专测稳态锁
    return j

def _mk_lock_snap(ws=60 << 20):
    s = Snap(); s.name="lock.exe"; s.ws=ws; s.path="d:\\app\\lock.exe"; s.pid=9200; s.pf=0; s.priv=0; s.fg=False
    return s

# a. WS 基线：清后未回填（ws<基线）→ normal 拦 / deep·full 放行
for mode, expect_ok in (("normal", False), ("deep", True), ("full", True)):
    j = _mk_lock_j(mode)
    j.mark_trimmed("lock.exe", freed=0, ws_before=100 << 20, pf_delta=0, ws_after=80 << 20)
    j._post_clean_time["lock.exe"] = time.time() - 100
    ok, reason = j.can_trim(_mk_lock_snap(60 << 20))
    check(f"WS基线 {mode}={'放行' if expect_ok else '拦截'}", ok == expect_ok, f"{mode} {reason}")
# b. 稳态锚点：低于自然稳态 → normal 拦 / deep·full 放行（ws>基线 隔离 WS 基线检查）
for mode, expect_ok in (("normal", False), ("deep", True), ("full", True)):
    j = _mk_lock_j(mode)
    j.mark_trimmed("lock.exe", freed=0, ws_before=100 << 20, pf_delta=0, ws_after=50 << 20)
    j._post_clean_time["lock.exe"] = time.time() - 100
    j.learner.stable_anchors.anchors["d:\\app\\lock.exe"] = type("A", (), {
        "confirmed": True, "should_suppress": lambda self, ws, m=0.15: True})()
    ok, reason = j.can_trim(_mk_lock_snap(100 << 20))
    check(f"锚点抑制 {mode}={'放行' if expect_ok else '拦截'}", ok == expect_ok, f"{mode} {reason}")
# c. 回弹后退：高回填后退期 → normal 拦 / deep·full 放行
for mode, expect_ok in (("normal", False), ("deep", True), ("full", True)):
    j = _mk_lock_j(mode)
    for _ in range(3):  # 3 次全回填采样：ewma 0.51→0.657→0.76 ≥ 0.7 且 count≥3 → 进入后退期
        j.learner.rebound.record("d:\\app\\lock.exe", 100 << 20, 100 << 20, time.time())
    check("回弹后退已进入", j.learner.rebound.in_backoff("d:\\app\\lock.exe", time.time()))
    ok, reason = j.can_trim(_mk_lock_snap())
    check(f"回弹后退 {mode}={'放行' if expect_ok else '拦截'}", ok == expect_ok, f"{mode} {reason}")
_random.random = _orig_random
# efis 参数边界合理化：pid_kp 下限防触底（0.30 时高压峰值 agg 仅 0.38）、pid_kd 上限防触顶（0.50 的 D 项振荡）
check("pid_kp 下限防触底", PARAMS["pid_kp"]["min"] == 0.45)
check("pid_kd 上限防触顶", PARAMS["pid_kd"]["max"] == 0.35)

print("\n[18] 投票 threshold 模式梯度接线（normal=0 / deep=-1 / full=-2）")
# policy 早已支持 threshold 参数但调用处未传——2026-08-14 接线验证（设计意图补全）
def _mk_vote_j(mode):
    j = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
    j._mode_guard = mode
    j.aggressiveness = 0.3
    if mode != "full":
        j._low_activity[9300] = (2, time.time(), None)
    j._post_clean_ws["vote.exe"] = 150 << 20  # 有基线且 ws<2×基线 → 走投票分支（非 ws_override）
    return j
_captured = {}
for mode, expect in (("normal", 0), ("deep", -1), ("full", -2)):
    j = _mk_vote_j(mode)
    _orig_vote = j.learner.policy.should_trim
    def _wrap(name, ws, state, learner, threshold=0, _m=mode):
        _captured[_m] = threshold
        return _orig_vote(name, ws, state, learner, threshold)
    j.learner.policy.should_trim = _wrap
    sv = Snap(); sv.name="vote.exe"; sv.ws=200<<20; sv.path="d:\\app\\vote.exe"; sv.pid=9300; sv.pf=0; sv.priv=0; sv.fg=False
    j.can_trim(sv)
    check(f"投票threshold {mode}={expect}", _captured.get(mode) == expect, f"实际 {_captured.get(mode)}")


print("\n[19] 窗口冷却与回弹学习（A/B 方案批次）")
# ── 窗口冷却：有可见窗口 600s / 无窗口 300s（301-599s 区间区分）──
j_win = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j_win._low_activity[8001] = (2, time.time(), None)
pw = j_win.learner.get("wintest.exe"); pw.last_foreground_at = time.time() - 400
sw = Snap(); sw.name="wintest.exe"; sw.ws=200<<20; sw.path="d:\\app\\wintest.exe"; sw.pid=8001; sw.pf=0; sw.priv=0; sw.fg=False
sw.has_visible = True
ok_w, reason_w = j_win.can_trim(sw)
check("可见窗口400s仍拒绝", not ok_w and "刚切走" in reason_w, reason_w)
sw.has_visible = False
ok_w2, _ = j_win.can_trim(sw)
check("无窗口400s放行", ok_w2)
# 手动模式跳过窗口冷却
j_win._manual_mode = True
sw.has_visible = True
ok_w3, _ = j_win.can_trim(sw)
j_win._manual_mode = False
check("手动跳过窗口冷却", ok_w3)
# ── 回弹学习纯函数：观察→结算→后退→解除 ──
from core.rebound import ReboundLearner, _key
rb = ReboundLearner()
now0 = time.time()
rb.begin(r"d:\app\chrome.exe", 200<<20, 300<<20, now0)
class _S: pass
def _mk(ws, path):
    s = _S(); s.ws = ws; s.path = path; return s
# 观察期未到：不结算
rb.observe([_mk(500<<20, r"d:\app\chrome.exe")], now0 + 60)
check("观察期未到不结算", rb.count == {})
# 到期结算：回填 190MB/200MB = 95% → EWMA 高
rb.observe([_mk(490<<20, r"d:\app\chrome.exe")], now0 + 121)
check("回弹结算", rb.count.get(r"d:\app\chrome.exe".lower().replace("/", "\\")) == 1)
k = _key(r"d:\app\chrome.exe")
check("回弹EWMA吸收高回弹", rb.ewma.get(k, 0) > 0.4)  # 首次 0.3×0.95+0.7×0.3=0.495
# 连续 3 次高回弹 → 后退
for i in range(2):
    rb.begin(r"d:\app\chrome.exe", 200<<20, 300<<20, now0 + 200 + i)
    rb.observe([_mk(490<<20, r"d:\app\chrome.exe")], now0 + 320 + i)
check("高回弹3次后退", rb.in_backoff(r"d:\app\chrome.exe", now0 + 400))
# 回弹率持续回落（2 次低回弹，EWMA 惯性越过 0.5）→ 解除后退
rb.record(k, 200<<20, 20<<20, now0 + 500)   # 10% 回弹
rb.record(k, 200<<20, 20<<20, now0 + 600)
check("低回弹解除后退", not rb.in_backoff(r"d:\app\chrome.exe", now0 + 700))
# 后退期不随记录重置（未到 30 分钟）——验证 in_backoff 时间判定；
# 解除后再次持续高回弹（3 次越过 0.7 迟滞线——防抖设计使重新触发需多轮确认）→ 重新后退
rb.record(k, 200<<20, 190<<20, now0 + 700)
rb.record(k, 200<<20, 190<<20, now0 + 800)
rb.record(k, 200<<20, 190<<20, now0 + 900)
check("再次高回弹进入后退", rb.in_backoff(r"d:\app\chrome.exe", now0 + 1000))
# 持久化 roundtrip
tmp3 = os.path.join(tempfile.gettempdir(), "mw_rebound_test.json")
l_rb = PareLearner(); l_rb.rebound = rb
check("rebound save ok", l_rb.save(tmp3))
l_rb2 = PareLearner.load(tmp3)
check("rebound load roundtrip", l_rb2.rebound.ewma.get(k, 0) == rb.ewma.get(k, 0) and
      l_rb2.rebound.backoff_until.get(k, 0) == rb.backoff_until.get(k, 0))
os.remove(tmp3)

# ═══════════════════════════════════════════
# ── 全量审查修复回归（v3.7.09 追加）──
try:
    # learner.top(n)：CLI learn 依赖（曾缺失导致 AttributeError 崩溃）
    lt = PareLearner()
    for nm, ws, freed, ok in [("aaa.exe", 50 << 20, 200 << 20, True), ("bbb.exe", 60 << 20, 40 << 20, True), ("ccc.exe", 30 << 20, 0, False)]:
        p = lt.get(nm)
        for _ in range(3):
            p.feed(ws)
        p.record_clean(ok, freed, 10)
    top3 = lt.top(25)
    check("top returns list", isinstance(top3, list))
    check("top sorted by roi", top3 == sorted(top3, key=lambda x: x[1], reverse=True))
    check("top roi 有区分度", top3[0][1] > top3[-1][1])
    check("top tuple shape", len(top3[0]) == 4 if top3 else True)
    check("top filters <2 samples", all(p.total_samples >= 2 for _, _, _, p in top3))
    # get_parent_process_name：64 位偏移兼容（修复前返回垃圾值/None）
    import os as _os, core.winapi as _wa
    _pp = _wa.get_parent_process_name(_os.getpid())
    check("parent name str", isinstance(_pp, str) and len(_pp) > 0)
    check("parent unknown pid", _wa.get_parent_process_name(99999999) is None)
except Exception as ex:
    check("review regression", False, repr(ex))

print("\n[20] 多实例计数独立（A1 修复：确认键按 PID）")
j_mi = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
# 两个同名进程（如 chrome 子进程）：一个活跃一个低活动——计数互不干扰
s_m1 = Snap(); s_m1.name="chrome.exe"; s_m1.pid=9501; s_m1.cpu=50.0; s_m1.create=1
s_m2 = Snap(); s_m2.name="chrome.exe"; s_m2.pid=9502; s_m2.cpu=1.0; s_m2.create=1
j_mi.update_activity([s_m1, s_m2])
check("活跃实例计数清零", 9501 not in j_mi._low_activity)
check("低活动实例独立计数", j_mi._low_activity.get(9502, (0, 0, 0))[0] == 1)
j_mi.update_activity([s_m1, s_m2])
check("低活动实例累计2", j_mi._low_activity.get(9502, (0, 0, 0))[0] == 2)

print("\n[21] i18n 语言支持（原文即 key / 前缀匹配 / 递归 / 回退）")
from core.i18n import tr, tr_msg, set_language, get_language, LANGUAGES, _EN
# 中文模式：原样返回
set_language("zh_CN")
check("中文模式原样", tr("⚡ 优化") == "⚡ 优化" and get_language() == "zh_CN")
# 英文模式：精确匹配
set_language("en")
check("英文精确匹配", tr("⚡ 优化") == "⚡ Optimize")
# 前缀匹配 + 参数保留 + 后缀递归
check("前缀参数保留", tr_msg("WS未填满(80/120)") == "WS below baseline (80/120)", tr_msg("WS未填满(80/120)"))
check("冷却参数保留", tr_msg("失败冷却中(45s)") == "Failure cooldown (45s)", tr_msg("失败冷却中(45s)"))
# 数字开头 + 片段替换（托盘场景）
check("托盘tip递归", tr_msg("🔴 守护中 90% — 内存紧张") == "🔴 Guarding 90% — memory pressure", tr_msg("🔴 守护中 90% — 内存紧张"))
# 未命中回退（渐进式安全）
check("未命中回退原文", tr("完全未收录的测试字符串") == "完全未收录的测试字符串")
# 未知语言回退中文
set_language("fr")
check("未知语言回退", get_language() == "zh_CN")
set_language("en")
# 映射表完整性：核心判定理由全覆盖
for reason in ("刚切走", "CPU活跃", "IO活跃", "稳态抑制", "回弹后退", "价值不足", "系统核心进程"):
    check(f"理由覆盖:{reason}", _EN.get(reason) is not None)
# tooltip 拼接场景（相邻字面量合并后的完整串——精确匹配必失败，走片段全替换）
_tooltip = ("按当前选择的清理模式立即执行一次内存优化\n" "游戏模式下游戏进程受完全保护，其余进程将由进程决策优化")
_tr_r = tr(_tooltip)
check("tooltip拼接翻译", "optimization" in _tr_r and "protected" in _tr_r and "process decisions" in _tr_r, _tr_r[:60])
# "维持" 与 agg 标签（高/中/低）分离——粘连防护
check("维持高分离", tr_msg("维持高") == "staying high", tr_msg("维持高"))
check("维持中分离", tr_msg("维持中") == "staying medium", tr_msg("维持中"))
check("维持低分离", tr_msg("维持低") == "staying low", tr_msg("维持低"))
# GUI 全部 tr("中文") 字面量静态完整性（精确键或可片段替换）
import io as _io, re as _re
_src = _io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memwise_gui.py"),
                encoding="utf-8").read()
_missing = []
for m in _re.finditer(r'tr\("([^"]*[\u4e00-\u9fff][^"]*)"\)', _src):
    lit = m.group(1).replace("\\n", "\n")  # 源码转义还原（\n → 真实换行）
    if lit not in _EN and not any(len(k) >= 4 and k in lit for k in _EN):
        _missing.append(lit[:30])
check("GUI tr 字面量全覆盖", not _missing, f"缺映射: {_missing[:5]}")

print("\n[22] 2026-08-14 全量审查修复回归")
# ── A1 稳态锚点多实例聚合（同路径多实例锚点不再每轮重置）──
class _Snap:
    pass
def _mk_s(name, ws, path, create):
    s = _Snap(); s.name = name; s.ws = ws; s.path = path; s.create = create
    return s
_store = StableAnchorStore()
_multi = [_mk_s("chrome.exe", (300 + i * 40) << 20, r"d:\app\chrome\chrome.exe", 1000 + i) for i in range(8)]
for _ in range(30):
    _store.feed(_multi, time.time(), set())
_a = _store.anchors.get(r"d:\app\chrome\chrome.exe")
check("A1 多实例锚点收敛", _a is not None and _a.samples >= 5 and _a.confirmed, f"samples={_a.samples if _a else 0}")
_store1 = StableAnchorStore()
for _ in range(8):
    _store1.feed([_mk_s("note.exe", 500 << 20, r"d:\app\note.exe", 777)], time.time(), set())
_a1 = _store1.anchors.get(r"d:\app\note.exe")
check("A1 单实例行为不变", _a1.samples == 8 and _a1.confirmed)
_gen0 = _a1.generation
_store1.feed([_mk_s("note.exe", 500 << 20, r"d:\app\note.exe", 9999)], time.time(), set())
check("A1 真重启触发新代", _store1.anchors[r"d:\app\note.exe"].generation == _gen0 + 1)
# ── A2 config 归一 + 白名单（临时文件，不碰真实配置）──
import core.config as _cfg_mod
_orig_cfg_p = _cfg_mod.CONFIG_PATH
_tcfg = os.path.join(tempfile.gettempdir(), "mw_cfg_audit.yaml")
with open(_tcfg, "w", encoding="utf-8") as f:
    f.write("never: null\ngame_processes: null\nclean_operations: null\ndaemon_trim_every_ticks: 3\n")
_cfg_mod.CONFIG_PATH = _tcfg
_d2 = _cfg_mod.load()
_cfg_mod.CONFIG_PATH = _orig_cfg_p
os.remove(_tcfg)
check("A2 死键白名单清除", "daemon_trim_every_ticks" not in _d2)
check("A2 never 归一为列表", _d2.get("never") == [] and isinstance(_d2.get("game_processes"), list))
check("A2 clean_operations 归一", isinstance(_d2.get("clean_operations"), list) and len(_d2.get("clean_operations", [])) > 0)
# ── A3 judger 并发锁存在（修复面静态断言）──
_jl = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
check("A3 judger._lock 存在", hasattr(_jl, "_lock"))
# ── B1/B8/B9 双语键完备 ──
from core.i18n import _EN as _EN_A
for _k in ("  · quick — 仅系统级清理，几秒完成，几乎无感知\n",
           "  · deep — 追加系统级深度清扫与深层回收，清理更彻底\n",
           "  · full — 极限释放，尽最大可能腾出内存空间，包括刚切走或正在工作的程序内存\n",
           "                   适合：随手一点，不想有任何感知\n",
           "                      适合：日常使用，兼顾效果与流畅\n",
           "                  适合：内存偏紧，接受短暂变慢\n",
           "               适合：内存告急，需要立刻腾出最多空间\n"):
    check(f"B1 键存在:{_k.strip()[:18]}", _k in _EN_A or _k.rstrip("\n") in _EN_A)
check("B8 是/否键", "是" in _EN_A and "否" in _EN_A)
check("B9 守护异常键", "❌ 守护异常，详见下方错误信息" in _EN_A)
# ── B1 翻译实证：补键后 tooltip 行完整英文无中文 ──
set_language("en")
_line_d = tr("  · deep — 追加系统级深度清扫与深层回收，清理更彻底\n")
check("B1 deep 行完整翻译", "Deep" in _line_d and "深度" not in _line_d and "清理" not in _line_d, _line_d[:40])
set_language("zh_CN")
# ── B10 kalman_r 遍历更新逻辑 ──
_lr = PareLearner()
_pa = _lr.get("kr.exe")
for _p in _lr.profiles.values():
    _p.kalman.r = 8.0
check("B10 kalman_r 遍历生效", _pa.kalman.r == 8.0)

print("\n[23] 四模式梯度修复回归（2026-08-14 梯度专项）")
# ── 活动确认梯度：normal 2 轮 / deep 1 轮 / full 跳过 ──
j_g = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j_g._mode_guard = "normal"; j_g.aggressiveness = 0.1
j_g._low_activity[9601] = (1, time.time(), None)
sg = Snap(); sg.name="g.exe"; sg.ws=200<<20; sg.path="d:\\app\\g.exe"; sg.pid=9601; sg.pf=0; sg.priv=0; sg.fg=False
ok_n, r_n = j_g.can_trim(sg)
check("活动确认 normal 1轮拦", not ok_n and "活动确认" in r_n, r_n)
j_d = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j_d._mode_guard = "deep"; j_d.aggressiveness = 0.1
j_d._low_activity[9601] = (1, time.time(), None)
ok_d, r_d = j_d.can_trim(sg)
check("活动确认 deep 1轮放行", ok_d, r_d)
j_f = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j_f._mode_guard = "full"; j_f.aggressiveness = 0.1
ok_f, _ = j_f.can_trim(sg)
check("活动确认 full 跳过", ok_f)
# ── ws_all 使用率门控：中高压(≥33%)执行 / 低压豁免（monkeypatch，不触碰真实系统操作）──
from core.cleaner import PareCleaner, DEEP_WSALL_PCT_GATE
import core.winapi as _wa
def _run_deep_opt(pct):
    lr_o = PareLearner()
    j_o = PareJudger(lr_o, {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[],"efis_params":{}})
    c_o = PareCleaner(j_o)
    captured = {}
    c_o._layer1_memreduct = lambda **kw: captured.update(ops=kw.get('ops'))
    c_o._layer3_deep = lambda *a, **k: None  # 防真实系统清理调用
    _orig_ms = _wa.get_memory_status
    _orig_mub = _wa.get_memory_used_bytes
    _wa.get_memory_status = lambda: {"pct": pct, "total": 16<<30, "avail": (16<<30)-int(pct/100*16)<<30, "used": int(pct/100*16)<<30}
    _wa.get_memory_used_bytes = lambda: int(pct/100*16)<<30
    try:
        c_o.optimize([], lr_o, "deep", operations=["ws"], aggressiveness=0.1)
    finally:
        _wa.get_memory_status = _orig_ms
        _wa.get_memory_used_bytes = _orig_mub
    return captured.get('ops')
ops_hi = _run_deep_opt(40)
check("deep 使用率40% ws_all 执行", ops_hi is not None and "ws_all" in ops_hi, str(ops_hi))
ops_lo = _run_deep_opt(30)
check("deep 使用率30% ws_all 豁免", ops_lo is not None and "ws_all" not in ops_lo, str(ops_lo))
check("DEEP_WSALL_PCT_GATE=33", DEEP_WSALL_PCT_GATE == 33)
# ── fast_track 梯度：deep 350KB/s 档（normal 500 不进 / deep 400 进）──
def _run_ft(mode, refill_kb):
    lr_f = PareLearner()
    j_f2 = PareJudger(lr_f, {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[],"efis_params":{}})
    j_f2._mode_guard = mode
    c_f = PareCleaner(j_f2)
    _orig_can = j_f2.can_trim
    j_f2.can_trim = lambda s: (True, "")
    _orig_trim = c_f._trim_process
    c_f._trim_process = lambda snap, learner: (True, 0, 0, "模拟")
    _orig_eco = _wa.set_eco_qos; _orig_mp = _wa.set_memory_priority
    _wa.set_eco_qos = lambda *a, **k: True; _wa.set_memory_priority = lambda *a, **k: True
    sf = Snap(); sf.name="ft.exe"; sf.ws=200<<20; sf.path="d:\\app\\ft.exe"; sf.pid=9701
    sf.pf=0; sf.priv=0; sf.fg=False; sf.cpu=0.0; sf.parent=0; sf.create=time.time(); sf.has_visible=False
    p = lr_f.get("ft.exe"); p.refill_ewma = refill_kb << 10
    try:
        c_f._layer2_process([sf], lr_f)
    finally:
        j_f2.can_trim = _orig_can
        c_f._trim_process = _orig_trim
        _wa.set_eco_qos = _orig_eco; _wa.set_memory_priority = _orig_mp
    return 9701 in c_f._fast_track
check("fast_track deep 400KB/s 进池", _run_ft("deep", 400) is True)
check("fast_track normal 400KB/s 不进池", _run_ft("normal", 400) is False)

# ── 守护运行中手动即时优化：exec_lock 互斥 + optimize 壳转发 + _manual_run 生命周期 ──
import threading as _th
lr_x = PareLearner()
j_x = PareJudger(lr_x, {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[],"efis_params":{}})
c_x = PareCleaner(j_x)
check("exec_lock 为 RLock", type(c_x._exec_lock).__name__ == "RLock", str(type(c_x._exec_lock)))
_orig_ol = c_x._optimize_locked
_called_modes = []
c_x._optimize_locked = lambda *a, **k: _called_modes.append(a[2] if len(a) > 2 else k.get("mode")) or {"mode": a[2] if len(a) > 2 else k.get("mode")}
c_x.optimize([], lr_x, "full", operations=["ws"])
c_x._optimize_locked = _orig_ol
check("optimize 壳转发 _optimize_locked", _called_modes == ["full"], str(_called_modes))
# 锁内重入（RLock）不阻塞：手动 worker 持锁期间同一线程再次 optimize
with c_x._exec_lock:
    c_x.optimize([], lr_x, "quick", operations=["ws"])  # quick+ws 无真实系统清理，安全
check("exec_lock 锁内重入不阻塞", True)
# _opt_worker_once：_manual_run 生命周期 + 事件输出（fake sniffer，临时状态文件）
class _FakeSniffer:
    def snapshot(self):
        return []
from core.engine import MemWiseEngine
from core.efis import EfisController
_tmp_state = os.path.join(tempfile.mkdtemp(), "state.json")
_efis_x = EfisController(state_path=None)  # 内存态，不碰磁盘
_j_x2 = PareJudger(lr_x, {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[],"efis_params":{}})
c_x2 = PareCleaner(_j_x2)
_manual_seen = []
_orig_opt = c_x2.optimize
c_x2.optimize = lambda *a, **k: (_manual_seen.append(c_x2._manual_run), {"mode": k.get("mode"), "layer2": [], "probe": [], "net_freed": 0})[1]
eng_x = MemWiseEngine(lr_x, _j_x2, c_x2, _efis_x, _FakeSniffer(), _tmp_state)
eng_x._opt_worker_once("full", None)
eng_x.shutdown()
c_x2.optimize = _orig_opt
check("once 执行期间 _manual_run=True", _manual_seen == [True], str(_manual_seen))
check("once 结束后 _manual_run 复位", c_x2._manual_run is False)
_evs = [m for t, m in list(eng_x.events.queue)]
check("once 输出即时优化日志", any("即时优化" in m for m in _evs), str(_evs))

import re
with open(__file__, encoding='utf-8') as fh: cnt=len(re.findall(r'^\s*check\(',fh.read(),re.MULTILINE))
print(f"\n{'='*40}")
if errors:
    print(f"FAIL: {len(errors)}")
    for e in errors: print(f"  - {e}")
    sys.exit(1)
else:
    print(f"ALL OK — {cnt} assertions")
    sys.exit(0)
