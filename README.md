# onyx-rc2-ebc

A description of the stock **RK3026 EBC (E-Ink) driver** of the **ONYX BOOX Robinson Crusoe 2** (internal name `MC_Kepler_R2`,
Rockchip RK3026, panel ED060KD1C2 1448×1072, PMIC TPS65185), as found in the vendor kernel binary. The vendor ships this driver only
as prebuilt code: the public Rockchip RK3026 E-Ink tree has an older generation of it as precompiled `.uu` objects, and the RC2 kernel
has a newer one with no source at all. Everything here was worked out by static analysis of the kernel Image (disassembly, decompilation
for reading, emulation of single functions in Unicorn) and, where marked, checked against device logs.

The audience is anyone writing an EPD/EBC driver for RK3026 boards (mainline or otherwise) who wants to know what the vendor driver
actually does: buffer model, modes, LUT pipeline, timing, power sequencing and its bugs.

Related:
- [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform): the waveform file (`/ebc_waveform.bin`, E Ink WBF), its format and a
  decoder. Waveform-format details live there and are not repeated here.
- [onyx-rc2-hardware](https://github.com/hsw/onyx-rc2-hardware): the board (pins, PMIC, VCOM, power rails, the ONYX board file).

## The analysed kernel

The analysed Image is the **stock RC2 kernel built 2017-11-07**:
`Linux version 3.0.36+ ... #1 SMP PREEMPT Tue Nov 7 21:44:55 CST 2017`, 7 766 052 bytes, sha256
`47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af`. It was read from a device running firmware 1.8.2; that firmware
is not publicly downloadable. The Image is uncompressed ARM (no zImage header), loaded at PA 0x60408000, so
**VA = file offset + 0xc0408000**. It has no embedded config and no System.map; symbol names come from its kallsyms table.

ONYX publishes a later firmware update on its support page <https://onyx-boox.ru/support/boox_robinson-crusoe2> (the firmware update
download: 1.9.1-simple 2019-11-05_18-20 db0cce3, MD5 `bce0d3914e8acabb494685159fc9a141` as listed on that page). Its `boot.img`
carries a kernel built 2019-11-05 (raw Image, 7 774 244 bytes, sha256 starting `56bb7228a064f6a1`) with the same EBC banner
`V1.0.20 VERSION 20171023-23`.

Comparison of the two kernels:
- All **356 text symbols of the EBC span 0xc060b29c–0xc0617604 sit at the same addresses with the same sizes** in both kernels. The only
  differing words in the span are BL/B branch targets outside the span (226 words) and literal pointers into data/bss, shifted by
  0x2000–0x2bcf (about 460 words).
- So **function addresses in these documents apply to the public 2019 kernel as-is.**
- **Everything outside the span differs**: .data/.bss addresses, strings, and the few out-of-span functions (the initcalls at 0xc0419…,
  `spi_flash_probe` 0xc08b4604). A spot check of literal pools: the globals block G 0xc0ca31e0 → 0xc0ca51e0 (bss +0x2000), `lut_info`
  0xc0ca3250 → 0xc0ca5250, `spi_id_buffer` 0xc0d28b90 → 0xc0d2ab90, the panel timing 0xc0a8faa8 → 0xc0a91ae8 (.data +0x2040), `/dev/ebc`
  fops 0xc08e50d0 → 0xc08e74d0 (+0x2400), strings about +0x29d0. Other data/bss addresses (LUT5, PMV_TAB, …) were not checked one by one
  [VERIFY exact shift].
- The emulation harnesses (`driver/tools/ebc_emu.py`, `reagl/tools/reagl_emu.py`) and the Ghidra drivers (`*/tools/run.sh`) pin the
  2017 Image hash, and the harnesses also pin its data/bss addresses (and, in `reagl_emu.py`, the addresses of the stubbed kernel routines). `kernel/extract_kallsyms.py`, `kdis.py`, `objdiff.py` and
  `inventory.py` work on either kernel (`inventory.py` has one 2017-specific constant, see its usage).

## Repository map

| Path | What |
|---|---|
| [`driver/README.md`](driver/README.md) | **Main document.** The whole EBC span 0xc060b29c–0xc0617604: architecture, buffers and the userspace contract, `ebc_thread` state machine and mode table, LUT pipeline and temperature, the three engines, power, waveform source and boot, SPI flash, boot animation, PMIC, a 203-function inventory versus the public `.uu` objects, struct offset tables, EBC registers, Unicorn results, tunables and nodes, corrections to `abi/`, notes for clients, open questions. |
| [`driver/tools/`](driver/tools/) | Ghidra headless recipe (`run.sh`, `ImportKallsymsRaw.java`, `DecompileList.java`, `DecompileAllObj.java`, `annotate_decomp.py`), annotated objdump (`kdis.py`), stock-vs-`.uu` diff (`objdiff.py`), liveness inventory (`inventory.py`), Unicorn byte-exact checks (`ebc_emu.py`). |
| [`reagl/README.md`](reagl/README.md) | REAGL (EPD mode 15): the two-pass algorithm, the halo mask, the thresholds, the internal mode 16, dead code. |
| [`reagl/tools/`](reagl/tools/) | Ghidra recipe for the REAGL functions and the Unicorn checker `reagl_emu.py`. |
| [`abi/ebc-abi.md`](abi/ebc-abi.md) | The `/dev/ebc` ioctl ABI, `struct ebc_buf_info`, the frame format, the EPD mode numbers across layers, the extended `framebuffer_device_t` interface of the stock fb HAL, what the kernel receives from the stock userspace, the waveform header as the kernel sees it. Older than `driver/`; superseded statements are marked. |
| [`abi/epd-modes.tsv`](abi/epd-modes.tsv), [`abi/ioctl-table.tsv`](abi/ioctl-table.tsv) | The same tables in machine-readable form. |
| [`abi/fb_onyx.h`](abi/fb_onyx.h) | A header reconstructed from the binaries for the ONYX/Rockchip `framebuffer_device_t` extension (not vendor source); the interface a replacement fb HAL must implement. |
| [`kernel/kernel-layout.md`](kernel/kernel-layout.md) | Map of the Image (sections, link order, where the vendor code without public source lives) and how to decompile a piece of it. |
| [`kernel/extract_kallsyms.py`](kernel/extract_kallsyms.py) | Recovers kallsyms from a raw Image: `python3 -I kernel/extract_kallsyms.py IMAGE OUT.txt`. |
| [`SOURCE-AVAILABILITY.md`](SOURCE-AVAILABILITY.md) | The GPL kernel code and modules in the RC2 firmware, and what source for them exists. |
| [`kernel/image-initcalls.txt`](kernel/image-initcalls.txt) | The 637 initcalls of the 2017 Image (= the built-in drivers and subsystems). |

## Highlights for driver writers

All of these are explained, with addresses and confidence marks, in [`driver/README.md`](driver/README.md) and [`reagl/README.md`](reagl/README.md).

- **Buffer model.** ioctl 0x7000 hands out one of **4 slots of w·h bytes** (8-bpp capacity; a 4-bpp frame uses the first half) from an
  8 MB pool reserved at 0x7f700000. It blocks until a slot is free. At steady state one slot is pinned as the "old" image, so userspace
  has at most 3 in flight. The pool is mmapped write-combining with no bounds check; the kernel reads it through a cached mapping.
- **Modes accepted from userspace: 0–6, 8–12, 15.** 7 (TEXT), 13, 14 and ≥ 16 take the error path and **leak a slot**. Mode 16 exists
  only as the kernel-internal second REAGL pass.
- **Three engines.** Hardware LUT (16 words per frame in the EBC LUT SRAM, loaded in 64-frame chunks, the next chunk queued from the
  frame-end IRQ); CPU "direct" for modes 9/11/12 (2-bpp ping-pong buffers computed one frame per IRQ on a SCHED_FIFO-99 kthread); CPU
  AUTO (mode 0) with a per-pixel frame counter.
- **LUT pipeline.** The waveform is decoded on every update into a 5-bit `tbl[f][32][32]`; the hardware LUT is packed from the even
  indices, `word[f·16+old] |= tbl[f][2·old][2·new] << 2·new`. The 512 KB LUT is rebuilt whenever the **EPD mode** (not the LUT type) or
  the temperature range changes.
- **OED_PART (10) draws nothing**: its LUT type decodes the DU4 waveform and then builds no LUT.
- **Temperature quirks.** The TPS65185 temperature is read over I²C on every update (+10 ms `msleep`); the signed byte is clamped as
  unsigned (> 50 → 25, so −1 °C becomes 25 °C); **≥ 43 °C falls through to range 0**, the coldest waveform (GC16 131 frames instead of 38).
- **The kernel filters frames.** PART/OED_PART/DIRECT_PART frames with no changed pixel are dropped before power-up; if every changed
  pixel's new value is pure black or white, the frame is promoted to DU. Queued, not-yet-started PART-class frames are collapsed into
  the newest one (A2, BLOCK and FULL_WIN are never dropped).
- **Timing.** 1448×1072 at 40 MHz pixel clock, 4 px per clock: 11.96 ms per frame (83.6 Hz). GC16 at range 8 is 38 frames = 0.454 s;
  back-to-back updates are 0.47 s apart on the device.
- **Idle → busy costs.** When the queue drains the PMIC is powered down at once; the next post first waits in a **100 ms busy-wait**
  (`mdelay(100)`), then pays the ~25 ms PMIC power-up. There is no power-off hold time.
- **Power sequencing.** On: wake lock `ebc`, board power (ACT8931 LDO4 3.0 V panel logic + pin mux), clocks (`dclk_ebc`, `hclk_ebc`,
  `aclk_lcdc1`, `pd_lcdc1`), then TPS65185: UPSEQ0/1 overridden to 0x39/0x11, ENABLE 0x20 (3V3) → 2 ms → 0xAF, poll PG == 0xFA up to
  30× at ~20 ms, 3 attempts, **a final failure is swallowed**. Off: ENABLE 0x6F (standby, 3V3 kept), clocks, board off.
- **REAGL (mode 15)** is an algorithm: a GL16 pass, then an internal mode-16 pass that pulses `tbl[31][31]` on white pixels that bordered
  dark pixels on the previous page. Fewer than 200 differing 32-bit words → PART; pass 2 runs only if the 83-px status-bar stripe is
  unchanged.
- **Waveform source.** `/ebc_waveform.bin` from the initramfs, read into the 1 MB `waveform_addr=0x7ff00000` window with no size and
  no CRC check. The waveform in the panel's own SPI flash is never used for display.
- **Known stock bugs.** LUT-mode window start uses a hard-coded 1024-px stride (`(x1 + y1·1024)/2`), so a sub-window with `y1 ≠ 0`
  fetches the wrong rows; `direct_mode_data_change` compares pixels 1–3 of a group as `old == 2·new`; `ebc_empty_buf_get` recurses
  after a signal; `decodewaveform_19` checks its 512-frame limit only after a whole RLE run; mode-9 window bounds are inclusive.

## How to reproduce

1. **Get a kernel.** Download the firmware update from the support page above. `boot.img` inside the zip is an Android boot image
   (`ANDROID!` magic): the kernel size is the u32 at offset 8, the page size the u32 at offset 0x24 (16384 here), and the raw Image
   starts at the first page boundary after the header (offset = page size):

   ```sh
   python3 -I -c 'import sys,zipfile,struct; b=zipfile.ZipFile(sys.argv[1]).read("boot.img"); assert b[:8]==b"ANDROID!"; n,=struct.unpack_from("<I",b,8); p,=struct.unpack_from("<I",b,36); open(sys.argv[2],"wb").write(b[p:p+n])' update.zip Image
   ```

   This gives the 2019 Image (7 774 244 bytes, sha256 `56bb7228a064f6a1…`).
2. **Symbols.** `python3 -I kernel/extract_kallsyms.py Image kallsyms.txt` (38 772 symbols in the 2019 Image, 38 721 in the 2017 one).
3. **Read the code.** `python3 -I driver/tools/kdis.py Image kallsyms.txt ebc_image_addr_set` prints an annotated objdump listing;
   `--callers SYM…` scans for callers. Ghidra: `IMAGE=… KALLSYMS=… RK=… driver/tools/run.sh <scratch-dir>` (raw-binary import at
   0xc0408000, kallsyms labels, functions only for the EBC span) also decompiles the public `.uu` objects and runs `objdiff.py` and
   `inventory.py`. The Ghidra scripts and the Unicorn harnesses check the 2017 hash; with the 2019 Image, use `kdis.py`, `objdiff.py`
   and `inventory.py` directly (see `driver/README.md` §10).
4. **Emulate.** `uv run --script driver/tools/ebc_emu.py IMAGE KALLSYMS [ebc_waveform.bin]` and
   `uv run --script reagl/tools/reagl_emu.py IMAGE` enter single stock functions in Unicorn 2.1.4 and compare them byte for byte with
   Python reference implementations (2017 Image only).
5. **Public older generation.** The precompiled `.uu` objects of the previous driver generation are in
   [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources) under `drivers/video/rockchip/rk_epd/` (they carry
   symbols and relocations; uudecode them, never run them). [ridi/linux-paper](https://github.com/ridi/linux-paper) has source for
   `epd_spi_flash.c`, `ebc_public.c` (panel table, 1448×1072 timings) and `tps65185.c` of that generation, but not `hardware_ebc.c`
   or `epd_lut.c`.

Do not publish what the tools generate (decompiles, uudecoded objects, full listings): that is vendor code.

## Confidence marks

- [CONFIRMED-emu]: the stock function was run alone in Unicorn and matched a Python reference byte for byte.
- [CONFIRMED-dis]: read directly in the objdump listing at the given address.
- [CONFIRMED-log]: seen in a device dmesg log.
- [CONFIRMED] (in `abi/`): read directly from code.
- [STRONG]: inferred from several confirmed facts.
- [VERIFY] / [GUESS]: open, or needs the device.
- [DANGER]: would need patching the stock kernel binary.

## About this work

Not affiliated with ONYX or Rockchip. This came out of porting Android 4.4 to the RC2 on its stock kernel. The analysis was done with
an AI coding assistant (Claude); results were checked on the hardware where marked [CONFIRMED]. Reverse engineering was done for
interoperability. This repository describes the vendor driver; it contains no vendor code or binaries. The vendor ships this
code inside its GPLv2 kernel without publishing the source; see [`SOURCE-AVAILABILITY.md`](SOURCE-AVAILABILITY.md). Code: MIT (`LICENSE`).
Text: CC BY 4.0.
