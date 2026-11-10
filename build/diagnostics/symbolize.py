"""Symbolize RVAs against a PDB via DIA, registration-free.

Usage: python -I symbolize.py <exe> <rva> [rva ...]
"""
import ctypes
import sys

import comtypes
import comtypes.client
from comtypes import GUID
from comtypes.gen import Dia2Lib as dia

CLSID_DiaSource = GUID("{E975526A-88CE-4C0D-9B4B-3B5B2A1C3E51}")


def find_msdia():
    import os
    candidates = [
        r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools"
        r"\Common7\IDE\CommonExtensions\Microsoft\TestWindow\VsTest"
        r"\TestHostNetFramework\x64\msdia140.dll",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    for root in (r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools",
                 r"C:\Program Files\Microsoft Visual Studio\2022"):
        for dirpath, _d, files in os.walk(root):
            if "msdia140.dll" in files and "x64" in dirpath.lower():
                return os.path.join(dirpath, "msdia140.dll")
    raise SystemExit("x64 msdia140.dll not found")


def make_source():
    comtypes.CoInitialize()
    path = find_msdia()
    dll = ctypes.WinDLL(path)
    dll.DllGetClassObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                      ctypes.c_void_p]
    iid_cf = comtypes.IUnknown._iid_  # placeholder replaced below
    IID_IClassFactory = GUID("{00000001-0000-0000-C000-000000000046}")
    cf = ctypes.c_void_p()
    hr = dll.DllGetClassObject(ctypes.byref(CLSID_DiaSource),
                               ctypes.byref(IID_IClassFactory),
                               ctypes.byref(cf))
    if hr != 0:
        raise SystemExit(f"DllGetClassObject hr=0x{hr & 0xffffffff:x}")
    # IClassFactory vtable: QI, AddRef, Release, CreateInstance, LockServer
    vtbl = ctypes.cast(ctypes.cast(cf, ctypes.POINTER(ctypes.c_void_p)).contents,
                       ctypes.POINTER(ctypes.c_void_p * 5)).contents
    create = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.c_void_p)(vtbl[3])
    ppv = ctypes.c_void_p()
    hr = create(cf, ctypes.byref(dia.IDiaDataSource._iid_), ctypes.byref(ppv))
    if hr != 0:
        raise SystemExit(f"IClassFactory.CreateInstance hr=0x{hr & 0xffffffff:x}")
    return dia.IDiaDataSource(ppv)


def main():
    exe = sys.argv[1]
    rvas = [int(a, 0) for a in sys.argv[2:]]
    src = make_source()
    src.loadDataForExe(exe, "", None)
    session = src.openSession()
    session.put_loadAddress(0)

    # Enumerate public/function symbols once, then nearest-match by RVA.
    table = None
    enum_tables = session.getEnumTables()
    for t in enum_tables:
        if t.name == "Symbols":
            table = t
            break
    if table is None:
        raise SystemExit("Symbols table not found")
    syms = []
    fetched = table.Item(0)
    count = fetched.Count
    for i in range(count):
        s = fetched.Item(i)
        try:
            if s.symTag in (5, 6, 10):  # Function, PublicSymbol, Data
                rva = s.relativeVirtualAddress
                if rva:
                    syms.append((rva, s.name, s.symTag, s.length))
        except Exception:
            continue
    syms.sort()
    print(f"loaded {len(syms)} symbols")

    import bisect
    starts = [s[0] for s in syms]
    for rva in rvas:
        i = bisect.bisect_right(starts, rva) - 1
        if i < 0:
            print(f"rva 0x{rva:x}: no preceding symbol")
            continue
        r, name, tag, length = syms[i]
        inside = "inside" if rva < r + max(length, 1) else "AFTER(end?)"
        delta = rva - r
        print(f"rva 0x{rva:x}: {name} +0x{delta:x} ({inside}, len=0x{length:x})")


if __name__ == "__main__":
    main()
