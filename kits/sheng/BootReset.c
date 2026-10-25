// SPDX-License-Identifier: MIT
// SM8475 uses the same PMIC-arbiter windows and PMK8350 SDAM reboot cell as
// the guarded reset implementation in package/.  The implementation probes
// the arbiter version, APID ownership and cell readability before any write.
#include "../../package/BootReset.c"
