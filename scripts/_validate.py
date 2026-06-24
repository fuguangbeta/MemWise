"""MemWise v1.0 验证脚本"""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.learner import Learner
from core.judger import Judger
from core.cleaner import Cleaner
from core.sniffer import Sniffer, ProcessSnapshot
from core import winapi

errors = []
def check(name, cond, detail=""):
    print(f"  [{'OK' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond: errors.append(name)

print("=== MemWise v1.0 验证 ===\n")

# 1. 模块导入
print("[1] 模块导入")
try:
    l = Learner()
    j = Judger(l, {"min_score":80,"never":[],"cooldown":300,"fail_cooldown":3600})
    c = Cleaner(j); s = Sniffer()
    check("所有核心模块 import", True)
except Exception as e: check("所有核心模块 import", False, str(e))

# 2. 评分算法
print("\n[2] 评分算法")
check("system 白名单 = 0", l.score("system") == 0)
check("explorer 白名单 = 0", l.score("explorer") == 0)
check("未知进程样本不足 = 40", l.score("unknown.exe") == 40)
for i in range(15):
    l.feed([ProcessSnapshot(1234,"notepad.exe",30<<20,100+i,0.1,False)])
    l.feed([ProcessSnapshot(5678,"chrome.exe",500<<20,1000+i,5.0,True,None)])
ns = l.score("notepad.exe"); cs = l.score("chrome.exe")
check(f"后台闲置 notepad 高分 = {ns}", ns >= 70)
check(f"前台活跃 chrome 低分 = {cs}", cs <= 60)
check("评分在 0-100 范围内", 0 <= ns <= 100 and 0 <= cs <= 100)
check("高风险 chrome 扣 20 分", cs < 80)

# 3. 持久化
print("\n[3] 持久化")
tmp = os.path.join(tempfile.gettempdir(), "mw_test.json")
try:
    check("save 成功", l.save(tmp))
    l2 = Learner.load(tmp)
    check("load 后进程数一致", len(l2.profiles) == len(l.profiles))
    check("load 后评分一致", l2.score("notepad.exe") == l.score("notepad.exe"))
    os.remove(tmp)
except Exception as e: check("持久化", False, str(e))

# 4. Judger 9层防护
print("\n[4] Judger 防护")
check("前台进程被拦截", not j.can_trim(ProcessSnapshot(0,"test.exe",100<<20,100,1.5,True,None), 90)[0])
check("低评分被拦截", not j.can_trim(ProcessSnapshot(0,"bg.exe",100<<20,100,0.1,False,None), 50)[0])
check("工作集太小被拦截", not j.can_trim(ProcessSnapshot(0,"tiny.exe",5<<20,100,0.1,False,None), 95)[0])
check("系统核心被拦截", not j.can_trim(ProcessSnapshot(0,"svchost",100<<20,100,0.1,False,"c:\\windows\\system32\\svchost.exe"), 95)[0])
check("路径安全校验", not j.can_trim(ProcessSnapshot(0,"bg.exe",100<<20,100,0.1,False,"c:\\windows\\system32\\bg.exe"), 85)[0])

# 5. Cleaner 批量接口
print("\n[5] Cleaner 接口")
check("trim_batch 存在", hasattr(c, "trim_batch") and callable(c.trim_batch))
check("trim_process 存在", hasattr(c, "trim_process") and callable(c.trim_process))
stats = c.summary()
check("stats 含 freed_mb", "freed_mb" in stats)
check("stats 含 freed_bytes", "freed_bytes" in stats)

# 6. winapi 扩展
print("\n[6] winapi 扩展")
check("is_admin 可调用", isinstance(winapi.is_admin(), bool))
m = winapi.get_memory_status()
check("get_memory_status 正常", m and "pct" in m)
check("get_process_path 可调用", callable(winapi.get_process_path))

# 7. 新增 winapi 函数
print("\n[7] 新增 winapi")
check("flush_modified_pages 可调用", callable(winapi.flush_modified_pages))
check("clear_system_file_cache 可调用", callable(winapi.clear_system_file_cache))
check("register_hotkey 可调用", callable(winapi.register_hotkey))
check("report_event 可调用", callable(winapi.report_event))
check("set_auto_start 可调用", callable(winapi.set_auto_start))
check("tray_add 可调用", callable(winapi.tray_add))
check("load_std_icon 可调用", callable(winapi.load_std_icon))
check("get_last_input_tick 可调用", callable(winapi.get_last_input_tick))

# 8. 清理分级
print("\n[8] Cleaner 分级")
check("cleaner.MODE_QUICK = 'quick'", getattr(c, 'MODE_QUICK', '') == 'quick')
check("cleaner.MODE_NORMAL = 'normal'", getattr(c, 'MODE_NORMAL', '') == 'normal')
check("cleaner.MODE_DEEP = 'deep'", getattr(c, 'MODE_DEEP', '') == 'deep')
check("cleaner.MODE_FULL = 'full'", getattr(c, 'MODE_FULL', '') == 'full')
check("clean_modified_pages 可调用", callable(getattr(c, 'clean_modified_pages', None)))
check("clear_file_cache 可调用", callable(getattr(c, 'clear_file_cache', None)))
check("optimize 可调用", callable(getattr(c, 'optimize', None)))
check("optimize 返回 dict", isinstance(c.optimize([], l, "quick"), dict))

# 总结
print(f"\n{'='*30}")
if errors: print(f"失败: {len(errors)} 项"); [print(f"  - {e}") for e in errors]; sys.exit(1)
else: print("全部通过 [OK]"); sys.exit(0)
