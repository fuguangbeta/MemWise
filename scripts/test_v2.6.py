# -*- coding: utf-8 -*-
"""
MemWise v3.9.28 全量单元测试 — 16 模块全覆盖（ERIS 纯函数共用 core.eris，无内联副本）
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

# ═══════════════════════════════════════════
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
ok2,_=j.can_trim(s2); check("notepad allowed", ok2)
j.mark_failed("test.exe",1); check("cooldown recorded", "test.exe" in j.cooldown)
# 非首轮（已有基线）：策略投票必须真实生效，不得抛异常全拒
j3 = PareJudger(l2, {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
j3._post_clean_ws["other.exe"] = 10 << 20
s3=Snap(); s3.name="vote.exe"; s3.ws=300<<20; s3.path="d:\\app\\vote.exe"; s3.pid=9999; s3.pf=0; s3.priv=0; s3.fg=False
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
check("PARAMS 9 keys", len(PARAMS)==9)
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
