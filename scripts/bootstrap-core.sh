#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CORE=${1:-${UNIXNU_ROOT:-"$ROOT/../UniXNU"}}
PIN=$(tr -d '[:space:]' < "$ROOT/integration/core/UniXNU.commit")
NATIVE_PIN=$(tr -d '[:space:]' < "$ROOT/integration/core/NativeUfs.commit")

say() {
  printf '[udon-bootstrap] %s\n' "$*"
}

die() {
  printf '[udon-bootstrap] error: %s\n' "$*" >&2
  exit 1
}

if [[ ! -e "$CORE" ]]; then
  say "cloning UniXNU into $CORE"
  git clone https://github.com/UniXNU/UniXNU.git "$CORE"
fi
[[ -d "$CORE/.git" ]] || die "$CORE is not a Git checkout"

if [[ "$(git -C "$CORE" rev-parse HEAD)" != "$PIN" ]]; then
  [[ -z "$(git -C "$CORE" status --porcelain)" ]] ||
    die "$CORE is dirty; check out commit $PIN in a clean dependency tree first"
  say "checking out UniXNU $PIN"
  git -C "$CORE" switch --detach "$PIN"
fi

say "initializing NativeUfs"
git -C "$CORE" submodule update --init drivers/NativeUfs
actual_native=$(git -C "$CORE/drivers/NativeUfs" rev-parse HEAD)
[[ "$actual_native" == "$NATIVE_PIN" ]] ||
  die "NativeUfs is $actual_native, expected $NATIVE_PIN"

apply_once() {
  local repo=$1
  local patch=$2
  if git -C "$repo" apply --reverse --check "$patch" >/dev/null 2>&1; then
    say "already applied: $(basename "$patch")"
    return
  fi
  git -C "$repo" apply --check "$patch"
  git -C "$repo" apply "$patch"
  say "applied: $(basename "$patch")"
}

apply_once "$CORE" "$ROOT/integration/core/UniXNU-core-changes.patch"
apply_once "$CORE/drivers/NativeUfs" "$ROOT/integration/NativeUfs.patch"

mkdir -p "$CORE/patches/xnu" "$CORE/scripts"
cp "$ROOT"/integration/xnu/*.patch "$CORE/patches/xnu/"
cp "$ROOT"/integration/core/scripts/*.py "$CORE/scripts/"

say "core ready at $CORE"
say "patches and Udon tools are installed"
