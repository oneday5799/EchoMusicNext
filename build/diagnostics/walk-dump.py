"""Walk a crashpad minidump: exception context + module-relative stack candidates."""
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
print(f"main exe base=0x{main_exe.baseaddress:x} size=0x{main_exe.size:x}")

rec = md.exception.exception_records[0]
er = rec.ExceptionRecord
raw = blob[rec.ThreadContext.Rva:rec.ThreadContext.Rva + rec.ThreadContext.DataSize]
names = ["Rax", "Rcx", "Rdx", "Rbx", "Rsp", "Rbp", "Rsi", "Rdi",
         "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15", "Rip"]
regs = {n: struct.unpack_from("<Q", raw, 0x78 + 8 * i)[0] for i, n in enumerate(names)}
print(f"tid={rec.ThreadId} code={er.ExceptionCode} addr=0x{er.ExceptionAddress:x}")
print(" ".join(f"{n}=0x{v:x}" for n, v in regs.items()))


def who(addr):
    for m in mods:
        if m.baseaddress <= addr < m.baseaddress + m.size:
            return PureWindowsPath(str(m.name)).name, addr - m.baseaddress
    return None, None


n, rva = who(regs["Rip"])
print(f"rip in {n} +0x{rva:x}" if n else "rip not in any module")

# Locate the stack region covering rsp among memory ranges (64-bit stream preferred).
if md.memory_segments_64 is not None:
    segs = md.memory_segments_64.memory_segments
else:
    segs = md.memory_segments.memory_segments
ranges = [(seg.start_virtual_address, seg.start_virtual_address + seg.size,
           seg.start_file_address) for seg in segs]
rsp = regs["Rsp"]
region = next((r for r in ranges if r[0] <= rsp < r[1]), None)
if region is None:
    print("rsp not covered by any memory range")
    raise SystemExit(0)
lo, hi, fo = region
data = blob[fo + (rsp - lo):fo + (hi - lo)]
print(f"stack range 0x{lo:x}-0x{hi:x} ({len(data)} bytes from rsp)")
count = 0
for off in range(0, len(data) - 8, 8):
    val = int.from_bytes(data[off:off + 8], "little")
    n, rva = who(val)
    if n and not n.startswith(("api-ms", "ext-ms")):
        print(f"  rsp+{off:<6} {n:<28} rva=0x{rva:x}")
        count += 1
        if count >= 60:
            break
