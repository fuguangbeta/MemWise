"""MemWise v1.6 验证脚本 — 适配当前 API"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.learner import PareLearner as Learner
from core.judger import PareJudger as Judger
from core.cleaner import PareCleaner as Cleaner
from core.sniffer import Sniffer, ProcessSnapshot
from core import winapi

errors = []
def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond: errors.append(name)

print("=== MemWise v1.6 验证 ===\n")

# 1. 模块导入
print("[1] 模块导入")
try:
    l = Learner()
    j = Judger(l, {"kp":0.6,"ki":0.15,"kd":0.1,"target_usage":60,"never":[]})
    c = Cleaner(j); s = Sniffer()
    check("所有核心模块 import", True)
except Exception as e: check("所有核心模块 import", False, str(e))

# 2. Thompson Sampling 评分
print("\n[2] Thompson Sampling 评分")
check("system 白名单 = 0.0", l.thompson_score("system") == 0.0)
check("explorer 白名单 = 0.0", l.thompson_score("explorer") == 0.0)
check("未知进程 = 0.35 (探针阈值)", l.thompson_score("unknown.exe") == 0.35)

# 喂入样本：notepad 后台低 CPU（积极），chrome 前台高 CPU（消极）
for i in range(15):
    l.feed([ProcessSnapshot(1234,"notepad.exe",30<<20,100+i,0.1,False)])
    l.feed([ProcessSnapshot(5678,"chrome.exe",500<<20,1000+i,5.0,True,None)])
# 记录几次清理结果：notepad 成功数次 → alpha 上升，chrome 失败 → beta 上升
nt = l.get("notepad.exe"); ch = l.get("chrome.exe")
nt.record_clean(True, 10<<20, 5)   # 成功 α+1
nt.record_clean(True, 8<<20, 3)    # 成功 α+1
nt.record_clean(True, 12<<20, 7)   # 成功 α+1 → alpha=5
ch.record_clean(False, 0, 50)      # 失败 β+1
ch.record_clean(False, 0, 80)      # 失败 β+1 → beta=3

ns = l.thompson_score("notepad.exe"); cs = l.thompson_score("chrome.exe")
check(f"notepad theta > 未知进程阈值", ns > 0.35)
check("notepad theta 在 [0,1] 范围内", 0 <= ns <= 1)
check("chrome theta 在 [0,1] 范围内", 0 <= cs <= 1)
# 比较期望值而非采样值，避免随机波动
nt_mean = nt.alpha / (nt.alpha + nt.beta)  # 5/6 ≈ 0.833
ch_mean = ch.alpha / (ch.alpha + ch.beta)  # 2/5 = 0.4
check("notepad 均值 > chrome 均值 (α/β)", nt_mean > ch_mean)

# 3. 持久化
print("\n[3] 持久化")
tmp = os.path.join(tempfile.gettempdir(), "mw_test.json")
try:
    check("save 成功", l.save(tmp))
    l2 = Learner.load(tmp)
    check("load 后进程数一致", len(l2.profiles) == len(l.profiles))
    p1 = l.get_profile("notepad.exe"); p2 = l2.get_profile("notepad.exe")
    check("load 后 alpha 一致", p1 and p2 and p1.alpha == p2.alpha)
    check("load 后 beta 一致", p1 and p2 and p1.beta == p2.beta)
    check("load 后 WS 样本数一致", p1 and p2 and len(p1.ws_deque) == len(p2.ws_deque))
    os.remove(tmp)
except Exception as e: check("持久化", False, str(e))

# 4. Judger 防护
print("\n[4] Judger 防护")
check("前台进程被拦截 (agg=0)",
    not j.can_trim(ProcessSnapshot(0,"test.exe",100<<20,100,1.5,True,None))[0])
check("低 θ 进程被拦截",
    not j.can_trim(ProcessSnapshot(0,"bg.exe",100<<20,100,0.1,False,None))[0])
check("工作集太小被拦截 (<10MB)",
    not j.can_trim(ProcessSnapshot(0,"tiny.exe",5<<20,100,0.1,False,None))[0])
check("系统核心被拦截 (svchost)",
    not j.can_trim(ProcessSnapshot(0,"svchost",100<<20,100,0.1,False,"c:\\windows\\system32\\svchost.exe"))[0])
check("系统目录路径安全拦截",
    not j.can_trim(ProcessSnapshot(0,"bg.exe",100<<20,100,0.1,False,"c:\\windows\\system32\\bg.exe"))[0])

# 5. Cleaner 接口
print("\n[5] Cleaner 接口")
check("trim_batch 可调用", callable(c.trim_batch))
check("optimize 可调用", callable(c.optimize))
stats = c.summary()
check("summary 含 freed_bytes", "freed_bytes" in stats)
check("summary 含 freed_mb", "freed_mb" in stats)
check("optimize 返回 dict", isinstance(c.optimize([], l, "quick"), dict))

# 6. winapi 基础
print("\n[6] winapi 基础")
check("is_admin 返回 bool", isinstance(winapi.is_admin(), bool))
m = winapi.get_memory_status()
check("get_memory_status 正常", m and "pct" in m and "total" in m)
check("get_process_path 可调用", callable(winapi.get_process_path))

# 7. winapi 扩展
print("\n[7] winapi 扩展")
check("empty_standby 可调用", callable(winapi.empty_standby))
check("flush_modified_pages 可调用", callable(winapi.flush_modified_pages))
check("clear_system_file_cache 可调用", callable(winapi.clear_system_file_cache))
check("register_hotkey 可调用", callable(winapi.register_hotkey))
check("report_event 可调用", callable(winapi.report_event))
check("set_auto_start 可调用", callable(winapi.set_auto_start))
check("tray_add 可调用", callable(winapi.tray_add))
check("create_memwise_icon 可调用", callable(winapi.create_memwise_icon))
check("get_last_input_tick 可调用", callable(winapi.get_last_input_tick))

# 8. Cleaner 分层
print("\n[8] Cleaner 分层")
check("clean_modified_pages 可调用", callable(c.clean_modified_pages))
check("clear_file_cache 可调用", callable(c.clear_file_cache))
check("clean_standby 可调用", callable(c.clean_standby))
check("clean_standby_low 可调用", callable(c.clean_standby_low))
check("clean_combine_lists 可调用", callable(c.clean_combine_lists))
check("clean_deep_standby 可调用", callable(c.clean_deep_standby))
check("optimize 支持 mode=normal", c.optimize([], l, "normal")["mode"] == "normal")
check("optimize 支持 mode=deep", c.optimize([], l, "deep")["mode"] == "deep")
check("optimize 支持 mode=quick", c.optimize([], l, "quick")["mode"] == "quick")
check("optimize 支持 mode=full", c.optimize([], l, "full")["mode"] == "full")

# 9. Learner 辅助指标
print("\n[9] Learner 辅助指标")
check("notepad ROI 存在", l.get_roi("notepad.exe") > 0)
check("notepad slope 存在", isinstance(l.get_slope("notepad.exe"), (int, float)))
check("get_profile 返回 Profile", l.get_profile("notepad.exe") is not None)
check("get_confidence 0~1", 0 <= l.get_confidence("notepad.exe") <= 1)

# 总结
print(f"\n{'='*30}")
if errors: print(f"失败: {len(errors)} 项"); [print(f"  - {e}") for e in errors]; sys.exit(1)
else: print("全部通过 [OK]"); sys.exit(0)
