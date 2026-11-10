"""Histogram exe-RVA occurrences on the crashing thread's stack region.

Verifies the recursion loop membership claimed in the pixel-snap crash report:
counts how often each loop-member RVA appears across every memory range that
belongs to the crashing thread's stack window.
"""
import struct
import sys
from pathlib import PureWindowsPath

from minidump.minidumpfile import MinidumpFile

dmp = sys.argv[1]
md = MinidumpFile.parse(dmp)
with open(dmp, "rb") as fh:
    blob = fh.read()
mods = md.modules.modules
main_exe = next(m for m in mods if str(m.name).lower().endswith("echomusicnext.exe"))
base = main_exe.baseaddress

rec = md.exception.exception_records[0]
raw = blob[rec.ThreadContext.Rva:rec.ThreadContext.Rva + rec.ThreadContext.DataSize]
rsp = struct.unpack_from("<Q", raw, 0x78 + 8 * 4)[0]
print(f"tid={rec.ThreadId} rsp=0x{rsp:x} exe base=0x{base:x}")

if md.memory_segments_64 is not None:
    segs = md.memory_segments_64.memory_segments
else:
    segs = md.memory_segments.memory_segments
ranges = [(seg.start_virtual_address, seg.start_virtual_address + seg.size,
           seg.start_file_address) for seg in segs]

# Loop members named by the report, plus a net over the AOT lambda cluster.
named = {0x872480: "refresh", 0x867db0: "validSelector", 0x17560: "slot(void())",
         0x8d290f: "y-binding(AOT)", 0x8d4630: "lambda_37", 0x8d5350: "lambda_7",
         0x8d37b0: "lambda_31"}
hits = {}
total_ptr = 0
for lo, hi, fo in ranges:
    if not (lo <= rsp < hi or abs(lo - rsp) < 4 * 1024 * 1024):
        continue  # stack window only
    data = blob[fo:fo + (hi - lo)]
    for off in range(0, len(data) - 7):
        v = struct.unpack_from("<Q", data, off)[0]
        if base <= v < base + main_exe.size:
            total_ptr += 1
            hits[v - base] = hits.get(v - base, 0) + 1

print(f"exe pointers on stack window: {total_ptr}")
named_hits = 0
for rva, label in sorted(named.items()):
    # Count exact returns and near-returns (function interiors of the same fn).
    exact = hits.get(rva, 0)
    near = sum(c for r, c in hits.items() if rva <= r < rva + 0x1000)
    print(f"  {label:18} 0x{rva:x}: exact={exact} in-fn={near}")
    named_hits += exact
cluster = sum(c for r, c in hits.items() if 0x8d0000 <= r < 0x8d6000)
print(f"  AOT lambda cluster 0x8d0000-0x8d6000 total: {cluster}")
top = sorted(hits.items(), key=lambda kv: -kv[1])[:12]
print("top RVAs:", " ".join(f"0x{r:x}x{c}" for r, c in top))
