#!/usr/bin/env python3
"""Build a fastboot-boot-only UniXNU log reader from an existing Android boot image.

The kernel (including an appended DTB, when present) is reused byte for byte.  A
small initramfs supplies busybox, the init next to this file, rebootbl and any
requested loader/modules.  Nothing on UFS is mounted or written.  Header v0 and
v3/v4 boot images are accepted so the same reader can be used by sheng and udon.

usage: build-linux-log-boot.py --boot boot.img --busybox busybox --lib ld-musl-aarch64.so.1 --rebootbl rebootbl --out log.img"""
import argparse
import gzip
import hashlib
import struct
from pathlib import Path

HERE = Path(__file__).resolve().parent
CMDLINE = b'rdinit=/init console=tty0 loglevel=4 consoleblank=0'


def cpio(entries):
    """newc archive; entries are (path, mode, data) with directories first."""
    out = bytearray()
    for ino, (name, mode, data) in enumerate(entries + [('TRAILER!!!', 0, b'')], 1):
        path = name.encode() + b'\0'
        out += b'070701' + b''.join(b'%08x' % v for v in (ino, mode, 0, 0, 1, 0, len(data), 0, 0, 0, 0, len(path), 0)) + path
        out += b'\0' * (-len(out) % 4) + data
        out += b'\0' * (-len(out) % 4)
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    for name in ('boot', 'busybox', 'rebootbl', 'out'):
        ap.add_argument('--' + name, required=True, type=Path)
    ap.add_argument('--lib', action='append', default=[], type=Path,
                    help='runtime loader/library copied to /lib (repeatable)')
    ap.add_argument('--module', action='append', default=[], type=Path)
    a = ap.parse_args()
    boot = a.boot.read_bytes()
    if boot[:8] != b'ANDROID!':
        raise SystemExit('not an Android boot image')
    version = struct.unpack_from('<I', boot, 40)[0]
    if version in (3, 4):
        kernel_size, old_ramdisk_size, os_version, header_size = struct.unpack_from('<4I', boot, 8)
        if header_size < 1580:
            raise SystemExit(f'invalid Android boot v{version} header size {header_size}')
        page = 4096
        kernel = boot[page:page + kernel_size]
        kernel_addr = tags = 0
    else:
        kernel_size, kernel_addr, old_ramdisk_size, _, second_size, _, tags, page, version, os_version = struct.unpack_from('<10I', boot, 8)
        if version != 0 or second_size:
            raise SystemExit('expected Android boot header v0, v3 or v4')
        kernel = boot[page:page + kernel_size]
    dirs = ['bin', 'dev', 'proc', 'sys', 'run', 'tmp', 'lib', 'lib/modules']
    entries = [(d, 0o40755, b'') for d in dirs]
    entries += [('dev/console', 0o20600, b''), ('init', 0o100755, (HERE / 'init').read_bytes()),
                ('bin/busybox', 0o100755, a.busybox.read_bytes()), ('bin/rebootbl', 0o100755, a.rebootbl.read_bytes())]
    entries += [('lib/' + lib.name, 0o100755, lib.read_bytes()) for lib in a.lib]
    entries += [('lib/modules/' + m.name, 0o100644, m.read_bytes()) for m in a.module]
    ramdisk = gzip.compress(cpio(entries), 9, mtime=0)
    pad = lambda b: b + b'\0' * (-len(b) % page)
    header = bytearray(page)
    header[:8] = b'ANDROID!'
    if version in (3, 4):
        struct.pack_into('<4I', header, 8, len(kernel), len(ramdisk), os_version, 1584 if version == 4 else 1580)
        struct.pack_into('<I', header, 40, version)
        header[44:44 + len(CMDLINE)] = CMDLINE
        if version == 4:
            struct.pack_into('<I', header, 1580, 0)  # no boot signature
    else:
        struct.pack_into('<10I', header, 8, len(kernel), kernel_addr, len(ramdisk), 0x01000000, 0, 0x00f00000, tags, page, 0, os_version)
        header[64:64 + len(CMDLINE)] = CMDLINE
        digest = hashlib.sha1()
        for blob in (kernel, ramdisk, b''):
            digest.update(blob)
            digest.update(struct.pack('<I', len(blob)))
        header[576:596] = digest.digest()
    image = bytes(header) + pad(kernel) + pad(ramdisk)
    a.out.write_bytes(image)
    print(f'BUILT {a.out} ({len(image)} bytes) sha256 {hashlib.sha256(image).hexdigest()} ramdisk {len(ramdisk)}')


if __name__ == '__main__':
    main()
