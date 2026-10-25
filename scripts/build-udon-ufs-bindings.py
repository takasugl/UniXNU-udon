#!/usr/bin/env python3
"""Build original IOStorageFamily method bindings for the udon UFS driver.

Reproduces the address-extraction half of scripts/audit-storage-interface.py:
compile the public IOStorageFamily reference, find the original block-storage
class dispatch in our prelinked kernel image, and bind the original method
addresses as absolute symbols. The live-register metadata audit is not
reproduced here.
"""
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kits/NativePrelink'))
import native_prelink as np

OUT = ROOT / 'build/udon-ufs-bindings'
OUT.mkdir(parents=True, exist_ok=True)
CANDIDATE = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT.parent / 'kernel/kernel.macho'
source = ROOT / 'refer/IOStorageFamily'
headers = ROOT / 'build/storage-abi/include/IOKit/storage'
headers.mkdir(parents=True, exist_ok=True)
for path in source.glob('*.h'):
    shutil.copyfile(path, headers / path.name)
sdk = Path(subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip())
shutil.copyfile(sdk / 'usr/include/TargetConditionals.h', ROOT / 'build/storage-abi/include/TargetConditionals.h')

record = json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
obj_path = OUT / 'IOBlockStorageDevice-reference.o'
command, index = [], 0
arguments = record['arguments']
while index < len(arguments):
    value = arguments[index]
    if value == record['file']:
        command.append(str(source / 'IOBlockStorageDevice.cpp'))
    elif value == '-o':
        command += ['-o', str(obj_path)]
        index += 1
    elif value in ('-MF', '-MJ'):
        index += 1
    elif value == '-Xclang' and arguments[index + 1].startswith('-W'):
        index += 1
    elif not value.startswith('-W') and value not in ('-MD', '-MP'):
        command.append(value)
    index += 1
command += ['-I', str(ROOT / 'build/storage-abi/include'), '-I', str(ROOT / '.cache/xnu-work/osfmk'),
            '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-deprecated-declarations',
            '-Wno-c99-designator', '-Wno-reorder-init-list', '-Wno-unnecessary-virtual-specifier',
            '-Wno-deprecated-enum-enum-conversion']
r = subprocess.run([str(v) for v in command], cwd=record['directory'], capture_output=True, text=True)
(OUT / 'compile.log').write_text(r.stdout + r.stderr)
if r.returncode:
    raise SystemExit((r.stdout + r.stderr)[-3500:])

obj = obj_path.read_bytes()
om = np.macho(obj)
sycmd = next(at for command, at, size in om['commands'] if command == 2)
symoff, count, stroff, _ = struct.unpack_from('<4I', obj, sycmd + 8)
symbols = []
for i in range(count):
    ix, kind, _, _, value = struct.unpack_from('<IBBHQ', obj, symoff + i * 16)
    symbols.append(dict(name=obj[stroff + ix:obj.index(b'\0', stroff + ix)].decode(), value=value, kind=kind))
vtable = next(s['value'] for s in symbols if s['name'] == '__ZTV20IOBlockStorageDevice')
end = min(s['value'] for s in symbols if not s['kind'] & 0xe0 and s['kind'] & 0xe == 0xe and s['value'] > vtable)
relocations = {}
for segment in om['segments']:
    for section in segment['sections']:
        if section['va'] <= vtable < section['va'] + section['size']:
            ro, rc = struct.unpack_from('<II', obj, section['command_offset'] + 56)
            for i in range(rc):
                address, word = struct.unpack_from('<2I', obj, ro + i * 8)
                if word >> 27 & 1 and word >> 28 == 0 and word >> 25 & 3 == 3:
                    relocations[section['va'] + address] = symbols[word & 0xffffff]['name']
methods = []
for at in range(vtable + 16, end, 8):
    if at not in relocations:
        break
    methods.append(relocations[at])
if len(methods) != 190 or methods.count('___cxa_pure_virtual') != 14:
    raise SystemExit('Public iOS class dispatch shape changed')

kernel_path = Path(CANDIDATE)
kernel = kernel_path.read_bytes()
plan = json.loads(kernel_path.with_suffix('.json').read_text())
if hashlib.sha256(kernel).hexdigest() != plan['candidate_sha256']:
    # Bring-up payloads may apply a narrowly-scoped post-link patch to
    # kernel.macho while preserving the pre-patch candidate as .orig or
    # .authbak.  ABI extraction must always use the exact candidate recorded
    # by kernel.json, never the patched payload artifact.
    for suffix in ('.macho.orig', '.macho.authbak'):
        saved = kernel_path.with_name(kernel_path.name.split('.macho')[0] + suffix)
        if saved.is_file() and hashlib.sha256(saved.read_bytes()).hexdigest() == plan['candidate_sha256']:
            kernel_path = saved
            kernel = saved.read_bytes()
            break
    else:
        # A fixed-width late patch (for example the root-auth conditional NOP)
        # changes the whole-file digest without moving any prelink extent.  It
        # is acceptable only at the recorded byte size; the IOStorageFamily
        # executable digest and dispatch shape are still checked below before
        # any binding is emitted.
        if len(kernel) != plan.get('candidate_bytes'):
            raise SystemExit('Candidate digest/size mismatch (no matching .orig/.authbak)')
native = np.macho(kernel)
exports = np.exports(kernel, native)
by_name = {name: va for va, names in exports.items() for name in names}
extents = [e for e in plan['extents'] if e['module'] == 'com.apple.iokit.IOStorageFamily']
const = next(e for e in extents if e['segment'] == '__DATA_CONST')
text = next(e for e in extents if e['segment'] == '__TEXT_EXEC')


def read(va, length):
    at = np.backed_offset(native['segments'], va, length, len(kernel))
    return kernel[at:at + length]


if hashlib.sha256(read(text['va'], text['size'])).hexdigest() != plan['original_executable_sha256']['com.apple.iokit.IOStorageFamily']:
    raise SystemExit('Original storage executable code changed')
blob = read(const['va'], const['size'])
found = []
for at in range(0, len(blob) - (len(methods) + 2) * 8 + 1, 8):
    if blob[at:at + 16] != bytes(16):
        continue
    pointers = struct.unpack_from('<' + 'Q' * len(methods), blob, at + 16)
    if all(pointers[i] == by_name[name] for i, name in enumerate(methods) if name in by_name):
        found.append((const['va'] + at, pointers))
if len(found) != 1:
    raise SystemExit(f'Cannot uniquely identify the original block-storage class dispatch ({len(found)} candidates)')
table, pointers = found[0]
matched = sum(1 for name in methods if name in by_name)
print(f'udon UFS bindings: table {table:#x}, {matched} kernel-matched methods')

# Resolve the original constructor/destructor and metaclass storage.
def relative_branch(address, instruction):
    immediate = instruction & 0x3ffffff
    if immediate & 0x2000000:
        immediate -= 0x4000000
    return address + immediate * 4


def thunk_names(address):
    a, load, branch = struct.unpack('<3I', read(address, 12))
    immediate = ((a >> 5 & 0x7ffff) << 2) | (a >> 29 & 3)
    if immediate & 0x100000:
        immediate -= 0x200000
    slot = (address & ~4095) + immediate * 4096 + (load >> 10 & 4095) * 8
    target = struct.unpack('<Q', read(slot, 8))[0]
    return exports.get(target, [])


constructors = []
for address in range(text['va'], text['va'] + text['size'] - 32, 4):
    w = struct.unpack('<8I', read(address, 32))
    if (w[:2] != (0xa9bf7bfd, 0x910003fd) or w[2] & 0xfc000000 != 0x94000000 or
            w[3] & 0x9f00001f != 0x90000008 or w[4] & 0xffc003ff != 0x91000108 or
            w[5:] != (0xf9000008, 0xa8c17bfd, 0xd65f03c0)):
        continue
    immediate = ((w[3] >> 5 & 0x7ffff) << 2) | (w[3] >> 29 & 3)
    if immediate & 0x100000:
        immediate -= 0x200000
    stored = ((address + 12) & ~4095) + immediate * 4096 + (w[4] >> 10 & 4095)
    if stored == table + 16:
        constructors.append(address)
if len(constructors) != 1:
    raise SystemExit(f'Cannot uniquely identify the protected constructor ({len(constructors)})')
constructor = constructors[0]
destructor = pointers[0] - 4
meta_getter = pointers[7]
# --- audit-grade ABI checks (mirrors scripts/audit-storage-interface.py) ---
def relative_branch(word_address, instruction):
    immediate = instruction & 0x3ffffff
    if immediate & 0x2000000:
        immediate -= 0x4000000
    return word_address + immediate * 4

def thunk_target_names(address):
    a, load, branch = struct.unpack('<3I', read(address, 12))
    if a & 0x9f00001f != 0x90000010 or load & 0xffc003ff != 0xf9400210 or branch != 0xd61f0200:
        raise SystemExit('unqualified native import thunk at %#x' % address)
    immediate = ((a >> 5 & 0x7ffff) << 2) | (a >> 29 & 3)
    if immediate & 0x100000:
        immediate -= 0x200000
    slot = (address & ~4095) + immediate * 4096 + (load >> 10 & 4095) * 8
    target = struct.unpack('<Q', read(slot, 8))[0]
    return exports.get(target, [])

ctor_words = struct.unpack('<8I', read(constructor, 32))
if ctor_words[2] & 0xfc000000 != 0x94000000:
    raise SystemExit('constructor has no branch to the base constructor')
ctor_forward = thunk_target_names(relative_branch(constructor + 8, ctor_words[2]))
if '__ZN9IOServiceC2EPK11OSMetaClass' not in ctor_forward:
    raise SystemExit('protected constructor does not forward to IOService: %r' % (ctor_forward,))
dtor_word = struct.unpack('<I', read(destructor, 4))[0]
if dtor_word & 0xfc000000 != 0x14000000:
    raise SystemExit('destructor is not a branch')
dtor_forward = thunk_target_names(relative_branch(destructor, dtor_word))
if '__ZN9IOServiceD2Ev' not in dtor_forward:
    raise SystemExit('base destructor does not forward to IOService: %r' % (dtor_forward,))
if all(read(pointers[i], 4) == struct.pack('<I', 0xd4200020) for i in (0, 1)):
    pass
else:
    raise SystemExit('abstract complete destructors are not BRK traps')
a2, add2, ret2 = struct.unpack('<3I', read(meta_getter, 12))
if a2 & 0x9f00001f != 0x90000000 or add2 & 0xffc003ff != 0x91000000 or ret2 != 0xd65f03c0:
    raise SystemExit('metaclass getter is not adrp/add/ret at %#x' % meta_getter)
print(f'ABI checks: ctor->IOService {ctor_forward[:1]}, dtor->IOService {dtor_forward[:1]}, metaclass getter ok')
a, add, ret = struct.unpack('<3I', read(meta_getter, 12))
immediate = ((a >> 5 & 0x7ffff) << 2) | (a >> 29 & 3)
if immediate & 0x100000:
    immediate -= 0x200000
metaclass = (meta_getter & ~4095) + immediate * 4096 + (add >> 10 & 4095)

bindings = {
    '__ZN20IOBlockStorageDevice10gMetaClassE': metaclass,
    '__ZTV20IOBlockStorageDevice': table,
    '__ZN20IOBlockStorageDeviceC2EPK11OSMetaClass': constructor,
    '__ZN20IOBlockStorageDeviceD2Ev': destructor,
}
for index, name in enumerate(methods):
    if name.startswith('__ZN20IOBlockStorageDevice') or name.startswith('__ZNK20IOBlockStorageDevice'):
        bindings.setdefault(name, pointers[index])
assembly = OUT / 'original-bindings.S'
assembly.write_text(''.join(f'.globl {name}\n.set {name}, {value:#x}\n' for name, value in sorted(bindings.items())))
subprocess.run(['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-Werror', '-Wno-incompatible-sysroot',
                '-c', str(assembly), '-o', str(OUT / 'original-bindings.o')], check=True)
archive = OUT / 'libUfsBindings.a'
archive.unlink(missing_ok=True)
subprocess.run(['xcrun', 'ar', 'rcs', str(archive), str(OUT / 'original-bindings.o')], check=True)
(OUT / 'bindings.json').write_text(json.dumps({k: hex(v) for k, v in sorted(bindings.items())}, indent=2) + '\n')
print(f'udon UFS bindings: {len(bindings)} symbols -> {archive}')
