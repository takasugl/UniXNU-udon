#!/usr/bin/env bash
# One unattended Udon iteration:
#   fastboot -> flash super payload -> run XNU -> automatic fastboot reset ->
#   temporarily boot the read-only Linux reader -> fetch/decode log -> fastboot.
# If the guarded reset probe refuses the reset, the script keeps waiting and
# accepts a manual fastboot entry without losing the persistent log.
#
# usage: [SERIAL=serial] [READER=reader.img] run-udon-unattended.sh [payload.img] [wait_seconds]
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
CORE=${UNIXNU_ROOT:-"$ROOT/../UniXNU"}
PAYLOAD=${1:-"$CORE/out/udon/payload/payload.img"}
LIMIT=${2:-420}
READER=${READER:-"$CORE/out/udon/boot/udon-linux-log-graft.img"}
LOG_OUT=${LOG_OUT:-"$ROOT/build/udon-logs"}

[ -f "$PAYLOAD" ] || { echo "missing payload: $PAYLOAD" >&2; exit 1; }
[ -f "$READER" ] || { echo "missing log reader: $READER" >&2; exit 1; }
python3 -c 'import pathlib,sys; b=pathlib.Path(sys.argv[1]).read_bytes(); sys.exit(b[-64:-60] != b"AVBf")' "$READER" ||
  { echo "log reader has no AVB footer: $READER" >&2; exit 1; }
SERIAL=${SERIAL:-}
echo "waiting for the Udon fastboot device"
while :; do
  if [ -n "$SERIAL" ]; then
    fastboot devices 2>/dev/null | grep -q "^$SERIAL[[:space:]]" && break
  else
    SERIAL=$(fastboot devices 2>/dev/null | awk 'NR==1{print $1}')
    [ -n "$SERIAL" ] && break
  fi
  sleep 2
done
present() { fastboot devices 2>/dev/null | grep -q "^$SERIAL[[:space:]]"; }

echo "[$SERIAL] flashing test payload to super"
fastboot -s "$SERIAL" flash super "$PAYLOAD"
fastboot -s "$SERIAL" reboot

# Observe an actual disconnect before accepting the next fastboot appearance.
for _ in $(seq 1 30); do present || break; sleep 1; done
echo "[$SERIAL] XNU running; waiting up to ${LIMIT}s for guarded autoreset"
deadline=$((SECONDS + LIMIT))
timed_out=0
until present; do
  if ((SECONDS >= deadline)); then
    timed_out=1
    echo "autoreset did not return in ${LIMIT}s; enter fastboot manually (the UFS log is preserved)" >&2
    deadline=$((SECONDS + 86400))
  fi
  sleep 2
done
if ((timed_out)); then
  echo "[$SERIAL] fastboot detected after timeout (manual entry or a late reset)"
else
  # USB enumeration alone cannot distinguish the PMIC autoreset from a user
  # pressing the key chord. Correlate this with the on-device observation and
  # the persistent [reset] log before calling the reset automatic.
  echo "[$SERIAL] fastboot detected within the window (reset source unverified)"
fi

echo "[$SERIAL] booting read-only Linux log reader"
fastboot -s "$SERIAL" boot "$READER"
python3 "$ROOT/scripts/read-sheng-log.py" --out "$LOG_OUT" --wait 240

echo "waiting for reader to return to fastboot"
for _ in $(seq 1 120); do
  if present; then
    echo "[$SERIAL] cycle complete; logs: $LOG_OUT"
    exit 0
  fi
  sleep 1
done
echo "reader log was fetched, but fastboot did not reappear within 120s" >&2
exit 2
