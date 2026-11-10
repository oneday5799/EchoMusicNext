import struct, re, sys

MAP = r"D:\Code\EchoMusicNext\build\release\app\echomusicnext.map"
EXE = r"D:\Code\EchoMusicNext\build\release\app\echomusicnext-map.exe"

d = open(EXE, 'rb').read()
pe = struct.unpack_from('<I', d, 0x3c)[0]
imagebase = struct.unpack_from('<Q', d, pe + 24 + 24)[0]

syms = []
pat = re.compile(r'^\s*([0-9a-f]{4}):([0-9a-f]{8})\s+(\S+)\s+([0-9a-f]{16})\s')
for line in open(MAP, encoding='utf-8', errors='replace'):
    m = pat.match(line)
    if m:
        va = int(m.group(4), 16)
        if va >= imagebase:
            syms.append((va - imagebase, m.group(3)))
syms.sort()

def lookup(rva):
    lo, hi = 0, len(syms)
    while lo < hi:
        mid = (lo + hi) // 2
        if syms[mid][0] <= rva:
            lo = mid + 1
        else:
            hi = mid
    if lo == 0:
        return None
    rva0, name = syms[lo - 1]
    return name, rva - rva0, syms[lo] if lo < len(syms) else None

targets = [int(a, 16) for a in sys.argv[1:]]
for t in targets:
    r = lookup(t)
    if r:
        name, off, nxt = r
        print(f"0x{t:x}  {name}+0x{off:x}")
    else:
        print(f"0x{t:x}  <no symbol>")
