import ctypes, ctypes.wintypes as w, time, math

TH32CS_SNAPPROCESS = 2
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100
PROCESS_SET_INFORMATION = 0x0200
PROCESS_TERMINATE = 0x0001
PROCESS_VM_READ = 0x0010
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD),("cntUsage", w.DWORD),("th32ProcessID", w.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),("th32ModuleID", w.DWORD),("cntThreads", w.DWORD),
        ("th32ParentProcessID", w.DWORD),("pcPriClassBase", w.LONG),("dwFlags", w.DWORD),
        ("szExeFile", w.WCHAR * 260)]

class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [("dwLength", w.DWORD),("dwMemoryLoad", w.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [("cb", w.DWORD),("PageFaultCount", w.DWORD),("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),("PrivateUsage", ctypes.c_size_t)]

class PROCESS_MEMORY_PRIORITY_INFORMATION(ctypes.Structure):
    _fields_ = [("MemoryPriority", w.ULONG)]

class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", w.DWORD),("dwHighDateTime", w.DWORD)]

class IO_COUNTERS(ctypes.Structure):
    _fields_ = [("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong)]

class LUID(ctypes.Structure):
    _fields_ = [("LowPart", w.DWORD), ("HighPart", w.LONG)]

class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", w.DWORD)]

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
NtQuerySystemInformation = ntdll.NtQuerySystemInformation
NtQuerySystemInformation.argtypes = [w.LONG, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG)]
NtQuerySystemInformation.restype = w.LONG
NtSetSystemInformation = ntdll.NtSetSystemInformation; NtSetSystemInformation.argtypes=[w.INT,ctypes.c_void_p,w.ULONG]; NtSetSystemInformation.restype=w.LONG
# Nt 直通（2026-08-11 实验：K32 SetProcessInformation 本机全返回 87，EcoQoS/MemoryPriority 原实现静默失效）
NtSetInformationProcess = ntdll.NtSetInformationProcess
NtSetInformationProcess.argtypes = [w.HANDLE, w.INT, ctypes.c_void_p, w.ULONG]
NtSetInformationProcess.restype = w.LONG
psapi = ctypes.WinDLL("psapi", use_last_error=True)
u32 = ctypes.WinDLL("user32", use_last_error=True)
adv32 = ctypes.WinDLL("advapi32", use_last_error=True)

# --- 函数绑定 ---
CreateToolhelp32Snapshot = k32.CreateToolhelp32Snapshot; CreateToolhelp32Snapshot.argtypes=[w.DWORD,w.DWORD]; CreateToolhelp32Snapshot.restype=w.HANDLE
Process32FirstW = k32.Process32FirstW; Process32FirstW.argtypes=[w.HANDLE,ctypes.POINTER(PROCESSENTRY32W)]; Process32FirstW.restype=w.BOOL
Process32NextW = k32.Process32NextW; Process32NextW.argtypes=[w.HANDLE,ctypes.POINTER(PROCESSENTRY32W)]; Process32NextW.restype=w.BOOL
OpenProcess = k32.OpenProcess; OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD]; OpenProcess.restype=w.HANDLE
CloseHandle = k32.CloseHandle; CloseHandle.argtypes=[w.HANDLE]; CloseHandle.restype=w.BOOL
GetCurrentProcess = k32.GetCurrentProcess; GetCurrentProcess.argtypes=[]; GetCurrentProcess.restype=w.HANDLE
CreateFileW = k32.CreateFileW; CreateFileW.argtypes=[w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]; CreateFileW.restype=w.HANDLE
FlushFileBuffers = k32.FlushFileBuffers; FlushFileBuffers.argtypes=[w.HANDLE]; FlushFileBuffers.restype=w.BOOL
OpenProcessToken = k32.OpenProcessToken; OpenProcessToken.argtypes=[w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]; OpenProcessToken.restype=w.BOOL
LookupPrivilegeValueW = adv32.LookupPrivilegeValueW; LookupPrivilegeValueW.argtypes=[w.LPCWSTR, w.LPCWSTR, ctypes.POINTER(LUID)]; LookupPrivilegeValueW.restype=w.BOOL
AdjustTokenPrivileges = adv32.AdjustTokenPrivileges; AdjustTokenPrivileges.argtypes=[w.HANDLE, w.BOOL, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, ctypes.c_void_p]; AdjustTokenPrivileges.restype=w.BOOL
EmptyWorkingSet = psapi.EmptyWorkingSet; EmptyWorkingSet.argtypes=[w.HANDLE]; EmptyWorkingSet.restype=w.BOOL
TerminateProcess = k32.TerminateProcess; TerminateProcess.argtypes=[w.HANDLE, w.UINT]; TerminateProcess.restype=w.BOOL
GetProcessTimes = k32.GetProcessTimes; GetProcessTimes.argtypes=[w.HANDLE,ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME)]; GetProcessTimes.restype=w.BOOL
GetProcessIoCounters = k32.GetProcessIoCounters; GetProcessIoCounters.argtypes=[w.HANDLE,ctypes.POINTER(IO_COUNTERS)]; GetProcessIoCounters.restype=w.BOOL
GetSystemTimes = k32.GetSystemTimes; GetSystemTimes.argtypes=[ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME)]; GetSystemTimes.restype=w.BOOL
GlobalMemoryStatusEx = k32.GlobalMemoryStatusEx; GlobalMemoryStatusEx.argtypes=[ctypes.POINTER(MEMORYSTATUSEX)]; GlobalMemoryStatusEx.restype=w.BOOL
GetProcessMemoryInfo = psapi.GetProcessMemoryInfo; GetProcessMemoryInfo.argtypes=[w.HANDLE,ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),w.DWORD]; GetProcessMemoryInfo.restype=w.BOOL
GetForegroundWindow = u32.GetForegroundWindow; GetForegroundWindow.argtypes=[]; GetForegroundWindow.restype=w.HANDLE
GetSystemMetrics = u32.GetSystemMetrics; GetSystemMetrics.argtypes=[w.INT]; GetSystemMetrics.restype=w.INT
GetWindowThreadProcessId = u32.GetWindowThreadProcessId; GetWindowThreadProcessId.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]; GetWindowThreadProcessId.restype=w.DWORD
IsWindowVisible = u32.IsWindowVisible; IsWindowVisible.argtypes=[w.HANDLE]; IsWindowVisible.restype=w.BOOL
SetWindowLongPtrW = u32.SetWindowLongPtrW; SetWindowLongPtrW.argtypes=[w.HANDLE, w.INT, ctypes.c_void_p]; SetWindowLongPtrW.restype=ctypes.c_void_p
CallWindowProcW = u32.CallWindowProcW; CallWindowProcW.argtypes=[ctypes.c_void_p, w.HANDLE, w.UINT, ctypes.c_void_p, ctypes.c_void_p]; CallWindowProcW.restype=ctypes.c_void_p
# K32 官方通道（跨机器保留：本机 Win11 26100 实测全失效 87，但其他系统可能正常——
# 双通道策略：K32 优先（可反复设置/恢复），失败回退 Nt 直通兜底）
SetProcessInformation = k32.SetProcessInformation; SetProcessInformation.argtypes=[w.HANDLE,w.DWORD,ctypes.c_void_p,w.DWORD]; SetProcessInformation.restype=w.BOOL
GetDriveTypeW = k32.GetDriveTypeW; GetDriveTypeW.argtypes=[w.LPCWSTR]; GetDriveTypeW.restype=w.UINT
RegisterHotKey = u32.RegisterHotKey; RegisterHotKey.argtypes=[w.HANDLE,w.INT,w.UINT,w.UINT]; RegisterHotKey.restype=w.BOOL
UnregisterHotKey = u32.UnregisterHotKey; UnregisterHotKey.argtypes=[w.HANDLE,w.INT]; UnregisterHotKey.restype=w.BOOL
GetLastInputInfo = u32.GetLastInputInfo; GetLastInputInfo.argtypes=[ctypes.c_void_p]; GetLastInputInfo.restype=w.BOOL
RegisterEventSourceW = adv32.RegisterEventSourceW; RegisterEventSourceW.argtypes=[w.LPCWSTR,w.LPCWSTR]; RegisterEventSourceW.restype=w.HANDLE
ReportEventW = adv32.ReportEventW; ReportEventW.argtypes=[w.HANDLE,w.WORD,w.WORD,w.DWORD,w.HANDLE,w.WORD,w.DWORD,ctypes.c_void_p,ctypes.c_void_p]; ReportEventW.restype=w.BOOL
DeregisterEventSource = adv32.DeregisterEventSource; DeregisterEventSource.argtypes=[w.HANDLE]; DeregisterEventSource.restype=w.BOOL

def _ft_to_ns(ft):
    return (ft.dwHighDateTime << 32) + ft.dwLowDateTime

def enum_processes():
    snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == INVALID_HANDLE_VALUE: return []
    try:
        pe = PROCESSENTRY32W(); pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not Process32FirstW(snap, ctypes.byref(pe)): return []
        r = []
        while True:
            r.append((pe.th32ProcessID, str(pe.szExeFile), pe.th32ParentProcessID))
            if not Process32NextW(snap, ctypes.byref(pe)): break
        return r
    finally:
        CloseHandle(snap)

def get_memory_status():
    ms = MEMORYSTATUSEX(); ms.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if GlobalMemoryStatusEx(ctypes.byref(ms)):
        return {"pct": ms.dwMemoryLoad, "total": ms.ullTotalPhys, "avail": ms.ullAvailPhys, "used": ms.ullTotalPhys - ms.ullAvailPhys}
    return None

# ── GetPerformanceInfo（SystemCache 精确测量文件缓存，filecache 释放量统计用）──
class PERFORMANCE_INFORMATION(ctypes.Structure):
    _fields_ = [("cb", w.DWORD), ("CommitTotal", ctypes.c_size_t), ("CommitLimit", ctypes.c_size_t),
        ("CommitPeak", ctypes.c_size_t), ("PhysicalTotal", ctypes.c_size_t),
        ("PhysicalAvailable", ctypes.c_size_t), ("SystemCache", ctypes.c_size_t),
        ("KernelTotal", ctypes.c_size_t), ("KernelPaged", ctypes.c_size_t),
        ("KernelNonpaged", ctypes.c_size_t), ("PageSize", ctypes.c_size_t),
        ("HandleCount", w.DWORD), ("ProcessCount", w.DWORD), ("ThreadCount", w.DWORD)]

GetPerformanceInfo = psapi.GetPerformanceInfo
GetPerformanceInfo.argtypes = [ctypes.POINTER(PERFORMANCE_INFORMATION), w.DWORD]
GetPerformanceInfo.restype = w.BOOL

def get_performance_info():
    """系统性能信息（PSAPI）：SystemCache 反映文件缓存占用（页数 × page_size 转字节；
    filecache 释放量精确测量用，不受其他进程内存分配干扰）"""
    pi = PERFORMANCE_INFORMATION(); pi.cb = ctypes.sizeof(PERFORMANCE_INFORMATION)
    if GetPerformanceInfo(ctypes.byref(pi), ctypes.sizeof(pi)):
        ps = pi.PageSize
        return {"system_cache": pi.SystemCache * ps, "physical_avail": pi.PhysicalAvailable * ps,
                "page_size": ps}
    return None

def get_process_memory(pid):
    """获取进程内存信息。先用标准权限查询，失败时回退到受限查询。"""
    h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
    if not h:
        h = OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h: return None
    try:
        pmc = PROCESS_MEMORY_COUNTERS_EX(); pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
        if GetProcessMemoryInfo(h, ctypes.byref(pmc), ctypes.sizeof(pmc)):
            return {"ws": pmc.WorkingSetSize, "pf": pmc.PageFaultCount, "priv": pmc.PrivateUsage}
        return None
    finally:
        CloseHandle(h)

def get_foreground_pid():
    hwnd = GetForegroundWindow(); pid = w.DWORD()
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value

# ── 可见窗口枚举（窗口状态采集：有可见窗口的后台程序=用户可能随时切回，清理冷却更长）──
# IsWindowVisible 对最小化窗口返回 True（最小化仍属"可见状态"）——覆盖可见+最小化两类
_WNDENUMPROC = ctypes.WINFUNCTYPE(w.BOOL, w.HANDLE, w.LPARAM)

def enum_visible_window_pids():
    """枚举所有可见顶层窗口的 PID 集合（含最小化；调用方按需缓存——窗口状态变化慢）"""
    pids = set()
    @_WNDENUMPROC
    def _cb(hwnd, lparam):
        try:
            if IsWindowVisible(hwnd):
                pid = w.DWORD()
                GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value:
                    pids.add(pid.value)
        except Exception:
            pass
        return True
    try:
        EnumWindows = u32.EnumWindows
        EnumWindows.argtypes = [_WNDENUMPROC, w.LPARAM]
        EnumWindows.restype = w.BOOL
        EnumWindows(_cb, 0)
    except Exception:
        pass
    return pids

def get_process_times(pid):
    """进程时间（FILETIME 100ns 单位；与 get_all_processes_memory 同源）。
    create 供 PID 复用防护使用——两条路径（批量/回退）都必须提供，否则复用防护会随
    数据源切换而静默失效（2026-09-11 审查 F42 附修）"""
    h = OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not h: return None
    try:
        ct, et, kt, ut = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        if GetProcessTimes(h, ctypes.byref(ct), ctypes.byref(et), ctypes.byref(kt), ctypes.byref(ut)):
            return {"create": _ft_to_ns(ct), "kernel": _ft_to_ns(kt), "user": _ft_to_ns(ut)}
        return None
    finally:
        CloseHandle(h)

def get_process_io_counters(pid):
    """进程累计 IO 字节数（读+写，GetProcessIoCounters 累计计数）——IO 活跃判定用；
    速率需调用方与上次采样差分。失败（权限/退出）返回 None"""
    h = OpenProcess(_PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return None
    try:
        io = IO_COUNTERS()
        if GetProcessIoCounters(h, ctypes.byref(io)):
            return io.ReadTransferCount + io.WriteTransferCount
        return None
    finally:
        CloseHandle(h)

def get_system_times():
    idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
    if GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        return {"idle": _ft_to_ns(idle), "kernel": _ft_to_ns(kernel), "user": _ft_to_ns(user)}
    return None

def empty_ws(pid):
    h = OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_SET_QUOTA, False, pid)
    if not h: return False
    try: return bool(EmptyWorkingSet(h))
    finally: CloseHandle(h)


def terminate_process(pid, exit_code=1):
    """终止指定进程（管理员权限可强制结束）"""
    h = OpenProcess(PROCESS_TERMINATE, False, pid)
    if not h:
        return False
    try:
        return bool(TerminateProcess(h, exit_code))
    finally:
        CloseHandle(h)


def set_memory_priority(pid, level=0):
    """设置进程内存优先级 (0=最低, 4=正常)。双通道：
    K32 官方通道优先（SetProcessInformation 类 0 = ProcessMemoryPriority，文档值——
    2026-08-30 实验证实可用且可反复设置/恢复，5→4→5 全部 TRUE）；失败回退
    Nt 类 42 (ProcessMemoryPriority, PHNT)——Nt 通道每进程仅可设置一次
    （二次恒 STATUS_ALREADY_COMPLETE）。低优先级进程的页面在内存紧张时被系统优先回收。"""
    h = OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    if not h:
        return False
    try:
        info = PROCESS_MEMORY_PRIORITY_INFORMATION(max(0, min(5, level)))
        if SetProcessInformation(h, 0, ctypes.byref(info), ctypes.sizeof(info)):
            return True
        # K32 失效 → Nt 42 直通（ALREADY_COMPLETE 掩码判定同 EcoQoS）
        v = w.ULONG(max(0, min(5, level)))
        ret = NtSetInformationProcess(h, 42, ctypes.byref(v), ctypes.sizeof(v))
        return ret == 0 or (ret & 0xFFFFFFFF) == 0xC0000048
    finally:
        CloseHandle(h)

# ── EcoQoS (ProcessPowerThrottling) ──
# Win11 引入的节能标记。标记为 EcoQoS 后系统会主动降低 CPU 频率
# 并更积极回收该进程的物理内存页。纯操作系统级提示，零副作用。
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 1

class PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [("Version", w.ULONG), ("ControlMask", w.ULONG), ("StateMask", w.ULONG)]

def set_eco_qos(pid, enable=True):
    """标记进程为 EcoQoS(节能)或恢复正常。双通道：
    K32 官方通道优先（SetProcessInformation 类 4 = ProcessPowerThrottling，文档值——
    2026-08-30 实验证实可用且 enable/disable 可反复切换）；失败回退 Nt 类 15 直通。
    EcoQoS 让系统更积极回收该进程的物理内存页。纯性能提示，不影响调度正确性。
    0xC0000048（STATUS_ALREADY_COMPLETE）= 目标状态已达成，同样视为成功（仅 Nt 通道）"""
    h = OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    if not h:
        return False
    try:
        state = PROCESS_POWER_THROTTLING_STATE(
            PROCESS_POWER_THROTTLING_CURRENT_VERSION,
            PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
            PROCESS_POWER_THROTTLING_EXECUTION_SPEED if enable else 0
        )
        if SetProcessInformation(h, 4, ctypes.byref(state), ctypes.sizeof(state)):
            return True
        # K32 失效 → Nt 类 15 直通（ALREADY_COMPLETE 掩码比较：LONG 有符号返回需掩码）
        ret = NtSetInformationProcess(h, 15, ctypes.byref(state), ctypes.sizeof(state))
        return ret == 0 or (ret & 0xFFFFFFFF) == 0xC0000048
    finally:
        CloseHandle(h)


def probe_k32_channels():
    """K32 官方双通道可用性试探（环境画像用）——自身进程、即探即还原、零残留。
    ⚠ 必须直调 SetProcessInformation，不经 set_memory_priority/set_eco_qos 封装：
    封装在 K32 失败时会走 Nt 直通兜底，而 Nt 类 42 每进程仅可设置一次（一次性通道
    不能被试探消耗）。K32 失效的机器上两通道运行期走 Nt 兜底（MemoryPriority 一次性、
    EcoQoS 不可撤），回收行为语义不同 ⇒ 该结果是跨机器归因的字段。
    仅在日志开启时被 engine._log_open 调用（关日志用户零开销）。"""
    import os

    def _probe(cls_id, info, restore):
        h = OpenProcess(PROCESS_SET_INFORMATION, False, os.getpid())
        if not h:
            return False
        try:
            if not SetProcessInformation(h, cls_id, ctypes.byref(info), ctypes.sizeof(info)):
                return False
            SetProcessInformation(h, cls_id, ctypes.byref(restore), ctypes.sizeof(restore))
            return True
        finally:
            CloseHandle(h)

    try:
        mp = _probe(0, PROCESS_MEMORY_PRIORITY_INFORMATION(4),
                    PROCESS_MEMORY_PRIORITY_INFORMATION(5))
        eco = _probe(4, PROCESS_POWER_THROTTLING_STATE(1, 1, 1),
                     PROCESS_POWER_THROTTLING_STATE(1, 1, 0))
        return mp, eco
    except Exception:
        return False, False


def _try_enable_privilege(name):
    """尝试启用指定权限，成功返回 True"""
    h_token = w.HANDLE()
    TOKEN_QUERY_ADJUST = 0x0028
    if not OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY_ADJUST, ctypes.byref(h_token)):
        return False
    try:
        luid = LUID()
        if not LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
            return False
        class TP(ctypes.Structure):
            _fields_ = [("PrivilegeCount", w.DWORD), ("Privileges", LUID_AND_ATTRIBUTES * 1)]
        tp = TP()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = 2
        ok = AdjustTokenPrivileges(h_token, False, ctypes.byref(tp), ctypes.sizeof(tp), None, None)
        if not ok:
            return False
        err = ctypes.windll.kernel32.GetLastError()
        return err == 0
    finally:
        CloseHandle(h_token)

# --- 新增常量 ---
EVENTLOG_INFORMATION_TYPE = 0x0004
EVENTLOG_WARNING_TYPE = 0x0002
EVENTLOG_ERROR_TYPE = 0x0001

MOD_ALT = 0x0001
MOD_SHIFT = 0x0004
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000

NIM_ADD = 0; NIM_MODIFY = 1; NIM_DELETE = 2
NIF_MESSAGE = 1; NIF_ICON = 2; NIF_TIP = 4
# 计算 NOTIFYICONDATA 真实大小（64位系统下 976字节）
WM_TRAYICON = 0x8001

class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", w.DWORD),
        ("hWnd", w.HANDLE),
        ("uID", w.UINT),
        ("uFlags", w.UINT),
        ("uCallbackMessage", w.UINT),
        ("hIcon", w.HANDLE),
        ("szTip", w.WCHAR * 128),
        ("dwState", w.DWORD),
        ("dwStateMask", w.DWORD),
        ("szInfo", w.WCHAR * 256),
        ("uVer", w.UINT),
        ("szInfoTitle", w.WCHAR * 64),
        ("dwInfoFlags", w.DWORD),
        ("guid", w.BYTE * 16),
    ]

shell32 = ctypes.WinDLL("shell32", use_last_error=True)
Shell_NotifyIconW = shell32.Shell_NotifyIconW
Shell_NotifyIconW.argtypes = [w.DWORD, ctypes.POINTER(NOTIFYICONDATA)]
Shell_NotifyIconW.restype = w.BOOL
ExtractIconExW = shell32.ExtractIconExW
ExtractIconExW.argtypes = [w.LPCWSTR, w.INT, ctypes.POINTER(w.HANDLE), ctypes.POINTER(w.HANDLE), w.UINT]
ExtractIconExW.restype = w.UINT

LoadIconW = u32.LoadIconW
LoadIconW.argtypes = [w.HANDLE, ctypes.c_void_p]
LoadIconW.restype = w.HANDLE
LoadImageW = u32.LoadImageW
LoadImageW.argtypes = [w.HANDLE, w.LPCWSTR, w.UINT, w.INT, w.INT, w.UINT]
LoadImageW.restype = w.HANDLE

# 模块级缓存 NtSetSystemInformation 方法检测结果
def empty_standby():
    """清空 Standby 列表 — MemoryPurgeStandbyList = 4 (PHNT standard)"""
    try:
        _try_enable_privilege("SeIncreaseQuotaPrivilege")
        info = w.ULONG(4)  # MemoryPurgeStandbyList (PHNT standard)
        return NtSetSystemInformation(80, ctypes.byref(info), ctypes.sizeof(info)) == 0
    except Exception:
        return False



# SYSTEM_PROCESS_INFORMATION 布局候选（x64）：(pid_off, ws_off, priv_off, user_off, kernel_off, create_off)
# 微软可能增删字段改变布局（实测 Win11 24H2+ 为 0x50/0x90/0xB8，旧版为 0x68/0x1F8/0x210），
# 用自身进程交叉校验动态选表，跨版本兼容；CPU 时间/创建时间偏移（0x28/0x30/0x20）自 Win10 稳定，
# 仍以自身进程 CPU 时间交叉校验兜底
_SPI_LAYOUTS = (
    (0x50, 0x90, 0xB8, 0x28, 0x30, 0x20),   # Win11 24H2+ 实测布局
    (0x68, 0x1F8, 0x210, 0x28, 0x30, 0x20),  # Win10 2004+ / Win11 早期
    (0x68, 0x1E8, 0x200, 0x28, 0x30, 0x20),  # Win10 1809-1903 附近
    (0x68, 0x1C8, 0x1E0, 0x28, 0x30, 0x20),  # 更早版本
)
_spi_layout = None  # 模块级缓存：首次自校验后锁定；False = 已确认全候选不匹配（防每轮重复重试）

def _resolve_spi_layout(buf, ret_len):
    """用自身进程的已知 PID/WS/CPU 时间交叉校验，选定结构布局（失败返回 None，调用方有兜底）。
    单位口径（2026-09-11 审查 F42 修复）：缓冲区内的 KernelTime/UserTime 与 get_process_times()
    同为 FILETIME 100ns 单位——旧实现把缓冲值 ×100 与未换算的自身值比较（差 100 倍），
    使"自证"只在进程 CPU 时间 ≤ 约 50 ms 时偶然通过；一旦进程已运行稍久（GUI 真实启动序列
    实测 kernel 171.9 ms），布局永远解析失败 ⇒ 批量快照整条链路失效（退回逐进程 OpenProcess、
    create 恒空 ⇒ PID 复用防护与锚点代际隔离双双失效）。现两侧同单位比较，不再依赖调用时机。"""
    global _spi_layout
    if _spi_layout is not None:
        return _spi_layout or None
    import os
    self_pid = os.getpid()
    self_ws = 0
    self_kt = self_ut = None
    try:
        m = get_process_memory(self_pid)
        self_ws = m["ws"] if m else 0
        t = get_process_times(self_pid)
        if t:
            self_kt, self_ut = t["kernel"], t["user"]
    except Exception:
        pass
    if self_ws <= 0:
        return None
    for pid_off, ws_off, priv_off, user_off, kernel_off, create_off in _SPI_LAYOUTS:
        off = 0
        while off < ret_len.value:
            ne = ctypes.c_uint32.from_buffer(buf, off).value
            pid = ctypes.c_size_t.from_buffer(buf, off + pid_off).value
            if pid == self_pid:
                ws = ctypes.c_size_t.from_buffer(buf, off + ws_off).value
                if abs(ws - self_ws) <= (1 << 20):  # 1MB 容差（两次读取间瞬时抖动）
                    if self_kt is not None:
                        # CPU 时间交叉校验（同单位 100ns；容差 50ms = 500000）
                        kt = ctypes.c_ulonglong.from_buffer(buf, off + kernel_off).value
                        ut = ctypes.c_ulonglong.from_buffer(buf, off + user_off).value
                        if abs(kt - self_kt) > 500_000 or abs(ut - self_ut) > 500_000:
                            break  # 该候选布局 CPU 偏移不符，试下一个
                    _spi_layout = (pid_off, ws_off, priv_off, user_off, kernel_off, create_off)
                    return _spi_layout
            if ne == 0:
                break
            off += ne
    _spi_layout = False  # 全部候选不匹配：缓存失败态，调用方据此走回退路径且不再重复重试
    # 机器级永久降级 ⇒ crash 通道一次性留痕（不受日志开关门控；下次开启日志自动并入统一
    # 日志）——跨机器报障时这是"快照变慢/学习变笨"类问题的唯一线索（winapi 层无日志体系）
    try:
        from core.engine import _event_log
        _event_log("系统环境: 批量快照布局自校验失败（Windows build %d），已回退逐进程采集模式（快照开销上升，防护能力维持）"
                   % get_os_build())
    except Exception:
        pass
    return None

def get_all_processes_memory():
    """Returns {pid: {"ws":bytes, "priv":bytes, "pf":0, "kernel":ns, "user":ns, "create":ns}}
    for ALL processes via NtQuerySystemInformation —— 内存 + CPU 时间 + 创建时间一次批量获取
    （sniffer 无需再逐进程 OpenProcess 读 CPU 时间；create 供 PID 复用检测）。
    No OpenProcess needed -- works with protected processes like AV.
    布局运行时自校验跨版本兼容；内置重试(×3)和条目上限(8192)。"""
    MAX_RETRIES = 3
    MAX_ITEMS = 8192
    for attempt in range(MAX_RETRIES):
        buf_size = 1 << 20  # 1MB starting buffer
        status = 0; ret_len = w.ULONG()
        while True:
            buf = (ctypes.c_ubyte * buf_size)()
            ret_len = w.ULONG()
            status = NtQuerySystemInformation(5, buf, buf_size, ctypes.byref(ret_len))
            if status == 0:
                break
            if status == 0xC0000004:  # STATUS_INFO_LENGTH_MISMATCH
                buf_size = ret_len.value + (512 << 10)
                continue
            break
        if status != 0:
            continue
        layout = _resolve_spi_layout(buf, ret_len)
        if not layout:
            if _spi_layout is False:
                return {}   # 布局已确认不匹配：直接回退，不再重复 3 次 NtQuery（省重复系统调用）
            continue
        pid_off, ws_off, priv_off, user_off, kernel_off, create_off = layout
        result = {}
        off = 0; items = 0
        while off < ret_len.value and items < MAX_ITEMS:
            ne = ctypes.c_uint32.from_buffer(buf, off).value
            pid = ctypes.c_size_t.from_buffer(buf, off + pid_off).value
            if pid and pid > 4:
                ws = ctypes.c_size_t.from_buffer(buf, off + ws_off).value
                priv = ctypes.c_size_t.from_buffer(buf, off + priv_off).value
                # 时间字段统一 FILETIME 100ns（与 get_process_times/get_system_times 同源）
                # ——旧实现 ×100 转 ns 而消费方按 100ns 折算，令 CPU% 放大 100 倍并被
                # min(100.0) 截断（2026-09-11 审查 F43：修 F42 后此缺陷会立即暴露）
                kt = ctypes.c_ulonglong.from_buffer(buf, off + kernel_off).value
                ut = ctypes.c_ulonglong.from_buffer(buf, off + user_off).value
                ct = ctypes.c_ulonglong.from_buffer(buf, off + create_off).value
                result[pid] = {"ws": ws, "priv": priv, "pf": 0,
                               "kernel": kt, "user": ut, "create": ct}
            if ne == 0:
                break
            off += ne
            items += 1
        if items < MAX_ITEMS:
            return result
    return {}

class _OSVERSIONINFOW(ctypes.Structure):
    _fields_ = [("dwOSVersionInfoSize", w.DWORD), ("dwMajorVersion", w.DWORD),
                ("dwMinorVersion", w.DWORD), ("dwBuildNumber", w.DWORD),
                ("dwPlatformId", w.DWORD), ("szCSDVersion", w.WCHAR * 128)]

RtlGetVersion = ntdll.RtlGetVersion
RtlGetVersion.argtypes = [ctypes.POINTER(_OSVERSIONINFOW)]
RtlGetVersion.restype = w.LONG


def get_os_build():
    """真实 Windows build 号（RtlGetVersion 直读 ntdll，不受 manifest 兼容声明影响）——
    环境画像第一字段：build 决定 SPI 布局候选与系统类号的相关性，跨机器报障归因用。
    失败返回 0（画像行显示 0 即探测通道异常本身也是线索）。"""
    try:
        osv = _OSVERSIONINFOW()
        osv.dwOSVersionInfoSize = ctypes.sizeof(_OSVERSIONINFOW)
        if RtlGetVersion(ctypes.byref(osv)) == 0:
            return int(osv.dwBuildNumber)
    except Exception:
        pass
    return 0


def is_elevated():
    try:
        h_token = w.HANDLE()
        TOKEN_QUERY = 0x0008
        if not OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(h_token)):
            return False
        try:
            elev = w.DWORD()
            sz = w.DWORD(4)
            if ctypes.windll.advapi32.GetTokenInformation(h_token, 20, ctypes.byref(elev), 4, ctypes.byref(sz)):
                return bool(elev.value)
            return False
        finally:
            CloseHandle(h_token)
    except Exception:
        return False


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

# --- 进程可执行文件路径 ---
_PROCESS_QUERY_LIMITED = 0x1000
def get_process_path(pid):
    h = OpenProcess(_PROCESS_QUERY_LIMITED, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(260)
        size = w.DWORD(260)
        ok = k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        if ok:
            return buf.value
        return None
    except AttributeError:
        return None
    finally:
        CloseHandle(h)

try:
    k32.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, ctypes.c_wchar_p, ctypes.POINTER(w.DWORD)]
    k32.QueryFullProcessImageNameW.restype = w.BOOL
except AttributeError:
    pass

# ── 事件驱动：内存通知 + 等待 ──

MEMORY_RESOURCE_NOTIFICATION_TYPE_LOW = 0
MEMORY_RESOURCE_NOTIFICATION_TYPE_HIGH = 1

def create_memory_resource_notification(notification_type):
    """创建内存资源通知对象。
    Low: 可用内存低于阈值时触发
    High: 可用内存恢复到阈值以上时触发
    返回 HANDLE，可在 WaitForSingleObject 中使用
    """
    try:
        k32.CreateMemoryResourceNotification.argtypes = [w.DWORD]
        k32.CreateMemoryResourceNotification.restype = w.HANDLE
        return k32.CreateMemoryResourceNotification(notification_type)
    except Exception:
        return None

def wait_for_object(handle, timeout_ms):
    """等待对象置位，或超时。
    timeout_ms=INFINITE(0xFFFFFFFF) → 一直等到有信号
    返回值: WAIT_OBJECT_0(0)=有信号, WAIT_TIMEOUT(0x102)=超时
    """
    WAIT_TIMEOUT = 0x102
    try:
        k32.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
        k32.WaitForSingleObject.restype = w.DWORD
        ret = k32.WaitForSingleObject(handle, timeout_ms)
        if ret == WAIT_TIMEOUT:
            return "timeout"
        return "signaled"
    except Exception:
        return "error"

def close_handle(handle):
    """关闭内核句柄（供守护等模块释放事件/内存通知对象）"""
    try:
        return bool(CloseHandle(handle))
    except Exception:
        return False

# ============================================================
# 新增: 拓展清理操作
# ============================================================

def empty_all_working_sets():
    """MemoryEmptyWorkingSets — 系统级全进程 WS 清空（单次内核调用）"""
    try:
        _try_enable_privilege("SeIncreaseQuotaPrivilege")
        info = w.ULONG(2)  # MemoryEmptyWorkingSets = 2 (PHNT standard)
        return NtSetSystemInformation(80, ctypes.byref(info), ctypes.sizeof(info)) == 0
    except Exception:
        return False

def purge_low_priority_standby():
    """清空低优先级 Standby — MemoryPurgeLowPriorityStandbyList = 5 (PHNT standard)"""
    try:
        info = w.ULONG(5)  # MemoryPurgeLowPriorityStandbyList = 5 (PHNT standard)
        return NtSetSystemInformation(80, ctypes.byref(info), ctypes.sizeof(info)) == 0
    except Exception:
        return False

# ── 文件缓存上下限（字节口径权威 API）与 SystemFileCacheInformation（Nt 类 0x15）──
# 字段单位（2026-09-11 审查 F45 实测确认）：CurrentSize/PeakSize = 字节；
# Minimum/MaximumWorkingSet = 页（×page_size 恰好等于 GetSystemFileCacheSize 返回的字节值）
GetSystemFileCacheSize = k32.GetSystemFileCacheSize
GetSystemFileCacheSize.argtypes = [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(w.DWORD)]
GetSystemFileCacheSize.restype = w.BOOL
SetSystemFileCacheSize = k32.SetSystemFileCacheSize
SetSystemFileCacheSize.argtypes = [ctypes.c_size_t, ctypes.c_size_t, w.DWORD]
SetSystemFileCacheSize.restype = w.BOOL

_SFCI_CACHE_TARGET_PAGES = 4096   # 回收目标 4096 页 = 16 MB（实测回收 99.7%，且远离 0 更安全）


class _SFCI(ctypes.Structure):
    _fields_ = [
        ("CurrentSize", ctypes.c_size_t),
        ("PeakSize", ctypes.c_size_t),
        ("PageFaultCount", ctypes.c_ulong),
        ("MinimumWorkingSet", ctypes.c_size_t),
        ("MaximumWorkingSet", ctypes.c_size_t),
        ("Unused", ctypes.c_size_t * 4),
    ]


def get_system_file_cache_limits():
    """文件缓存上下限（字节，权威 API）——供恢复与回读校验使用"""
    mn = ctypes.c_size_t(); mx = ctypes.c_size_t(); fl = w.DWORD()
    if GetSystemFileCacheSize(ctypes.byref(mn), ctypes.byref(mx), ctypes.byref(fl)):
        return (mn.value, mx.value)
    return None


def clear_system_file_cache_ex():
    """强制 OS 回收文件缓存 —— 可回收 + 可验证 + 不留系统级副作用（2026-09-11 审查 F45 重写）。
    旧实现两处缺陷（均实测）：① 把字节口径的 PeakSize 写进页口径的 Min/Max 字段 ⇒ 等于请求
    1.1 TB 上限，实测回收 0 字节；② "恢复"用新建结构写回（其余字段清零）且不回读校验，实测把
    系统文件缓存上限从 16 TiB 改写成 4 GiB 后不再回滚。
    新序列：① GetSystemFileCacheSize 取原始字节上下限（权威，供恢复）
            ② 保留查询到的真实字段，仅把 Min=Max 设为 4096 页（16 MB）强制回收
            ③ **短暂驻留并轮询**等待缓存管理器执行裁剪（实测：钳制后立刻恢复会被合并/忽略 ⇒
               回收 0；驻留 ~0.4 s 时回收 99.7%）
            ④ SetSystemFileCacheSize 恢复①的字节值 + 回读校验（≤3 次）
    返回值：仅当"上限已确认恢复"且"确实回收了缓存（或缓存本就不足 32 MB 无需回收）"时为 True
            —— 与 Layer1/Layer3 的"按 API 真实成功计数"口径一致，不虚增统计。"""
    if not _try_enable_privilege("SeIncreaseQuotaPrivilege"):
        return False
    orig = get_system_file_cache_limits()
    if not orig:
        return False
    _pi0 = get_performance_info()
    before = _pi0["system_cache"] if _pi0 else 0
    # 缓存本已极小（清理待机列表后常见，实测 2114→25 MB）⇒ 无需钳制：直接视为达成，
    # 零耗时且完全不触碰系统上限（2026-09-11 实测：此状态下钳制收益恒为 0）
    if before <= (32 << 20):
        return True
    info = _SFCI()
    ret_len = w.ULONG()
    if NtQuerySystemInformation(0x15, ctypes.byref(info), ctypes.sizeof(info), ctypes.byref(ret_len)) != 0:
        return False
    # ② 保留 CurrentSize/PeakSize/PageFaultCount 等真实字段，只改页口径的上下限
    info.MinimumWorkingSet = _SFCI_CACHE_TARGET_PAGES
    info.MaximumWorkingSet = _SFCI_CACHE_TARGET_PAGES
    ret = NtSetSystemInformation(0x15, ctypes.byref(info), ctypes.sizeof(info))
    ok_set = ret == 0 or (ret & 0xFFFFFFFF) == 0x40000002
    # ③ 驻留 + 轮询观察裁剪是否落实（实测：钳制后立刻恢复会被合并/忽略 ⇒ 回收 0；驻留
    #    ~0.4 s 时曾实测回收 99.7%。上限 0.8 s，多数情况提前命中）
    low = before
    if ok_set:
        for _ in range(10):
            time.sleep(0.08)
            pi = get_performance_info()
            if pi:
                low = min(low, pi["system_cache"])
                if low < max(1 << 20, before // 10):
                    break
    # ④ 恢复原始字节上下限 + 回读校验
    restored = False
    for _ in range(3):
        SetSystemFileCacheSize(orig[0], orig[1], 0)
        if get_system_file_cache_limits() == orig:
            restored = True
            break
    released = max(0, before - low)
    return bool(restored and ok_set and (released > (1 << 20) or before <= (32 << 20)))


# ============================================================
# 托盘百分比图标
# ============================================================

def create_tray_percent_icon(percent, color=(0, 200, 0)):
    """在 16x16 内存 DC 上绘制百分比数字图标"""
    import ctypes.wintypes as wt
    gm = ctypes.windll.gdi32
    um = ctypes.windll.user32
    hdc_screen = hdc = hbm = hbm_mask = hicon = None
    try:
        hdc_screen = um.GetDC(None)
        if not hdc_screen:
            return None
        hdc = gm.CreateCompatibleDC(hdc_screen)
        hbm = gm.CreateCompatibleBitmap(hdc_screen, 16, 16)
        hbm_mask = gm.CreateBitmap(16, 16, 1, 1, None)
        if not hdc or not hbm or not hbm_mask:
            # 失败路径逐个释放已创建对象（2026-08-15 审查：原 `all` 判断直接返回泄漏 DC/位图）
            if hbm_mask: gm.DeleteObject(hbm_mask)
            if hbm: gm.DeleteObject(hbm)
            if hdc: gm.DeleteDC(hdc)
            return None
        prev_bm = gm.SelectObject(hdc, hbm)
        prev_font = gm.SelectObject(hdc, gm.GetStockObject(17))  # DEFAULT_GUI_FONT
        # Draw background
        r, g, b = color
        bg_color = r | (g << 8) | (b << 16)
        brush = gm.CreateSolidBrush(bg_color)
        rect = wt.RECT(0, 0, 16, 16)
        gm.FillRect(hdc, ctypes.byref(rect), brush)
        gm.DeleteObject(brush)
        # Draw text（0-100 如实显示——原 min(99) 使 100% 显示 99，2026-08-30 修正）
        text = str(max(0, min(100, int(percent))))
        gm.SetBkMode(hdc, 1)  # TRANSPARENT
        gm.SetTextColor(hdc, 0xFFFFFF)  # white text
        gm.DrawTextW(hdc, text, -1, ctypes.byref(rect), 0x25)  # DT_CENTER|DT_VCENTER|DT_SINGLELINE
        gm.SelectObject(hdc, prev_font)
        gm.SelectObject(hdc, prev_bm)
        gm.DeleteDC(hdc); hdc = None
        # Create icon
        class ICONINFO(ctypes.Structure):
            _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
                        ("hbmMask", wt.HBITMAP), ("hbmColor", wt.HBITMAP)]
        ii2 = ICONINFO(True, 0, 0, hbm_mask, hbm)
        hicon = ctypes.windll.user32.CreateIconIndirect(ctypes.byref(ii2))
        return hicon
    except Exception:
        return None
    finally:
        if hbm_mask: gm.DeleteObject(hbm_mask)
        if hbm: gm.DeleteObject(hbm)
        if hdc: gm.DeleteDC(hdc)
        if hdc_screen: um.ReleaseDC(None, hdc_screen)

def enable_reduct_privileges():
    """启用清理所需权限（SE_PROF_SINGLE_PROCESS + SE_INCREASE_QUOTA）"""
    try:
        for priv in ("SeIncreaseQuotaPrivilege", "SeProfileSingleProcessPrivilege"):
            _try_enable_privilege(priv)
        return True
    except Exception:
        return False

def get_memory_used_bytes():
    """获取物理内存已用量（字节）"""
    try:
        s = get_memory_status()
        if s:
            return s["total"] - s["avail"]
        return 0
    except Exception:
        return 0


def flush_modified_pages():
    """冲刷 Modified 脏页列表 — MemoryFlushModifiedList = 3 (PHNT standard)"""
    try:
        _try_enable_privilege("SeIncreaseQuotaPrivilege")
        info = w.ULONG(3)  # MemoryFlushModifiedList = 3 (PHNT standard)
        return NtSetSystemInformation(80, ctypes.byref(info), ctypes.sizeof(info)) == 0
    except Exception:
        return False


def deep_compress():
    """单轮完整压缩：flush modified → purge standby — 无 sleep，不碰自身 WS"""
    if not _try_enable_privilege("SeIncreaseQuotaPrivilege"):
        return False
    ok = False
    # Flush modified pages (MemoryFlushModifiedList = 3)
    if NtSetSystemInformation(80, ctypes.byref(w.ULONG(3)), 4) == 0:
        ok = True
    # Purge standby list (MemoryPurgeStandbyList = 4)
    if NtSetSystemInformation(80, ctypes.byref(w.ULONG(4)), 4) == 0:
        ok = True
    return ok

def clear_registry_cache():
    """清空注册表缓存 — SystemRegistryReconciliationInformation = 155。
    2026-09-26 实测订正（本机 Win11 26100，管理员）：原实现写 class 81 —— 81 是**文件缓存**类
    （SystemFileCacheInformationEx），实测返回 STATUS_INFO_LENGTH_MISMATCH(0xC0000004) 恒失败，
    既让"注册表缓存清理"开关空转，又是"调错系统类"的隐患；正确类号 155 实测 (NULL, len 0)
    即 STATUS_SUCCESS。类号 155 自 Win8.1 起提供（旧系统不支持时返回失败，由留痕通道记录）。"""
    try:
        _try_enable_privilege("SeIncreaseQuotaPrivilege")
        return NtSetSystemInformation(155, None, 0) == 0
    except Exception:
        return False

_VOLUME_DEVICE_PREFIX = "\\\\.\\"   # 设备命名空间：打开卷必须用它（用 "C:\\" 会 ERROR_PATH_NOT_FOUND=3）

def flush_volume_cache():
    """冲刷所有卷的待写缓冲区（仅本地固定/可移动卷——网络盘/光驱冲刷对内存释放无意义且网络卷可能阻塞数秒）。
    2026-09-26 实测订正：原实现用盘符根目录 "C:\\" 调 CreateFileW，实测 C:/D: 两卷均返回
    ERROR_PATH_NOT_FOUND(3) ⇒ **该开关从未生效过**（此前"两周计数 0"被误读为"执行了但零收益"）。
    正确形式为设备命名空间 "\\\\.\\C:"，实测句柄可开、FlushFileBuffers 成功（管理员）。
    返回真实执行结果：无任何卷成功打开时返回 False（2026-08-30 审查：原恒 True 使统计虚增）"""
    try:
        _try_enable_privilege("SeIncreaseQuotaPrivilege")
        import string, os
        flushed = False
        for letter in string.ascii_uppercase:
            vol = f"{letter}:\\"
            if not os.path.exists(vol):
                continue
            if GetDriveTypeW(vol) not in (2, 3):  # DRIVE_REMOVABLE / DRIVE_FIXED
                continue
            h = k32.CreateFileW(f"{_VOLUME_DEVICE_PREFIX}{letter}:", 0x40000000, 3, None, 3, 0x80, None)
            if h and h != INVALID_HANDLE_VALUE:
                k32.FlushFileBuffers(h)
                k32.CloseHandle(h)
                flushed = True
        return flushed
    except Exception:
        return False

def empty_standby_deep():
    """深度 Standby 清空：低优先 → 全量 → 冲刷脏页 — 无 sleep，不碰自身 WS"""
    if not _try_enable_privilege("SeIncreaseQuotaPrivilege"):
        return False
    ok = False
    # Low-priority standby (MemoryPurgeLowPriorityStandbyList = 5)
    if NtSetSystemInformation(80, ctypes.byref(w.ULONG(5)), 4) == 0:
        ok = True
    # Full standby purge (MemoryPurgeStandbyList = 4)
    if NtSetSystemInformation(80, ctypes.byref(w.ULONG(4)), 4) == 0:
        ok = True
    # Flush modified list (MemoryFlushModifiedList = 3)
    if NtSetSystemInformation(80, ctypes.byref(w.ULONG(3)), 4) == 0:
        ok = True
    return ok

# ============================================================
# 新增: 全局热键
# ============================================================

def register_hotkey(hwnd, id, modifiers, vk):
    """注册全局热键"""
    return bool(RegisterHotKey(hwnd, id, modifiers, vk))

def unregister_hotkey(hwnd, id):
    """注销全局热键"""
    return bool(UnregisterHotKey(hwnd, id))

# ============================================================
# 新增: Event Viewer 日志
# ============================================================

def report_event(source, message, level=EVENTLOG_INFORMATION_TYPE):
    """写入 Windows 事件查看器"""
    h = RegisterEventSourceW(None, source)
    if not h:
        return False
    try:
        msg_ptr = ctypes.c_wchar_p(message)
        ok = ReportEventW(h, level, 0, 0, None, 1, 0, ctypes.byref(msg_ptr), None)
        return bool(ok)
    finally:
        DeregisterEventSource(h)

# ============================================================
# 开机自启 — 启动文件夹快捷方式（避免杀软拦截）
# ============================================================

# ── 开机自启（IShellLink 纯 API，不碰 PowerShell / WScript）──

_CLSID_ShellLink = (b"\x01\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46")
# 标准 IID_IShellLinkW = {000214F9-0000-0000-C000-000000000046}（小端字节）
# 曾误用 {EE80CA92-4274-11D2-B3ED-00C04F990E17} → CoCreateInstance 返回 E_NOINTERFACE → 普通自启静默失效
_IID_IShellLinkW = (b"\xf9\x14\x02\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46")
# 标准 IID_IPersistFile = {0000010B-0000-0000-C000-000000000046}（小端字节；曾写反为 01 10 0B 00 → QI 失败）
_IID_IPersistFile = (b"\x0b\x01\x00\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46")

class GUID(ctypes.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD),
                ("Data4", w.BYTE * 8)]

def _guid_from_bytes(b):
    return GUID(ctypes.c_uint32.from_buffer_copy(b[:4]).value,
                ctypes.c_uint16.from_buffer_copy(b[4:6]).value,
                ctypes.c_uint16.from_buffer_copy(b[6:8]).value,
                (w.BYTE * 8)(*b[8:16]))

def _com_vtbl_call(iface_ptr, vtbl_idx, restype, argtypes, *args):
    """通过 vtable 调用 COM 方法"""
    vtbl = ctypes.cast(iface_ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    method = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[vtbl_idx]
    func = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(method)
    return func(iface_ptr, *args)

_ole32 = ctypes.windll.ole32
_COM_INITIALIZED = False  # 标记 COM 是否已初始化

# ── GDI+：内存 PNG → HICON（任务栏扁平图标用，零临时文件）──
# IShellLinkW vtbl indices: QueryInterface=0, AddRef=1, Release=2,
# GetPath=3, GetIDList=4, SetIDList=5, GetDescription=6, SetDescription=7,
# GetWorkingDirectory=8, SetWorkingDirectory=9, GetArguments=10, SetArguments=11,
# GetHotkey=12, SetHotkey=13, GetShowCmd=14, SetShowCmd=15,
# GetIconLocation=16, SetIconLocation=17, SetRelativePath=18, Resolve=19,
# SetPath=20
# IPersistFile vtbl: QI=0, AddRef=1, Release=2, GetClassID=3,
# IsDirty=4, Load=5, Save=6, SaveCompleted=7, GetCurFile=8

def set_auto_start(name, target_path, arguments="", work_dir=""):
    """通过 IShellLink 创建启动文件夹快捷方式（纯 Win32 API，无脚本引擎）。
    ⚠ 2026-08-15 起无调用方（普通权限自启功能已移除，仅保留管理员自启）——
    定义保留不删（红线：不草率弃用，未来如需恢复普通自启零成本）"""
    global _COM_INITIALIZED
    if not _COM_INITIALIZED:
        ret = _ole32.CoInitializeEx(None, 2)  # COINIT_APARTMENTTHREADED
        if ret not in (0, 1):  # S_OK or S_FALSE
            return False
        _COM_INITIALIZED = True
    try:
        import os
        startup = os.path.join(os.environ['APPDATA'],
            'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
        os.makedirs(startup, exist_ok=True)
        lnk = os.path.join(startup, f'{name}.lnk')

        clsid = _guid_from_bytes(_CLSID_ShellLink)
        iid = _guid_from_bytes(_IID_IShellLinkW)

        psl = ctypes.c_void_p()
        hr = _ole32.CoCreateInstance(ctypes.byref(clsid), None, 1,
                                     ctypes.byref(iid), ctypes.byref(psl))
        if hr != 0 or not psl: return False

        # SetPath (vtbl 20)
        _com_vtbl_call(psl.value, 20, w.HRESULT, [w.LPCWSTR], target_path)
        # SetArguments (vtbl 11)
        _com_vtbl_call(psl.value, 11, w.HRESULT, [w.LPCWSTR], arguments)
        if work_dir:
            _com_vtbl_call(psl.value, 9, w.HRESULT, [w.LPCWSTR], work_dir)

        # Query IPersistFile
        iid_pf = _guid_from_bytes(_IID_IPersistFile)
        ppf = ctypes.c_void_p()
        _com_vtbl_call(psl.value, 0, w.HRESULT,  # QueryInterface
                       [ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)],
                       ctypes.byref(iid_pf), ctypes.byref(ppf))
        if not ppf: return False

        # Save (vtbl 6) — IPersistFile::Save(file, fRemember)
        _com_vtbl_call(ppf.value, 6, w.HRESULT, [w.LPCWSTR, w.BOOL], lnk, True)

        # Release both interfaces
        _com_vtbl_call(ppf.value, 2, w.HRESULT, [])
        _com_vtbl_call(psl.value, 2, w.HRESULT, [])
        return True
    except Exception:
        return False

def remove_auto_start(name):
    """移除启动文件夹中的快捷方式"""
    try:
        import os
        startup = os.path.join(os.environ['APPDATA'],
            'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
        lnk = os.path.join(startup, f'{name}.lnk')
        if os.path.isfile(lnk):
            os.remove(lnk)
        return True
    except Exception:
        return False

# ============================================================
# 新增: 系统托盘图标
# ============================================================

def tray_add(hwnd, uid, icon_handle, tip=""):
    """添加系统托盘图标。
    NIM_ADD 成功后再 NIM_SETVERSION（微软官方样例顺序）——SETVERSION 先于 ADD
    会因图标尚不存在静默失败（2026-08-30 实验：前置 FALSE(0x80004005)/后置 TRUE），
    程序将始终运行在 legacy 回调格式。"""
    nid = NOTIFYICONDATA()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
    nid.hWnd = hwnd
    nid.uID = uid
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    nid.uCallbackMessage = WM_TRAYICON
    nid.hIcon = icon_handle
    nid.szTip = tip[:127]
    nid.uVer = 4  # NOTIFYICON_VERSION_4
    ok = bool(Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
    Shell_NotifyIconW(0x00000004, ctypes.byref(nid))  # NIM_SETVERSION（ADD 后设置版本）
    return ok

def tray_modify(hwnd, uid, icon_handle, tip=""):
    """更新托盘图标"""
    nid = NOTIFYICONDATA()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
    nid.hWnd = hwnd
    nid.uID = uid
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    nid.uCallbackMessage = WM_TRAYICON
    nid.hIcon = icon_handle
    nid.szTip = tip[:127]
    return bool(Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid)))

def tray_remove(hwnd, uid):
    """移除托盘图标"""
    nid = NOTIFYICONDATA()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
    nid.hWnd = hwnd; nid.uID = uid
    return bool(Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid)))

IMAGE_ICON = 1
LR_LOADFROMFILE = 0x10
LR_DEFAULTSIZE = 0x40

# ============================================================
# 新增: 在内存中创建自定义图标 (零外部文件)
# ============================================================

gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", w.DWORD), ("biWidth", w.LONG), ("biHeight", w.LONG),
        ("biPlanes", w.WORD), ("biBitCount", w.WORD),
        ("biCompression", w.DWORD), ("biSizeImage", w.DWORD),
        ("biXPelsPerMeter", w.LONG), ("biYPelsPerMeter", w.LONG),
        ("biClrUsed", w.DWORD), ("biClrImportant", w.DWORD),
    ]

class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER)]

class ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", w.BOOL), ("xHotspot", w.DWORD), ("yHotspot", w.DWORD),
                ("hbmMask", w.HANDLE), ("hbmColor", w.HANDLE)]

CreateDIBSection = gdi32.CreateDIBSection
CreateDIBSection.argtypes = [w.HANDLE, ctypes.POINTER(BITMAPINFO), w.UINT, ctypes.POINTER(ctypes.c_void_p), w.HANDLE, w.DWORD]
CreateDIBSection.restype = w.HANDLE
CreateBitmap = gdi32.CreateBitmap
CreateBitmap.argtypes = [w.INT, w.INT, w.UINT, w.UINT, ctypes.c_void_p]
CreateBitmap.restype = w.HANDLE
DeleteObject = gdi32.DeleteObject
DeleteObject.argtypes = [w.HANDLE]; DeleteObject.restype = w.BOOL
CreateIconIndirect = u32.CreateIconIndirect
CreateIconIndirect.argtypes = [ctypes.POINTER(ICONINFO)]
CreateIconIndirect.restype = w.HANDLE
GetObjectW = gdi32.GetObjectW
GetObjectW.argtypes = [w.HANDLE, w.INT, ctypes.c_void_p]
GetObjectW.restype = w.INT
GetDIBits = gdi32.GetDIBits
GetDIBits.argtypes = [w.HANDLE, w.HANDLE, w.UINT, w.UINT, ctypes.c_void_p, ctypes.c_void_p, w.UINT]
GetDIBits.restype = w.INT

def _dist_to_seg_hq(px, py, x1, y1, x2, y2):
    """返回 (距离, 最近点x, 最近点y)"""
    vx, vy = x2 - x1, y2 - y1
    wx, wy = px - x1, py - y1
    c1 = vx * wx + vy * wy
    if c1 <= 0:
        return math.hypot(px - x1, py - y1), x1, y1
    c2 = vx * vx + vy * vy
    if c2 <= c1:
        return math.hypot(px - x2, py - y2), x2, y2
    t = c1 / c2
    nx, ny = x1 + t * vx, y1 + t * vy
    return math.hypot(px - nx, py - ny), nx, ny


def _draw_memwise_pixels_hq(size, buf, base_color=(62, 62, 72), off_mult=0.75, shadow=True, gradient=0.47, force_large=False):
    """HQ 渲染（4x 超采样）：径向渐变圆盘 + 管状法线光照 M + 圆盘内投影。
    base_color 为圆盘基色（托盘变色图标传不同颜色仍可区分）；M 保持白光照。
    shadow=False 时不投影（托盘变色用，小尺寸下投影会糊）；gradient 控制渐变压暗幅度（托盘用 0.12 保持鲜亮）。
    小尺寸：M 等比收进圆内（无伸出毛刺）+ 扁平光照 + 窄柔边（干净锐利）。
    输出写入 buf（BGRA top-down，长度 size*size*4）。"""
    SS = 4
    cs = size * SS
    n = cs * cs
    canvas = [[0, 0, 0, 0] for _ in range(n)]
    cx = cy = cs // 2
    R = (size // 2 - 2) * SS
    s = size / 16.0

    small = (size <= 48) and not force_large
    if small:
        # 小尺寸简洁模式：纯色（零色差）+ 无投影 + 窄柔边（防设计过度显脏）
        shadow = False
        gradient = 0.0
    edge_out = (0.4 if small else 0.5) * SS   # 圆外柔边（小尺寸收窄→边缘更锐利，4x 超采样下仍无锯齿）
    edge_in = (0.7 if small else 1.0) * SS    # 圆内柔边

    # 1. 径向渐变背景（平面感，相对 base_color 明暗：中心亮 → 边缘暗）
    for y in range(cs):
        for x in range(cs):
            dx, dy = x - cx, y - cy
            d = math.sqrt(dx * dx + dy * dy)
            if d > R + edge_out:
                continue
            t = min(1.0, d / R)
            lum = 1.0 - gradient * t
            r = int(min(255, base_color[0] * lum))
            g = int(min(255, base_color[1] * lum))
            b = int(min(255, base_color[2] * lum))
            a = 255
            if d > R - edge_in:
                a = max(0, min(255, int(255 * (R + edge_out - d) / (edge_in + edge_out))))
            canvas[y * cs + x] = [b, g, r, a]

    # 2. M 骨架（off_mult 控制重心下移；小尺寸等比收窄 0.87 防横向显扁，大尺寸与母版同构）
    core_r = 1.1 * s
    soft_r = (1.22 if small else 1.35) * s
    m_scale = 0.87 if small else 1.0
    segs = []
    off = -off_mult * s
    lx = -6 * s * m_scale; rx = 6 * s * m_scale
    ty = -5 * s * m_scale + off; by = 5 * s * m_scale + off
    mx = 0; my = 1 * s * m_scale + off
    segs.extend([(lx, ty, lx, by), (lx, ty, mx, my), (mx, my, rx, ty), (rx, ty, rx, by)])

    # 3. M 掩码 + 管状法线光照
    m_alpha = [0.0] * n
    m_col = [None] * n
    # 小尺寸扁平光照（近白纯色），大尺寸立体管状光照（深色管 + 白色高光）
    DARK = (235, 238, 242) if small else (125, 135, 150)
    BRIGHT = (255, 255, 255)
    MLX, MLY = -0.7071, -0.7071
    for y in range(cs):
        row = y * cs
        for x in range(cs):
            px, py = (x - cx) / SS, (y - cy) / SS
            best = None
            for sg in segs:
                d, nx_, ny_ = _dist_to_seg_hq(px, py, *sg)
                if best is None or d < best[0]:
                    best = (d, nx_, ny_)
            d, nx_, ny_ = best
            if d >= soft_r:
                continue
            a = 1.0 if d < core_r else (soft_r - d) / (soft_r - core_r)
            m_alpha[row + x] = a
            if d > 1e-6:
                nx2, ny2 = (px - nx_) / d, (py - ny_) / d
                diff = nx2 * MLX + ny2 * MLY
                shade = 0.9 if small else (0.55 + 0.45 * diff)
            else:
                shade = 0.9 if small else 0.55
            r = int(DARK[0] + (BRIGHT[0] - DARK[0]) * shade)
            g = int(DARK[1] + (BRIGHT[1] - DARK[1]) * shade)
            b = int(DARK[2] + (BRIGHT[2] - DARK[2]) * shade)
            m_col[row + x] = (b, g, r)

    # 4. 投影（高斯模糊掩码偏移；仅叠加在完全不透明圆内像素，防缩小后暗色扩散到圆外）
    tmp = [0.0] * n
    for y in range(cs):
        row = y * cs
        for x in range(cs):
            v = m_alpha[row + x]
            tmp[row + x] = (m_alpha[row + x - 1] if x > 0 else v) + 2 * v + (m_alpha[row + x + 1] if x < cs - 1 else v)
    blurred = [0.0] * n
    for y in range(cs):
        for x in range(cs):
            i = y * cs + x
            v = tmp[i]
            blurred[i] = ((tmp[i - cs] if y > 0 else v) + 2 * v + (tmp[i + cs] if y < cs - 1 else v)) / 16.0

    if shadow:
        ox, oy = int(0.6 * s * SS), int(0.9 * s * SS)
        for y in range(cs):
            sy = y - oy
            if sy < 0 or sy >= cs:
                continue
            row_s = sy * cs
            for x in range(cs):
                sx = x - ox
                if sx < 0 or sx >= cs:
                    continue
                sh = blurred[row_s + sx] * 0.42
                if sh > 0.01:
                    i = y * cs + x
                    if canvas[i][3] < 250:
                        continue  # 边缘 AA 像素不叠加投影（防扩散出圆）
                    a = int(255 * sh)
                    cb, cg, cr, ca = canvas[i]
                    canvas[i] = [(cb * (255 - a)) // 255, (cg * (255 - a)) // 255,
                                 (cr * (255 - a)) // 255, min(255, ca + a)]

    # 5. M 本体合成（圆外直接画，圆内混合）
    for y in range(cs):
        row = y * cs
        for x in range(cs):
            a_m = m_alpha[row + x]
            if a_m <= 0:
                continue
            a = int(255 * a_m)
            i = row + x
            mb, mg, mr = m_col[i]
            bg_a = canvas[i][3]
            if bg_a == 0:
                canvas[i] = [mb, mg, mr, a]
            else:
                cb, cg, cr, ca = canvas[i]
                canvas[i] = [(cb * (255 - a) + mb * a) // 255,
                             (cg * (255 - a) + mg * a) // 255,
                             (cr * (255 - a) + mr * a) // 255,
                             min(255, ca + a)]

    # 6. 4x 盒式缩小 → 写入 buf
    for y in range(size):
        for x in range(size):
            rs = gs = bs = as_ = 0
            for sy in range(SS):
                for sx in range(SS):
                    b, g, r, a = canvas[(y * SS + sy) * cs + (x * SS + sx)]
                    rs += r; gs += g; bs += b; as_ += a
            nn = SS * SS
            i = (y * size + x) * 4
            buf[i] = bs // nn; buf[i+1] = gs // nn; buf[i+2] = rs // nn
            buf[i+3] = as_ // nn if as_ else 0
    return buf


def _sharpen_bgra(buf, size, amount=0.8):
    """Unsharp 锐化（拉普拉斯 4 邻域）：只处理不透明像素，透明邻域不参与，避免边缘发暗。
    仅任务栏图标使用。"""
    src = bytes(buf)
    for y in range(size):
        for x in range(size):
            i = (y * size + x) * 4
            if src[i + 3] < 100:
                continue
            nb = [(dx, dy) for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
                  if 0 <= x + dx < size and 0 <= y + dy < size
                  and src[((y + dy) * size + x + dx) * 4 + 3] > 100]
            if len(nb) < 2:
                continue
            for c in range(3):
                v = src[i + c]
                s = sum(src[((y + dy) * size + x + dx) * 4 + c] for dx, dy in nb)
                lap = len(nb) * v - s
                buf[i + c] = max(0, min(255, int(v + amount * lap / len(nb))))


def create_hicon_from_rgba(width, height, rgba):
    """BGRA 像素 → HICON（CreateDIBSection + CreateIconIndirect，与动态渲染同通道。
    替代 GDI+ 解码：GDI+ HICON 句柄经 ctypes c_int 截断后 WM_SETICON 无效（v3.4.19 图标失效根因）"""
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    bits_ptr = ctypes.c_void_p()
    hColor = CreateDIBSection(None, ctypes.byref(bmi), 0, ctypes.byref(bits_ptr), None, 0)
    if not hColor:
        return None
    ctypes.memmove(bits_ptr.value, rgba, width * height * 4)
    mask_row = ((width + 15) // 16) * 2  # 1bpp scanline aligned to WORD
    mask_bits = (ctypes.c_ubyte * (mask_row * height))()  # all zeros = 不透明
    hMask = CreateBitmap(width, height, 1, 1, mask_bits)
    if not hMask:
        DeleteObject(hColor)
        return None
    ii = ICONINFO()
    ii.fIcon = 1
    ii.hbmMask = hMask
    ii.hbmColor = hColor
    hIcon = CreateIconIndirect(ctypes.byref(ii))
    DeleteObject(hColor)
    DeleteObject(hMask)
    return hIcon


def create_memwise_icon(size=32, bg_color=(45,45,50), shadow=True, gradient=0.47, force_large=False, sharpen=False):
    """在内存中创建 MemWise 图标，bg_color 为 (R,G,B) 自动转 BGRA
    默认深灰(45,45,50)，托盘和大图标都清晰。
    shadow=False + 轻 gradient 供托盘变色图标使用（小尺寸下保持鲜亮、无投影糊边）"""
    # RGB → BGRA
    bg = (bg_color[2], bg_color[1], bg_color[0])
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = size
    bmi.bmiHeader.biHeight = -size
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0

    bits_ptr = ctypes.c_void_p()
    hColor = CreateDIBSection(None, ctypes.byref(bmi), 0, ctypes.byref(bits_ptr), None, 0)
    if not hColor:
        return None

    w_addr = bits_ptr.value
    buf = (ctypes.c_ubyte * (size * size * 4)).from_address(w_addr)

    # HQ 渲染：径向渐变圆盘 + 管状光照 M + 圆盘内投影（4x 超采样）
    # base_color 即托盘变色基色——不同状态颜色仍可区分
    _draw_memwise_pixels_hq(size, buf, bg_color, off_mult=0.75, shadow=shadow, gradient=gradient, force_large=force_large)
    if sharpen:
        _sharpen_bgra(buf, size)

    # 创建 1bpp 遮罩（全部为 0 = 不透明）
    mask_row = ((size + 15) // 16) * 2  # 1bpp scanline aligned to WORD
    mask_bits = (ctypes.c_ubyte * (mask_row * size))()  # all zeros
    hMask = CreateBitmap(size, size, 1, 1, mask_bits)
    if not hMask:
        DeleteObject(hColor)
        return None

    ii = ICONINFO()
    ii.fIcon = 1
    ii.hbmMask = hMask
    ii.hbmColor = hColor
    hIcon = CreateIconIndirect(ctypes.byref(ii))

    DeleteObject(hColor)
    DeleteObject(hMask)
    return hIcon


# ─── 开机自启（管理员权限·Task Scheduler） ───

def set_auto_start_admin(name, target_path, arguments=""):
    """通过 schtasks 创建计划任务，登录时以最高权限启动（无 UAC 弹窗）"""
    try:
        import subprocess
        quoted = f'"{target_path}"'
        if arguments:
            quoted += f" {arguments}"
        cmd = (
            f'schtasks /Create /SC ONLOGON /TN "{name}" '
            f'/TR "{quoted}" /RL HIGHEST /IT /F'
        )
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, shell=True)
        return r.returncode == 0
    except Exception:
        return False

def remove_auto_start_admin(name):
    """移除 schtasks 创建的计划任务"""
    try:
        import subprocess
        cmd = f'schtasks /Delete /TN "{name}" /F'
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15, shell=True)
        return r.returncode == 0
    except Exception:
        return False
