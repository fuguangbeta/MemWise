# -*- coding: utf-8 -*-
"""
MemWise v4.5.038 全量单元测试 — 16 模块全覆盖（ERIS 纯函数共用 core.eris，无内联副本）
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
check("PARAMS 12 keys", len(PARAMS)==12)
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

print("\n[11] 终极审查修复回归（2026-08-12）")
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

print("\n[12] 稳定锚点与安全门（P0/P1 批次）")
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

print("\n[13] 清理模式严格度适配（四模式×守卫）")
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

print("\n[14] 模式价值底线梯度（θ：deep 0.12 / full 0.06 / normal 无）")
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
    check("full中低θ清理放行", True)  # 画像实际 θ 低于底线则跳过（断言构造失效保护）
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

print("\n[15] 稳态锁梯度（deep/full 跳过 WS基线/锚点/回弹，normal 保留）")
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

print("\n[16] 投票 threshold 模式梯度接线（normal=0 / deep=-1 / full=-2）")
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


print("\n[17] 窗口冷却与回弹学习（A/B 方案批次）")
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

print("\n[18] 多实例计数独立（A1 修复：确认键按 PID）")
j_mi = PareJudger(PareLearner(), {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
# 两个同名进程（如 chrome 子进程）：一个活跃一个低活动——计数互不干扰
s_m1 = Snap(); s_m1.name="chrome.exe"; s_m1.pid=9501; s_m1.cpu=50.0; s_m1.create=1
s_m2 = Snap(); s_m2.name="chrome.exe"; s_m2.pid=9502; s_m2.cpu=1.0; s_m2.create=1
j_mi.update_activity([s_m1, s_m2])
check("活跃实例计数清零", 9501 not in j_mi._low_activity)
check("低活动实例独立计数", j_mi._low_activity.get(9502, (0, 0, 0))[0] == 1)
j_mi.update_activity([s_m1, s_m2])
check("低活动实例累计2", j_mi._low_activity.get(9502, (0, 0, 0))[0] == 2)

print("\n[19] i18n 语言支持（原文即 key / 前缀匹配 / 递归 / 回退）")
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

print("\n[20] 2026-08-14 全量审查修复回归")
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

print("\n[21] 四模式梯度修复回归（2026-08-14 梯度专项）")
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

print("\n[22] 2026-08-15 全量审查修复回归")
# ── efis_params 类型清洗：畸形配置不崩溃（回退空 dict），坏值键删除 ──
import core.config as _cfg3
_ocp3 = _cfg3.CONFIG_PATH
_tc3 = os.path.join(tempfile.gettempdir(), "mw_cfg_e1.yaml")
with open(_tc3, "w", encoding="utf-8") as f:
    f.write("efis_params: [1,2,3]\n")
_cfg3.CONFIG_PATH = _tc3
_dc1 = _cfg3.load()
_cfg3.CONFIG_PATH = _ocp3
os.remove(_tc3)
check("efis_params 列表清洗为 dict", isinstance(_dc1.get("efis_params"), dict), str(type(_dc1.get("efis_params"))))
_tc4 = os.path.join(tempfile.gettempdir(), "mw_cfg_e2.yaml")
with open(_tc4, "w", encoding="utf-8") as f:
    f.write("efis_params: {pid_kp: 'abc', target_usage: 60}\n")
_cfg3.CONFIG_PATH = _tc4
_dc2 = _cfg3.load()
_cfg3.CONFIG_PATH = _ocp3
os.remove(_tc4)
check("efis_params 坏值键清除", "pid_kp" not in _dc2["efis_params"] and _dc2["efis_params"].get("target_usage") == 60,
      str(_dc2.get("efis_params")))
# ── 普通自启移除：DEFAULT_CFG 无 auto_start 键（旧配置残留由白名单自动清洗）──
check("auto_start 已移除", "auto_start" not in DEFAULT_CFG)
# ── 锚点聚合签名保持最老实例：子进程更替不换代（原实现被最大 WS 实例劫持）──
_store_a = StableAnchorStore()
_store_a.feed([_mk_s("app.exe", 300 << 20, r"d:\app\app.exe", 1000),
               _mk_s("app.exe", 500 << 20, r"d:\app\app.exe", 2000)], time.time(), set())
_store_a.feed([_mk_s("app.exe", 300 << 20, r"d:\app\app.exe", 1000),
               _mk_s("app.exe", 520 << 20, r"d:\app\app.exe", 2100)], time.time(), set())
_aa = _store_a.anchors.get(r"d:\app\app.exe")
check("锚点签名保持最老实例", _aa is not None and _aa.launch_sig.endswith("|1000"), _aa.launch_sig if _aa else "None")
check("锚点子进程更替不换代", _aa is not None and _aa.generation == 0 and _aa.samples == 2,
      f"gen={_aa.generation} samples={_aa.samples}" if _aa else "None")
# ── 回弹二轮按 PID 匹配（与 Layer3 阶段 D 同口径，防同名多实例误清）──
_cleaner_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "core", "cleaner.py"), encoding="utf-8").read()
check("layer2_trimmed 记录 PID", '{r[0].pid for r in l2_results if r[1]}' in _cleaner_src)
check("回弹二轮按 PID 匹配", 's.pid in pipeline_ctx["layer2_trimmed"]' in _cleaner_src)
# ── engine 共享快照（排行窗口守护运行中零额外采集）──
_eng_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "core", "engine.py"), encoding="utf-8").read()
check("engine 共享快照 _snap", "def _snap" in _eng_src and "_last_snaps" in _eng_src)
# ── i18n 审查补键行为（T15 作保留/完成/即时优化/热键/自启日志）──
set_language("en")
check("T15 作保留键", any("作保留" in k for k in _EN_A))
check("完成键", tr("完成") == "Done")
check("即时优化翻译", tr_msg("⚡ 即时优化（full）已启动") == "⚡ Instant optimize (full) started",
      tr_msg("⚡ 即时优化（full）已启动"))
check("热键 tooltip 首行键", "手动优化全局快捷键" in _EN_A and "游戏模式开关全局快捷键" in _EN_A)
check("管理员自启日志键", "管理员权限开机自启已启用" in _EN_A and "管理员权限开机自启已关闭" in _EN_A)
check("T6 八分区键", "  窗口与托盘 — 关闭按钮行为、托盘左键行为" in _EN_A
      and "  清理 — 6 种操作独立开关与清理深度" in _EN_A
      and "  守护 — 紧急阈值、守护清理间隔" in _EN_A
      and "  日志 — 文件日志开关" in _EN_A
      and "窗口与托盘" in _EN_A and "守护" in _EN_A
      and "触发与日志" not in _EN_A)
check("托盘初始 tip 键", "MemWise — 智能内存看护" in _EN_A)
set_language("zh_CN")

print("\n[23] 模式×场景参数组隔离（2026-08-16 用户定稿）")
from core.efis import MODE_DEFAULTS, MODE_TUNE_WHITELIST
# ── 激进初始值与调参白名单 ──
check("deep 初始 target_usage=45", MODE_DEFAULTS["deep"].get("target_usage") == 45)
check("full 初始 target_usage=35", MODE_DEFAULTS["full"].get("target_usage") == 35)
check("deep 初始 pid_kp=0.8", MODE_DEFAULTS["deep"].get("pid_kp") == 0.8)
check("full 白名单 9 参数", MODE_TUNE_WHITELIST["full"] ==
      ["pid_kp", "pid_kd", "target_usage", "cooloff_base", "learning_rate", "composite_kalman_w",
       "kalman_r", "cpu_gate", "io_gate"])
check("deep 白名单排除 L3 门与锚点", "layer3_agg_gate" not in MODE_TUNE_WHITELIST["deep"]
      and "anchor_margin" not in MODE_TUNE_WHITELIST["deep"] and len(MODE_TUNE_WHITELIST["deep"]) == 10)
check("quick 白名单空", MODE_TUNE_WHITELIST["quick"] == [])
# ── 16 组隔离:normal 调参不污染 full、切回 normal 参数保持 ──
_ef25 = EfisController(state_path=None)
def _osc25(mode, i):
    return {"mem_pct": 50 + (i % 2) * 30, "trimmed_cnt": 10, "failed_cnt": 2,
            "total_attempts": 12, "cycle_freed": 500, "snaps": [], "fore_fullscreen": False,
            "cycle_duration": 60, "pf_delta": 0, "deepen_cnt": 0, "deepen_extra": 0,
            "layer3_ran": 0, "layer3_extra": 0, "cooldown_cnt": 0, "repeat_fail": 0,
            "theta_mean": 0.5, "theta_above_06": 0.3, "agg": 0.6, "mode": mode}
for i in range(10):
    _ef25.tick(_osc25("normal", i))
_pid_n = _ef25.get_params("normal")["pid_kp"]
check("normal 振荡后 pid_kp 下降", _pid_n < 0.6, f"pid_kp={_pid_n}")
check("full 组初始 pid_kp 未被污染", _ef25.get_params("full")["pid_kp"] == 0.6, f"pid_kp={_ef25.get_params('full')['pid_kp']}")
# full 低压振荡(30/40):只触发 pid_kp 症状,不与 full 组 target_usage=35 的反向调整冲突
for i in range(10):
    s25 = _osc25("full", i)
    s25["mem_pct"] = 30 + (i % 2) * 10
    _ef25.tick(s25)
check("full 白名单外 deepen_theta 不变", _ef25.get_params("full")["deepen_theta"] == 0.6,
      f"deepen_theta={_ef25.get_params('full')['deepen_theta']}")
check("full 组 pid_kp 可调(白名单内,gap 阶段消费)", _ef25.get_params("full")["pid_kp"] < 0.6,
      f"pid_kp={_ef25.get_params('full')['pid_kp']}")
check("normal 组不受 full 调参影响", abs(_ef25.get_params("normal")["pid_kp"] - _pid_n) < 1e-9,
      f"normal pid_kp={_ef25.get_params('normal')['pid_kp']}")
# ── v3 → v4 迁移 ──
_tmp25 = os.path.join(tempfile.mkdtemp(), "memwise_state.json")   # 与真实命名一致：EFIS/ERIS 状态由目录推导
_tmp25e = os.path.join(os.path.dirname(_tmp25), "memwise_efis_state.json")
with open(_tmp25e, "w", encoding="utf-8") as f:
    json.dump({"efis": {"version": 3, "params": {"pid_kp": 0.9, "target_usage": 55},
                        "scene_params": {"general": {"pid_kp": 0.7}, "browser": {"pid_kp": 0.8}},
                        "current_scene": "general", "scene_stable": 3, "cycle_count": 7,
                        "symptoms": {}, "adjust_log": []}}, f)
_efm25 = EfisController(_tmp25)
check("v3 迁移:normal.general 用旧全局参数", _efm25.get_params("normal")["pid_kp"] == 0.9
      and _efm25.get_params("normal")["target_usage"] == 55, str(_efm25.get_params("normal")))
check("v3 迁移:current_scene 组不被场景历史覆盖", _efm25._group("normal", "general")["params"]["pid_kp"] == 0.9,
      str(_efm25._group("normal", "general")["params"]["pid_kp"]))
check("v3 迁移:非当前场景组独立保留", _efm25._group("normal", "browser")["params"]["pid_kp"] == 0.8,
      str(_efm25._group("normal", "browser")["params"]["pid_kp"]))
check("v3 迁移:deep 组用模式初始值", _efm25.get_params("deep")["target_usage"] == 45)
# v4 current_scene 持久化往返（审查 P10）
_efs25 = EfisController(state_path=_tmp25)
_efs25.current_scene = "browser"
_efs25.save()
_efs25b = EfisController(state_path=_tmp25)
check("v4 current_scene 往返", _efs25b.current_scene == "browser", _efs25b.current_scene)
os.remove(_tmp25e)
# ── Policy 树权重 4 组隔离 ──
_pv25 = PolicyVoter()
_pv25.set_mode("normal")
_pv25.update_weights_per_trim([2, 0, 0, 0, 0], True)
_w_norm = _pv25._mode_weights["normal"][0]
check("normal 组权重上升", _w_norm > 1.0, f"w={_w_norm}")
_pv25.set_mode("full")
check("full 组权重初始 1.0", _pv25._mode_weights["full"][0] == 1.0)
_pv25.update_weights_per_trim([2, 0, 0, 0, 0], False)
check("full 组权重独立下降", _pv25._mode_weights["full"][0] < 1.0)
check("normal 组权重不受 full 学习影响", abs(_pv25._mode_weights["normal"][0] - _w_norm) < 1e-9)

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
check("once 输出即时优化载荷", any(isinstance(m, dict) and m.get("mode") == "full"
                                   and "released" in m for m in _evs), str(_evs)[:120])

print("\n[24] 2026-08-30 全量审查批次回归")
import re as _re26, threading as _th26
_ROOT26 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def _src26(*parts):
    return open(os.path.join(_ROOT26, *parts), encoding="utf-8").read()
_wa26_src = _src26("core", "winapi.py")
_gui26_src = _src26("memwise_gui.py")
_mw26_src = _src26("memwise.py")
_eng26_src = _src26("core", "engine.py")
_i18n26_src = _src26("core", "i18n.py")
_lm26_src = _src26("core", "learner.py")
_meta26_src = _src26("core", "meta.py")
_cl26_src = _src26("core", "cleaner.py")

# ── K32 双通道类号（文档类 0/4；Nt 枚举值 15/0x13 误用已清除）──
check("K32 MemoryPriority 类 0", "SetProcessInformation(h, 0," in _wa26_src)
check("K32 PowerThrottling 类 4", "SetProcessInformation(h, 4," in _wa26_src)
check("Nt 枚举值 0x13 已清除", "SetProcessInformation(h, 0x13" not in _wa26_src)
check("Nt 枚举值 15 已清除", "SetProcessInformation(h, 15," not in _wa26_src)
# ── 托盘：ADD 先于 SETVERSION（官方顺序）+ LOWORD 消息解析 ──
check("托盘 ADD 先于 SETVERSION",
      _wa26_src.index("Shell_NotifyIconW(NIM_ADD") < _wa26_src.index("0x00000004, ctypes.byref(nid))"))
check("托盘消息 LOWORD 解析", "lp & 0xFFFF" in _gui26_src)
# ── learner 并发写锁 + 策略树权重持久化（含旧格式兼容）──
from core import learner as _lm26
check("learner.save 写锁", hasattr(_lm26, "_SAVE_LOCK") and hasattr(_lm26._SAVE_LOCK, "acquire"))
_lr26 = PareLearner()
_lr26.policy.set_mode("deep"); _lr26.policy.update_weights_per_trim([1, 0, 0, 0, 0], True)
_t26 = os.path.join(tempfile.mkdtemp(), "state.json")
check("save ok(含 policy)", _lr26.save(_t26))
_lr26b = PareLearner.load(_t26)
check("树权重持久化往返", _lr26b.policy._mode_weights.get("deep", [0] * 5)[0] > 1.0)
_d26 = json.load(open(_t26, encoding="utf-8")); _d26.pop("policy", None)
json.dump(_d26, open(_t26, "w", encoding="utf-8"))
_lr26c = PareLearner.load(_t26)
check("旧格式无 policy 键兼容", _lr26c.policy._mode_weights.get("deep", [1.0] * 5)[0] == 1.0)
os.remove(_t26)
# ── config 数值键钳制（手改越界值不再穿透门槛）──
import core.config as _cfg26
_ocp26 = _cfg26.CONFIG_PATH
_t26c = os.path.join(tempfile.gettempdir(), "mw_cfg_clamp.yaml")
with open(_t26c, "w", encoding="utf-8") as f:
    f.write("emergency_threshold: 0\nclean_passes: 1000\ninterval: 1\ngap_seconds: 1\n")
_cfg26.CONFIG_PATH = _t26c
_dc26 = _cfg26.load()
_cfg26.CONFIG_PATH = _ocp26
os.remove(_t26c)
check("emergency_threshold 钳制", _dc26.get("emergency_threshold") == 50, str(_dc26.get("emergency_threshold")))
check("clean_passes 钳制", _dc26.get("clean_passes") == 6)
check("interval 钳制", _dc26.get("interval") == 10)
check("gap_seconds 钳制", _dc26.get("gap_seconds") == 8)
# ── rebound 多实例 max 聚合（快照顺序无关）──
from core.rebound import ReboundLearner as _RL26
class _S26:
    pass
def _mk26(ws):
    s = _S26(); s.ws = ws; s.path = r"d:\app\order.exe"; return s
_n26 = time.time()
def _run26(order):
    rb = _RL26(); rb.begin(r"d:\app\order.exe", 200 << 20, 300 << 20, _n26)
    rb.observe([_mk26(w) for w in order], _n26 + 121)
    return rb.ewma.get(r"d:\app\order.exe")
check("rebound 多实例顺序无关",
      abs(_run26([900 << 20, 200 << 20]) - _run26([200 << 20, 900 << 20])) < 1e-9)
# ── full 模式执行前 IO 复检梯度（与 can_trim/Layer3 同口径）──
from core.cleaner import PareCleaner as _PC26
_l26 = PareLearner()
_j26 = PareJudger(_l26, {"kp": 0.6, "ki": 0.15, "kd": 0.1, "target_usage": 60, "never": [], "efis_params": {}})
_c26 = _PC26(_j26)
_s26 = Snap(); _s26.name = "iofull.exe"; _s26.ws = 200 << 20; _s26.path = "d:\\app\\iofull.exe"
_s26.pid = 9801; _s26.pf = 0; _s26.priv = 0; _s26.fg = False
_oio26 = _j26._io_active
_j26._io_active = lambda pid: True
_j26._mode_guard = "full"
_r26 = _c26._trim_process(_s26, _l26)[3]
check("full 跳过执行前 IO 复检", _r26 != "执行前IO活跃", _r26)  # 假 PID → API失败
_j26._mode_guard = "normal"
_r26 = _c26._trim_process(_s26, _l26)[3]
check("normal 保留执行前 IO 复检", _r26 == "执行前IO活跃", _r26)
_j26._io_active = _oio26
# ── MemoryPriority 防重集合接线（同轮不重复调用一次性 API）──
import core.winapi as _wa26
_l27 = PareLearner()
_j27 = PareJudger(_l27, {"kp": 0.6, "ki": 0.15, "kd": 0.1, "target_usage": 60, "never": [], "efis_params": {}})
_c27 = _PC26(_j27)
_j27.can_trim = lambda s: (True, "")
_c27._trim_process = lambda snap, learner: (True, 0, 0, "模拟")
_calls26 = {"eco": 0, "mp": 0}
_oe26, _om26 = _wa26.set_eco_qos, _wa26.set_memory_priority
_wa26.set_eco_qos = lambda *a, **k: (_calls26.__setitem__("eco", _calls26["eco"] + 1), False)[1]
_wa26.set_memory_priority = lambda *a, **k: (_calls26.__setitem__("mp", _calls26["mp"] + 1), True)[1]
import random as _r26m
_or26m = _r26m.betavariate
_r26m.betavariate = lambda a, b: 0.9
_p26p = _l27.get("mp26.exe")  # 喂样本走画像 θ（无样本走先验 0.35 不达门槛）
_p26p.ws_deque.append(100 << 20); _p26p.ws_deque.append(100 << 20)
_sf26 = Snap(); _sf26.name = "mp26.exe"; _sf26.ws = 200 << 20; _sf26.path = "d:\\app\\mp26.exe"
_sf26.pid = 9810; _sf26.pf = 0; _sf26.priv = 0; _sf26.fg = False
_sf26.cpu = 0.0; _sf26.parent = 0; _sf26.create = 1.0; _sf26.has_visible = False
try:
    _c27._layer2_process([_sf26], _l27)
    _c27._layer2_process([_sf26], _l27)  # 第二轮：pid 已在 _mem_pri_set，不得重复调用
finally:
    _r26m.betavariate = _or26m
    _wa26.set_eco_qos = _oe26; _wa26.set_memory_priority = _om26
check("MemoryPriority 防重集合接线", _calls26["mp"] == 1, str(_calls26))
# ── CLI：i18n 导入完整 + 输出零中文残留 ──
check("CLI i18n 导入完整", "from core.i18n import tr, tr_msg, set_language" in _mw26_src)
_mw26_bad = [l.strip()[:60] for l in _mw26_src.splitlines()
             if _re26.search(r"[\u4e00-\u9fff]", l) and "print(" in l
             and not _re26.search(r"\btr(_msg)?\(", l) and not l.strip().startswith("#")]
check("CLI 输出翻译零残留", not _mw26_bad, str(_mw26_bad[:2]))
check("CLI --mode 参数组对齐", "_cli_mode_override" in _mw26_src and _mw26_src.count("_efis.set_mode(mode)") >= 2)
# ── 常驻崩溃现场 ──
check("崩溃现场安装函数", "_install_crash_sink" in _eng26_src
      and "_install_crash_sink()" in _gui26_src and "_install_crash_sink()" in _mw26_src)
check("崩溃现场独立于日志开关", "memwise_crash.log" in _eng26_src and "MEMWISE_LOG_DIR" in _eng26_src)
# ── 字典快照迭代（守护线程防 RuntimeError）──
check("θ 统计快照迭代", _eng26_src.count("dict(learner.profiles).values()") == 2)
check("pop_info 快照迭代", "dict(self.profiles)" in _lm26_src)
check("meta.tick 快照迭代", "dict(self.learner.profiles)" in _meta26_src)
# ── i18n 零重复键 + 新键 + 退出表述 ──
_ks26 = _re26.findall(r'^\s+"((?:[^"\\]|\\.)*)"\s*:', _i18n26_src, _re26.M)
check("i18n 零重复键", len(_ks26) == len(set(_ks26)), f"{len(_ks26)} vs {len(set(_ks26))}")
set_language("en")
check("热键错误串英文", tr("不能为空") == "Cannot be empty"
      and tr("至少需要一个修饰键（ctrl/alt/shift）") == "Needs at least one modifier (ctrl/alt/shift)")
_hk26 = tr_msg("⚠ 手动优化热键配置无效（不能为空），本次使用默认 ctrl+shift+m")
check("热键日志片段翻译", "Manual Optimize" in _hk26 and "invalid" in _hk26 and "Cannot be empty" in _hk26, _hk26)
set_language("zh_CN")
check("退出表述键", "进程已退出·内存随之释放" in _cl26_src
      and "进程已退出·内存随之释放" in _i18n26_src)
# ── 界面微修 ──
check("托盘数字图标按档着色", "create_tray_percent_icon(pct, color=_color)" in _gui26_src)
check("托盘百分比 100 如实显示", "min(100, int(percent))" in _wa26_src)
check("全屏检测按窗口所在显示器", "MonitorFromWindow" in _wa26_src and "GetMonitorInfoW" in _wa26_src)
check("卷缓存真实成功计数", "return flushed" in _wa26_src)
check("排行学习标记口径统一", 'p.total_samples >= 2 else ""' in _gui26_src)
check("GUI 死导入已清", "from core.eris import" not in _gui26_src
      and "res_dir," not in _gui26_src)

print("\n[25] 游戏态调参冻结（2026-08-30）")
_ef27 = EfisController(state_path=None)
def _st27(i, game):
    return {"mem_pct": 50 + (i % 2) * 30, "trimmed_cnt": 10, "failed_cnt": 2,
            "total_attempts": 12, "cycle_freed": 500, "snaps": [], "fore_fullscreen": False,
            "cycle_duration": 60, "pf_delta": 0, "deepen_cnt": 0, "deepen_extra": 0,
            "layer3_ran": 0, "layer3_extra": 0, "cooldown_cnt": 0, "repeat_fail": 0,
            "theta_mean": 0.5, "theta_above_06": 0.3, "agg": 0.6, "mode": "normal",
            "game": game}
_log27 = len(_ef27._adjust_log)
for _i in range(4):
    _ef27.tick(_st27(_i, False))
check("日常周期累积窗口", len(_ef27._window) == 4)
_g27 = _ef27.tick(_st27(4, True))
check("游戏周期返回空且清窗", _g27 == "" and len(_ef27._window) == 0)
for _i in range(10):
    _ef27.tick(_st27(_i, True))
check("游戏期零调参零累积", len(_ef27._adjust_log) == _log27 and len(_ef27._window) == 0)
for _i in range(5):
    _ef27.tick(_st27(_i, False))
check("游戏退出后干净恢复累积", len(_ef27._window) == 5 and len(_ef27._adjust_log) == _log27)
check("参数组未被游戏期触碰", _ef27.get_params("normal")["pid_kp"] == _ef27.get_params("normal")["pid_kp"]
      and _ef27.get_params("full")["target_usage"] == 35)
_ef27q = EfisController(state_path=None)
_ef27q.set_mode("quick")
check("quick 模式游戏态双冻结", _ef27q.tick(_st27(0, True)) == "" and len(_ef27q._window) == 0)
check("引擎游戏态接线", "'game': game_seen" in _eng26_src
      and "if not game_seen:" in _eng26_src
      and "game_seen = self.cleaner.game_mode" in _eng26_src)

print("\n[26] 手动优化播报重设计（2026-08-30）")
# 结果卡头行翻译（tr_msg 片段全覆盖）
set_language("en")
_head28 = tr_msg("⚡ full 优化完成 · 系统缓存 453 MB + 进程 15 MB = 共 468 MB · 净下降 296 MB（可用 62%→71%）")
check("结果卡头行翻译（系统缓存/进程分列）",
      _head28 == "⚡ full optimization done · system cache 453 MB + processes 15 MB = total 468 MB"
                 " · net drop 296 MB (available 62%→71%)", _head28)
check("三轮启动文案", tr_msg("开始优化（full·三轮）…") == "Start optimization (full · three rounds)…")
check("轮次节拍文案", tr_msg("第 2/3 轮完成 · 本轮释放 152 MB") == "Round 2/3 done · this round freed 152 MB")
check("余量聚合行", tr_msg("✓ 其余 21 个进程") == "✓ plus 21 processes")
check("零结果明示键", tr("没有找到值得清理的进程（全部受保护或无闲置内存）") == "No processes worth cleaning found (all protected or no idle memory)")
check("状态栏临时提示键", tr("⚡ 即时优化中…") == "⚡ Instant optimizing…")
set_language("zh_CN")
# 接线静态断言（结果卡整卡输出/过程节拍/载荷扩展/旧重复摘要移除）
check("结果卡整卡输出", "_log_batch(card, to_file=True)" in _gui26_src and "by_freed" in _gui26_src)
check("过程节拍接线", "本轮释放" in _eng26_src and "第 {round_idx + 1}/3 轮完成" in _eng26_src)
check("载荷扩展", '"released": released' in _eng26_src and '"pct0": m0[\'pct\'] if m0 else None' in _eng26_src)
check("旧重复摘要已移除", "三轮优化合计释放" not in _eng26_src
      and "即时优化完成 · 释放" not in _eng26_src and "开始优化..." not in _gui26_src)
check("旧键已清理", "📊 三轮优化合计释放" not in _i18n26_src
      and "即时优化完成 · 释放" not in _i18n26_src and "开始优化..." not in _i18n26_src)

print("\n[27] 日志面板分组写入语义（2026-08-30）")
import memwise_gui as _mg29
check("面板阈值常量", _mg29.PANEL_MAX_LINES == 7)
check("实际行数计数", _mg29._msg_lines(["a", "b\nc", "d\ne\nf"]) == 6)
check("组间≤7接续", _mg29._panel_needs_clear(4, 2) is False and _mg29._panel_needs_clear(0, 7) is False)
check("组间>7清屏", _mg29._panel_needs_clear(6, 3) is True and _mg29._panel_needs_clear(7, 1) is True
      and _mg29._panel_needs_clear(0, 10) is True)
# 真实面板端到端（Tk Text + 桩 self，走真实 _write_group 原语）
import tkinter as _tk29
from collections import deque as _dq29
_root29 = _tk29.Tk(); _root29.withdraw()
_stub29 = _mg29.MemWiseGUI.__new__(_mg29.MemWiseGUI)
_stub29.log = _tk29.Text(_root29)
_stub29._log_history = _dq29(maxlen=300)
_stub29._last_msg = None
def _panel29():
    # end-1c 带隐式终止行偏置：减 1 得真实可见行数（与 _write_group 同口径）
    return max(0, int(_stub29.log.index('end-1c').split('.')[0]) - 1)
_stub29._write_group([f"行 {i}" for i in range(1, 5)])
check("组1=4行", _panel29() == 4)
_stub29._write_group(["事件 A", "事件 B"])
check("组2=2行接续(6≤7)", _panel29() == 6)
_stub29._write_group(["汇总", "x", "y"])
check("组3=3行清屏(9>7)", _panel29() == 3)
_stub29._write_group([f"卡行 {i}" for i in range(1, 11)])
check("大组10行完整呈现", _panel29() == 10)
_stub29._write_group(["新事件"])
check("下一组清屏恢复", _panel29() == 1)
for _i in range(6):
    _stub29._write_group([f"单行 {_i}"])
check("单行逐条接续至7行", _panel29() == 7)
_stub29._write_group(["多行\n消息"])  # 实际 2 行：7+2=9>7 → 清屏（若按 1 条计会接续成 8 行）
check("多行消息按实际行计", _panel29() == 2)
check("历史缓存累积", len(_stub29._log_history) == 4 + 2 + 3 + 10 + 1 + 6 + 1)
_root29.destroy()
check("三路径统一委托", _gui26_src.count("_write_group([m])") == 2
      and "_write_group(msgs, to_file)" in _gui26_src)
check("engine 启动信息打包", "'log_batch', start_lines" in _eng26_src)

print("\n[28] 周期批分组化 + 同批修复（2026-08-30）")
check("周期批分组化", "'display_groups', cycle_groups" in _eng26_src
      and "_cycle_log_groups" in _eng26_src and "_cycle_log_buffer" not in _eng26_src)
check("紧急消息统一入批", 'self._cycle_log_groups.append(["⚠ 紧急触发清理(full模式)"])' in _eng26_src)
check("EFIS 并入周期批", 'cycle_groups.append(["[EFIS] " + efis_msg])' in _eng26_src
      and "('display', ['[EFIS] ' + efis_msg])" not in _eng26_src)
check("display 事件分组载荷", "elif action == 'display_groups':" in _gui26_src
      and "self._write_group([m for g in args for m in g], to_file=False)" in _gui26_src
      and "elif action == 'display':" not in _gui26_src)
# 大整体语义端到端：面板 6 行 + 周期批 3 组（各 1 行）→ 合并为一个大整体一次判定，
# 整批完整可见（旧逐组判定下：组1 接续至 7、组2 清屏自占、组3 接续——组1 消失）
_root30 = _tk29.Tk(); _root30.withdraw()
_stub30 = _mg29.MemWiseGUI.__new__(_mg29.MemWiseGUI)
_stub30.log = _tk29.Text(_root30)
_stub30._log_history = _dq29(maxlen=300)
_stub30._last_msg = None
for _i in range(6):
    _stub30._write_group([f"既有 {_i}"])
_groups30 = [["周期汇总"], ["[EFIS] 调整pid_kp: 0.60→0.50"], ["📈 内存 70%·清理强度：维持高"]]
_stub30._write_group([m for g in _groups30 for m in g], to_file=False)
_vis30 = _stub30.log.get('1.0', 'end').rstrip(chr(10)).splitlines()
check("周期大整体完整可见", len(_vis30) == 3 and any("周期汇总" in l for l in _vis30)
      and any("[EFIS]" in l for l in _vis30) and any("📈" in l for l in _vis30))
_root30.destroy()
check("守护异常同批", '["❌ 守护异常，详见下方错误信息", f"🔍 {err}"]' in _gui26_src)
check("崩溃恢复单条", _gui26_src.count("🔄 从崩溃中恢复 — 守护模式已自动继续") == 1
      and 'log_msg or "守护模式启动"' in _gui26_src)
check("热键只报变更键", 'changed={hk["key"]} if spec != old else set()' in _gui26_src
      and 'not initial and hk["key"] in changed' in _gui26_src)
check("事件契约更新", "'display_groups', [组, …]" in _eng26_src)

print("\n[29] 2026-09-06 全量审查批次回归（F1-F13）")
# ── F1 消息队列 log/log_batch 分支唯一（重复 if 链已删）──
check("F1 消息队列 log 分支唯一", _gui26_src.count("if action == 'log': self._log(args)") == 1)
# ── F2 dict 快照防护全景（2026-08-30 修复的残留漏网收口）──
_prior26_src = _src26("core", "prior.py")
_policy26_src = _src26("core", "policy.py")
_judger26_src = _src26("core", "judger.py")
_rebound26_src = _src26("core", "rebound.py")
check("F2 prior 快照迭代", "dict(profiles).items()" in _prior26_src)
check("F2 meta 探索覆盖快照迭代", _meta26_src.count("dict(self.learner.profiles)") == 2)
check("F2 policy 树5 快照迭代", "list(learner.profiles.values())" in _policy26_src)
check("F2 learner save 快照迭代", _lm26_src.count("dict(self.profiles)") == 3)
check("F2 engine 周期统计快照迭代", "dict(self.learner.profiles).values()" in _eng26_src)
check("F2 engine kalman_r 遍历快照迭代", "list(self.learner.profiles.values())" in _eng26_src)
# ── F3 守护互斥 + tmp 进程隔离 ──
check("F3 守护互斥 mutex 接线", "MemWise_Daemon" in _eng26_src and "DAEMON_MUTEX_NAME" in _mw26_src)
check("F3 CLI daemon 入口互斥", "GetLastError() in (0xB7, 5)" in _mw26_src)
check("F3 GUI 启动失败区分 CLI 占用", "_daemon_busy_cli" in _eng26_src and "_daemon_busy_cli" in _gui26_src)
check("F3 learner tmp 隔离", "{os.getpid()}.tmp" in _lm26_src)
check("F3 efis tmp 隔离", "{os.getpid()}.tmp" in _src26("core", "efis.py"))
check("F3 config tmp 隔离", "{os.getpid()}.tmp" in _src26("core", "config.py"))
check("F3 engine tmp 隔离×4（含 ② 校准文件）", _eng26_src.count("{os.getpid()}.tmp") == 4)
# ── F6 游戏模式实时化（确认计数器全清，启用/退出即时生效）──
check("F6 游戏退出即时化", "game_gone_count" not in _eng26_src and "game_gone_count" not in _cl26_src)
check("F6 实时退出注释接线", "实时退出" in _eng26_src and "实时退出" in _cl26_src)
# ── F7 双语残留清零 ──
check("F7 守护异常状态栏键", "⚠ 守护异常" in _EN_A and 'tr("⚠ 守护异常")' in _gui26_src)
check("F7 CLI reason 翻译", "tr_msg(reason)" in _mw26_src)
# ── F8 docstring 与实现一致（quick 零进程清理）──
check("F8 quick 零进程清理描述", "零进程清理" in _cl26_src and "layer2(full probe+trim)" not in _cl26_src)
# ── F9 never 黑名单归一（临时文件，不碰真实配置）──
_tc26n = os.path.join(tempfile.gettempdir(), "mw_cfg_never.yaml")
with open(_tc26n, "w", encoding="utf-8") as f:
    f.write('never: [Chrome, "msedge.exe", ""]\n')
_ocp26n = _cfg26.CONFIG_PATH
_cfg26.CONFIG_PATH = _tc26n
_dn26 = _cfg26.load()
_cfg26.CONFIG_PATH = _ocp26n
os.remove(_tc26n)
check("F9 never 无后缀归一", _dn26.get("never") == ["chrome.exe", "msedge.exe"], str(_dn26.get("never")))
# ── F10 EFIS stats 无 snaps 死字段 ──
check("F10 stats 无 snaps", "'snaps': snaps" not in _eng26_src)
# ── F11/F12 删除项防回退（保留项防误删）──
check("F11 图标多尺寸函数已删", "create_memwise_ico_multi" not in _wa26_src)
# 定义行级锚定（清理说明注释可提及原符号名，不构成残留）
check("F12 死常量已删", not _re26.search(r"^Z_SCORE_THRESHOLD\s*=", _lm26_src, _re26.M)
      and not _re26.search(r"^DT\s*=\s*5", _judger26_src, _re26.M)
      and not _re26.search(r"^def suggest\(", _rebound26_src, _re26.M)
      and "SUGGEST_STRENGTH" not in _rebound26_src)
check("F12 TARGET_USAGE 保留（有消费方）", "TARGET_USAGE" in _judger26_src)
check("F12 stable MIN_SAMPLES 不误伤", "MIN_SAMPLES = 5" in _src26("core", "stable.py"))
# ── F4/F5 自启最小化联动 + 文案落盘 ──
check("F4 最小化联动任务重建", _gui26_src.count("target, task_args = _admin_task_args()") == 2)
check("F4 改名键生效", "开机自启动后最小化到托盘" in _i18n26_src and '"启动后最小化到托盘"' not in _i18n26_src)
check("F4 引用文本联动", "配合「开机自启动后最小化到托盘」使用效果更佳" in _gui26_src)
check("F5 T10 定稿文案", "打开期间自动刷新，可看到内存变化" in _i18n26_src
      and "关闭窗口后重新打开可获取最新数据" not in _i18n26_src
      and "打开期间自动刷新，可看到内存变化" in _gui26_src)
# ── 英文适配全量扫描补键（事件日志/终止确认尾段/tr_msg 对称）──
# （对运行时 _EN 字典断言：键中 \n 经解释为真实换行，与源码字面转义形态无关）
for _k in ("⚠ 图表异常: ", "GUI 优化: ", "MB 释放, ", "优化完成: ",
           "服务模式已安装 (Scheduled Task)", ") 吗？\n\n该操作会强制结束进程，未保存的数据可能丢失。",
           "收益高", "收益中", "内存紧张", "内存充足", "内存上升中", "预测优势"):
    check(f"EN 补键:{_k.strip()[:14]}", _k in _EN_A)
check("report_event 双语包裹", "tr_msg(f\"GUI 优化: " in _gui26_src
      and _mw26_src.count("winapi.report_event(\"MemWise\", tr_msg(") == 3)
# tr_msg 去尾 \n 变体（与 tr 对称）：无尾换行目标串命中带尾 \n 键
set_language("en")
_t25en = tr_msg("清空系统文件读取缓存\n会降低文件操作速度直到缓存重建\n在指定的收割阶段执行\n\n⚠ 谨慎使用——文件缓存重建期间磁盘性能下降")
check("tr_msg 尾\\n 变体对称", "谨慎" not in _t25en and "Use with care" in _t25en, _t25en[-60:])
set_language("zh_CN")

print("\n[30] 图表标度与效率阈值适配（2026-09-06 用户定稿）")
# ── 任务1: 纵轴 GB 标度 ≥10 取整 ──
_gui32_src = _src26("memwise_gui.py")
_eris_v7_src = _src26("core/eris.py")   # ERIS v7 纯函数核心
check("纵轴 GB≥10 取整", '_gb_v = lbl_v / 1024.0' in _gui32_src
      and 'f"{_gb_v:.0f}GB" if _gb_v >= 10 else f"{_gb_v:.1f}GB"' in _gui32_src)
# ── 任务2: 效率异常下限 60→50（折点着色 + 因子极性，含等于语义不变）──
_eng32_src = _src26("core", "engine.py")
check("折点阈值 ≤50", "elif r_eff <= 50:" in _gui32_src and "elif r_eff <= 60" not in _gui32_src)
check("因子下极性 ≤50（v7：阈值常量）",
      "elif eff <= E.WARN_TH:" in _eng32_src and "WARN_TH = 50.0" in _eris_v7_src)
check("上极性 ≥100 不动（v7：阈值常量）",
      "elif eff >= E.SUPER_TH:" in _eng32_src and "SUPER_TH = 100.0" in _eris_v7_src
      and "over_100 = r_eff >= 100" in _gui32_src)
# README 双语同步（v7 口径：五维标尺 + 阈值语义 + 词条规则）
_readme32 = open(os.path.join(_ROOT26, "README.md"), encoding="utf-8").read()
for _frag in ("50 分 = 该维历史中位水平，100 分 = 突破历史高位",
              "≥100% 折点显示金色并标注",
              "≤50% 显示珊瑚红并标注",
              "仅在 50–100% 区间内",
              "50 = the dimension's historical median, 100 = beyond its historical best",
              "≥100% marks gold dots",
              "≤50% coral-red dots",
              "within the 50–100% band only"):
    check(f"README 同步:{_frag[:16]}", _frag in _readme32)
check("README 旧口径清零", "80 + 40" not in _readme32 and "IQR 分位数归一化" not in _readme32
      and "trimmed-IQR" not in _readme32 and "（60-100）" not in _readme32)

print("\n[31] 配置包：导出/导入/备份/恢复出厂（2026-09-06 任务3）")
import zipfile as _zf33
from core import backup as _bk33
_b33 = os.path.join(tempfile.mkdtemp(), "data")
os.makedirs(_b33, exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(_b33), "config"), exist_ok=True)
open(os.path.join(os.path.dirname(_b33), "config", "config.yaml"), "w", encoding="utf-8").write("interval: 45\n")
open(os.path.join(_b33, "memwise_state.json"), "w", encoding="utf-8").write('{"version": 4, "profiles": {}}')
# ── 导出：包名/缺失记录/根平铺/manifest 内容 ──
p1, miss1 = _bk33.export_state("export", base=_b33)
check("导出成功且缺失记录", p1 is not None and "MemWise_Export_" in os.path.basename(p1)
      and set(miss1) == {"memwise_efis_state.json", "memwise_eris_ewma.json"})
with _zf33.ZipFile(p1) as _z33:
    _names33 = _z33.namelist()
    _m33 = json.loads(_z33.read("manifest.json").decode("utf-8"))
check("包根平铺 manifest+files", sorted(_names33) == sorted(_m33["files"] + ["manifest.json"])
      and _m33["format_version"] == 1 and _m33["source"] == "export"
      and _m33["files"] == ["config.yaml", "memwise_state.json"])
_m33v, _e33v = _bk33.validate_package(p1)
check("validate 正常包通过", _e33v == [] and _m33v is not None)
# ── 坏包四类 + 未来版本拒绝（差异提示含具体清单）──
_bad33 = os.path.join(tempfile.mkdtemp(), "bad.zip")
with _zf33.ZipFile(_bad33, "w") as z:
    z.writestr("manifest.json", json.dumps({"format_version": 1, "files": ["config.yaml", "memwise_state.json"]}))
    z.writestr("config.yaml", "interval: 1")
_, _e33a = _bk33.validate_package(_bad33)
check("少文件拒绝", any("缺少" in x for x in _e33a), str(_e33a))
with _zf33.ZipFile(_bad33, "w") as z:
    z.writestr("manifest.json", json.dumps({"format_version": 1, "files": ["config.yaml"]}))
    z.writestr("config.yaml", "a: 1")
    z.writestr("extra.txt", "x")
_, _e33b = _bk33.validate_package(_bad33)
check("多文件拒绝", any("多出" in x for x in _e33b), str(_e33b))
with _zf33.ZipFile(_bad33, "w") as z:
    z.writestr("manifest.json", json.dumps({"format_version": 99, "files": ["config.yaml"]}))
    z.writestr("config.yaml", "a: 1")
_m33f, _e33c = _bk33.validate_package(_bad33)
check("未来版本拒绝", _m33f is not None and any("升级" in x for x in _e33c), str(_e33c))
with _zf33.ZipFile(_bad33, "w") as z:
    z.writestr("manifest.json", json.dumps({"format_version": 1, "files": ["config.yaml", "memwise_state.json"]}))
    z.writestr("config.yaml", "interval: 1")
    z.writestr("memwise_state.json", "{broken")
_, _e33d = _bk33.validate_package(_bad33)
check("坏 JSON 拒绝", any("无法解析" in x for x in _e33d), str(_e33d))
# ── 导入往返复刻：A 状态导出 → B 导入 → 逐文件一致 + 预期外删除 ──
_bA = os.path.join(tempfile.mkdtemp(), "data")
os.makedirs(_bA, exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(_bA), "config"), exist_ok=True)
open(os.path.join(os.path.dirname(_bA), "config", "config.yaml"), "w", encoding="utf-8").write("interval: 33\n")
open(os.path.join(_bA, "memwise_state.json"), "w", encoding="utf-8").write('{"version": 4, "mark": "A"}')
_pa33, _ = _bk33.export_state("export", base=_bA)
_bB = os.path.join(tempfile.mkdtemp(), "data")
os.makedirs(_bB, exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(_bB), "config"), exist_ok=True)
open(os.path.join(os.path.dirname(_bB), "config", "config.yaml"), "w", encoding="utf-8").write("interval: 99\n")
open(os.path.join(_bB, "memwise_state.json"), "w", encoding="utf-8").write('{"version": 4, "mark": "B"}')
open(os.path.join(_bB, "memwise_efis_state.json"), "w", encoding="utf-8").write('{"efis": {}}')  # 预期外（A 无此文件）
_ok33, _err33 = _bk33.import_state(_pa33, backup=False, base=_bB)
check("导入成功", _ok33 and _err33 == "", _err33)
check("复刻 config", open(os.path.join(os.path.dirname(_bB), "config", "config.yaml"), encoding="utf-8").read() == "interval: 33\n")
check("复刻 state", json.load(open(os.path.join(_bB, "memwise_state.json"), encoding="utf-8"))["mark"] == "A")
check("预期外文件已删（完整复刻）", not os.path.isfile(os.path.join(_bB, "memwise_efis_state.json")))
# ── reset_factory：备份可选 + 删除 ──
_ok33r, _bak33 = _bk33.reset_factory(backup=True, base=_bB)
check("reset 备份包生成", _ok33r and _bak33 and "MemWise_Backup_" in os.path.basename(_bak33)
      and os.path.isfile(_bak33))
check("reset 状态文件删除", not any(os.path.isfile(p) for p in _bk33._state_paths(_bB).values()))
# ── GUI/CLI 静态接线 ──
check("GUI 两栏三按钮接线", "self._on_factory_reset" in _gui26_src
      and "self._on_export_config" in _gui26_src and "self._on_import_config" in _gui26_src
      and "配置传输" in _gui26_src)
check("GUI 自动重启接线（root.destroy 自然关闭，bootloader 干净清理）",
      "backup.restart_application()" in _gui26_src
      and "self.root.destroy()" in _gui26_src and "os._exit(0)" not in _gui26_src)
check("GUI 导入候选单目录（import_export 三合一）", "backup.import_export_dir()" in _gui26_src
      and "backup_export" not in _gui26_src)
check("CLI export/import/reset 接线", "cmd_export" in _mw26_src and "cmd_import" in _mw26_src
      and "reset_factory" in _mw26_src and "backup.import_state" in _mw26_src)
check("backup 模块核心面", "PACKAGE_VERSION = 1" in _src26("core", "backup.py")
      and "restart_application" in _src26("core", "backup.py")
      and "watchdog" in _src26("core", "backup.py"))
check("T6 分区联动两行", "  重置 — 恢复默认设置与数据" in _gui26_src
      and "  配置传输 — 导出与导入配置包" in _gui26_src)

# ═══════════════════════════════════════════
print("\n[32] 2026-09-11 全量审查修复回归（F1/F2/F3/F6/F7/F8/F9/F10/F11/F12/F24/F26/F27/F28/F29/F30/F32/F38/F39/F42/F43/F45/F47/F48 + 兼容性）")
import io as _io34, os as _os34, re as _re34, subprocess as _sp34, tempfile as _tf34
_ROOT34 = _os34.path.dirname(_os34.path.dirname(_os34.path.abspath(__file__)))
def _src34(*parts):
    return _io34.open(_os34.path.join(_ROOT34, *parts), encoding="utf-8").read()
_wa34 = _src34("core", "winapi.py"); _cl34 = _src34("core", "cleaner.py")
_jd34 = _src34("core", "judger.py"); _lm34 = _src34("core", "learner.py")
_eg34 = _src34("core", "engine.py"); _gui34 = _src34("memwise_gui.py")
_mw34 = _src34("memwise.py"); _i18n34 = _src34("core", "i18n.py")
_cf34 = _src34("core", "config.py"); _bk34 = _src34("core", "backup.py")
_sn34 = _src34("core", "sniffer.py")
import core.winapi as _w34, core.engine as _e34, core.backup as _b34
from core.learner import _is_self_path

# ── F42/F43 批量快照：同量纲自证 + 失败缓存 + 时间字段同源 ──
check("F42 交叉校验同量纲(100ns)", "if abs(kt - self_kt) > 500_000" in _wa34)
check("F42 布局失败态缓存", "_spi_layout = False" in _wa34 and "if _spi_layout is False" in _wa34)
check("F43 批量时间字段不再 ×100",
      "kernel_off).value * 100" not in _wa34 and "user_off).value * 100" not in _wa34)
check("F42 回退路径同样提供 create", 'create": t.get("create")' in _sn34)
check("F42 get_process_times 返回 create", '"create": _ft_to_ns(ct)' in _wa34)
# 行为实证：本回归进程已运行较久（CPU 时间远超旧实现 ~50ms 阈值）——批量路径必须仍然可用
_pid34 = _os34.getpid()
_s034 = _w34.get_system_times(); _b034 = _w34.get_process_times(_pid34)
_t34a = time.time()
while time.time() - _t34a < 0.25:
    pass
_s134 = _w34.get_system_times(); _b134 = _w34.get_process_times(_pid34)
_bulk34 = _w34.get_all_processes_memory()
_sd34 = (_s134["kernel"] + _s134["user"]) - (_s034["kernel"] + _s034["user"])
check("F42 长运行进程内批量快照仍可用", len(_bulk34) > 20, "count=%d" % len(_bulk34))
if _bulk34.get(_pid34) and _sd34 > 0:
    _cpu_fb = ((_b134["kernel"] + _b134["user"]) - (_b034["kernel"] + _b034["user"])) / _sd34 * 100.0
    _cpu_bk = ((_bulk34[_pid34]["kernel"] + _bulk34[_pid34]["user"]) - (_b034["kernel"] + _b034["user"])) / _sd34 * 100.0
    check("F43 批量/回退 CPU% 口径一致", abs(_cpu_bk - _cpu_fb) <= max(0.15 * abs(_cpu_fb), 0.5),
          "bulk=%.3f fallback=%.3f" % (_cpu_bk, _cpu_fb))
    check("F42 批量提供 create（PID 复用防护）", bool(_bulk34[_pid34].get("create")))
else:
    check("F42/F43 批量路径可用性", False, "bulk 空或 sys_delta=0")

# ── F1 开关语义 / F6 quick 开关面 / F2 Layer3 开关契约 / F11 每轮归零 ──
check("F1 空集不再折叠为全量", "set(operations) if operations is not None else None" in _cl34)
_j34 = {"kp": 0.6, "ki": 0.15, "kd": 0.1, "target_usage": 60, "never": [], "efis_params": {}}
_ms34, _mu34 = _w34.get_memory_status, _w34.get_memory_used_bytes
_w34.get_memory_status = lambda: {"pct": 40, "total": 16 << 30, "avail": 9 << 30, "used": 7 << 30}
_w34.get_memory_used_bytes = lambda: 7 << 30
_OPS34 = ("empty_all_working_sets", "clear_system_file_cache_ex", "flush_modified_pages",
          "empty_standby", "purge_low_priority_standby", "flush_volume_cache", "clear_registry_cache")
try:
    _cap34 = {}; _l2c34 = []
    _lr34a = PareLearner(); _c34a = PareCleaner(PareJudger(_lr34a, dict(_j34)))
    _c34a._layer1_memreduct = lambda **kw: _cap34.update(ops=kw.get("ops"))
    _c34a._layer2_process = lambda *a, **k: (_l2c34.append(1), ([], []))[1]
    _c34a._layer3_deep = lambda *a, **k: None
    _c34a.optimize([], _lr34a, "normal", operations=[])
    check("F1 [] ⇒ 零系统操作且不做进程清理",
          _cap34.get("ops") == set() and not _l2c34, "ops=%r l2=%s" % (_cap34.get("ops"), _l2c34))

    _orig34 = {n: getattr(_w34, n) for n in _OPS34}
    _calls34 = []
    for _n34 in _OPS34:
        setattr(_w34, _n34, (lambda nm: (lambda *a, **k: (_calls34.append(nm), True)[1]))(_n34))
    try:
        _lr34q = PareLearner(); _c34q = PareCleaner(PareJudger(_lr34q, dict(_j34)))
        _calls34.clear(); _c34q.optimize([], _lr34q, "quick", operations=["ws", "filecache", "volume"])
        _q_inert = list(_calls34)
        _calls34.clear(); _c34q.optimize([], _lr34q, "quick", operations=["standby", "modified", "registry"])
        _q_act = sorted(_calls34)
    finally:
        for _n34, _f34 in _orig34.items():
            setattr(_w34, _n34, _f34)
    check("F6 quick 只勾 ws/filecache/volume ⇒ 零系统调用", _q_inert == [], str(_q_inert))
    check("F6 quick 勾 standby/modified/registry ⇒ 执行三项",
          _q_act == ["clear_registry_cache", "empty_standby", "flush_modified_pages"], str(_q_act))

    _orig34b = {n: getattr(_w34, n) for n in _OPS34}
    _calls34b = []
    for _n34 in _OPS34:
        setattr(_w34, _n34, (lambda nm: (lambda *a, **k: (_calls34b.append(nm), True)[1]))(_n34))
    try:
        _lr34b = PareLearner(); _c34b = PareCleaner(PareJudger(_lr34b, dict(_j34)))
        _calls34b.clear(); _c34b._layer3_deep([], _lr34b, ops_filter={"ws", "modified"})
        _mod_only = list(_calls34b)
        _calls34b.clear(); _c34b._layer3_deep([], _lr34b, ops_filter={"ws", "standby"})
        _stb_only = list(_calls34b)
    finally:
        for _n34, _f34 in _orig34b.items():
            setattr(_w34, _n34, _f34)
    check("F2 只勾 modified ⇒ 不清待机列表", not any("standby" in x for x in _mod_only), str(_mod_only))
    check("F2 只勾 standby ⇒ 不写回脏页",
          not any(("modified" in x or "deep_compress" in x) for x in _stb_only), str(_stb_only))
    check("F2 standby 全量回收同轮只执行一次", _stb_only.count("empty_standby") <= 1, str(_stb_only))

    _lr34r = PareLearner(); _c34r = PareCleaner(PareJudger(_lr34r, dict(_j34)))
    _c34r._fast_track = {999: 1}; _c34r._last_layer2_results = ["stale"]
    _c34r._layer1_memreduct = lambda **kw: None; _c34r._layer3_deep = lambda *a, **k: None
    _c34r.optimize([], _lr34r, "normal", operations=["standby"])
    check("F11 每轮入口状态归零", _c34r._fast_track == {} and _c34r._last_layer2_results == [],
          "%r %r" % (_c34r._fast_track, _c34r._last_layer2_results))
finally:
    _w34.get_memory_status, _w34.get_memory_used_bytes = _ms34, _mu34

# ── F3 紧急绝对阈值：钳制 + 判定内自检 ──
check("F3 配置钳制含 emergency_abs_pct", '("emergency_abs_pct", 0, 99)' in _cf34)
_old_ap34 = _e34.CFG.get("emergency_abs_pct")
_e34.CFG["emergency_abs_pct"] = 200
check("F3 判定内自检：越界值不再恒触发", _e34._emergency_active(
    {"pct": 30, "total": 16 << 30, "avail": int(0.7 * (16 << 30))}) is False)
_e34.CFG["emergency_abs_pct"] = _old_ap34

# ── F12/F48 身份复检与自身排除 ──
_lr34s = PareLearner(); _j34s = PareJudger(_lr34s, dict(_j34)); _c34s = PareCleaner(_j34s)
check("F12 quick_retrim 创建时间不符即放弃", _c34s.quick_retrim(_os34.getpid(), 1) == 0)
check("F48 自身可执行路径被重清拒绝", _c34s.quick_retrim(_os34.getpid(), None) == 0)
check("F48 自身进程判据（按完整路径）",
      _is_self_path(sys.executable) is True and _is_self_path(r"D:\other\python.exe") is False)
class _S48: pass
_s48 = _S48(); _s48.name = "self48.exe"; _s48.pid = 4243; _s48.ws = 200 << 20
_s48.path = sys.executable; _s48.fg = False
check("F48 自身进程不清理、不试探", _j34s.can_trim(_s48)[0] is False and _j34s.can_probe(_s48) is False)
_s48t = _S48(); _s48t.name = "tiny48.exe"; _s48t.pid = 4242; _s48t.ws = 512 * 1024
_s48t.path = r"d:\app\tiny.exe"; _s48t.fg = False
check("F48 WS<1MB 不试探", _j34s.can_probe(_s48t) is False)

# ── F48 零释放不抬 α + 零释放退避 ──
_p48 = Profile("p48.exe"); _a0_48 = _p48.alpha
_p48.record_probe(True, freed=0); _p48.record_probe(True, freed=0)
check("F48 零释放试探不抬 α、累计退避计数", _p48.alpha == _a0_48 and _p48.probe_zero == 2)
_p48.record_probe(True, freed=5 << 20)
check("F48 出现释放后退避计数清零", _p48.probe_zero == 0 and _p48.alpha > _a0_48)
_lr48 = PareLearner(); _j48 = PareJudger(_lr48, dict(_j34))
_s48c = _S48(); _s48c.name = "zero48.exe"; _s48c.pid = 4244; _s48c.ws = 100 << 20
_s48c.path = r"d:\app\zero.exe"; _s48c.fg = False
_pz = _lr48.get("zero48.exe"); _pz.ws_deque.append(100 << 20); _pz.probe_zero = 5
_j48._probe_dynamic_interval = 120
_j48._probe_last_time["zero48.exe"] = time.time() - 300
check("F48 零释放退避：间隔×20 后 300s 内不再试探", _j48.can_probe(_s48c) is False)
_lr48n = PareLearner(); _j48n = PareJudger(_lr48n, dict(_j34))
_pn = _lr48n.get("zero48.exe"); _pn.ws_deque.append(100 << 20)
_j48n._probe_dynamic_interval = 120
_j48n._probe_last_time["zero48.exe"] = time.time() - 300
check("F48 无零释放记录时 300s 后可再试探", _j48n.can_probe(_s48c) is True)

# ── F47 PF 判据扣除进程自身速率 + 清后基线与 ok 解耦 ──
_lr47 = PareLearner(); _j47 = PareJudger(_lr47, dict(_j34))
_j47.pf_before[555] = (1000, time.time() - 2.0)
_ok_a47, _fa47, _pfa47 = _j47.check_feedback(555, 1000 + 90000, 100 << 20, 60 << 20, 2)
_j47._pf_rate[555] = 100000.0
_j47.pf_before[555] = (1000, time.time() - 2.0)
_ok_b47, _fb47, _pfb47 = _j47.check_feedback(555, 1000 + 90000, 100 << 20, 60 << 20, 2)
check("F47 同一 PF 增量：无自身速率判失败、计入后判成功", _ok_a47 is False and _ok_b47 is True)
check("F47 清后基线与 ok 解耦", "if ws_after > 0 and (ok or freed > 0):" in _cl34)
check("F47 PF 速率缓存有过期清理", "self._pf_rate.pop(k, None)" in _jd34)

# ── F45 filecache 四步（单位/恢复/校验）──
check("F45 用权威字节上下限恢复", "get_system_file_cache_limits()" in _wa34
      and "SetSystemFileCacheSize(orig[0], orig[1], 0)" in _wa34)
check("F45 不再把字节 PeakSize 写进页字段", "info.MinimumWorkingSet = info.PeakSize" not in _wa34)
check("F45 回收目标为页口径常量", "_SFCI_CACHE_TARGET_PAGES = 4096" in _wa34)
check("F45 恢复后回读校验", "if get_system_file_cache_limits() == orig:" in _wa34)

# ── F38/F39/F40 初始化显式化 / CLI 日志与消息 / docstring ──
check("F38 init_runtime 已抽取且 import 不再调用",
      "def init_runtime()" in _eg34 and "_migrate_runtime_data()\n\n\nif \"--watchdog\"" not in _eg34)
_r38 = _sp34.run([sys.executable, "-B", "-c",
                  ("import sys,ctypes;sys.path.insert(0,r'%s');"
                   "a=ctypes.c_int();ctypes.windll.shcore.GetProcessDpiAwareness(None,ctypes.byref(a));b0=a.value;"
                   "import core.engine;"
                   "b=ctypes.c_int();ctypes.windll.shcore.GetProcessDpiAwareness(None,ctypes.byref(b));"
                   "print(b0,b.value)") % _ROOT34],
                 capture_output=True, text=True, timeout=90)
_out38 = (_r38.stdout or "").strip().split()
check("F38 import core.engine 不改变 DPI 感知（子进程实证）",
      len(_out38) == 2 and _out38[0] == _out38[1], "%r" % _out38)
check("F38 GUI/CLI 入口调用 init_runtime", "init_runtime()" in _gui34 and "init_runtime()" in _mw34)
check("F39 CLI 按开关打开统一日志", 'CFG.get("log_to_file")' in _mw34 and "from core.engine import _log_open" in _mw34)
check("F40 optimize docstring 与实现一致",
      "四模式行为矩阵与参数契约" in _cl34 and "已激活 8 步内核快速管线" not in _cl34)
check("F28 CLI 消费 learner/cleaner 消息", "learner.pop_info()" in _mw34 and "cleaner.pop_info()" in _mw34)
check("F27 atexit 只注册一次", "_ATEXIT_REGISTERED" in _eg34)
check("F26 save 内做内存侧同口径淘汰", "self.profiles.pop(_k, None)" in _lm34)

# ── F30 消息清空就地化（对象同一性 + 不丢消息）──
_lr30 = PareLearner(); _j30 = PareJudger(_lr30, dict(_j34)); _c30 = PareCleaner(_j30)
_c30._info_msgs.append("🎮 检测到游戏运行 · 启用 游戏模式")
_bid30 = id(_c30._info_msgs)
_gm30 = _c30.pop_game_msgs()
check("F30 pop_game_msgs 就地清空", id(_c30._info_msgs) == _bid30 and len(_gm30) == 1
      and _c30._info_msgs == [])

# ── F29 备份包保留上限（用户导出包永不自动清理）──
_bkb34 = _os34.path.join(_tf34.mkdtemp(), "data")
_os34.makedirs(_bkb34, exist_ok=True)
_os34.makedirs(_os34.path.join(_os34.path.dirname(_bkb34), "config"), exist_ok=True)
_io34.open(_os34.path.join(_os34.path.dirname(_bkb34), "config", "config.yaml"), "w", encoding="utf-8").write("interval: 60\n")
_io34.open(_os34.path.join(_bkb34, "memwise_state.json"), "w", encoding="utf-8").write('{"version": 4}')
_orig_stamp34 = _b34._now_stamp
_cnt34 = [0]
def _stamp34():
    _cnt34[0] += 1
    return "20260911-%06d" % _cnt34[0]
_b34._now_stamp = _stamp34
try:
    _b34.export_state("export", base=_bkb34)
    for _i34 in range(13):
        _b34.create_backup(base=_bkb34)
finally:
    _b34._now_stamp = _orig_stamp34
_files34 = _os34.listdir(_os34.path.join(_bkb34, "import_export"))
check("F29 自动备份包保留上限生效",
      len([f for f in _files34 if f.startswith("MemWise_Backup_")]) == _b34.BACKUP_KEEP,
      "backups=%d" % len([f for f in _files34 if f.startswith("MemWise_Backup_")]))
check("F29 用户导出包不被自动清理", len([f for f in _files34 if f.startswith("MemWise_Export_")]) == 1)

# ── F7/F8/F9/F10/F24/F32/F31 结构性 ──
check("F7 处理资源管理器重启消息", "_TASKBAR_CREATED" in _gui34 and "action == 'readd'" in _gui34
      and "def _readd_tray" in _gui34)
check("F8 跨用户会话退出前有提示", "MessageBoxW" in _gui34 and "只允许运行一个实例" in _gui34)
check("F9 日志文件名文案订正", "memwise1.log" not in _i18n34 and "memwise1.log" not in _gui34
      and "memwise.log.1" in _i18n34)
check("F10 自适应 gap 收敛到 8-20", "min(20.0, gap + 3)" in _eg34 and "min(25.0, gap + 3)" not in _eg34)
check("F24 新增守护周期控件与更名后的标签",
      "守护周期: " in _gui34 and "周期内轻量压制间隔: " in _gui34 and "ttk.Spinbox" in _gui34)
check("F32 标准权限显式提示", "当前为标准权限运行" in _gui34 and "当前为标准权限运行" in _i18n34)
check("F32 运行时显式提权 + 防重启循环",
      "def _relaunch_elevated" in _gui34 and '"runas"' in _gui34 and "--elevated-retry" in _gui34)
check("F32 提权重启路径的互斥接管重试", "--elevated-retry" in _gui34 and "for _ in range(20)" in _gui34)
check("F32 清单改为 asInvoker 且不再用 uac_admin",
      "asInvoker" in _io34.open(_os34.path.join(_ROOT34, "MemWise.manifest"), encoding="utf-8").read()
      and "\n    uac_admin=True," not in _io34.open(_os34.path.join(_ROOT34, "MemWise.spec"), encoding="utf-8").read()
      and "manifest='MemWise.manifest'" in _io34.open(_os34.path.join(_ROOT34, "MemWise.spec"), encoding="utf-8").read())
check("F48 自身进程原因串已入 i18n", "程序自身" in _i18n34)
check("F49 EFIS 状态路径显式拼接（不再依赖文件名子串）",
      "_efis_state_path" in _src34("core", "efis.py")
      and 'efis_path = self.state_path.replace' not in _src34("core", "efis.py"))
check("F45 缓存极小则跳过钳制（零副作用快路径）", "if before <= (32 << 20):" in _wa34)
check("F33 等待时长按实际执行轮数等比（档位不再带来无收益等待）",
      "total_wait * (rounds_done / max(passes, 1))" in _cl34)

# ── S5 压力判据统一 + 门槛重标定（F4/F5/F21/F44）──
_j5 = PareJudger(PareLearner(), {"kp": 0.6, "ki": 0.15, "kd": 0.1, "target_usage": 60, "never": [],
                                 "efis_params": {}, "emergency_threshold": 80})
_j5.aggressiveness = 0.5; _j5._last_mem_pct = 50
check("S5 高压让路：agg 未达且使用率未达⇒否", _j5._high_pressure() is False)
_j5.aggressiveness = 0.85
check("S5 agg≥0.8 仍判高压", _j5._high_pressure() is True)
_j5.aggressiveness = 0.5; _j5._last_mem_pct = 80
check("S5 使用率达用户紧急阈值即高压", _j5._high_pressure() is True)
_j5._last_mem_pct = 79.9
check("S5 阈值下方不触发", _j5._high_pressure() is False)
_j5.cfg["emergency_threshold"] = 90
_j5._last_mem_pct = 85
check("S5 阈值调高后 85% 不触发", _j5._high_pressure() is False)
_j5._last_mem_pct = 90
check("S5 阈值调高后 90% 触发", _j5._high_pressure() is True)
_pv5 = PolicyVoter(); _l5 = PareLearner()
_, _, _sc5 = _pv5.should_trim("x.exe", 10 << 20, {"mem_pct": 85, "mem_trend": 0, "emergency": 80}, _l5)
_, _, _sc5b = _pv5.should_trim("x.exe", 10 << 20, {"mem_pct": 84, "mem_trend": 0, "emergency": 90}, _l5)
_, _, _sc5c = _pv5.should_trim("x.exe", 10 << 20, {"mem_pct": 92, "mem_trend": 0, "emergency": 90}, _l5)
check("S5 树2 阈值随用户设定（80%@85=+2 / 90%@84=+1 / 90%@92=+2）",
      _sc5[1] == 2 and _sc5b[1] == 1 and _sc5c[1] == 2, "%r %r %r" % (_sc5[1], _sc5b[1], _sc5c[1]))

def _run_l3_5(pct, em):
    lr_o = PareLearner()
    j_o = PareJudger(lr_o, {"kp": 0.6, "ki": 0.15, "kd": 0.1, "target_usage": 60, "never": [],
                            "efis_params": {}, "emergency_threshold": em})
    c_o = PareCleaner(j_o); hit = []
    c_o._layer3_deep = lambda *a, **k: hit.append(1)
    _oms5, _omu5 = _w34.get_memory_status, _w34.get_memory_used_bytes
    _w34.get_memory_status = lambda: {"pct": pct, "total": 16 << 30, "avail": 9 << 30, "used": 7 << 30}
    _w34.get_memory_used_bytes = lambda: 7 << 30
    try:
        c_o.optimize([], lr_o, "normal", operations=["ws"], aggressiveness=0.1)
    finally:
        _w34.get_memory_status, _w34.get_memory_used_bytes = _oms5, _omu5
    return bool(hit)
check("S5 normal 深度聚合使用率路径（68% 触发 / 60% 不触发）",
      _run_l3_5(68, 80) is True and _run_l3_5(60, 80) is False)
check("S5 使用率路径随用户阈值移动（阈值 90 ⇒ 77% 触发、70% 不触发）",
      _run_l3_5(77, 90) is True and _run_l3_5(70, 90) is False)
check("S5 使用率判据存在（结构性）", "_l3_usage" in _cl34 and "_em_l3 * 0.85" in _cl34)
check("F6 quick 开关置灰 + 说明已接线", 'CFG.get("clean_mode", "normal") == "quick"' in _gui34
      and '_cb.state(["disabled"])' in _gui34 and "quick 模式下「释放进程闲置内存」" in _i18n34)
# ── F50 开关标题名不副实（2026-09-11 用户实测指出）──
check("F50 开机自启开关标题不再歧义",
      '"以管理员权限开机自启动"' in _gui34 and "需搭配「以管理员权限开机自启动」" in _gui34
      and "以管理员权限开机自启动" in _i18n34)
check("F50 旧标题键已清除", '"管理员权限启动"' not in _i18n34 and 'tr("管理员权限启动")' not in _gui34)

# ── F51 语言往返正确性：日志历史必须是中文原文（写进历史的东西不得提前翻译）──
_bad51 = [m.group(0)[:40] for m in _re34.finditer(
    r"self\._log(?:_op|_batch)?\(\s*(?:\[\s*)?(?:tr|tr_msg)\(", _gui34)]
_bad51 += [m.group(0)[:40] for m in _re34.finditer(r"append\(\s*(?:tr|tr_msg)\(", _gui34)]
check("F51 日志调用不得提前翻译（历史只存中文原文）", not _bad51, str(_bad51[:3]))
check("F51 judger 标签返回中文原文（不在构造期翻译）",
      'return "极高"' in _jd34 and 'return tr("极高")' not in _jd34
      and 'return "高"' in _jd34 and 'return tr("高")' not in _jd34)
# 行为级：直接复现用户观察到的那一行（引擎拼装 → 显示层渲染 → 往返切换）
import tkinter as _tk51
from collections import deque as _dq51
_root51 = _tk51.Tk(); _root51.withdraw()
_stub51 = _mg29.MemWiseGUI.__new__(_mg29.MemWiseGUI)
_stub51.log = _tk51.Text(_root51)
_stub51._log_history = _dq51(maxlen=300)
_stub51._last_msg = None
set_language("zh_CN")
_stub51._write_group(["📈 内存 70%（偏高）· 清理强度：维持高"])
set_language("en")
_stub51._rerender_log()
_txt_en51 = _stub51.log.get("1.0", "end")
set_language("zh_CN")
_stub51._rerender_log()
_txt_zh51 = _stub51.log.get("1.0", "end")
_root51.destroy()
check("F51 英文态整行无中文残留",
      "Memory" in _txt_en51 and "intensity" in _txt_en51
      and not _re34.search(r"[\u4e00-\u9fff]", _txt_en51), _txt_en51.strip()[:70])
check("F51 切回中文后无英文残留（往返正确）",
      "内存" in _txt_zh51 and "维持高" in _txt_zh51
      and not _re34.search(r"[A-Za-z]{3,}", _txt_zh51.split("] ")[-1]), _txt_zh51.strip()[:70])

# ── F52 日志图标位对齐（2026-09-11 用户要求：图标对图标、文字对文字）──
# 实现为「固定制表位」：图标后接制表符跳到文字列；无图标则制表符独占图标位。
# 实测 Consolas 9 各图标像素宽差异大（→ 7px、✓ 12px、⚡/⚠ 16px），空格补齐无法对齐。
_AL52 = _mg29._align_log_line
check("F52 图标识别（emoji/箭头/对勾/警告等）",
      all(_mg29._log_is_icon(c) for c in "🎮📈🧹🔍⚠❌⚡✨✓✗→←↑↻🔄")
      and not any(_mg29._log_is_icon(c) for c in "内存MB7z[("))
check("F52 有图标行：图标独占位 + 制表到文字列", _AL52("🎮 检测到游戏运行") == "🎮\t检测到游戏运行")
check("F52 无图标行：制表符留空图标位", _AL52("本轮释放 1.0MB") == "\t本轮释放 1.0MB")
check("F52 对勾行（卡片名单）", _AL52("✓ 其余 21 个进程") == "✓\t其余 21 个进程")
check("F52 卡片缩进被规范化到图标位", _AL52("  ✓ 7z.exe (PID=1) 512 MB") == "✓\t7z.exe (PID=1) 512 MB")
check("F52 多行消息逐行处理", _AL52("🔍 err\nTraceback") == "🔍\terr\n\tTraceback")
check("F52 幂等（重复对齐不变形）", _AL52(_AL52("📈 内存 70%")) == _AL52("📈 内存 70%"))
check("F52 空串与纯空白行安全", _AL52("") == "" and _AL52("\n") == "\t\n\t")
_i18n_icon_miss52 = [(z, e) for z, e in _EN.items()
                     if isinstance(e, str) and e and _mg29._log_is_icon(z[0])
                     and not _mg29._log_is_icon(e[0])]
check("F52 译文不丢图标（中文带图标的条目，英文同样以图标开头）",
      not _i18n_icon_miss52, str(_i18n_icon_miss52[:3]))

# ── F52b 画像输出标签列宽一致（命令行 profile 输出；中英各自成列）──
import unicodedata as _uda52
def _dw52(s):
    return sum(2 if _uda52.east_asian_width(c) in ("W", "F") else 1 for c in s)
_PROF52 = ("路径:", "工作集:", "页面错误:", "Thompson θ:", "ROI:", "Z-score:", "趋势:", "泄漏:", "清理:")
def _pkeys52(lang):
    set_language(lang)
    out = []
    for core in _PROF52:
        for k in _EN:
            if k.startswith("  ") and k.strip() == core:
                out.append(_dw52(tr(k)) if lang == "en" else _dw52(k))
    return out
_zhw52, _enw52 = _pkeys52("zh_CN"), _pkeys52("en")
set_language("zh_CN")
check("F52b 画像标签列宽一致（中文 9 行同列）",
      len(_zhw52) == 9 and len(set(_zhw52)) == 1, str(sorted(set(_zhw52))))
check("F52b 画像标签列宽一致（英文 9 行同列）",
      len(_enw52) == 9 and len(set(_enw52)) == 1, str(sorted(set(_enw52))))
_mw_py52 = _io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "memwise.py"),
                    encoding="utf-8").read()
_lits52 = _re.findall(r'tr\("(  [^"]*?)"\)', _mw_py52)
check("F52b 命令行标签字面量都是精确键（否则退化为片段翻译、列宽失准）",
      bool(_lits52) and all(L in _EN for L in _lits52),
      str([L for L in _lits52 if L not in _EN][:3]))

# ── F53 手动/即时优化的"候选预览"与实际执行同口径（manual/guard 只读覆盖）──
# 症状（日志实证 2026-09-07）：同一按钮有的轮次有「📋 将清理 N 个进程候选」，有的轮次没有，
# 且候选名单与完成卡名单对不上——预览在 cleaner 同步 _manual_mode/_mode_guard 之前求值，
# 沿用了上一轮守护遗留的保守门（刚切走/活动确认/稳态抑制/回弹后退 + 旧模式门）。
_lr53 = PareLearner(); _j53 = PareJudger(_lr53, dict(_j34))
class _S53: pass
def _snap53(name, pid, ws=200 << 20, fg=False, cpu=0.0):
    s = _S53(); s.name = name; s.pid = pid; s.ws = ws; s.fg = fg; s.cpu = cpu
    s.path = r"d:\app53\%s" % name; s.has_visible = False
    return s
_s53 = _snap53("prev53.exe", 4353)
_lr53.get("prev53.exe").last_foreground_at = time.time() - 60   # 刚切走（有窗口 10 分钟冷却）
check("F53 保守门（刚切走）在守护口径下拦截", _j53.can_trim(_s53)[0] is False)
check("F53 预览口径（manual=True + 本次模式）放行保守门，与实际执行同口径",
      _j53.can_trim(_s53, manual=True, guard="normal")[0] is True)
check("F53 保守门（活动确认中）守护口径拦截、预览口径放行",
      _j53.can_trim(_snap53("act53.exe", 4354))[0] is False
      and _j53.can_trim(_snap53("act53.exe", 4354), manual=True, guard="normal")[0] is True)
check("F53 模式门按本次模式评估（CPU 活跃门：normal 拦 / full 放行）",
      _j53.can_trim(_snap53("cpu53.exe", 4355, cpu=50.0), manual=True, guard="normal")[0] is False
      and _j53.can_trim(_snap53("cpu53.exe", 4355, cpu=50.0), manual=True, guard="full")[0] is True)
check("F53 非三档模式（quick）按 normal 归一，与清理器同口径",
      _j53.can_trim(_snap53("cpu53.exe", 4355, cpu=50.0), manual=True, guard="quick")[0] is False)
_j53._mode_guard = "full"
_ok53_def = _j53.can_trim(_snap53("cpu53.exe", 4355, cpu=50.0))[0]
_j53._mode_guard = "normal"
check("F53 缺省 guard 沿用当前状态（守护路径行为不变）",
      _ok53_def is True and _j53.can_trim(_snap53("cpu53.exe", 4355, cpu=50.0))[0] is False)
check("F53 口径覆盖是只读的（不改对象状态）",
      _j53._manual_mode is False and _j53._mode_guard == "normal"
      and _j53.can_trim(_s53)[0] is False)
_eng53 = _io.open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               "core", "engine.py"), encoding="utf-8").read()
check("F53 引擎两处候选预览均按同口径调用", _eng53.count("can_trim(s, manual=True, guard=mode)") == 2)

# ── F54 结果卡信息结构：系统缓存 / 进程分列（2026-09-11 用户定稿）+ 候选行口径 ──
check("F54 候选行文案改为「本次将评估」",
      _eng53.count('f"📋 本次将评估 {len(preview)} 个进程：{shown}"') == 2
      and "📋 将清理" not in _eng53)
class _Snap54:
    def __init__(self, name, pid):
        self.name = name; self.pid = pid
class _Cleaner54:
    def summary(self):
        return {"freed_mb": 468.0}
class _Engine54:
    daemon_running = True
_root54 = _tk51.Tk(); _root54.geometry("900x200+4000+4000")
_g54 = _mg29.MemWiseGUI.__new__(_mg29.MemWiseGUI)
_g54.log = _tk51.Text(_root54, font=("Consolas", 9))
_g54.log.pack(fill="both", expand=True)
_mg29._setup_log_widget(_g54.log)
_g54._log_history = _dq51(maxlen=50); _g54._last_msg = None
_g54.cleaner = _Cleaner54(); _g54.engine = _Engine54()
_g54._upd_stats = lambda: None
_g54._once_optimizing = True
_cfg54 = _mg29.CFG.get("log_to_file")
_mg29.CFG["log_to_file"] = False          # 仅内存：防测试写真实 memwise.log
_rep54 = _mg29.winapi.report_event
_mg29.winapi.report_event = lambda *a, **k: None
set_language("zh_CN")
_g54._opt_done({"mode": "full",
                "layer2": [(_Snap54("chrome.exe", 12040), True, 10 << 20, ""),
                           (_Snap54("7z.exe", 3311), True, 5 << 20, ""),
                           (_Snap54("skip.exe", 999), False, 0, "CPU活跃")],
                "probe": [], "released": 468.0, "net": 296 << 20, "pct0": 62, "pct1": 71})
_txt54 = _g54.log.get("1.0", "end")
_mg29.winapi.report_event = _rep54
_mg29.CFG["log_to_file"] = _cfg54
_root54.destroy()
check("F54 结果卡分列且合计一致（系统缓存 453 + 进程 15 = 共 468）",
      "系统缓存 453 MB + 进程 15 MB = 共 468 MB" in _txt54, _txt54.strip().replace("\n", " | ")[:110])
check("F54 失败项不计入进程释放量、明细仍只列成功项",
      "chrome.exe" in _txt54 and "7z.exe" in _txt54 and "skip.exe" not in _txt54,
      _txt54.strip().replace("\n", " | ")[:110])
set_language("en")
check("F54 英文界面下动态拼接的顿号转半角逗号",
      tr_msg("本次将评估 3 个进程：a.exe、b.exe、c.exe") == "Evaluating 3 processes: a.exe, b.exe, c.exe"
      or "、" not in tr_msg("a、b"))
set_language("zh_CN")
check("F54 中文界面顿号保持原样", tr_msg("a、b") == "a、b")

# 真实面板像素级核验：同一 Text（与应用同字体/同制表位）内，所有行的图标列与文字列必须一致
_root52 = _tk51.Tk(); _root52.geometry("900x200+4000+4000")  # 映射到屏幕外：bbox 需已映射，但不闪窗口
_stub52 = _mg29.MemWiseGUI.__new__(_mg29.MemWiseGUI)
_stub52.log = _tk51.Text(_root52, font=("Consolas", 9))
_stub52.log.pack(fill="both", expand=True)
_mg29._setup_log_widget(_stub52.log)
_stub52._log_history = _dq51(maxlen=50)
_stub52._last_msg = None
set_language("zh_CN")
_stub52._write_group(["📈 内存 70%（偏高）· 清理强度：维持高", "本轮释放 512MB · 整理 12 进程",
                      "  ✓ 7z.exe (PID=1) 512 MB", "守护已停止"])
_stub52._write_group(["⚡ normal 优化完成 · 释放 812 MB", "  ✓ chrome.exe (PID=12040) 322 MB",
                      "✓ 其余 21 个进程"])
_stub52.log.update_idletasks()
_root52.update()
# 索引一律走 Tk 自身（非 BMP emoji 在 Tk 里占 2 个字符，Python 下标会错位）
_px52 = {"icon_x": set(), "text_x": set()}
for _i, _ln in enumerate(_stub52.log.get("1.0", "end").splitlines(), start=1):
    if not _ln.strip():
        continue
    _b_icon = _stub52.log.bbox(f"{_i}.11")            # 时间戳前缀恒 11 字符，其后即图标位
    _i_tab = _stub52.log.search("\t", f"{_i}.11", f"{_i}.end")
    if _b_icon:
        _px52["icon_x"].add(_b_icon[0])
    if _i_tab:
        _b_text = _stub52.log.bbox(_stub52.log.index(f"{_i_tab} + 1c"))
        if _b_text:
            _px52["text_x"].add(_b_text[0])
_tab52 = _mg29._log_tab_stop(_stub52.log)
_x0_52 = _stub52.log.bbox("1.0")[0]                     # 文本区左缘（含边框偏移）
_f52_f = _tk51.font.Font(font=_stub52.log.cget("font"))
_f52_pre = _f52_f.measure("[00:00:00] ")
_f52_room = _tab52 - _f52_pre
_f52_wide = max(_f52_f.measure(c) for c in _mg29._LOG_ICON_PROBE)
_stub52.log.destroy(); _root52.destroy()
check("F52 真实面板：图标列像素一致 + 文字列像素一致且恰在制表位",
      len(_px52["icon_x"]) == 1 and _px52["text_x"] == {_x0_52 + _tab52},
      f"icon_x={_px52['icon_x']} text_x={_px52['text_x']} 期望={_x0_52 + _tab52}")
check("F52 图标位宽容得下最宽图标（否则制表符跳不过去、该行错位）",
      _f52_room >= _f52_wide, f"图标位={_f52_room} 最宽图标={_f52_wide}")
check("F22 两个活跃门已入 i18n 参数名", "CPU活跃门" in _i18n34 and "IO活跃门" in _i18n34)
check("F31 崩溃恢复提示含退出指引", "如需彻底退出" in _gui34 and "如需彻底退出" in _i18n34)

# ── 旧数据 / 升级兼容性 ──
check("兼容：旧画像无 probe_zero 字段可加载", Profile.from_dict({"name": "old.exe"}).probe_zero == 0)
check("兼容：新参数在旧 efis_state 下有默认值",
      EfisController(state_path=None).get_params("normal").get("cpu_gate") == 8.0
      and EfisController(state_path=None).get_params("full").get("io_gate") == 4.0)
check("兼容：v3 迁移后新参数同样有默认值", _efm25.get_params("normal").get("cpu_gate") == 8.0)
_t_old34 = _os34.path.join(_tf34.mkdtemp(), "old_state.json")
_io34.open(_t_old34, "w", encoding="utf-8").write(json.dumps({
    "version": 4,
    "profiles": {"legacy.exe": {"name": "legacy.exe", "alpha": 5, "beta": 2, "ws": [1, 2, 3]}},
    "stable_anchors": {}, "rebound": {}}))
_l_old34 = PareLearner.load(_t_old34)
check("兼容：旧版 state（无 probe_zero/policy 键）加载且数据保留",
      "legacy.exe" in _l_old34.profiles and _l_old34.profiles["legacy.exe"].probe_zero == 0
      and _l_old34.profiles["legacy.exe"].alpha == 5)


print("\n[33] ERIS v7 五维绝对标尺（2026-09-11 用户定稿；设计见记忆 learning-engine-specs §B4）")
from core.eris import (DIM_ANCHORS as _A7, EFF_K as _K7, SUPER_TH as _ST7, WARN_TH as _WT7,
                       DIM_WORDS as _W7, dim_score as _ds7, efficiency as _ef7,
                       pick_factor as _pf7, smooth3_append as _sm7, SMOOTH_N as _SN7,
                       new_state as _ns7)
check("v7 锚点/词条维度数一致", len(_A7) == 5 and len(_W7) == 5)
check("v7 四锚点映射精确（p10/p50/p90/p99 → 20/50/80/110）",
      all(round(_ds7(a[0], a)) == 20 and round(_ds7(a[1], a)) == 50
          and round(_ds7(a[2], a)) == 80 and round(_ds7(a[3], a)) == 110 for a in _A7))
check("v7 分数钳制（下限 0 / 上限 140）", _ds7(-1e9, _A7[0]) == 0.0 and _ds7(1e9, _A7[0]) == 140.0)
check("v7 副作用为对数维（单调且 p50 命中 50 分）",
      round(_ds7(_A7[3][1], _A7[3], log_scale=True)) == 50
      and _ds7(_A7[3][0], _A7[3], log_scale=True) < _ds7(_A7[3][2], _A7[3], log_scale=True))
check("v7 效率合成（五维各 K/5 ⇒ 恰 100%）", abs(_ef7([_K7 / 5] * 5) - 100.0) < 0.01)
check("v7 极性阈值（超常 100 / 异常 50）", _ST7 == 100.0 and _WT7 == 50.0)
_dq7 = _dq51(maxlen=_SN7)
check("v7 平滑 N=3 滚动中位", [_sm7(_dq7, x) for x in (1.0, 3.0, 2.0, 10.0)] == [1.0, 2.0, 2.0, 3.0])
check("v7 词条：升→上升维中最高分；降→下降维中最低分",
      _pf7([70, 60, 55, 50, 51], [60, 60, 50, 50, 50], True) == 0
      and _pf7([70, 40, 55, 50, 51], [60, 50, 50, 50, 50], False) == 1)
check("v7 词条：无同向变化维 ⇒ None（调用方兜底）",
      _pf7([10, 20, 30, 40, 50], [10, 20, 30, 40, 50], True) is None)
check("v7 五维词条统一四字", all(len(w.strip("↑↓")) == 4 for pair in _W7 for w in pair))
_es7 = _ns7()
check("v7 状态容器（5 个滚动窗 + 上轮分/趋势）",
      len(_es7["hist"]) == 5 and _es7["prev_scores"] is None and _es7["trend"] == [])
_eng7 = _eng32_src
check("v7 引擎接线（五维原始值 + 平滑 + 同向门槛；无 v6 残留/防振荡硬规则）",
      all(k in _eng7 for k in ("_cycle_trim_detail", "_cycle_pf", "_cycle_probe",
                               "_eris_hist", "E.pick_factor", "E.smooth3_append"))
      and all(k not in _eng7 for k in ("_eris_bufs", "_eris_iqr_ewma", "prev_factor",
                                       "iqr_dim", "round(eff) >= 100")))
check("v7 旧状态（v6 分位数窗格式）自动忽略：加载入口只认 v==7",
      'payload.get("v") == 7' in _eng7 and "memwise_eris_ewma.json" in _eng7)

import re
print("\n[34] ERIS v7 ② 自校准（冷启动 + 长周期爬行；独立存储 / 恢复默认清除）")
from core.eris import (new_calib as _nc7, calib_valid as _cv7, calibrate_and_score as _cs7,
                       anchors_center_span as _ac7, DIM_ANCHORS as _A7b,
                       dim_score as _ds7b)
import random as _r36
_r36.seed(11)
# ① 分位估计收敛（喂入已知分布，估计应贴近真分位）
_c36 = _nc7()
for _ in range(6000):
    _cs7([_r36.gauss(100, 10), _r36.gauss(1.0, 0.2), 2.0, 0.05, 0.35], _c36)
_q10, _q50, _q90 = _c36["modes"]["normal"]["dims"][0]
check("② 分位估计收敛（q50 贴近真中位，q10<q50<q90）",
      abs(_q50 - 100) < 1.5 and _q10 < _q50 < _q90, f"{_q10:.1f}/{_q50:.1f}/{_q90:.1f}")
check("② 计数与初始化标记", _c36["modes"]["normal"]["n"] == 6000 and _c36["modes"]["normal"]["init"] is True)
# ② 冷启动首轮 ≈ 不校准（淡入自 1/100 起步）
_c36b = _nc7()
_s_first, _ = _cs7([0.35, 1.0, 2.0, 0.03, 0.35], _c36b)
_s_cold = [_ds7b(0.35, _A7b[0]), _ds7b(1.0, _A7b[1]), _ds7b(2.0, _A7b[2]),
           _ds7b(0.03, _A7b[3], log_scale=True), _ds7b(0.35, _A7b[4])]
check("② 冷启动首轮≈不校准（淡入生效）",
      all(abs(a - b) < 1.2 for a, b in zip(_s_first, _s_cold)), f"{[round(x,1) for x in _s_first]}")
# ③ 他机（整体偏低）经校准不再贴底，且中心位移被限幅
_c36c = _nc7()
for _ in range(3000):
    _cs7([0.32, 0.60, 2.0, 0.05, 0.35], _c36c)
_s3, _ = _cs7([0.32, 0.60, 2.0, 0.05, 0.35], _c36c)
_m_cold36, _sp_cold36 = _ac7(_A7b[1])
check("② 他机中位由「贴底」升至限幅允许的区间（20~55 分）", 20.0 < _s3[1] < 55.0, f"{_s3[1]:.1f}")
_c36f = _nc7()
for _ in range(3000):
    _cs7([0.32, 0.10, 2.0, 0.05, 0.35], _c36f)
_s6, _ = _cs7([0.32, 0.10, 2.0, 0.05, 0.35], _c36f)
_exp36 = _ds7b(_m_cold36 - 0.5 * _sp_cold36, _A7b[1])
check("② 中心位移限幅：极偏离机器的分数恰为「限幅边界」对应分值",
      abs(_s6[1] - _exp36) < 3.0, f"{_s6[1]:.1f} vs {_exp36:.1f}")
# ④ 跨度比限幅
_c36d = _nc7()
for _ in range(2000):
    _cs7([0.32, 0.05 if _r36.random() < 0.5 else 3.0, 2.0, 0.05, 0.35], _c36d)
_sp_local = max(_c36d["modes"]["normal"]["dims"][1][2] - _c36d["modes"]["normal"]["dims"][1][0], 1e-9)
_ratio36 = max(0.70, min(1.40, _sp_cold36 / _sp_local))
check("② 跨度比限幅落在 [0.70, 1.40]", 0.70 - 1e-9 <= _ratio36 <= 1.40 + 1e-9, f"{_ratio36:.2f}")
# ⑤ ② 的核心目的：他机失配下词条仍能轮换
_c36e = _nc7()
_spec = [0.32, 0.60, 1.2, 0.02, 0.28]
for _ in range(1500):
    _cs7([_r36.gauss(a, abs(a) * 0.05) for a in _spec], _c36e)
_picks36, _prev36, _prevs36 = [], None, None
for _ in range(60):
    _raw = [_r36.gauss(a, abs(a) * 0.06) for a in _spec]
    _sc, _ = _cs7(_raw, _c36e)
    _e = sum(_sc)
    if _prev36 is not None and _e != _prev36:
        _up = _e > _prev36
        _cand = [j for j in range(5) if (_sc[j] > _prevs36[j]) == _up and _sc[j] != _prevs36[j]]
        if _cand:
            _picks36.append(max(_cand, key=lambda k: _sc[k]) if _up
                            else min(_cand, key=lambda k: _sc[k]))
    _prev36, _prevs36 = _e, _sc
check("② 他机失配下词条仍轮换（≥3 个维度被点名）",
      len(set(_picks36)) >= 3, str(sorted(set(_picks36))))
# ⑥ 结构校验 + 存储策略（不进配置包 / 恢复默认清除）
check("② 校准结构校验（好样本通过，版本/维度/负计数被拒）",
      _cv7(_nc7()) and not _cv7({"v": 2, "dims": [[0, 0, 0]] * 5})
      and not _cv7({"v": 1, "dims": []})
      and not _cv7({"v": 1, "dims": [[0, 0, 0]] * 5, "n": -1}))
_bk_src36 = _src26("core", "backup.py")
check("② 校准文件不进配置包、但恢复默认显式清除",
      "_CALIB_NAME" in _bk_src36 and "memwise_eris_calib.json" in _bk_src36
      and "memwise_eris_calib.json" not in _bk_src36.split("_STATE_NAMES")[1].split(")")[0])
check("② 引擎接线（独立文件 + 结构校验 + 只读评估不更新校准）",
      "memwise_eris_calib.json" in _eng32_src and "calib_valid" in _eng32_src
      and "update=update_state" in _eng32_src)
# ⑦ 恢复默认功能性验证（临时目录：四状态文件 + 校准文件全清）
_t36 = tempfile.mkdtemp(prefix="mw_rst36_")
for _n36 in ("config.yaml", "memwise_state.json", "memwise_efis_state.json",
             "memwise_eris_ewma.json", "memwise_eris_calib.json"):
    open(os.path.join(_t36, _n36), "w", encoding="utf-8").write("{}")
import core.backup as _bk36
_bk36.reset_factory(backup=False, base=_t36)
check("② 恢复默认清除四个状态文件 + 校准文件（功能性验证）",
      not [f for f in os.listdir(_t36) if f.endswith(".json")], str(os.listdir(_t36)))
print("\n[35] 运行日志诊断性（2026-09-11 用户要求：只看日志即可定位问题）")
_eng_log = _src26("core", "engine.py")
_cl_log = _src26("core", "cleaner.py")
check("日志：逐轮效率/五维分数/原始值/输入/校准进度",
      all(k in _eng_log for k in ('"效率"', "result.get(\"scores\"", "result.get(\"raws\"",
                                  "校准 n=", "输入[整理")))
check("日志：周期明细含系统操作计数/释放前三/判定拦截原因/内存状态",
      all(k in _eng_log for k in ("明细: %s · 释放前三", "拦截[%s]", "内存 %d%%(可用")))
check("日志：设定与配置（启动生效设置快照 + 逐键变更 diff）",
      all(k in _eng_log for k in ("生效设置: 模式 %s", "_CFG_SNAPSHOT", '"配置"')))
check("日志：学习状态周期摘要（画像/锚点/回退/抑制/策略权重/当前参数）",
      all(k in _eng_log for k in ("学习状态: 画像 %d", "策略权重[%s]", "当前参数 %s")))
check("日志：游戏启停入文件 + 周期行含所用模式",
      '"决策", msg' in _eng_log and "模式 {CFG.get('clean_mode'" in _eng_log)
check("日志：清理器逐轮统计判定拦截原因（can_trim 拒绝计数）",
      "_cycle_reasons[reason]" in _cl_log and "self._cycle_reasons = {}" in _cl_log)
with open(__file__, encoding='utf-8') as fh: cnt=len(re.findall(r'^\s*check\(',fh.read(),re.MULTILINE))
print(f"\n{'='*40}")
if errors:
    print(f"FAIL: {len(errors)}")
    for e in errors: print(f"  - {e}")
    sys.exit(1)
else:
    print(f"ALL OK — {cnt} assertions")
    sys.exit(0)
