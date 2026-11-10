import struct
import sys

from minidump.minidumpfile import MinidumpFile

dmp = sys.argv[1]
md = MinidumpFile.parse(dmp)
with open(dmp, "rb") as fh:
    blob = fh.read()
rec = md.exception.exception_records[0]
raw = blob[rec.ThreadContext.Rva:rec.ThreadContext.Rva + rec.ThreadContext.DataSize]
rsp = struct.unpack_from("<Q", raw, 0x78 + 8 * 4)[0]
print(f"rsp=0x{rsp:x}")

# Thread stack base/limit from MINIDUMP_THREAD list for the faulting thread.
# Parse the ThreadsStream manually via md.threads if available.
try:
    threads = md.threads.threads
    for t in threads:
        if t.ThreadId == rec.ThreadId:
            sb = t.Stack.StartOfMemoryRange
            sz = t.Stack.Memory.DataSize
            print(f"thread stack: start=0x{sb:x} size=0x{sz:x} end=0x{sb + sz:x}")
            print(f"rsp inside: 0x{rsp - sb:x} from stack start; "
                  f"0x{sb + sz - rsp:x} from stack end")
            break
except Exception as e:
    print("threads parse:", e)

# Committed stack region(s) around rsp from MemoryInfoList.
mi = md.memory_info
for r in (mi.infos if hasattr(mi, "infos") else mi):
    base = r.BaseAddress if hasattr(r, "BaseAddress") else r.base_address
    size = r.RegionSize if hasattr(r, "RegionSize") else r.size
    state = getattr(r, "State", None)
    protect = getattr(r, "Protect", None)
    if base <= rsp < base + size:
        print(f"rsp region: base=0x{base:x} size=0x{size:x} state={state} protect={protect}")
    # regions named stack-guard candidates near rsp
    if abs(base + size - rsp) < 0x100000 and base < rsp:
        print(f"near-below region: base=0x{base:x} size=0x{size:x} state={state} protect={protect}")
