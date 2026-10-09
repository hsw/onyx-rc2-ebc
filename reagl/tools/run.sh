#!/bin/bash
# SPDX-License-Identifier: MIT
# Decompile the REAGL-related EBC functions of the stock RC2 kernel Image with Ghidra (headless, raw binary import).
#
# Usage: IMAGE=<Image> KALLSYMS=<kallsyms.txt> run.sh <work-dir>
#   IMAGE     the stock 2017 RC2 kernel Image (raw ARM, sha256 47a13cf3...; checked below)
#   KALLSYMS  its kallsyms, from kernel/extract_kallsyms.py
#   work-dir  scratch directory for the Ghidra project and logs; outputs go to $OUT (default <work-dir>/out)
# Needs: Ghidra 12.1.4 + OpenJDK 21 (GHIDRA_HEADLESS, JAVA_HOME), GNU objdump (OBJDUMP), python3.
# The Image is only read (Ghidra/objdump), never executed. The outputs contain vendor code: do not publish them.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
IMG="${IMAGE:?usage: IMAGE=<Image> KALLSYMS=<kallsyms.txt> run.sh <work-dir>}"
SYMS="${KALLSYMS:?set KALLSYMS (kernel/extract_kallsyms.py output)}"
WORK="${1:?work dir}"
OUT="${OUT:-$WORK/out}"
export JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@21/libexec/openjdk.jdk/Contents/Home}"
GH="${GHIDRA_HEADLESS:-/opt/homebrew/opt/ghidra/libexec/support/analyzeHeadless}"
echo "47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af  $IMG" | shasum -a 256 -c -
mkdir -p "$WORK/proj" "$OUT"
# functions are created for every kallsyms text symbol of the EBC driver + epd_lut (0xc060b29c..0xc06132a4)
# and their direct callees; no auto-analysis of the 7.7 MB Image.
"$GH" "$WORK/proj" rc2kernel -import "$IMG" -overwrite -noanalysis \
  -loader BinaryLoader -loader-baseAddr 0xc0408000 -processor ARM:LE:32:v7 \
  -scriptPath "$HERE" \
  -postScript ImportKallsymsRaw.java "$SYMS" 0xc060b29c 0xc0616700 \
  -postScript DecompileList.java "$OUT/reagl.decomp.c" "$HERE/reagl.list" \
  > "$WORK/ghidra.log" 2>&1
grep -E "ImportKallsymsRaw|DecompileList|ERROR|Exception" "$WORK/ghidra.log" | sed 's/^INFO  //' | head -40 || true
# objdump listings with kallsyms annotations (the arbiter for loops/constants)
grep -v '^#' "$HERE/reagl.list" | while read -r f; do
  [ -n "$f" ] && python3 -I "$HERE/kdis.py" "$IMG" "$SYMS" "$f" > "$OUT/$f.s"
done
python3 -I "$HERE/kdis.py" "$IMG" "$SYMS" --callers reagl_1 reagl_2 enable_reagl reagltopart get_reagl_diffnum \
  get_reagllut_data_hard epd_lut_reagle > "$OUT/callers.txt"
echo "outputs in $OUT"
