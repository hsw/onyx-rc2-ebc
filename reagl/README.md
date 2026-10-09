# REAGL in the stock RC2 kernel: `reagl_1`, `reagl_2`, `enable_reagl`, EPD modes 15/16

Static analysis, 2026-10-08. Target: the stock RC2 kernel Image (Linux 3.0.36+ built 2017-11-07, sha256 `47a13cf3…30af`, raw ARM,
VA = file offset + 0xc0408000; see [the top README](../README.md#the-analysed-kernel)), symbols from kallsyms recovered with
[`kernel/extract_kallsyms.py`](../kernel/extract_kallsyms.py). There is no source for any of this code: the public rychly tree only has
precompiled `.uu` objects of an older generation, without REAGL. The rest of the driver is in [`driver/README.md`](../driver/README.md).

Confidence marks:
- [CONFIRMED-emu]: the stock function was run alone in Unicorn and matched the Python reimplementation byte for byte (`tools/reagl_emu.py`).
- [CONFIRMED-dis]: read directly in the objdump listing at the given address.
- [STRONG]: an inference from several confirmed facts.
- [GUESS] / [VERIFY]: not proven; needs the device.

## TL;DR

- **REAGL here is an algorithm, not a waveform.** A mode-15 (REGLA) update runs in **two hardware passes** inside `ebc_thread`:
  1. **Pass 1:** GL16 over the update window, using the GLR16 table. GLR16 is byte-identical to GL16 on the RC2.
  2. **Pass 2:** the kernel-internal mode 16. It drives **only the white pixels that bordered dark pixels on the previous page**, with the
     special 5-bit waveform entry `tbl[f][31][31]`. In the RC2 GL16/GLR16 table that entry is a short alternating black/white pulse train that ends
     on white (`…1212121212121212 2`, 17 of 38 frames at temperature range 8). In GC16 the same entry is all zero.
  - Pass 2 is the actual REAGL edge cleanup. It removes the grey fringe that GL16 leaves around the old text, because GL16 never drives
    white→white pixels.
- **Fallbacks:**
  - If fewer than **200 32-bit words** (8 px each, i.e. at most ~1600 px, about 0.1% of the 1448×1072 frame) differ between the new and
    the old frame, the frame is downgraded to **PART** (mode 3, GC16, hardware partial).
  - If nothing differs, the frame is dropped.
  - **Pass 2 runs only when the 83-px "status bar" stripe is unchanged.** Otherwise mode 15 is a single plain GL16 pass.
- **Mode 16 from userspace (gralloc's WAKEUP) is rejected** by `ebc_thread` ("ebc buffer mode error!"). Two consequences, both [STRONG]:
  - the rejected buffer leaks;
  - the currently displayed buffer is released while it is still the reference "old" image.
  - In practice this is **latent**: SurfaceFlinger calls `requestEpdMode(frame mode)` before every post, which overwrites the gralloc one-shot 16,
    and no device log has a single `eink mode = 16` (4 Power wakes in a suspend/wake test, ~2400 logged frames in device logs). It matters only
    if something ever passes raw 16 to 0x7001.
- **Dead code:**
  - `enable_reagl` is a time-based unlock (key = `tv_sec % 1e8` as `"%ld"` XOR `"onYxeNCy"`). It has no caller, and the flag it sets is never read.
  - `reagl_1` (same marking without the mask step), `reagltopart` and `epd_lut_reagle` also have no callers.
- **Tunables:** none. No sysfs, no module parameter. The thresholds are compiled-in function returns:
  - `get_reagl_diffnum()` = 200;
  - `get_statusbar_hight()` = 83;
  - `get_bottom_hight()` = 0.
  - The only data knob is `tbl[f][31][31]` of the waveform, and the waveform is stock-only.

## Method (reproducible, nothing executed natively)

| Step | Tool | Output |
|---|---|---|
| Annotated disassembly per function; BL/B and pointer scan for callers | `tools/kdis.py IMAGE KALLSYMS <sym or hex> [stop]`, `--callers SYM…` (GNU objdump `-b binary -m arm --adjust-vma=0xc0408000`) | `<fn>.s`, `callers.txt` (not published) |
| Ghidra 12.1.4 headless on the raw Image | `tools/run.sh <scratch-dir>`: `BinaryLoader -loader-baseAddr 0xc0408000 -processor ARM:LE:32:v7 -noanalysis`. The postScript `ImportKallsymsRaw.java` splits the block into text/rodata (read-only) / data, adds .bss up to 0xc1600000, labels all 38 721 kallsyms entries, and creates functions only for the EBC + epd_lut range 0xc060b29c–0xc0616700 plus their direct callees. `DecompileList.java` decompiles the names in `tools/reagl.list`. The run takes about 10 s. | `reagl.decomp.c` (not published) |
| Byte-exact check of the leaf helpers | `tools/reagl_emu.py IMAGE [--seed N] [--quick]` (Unicorn 2.1.4; PEP 723 header, `uv run --script`). Each stock function is entered alone. Kernel calls (`memcpy`, `memset`, `__memzero`, `do_gettimeofday`, `printk`, `flush_tlb_all`, the cache-flush pointers at 0xc0a60298/0xc0a602d0) are replaced by `bx lr` stubs emulated in Python, and any unmapped access aborts the run. | 0 failures: seeds 1 and 7 full (1254 cases, incl. the real 1448×1072 frame with sb = 83), seeds 2 and 3 `--quick` (1225 cases). A mutated reference fails 147/1225, so the test discriminates. |
| Waveform entries near white | the WBF decoder `wbf.py` of [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform) on the stock `ebc_waveform.bin` | table below |

Ghidra mistakes caught by objdump or the emulator:
- the rotation-2 margin semantics of `reagl_2`;
- `check_part_mode_text_rect` was shown as 32 bytes long (jump-table body).

Emulation covers the leaf helpers (`reagl_1/2`, `check_part_mode_text`, `check_rotate`, `check_part_mode_text_rect`, `backupstatarbar`,
`revertstatarbar`, `y4bitto8bit`, `y8bitto4bit`, `reagltopart`, `get_reagllut_data_hard`, `get_reagl_diffnum`). The control flow (`ebc_thread`,
`ebc_register_update`, `ebc_io_ctl`, `epd_lut_data_get_pvi_hard`) is disassembly-only.

## Data structures (offsets used below)

- `info` = `*(0xc0ca31e0)`, the `rk29_ebc_info` of this kernel (the layout differs from rychly `ebc.h`):

  | Offset | Field |
  |---|---|
  | `+0x00` | ebc_status |
  | `+0x04` | frame_total (byte) |
  | `+0x30` | frame-done flag |
  | `+0xb0` | **width** = `vir_width` (1448 on the RC2; [`abi/ebc-abi.md`](../abi/ebc-abi.md) §2.1 `ebc_buf_info`) |
  | `+0xb4` | **height** = `vir_height` (1072) |
  | `+0x140` | `lut_ops.lut_get` |
  | `+0x144` | `lut_ops.reagle` |
  | `+0x150` | temperature op |
  | `+0x154` | `ebc_ops` |
  | `+0x158` | `lut_data` (frame_num, lut ptr) |
  | `+0x194` | **prev_dsp_buf** (the image currently on the panel = "old") |
  | `+0x198` | **curr_dsp_buf** |
  | `+0x2bc` | last diff count |

  [CONFIRMED-dis, ebc_thread 0xc060fbdc–0xc060fd84]
- `G` = 0xc0ca31e0, a block of driver globals:

  | Offset | Content |
  |---|---|
  | `+0` | info* |
  | `+4` | dev_t |
  | `+8` | cdev |
  | `+0x44` | class |
  | `+0x48` | **reagl unlock flag** (written only by `enable_reagl`) |
  | `+0x54` | 8-bit scratch buffer (w·h bytes) |
  | `+0x58` | status-bar backup buffer (kmalloc w·h/2 on first use) |
  | `+0x60` | detected rotation |
  | `+0x64` | **pass-2 pending flag** |
  | `+0x74` | waveform data pointer (epd_lut, read by `epd_lut_reagle` and `epd_lut_data_get_pvi_hard`) |
  | `0xc0ca3260…` | decoded 5-bit `tbl[f][old][new]`, 0x400 B per frame |
- `ebc_buf_s`:

  | Offset | Field |
  |---|---|
  | `+0` | in-use |
  | `+4` | phys |
  | `+8` | virt (4-bpp packed, low nibble = left pixel, 0 = black, 15 = white) |
  | `+0xc` | **mode** |
  | `+0x14..+0x20` | win x1, y1, x2, y2 |

  Pool of at most **4** buffers (`ebc_buf_init` stops at count == 4 or at the end of the memory window, 0xc06152f8). Free = `+0 == 0`; `ebc_empty_buf_get` sleeps until some `ebc_buf_release` [CONFIRMED-dis].

## 1. What `reagl_2` (and `reagl_1`) compute

`reagl_2(u8 *old4, int h, int w, int sb, int bottom, int rot)`. It is called only from `ebc_thread` at 0xc060fc14, with
`old4 = prev_dsp_buf->virt`, `h = info+0xb4`, `w = info+0xb0`, `sb = 83`, `bottom = 0`, `rot = G+0x60` [CONFIRMED-dis]. The algorithm is
[CONFIRMED-emu], in steps:

1. **Expand.** The old frame is expanded into the 8-bit scratch buffer at `G+0x54` (w·h bytes), exactly as `y4bitto8bit` does: each
   nibble g becomes the 5-bit level L = 2·g, so 0..30 (30 = white). Level 31 is the "REAGL white" marker.
2. `do_gettimeofday` is called; the result is unused (a timing leftover).
3. **Halo marking.** For every pixel with level < 29, each in-bounds 8-neighbour with level 30 is set to 31. So every white pixel that is
   8-adjacent to a non-white one becomes 31.
4. **Mask.** The old 4-bpp buffer is zeroed (`memzero(old4, w·h/2)`): the OLD image is overwritten by a mask. Then, for every byte inside the
   region (everything except the status-bar stripe `sb` and the bottom-bar stripe), with pixel index px from the table: the low nibble
   becomes 0xF if pixel px is 31, and the high nibble becomes 0xF if pixel px+1 is 31.

   | rot | rows y | bytes j of the row | px |
   |---|---|---|---|
   | 0 | all | `[sb/2, (w−bottom)/2)` | `y·w + sb + 2·(j − sb/2)` (NB: sb is odd, 83, so the mask is shifted 1 px) |
   | 1 | `[sb, h−bottom)` | all | `y·w + 2j` |
   | 2 | all | `[0, (w−sb)/2 − bottom)` (`bottom` counted in bytes here) | `y·w + 2j` |
   | 3 | `[bottom, h−sb)` | all | `y·w + 2j` |
   | other | — | — | nothing (mask all zero) |
5. `flush_cache_all()`: `cpu_cache.flush_kern_all` + outer flush + `flush_tlb_all` + isb.

What this means:
- **Input:** the previous (displayed) frame.
- **Output:** written in place into that buffer, as a 4-bpp **mask**. A nibble is **0xF** for a *halo pixel*: a pixel that was white
  (gray 15) on the old page and has at least one non-white (gray ≤ 14) neighbour among its 8. Every other nibble is 0.
- There is no neighbourhood rule beyond the 3×3, no second pass and no counting.
- The marking is order-independent: it only changes 30→31, and the trigger is `< 29`.

The quirks are [CONFIRMED-emu]:
- **One-pixel shift in rotation 0 with odd `sb`.** Byte 41 (pixels 82/83) receives the marks of pixels 83/84. Rotation 0 is also `check_rotate`'s fallback.
  So with `sb = 83` the whole rotation-0 mask is shifted 1 px to the left: pixel x gets the mark of pixel x+1.
- **Out-of-bounds read.** The last row then reads 1 byte past the scratch buffer. The read is harmless.
- **Rotation 2.** The bottom margin is applied in bytes, at the far end. It is a no-op on the RC2 (`bottom = 0`).

`reagl_1(u8 *e8, int h, int w)` (0xc060edc8) is the same halo marking applied in place to an already expanded 8-bit buffer. It has no mask step
and no region [CONFIRMED-emu]. **It has no caller** [CONFIRMED-dis: no BL/B in the whole text; the only data hit, 0xc0918b2c, is an entry of
`kallsyms_addresses` (0xc090d740 + 4·11497)], so it is an earlier version.

## 2. `enable_reagl` (0xc060c038)

`int enable_reagl(int enable, const u8 key[20])` [CONFIRMED-dis 0xc060c038–0xc060c114]:
1. `snprintf(s, 9, "%ld", tv_sec % 100000000)`, into a 12-byte zeroed buffer;
2. `s[0..7] ^= "onYxeNCy"`;
3. compare 20 bytes of `key` with `s[0..7]` followed by 12 zero bytes;
4. on a match, store `enable` to `G+0x48` and return 0. Otherwise return −1.

So it is a challenge/unlock that is valid only within the same second.
- **No caller:** no BL/B anywhere, and the only "pointer" is the kallsyms table entry 0xc0918ae4. It is not in `__ksymtab` [CONFIRMED-dis].
- **Nobody reads `G+0x48`:** the only `[Rn,#0x48]` accesses in the EBC driver are this store and a register write (`EBC_VCOM2`, 0xc060b454).
  `rk29_ebc_init` touches only `G+4/+8/+0x2c/+0x30/+0x44` [CONFIRMED-dis].
- REAGL is therefore **always on**, gated only by the userspace mode value 15. It is not toggled at boot, by ioctl or through sysfs.
- `support_regal` (sysfs) is hard-wired to 1, and ioctl 0x7004 returns the constant 3028 ([`abi/ebc-abi.md`](../abi/ebc-abi.md)).

## 3. Mode 15 end to end, and mode 16

1. **Userspace.** gralloc `fb_post` → ioctl `0x7001 SET_EBC_SEND_BUFFER` with `epd_mode = 15`. `ebc_io_ctl` (0xc06103c8–0xc06104b0) does only this:
   - looks up the buffer by phys;
   - stores `buf->mode = 15` and the window, ×3 for x on a colour panel;
   - `ebc_add_to_dsp_buf_list`;
   - wakes the thread.

   Mode 15 gets no special treatment here, and only mode 8 waits synchronously [CONFIRMED-dis].
2. **`ebc_thread` accepts the mode** if `mode ≤ 15 && (1<<mode) & 0x9f7e`: modes 1–6, 8–12 and 15 [CONFIRMED-dis 0xc060fa44–0xc060fa64]. Mode 0 (AUTO)
   has its own branch. **7, 13, 14 and every mode > 15, including 16, go to "ebc buffer mode error!"** (0xc060ff00).
3. **Mode 15 decision** (0xc060fc3c–0xc060fd88, [CONFIRMED-dis]; helpers [CONFIRMED-emu]):

   1. `n = check_part_mode_text(curr->virt, prev->virt, w/2, h)`: the number of differing 32-bit words (8 px) over the whole frame. It is
      stored as the diff count (`info+0x2bc`).
   2. `n == 0`: the frame is dropped (no refresh; curr becomes prev).
   3. `n < get_reagl_diffnum()` (200): `curr->mode = 3`, straight to display. That is PART = GC16, hardware partial, with no `check_part_mode()`.
   4. Otherwise `G->rot = check_rotate(curr->virt, w/2, h)`: the first all-black (byte 0x00) edge of the NEW frame; left column → 0, top
      row → 1, right column → 2, bottom row → 3, else 0. Prints `rotate = %d`.
   5. `G->pending = check_part_mode_text_rect(curr, prev, 83, w/2, h, rot)`: 1 if the stripe of 83 px (82 px = 41 bytes for rot 0/2) on that
      edge is identical. Prints `statusbar = %d`.
   6. If pending, `backupstatarbar(curr, prev, G->bak, 83, 0, w/2, h, rot)`: bak ← the curr stripe; the curr stripe and the prev stripe are
      set to 0xFF (white→white = no drive in GL16).
   7. Display: `ebc_register_update()`, `ebc_frame_start()`, wait for the frame end (timeout timer 3 s).
4. **`ebc_register_update`** (0xc060b610) [CONFIRMED-dis]:
   - Hardware mode bits for `ebc_dsp_ctl_set`:
     - modes 2, 3, 6 (A2, PART, BLACK_WHITE) get `DSP_CTRL bit 29` (`m_DISPLAY_UPDATE_MODE` in rychly `ebc.h`) plus bit 28;
     - modes 0, 9, 11, 12 get neither;
     - all others, **including 15 and 16**, get only bit 28 (`m_DISPLAY_MODE`; = hardware-LUT mode, since 0/9/11/12 are the software
       "direct"/auto paths) [names CONFIRMED-dis, meaning STRONG].
     - [STRONG] Bit 29 is the "partial" update: only pixels with old ≠ new are driven. So **REGAL runs as a full-window update**.
   - Mode → `lut_get` type: 0→5, 2/12→6, 5→1, 6→4, 10→3, **15→8**, **16→9**, everything else → 2.
   - Then `epd_lut_data_get_pvi_hard` (0xc0611b2c; `get_chip()` = 0):
     - type 8 → `get_lut_data_hard` with `get_lut_mode(8)` = `map_to_pvi_mode(8)` = 5 = wbf mode 4 (GLR16). This uses the even entries
       `tbl[f][2i][2j]` only, i.e. 16 levels;
     - type 9 → a zeroed 512 KB LUT plus `get_reagllut_data_hard`.

       It builds the hardware LUT from GLR16 too, but sets **only** `word[f·16+15] bits 30–31 = tbl[f][31][31]` (old 15 → new 15)
       [CONFIRMED-emu + dis, call at 0xc0611c70]. The frame count is the same as GLR16 (`n | n<<8`).
   - The LUT is rebuilt whenever the mode or the temperature changes, so a REAGL page turn rebuilds it twice.
5. **Pass 2** (0xc060ff38–0xc060ff94 → 0xc060fbe4) [CONFIRMED-dis]. After the pass-1 frame ends, `if (G->pending)`:

   1. `revertstatarbar(curr, G->bak, …)`, `G->pending = 0`, `curr->mode = 16`;
   2. `reagl_2(prev->virt, h, w, 83, 0, G->rot)`: prev, the page BEFORE the turn, becomes the halo mask;
   3. `ebc_register_update()`, `ebc_frame_start()`, wait. In hardware: old = the mask, new = the new page, LUT only (15,15) = `tbl[31][31]`.

   The hardware drives a pixel only if its old value is 15, its new value is 15, and its LUT entry is non-zero. Therefore pass 2 pulses exactly the
   pixels that meet all of these:
   - (a) white on the old page;
   - (b) next to old text;
   - (c) white on the new page;
   - (d) outside the status-bar stripe.

   The status bar is not driven in either pass:
   - pass 1: both images are white there;
   - pass 2: the mask is 0 there.

   Afterwards `prev = curr` with the restored stripe [STRONG].
6. **Cost per REAGL page turn:**
   - 2 × the GL16 frame count (38 frames at temperature range 8 for each pass);
   - two 512 KB LUT rebuilds;
   - a w·h expand plus halo pass on the CPU, and three full-frame compares.
   - Real time [GUESS ≈ 2 × 0.4–0.5 s; measure].

**Mode 16 (WAKEUP) from userspace is not a REAGL request in this kernel** [CONFIRMED-dis 0xc060fa48: `cmp mode,#15; bhi error`]. Mode 16 exists
only as the internal pass-2 marker. A buffer submitted with 16 (also 7, 13, 14, ≥17) takes the error path 0xc060ff00 → 0xc060ff98:
- `ebc_remove_from_dsp_buf_list(buf)` with **no `ebc_buf_release(buf)`**, so the buffer stays in-use forever [STRONG];
- `ebc_buf_release(prev)`. In the steady state `prev == curr` is the displayed image, so it is freed while it is still the "old" reference;
- `prev = curr`.

With a pool of 4, a few such submits would make `GET_EBC_BUFFER` (0x7000 → `ebc_empty_buf_get`) block forever [STRONG].

**Why this does not bite today:**
- In the stock gralloc, `requestEpdMode(16)` only sets a one-shot `cur_mode`, or with `ro.need.white.with.standby=y` while in standby it posts a
  white mode-8 frame instead ([`abi/ebc-abi.md`](../abi/ebc-abi.md) §3).
- The stock 4.2 SurfaceFlinger calls `requestEpdMode(mode)` → `setA2Region` → `setUpdateRegion` before every post, which overwrites `cur_mode`
  before the next `fb_post`. So 16 never reaches 0x7001.
- Device evidence: `eink mode = %d` is printed unconditionally for every frame (0xc060fa30/0xc060fa40). No device log contains 16, including
  the 4 Power wakes of a suspend/wake test.
- Rule for any userspace client: never pass 16, 7, 13, 14 or ≥ 17 to 0x7001.

This also corrects `abi/ebc-abi.md` §3 ("16 → type 9"): type 9 is reachable only from inside the kernel.

## 4. What REGAL changes visibly; tunables

Waveform entries (RC2 `ebc_waveform.bin`, temperature range 8, 38 frames; 1 = towards black, 2 = towards white; GLR16 ≡ GL16):

| entry | GC16 | GL16 / GLR16 |
|---|---|---|
| `[30][30]` white→white | full flash `1111111111111111 22222222 0000 22222222 00` | **no drive** |
| `[31][31]` REAGL white | all 0 | `00000000000000000 1212121212121212 2 0000` (9 W / 8 B pulses) |
| `[0][0]` black→black | driven | driven (same as GC16) |

- **Versus PART (mode 3: GC16, hardware partial):**
  - PART drives only the changed pixels, each with a full GC16 sequence (they flash).
  - Unchanged text is not refreshed, and ghosts of erased text stay as they are.
  - REGAL pass 1 drives every pixel in the window except white→white, so unchanged dark and grey text gets a GL16/GC16 sequence. Expect a mild flicker of
    unchanged text. The white background does not flash.
  - REGAL pass 2 then cleans the white fringe around the previous page's text with low-amplitude alternating pulses, which PART never does.
  - Updates smaller than 200 words are sent as PART anyway.
- **Versus plain GL16:** the kernel has no GL16-only mode. Mode 15 is "GL16 + edge cleanup", and it degenerates to plain GL16 (no pass 2) when the
  83-px stripe changed:
  - for example a clock or battery change in a black status bar;
  - or, when `check_rotate` finds no black edge (for example KOReader, or a light status bar), a change in the left 82 px of the native 1448×1072 frame (the panel is landscape-native).

  Which screen edge that is under `ro.sf.hwrotation=270` is [VERIFY].
- **A/B to confirm on the device:**
  - Same page, 10 turns each in mode 3, mode 15 and FULL. Photograph the result.
  - Watch whether unchanged dark text blinks under 15 but not under 3 (this proves the bit-29 meaning).
  - Watch whether the fringe around erased glyphs is cleaner after 15.
  - Also time one mode-15 update with dmesg (`eink mode = 15`, `rotate = %d`, `statusbar = %d`, `frame send end.` when the debug level is raised through `ebc_dbg`).
- **Tunables: none at run time.**
  - The Image's sysfs attribute table has only `support_regal` (0444, constant 1) and `ebc_dbg` (debug level) for EBC/REAGL.
  - There are no `__param_*` entries for ebc/epd/lut/reagl in kallsyms.
  - The thresholds are function returns: `get_reagl_diffnum` 0xc061083c = 200, `get_statusbar_hight` 0xc0610884 = 83, `get_bottom_hight` 0xc061088c = 0.
    They could only be changed by patching the Image ([DANGER]).
  - Policy that is left to userspace: whether to send 15 at all; making the status bar black on the edge `check_rotate` probes, so that pass 2 runs reliably
    while the clock is static; never sending 16.

## Other functions

- **`reagltopart(dst, src, nframes)`** (0xc06119b4) [CONFIRMED-emu]: copies a 5-bit LUT and zeroes the diagonal `tbl[f][k][k]`, i.e. turns it into a
  "partial" LUT where unchanged pixels are not driven. **It has no caller.** The only fallback to PART is the mode rewrite at 0xc060fc90.
- **`epd_lut_reagle`** (0xc061097c): returns 1 if waveform header byte 0x10 (mode version) ∈ {0x18, 0x19, 0x20}; the RC2 has 0x19. It is registered at
  `info+0x144` by `epd_lut_op_register` (ops base `info+0x140`, rk29_ebc_probe 0xc060d6cc). **No `[Rn,#0x144]` load exists in the driver**, so it is never
  called [STRONG].
- **`epd_lut_analying`**: waveform loader. It checks the CRC and the "Einks"/"OED" tag, XOR-descrambles 1 KB (0xaa55aa55/0x55aa55aa) and calls `zip_init`. It is
  not REAGL-specific despite the name.
- **`check_part_mode`** (PART/OED/DIRECT_PART path only, 0xc060fdbc): returns 0 if nothing changed. If every changed nibble is 0 or 15, it rewrites the mode
  to 6 (BLACK_WHITE, i.e. DU) [CONFIRMED-dis via decompile]. It is not used for mode 15.

## Open questions

1. The real meaning of EBC `DSP_CTRL` bits 28/29. There is no RK3026 EBC TRM; check on the device with the A/B above.
2. Which screen edge the rotation-0 "status bar" stripe is on under `ro.sf.hwrotation=270`, and whether the userspace status bar is black there.
3. (Latent) the mode-16 rejection/leak path, if anything ever passes raw 16.
4. Frame timing (ms per frame) for the two passes.

## Files

- `tools/kdis.py`: objdump wrapper with kallsyms annotation and a caller scan.
- `tools/ImportKallsymsRaw.java`, `tools/DecompileList.java`, `tools/reagl.list`, `tools/run.sh`: the Ghidra headless recipe for the raw Image.
- `tools/reagl_emu.py`: Unicorn byte-exact check of the leaf helpers against the reference implementation (the algorithm of §1 and §3, implemented in Python).
- Generated, not published (vendor code): `reagl.decomp.c`, `<fn>.s`, `callers.txt`.
