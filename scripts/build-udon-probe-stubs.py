#!/usr/bin/env python3
"""Build weak probe stubs with the XNU compile record (like the other archives)."""
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/udon-probe-stubs'
OUT.mkdir(parents=True, exist_ok=True)
source = ROOT / 'kits/udon/probe-stubs.c'
obj = OUT / 'probe-stubs.o'
record = json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
command, i = [], 0
arguments = record['arguments']
while i < len(arguments):
    arg = arguments[i]
    if arg == record['file']:
        command.append(source)
    elif arg == '-o':
        command += ['-o', obj]
        i += 1
    elif arg == '-Xclang' and arguments[i + 1].startswith('-W'):
        i += 1
    elif not arg.startswith('-W'):
        command.append(arg)
    i += 1
command += ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-I', OUT]
subprocess.run([str(v) for v in command], cwd=record['directory'], check=True)
archive = OUT / 'libProbeStubs.a'
archive.unlink(missing_ok=True)
subprocess.run(['ar', 'rcs', str(archive), str(obj)], check=True)
print(f'probe stubs: {archive}')
