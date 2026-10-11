# RK3026 EBC registers: a checked reference

A register reference for anyone writing a new RK3026 EBC driver. It refines the short table in [`README.md`](README.md) §4.5 with
what the stock RC2 kernel **actually writes**, a register readback on the device, and a comparison with the public headers and
with the later RK3566 controller. Where this page and §4.5 differ, this page is newer. Behaviour is described in our own words;
no vendor code is reproduced.

Sources:
- **Stock**: the RC2 kernel Image (2017-11-07; addresses as in the rest of this repository). Every access through the driver's
  register pointer in all 203 EBC functions was enumerated. **Writers:** `ebc_panel_scan_set` 0xc060b2a4, `ebc_win_dsp_set`
  0xc060b394, `ebc_border_set` 0xc060b430, `ebc_dsp_ctl_set` 0xc060b46c, `ebc_image_addr_set` 0xc060b4a0, `_ebc_frame_start`
  0xc060b504, `ebc_frame_start` 0xc060cd0c, `ebc_auto_tast_function`, `rk29_ebc_irq` 0xc060e0f4, `rk29_ebc_probe` (EPD_CTRL), the
  dead `rk29_ebc_set_gdpwr0` 0xc0610764. **Hardware reads: only two**, `INT` in the interrupt handler and `WIN_MST0` in the
  direct-mode ping-pong (0xc060cb5c); everything else is kept in a shadow copy.
- **`.uu`**: the older driver generation in [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources)
  (`drivers/video/rockchip/rk_epd/`), disassembled: it writes the same constants.
- **Headers**: rychly `rk_epd/ebc.h` and ridi `rk_epd/hardware_ebc.h`. They are **the same text** reformatted, so their agreement
  confirms nothing.
- **RK3566**: Rockchip's `drivers/gpu/drm/rockchip/ebc-dev/tcon/ebc_tcon.c` (GPL-2.0, rockchip-linux kernel): a later controller
  of the same line.
- **DS**: `RK302X_datasheet_V1.2` (feature list only).
- **Device**: a read-only dump of 0x00–0x50 on the running RC2 (2026-10-11), display idle after a partial update, plus
  `/proc/iomem`, `/proc/interrupts`, panel tests.

Marks: [CONFIRMED-dis] read in the stock listing (address given); [CONFIRMED-emu] stock function run in Unicorn; [CONFIRMED-device]
seen on the RC2; [CONFIRMED-src] written in a public source; [STRONG] inferred from several facts; [VERIFY] / [GUESS] open.

## 1. Summary

- **The 0x00–0x50 map of the public header is right by offsets and names** (21 registers, base 0x10114000, 16 KiB window,
  Linux IRQ 81 = `GIC_SPI 49`). What it does not say: the **LUT SRAM at +0x1000**, which interrupt bit means "done", and the
  write order.
- **`WIN_CTRL`: the masks (`m_*`) are right, the value constructors (`v_*`) are shifted by one bit.** Both driver generations
  write the constant `0x20FC0 | fmt`; read with the masks, every set bit means something (§3.4).
- **`INT` has three sources**: status bits 2:0, masks 5:3, clears 8:6. "Update done" is **status bit 1, cleared by bit 7**,
  masked by bit 4. The RK3566 layout (four sources, clear at bit 9) does **not** apply.
- **`DSP_START`**: bit 0 start, **bits 7:2 = frames − 1 (6 bits, at most 64 frames per start)**. The LUT SRAM is 64 frames × 16
  words = 4 KB at +0x1000..+0x1FFF; longer waveforms go in 64-frame chunks reloaded from the interrupt. The datasheet's
  "128 frames, 8 KB" is unconfirmed (§4).
- **On the device every predicted value read back as predicted**, except `WIN_VIR` bits 31:16 (read 0).
- **Outside the window:** the EBC data lines reach the panel only when **`GRF_LVDS_CON0` bit 0** is set (§5).

## 2. The window 0x10114000–0x10117FFF

| Offset | What | Who touches it | Mark |
|---|---|---|---|
| 0x000–0x050 | 21 registers (§3) | stock | CONFIRMED-dis |
| 0x054–0xFFF | nothing. RK3566 has `VNUM` at 0x54 and `WIN_MST2` at 0x58 (three-window mode); the RK3026 header and code have neither | nobody | VERIFY; not needed |
| **0x1000–0x1FFF** | **LUT SRAM**: 1024 words = 64 frames × 16 words (one word per old level, 2 bits per new level). Write-only from the driver's point of view: `ebc_frame_start` copies a full chunk (0xc060d0b0–0xc060d0c4) or the last n·16 words (0xc060d174–0xc060d190) and never reads back | stock | CONFIRMED-dis; word packing CONFIRMED-emu |
| 0x2000–0x3FFF | nothing; whether LUT memory continues at 0x2000 (8 KB per the datasheet) is §4 | nobody | VERIFY |

Device: `/proc/iomem` `10114000-10117fff : ebc reg`, `/proc/interrupts` `81: GIC rk29-ebc` [CONFIRMED-device].

## 3. Registers 0x00–0x50

RC2 values computed from the stock formulas and the panel constants in the Image (0xc0a8faa8: 1448×1072, hsync 17, hstart 8,
hend 55, vsync 2, vstart 4, vend 4, gdck_sta 100, lgonl 281, virtual 1448×1072, SDCLK 40 MHz). The last column is the value read
on the device at idle after a partial (LUT, diff) update of 38 frames [CONFIRMED-device].

| Off | Name | Fields as stock uses them | Computed | Read on the RC2 |
|---|---|---|---|---|
| 0x00 | DSP_START | b0 start; b7:2 frames − 1 | LUT: `((n−1)<<2)\|1`, a full chunk `0xFD`; direct/AUTO: `0x01` | `0x00000095` (n = 38; b0 stays 1) |
| 0x04 | EPD_CTRL | b1:0 source/gate scan direction (= 3); b4:2 GDPWR power enables (= 0); b5 panel type (= 0); b15:8 `min(width/4, 255)`; b26:16 `hsync+gdck_sta+lgonl`; b31:27 `hsync+gdck_sta` truncated to 5 bits | `0xA98EFF03` | `0xA98EFF03` |
| 0x08 | DSP_CTRL | b31:30 swap = 3; b29 diff (only old ≠ new driven); b28 LUT mode (0 = direct); b27 "continue"; b19:16 SDCLK divider = 3; b15:0 = 0 | direct/AUTO `0xC8030000`; full LUT `0xD8030000`; partial LUT `0xF8030000`; b27 = 0 in the last or only LUT chunk | `0xF0030000` (partial LUT, last chunk) |
| 0x0C | DSP_HTIMING0 | b7:0 HSYNC end; b27:16 line total in SDCLK | `0x01BA0011` (17, 442) | same |
| 0x10 | DSP_HTIMING1 | b7:0 active start; b26:16 active end | `0x01830019` (25, 387) | same |
| 0x14 | DSP_VTIMING0 | b7:0 VSYNC end; b26:16 frame total in lines | `0x043A0002` (2, 1082) | same |
| 0x18 | DSP_VTIMING1 | b7:0 first active line; b26:16 last | `0x04360006` (6, 1078) | same |
| 0x1C | DSP_ACT_INFO | b11:0 width; b26:16 height (px) | `0x043005A8` | same |
| 0x20 | WIN_CTRL | b1:0 format (0 = 4-bpp Y); rest in §3.4 | `0x00020FC0` | `0x00020FC0` |
| 0x24 | WIN_MST0 | LUT: physical address of the **old** frame + window offset; direct/AUTO: the 2-bpp drive-code frame | varies | `0x7F87AF80` (the third 4-bpp frame of the 8 MiB display pool) |
| 0x28 | WIN_MST1 | LUT: the **new** frame + window offset; direct/AUTO: 0 | varies | `0x7F700000` (start of the pool) |
| 0x2C | WIN_VIR | b15:0 buffer line stride (px); b31:16 buffer height | `0x043005A8` | **`0x000005A8`**: the stride is there, b31:16 read 0 (not stored, or stock writes 0) [VERIFY]; the hardware needs only the stride |
| 0x30 | WIN_ACT | b11:0 width, b26:16 height of the window | full screen `0x043005A8`; window `(x2−x1) \| (y2−y1)<<16` | `0x043005A8` |
| 0x34 | WIN_DSP | same; stock always writes = WIN_ACT | same | `0x043005A8` |
| 0x38 | WIN_DSP_ST | b11:0 x start in SDCLK (`hsync+hstart+1 + x1/4`); b26:16 y (`vsync+4 + y1`) | no window `0x0006001A` | `0x0006001A` |
| 0x3C | INT | §3.5 | at start `0x28 \| n<<9` | `0x00004C28` = `0x28 \| 38<<9` |
| 0x40–0x4C | VCOM0–3 | always 0 | 0 | 0 |
| 0x50 | CONFIG_DONE | written after every group of writes | `0x0000FFFF` | 0 (write-only or self-clearing) |

### 3.1 DSP_START (0x00)

- **Frames − 1** in bits 7:2. For a 64-frame chunk stock sets all six bits (`0xFC`, 0xc060d13c–0xc060d150); for the last chunk
  `(n−1)<<2` truncated to a byte (0xc060d204–0xc060d224). Direct and AUTO always run one frame (field 0) [CONFIRMED-dis].
- **Start (bit 0).** Stock clears bit 0 only in the shadow copy and writes the hardware with bit 0 = 1, so after the first update
  the hardware never sees bit 0 = 0, yet every frame starts: the start triggers on a write of 1, not on a 0→1 edge [STRONG]. RK3566
  writes the frame count with bit 0 = 0, then `CONFIG_DONE`, then bit 0 = 1; that order is safer for a new driver but untested
  on the RK3026 [VERIFY].
- The RK3566 upper bits (`SDCE_WIDTH` 25:16, `SW_BURST_CTRL` 12, `EINK_MODE` 13, `OUT_LOW` 31) are never written by stock;
  whether the RK3026 has them is unknown [VERIFY].

### 3.2 EPD_CTRL (0x04)

Written once at probe (0xc060d558–0xc060d5b4) [CONFIRMED-dis]:
- bits 1:0 = 3: both scan directions reversed (RK3566: bit 0 `SDSHR`, bit 1 `GDRL`). These probably drive the `EBC_SDSHR`/`EBC_GDRL`
  pins (GPIO2_C5/C4), which on the RC2 are I2C2, not EBC [STRONG];
- bits 4:2 power enables (GDPWR0–2) = 0. The only writer that sets bit 2 is dead. GDPWR1/2 are muxed to the EBC on the RC2, but the
  driver never raises them [CONFIRMED-dis];
- bit 5 (RK3566 `EPD_AUO`, 0 = E Ink) = 0;
- bits 15:8 = `min(width/4, 255)` (255 on the RC2, although 1448/4 = 362); bits 26:16 = `hsync+gdck_sta+lgonl` = 398; bits 31:27 =
  `hsync+gdck_sta` = 117, of which 5 bits (21) survive. RK3566 keeps the gate-clock start (`GD_ST`) in 15:8, the end (`GD_END`) in
  26:16, and `MODE_SWAP`/`FRM_SEL` in 31/30. So RK3026 bits 26:16 are the same `GD_END` [STRONG]; bits 15:8 and 31:27 are
  [VERIFY]. The value `0xA98EFF03` works on this panel.

### 3.3 DSP_CTRL (0x08)

- `ebc_dsp_ctl_set` always ORs in `0xC0030000`: swap = 3 and SDCLK divider = 3, the same as RK3566 for an 8-bit bus
  [CONFIRMED-dis 0xc060b46c]. `dclk_ebc` is set to 4 × 40 MHz = 160 MHz (measured on the device), so SDCLK = `dclk / (div + 1)`
  = 40 MHz, 4 pixels per clock; a frame is 442 × 1082 / 40 MHz = 11.96 ms.
- Per mode in `ebc_register_update` (0xc060b640–0xc060b6b4) [CONFIRMED-dis]: **bit 28** (LUT) for modes 1, 4, 5, 8, 10, 15, 16,
  and together with **bit 29** for 2, 3, 6; **no bit 28** (direct) for 0, 9, 11, 12; **bit 27** always.
- `_ebc_frame_start(n, cont)` rewrites bit 27 = `cont`: 1 for intermediate LUT chunks and for AUTO/direct, 0 for the last (or
  only) LUT chunk (0xc060b524–0xc060b540).
- Meaning: bit 28 = LUT mode, otherwise the EBC reads ready-made 2-bit drive codes [STRONG]; bit 29 = diff, unchanged pixels are
  not driven [STRONG]; bit 27 is named `VCOM_MODE` in the header, used as "update continues" [GUESS]. RK3566 keeps `VCOM_MODE`
  = 1 all the time.
- Bits 15:0 (`SDO_VALUE`) = 0.

### 3.4 WIN_CTRL (0x20): masks versus constructors

Stock writes `fmt | 0x20FC0` with fmt = 0 (from probe, 0xc060b394–0xc060b3a4); the `.uu` generation writes the same; there is no
other writer [CONFIRMED-dis]. The header's masks and value constructors disagree for four fields:

| Field | Mask `m_*` | Constructor `v_*` | RK3566 | `0x20FC0` read with `m_*` | read with `v_*` |
|---|---|---|---|---|---|
| WIN_EN | b17 | b16 | b18 | **1** (window enabled) | 0, and b17 belongs to nothing |
| AHB_INCR | b16:12 | b15:11 | — | 0 | 1 |
| BURST | b11:9 | b10:8 | b12:10 | **7** = INCR16 | 7 |
| WIN_FIFO | b8:2 (7 bits) | b7:2 (value cut to 6 bits) | b9:2 (8 bits) | **112** = 128 − 16 | 48 |
| WIN_FMT | b1:0 | b1:0 | b1:0 | 0 = Y 4 bpp | 0 |

Verdict [STRONG]:
- the masks describe the RK3566 layout with a FIFO field one bit narrower and everything above it one bit lower;
- read through the masks, every set bit of the stock constant means something: window on, burst INCR16 (the value RK3566 uses,
  "burst_reg = 7 mean ahb burst is incr16"), FIFO threshold 112 = FIFO size − 16 (RK3566: 240 for a 256-entry FIFO);
- the constructors are shifted by one bit and `v_WIN_FIFO` truncates the field. These header bugs harm nobody: no C file in the
  public trees calls them, and the binaries write the ready constant;
- `INCR` = 0 with BURST = INCR16 does not matter (it only applies to the INCR burst type).

In `DSP_START`, `DSP_CTRL`, `EPD_CTRL` and `INT` the masks and constructors agree.

### 3.5 INT (0x3C)

| Bit | Name (header and RK3566 order) | What stock does | Mark |
|---|---|---|---|
| 0 | status FRAMEEND | not looked at | STRONG by analogy |
| **1** | **status DISPLAYEND (all n frames of the start sent)** | the handler acts only on bit 1 (0xc060e108–0xc060e110) | CONFIRMED-dis |
| 2 | status FRAMEFLAG (frame number N reached) | not looked at | STRONG |
| 3 | mask FRAMEEND | 1 at start | STRONG |
| 4 | mask DISPLAYEND | 0 at start; 1 while handling, then 0 again | CONFIRMED-src + dis |
| 5 | mask FRAMEFLAG | 1 at start | STRONG |
| 6 | clear FRAMEEND | 1 in the handler | CONFIRMED-src + dis |
| **7** | **clear DISPLAYEND** | 1 in the handler | CONFIRMED-src + dis |
| 8 | clear FRAMEFLAG | 1 in the handler | CONFIRMED-src + dis |
| 9+ | frame number for FRAMEFLAG (RK3566's `DSP_FRM_INT_NUM` sits right after its clear bits) | `_ebc_frame_start` writes n (the chunk's frame count; for 64 this reaches bit 15) | name STRONG, width VERIFY; the source is masked, so it does not matter |

- At start `_ebc_frame_start` writes `INT = 0x28 | n<<9` whole (0xc060b508–0xc060b520): clear bits 0, FRAMEEND and FRAMEFLAG
  masked. RK3566 also masks everything except DSP_END. Polarity "1 = masked" [STRONG].
- The handler (0xc060e0f4) [CONFIRMED-dis]: reads `INT`, sets bits 6, 7, 8 one at a time (each a hardware write), sets mask bit 4,
  calls the update work if status bit 1 is set, clears bit 4, writes `CONFIG_DONE`, and always returns "handled".
- On the device after a handler run: bits 6–8 read 0, so the clear bits self-clear; bit 4 = 0, bits 3/5 = 1, bits 9+ = 38
  [CONFIRMED-device].
- Device logs with more than 20 000 updates show no `frame timeout` (the driver's 3 s watchdog): the "status 1 / clear 7 / mask 4"
  scheme works [CONFIRMED-device, indirect].
- RK3566 has four sources (status 3:0, masks 7:4, clears 11:8, DSP_END = bit 1, clear bit 9). **An RK3566 handler on the RK3026
  would clear bit 9** (part of the frame-number field) instead of bit 7, and the interrupt would never be acknowledged [STRONG].

### 3.6 VCOM0–3 (0x40–0x4C) and CONFIG_DONE (0x50)

- `ebc_border_set` (0xc060b430) zeroes all four VCOM registers; nothing else touches them [CONFIRMED-dis]. RK3566 does not write them
  either. On the RC2 the VCOM voltage comes from the TPS65185 EEPROM and the `EBC_VCOM` pin (GPIO2_C0) switches it. What these
  registers do is unknown [VERIFY]; zeros are enough.
- `CONFIG_DONE` = `0xFFFF` after **every** group of writes: timings, window, `DSP_CTRL`, addresses, start, end of the handler
  [CONFIRMED-dis]. RK3566 writes 1. The values seem to take effect only after this write [STRONG]. A new driver should write
  `0xFFFF` as stock does; it reads back 0.

### 3.7 Write order of stock

**LUT update** (`ebc_register_update`, then `ebc_frame_start`) [CONFIRMED-dis]:
1. `DSP_CTRL` (mode) → `CONFIG_DONE`;
2. `WIN_MST0` = old, `WIN_MST1` = new (+ window offset) → `CONFIG_DONE`;
3. a LUT chunk into +0x1000: 64 frames or the remainder;
4. `WIN_DSP_ST`, `WIN_DSP`, `WIN_ACT` for the window;
5. `DSP_START` with the frame count;
6. `INT = 0x28 | n<<9`; `DSP_CTRL` bit 27 (1 = more chunks follow, 0 = last) → `CONFIG_DONE`;
7. `DSP_START` with bit 0 = 1;
8. interrupt with status bit 1: if frames remain, work queued from the interrupt repeats steps 3–7 with the next chunk; otherwise
   the update is done.

**Direct (9, 11, 12) and AUTO (0):**
1. the CPU computes frame 0 into buffer A;
2. `WIN_MST0` = A, `WIN_MST1` = 0; full-screen window; `WIN_FMT` stays 0 (bit 28 of `DSP_CTRL`, not the window format, selects
   how the data is read);
3. `DSP_CTRL` bit 27 = 1, `DSP_START` = 1 frame → `CONFIG_DONE` → start;
4. the CPU computes frame 1 into buffer B;
5. on each interrupt a SCHED_FIFO-99 thread **reads `WIN_MST0`**, switches it to the other buffer, starts, and computes the next
   frame (0xc060cb44–0xc060cbc4).

### 3.8 Addresses and windows

- `WIN_VIR` is the size of the **whole buffer**; the controller takes the line stride from it. `WIN_MST0/1` point at the **first
  pixel of the window**. Checked on the panel: with a window at y1 > 0 the content comes from `(x1 + 1024·y1)/2` (the stock
  1024-px stride bug in `ebc_image_addr_set`), and further rows follow with the real 1448 stride [CONFIRMED-device].
- In LUT mode both frames are 4 bpp, low nibble = left pixel. In direct/AUTO `WIN_MST0` is a 2-bit drive-code frame (w·h/4 bytes,
  two buffers in turn), `WIN_MST1` = 0.
- LUT window: `WIN_ACT = WIN_DSP = (x2−x1) | (y2−y1)<<16`, `WIN_DSP_ST` moves by x1/4 and y1; x1 must be a multiple of 4
  (0xc060d0c8–0xc060d130). The vertical base is hard-coded as `vsync + 4` instead of `vsync + vstart` (equal on the RC2).

## 4. Frame count and LUT size: 64 or 128

| Argument | For 64 frames / 4 KB | For 128 / 8 KB |
|---|---|---|
| stock 2017 and `.uu` 2014 | compare with 64, copy exactly 0x1000 bytes, 6-bit field [CONFIRMED-dis] | — |
| header | `m_FRAME_NUM` = `0x3f<<2` | — |
| RK3566 (same IP line) | 8-bit count ↔ 256 frames ↔ 16 KB: LUT size = 64 B × 2^width; 6 bits give 4 KB | — |
| DS V1.2 | — | "up to 128 frames", "LUT updateable (8KB)", consistent with each other (128 × 64 B) |
| the 16 KiB window | — | room for +0x1000..+0x2FFF |
| what stock never tests | — | `DSP_START` bit 8 is always 0 and +0x2000 is never touched; a 7-bit counter and a second 4 KB would go unnoticed |

Assessment: **the working size is 64 frames / 4 KB** [CONFIRMED-dis on two driver generations, works on the device]. The
datasheet claim is neither refuted nor supported; the EPD text first appears in V1.2 (2013-11-30, "Add HDMI and EPD/EBC
description"), and V1.1 has none [GUESS: the numbers may describe another chip of the family]. For a driver the difference is
small: GC16 at 0–3 °C is 131 frames with this waveform, more than 128, so chunked reloading from the interrupt is needed either
way. A safe check is a module that writes and reads back +0x2000 with the panel unpowered [VERIFY].

## 5. Outside the EBC window

- **`GRF_LVDS_CON0` (GRF 0x20008150) bit 0 `DATA_SEL`**: the source data lines `SDDO0–7` and `SDCE0/1` sit on the LVDS pads
  (datasheet V1.2, pins 47–56; `LCDC_D0..D9`) and are not in the iomux at all. Stock sets bit 0 (masked write) at init and at
  every panel power-up, and writes `0xFFFF0300` at power-down (bit 0 = 0, bit 8 LVDS PLL off, bit 9 LVTTL). At idle the register
  reads `0x0300` [CONFIRMED-device]. A new driver needs a `rockchip,grf` phandle for this; without it nothing reaches the panel.
- **Clocks:** `dclk_ebc` = CLKSEL23 div 3 from CPLL, **160 MHz**; the EBC probe retunes CPLL to 640 MHz once and it stays there
  [CONFIRMED-device]. `hclk_ebc`; stock also enables `aclk_lcdc1` and the `pd_lcdc1` domain; whether the EBC needs them is
  [VERIFY]. Stock enables all of them on every update and never disables them (use count = updates + 1 on the device), so whether
  they can be gated between updates is untested [VERIFY].
- **Pins at idle:** SDCLK/SDLE/GDCLK/GDOE/GDSP (GPIO2_B0/B1/B3/C1/C2) parked as GPIO low, VCOM (GPIO2_C0) GPIO high, GDPWR1/2
  (GPIO2_D0/D1) stay in the EBC function [CONFIRMED-device]. SDOE, SDCE2–5 and GDPWR0 are used as GPIOs on the RC2.
- **Interrupt:** Linux IRQ 81 = `GIC_SPI 49`. Stock requests it without a trigger type (`IRQF_DISABLED` only, 0xc060d480); the
  default level is to be checked [VERIFY].
- SoC-side details (CRU fields, GRF, pins): [onyx-rc2-hardware](https://github.com/hsw/onyx-rc2-hardware) `soc/README.md`.

## 6. For a new driver

- **Start from the values proven on this panel**, bit for bit: `EPD_CTRL 0xA98EFF03`, the timings of §3, `WIN_CTRL 0x00020FC0`,
  `WIN_VIR` = buffer size, `DSP_CTRL 0xC0030000` + mode bits, `VCOM0–3 = 0`, `CONFIG_DONE 0xFFFF` after each group,
  `GRF_LVDS_CON0` bit 0 = 1. Do not "fix" the unclear fields (`EPD_CTRL` 15:8 and 31:27, `DSP_CTRL` 27) without an A/B test on
  the panel.
- **Bit definitions from this page**, not from the header and not from RK3566: `WIN_CTRL` by the masks; `INT` status bit 1,
  clear bit 7, mask bit 4, `0x28` at start; `DSP_START` with a 6-bit count in 7:2.
- **LUT engine:** at most 64 frames × 16 words at +0x1000; longer waveforms in chunks from the DISPLAYEND interrupt, `DSP_CTRL`
  bit 27 = 1 for intermediate chunks, 0 for the last.
- **Addresses:** `WIN_MST0` = old, `WIN_MST1` = new, window offset `(x1 + y1·vir_width)/2` (not 1024), x1 a multiple of 4,
  `WIN_DSP_ST` = base + x1/4, y1, with vertical base `vsync + vstart`.
- **Direct mode** (partial updates without the LUT): bit 28 = 0, `WIN_MST0` = 2-bit frame (w·h/4), `WIN_FMT` unchanged, one frame
  per start, two buffers in turn.
- **Read the hardware as little as stock does** (`INT` and, in direct mode, `WIN_MST0`); keep the rest in a cached regmap. Reads of
  other registers are untested.
- **Device tree:** `reg = <0x10114000 0x4000>`, `interrupts = <GIC_SPI 49 …>`, clocks `dclk_ebc` (160 MHz) and `hclk_ebc`
  (+ possibly `aclk_lcdc1`/`pd_lcdc1`), `rockchip,grf`, pinctrl `default`/`sleep` for the eight GPIO2 pins.
- **Do not touch** +0x54..+0xFFF and +0x2000..+0x3FFF until checked.
- **Waveform and temperature:** load with `request_firmware()` and check sizes and offsets (stock checks nothing); temperature
  range: ≥ 43 °C → the last range, below 0 °C → the first, without the stock bugs.

## 7. Still [VERIFY]

1. `DSP_CTRL` bit 27: what changes on the panel if the last chunk keeps 1 or an intermediate chunk has 0.
2. `DSP_CTRL` bit 29: A/B of PART against a full LUT update on dark unchanged text.
3. `EPD_CTRL` bits 15:8 and 31:27; whether RK3026 has `SDCE_WIDTH`/`OUT_LOW` in `DSP_START`.
4. The width of the `INT` frame-number field (bits 9+); whether clearing bits 6/8 is needed at all.
5. LUT 64 or 128 frames, memory at +0x2000 (§4).
6. Whether a start fires on a write of bit 0 = 1 without a 0→1 edge, and whether a write of `DSP_START` before `CONFIG_DONE`
   already starts a frame.
7. Whether the EBC needs `aclk_lcdc1`/`pd_lcdc1`; gating between updates; the IRQ trigger type.
8. `WIN_VIR` bits 31:16 (read 0 where 1072 was expected).
