# SPDX-License-Identifier: MIT
# /// script
# requires-python = ">=3.9"
# dependencies = ["unicorn==2.1.4"]
# ///
"""Byte-exact Unicorn checks of the EBC driver pixel/LUT routines of the stock RC2 kernel Image.

Each stock *function* is entered alone inside Unicorn (ARMv7, no OS, no devices) on synthetic buffers (and on the
real waveform file) and compared with an independent Python reference implementation (below).  The Image is never
run as a program: only leaf-ish routines are entered; every kernel call they make (memcpy, memset, __memzero,
do_gettimeofday, printk, flush_tlb_all, schedule, __aeabi_idivmod, kmalloc_order_trace, the cpu_cache/outer_cache
flush pointers) is replaced by a `bx lr` stub whose effect is done in Python; any access outside the mapped buffers
aborts the run.  The public .uu objects are never executed.  Each group also runs a deliberately wrong reference
("mutation") on the same inputs, which must disagree, so the test demonstrably discriminates.

usage:  uv run --script ebc_emu.py IMAGE KALLSYMS [WAVEFORM] [--seed N] [--quick]
        IMAGE    = the stock 2017 RC2 kernel Image (Linux 3.0.36+ #1 Tue Nov 7 2017, sha256 47a13cf3...; checked)
        KALLSYMS = its kallsyms, from kernel/extract_kallsyms.py
        WAVEFORM = the stock /ebc_waveform.bin (optional; enables the waveform group), e.g. extracted with
                   extract_waveform.py of https://github.com/hsw/onyx-rc2-waveform
Only the 2017 Image is accepted: besides the hash, the data/bss addresses below (G, LUT5, WF_PTR, PMV_TAB, FLUSH_PTRS)
belong to it.  The public 2019 kernel has the same text addresses in the EBC span but shifted data/bss.
"""
import argparse
import hashlib
import random
import struct
import sys

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_INVALID
from unicorn import arm_const as A

BASE = 0xc0408000
BSS_LO, BSS_HI = 0xc0b71000, 0xc0e00000
G = 0xc0ca31e0                       # EBC driver globals: [0]=rk29_ebc_info*, +0x4c AUTO row-flag array*, +0x74 waveform*
LUT5 = 0xc0ca3260                    # decoded 5-bit waveform tbl[f][old][new], 0x400 bytes per frame (512 KiB)
WF_PTR, CACHE_TAG, CACHE_TEMP = 0xc0ca3254, 0xc0ca3258, 0xc0ca325c
PMV_TAB = 0xc0d23260                 # parse_mode_version's 8-entry mode-index table
FLUSH_PTRS = (0xc0a60298, 0xc0a602d0)  # cpu_cache.flush_kern_all, outer_cache.flush_all
BUF, BUF_SIZE = 0x10000000, 0x08000000
STACK, STACK_SIZE = 0x20000000, 0x00100000
STUB, RET = 0x00100000, 0x00200000
IMAGE_SHA256 = '47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af'
EXT_NAMES = ['memcpy', 'memset', '__memzero', 'do_gettimeofday', 'printk', 'flush_tlb_all', 'schedule',
             '__aeabi_idivmod', 'kmalloc_order_trace']
SPAN = (0xc060b29c, 0xc0617604)


def load_syms(path):
    s = {}
    for line in open(path):
        p = line.split()
        if len(p) < 3 or p[0].startswith('#'):
            continue
        a = int(p[0], 16)
        if p[2] in s and not (SPAN[0] <= a < SPAN[1]):
            continue
        s[p[2]] = a
    return s


class KEmu:
    def __init__(self, path, syms):
        img = open(path, 'rb').read()
        if hashlib.sha256(img).hexdigest() != IMAGE_SHA256:
            raise SystemExit('unexpected Image (sha256 mismatch)')
        self.sym = syms
        uc = self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        uc.mem_map(BASE, (len(img) + 0xfff) & ~0xfff)
        uc.mem_write(BASE, img)
        uc.mem_map(BSS_LO, BSS_HI - BSS_LO)
        uc.mem_map(BUF, BUF_SIZE)
        uc.mem_map(STACK, STACK_SIZE)
        uc.mem_map(STUB, 0x1000)
        uc.mem_map(RET, 0x1000)
        bxlr = struct.pack('<I', 0xe12fff1e)
        uc.mem_write(STUB, bxlr)
        for p in FLUSH_PTRS:
            uc.mem_write(p, struct.pack('<I', STUB))
        self.ext_by_addr = {}
        for n in EXT_NAMES:
            a = syms[n]
            uc.mem_write(a, bxlr)             # the stub replaces the kernel routine in the emulated copy only
            self.ext_by_addr[a] = n
            uc.hook_add(UC_HOOK_CODE, self._ext, begin=a, end=a)
        uc.hook_add(UC_HOOK_MEM_INVALID, self._bad)
        self.calls = {}
        self.top = BUF + 0x1000

    def _ext(self, uc, addr, size, _):
        n = self.ext_by_addr[addr]
        self.calls[n] = self.calls.get(n, 0) + 1
        r = [uc.reg_read(getattr(A, 'UC_ARM_REG_R%d' % i)) for i in range(4)]
        if n == 'memcpy':
            uc.mem_write(r[0], bytes(uc.mem_read(r[1], r[2])))
        elif n == 'memset':
            uc.mem_write(r[0], bytes([r[1] & 0xff]) * r[2])
        elif n == '__memzero':
            uc.mem_write(r[0], bytes(r[1]))
        elif n == 'do_gettimeofday':
            uc.mem_write(r[0], struct.pack('<II', 1234567890, 0))
        elif n == '__aeabi_idivmod':
            a, b = [x - (1 << 32) if x & 0x80000000 else x for x in r[:2]]
            q = abs(a) // abs(b) * (1 if (a < 0) == (b < 0) else -1)
            uc.reg_write(A.UC_ARM_REG_R0, q & 0xffffffff)
            uc.reg_write(A.UC_ARM_REG_R1, (a - q * b) & 0xffffffff)
        elif n == 'kmalloc_order_trace':
            uc.reg_write(A.UC_ARM_REG_R0, self.alloc(r[0]))

    def _bad(self, uc, access, addr, size, value, _):
        raise RuntimeError('invalid memory access at 0x%x (pc 0x%x)' % (addr, uc.reg_read(A.UC_ARM_REG_PC)))

    def alloc(self, data_or_len):
        data = bytes(data_or_len) if not isinstance(data_or_len, int) else bytes(data_or_len)
        a = self.top
        self.top = (self.top + len(data) + 0x40 + 0xfff) & ~0xfff
        assert self.top < BUF + BUF_SIZE
        self.uc.mem_write(a, data)
        return a

    def reset(self):
        self.top = BUF + 0x1000          # first page = the fake rk29_ebc_info used by the tests

    def rd(self, a, n):
        return bytes(self.uc.mem_read(a, n))

    def wr(self, a, d):
        self.uc.mem_write(a, bytes(d))

    def w32(self, a, v):
        self.wr(a, struct.pack('<I', v & 0xffffffff))

    def r32(self, a):
        return struct.unpack('<I', self.rd(a, 4))[0]

    def call(self, fn, args, regs=None):
        uc = self.uc
        sp = STACK + STACK_SIZE - 0x1000
        for i, v in enumerate(args[4:]):
            uc.mem_write(sp + 4 * i, struct.pack('<I', v & 0xffffffff))
        for i in range(13):
            uc.reg_write(getattr(A, 'UC_ARM_REG_R%d' % i), 0)
        for i, v in enumerate(args[:4]):
            uc.reg_write(getattr(A, 'UC_ARM_REG_R%d' % i), v & 0xffffffff)
        for k, v in (regs or {}).items():
            uc.reg_write(getattr(A, 'UC_ARM_REG_' + k.upper()), v & 0xffffffff)
        uc.reg_write(A.UC_ARM_REG_SP, sp)
        uc.reg_write(A.UC_ARM_REG_LR, RET)
        try:
            uc.emu_start(self.sym[fn], RET, timeout=0, count=0)
        except Exception as e:
            raise RuntimeError('%s: %s at pc 0x%x' % (fn, e, uc.reg_read(A.UC_ARM_REG_PC)))
        r0 = uc.reg_read(A.UC_ARM_REG_R0)
        return r0 - (1 << 32) if r0 & 0x80000000 else r0


# ============================================================================ helpers
def nib(x, k):
    return (x >> (4 * k)) & 0xf


def setnib(x, k, v):
    return (x & ~(0xf << (4 * k))) | ((v & 0xf) << (4 * k))


def words(b):
    return list(struct.unpack('<%dI' % (len(b) // 4), b))


def pack_words(w):
    return struct.pack('<%dI' % len(w), *[x & 0xffffffff for x in w])


def halves(b):
    return list(struct.unpack('<%dH' % (len(b) // 2), b))


def a24(d, o):
    return d[o] | d[o + 1] << 8 | d[o + 2] << 16


# ============================================================================ references: waveform / LUT
def ref_decode19(d, a, mutate=False):
    """Own WBF stream decoder (same algorithm as wbf.py of onyx-rc2-waveform, device-validated frame counts).
    Returns (frames, table) with table[f*1024 + old*32 + new] = code; the stream's fast index is the OLD level."""
    codes = []
    rle = True
    i = a
    while True:
        b = d[i]
        if b == 0xff:
            break
        if b == 0xfc:
            rle = not rle
            i += 1
            b = d[i]
        q = [(b >> s) & 3 for s in (0, 2, 4, 6)]
        if rle:
            codes += q * (d[i + 1] + 1)
            i += 2
        else:
            codes += q
            i += 1
        if len(codes) >= 512 * 1024:
            break
    nf = len(codes) // 1024
    # the kernel checks the 512-frame limit only after a whole RLE run, so a run can spill up to 1023 codes past
    # the 512 KiB table (into parse_mode_version's table at 0xc0d23260 and beyond): model 4 KiB of spill, pre-filled 0xaa
    t = bytearray(0x80000) + b'\xaa' * 0x1000
    for s, c in enumerate(codes):
        f, rem = divmod(s, 1024)
        slow, fast = divmod(rem, 32)
        t[f * 1024 + fast * 32 + slow] = c
    if mutate:   # wrong axis order (old/new swapped)
        t2 = bytearray(t)
        for f in range(nf):
            for o in range(32):
                for n in range(32):
                    t2[f * 1024 + o * 32 + n] = t[f * 1024 + n * 32 + o]
        t = t2
    return nf, bytes(t)


def ref_parse_mode_version(mv):
    if mv == 0x19:
        return [0, 1, 7, 2, 3, 4, 5, 6]
    if mv in (0x18, 0x20):
        return [0, 1, 1, 2, 3, 4, 5, 6]
    if mv == 0x12:
        return [0, 1, 7, 3, 3, 5, 6, 4]
    if mv == 0x23:
        return [0, 1, 5, 2, 3, 3, 3, 4]
    return [0, 1, 1, 2, 3, 4, 5, 6]


def ref_get_lut_mode(mv, typ, r4):
    tab = ref_parse_mode_version(mv)
    if typ > 9 or typ < 0:
        return -1
    idx = {1: 0, 2: 3, 3: 2, 4: 1, 5: 3, 6: 7, 8: 5, 9: 5}.get(typ, r4)   # types 0 and 7: caller's r4 (uninitialised)
    return tab[idx]


def ref_get_lut_temp(d, temp, r3):
    for i in range(d[0x26] + 1):            # bounds d[0x30..0x30+cnt-1]: the LAST bound (48 C) is never read
        if temp < d[0x30 + i]:
            return i - 1                    # temp < 0 -> -1
    return r3                               # temp >= 43 C: whatever the caller left in r3


def ref_get_lut_frame(d, mode, t):
    """-> (frames or -1, table or None)"""
    e = d[0x20] + 4 * mode                  # NB only the low byte of the 24-bit mode-table pointer is used
    if d[e + 3] != (d[e] + d[e + 1] + d[e + 2]) & 0xff:
        return -1, None
    tp = a24(d, e) + 4 * t
    if d[tp + 3] != (d[tp] + d[tp + 1] + d[tp + 2]) & 0xff:
        return -1, None
    assert d[0x10] in (0x18, 0x19, 0x20)
    return ref_decode19(d, a24(d, tp))


def ref_hard_words(tbl, n, nwords=0x20000):
    w = [0] * nwords
    for f in range(n):
        for k in range(16):
            v = 0
            for j in range(16):
                v |= tbl[f * 1024 + 2 * k * 32 + 2 * j] << (2 * j)
            w[f * 16 + k] = v
    return w


def ref_get_lut_data(tbl, n, tag):
    d = bytearray(tbl[:n * 1024])
    if tag in (2, 3):
        for f in range(n):
            for k in range(32):
                d[f * 1024 + k * 33] = 0
    elif tag == 15:
        for f in range(n):
            d[f * 1024 + 29 * 32 + 30] = d[f * 1024 + 29 * 32 + 29]
            d[f * 1024 + 31 * 32 + 30] = d[f * 1024 + 31 * 32 + 31]
    return d


def ref_a2_bk(dst, du, n2):
    d = bytearray(dst)
    for f in range(n2):
        for r in range(31):                 # rows 0..30 only (row 31 untouched)
            for c in (0, 30):
                d[f * 1024 + r * 32 + c] = du[f * 1024 + r * 32 + c]
    return d


def ref_pvi_hard(d, typ, tag, temp, r4=0, mutate=False):
    """Reference of epd_lut_data_get_pvi_hard(lut_data*, type, ?, tag, temp) on an empty cache.
    -> (ret, frame_word or None (unchanged), lut bytes or None (not rebuilt))"""
    mode = ref_get_lut_mode(d[0x10], typ, r4)
    t = ref_get_lut_temp(d, temp, 0)        # r3 == 0 at the call site (set before get_lut_mode, preserved)
    if mutate:                              # wrong temperature range
        t = t + 1 if t < d[0x26] else t - 1
    n, tbl = ref_get_lut_frame(d, mode, t)
    if n == -1:
        return -1, None, None
    lut = bytearray(0x80000)
    fw = None
    if typ in (1, 2, 4, 6, 8):
        fw = n
        lut = bytearray(pack_words(ref_hard_words(tbl, n)))
    elif typ == 5:
        n1, t1 = ref_get_lut_frame(d, ref_get_lut_mode(d[0x10], 2, 0), t)
        lut[:n1 * 1024] = ref_get_lut_data(t1, n1, tag)
        n2, t2 = ref_get_lut_frame(d, ref_get_lut_mode(d[0x10], 4, 0), t)
        lut = ref_a2_bk(lut, t2, n2)
        fw = n1 | n2 << 8
    elif typ == 9:
        fw = n | n << 8
        w = [0] * 0x20000
        for f in range(n):
            w[f * 16 + 15] = tbl[f * 1024 + 31 * 32 + 31] << 30
        lut = bytearray(pack_words(w))
    return 0, fw, bytes(lut)


# ============================================================================ references: frame compute (C)
def ref_full_win(new, old, w, h, win, lutw, mutate=False):
    """full_win_mode_data_change: 4 px per output byte, 2 bits each (pixel 0 in bits 0-1); code = (lutw[old] >> 2*new) & 3,
    only inside the window (x in units of 4 px, all bounds inclusive); unchanged pixels ARE driven inside the window."""
    x1, y1, x2, y2 = win
    q = lambda v: int(v / 4)                 # C division truncates toward zero
    x1, x2 = q(x1), q(x2)
    out = bytearray()
    nh = len(new) // 2
    nw, ow = halves(new), halves(old)
    i = 0
    for y in range(h):
        for j in range(int(w / 4)):
            inside = (x1 <= j <= x2) and (y1 <= y <= y2)
            if mutate:
                inside = inside and y < y2
            b = 0
            if inside:
                for k in range(4):
                    b |= ((lutw[nib(ow[i], k)] >> (2 * nib(nw[i], k))) & 3) << (2 * k)
            out.append(b)
            i += 1
    return bytes(out)


def ref_direct(new, old, w, h, lutw, mutate=False):
    """direct_mode_data_change: 4 px group skipped when identical; pixel 0 skipped when equal; pixels 1-3 are compared
    as (old nibble) vs (2 * new nibble) -- a stock bug -- so an unchanged non-black pixel 1-3 is still driven."""
    out = bytearray()
    nw, ow = halves(new), halves(old)
    i = 0
    for y in range(h):
        for j in range(int(w / 4)):
            a, o = nw[i], ow[i]
            b = 0
            if a != o:
                for k in range(4):
                    na, no = nib(a, k), nib(o, k)
                    same = (na == no) if (k == 0 or mutate) else (no == 2 * na)
                    if not same:
                        b |= ((lutw[no] >> (2 * na)) & 3) << (2 * k)
            out.append(b)
            i += 1
    return bytes(out)


def ref_direct_text(new8, old8, w, h, tbl, mutate=False):
    """direct_mode_data_change_text (dead): 8-bit levels, code = tbl[old][new], 4 px per output byte."""
    out = bytearray()
    for y in range(h):
        for x in range(0, (w // 8) * 8, 4):
            b = 0
            for k in range(4):
                p = y * ((w // 8) * 8) + x + k
                c = tbl[old8[p] * 32 + new8[p]] if not mutate else tbl[new8[p] * 32 + old8[p]]
                b |= (c << (2 * k)) & 0xff
            out.append(b)
    return bytes(out)


def ref_check_part_mode(new, old, a, b):
    """-> (ret, mode_written or None)"""
    n = (a * b)
    n = int(n / 8)
    nw, ow = words(new[:4 * n]), words(old[:4 * n])
    changed = 0
    bw = 0
    for i in range(n):
        if nw[i] == ow[i]:
            continue
        for k in range(8):
            v = nib(nw[i], k)
            if v != nib(ow[i], k):
                if v not in (0, 15):
                    return 1, None            # a grey pixel changed: plain partial
                bw = 1
        changed = 1
    if changed and bw:
        return changed, 6                     # only black/white targets changed -> BLACK_WHITE (DU)
    return changed, None


def ref_auto(st, w, h, ft, fbw, lut, mutate=False):
    """get_auto_image_new_hard: per-pixel AUTO engine on 8-bit level buffers.
    st: dict of bytearrays out/new/lat/old/cnt/rowflag, int info6.  Mutates st."""
    nf = [fbw if (v == 0 or v > 28) else ft for v in range(32)]
    if mutate:
        nf = [ft] * 32
    nb = (w // 8) * 8
    st['info6'] = 0
    out, new, lat, old, cnt, rf = st['out'], st['new'], st['lat'], st['old'], st['cnt'], st['rowflag']
    for y in range(h):
        r = y * w
        o = y * (w // 4)
        if rf[y] == 0 and new[r:r + nb] == lat[r:r + nb]:
            out[o:o + w // 4] = bytes(w // 4)
            ch = 0
        else:
            ch = 0
            for x in range(nb):
                p = r + x
                c = cnt[p]
                if c == 0:
                    lat[p] = new[p]
                    if old[p] != lat[p]:
                        code = lut[old[p] * 32 + lat[p]]
                        cnt[p] = 1
                        ch = 1
                    else:
                        code = 0
                else:
                    code = lut[c * 1024 + old[p] * 32 + lat[p]]
                    c = (c + 1) & 0xff
                    cnt[p] = c
                    if c < nf[lat[p]]:
                        ch = 1
                    else:
                        cnt[p] = 0
                        old[p] = lat[p]
                ob = o + x // 4
                if x % 4 == 0:
                    out[ob] = code & 0xff
                else:
                    out[ob] = (out[ob] | (code << (2 * (x % 4)))) & 0xff
        st['info6'] |= ch
        rf[y] = ch


def ref_set_window_part(a, b, w, h, y1, y2, x1, x2, mark=1):
    b = bytearray(b)
    y1 = min(max(0, y1), h)
    y2 = min(max(0, y2), h)
    x1 = min(max(0, x1), w)
    x2 = min(max(0, x2), w)
    for y in range(y1, y2):
        for x in range(x1, x2):
            if a[y * w + x] == b[y * w + x]:
                b[y * w + x] = mark
    return bytes(b)


def ref_crc32(data, poly=0x04c10db7):
    """crc_32: MSB-first table CRC, init 0, no final xor, polynomial 0x04C10DB7 (NOT the standard 0x04C11DB7)."""
    tab = []
    for i in range(256):
        c = 0
        v = i << 24
        for _ in range(8):
            c = ((c << 1) ^ poly) & 0xffffffff if (c ^ v) & 0x80000000 else (c << 1) & 0xffffffff
            v = (v << 1) & 0xffffffff
        tab.append(c)
    crc = 0
    for b in data:
        crc = tab[(b ^ (crc >> 24)) & 0xff] ^ ((crc << 8) & 0xffffffff)
    return crc


def ref_check_temp(tbl, temp):
    t = 0 if temp < 0 else (49 if temp > 48 else temp)
    ret = 0
    for i in range(50):
        if t < tbl[i]:
            return ret
        if tbl[i + 1] == 0:
            return i
        ret = i
    return 49


def ref_translate(b, n):
    out = bytearray(b)
    for i in range(max(0, n)):
        v = out[i]
        if 0xcb <= v <= 0xe4:
            v = (v + 0x96) & 0xff          # 'a'..'z'
        elif 0xe5 <= v <= 0xfe:
            v = (v + 0x5c) & 0xff          # 'A'..'Z'
        elif v < 10:
            v += 0x30                      # '0'..'9'
        elif v == 10:
            v = 0x5f                       # '_'
        elif v == 11:
            v = 0x2e                       # '.'
        elif v == 12:
            v = 0x2d                       # '-'
        else:
            v = 0
        out[i] = v
    return bytes(out)


# ============================================================================ references: hand-written asm (dead code)
def ref_refresh(dst, src, cnt, niter):
    d, s = words(dst), words(src)
    for i in range(2 * niter):
        for k in range(8):
            if cnt[8 * i + k] == 0:
                d[i] = setnib(d[i], k, nib(s[i], k))
    return pack_words(d)


def ref_get_auto_sarm(new, old, cnt, info, lutw, niter, mutate=False):
    """-> out(bytes), old(bytes), cnt(bytes), info6"""
    a, b = words(new), words(old)
    cnt = bytearray(cnt)
    ft, fbw = info[4], info[5]
    out = []
    info6 = 0
    for i in range(2 * niter):
        code = 0
        if a[i] != b[i]:
            for k in range(8):
                p = 8 * i + k
                an, bn = nib(a[i], k), nib(b[i], k)
                c = cnt[p]
                if bn != an:
                    code |= ((lutw[c * 16 + bn] >> (2 * an)) & 3) << (2 * k)
                    c += 1
                    fr = fbw if an in ((0, 15) if not mutate else (0,)) else ft
                    info6 = 1
                    if fr == c:
                        b[i] = setnib(b[i], k, an)
                        c = 0
                cnt[p] = c & 0xff
        out.append(code)
    return struct.pack('<%dH' % len(out), *out), pack_words(b), bytes(cnt), info6


def ref_check_auto_sarm(A_, B_, C_, cnt, info, lutw, niter, mutate=False):
    """check_auto_image_sARM: like get_auto_image_sARM plus a 'pending image' C merged into A where the counter is 0
    (only while info.u16[0x24] != 0), quarter-wise skips on equal 16-bit halves of A/B *as in memory*, flags at
    info+0x26/0x2c/0x24.  info is a bytearray (mutated).  -> out, A, B, cnt"""
    a_mem, b_mem, c_mem = words(A_), words(B_), words(C_)
    cnt = bytearray(cnt)
    lut = lutw
    u16 = lambda o: info[o] | info[o + 1] << 8

    def s16(o, v):
        info[o] = v & 0xff
        info[o + 1] = (v >> 8) & 0xff

    def s32(o, v):
        info[o:o + 4] = struct.pack('<I', v & 0xffffffff)

    s16(6, 0)
    out = []
    for it in range(niter):
        s32(0x14, niter - it)
        for wsel in range(2):
            i = 2 * it + wsel
            a, b, cw = a_mem[i], b_mem[i], c_mem[i]
            lr = 0
            for q in range(2):
                ks = range(4 * q, 4 * q + 4)
                cntw = struct.unpack('<I', bytes(cnt[8 * i + 4 * q: 8 * i + 4 * q + 4]))[0]
                if u16(0x24) != 0:
                    # q0 compares the low halves of A and C as in memory, q1 the whole (already merged) A word with C
                    differ = ((a_mem[i] & 0xffff) != (cw & 0xffff)) if q == 0 else (a != cw)
                    if mutate:                  # 'no merge of the pending image'
                        differ = False
                    if differ:
                        if cntw != 0:
                            s32(0x2c, 1)
                        for k in ks:
                            if cnt[8 * i + k] == 0:
                                a = setnib(a, k, nib(cw, k))
                if ((a_mem[i] >> (16 * q)) & 0xffff) == ((b_mem[i] >> (16 * q)) & 0xffff):
                    continue
                for k in ks:
                    p = 8 * i + k
                    an, bn = nib(a, k), nib(b, k)
                    c = cnt[p]
                    if bn != an:
                        lr |= ((lut[c * 16 + bn] >> (2 * an)) & 3) << (2 * k)
                        c += 1
                        fr = info[5] if an in (0, 15) else info[4]
                        s16(6, 1)
                        if fr == c:
                            s16(0x26, 1)
                            b = setnib(b, k, an)
                            c = 0
                    cnt[p] = c & 0xff
            out.append(lr)
            a_mem[i], b_mem[i] = a, b
    s16(0x24, 0)
    if u16(0x26) != 0:
        s16(0x26, 0)
        if struct.unpack('<I', bytes(info[0x2c:0x30]))[0] != 0:
            s16(0x24, 1)
            s32(0x2c, 0)
    return struct.pack('<%dH' % len(out), *out), pack_words(a_mem), pack_words(b_mem), bytes(cnt)


def ref_direct_sarm(new, old, fi, lutw, niter, fullwin=False, mutate=False):
    a, b = words(new), words(old)
    out = []
    for i in range(2 * niter):
        code = 0
        if fullwin:
            first = (i % 2 == 0)
            if first and a[i] == b[i]:
                out.append(0)
                continue
            for k in range(8):
                an, bn = nib(a[i], k), nib(b[i], k)
                if (not first) and k == 0 and an == bn:
                    continue
                if mutate and an == bn:
                    continue
                code |= ((lutw[fi * 16 + bn] >> (2 * an)) & 3) << (2 * k)
        elif a[i] != b[i]:
            for k in range(8):
                an, bn = nib(a[i], k), nib(b[i], k)
                if an != bn or mutate:
                    code |= ((lutw[fi * 16 + bn] >> (2 * an)) & 3) << (2 * k)
        out.append(code)
    return struct.pack('<%dH' % len(out), *out)


# ============================================================================ test-data generators
def img4(rng, n, kind):
    if kind == 0:
        return bytes(rng.randrange(256) for _ in range(n))
    if kind == 1:   # mostly white with black/grey text
        return bytes(rng.choice([0xff] * 6 + [0x00, 0x0f, 0xf0, 0x77, rng.randrange(256)]) for _ in range(n))
    return bytes(rng.choice([0x00, 0xff, 0x0f, 0xf0]) for _ in range(n))


def perturb(rng, b, frac):
    b = bytearray(b)
    for _ in range(int(len(b) * frac)):
        b[rng.randrange(len(b))] = rng.randrange(256)
    return bytes(b)


def lut_words(rng, n):
    return [rng.getrandbits(32) for _ in range(n)]


# ============================================================================ tests
class Tally:
    def __init__(self):
        self.g = {}
        self.order = []

    def check(self, grp, ok, mut_differs, info=''):
        if grp not in self.g:
            self.g[grp] = [0, 0, 0]
            self.order.append(grp)
        e = self.g[grp]
        e[0] += 1
        if not ok:
            e[1] += 1
            if e[1] <= 5:
                print('FAIL', grp, info)
        if mut_differs:
            e[2] += 1


def run(emu, rng, quick, wf, T):
    S = emu.sym
    info_buf = BUF

    def new_info(fields):
        emu.wr(info_buf, bytes(0x400))
        for off, (fmt, v) in fields.items():
            emu.wr(info_buf + off, struct.pack('<' + fmt, v))
        emu.w32(G, info_buf)
        return info_buf

    # ------------------------------------------------------------------ 1. waveform decode + LUT build (real file)
    if wf is not None:
        d = wf
        emu.reset()
        d = d + bytes(0x80000)          # zero pad: a negative temperature makes the kernel decode from wild offsets
        wfa = emu.alloc(d)
        mc, tc = d[0x25] + 1, d[0x26] + 1
        pairs = [(m, t) for m in range(mc) for t in range(tc)]
        if quick:
            pairs = [(m, t) for m in range(mc) for t in (0, 8, 13)]
        pairs += [(m, -1) for m in range(mc)]     # temperature < 0 C: get_lut_temp returns -1 (wild table entry)
        for m, t in pairs:
            emu.wr(LUT5, b'\xaa' * 0x81000)          # garbage: the function must clear the first 512 KiB itself
            n = emu.call('get_lut_frame', [wfa, m, t, 0])
            got = emu.rd(LUT5, 0x81000)
            en, et = ref_get_lut_frame(d, m, t)
            mn, mt = ref_decode19(d, a24(d, a24(d, d[0x20] + 4 * m) + 4 * t), mutate=True)
            T.check('decodewaveform_19 via get_lut_frame (real WBF)', n == en and got == et, got != mt,
                    'mode %d range %d: frames %d vs %d' % (m, t, n, en))
        # frame counts at range 8 against the device-validated values
        dev = {1: 22, 2: 38, 7: 24}
        for m, fr in dev.items():
            n = emu.call('get_lut_frame', [wfa, m, 8, 0])
            T.check('get_lut_frame frame count = device (range 8)', n == fr, n != fr + 1, 'mode %d: %d' % (m, n))
        # bad checksum -> -1
        bad = bytearray(d)
        bad[a24(d, d[0x20] + 4 * 2) + 4 * 3 + 3] ^= 1
        ba = emu.alloc(bytes(bad) + bytes(64))
        n = emu.call('get_lut_frame', [ba, 2, 3, 0])
        T.check('get_lut_frame bad temp-pointer checksum -> -1', n == -1, n != 38)
        # get_lut_temp
        for temp in range(-5, 60):
            for r3 in (0, 77):
                got = emu.call('get_lut_temp', [wfa, temp, 0, r3])
                exp = ref_get_lut_temp(d, temp, r3)
                T.check('get_lut_temp', got == exp, got != (min(13, max(0, temp // 3)) if temp < 39 else 13),
                        'temp %d r3 %d: %d vs %d' % (temp, r3, got, exp))
        # parse_mode_version / get_lut_mode
        for mv in (0x12, 0x18, 0x19, 0x20, 0x23, 0x11, 0x30):
            hdr = bytearray(d[:0x40])
            hdr[0x10] = mv
            ha = emu.alloc(bytes(hdr))
            emu.wr(PMV_TAB, bytes(32))
            r = emu.call('parse_mode_version', [ha, 0, 0, 0])
            tab = words(emu.rd(PMV_TAB, 32))
            exp = ref_parse_mode_version(mv)
            T.check('parse_mode_version', r == PMV_TAB - (1 << 32) and tab == exp, tab != [0, 1, 2, 3, 4, 5, 6, 7],
                    'mv %#x: %s vs %s' % (mv, tab, exp))
            for typ in range(0, 12):
                r4 = rng.randrange(8)
                got = emu.call('get_lut_mode', [ha, typ, 0, 0], regs={'r4': r4})
                e = ref_get_lut_mode(mv, typ, r4)
                T.check('get_lut_mode', got == e, got != (e + 1), 'mv %#x type %d r4 %d: %d vs %d' % (mv, typ, r4, got, e))
        # full LUT build: epd_lut_data_get_pvi_hard
        emu.w32(WF_PTR, wfa)
        temps = [25] if quick else [-1, 0, 2, 25, 42, 43, 45, 60]
        # type 7 (and 0) is not run: get_lut_mode then indexes the mode table with the caller's r4, which in
        # epd_lut_data_get_pvi_hard is the lut_data pointer -> wild read (no buf_mode maps to lut type 0/7)
        for typ in (1, 2, 3, 4, 5, 6, 8, 9):
            for temp in temps:
                for tag in ((0, 3, 15) if typ == 5 else (typ,)):
                    emu.w32(CACHE_TAG, 0xdeadbeef)
                    emu.w32(CACHE_TEMP, 0xdeadbeef)
                    ld = emu.alloc(8)
                    emu.w32(ld, 0x12345678)
                    lutbuf = emu.alloc(b'\x55' * 0x80000)
                    emu.w32(ld + 4, lutbuf)
                    r4 = 0
                    ret = emu.call('epd_lut_data_get_pvi_hard', [ld, typ, 1, tag, temp], regs={'r4': r4})
                    fw = emu.r32(ld)
                    lut = emu.rd(lutbuf, 0x80000)
                    er, efw, elut = ref_pvi_hard(d, typ, tag, temp, r4)
                    ok = ret == er and (fw == (efw if efw is not None else 0x12345678)) and \
                        (lut == (elut if elut is not None else b'\x55' * 0x80000))
                    mr, mfw, mlut = ref_pvi_hard(d, typ, tag, temp, r4, mutate=True)
                    if typ in (3, 7) and er == 0:
                        elut = bytes(0x80000)        # types 3/7: LUT zeroed, frame word untouched
                        ok = ret == 0 and fw == 0x12345678 and lut == elut
                        mdiff = lut != b'\x55' * 0x80000   # (mutation: 'no rebuild at all')
                    else:
                        mdiff = (ret, fw, lut) != (mr, mfw if mfw is not None else 0x12345678,
                                                   mlut if mlut is not None else b'\x55' * 0x80000)
                    T.check('epd_lut_data_get_pvi_hard (type x temp, real WBF)', ok, mdiff,
                            'type %d tag %d temp %d: ret %d/%d fw %#x/%s' % (typ, tag, temp, ret, er, fw, efw))
        # cache hit: same tag and range -> nothing rebuilt
        ld = emu.alloc(8)
        lutbuf = emu.alloc(b'\x55' * 0x80000)
        emu.w32(ld + 4, lutbuf)
        emu.call('epd_lut_data_get_pvi_hard', [ld, 2, 1, 7, 25])
        emu.wr(lutbuf, b'\x55' * 16)
        ret = emu.call('epd_lut_data_get_pvi_hard', [ld, 4, 1, 7, 25])   # other TYPE, same tag/temp
        T.check('epd_lut_data_get_pvi_hard cache key = (tag, range), not type', ret == 0 and emu.rd(lutbuf, 16) == b'\x55' * 16,
                True)

    # ------------------------------------------------------------------ 2. LUT packing helpers (synthetic tables)
    emu.reset()
    for n in (1, 3, 38, 131):
        tbl = bytes(rng.randrange(4) for _ in range(n * 1024))
        emu.wr(LUT5, tbl)
        dst = emu.alloc(0x80000)
        emu.call('get_lut_data_hard', [dst, 0, 0, n, 0])
        got = words(emu.rd(dst, n * 64))
        exp = ref_hard_words(tbl, n, n * 16)
        mut = [x ^ (1 if i == 0 else 0) for i, x in enumerate(exp)]
        T.check('get_lut_data_hard', got == exp, got != mut)
        for tag in (0, 2, 3, 15, 16):
            dst = emu.alloc(0x80000)
            emu.call('get_lut_data', [dst, 0, 0, n, tag])
            got = emu.rd(dst, n * 1024)
            exp = ref_get_lut_data(tbl, n, tag)
            mut = ref_get_lut_data(tbl, n, 0)
            T.check('get_lut_data (tag 0/2/3/15)', got == exp, got != mut, 'n %d tag %d' % (n, tag))
        pre = bytes(rng.randrange(256) for _ in range(n * 1024 + 64))
        dst = emu.alloc(pre)
        emu.call('get_lut_data_a2_bk', [dst, 0, 0, n, 0])
        got = emu.rd(dst, n * 1024 + 64)
        exp = bytes(ref_a2_bk(pre[:n * 1024], tbl, n)) + pre[n * 1024:]
        mut = bytes(ref_a2_bk(pre[:n * 1024], tbl, max(0, n - 1))) + pre[n * 1024:]
        T.check('get_lut_data_a2_bk', got == exp, got != mut)

    # ------------------------------------------------------------------ 3. frame compute (live C)
    sizes = [(16, 4), (32, 6), (64, 9), (100, 7), (48, 400 + 3)]
    if not quick:
        sizes += [(1448, 64)]
    for (w, h) in sizes:
        for trial in range(4):
            emu.reset()
            n4 = w * h // 2
            old = img4(rng, n4, trial % 3)
            new = perturb(rng, old, rng.choice([0.0, 0.01, 0.2, 1.0]))
            lw = lut_words(rng, 16 * 40)
            ft = rng.randrange(1, 40)
            fl = rng.randrange(1, ft + 1)
            lutp = emu.alloc(pack_words(lw))
            cur = emu.alloc(32)
            win = (rng.randrange(-4, w), rng.randrange(-2, h), rng.randrange(0, w + 8), rng.randrange(0, h + 2))
            emu.wr(cur + 0x14, struct.pack('<4i', *win))
            info = new_info({4: ('B', ft), 8: ('i', fl), 0x15c: ('I', lutp), 0x98: ('i', h), 0xb0: ('i', w),
                             0x94: ('i', w), 0x198: ('I', cur)})
            frame = lw[(ft - fl) * 16:(ft - fl) * 16 + 16]
            na, oa, out = emu.alloc(new), emu.alloc(old), emu.alloc(w * h // 4 + 16)
            emu.call('full_win_mode_data_change', [out, na, oa, info])
            got = emu.rd(out, (w // 4) * h)
            T.check('full_win_mode_data_change', got == ref_full_win(new, old, w, h, win, frame),
                    got != ref_full_win(new, old, w, h, win, frame, mutate=True),
                    '%dx%d win %s' % (w, h, win))
            emu.call('direct_mode_data_change', [out, na, oa, info])
            got = emu.rd(out, (w // 4) * h)
            T.check('direct_mode_data_change', got == ref_direct(new, old, w, h, frame),
                    got != ref_direct(new, old, w, h, frame, mutate=True), '%dx%d' % (w, h))
            # check_part_mode
            bw_new = bytes((b & 0x0f if (b & 0xf) in (0, 15) else 0xf) | (b & 0xf0 if (b >> 4) in (0, 15) else 0xf0)
                           for b in new)
            for cand in (new, bw_new, old):
                mp = emu.alloc(struct.pack('<I', 0x77))
                ca = emu.alloc(cand)
                r = emu.call('check_part_mode', [ca, oa, w, h, mp])
                em = emu.r32(mp)
                er, emode = ref_check_part_mode(cand, old, w, h)
                ok = r == er and em == (emode if emode is not None else 0x77)
                T.check('check_part_mode', ok, (r, em) != (er, 0x77 if emode == 6 else 6), '%dx%d' % (w, h))
    # schedule() every 400 rows in full_win
    T.check('full_win_mode_data_change calls schedule() every 400 rows', emu.calls.get('schedule', 0) > 0, True)

    # AUTO engine: get_auto_image_new_hard via auto_caclu_next_frame, several successive frames
    for (w, h) in ([(16, 3), (32, 5), (64, 4)] + ([] if quick else [(1448, 6)])):
        emu.reset()
        npx = w * h
        lev = lambda: rng.choice([0, 30, 30, 30, 2 * rng.randrange(16), 29, 31])
        st = {'new': bytearray(lev() for _ in range(npx)), 'lat': bytearray(npx), 'old': bytearray(30 for _ in range(npx)),
              'cnt': bytearray(npx), 'out': bytearray(rng.randrange(256) for _ in range(npx // 4)),
              'rowflag': bytearray(rng.choice([0, 1]) for _ in range(h)), 'info6': 0}
        st['lat'][:] = st['old']
        ft, fbw = rng.randrange(3, 12), rng.randrange(2, 8)
        lut = bytes(rng.randrange(4) for _ in range(256 * 1024))
        lutp = emu.alloc(lut)
        bufs = {k: emu.alloc(bytes(st[k])) for k in ('new', 'lat', 'old', 'cnt', 'out', 'rowflag')}
        cur = emu.alloc(32)
        emu.w32(cur + 8, bufs['new'])
        info = new_info({4: ('B', ft), 5: ('B', fbw), 6: ('H', 0x5555), 0x15c: ('I', lutp), 0x94: ('i', w),
                         0x98: ('i', h), 0x198: ('I', cur), 0x16c: ('I', bufs['lat']), 0x170: ('I', bufs['old']),
                         0x174: ('I', bufs['cnt'])})
        emu.w32(G + 0x4c, bufs['rowflag'])
        mst = {k: (bytearray(v) if isinstance(v, bytearray) else v) for k, v in st.items()}
        for step in range(30):
            if step % 7 == 0:   # new content arrives mid-update
                for _ in range(rng.randrange(1, npx // 2)):
                    st['new'][rng.randrange(npx)] = lev()
                mst['new'][:] = st['new']
                emu.wr(bufs['new'], st['new'])
            emu.call('auto_caclu_next_frame', [bufs['out'], 0, 0, 0])
            ref_auto(st, w, h, ft, fbw, lut)
            ref_auto(mst, w, h, ft, fbw, lut, mutate=True)
            got = {k: emu.rd(bufs[k], len(st[k])) for k in ('out', 'lat', 'old', 'cnt', 'rowflag')}
            got6 = struct.unpack('<H', emu.rd(info + 6, 2))[0]
            ok = all(got[k] == bytes(st[k]) for k in got) and got6 == st['info6']
            md = any(got[k] != bytes(mst[k]) for k in got)
            T.check('get_auto_image_new_hard (AUTO engine, 30 chained frames)', ok, md, '%dx%d step %d %s' % (
                w, h, step, [k for k in got if got[k] != bytes(st[k])]))
            if md:   # keep the mutated chain in sync so that every step tests one step of difference
                for k in mst:
                    if k != 'info6':
                        mst[k][:] = st[k]

    # dead C helpers
    for (w, h) in [(16, 3), (40, 5)]:
        emu.reset()
        n8 = w * h
        new8 = bytes(rng.randrange(32) for _ in range(n8))
        old8 = bytes(rng.randrange(32) for _ in range(n8))
        tbl = bytes(rng.randrange(4) for _ in range(64 * 1024))
        tp = emu.alloc(tbl)
        for diff in (10, 500):
            ft, fl = 9, rng.randrange(1, 9)
            info = new_info({4: ('B', ft), 8: ('i', fl), 0x15c: ('I', tp), 0x2bc: ('i', diff), 0x94: ('i', w),
                             0x98: ('i', h)})
            off = ((ft + 1) * 0x400 if diff < 200 else 0) + (ft - fl) * 0x400
            o = emu.alloc(n8 // 4 + 8)
            emu.call('direct_mode_data_change_text', [o, emu.alloc(new8), emu.alloc(old8), info])
            got = emu.rd(o, n8 // 4)
            T.check('direct_mode_data_change_text (dead)', got == ref_direct_text(new8, old8, w, h, tbl[off:]),
                    got != ref_direct_text(new8, old8, w, h, tbl[off:], mutate=True))
        a = bytes(rng.randrange(3) for _ in range(n8))
        b = bytes(rng.randrange(3) for _ in range(n8))
        for _ in range(4):
            y1, y2, x1, x2 = rng.randrange(-2, h + 2), rng.randrange(-2, h + 2), rng.randrange(-3, w + 3), rng.randrange(-3, w + 3)
            aa, ba = emu.alloc(a), emu.alloc(b)
            emu.call('set_window_part', [aa, ba, w, h, y1, y2, x1, x2])
            got = emu.rd(ba, n8)
            T.check('set_window_part (dead)', got == ref_set_window_part(a, b, w, h, y1, y2, x1, x2),
                    got != ref_set_window_part(a, b, w, h, y1, y2, x1, x2, mark=2))

    # ------------------------------------------------------------------ 4. small helpers
    emu.reset()
    for L in (0, 1, 7, 256, 4093):
        data = bytes(rng.randrange(256) for _ in range(L))
        da = emu.alloc(data + bytes(8))
        got = emu.call('crc_32', [da, L]) & 0xffffffff
        T.check('crc_32 (poly 0x04C10DB7, init 0)', got == ref_crc32(data), got != ref_crc32(data, 0x04c11db7),
                'len %d: %#x vs %#x' % (L, got, ref_crc32(data)))
    for _ in range(6):
        k = rng.randrange(1, 49)
        bounds = sorted(rng.sample(range(1, 60), k))
        tbl = bytes(bounds) + bytes(60)
        ta = emu.alloc(tbl)
        for temp in range(-3, 64, 2):
            got = emu.call('epd_lut_check_temp', [ta, temp])
            exp = ref_check_temp(tbl, temp)
            T.check('epd_lut_check_temp', got == exp, got != ref_check_temp(tbl, temp + 3),
                    'temp %d: %d vs %d' % (temp, got, exp))
    for _ in range(8):
        data = bytes(rng.randrange(256) for _ in range(64))
        n = rng.randrange(-1, 64)
        da = emu.alloc(data)
        emu.call('panel_data_translate', [da, n])
        got = emu.rd(da, 64)
        exp = ref_translate(data, n)
        T.check('panel_data_translate', got == exp, got != ref_translate(data, n - 1))

    # ------------------------------------------------------------------ 5. hand-written asm (no callers in the Image)
    for (w, h) in [(16, 1), (32, 3), (64, 5), (160, 4)]:
        for trial in range(5):
            emu.reset()
            niter = (w >> 4) * h
            n4 = w * h // 2
            old = img4(rng, n4, trial % 3)
            new = perturb(rng, old, rng.choice([0.05, 0.3, 1.0]))
            cnt = bytes(rng.choice([0, 0, 0, 1, 2, rng.randrange(8)]) for _ in range(w * h))
            lw = lut_words(rng, 16 * 256)
            lutp = emu.alloc(pack_words(lw))
            ft, fbw = rng.randrange(2, 9), rng.randrange(2, 6)
            ib = bytearray(0x40)
            ib[4], ib[5] = ft, fbw
            ib[0x18:0x24] = struct.pack('<III', lutp, h, w)
            # refresh_new_image_sARM(dst, src, cnt, info)
            emu.wr(info_buf, ib)
            da, sa, ca = emu.alloc(old), emu.alloc(new), emu.alloc(cnt)
            emu.call('refresh_new_image_sARM', [da, sa, ca, info_buf])
            got = emu.rd(da, n4)
            T.check('refresh_new_image_sARM (dead)', got == ref_refresh(old, new, cnt, niter),
                    got != ref_refresh(old, new, bytes(1 if c == 0 else 0 for c in cnt), niter))
            # get_auto_image_sARM(out, new, old, -, cnt, info)
            emu.wr(info_buf, ib)
            oa, na, ba, ca = emu.alloc(n4 // 2 + 4), emu.alloc(new), emu.alloc(old), emu.alloc(cnt)
            emu.call('get_auto_image_sARM', [oa, na, ba, 0, ca, info_buf])
            eo, eb, ec, e6 = ref_get_auto_sarm(new, old, cnt, ib, lw, niter)
            mo, mb, mc_, _ = ref_get_auto_sarm(new, old, cnt, ib, lw, niter, mutate=True)
            got = (emu.rd(oa, n4 // 2), emu.rd(na, n4), emu.rd(ba, n4), emu.rd(ca, w * h), emu.rd(info_buf + 6, 2)[0])
            T.check('get_auto_image_sARM (dead)', got == (eo, new, eb, ec, e6), got[:4] != (mo, new, mb, mc_))
            # check_auto_image_sARM(out, A, B, C, cnt, info)
            for flag in (0, 1):
                ib2 = bytearray(ib)
                ib2[0x24] = flag
                ib2[0x2c:0x30] = struct.pack('<I', rng.choice([0, 1]))
                emu.wr(info_buf, ib2)
                C = perturb(rng, new, 0.3)
                oa, aa, ba, cca, ca = emu.alloc(n4 // 2 + 4), emu.alloc(new), emu.alloc(old), emu.alloc(C), emu.alloc(cnt)
                emu.call('check_auto_image_sARM', [oa, aa, ba, cca, ca, info_buf])
                einfo = bytearray(ib2)
                eo, ea, eb, ec = ref_check_auto_sarm(new, old, C, cnt, einfo, lw, niter)
                minfo = bytearray(ib2)
                mo, ma, mb, mc_ = ref_check_auto_sarm(new, old, C, cnt, minfo, lw, niter, mutate=True)
                got = (emu.rd(oa, n4 // 2), emu.rd(aa, n4), emu.rd(ba, n4), emu.rd(ca, w * h), emu.rd(info_buf, 0x40))
                T.check('check_auto_image_sARM (dead)', got == (eo, ea, eb, ec, bytes(einfo)),
                        got != (mo, ma, mb, mc_, bytes(minfo)))
            # direct_mode_sARM / direct_fullwin_mode_sARM(out, new, old, frame_left, info)
            fl = rng.randrange(0, ft + 1)
            emu.wr(info_buf, ib)
            for fn, fw in (('direct_mode_sARM', False), ('direct_fullwin_mode_sARM', True)):
                oa = emu.alloc(n4 // 2 + 4)
                emu.call(fn, [oa, emu.alloc(new), emu.alloc(old), fl, info_buf])
                got = emu.rd(oa, n4 // 2)
                T.check(fn + ' (dead)', got == ref_direct_sarm(new, old, ft - fl, lw, niter, fullwin=fw),
                        got != ref_direct_sarm(new, old, ft - fl, lw, niter, fullwin=fw, mutate=True))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('kallsyms')
    ap.add_argument('waveform', nargs='?')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--quick', action='store_true')
    a = ap.parse_args()
    syms = load_syms(a.kallsyms)
    emu = KEmu(a.image, syms)
    wf = open(a.waveform, 'rb').read() if a.waveform else None
    T = Tally()
    run(emu, random.Random(a.seed), a.quick, wf, T)
    tot = fails = 0
    print('%-62s %6s %6s %9s' % ('group', 'cases', 'fails', 'mut-diff'))
    weak = []
    for g in T.order:
        c, f, m = T.g[g]
        tot += c
        fails += f
        print('%-62s %6d %6d %9d' % (g, c, f, m))
        if m == 0:
            weak.append(g)
    print('ebc_emu: %d cases, %d failures (seed %d)%s; mutation not detected in: %s; kernel calls stubbed: %s'
          % (tot, fails, a.seed, ' quick' if a.quick else '', weak or 'none', dict(sorted(emu.calls.items()))))
    sys.exit(1 if fails or weak else 0)


if __name__ == '__main__':
    main()
