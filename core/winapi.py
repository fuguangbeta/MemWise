import ctypes, ctypes.wintypes as w, time

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

class RECT(ctypes.Structure):
    _fields_ = [("left", w.LONG), ("top", w.LONG), ("right", w.LONG), ("bottom", w.LONG)]

class LUID(ctypes.Structure):
    _fields_ = [("LowPart", w.DWORD), ("HighPart", w.LONG)]

class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", w.DWORD)]

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
NtQuerySystemInformation = ntdll.NtQuerySystemInformation
NtQuerySystemInformation.argtypes = [w.LONG, ctypes.c_void_p, w.ULONG, ctypes.POINTER(w.ULONG)]
NtQuerySystemInformation.restype = w.LONG
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
GetSystemTimes = k32.GetSystemTimes; GetSystemTimes.argtypes=[ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME)]; GetSystemTimes.restype=w.BOOL
GlobalMemoryStatusEx = k32.GlobalMemoryStatusEx; GlobalMemoryStatusEx.argtypes=[ctypes.POINTER(MEMORYSTATUSEX)]; GlobalMemoryStatusEx.restype=w.BOOL
NtSetSystemInformation = ntdll.NtSetSystemInformation; NtSetSystemInformation.argtypes=[w.INT,ctypes.c_void_p,w.ULONG]; NtSetSystemInformation.restype=w.LONG
GetProcessMemoryInfo = psapi.GetProcessMemoryInfo; GetProcessMemoryInfo.argtypes=[w.HANDLE,ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),w.DWORD]; GetProcessMemoryInfo.restype=w.BOOL
GetForegroundWindow = u32.GetForegroundWindow; GetForegroundWindow.argtypes=[]; GetForegroundWindow.restype=w.HANDLE
GetWindowRect = u32.GetWindowRect; GetWindowRect.argtypes=[w.HANDLE, ctypes.c_void_p]; GetWindowRect.restype=w.BOOL
GetSystemMetrics = u32.GetSystemMetrics; GetSystemMetrics.argtypes=[w.INT]; GetSystemMetrics.restype=w.INT
GetWindowThreadProcessId = u32.GetWindowThreadProcessId; GetWindowThreadProcessId.argtypes=[w.HANDLE,ctypes.POINTER(w.DWORD)]; GetWindowThreadProcessId.restype=w.DWORD
SetWindowLongPtrW = u32.SetWindowLongPtrW; SetWindowLongPtrW.argtypes=[w.HANDLE, w.INT, ctypes.c_void_p]; SetWindowLongPtrW.restype=ctypes.c_void_p
CallWindowProcW = u32.CallWindowProcW; CallWindowProcW.argtypes=[ctypes.c_void_p, w.HANDLE, w.UINT, ctypes.c_void_p, ctypes.c_void_p]; CallWindowProcW.restype=ctypes.c_void_p
SetSystemFileCacheSize = k32.SetSystemFileCacheSize; SetSystemFileCacheSize.argtypes=[ctypes.c_size_t,ctypes.c_size_t,w.DWORD]; SetSystemFileCacheSize.restype=w.BOOL
SetProcessInformation = k32.SetProcessInformation; SetProcessInformation.argtypes=[w.HANDLE,w.DWORD,ctypes.c_void_p,w.DWORD]; SetProcessInformation.restype=w.BOOL
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

# 非游戏全屏窗口，防止假阳性触发游戏模式
IGNORE_FULLSCREEN_CLASSES = {
    "Chrome_WidgetWin_1",
    "MozillaWindowClass",
    "PPTFrameClass",
    "Progman",
    "WorkerW",
}

def is_foreground_fullscreen():
    """检测前台窗口是否为全屏模式（辅助游戏检测）"""
    hwnd = GetForegroundWindow()
    if not hwnd:
        return False
    # 窗口类名过滤
    buf = ctypes.create_unicode_buffer(256)
    if ctypes.windll.user32.GetClassNameW(hwnd, buf, 256):
        if buf.value in IGNORE_FULLSCREEN_CLASSES:
            return False
    rect = RECT()
    if not GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    screen_w = GetSystemMetrics(0)   # SM_CXSCREEN
    screen_h = GetSystemMetrics(1)   # SM_CYSCREEN
    return rect.left <= 0 and rect.top <= 0 and rect.right >= screen_w and rect.bottom >= screen_h

def get_process_times(pid):
    h = OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
    if not h: return None
    try:
        ct, et, kt, ut = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        if GetProcessTimes(h, ctypes.byref(ct), ctypes.byref(et), ctypes.byref(kt), ctypes.byref(ut)):
            return {"kernel": _ft_to_ns(kt), "user": _ft_to_ns(ut)}
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
    """设置进程内存优先级 (0=最低, 4=正常)。
    低优先级进程的页面在内存紧张时会被系统优先压缩/回收。
    纯内存管理提示，不影响进程调度，零副作用。"""
    h = OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    if not h:
        return False
    try:
        info = PROCESS_MEMORY_PRIORITY_INFORMATION(level)
        ok = SetProcessInformation(h, 0x13, ctypes.byref(info), ctypes.sizeof(info))
        return bool(ok)
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
    """标记进程为 EcoQoS(节能)或恢复正常。
    EcoQoS 让系统更积极回收该进程的物理内存页。
    纯性能提示，不影响调度正确性。"""
    h = OpenProcess(PROCESS_SET_INFORMATION, False, pid)
    if not h:
        return False
    try:
        state = PROCESS_POWER_THROTTLING_STATE(
            PROCESS_POWER_THROTTLING_CURRENT_VERSION,
            PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
            PROCESS_POWER_THROTTLING_EXECUTION_SPEED if enable else 0
        )
        return bool(SetProcessInformation(h, 0x0F, ctypes.byref(state), ctypes.sizeof(state)))
    finally:
        CloseHandle(h)

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



def get_process_private_ws(pid):
    """Private WS via QueryWorkingSetEx. Returns (private_ws, total_ws) or (None,None)."""
    h = None
    try:
        h = OpenProcess(0x0400, False, pid)
        if not h:
            return None, None
        buf_size = 16 << 20  # 16MB (1M pages max)
        buf = (ctypes.c_ubyte * buf_size)()
        if not psapi.QueryWorkingSetEx(h, ctypes.c_void_p(ctypes.addressof(buf)), buf_size):
            return None, None
        priv = 0; total = 0; n = 0
        for off in range(0, buf_size, 16):
            n += 1
            if n > 200000:  # max 200K pages (~800MB)
                break
            vp = ctypes.c_size_t.from_buffer(buf, off).value
            if vp == 0:
                break
            total += 4096
            attr = ctypes.c_size_t.from_buffer(buf, off + 8).value
            if not (attr & 0x8000):
                priv += 4096
        return priv, total
    except Exception:
        return None, None
    finally:
        if h:
            try: k32.CloseHandle(h)
            except: pass


def get_all_processes_memory():
    """Returns {pid: {"ws":bytes, "priv":bytes}} for ALL processes via NtQuerySystemInformation.
    No OpenProcess needed -- works with protected processes like AV."""
    buf_size = 1 << 20  # 1MB starting buffer
    while True:
        buf = (ctypes.c_ubyte * buf_size)()
        ret_len = w.ULONG()
        status = NtQuerySystemInformation(5, buf, buf_size, ctypes.byref(ret_len))
        if status == 0:
            break
        if status == 0xC0000004:
            buf_size = ret_len.value + (512 << 10)
            continue
        return {}
    result = {}
    off = 0
    while off < ret_len.value:
        ne = ctypes.c_uint32.from_buffer(buf, off).value
        pid = ctypes.c_size_t.from_buffer(buf, off + 0x68).value
        if pid and pid > 4:
            ws = ctypes.c_size_t.from_buffer(buf, off + 0x1F8).value
            priv = ctypes.c_size_t.from_buffer(buf, off + 0x210).value
            result[pid] = {"ws": ws, "priv": priv, "pf": 0}
        if ne == 0:
            break
        off += ne
    return result

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

# ── 进程树（父进程查询）──

def get_parent_process_name(pid):
    """返回给定 PID 的父进程名，或 None"""
    try:
        snapshot = k32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if snapshot and snapshot != w.HANDLE(-1).value:
            pe32 = (ctypes.c_ubyte * 556)()  # PROCESSENTRY32W size
            ctypes.memset(pe32, 0, 556)
            ctypes.cast(ctypes.pointer(pe32), ctypes.POINTER(w.DWORD))[0] = 556
            if k32.Process32FirstW(snapshot, ctypes.byref(pe32)):
                while True:
                    # dwSize[0], cntUsage[4], th32ProcessID[8], th32DefaultHeapID[12],
                    # th32ModuleID[20], cntThreads[24], th32ParentProcessID[28], pcPriClassBase[32], dwFlags[36], szExeFile[40]
                    entry_pid = ctypes.cast(ctypes.pointer(pe32) + 8, ctypes.POINTER(w.DWORD))[0]
                    entry_parent = ctypes.cast(ctypes.pointer(pe32) + 28, ctypes.POINTER(w.DWORD))[0]
                    if entry_pid == pid:
                        name_wchar = ctypes.c_wchar_p(ctypes.addressof(pe32) + 40)
                        name = name_wchar.value
                        k32.CloseHandle(snapshot)
                        return name
                    if not k32.Process32NextW(snapshot, ctypes.byref(pe32)):
                        break
            k32.CloseHandle(snapshot)
    except Exception:
        try:
            k32.CloseHandle(snapshot)
        except Exception:
            pass
    return None

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

def clear_system_file_cache_ex():
    """SystemFileCacheInformationEx — 强制 OS 回收文件缓存"""
    try:
        import sys
        class _SFCI(ctypes.Structure):
            _fields_ = [
                ("CurrentSize", ctypes.c_size_t),
                ("PeakSize", ctypes.c_size_t),
                ("PageFaultCount", ctypes.c_ulong),
                ("MinimumWorkingSet", ctypes.c_size_t),
                ("MaximumWorkingSet", ctypes.c_size_t),
                ("Unused", ctypes.c_size_t * 4),
            ]
        sfci = _SFCI()
        MAXSIZE = ctypes.c_size_t(sys.maxsize)
        sfci.MinimumWorkingSet = MAXSIZE
        sfci.MaximumWorkingSet = MAXSIZE
        return NtSetSystemInformation(0x15, ctypes.byref(sfci), ctypes.sizeof(sfci)) == 0
    except Exception:
        return False


# ============================================================
# 托盘百分比图标
# ============================================================

def create_tray_percent_icon(percent, color=(0, 200, 0)):
    """在 16x16 内存 DC 上绘制百分比数字图标"""
    try:
        import ctypes.wintypes as wt
        gm = ctypes.windll.gdi32
        um = ctypes.windll.user32
        hdc_screen = um.GetDC(None)
        if not hdc_screen:
            return None
        hdc = gm.CreateCompatibleDC(hdc_screen)
        hdc_mask = gm.CreateCompatibleDC(hdc_screen)
        hbm = gm.CreateCompatibleBitmap(hdc_screen, 16, 16)
        hbm_mask = gm.CreateBitmap(16, 16, 1, 1, None)
        if not all([hdc, hdc_mask, hbm, hbm_mask]):
            for h in [hdc, hdc_mask]: gm.DeleteDC(h)
            for h in [hbm, hbm_mask]: gm.DeleteObject(h)
            um.ReleaseDC(None, hdc_screen)
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
        # Draw text
        text = str(min(99, max(1, percent)))
        gm.SetBkMode(hdc, 1)  # TRANSPARENT
        gm.SetTextColor(hdc, 0xFFFFFF)  # white text
        gm.DrawTextW(hdc, text, -1, ctypes.byref(rect), 0x25)  # DT_CENTER|DT_VCENTER|DT_SINGLELINE
        gm.SelectObject(hdc, prev_font)
        gm.SelectObject(hdc, prev_bm)
        gm.DeleteDC(hdc)
        # Create icon
        ic = ctypes.windll.user32.CreateIconIndirect
        ii = (1, 0, 0, hbm, hbm_mask)
        hicon = _create_icon_indirect(*ii) if hasattr(globals(), '_create_icon_indirect') else None
        # Fallback: use ICONINFO via ctypes
        class ICONINFO(ctypes.Structure):
            _fields_ = [("fIcon", wt.BOOL), ("xHotspot", wt.DWORD), ("yHotspot", wt.DWORD),
                        ("hbmMask", wt.HBITMAP__), ("hbmColor", wt.HBITMAP__)]
        ii2 = ICONINFO(True, 0, 0, hbm_mask, hbm)
        hicon = ctypes.windll.user32.CreateIconIndirect(ctypes.byref(ii2))
        gm.DeleteObject(hbm)
        gm.DeleteObject(hbm_mask)
        gm.DeleteDC(hdc_mask)
        um.ReleaseDC(None, hdc_screen)
        return hicon
    except Exception:
        return None

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
        return s.total - s.free
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

def clear_system_file_cache():
    """清理系统文件缓存 (SetSystemFileCacheSize)"""
    try:
        return bool(SetSystemFileCacheSize(ctypes.c_size_t(-1), ctypes.c_size_t(-1), 0))
    except Exception:
        return False

def combine_memory_lists():
    """冲刷 Modified 列表以合并物理内存 — MemoryFlushModifiedList = 3 (PHNT standard)"""
    try:
        _try_enable_privilege("SeIncreaseQuotaPrivilege")
        info = w.ULONG(3)  # MemoryFlushModifiedList = 3 (PHNT standard)
        return NtSetSystemInformation(80, ctypes.byref(info), ctypes.sizeof(info)) == 0
    except Exception:
        return False

def trigger_memory_compression():
    """触发 Win10+ 内存压缩 — MemoryPurgeLowPriorityStandbyList = 5 (PHNT standard)"""
    try:
        _try_enable_privilege("SeIncreaseQuotaPrivilege")
        info = w.ULONG(5)  # MemoryPurgeLowPriorityStandbyList = 5 (PHNT standard)
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
    """清空注册表缓存 — SystemRegistryReconciliationInformation = 81 (Win8.1+)"""
    try:
        _try_enable_privilege("SeIncreaseQuotaPrivilege")
        return NtSetSystemInformation(81, None, 0) == 0
    except Exception:
        return False

def flush_volume_cache():
    """冲刷所有卷的待写缓冲区"""
    try:
        _try_enable_privilege("SeIncreaseQuotaPrivilege")
        import string, os
        for letter in string.ascii_uppercase:
            vol = f"{letter}:\\"
            if os.path.exists(vol):
                h = k32.CreateFileW(vol, 0x40000000, 3, None, 3, 0x80, None)
                if h and h != -1:
                    k32.FlushFileBuffers(h)
                    k32.CloseHandle(h)
        return True
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
_IID_IShellLinkW = (b"\x92\xca\x80\xee\x42\x74\x11\xd2\xb3\xed\x00\xc0\x4f\x99\x0e\x17")
_IID_IPersistFile = (b"\x01\x10\x0b\x00\x00\x00\x00\x00\xc0\x00\x00\x00\x00\x00\x00\x46")

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

# IShellLinkW vtbl indices: QueryInterface=0, AddRef=1, Release=2,
# GetPath=3, GetIDList=4, SetIDList=5, GetDescription=6, SetDescription=7,
# GetWorkingDirectory=8, SetWorkingDirectory=9, GetArguments=10, SetArguments=11,
# GetHotkey=12, SetHotkey=13, GetShowCmd=14, SetShowCmd=15,
# GetIconLocation=16, SetIconLocation=17, SetRelativePath=18, Resolve=19,
# SetPath=20
# IPersistFile vtbl: QI=0, AddRef=1, Release=2, GetClassID=3,
# IsDirty=4, Load=5, Save=6, SaveCompleted=7, GetCurFile=8

def set_auto_start(name, target_path, arguments="", work_dir=""):
    """通过 IShellLink 创建启动文件夹快捷方式（纯 Win32 API，无脚本引擎）"""
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
# 新增: 用户闲置检测
# ============================================================

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", w.UINT), ("dwTime", w.DWORD)]

def get_last_input_tick():
    """获取上次用户输入后的毫秒数"""
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    if GetLastInputInfo(ctypes.byref(lii)):
        return ctypes.windll.kernel32.GetTickCount() - lii.dwTime
    return 0

# ============================================================
# 新增: 系统托盘图标
# ============================================================

def tray_add(hwnd, uid, icon_handle, tip=""):
    """添加系统托盘图标"""
    nid = NOTIFYICONDATA()
    nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
    nid.hWnd = hwnd
    nid.uID = uid
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    nid.uCallbackMessage = WM_TRAYICON
    nid.hIcon = icon_handle
    nid.szTip = tip[:127]
    # NIM_SETVERSION MUST come before NIM_ADD (MSDN requirement)
    nid.uVer = 4  # NOTIFYICON_VERSION_4
    Shell_NotifyIconW(0x00000004, ctypes.byref(nid))  # NIM_SETVERSION
    nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
    return bool(Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))

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

def _dist_to_seg(px, py, x1, y1, x2, y2):
    """点到线段的最短距离"""
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = max(0, min(1, ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)))
    return ((px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2) ** 0.5

def _draw_memwise_pixels(size, buf, bg_color=(45,45,50)):
    """在 buf（BGRA bytes）上画圆+M，bg_color 为 (R,G,B) 自动转 BGRA"""
    # RGB → BGRA
    bg = (bg_color[2], bg_color[1], bg_color[0])
    cx = cy = size // 2
    R = cx - 2
    s = size / 16.0
    # 圆背景
    for y in range(size):
        for x in range(size):
            dx, dy = x - cx, y - cy
            dist = (dx*dx + dy*dy) ** 0.5
            i = (y * size + x) * 4
            if dist > R + 0.5:
                buf[i:i+4] = (0, 0, 0, 0)
            elif dist > R - 1.5:
                a = int(255 * (R + 0.5 - dist))
                buf[i:i+4] = (*bg, max(0, min(255, a)))
            else:
                buf[i:i+4] = (*bg, 255)
    # M 线段
    segs = []
    off = -2 * s
    lx = -6 * s; rx = 6 * s
    ty = -5 * s + off; by = 5 * s + off
    mx = 0; my = 1 * s + off
    segs.extend([(lx, ty, lx, by), (lx, ty, mx, my), (mx, my, rx, ty), (rx, ty, rx, by)])
    thick = 1.5 * s
    for y in range(size):
        for x in range(size):
            px, py = x - cx, y - cy
            min_d = float('inf')
            for x1, y1, x2, y2 in segs:
                d = _dist_to_seg(px, py, x1, y1, x2, y2)
                if d < min_d: min_d = d
            if min_d < thick:
                i = (y * size + x) * 4
                a = 255 if min_d < thick * 0.4 else int(255 * (thick - min_d) / (thick * 0.6))
                bg = buf[i+3]
                if bg > 0:
                    buf[i] = buf[i] * (255 - a) // 255 + 230 * a // 255
                    buf[i+1] = buf[i+1] * (255 - a) // 255 + 235 * a // 255
                    buf[i+2] = buf[i+2] * (255 - a) // 255 + 240 * a // 255
                    buf[i+3] = min(255, bg + a)
                else:
                    buf[i:i+4] = (230, 235, 240, a)
    return buf

def create_memwise_ico(path, size=32):
    """直接生成 .ico 文件，不走 HICON 中转"""
    import struct
    row = ((size * 32 + 31) // 32) * 4  # 每行 32bpp 对齐到 4 字节
    xor_size = row * size
    # BGRA 像素（从底部行开始，ICO 存储是 bottom-up）
    pixels = bytearray(xor_size)
    buf = (ctypes.c_ubyte * len(pixels)).from_buffer(pixels)
    _draw_memwise_pixels(size, buf)
    # 交换 BGRA → 自底向上排列
    bgra = bytearray(xor_size)
    for y in range(size):
        src_off = y * size * 4
        dst_off = (size - 1 - y) * row
        for x in range(size):
            pi = src_off + x * 4
            po = dst_off + x * 4
            bgra[po:po+4] = pixels[pi:pi+4]
    # AND 蒙版（32bpp 全零）
    and_row = ((size + 31) // 32) * 4
    and_mask = bytearray(and_row * size)
    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, 1))
        f.write(struct.pack("<BBBBHHII",
                size if size < 256 else 0,
                size if size < 256 else 0,
                0, 0, 1, 32, len(bgra) + len(and_mask), 22))
        f.write(bgra)
        f.write(and_mask)
    return True

def load_app_icon():
    """加载 exe 内嵌图标：遍历资源 ID，LoadImageW 从模块句柄加载"""
    import sys as _sys
    hInstance = ctypes.windll.kernel32.GetModuleHandleW(None)
    if not hInstance:
        return None
    # PyInstaller --icon 会将图标嵌入为 IDI_APPLICATION(32512)
    # 也有可能作为资源 ID 1 嵌入；遍历所有常见 ID
    for rid in (32512, 1, 101, 201):
        hIcon = ctypes.windll.user32.LoadImageW(
            hInstance, ctypes.c_void_p(rid), 1,  # IMAGE_ICON, MAKEINTRESOURCE(rid)
            16, 16,  # 托盘标准小图标尺寸
            0  # 无特殊标志
        )
        if hIcon:
            return hIcon
    # Ultimate fallback: GDI MemWise icon (never returns None)
    return create_memwise_icon(16)


def create_memwise_icon(size=32, bg_color=(45,45,50)):
    """在内存中创建 MemWise 图标，bg_color 为 (R,G,B) 自动转 BGRA
    默认深灰(45,45,50)，托盘和大图标都清晰"""
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
    cx = cy = size // 2
    R = cx - 2  # 圆半径
    s = size / 16.0  # 缩放因子

    # 绘制深色圆背景（带柔边）
    for y in range(size):
        for x in range(size):
            dx, dy = x - cx, y - cy
            dist = (dx*dx + dy*dy) ** 0.5
            i = (y * size + x) * 4
            if dist > R + 0.5:
                buf[i:i+4] = (0, 0, 0, 0)
            elif dist > R - 1.5:
                a = int(255 * (R + 0.5 - dist))
                buf[i:i+4] = (*bg, max(0, min(255, a)))
            else:
                buf[i:i+4] = (*bg, 255)

    # 用线段定义 M 形状（相对于圆心，按 size 缩放）
    # 4 条线段组成 M：左竖、左斜、右斜、右竖
    segs = []
    off = -2 * s  # 整体垂直微调
    # 左竖: (-6s~-5s, -5s+off) → (-6s~-5s, +5s+off)
    lx = -6 * s; rx = 6 * s
    ty = -5 * s + off; by = 5 * s + off
    mx = 0; my = 1 * s + off  # 中间顶点
    segs.append((lx, ty, lx, by))
    segs.append((lx, ty, mx, my))
    segs.append((mx, my, rx, ty))
    segs.append((rx, ty, rx, by))
    thick = 1.5 * s  # 线条粗细

    for y in range(size):
        for x in range(size):
            px, py = x - cx, y - cy
            min_d = float('inf')
            for x1, y1, x2, y2 in segs:
                d = _dist_to_seg(px, py, x1, y1, x2, y2)
                if d < min_d:
                    min_d = d
            if min_d < thick:
                i = (y * size + x) * 4
                if min_d < thick * 0.4:
                    a = 255
                elif min_d < thick:
                    a = int(255 * (thick - min_d) / (thick * 0.6))
                else:
                    continue
                bg = buf[i+3]
                alpha = max(0, min(255, a))
                if bg > 0:
                    buf[i] = buf[i] * (255 - alpha) // 255 + 230 * alpha // 255
                    buf[i+1] = buf[i+1] * (255 - alpha) // 255 + 235 * alpha // 255
                    buf[i+2] = buf[i+2] * (255 - alpha) // 255 + 240 * alpha // 255
                    buf[i+3] = min(255, bg + alpha)
                else:
                    buf[i:i+4] = (230, 235, 240, alpha)

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
