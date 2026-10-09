#!/bin/bash
# SPDX-License-Identifier: MIT
# Decompile the whole EBC driver span of the stock RC2 kernel Image (0xc060b29c..0xc0617604 + the EBC initcalls)
# and the public rychly .uu objects with Ghidra (headless), and write objdump listings.
#
# Usage: IMAGE=<Image> KALLSYMS=<kallsyms.txt> RK=<rk_epd dir> run.sh <work-dir>
#   IMAGE     the stock 2017 RC2 kernel Image (raw ARM, sha256 47a13cf3...; checked below)
#   KALLSYMS  its kallsyms, from kernel/extract_kallsyms.py
#   RK        drivers/video/rockchip/rk_epd of the public rychly/rk3026-linux-sources tree (the .uu objects)
#   work-dir  scratch directory for the Ghidra projects and logs; outputs go to $OUT (default <work-dir>/out)
# Needs: Ghidra 12.1.4 + OpenJDK 21 (GHIDRA_HEADLESS, JAVA_HOME), GNU binutils (OBJDUMP), uudecode, python3.
# Nothing is executed: the Image and the objects are only read by Ghidra/objdump.
# The outputs (decompiles, uudecoded objects, listings) contain vendor code: do not publish them.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
IMG="${IMAGE:?usage: IMAGE=<Image> KALLSYMS=<kallsyms.txt> RK=<rk_epd dir> run.sh <work-dir>}"
SYMS="${KALLSYMS:?set KALLSYMS (kernel/extract_kallsyms.py output)}"
RK="${RK:?set RK to drivers/video/rockchip/rk_epd of rychly/rk3026-linux-sources}"
WORK="${1:?work dir}"
OUT="${OUT:-$WORK/out}"
export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home}"
GH="${GHIDRA_HEADLESS:-/opt/homebrew/opt/ghidra/libexec/support/analyzeHeadless}"
OBJDUMP="${OBJDUMP:-/opt/homebrew/opt/binutils/bin/objdump}"
echo "47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af  $IMG" | shasum -a 256 -c -
mkdir -p "$WORK/proj" "$WORK/objproj" "$OUT/uuobj" "$OUT/s"

# 1. uudecode the public objects (never executed; only disassembled/decompiled)
for f in hardware_ebc check_auto_image_sARM bufmanage/buf_list bufmanage/buf_manage bootani/bootani \
         epdlut/epd_lut epdlut/spiflash/epd_spi_flash epdlut/epdzip/epd_zip; do
  uudecode -o "$OUT/uuobj/$(basename $f).o" "$RK/$f.uu"
done

# 2. function list: every kallsyms t/T symbol in the span except the internal asm labels, plus initcalls/devinit parts
EXTRA="0xc0419b1c 0xc0419c30 0xc0419c3c 0xc0419c6c 0xc08b4604 0xc08b65bc"   # rk29_ebc_init spi_flash_init lm_proc_init tps65185_init spi_flash_probe spi_flash_remove
python3 -I - "$SYMS" $EXTRA > "$WORK/ebc.list" <<'PY'
import sys
extra = {int(x, 16) for x in sys.argv[2:]}
for l in open(sys.argv[1]):
    p = l.split()
    if len(p) < 3 or p[1] not in 'tT':
        continue
    a = int(p[0], 16)
    asm = 0xc06132a4 <= a < 0xc0614ab8 and not p[2].endswith('_sARM')
    if (0xc060b29c <= a < 0xc0617604 and not asm) or a in extra:
        print(p[2])
PY
cp "$WORK/ebc.list" "$OUT/ebc.list"

# 3. Ghidra on the raw Image
"$GH" "$WORK/proj" rc2kernel -import "$IMG" -overwrite -noanalysis \
  -loader BinaryLoader -loader-baseAddr 0xc0408000 -processor ARM:LE:32:v7 \
  -scriptPath "$HERE" \
  -postScript ImportKallsymsRaw.java "$SYMS" 0xc060b29c 0xc0617604 $EXTRA \
  -postScript DecompileList.java "$OUT/ebc-image.decomp.c" "$WORK/ebc.list" \
  > "$WORK/ghidra.log" 2>&1
grep -E "ImportKallsymsRaw|DecompileList|ERROR|Exception" "$WORK/ghidra.log" | sed 's/^INFO  //' | head -40 || true

# 4. Ghidra on the public objects (ELF loader applies relocations -> named calls/data)
: > "$OUT/uu-objects.decomp.c"
"$GH" "$WORK/objproj" uuobj -import "$OUT"/uuobj/*.o -overwrite -scriptPath "$HERE" \
  -postScript DecompileAllObj.java "$OUT/uu-objects.decomp.c" > "$WORK/ghidra-obj.log" 2>&1
grep -E "DecompileAllObj|ERROR" "$WORK/ghidra-obj.log" | sed 's/^INFO  //' | head -20 || true

# 5. objdump listings with kallsyms annotations, one per function (the arbiter)
while read -r f; do
  python3 -I "$HERE/kdis.py" "$IMG" "$SYMS" "$f" > "$OUT/s/$f.s"
done < "$WORK/ebc.list"
python3 -I "$HERE/kdis.py" "$IMG" "$SYMS" 0xc06132a4 0xc0614ab8 > "$OUT/s/asm-block.s"
for o in "$OUT"/uuobj/*.o; do
  "$OBJDUMP" -d -r "$o" > "$OUT/uuobj/$(basename "$o" .o).dis"
done
# 6. string-annotated decompile, objdiff vs the .uu objects, inventory with liveness
python3 -I "$HERE/annotate_decomp.py" "$IMG" "$SYMS" "$OUT/ebc-image.decomp.c" "$OUT/ebc-image.annot.c"
python3 -I "$HERE/objdiff.py" "$IMG" "$SYMS" "$OUT/uuobj" --tsv "$OUT/objdiff.tsv"
python3 -I "$HERE/objdiff.py" "$IMG" "$SYMS" "$OUT/uuobj" -v > "$OUT/objdiff-v.txt"
python3 -I "$HERE/inventory.py" "$IMG" "$SYMS" "$OUT/objdiff.tsv" > "$OUT/inventory.tsv"
echo "outputs in $OUT"
