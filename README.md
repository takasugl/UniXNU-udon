<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/logo-light.svg">
    <img alt="UniXNU" src="assets/logo-light.svg" width="200">
  </picture>
</p>

<p align="center">
  <a href="https://unixnu.com"><img alt="Documentation" src="https://img.shields.io/badge/docs-unixnu.com-2A5BD7?logo=readthedocs&logoColor=white"></a>
  <a href="https://t.me/unixnu"><img alt="Telegram" src="https://img.shields.io/badge/Telegram-@unixnu-26A5E4?logo=telegram&logoColor=white"></a>
  <a href="https://x.com/unixnu"><img alt="X" src="https://img.shields.io/badge/X-@unixnu-000000?logo=x&logoColor=white"></a>
</p>

# UniXNU-udon

> **Work in progress.** iPadOS 17.7.11 boots into userspace on the OnePlus Ace 2 / 11R
> (PHK110, Udon, SM8475). The final home screen is not reached yet.

Device repository for the OnePlus Ace 2 / 11R. It pairs with
[`uefi-udon`](../../uefi-udon) and follows the layout of
[`UniXNU-tb128fu`](https://github.com/xVanTuring/UniXNU-tb128fu) and
[`UniXNU-sheng`](https://github.com/UniXNU/UniXNU-sheng).

The target is the unchanged iPad7,1 iPadOS 17.7.11 (21H461) restore image. XNU is
source-built with 4 KiB pages and prelinked from the target kernelcache.

## Current state

| Area | State | Evidence |
| --- | --- | --- |
| UEFI, UniXNU menu, DarwinBoot | ✅ | Firmware from `uefi-udon`; payload is read from the FAT volume in `super` |
| XNU entry and diagnostics | ✅ | Panic screen, live bring-up page, process and exit sampling |
| Native UFS root | ✅ | OS and SystemOS APFS windows are published from Udon's userdata |
| dyld shared cache | ✅ | `54 files / 62 mappings / kr=0` after adding the System trust cache |
| Boot manifest | ✅ | Public `boot-manifest-hash` is derived from the device's `SHNGROOT` manifest |
| Writable Data | ✅ | 32 MiB APFS seed through NativeRamBlock |
| launchd and userspace | ⚠️ | 117 processes and 176 seconds of live execution observed |
| Automatic return to fastboot | ✅ | 180-second diagnostic timer observed on hardware |
| Persistent log retrieval | ❌ | Linux reader, UEFI mass storage and USB BOT paths are not yet qualified |
| Complete iPadOS UI | ❌ | Seven signal exits and the last visible `ReportCrash` stage still need investigation |
| GPU, audio, Wi-Fi, suspend | ❌ | Not part of this milestone |

The latest hardware run reached:

```text
time=176s ... root=0 procs=117 free=164163
stage: pid=98 ReportCrash open /private/preboot/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64e
EXIT 79 nonzero12 crashsig7 drop332
```

The device then rebooted itself into fastboot at the configured 180-second deadline.
That is no longer the earlier launchd/cache/watchdog panic path.

See [`docs/BRINGUP-2026-10-25.md`](docs/BRINGUP-2026-10-25.md) for the complete
experiment log, payload hashes and failing hypotheses.

## Relation to upstream UniXNU

This repository contains the device-side sources only:

| Path | Purpose |
| --- | --- |
| `board.toml` | SM8475, iPad7,1 IPSW, userdata windows, payload and ADT policy |
| `configs/udon_defconfig` | Kernel features used by the current build |
| `kits/sheng/` | Shared diagnostic, panic, watchdog and boot-progress implementation |
| `scripts/` | Udon ADT, UFS binding, payload, patch, flash and log tools |
| `integration/xnu/` | Bring-up XNU patches developed for Udon |
| `integration/NativeUfs.patch` | NativeUfs SM8475 changes relative to upstream |
| `integration/core/` | Additional core tools not yet upstreamed |
| `docs/` | Status and dated bring-up record |

Firmware changes live in the companion
[`uefi-udon`](../../uefi-udon) repository.

## Build

The current working procedure uses a UniXNU checkout beside this repository:

```sh
git clone --recurse-submodules https://github.com/UniXNU/UniXNU.git
git clone https://github.com/UniXNU/UniXNU-udon.git
cd UniXNU
./unixnu fetch -D ../UniXNU-udon
./unixnu defconfig udon_defconfig -D ../UniXNU-udon
./unixnu build kernel -D ../UniXNU-udon
```

The experimental root-auth step and trust-cache union are kept under
`integration/`. They must be copied into the UniXNU checkout before the corresponding
kernel and payload build:

```sh
cp ../UniXNU-udon/integration/core/scripts/*.py scripts/
cp ../UniXNU-udon/integration/xnu/*.patch patches/xnu/
python3 scripts/udon-patch-root-auth-skip.py out/udon/kernel/kernel.macho
python3 scripts/build-trustcache-container.py \
  --output out/ipsw/tc-raw/static-system.container \
  out/ipsw/tc-raw/static.trustcache \
  out/ipsw/tc-raw/system.trustcache
./unixnu build payload -D ../UniXNU-udon \
  --unique-chip-id <16-hex-digits> \
  --trust-cache out/ipsw/tc-raw/static-system.container
```

The root-auth patch is a bring-up experiment, not a production security policy. The
project does not redistribute Apple IPSW contents, firmware blobs or the platform seed.

## Hardware and recovery

- Device: OnePlus Ace 2 / 11R, PHK110 / Udon, SM8475, 12 GiB DRAM
- Active Android slot used for testing: `b`; use the serial printed by `fastboot devices`
- Payload partition: `super`; the current payload volume is 96 MiB
- Android partitions were backed up before the experiments; flashing is destructive

Read the handoff document before flashing. Keep stock `boot_b`, `vendor_boot_b`, `dtbo_b`
and `vbmeta_b` available for recovery.

## License

BSD-2-Clause-Patent. See [LICENSE](LICENSE). Some shared files retain their original
SPDX headers and provenance.
