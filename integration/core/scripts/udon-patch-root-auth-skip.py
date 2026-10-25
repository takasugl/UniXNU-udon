#!/usr/bin/env python3
"""Binary-patch the built kernel.macho to skip the rootvp-auth panic.

Reconstruction of the 2026-10-22 binary patch (flashed sha 727cd158…):
  bsd_init.c: if (autherr && !owner_authorized) panic("rootvp not authenticated after mounting");
The compiler lowers this to a conditional branch into a block that materializes
the panic string with adrp+add and calls panic.  The patch NOPs that branch.

Algorithm:
  1. locate "rootvp not authenticated after mounting" in __TEXT,__cstring;
  2. find the adrp+add pair in executable text that builds that address;
  3. find the branch (cbnz/cbz/b.cond/b) whose target is the adrp;
  4. rewrite it to NOP (0xD503201F).
Idempotent: if the branch site is already NOP, report and exit 0.
"""
import struct
import sys

PANIC_STRING = b"rootvp not authenticated after mounting @%s:%d\x00"
NOP = 0xD503201F


def sections(data):
    magic, = struct.unpack_from("<I", data, 0)
    if magic != 0xFEEDFACF:
        raise SystemExit(f"not a 64-bit mach-o: magic {magic:#x}")
    ncmds, = struct.unpack_from("<I", data, 16)
    off = 32
    secs = []
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        if cmd == 0x19:  # LC_SEGMENT_64
            nsects, = struct.unpack_from("<I", data, off + 64)
            so = off + 72
            for _ in range(nsects):
                sectname = data[so:so + 16].rstrip(b"\0").decode()
                segname = data[so + 16:so + 32].rstrip(b"\0").decode()
                addr, sz = struct.unpack_from("<QQ", data, so + 32)
                fo, = struct.unpack_from("<I", data, so + 48)
                secs.append((segname, sectname, addr, sz, fo))
                so += 80
        off += size
    return secs


def exec_ranges(secs):
    # scan whole executable-ish segments; cstring data inside them is skipped
    out = []
    for segname, sectname, addr, sz, fo in secs:
        if "cstring" in sectname.lower():
            continue
        if "TEXT" in segname or "EXEC" in segname:
            out.append((addr, sz, fo))
    return out


def segments(data):
    ncmds, = struct.unpack_from("<I", data, 16)
    off = 32
    segs = []
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        if cmd == 0x19:  # LC_SEGMENT_64
            segname = data[off + 8:off + 24].rstrip(b"\0").decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", data, off + 24)
            segs.append((segname, vmaddr, vmsize, fileoff, filesize))
        off += size
    return segs


def find_string_va(data, secs):
    # prelinked kernels may place the panic string outside __cstring; search the
    # whole file and map the file offset back through the segment table
    idx = data.find(PANIC_STRING)
    if idx < 0:
        raise SystemExit("panic string not found in binary")
    for segname, vmaddr, vmsize, fileoff, filesize in segments(data):
        if fileoff <= idx < fileoff + filesize:
            va = vmaddr + (idx - fileoff)
            return va
    raise SystemExit(f"panic string at file {idx:#x} is not inside any segment")


def decode_adrp(i, pc):
    if i & 0x9F000000 != 0x90000000:
        return None
    immlo = (i >> 29) & 3
    immhi = (i >> 5) & 0x7FFFF
    imm = (immhi << 2) | immlo
    if imm & (1 << 20):
        imm -= 1 << 21
    rd = i & 0x1F
    return ((pc & ~0xFFF) + (imm << 12)) & ((1 << 64) - 1), rd


def decode_add_imm(i):
    if i & 0xFF800000 != 0x91000000:
        return None
    imm12 = (i >> 10) & 0xFFF
    sh = (i >> 22) & 1
    return imm12 << (12 if sh else 0)


def branch_target(i, pc):
    op = i & 0x7C000000
    if (i & 0x7F000000) in (0x34000000, 0x35000000):  # cbz/cbz
        imm = (i >> 5) & 0x7FFFF
        if imm & (1 << 18):
            imm -= 1 << 19
        return pc + (imm << 2), "cbz/cbnz"
    if i & 0xFF000000 == 0x54000000:  # b.cond
        imm = (i >> 5) & 0x7FFF
        if imm & (1 << 13):
            imm -= 1 << 14
        return pc + (imm << 2), "b.cond"
    if op == 0x14000000:  # b
        imm = i & 0x3FFFFFF
        if imm & (1 << 25):
            imm -= 1 << 26
        return pc + (imm << 2), "b"
    return None


def main(path):
    data = bytearray(open(path, "rb").read())
    secs = sections(data)
    strva = find_string_va(data, secs)
    ranges = exec_ranges(secs)
    site = None
    for addr, sz, fo in ranges:
        for off in range(fo, fo + sz - 8, 4):
            i, = struct.unpack_from("<I", data, off)
            pc = addr + (off - fo)
            a = decode_adrp(i, pc)
            if not a:
                continue
            page, rd = a
            for d in range(1, 6):
                j, = struct.unpack_from("<I", data, off + 4 * d)
                if j & 0xFF800000 == 0x91000000 and (j & 0x1F) == rd and ((j >> 5) & 0x1F) == rd:
                    imm = decode_add_imm(j)
                    if page + imm == strva:
                        site = (pc, off)
                        break
            if site:
                break
        if site:
            break
    if not site:
        raise SystemExit("adrp+add for the panic string not found")
    pc, off = site
    print(f"panic string va {strva:#x}; adrp site va {pc:#x} (file {off:#x})")

    def file_to_va(o):
        for segname, vmaddr, vmsize, fileoff, filesize in segments(data):
            if fileoff <= o < fileoff + filesize:
                return vmaddr + (o - fileoff)
        return None

    # The compiler may outline the panic block into its own function (or a tail
    # call at the caller's end) whose entry precedes the string adrp by up to
    # 0x80 bytes.  Branches into that window enter the panic path; an
    # unconditional `b` entry is itself guarded by a conditional elsewhere.
    entries = set(range(pc - 0x20, pc + 4, 4))
    cands = []
    for addr, sz, fo in ranges:
        for o in range(fo, fo + sz - 4, 4):
            i, = struct.unpack_from("<I", data, o)
            bpc = addr + (o - fo)
            bt = branch_target(i, bpc)
            if bt and bt[0] in entries:
                cands.append((bpc, o, i, bt[1]))
    if not cands:
        print("no branch targets the panic block: block is orphaned -> already patched")
        return 0
    for bpc, boff, i, kind in cands:
        print(f"branch site va {bpc:#x} (file {boff:#x}) = {i:#010x} ({kind}) -> panic block")
    # NOP the CONDITIONAL instruction: either a conditional entry itself, or the
    # conditional guarding an unconditional tail-call entry (NOPing the tail `b`
    # would fall into the next function).
    targets = []
    for bpc, boff, i, kind in cands:
        if kind != "b":
            targets.append((bpc, boff, i, kind))
        else:
            for addr, sz, fo in ranges:
                for o in range(fo, fo + sz - 4, 4):
                    j, = struct.unpack_from("<I", data, o)
                    gpc = addr + (o - fo)
                    gt = branch_target(j, gpc)
                    if gt and gt[0] == bpc and gt[1] != "b":
                        targets.append((gpc, o, j, gt[1]))
    if not targets:
        print("no conditional guard found: guard already NOPed -> already patched")
        return 0
    seen = set()
    for bpc, boff, i, kind in targets:
        if bpc in seen:
            continue
        seen.add(bpc)
        print(f"NOPing conditional at va {bpc:#x} = {i:#010x} ({kind})")
        data[boff:boff + 4] = struct.pack("<I", NOP)
    open(path, "wb").write(data)
    print(f"kernel rewritten: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "out/udon/kernel/kernel.macho"))
