# Bring-up integration

These files are part of the Udon experiment but still need to be folded into the
corresponding upstream projects.

## XNU patches

`xnu/*.patch` contains the source-level diagnostics and bring-up changes for:

- initial Udon boot and syscall tracing;
- read/write-lock and page-fault diagnostics;
- `openat` and shared-cache mapping probes;
- cache preflight tracing.

Apply them to the UniXNU core checkout when reproducing the current diagnostic
kernel. Stop any probe that unconditionally calls `panic()` before building a
normal userspace image.

## NativeUfs

`NativeUfs.patch` is relative to the upstream NativeUfs commit used by this checkout.
It contains the SM8475 SMMU bypass, diagnostic UFS errors, unverified window
publication, volume lookup by UUID and owner manifest digest publication.

The SMMU bypass is board-specific and must not be generalized without hardware
evidence on another SoC.

## Core scripts

`core/scripts/` contains:

- `udon-patch-root-auth-skip.py`: locate and NOP the conditional root-auth panic
  guard in a linked kernel;
- `build-trustcache-container.py`: build the offset-table container expected by
  DarwinBoot/UniXNU;
- `save-xnu-patch.py`: the version that accepts `XNU_WORK` for a staged XNU tree.

The root-auth patch exists only to reach the next bring-up gate. It should not be used
as a security design.
