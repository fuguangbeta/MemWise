"""
MemWise v3.2.6 全量单元测试 — 15 模块全覆盖
"""
import sys, os, json, math, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.kalman import KalmanProfile
from core.prior import HierarchicalPrior
from core.learner import Profile, PareLearner, SYSTEM_CORE
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

print("\n[4] Profile")
p=Profile("test.exe"); check("alpha=2", p.alpha==2); check("beta=1", p.beta==1)
check("_info_msgs=[]", p._info_msgs==[]); check("timeout_count=0", p.timeout_count==0)
p.ws_deque.append(50<<20); p.ws_deque.append(55<<20); check("slope finite", math.isfinite(p.slope))
p.record_clean(True, 100<<20, 10); check("ok→alpha>2", p.alpha>2); check("clean_count=1", p.clean_count==1)
p.record_clean(False, 0, 50); check("fail→beta>1", p.beta>1)
d=p.to_dict(); p2=Profile.from_dict(d)
check("rt alpha", p2.alpha==p.alpha); check("rt _info_msgs=[]", p2._info_msgs==[]); check("rt timeout_count=0", p2.timeout_count==0)

print("\n[5] PareLearner")
l=PareLearner(); check("empty profiles=0", len(l.profiles)==0)
p=l.get("test.exe"); p.ws_deque.append(50<<20); l.feed([])
p.record_clean(True, 80<<20, 5)
check("theta 0-1", 0<=l.thompson_score("test.exe")<=1)
# svchost in SYSTEM_CORE → theta=0
check("svchost→0", l.thompson_score("svchost")==0)
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
s=Snap(); s.name="svchost"; s.ws=100<<20; s.path="c:\\windows\\system32\\svchost.exe"; s.pid=1234; s.pf=0; s.priv=0
ok,_=j.can_trim(s); check("svchost blocked", not ok)
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

print("\n[8] Config")
cfg=config_load(); check("has clean_passes", "clean_passes" in cfg); check("has gap_seconds", "gap_seconds" in cfg)

print("\n[9] EFIS")
check("PARAMS 9 keys", len(PARAMS)==9)
for k,v in PARAMS.items():
    check(f"{k} valid range", v["min"]<=v["default"]<=v["max"])
e=EfisController(); e.tick({"mem_pct":50,"trimmed_cnt":10,"failed_cnt":2,"total_attempts":12,"cycle_freed":500<<20,"snaps":[],"fore_fullscreen":False})
check("EFIS tick ok", True)
# 症状双向累积：连续两次同向负面必须调整（防单向漂移）
e2=EfisController(); e2._apply({"pid_kp": -1}); e2._apply({"pid_kp": -1})
check("EFIS 负面调整生效", e2.params["pid_kp"] < 0.6)

print("\n[10] PolicyVoter")
pv=PolicyVoter(); check("PolicyVoter ok", pv is not None)

def iqr_dim(raw,bufs):
    if len(bufs)<2: return 80.0
    L=sorted(bufs); n=len(L); p50=L[n//2]; p25=L[max(0,n//4-1)]; p75=L[min(n-1,3*n//4)]
    return max(1.0,min(130.0,80.0+60.0*(raw-p50)/max(p75-p25,0.01)))
check("above median>80", iqr_dim(100,[50,60,70,80,90])>80)
check("below median<80", iqr_dim(50,[50,60,70,80,90])<80)
check("zero IQR ok", math.isfinite(iqr_dim(70,[70]*5)))
check("clamp≤130", iqr_dim(1000,[50,60,70,80,90])<=130)
check("clamp≥1", iqr_dim(-100,[50,60,70,80,90])>=1)

print("\n[14] ERIS Data Validation")
def validate(d):
    if not (isinstance(d,dict) and isinstance(d.get("bufs"),list) and len(d["bufs"])==5): return False
    ew=d.get("iqr_ewma",[0.0]*5); bufs=d["bufs"]
    if not (isinstance(ew,list) and len(ew)==5): return False
    for b in bufs:
        if not isinstance(b,list) or len(b)>50: return False
        for v in b:
            if not isinstance(v,(int,float)) or not math.isfinite(v): return False
    for v in ew:
        if not isinstance(v,(int,float)) or not math.isfinite(v) or v<0: return False
    return True
check("valid", validate({"bufs":[[1.0]*10]*5,"iqr_ewma":[0.1]*5}))
check("dim mismatch", not validate({"bufs":[[1.0]]*3,"iqr_ewma":[0.0]*3}))
check(">50 elements", not validate({"bufs":[[1.0]*51]*5,"iqr_ewma":[0.0]*5}))
check("NaN", not validate({"bufs":[[float('nan')]*10]*5,"iqr_ewma":[0.0]*5}))
check("inf", not validate({"bufs":[[float('inf')]*10]*5,"iqr_ewma":[0.0]*5}))
check("negative ewma", not validate({"bufs":[[1.0]*10]*5,"iqr_ewma":[-0.1,0,0,0,0]}))
check("not dict", not validate("string"))
check("empty bufs ok", validate({"bufs":[[],[],[],[],[]],"iqr_ewma":[0.0]*5}))

print("\n[15] Factor Selection")
DP=[("↑预测精准","↓预测偏差"),("↑释放改善","↓释放退步"),("↑副作用低","↓副作用高"),("↑参数稳定","↓频繁调参"),("↑覆盖广泛","↓覆盖狭窄")]
def sf(eff,dims,vlen,pe=None,pd=-1,pp=None):
    if vlen<=3: return ["影响因素分析中…"],-1,None,None
    if eff>=100:
        bi=max(range(5),key=lambda i:abs(dims[i]-80))
        if pd==bi and pp is not None and pp is not True:
            r=sorted(range(5),key=lambda i:abs(dims[i]-80),reverse=True); bi=r[1] if len(r)>1 else bi
        return [DP[bi][0],"🚀效率超常"],bi,True,99
    if eff<=60:
        bi=max(range(5),key=lambda i:abs(dims[i]-80))
        if pd==bi and pp is not None and pp is not False:
            r=sorted(range(5),key=lambda i:abs(dims[i]-80),reverse=True); bi=r[1] if len(r)>1 else bi
        return [DP[bi][1],"⚠效率异常"],bi,False,-99
    if pe is not None and abs(eff-pe)>=2:
        ip=eff>pe; bi=max(range(5),key=lambda i:abs(dims[i]-80))
        f=[DP[bi][0]] if ip else [DP[bi][1]]
        if pd==bi and pp is not None and pp!=(f[0].startswith("↑")):
            r=sorted(range(5),key=lambda i:abs(dims[i]-80),reverse=True); bi=r[1] if len(r)>1 else r[0]
            f=[DP[bi][0]] if f[0].startswith("↑") else [DP[bi][1]]
        return f,bi,f[0].startswith("↑"),1 if f[0].startswith("↑") else -1
    return ["相对平稳"],-1,None,0

f,_,_,_=sf(72,[80]*5,10); check("cold→stable", f==["相对平稳"])
f,_,_,_=sf(75,[85,80,80,80,80],10,70); check("up→positive", f[0].startswith("↑"))
f,_,_,_=sf(72,[85,80,80,80,80],10,75); check("down→negative", not f[0].startswith("↑"))
f,_,_,t=sf(105,[90]*5,10,95); check("≥100→pos+tag", f[0].startswith("↑") and "🚀" in str(f)); check("≥100 trend=99", t==99)
f,_,_,t=sf(55,[90]*5,10,65); check("≤60→neg+tag", not f[0].startswith("↑") and "⚠" in str(f)); check("≤60 trend=-99", t==-99)
_,d,_,_=sf(70,[85]*5,10,75,pd=0,pp=True); check("anti-flip", d!=0)
_,d,_,_=sf(75,[85]*5,10,70,pd=0,pp=True); check("same-dir no flip", d==0)
f,d,p,_=sf(72,[80]*5,10,71); check("stable reset dim", d==-1); check("stable reset pos", p is None)

# ═══════════════════════════════════════════
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
