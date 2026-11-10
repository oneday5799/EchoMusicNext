"""Map RVAs in a PE (Qt6Qml.dll etc.) to function begin (via .pdata) and the
nearest export at or before that function — enough to name QV4 internals
without PDBs.

Usage: python -I qt-rva-name.py <file.dll> <rva> [rva...]
"""
import bisect
import struct
import sys


def pe(path):
    with open(path, "rb") as fh:
        dos = fh.read(0x40)
        e_lfanew = struct.unpack_from("<I", dos, 0x3C)[0]
        fh.seek(e_lfanew)
        pe = fh.read(24)
        opt_size = struct.unpack_from("<H", pe, 20)[0]
        fh.seek(e_lfanew + 24)
        opt = fh.read(opt_size)
        magic = struct.unpack_from("<H", opt, 0)[0]
        dd_off = 112 if magic == 0x20B else 96
        dirs = struct.unpack_from("<II", opt, dd_off)
        exc_va, exc_sz = struct.unpack_from("<II", opt, dd_off + 3 * 8)
        exp_va, exp_sz = struct.unpack_from("<II", opt, dd_off + 0 * 8)
        nsec = struct.unpack_from("<H", pe, 6)[0]
        sec_off = e_lfanew + 24 + opt_size
        secs = []
        for i in range(nsec):
            fh.seek(sec_off + i * 40)
            s = fh.read(40)
            vsz, va, rawsz, rawptr = struct.unpack_from("<IIII", s, 8)
            secs.append((va, max(vsz, rawsz), rawptr))

        def rva2off(rva):
            for va, span, rawptr in secs:
                if va <= rva < va + span:
                    return rawptr + (rva - va)
            return None

        entries = []
        if exc_sz:
            fh.seek(rva2off(exc_va))
            data = fh.read(exc_sz)
            for i in range(len(data) // 12):
                b, e, u = struct.unpack_from("<III", data, i * 12)
                if b or e:
                    entries.append((b, e, u))

        exports = []  # (rva, name)
        if exp_va:
            fh.seek(rva2off(exp_va))
            d = fh.read(40)
            nfun, nnam = struct.unpack_from("<II", d, 16 + 4)  # after Base
            nfun = struct.unpack_from("<I", d, 20)[0]
            nnam = struct.unpack_from("<I", d, 24)[0]
            af, an, ao = struct.unpack_from("<III", d, 28)
            fh.seek(rva2off(an))
            name_rvas = struct.unpack("<%dI" % nnam, fh.read(4 * nnam))
            fh.seek(rva2off(ao))
            ords = struct.unpack("<%dH" % nnam, fh.read(2 * nnam))
            fh.seek(rva2off(af))
            func_rvas = struct.unpack("<%dI" % nfun, fh.read(4 * nfun))
            for i in range(nnam):
                nr = name_rvas[i]
                fh.seek(rva2off(nr))
                raw = fh.read(160)
                name = raw.split(b"\0")[0].decode("ascii", "replace")
                exports.append((func_rvas[ords[i]], name))
        exports.sort()
    return entries, exports


def main():
    path = sys.argv[1]
    rvas = [int(a, 16) if not a.startswith("0x") else int(a, 16)
            for a in sys.argv[2:]]
    pdata, exports = pe(path)
    starts = [e[0] for e in pdata]
    exp_starts = [e[0] for e in exports]
    for r in rvas:
        i = bisect.bisect_right(starts, r) - 1
        if i < 0:
            print(f"0x{r:x}  (no function)")
            continue
        b, e, u = pdata[i]
        j = bisect.bisect_right(exp_starts, b) - 1
        exp = ""
        if j >= 0:
            er, en = exports[j]
            # only trust the nearest export if it's close to this function
            if b - er < 0x400:
                exp = f"  exp~{en} (+0x{b - er:x})"
        print(f"0x{r:x}  func 0x{b:x}-0x{e:x} (off +0x{r - b:x}){exp}")


if __name__ == "__main__":
    main()
