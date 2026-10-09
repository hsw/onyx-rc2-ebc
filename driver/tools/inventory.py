#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Inventory of the EBC span of the stock RC2 kernel Image: one row per kallsyms function, with the objdiff verdict
(vs the public .uu objects), the public C source where one exists, and liveness (direct BL/B callers and pointer
references outside the kallsyms_addresses table).  Read-only on the Image.

usage: python3 -I inventory.py IMAGE KALLSYMS OBJDIFF.tsv > inventory.tsv
       (OBJDIFF.tsv from `objdiff.py ... --tsv`.)  KALLSYMS_TAB below is the kallsyms_addresses range of the 2017 Image;
       for another Image take it from kernel/extract_kallsyms.py's stderr ('addr_off').
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kdis  # noqa: E402

SPAN = (0xc060b29c, 0xc0617604)
EXTRA = (0xc0419b1c, 0xc0419c30, 0xc0419c3c, 0xc0419c6c, 0xc08b4604, 0xc08b65bc)
ASM = (0xc06132a4, 0xc0614ab8)
KALLSYMS_TAB = (0xc090d740, 0xc0933450)      # kallsyms_addresses (file 0x505740 .. num_syms 0x52b450)
PUBLIC_C = {}
for n in ('set_epd_info ebc_io_ctl support_pvi_waveform get_lut_position set_end_display get_bootup_logo_cycle '
          'is_bootup_ani_loop is_need_show_lowpower_pic support_bootup_ani get_bootup_ani_mode '
          'support_tps_3v3_always_alive').split():
    PUBLIC_C[n] = 'hardware_epd_public.c'
for n in ('rk29ebc_dbg_lve_set rk29ebc_dbg_lve_show').split():
    PUBLIC_C[n] = 'ebc_dbg/rk29_ebc_dbg.c'


def main():
    img = open(sys.argv[1], 'rb').read()
    syms = kdis.Syms(sys.argv[2])
    od = {}
    for l in open(sys.argv[3]):
        if l.startswith('#'):
            continue
        p = l.rstrip('\n').split('\t')
        if p[2]:
            od[int(p[2], 16)] = (p[0], p[5], p[3])
    funcs = [(a, n) for a, t, n in syms.s if t in 'tT' and ((SPAN[0] <= a < SPAN[1] and not (ASM[0] < a < ASM[1]
             and not n.endswith('_sARM'))) or a in EXTRA)]
    want = {a: [] for a, _ in funcs}
    text_end = 0xc0a02000
    for off in range(0, text_end - kdis.BASE, 4):
        w, = struct.unpack_from('<I', img, off)
        if (w >> 25) & 7 == 5 and (w >> 28) != 0xf:
            imm = w & 0xffffff
            if imm & 0x800000:
                imm -= 0x1000000
            a = kdis.BASE + off
            t = a + 8 + imm * 4
            if t in want:
                src = syms.name(a) or hex(a)
                if not src.startswith(syms.name(t, exact=True) + '+'):      # skip branches inside the function
                    want[t].append(src.split('+')[0])
    for off in range(0, len(img) - 3, 4):
        v, = struct.unpack_from('<I', img, off)
        a = kdis.BASE + off
        if v in want and not (KALLSYMS_TAB[0] <= a < KALLSYMS_TAB[1]):
            want[v].append('&' + (syms.name(a) or hex(a)).split('+')[0])
    print('#va\tsize\tname\tobject\tverdict_vs_uu\tobj_size\tcallers')
    for a, n in sorted(funcs):
        size = syms.end(a) - a
        if ASM[0] <= a < ASM[1]:
            nxt = [x for x, m in funcs if x > a and m.endswith('_sARM')] + [ASM[1]]
            size = min(nxt) - a
        o = od.get(a, ('-', 'NEW', ''))
        obj, verdict, osz = o
        if verdict == 'NEW' and n in PUBLIC_C:
            obj, verdict = PUBLIC_C[n], 'PUBLIC-C'
        if verdict == 'NEW' and 0xc06166c0 <= a < SPAN[1]:
            obj, verdict = 'epdpower/tps65185.c', 'PUBLIC-C'
        if a in (0xc0419c3c, 0xc0419c6c):
            obj, verdict = 'epdpower/tps65185.c', 'PUBLIC-C'
        c = sorted(set(want[a]))
        print('%08x\t%d\t%s\t%s\t%s\t%s\t%s' % (a, size, n, obj, verdict, osz, ','.join(c) if c else 'DEAD'))


if __name__ == '__main__':
    main()
