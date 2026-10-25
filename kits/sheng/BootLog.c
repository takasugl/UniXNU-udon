// SPDX-License-Identifier: MIT
// Minimal Udon unattended logger. With sheng-log=1 it writes a version-1
// SHLOG001 window to the final 32 MiB of userdata through NativeUfs. The
// writer runs on its own thread and records the visible diagnostic page,
// sampling profile, caught panic text and kernel message buffer every 2 s.
#include <kern/thread.h>
#include <string.h>
#include <pexpert/pexpert.h>
#include <kern/misc_protos.h>
#include <IOKit/IOLib.h>

extern int native_ufs_log_open(uint64_t *, uint64_t *, const char **);
extern int native_ufs_log_write(uint64_t, uint32_t, const void *);
extern int native_ufs_log_sync(void);
extern unsigned native_ufs_store_gpt_check(void);
extern char boot_progress_page_text[48][120];
extern char boot_progress_banner_text[49][120];
extern volatile unsigned boot_progress_banner_rows;
extern char boot_progress_panic_text[256];
extern const char *boot_progress_tag(void);
extern size_t boot_progress_profile_rows(char *, size_t);
extern int boot_reset_probe(char *, unsigned);
extern int boot_reset_bootloader(char *, unsigned);

// The leading fields of bsd/sys/msgbuf.h are stable for this source build.
struct boot_log_msgbuf { int msg_magic, msg_size, msg_bufx, msg_bufr; char *msg_bufc; };
extern struct boot_log_msgbuf *msgbufp;

enum {
  LogBlock = 4096,
  LogMsgFirst = 1,
  LogMsgBlocks = 32,
  LogSlotFirst = 33,
  LogSlotBlocks = 8,
  LogPeriodMs = 2000,
  LogMaxErrors = 3
};

struct boot_log_header {
  char magic[8];
  uint32_t version, header_bytes;
  uint64_t boot_id, first_lba;
  uint32_t window_blocks, msg_first, msg_blocks, msg_bytes;
  uint32_t slot_first, slot_blocks, slot_count, slots_written;
  uint32_t uptime_s, rounds, write_errors, gpt_open, gpt_last, state;
  char tag[32];
};

volatile uint32_t boot_log_state, boot_log_rounds, boot_log_errors;
volatile uint64_t boot_log_first_lba;
static int boot_log_started;
static uint8_t *boot_log_buffer;
static char reset_probe[240], reset_result[120];

static uint64_t ticks(void) {
  uint64_t value;
  __asm__ volatile("isb\n\tmrs %0, cntpct_el0" : "=r"(value));
  return value;
}

static size_t put(char *out, size_t at, size_t cap, const char *text, size_t max) {
  size_t n = strnlen(text, max);
  while (n && (text[n - 1] == ' ' || text[n - 1] == 0)) --n;
  for (size_t i = 0; i < n && at + 2 < cap; ++i) {
    char c = text[i];
    out[at++] = c >= 32 && c < 127 ? c : '?';
  }
  if (at + 1 < cap) out[at++] = '\n';
  return at;
}

static size_t compose(char *out, size_t cap, uint32_t slot, unsigned now) {
  char row[160];
  size_t at = 0;
  snprintf(row, sizeof row, "#slot %u t=%us tag=%s", slot, now, boot_progress_tag());
  at = put(out, at, cap, row, sizeof row);
  at = put(out, at, cap, "[page]", 8);
  for (unsigned i = 0; i < 48; ++i)
    if (boot_progress_page_text[i][0]) at = put(out, at, cap, boot_progress_page_text[i], 120);
  at = put(out, at, cap, "[banner]", 10);
  unsigned banner_rows = boot_progress_banner_rows;
  if (banner_rows > 49) banner_rows = 49;
  for (unsigned i = 0; i < banner_rows; ++i)
    at = put(out, at, cap, boot_progress_banner_text[i], 120);
  static char profile[6144];
  size_t profile_bytes = boot_progress_profile_rows(profile, sizeof profile);
  if (profile_bytes) {
    at = put(out, at, cap, "[profile]", 10);
    for (char *line = profile; *line && at + 130 < cap;) {
      char *end = strchr(line, '\n');
      size_t n = end ? (size_t)(end - line) : strlen(line);
      at = put(out, at, cap, line, n);
      if (!end) break;
      line = end + 1;
    }
  }
  if (reset_probe[0]) {
    at = put(out, at, cap, "[reset]", 8);
    at = put(out, at, cap, reset_probe, sizeof reset_probe);
    if (reset_result[0]) at = put(out, at, cap, reset_result, sizeof reset_result);
  }
  if (boot_progress_panic_text[0]) {
    at = put(out, at, cap, "[panic]", 8);
    at = put(out, at, cap, boot_progress_panic_text, sizeof boot_progress_panic_text);
  }
  return at;
}

static uint32_t copy_msgbuf(uint8_t *out) {
  memset(out, 0, LogMsgBlocks * LogBlock);
  struct boot_log_msgbuf *m = msgbufp;
  if (!m || !m->msg_bufc || m->msg_size <= 0) return 0;
  int size = m->msg_size, x = m->msg_bufx;
  if (x < 0 || x >= size) x = 0;
  uint32_t n = 0;
  for (int i = 0; i < size && n < LogMsgBlocks * LogBlock; ++i) {
    char c = m->msg_bufc[(x + i) % size];
    if (c) out[n++] = (uint8_t)c;
  }
  return n;
}

static void writer(void *arg, wait_result_t result) {
  (void)arg;
  (void)result;
  thread_set_thread_name(current_thread(), "udon_boot_log");
  uint64_t first = 0, blocks = 0;
  const char *why = "";
  boot_log_state = 1;
  while (!native_ufs_log_open(&first, &blocks, &why)) {
    if (strcmp(why, "no root layout") != 0) { boot_log_state = 3; return; }
    IOSleep(1000);
  }
  if (blocks <= LogSlotFirst + LogSlotBlocks) { boot_log_state = 3; return; }
  boot_log_first_lba = first;
  const uint32_t slot_count = (uint32_t)((blocks - LogSlotFirst) / LogSlotBlocks);
  struct boot_log_header h;
  memset(&h, 0, sizeof h);
  memcpy(h.magic, "SHLOG001", 8);
  h.version = 1;
  h.header_bytes = sizeof h;
  h.boot_id = ticks();
  h.first_lba = first;
  h.window_blocks = (uint32_t)blocks;
  h.msg_first = LogMsgFirst;
  h.msg_blocks = LogMsgBlocks;
  h.slot_first = LogSlotFirst;
  h.slot_blocks = LogSlotBlocks;
  h.slot_count = slot_count;
  h.gpt_open = h.gpt_last = native_ufs_store_gpt_check();
  strlcpy(h.tag, boot_progress_tag(), sizeof h.tag);

  uint32_t autoreset = 0;
  int reset_ok = boot_reset_probe(reset_probe, sizeof reset_probe) == 0;
  PE_parse_boot_argn("sheng-autoreset", &autoreset, sizeof autoreset);
  uint64_t frequency = 0;
  __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
  if (!frequency) frequency = 19200000;
  const uint64_t start = ticks();
  uint32_t errors = 0;
  int reset_tried = 0;
  boot_log_state = 2;
  for (;;) {
    unsigned now = (unsigned)((ticks() - start) / frequency);
    int ok = 1;
    memset(boot_log_buffer, 0, LogSlotBlocks * LogBlock);
    compose((char *)boot_log_buffer, LogSlotBlocks * LogBlock, h.slots_written, now);
    ok &= native_ufs_log_write(LogSlotFirst + (uint64_t)(h.slots_written % slot_count) * LogSlotBlocks,
                               LogSlotBlocks, boot_log_buffer);
    h.msg_bytes = copy_msgbuf(boot_log_buffer);
    ok &= native_ufs_log_write(LogMsgFirst, LogMsgBlocks, boot_log_buffer);
    if (ok) ++h.slots_written; else ++h.write_errors;
    h.uptime_s = now;
    h.rounds = ++boot_log_rounds;
    h.state = boot_log_state;
    if (!(h.rounds % 30)) h.gpt_last = native_ufs_store_gpt_check();
    memset(boot_log_buffer, 0, LogBlock);
    memcpy(boot_log_buffer, &h, sizeof h);
    ok &= native_ufs_log_write(0, 1, boot_log_buffer);
    ok &= native_ufs_log_sync();
    if (!ok) boot_log_errors = ++errors; else errors = 0;
    if (errors >= LogMaxErrors || h.gpt_last != h.gpt_open) { boot_log_state = errors >= LogMaxErrors ? 3 : 4; return; }
    if (autoreset && now >= autoreset && !reset_tried && ok) {
      reset_tried = 1;
      if (!reset_ok) {
        strlcpy(reset_result, "autoreset skipped: reset probe refused the write", sizeof reset_result);
      } else {
        int rc = boot_reset_bootloader(reset_result, sizeof reset_result);
        char tail[24];
        snprintf(tail, sizeof tail, " (returned %d)", rc);
        strlcat(reset_result, tail, sizeof reset_result);
      }
    }
    IOSleep(LogPeriodMs);
  }
}

void boot_log_tick(unsigned now) {
  (void)now;
  if (boot_log_started) return;
  boot_log_started = 1;
  uint32_t mode = 0;
  if (!PE_parse_boot_argn("sheng-log", &mode, sizeof mode) || mode != 1) return;
  boot_log_buffer = (uint8_t *)IOMallocAligned(LogMsgBlocks * LogBlock, LogBlock);
  if (!boot_log_buffer) { boot_log_state = 3; return; }
  thread_t thread;
  if (kernel_thread_start_priority(writer, 0, BASEPRI_KERNEL, &thread) == KERN_SUCCESS) {
    thread_deallocate(thread);
  } else {
    boot_log_state = 3;
  }
}
