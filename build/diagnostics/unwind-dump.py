"""Self-contained x64 stack unwinder for crashpad minidumps.

Parses each module's PE .pdata (RUNTIME_FUNCTION / UNWIND_INFO) from the real
files on disk — no PDBs, no dbghelp — and simulates prologues to walk the
crashing thread's stack. Prints frames newest->oldest.

Usage: python -I unwind-dump.py <dump.dmp> [--all] [--exe-map]
  --all  unwind every thread with a captured context, not just the crash thread
"""
import bisect
import ctypes
import struct
import sys

from minidump.minidumpfile import MinidumpFile


def pe_pdata(path):
    """Returns (image_base, [(begin_rva, end_rva, unwind_rva), ...]) or None."""
    try:
        with open(path, "rb") as fh:
            dos = fh.read(0x40)
            if len(dos) < 0x40 or dos[:2] != b"MZ":
                return None
            e_lfanew = struct.unpack_from("<I", dos, 0x3C)[0]
            fh.seek(e_lfanew)
            pe = fh.read(24)
            if pe[:4] != b"PE\0\0":
                return None
            machine = struct.unpack_from("<H", pe, 4)[0]
            opt_size = struct.unpack_from("<H", pe, 20)[0]
            fh.seek(e_lfanew + 24)
            opt = fh.read(opt_size)
            magic = struct.unpack_from("<H", opt, 0)[0]
            base_off = 24 if magic == 0x20B else 28
            image_base = struct.unpack_from("<Q", opt, base_off)[0]
            dd_off = 112 if magic == 0x20B else 96
            exc_va, exc_sz = struct.unpack_from("<II", opt, dd_off + 3 * 8)
            if not exc_sz:
                return None
            nsec = struct.unpack_from("<H", pe, 6)[0]
            sec_off = e_lfanew + 24 + opt_size
            secs = []
            for i in range(nsec):
                fh.seek(sec_off + i * 40)
                s = fh.read(40)
                vsz, va, rawsz, rawptr = struct.unpack_from("<IIII", s, 8)
                secs.append((va, max(vsz, rawsz), rawptr, rawsz))

            def rva2off(rva):
                for va, span, rawptr, rawsz in secs:
                    if va <= rva < va + span:
                        return rawptr + (rva - va)
                return None

            off = rva2off(exc_va)
            if off is None:
                return None
            fh.seek(off)
            data = fh.read(exc_sz)
            entries = []
            for i in range(len(data) // 12):
                b, e, u = struct.unpack_from("<III", data, i * 12)
                if b or e:
                    entries.append((b, e, u))
            return image_base, entries, rva2off
    except OSError:
        return None


def parse_unwind(mod, unwind_rva):
    """Returns (flags, total_stack_bytes, prologue_end) — prologue-completed
    stack adjustment for a frame whose whole prologue ran."""
    _, _, rva2off = mod
    off = rva2off(unwind_rva)
    if off is None:
        return None
    with open(mod[3] if len(mod) > 3 else mod and "", "rb") as fh:
        pass
    return None


class Module:
    def __init__(self, base, size, path):
        self.base, self.size, self.path = base, size, path
        self.pdata = None
        self.image_base = 0
        self.rva2off = None
        self.starts = []
        pd = pe_pdata(path)
        if pd:
            self.image_base, entries, self.rva2off = pd
            self.pdata = entries
            self.starts = [e[0] for e in entries]

    def find(self, rva):
        """RUNTIME_FUNCTION containing rva (as a RETURN address)."""
        if not self.pdata:
            return None
        i = bisect.bisect_right(self.starts, rva) - 1
        if i < 0:
            return None
        b, e, u = self.pdata[i]
        if b <= rva < e:
            return (b, e, u)
        return None

    def unwind_info(self, unwind_rva):
        off = self.rva2off(unwind_rva)
        if off is None:
            return None
        with open(self.path, "rb") as fh:
            fh.seek(off)
            info = fh.read(64)
        return info

    def unwind_adj(self, unwind_rva, rva, func_begin):
        """Adj for an unwind-info RVA at absolute-module rva belonging to the
        function starting at func_begin; follows chained info."""
        info = self.unwind_info(unwind_rva)
        if info is None:
            return None
        flags = (info[0] >> 3) & 7
        cnt = info[2]
        codes_off = 4
        adj = 0
        delta = rva - func_begin
        i = 0
        while i < cnt:
            if delta < info[codes_off + i * 2]:
                break
            b2 = info[codes_off + i * 2 + 1]
            op = b2 & 0xF
            opinfo = b2 >> 4
            if op == 0:
                adj += 8
                i += 1
            elif op == 1:
                if opinfo == 0:
                    sz = struct.unpack_from("<H", info, codes_off + (i + 1) * 2)[0]
                    adj += sz * 8
                    i += 2
                else:
                    sz = struct.unpack_from("<I", info, codes_off + (i + 1) * 2)[0]
                    adj += sz * 8
                    i += 3
            elif op == 2:
                adj += (opinfo + 1) * 8
                i += 1
            elif op == 3:
                i += 1
            elif op == 4:
                i += 2
            elif op == 5:
                i += 3
            elif op == 6:
                i += 2
            elif op == 7:
                i += 3
            elif op == 8:
                adj += 8 if opinfo == 0 else 16
                i += 1
            else:
                i += 1
        if flags & 4:  # UNW_FLAG_CHAININFO: the chained entry describes the
            # same frame (joined prologue), not the caller.
            end_off = codes_off + ((cnt + 1) & ~1) * 2
            cb, ce, cu = struct.unpack_from("<III", info, end_off)
            more = self.unwind_adj(cu, rva, cb)
            if more is None:
                return None
            adj += more
        return adj

    def stack_adjust(self, rva):
        rf = self.find(rva)
        if not rf:
            return None
        b, e, u = rf
        return self.unwind_adj(u, rva, b)


def main():
    dmp = next(a for a in sys.argv[1:] if not a.startswith("--"))
    all_threads = "--all" in sys.argv
    md = MinidumpFile.parse(dmp)
    exc = md.exception.exception_records[0]
    crash_tid = exc.ThreadId

    if md.memory_segments_64 is not None:
        segs = md.memory_segments_64.memory_segments
    else:
        segs = md.memory_segments.memory_segments
    ranges = sorted([(s.start_virtual_address,
                      s.start_virtual_address + s.size, s.start_file_address)
                     for s in segs])
    starts = [r[0] for r in ranges]

    with open(dmp, "rb") as cache_fh:
        pass

    def read_mem(addr, size):
        i = bisect.bisect_right(starts, addr) - 1
        if i < 0:
            return b""
        base, end, foff = ranges[i]
        if addr + size > end:
            size = end - addr
        if size <= 0:
            return b""
        with open(dmp, "rb") as fh:
            fh.seek(foff + (addr - base))
            return fh.read(size)

    def readq(addr):
        d = read_mem(addr, 8)
        return struct.unpack("<Q", d)[0] if len(d) == 8 else None

    mods = []
    for m in md.modules.modules:
        mod = Module(m.baseaddress, m.size, str(m.name))
        mods.append(mod)

    def mod_of(pc):
        for mod in mods:
            if mod.base <= pc < mod.base + mod.size:
                return mod
        return None

    def name_of(mod):
        return mod.path.replace("\\", "/").rstrip("/").split("/")[-1]

    # exe map
    exesyms = []
    try:
        import re
        MAP = r"D:\Code\EchoMusicNext\build\release\app\echomusicnext.map"
        pat = re.compile(r'^\s*([0-9a-f]{4}):([0-9a-f]{8})\s+(\S+)\s+([0-9a-f]{16})\s')
        for line in open(MAP, encoding="utf-8", errors="replace"):
            m2 = pat.match(line)
            if m2:
                va = int(m2.group(4), 16)
                if va >= 0x140000000:
                    exesyms.append((va - 0x140000000, m2.group(3)))
        exesyms.sort()
        exe_starts = [s[0] for s in exesyms]
    except OSError:
        exe_starts = []

    def exe_sym(rva):
        i = bisect.bisect_right(exe_starts, rva) - 1
        return exesyms[i][1] if i >= 0 and exesyms else None

    def walk(tid, raw_ctx):
        rsp = struct.unpack_from("<Q", raw_ctx, 0x98)[0]
        rip = struct.unpack_from("<Q", raw_ctx, 0xF8)[0]
        frames = []
        seen = 0
        for _ in range(400):
            frames.append((rip, rsp))
            seen += 1
            mod = mod_of(rip)
            nxt = None
            if mod and mod.pdata:
                adj = mod.stack_adjust(rip - mod.base)
                if adj is not None:
                    ret = readq(rsp + adj)
                    if ret is not None and mod_of(ret):
                        nxt = (ret, rsp + adj + 8)
            if nxt is None and mod:
                # R11-based JIT wrappers, machframe edges and decode gaps:
                # scan a small window above rsp for the first module-code
                # pointer and treat it as the return address.
                for delta in range(0, 0x600, 8):
                    v = readq(rsp + delta)
                    if v is not None and mod_of(v):
                        nxt = (v, rsp + delta + 8)
                        break
            if nxt is None:
                # leaf or unknown: pop one slot
                ret = readq(rsp)
                if ret is None:
                    break
                nxt = (ret, rsp + 8)
            if nxt[0] == 0:
                break
            rip, rsp = nxt
        return frames

    def dump_thread(tid, raw):
        rsp = struct.unpack_from("<Q", raw, 0x98)[0]
        rip = struct.unpack_from("<Q", raw, 0xF8)[0]
        print(f"\n=== tid={tid} rsp=0x{rsp:x} rip=0x{rip:x} ===")
        if "--regs" in sys.argv:
            names = ["Rax", "Rcx", "Rdx", "Rbx", "Rsp", "Rbp", "Rsi", "Rdi",
                     "R8", "R9", "R10", "R11", "R12", "R13", "R14", "R15"]
            for i, n in enumerate(names):
                v = struct.unpack_from("<Q", raw, 0x78 + 8 * i)[0]
                print(f"  {n}=0x{v:x}")
            for reg_i in (0, 1, 2, 3):  # Rax Rcx Rdx Rbx
                v = struct.unpack_from("<Q", raw, 0x78 + 8 * reg_i)[0]
                if v:
                    d = read_mem(v, 48)
                    if d:
                        hx = " ".join(f"{b:02x}" for b in d)
                        print(f"  [{names[reg_i]}] {hx}")
                    else:
                        print(f"  [{names[reg_i]}] <unreadable>")
        for fr_rip, fr_rsp in walk(tid, raw):
            mod = mod_of(fr_rip)
            if mod:
                tag = name_of(mod)
                rva = fr_rip - mod.base
                extra = ""
                if tag == "echomusicnext.exe":
                    s = exe_sym(rva)
                    if s:
                        extra = f"  {s[:100]}"
                print(f"  {tag}+0x{rva:x}{extra}")
            else:
                print(f"  0x{fr_rip:x}")

    threads = {t.ThreadId: t for t in md.threads.threads}
    if all_threads:
        for t in md.threads.threads:
            t0 = t.ThreadContext
            if t0 and t0.DataSize:
                with open(dmp, "rb") as fh:
                    fh.seek(t0.Rva)
                    raw = fh.read(t0.DataSize)
                dump_thread(t.ThreadId, raw)
    else:
        t0 = exc.ThreadContext  # exception-time context for the crash thread
        with open(dmp, "rb") as fh:
            fh.seek(t0.Rva)
            raw = fh.read(t0.DataSize)
        dump_thread(crash_tid, raw)


if __name__ == "__main__":
    main()
