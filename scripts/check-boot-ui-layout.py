#!/usr/bin/env python3
"""Execute the actual diagnostic middle layout and reject old-log underpainting."""
import hashlib,json,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1];out=root/'build/cpu-desktop/ui-layout';out.mkdir(parents=True,exist_ok=True)
s=(root/'kits/sheng/BootProgress.c').read_text()
body=s[s.index('  if(exit_snapshot.total && !bp_profile_mode)'):s.index('  if(trace_visible)')]
body=body[:body.rfind('\n  }')]
prefix=r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include "BootProgressCore.h"
#include "BootProgressLifecycle.h"
static struct bp_exits exit_records,exit_snapshot;
static unsigned exit_lock,exit_dropped;
static unsigned bp_profile_mode;
static unsigned writes[48];static char final[48][120];
#define BP_BAR_SECTION 0
static void line(unsigned row,const char *text,uint32_t color){(void)color;assert(row<48);++writes[row];snprintf(final[row],120,"%s",text);}
static void bar(unsigned row,const char *text,uint32_t color,uint32_t bg){(void)color;(void)bg;assert(row<48);++writes[row];snprintf(final[row],120,"%s",text);}
static void layout(struct bp_core *visible){(void)visible;char b[120];
'''
main=r'''
}
int main(void){
 struct bp_core core={0};
 for(unsigned pass=0;pass<4;++pass){
  memset(writes,0,sizeof(writes));
  if(pass==1){exit_records.total=1;exit_records.failed=1;strcpy(exit_records.failures[0],"p86 SIGSEGV");}
  if(pass==3){exit_records.crashes=1;strcpy(exit_records.crash[0],"p86 SIGSEGV PC100012340");strcpy(exit_records.failures[0],"ordinary SIGKILL");strcpy(exit_records.reason,"uncaught exception test reason");}
  if(pass==2)exit_lock=1;else exit_lock=0;
  exit_snapshot=exit_records;
  layout(&core);
  for(unsigned row=16;row<=23;++row)
    if(writes[row]!=(exit_records.total?1:0))fprintf(stderr,"pass%u row%u writes%u total%u\\n",pass,row,writes[row],exit_records.total);
  for(unsigned row=16;row<=23;++row)assert(writes[row]==(exit_records.total?1:0));
  if(pass==3)assert(strstr(final[18],"SIGSEGV PC100012340")||strstr(final[19],"SIGSEGV PC100012340")||
                    strstr(final[20],"SIGSEGV PC100012340")||strstr(final[21],"SIGSEGV PC100012340"));
  if(pass==3)assert(strstr(final[22],"uncaught exception test reason"));
 }
 exit_records=(struct bp_exits){0};exit_snapshot=exit_records;exit_lock=0;memset(writes,0,sizeof(writes));layout(&core);
 for(unsigned row=16;row<=23;++row)assert(!writes[row]);
 puts("PASS: actual exit layout renders summary, latest failure, crash and reason rows once; empty, contended and old-format states");
}
'''
(out/'test.c').write_text(prefix+body+main)
subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-Wno-pointer-bool-conversion','-Wno-unused-function','-fsanitize=address,undefined','-I',str(root/'kits/sheng'),str(out/'test.c'),'-o',str(out/'test')],check=True,timeout=45)
r=subprocess.run([str(out/'test')],text=True,capture_output=True,check=True,timeout=15);print(r.stdout,end='')
(out/'report.json').write_text(json.dumps(dict(passed=True,layout_body_sha256=hashlib.sha256(body.encode()).hexdigest(),pixel_writes_substituted=True,hardware_flicker_fix_observed=False),indent=2)+'\n')
