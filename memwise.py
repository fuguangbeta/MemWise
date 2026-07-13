"""
MemWise v1.7 PARES —— 智能内存看护
进阶算法: 上下文增强 Thompson + PID 控制 + 3层清理
全程不杀进程、不写文件、不改代码。
"""

import os, sys, time

from core.learner import PareLearner as Learner
from core.judger import PareJudger as Judger
from core.cleaner import PareCleaner as Cleaner
from core.sniffer import Sniffer
from core import winapi
from core.config import load as _load_cfg
from core.config import get_state_path
import core.config as _config

SEP = "─" * 50
STATE_PATH = get_state_path()

CFG = _load_cfg()

def _gb(b): return b / (1 << 30)
def _mb(b): return b / (1 << 20)

def _mem_or_none():
    m = winapi.get_memory_status()
    if not m: print("无法获取内存状态")
    return m

def _build_pipeline():
    learner = Learner.load(STATE_PATH)
    jcfg = {"kp": CFG.get("kp", 0.6), "ki": CFG.get("ki", 0.15),
            "kd": CFG.get("kd", 0.1), "target_usage": CFG.get("target_usage", 60),
            "never": CFG.get("never",[])}
    judger = Judger(learner, jcfg)
    return learner, judger, Cleaner(judger)

def cmd_status(_):
    m = _mem_or_none()
    if not m: return
    print(f" 总内存: {_gb(m['total']):.1f} GB")
    print(f" 已用:   {_gb(m['used']):.1f} GB ({m['pct']}%)")
    print(f" 可用:   {_gb(m['avail']):.1f} GB")
    print(f" 权限:   {'管理员' if winapi.is_admin() else '普通用户'}")
    if os.path.isfile(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
            print(f" 画像:   {len(meta.get('profiles',{}))} 个进程已学习")
        except Exception:
            pass

def cmd_learn(args):
    minutes = int(args[0]) if args and args[0].isdigit() else 10
    print(f"学习模式 ({minutes} 分钟) — 仅观察不动手")
    sniffer = Sniffer(); learner = Learner.load(STATE_PATH)
    try:
        for i in range(minutes * 12):
            snaps = sniffer.snapshot(); learner.feed(snaps)
            sampled = sum(p.total_samples for p in learner.profiles.values())
            sys.stdout.write(f"\r⏳ {i*5}s | 进程 {len(snaps)} | 画像 {len(learner.profiles)} | 样本 {sampled}")
            sys.stdout.flush(); time.sleep(5)
    except KeyboardInterrupt: print("\n中断")
    finally: learner.save(STATE_PATH); print(f"\n学习数据已保存")
    print(f"\n{SEP}")
    print(f"{'进程名':<24} {'θ':>4} {'WS':>8} {'样本':>5} {'ROI':>6}")
    print(SEP)
    for name, roi, theta, p in learner.top(25):
        ws = _mb(p.ws_deque[-1]) if p.ws_deque else 0
        print(f"{name:<24} {theta:>4.2f} {ws:>6.0f}MB {p.total_samples:>5} {roi:>6.1f}")

def cmd_optimize(args):
    mode = CFG.get("clean_mode", "normal")
    i = 0
    while i < len(args):
        if args[i] == "--quick": mode = "quick"
        elif args[i] == "--mode" and i+1 < len(args): mode = args[i+1]; i += 1
        i += 1
    print(f"{mode.title()} 优化模式")
    m0 = _mem_or_none()
    if not m0: return
    print(f"优化前: {_gb(m0['avail']):.1f}GB 可用 ({m0['pct']}%)")
    learner, judger, cleaner = _build_pipeline()
    sniffer = Sniffer()
    print("  ─ 采集进程基线...")
    snaps = []
    for i in range(3):
        snaps = sniffer.snapshot(); learner.feed(snaps)
        if i < 2: time.sleep(2)
    print(f"  ─ 观察到 {len(snaps)} 个进程")
    print("  ─ 执行清理...")
    result = cleaner.optimize(snaps, learner, mode)
    stats = cleaner.summary()
    trimmed = [t for t in result.get("layer2", []) if t[1]]
    print(f"\n释放: {stats['freed_mb']} MB | 待机缓存={stats['standby']} "
          f"已修改页={stats['modified']} 压缩={stats['compress']} "
          f"文件缓存={stats['filecache']} | "
          f"整理={stats['ws_trim']} | Probe={stats['probe']} | 反馈异常={stats['failed_feedback']}")
    if trimmed:
        for snap, ok, freed, reason in trimmed[:20]:
            print(f"  ✓ {snap.name} (PID={snap.pid}) {_mb(freed):.0f}MB — {reason}")
        if len(trimmed) > 20: print(f"  ... 还有 {len(trimmed)-20} 个")
    probe_n = len(result.get("probe", []))
    if probe_n:
        print(f"  Probe: {probe_n} 个进程微型试探完成")
    winapi.report_event("MemWise", f"优化完成: {stats['freed_mb']}MB 释放, {len(trimmed)} 进程")
    learner.save(STATE_PATH)

def cmd_daemon(args):
    print("MemWise PARES 守护 (Ctrl+C 停止)")
    learner, judger, cleaner = _build_pipeline()
    sniffer = Sniffer()
    interval = CFG.get("interval", 30)
    mode = CFG.get("clean_mode", "normal")
    scheduled = CFG.get("scheduled_clean")
    i = 0
    while i < len(args):
        if args[i] == "--scheduled" and i+1 < len(args): scheduled = args[i+1]; i += 1
        elif args[i] == "--mode" and i+1 < len(args): mode = args[i+1]; i += 1
        i += 1
    last_sched_day = -1
    tick = 0
    try:
        while True:
            tick += 1
            tick_start = time.time()
            m = _mem_or_none()
            if not m: time.sleep(interval); continue
            snaps = sniffer.snapshot(); learner.feed(snaps)
            agg = judger.update_pressure(m["pct"])
            ops = CFG.get("clean_operations")
            result = cleaner.optimize(snaps, learner, mode, operations=ops, aggressiveness=agg)
            l2_results = result.get("layer2", [])
            probe_results = result.get("probe", [])
            agg = result.get("aggressiveness", agg)
            # 配置热加载：每 2 tick 检查 config.yaml 是否变更
            if tick % 2 == 0:
                try:
                    mtime = os.path.getmtime(_config.CONFIG_PATH)
                    if mtime != getattr(cmd_daemon, "_cfg_mtime", 0):
                        cmd_daemon._cfg_mtime = mtime
                        CFG.update(_load_cfg())
                        mode = CFG.get("clean_mode", "normal")
                        interval = CFG.get("interval", 30)
                except Exception:
                    pass
            if scheduled:
                try:
                    sh, sm = map(int, scheduled.split(":"))
                    lt = time.localtime()
                    if lt.tm_hour == sh and lt.tm_min == sm and lt.tm_yday != last_sched_day:
                        last_sched_day = lt.tm_yday
                        print(f"\n⏰ 定时清理触发 ({scheduled})")
                        cleaner.optimize(snaps, learner, mode)
                except Exception:
                    pass
            if tick % 10 == 0: judger.purge_expired(); learner.save(STATE_PATH); import gc; gc.collect()
            stats = cleaner.summary()
            sched_info = f" | 定时 {scheduled}" if scheduled else ""
            sys.stdout.write(f"\r内存 {m['pct']}% | 清理强度={agg:.2f} | 可用 {_gb(m['avail']):.1f}GB | "
                             f"释放 {stats['freed_mb']}MB | SB={stats['standby']} MP={stats['modified']} "
                             f"压缩={stats['compress']} 文件缓存={stats['filecache']} | "
                             f"整理 {stats['ws_trim']}{sched_info} | {tick*interval}s")
            sys.stdout.flush()
            elapsed = time.time() - tick_start
            time.sleep(max(0.5, interval - elapsed))
    except KeyboardInterrupt:
        learner.save(STATE_PATH)
        stats = cleaner.summary()
        print(f"\n停止 | 累计释放 {stats['freed_mb']} MB | "
              f"待机缓存={stats['standby']} | 整理={stats['ws_trim']}")

def cmd_reset(_):
    print("恢复出厂设置...")
    from core.config import CONFIG_PATH
    for p in [STATE_PATH, CONFIG_PATH]:
        if os.path.isfile(p):
            bak = p + ".bak"
            os.replace(p, bak)
            print(f"  已备份: {os.path.basename(bak)}")
    print("完成。下次启动使用默认配置。")
    winapi.report_event("MemWise", "已恢复出厂设置")

def cmd_auto_start(args):
    if not args:
        print("用法: memwise.py auto-start on|off")
        return
    if getattr(sys, "frozen", False):
        target = sys.executable
        arg = ""
        wd = os.path.dirname(sys.executable)
    else:
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
        target = pythonw if os.path.isfile(pythonw) else sys.executable
        arg = os.path.abspath(__file__) + " daemon --minimized"
        wd = os.path.dirname(os.path.abspath(__file__))
    if args[0] == "on":
        ok = winapi.set_auto_start("MemWise", target, arg, wd)
        print(f"开机自启 {'✓ 已启用' if ok else '✗ 启用失败'}")
    elif args[0] == "off":
        ok = winapi.remove_auto_start("MemWise")
        print(f"开机自启 {'✓ 已关闭' if ok else '✗ 关闭失败'}")

def cmd_install_service(args):
    import subprocess
    exe = sys.executable
    script = os.path.abspath(__file__)
    task_name = "MemWiseDaemon"
    action = f'"{exe}" "{script}" daemon --minimized'
    if args and args[0] == "remove":
        subprocess.run(["schtasks", "/delete", "/tn", task_name, "/f"],
                       capture_output=True, shell=True)
        print("Scheduled Task 已移除")
        return
    cmd = ["schtasks", "/create", "/tn", task_name, "/tr", action,
           "/sc", "onstart", "/ru", "SYSTEM", "/rl", "highest", "/f"]
    r = subprocess.run(cmd, capture_output=True, shell=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode == 0:
        print("✓ Scheduled Task 已安装 (系统启动时自动运行)")
        winapi.report_event("MemWise", "服务模式已安装 (Scheduled Task)")
    else:
        print(f"✗ 安装失败 (需管理员权限): {r.stderr.decode('gbk','ignore').strip()}")

def cmd_profile(args):
    if not args: print("用法: memwise profile <pid>"); return
    try: pid = int(args[0])
    except: print("PID 必须是数字"); return
    mem = winapi.get_process_memory(pid)
    if not mem: print(f"PID {pid} 不存在"); return
    name = next((n for p,n,_ in winapi.enum_processes() if p==pid), "?")
    path = winapi.get_process_path(pid)
    p = Learner.load(STATE_PATH).get_profile(name)
    print(f"PID {pid} — {name}")
    if path: print(f"  路径:    {path}")
    print(f"  工作集:  {_mb(mem['ws']):.1f} MB")
    print(f"  页面错误: {mem['pf']}")
    if p:
        print(f"  Thompson θ: {p.thompson_theta:.2f}")
        print(f"  ROI:        {p.roi:.2f}")
        print(f"  Z-score:    {p.z_score:.2f}")
        print(f"  趋势:       {p.slope:.1f} bytes/tick")
        print(f"  泄漏:       {'⚠ 疑似' if p.leak_suspect else '正常'}")
        print(f"  清理:       {p.clean_count} 次 | Probe: {p.probe_ok}/{p.probe_ok+p.probe_fail}")

def main():
    if len(sys.argv) < 2:
        print("MemWise v1.7 PARES —— 智能内存看护")
        print("用法: py memwise.py <命令> [参数]")
        print("  status                    内存状态")
        print("  learn [分钟]              学习进程行为 (默认10分钟)")
        print("  optimize [--mode q|n|d|f] 执行优化")
        print("  daemon [--scheduled HH:MM] 守护模式")
        print("         [--mode q|n|d|f]")
        print("  profile <pid>             进程详情 (含 PARES 指标)")
        print("  auto-start on|off         开机自启")
        print("  service [remove]          安装/移除 Scheduled Task 服务")
        print("  reset                     恢复出厂设置")
        return
    cmd = sys.argv[1]; args = sys.argv[2:]
    cmds = {"status":cmd_status,"learn":cmd_learn,"optimize":cmd_optimize,
            "daemon":cmd_daemon,"profile":cmd_profile,
            "reset":cmd_reset,"auto-start":cmd_auto_start,"service":cmd_install_service}
    fn = cmds.get(cmd)
    if fn: fn(args)
    else: print(f"未知命令: {cmd}")

if __name__ == "__main__":
    main()