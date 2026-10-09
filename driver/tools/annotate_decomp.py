#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Post-process the Ghidra decompile of the raw stock Image: replace `&UNK_c0xxxxxx` / `0xc0xxxxxx` with the C string at
that VA (as /*"..."*/) or the kallsyms name, so the output reads like the objdump listings.  Read-only on the Image.
usage: python3 -I annotate_decomp.py IMAGE KALLSYMS IN.c OUT.c
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kdis  # noqa: E402

img = open(sys.argv[1], 'rb').read()
syms = kdis.Syms(sys.argv[2])


def sub(m):
    v = int(m.group(2), 16)
    s = kdis.cstr(img, v)
    if s:
        return '%s/*"%s"*/' % (m.group(0), s[:80])
    n = syms.name(v, exact=True)
    if n and not m.group(0).endswith(n):
        return '%s/*<%s>*/' % (m.group(0), n)
    return m.group(0)


src = open(sys.argv[3]).read()
src = re.sub(r'(&?(?:UNK|DAT|PTR_DAT)_|0x)(c0[0-9a-f]{6})\b', sub, src)
open(sys.argv[4], 'w').write(src)
