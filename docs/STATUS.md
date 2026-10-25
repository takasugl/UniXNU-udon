# Udon / PHK110 status

Status date: 2026-10-25

## Milestones reached

1. ABL loads the Mu-Silicium UEFI on the OnePlus Ace 2.
2. UniXNU and DarwinBoot launch the target XNU from the FAT payload in `super`.
3. NativeUfs publishes the OS and SystemOS windows without taking over the SM8475 SMMU.
4. The complete static + System trust cache fixes `F_ADDFILESIGS_RETURN` and permits the
   dyld shared-cache mapping (`54 files`, `62 mappings`, `kr=0`).
5. The owner boot manifest supplies `boot-manifest-hash`; a NativeRamBlock-backed APFS
   Data seed supplies writable `/private/var`.
6. `watchdogd` is isolated during bring-up because Udon has no `IOWatchdog` backend.
7. `native-data-008` remains live at 176 seconds with 117 processes and returns to
   fastboot through the 180-second diagnostic timer.

## Last observed user-space state

```text
LIVE: DEADLINE EXCEEDED - OS and diagnostic recording continue
time=176s idle=0 IRQ=332447 monitor=166 lost=43 root=0 procs=117 free=164163
stage: pid=98 ReportCrash open /private/preboot/System/Library/Caches/com.apple.dyld/dyld_shared_cache_arm64e
PROC pass0 seen0 worker2 attempt0 busy0 age0s; trace phase0 index0;
EXIT 79 nonzero12 crashsig7 drop332
```

This proves that the kernel, launchd, many daemons, SpringBoard, powerd and the
diagnostic timer are all alive. It does not prove that the iPadOS home screen rendered.

## Open gates

1. Qualify a persistent-log reader for Udon.
2. Recover the seven signal-exit records and identify why `ReportCrash` repeatedly
   samples the arm64e shared cache.
3. Continue toward a complete user interface and then the platform devices listed as
   unsupported in the README.

The current `board.toml` is prepared for a `native-data-010` evidence run. The payload
was built at 16:28 CST with SHA-256
`02abfb7392f34fd901f1157f5758a457744a42e42faef373585c17fd65aacbe2`.
Its hardware result is still pending; `payload.json` continues to say
`hardware_tested: false` until a result is recorded explicitly.

## Evidence discipline

- A live `fastboot devices` entry is required before flashing.
- `fastboot boot` returning OKAY does not prove that the booted image executed.
- USB re-enumeration alone does not prove which component initiated a reset.
- `payload.json` is a build report; it is not a hardware test certificate.
