#!/usr/bin/env python3
"""Static checks that do not require Xcode, an IPSW, or a connected phone."""

from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    sys.exit("check-repository.py requires Python 3.11 or newer")

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []


def require(path: str) -> Path:
    candidate = ROOT / path
    if not candidate.exists():
        ERRORS.append(f"missing required path: {path}")
    return candidate


def run(command: list[str]) -> None:
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        detail = (result.stdout + result.stderr).strip()
        ERRORS.append(f"command failed: {' '.join(command)}\n{detail}")


for path in (
    "board.toml",
    "configs/udon_defconfig",
    "kits/udon/ShengPlatformPower.cpp",
    "kits/udon/probe-stubs.c",
    "kits/udon/BootProcessProbe.c",
    "integration/NativeUfs.patch",
    "integration/core/UniXNU-core-changes.patch",
    "integration/core/UniXNU.commit",
    "integration/core/NativeUfs.commit",
    "scripts/bootstrap-core.sh",
):
    require(path)

board_path = require("board.toml")
if board_path.is_file():
    with board_path.open("rb") as stream:
        board = tomllib.load(stream)
    if board.get("board", {}).get("name") != "udon":
        ERRORS.append("board.toml [board].name must be udon")
    if board.get("board", {}).get("soc") != "SM8475":
        ERRORS.append("board.toml [board].soc must be SM8475")
    ipsw = board.get("ipsw", {})
    if (ipsw.get("product"), ipsw.get("build")) != ("iPad7,1", "21H461"):
        ERRORS.append("board.toml must target iPad7,1 21H461")
    payload = board.get("payload", {})
    if payload.get("volume") != "UDONESP" or payload.get("size_mib") != 96:
        ERRORS.append("payload volume must be UDONESP at 96 MiB")
    if payload.get("adt", {}).get("unique_chip_id") != "required":
        ERRORS.append("the platform seed must remain an external input")
    args = "\n".join(payload.get("kernel_args", []))
    for argument in (
        "sheng-pmgr=2",
        "native-ufs-root=1",
        "sheng-disable-watchdogd=1",
        "sheng-log=1",
    ):
        if argument not in args:
            ERRORS.append(f"missing kernel argument: {argument}")

for commit_file in ("integration/core/UniXNU.commit", "integration/core/NativeUfs.commit"):
    path = ROOT / commit_file
    if path.is_file():
        value = path.read_text().strip()
        if len(value) != 40 or any(ch not in "0123456789abcdef" for ch in value):
            ERRORS.append(f"{commit_file} must contain one lowercase 40-hex commit")

git_files = subprocess.run(
    ["git", "ls-files"], cwd=ROOT, text=True, capture_output=True, check=False
)
if git_files.returncode == 0:
    forbidden = {".img", ".macho", ".ipsw", ".dmg", ".dylib", ".efi", ".bin"}
    for name in git_files.stdout.splitlines():
        if Path(name).suffix.lower() in forbidden:
            ERRORS.append(f"proprietary/build artifact must not be tracked: {name}")

for directory in ("scripts", "integration/core/scripts", "package/linux-log"):
    for path in sorted((ROOT / directory).glob("*.py")):
        try:
            py_compile.compile(path, doraise=True)
        except py_compile.PyCompileError as error:
            ERRORS.append(str(error))

for path in sorted((ROOT / "scripts").glob("*.sh")):
    run(["bash", "-n", str(path)])

if ERRORS:
    print("Udon repository check failed:", file=sys.stderr)
    for error in ERRORS:
        print(f"- {error}", file=sys.stderr)
    sys.exit(1)

print("Udon repository check passed")
