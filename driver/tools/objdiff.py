#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Function-by-function comparison of the public rychly EBC objects (.uu -> ELF .o, older generation, with symbols and
relocations) against the stock RC2 kernel Image (raw ARM, VA = file offset + 0xc0408000, names from kallsyms).

For every function symbol of every object the matching Image function is looked up by name and compared word by word:
  * identical words                                  -> equal
  * words covered by a relocation in the .o          -> resolved and checked by *name*: branch target name (kallsyms) vs
                                                        reloc symbol; literal word vs reloc symbol (function name, or the
                                                        C string for .rodata.str* section relocs); data symbols are
                                                        accepted as 'data' (the Image has no data symbols)
  * B/BL without a relocation (local static call)    -> target names compared
  * anything else                                    -> a real difference
Verdicts: SAME (all words equal or name-equal relocations), SAME-RELOC-DATA (only data-reloc words unverifiable),
CHANGED (same or different size, with real differences; an instruction-level diff summary is printed with -v),
NOT-IN-IMAGE. Image functions of the span that are absent from every object are listed as NEW.
Nothing is executed: the objects and the Image are only read (readelf/objdump/struct).

usage: python3 -I objdiff.py IMAGE KALLSYMS OBJDIR [-v] [--tsv OUT.tsv] [--only NAME]
       OBJDIR = the uudecoded .uu objects (driver/tools/run.sh writes them to <work-dir>/out/uuobj);
       BINUTILS = directory of GNU readelf/objdump if not the Homebrew binutils one or on PATH.
The SPAN/ASM constants are text addresses, which are the same in the 2017 and 2019 kernels.
"""
import difflib
import os
import re
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kdis  # noqa: E402

BIN = os.path.join(os.environ['BINUTILS'], '') if os.environ.get('BINUTILS') else \
    ('/opt/homebrew/opt/binutils/bin/' if os.path.isdir('/opt/homebrew/opt/binutils/bin') else '')
SPAN = (0xc060b29c, 0xc0617604)
ASM_LO, ASM_HI = 0xc06132a4, 0xc0614ab8
OBJS = ['hardware_ebc.o', 'check_auto_image_sARM.o', 'buf_manage.o', 'buf_list.o', 'bootani.o', 'epd_lut.o',
        'epd_spi_flash.o', 'epd_zip.o']


def run(*a):
    return subprocess.run(a, capture_output=True, text=True, check=True).stdout


class Obj:
    def __init__(self, path):
        self.path = path
        self.data = open(path, 'rb').read()
        self.sec = {}          # idx -> (name, off, size)
        for l in run(BIN + 'readelf', '-SW', path).splitlines():
            m = re.match(r'\s*\[\s*(\d+)\]\s+(\S+)\s+\S+\s+[0-9a-f]+\s+([0-9a-f]+)\s+([0-9a-f]+)', l)
            if m:
                self.sec[int(m.group(1))] = (m.group(2), int(m.group(3), 16), int(m.group(4), 16))
        self.syms = []         # (name, secidx, value, size, type)
        for l in run(BIN + 'readelf', '-sW', path).splitlines():
            p = l.split()
            if len(p) >= 8 and p[0].endswith(':') and p[6].isdigit():
                self.syms.append((p[7], int(p[6]), int(p[1], 16), int(p[2], 0) if not p[2].startswith('0x') else int(p[2], 16), p[3]))
        self.funcs = [s for s in self.syms if s[4] == 'FUNC' or (s[4] == 'NOTYPE' and self.sec[s[1]][0].endswith('text')
                                                                     and not s[0].startswith('$'))]
        # relocations per target section name: {secname: {offset: (type, symname, symsec)}}
        self.rel = {}
        cur = None
        for l in run(BIN + 'readelf', '-rW', path).splitlines():
            m = re.match(r"Relocation section '\.rel(\S+)'", l)
            if m:
                cur = self.rel.setdefault(m.group(1), {})
                continue
            p = l.split()
            if cur is not None and len(p) >= 5 and re.fullmatch(r'[0-9a-f]{8}', p[0]):
                cur[int(p[0], 16)] = (p[2], p[4])
        self.secbyname = {v[0]: k for k, v in self.sec.items()}

    def secdata(self, secname):
        _, off, size = self.sec[self.secbyname[secname]]
        return self.data[off:off + size]

    def cstr(self, secname, addend):
        d = self.secdata(secname)
        e = d.find(b'\0', addend)
        return d[addend:e].decode('latin1')

    def func_at(self, secidx, off):
        best = None
        for n, si, v, sz, t in self.funcs:
            if si == secidx and v <= off < v + max(sz, 4):
                if best is None or v > best[1]:
                    best = (n, v)
        return best


def branch_target(word, addr):
    if (word >> 25) & 7 != 5 or (word >> 28) == 0xf:
        return None
    imm = word & 0xffffff
    if imm & 0x800000:
        imm -= 0x1000000
    return addr + 8 + imm * 4


_DCACHE = {}


def dis1(w):
    """disassemble one ARM word (position-independent part only)"""
    if w not in _DCACHE:
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.bin') as f:
            f.write(struct.pack('<I', w))
            f.flush()
            o = run(BIN + 'objdump', '-D', '-b', 'binary', '-m', 'arm', f.name)
        m = re.search(r'0:\s+[0-9a-f]{8}\s+(.*)', o)
        _DCACHE[w] = re.sub(r'\s+', ' ', m.group(1)).strip() if m else '%08x' % w
    return _DCACHE[w]


def compare(obj, fname, secidx, val, size, img, syms, iva, isize):
    """returns (verdict, ndiff, notes)"""
    sname = obj.sec[secidx][0]
    od = obj.secdata(sname)[val:val + size]
    rel = obj.rel.get(sname, {})
    notes = []
    nreal = nrel = ndata = 0
    n = min(size, isize) // 4
    for i in range(n):
        ow, = struct.unpack_from('<I', od, 4 * i)
        iw, = struct.unpack_from('<I', img, iva - kdis.BASE + 4 * i)
        r = rel.get(val + 4 * i)
        if r:
            typ, sym = r
            nrel += 1
            if typ in ('R_ARM_CALL', 'R_ARM_JUMP24', 'R_ARM_PC24'):
                t = branch_target(iw, iva + 4 * i)
                tn = syms.name(t, exact=True) if t else None
                if (ow >> 24) != (iw >> 24) or tn != sym:
                    # section-relative call: resolve local function
                    if sym.startswith('.'):
                        imm = ow & 0xffffff
                        if imm & 0x800000:
                            imm -= 0x1000000
                        tgt = obj.func_at(obj.secbyname[sym], imm * 4 + 8) if False else None
                    nreal += 1
                    notes.append('+%#x call %s -> image %s' % (4 * i, sym, tn))
            elif typ == 'R_ARM_ABS32':
                sec_sym = sym in obj.secbyname
                if sec_sym and sym.startswith('.rodata.str'):
                    s = obj.cstr(sym, ow)
                    s2 = kdis.cstr(img, iw)
                    if s != (s2 or '').replace('\\n', '\n'):
                        nreal += 1
                        notes.append('+%#x str %r -> image %r' % (4 * i, s[:40], (s2 or '')[:40]))
                elif sec_sym and sym == '.rodata':
                    osym = [x[0] for x in obj.syms if obj.sec.get(x[1], ('',))[0] == '.rodata' and x[2] == ow
                            and x[4] == 'OBJECT']
                    tn = syms.name(iw, exact=True) or ''
                    os_ = obj.cstr('.rodata', ow) if ow < len(obj.secdata('.rodata')) else ''
                    is_ = kdis.cstr(img, iw) or ''
                    base = lambda x: re.sub(r'\.\d+$', '', x)
                    if (osym and base(osym[0]) == base(tn) and (not osym[0].startswith('__func__') or os_ == is_)) \
                            or (os_ and os_ == is_):
                        pass
                    else:
                        nreal += 1
                        notes.append('+%#x rodata %s %r -> image %s %r' % (4 * i, osym[:1], os_[:30], tn, is_[:30]))
                elif sec_sym and sym.endswith('text'):
                    f = obj.func_at(obj.secbyname[sym], ow)
                    tn = syms.name(iw, exact=True)
                    if f and f[1] == ow and tn != f[0]:
                        nreal += 1
                        notes.append('+%#x ptr %s -> image %s' % (4 * i, f[0], tn))
                    elif not f:
                        ndata += 1
                else:
                    tn = syms.name(iw, exact=True)
                    if tn == sym:
                        pass
                    elif tn is None or not (0xc0408000 <= iw < 0xc0a02000):
                        ndata += 1            # data/bss symbol: not checkable by name
                    else:
                        nreal += 1
                        notes.append('+%#x ptr %s -> image %s' % (4 * i, sym, tn))
            else:
                if ow != iw:
                    ndata += 1
            continue
        if ow == iw:
            continue
        # local branch without relocation
        to = branch_target(ow, val + 4 * i)
        ti = branch_target(iw, iva + 4 * i)
        if to is not None and ti is not None and (ow >> 24) == (iw >> 24):
            fo = obj.func_at(secidx, to)
            on = fo[0] if fo and fo[1] == to else ('%s+%#x' % (fname, to - val) if val <= to < val + size else '?')
            inn = syms.name(ti)
            inn_rel = '%s+%#x' % (fname, ti - iva) if iva <= ti < iva + isize else inn
            if on == inn or on == inn_rel:
                continue
        nreal += 1
        if size == isize and len(notes) < 8:
            notes.append('+%#x %s | %s' % (4 * i, dis1(ow), dis1(iw)))
    if size != isize:
        return 'CHANGED', nreal, ['size %d -> %d' % (size, isize)] + notes
    if nreal:
        return 'CHANGED', nreal, notes
    return ('SAME-RELOC-DATA' if ndata else 'SAME'), 0, ['%d relocs, %d data relocs' % (nrel, ndata)]


def norm_obj_listing(obj, fname, val, size, secname):
    out = run(BIN + 'objdump', '-d', '-r', '--section=' + secname, '--start-address=%#x' % val,
              '--stop-address=%#x' % (val + size), obj.path)
    toks = []
    pending = None
    for l in out.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\s+([0-9a-f]{8})\s+(\S+)\s*(.*)', l)
        r = re.match(r'\s*[0-9a-f]+: (R_ARM_\S+)\s+(\S+)', l)
        if r and toks:
            toks[-1] = toks[-1].split(' ')[0] + ' <' + r.group(2) + '>'
            continue
        if m:
            mn, ops = m.group(3), m.group(4)
            ops = re.sub(r'\s*[@;].*', '', ops)
            if mn.startswith('b') and re.match(r'[0-9a-f]+ <', ops):
                ops = re.sub(r'[0-9a-f]+ <(.*)>', r'<\1>', ops)
                ops = re.sub(r'\+0x[0-9a-f]+', '+L', ops)
            if '[pc' in ops:
                ops = re.sub(r'\[pc, #-?\d+\]', '=lit', ops)
            toks.append(mn + ' ' + ops)
    return toks


def norm_img_listing(img_path, img, syms, iva, isize):
    out = run(BIN + 'objdump', '-D', '-b', 'binary', '-m', 'arm', '--adjust-vma=%#x' % kdis.BASE,
              '--start-address=%#x' % iva, '--stop-address=%#x' % (iva + isize), img_path)
    toks = []
    for l in out.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\s+([0-9a-f]{8})\s+(\S+)\s*(.*)', l)
        if not m:
            continue
        a = int(m.group(1), 16)
        mn, ops = m.group(3), m.group(4)
        ops = re.sub(r'\s*[@;].*', '', ops)
        w = int(m.group(2), 16)
        t = branch_target(w, a)
        if t is not None and mn.startswith('b'):
            n = syms.name(t)
            ops = '<%s>' % (re.sub(r'\+0x[0-9a-f]+', '+L', n) if n else hex(t))
        if '[pc' in ops:
            ops = re.sub(r'\[pc, #-?\d+\]', '=lit', ops)
        # literal-pool words: name or string
        if mn in ('.word',) or (0xc0400000 <= w < 0xc2000000 and not t):
            n = syms.name(w, exact=True)
            s = kdis.cstr(img, w)
            if n or s:
                toks.append('.word <%s>' % (n or ('"%s"' % s)))
                continue
        toks.append(mn + ' ' + ops)
    return toks


def main():
    a = [x for x in sys.argv[1:]]
    verbose = '-v' in a
    tsv = None
    only = None
    if '--tsv' in a:
        tsv = a[a.index('--tsv') + 1]
    if '--only' in a:
        only = a[a.index('--only') + 1]
    img_path, ks, objdir = a[0], a[1], a[2]
    img = open(img_path, 'rb').read()
    syms = kdis.Syms(ks)
    seen = set()
    rows = []
    for on in OBJS:
        obj = Obj(os.path.join(objdir, on))
        for n, si, v, sz, t in sorted(obj.funcs, key=lambda s: (s[1], s[2])):
            if only and n != only:
                continue
            if n.startswith('$') or obj.sec[si][0] not in ('.text', '.init.text', '.exit.text', '.devinit.text',
                                                           '.devexit.text'):
                continue
            cands = [va for va, _, sn in syms.s if sn == n]
            inspan = [va for va in cands if SPAN[0] <= va < SPAN[1]]
            iva = (inspan or cands or [None])[0]
            if on == 'check_auto_image_sARM.o' and not n.endswith('_sARM'):
                continue      # internal asm labels: compared as part of the entry functions below
            if on == 'check_auto_image_sARM.o':
                # asm entries: compare up to the next exported entry
                ents = sorted(s[2] for s in obj.funcs if s[4] != 'NOTYPE' or s[0].endswith('_sARM'))
                ents = sorted(s[2] for s in obj.syms if s[0].endswith('_sARM')) + [obj.sec[si][2]]
                sz = min(e for e in ents if e > v) - v
            if iva is None:
                rows.append((on, n, None, sz, None, 'NOT-IN-IMAGE', 0, ''))
                continue
            seen.add(iva)
            isize = syms.end(iva) - iva
            if on == 'check_auto_image_sARM.o':
                isize = sz       # labels split the image symbol; compare the same span
            verdict, nd, notes = compare(obj, n, si, v, sz, img, syms, iva, isize)
            rows.append((on, n, iva, sz, isize, verdict, nd, '; '.join(notes[:6])))
            if verbose and verdict == 'CHANGED':
                to = norm_obj_listing(obj, n, v, sz, obj.sec[si][0])
                ti = norm_img_listing(img_path, img, syms, iva, isize)
                sm = difflib.SequenceMatcher(None, to, ti, autojunk=False)
                print('==== %s (%s) obj %d B -> image %d B, similarity %.2f' % (n, on, sz, isize, sm.ratio()))
                for op, i1, i2, j1, j2 in sm.get_opcodes():
                    if op == 'equal':
                        continue
                    print('  %s obj[%d:%d] image[%#x..%#x]' % (op, i1, i2, iva + 4 * j1, iva + 4 * j2))
                    for x in to[i1:i2][:12]:
                        print('     - ' + x)
                    for x in ti[j1:j2][:12]:
                        print('     + ' + x)
    # NEW functions
    for va, typ, n in syms.s:
        if SPAN[0] <= va < SPAN[1] and typ in 'tT' and va not in seen and not (ASM_LO <= va < ASM_HI):
            rows.append(('-', n, va, None, syms.end(va) - va, 'NEW', 0, ''))
    rows.sort(key=lambda r: (r[2] or 0))
    out = open(tsv, 'w') if tsv else sys.stdout
    print('#obj\tname\timage_va\tobj_size\timage_size\tverdict\treal_diff_words\tnotes', file=out)
    for r in rows:
        print('\t'.join('' if x is None else ('%08x' % x if i == 2 else str(x)) for i, x in enumerate(r)), file=out)


if __name__ == '__main__':
    main()
