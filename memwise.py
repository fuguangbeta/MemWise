"""
MemWise v4.4.021 PARES —— 智能内存看护
进阶算法: 上下文增强 Thompson + PID 控制 + 3层清理
全程不杀进程、不写文件、不改代码。
"""

import ctypes, json, os, sys, time

from core.learner import PareLearner as Learner
from core.judger import PareJudger as Judger
from core.cleaner import PareCleaner as Cleaner
from core.sniffer import Sniffer
from core import winapi
from core.config import load as _load_cfg
from core.config import get_state_path
from core.i18n import tr, tr_msg, set_language  # 界面语言（跟随 GUI 设置）
import core.config as _config

SEP = "─" * 50
STATE_PATH = get_state_path()

CFG = _load_cfg()
set_language(CFG.get("language", "zh_CN"))

def _gb(b): return b / (1 << 30)
def _mb(b): return b / (1 << 20)

def _mem_or_none():
    m = winapi.get_memory_status()
    if not m: print(tr("无法获取内存状态"))
    return m

def _build_pipeline():
    learner = Learner.load(STATE_PATH)
    jcfg = {"kp": CFG.get("kp", 0.6), "ki": CFG.get("ki", 0.15),
            "kd": CFG.get("kd", 0.1), "target_usage": CFG.get("target_usage", 60),
            "never": CFG.get("never",[]),
            "game_processes": CFG.get("game_processes",[]),
            "clean_passes": CFG.get("clean_passes", 4),
            "efis_params": CFG.get("efis_params",{})}
    # 与 GUI 同权威源（2026-08-15 审查）：EFIS 调参状态以 efis_state.json 为准，
    # config.yaml 可能滞后——CLI 与 GUI 优化参数一致；按当前清理模式取对应参数组
    try:
        from core.efis import EfisController
        _efis = EfisController(STATE_PATH)
        _efis.set_mode(CFG.get("clean_mode", "normal"))
        jcfg["efis_params"] = _efis.get_params()
    except Exception:
        pass
    judger = Judger(learner, jcfg)
    # Kalman 观测噪声同步（与 GUI 启动同款）：新画像与已有画像一并生效
    try:
        _kr = jcfg["efis_params"].get("kalman_r", 5.0)
        learner._kalman_r = _kr
        for _p in learner.profiles.values():
            _p.kalman.r = _kr
    except Exception:
        pass
    return learner, judger, Cleaner(judger)

def cmd_status(_):
    m = _mem_or_none()
    if not m: return
    print(tr(" 总内存: ") + f"{_gb(m['total']):.1f} GB")
    print(tr(" 已用:   ") + f"{_gb(m['used']):.1f} GB ({m['pct']}%)")
    print(tr(" 可用:   ") + f"{_gb(m['avail']):.1f} GB")
    print(tr(" 权限:   ") + (tr("管理员") if winapi.is_admin() else tr("普通用户")))
    if os.path.isfile(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                meta = json.load(f)
            print(tr(" 画像:   ") + f"{len(meta.get('profiles',{}))} " + tr("个进程已学习"))
        except Exception:
            pass

def cmd_learn(args):
    minutes = int(args[0]) if args and args[0].isdigit() else 10
    print(tr_msg(f"学习模式 ({minutes} 分钟) — 仅观察不动手"))
    # 学习模式不需要进程路径（cleaner 决策才用）——关掉路径采集省快照开销
    sniffer = Sniffer(collect_path=False); learner = Learner.load(STATE_PATH)
    try:
        for i in range(minutes * 12):
            snaps = sniffer.snapshot(); learner.feed(snaps)
            sampled = sum(p.total_samples for p in learner.profiles.values())
            sys.stdout.write(tr_msg(f"\r⏳ {i*5}s | 进程 {len(snaps)} | 画像 {len(learner.profiles)} | 样本 {sampled}"))
            sys.stdout.flush(); time.sleep(5)
    except KeyboardInterrupt: print("\n" + tr("中断"))
    finally: learner.save(STATE_PATH); print(f"\n{tr('学习数据已保存')}")
    print(f"\n{SEP}")
    print(f"{tr('进程名'):<24} {'θ':>4} {'WS':>8} {tr('样本'):>5} {'ROI(MB/PF)':>10}")
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
    if mode not in ("quick", "normal", "deep", "full"):
        print(tr_msg(f"未知模式 {mode}，回退 normal"))
        mode = "normal"
    print(f"{mode.title()}{tr(' 优化模式')}")
    m0 = _mem_or_none()
    if not m0: return
    print(tr_msg(f"优化前: {_gb(m0['avail']):.1f}GB 可用 ({m0['pct']}%)"))
    learner, judger, cleaner = _build_pipeline()
    # 命令行模式与参数组对齐（2026-08-16 模式参数组，审查 P7）：
    # --mode 覆盖 CFG 时按命令行模式取对应参数组，否则 CLI 用 CFG 模式参数
    if mode != CFG.get("clean_mode", "normal"):
        try:
            from core.efis import EfisController
            _e = EfisController(STATE_PATH)
            _e.set_mode(mode)
            judger.cfg["efis_params"] = _e.get_params()
        except Exception:
            pass
    sniffer = Sniffer()
    print(tr("  ─ 采集进程基线..."))
    snaps = []
    for i in range(3):
        snaps = sniffer.snapshot(); learner.feed(snaps)
        if i < 2: time.sleep(2)
    print(tr_msg(f"  ─ 观察到 {len(snaps)} 个进程"))
    print(tr("  ─ 执行清理..."))
    cleaner._manual_run = True  # 手动优化：跳过自动化保守门，保留实时安全门（CPU/IO 活跃）
    try:
        freed0 = cleaner.summary()['freed_mb']  # 释放量基线（标量总和口径）
        result = cleaner.optimize(snaps, learner, mode, operations=CFG.get("clean_operations"))
    finally:
        cleaner._manual_run = False
    stats = cleaner.summary()
    trimmed = [t for t in result.get("layer2", []) if t[1]]
    net = result.get("net_freed", 0)
    released = max(0.0, stats['freed_mb'] - freed0)
    print(tr_msg(f"\n本次释放: {released:.0f} MB · 内存净下降: {_mb(net):.0f} MB | 累计释放: {stats['freed_mb']} MB"))
    print(tr_msg(f"待机缓存={stats['standby']} 已修改页={stats['modified']} "
          f"文件缓存={stats['filecache']} | "
          f"整理={stats['ws_trim']} | Probe={stats['probe']} | 反馈异常={stats['failed_feedback']}"))
    if trimmed:
        for snap, ok, freed, reason in trimmed[:20]:
            # reason 经 tr_msg 翻译（can_trim 理由串键全覆盖；f-string 变量插值是
            # [26] 字面量静态扫描的盲区，2026-09-06 审查 F7 补包裹）
            print(f"  ✓ {snap.name} (PID={snap.pid}) {_mb(freed):.0f}MB — {tr_msg(reason)}")
        if len(trimmed) > 20: print(tr_msg(f"  ... 还有 {len(trimmed)-20} 个进程"))
    probe_n = len(result.get("probe", []))
    if probe_n:
        print(tr_msg(f"  Probe: {probe_n} 个进程微型试探完成"))
    winapi.report_event("MemWise", tr_msg(f"优化完成: {stats['freed_mb']}MB 释放, {len(trimmed)} 进程"))
    learner.save(STATE_PATH)

def cmd_daemon(args):
    # 命令行守护互斥（2026-09-06 审查 F3）：防 CLI 双开与 GUI 守护并发——双进程同时
    # 写同一状态文件，进程内锁不跨进程会交错损坏画像唯一副本
    from core.engine import DAEMON_MUTEX_NAME
    _daemon_mutex = ctypes.windll.kernel32.CreateMutexW(None, False, DAEMON_MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() in (0xB7, 5):
        print(tr("命令行守护已在运行，本实例退出"))
        return
    print(tr("MemWise PARES 守护 (Ctrl+C 停止)"))
    learner, judger, cleaner = _build_pipeline()
    sniffer = Sniffer()
    # 持有 EFIS 实例（2026-08-16 模式参数组，审查 P8）：模式/配置热加载时按模式取参，
    # 不依赖 _build_pipeline 的局部实例
    try:
        from core.efis import EfisController
        _efis = EfisController(STATE_PATH)
        _efis.set_mode(CFG.get("clean_mode", "normal"))
    except Exception:
        _efis = None
    interval = CFG.get("interval", 60)  # 与 DEFAULT_CFG 一致（原 30 系历史默认值残留）
    mode = CFG.get("clean_mode", "normal")
    i = 0
    while i < len(args):
        if args[i] == "--mode" and i+1 < len(args): mode = args[i+1]; i += 1
        elif args[i] == "--minimized": pass  # 自启兼容参数（CLI 无窗口，忽略）
        i += 1
    # --mode 显式覆盖（2026-08-30 审查）：命令行模式优先于配置文件——立即对齐 EFIS
    # 参数组（原仅在配置热加载时对齐，且热加载会用 CFG 模式覆盖 --mode 显式意图）
    _cli_mode_override = mode != CFG.get("clean_mode", "normal")
    if _efis is not None and _cli_mode_override:
        _efis.set_mode(mode)
        judger.cfg["efis_params"] = _efis.get_params()
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
                        if not _cli_mode_override:
                            mode = CFG.get("clean_mode", "normal")
                        interval = CFG.get("interval", 60)
                        # 同步 judger 运行配置（排除列表/游戏名单/清理深度即时生效）
                        judger.cfg["never"] = CFG.get("never", [])
                        judger.cfg["game_processes"] = CFG.get("game_processes", [])
                        judger.cfg["clean_passes"] = CFG.get("clean_passes", 4)
                        # EFIS 参数按当前模式取（状态文件权威，config 快照不回灌，审查 P3/P8）
                        if _efis is not None:
                            _efis.set_mode(mode)
                            judger.cfg["efis_params"] = _efis.get_params()
                except Exception:
                    pass
            if tick % 10 == 0: judger.purge_expired(); learner.save(STATE_PATH); import gc; gc.collect()
            stats = cleaner.summary()
            sys.stdout.write(tr_msg(f"\r内存 {m['pct']}% | 清理强度={agg:.2f} | 可用 {_gb(m['avail']):.1f}GB | "
                             f"释放 {stats['freed_mb']}MB | SB={stats['standby']} MP={stats['modified']} "
                             f"文件缓存={stats['filecache']} | "
                             f"整理 {stats['ws_trim']} | {tick*interval}s"))
            sys.stdout.flush()
            elapsed = time.time() - tick_start
            time.sleep(max(0.5, interval - elapsed))
    except KeyboardInterrupt:
        learner.save(STATE_PATH)
        stats = cleaner.summary()
        print(tr_msg(f"\n停止 | 累计释放 {stats['freed_mb']} MB | "
              f"待机缓存={stats['standby']} | 整理={stats['ws_trim']}"))

def cmd_reset(_):
    print(tr("恢复出厂设置..."))
    # 守护互斥（2026-09-06 任务3）：CLI daemon 运行中拒绝（防写回竞态，与 GUI 同语义）
    from core.engine import DAEMON_MUTEX_NAME
    _mx = ctypes.windll.kernel32.CreateMutexW(None, False, DAEMON_MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() in (0xB7, 5):
        print(tr("守护模式运行中，无法恢复默认——请先停止守护"))
        return
    from core import backup as _backup
    # 恢复出厂=全量状态复位（2026-09-06 任务3：共用 backup.reset_factory，
    # 备份形态从散落 .bak 文件升级为标准配置包——可经导入完整复刻）
    ok, bak = _backup.reset_factory(backup=True)
    if bak:
        print(tr_msg(f"已备份: {os.path.basename(bak)}"))
    print(tr("完成。下次启动使用默认配置。"))
    winapi.report_event("MemWise", tr_msg("已恢复出厂设置"))


def cmd_export(_):
    from core import backup as _backup
    p, missing = _backup.export_state("export")
    if p is None:
        print(tr("无法导出：程序尚未生成任何状态文件"))
        return
    print(tr_msg(f"配置包已导出: {p}"))
    if missing:
        print(tr("缺少：") + "、".join(missing))


def cmd_import(args):
    from core.engine import DAEMON_MUTEX_NAME
    _mx = ctypes.windll.kernel32.CreateMutexW(None, False, DAEMON_MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() in (0xB7, 5):
        print(tr("守护模式运行中，无法导入配置——请先停止守护"))
        return
    from core import backup as _backup
    idir = _backup.import_export_dir()
    if not args:
        # 候选 = import_export 目录全部 zip（与 GUI 同口径）
        candidates = sorted(f for f in (os.listdir(idir) if os.path.isdir(idir) else [])
                            if f.lower().endswith(".zip"))
        if not candidates:
            print(tr_msg(f"导入文件夹中没有配置包，请先将 .zip 配置包放入：\n{idir}"))
            return
        print(tr("导入文件夹中的配置包："))
        for c in candidates:
            print(f"  {c}")
        print(tr("用法: memwise.py import <文件名>"))
        return
    pkg = os.path.join(idir, args[0])
    if not os.path.isfile(pkg):
        if os.path.isfile(args[0]):  # 允许直接给完整路径（脚本场景）
            pkg = args[0]
        else:
            print(tr("配置包不存在"))
            return
    ok, err = _backup.import_state(pkg, backup=True)
    if not ok:
        # 错误串在 backup 内已翻译（显示层零残留由 [26] 扫描保证）
        print(err)
        return
    print(tr("配置已导入，重启程序后生效"))

def cmd_install_service(args):
    import subprocess
    exe = sys.executable
    script = os.path.abspath(__file__)
    task_name = "MemWiseDaemon"
    action = f'"{exe}" "{script}" daemon --minimized'
    if args and args[0] == "remove":
        # shell=False：列表直接传 schtasks，不经过 cmd.exe 二次解析（引号错乱隐患源）
        subprocess.run(["schtasks", "/delete", "/tn", task_name, "/f"],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        print(tr("Scheduled Task 已移除"))
        return
    cmd = ["schtasks", "/create", "/tn", task_name, "/tr", action,
           "/sc", "onstart", "/ru", "SYSTEM", "/rl", "highest", "/f"]
    r = subprocess.run(cmd, capture_output=True,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    if r.returncode == 0:
        print(tr("✓ Scheduled Task 已安装 (系统启动时自动运行)"))
        winapi.report_event("MemWise", tr_msg("服务模式已安装 (Scheduled Task)"))
    else:
        print(tr("✗ 安装失败 (需管理员权限): ") + r.stderr.decode('gbk','ignore').strip())

def cmd_profile(args):
    if not args: print(tr("用法: memwise profile <pid>")); return
    try: pid = int(args[0])
    except: print(tr("PID 必须是数字")); return
    mem = winapi.get_process_memory(pid)
    if not mem: print(tr_msg(f"PID {pid} 不存在")); return
    name = next((n for p,n,_ in winapi.enum_processes() if p==pid), "?")
    path = winapi.get_process_path(pid)
    p = Learner.load(STATE_PATH).get_profile(name)
    print(f"PID {pid} — {name}")
    if path: print(tr("  路径:    ") + f"{path}")
    print(tr("  工作集:  ") + f"{_mb(mem['ws']):.1f} MB")
    print(tr("  页面错误: ") + f"{mem['pf']}")
    if p:
        print(f"  Thompson θ: {p.thompson_theta:.2f}")
        print(f"  ROI:        {p.roi:.2f} MB/PF")
        print(f"  Z-score:    {p.z_score:.2f}")
        print(tr("  趋势:       ") + f"{p.slope:.1f}" + tr(" bytes/tick"))
        print(tr("  泄漏:       ") + (tr("⚠ 疑似") if p.leak_suspect else tr("正常")))
        print(tr("  清理:       ") + f"{p.clean_count}" + tr(" 次 | Probe: ") + f"{p.probe_ok}/{p.probe_ok+p.probe_fail}")

def main():
    # GBK 控制台/重定向时 emoji 输出不崩溃（替换为 ? 而非抛 UnicodeEncodeError）
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    # 数据/配置目录预建（2026-08-14 审查：GUI 由 engine 建，CLI 独立进程需自建——
    # 否则全新环境下 learner.save 静默失败，学习/优化结果不持久化）
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        os.makedirs(os.path.dirname(_config.CONFIG_PATH), exist_ok=True)
    except Exception:
        pass
    # 启用清理所需权限（2026-08-15 审查）：GUI 启动即启用，CLI 缺失致 deep/full 的
    # ws_all（系统级全清）静默失效；管理员下 SeProfileSingleProcessPrivilege 必须
    # 运行时启用，非管理员 AdjustTokenPrivileges 失败无害
    winapi.enable_reduct_privileges()
    # 常驻崩溃现场（2026-08-30）：独立于日志开关，CLI 崩溃同样保留 memwise_crash.log
    try:
        from core.engine import _install_crash_sink
        _install_crash_sink()
    except Exception:
        pass
    if len(sys.argv) < 2:
        print(tr("MemWise v4.4.021 PARES —— 智能内存看护"))
        print(tr("用法: py memwise.py <命令> [参数]"))
        print(tr("  status                    内存状态"))
        print(tr("  learn [分钟]              学习进程行为 (默认10分钟)"))
        print(tr("  optimize [--mode q|n|d|f] 执行优化"))
        print(tr("  daemon [--mode q|n|d|f] 守护模式"))
        print(tr("  profile <pid>             进程详情 (含 PARES 指标)"))
        print(tr("  export                    导出配置包到数据目录"))
        print(tr("  import <文件名>            从导入文件夹导入配置包"))
        print(tr("  service [remove]          安装/移除 Scheduled Task 服务"))
        print(tr("  reset                     恢复出厂设置"))
        return
    cmd = sys.argv[1]; args = sys.argv[2:]
    cmds = {"status":cmd_status,"learn":cmd_learn,"optimize":cmd_optimize,
            "daemon":cmd_daemon,"profile":cmd_profile,
            "export":cmd_export,"import":cmd_import,
            "reset":cmd_reset,"service":cmd_install_service}
    fn = cmds.get(cmd)
    if fn: fn(args)
    else: print(tr_msg(f"未知命令: {cmd}"))

if __name__ == "__main__":
    main()