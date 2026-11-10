"""Attribute residue frames in a dump to threads: scan every captured thread
stack for addresses landing in a given main-exe RVA window."""
import struct
import sys
from pathlib import PureWindowsPath

from minidump.minidumpfile import MinidumpFile

dmp, lo_rva, hi_rva = sys.argv[1], int(sys.argv[2], 16), int(sys.argv[3], 16)
md = MinidumpFile.parse(dmp)
with open(dmp, "rb") as fh:
    blob = fh.read()
mods = md.modules.modules
exe = next(m for m in mods if str(m.name).lower().endswith("echomusicnext.exe"))

if md.memory_segments_64 is not None:
    segs = md.memory_segments_64.memory_segments
else:
    segs = md.memory_segments.memory_segments
ranges = [(s.start_virtual_address, s.start_virtual_address + s.size, s.start_file_address)
          for s in segs]

crash_tid = md.exception.exception_records[0].ThreadId
threads = md.threads.threads
print(f"threads={len(threads)} crash_tid={crash_tid}")
for t in threads:
    tid = t.ThreadId
    stack = t.Stack
    start = getattr(stack, "StartOfMemoryRange", None)
    size = getattr(stack, "Size", None) or 0
    if start is None or not size:
        continue
    region = next((r for r in ranges if r[0] <= start < r[1]), None)
    if region is None:
        continue
    data = blob[region[2]:region[2] + min(size, region[1] - region[0])]
    hits = {}
    for off in range(0, max(0, len(data) - 8), 8):
        val = int.from_bytes(data[off:off + 8], "little")
        if exe.baseaddress <= val < exe.baseaddress + exe.size:
            rva = val - exe.baseaddress
            if lo_rva <= rva < hi_rva:
                hits[rva] = hits.get(rva, 0) + 1
    if hits:
        total = sum(hits.values())
        mark = " <== CRASHING THREAD" if tid == crash_tid else ""
        print(f"tid={tid} stack=0x{start:x}+0x{size:x} hits={total}{mark}")
        for rva, n in sorted(hits.items(), key=lambda kv: -kv[1])[:6]:
            print(f"   rva=0x{rva:x} x{n}")
