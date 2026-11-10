"""Enumerate a process's threads grouped by start-address module."""
import ctypes
import ctypes.wintypes as wt
import struct
import sys

pid = int(sys.argv[1])

TH32CS_SNAPMODULE = 0x8
TH32CS_SNAPTHREAD = 0x4
THREAD_QUERY_INFORMATION = 0x0040

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
nt = ctypes.WinDLL("ntdll")


class MODULEENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("th32ModuleID", wt.DWORD),
                ("th32ProcessID", wt.DWORD), ("GlblcntUsage", wt.DWORD),
                ("ProccntUsage", wt.DWORD), ("modBaseAddr", ctypes.c_void_p),
                ("modBaseSize", wt.DWORD), ("hModule", wt.HMODULE),
                ("szModule", ctypes.c_wchar * 256), ("szExePath", ctypes.c_wchar * 260)]


class THREADENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ThreadID", wt.DWORD), ("th32OwnerProcessID", wt.DWORD),
                ("tpBasePri", wt.LONG), ("tpDeltaPri", wt.LONG), ("dwFlags", wt.DWORD)]


k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
k32.Module32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
k32.Module32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(MODULEENTRY32W)]
k32.Thread32First.argtypes = [wt.HANDLE, ctypes.POINTER(THREADENTRY32)]
k32.Thread32Next.argtypes = [wt.HANDLE, ctypes.POINTER(THREADENTRY32)]
k32.OpenThread.restype = wt.HANDLE

h = k32.CreateToolhelp32Snapshot(TH32CS_SNAPMODULE, pid)
mods = []
me = MODULEENTRY32W()
me.dwSize = ctypes.sizeof(me)
ok = k32.Module32FirstW(h, ctypes.byref(me))
while ok:
    mods.append((me.modBaseAddr, me.modBaseSize, me.szModule))
    ok = k32.Module32NextW(h, ctypes.byref(me))
k32.CloseHandle(h)

# NtQueryInformationThread(ThreadBasicInformation=0) ->
#   THREAD_BASIC_INFORMATION { NTSTATUS, PVOID TebBase, CLIENT_ID, AFFINITY, KPRIORITY }
# Thread start address is at TEB + 0x08 on x64 (NtQueryInformationThread with
# ThreadQuerySetWin32StartAddress=9 is easier).
nt.NtQueryInformationThread.argtypes = [wt.HANDLE, ctypes.c_uint, ctypes.c_void_p,
                                        wt.ULONG, ctypes.POINTER(wt.ULONG)]
buf = ctypes.c_uint64(0)
retlen = wt.ULONG(0)


def start_address(tid):
    t = k32.OpenThread(THREAD_QUERY_INFORMATION, False, tid)
    if not t:
        return None
    try:
        status = nt.NtQueryInformationThread(t, 9, ctypes.byref(buf), 8,
                                             ctypes.byref(retlen))
        if status != 0:
            return None
        return buf.value
    finally:
        k32.CloseHandle(t)


def which_module(addr):
    if addr is None:
        return "<denied>"
    for base, size, name in mods:
        if base <= addr < base + size:
            return name
    return f"0x{addr:x} (<no module>)"


h = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
te = THREADENTRY32()
te.dwSize = ctypes.sizeof(te)
counts = {}
ok = k32.Thread32First(h, ctypes.byref(te))
while ok:
    if te.th32OwnerProcessID == pid:
        name = which_module(start_address(te.th32ThreadID))
        counts[name] = counts.get(name, 0) + 1
    ok = k32.Thread32Next(h, ctypes.byref(te))
k32.CloseHandle(h)

total = sum(counts.values())
print(f"threads: {total}")
for name, count in sorted(counts.items(), key=lambda kv: -kv[1]):
    print(f"  {count:3d}  {name}")
