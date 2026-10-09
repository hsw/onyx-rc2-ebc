#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# /// script
# requires-python = ">=3.9"
# dependencies = ["unicorn==2.1.4"]
# ///
"""Check the reverse-engineered REAGL helpers of the stock RC2 kernel byte for byte.

Each stock *function* is run in isolation inside Unicorn (ARMv7, no OS, no devices) on synthetic buffers and compared
with the Python reimplementation below (the algorithm described in reagl/README.md).  The kernel Image is never run as a
program: only leaf helpers are entered, every kernel call they make (memcpy, memset, __memzero, do_gettimeofday,
printk, flush_tlb_all, the cpu_cache/outer_cache flush pointers) is replaced by a `bx lr` stub whose effect is
done in Python, and any access outside the mapped buffers aborts the run.

usage:  uv run --script reagl_emu.py IMAGE [--seed N] [--quick]     (or any python3 with unicorn 2.1.4)
        IMAGE = the stock 2017 RC2 kernel Image (Linux 3.0.36+ #1 Tue Nov 7 2017, sha256 47a13cf3...; checked)
Only the 2017 Image is accepted: besides the hash, the addresses below (G, LUT5, FLUSH_PTRS and the EXT kernel routines)
belong to it.  The public 2019 kernel has the same text addresses in the EBC span but shifted data/bss.
"""
import argparse
import random
import struct
import sys

from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_INVALID
from unicorn import arm_const as A

BASE = 0xc0408000
BSS_LO, BSS_HI = 0xc0b71000, 0xc0e00000
G = 0xc0ca31e0                       # ONYX/Rockchip EBC globals block: [0]=ebc_info*, +0x54 scratch 8-bit buffer, ...
LUT5 = 0xc0ca3260                    # decoded 5-bit waveform tbl[f][old][new], 0x400 bytes per frame
BUF = 0x10000000
BUF_SIZE = 0x04000000
STACK = 0x20000000
STACK_SIZE = 0x00100000
STUB = 0x00100000                    # target of the cache-flush function pointers
RET = 0x00200000

SYM = dict(reagl_1=0xc060edc8, reagl_2=0xc060f234, check_part_mode_text=0xc060e380, check_rotate=0xc060e410,
           check_part_mode_text_rect=0xc060e508, backupstatarbar=0xc060e66c, revertstatarbar=0xc060e9a0,
           y8bitto4bit=0xc060ec4c, y4bitto8bit=0xc060ed00, reagltopart=0xc06119b4,
           get_reagllut_data_hard=0xc0611a24, get_reagl_diffnum=0xc061083c, enable_reagl=0xc060c038)
EXT = dict(memcpy=0xc05e0ba0, memset=0xc05e1240, __memzero=0xc05e1300, do_gettimeofday=0xc049dff0,
           printk=0xc08b9e20, flush_tlb_all=0xc044f1c4)
FLUSH_PTRS = (0xc0a60298, 0xc0a602d0)  # cpu_cache.flush_kern_all, outer_cache.flush_all
IMAGE_SHA256 = '47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af'


class KEmu:
    def __init__(self, path):
        import hashlib
        img = open(path, 'rb').read()
        if hashlib.sha256(img).hexdigest() != IMAGE_SHA256:
            raise SystemExit('unexpected Image (sha256 mismatch)')
        uc = self.uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        size = (len(img) + 0xfff) & ~0xfff
        uc.mem_map(BASE, size)
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
        for n, a in EXT.items():
            uc.mem_write(a, bxlr)                       # the stub replaces the kernel routine in the emulated copy
            self.ext_by_addr[a] = n
            uc.hook_add(UC_HOOK_CODE, self._ext, begin=a, end=a)
        uc.hook_add(UC_HOOK_MEM_INVALID, self._bad)
        self.calls = {}
        self.top = BUF

    # ---------------------------------------------------------------- kernel call stubs
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

    def _bad(self, uc, access, addr, size, value, _):
        raise RuntimeError('invalid memory access at 0x%x (pc 0x%x)' % (addr, uc.reg_read(A.UC_ARM_REG_PC)))

    # ---------------------------------------------------------------- helpers
    def alloc(self, data_or_len):
        data = bytes(data_or_len) if not isinstance(data_or_len, int) else bytes(data_or_len)
        a = self.top
        self.top = (self.top + len(data) + 0x40 + 0xfff) & ~0xfff
        assert self.top < BUF + BUF_SIZE
        self.uc.mem_write(a, data)
        return a

    def reset(self):
        self.top = BUF

    def rd(self, a, n):
        return bytes(self.uc.mem_read(a, n))

    def wr(self, a, d):
        self.uc.mem_write(a, bytes(d))

    def call(self, fn, args):
        uc = self.uc
        regs, stack = args[:4], args[4:]
        sp = STACK + STACK_SIZE - 0x1000
        for i, v in enumerate(stack):
            uc.mem_write(sp + 4 * i, struct.pack('<I', v & 0xffffffff))
        for i, v in enumerate(regs):
            uc.reg_write(getattr(A, 'UC_ARM_REG_R%d' % i), v & 0xffffffff)
        uc.reg_write(A.UC_ARM_REG_SP, sp)
        uc.reg_write(A.UC_ARM_REG_LR, RET)
        uc.emu_start(SYM[fn], RET, timeout=0, count=0)
        r0 = uc.reg_read(A.UC_ARM_REG_R0)
        return r0 - (1 << 32) if r0 & 0x80000000 else r0


# ==================================================================== reference implementations (README algorithm)
def expand(packed):
    """4-bpp packed (low nibble = left pixel) -> one byte per pixel, 5-bit level 2*g (0..30)."""
    out = bytearray(2 * len(packed))
    out[0::2] = bytes((b & 0xf) << 1 for b in packed)
    out[1::2] = bytes((b >> 4) << 1 for b in packed)
    return out


def halo_mark(p, h, w):
    """In place: every white (level 30) pixel that has a non-white (level < 29) 8-neighbour becomes 31."""
    src = bytes(p)
    for y in range(h):
        for x in range(w):
            if src[y * w + x] < 29:
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if (dy or dx) and 0 <= y + dy < h and 0 <= x + dx < w:
                            i = (y + dy) * w + x + dx
                            if p[i] == 30:
                                p[i] = 31
    return p


def ref_reagl_2(packed, h, w, sb, bottom, rot):
    """Returns the new content of the packed buffer: a 4-bpp mask, nibble 0xF = 'halo' pixel, else 0."""
    e = halo_mark(expand(packed), h, w)
    out = bytearray(len(packed))
    bpr = w // 2

    def put(byte_idx, pix_idx):
        # with an odd sb in rotation 0 the last read is 1 byte past the w*h scratch buffer (stock bug, harmless);
        # the harness pads the scratch buffer with zeros, so treat it as 'not marked'
        if pix_idx < len(e) and e[pix_idx] == 31:
            out[byte_idx] |= 0x0f
        if pix_idx + 1 < len(e) and e[pix_idx + 1] == 31:
            out[byte_idx] |= 0xf0

    if rot == 0:      # skip sb columns on the left, bottom columns on the right; NB pixel index starts at sb, byte at sb//2
        for y in range(h):
            for j in range(sb // 2, (w - bottom) // 2):
                put(y * bpr + j, y * w + sb + 2 * (j - sb // 2))
    elif rot == 1:    # skip sb rows on top, bottom rows at the end
        for y in range(sb, h - bottom):
            for j in range(bpr):
                put(y * bpr + j, y * w + 2 * j)
    elif rot == 2:    # skip sb columns on the right; 'bottom' (in BYTES here) only shortens the row further (stock quirk)
        for y in range(h):
            for k in range((w - sb) // 2 - bottom):
                put(y * bpr + k, y * w + 2 * k)
    elif rot == 3:    # skip bottom rows on top, sb rows at the end
        for y in range(bottom, h - sb):
            for j in range(bpr):
                put(y * bpr + j, y * w + 2 * j)
    return bytes(out)


def ref_check_part_mode_text(new, old, bpr, h):
    n = (bpr * h) // 4 if bpr * h >= 0 else -((-bpr * h) // 4)
    return sum(1 for i in range(n) if new[4 * i:4 * i + 4] != old[4 * i:4 * i + 4])


def ref_check_rotate(img, bpr, h):
    if h > 0 and all(img[y * bpr] == 0 for y in range(h)):
        return 0                                          # black left column (pixels 0-1)
    if bpr > 0 and all(img[x] == 0 for x in range(bpr)):
        return 1                                          # black top row
    if h > 0 and all(img[y * bpr + bpr - 1] == 0 for y in range(h)):
        return 2                                          # black right column
    if bpr > 0 and all(img[(h - 1) * bpr + x] == 0 for x in range(bpr)):
        return 3                                          # black bottom row
    return 0


def bar_bytes(sb, bottom, bpr, h, rot):
    """Byte indices of the status-bar stripe (sb) and the opposite bottom stripe, as used by backup/revert."""
    s, b = [], []
    if rot == 0:
        s = [y * bpr + j for y in range(h) for j in range(sb // 2)]
        b = [y * bpr + j for y in range(h) for j in range(bpr - bottom // 2, bpr)]
    elif rot == 1:
        s = [y * bpr + j for y in range(sb) for j in range(bpr)]
        b = [y * bpr + j for y in range(h - bottom, h) for j in range(bpr)]
    elif rot == 2:
        s = [y * bpr + j for y in range(h) for j in range(bpr - sb // 2, bpr)]
        b = [y * bpr + j for y in range(h) for j in range(bottom // 2)]
    elif rot == 3:
        s = [y * bpr + j for y in range(h - sb, h) for j in range(bpr)]
        b = [y * bpr + j for y in range(bottom) for j in range(bpr)]
    return s, b


def ref_check_part_mode_text_rect(new, old, sb, bpr, h, rot):
    s, _ = bar_bytes(sb, 0, bpr, h, rot)
    return 0 if any(new[i] != old[i] for i in s) else 1


def ref_backupstatarbar(new, old, bak, sb, bottom, bpr, h, rot):
    new, old, bak = bytearray(new), bytearray(old), bytearray(bak)
    s, b = bar_bytes(sb, bottom, bpr, h, rot)
    for i in s + b:
        bak[i] = new[i]
        new[i] = 0xff
        old[i] = 0xff
    return bytes(new), bytes(old), bytes(bak)


def ref_revertstatarbar(new, bak, sb, bottom, bpr, h, rot):
    new = bytearray(new)
    s, b = bar_bytes(sb, bottom, bpr, h, rot)
    for i in s + b:
        new[i] = bak[i]
    return bytes(new)


def ref_reagltopart(src, nframes):
    d = bytearray(src[:nframes * 1024])
    for f in range(nframes):
        for k in range(32):
            d[f * 1024 + k * 33] = 0                    # tbl[f][k][k] = 0: unchanged pixels are not driven
    return bytes(d)


def ref_get_reagllut_data_hard(lut_words, tbl, nframes):
    w = list(lut_words)
    for f in range(nframes):
        w[f * 16 + 15] |= (tbl[f * 1024 + 31 * 32 + 31] << 30) & 0xffffffff   # only old=15 -> new=15, from tbl[f][31][31]
    return w


# ==================================================================== test images
def text_like(rng, w, h, density=0.08, gray=True):
    """White page with random dark 'glyph' blobs (and some grey anti-aliasing), 4-bpp packed."""
    px = [15] * (w * h)
    for _ in range(max(1, int(w * h * density / 12))):
        x0, y0 = rng.randrange(w), rng.randrange(h)
        bw, bh = rng.randint(1, 4), rng.randint(1, 6)
        v = rng.choice([0, 0, 0, 2, 5, 9, 13, 14]) if gray else 0
        for y in range(y0, min(h, y0 + bh)):
            for x in range(x0, min(w, x0 + bw)):
                px[y * w + x] = v
    return pack(px)


def random_px(rng, w, h):
    return pack([rng.choice([0, 15, 15, 15, 14, 1, rng.randrange(16)]) for _ in range(w * h)])


def pack(px):
    return bytes(px[i] | (px[i + 1] << 4) for i in range(0, len(px), 2))


# ==================================================================== tests
def run(emu, rng, quick):
    fails = 0
    cases = 0

    def check(name, ok, info=''):
        nonlocal fails, cases
        cases += 1
        if not ok:
            fails += 1
            if fails < 20:
                print('FAIL', name, info)

    scratch = emu  # noqa
    sizes = [(4, 3), (6, 4), (8, 8), (16, 5), (34, 9), (64, 40), (100, 60)]
    if not quick:
        sizes += [(1448, 1072)]
    for (w, h) in sizes:
        for trial in range(1 if (w, h) == (1448, 1072) else 6):
            emu.reset()
            img = text_like(rng, w, h) if trial % 2 == 0 else random_px(rng, w, h)
            n = w * h // 2
            scratch8 = emu.alloc(w * h + 64)
            emu.wr(G + 0x54, struct.pack('<I', scratch8))
            for rot in range(5):
                sb = min(83, w - 2, h - 2) if (w, h) == (1448, 1072) else rng.choice([0, 1, 2, 3, 5, min(w, h) // 2])
                bottom = 0 if trial < 3 else rng.choice([0, 2, 4])
                if rot in (0, 2):
                    sb = min(sb, w - 2)
                buf = emu.alloc(img)
                emu.call('reagl_2', [buf, h, w, sb, bottom, rot])
                got = emu.rd(buf, n)
                exp = ref_reagl_2(img, h, w, sb, bottom, rot)
                check('reagl_2 %dx%d sb=%d bot=%d rot=%d' % (w, h, sb, bottom, rot), got == exp,
                      'diff bytes %d' % sum(1 for a, b in zip(got, exp) if a != b))
            # reagl_1: same marking, in place on an 8-bit 5-bit-level buffer
            e8 = bytes(expand(img))
            b8 = emu.alloc(e8)
            emu.call('reagl_1', [b8, h, w])
            check('reagl_1 %dx%d' % (w, h), emu.rd(b8, w * h) == bytes(halo_mark(bytearray(e8), h, w)))
            # y4bitto8bit / y8bitto4bit
            src = emu.alloc(img)
            dst = emu.alloc(w * h)
            emu.call('y4bitto8bit', [src, dst, w, h])
            check('y4bitto8bit %dx%d' % (w, h), emu.rd(dst, w * h) == bytes(expand(img)))
            emu.call('y8bitto4bit', [dst, dst, w, h])
            check('y8bitto4bit %dx%d' % (w, h), emu.rd(dst, n) == img)
            # frame diff counter
            img2 = bytearray(img)
            for _ in range(rng.randrange(0, 40)):
                img2[rng.randrange(n)] ^= rng.randrange(1, 256)
            a, b = emu.alloc(img2), emu.alloc(img)
            got = emu.call('check_part_mode_text', [a, b, w // 2, h])
            check('check_part_mode_text %dx%d' % (w, h), got == ref_check_part_mode_text(img2, img, w // 2, h),
                  '%d vs %d' % (got, ref_check_part_mode_text(img2, img, w // 2, h)))
            # rotation probe: paint a black edge
            for rot in range(4):
                px = list(img)
                bpr = w // 2
                im = bytearray(img)
                if rot == 0:
                    for y in range(h):
                        im[y * bpr] = 0
                elif rot == 1:
                    im[0:bpr] = bytes(bpr)
                elif rot == 2:
                    for y in range(h):
                        im[y * bpr + bpr - 1] = 0
                else:
                    im[(h - 1) * bpr:h * bpr] = bytes(bpr)
                for variant in (im, img):
                    a = emu.alloc(variant)
                    got = emu.call('check_rotate', [a, bpr, h])
                    check('check_rotate %dx%d rot=%d' % (w, h, rot), got == ref_check_rotate(variant, bpr, h),
                          '%d vs %d' % (got, ref_check_rotate(variant, bpr, h)))
            # status-bar compare / backup / revert
            bpr = w // 2
            for rot in range(4):
                sb = rng.choice([0, 1, 2, 3, min(w, h) // 3])
                bottom = rng.choice([0, 0, 2])
                new = bytearray(img)
                old = bytearray(img)
                if rng.random() < 0.5:
                    s, _ = bar_bytes(sb, 0, bpr, h, rot)
                    if s:
                        new[rng.choice(s)] ^= 0x11
                a, b = emu.alloc(new), emu.alloc(old)
                got = emu.call('check_part_mode_text_rect', [a, b, sb, bpr, h, rot])
                check('check_part_mode_text_rect rot=%d' % rot, got == ref_check_part_mode_text_rect(new, old, sb, bpr, h, rot))
                old2 = bytes(random_px(rng, w, h))
                bk0 = bytes(rng.randrange(256) for _ in range(n))
                a, b, c = emu.alloc(new), emu.alloc(old2), emu.alloc(bk0)
                emu.call('backupstatarbar', [a, b, c, sb, bottom, bpr, h, rot])
                en, eo, eb = ref_backupstatarbar(new, old2, bk0, sb, bottom, bpr, h, rot)
                check('backupstatarbar rot=%d sb=%d bot=%d' % (rot, sb, bottom),
                      (emu.rd(a, n), emu.rd(b, n), emu.rd(c, n)) == (en, eo, eb))
                emu.call('revertstatarbar', [a, c, sb, bottom, bpr, h, rot])
                check('revertstatarbar rot=%d' % rot, emu.rd(a, n) == ref_revertstatarbar(en, eb, sb, bottom, bpr, h, rot))
    # LUT helpers
    for nf in (1, 5, 38):
        emu.reset()
        src = bytes(rng.randrange(3) for _ in range(nf * 1024))
        a, b = emu.alloc(src), emu.alloc(nf * 1024)
        emu.call('reagltopart', [b, a, nf, 0])
        check('reagltopart nf=%d' % nf, emu.rd(b, nf * 1024) == ref_reagltopart(src, nf))
        tbl = bytes(rng.randrange(3) for _ in range(nf * 1024))
        emu.wr(LUT5, tbl)
        words = [rng.randrange(1 << 30) for _ in range(nf * 16)]
        lw = emu.alloc(struct.pack('<%dI' % len(words), *words))
        emu.call('get_reagllut_data_hard', [lw, 0, 0, nf])
        got = list(struct.unpack('<%dI' % len(words), emu.rd(lw, 4 * len(words))))
        check('get_reagllut_data_hard nf=%d' % nf, got == ref_get_reagllut_data_hard(words, tbl, nf))
    check('get_reagl_diffnum', emu.call('get_reagl_diffnum', []) == 200)
    return cases, fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('image')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--quick', action='store_true')
    a = ap.parse_args()
    emu = KEmu(a.image)
    cases, fails = run(emu, random.Random(a.seed), a.quick)
    print('reagl_emu: %d cases, %d failures (seed %d)%s; kernel calls stubbed: %s'
          % (cases, fails, a.seed, ' quick' if a.quick else '', dict(sorted(emu.calls.items()))))
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
