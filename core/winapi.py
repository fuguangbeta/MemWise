import ctypes, ctypes.wintypes as w, time

TH32CS_SNAPPROCESS = 2
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_SET_QUOTA = 0x0100
PROCESS_SET_INFORMATION = 0x0200
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

class LUID(ctypes.Structure):
    _fields_ = [("LowPart", w.DWORD), ("HighPart", w.LONG)]

class LUID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Luid", LUID), ("Attributes", w.DWORD)]

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
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
OpenProcessToken = k32.OpenProcessToken; OpenProcessToken.argtypes=[w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]; OpenProcessToken.restype=w.BOOL
LookupPrivilegeValueW = adv32.LookupPrivilegeValueW; LookupPrivilegeValueW.argtypes=[w.LPCWSTR, w.LPCWSTR, ctypes.POINTER(LUID)]; LookupPrivilegeValueW.restype=w.BOOL
AdjustTokenPrivileges = adv32.AdjustTokenPrivileges; AdjustTokenPrivileges.argtypes=[w.HANDLE, w.BOOL, ctypes.c_void_p, w.DWORD, ctypes.c_void_p, ctypes.c_void_p]; AdjustTokenPrivileges.restype=w.BOOL
EmptyWorkingSet = psapi.EmptyWorkingSet; EmptyWorkingSet.argtypes=[w.HANDLE]; EmptyWorkingSet.restype=w.BOOL
GetProcessTimes = k32.GetProcessTimes; GetProcessTimes.argtypes=[w.HANDLE,ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME)]; GetProcessTimes.restype=w.BOOL
GetSystemTimes = k32.GetSystemTimes; GetSystemTimes.argtypes=[ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME),ctypes.POINTER(FILETIME)]; GetSystemTimes.restype=w.BOOL
GlobalMemoryStatusEx = k32.GlobalMemoryStatusEx; GlobalMemoryStatusEx.argtypes=[ctypes.POINTER(MEMORYSTATUSEX)]; GlobalMemoryStatusEx.restype=w.BOOL
NtSetSystemInformation = ntdll.NtSetSystemInformation; NtSetSystemInformation.argtypes=[w.INT,ctypes.c_void_p,w.ULONG]; NtSetSystemInformation.restype=w.LONG
GetProcessMemoryInfo = psapi.GetProcessMemoryInfo; GetProcessMemoryInfo.argtypes=[w.HANDLE,ctypes.POINTER(PROCESS_MEMORY_COUNTERS_EX),w.DWORD]; GetProcessMemoryInfo.restype=w.BOOL
GetForegroundWindow = u32.GetForegroundWindow; GetForegroundWindow.argtypes=[]; GetForegroundWindow.restype=w.HANDLE
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

Other functions and classes remain unchanged from the current version...
