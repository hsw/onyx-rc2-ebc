# Other EBC and EPDC drivers compared with the RK3026

One reference for every E-Ink controller driver that was read while documenting the RK3026 EBC: two generations of
Rockchip's vendor driver for the later RK3566/RK3568 EBC, the two mainline RFCs from 2022 (Rockchip EBC and i.MX6 EPDC) and
Amazon's Kindle Paperwhite 3 kernel (i.MX6 SoloLite EPDC). The RK3026 column is the stock RC2 driver described in
[`README.md`](README.md) and [`registers.md`](registers.md).

Inputs (all public):
- **Ralim**: [Ralim/ebc-dev-reverse-engineering](https://github.com/Ralim/ebc-dev-reverse-engineering) at `1a089fc`
  (2022-01-17): a Ghidra clean-up of Rockchip's RK3566 `ebc_dev` driver, version "1.01" in `done/` and a second pass on
  version "2.09" in `v2.09/`. Paths below are relative to that repository. Nothing in it was built or run.
- **Rockchip**: [rockchip-linux/kernel](https://github.com/rockchip-linux/kernel) branch `develop-4.19` at `f39b590`
  (2022-08), `drivers/gpu/drm/rockchip/ebc-dev/`: C glue plus the compiler-generated `ebc_dev_v8.S`,
  `epdlut/pvi_waveform_v8.S` and `epdlut/rkf_waveform_v8.S` (driver "4.15"); and branch `develop-6.1` (driver "1.05"),
  summarised in [`new-driver.md` §1](new-driver.md#1-rockchips-later-vendor-driver-ebc-dev-61-tree).
- **Holland RFC**: Samuel Holland, "[RFC PATCH 00/16] drm/rockchip: Rockchip EBC ("E-Book Controller") display driver",
  2022-04-13, <https://lore.kernel.org/all/20220413221916.50995-1-samuel@sholland.org/> (the whole thread, 28 messages).
  Patch numbers below are the series' own (`09/16` …).
- **Kemnade RFC**: Andreas Kemnade, "[RFC PATCH 0/6] drm: EPDC driver for i.MX6", 2022-02-06,
  <https://lore.kernel.org/all/20220206080016.796556-1-andreas@kemnade.info/> (the whole thread, 22 messages).
- **Kindle**: Amazon's GPL release for the Kindle Paperwhite 3 (7th generation), "Kindle Source Code Notice", release
  5.16.2.1.1, `Kindle_src_5.16.2.1.1_4097470002.tar.gz`, kernel `linux-3.0.35` (`drivers/video/mxc/mxc_epdc_fb.c` with
  Amazon's `mxc_epdc_fb_lab126.c`, `drivers/regulator/max77696-epd.c`).
- **ONYX RK3128**: two ONYX BOOX firmware kernels (static analysis only, nothing run): Livingstone, build
  `2022-08-16_11-05_2.1.2_467fe95`, kernel 3.10.0 `#738` (2022-08-04), `update.upx` from
  <https://onyx-boox.ru/files/livingstone/update.upx> (sha256 `90c3cd5f…3eef`), decompressed kernel Image sha256
  `a4ff04ed58bff9c1bc3e0e8dde50a7adb4d964a8fb169a745d30f2fdce7a2cab`; and Darwin 7 (`MC_DARWIN7`), build
  `2022-01-17_21-12_2.1.2_5b90d57`, kernel 3.10.0 `#71`, <https://onyx-boox.ru/files/darwin7/update.upx> (sha256
  `fa338693…625b`), Image sha256 `4d99c6210f9871795a944e4a5b7d80dbae0189a1e5f051e39ab67625681b13b9`. `update.upx` is AES-128-CFB of
  a recovery zip; the per-model key comes from the community list
  [Hagb/decryptBooxUpdateUpx](https://github.com/Hagb/decryptBooxUpdateUpx) (`BooxKeys.csv`, last change `ca511056`,
  2026-10-02). The kernels carry kallsyms (symbols recovered with `vmlinux-to-elf`); the device tree is the `rk-kernel.dtb`
  in the RSCE resource image of each `boot.img`. Mainline reference: Linux master `24a19b95` (2026-10-12),
  `drivers/clk/rockchip/clk-rk3128.c`, `arch/arm/boot/dts/rockchip/rk3128.dtsi`.
- **Storytel Reader** (made by ONYX for Storytel; 2023 firmware): [ntherning/StorytelReaderMods](https://github.com/ntherning/StorytelReaderMods)
  at `389b3b2` (2025-12-29): the boot logs `dumps/gen{1,2}/bootlog` (sha256 `449c54bf…59b1b`, `9ec2686c…0f328`) and the release
  `20231112` assets `boot-gen1-patched.img.zip` (sha256 `4b55f24c…4165f`; inside `boot-gen1-patched.img` `56fda19d…6e5`) and
  `boot-gen2-patched.img.zip` (`35e7b372…4c7`; inside `boot-gen2-patched.img` `31a94a57…dee`), from
  <https://github.com/ntherning/StorytelReaderMods/releases/download/20231112/>. Gen 2 (RK3128, Android 6): kernel Image
  from that `boot.img` sha256 `c65e9586b029793d349c2da8d5b0edcbe3a3beb83c17d5306e60986f78962aa3`, DTB (RSCE `second`) `f4101eaf…1a29`.
  Gen 1 (RK3026, Android 4.2): ramdisk only, no kernel. Static analysis and log reading only.
- **RK3026**: the stock RC2 kernel Image (2017-11-07; see the [top README](../README.md#the-analysed-kernel)), checked in a
  disassembly of that kernel and, where marked, on the device; the public headers in
  [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources).

Facts only: behaviour is described in our own words, no code from any of these sources is copied. Names of registers,
fields, functions and files, offsets and constants are given so that the statements can be checked.

Marks: [CONFIRMED] read directly in the cited source; [CONFIRMED-dis] read in the stock RC2 disassembly; [CONFIRMED-emu]
the stock function run in Unicorn against a reference; [STRONG] inferred from several confirmed facts; [VERIFY] / [GUESS]
open.

## 1. Matrix

Short cells; the sections below have the detail and the confidence marks. "—" = does not exist, "n/a" = does not apply,
"unknown" = not found in what was read.

| | RK3026 stock (this repo) | RK3566 `ebc_dev` 1.01 / 2.09 (Ralim) | Rockchip 6.1 `ebc-dev` 1.05 | Holland RFC (RK3566/68) | Kemnade RFC (i.MX6 EPDC) | Kindle PW3 (i.MX6SL EPDC) | RK3128 (ONYX, kernel 3.10) |
|---|---|---|---|---|---|---|---|
| **Register layout vs RK3026** | reference: 21 registers 0x00–0x50, LUT SRAM at +0x1000 | 0x00–0x50 same offsets and names; `DSP_START` count, `INT`, `WIN_CTRL`, top of `EPD_CTRL` differ; adds `VNUM` 0x54, `WIN_MST2` 0x58 | as RK3566 (`tcon/ebc_tcon.c`) | RK3566 header plus `DSP_RST`, polarity bits, `DSP_FRM_INT_NUM` | other controller | other controller (same EPDC family as Kemnade) | same IP: window `0x10114000`, 16 KiB, GIC SPI 49; the driver writes the same offsets 0x00–0x50 with the RK3026 formulas (`ebc_panel_scan_set`, `ebc_win_dsp_set`, `ebc_dsp_ctl_set`, `ebc_image_addr_set`, even the same function names) [CONFIRMED-dis]; no RK3566 registers (`VNUM`, `WIN_MST2`) |
| **LUT engine used?** | yes: modes 1–6, 8, 10, 15, 16; CPU direct for 9, 11, 12 and AUTO 0 | no: every mode is CPU direct, one frame per start | no [STRONG] | only for full-screen reset and clear; partial updates CPU direct (default) or three-window | yes: hardware LUTs, up to 64 at once | yes (same EPDC hardware) | no: every frame is a direct-mode frame (`WIN_MST0` = 2-bit drive codes, `DSP_START` = 1); nothing is written to +0x1000; frames built by the CPU in a software EPDC (`onyx,sepdc`) [CONFIRMED-dis] |
| **LUT size / frames per load** | 4 KB = 64 frames × 16 words; longer waveforms in 64-frame chunks reloaded from the IRQ | 16 KB: ≤ 256 frames (16-level) or ≤ 64 (32-level mode); not used | same hardware; upload check "≤ 256 frames" | whole 16 KiB written, ≤ 256 phases in one start | n/a: the controller reads the waveform from memory | n/a | n/a (SRAM unused); `DSP_START` frame count always 0; software side: 128 LUT slots (bitmap of 4 words, `epdc_get_free_lut` stops at 127) [CONFIRMED-dis] |
| **Interrupt bits** | 3 sources: status 2:0, mask 5:3, clear 8:6; done = status 1, clear 7 | 4 sources: status 3:0, mask 7:4, clear 11:8; done = status 1, clear 9 | as RK3566 | as RK3566 | per-LUT completion (`EPDC_IRQ1`/`EPDC_IRQ2`, one bit per LUT, 64 LUTs), working-buffer complete, LUT collision, TCE underrun, frame end [CONFIRMED-src, patch 4/6] | as Kemnade (same hardware) | as RK3026: status 2:0, mask 5:3, clear 8:6; done = status 1, clear 7, mask 4; a start clears bits 15:9 and 7:3 of `INT` and sets `0x28` (frame count field 15:9 = 0) [CONFIRMED-dis] |
| **Windows (`WIN_MST0/1/2`)** | LUT: MST0 old, MST1 new; direct: MST0 = 2-bit frame; no MST2 | MST0 = 2-bit frame only (the core); MST2 exists | as RK3566 | LUT: MST0 new, MST1 old (LUT transposed); three-window: per-pixel phase buffer in MST2; direct: MST0 | n/a (16-bpp working buffer) | n/a | direct only: `WIN_MST0` = frame address; `WIN_MST1` never written; `WIN_ACT`/`WIN_DSP` = the full panel, `WIN_CTRL` = `0x20FC0 \| fmt`, the RK3026 constant [CONFIRMED-dis] |
| **Waveform format, parsed where** | E Ink WBF `/ebc_waveform.bin` from the initramfs; decoded in the kernel on every update | WBF or Rockchip `rkf`; in the kernel (prebuilt) | as 1.01, prebuilt; reserved memory or `waveform.bin` | the panel's raw WBF (`rockchip/ebc.wbf`); kernel helper, 5-bit files only | NXP's pre-converted `imx/epdc/epdc.fw`; the controller decodes | gzipped, pre-converted `imx/epdc_<video-mode name>.fw` made in userspace; the kernel reads only the header, the temperature table and the voltage data [CONFIRMED-src: `mxc_epdc_fb.c:5793-5808`, `5646`, `5659-5674`] | E Ink WBF ("PVI") or an i.MX-style pre-converted file, chosen by the DT/driver value `waveform_file_format` (0 = PVI parser `onyx_waveform_parse_pvi`, 1 = `onyx_waveform_parse_imx`; other value: error); `request_firmware_nowait("waveform.wbf")` from `/vendor/waveform/`, else the file `/waveform/eink_waveform.wbf`; decoded in the kernel, to per-frame buffers by the CPU [CONFIRMED-dis; default value of the property unknown, [VERIFY]] |
| **Temperature-range selection** | range `i − 1` for the first `T < bound[i]`; **≥ 43 °C falls to range 0** (bug) | **one range warmer** than RK3026; last range never used | as RK3566 | RK3026 convention; below the first bound keeps the old LUT; last range never used [STRONG] | `bound[i] ≤ T < bound[i+1]`, clamped to the first and last range | last range never used; below the table: range 0 [CONFIRMED-src: `mxc_epdc_fb.c:2216-2241`] | not traced; `onyx_epdc_set_temp` stores a temperature byte pushed by userspace and clears an 11-entry per-range table [VERIFY] |
| **Who chooses the update mode** | userspace per frame (ioctl 0x7001); the kernel drops unchanged frames, promotes black/white-only frames to DU, runs REAGL | userspace per buffer (`/dev/ebc`, other mode numbers) | userspace per buffer | module parameter `default_waveform` (GC16); none from userspace | the hardware (`WAVEFORM_MODE_AUTO`) | userspace per update, or AUTO by a PxP histogram [CONFIRMED-src: `mxc_epdc_fb.c:4678-4690`] | userspace per update (HWC through `SET_EBC_SEND_UPDATE`); the kernel only maps its mode number to the waveform file's mode index (`onyx_waveform_mode_transform`, 13-row table of 56-byte rows chosen by the WBF type byte); AUTO is not a hardware mode [STRONG] |
| **Temperature source** | TPS65185 ADC on every update (I²C, +10 ms); > 50 → 25 °C, read as unsigned | TPS65185; 1.01 > 50 → 25 °C (same message), 2.09 clamps to 0–50 | TPS65185 polled every 10 s; outside 0–50 → 25 °C | IIO channel, every refresh; review asked for a thermal zone | thermal zone by name, default 20 °C | panel NTC through the PMIC ADC (channel AIN0), every 60 s, default 25 °C [CONFIRMED-src: `drivers/hwmon/max77696-adc.c:45-48`, `1034-1067`] | TPS65185 ADC as on the RC2: regulator `TMST` of the `tps6518x` driver (start conversion in register 0x0C, poll for done, bit 5) [CONFIRMED-dis]; who calls it and how often: [VERIFY] |
| **Panel timings** | panel table compiled into the kernel | device tree, as 6.1 [STRONG] | `ebc-dev` device-tree node, `panel,*` properties | `drm_panel` (panel-simple) through the OF graph | the controller node | board file, mode chosen by the first three barcode characters [CONFIRMED-src: `arch/arm/mach-mx6/board-mx6sl_wario.c:1055-1260`, `mxc_epdc_fb_lab126.c:1418`, `2586-2599`] | device tree node `eink-timings`: `panel_name = ED060KD1`, 1448×1072, `sdclk-frequency` 40 MHz, margins 8/55/4/4, `hsync_len` 17, `vsync_len` 2, `gdck_sta` 100, `lgonl` 281, frame rate 85: the RC2's constants [CONFIRMED, DTB] |
| **PMIC** | TPS65185: on when an update arrives, off as soon as the queue drains | TPS65185 behind an `ebc_pmic` layer | TPS65185 vendor driver (not safe on the RC2) | `panel`/`vcom`/`vdrive` regulators on the EBC node; no PMIC driver in the series | regulators (TPS65185 or SY7636A) | MAX77696: rails, then VCOM after PWR_GOOD; deferred power-off [CONFIRMED-src: `mxc_epdc_fb.c:1425-1523`, `drivers/regulator/max77696-epd.c:237-305`, `398-436`] | TPS65185 (`TI,tps6518x` at I²C `0x68`, `pwr_seq`/`upseq`/`dwnseq`, VCOM and wake-up GPIOs), regulators `DISPLAY`, `VCOM`, `V3P3`, `TMST`; powered up per update, powered down by a delayed worker (`onyx_epdc_set_pwrdown_delay`) [CONFIRMED-dis/DTB] |
| **Completion event to userspace** | none in general; mode 8 (BLOCK) blocks its ioctl until shown | unknown | unknown | fake vblank when the pixels are copied, not when the panel is done | none: `pipe_update` only queues one hardware update per damage clip (patch 4/6); per-LUT completion IRQs stay inside the driver (they free the LUT and the update buffer); the only wait is `mxc_epdc_flush_updates` on pipe disable [CONFIRMED-src] | `MXCFB_WAIT_FOR_UPDATE_COMPLETE` on an update marker: returns when the LUT-complete interrupt has fired, 5 s timeout [CONFIRMED-src, §7] | `SET_EBC_WAIT_ALL_UPDATE_COMPLETE` flushes the update queue and sleeps on a completion; a per-update wait (`onyx_epdc_fb_wait_update_complete`) finds the update by its **magic** (marker) in the list and waits up to 2000 ms on that update's completion (`-ETIMEDOUT` after). The EBC ISR calls a callback that releases a semaphore per frame and wakes the waiters after the last frame [CONFIRMED-dis] |
| **Status / fate** | shipping binary, no source (kernel 3.0.36) | prebuilt AArch64 objects in the 4.19 BSP; Ralim's decompile, untested | prebuilt AArch64 core, not wired into the 6.1 build | RFC v1 only; last reply 2022-06-08 | RFC v1 only; thread ends 2022-03-14 [VERIFY later versions] | shipped product kernel, GPL release (3.0.35) | shipping kernel, no source; Livingstone (2022-08) and Darwin 7 (2022-01); driver version string `ONYX_EBC_DRIVER_VERSION_2.00` |

## 2. RK3026 stock (this repository)

The reference column. Details: buffers and the userspace contract in [`README.md` §2.2](README.md#22-buffers-and-the-userspace-contract),
the frame pipeline and LUT chunking in [§2.3](README.md#23-the-frame-pipeline), modes in
[§2.4](README.md#24-ebc_thread-state-machine-and-the-mode-table), waveform decode and temperature in
[§2.5](README.md#25-lut-pipeline-waveform-decode-temperature), the CPU engines in [§2.6](README.md#26-the-cpu-engines), the
waveform source in [§2.9](README.md#29-waveform-source-and-boot-sequence), the PMIC in
[§2.10c](README.md#210c-pmic-tps65185-papyrus-epdpowertps65185c), and the registers in [`registers.md`](registers.md).

## 3. RK3566 `ebc_dev` 1.01 / 2.09 (Ralim's decompile)

### 3.1 What the repository is

- **The SoC is the RK3566 (PineNote), not the RK3188.** The repository's description says "Reverse engineering notes on the
  RK3566 EBC controller #pinenote", and its TCON file matches `"rockchip,rk3568-ebc-tcon"` [CONFIRMED]. The RK3188 has no EBC
  block: in the rychly tree `rk3188_epd_defconfig` sets `CONFIG_SOFTWARE_EBC=y`, `board-rk3188-epd.c` drives the panel
  through LCDC1 (`EBC_EXTEND`, `ebc_init_lcdc`), and no RK3188 header defines an EBC base. The hardware EBC exists on RK29xx
  and RK3026 (`0x10114000`, 16 KB, IRQ 81 on the RK3026) and then on RK3566/RK3568 [CONFIRMED].
- **Sources reconstructed:** Rockchip's prebuilt `ebc_dev_v8.o`, `pvi_waveform_v8.o` and `rkf_waveform_v8.o` (AArch64)
  from the 4.19 BSP. `done/` is driver "1.01"; `v2.09/` is a second pass on driver 2.09 by Samuel Holland (pull request #3,
  "much closer to … the stock Android build (v2.08)"). The current `develop-4.19` blob reports "4.15" [CONFIRMED].
- **Copied, not reversed:** `done/tcon/*` (register map, `ebc_tcon.c`), `done/pmic/*` (TPS65185), `done/bufmanage/*`,
  `done/epdlut/epd_lut.[ch]`, `ebc_panel.h`, `ebc_dev.h`, `ebc_public.c` are Rockchip's public GPL C (2020). Against
  `develop-4.19`: `eink_tcon.c`, `ebc_pmic.[ch]`, `buf_list.c`, `ebc_public.c` are identical, `ebc_tcon.c` differs in 4
  lines (timing details), the rest are older revisions [CONFIRMED].
- **State:** the author says it is untested and not compiled; it is raw Ghidra output with names added and does not compile
  as is. No licence file; the copied files carry SPDX GPL-2.0, the decompiled ones no header. No binaries, only Ghidra
  databases. No LUT-mode code and no register documentation beyond the public header [CONFIRMED].
- **Relation to Holland's RFC:** his `v2.09/` pass was written to check his own data-path reimplementation, which became
  the 2022 mainline RFC (§5). Both describe the same RK3566/RK3568 EBC generation [CONFIRMED].
- **Same driver family as the RK3026 one:** `ebc_thread`, `ebc_auto_tast_function` (with the same typo),
  `direct_mode_data_change`, `frame_done_callback`/`ebc_frame_timeout`, `new_buffer_refresh`, the `ebc_info` fields, the
  ioctl range 0x7000+, `ebc_buf_s`, the TPS65185 "papyrus" driver and several log strings are inherited from the RK3026
  `rk_epd` driver [CONFIRMED].

### 3.2 Registers against the RK3026

RK3566 side: `done/tcon/ebc_tcon.c` (Rockchip's public header text). RK3026 side: rychly `rk_epd/ebc.h` plus the stock
writes ([`registers.md`](registers.md)).

| Off | Name | RK3566 | RK3026 | Same? |
|---|---|---|---|---|
| 0x00 | `DSP_START` | b0 start, **b9:2 frames − 1 (8 bit)**, b12 `SW_BURST_CTRL`, b13 `EINK_MODE`, b25:16 `SDCE_WIDTH`, b31 `OUT_LOW` | b0 start, **b7:2 frames − 1 (6 bit)** | offset yes; counter narrower, upper fields unknown [CONFIRMED-dis + header] |
| 0x04 | `EPD_CTRL` | b0 `SDSHR`, b1 `GDRL`, b4:2 `PWR`, b5 `AUO`, b6 `SDDW`, b7 `THREE_WIN`, b15:8 `GD_ST`, b26:16 `GD_END`, b30 `FRM_SEL`, b31 `MODE_SWAP` | low 6 bits named the same; stock writes width/4 into b15:8 and a gate-start value into b31:27 | low bits same [CONFIRMED]; b26:16 gate end in both [STRONG]; the upper half re-laid out [GUESS for the RK3026 meaning] |
| 0x08 | `DSP_CTRL` | b31:30 swap, b29 diff (update mode), b28 LUT (display mode), b27 `VCOM_MODE`, b19:16 SDCLK divider | same masks; stock always ORs `0xC0030000` | **identical** [CONFIRMED] |
| 0x0C–0x1C | H/V timings, `DSP_ACT_INFO` | total, sync end, active start/end; size | the same packing | same layout [CONFIRMED-dis] |
| 0x20 | `WIN_CTRL` | b27:19 `WIN2_FIFO_AF`, **b18 enable**, b12:10 burst, b9:2 FIFO, b1:0 format | `0x20FC0 \| fmt`: **b17 enable**, FIFO/burst in b15:2 | **different layout**; format b1:0 agrees (0 = 4 bpp) [STRONG] |
| 0x24/0x28 | `WIN_MST0/1` | previous / current image, or the direct frame in MST0 | old / new; MST0 = direct frame | same role [CONFIRMED-dis] |
| 0x2C–0x38 | `WIN_VIR`, `WIN_ACT`, `WIN_DSP`, `WIN_DSP_ST` | height 26:16 or 31:16, width low bits | the same packing | same |
| 0x3C | `INT` | status 3:0 {frame end, **display end**, frame flag, line flag}, mask 7:4, clear 11:8, frame number 19:12 | status 2:0, mask 5:3, clear 8:6; stock tests b1, clears b6–b8, writes `0x28 \| n<<9` at start | **3 sources on the RK3026, 4 on the RK3566**; "b1 = display end" in both [STRONG] |
| 0x40–0x4C | `VCOM0–3` | not written | zeroed | same offsets |
| 0x50 | `CONFIG_DONE` | written as 1 | written as `0xFFFF` | same register, different value [CONFIRMED] |
| 0x54 | `VNUM` | line-flag number | — | RK3566 only |
| 0x58 | `WIN_MST2` | per-pixel frame counters (three-window mode) | — | RK3566 only |
| 0x1000 | LUT SRAM | 16-level: ≤ 256 frames × 16 words; 32-level mode: ≤ 64 frames × 64 words; 16 KB | 64 frames × 16 words = 4 KB | same start, 4× larger, extra 32-level mode [CONFIRMED-dis / CONFIRMED] |

Base and clocks: RK3568/RK3566 `0xfdec0000`, size `0x5000`, `GIC_SPI 17`, `hclk`/`dclk`, power domain `PD_RGA` (from the
`develop-4.19` `rk3568.dtsi`). RK3026: `0x10114000`, 16 KB, `GIC_SPI 49` ([`registers.md` §5](registers.md#5-outside-the-ebc-window)).

**Verdict:** one IP family. The RK3566 is a later revision with a wider frame counter, a bigger LUT SRAM, a 32-level LUT mode,
three-window mode and a fourth interrupt source; the RK3026 is the earlier one, probably shared with RK29xx at the same base
address [STRONG]. The RK3566 `EINK_MODE`, `THREE_WIN` and `OUT_LOW` bits may have no RK3026 equivalent [VERIFY].

### 3.3 LUT format and the LUT engine

- **The hardware LUT word is the same on both** [STRONG; RK3026 CONFIRMED-emu]: 16 words of 32 bits per frame, word *k* =
  old level *k*, bits `2n+1:2n` = the 2-bit drive code for new level *n* (0 none, 1 toward black, 2 toward white). Both
  build it from the even indices of the 32-level WBF table: RK3026 `get_lut_data_hard`, RK3566 `get_lut_gray16_data` after
  compacting the table to 16 levels. The RK3566 expansion in `ebc_lut_update` confirms "word = old, field = new".
- **The RK3566 vendor driver never programs the LUT engine.** `lut_data_set` is never called, and `dsp_mode_set` is called
  only from `flip()` with all zeros (direct mode, one frame per start) in both `done/` and `v2.09/` [CONFIRMED in the
  decompile; STRONG for the binary]. On the RK3026 most modes use the hardware LUT ([`README.md` §2.4](README.md#24-ebc_thread-state-machine-and-the-mode-table)).

| | RK3566 1.01 / 2.09 | RK3026 stock |
|---|---|---|
| levels | 16 and 32 (`WF_TYPE_GRAY32`: 64 words per frame) | 16 in hardware; the 32-level table is kept for the CPU AUTO engine |
| frames per LUT load | ≤ 256 (16-level) / ≤ 64 (32-level), `tcon_lut_data_set` | **≤ 64**; longer waveforms in 64-frame chunks reloaded from the IRQ through a workqueue, `DSP_CTRL` b27 set for middle chunks |
| CPU direct table | 64 KB per frame, indexed by old byte × 256 + new byte (2 pixels at a time) | none: per pixel `(word[old] >> 2·new) & 3` from the 16-word LUT [CONFIRMED-emu] |
| AUTO | GC16 words with the new = 0 and new = 15 pairs replaced by DU codes | the same idea on the 32-level table: GC16 plus DU in the target-0/30 columns; `frame_num = gc16 \| du << 8` in both [CONFIRMED-emu] |
| RESET | one code per frame broadcast to all pairs | a full table through `get_lut_data_hard` |
| LUT cache key | LUT type + `temperature / 3` | **EPD mode** + temperature range; the waveform is re-decoded on every update |
| LUT-type numbers | RESET 1, GRAY16 2, GRAY4 3, GRAY2 4, AUTO 5, A2 6, GC16 7, GL16 8, GLR16 9, … | RESET 1, GC16 2, DU4 3, DU 4, AUTO 5, A2 6, REAGL 8/9: **1–6 are the same numbers** (the older public `.uu` generation numbered them differently) [CONFIRMED-dis] |

Both store the frame count as a byte and program `frames − 1` into `DSP_START` (always 1 frame on the RK3566 vendor driver,
which flips per frame).

**Buffer order.** Holland's RFC (§5) puts the **new** image in `WIN_MST0` and the old one in `WIN_MST1` and transposes the
LUT to match (word = new level, field = old level). Rockchip (RK3566 vendor and RK3026 stock) does the opposite. Both are
consistent with one hardware rule: **the word is selected by the MST0 pixel and the 2-bit field by the MST1 pixel** [STRONG:
three independent drivers agree; the swapped order was not tested on the RK3026].

### 3.4 Frame and buffer pipeline

| | RK3566 1.01 / 2.09 | RK3026 stock |
|---|---|---|
| image buffers | 4 bpp grey, low nibble first (`WIN_FMT` 0) | the same; slots are w·h bytes (8-bpp capacity for AUTO), 4 slots |
| old / new | `prev_dsp_buf` / `curr_dsp_buf` | the same names and roles, `prev` pinned as "old" |
| direct frame | 2 bpp, two ping-pong buffers | the same: `auto_direct_buffer0/1`, w·h/4 each, pixel 0 in bits 1:0 [CONFIRMED-emu] |
| per-frame flow | compute frame 0, `flip()` (DMA sync, direct mode, MST0 = buffer, start 1 frame), compute frame 1; each IRQ flips and computes the next | the same ping-pong for modes 9/11/12 and AUTO; LUT modes start once per ≤ 64-frame chunk |
| IRQ | tests display end (b1), clears b9 | tests b1, clears b6/b7/b8, toggles mask b4 [CONFIRMED-dis] |
| watchdog | `frame_timer` → `ebc_frame_timeout` → `frame_done_callback` | `frame_timer` 3 s → `rk29_ebc_frame_timeout` → the same completion |
| DMA / cache | `dma_sync_single_for_device` before each flip | `flush_cache_all` in the CPU paths; the pool is cached in the kernel, write-combining for userspace |
| modes | 0 AUTO, 1 OVERLAY, 2–6 FULL_{GC16, GL16, GLR16, GLD16, GCC16}, 7–11 PART_*, 12 A2, 13 DU, 14 RESET, … | 0 AUTO, 1 FULL, 2 A2, 3 PART, … 15 REGAL: **different numbering**; ioctls 0x7000–0x7005 against 0x7000–0x7004 |
| "partial" | on the CPU (unchanged pixels → 0) | LUT modes use `DSP_CTRL` b29; direct mode 11 zeroes unchanged groups |

The 2.09 direct path is a different implementation (table lookup, 2 pixels at a time, with a mirror option), so the RK3026
`direct_mode_data_change` bug (`old == 2·new`, [`README.md` §2.6](README.md#26-the-cpu-engines)) cannot be checked against it
[VERIFY whether 1.01 had the per-pixel version].

### 3.5 Waveform handling

**E Ink WBF (PVI) path: the same decoder lineage** [STRONG]:
- RLE stream: `0xFC` toggles single-byte mode, `0xFF` ends the stream, a repeat byte follows outside `0xFC` mode, 4 codes per
  byte LSB first; output 1024 B per frame laid out `(frame·32 + old)·32 + new`, with a 512-frame limit. RK3026
  `decodewaveform_19` has the same layout [CONFIRMED-emu on the real file]. The RK3566 folds the mode versions into one
  `decodewaveform`; the RK3026 has `decodewaveform_19` and `decodewaveform`.
- **Both read only the low byte** of the 24-bit mode-table pointer at header 0x20 and check the 8-bit sums [CONFIRMED].
- **Mode-index tables, compared byte for byte** (RK3026 `parse_mode_version`, Ralim's `get_wf_mode_index`, and the
  `pvi_mode_table` data in the `develop-4.19` blob): the first 8 entries are identical for MV 0x12 `{0,1,7,3,3,5,6,4}`, 0x19
  `{0,1,7,2,3,4,5,6}`, 0x23 `{0,1,5,2,3,3,3,4}` and 0x18/0x20/default `{0,1,1,2,3,4,5,6}`. The RK3566 adds a 9th entry
  (GCC16) and MVs 0x09, 0x16, 0x43, 0x48, 0x54 [CONFIRMED].
- **The temperature index differs by one** [STRONG]. The RK3566 code returns the first range *i* with `T < bound[i]`,
  capped at header byte 0x26 − 1; RK3026 `get_lut_temp` returns `i − 1` for the first `T < bound[i]` [CONFIRMED-emu].
  - With the RC2 waveform's bounds (0, 3, …, 24, 27, …, 38, 43, 48), the RK3026 uses range 8 (24–27 °C) at 25 °C, which is
    what the device logs (`lut_temp = 8`); the RK3566 code would pick range 9 (27–30 °C).
  - At ≥ 43 °C the RK3026 falls into its range-0 bug ([`README.md` §2.5](README.md#25-lut-pipeline-waveform-decode-temperature));
    the RK3566 caps at range 12, so its last range (43–48 °C) is never used.
  - E Ink's range *i* is [bound *i*, bound *i+1*), so the RK3026 convention looks right [VERIFY]. Holland's helper and
    Kemnade's driver both use it, which makes the RK3566 vendor code the odd one out [STRONG].
- **No CRC on the PVI path** on either: the RK3566 only checks the mode-version byte, as the RK3026 does.

**Rockchip `rkf`: same name, different format:**
- RK3566 `rkf_wf_input`: magic `"rkf waveform"` at +4, length at +0 (≤ 0x40000), CRC at the end, **polynomial 0x04C10DB7,
  MSB first, init 0**: the same unusual polynomial as RK3026 `crc_32` [CONFIRMED-emu]. The constant is also in the
  `develop-4.19` blob.
- The payload differs: per-mode temperature tables and data tables at fixed offsets, LUTs stored **already packed** in the
  16-word format. **No XOR descramble and no Huffman (`zip_init`).** The RK3026 `epd_lut_analying` (CRC, tag, XOR,
  `zip_init`) is the older `rkf` generation and is unreachable on the RC2 ([`README.md` §2.9](README.md#29-waveform-source-and-boot-sequence))
  [CONFIRMED-dis].

**Source:** RK3566 `request_firmware_into_buf("waveform.bin")` or a reserved memory region (`waveform-region` in the device
tree); RK3026 stock reads `/ebc_waveform.bin` from the initramfs into the `waveform_addr` window.

### 3.6 PMIC, power, temperature

- **Both use the TPS65185 "papyrus" driver** (public C on both sides): the same register names, temperature read (TMST1 =
  0x80, poll, `msleep`, read), PG mask `0xFA`, UPSEQ0/1 programming [CONFIRMED]. Default UPSEQ: RK3566 VEE → VNEG → VPOS → VDD
  with 3 ms delays; the rychly RK3026 tree VNEG, VEE, VPOS, VDD or `0xE1/0x55` depending on the branch; the stock RC2 kernel
  overrides them to `0x39/0x11` ([`README.md` §2.10c](README.md#210c-pmic-tps65185-papyrus-epdpowertps65185c)).
- The RK3566 adds an `ebc_pmic` abstraction with GPIO descriptors (`wake_up`, `vcom_ctl`); the RK3026 uses `pwr_ops` /
  `temp_ops` pointers plus board hooks.
- **Power-off:** RK3566 `tcon_disable` sets `DSP_START` b31 (`OUT_LOW`); the RK3026 parks the pins low in the board hook.
- **Temperature clamp:** RK3566 1.01: > 50 → 25 with the message `temperature = %d, out of range0~50 ,use 25`, **the same
  string and the same unsigned-clamp shape as the RK3026**, where −1 °C reads as 25 °C [CONFIRMED: the string is in the stock
  Image]. 2.09: < 0 → 0, > 50 → 50.

### 3.7 What was compared byte for byte, and why not more

- Instruction streams cannot be compared: the RK3566 objects are AArch64, the RK3026 is ARMv7, and Ralim's repository holds
  no binaries.
- Compared: the mode-index rows (identical), the CRC polynomial (identical), the header offsets used (0x10 mode version,
  0x20 low byte, 0x26 range count, 0x30 bounds: identical), and log strings (`out of range0~50 ,use 25`;
  `Unknow waveform version` in both, slightly reworded).
- RK3566 values were also read from the `develop-4.19` `pvi_waveform_v8.S` / `rkf_waveform_v8.S` (driver "4.15", newer than
  Ralim's 1.01). Where the decompile and that file agree, the fact is [CONFIRMED]; where only one was read, [STRONG].

## 4. Rockchip 6.1 `ebc-dev` 1.05

Summarised in [`new-driver.md` §1](new-driver.md#1-rockchips-later-vendor-driver-ebc-dev-61-tree): the core
(`ebc_dev_v8.S`, driver "1.05") and the waveform parsers are prebuilt AArch64 objects that the 6.1 build does not even
reference; only the TCON layer, a TPS65185 driver, a buffer manager and the waveform loader are C. For the matrix:

- like 1.01, the core does not use the LUT engine [STRONG];
- its TCON layer has the RK3566 `INT`, `WIN_CTRL` and `DSP_START` layouts and a "≤ 256 frames" LUT check, all wrong for
  the RK3026;
- its PVI parser accepts mode version 0x19 and picks the same one-warmer temperature range as 1.01, never using the last
  range [STRONG];
- the TPS65185 is polled every 10 s from a workqueue, and its vendor PMIC driver keeps the rails on without a PWRUP GPIO;
- panel timings are `panel,*` properties of a virtual `ebc-dev` device-tree node;
- its `/dev/ebc` ABI is of the same family as the RC2's but incompatible (other meanings for 0x7002–0x7004, a 44-byte
  buffer-info struct, other mode numbers).

## 5. Samuel Holland's mainline RFC (RK3566/RK3568, April 2022)

The series adds `drm_epd_helper.c` (663 lines, GPL-2.0 OR MIT), `rockchip_ebc.c` (1586 lines), the binding
`rockchip,rk3568-ebc.yaml`, a panel-simple entry for the ED103TC2 and rk356x/PineNote device-tree changes. The cover letter
calls it "a clean-sheet design", not a port of the vendor driver [CONFIRMED].

### 5.1 How it drives the hardware

| Path | When | How | Patch |
|---|---|---|---|
| **Global refresh = hardware LUT mode** | display reset at start (skippable with `skip_reset`); clear to white with GC16 when the CRTC is disabled | `DSP_CTRL` b28 (LUT) plus b29 (diff) if `diff_mode`; `WIN_MST0` = next, `WIN_MST1` = previous; `DSP_START` with `SDCE_WIDTH`, `SW_BURST_CTRL` and the phase count; wait for display end (3 s timeout), then `OUT_LOW`. The whole waveform runs in one start (≤ 256 phases) | 09/16 |
| **Partial refresh, three-window mode** | every plane update (damage clips) | `EPD_CTRL` b7 `THREE_WIN_MODE`; a 1-byte-per-pixel **phase buffer** at `WIN_MST2` says which LUT phase each pixel is in. Three-window mode disables the hardware frame counter, so the driver rewrites the phase buffer (two ping-pong buffers) and restarts every frame, with a 25 ms per-frame timeout. Idle pixels hold phase `0xFF`, all-zero in every LUT | 10/16 |
| **Partial refresh, direct mode** (default: `direct_mode = true`) | as above | "Currently, 3-window mode causes some artifacting"; direct mode is offered instead. The CPU looks up each pixel's 2-bit code in the same LUT (word = new level, field = old level), packs 4 pixels per byte into `WIN_MST0`, no mode bits. CPU load keeps it below the panel's 85 Hz | 12/16 |
| **Diff mode** (default on) | LUT and three-window modes; emulated in direct mode | `DSP_CTRL` b29: the hardware ignores the LUT and drives zero for pixels whose value did not change | 11/16 |

- **Concurrency.** Damage rectangles are queued. Areas that do not overlap refresh at the same time, each at its own phase;
  an overlapping area waits for the running one; an area not yet started and fully covered by another is dropped. Buffers:
  Y4 `prev`/`next`/`final` (the last collects updates that arrive while a waveform runs) and two 1-byte-per-pixel phase
  buffers (07/16, 10/16).
- **On the RK3026:**
  - the global-refresh path is what the stock LUT engine does, but the RK3026 has to split it into ≤ 64-frame chunks;
  - three-window mode needs `WIN_MST2`, which the RK3026 does not have [STRONG];
  - direct mode is the same idea as the stock direct and AUTO engines and fits the RK3026 as is (`WIN_MST0` = 2-bpp frame,
    pixel 0 in bits 1:0);
  - diff mode b29 is the bit RK3026 stock sets for PART, A2 and DU; Holland's description ("only changed pixels driven")
    confirms that reading from an independent source [STRONG].

### 5.2 Waveform loading and LUT generation (patches 01/16, 08/16)

- **Format: the panel's own PVI `.wbf`.** The cover letter proposes that the file on disk "should always be what was
  shipped with the panel -- the .wbf file", with any extracting or reformatting done in the kernel. Loaded with
  `request_firmware()` as `rockchip/ebc.wbf` [CONFIRMED].
- **Header:** the same fields and offsets the RK3026 uses (mode version 0x10, `wmta` 0x20, `luts` 0x24, mode count 0x25,
  temperature-range count 0x26, temperature table from 0x30). Pointers are 24-bit with an 8-bit sum, bounds-checked
  against the file size. **The full 24-bit `wmta` is used** (the Rockchip drivers use its low byte). The file-size field is
  checked, the file CRC is not.
- **Mode tables** for MV 0x09, 0x12, 0x16, 0x18/0x20, 0x19/0x43, 0x23, 0x54: the Rockchip tables (§3.5), keyed by waveform
  name (RESET, DU, DU4, GC16, GL16, GLR16, GLD16, A2, GCC16). For 0x19: DU4 → 7, GC16 → 2, A2 → 6, GLR16 → 4, as in RK3026
  `parse_mode_version` [CONFIRMED].
- **Bit depth:** only 5-bit (32-level) files are converted; 4-bit ones (MV 0x09/0x12/0x23/0x54) are refused with
  `-EOPNOTSUPP`. The RC2's MV 0x19 file is 5-bit and would load.
- **Decoder:** the same RLE as above, but it **checks the output length before writing** ("LUT contains too many phases"),
  so it does not have the RK3026 overrun (`decodewaveform_19` checks its limit only after a whole run).
- **Conversion** (`DRM_EPD_LUT_4BIT_PACKED`): the even rows and columns of the 32-level table, 16 × 2 bits per 32-bit word,
  word = new level, field = old level. The packing is the RK3026 hardware format; only the index order is transposed (§3.3).
- **Temperature.** `pvi_wbf_get_temp_index` returns `i − 1` for the first `T < bound[i]`, so at 25 °C on the RC2 file it
  gives range 8, as the RK3026 does. Below the first bound it returns −1, which is refused (`-ENOENT`), and the LUT keeps
  the previous range.
  - Reading the code, the loop runs only up to header byte 0x26, which it treats as the range *count*; the file stores
    count − 1 there (13 on the RC2). So the last range (43–48 °C on the RC2) is never used and a temperature ≥ 43 °C still
    gets range 12 (38–43 °C) [STRONG; not run].
  - The temperature comes from an **IIO channel** (`io-channels`, millidegrees ÷ 1000), read before every refresh. The
    PineNote device tree points it at a TPS65185 node whose binding is marked as still to be written; the PMIC driver is
    **not in this series** [CONFIRMED].
- **When the LUT is rebuilt and loaded:** rebuilt only when the waveform or the temperature range changes; the whole 16 KiB
  SRAM is written when the LUT changed or after runtime resume, with `max_phases = 256`. **On the RK3026 this has to become
  `max_phases = 64` plus chunked reloads**, or the cold-temperature GC16 and INIT waveforms (66–131 phases on the RC2 file)
  are refused.

### 5.3 Register defines against the RK3026

Holland's defines (03/16) are a superset of Rockchip's public RK3566 header (§3.2). They add `DSP_START` b1 `DSP_RST`;
`DSP_CTRL` b26:20 polarity bits (GDOE, GDSP, GDCLK, SDCE, SDOE, SDLE, SDCLK) and b15:0 `DSP_BACKGROUND` (the rychly RK3026
header has `m_SDO_VALUE 0xffff<<0` at the same place [STRONG]); `WIN_CTRL` b13 `AHB_INCR_NUM_REG`; `VNUM` fields; and
`DSP_FRM_INT_NUM` from b12 in `INT`, with the 4-source layout.

`CONFIG_DONE` is written as 1 (RK3026 stock: `0xFFFF`). `DSP_CTRL` gets swap mode 3 and SDCLK divider 3 for an 8-bit bus, the
same as the RK3026 stock `0xC0030000`. He leaves b27 `VCOM_MODE` clear; the RK3026 sets it for middle chunks (meaning
[VERIFY]).

What the RK3026 lacks: `WIN_MST2`/`VNUM` and three-window mode, the 8-bit frame count (6 bits), the 16 KiB LUT SRAM
(4 KiB), and the 4-source `INT` layout (display-end clear is b7, not b9). Unknown on the RK3026: `DSP_RST`, the polarity
bits, `OUT_LOW` [VERIFY].

**Timings** (05/16) are derived from a `drm_display_mode`: horizontal values divided by 4 pixels per SDCLK (8 for a 16-bit
bus, flagged with `DRM_MODE_FLAG_CLKDIV2`), the gate-clock position carried in `hskew`, `SDCE_WIDTH` = active width in
SDCLK. That is the same arithmetic as the RK3026 `ebc_panel_scan_set` / `ebc_win_dsp_set`; the RK3026 stock puts width/4 in
`EPD_CTRL` b15:8 instead of `DSP_START` b25:16 [GUESS].

### 5.4 Userspace interface

- **KMS:** one CRTC, one primary plane, an encoder and a bridge to a `drm_panel` through the OF graph;
  `drm_simple_display_pipe` is not used, so planes can be added later. **XRGB8888 only**, converted to Y4 in software
  ((2R + 5G + B) / 8, rounded). FB damage clips and fbdev emulation.
- **Waveform selection: none from userspace.** Module parameters `default_waveform` (GC16), `diff_mode`, `direct_mode`,
  `skip_reset` and `panel_reflection` (the PineNote panel is mirrored). The cover letter asks whether waveforms should be a
  plane property, possibly one plane per waveform with software blending.
- **VBLANK:** the event completes when the pixels are copied into the shadow buffer (`drm_atomic_helper_fake_vblank`), not
  when the panel is done.
- **Power:** runtime PM with 2 s autosuspend; the `panel`, `vcom` and `vdrive` regulators are consumed by the EBC node, not the
  panel, because they must be on only during refreshes.

### 5.5 Review and fate

Reviewers: Maxime Ripard, Andreas Kemnade, Nicolas Frattaroli, Daniel Vetter (April to June 2022).
- *Power:* reuse the panel-self-refresh (PSR) infrastructure, so the backlight goes with prepare and the regulators with PSR
  entry/exit (Ripard).
- *Timings:* reusing `drm_display_mode` is fine if the parameters can be derived both ways (Ripard); horizontal panel
  timings should be in pixels, and the existing panel-simple EPD entry that uses clock cycles should be fixed (Vetter).
- *Reflection:* model it like `drm_panel_orientation` with `DRM_MODE_REFLECT_X` (Ripard).
- *CRTC disable:* the panel is expected to be blank; a "keep the image" mode is out of scope (Ripard).
- *VBLANK:* for hardware without vblank, the event should fire when the refresh or upload is done, with frame count 0
  (Vetter).
- *Waveform file:* name it after the panel compatible, found through the OF graph (Ripard, who is uneasy with parsing in the
  kernel "from a file you have no control over"); putting the right file into the firmware directory is the best available
  (Vetter).
- *Waveform selection:* "the current consensus is that it's up to userspace" (Ripard); a single plane means a single
  waveform choice.
- *Software conversion:* XRGB8888 to grey in the kernel is accepted reluctantly; RGA or dithering belong in a V4L2
  mem2mem device set up by userspace, not hidden in KMS (Vetter).
- *EPDs on plain LCD TCONs* must not be exposed as ordinary KMS connectors if wrong data can damage the panel; applying the
  waveform in the kernel is tolerated for those (Ripard, Vetter).
- *Device tree* (Kemnade): use the existing SY7636A driver's temperature (hwmon/thermal) instead of `io-channels`; the
  supplies belong to the panel, and not all can be required. Holland agreed that "the consensus is to use a thermal zone for
  panel temperature", referenced by phandle, with the regulators in a panel node and a custom panel driver.

**Fate:** no v2 was posted. A lore search for his messages with "ebc" in the subject lists only the RFC v1 patches and his
reply of 2022-04-15; the last message in the thread is from 2022-06-08; nothing is in mainline [STRONG. A renamed later
series, or work kept in his own tree, cannot be excluded: VERIFY].

## 6. Andreas Kemnade's i.MX6 EPDC RFC (February 2022)

`drivers/gpu/drm/mxc-epdc/` (about 3 kLOC), "based on the EPDC framebuffer driver" by Freescale/NXP, for i.MX6SL and
i.MX6SLL (Kobo Clara HD, Tolino Shine 2HD/3), to be paired with an EPD PMIC driver (TPS65185 or SY7636A).

- **Hardware model, very different from the Rockchip EBC:** a 16-bpp working buffer (old and new state per pixel), up to 64
  hardware LUTs running at the same time on separate update rectangles, collision detection and interrupts per LUT. The
  auto-waveform table (`EPDC_AUTOWV_LUT`) lets the **hardware choose** DU/GC4/GC8/GC16/GC32 per update
  (`WAVEFORM_MODE_AUTO`). The controller decodes the waveform from the loaded buffer.
- **Waveform file:** `request_firmware("imx/epdc/epdc.fw")`, NXP's pre-converted format: a WBF-like header (`wi0..6`, `xwia`,
  `wmta`, `trc`, …), then the temperature table and the waveform data, copied into a DMA buffer for the hardware. It is
  **not** the panel's raw `.wbf`; Holland's cover letter calls it ".wrf … containing multiple waveforms". Mode numbers are
  fixed in the driver (init 0, DU 1, GC16 2, GC4 3). A reviewer (Neuschäfer) asked how several waveform files would be named.
- **Temperature:** a thermal zone looked up **by name** (`epd-thermal-zone = "epd-thermal"`), millidegrees ÷ 1000, default
  20 °C. The range is chosen as `bound[i] ≤ T < bound[i+1]` from `trc + 1` entries, the same convention as the RK3026 and
  Holland; out-of-range values clamp to the first or last range.
- **Userspace interface:** `drm_simple_display_pipe`, XRGB8888 only (grey = (3R + 6G + B) / 10; on some waveforms reduced
  levels "found by experimentation"), damage clips → hardware update rectangles, partial updates with
  `WAVEFORM_MODE_AUTO`. "It does not provide any special userspace API to fine-tune updates. That is also IMHO something for
  a second step." The PXP (rotation and NXP's waveform pre-processing) is not used.
- **Timings:** all EPD timing parameters (`vscan-holdoff`, `sdoed-*`, `gdclk-*`, `num-ce`, plus a `timing` node) are in the
  **controller** node, as in the vendor kernel.
- **Review:** Rob Herring asked whether it is compatible with the i.MX50 EPDC (if differences are probed from
  `EPDC_VERSION`, one `fsl,imx-epdc` compatible is enough). Krzysztof Kozlowski: lower-case supply names, `epd-controller`
  as the node name, the thermal zone typed as a string. Jonathan Neuschäfer: defaults for the timing parameters or a separate
  panel node, store the raw `EPDC_VERSION`, document the modes; Kemnade answered that vendor kernels have no sane defaults and
  keep a parameter set per display. The thread ends on 2022-03-14; later versions were not checked [VERIFY].

**Compared with Holland:**

| | Kemnade | Holland |
|---|---|---|
| shared code | none; no common helper | — |
| waveform file | pre-converted `.fw` | the raw `.wbf`, parsed by his helper |
| waveform choice | the hardware (`AUTO`) | a fixed module parameter |
| timings | the controller node | a `drm_panel` |
| temperature | thermal zone by name | IIO, then agreed to move to a thermal zone |
| userspace waveform API | none | none |
| concurrent rectangles | hardware LUTs | software scheduling of areas |

Holland's cover letter credits Kemnade's series, and Kemnade reviewed Holland's binding. Open questions shared by both:
timings in a panel node or in the controller node, PMIC temperature and supplies, waveform file naming, and userspace
waveform selection.

## 7. Kindle Paperwhite 3 (Amazon's GPL kernel)

The public parts are already written up: how the driver splits the work in
[`new-driver.md` §3.3](new-driver.md#33-the-kindle-approach-amazons-gpl-kernel); timings, logic level, power and VCOM in
[onyx-rc2-hardware `panel/README.md`](https://github.com/hsw/onyx-rc2-hardware/blob/main/panel/README.md); the panel flash
layout in [onyx-rc2-hardware `panel-flash/README.md`](https://github.com/hsw/onyx-rc2-hardware/blob/main/panel-flash/README.md#same-format-in-the-kindle-paperwhite-3);
the WBF header fields, voltage-control blocks and its temperature lookup in
[onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform#how-the-stock-rk3026-kernel-uses-this-file). For the matrix
[CONFIRMED-src unless marked]:

- **Controller:** the i.MX6 SoloLite EPDC, the same controller family as Kemnade's RFC: hardware LUTs, update rectangles,
  per-LUT interrupts.
- **Waveform:** the kernel parses no waveform streams. It reads only the WBF header, the panel name and the voltage-control
  data, and drives the panel from pre-converted per-mode tables `imx/epdc_<mode>.fw` loaded with `request_firmware()`. The
  firmware file is gunzipped by the kernel (`mxc_epdc_fb.c:5646`) and is named after the video mode (`5793-5808`). The
  converter is userspace and not in the GPL release. The mode table for mode version 0x19 (= 25 decimal, the kernel's
  `panel_mode_25`) is the RC2's: init 0, du 1, gc16 2, gl16 3, reagl 4, reagld 5, a2 6, du4 7
  (`mxc_epdc_fb_lab126.c:91-92`, `1029-1042`, `2522-2524`). The REAGL pixel code is not in the release (`mxc_epdc_fb.c:6620-6630`
  only references it).
- **Mode choice:** userspace per update, or AUTO (`WAVEFORM_MODE_AUTO` = 257, `include/linux/mxcfb.h:100`), where the PxP
  histogram status picks the caller's preferred black/white mode (default DU) if the content is black/white only and the
  preferred grey mode (default GC16) otherwise (`mxc_epdc_fb.c:4678-4690`, `3696-3708`).
- **Temperature:** the panel's NTC through the MAX77696 ADC, about once a minute, default 25 °C. Its range lookup keeps one
  lower bound per range and stops one index early, so the hottest range is never used; below the table it uses range 0.
- **Timings:** in the board file, chosen by the first three characters of the panel's barcode.
- **Power:** one regulator for the rails, a wait for PWR_GOOD on an interrupt with a 250 ms timeout, VCOM as a separate
  regulator enabled only after PWR_GOOD; on a fault off, 1 ms, on again; a power-down delay settable from userspace keeps the
  rails up between close updates.
- **Completion:** the i.MX `mxcfb` framebuffer UAPI. `MXCFB_WAIT_FOR_UPDATE_COMPLETE` is `_IOWR('F', 0x2F, struct
  mxcfb_update_marker_data)` (`include/linux/mxcfb.h:204`; the struct is `{update_marker, collision_test}`, `150-153`);
  `MXCFB_SEND_UPDATE` is `_IOW('F', 0x2E, struct mxcfb_update_data)` (`203`) with `update_region`, `waveform_mode`,
  `update_mode` (0 partial, 1 full), `update_marker`, the two Amazon histogram modes, `temp`, `flags`, `alt_buffer_data`
  (`138-148`). The handler reads only the first 32 bits of the argument, the marker (`mxc_epdc_fb.c:4253-4261`), so
  `collision_test` is never written back (the assignment is commented out, `4085`). Marker 0 is invalid (`-EINVAL`,
  `4044-4046`); an unknown marker returns 0 at once (already finished); the wait is `wait_for_completion_timeout` of
  5000 ms, `-ETIMEDOUT` after that (`4077-4083`). The completion is signalled from the interrupt handler once the
  update's LUT-complete bit is set and all LUTs of that marker are done (`4895-4928`; the dry-run path `5015-5040`, the
  write-back path `5310-5330`), so it means "the waveform has been driven to the panel", not "queued": the earlier event is
  `MXCFB_WAIT_FOR_UPDATE_SUBMISSION` (`_IOW('F', 0x37, __u32)`, `mxcfb.h:214`; signalled when the update has reached the
  working buffer, `mxc_epdc_fb.c:5286-5300`). A marker is only tracked when non-zero (`3807`). `EPDC_FLAG_TEST_COLLISION`
  (`mxcfb.h:111`) makes a dry-run update that takes no LUT (`mxc_epdc_fb.c:3218`).

## 8. RK3128 (ONYX, kernel 3.10)

ONYX's RK3128 BOOX firmware (Android 4.4, kernel 3.10.0) carries a driver whose register layer (`rk3128_ebc_*`, `ebc_*_set`) is
the RK3026 stock driver ported with almost no change, with a different frame engine on top (`onyx,sepdc`, a software EPDC).
Analysed: Livingstone (`#738`, 2022-08) in full, Darwin 7 (`#71`, 2022-01) for the differences; sources in the list at the top.

**Conclusion: the RK3128 EBC is the same IP generation as the RK3026's.** [CONFIRMED-dis] for the register side:
- The device tree node `ebc@10114000` (`rockchip,rk3128-ebc`) maps the same 16 KiB window as the RK3026, with IRQ `GIC_SPI 49`
  (the RK3026's Linux IRQ 81), clocks `aclk_ebc`, `hclk_ebc`, `dclk_ebc`, power domain `pd_ebc`, and a second resource at
  `0x20038150` named `ebc_lvds_ctrl` (the `GRF_LVDS_CON0` register that gates the EBC data lines on the RK3026, at GRF
  `0x…8150` there; the base differs in the node, the offset 0x150 matches; [VERIFY] which block `0x20038000` is).
  The driver sets `GRF_LVDS_CON0` bit 0 (value `0xffff0381` in the write-mask format) when it enables the output.
- Writers of the window: `ebc_panel_scan_set` writes `DSP_HTIMING0/1`, `DSP_VTIMING0/1`, `DSP_ACT_INFO` (0x0C–0x1C) with the
  RK3026 sums of hsync, start, end, gdck_sta and lgonl; `ebc_win_dsp_set` writes `WIN_CTRL` = `0x20FC0 | fmt` (the same constant
  as the RK3026, [`registers.md` §3.4](registers.md)), `WIN_VIR`, `WIN_ACT`, `WIN_DSP` and `WIN_DSP_ST` = hsync+hstart+1 /
  vstart+4; `ebc_border_set` zeroes `VCOM0–3`; `ebc_image_addr_set` writes `WIN_MST0/1`; each ends with `CONFIG_DONE` = 1. The
  function names are the RK3026's.
- The ISR (`rk3128_ebc_isr`) sets the three clear bits 6, 7, 8 of `INT` (0x3C), masks the done source (bit 4), calls the
  callback when status bit 1 is set, unmasks, writes `CONFIG_DONE`: the RK3026 layout (status 2:0, mask 5:3, clear 8:6).
- The panel is the same: `eink-timings` in the DTB says `ED060KD1`, 1448×1072, SDCLK 40 MHz, `hsync_len` 17, margins 8/55/4/4,
  `vsync_len` 2, `gdck_sta` 100, `lgonl` 281, the constants of [`registers.md` §3](registers.md). The same `dclk_ebc` is
  set to 4 × SDCLK.
- Mainline already knows the RK3128 EBC clocks and bus QoS but no controller node: `clk-rk3128.c` has `DCLK_EBC` (line 337)
  and `HCLK_EBC` (473); `rk3128.dtsi` lists both in a power domain (lines 218–235) and has `qos_ebc: qos@1012f080` (365),
  the same address as the `cpu_axi_bus/qos/ebc` node in the ONYX DTB. RK3036 has no EBC at all (no mention in the mainline
  clock driver or dtsi).

**Differences from the RK3026 driver** (all in the layer above the registers, or in what is not written):
- **Direct mode only.** One `rk3128_ebc_update(addr)` = `WIN_MST0` := frame, `DSP_START` := 1 (frame count 0), `INT` start
  pattern, `CONFIG_DONE`. The 4 KB LUT SRAM at +0x1000 is never written (only a debug register dump reads it), `WIN_MST1`
  never. So the RK3026's LUT modes have no counterpart; every waveform frame is built by the CPU (`onyx_get_waveform_one_frame_*`,
  8/16-bit and rect/segment variants, NEON helpers), which is what the RK3026 does for its own direct modes 9, 11, 12 and AUTO.
  Whether the hardware has the LUT SRAM on RK3128 is therefore [VERIFY]; it is simply not used.
- **`DSP_CTRL` = `0x00030000`** from `ebc_dsp_ctl_set(0,0,0)`: the SDCLK divider 3 as on the RK3026, but swap bits 31:30 = 0 and
  bit 27 = 0, where the RK3026 direct mode writes `0xC8030000`. The CPU's frame packing may differ, or the bits mean something
  else on this chip [VERIFY].
- **`EPD_CTRL` (0x04) is not written** by any function that touches the window (the writer list is complete: the xrefs to the
  driver pointer are probe, enable/disable, `func_enable`, `set_panle_timing`, `update`, `output_ebc`); the RK3026 writes
  `0xA98EFF03` at probe. The value either comes from the boot loader's display initialisation (`support_uboot_display` is
  consulted at probe) or from reset [VERIFY]. A register dump on a RK3128 device would settle it.
- **`CONFIG_DONE` (0x50) is written with 1**, in every writer (`ebc_panel_scan_set`, `ebc_win_dsp_set`, `ebc_dsp_ctl_set`, `ebc_image_addr_set`, `update`, ISR); the RK3026 writes `0xFFFF`. Probably only bit 0 matters [VERIFY].
- **Software EPDC (`onyx,sepdc`)**: an i.MX-style update model on top of the direct frames: 128 software LUT slots, update
  merging (`onyx_epdc_merge_upd`, `epdc_submit_merge`), collision masks per update, per-update **magic** values,
  region/4-bit/5-bit conversion (`epdc_update_region_cal_*`, `onyx_epdc_wb_convert`), a frame task that builds one frame at a
  time (`epdc_refresh_waveform_task`) and a semaphore the EBC ISR releases per displayed frame. Its userspace interface is
  `/dev/ebc` ioctl 0x7000 + n (34 commands in Livingstone, 31 in Darwin 7), driver version string
  `ONYX_EBC_DRIVER_VERSION_2.00`; not the RK3026's ioctl set (0x7000–0x7004).
- **Waveform**: the E Ink file is parsed as PVI/WBF or as an i.MX-style converted file (`waveform_file_format`), requested as
  firmware `waveform.wbf` from `/vendor/waveform/` with the fallback file `/waveform/eink_waveform.wbf`; the RK3026 reads
  `/ebc_waveform.bin`. The kernel maps its update-mode number to the file's mode index through a table keyed by the WBF type
  byte, and builds extra Regal ("REGAL") and GLR16/GLD16 variants at load time (`onyx_convert_waveform_data_pvi`).
- **Temperature**: the same TPS65185 ADC (regulator `TMST`), but the value reaches the update path through a setter
  (`onyx_epdc_set_temp`), not a read on every update inside the EBC code [VERIFY who calls it].
- **Panel timings and the PMIC are in the device tree** (`eink-timings`, `tps6518x@68`), where the RK3026 compiles the panel
  table into the kernel.

**Darwin 7 → Livingstone (5 months).** The register layer is byte-identical apart from one argument position of
`rk3128_ebc_update`. Darwin 7 is a framebuffer-style driver: `fb_ops` with `ioctl`/`write`, `dpy_update`, a work-queue per
update (`onyx_epdc_submit_work_func`, `update_wb_work_func`), per-pixel LUT collision tests (`onyx_lut_is_collision*`). Livingstone
replaces that with a message queue (`epdc_msg_*`), a waveform-buffer queue and a producer/consumer split (`epdc_refresh_waveform_task`,
`onyx_epdc_produce_wf_segment`, `_sg` scatter variants), block and 4/5-bit region calculation, a Regal pass, a splash-memory
handover, `onyx_epdc_wait_all_update_compelete`, `onyx_epdc_parse_dt` and `waveform_desc` lists, and 3 more ioctls. The panel
node and the PMIC node in the two DTBs are identical.

**What it means for one mainline driver.** The register block, the interrupt scheme, the window/stride registers, the 40 MHz
SDCLK/GRF gate and the panel are the same on RK3026 and RK3128, so one controller driver can serve both with one compatible
string per SoC and the RK3026's [`registers.md`](registers.md) as its register description; the differences are the SoC glue
(clock names, power domain, `GRF` block) and, at most, the unwritten registers above. The RK3026's LUT engine is optional:
ONYX's RK3128 driver gets by with direct frames only, as Rockchip's RK3566 vendor driver and Holland's RFC (for partial
updates) also do, so a first mainline driver can use direct frames only on both chips. What differs is above the controller:
ONYX adds its own software EPDC and ioctl ABI, which a mainline driver would not follow. The RK3566's register differences
(§3.2) are still the dividing line between this IP family and its successor.

### 8.1 Storytel Reader: a further RK3128 sample (gen 2) and an RK3026 sample (gen 1)

The Storytel Reader (ONYX hardware, sold by Storytel) comes in two generations, both with boot logs in the project above.

**Gen 2: RK3128, Android 6, kernel 3.10.104.** The `boot.img` of the release is an ANDROID! image with kernel (LZO zImage, 16 348 896 B
Image), ramdisk and an RSCE `second` with the DTB. The README says only the ramdisk is patched (`mods/gen2/01.patch`, magisk files);
the kernel is the original one. Its banner is `3.10.104 (vinicius@…) #1 SMP PREEMPT Wed Feb 15 11:11:51 UTC 2023`, i.e. not an ONYX
Jenkins build: Storytel (or its contractor) built it from ONYX's tree. Symbols from kallsyms (94 037), disassembly with llvm-objdump
(GNU objdump misdecodes some instructions in these ELFs).
- **Generation: the Darwin 7 one, older than Livingstone.** [CONFIRMED-dis] Version string `K29_EBC_DRIVER_VERSION_1.00` (Darwin 7
  has the same, Livingstone `ONYX_EBC_DRIVER_VERSION_2.00`). The `rk3128_ebc_*`/`ebc_*`/`onyx_*`/`epdc_*` symbol set equals Darwin 7's
  except seven names; what gen 2 lacks are device extras (vibrator, key control, battery `cc`/`rdc` counters, RGB-to-YUV helper). It has
  the framebuffer-style engine (`onyx_epdc_fb_ioctl/write/dpy_update`, `onyx_epdc_submit_work_func`, `onyx_lut_is_collision*`), none of
  Livingstone's `epdc_msg_*` / waveform-buffer queue / Regal pass. `epdc_ioctl` is a 28-entry jump table (0x7000–0x701B) plus an
  `ebc_io_ctl_hook` and the Rockchip-style `ebc_buf_*` list (`ebc_empty_buf_get`, `ebc_dsp_buf_get`, two buffers of 200 704 B).
- **Register layer: identical to Livingstone and Darwin 7.** [CONFIRMED-dis] `ebc_border_set` and `ebc_image_addr_set` are
  instruction-identical; `ebc_dsp_ctl_set`, `ebc_win_dsp_set`, `ebc_panel_scan_set` (same sizes 80/160/232 B), `rk3128_ebc_isr` (176 B)
  and `rk3128_ebc_set_panle_timing` differ only in branch targets, literal-pool addresses and the driver-struct field offsets
  (ISR 0x104 against 0xf4). `rk3128_ebc_update` writes `WIN_MST0`, `DSP_START` = 1, `INT` (clear 0xfe00/0xf8, set 0x28) and
  `CONFIG_DONE` = 1 as in §8, and has a one-shot register dump behind a debug flag. No write to `LUT` (+0x1000), `WIN_MST1` or `EPD_CTRL`.
- **Direct mode.** [CONFIRMED-log] `waveform_file_format` and `color_panel`/`half_empty` absent from the DT default to 0
  (`get waveform_file_format failed! set default val 0!`), and the PVI/WBF parser runs (`onyx_waveform_parse_pvi`).
- **Waveform.** [CONFIRMED-log] firmware request `/vendor/waveform/waveform.wbf` fails ("fail to open"), then
  `request_firmware_nowait [/waveform/eink_waveform.wbf]`, 296 408 B; header name `320_R083_ABB401_ED060XCDU2_TC`, frame rate 85 Hz,
  `waveform_lookup_table_fmt` = 4, `mode_num` = 8, `temp_num` = 14, 32 gray levels (5-bit file, `is_5bit_to_4bit` = 0); two extra
  modes are converted (`waveform_mode_index` 4 and 5, GLR16 index 7). Parsing takes about 0.14 s.
- **Panel: a different one.** [CONFIRMED-log] `eink-timings` in the DTB: `ED060XH7`, 1024×758, `panel_width` 8, SDCLK 20 MHz, margins
  6/38/4/5, `hsync_len` 6, `vsync_len` 2, `gdck_sta` 4, `lgonl` 0x106 (262), frame rate 85. `dclk_ebc` is read back as 80 MHz = 4 × SDCLK, as
  on the RC2. The window registers follow: `WIN_VIR` = 0x400, `WIN_ACT` = `WIN_DSP` = `DSP_ACT_INFO` = 0x02F60400 (758 << 16 | 1024),
  `WIN_CTRL` = 0x20FC0. So the register constants of §8 are not panel-specific; only the timing inputs change.
- **Device tree.** [CONFIRMED-dis] `ebc@10114000` `rockchip,rk3128-ebc`, reg `0x10114000/0x4000` and `0x20038150/4` (`ebc_lvds_ctrl`), IRQ
  SPI 49, clocks `aclk_ebc`, `dclk_ebc`, `hclk_ebc`, `pd_ebc`, `sclk_pll`; `tps6518x@68` (`TI,tps6518x`: `pwr_seq0/1/2` 0xe1/0x30/0x33,
  `upseq0` 0xe4, `dwnseq0` 0x1e, `max_wait` 24, `delay_3v3_highv` 3, VCOM-control and wakeup GPIOs; no PWRGOOD, INT or V3P3 pin); `sepdc`
  (`onyx,sepdc`); QoS node `ebc@1012f080`, priority 3/3.
- **PMIC and temperature.** [CONFIRMED-log] TPS6518x rev ID 0x66 (a TPS65185-family part; the log also prints `ERROR TPS6518x waiting for power
  good!` once, because the DT has no PWRGOOD pin), I2C 2-0068, `tps6518x_sensor_probe`; the temperature reaches the update path as
  `onyx_epdc_set_temp(): temp val = 24`. [CONFIRMED-dis] the only direct caller of `onyx_epdc_set_temp` is `onyx_epdc_draw_mode0`.
- **Completion.** [CONFIRMED-dis] `rk3128_ebc_set_isr_callback` stores a pointer at struct offset 0x104, which `rk3128_ebc_isr` calls (no direct `bl` to the setter: it is reached through an ops table); `onyx_epdc_EBC_isr_callback` is the EPDC-side function; the EBC part of the
  driver comes up as `onyx_epdc_EBC_init` → `ebc_panel_scan_set`, `ebc_win_dsp_set`, `ebc_dsp_ctl_set`, `rk3128_ebc_set_panle_timing`.
- **A real register dump** from a running RK3128 (`rk3128_ebc_reg_dump`, taken inside the first update). [CONFIRMED-log]
  `0x00` = 0, **`0x04` (EPD_CTRL) = 0x00D76400**, `0x08` = 0x30000, `0x0C` = 0x01320006, `0x10` = 0x010C000C, `0x14` = 0x03010002,
  `0x18` = 0x02FC0006, `0x1C` = 0x02F60400, `0x20` = 0x20FC0, `0x24` = frame address, `0x28` (WIN_MST1) = 0x63B78BA0 (stale, never written),
  `0x2C` = 0x400, `0x30` = `0x34` = 0x02F60400, `0x38` = 0x0006000D, `0x3C` = 0x28, `0x50` = 0 (reads 0 after the driver wrote 1),
  `0x1000` = 0. GRF `LVDS_CON0` reads 0x381 before and after the driver's write.
- **Boot facts.** [CONFIRMED-log] two probes use the same region: `rk31xx-lvds 20038000.lvds` claims `0x20038000–0x2003BFFF`, so the EBC
  driver's request for `0x20038150–53` fails with "can't request region … ioremap ebc-lvds ctrl reg failed", yet the probe reports success
  and `rk31xx_output_ebc` reads and writes `RK312X_GRF_LVDS_CON0` (so the access goes another way). The RK3128 therefore has the EBC data-line
  gate in the LVDS block at `0x20038000` + 0x150.

**Gen 1: RK3026, Android 4.2, kernel 3.0.36+ (`jenkins@jim-hp-workstation-15`, `#1` Wed Aug 8 18:38:56 CST 2018).**
- **No kernel in the image.** `boot-gen1-patched.img` is a `KRNL` container around a 1 773 648-byte gzip cpio ramdisk (42 entries): the
  kernel is in the separate `kernel` partition (8 MiB at sector 0x4000; `boot` is at 0x8000, `mtdparts` in `dumps/gen1/params`). The
  release therefore gives no kernel to compare; the boot log is all there is.
- **Same machine, older EBC driver.** [CONFIRMED-log] banner `[RK_EPD]: version 1.02 20141016` (same as the RC2 kernel) but
  **`V1.0.11 VERSION 20170418`**, where the RC2 kernel (2017-11-07) prints `V1.0.20 VERSION 20171023-23`. So the EBC span is **not** the
  RC2's although the kernel is 9 months younger: the Storytel kernel carries an older EBC branch. Not comparable symbol by symbol.
- Memory reserved (`ebc waveform buf` 1 MiB at 0x7FF00000, `ebc disp buf` 8 MiB at 0x7F700000, `fb0 buf` 9 MiB at 0x7EE00000);
  `waveform_addr=0x7ff00000` on the command line and `get_ebc_waveform_addr`; the log prints `epd_lut_from_nand_init` waveform info
  `bf 24 4c 7a` and `spi_id_buffer = 320_G108_AB1F01_ED060XC9T1_TCx`, then `get lut from file sucesss`; modes are chosen as `eink mode = 5` / `3`, with
  `epd_lut_data_get_pvi_hard 5/6` (the RK3026 LUT-from-PVI path). The panel is an ED060XC9 (also a 1024×758 6" panel), not the RC2's.
- PMIC `tps65185_probe` I2C 0x68, `papyrus: detected device with ID=65 (TPS65185r1p2)`, VCOM read back 211 mV (the code then prints
  `panel_get_id unknown vcom value … default to -1.80V`, vcom -2200). Other ONYX facts: `pcb version [V1.73]`, battery fuel gauge `cw_*`.
- **Ramdisk files.** `ebc_waveform.bin` (251 165 B, sha256 `efdee319…56ca`, header name `320_G108_AB1F01_ED060XC9T1_TCx`) differs from the RC2's;
  `rk30xxnand_ko.ko.3.0.36+` (181 130 B, sha256 `de80b9c1…b287`) is **byte-identical** to the RC2's.

**[VERIFY] items of §8 against this data.**
- `0x20038000` block: closed, the RK3128 LVDS controller (`rk31xx-lvds 20038000.lvds`, `RK312X_GRF_LVDS_CON0` at +0x150) [CONFIRMED-log].
- `waveform_file_format` default: closed, 0 [CONFIRMED-log]. Second RK3128 device with the identical register layer: [CONFIRMED-dis].
- `EPD_CTRL` source: the driver does not write it (dis, also in this kernel) and a running device holds `0x00D76400`, not the RK3026's
  `0xA98EFF03` and not that formula's result for this panel (b15:8 would be 255, b26:16 would be 272) [CONFIRMED-log]. It is therefore reset
  or loader state; the bit meaning on RK3128 stays open.
- `CONFIG_DONE` value: reads 0 after a write of 1 (and the start bit `DSP_START` reads 0): a strobe, bit 0 is enough in practice [STRONG].
- Temperature setter caller: one direct caller, `onyx_epdc_draw_mode0`; further callers through pointers are not excluded [STRONG].
- LUT SRAM at +0x1000: reads 0 on a running device, never written; still [VERIFY] (a zero read does not show that RAM is there).
- `DSP_CTRL` = 0x00030000 swap/bit 27: the running value is the same 0x30000 here; the meaning of the swap bits is still [VERIFY]
  (the RK3128 direct mode needs different packing, or the bits are unused).
- Still open: the RK3128 `INT` mask value 0x28 matches the RK3026; `0x38` = 0x6000D has no counterpart in the RK3026 register table.

## 9. Not analysed

IT8951 (E Ink's USB/SPI timing controller), the MediaTek EPD controllers of newer Kobo devices, and Allwinner's EINK
engine were not read for this page.

## 10. Reproduce

```sh
# RK3128 (ONYX): decrypt update.upx with the key list above, take the kernel out of boot.img (LZO zImage), then
# vmlinux-to-elf for the symbols, objdump -d for the functions named in §8, dtc/libfdt for rk-kernel.dtb
# RK3566 decompile (read only)
git clone https://github.com/Ralim/ebc-dev-reverse-engineering && git -C ebc-dev-reverse-engineering checkout 1a089fc
# Rockchip vendor driver: C glue and the generated assembly
git clone --filter=blob:none --no-checkout https://github.com/rockchip-linux/kernel rockchip-kernel
git -C rockchip-kernel show f39b590:drivers/gpu/drm/rockchip/ebc-dev/tcon/ebc_tcon.c | \
    diff -w - ebc-dev-reverse-engineering/done/tcon/ebc_tcon.c
git -C rockchip-kernel show f39b590:drivers/gpu/drm/rockchip/ebc-dev/epdlut/pvi_waveform_v8.S > pvi_waveform_v8.S
# the two RFC threads as mbox files
curl -L -o holland-ebc-rfc.mbox.gz https://lore.kernel.org/all/20220413221916.50995-1-samuel@sholland.org/t.mbox.gz
curl -L -o kemnade-epdc-rfc.mbox.gz https://lore.kernel.org/all/20220206080016.796556-1-andreas@kemnade.info/t.mbox.gz
# RK3026 side, with the tools of this repository (see the top README for the kernel)
for fn in ebc_panel_scan_set ebc_win_dsp_set ebc_dsp_ctl_set _ebc_frame_start rk29_ebc_irq get_lut_temp; do
    python3 -I driver/tools/kdis.py Image kallsyms.txt "$fn"; done
```
