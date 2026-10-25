#!/usr/bin/env python3
"""Build a DarwinBoot/UniXNU trust-cache offset-table container.

The sidecar format starts with a module count, followed by absolute module
offsets. Each module is an unchanged version-2 trust-cache payload.
"""

import argparse
import hashlib
import os
import struct
from pathlib import Path


def validate_module(path):
    data = path.read_bytes()
    if len(data) < 24:
        raise SystemExit(f"{path}: truncated trust-cache module")
    version, count = struct.unpack_from("<II", data, 0)[0], struct.unpack_from("<I", data, 20)[0]
    expected = 24 + count * 24
    if version != 2 or len(data) != expected:
        raise SystemExit(
            f"{path}: expected version-2 module with {count} entries and {expected} bytes, "
            f"got version {version}, {len(data)} bytes"
        )
    return data


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", "-o", type=Path, required=True)
parser.add_argument("modules", nargs="+", type=Path)
args = parser.parse_args()

modules = [validate_module(path) for path in args.modules]
header_size = 4 * (len(modules) + 1)
offsets = []
cursor = header_size
for module in modules:
    offsets.append(cursor)
    cursor += len(module)
container = struct.pack(f"<{len(offsets) + 1}I", len(modules), *offsets) + b"".join(modules)

args.output.parent.mkdir(parents=True, exist_ok=True)
temporary = args.output.with_name(args.output.name + ".partial")
temporary.write_bytes(container)
os.replace(temporary, args.output)

print(f"wrote {args.output}: {len(modules)} modules, {len(container)} bytes")
for path, module, offset in zip(args.modules, modules, offsets):
    entries = struct.unpack_from("<I", module, 20)[0]
    print(
        f"  offset={offset:#x} entries={entries} bytes={len(module)} "
        f"sha256={hashlib.sha256(module).hexdigest()} {path}"
    )
print(f"container_sha256={hashlib.sha256(container).hexdigest()}")
