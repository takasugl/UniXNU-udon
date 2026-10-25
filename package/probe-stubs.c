/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Weak stubs for optional components that are referenced by the linked UFS
 * driver but whose archives are not part of this bring-up configuration. */
#ifdef __cplusplus
extern "C" {
#endif
__attribute__((weak)) void native_legacy_display_probe(void) {}
__attribute__((weak)) void native_legacy_display_late_probe(void) {}
__attribute__((weak)) void native_mobile_graphics_client_probe(void) {}
__attribute__((weak)) void boot_progress_poll(void) {}
__attribute__((weak)) unsigned char verified_root_key[64];
__attribute__((weak)) void *verified_root_policies[8];
__attribute__((weak)) unsigned int verified_root_policy_count;
__attribute__((weak)) int vr_open(void) { return -1; }
__attribute__((weak)) int vr_verify_block(void) { return -1; }
__attribute__((weak)) int vr_xnu_crypto(void) { return -1; }
#ifdef __cplusplus
}
#endif
