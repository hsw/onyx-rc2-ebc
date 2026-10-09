# RC2 E-Ink userspace ↔ kernel ABI (`/dev/ebc`, extended fb HAL)

> This document was written before the full driver analysis. Where it and [`driver/README.md`](../driver/README.md) disagree, the driver
> document is later and wins (its §7, "Corrections to `abi/`"). Statements known to be superseded are marked **[superseded]** here.

Produced on 2026-10-06 by static analysis only. No device access was used, and none of the inputs were executed.

**Inputs**
- Stock RC2 binaries (Android 4.2.2, firmware 1.8.2): `/system/lib/hw/gralloc.rk30board.so`, `/system/lib/libsurfaceflinger.so`, `/system/lib/libui.so`.
- The stock kernel Image (the 2017 Image described in the [top README](../README.md#the-analysed-kernel)). It is uncompressed and still contains the EBC driver code.
- The public kernel source tree [rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources), `drivers/video/rockchip/rk_epd/`. This includes the precompiled `hardware_ebc.uu` and `epdlut/epd_lut.uu` objects, which were uudecoded and disassembled.
- The stock `/ebc_waveform.bin` from the boot ramdisk (see [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform)).

**Tools**
- Ghidra 12.1.4 headless decompiler. The project was imported at base 0x10000, so *Ghidra address = file vaddr + 0x10000*. PC-relative constants were resolved with a small script (working notes, not published).
- llvm-objdump (thumbv7) and GNU objdump (ARM, raw Image).

**Address conventions**
- Addresses in this document are the **file vaddr** of the `.so` unless stated otherwise.
- Kernel addresses are written as `file offset + 0xc0008000`. The kernel's own jump tables show that the runtime VA is that value + 0x400000.
  **[superseded]** `driver/` and `reagl/` use the runtime VA, file offset + 0xc0408000.

**Confidence marks:** [CONFIRMED] means read directly from code. [STRONG] means a consistent inference. [VERIFY] means open.

---

## 0. Summary

**The ioctls**
- `/dev/ebc` uses plain integer ioctl numbers `0x7000`–`0x7004`. They are not `_IO()` encoded: `ebc.h` `#define`s literal constants.
- Every ioctl that carries a struct carries **one 56-byte `struct ebc_buf_info`**.
- `0x7004` is a stock-kernel-only extension (not in the public source). It returns the constant **3028** (0xbd4), and gralloc uses it as a "driver variant / REAGL-capable" probe [CONFIRMED in both kernel and gralloc].

**The display path**
- In the stock system the stock userspace (SurfaceFlinger plus a proprietary gralloc/fb HAL) drives `/dev/ebc` once per posted frame:
  ioctl 0x7004 (variant probe) → 0x7000 (free buffer) → 4-bit gray conversion into the mmapped buffer → 0x7001 (mode + window).
  §4 describes the HAL's extended `framebuffer_device_t` interface (what a replacement HAL must provide); §5 lists what the kernel receives.

**Verdict:** the kernel ABI is fully understood for what the stock userspace uses.

---

## 1. `/dev/ebc` ioctl ABI

`ebc.h` (source tree) defines the commands as literal constants:

```c
#define GET_EBC_BUFFER       (0x7000)
#define SET_EBC_SEND_BUFFER  (0x7001)
#define GET_EBC_DRIVER_SN    (0x7002)
#define GET_EBC_BUFFER_INFO  (0x7003)
```

They are not built with `_IO/_IOR` macros, so the number is the constant itself. They are numerically equal to `_IO('p', n)`, the same range the RTC ioctls use, which does not matter because they go to a different device.

**Kernel side**
- Stock `ebc_io_ctl` is at file offset 0x208284, which is `ebc_io_ctl` @0xc0610284 in kallsyms.
- It does `sub r1,r1,#0x7000; cmp r1,#4; ldrls pc,[pc,r1,lsl#2]`, so there are exactly **5 handled commands, 0x7000..0x7004**. Anything else returns 0.
- The case bodies match `hardware_epd_public.c::ebc_io_ctl` field-for-field, plus one new case, 0x7004.

| cmd | name | arg | kernel behaviour (stock Image) | stock userspace usage |
|---|---|---|---|---|
| 0x7000 | `GET_EBC_BUFFER` | `struct ebc_buf_info*` (56 B, out) | See note A below the table. | See note B below the table. |
| 0x7001 | `SET_EBC_SEND_BUFFER` | `struct ebc_buf_info*` (56 B, in) | See note C below the table. | See note D below the table. |
| 0x7002 | `GET_EBC_DRIVER_SN` | `struct ebc_sn_info*` (40 B, in/out) | Encodes `"RK29_EBC_DRIVER_VERSION_1.00"` with the user key. | unused |
| 0x7003 | `GET_EBC_BUFFER_INFO` | `struct ebc_buf_info*` (56 B, out) | Same panel fields as 0x7000, without `offset`. | called once at open to get the panel geometry, then the buffer is mmapped |
| 0x7004 | **no name in any source** (suggested `GET_EBC_VERSION`) [VERIFY name] | `int*` (4 B, out) | See note E below the table. | See note F below the table. |

**A. Kernel behaviour of 0x7000 `GET_EBC_BUFFER`:**
- Takes an empty buffer from the pool with `ebc_empty_buf_get` and sets `offset = buf->phy − pool base`.
- Copies these panel fields: `height`, `width`, `vir_height`, `vir_width`, `fb_width`, `fb_height`, `color_panel`, `rotate`. It does **not** set `epd_mode` or `win_*`.
- Does `copy_to_user(56)`.
- The first call also kills the kernel boot animation and calls `rk29ebc_notify(EBC_ON)`.

**B. Stock userspace usage of 0x7000:** once per posted frame; it writes the frame at `mmap base + info.offset` and reuses the struct for 0x7001.

**C. Kernel behaviour of 0x7001 `SET_EBC_SEND_BUFFER`:**
- Does `copy_from_user(56)` and looks the buffer up as `base + offset`.
- Copies these into `struct ebc_buf_s`: `buf_mode = epd_mode` and `win_x1/y1/x2/y2`. When `color_panel == 1`, the x coordinates are multiplied by 3.
- Queues the buffer on the display list and wakes `ebc_thread`.
- If `epd_mode == 8` (`EPD_BLOCK`) it sleeps until the frame has been displayed.

**D. Stock userspace usage of 0x7001:** sets `+0x04 epd_mode`, `+0x24 win_x1`, `+0x28 win_y1`, `+0x2c win_x2`, `+0x30 win_y2`.

**E. Kernel behaviour of 0x7004:**
- Returns `-1` if `arg == NULL`.
- Otherwise does `put_user(3028)` and returns 0.

**F. Stock userspace usage of 0x7004:** called before every frame; a non-zero value enables the REAGL/hold features, and the value selects the frame layout: 3026, 3027, **3028 (RC2, 4-bpp gray16)**, 3188 (RK3188 colour/LCDC path). A kernel without 0x7004 (the public source) returns 0 and turns those features off.

The machine-readable version is `ioctl-table.tsv`.

**mmap**
- `mmap(NULL, vir_width*vir_height*4, PROT_READ|PROT_WRITE, MAP_SHARED, ebc_fd, 0)` → the buffer base.
- For RC2 this is presumably 1448×1072×4 = 6,209,024 B, assuming `vir_width = 1448` [VERIFY: `vir_*` values come from the kernel at runtime].
- Gralloc never assumes a buffer count. It only adds the `offset` that 0x7000 returns.
- The kernel's `ebc_buf_init(phy, virt, len, dest_buf_len)` decides the slot size. At 4 bpp a frame is w·h/2 = 776,128 B, so the mapping holds up to 8 frames [STRONG, count VERIFY]. **[superseded]** The pool is 4 slots of w·h bytes (8-bpp capacity for AUTO; `driver/README.md` §2.2).

---

## 2. Shared structs

### 2.1 `struct ebc_buf_info` (56 bytes)

Defined in `ebc.h`, section "android use struct". The kernel copies `sizeof == 0x38` in both directions, and the userspace's `ebc_buf_info` object has size 56 [CONFIRMED].

| off | field | filled by | used by gralloc |
|---|---|---|---|
| 0x00 | `int offset` | 0x7000 (kernel) | buffer = `ebc_buffer_base + offset`; passed back unchanged in 0x7001 |
| 0x04 | `int epd_mode` | gralloc (0x7001) | EPD mode of this frame (§3) |
| 0x08 | `int height` | kernel | gray conversion height; region clipping |
| 0x0c | `int width` | kernel | conversion width / row stride |
| 0x10 | `int vir_height` | kernel | mmap size; default window `win_y2` |
| 0x14 | `int vir_width` | kernel | mmap size; default window `win_x2`; malloc sizes |
| 0x18 | `int fb_width` | kernel | color path only |
| 0x1c | `int fb_height` | kernel | color path only |
| 0x20 | `int color_panel` | kernel | 1 → `Rgb888_to_color_eink`; kernel multiplies x by 3 |
| 0x24 | `int win_x1` | gralloc | normally 0 |
| 0x28 | `int win_y1` | gralloc | normally 0 |
| 0x2c | `int win_x2` | gralloc | normally `vir_width` |
| 0x30 | `int win_y2` | gralloc | normally `vir_height` |
| 0x34 | `int rotate` | kernel | `framebuffer_device_open` does `snprintf("%d", rotate)` → `property_set("ro.sf.hwrotation", …)`. **The stock `ro.sf.hwrotation=270` therefore comes from the kernel panel info**, not only from build.prop [CONFIRMED]. |

The kernel copies its fields from `ebc_panel_info` at `prk29_ebc_info+0x94..0xc8`, in the source order `width, height, …, vir_width(+0xb0), vir_height(+0xb4), refcount, fb_width, fb_height, color_panel, rotate(+0xc8)` [CONFIRMED].

The window passed to 0x7001 is normally the full `0,0,vir_width,vir_height`. A sub-rectangle is used only for the `EPD_FULL_WIN` (9) pass that follows an A2 region going away. In that pass the window is the bounding box of `update ∪ prevA2 ∪ accum`, where accum is everything updated during the A2 session (corrected 2026-10-08).

### 2.2 Kernel-internal `struct ebc_buf_s` (for reference)

The layout is `status, phy_addr, virt_addr, buf_mode(+0xc), len(+0x10), win_x1(+0x14), win_y1(+0x18), win_x2(+0x1c), win_y2(+0x20)`. The stock 0x7001 handler stores to exactly these offsets [CONFIRMED].

### 2.3 `struct ebc_sn_info` (40 bytes)

`u32 key; u32 sn_len; char cip_sn[29]`, padded to 40. Only relevant for 0x7002, which nobody in userspace uses.

### 2.4 Frame format written by gralloc

- **Source:** the SurfaceFlinger framebuffer is a 32-bpp fbdev buffer.
  - `init_frame_buffer_locked` forces `bits_per_pixel = 32` and `R/G/B offsets = 16/8/0`, i.e. BGRA.
  - `var.nonstd = 5`, and `fb->format = 5` (`HAL_PIXEL_FORMAT_BGRA_8888`).
  - `yres_virtual = 3*yres`.
  - fbdev is used only as the composition target. Scan-out to the panel is entirely via `/dev/ebc`.
- **Destination on RC2 (variant 3, i.e. 0x7004 returns 3028):**
  - **Gray16, 4 bits/pixel, 2 px/byte, left pixel = low nibble.** Converted with `neon_rgb888_to_gray16ARM`, luma weights 11/16/5 over 32. The weights apply to bytes 0/1/2 of each pixel, which are **B/G/R** on this BGRA fb, so stock weights blue 11 and red 5 (corrected 2026-10-08). As a formula: gray4 = (11·b0 + 16·b1 + 5·b2) >> 9 with b0 = blue, row stride `vir_width/2`. `rgb888_to_gray16_dither` advances the destination by width/2 bytes per row.
  - In mode 4 (`FULL_DITHER`) the conversion uses `rgb888_to_gray16_dither`.
  - In A2 it uses `rgb888_to_gray2_dither` / `gray256_to_gray2_dither` (2-level dither, still in the 4-bpp buffer).
- **Other variants:**
  - Only variant 2 (3027) uses the 8-bit-per-pixel "gray16_8" layout, and only for AUTO and REGAL. Variant 1 (3026) stays 4-bpp, with AUTO→PART (corrected 2026-10-08).
  - Variant 3188 uses the colour/LCDC path.
  - Neither is relevant to RC2.

---

## 3. EPD mode numbers (one table)

The full table is `epd-modes.tsv`. The values are identical across all three layers: Java `View$EINK_MODE.getValue()` = SF transaction ints = `fb_requestEpdMode(int)` = `ebc_buf_info.epd_mode` = kernel `EPD_*`. Modes 13..17 are handled (mostly) in the stock userspace.

| val | `View$EINK_MODE` | `ebc.h` | stock kernel `buf_mode` → `lut_get(type)` | stock userspace behaviour |
|---|---|---|---|---|
| −1 | EPD_NULL | – | – | no update at all this frame |
| 0 | AUTO | EPD_AUTO | type 5 (auto path) | sticky; variant 1 (and holddisp re-send): AUTO→PART |
| 1 | FULL | EPD_FULL | type 2 (GC16) | **one-shot**, not sticky (corrected 2026-10-08); resets auto-full counter; while a previous A2 region exists it becomes the A2-exit pair 2 → 9 |
| 2 | A2 | EPD_A2 | type 6 (A2) | forced whenever this frame's or the previous frame's A2 region is non-empty; a requested 2 without one →3. Not counted by auto-full |
| 3 | PART | EPD_PART | type 2 | **default** (initial `cur = sticky = 3`) |
| 4 | FULL_DITHER | EPD_FULL_DITHER | type 2 | dithered gray16; resets counter |
| 5 | RESET | EPD_RESET | type 1 (INIT) | one-shot |
| 6 | BLACK_WHITE | EPD_BLACK_WHITE | type 4 (DU) | also used internally on A2 **entry** or a new area (new areas white, then mode 2), not on exit (corrected 2026-10-08) |
| 7 | TEXT | EPD_TEXT | type 2 **[superseded: rejected by the stock `ebc_thread`, leaks a slot]** | one-shot |
| 8 | BLOCK | EPD_BLOCK | type 2; **ioctl blocks until shown** | used for standby/wake white frames |
| 9 | FULL_WIN | EPD_FULL_WIN | type 2, windowed | internal second pass after A2 exit |
| 10 | OED_PART | EPD_OED_PART | type 3 | sticky |
| 11 | DIRECT_PART | EPD_DIRECT_PART | type 2 | one-shot |
| 12 | DIRECT_A2 | EPD_DIRECT_A2 | type 6 | one-shot |
| 13 | STANDBY | — | (2) **[superseded: rejected if ever sent]** | draws standby PNG, sends as mode 8 (SF `onScreenReleased`) |
| 14 | POWEROFF | — | (2) **[superseded: rejected if ever sent]** | draws poweroff/nopower PNG as mode 1, then **drops every later frame** (SF `handleMessagePoweroff`) |
| 15 | REGLA (REAGL) | — (stock kernel only) | type 8 → GLR16 (wbf 4) | sticky; variant 0: →3 |
| 16 | WAKEUP | — (stock kernel only) | type 9 **[superseded: rejected from userspace, leaks a slot; type 9 is kernel-internal, `reagl/README.md` §3]** | while in standby and `ro.need.white.with.standby=y`: white mode-8 frame, then the next frame is FULL. Otherwise a plain one-shot 16 (SF `onScreenAcquired`) |
| 17 | (userspace "EPD_REBOOT") | — | (2) | draws reboot PNG; no stock sender found [VERIFY] |

**Stock userspace mode state** (summary): modes 0, 3, 10 and 15 are sticky (they become the default for later frames), the others are one-shot; every 401 counted frames the userspace forces one FULL update (auto-full, default limit 400).

**Kernel switch** [CONFIRMED]:
- The stock kernel's per-buffer switch accepts `buf_mode` 0..16 (17 cases, file offset 0x2036ec, inside `ebc_register_update` @0xc060b610).
  **[superseded]** `ebc_thread` filters the mode first, so the accepted set is {0–6, 8–12, 15} (`driver/README.md` §2.4).
- The source tree only defines 0..12, so the stock driver is newer: its banner is `[RK_EPD]: version 1.02 20141016`. The precompiled `hardware_ebc.o` in the source tree carries the same banner, but its `ebc_io_ctl`/`get_lut_mode` differ.

---

## 4. Extended `framebuffer_device_t`

**Baseline: AOSP 4.2 (and 4.4) `fb.h` layout**

| Offset | Field |
|---|---|
| 0x00 | `hw_device_t` (size 0x40) |
| 0x40 | `flags` |
| 0x44 | `width` |
| 0x48 | `height` |
| 0x4c | `stride` |
| 0x50 | `format` |
| 0x54 | `xdpi` |
| 0x58 | `ydpi` |
| 0x5c | `fps` |
| 0x60 | `minSwapInterval` |
| 0x64 | `maxSwapInterval` |
| 0x68 | `numFramebuffers` |
| 0x6c | `reserved[7]` |
| 0x88 | `setSwapInterval` |
| 0x8c | `setUpdateRect` |
| 0x90 | `post` |
| 0x94 | `compositionComplete` |
| 0x98 | `dump` |
| 0x9c | `enableScreen` |
| 0xa0 | `reserved_proc[6]` |
| **0xb8** | end of the AOSP struct |

**Binary cross-checks of the baseline** [CONFIRMED]:
- Stock `libui` `FramebufferNativeWindow` reads `+0x44/+0x48/+0x50/+0x54/+0x58/+0x60/+0x64/+0x68/+0x8c`.
- SF `HWComposer::fbPost` calls `+0x90`, `fbCompositionComplete` calls `+0x94`, and `fbDump` calls `+0x98`.
- The 4.4 `fb.h` layout is unchanged from 4.2 [STRONG; AOSP history].

**What gralloc fills in** (`framebuffer_device_open`, a zeroed 0xd0-byte struct) [CONFIRMED]:
- `tag = 'HWDT'`, `version = 0`, `close`.
- `setSwapInterval`, `post`, `compositionComplete`.
- `setUpdateRect = NULL`, `dump = NULL`, `enableScreen = NULL`, `numFramebuffers = 0`.
- `format = 5`, `min/maxSwapInterval = 1`.

It also stores these extension slots:

| off | gralloc implementer | SF caller | signature (from both sides) |
|---|---|---|---|
| 0xb8 | `fb_setA2Region(android::Region)` | `HWComposer::setA2Region(Region)`: Region copy on stack, `r0 = &copy`, return value propagated | `int (*)(android::Region)` |
| 0xbc | `fb_setUpdateRegion(android::Region)` | `HWComposer::setUpdateRegion(Region)` (same pattern) | `int (*)(android::Region)` |
| 0xc0 | `fb_requestEpdMode(framebuffer_device_t*, int)` | `HWComposer::requestEpdMode(int)`: `r0 = mFbDev`, `r1 = mode` | `void (*)(framebuffer_device_t*, int)` |
| 0xc4 | `fb_get_reagl()` | `HWComposer::get_reagl()`: `r0 = mFbDev` (ignored); the result goes to `Parcel::writeInt32` (transaction 0x451) | `int (*)(void)` |
| 0xc8 | `fb_set_holddisp(int,int,int)` | `HWComposer::set_holddisp(a,b,c)`: shifts the args to r0..r2 | `int (*)(int hold, int mode, int count)` |
| 0xcc | `set_autofull_max(int)` | **no caller in SF** (no load of `fbDev+0xcc` in any HWComposer method) | `void (*)(int)` |

- Slot 0xcc is `set_autofull_max` [CONFIRMED].
- The `Region`-by-value arguments are passed as a pointer to a caller-owned temporary (ARM C++ ABI, non-trivial class). This was verified in SF's disassembly: `add r0,sp,#4; blx Region::Region(copy); add r0,sp,#4; blx slot`.
- **Reconstructed header:** `fb_onyx.h`.

---

## 5. What the kernel receives from the stock userspace

Observed behaviour of the stock userspace, as seen from the kernel side [CONFIRMED by disassembly and device traces]:
- **Per posted frame:** one 0x7004 call (returns 3028), one 0x7000 call (blocks until a slot is free), a full-screen 4-bpp frame
  written into that slot, and one 0x7001 with the mode and a window. The window is `(0,0,vir_w,vir_h)` except for mode 9 (FULL_WIN).
- **No regions reach the kernel.** Userspace tracks update and A2 regions itself; the kernel only gets the mode plus one rectangle.
- **A2 sequences:** when an A2 area appears, the new A2/update areas are filled white and sent as **mode 6** (DU), then the 2-level
  frames go as **mode 2** (A2). When the A2 area disappears, the union of the update area and the previous A2 areas is filled white
  and sent as **mode 2**, followed by **mode 9 (FULL_WIN)** with the window = the bounds of that union (auto-full may turn it into
  mode 1 with the same window).
- **Hold/batching:** the stock userspace can hold updates (frames are composed but not sent) and later re-send the last frame once,
  turning AUTO (0) into PART (3). ONYX reader apps use this to batch page turns.
- **Special screens** (standby/wake/power-off pictures, modes 13/14/16/17 in userspace numbering) are rendered in userspace and sent
  through the same 0x7000/0x7001 path; the kernel sees them as ordinary frames with mode 8 (BLOCK) or a normal mode.

---

## 6. Waveform file vs kernel expectations

`ebc_waveform.bin` is a standard **E Ink WBF** file. Every header checksum validates. Parser: `wbf.py` in [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform).

| off | field | value |
|---|---|---|
| 0x00 | checksum (file CRC32) | 0xc633dbbd |
| 0x04 | file size | 256003 (matches) |
| 0x08 | serial | 5487 |
| 0x0c | run_type / fpl_platform / fpl_lot | 0x11 / 0x00 / 110 ("R110") |
| 0x10 | **mode_version** / wf_version / wf_subversion / wf_type | **0x19** / 0x4d / 0x21 / 0x50 ("…4D21") |
| 0x14 | panel_size / amepd_part / wfm_rev / frame_rate | 0x00 / 0x5b / 0x00 / 0x85 (85 Hz) |
| 0x1c | xwia (24-bit) / cs1 | **0x40** / 0x4f (= sum 0x08..0x1e) |
| 0x20 | wmta (mode table) / fvsn | 0x5f / 0x01 |
| 0x24 | luts / mode count−1 / temp-range count−1 / adv flags | 0x04 / 7 / 13 / 0x03 |
| 0x28 | eb / sb / … / cs2 | 0xff / 0xfc / … / 0x77 (= sum 0x20..0x2e) |
| 0x30 | temperature table (15 bounds) + cs | 0,3,6,…,33,38,43,48 °C → 14 ranges; cs 0x47 |
| 0x40 | **panel ID string** (Pascal: len 0x1d) | `320_R110_AE4D21_ED060KD1C2_TC` at **0x41..0x5d**; cs 0x5e |
| 0x5f | mode table | 8 × (24-bit ptr + cs), all valid |

**Mode table contents**
- Modes 3, 4 and 5 point to **identical** temperature tables. That is the usual "GL16 = GLR16 = GLD16" aliasing of REAGL-capable mode_version 0x19 waveforms.
- Mode 6 has very short tables (A2) and mode 0 is the INIT table.
- So the labelling is [STRONG]: 0 INIT, 1 DU, 2 GC16, 3 GL16, 4 GLR16, 5 GLD16, 6 A2, 7 DU4.

**Comparison with the kernel source and objects**
- `epdlut/waveform.h` in the source tree is **not** a WBF. It is a built-in Rockchip `rkf:v1.0.1` array for a V110 panel, used only as the "use array lut" fallback. Its layout does not apply to this file.
- The WBF parsing lives in the precompiled `epd_lut` object (`decodewaveform`, `decodewaveform_19`, `epd_lut_data_get_pvi`, `crc_32`, `get_lut_temp`). The only header constant in a readable header is `WFM_HDR_SIZE 0x30` (`epd_spi_flash.h`), which matches: the temperature table starts at 0x30.
- `decodewaveform_19` is the decoder for **mode_version 0x19**, which is exactly this file's value.
- The stock kernel's `parse_mode_version` (file offset 0x2094b0) switches on header byte 0x10 (mode_version, cases 0x12/0x18/0x19/0x20/0x23).
  - For 0x19 it builds the index table `{0,1,7,2,3,4,5,6}`.
  - `get_lut_mode` (file offset 0x209618) maps lut type to index: `RESET→0`, `2→3`, `3→2`, `4→1`, `5→3`, `6→7`, `8/9→map_to_pvi_mode(8)=5`.
  - So REGAL (and 16) use table[5] = wbf mode 4, i.e. **GLR16** [STRONG]. Type 7 uses an uninitialised index (dead path).
  - Combined with the buf_mode switch, this gives: RESET→INIT, FULL/PART→GC16, BLACK_WHITE→DU, A2/DIRECT_A2→A2, REGAL→GLR16, OED_PART→DU4(?) [labels STRONG; OED_PART VERIFY]. **[superseded]** Type 3 decodes wbf 7 (DU4) but builds no LUT, so OED_PART draws nothing (`driver/README.md` §2.5).
- **Source of the waveform at boot:** the kernel has both `/ebc_waveform.bin` (ramdisk file) and `waveform_addr=` (cmdline 0x7ff00000, loader-provided) paths, plus "spi and nand waveform are same/different" checks. Which copy wins on RC2 is still [VERIFY] (dmesg did not capture EBC lines). **[superseded]** The ramdisk file wins: the kernel reads it into the `waveform_addr` window, overwriting the loader's copy (`driver/README.md` §2.9).

