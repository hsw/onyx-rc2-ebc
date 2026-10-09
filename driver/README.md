# The stock RC2 E-Ink (EBC) driver: 0xc060b29c–0xc0617604

Static analysis, 2026-10-08. Target: the stock RC2 kernel Image (Linux 3.0.36+ built 2017-11-07, sha256 `47a13cf3…30af`, raw ARM,
VA = file offset + 0xc0408000; see [the top README](../README.md#the-analysed-kernel) for which addresses also hold in the public
2019 kernel), names from kallsyms recovered with [`kernel/extract_kallsyms.py`](../kernel/extract_kallsyms.py). Nothing was executed
natively and the device was not touched. Device facts quoted below come from device dmesg logs captured earlier.

This report covers the whole contiguous EBC span plus its initcalls. The REAGL part (`reagl_1/2`, `enable_reagl`, `check_rotate`,
`backupstatarbar`/`revertstatarbar`, `check_part_mode_text*`, `get_reagllut_data_hard`, the mode-15 path) is done in `../reagl/README.md`
and is only referenced here. The board side (`ebc_power_on/off`, `ebc_io_init`, the platform resources) is described in [onyx-rc2-hardware](https://github.com/hsw/onyx-rc2-hardware).

Confidence marks:
- [CONFIRMED-emu]: the stock function was run alone in Unicorn and matched a Python reference byte for byte (`tools/ebc_emu.py`).
- [CONFIRMED-dis]: read directly in the objdump listing at the given address.
- [CONFIRMED-log]: seen in a device dmesg log.
- [STRONG]: inferred from several confirmed facts.
- [VERIFY] / [GUESS]: open, or needs the device.

---

## 0. Summary

**What the span is.** 203 functions in these files, in link order:
- `hardware_ebc` core: 0xc060b29c–0xc06107c4, which now also contains `ebc_io_ctl`;
- `hardware_epd_public.c`: `set_epd_info` and the constant functions, 0xc06107c4–0xc0610894;
- `epd_lut`: 0xc0610894–0xc0612698;
- `epd_zip`: 0xc0612698–0xc0612854;
- `epd_spi_flash`: 0xc0612854–0xc06132a4;
- `check_auto_image_sARM` (hand-written asm): 0xc06132a4–0xc0614ab8;
- `buf_manage` and `buf_list`: 0xc0614ab8–0xc061574c;
- `bootani`: 0xc061574c–0xc06165d4;
- `rk29_ebc_dbg.c`: 0xc06165d4–0xc06166c0;
- `epdpower/tps65185.c`: 0xc06166c0–0xc0617604.

The probe banner is `V1.0.20 VERSION 20171023-23` (0xc09c1f8b). That string is not in the public `.uu`. The init banner `[RK_EPD]: version 1.02 20141016` is
unchanged, so the banner [`abi/ebc-abi.md`](../abi/ebc-abi.md) quotes says nothing about the generation.

**Versus the public rychly `.uu` objects** (older generation, GCC 4.6.x-google, with symbols; `tools/objdiff.py`, `§3`). Of the 203 functions in the span:
- **80 are the same code as the `.uu`.** They are byte-identical, or differ only in relocated data, `__func__` pointers, `__LINE__` constants or shifted `rk29_ebc_info` offsets.
- **36 are CHANGED.**
- **32 are NEW**, with no public code: REAGL, the hardware-LUT/PVI path, the C AUTO engine, `_ebc_frame_start`, `parse_mode_version`, …
- **55 come from public C files**: `hardware_epd_public.c`, `rk29_ebc_dbg.c`, `tps65185.c`. 7 of them were changed.
- **17 `.uu` functions have no kallsyms symbol in the Image** (removed or inlined): `win_cpy`, `new_buffer_refresh`, `get_lut_gray16_data`, the PVI panel helpers in spi_flash, …
- Liveness (BL/B and pointer scan): **29 functions have no reference at all**, and 14 more are unreachable on the RC2 because of compile-time constants.

**Attribution.** "NEW" means newer than the `.uu`, not necessarily ONYX. Only these carry ONYX-specific evidence:
- the `onYxeNCy` REAGL key;
- the status-bar height;
- the SPI-flash panel layout and the VCOM auto-fix;
- `/proc/panel_info`;
- the PMIC UPSEQ override;
- the `"ebc ___ onyx _____"` battery message (printed by the battery driver from the probe path, outside this span);
- 0x7004.

The LUT/PVI rewrite, `parse_mode_version` and the C AUTO engine look like a later Rockchip SDK generation [GUESS].

**The architecture in one paragraph** (`§2`):
1. ioctl 0x7000 hands out one of **4 buffer slots of w·h bytes** (8 bpp capacity; a 4-bpp frame uses the first half).
2. 0x7001 queues the slot with a mode and a window and wakes **`ebc_thread`**.
3. The thread pre-processes per mode:
   - AUTO: 4→8-bit expansion;
   - PART/OED_PART/DIRECT_PART: `check_part_mode` drops unchanged frames and turns pure black/white changes into DU;
   - REGAL: the two-pass REAGL.
4. It powers the panel up if needed (wake lock `ebc`, board power, TPS65185 on).
5. `ebc_register_update` reads the PMIC temperature over I²C, sets `DSP_CTRL` (LUT or direct mode, partial bit), sets the old/new image
   addresses, and gets a LUT. **The LUT is rebuilt (512 KB) every time the EPD mode or the temperature range changes.** The waveform is
   re-decoded on every update.
6. `ebc_frame_start` then runs one of three engines:
   - **hardware LUT**: the EBC looks up old→new per pixel in a 16-word-per-frame LUT SRAM, loaded in 64-frame chunks;
   - **software direct**: modes 9, 11, 12. The CPU computes 2-bit drive frames into two ping-pong buffers, one frame per IRQ, on the SCHED_FIFO-99
     kthread `ebc_auto_taskup`;
   - **AUTO**: per-pixel asynchronous waveforms, also on the CPU.
7. The thread sleeps until frame-end or the 3-s timeout.
8. When the queue is empty it **powers the PMIC down immediately** and sleeps.
9. On the next post it **busy-waits 100 ms (`mdelay(100)`)** before it looks at the queue.

**Top findings** (`§8`):
- **Every idle→busy transition costs 100 ms of busy-wait** in `ebc_thread` [CONFIRMED-dis 0xc061011c]. That is every time the queue drains, so two page turns 1 s apart each pay the 100 ms spin plus the ~25 ms PMIC power-up. It adds a PMIC power-up and, on any mode change, a 512 KB LUT
  rebuild. Steady-state GC16 throughput is one update per ~0.47 s [CONFIRMED-log].
- **Modes accepted from userspace: 0–6, 8–12, 15.** 7 (TEXT), 13, 14 and ≥16 take the error path and leak a buffer.
  - The public `.uu` accepted 0–12, so **EPD_TEXT (7) is newly rejected**.
  - This corrects `abi/ebc-abi.md`'s "7 → type 2" (`§7`).
- **The LUT-mode window start address uses a hard-coded stride of 1024 px** (`ebc_image_addr_set`, `(x1 + y1·1024)/2`). Width 1448 needs `y1·1448`.
  - The arithmetic is [CONFIRMED-dis]. The effect, **a LUT-mode update with a sub-window and `y1 ≠ 0` fetches the wrong rows**, is [STRONG]: it assumes the EBC fetches from MST0/1 with no other offset, `§9` item 1. The same code is in the `.uu`.
  - The stock gralloc can send mode 1 with an A2-exit window when auto-full fires. A client must send LUT modes with `y1 = 0` (normally the full screen).
- **PART (3), OED_PART (10) and DIRECT_PART (11) frames with no changed pixel are dropped in the kernel, before power-up.** Frames whose changed pixels are all
  pure black/white are silently promoted to **DU** [CONFIRMED-log: 79 DU LUT builds with no mode 6 ever sent].
- **Temperature ≥ 43 °C selects the coldest waveform (0–3 °C range)**: `get_lut_temp` falls through and returns the caller's r3 = 0 [CONFIRMED-dis].
  Temperatures < 0 °C read as > 50 and are clamped to 25 °C. The temperature is an I²C conversion (+10 ms `msleep`) on **every** update.
- **The waveform comes from the ramdisk file `/ebc_waveform.bin`.**
  - `epd_lut_from_file_init` does `filp_open` and reads `i_size` bytes into the 1 MB `waveform_addr=0x7ff00000` window, with no size check and no CRC check
    [CONFIRMED-dis 0xc061247c, CONFIRMED-log CRC `bd db 33 c6`].
  - If the file or `waveform_addr` is missing, the driver falls back to a built-in V110 array for a different panel.
  - The panel's own SPI flash holds another waveform (R177) that is never used for display.
- **Queued frames are collapsed.** `ebc_add_to_dsp_buf_list` drops every queued, not-yet-started frame (except FULL/A2/BLOCK/FULL_WIN) when a newer frame arrives.
  Together with the 100 ms busy-wait this is a kernel-side debounce: a client cannot assume every posted frame reaches the panel [CONFIRMED-dis, `§2.2`].
- **No power-off delay.** The vdd timer is re-armed to ~15 days before every frame, and `rk29_ebc_set_auto_power_off` has no caller. So the PMIC is cycled per update
  burst, and the `ebc` wake lock is held only while frames run.
- **The 5 hand-written asm pixel routines are dead.** AUTO uses the C `get_auto_image_new_hard`.
  - Also dead (no reference at all): `reagl_1`, `enable_reagl`, `direct_mode_data_change_text`, `set_window_part`, `rk3026_readefuse`, `get_lut_reset/gray2/grayA2_data`.
  - `epd_lut_data_get` and `epd_lut_data_get_pvi` are only *unreachable*: their pointers exist, but they are selected out by `support_pvi_waveform()` = 1 and `get_chip()` = 0.

---

## 1. Method and tools (all in `tools/`; their outputs are working files and are not published)

| Step | Tool | Output |
|---|---|---|
| uudecode the public objects (never executed) | `run.sh` step 1 | `uuobj/*.o`, `uuobj/*.dis` (objdump -d -r) |
| Ghidra 12.1.4 headless on the raw Image: BinaryLoader at 0xc0408000, kallsyms labels, a function at every t/T symbol in the span + 6 initcall/devinit entries, asm labels skipped | `run.sh` → `ImportKallsymsRaw.java` (extended copy of `../reagl/tools/`), `DecompileList.java` | `ebc-image.decomp.c`, `ebc-image.annot.c` (string-annotated by `annotate_decomp.py`) |
| Ghidra on the 8 public objects (ELF loader applies relocations → named calls) | `DecompileAllObj.java` | `uu-objects.decomp.c` |
| objdump listing per function with kallsyms/string annotation (the arbiter) | `kdis.py` (copy of `../reagl/tools/kdis.py`) | `s/<fn>.s`, `s/asm-block.s` |
| Function-by-function diff stock vs `.uu`: word compare, relocations resolved by **name** (call target, function pointer, string content, `__func__` content), local branches by target name; instruction-level diff for changed ones | `objdiff.py` | `objdiff.tsv`, `objdiff-v.txt` |
| Liveness: BL/B scan of the whole text + pointer scan outside the kallsyms table | `inventory.py` | `inventory.tsv` |
| Unicorn byte-exact checks against Python references, with mutation checks | `ebc_emu.py` (PEP 723, `uv run --script`) | console |

Ghidra mistakes caught by objdump: see `§2.11` and `../reagl/README.md`. The decompile of `rk29_ebc_irq_function`/`rk29_ebc_frame_timeout`
is tail-merged and wrong in places. The listing is authoritative.

---

## 2. Architecture

### 2.1 Objects, threads, timers, wait queues

| Object | Where | What |
|---|---|---|
| `/dev/ebc` | `rk29_ebc_init` 0xc0419b1c (initcall 6s): chrdev 261:0, class `ebc_class`, fops 0xc08e50d0 = {`ebc_open`, `ebc_mmap`, `unlocked_ioctl = ebc_io_ctl`} | [CONFIRMED-dis] |
| platform driver `rk29-ebc` | 0xc0a8f764: probe/remove/**shutdown (new)**/suspend/resume | [CONFIRMED-dis] |
| `ebc_thread` | kthread, default priority, created at the end of probe | the state machine (`§2.4`) |
| `ebc_auto_taskup` | kthread, **SCHED_FIFO prio 99**, `ebc_auto_tast_function` | computes the next software frame for AUTO (0) and direct modes (9/11/12); woken by the frame-end IRQ via `up(auto_sem)` |
| `info->work` (+0x250) | default workqueue, func = `ebc_frame_start` | reloads the next 64-frame LUT chunk from IRQ context |
| `bootup_ani_wq` (+0x2b8) | `ebc_bootup_work_fun` | boot animation frames |
| `vdd_timer` (+0x1fc) → `rk29_ebc_vdd_power_timeout` | armed at probe for jiffies+0x0fffffff, re-armed by `ebc_thread` to +`msecs_to_jiffies(0x4fffffff)` (~15.5 days at HZ 100) before every frame | **never fires in practice** [STRONG] |
| `frame_timer` (+0x234) → `rk29_ebc_frame_timeout` | 3000 ms around every LUT/direct update, then pushed to ~15 days | watchdog: prints `=========frame timeout.============` and runs the same completion as the IRQ |
| `boot_logo_timer` (+0x218) → `rk29_ebc_bootup_timer` | boot animation | |
| wait queues | 0xc0a8f75c "buffer posted" (thread idle), 0xc0a8f7e8 "frame done", 0xc0a8f810 "BLOCK done" (ioctl mode 8), semaphore 0xc0a8f7d4 (auto task) | names by role; `.data` layout differs from the `.uu`, so the `.uu` names do not map by offset |
| wake lock `ebc` (+0x1a0) | taken in `ebc_power_set(on)`, released in `ebc_power_set(off)` | visible as "ebc" in the suspend test log [CONFIRMED-log] |

### 2.2 Buffers and the userspace contract

- **Pool.** `rk29_ebc_probe` ioremaps the platform resource `"ebc disp buf"` with **MT_DEVICE_CACHED** (type 2). That memory is 8 MB reserved at 0x7f700000 [CONFIRMED-log
  `memory reserve … <ebc disp buf>`].
  - It is set to 0xFF, and then `ebc_buf_init(phys, virt, len = vir_w·vir_h·4, slot = bpp·vir_w·vir_h/8)` runs with `bits_per_pixel` (+0x2c) = **8**
    [CONFIRMED-dis 0xc060d728–0xc060d7c0].
  - That gives **4 slots of w·h = 1,552,256 bytes** each. A 4-bpp frame (w·h/2) uses the first half. The second half is the in-place 8-bpp
    expansion that AUTO needs.
  - The `.uu` used bpp 4 and a kmalloc'ed pool (4 slots of w·h/2).
- **mmap.** `ebc_mmap` maps the pool base for the full VMA length, **with no bounds check** (as in the `.uu`), now `pgprot_writecombine` (`& ~0x3c | 4`; the `.uu` was uncached).
  - Userspace writes go through a write-combining mapping.
  - The kernel reads the same memory through a *cached* mapping. Only the new CPU paths (`reagl_2`, `y4/y8bitto*`, direct modes, `backupstatarbar`, …) call
    `flush_cache_all`. `check_part_mode` reads without a flush [STRONG; whether stale lines ever matter is GUESS].
- **0x7000 GET_EBC_BUFFER.**
  - Stops the boot animation if it is running.
  - `ebc_empty_buf_get` **blocks** until a slot is free.
  - Returns `offset` plus the panel fields.
  - Calls `rk29ebc_notify(EBC_ON)` if the driver is idle.
- **0x7001 SET_EBC_SEND_BUFFER.**
  - Finds the slot by `base + offset` and stores `mode` and the window. x is ×3 on a colour panel.
  - Calls the empty `ebc_io_ctl_hook`, then `ebc_add_to_dsp_buf_list`, and wakes the thread.
  - Mode 8 then sleeps (interruptible) until the thread has shown it.
- **Queue collapsing** (`ebc_add_to_dsp_buf_list`, SAME as `.uu`) [CONFIRMED-dis]. Suppose the new frame's mode is not one of 2, 6, 8, 12, and the list has more than one entry. The
  function then walks from the tail down to index 1; index 0, the frame the thread holds, is never touched:
  - every queued frame whose mode is not 1, 2, 8 or 9 is removed **and released**;
  - after the first kept entry, older FULL (1) entries are dropped too;
  - the new frame is then appended.

  So PART/AUTO/REGAL/DU frames that the thread has not started are replaced by the newest one. A2 (2), BLOCK (8) and FULL_WIN (9) are never dropped.
  Gralloc's 6→2 A2-entry pair is safe, because a 2 never triggers the walk.
- **`ebc_empty_buf_get`** sleeps interruptibly. **After a signal it calls itself recursively**: a real `bl`, not a loop. With all 4 slots busy (for example after the
  mode-7/13/14/16 leak) and a pending signal, the kernel stack overflows [STRONG; same in `.uu`].
- **0x7004** returns 3028; **0x7002/0x7003** as in the public source ([`abi/ebc-abi.md`](../abi/ebc-abi.md) is correct there).
- **Buffer life cycle in `ebc_thread`**:
  - `curr` = the buffer being shown; `prev` = the image on the panel ("old").
  - After each update: `remove_from_dsp_list(curr)`, `ebc_buf_release(prev)`, then `prev = curr`.
  - The very first frame skips the release (`first_in`, +0x1f8).
  - So at steady state, **one slot is pinned as "old"**. Userspace can have at most 3 in flight: queued, being shown, or being written.

### 2.3 The frame pipeline

```
gralloc ioctl 0x7001 ─► dsp list ─► ebc_thread ─► per-mode pre-processing ─► power on (if off)
   ─► ebc_register_update: temp = tps65185 (I2C, +10 ms) ─► DSP_CTRL ─► MST0/MST1 = old/new (+window offset) ─► lut_get(type, mode, temp)
   ─► ebc_frame_start (info->work): engine by mode
        HW LUT:  copy ≤64 frames ×16 words into EBC LUT SRAM (regs +0x1000..+0x1fff), WIN_DSP/WIN_ACT/DSP_ST from the window, DSP_START
        direct:  CPU computes frame 0 and 1 into auto_direct_buffer0/1 (2 bpp), WIN_MST0 = buffer phys, start
        AUTO:    CPU computes the first per-pixel frame, start
   ─► IRQ (EBC_INT bit 1) → rk29_ebc_irq_function:
        HW LUT:  frames left (>64 case) → queue_work(next chunk)  else done
        direct:  frame_left-- → wake auto task (it starts the precomputed buffer, computes the next) else done
        AUTO:    flag + wake auto task (continues while any pixel is still mid-waveform or a new frame arrived)
   ─► done: ebc_status = 0, irq_status = 1, wake "frame done" and "idle" queues ─► ebc_thread releases prev, loops
```

- **Frame time.** The panel timing in the Image data `0xc0a8faa8` [CONFIRMED-dis] is:
  - **1448×1072**, hsync 17, hstart 8, hend 55;
  - vsync 2, vstart 4, vend 4;
  - frame_rate 85, pixclock 40 MHz, `rotate` 270, gdck_sta 100, lgonl 281.

  At 4 px per clock that is (362+80)·1082/40 MHz = **11.96 ms per frame (83.6 Hz)** [STRONG]. So:
  - GC16 at range 8 (38 frames) takes 0.454 s;
  - device back-to-back PART updates are 0.47 s apart [CONFIRMED-log: device dmesg, 10.03→13.34 s];
  - the ~15 ms gap is the I²C temperature read plus `decodewaveform_19` plus the LUT build ("eink mode" → "lut_temp" = 15.5 ms on the device).
- **LUT chunking.** The EBC LUT SRAM holds 64 frames.
  - Longer waveforms are split: INIT at range 8 has 113 frames, GC16 at ranges 0–5 has 66–131.
  - The IRQ queues `info->work`, which copies the next 64 frames and restarts (`_ebc_frame_start(64, 1)` for a middle chunk, `(n, 0)` for the last).
  - Bit 27 of DSP_CTRL is set for the middle chunks (`m_VCOM_MODE` in rychly `ebc.h`; its meaning here is [GUESS]: "keep VCOM/continue").
  - So there is a pause of one IRQ+workqueue latency between chunks [STRONG].

### 2.4 `ebc_thread` state machine and the mode table

Per dequeued buffer (0xc060f9d8 loop) [CONFIRMED-dis]:
1. `mod_timer(vdd_timer, ~15 days)`; enable clocks.
2. `printk("eink mode = %d")`. It is unconditional, at KERN_WARNING level, so the console log gets one line per frame.
3. The mode filter `mode ≤ 15 && (1<<mode) & 0x9f7e` (1–6, 8–12, 15), or mode 0. Anything else → `ebc buffer mode error!` (see `../reagl/README.md` §3 for the leak).
4. **AUTO (0):**
   - set `height/width`;
   - `y4bitto8bit(buf, buf)` expands the frame in place to 8 bpp; `curr = buf`; `buffer_need_update = 1`;
   - **if an AUTO refresh is already running, stop here.** The running per-pixel engine picks the new target up ("pipelined" updates);
   - otherwise `status = 1`, mark all rows dirty (G+0x4c, `memset(…,1,vir_h)`), expand `prev` into `auto_image_old` (+0x170) unless prev was AUTO, then
     `ebc_register_update` and `ebc_frame_start`.
5. **Other accepted modes:**
   - if an AUTO refresh is running and not finished, wait for "frame done";
   - `curr = buf`;
   - mode 16 (internal REAGL pass 2 only) → `reagl_2`;
   - otherwise, if `prev` was AUTO, `y8bitto4bit(prev)` back to 4 bpp;
   - mode 15 → the REAGL decision (`../reagl/README.md`);
   - modes 3, 10, 11 → `check_part_mode(curr, prev, w, h, &mode)`: returns 0 (frame dropped) if nothing changed, and rewrites mode → 6 (DU) when every
     changed pixel is pure 0/15 (`§2.6`);
   - power on if off;
   - `ebc_register_update` (returns −1 → frame dropped);
   - `frame_total = lut.frame_num`;
   - `ebc_frame_start`, 3 s watchdog, wait for "frame done".
6. **Completion:**
   - mode 8 → wake the blocked ioctl;
   - REAGL pass 2 pending → run it (`../reagl`);
   - else unlink `curr`, release `prev`, `prev = curr`.
7. **Queue empty:**
   - if AUTO is still running, wait for it;
   - then **power off immediately** if on (`ebc_ops->power_set(info, 0)`) and `rk29ebc_notify(EBC_OFF)`;
   - wait for the "buffer posted" flag;
   - **`mdelay(100)`** (100 × `__const_udelay(0x066665b0)` = `udelay(1000)` at HZ 100; a busy loop, 0xc061011c) [CONFIRMED-dis]. The `.uu` has no such delay.
   - So the first update after idle is late by ≥100 ms plus the PMIC power-up (~25 ms).
   - Frames posted within that window are **collapsed** by `ebc_add_to_dsp_buf_list` (`§2.2`), so only the newest PART-class frame survives.

**Mode table** (stock kernel; columns: what `ebc_thread` does, the `DSP_CTRL` bits from `ebc_register_update` 0xc060b640–0xc060b6b4, the LUT type and
waveform, the engine) [CONFIRMED-dis unless marked]:

| mode | name (`ebc.h`/View) | thread | DSP_CTRL | lut type → wbf mode (MV 0x19) | engine | notes |
|---|---|---|---|---|---|---|
| 0 | AUTO | async per-pixel path | none (direct) | 5 → GC16 + DU merged (`§2.6`) | CPU, `get_auto_image_new_hard` per frame | new frames merge into a running refresh |
| 1 | FULL | — | bit28 | 2 → GC16 | HW LUT, full window | |
| 2 | A2 | — | bit29+28 | 6 → A2 (wbf 6) | HW LUT, partial | |
| 3 | PART | `check_part_mode` (drop / →6) | bit29+28 | 2 → GC16 | HW LUT, partial | default of the stock gralloc and SurfaceFlinger |
| 4 | FULL_DITHER | — | bit28 | 2 → GC16 | HW LUT | dithering is gralloc's |
| 5 | RESET | — | bit28 | 1 → INIT (wbf 0) | HW LUT (113 fr. at range 8 → 2 chunks) | first frame at boot |
| 6 | BLACK_WHITE | — | bit29+28 | 4 → DU (wbf 1) | HW LUT, partial | also the target of the PART→DU promotion |
| 7 | TEXT | **rejected** (error path, leak) | (bit28) | (2) | — | `.uu` accepted it; `abi/ebc-abi.md` says type 2 (superseded, `§7`) |
| 8 | BLOCK | ioctl sleeps until shown | bit28 | 2 → GC16 | HW LUT | |
| 9 | FULL_WIN | — | none (direct) | 2 → GC16 | **CPU direct**, `full_win_mode_data_change`, honours the window | used by gralloc on A2 exit |
| 10 | OED_PART | `check_part_mode` | bit28 | 3 → **no LUT built** (DU4 decoded, then zeroed) | HW LUT of zeros | draws nothing (`§2.5`) |
| 11 | DIRECT_PART | `check_part_mode` | none (direct) | 2 → GC16 | **CPU direct**, `direct_mode_data_change`, full frame, unchanged pixels 0 | |
| 12 | DIRECT_A2 | — | none (direct) | 6 → A2 | **CPU direct** | |
| 13, 14 | STANDBY/POWEROFF (gralloc only) | **rejected** | (bit28) | (2) | — | gralloc never sends them (it converts to 8 / 1) |
| 15 | REGLA | REAGL two-pass | bit28 | 8 → GLR16 (wbf 4) | HW LUT | `../reagl/README.md` |
| 16 | (internal) | pass 2 only; **rejected from userspace** | bit28 | 9 → GLR16 `[31][31]` only | HW LUT | |

- **Bit 28** = LUT (waveform) mode; without it the EBC takes 2-bpp drive data (the direct/AUTO engines) [STRONG].
- **Bit 29** = partial: only old ≠ new pixels are driven [STRONG; device A/B still to do, `../reagl` open question 1].
- Bit 27 is always set by `ebc_register_update` and toggled per chunk by `_ebc_frame_start`.
- `ebc_dsp_ctl_set` always ORs `0xc0030000` (`DISPLAY_SWAP` = 3, SCLK divide 3).

**Changes versus the `.uu`** (`ebc_register_update` and `ebc_thread`):
- mode 7 has moved out of the partial set (`.uu` mask 0xcc → 0x4c);
- 15 and 16 were added;
- **the LUT-type numbering changed.** `.uu`: AUTO 8, A2 9, BW 7, OED 6, matching the public `epd_lut_type` enum. Stock: AUTO 5, A2 6, BW 4, OED 3,
  REAGL 8/9. `get_lut_mode` maps the new numbers onto the waveform's mode table.

### 2.5 LUT pipeline, waveform decode, temperature

`ebc_register_update` → `info->lut_ops.lut_get` (+0x140) = **`epd_lut_data_get_pvi_hard`** (0xc0611b2c):
- `epd_lut_op_register` picks it because `support_pvi_waveform()` = 1 and `get_chip()` = 0.
- `epd_lut_data_get` (non-PVI) and `epd_lut_data_get_pvi` (chip 1) are selected out and so dead.
- `+0x144` gets `epd_lut_reagle`, which is never called.

1. **`get_lut_mode(type)`** calls `parse_mode_version(wf)` every time. It fills an 8-entry index table at 0xc0d23260 from header byte 0x10:
   - MV 0x19 → `{0,1,7,2,3,4,5,6}`;
   - 0x12, 0x18, 0x20 and 0x23 have their own tables;
   - an unknown version prints `*[EBC ERROR]* : Unknow waveform version`.

   Then type→index: 1→0, 2/5→3, 3→2, 4→1, 6→7, 8/9→`map_to_pvi_mode(8)` = 5. **Type 7 → an uninitialised index** (dead path).

   For MV 0x19: RESET → wbf 0 INIT, GC16 → wbf 2, type 3 → wbf 7 DU4, DU → wbf 1, A2 → wbf 6, REAGL → wbf 4 GLR16. This matches
   `abi/ebc-abi.md` §6 [CONFIRMED-dis].
2. **`get_lut_temp(wf, temp)`**: the first i with `temp < tbl[0x30+i]`, minus 1, for i ≤ `wf[0x26]` (13 on the RC2).
   - **If temp ≥ tbl[13] = 43 °C the loop ends and the function returns its incoming r3.** At the only live call site r3 = 0, because `parse_mode_version`
     `push`/`pop`s r3. So 43–50 °C uses **range 0 (0–3 °C)**: GC16 131 frames instead of 38, with cold-panel drive [CONFIRMED-dis 0xc06116b8, 0xc0611b58,
     0xc0611608; emulation `§5`].
   - Unchanged from the `.uu`.
3. **`get_lut_frame(wf, wbfmode, range)`**:
   - verifies the 8-bit checksums of the mode-table entry (at `wf + wf[0x20] + 4·mode`; **only the low byte of the 24-bit `wmta` is used**) and of the
     temperature pointer;
   - prints `waveform crc error!` and returns −1 on a mismatch;
   - otherwise calls `decodewaveform_19` (MV 0x18/0x19/0x20) or `decodewaveform` (others).

   **The waveform is decoded on every `lut_get`**, even when the cached LUT is reused.

   `decodewaveform_19` writes the 5-bit transition table `tbl[f][old][new]` (0x400 B per frame) to 0xc0ca3260 and returns the frame count (> 0x200
   → an error printk) [`§5` for the emulation].
4. **Cache:** if `(mode, range)` equals the cached pair (0xc0ca3258/0xc0ca325c), return. **The key is the EPD mode, not the LUT type.** So FULL → PART
   (both GC16) rebuilds [CONFIRMED-log: `eink mode = 1` then `eink mode = 3` each followed by `lut_temp = 8, lut_mode = 2 lut_frame = 38`].
5. **Rebuild:**
   - `printk("lut_temp = %d, lut_mode = %d lut_frame = %d")`;
   - allocate (once) and `__memzero` 512 KB at `lut_data.data` (+0x15c);
   - then by type:
     - 1, 2, 4, 6, 8 → `get_lut_data_hard`: `word[f·16+old] |= tbl[f][2·old][2·new] << 2·new`, i.e. 16 levels from the even 5-bit indices; `frame_num = n`;
     - 5 (AUTO) → `get_lut_data` (a raw 5-bit copy of GC16, 0x400 B per frame, diagonal kept for tag 0) plus `get_lut_data_a2_bk` (DU codes into the target-0/30
       columns); `frame_num = gc16 | du << 8`;
     - 9 → `get_reagllut_data_hard`;
     - **3 and 7 → nothing.** The LUT stays zero and `frame_num` stays stale. This matches the waveform decode in [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform).
6. **Temperature source:**
   - `info->temp_ops` (+0x150) = `tps65185_temperature_get`, which calls `papyrus_hw_read_temperature`: write TMST1 = 0x80 (start), poll up to 50 times for "done",
     `msleep(10)`, then read TEMP as a **signed byte** [CONFIRMED-dis 0xc0616e34].
   - `ebc_register_update` treats it as unsigned and clamps anything > 50 to 25 (`temperature = %d, out of range0~50 ,use 25`), **so −1 °C → 25 °C**.
   - If the PMIC is not initialised, the value is uninitialised stack (the r3 slot pushed at 0xc060b610) [CONFIRMED-dis].
   - The temperature is read on every update; there is no caching.
   - The waveform's own range boundaries are `0,3,6,…,33,38,43,48` (14 ranges).
7. **Notes from the waveform decode** (format and per-mode tables: [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform)):
   - The non-hard getter `epd_lut_data_get_pvi` (unreachable on the RC2) has the same hole for types 3/7, and also for type 9.
   - Making DU4 (type 3) draw would need the type-3 jump-table entry of `epd_lut_data_get_pvi_hard` pointed at the `get_lut_data_hard`
     case (0xc0611c78); `get_lut_data_hard` handles any wbf mode index generically. That is a kernel patch ([DANGER]).
   - `get_lut_gray4_data` exists, but it is a 4-byte stub (`bx lr`) and nothing calls it. The rk356x PVI decoder has the same gap:
     it prints `unsupport WF GRAY4` and builds nothing.

### 2.6 The CPU engines

All of these are [CONFIRMED-emu]; case counts are in `§5`.

- **`check_part_mode(new, old, w, h, &mode)`** (SAME as `.uu`), modes 3/10/11:
  - returns 0 if no 32-bit word differs, and the thread then drops the frame **before** power-up and LUT work;
  - sets `*mode = 6` (DU: 22 instead of 38 frames at range 8, no grey targets) iff every changed pixel's **new** value is 0 or 15. The old value is not checked;
  - stops at the first grey change.
- **`full_win_mode_data_change(dst2bpp, new4, old4, info)`** (mode 9):
  - the LUT frame is `lut_data.data + (frame_total − frame_left)·64`;
  - inside the buffer window, every pixel gets `(word[old] >> 2·new) & 3`, **unchanged pixels included** (a GC16 flash of the window). Outside the window the drive is 0;
  - the window bounds are **inclusive**: x1/4 ≤ j ≤ x2/4 and y1 ≤ y ≤ y2. So an exclusive gralloc `x2/y2` drives up to 3 extra px and one extra row;
  - calls `schedule()` every 400 rows and flushes the caches at the end.
- **`direct_mode_data_change`** (modes 11/12): the same lookup over the whole frame, ignoring the window, with 0 for an unchanged 4-px group or pixel. **Bug (also in the
  `.uu`):** pixels 1–3 of each group are compared as `old == 2·new`. Inside a changed group:
  - unchanged non-black pixels are re-driven (they flash in mode 11);
  - changed pixels with old = 2·new (1←2, 2←4, …, 7←14) are **not** driven, so they stay as stale grey.

  Pure black/white content is unaffected, and so is A2 (12).
- **AUTO** (`auto_caclu_next_frame` → `get_auto_image_new_hard(dst, new8 = curr, latched = +0x16c, old = +0x170, counters = +0x174, info)`):
  - every pixel runs its **own frame counter**;
  - an idle pixel latches the current target and, if it differs from its old level, starts at frame 0;
  - a running pixel advances until the budget for its target. The budget is the DU frame count (`info+5`) for black/white targets and the GC16 count (`info+4`) for greys;
    the table is GC16 with DU columns for targets 0/30 (`get_lut_data` + `get_lut_data_a2_bk`);
  - rows whose dirty flag (G+0x4c) is 0 and whose target row is unchanged are skipped;
  - the refresh runs while any pixel is active (`info+6`) or a new frame arrived (`+0x24`);
  - a pixel takes a new target **only when it is idle**, so a fast change sequence finishes each waveform first;
  - this replaces the `.uu`'s `get_auto_image_sARM` (asm). **Gralloc on the RC2 does send AUTO (0)** when a layer requests it (variant 3 passes 0 through; `abi/ebc-abi.md` §3).
- **The five asm routines** are dead. They were verified anyway (`§5`). In `check_auto_image_sARM`/`get_auto_image_sARM` the only change versus the `.uu` is that
  `mov r7,#0` moved past three instructions that do not touch r7, which is semantically neutral.

### 2.7 A2, auto-full, REAGL

- **A2 in the kernel is only a waveform choice.**
  - Mode 2 → HW LUT A2 with the partial bit.
  - Mode 12 → CPU direct with the A2 LUT.
  - There is no A2 region state, no entry/exit logic and no dithering in the kernel. All of that is in the stock userspace gralloc (`abi/ebc-abi.md` §5).
- **Auto-full (periodic FULL) does not exist in this kernel.** It is gralloc's `autofull_max` counter.
- **REAGL:** see `../reagl/README.md`. In short: mode 15 → GL16 pass + a halo-cleaning internal mode-16 pass. Fewer than 200 differing words → PART. The 83-px stripe gates pass 2.

### 2.8 Power

- `ebc_power_set(info, on)` [CONFIRMED-dis 0xc060bb5c]:
  - **on:** `wake_lock(ebc)`, then the board `power_on` (platform data +8), the clocks (`dclk_ebc`, `hclk_ebc`, `aclk_lcdc1`, `pd_lcdc1`), then
    `tps65185_power_on`, and `power_status = on`;
  - **off:** the reverse: `tps65185_power_down`, the clocks, the board `power_off`, `wake_unlock`.
  - The board hooks (described in [onyx-rc2-hardware](https://github.com/hsw/onyx-rc2-hardware)):
    - `ebc_power_on` switches ACT8931 LDO4 (3.0 V panel logic) on and muxes the EBC pins;
    - `ebc_power_off` parks the pins low and switches LDO4 off;
    - neither has delays.

    Each update burst is therefore: LDO4 + pins, then the TPS65185 rails (~25 ms), then the frames, then everything off again.
- **When it happens:**
  - on: in `ebc_thread` before the first frame of a burst;
  - off: right when the queue is empty (`§2.4` step 7).
- **There is no hold time.**
  - `rk29_ebc_vdd_power_timeout` would do the off sequence minus the PMIC, but its timer is always pushed ~15 days out.
  - `rk29_ebc_set_auto_power_off` (would force power on) and `rk29_ebc_set_gdpwr0` (`EPD_CTRL` power bits) have **no caller**.
- **Suspend/resume (platform PM):** print `%s ebc_status = %d` and call the board `suspend`/`resume` hooks (platform data +0x18/+0x1c).
  - The board hooks are 8-byte stubs at 0xc045de90/0xc045de98 (board file; see onyx-rc2-hardware).
  - There is no queue drain and no wait for a running update [CONFIRMED-dis; CONFIRMED-log `ebc_suspend ebc_status = 0` in
    a device suspend/wake test log].
- **`ebc_shutdown`** (new, `.shutdown`) only prints.
- PMIC details (sequencing, VCOM, standby): `§2.10`.

### 2.9 Waveform source and boot sequence

- **Source** [CONFIRMED-dis + CONFIRMED-log: device boot dmesg 0.0–4.14 s]:
  - the loader passes `waveform_addr=0x7ff00000`, and the kernel reserves 1 MB `<ebc waveform buf>`;
  - the platform resource `"ebc buf"` points at it;
  - probe ioremaps it (+0x190) and, since `get_lut_position()` = 3 (LUT_FROM_WAVEFORM_FILE), calls `epd_lut_from_file_init(buf)` (SAME as `.uu`).
- **What `epd_lut_from_file_init` does:**
  - `filp_open("/ebc_waveform.bin")` from the initramfs;
  - one `vfs read` of `i_size` bytes into the window, **with no bound against the 1 MB**;
  - `filp_close`;
  - tail-call `epd_lut_from_nand_init(buf)`.
- **What `epd_lut_from_nand_init` does** (changed: it now copies the WBF panel string):
  - stores the waveform pointer (G+0x74 = 0xc0ca3254);
  - logs `waveform info: bd db 33 c6` (the file CRC 0xc633dbbd, the same as the ramdisk `ebc_waveform.bin`);
  - copies 32 B from `buf+0x41` into `spi_id_buffer`. Those are the 29-char Pascal string `320_R110_AE4D21_ED060KD1C2_TC` plus junk, served by sysfs `lut_version`;
  - logs `---get lut from file sucesss---`.
  - **It runs no CRC or format check on the PVI path.** `epd_lut_analying` (CRC, XOR descramble, `zip_init`) is only for Rockchip's own `rkf` format.
- **Whatever the loader put at 0x7ff00000 is overwritten by the file.** The panel's SPI flash waveform (`320_R177_AE6A41_ED060KD1U7_TC`) is never used for display [CONFIRMED-log].
  So the panel identity disagrees: the flash says KD1U7/R177, the kernel runs the KD1C2/R110 file.
- **Fallback:** a missing resource prints `=====parameter do not define waveform_addr,use array lut=====`, and a missing or unreadable file prints `cannot open` or
  `file read err`. Both go to `epd_lut_from_array_init`: the built-in rychly `rkf` V110 array at 0xc0a8fb38, for the **wrong panel**. The PVI getter would then
  decode it as a WBF [STRONG].
- The SPI-flash positions 0/1 and NAND 2 (`epd_lut_from_gpio_spi_init`, `_rk_spi_init`) and their "spi and nand waveform are same/different" logic are compiled in
  but unreachable.
- **Boot:**
  - probe queues a white **mode-5 RESET** frame (INIT, 113 frames at range 8) [CONFIRMED-log `eink mode = 5`, `lut_mode = 0 lut_frame = 113`];
  - if the battery is low (`rk30_adc_battery_get_bat_vol`, `is_need_show_lowpower_pic()` = 1) it shows the low-power picture and runs the charging-logo loop;
  - then it starts the boot animation (`support_bootup_ani()` = 1, mode `get_bootup_ani_mode()` = 3 PART, every `get_bootup_logo_cycle()` = 2000 ms, looping);
  - the first ioctl 0x7000 kills it.

### 2.10 SPI flash, boot animation, PMIC, debug node

(From the source-diff pass against the public C files and `.uu` objects. The per-function notes are working notes, not published.)

#### 2.10a SPI flash (the panel's own flash)

- **Hardware.** The RC2 has one: board `spi_board_info "epd_spi_flash"`, bus 0, cs 0, 6 MHz. Driver `epd_spi_flash`, initcall level 6 (the `.uu` used 4).
- **Probe** (ONYX-rewritten): creates `/dev/spi_flash` (chrdev 250:0, 0600) and `/proc/panel_info`, then reads the panel strings at flash 0x70000 with a flat ONYX
  layout. The `.uu` had a PVI/Broadsheet header parser. The device shows:

  | Field | Value [CONFIRMED-log] |
  |---|---|
  | part | `ED060KD1U7` |
  | VCOM | −2.06 V |
  | waveform | `320_R177_AE6A41_ED060KD1U7_TC` |
  | barcode | — |

- **VCOM auto-fix.** If the PMIC holds 1.25 or 1.80 V (factory defaults), probe programs the PMIC EEPROM to panel VCOM − 400 mV.
  - This unit holds 1.66 V = 2.06 − 0.40, so the fix ran once before.
- **`spi_flash_read`** (fops) is broken but harmless (root-only, unused):
  - it reads 256 KB of the panel waveform and computes its MD5;
  - it **returns the kmalloc pointer as the byte count**;
  - it copies nothing to user space and leaks the 256 KB buffer.
- The flash is **not** a waveform source on the RC2 (`§2.9`).

#### 2.10b Boot animation

- **Data.** The animation is **embedded in the Image** as `__init` data at 0xc042d640: `tAniHeader`, 1448×1072, 6 zlib images.
  - Image 0 is the full-screen base.
  - Images 1–4 are sprites.
  - Image 5 (`mType` = 1) is the low-power picture.
  - `boot_ani_init` (from probe) inflates all of them into kmalloc buffers before init memory is freed [CONFIRMED-log `mOrignalSize= 776131 / 19043 / …`].
- **Tick.** `rk29_ebc_bootup_timer` → `bootup_ani_wq` → `ebc_bootup_work_fun`: take a slot (may block; the `.uu` skipped the tick when the thread was busy), blit
  the next image (the first one on white, an ONYX change), queue it as **PART**, re-arm 2000 ms, loop forever.
- **Stop.** The first ioctl 0x7000 stops it.

#### 2.10c PMIC TPS65185 ("papyrus", `epdpower/tps65185.c`)

- **Identity.** I²C 0x68, 400 kHz, `TPS65185r1p2` [CONFIRMED-log]. Most functions are SAME as the public C (per-function verdicts in `§3`).
- **Changes** [CONFIRMED-dis]:
  - **`papyrus_hw_power_req` (power-up).** From the first power-up on it overrides UPSEQ0/1 to **0x39/0x11**; the public value is 0xE4/0x00. Read with the TPS65185
    register map [STRONG], that is strobe order VDDH, VNEG, VEE, VPOS and delays 6/3/6/3 ms. It then:
    1. sets ENABLE = 0x20 (3V3 only), waits 2 ms, and sets ENABLE = 0xAF (all rails, ACTIVE);
    2. polls PG == 0xFA up to 30× at ~20 ms intervals;
    3. on a timeout goes to STANDBY and retries after 200 ms, 3 attempts in all;
    4. **swallows a final failure**, so the EBC frame then runs with the rails down.

    Typical cost is about 25 ms; the worst case is about 2.3 s. Power-down sets ENABLE = 0x6F (STANDBY, 3V3 kept), with no wait.
  - **`tps65185_probe`** caches the VCOM register (166 → 1.66 V) at 0xc0d2ac6c. The sysfs `vcom_mv` read returns this stale cache **in 10 mV units**.
  - **`tps65185_vcom_get`** returns raw register units.
  - **`tps65185_vcom_set`** (EEPROM PROGRAM) now has bounded polling and 3 attempts.
- **VCOM writers (all program the non-volatile PMIC EEPROM):**
  - sysfs `/sys/bus/i2c/drivers/tps65185/vcom_mv` (0666);
  - `onyx_misc` `vcom_value` (0666);
  - a USB mass-storage vendor SCSI command in `fsg_main_thread`;
  - the SPI-flash auto-fix.

  The driver never writes VCOM at power-up, so the panel always runs on the EEPROM value.
- **Suspend/resume** of the PMIC are log-only, because `support_tps_3v3_always_alive()` = 1. The PMIC stays in STANDBY with 3V3 on across system suspend.
- **`/proc/epdsensor`** prints the PMIC temperature (`proc_lm_show`). The `onyx_misc` `pmic_temp` node always prints "25" and never reads the PMIC.

#### 2.10d Debug node

`/sys/devices/platform/rk29-ebc.0/ebc_dbg` (0644):
- **Write:** 5 chars, '0' clears and anything else sets bits of `gprint_dir_or_file`: bit0 bootani, bit1 bufmanage, bit2 dither, bit3 epdlut, bit4 ebc core.
- **Read:** prints help to the kernel log and returns 0 bytes.
- The level `gebc_dbg_lev` (0xc0b47164) is 3 and has no setter.
- The node is identical to the public `rk29_ebc_dbg.c`.
- `echo 00001 > ebc_dbg` turns on the `ebc %s(%d):` traces: `frame send end.`, `auto mode start.`, `ebc_buf_release …`, …

### 2.11 Ghidra pitfalls seen here

- Tail merging: `rk29_ebc_irq_function` and `rk29_ebc_frame_timeout` are decompiled into one body, and spinlock/`up()` inlines are shown as garbage.
- `UNK_`/`DAT_` for strings: use the string-annotated output of `tools/annotate_decomp.py`.
- `ebc_bootup_work_fun` is shown with an inlined `mod_timer`.
- `get_lut_temp`'s fall-through return value is shown as "param_4", which hides that it is the caller's r3.

---

## 3. Function inventory

How the table was made:
- **Rows:** one per kallsyms text symbol of the span, plus the 6 initcall/devinit entries. The 100 internal labels of the asm block (`LOOP`, `CHECK1`, `GET_POINT_DATA*`, …) are folded into their 5
  entry points.
- **Sizes:** distance to the next symbol, literal pool included.
- **"vs `.uu`":** the `objdiff.py` verdict, refined by hand where the instruction diff showed only offsets.
  - "SAME (offsets)" means the same code with `rk29_ebc_info` offsets shifted by `§4.1`.
  - "public C" means compared with the rychly `.c` source (PMIC, `ebc_dbg`, `hardware_epd_public.c`).
- **"live?":**
  - "dead": no BL/B and no pointer outside the kallsyms table;
  - "unreachable on RC2": only behind a compile-time constant (`support_pvi_waveform()` = 1, `get_chip()` = 0, `get_lut_position()` = 3) or the rkf fallback.
- **Machine-readable versions:** `tools/inventory.py` (with the caller list) and `tools/objdiff.py --tsv` regenerate them.

| VA | size | function | vs `.uu` / public C | live? | purpose | conf |
|---|---|---|---|---|---|---|
| c0419b1c | 276 | `rk29_ebc_init` | CHANGED: offsets of globals (−4: no `ebc_auto_task` global) | live | chrdev 261 `/dev/ebc`, class, platform driver register; only `.data` offsets differ | [CONFIRMED-dis] |
| c0419c30 | 12 | `spi_flash_init` | CHANGED: plain register, level 6 | live | `spi_register_driver(epd_spi_flash)`, initcall level 6 (was 4) | [CONFIRMED-dis] |
| c0419c3c | 48 | `lm_proc_init` | public C, same | live | `/proc/epdsensor` | [CONFIRMED-dis] |
| c0419c6c | 68 | `tps65185_init` | public C, same | live | i2c driver + `vcom_mv` driver attr (0666) | [CONFIRMED-dis] |
| c060b29c | 8 | `wvf_version_write` | SAME | live | sysfs `lut_version` store (ignored) | [CONFIRMED-dis] |
| c060b2a4 | 240 | `ebc_panel_scan_set` | SAME | live | ebc_ops[0]: HTIMING0/1, VTIMING0/1, DSP_ACT_INFO from panel info | [CONFIRMED-dis] |
| c060b394 | 156 | `ebc_win_dsp_set` | SAME | live | ebc_ops[1]: WIN_CTRL, WIN_VIR, WIN_ACT, WIN_DSP, WIN_DSP_ST (full panel) | [CONFIRMED-dis] |
| c060b430 | 60 | `ebc_border_set` | SAME | live | ebc_ops[2]: VCOM0..3 = 0 | [CONFIRMED-dis] |
| c060b46c | 52 | `ebc_dsp_ctl_set` | SAME | live | ebc_ops[4]: DSP_CTRL = a\|b\|c\|0xc0030000, CONFIG_DONE | [CONFIRMED-dis] |
| c060b4a0 | 100 | `ebc_image_addr_set` | SAME (offsets) | live | ebc_ops[5]: WIN_MST0/1 = old/new phys + (x1 + **y1·1024**)/2 (stride bug, `§8`; the effect is STRONG) | [CONFIRMED-dis] |
| c060b504 | 120 | `_ebc_frame_start` | **NEW** | live | INT = n<<9\|0x28, DSP_CTRL bit27 = "more chunks", DSP_START go | [CONFIRMED-dis] |
| c060b57c | 20 | `ebc_open` | SAME | live | clears file private fields | [CONFIRMED-dis] |
| c060b590 | 64 | `ebc_resume` | CHANGED: + printk | live | print + board `resume` hook | [CONFIRMED-dis] |
| c060b5d0 | 64 | `ebc_suspend` | CHANGED: + printk | live | print + board `suspend` hook (no drain) | [CONFIRMED-dis] |
| c060b610 | 472 | `ebc_register_update` | CHANGED: modes 0..16, new type numbering, 15/16, mode 7 not partial | live | per update: temperature (clamp >50 → 25), DSP_CTRL bits by mode, image addrs, `lut_get(type, mode, temp)` | [CONFIRMED-dis] |
| c060b7e8 | 56 | `ebc_shutdown` | **NEW** | live | platform `.shutdown`: print only | [CONFIRMED-dis] |
| c060b820 | 104 | `rk29_ebc_remove` | CHANGED: + printk, offsets | live | remove sysfs files, destroy wake lock | [CONFIRMED-dis] |
| c060b888 | 40 | `wvf_version_read` | SAME | live | sysfs `lut_version` = WBF panel string | [CONFIRMED-dis] |
| c060b8b0 | 28 | `ebc_dbg_write` | SAME | live | sysfs `ebc_dbg` store | [CONFIRMED-dis] |
| c060b8cc | 16 | `ebc_dbg_read` | SAME | live | sysfs `ebc_dbg` show (help to dmesg) | [CONFIRMED-dis] |
| c060b8dc | 48 | `ebc_clocks_enable` | SAME | live | enable dclk_ebc, hclk_ebc, aclk_lcdc1, pd_lcdc1 | [CONFIRMED-dis] |
| c060b90c | 208 | `ebc_bootup_work_fun` | CHANGED: always queues (may block) | live | boot-animation tick: take slot (may block), next frame, queue PART, re-arm 2 s | [CONFIRMED-dis] |
| c060b9dc | 24 | `rk29_ebc_bootup_timer` | SAME (offsets) | live | queue the boot-animation work | [CONFIRMED-dis] |
| c060b9f4 | 176 | `rk29_ebc_vdd_power_timeout` | CHANGED: offsets, line no. | live | board power off + clocks off + wake_unlock; timer never fires in practice | [STRONG] |
| c060baa4 | 168 | `ebc_mmap` | CHANGED: write-combining pgprot | live | remap the pool, no bounds check, now write-combining | [CONFIRMED-dis] |
| c060bb4c | 16 | `rk29ebc_register_notifier` | SAME | live | exported EBC on/off notifier (no in-kernel user) | [CONFIRMED-dis] |
| c060bb5c | 228 | `ebc_power_set` | SAME (offsets) | live | ebc_ops[3]: on = wake_lock, board on, clocks, TPS on; off = reverse | [CONFIRMED-dis] |
| c060bc40 | 16 | `rk29ebc_unregister_notifier` | SAME | dead | notifier | [CONFIRMED-dis] |
| c060bc50 | 20 | `rk29ebc_notify` | SAME | live | EBC_ON/EBC_OFF notifier call | [CONFIRMED-dis] |
| c060bc64 | 260 | `rk3026_readefuse` | **NEW** | dead | debug dump of the RK3026 eFuse (32 words) to dmesg | [CONFIRMED-dis] |
| c060bd68 | 416 | `full_win_mode_data_change` | CHANGED: full cache flush, offsets | live | mode 9: 2-bpp drive frame from the packed LUT inside the window; + cache flush, schedule every 400 rows | [CONFIRMED-dis] |
| c060bf08 | 304 | `direct_mode_data_change` | CHANGED: full cache flush, offsets | live | modes 11/12: 2-bpp drive frame from the packed LUT, 0 where old == new; + full cache flush | [CONFIRMED-dis] |
| c060c038 | 240 | `enable_reagl` | **NEW** | dead | time-based XOR unlock (`../reagl`) | [CONFIRMED-dis] |
| c060c128 | 432 | `direct_mode_data_change_text` | **NEW** | dead | 5-bit-table variant of the direct path keyed by the REAGL diff count | [CONFIRMED-dis] |
| c060c2d8 | 1852 | `get_auto_image_new_hard` | **NEW** | live | AUTO engine: per-pixel frame counters, next 2-bpp frame | [CONFIRMED-dis] |
| c060ca14 | 48 | `auto_caclu_next_frame` | **NEW** | live | wrapper → `get_auto_image_new_hard(dst, curr, +0x16c, +0x170, +0x174, info)` | [CONFIRMED-dis] |
| c060ca44 | 712 | `ebc_auto_tast_function` | CHANGED: C engine instead of asm, ping-pong rewrite | live | SCHED_FIFO-99 kthread: flip ping-pong buffer, start frame, compute next (AUTO/9/11/12) | [CONFIRMED-dis] |
| c060cd0c | 1352 | `ebc_frame_start` | CHANGED: AUTO via `auto_caclu_next_frame`, LUT chunking | live | work func: per engine program window + LUT chunk (≤64 frames) or first direct frames; start | [CONFIRMED-dis] |
| c060d254 | 3480 | `rk29_ebc_probe` | CHANGED: pool from resource (8 bpp slots), new aux buffers, RESET frame, battery logo, banner | live | resources, clocks, panel/timing, LUT source, PMIC ops, pool (4×w·h), aux buffers, timers, threads, RESET frame, low-battery and boot-animation start | [CONFIRMED-dis] |
| c060dfec | 232 | `rk29_ebc_irq_function` | CHANGED: AUTO wakes C engine, offsets | live | frame end: next LUT chunk / next direct frame / AUTO tick / completion + wake-ups | [CONFIRMED-dis] |
| c060e0d4 | 32 | `rk29_ebc_frame_timeout` | SAME | live | 3-s watchdog: print + same completion as the IRQ | [CONFIRMED-dis] |
| c060e0f4 | 212 | `rk29_ebc_irq` | SAME | live | ack INT bits 6/7/8/4; bit1 → `rk29_ebc_irq_function` | [CONFIRMED-dis] |
| c060e1c8 | 440 | `check_part_mode` | SAME | live | modes 3/10/11: 0 = identical (drop); all changed pixels 0/15 → mode 6 (DU) | [CONFIRMED-dis] |
| c060e380 | 144 | `check_part_mode_text` | **NEW** | live | REAGL: # differing 32-bit words (`../reagl`) | [CONFIRMED-dis] |
| c060e410 | 248 | `check_rotate` | **NEW** | live | REAGL: which edge is black (`../reagl`) | [CONFIRMED-dis] |
| c060e508 | 356 | `check_part_mode_text_rect` | **NEW** | live | REAGL: 83-px stripe unchanged? (`../reagl`) | [CONFIRMED-dis] |
| c060e66c | 820 | `backupstatarbar` | **NEW** | live | REAGL: blank the status-bar stripe (`../reagl`) | [CONFIRMED-dis] |
| c060e9a0 | 684 | `revertstatarbar` | **NEW** | live | REAGL: restore the stripe (`../reagl`) | [CONFIRMED-dis] |
| c060ec4c | 180 | `y8bitto4bit` | **NEW** | live | 8-bpp → 4-bpp in place (leaving AUTO) + flush | [CONFIRMED-dis] |
| c060ed00 | 200 | `y4bitto8bit` | **NEW** | live | 4-bpp → 8-bpp (entering AUTO; REAGL scratch) + flush | [CONFIRMED-dis] |
| c060edc8 | 1132 | `reagl_1` | **NEW** | dead | older halo marking (`../reagl`) | [CONFIRMED-dis] |
| c060f234 | 1852 | `reagl_2` | **NEW** | live | REAGL halo mask (`../reagl`) | [CONFIRMED-dis] |
| c060f970 | 2068 | `ebc_thread` | CHANGED: mode filter, AUTO expand, REAGL, `eink mode` printk, mdelay(100) | live | the state machine (`§2.4`) | [CONFIRMED-dis] |
| c0610184 | 216 | `set_window_part` | **NEW** | dead | mark equal bytes of a sub-rectangle as 1 + flush | [CONFIRMED-dis] |
| c061025c | 40 | `ebc_sn_encode` | SAME | live | ioctl 0x7002 SN encode | [CONFIRMED-dis] |
| c0610284 | 1136 | `ebc_io_ctl` | public C, changed | live | ioctls 0x7000–0x7004 (public C + 0x7004 = 3028 + hook calls) | [CONFIRMED-dis] |
| c06106f4 | 8 | `rkebc_register_notifier` | SAME | unreachable on RC2 | stub, called by `rk3188_cpufreq_driver_init` | [CONFIRMED-dis] |
| c06106fc | 104 | `rk29_ebc_set_auto_power_off` | SAME (offsets) | dead | would set +0x188 and power on | [CONFIRMED-dis] |
| c0610764 | 96 | `rk29_ebc_set_gdpwr0` | SAME | dead | EPD_CTRL power-enable bits | [CONFIRMED-dis] |
| c06107c4 | 84 | `set_epd_info` | public C, changed | live | memcpy 72-B RC2 panel info (0xc0a8faa8), pixclock 40 MHz, 1448×1072; also used by rk_fb | [CONFIRMED-dis] |
| c0610818 | 4 | `ebc_io_ctl_hook` | **NEW** | live | empty (`bx lr`), called by 0x7000/0x7001 | [CONFIRMED-dis] |
| c061081c | 8 | `support_pvi_waveform` | public C, same | live | 1 | [CONFIRMED-dis] |
| c0610824 | 8 | `get_lut_position` | public C, same | live | 3 = waveform file | [CONFIRMED-dis] |
| c061082c | 8 | `set_end_display` | public C, same | dead | 0 = END_RESET | [CONFIRMED-dis] |
| c0610834 | 8 | `get_bootup_logo_cycle` | public C, same | live | 2000 ms | [CONFIRMED-dis] |
| c061083c | 8 | `get_reagl_diffnum` | **NEW** | live | 200 | [CONFIRMED-dis] |
| c0610844 | 8 | `is_bootup_ani_loop` | public C, same | live | 1 | [CONFIRMED-dis] |
| c061084c | 8 | `is_need_show_lowpower_pic` | public C, same | live | 1 | [CONFIRMED-dis] |
| c0610854 | 8 | `support_bootup_ani` | public C, same | live | 1 | [CONFIRMED-dis] |
| c061085c | 8 | `get_bootup_ani_mode` | public C, same | live | 3 = PART | [CONFIRMED-dis] |
| c0610864 | 8 | `support_tps_3v3_always_alive` | public C, same | live | 1 | [CONFIRMED-dis] |
| c061086c | 16 | `map_to_pvi_mode` | **NEW** | live | 8 → 5, else identity | [CONFIRMED-dis] |
| c061087c | 8 | `get_chip` | **NEW** | live | 0 | [CONFIRMED-dis] |
| c0610884 | 8 | `get_statusbar_hight` | **NEW** | live | 83 | [CONFIRMED-dis] |
| c061088c | 8 | `get_bottom_hight` | **NEW** | live | 0 | [CONFIRMED-dis] |
| c0610894 | 132 | `crc_32` | SAME | unreachable on RC2 (rkf fallback only) | CRC-32 for the rkf format | [CONFIRMED-dis] |
| c0610918 | 100 | `epd_lut_check_temp` | SAME | unreachable on RC2 | rkf temperature ranges (non-PVI getter only) | [CONFIRMED-dis] |
| c061097c | 68 | `epd_lut_reagle` | **NEW** | live | MV ∈ {0x18,0x19,0x20} → 1 (`../reagl`) | [CONFIRMED-dis] |
| c06109c0 | 316 | `epd_lut_analying` | SAME (rodata XOR-key literal only) | unreachable on RC2 (rkf fallback only) | rkf: CRC, tag, XOR descramble, `zip_init` | [CONFIRMED-dis] |
| c0610afc | 136 | `rst_format_change` | SAME | unreachable on RC2 | rkf RESET table convert | [CONFIRMED-dis] |
| c0610b84 | 104 | `auto_data_change` | SAME | dead | rkf AUTO table convert | [CONFIRMED-dis] |
| c0610bec | 96 | `gray2_data_change` | SAME | unreachable on RC2 | rkf GRAY2 table convert | [CONFIRMED-dis] |
| c0610c4c | 964 | `epd_lut_data_get` | CHANGED: offsets/minor | unreachable on RC2 | rkf LUT getter (selected only if `support_pvi_waveform()`==0) | [CONFIRMED-dis] |
| c0611010 | 536 | `decodewaveform_19` | CHANGED: rewritten (5-bit, 0x400 B/frame) | live | WBF MV 0x18/0x19/0x20 RLE decode → 5-bit `tbl[f][32][32]`, returns frames | [CONFIRMED-dis] |
| c0611228 | 616 | `decodewaveform` | CHANGED: rewritten | unreachable on RC2 (other MVs only) | WBF decode for other MVs | [CONFIRMED-dis] |
| c0611490 | 32 | `getwaveformdata` | SAME | dead | accessor | [CONFIRMED-dis] |
| c06114b0 | 360 | `parse_mode_version` | **NEW** | live | MV → 8-entry wbf mode index table | [CONFIRMED-dis] |
| c0611618 | 160 | `get_lut_mode` | CHANGED: table from `parse_mode_version` | live | LUT type → wbf mode (`§2.5`) | [CONFIRMED-dis] |
| c06116b8 | 56 | `get_lut_temp` | SAME | live | temperature → range; ≥ last bound returns caller r3 (=0) | [CONFIRMED-dis] |
| c06116f0 | 248 | `get_lut_frame` | CHANGED: debug printk removed | live | mode/temp pointer checksums, decode | [CONFIRMED-dis] |
| c06117e8 | 164 | `get_lut_reset_data` | SAME (offsets) | dead | rkf RESET | [CONFIRMED-dis] |
| c061188c | 144 | `get_lut_gray2_data` | SAME | dead | rkf GRAY2 | [CONFIRMED-dis] |
| c061191c | 4 | `get_lut_gray4_data` | SAME | dead | `bx lr` stub | [CONFIRMED-dis] |
| c0611920 | 148 | `get_lut_data` | **NEW** | live | AUTO: copy 5-bit tables, zero diagonal (MV 2–3) | [CONFIRMED-dis] |
| c06119b4 | 112 | `reagltopart` | **NEW** | dead | zero diagonal (`../reagl`) | [CONFIRMED-dis] |
| c0611a24 | 60 | `get_reagllut_data_hard` | **NEW** | live | type 9: only `[31][31]` (`../reagl`) | [CONFIRMED-dis] |
| c0611a60 | 116 | `get_lut_data_hard` | **NEW** | live | pack `word[f·16+old]` 2 bits per new level from even 5-bit indices | [CONFIRMED-dis] |
| c0611ad4 | 88 | `get_lut_data_a2_bk` | **NEW** | live | AUTO: pack the DU part after the GC16 frames | [CONFIRMED-dis] |
| c0611b2c | 528 | `epd_lut_data_get_pvi_hard` | **NEW** | live | **the live LUT getter** (`§2.5`) | [CONFIRMED-dis] |
| c0611d3c | 524 | `epd_lut_data_get_pvi` | CHANGED: rewritten | unreachable on RC2 | PVI getter for chip 1 | [CONFIRMED-dis] |
| c0611f48 | 160 | `get_lut_grayA2_data` | SAME | dead | rkf A2 | [CONFIRMED-dis] |
| c0611fe8 | 48 | `epd_spi_flash_register` | SAME | live | store spi info | [CONFIRMED-dis] |
| c0612018 | 276 | `epd_lut_from_gpio_spi_init` | CHANGED: panel-id compare | unreachable on RC2 | waveform from GPIO-SPI flash vs NAND | [CONFIRMED-dis] |
| c061212c | 632 | `epd_lut_from_rk_spi_init` | CHANGED: panel-id compare | unreachable on RC2 | waveform from RK SPI flash vs NAND | [CONFIRMED-dis] |
| c06123a4 | 216 | `epd_lut_from_nand_init` | CHANGED: copies WBF panel string | live | set waveform ptr, log CRC, copy panel string | [CONFIRMED-dis] |
| c061247c | 216 | `epd_lut_from_file_init` | SAME | live | read `/ebc_waveform.bin` into the window → nand_init | [CONFIRMED-dis] |
| c0612554 | 144 | `epd_lut_from_array_init` | SAME (line no.) | unreachable on RC2 (fallback only) | fallback: built-in V110 rkf array | [CONFIRMED-dis] |
| c06125e4 | 44 | `epd_lut_uninit` | SAME | dead |  | [CONFIRMED-dis] |
| c0612610 | 96 | `epd_lut_op_register` | CHANGED: + reagle slot, chip select | live | lut_get = pvi_hard; reagle slot | [CONFIRMED-dis] |
| c0612670 | 40 | `get_waveform_version` | SAME | live | panel string for `lut_version` | [CONFIRMED-dis] |
| c0612698 | 152 | `zip_decode` | SAME | unreachable on RC2 | Huffman decode (rkf) | [CONFIRMED-dis] |
| c0612730 | 292 | `zip_init` | SAME | unreachable on RC2 (rkf fallback only) | Huffman tree (rkf) | [CONFIRMED-dis] |
| c0612854 | 140 | `panel_data_translate` | CHANGED: unknown → NUL | live | panel-flash byte → ASCII (unknown → NUL) | [CONFIRMED-dis] |
| c06128e0 | 20 | `spi_flash_open` | SAME | live | fops | [CONFIRMED-dis] |
| c06128f4 | 8 | `spi_flash_suspend` | SAME | live | return 0 | [CONFIRMED-dis] |
| c06128fc | 8 | `spi_flash_resume` | SAME | live | return 0 | [CONFIRMED-dis] |
| c0612904 | 140 | `SPIFlashRead` | CHANGED: printk dropped | live | cmd 0x03 read | [CONFIRMED-dis] |
| c0612990 | 96 | `SpiFlashWaitBusy` | SAME | live | poll status | [CONFIRMED-dis] |
| c06129f0 | 168 | `Sector_Erase` | SAME | live | 4 KB erase | [CONFIRMED-dis] |
| c0612a98 | 248 | `SPIFlashWrite` | SAME | live | page program | [CONFIRMED-dis] |
| c0612b90 | 580 | `spi_flash_write` | SAME (layout) | live | fops write (64 KB RMW) | [CONFIRMED-dis] |
| c0612dd4 | 176 | `proc_read_panel_info` | **NEW** | live | `/proc/panel_info` | [CONFIRMED-dis] |
| c0612e84 | 140 | `spi_flash_seek` | SAME | live | fops llseek | [CONFIRMED-dis] |
| c0612f10 | 380 | `panel_get_id` | CHANGED: ONYX rewrite | live | panel strings at flash 0x70000, VCOM parse | [CONFIRMED-dis] |
| c061308c | 536 | `spi_flash_read` | CHANGED: ONYX rewrite | live | fops read: waveform MD5, VCOM fix-up, returns a pointer (bug) | [CONFIRMED-dis] |
| c06132a4 | 2472 | `check_auto_image_sARM` | CHANGED: instruction order only | dead | asm, from the `.uu` AUTO generation; reordered `mov r7,#0` | [CONFIRMED-dis] |
| c0613c4c | 328 | `refresh_new_image_sARM` | SAME | dead | asm | [CONFIRMED-dis] |
| c0613d94 | 1852 | `get_auto_image_sARM` | CHANGED: instruction order only | dead | asm; reordered like check_auto | [CONFIRMED-dis] |
| c06144d0 | 820 | `direct_mode_sARM` | SAME | dead | asm | [CONFIRMED-dis] |
| c0614804 | 692 | `direct_fullwin_mode_sARM` | SAME | dead | asm | [CONFIRMED-dis] |
| c0614ab8 | 68 | `ebc_buf_release` | SAME | live | slot idle + wake waiter | [CONFIRMED-dis] |
| c0614afc | 176 | `ebc_remove_from_dsp_buf_list` | SAME | live | unlink by position | [CONFIRMED-dis] |
| c0614bac | 404 | `ebc_add_to_dsp_buf_list` | SAME | live | append + queue collapsing (`§2.2`) | [CONFIRMED-dis] |
| c0614d40 | 20 | `ebc_get_dsp_list_enum_num` | SAME | dead | list length | [CONFIRMED-dis] |
| c0614d54 | 96 | `ebc_find_buf_by_phy_addr` | SAME | live | slot by phys | [CONFIRMED-dis] |
| c0614db4 | 80 | `ebc_dsp_buf_get` | SAME | live | list head (not removed) | [CONFIRMED-dis] |
| c0614e04 | 524 | `ebc_empty_buf_get` | SAME | live | first idle slot; sleeps; recursive after a signal | [CONFIRMED-dis] |
| c0615010 | 16 | `ebc_phy_buf_base_get` | SAME | live | pool phys | [CONFIRMED-dis] |
| c0615020 | 16 | `ebc_virt_buf_base_get` | SAME | dead | pool virt | [CONFIRMED-dis] |
| c0615030 | 164 | `ebc_buf_uninit` | SAME | live |  | [CONFIRMED-dis] |
| c06150d4 | 788 | `ebc_buf_init` | SAME | live | ≤4 slots of `dest_buf_len` | [CONFIRMED-dis] |
| c06153e8 | 176 | `buf_list_init` | SAME | live |  | [CONFIRMED-dis] |
| c0615498 | 72 | `buf_list_uninit` | SAME | live |  | [CONFIRMED-dis] |
| c06154e0 | 64 | `buf_list_eol` | SAME | dead |  | [CONFIRMED-dis] |
| c0615520 | 52 | `buf_list_get` | SAME | live |  | [CONFIRMED-dis] |
| c0615554 | 116 | `buf_list_remove` | SAME | live |  | [CONFIRMED-dis] |
| c06155c8 | 140 | `buf_list_add` | SAME | live |  | [CONFIRMED-dis] |
| c0615654 | 104 | `buf_list_find` | SAME | dead |  | [CONFIRMED-dis] |
| c06156bc | 80 | `buf_list_get_pos` | SAME | live |  | [CONFIRMED-dis] |
| c061570c | 64 | `buf_list_set` | SAME | dead |  | [CONFIRMED-dis] |
| c061574c | 900 | `boot_ani_get_frame` | CHANGED: white first frame, chip branch | live | blit an animation image at 4 bpp (first on white); chip-1 8-bit branch | [CONFIRMED-dis] |
| c0615ad0 | 432 | `boot_deflate` | SAME | dead | zlib deflate (unused) | [CONFIRMED-dis] |
| c0615c80 | 404 | `boot_inflate` | SAME | live | zlib inflate | [CONFIRMED-dis] |
| c0615e14 | 164 | `boot_ani_remove_frame` | SAME | live |  | [CONFIRMED-dis] |
| c0615eb8 | 128 | `boot_ani_deinit` | SAME | live | free frames (0x7000) | [CONFIRMED-dis] |
| c0615f38 | 1000 | `boot_ani_init` | CHANGED: + printk | live | parse embedded animation, inflate 6 images | [CONFIRMED-dis] |
| c0616320 | 204 | `boot_ani_next_frame` | SAME | live | next image, loop | [CONFIRMED-dis] |
| c06163ec | 256 | `boot_ani_get_low_power_frame` | SAME (line no.) | live | low-battery picture | [CONFIRMED-dis] |
| c06164ec | 232 | `boot_ani_low_power_frame_rm` | SAME (line no.) | live | drop it from the loop | [CONFIRMED-dis] |
| c06165d4 | 68 | `rk29ebc_dbg_lve_set` | public C, same | live | `ebc_dbg` mask | [CONFIRMED-dis] |
| c0616618 | 168 | `rk29ebc_dbg_lve_show` | public C, same | live | help text | [CONFIRMED-dis] |
| c06166c0 | 16 | `papyrus_set_enable` | public C, same | live |  |  |
| c06166d0 | 40 | `papyrus_set_vcom_voltage` | public C, same | live |  |  |
| c06166f8 | 16 | `papyrus_set_vcom1` | public C, same | live |  |  |
| c0616708 | 16 | `papyrus_set_vcom2` | public C, same | live |  |  |
| c0616718 | 16 | `papyrus_set_vadj` | public C, same | live |  |  |
| c0616728 | 16 | `papyrus_set_int_en1` | public C, same | live |  |  |
| c0616738 | 16 | `papyrus_set_int_en2` | public C, same | live |  |  |
| c0616748 | 16 | `papyrus_set_upseq0` | public C, same | live |  |  |
| c0616758 | 16 | `papyrus_set_upseq1` | public C, same | live |  |  |
| c0616768 | 16 | `papyrus_set_dwnseq0` | public C, same | live |  |  |
| c0616778 | 16 | `papyrus_set_dwnseq1` | public C, same | live |  |  |
| c0616788 | 16 | `papyrus_set_tmst1` | public C, same | live |  |  |
| c0616798 | 16 | `papyrus_set_tmst2` | public C, same | live |  |  |
| c06167a8 | 20 | `proc_lm_open` | public C, same | live |  |  |
| c06167bc | 44 | `vcom_mv_get` | public C, changed | live | cached VCOM, 10 mV units | [CONFIRMED-dis] |
| c06167e8 | 100 | `papyrus_pm_resume` | public C, same | live |  |  |
| c061684c | 12 | `tps65185_resume` | public C, same | live |  |  |
| c0616858 | 132 | `papyrus_pm_sleep` | public C, same | live |  |  |
| c06168dc | 12 | `tps65185_suspend` | public C, same | live |  |  |
| c06168e8 | 68 | `papyrus_standby_dwell_time_ready` | public C, same | live |  |  |
| c061692c | 56 | `papyrus_remove` | public C, same | live |  |  |
| c0616964 | 40 | `tps65185_remove` | public C, same | live |  |  |
| c061698c | 164 | `papyrus_hw_setreg` | public C, same | live |  |  |
| c0616a30 | 88 | `papyrus_vcom_switch` | public C, same | live |  |  |
| c0616a88 | 216 | `papyrus_hw_getreg` | public C, same | live |  |  |
| c0616b60 | 552 | `papyrus_probe` | public C, same | live |  |  |
| c0616d88 | 172 | `papyrus_hw_power_ack` | public C, same | live |  |  |
| c0616e34 | 128 | `papyrus_hw_read_temperature` | public C, same | live | ADC start, poll, msleep 10, s8 °C | [CONFIRMED-dis] |
| c0616eb4 | 468 | `papyrus_hw_power_req` | public C, changed | live | rail power up/down; ONYX UPSEQ 0x39/0x11, PG retries | [CONFIRMED-dis] |
| c0617088 | 44 | `tps65185_power_on` | public C, same | live | EBC pwr op | [CONFIRMED-dis] |
| c06170b4 | 44 | `tps65185_power_down` | public C, same | live | EBC pwr op | [CONFIRMED-dis] |
| c06170e0 | 32 | `tps65185_temperature_get` | public C, same | live | EBC temp op | [CONFIRMED-dis] |
| c0617100 | 44 | `proc_lm_show` | public C, same | live |  |  |
| c061712c | 72 | `papyrus_set_i2c_address` | public C, same | dead |  |  |
| c0617174 | 196 | `tps65185_vcom_get` | public C, changed | live | read VCOM (raw register units) | [CONFIRMED-dis] |
| c0617238 | 180 | `tps65185_probe` | public C, changed | live | + cache VCOM | [CONFIRMED-dis] |
| c06172ec | 660 | `tps65185_vcom_set` | public C, changed | live | program EEPROM VCOM, 3 attempts | [CONFIRMED-dis] |
| c0617580 | 80 | `vcom_mv_set` | public C, same | live |  |  |
| c06175d0 | 32 | `register_ebc_pwr_ops` | public C, same | live |  | [CONFIRMED-dis] |
| c06175f0 | 20 | `register_ebc_temp_ops` | public C, same | live |  | [CONFIRMED-dis] |
| c08b4604 | 404 | `spi_flash_probe` | CHANGED: ONYX: /proc/panel_info, VCOM fix | live | ONYX: chrdev, `/proc/panel_info`, panel id, VCOM auto-fix | [CONFIRMED-dis] |
| c08b65bc | 76 | `spi_flash_remove` | SAME (layout) | live |  | [CONFIRMED-dis] |


## 4. Struct offset tables

### 4.1 `struct rk29_ebc_info` (kmalloc 0x2c0; `.uu` 0x2b8). Pointer at G+0 = 0xc0ca31e0

The layout of `ebc.h` (CONFIG_HARDWARE_EBC) applies up to +0x140. After that there are two insertions: **+0x144** (`lut_ops.reagle`) and **+0x160** (4 bytes that nothing
accesses). There is also one append, **+0x2bc** (the REAGL diff count). How it was derived:
- the same init stores were matched in `rk29_ebc_probe` of the Image and of the `.uu`;
- and the shifted accesses that `objdiff.py` found in same-size functions (for example `ebc_image_addr_set` +0x190→+0x198, `rk29_ebc_bootup_timer` +0x2b0→+0x2b8) [CONFIRMED-dis].

| Image off | `.uu` off | field | use in the stock driver |
|---|---|---|---|
| 0x000 | 0x000 | `ebc_status` | 1 while an AUTO/LUT refresh runs; 0 = idle |
| 0x004 | 0x004 | `frame_total` (u8) | remaining LUT frames (decremented by 64 per chunk); low byte of `lut_data.frame_num` |
| 0x005 | 0x005 | `frame_bw_total` (u8) | high byte of `frame_num` (DU frames of the AUTO merge) |
| 0x006 | 0x006 | `auto_need_refresh` (s16) | AUTO: some pixel still mid-waveform |
| 0x008 | 0x008 | `frame_left` | direct modes: frames still to compute |
| 0x00c | 0x00c | `ebc_send_count` | LUT chunk index (64-frame pages) |
| 0x018 | 0x018 | `lut_addr` | AUTO: LUT base |
| 0x01c / 0x020 | same | `height` / `width` | copies of vir_height / vir_width |
| 0x024 | 0x024 | `buffer_need_update` (s16) | AUTO: a new frame arrived |
| 0x02c | 0x02c | `bits_per_pixel` | **8** (`.uu`: 4); sets the slot size |
| 0x030 | 0x030 | `ebc_irq_status` | "frame done" flag |
| 0x038 | 0x038 | `ebc_dsp_buf_status` | "buffer posted" flag (ioctl → thread) |
| 0x040 | 0x040 | `ebc_clk_info` | dclk 0x40 (`dclk_ebc`), hclk 0x50 (`hclk_ebc`), aclk_lcdc 0x58 (`aclk_lcdc1`), pd_display 0x7c (`pd_lcdc1`), pixclock 0x90 (40 MHz; `clk_set_rate(dclk, 4·pixclock)`) |
| 0x094 | 0x094 | `ebc_panel_info` (18 ints) | width 0x94, height 0x98, hsync 0x9c, hstart 0xa0, vsync 0xa4, vend 0xa8, frame_rate 0xac, **vir_width 0xb0, vir_height 0xb4**, refcount 0xb8, fb_width 0xbc, fb_height 0xc0, color_panel 0xc4, rotate 0xc8, hend 0xcc, vstart 0xd0, gdck_sta 0xd4, lgonl 0xd8 |
| 0x0dc | 0x0dc | `ebc_reg_info` | reg_vir_base 0xdc, reg_phy_base 0xe0 (0x10114000), len 0xe4 (0x4000), **preg 0xe8**, regbak 0xec..0x13f (shadow of `EBC_REG`: DSP_START 0xec, EPD_CTRL 0xf0, DSP_CTRL 0xf4, …, INT 0x128, CONFIG_DONE 0x13c) |
| 0x140 | 0x140 | `lut_ops.lut_get` | = `epd_lut_data_get_pvi_hard` |
| **0x144** | — | `lut_ops.reagle` (new) | = `epd_lut_reagle`, never called |
| 0x148 / 0x14c | 0x144 / 0x148 | `pwr_ops.power_on/down` | TPS65185 |
| 0x150 | 0x14c | `temp_ops.temperature_get` | TPS65185 |
| 0x154 | 0x150 | `ebc_ops*` | 0xc0a8f7f8: {panel_scan_set, win_dsp_set, border_set, power_set, dsp_ctl_set, image_addr_set} |
| 0x158 / 0x15c | 0x154 / 0x158 | `lut_data.frame_num` / `.data` | frames (AUTO: gc16 \| du<<8) / 512 KB LUT |
| **0x160** | — | (new, never accessed) | [STRONG] |
| 0x164 | 0x15c | `ebc_task` | `ebc_thread` |
| 0x168 | 0x160 | `mach_info` | board `ebc_platform_data` (+8 power_on, +0xc power_off, +0x18 suspend, +0x1c resume) |
| 0x16c / 0x170 / 0x174 | 0x164 / 0x168 / 0x16c | `auto_image_new` / `auto_image_old` / `auto_frame_buffer` | AUTO: w·h bytes each |
| 0x17c / 0x180 | 0x174 / 0x178 | `auto_direct_buffer0/1` | ping-pong 2-bpp drive frames, w·h/4 each (phys = virt − 0x60000000) |
| 0x184 | 0x17c | `ebc_power_status` | |
| 0x188 | 0x180 | `ebc_auto_power_off` | 1, never changed (setter dead) |
| 0x18c | 0x184 | `ebc_last_display` | BLOCK (mode 8) wait flag |
| 0x190 | 0x188 | `lut_ddr_vir` | ioremap of the 1 MB waveform window |
| **0x194 / 0x198** | 0x18c / 0x190 | `prev_dsp_buf` / `curr_dsp_buf` | old (on panel) / new |
| 0x1a0 | 0x198 | `suspend_lock` | wake lock `ebc` |
| 0x1e8 | 0x1e0 | `wake_lock_is_set` | |
| 0x1f8 | 0x1f0 | `first_in` | first frame: do not release prev |
| 0x1fc / 0x218 / 0x234 | 0x1f4 / 0x210 / 0x22c | `vdd_timer` / `boot_logo_timer` / `frame_timer` | `timer_list` 0x1c each |
| 0x250 | 0x248 | `work` | func `ebc_frame_start` (the `.uu` set `new_buffer_refresh` on a second work) |
| 0x260 | 0x258 | `buf_info` (56 B) | unused by the stock code |
| 0x2a8 / 0x2b8 | 0x2a0 / 0x2b0 | `bootup_ani` work / `bootup_ani_wq` | |
| **0x2bc** | — | REAGL diff count (new) | written by `ebc_thread`, read only by the dead `direct_mode_data_change_text` |

### 4.2 The global block G = 0xc0ca31e0 (bss; no data symbols, offsets from literal pools)

| VA | G+ | content | `.uu` counterpart |
|---|---|---|---|
| 0xc0ca31e0 | 0x00 | `prk29_ebc_info` | `prk29_ebc_info` |
| 0xc0ca31e4 | 0x04 | dev_t 0x10500000 (261:0) | `dev` (`.uu` also had `ebc_auto_task` here) |
| 0xc0ca31e8 | 0x08 | `struct cdev` | `cdev` |
| 0xc0ca3224 | 0x44 | `ebc_class` | |
| 0xc0ca3228 | 0x48 | REAGL unlock flag (dead) | — |
| 0xc0ca322c | 0x4c | per-row dirty flags (kmalloc vir_h; AUTO) | `fb_buffer` |
| 0xc0ca3230 | 0x50 | AUTO frame-end flag (set by the IRQ, cleared by the auto task) | — |
| 0xc0ca3234 | 0x54 | 8-bpp scratch (w·h; REAGL) | — |
| 0xc0ca3238 | 0x58 | status-bar backup (w·h/2; REAGL) | — |
| 0xc0ca323c | 0x5c | `ebc_auto_taskup` task | — |
| 0xc0ca3240 / 44 | 0x60 / 0x64 | REAGL rotation / pass-2 pending | — |
| 0xc0ca3250 | — | `epd_lut` `lut_info`: +0 spi info, **+4 waveform pointer**, +8 cached mode, +0xc cached temp range | `lut_info` (0x10) |
| 0xc0ca3260 | — | decoded `tbl[f][32][32]` (0x400 B per frame, 0x80000 B = up to 512 frames); 0xc0ca327e/0xc0ca365f = offsets into it used by `a2_bk`/`reagllut` | `waveformdata` |
| 0xc0d23260 | — | `parse_mode_version` index table (8 ints) | (was `reset_data`) |
| 0xc0d28b90 | — | `spi_id_buffer` (32 B panel string) | `spi_id_buffer` |
| 0xc0d2ac44 | — | buf_manage state (pool and display list) | `ebc_buf_info` |
| 0xc0d2ac68 / 0xc0b47164 | — | `gprint_dir_or_file` (0) / `gebc_dbg_lev` (3) | |
| 0xc0d2ac6c / 0xc0d2ac74 | — | PMIC: cached VCOM / `pmic_sess_data` | |

### 4.3 `struct ebc_buf_s` (0x24 B; SAME as `bufmanage/buf_manage.h`)

`+0 status (0 idle/1 busy), +4 phy_addr, +8 virt_addr, +0xc buf_mode, +0x10 len, +0x14 win_x1, +0x18 win_y1, +0x1c win_x2, +0x20 win_y2`.
- The pool and the display list are `buf_list_t {nb_elt, int *array, maxelements = 100}`.
- The window is used by:
  - the LUT engine (WIN_DSP/WIN_ACT = (x2−x1) | (y2−y1)<<16, DSP_ST += x1/4 and y1; image address `§8`);
  - `full_win_mode_data_change` (x in 4-px units, inclusive bounds);
  - REAGL ignores it.

### 4.4 Waveform header bytes the kernel reads (WBF; `abi/ebc-abi.md` §6 and [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform) have the full header)

| off | read by | use |
|---|---|---|
| 0x10 | `parse_mode_version`, `get_lut_frame`, `epd_lut_reagle` | mode version (0x19): index table, decoder choice |
| 0x16 | error printk | (wf_type, printed only) |
| 0x20 | `get_lut_frame` | **low byte** of `wmta` = mode-table offset (0x5f) |
| 0x26 | `get_lut_temp` | temperature-range count − 1 (13) |
| 0x30.. | `get_lut_temp` | range bounds 0,3,…,43,48 |
| 0x41.. | `epd_lut_from_nand_init` | 32 B panel string → `lut_version` |
| 0x00..0x03 | `epd_lut_from_nand_init` | CRC bytes, printed only |
| mode table / temperature table | `get_lut_frame` | 24-bit pointer + 8-bit sum checksum each, verified on every decode |

No file CRC is checked for WBF.

### 4.5 EBC registers (base 0x10114000, `EBC_REG` of rychly `ebc.h`, confirmed by the regbak shadow offsets)

| Register | Offset | Notes |
|---|---|---|
| DSP_START | 0x00 | bit0 go, bits 2..7 = frames−1 |
| EPD_CTRL | 0x04 | written at probe: `(hsync+gdck_sta)<<27 \| 3 \| (…)<<16 \| min(width/4,255)<<8`; power bits 2..4 via the dead `set_gdpwr0` |
| DSP_CTRL | 0x08 | bit29 partial, bit28 LUT mode, bit27 chunk-continue, `0xc0030000` always |
| H/VTIMING0/1, DSP_ACT_INFO | 0x0c..0x1c | |
| WIN_CTRL | 0x20 | `0x20fc0 \| fmt` |
| WIN_MST0 | 0x24 | old image, or the direct buffer |
| WIN_MST1 | 0x28 | new image |
| WIN_VIR | 0x2c | vir_width \| vir_height<<16: the real stride |
| WIN_ACT, WIN_DSP, WIN_DSP_ST | 0x30..0x38 | |
| INT | 0x3c | bit1 = frame end; acked via bits 6/7/8; bit4 mask; `n<<9 \| 0x28` written at start [meaning GUESS] |
| VCOM0..3 | 0x40..0x4c | zeroed |
| CONFIG_DONE | 0x50 | 0xffff after every config |
| **LUT SRAM** | +0x1000..+0x1fff | 64 frames × 16 words |

## 5. Unicorn verification

`tools/ebc_emu.py` follows the pattern of `../reagl/tools/reagl_emu.py`:
- each stock function is entered alone in Unicorn 2.1.4;
- kernel calls are replaced by `bx lr` stubs emulated in Python (`memcpy`, `memset`, `__memzero`, `printk`, `schedule`, `__aeabi_idivmod`, `do_gettimeofday`,
  `flush_tlb_all`, `kmalloc_order_trace`, and the cache-flush pointers);
- any unmapped access aborts the run;
- every group also runs a **mutated reference**, which must disagree at least once.

The `.uu` objects are never executed.

**Result: 1044 cases, 0 failures for seeds 1, 3 and 7** (about 5 s per run). "mutation not detected in: none" for all 26 groups. The re-run with seed 7 for this report
also gave 0 failures.

| group | cases | mutation diffs | result / finding |
|---|---|---|---|
| `decodewaveform_19` via `get_lut_frame`, **real WBF**, 8 modes × 14 ranges (+ range −1) | 120 | 106 | the full 512 KB table matches an independent WBF decoder. `tbl[f·1024 + OLD·32 + NEW]`; the stream's fast index is OLD |
| frame count at range 8 = device | 3 | 3 | INIT 113, DU 22, GC16 38 (also A2 10, DU4 24) = dmesg |
| `get_lut_frame` bad checksum | 1 | 1 | −1 |
| `get_lut_temp` | 130 | 56 | **43–50 °C → caller's r3 (0) → range 0** |
| `parse_mode_version` | 7 | 7 | the tables for 0x12/0x18/0x19/0x20/0x23 and the default |
| `get_lut_mode` | 84 | 84 | types 0/7 → caller's r4 (wild read, latent) |
| `epd_lut_data_get_pvi_hard`, type × temp × tag, real WBF | 80 + 1 | 78 | the cache key is (tag = EPD mode, range); types 3/7 give an empty LUT and a stale `frame_num` |
| `get_lut_data_hard` / `get_lut_data` / `get_lut_data_a2_bk` | 4 / 20 / 4 | 4 / 12 / 4 | packing as in `§2.5`. `get_lut_data` zeroes the diagonal for tags 2/3 and patches [29]/[31] for tag 15; `a2_bk` writes DU into columns 0/30 for rows 0..30 |
| `full_win_mode_data_change` (+ schedule) | 24 + 1 | 11 | honours the window, with inclusive bounds |
| `direct_mode_data_change` | 24 | 14 | the `old == 2·new` bug |
| `check_part_mode` | 72 | 72 | drop / DU promotion |
| `get_auto_image_new_hard`, 30 chained frames up to 1448 wide | 120 | 24 | per-pixel engine |
| `crc_32` | 5 | 4 | polynomial **0x04C10DB7** (one bit off CRC-32), init 0. Ghidra drops the loop body |
| `epd_lut_check_temp`, `panel_data_translate` | 204 / 8 | 109 / 8 | rkf temperature ranges; E Ink panel-ID charset |
| dead: `direct_mode_data_change_text`, `set_window_part` | 4 / 8 | 4 / 2 | |
| dead asm: `refresh_new_image_sARM`, `get_auto_image_sARM`, `check_auto_image_sARM`, `direct_mode_sARM`, `direct_fullwin_mode_sARM` | 20/20/40/20/20 | 19/5/19/19/20 | the old AUTO engine. `direct_fullwin_mode_sARM` drives asymmetrically (word pairs); `direct_mode_sARM` has no 2× bug |

Other emulation findings:
- **A malformed stream can overflow the table.** `decodewaveform_19` checks the 512-frame limit only after a whole RLE run, so a stream with no 0xFF can write up to 1023 codes past the
  table into `parse_mode_version`'s index table. It needs a corrupt waveform, which `/ebc_waveform.bin` is never checked for.
- **Range −1 gives garbage tables.** For a negative temperature, range −1 makes `get_lut_frame` read the 4 bytes before each mode's temperature table. The checksums pass and the
  result is garbage: GC16 4 frames, A2 512. This is unreachable, because the clamp in `ebc_register_update` is unsigned.

The reference implementations are the `ref_*` functions in `tools/ebc_emu.py`.

## 6. Tunables, sysfs/proc/dev nodes

- **Runtime tunables: none for the update policy.** There are no module parameters.
  - Every threshold is a compiled constant: `get_reagl_diffnum` 200, `get_statusbar_hight` 83, `get_bottom_hight` 0, `get_bootup_logo_cycle` 2000 ms,
    `get_bootup_ani_mode` 3, the 3 s frame watchdog, the 100 ms idle busy-wait, the queue-collapsing rules, the 0..50 °C clamp.
  - Changing any of them means patching the Image ([DANGER]).

| node | mode | owner | read | write |
|---|---|---|---|---|
| `/dev/ebc` | (ueventd) | `ebc_ops` | — | ioctl 0x7000–0x7004, mmap (no bound) |
| `/sys/devices/platform/rk29-ebc.0/ebc_dbg` | 0644 | `ebc_dbg_read/write` | help text to dmesg, 0 bytes | 5 chars → trace mask |
| `/sys/devices/platform/rk29-ebc.0/lut_version` | 0644 | `wvf_version_read` | WBF panel string (`320_R110_AE4D21_ED060KD1C2_TC` + junk) | ignored |
| `/sys/bus/i2c/drivers/tps65185/vcom_mv` | **0666** | `vcom_mv_get/set` | cached VCOM, 10 mV units | **programs the PMIC EEPROM** |
| `/proc/epdsensor` | 0444 | `proc_lm_show` | PMIC temperature °C (I²C + 10 ms) | — |
| `/proc/panel_info` | 0444 | `proc_read_panel_info` | panel part/VCOM/waveform/barcode/MD5 from the panel SPI flash | — |
| `/dev/spi_flash` | 0600 | `spi_flash_*` | broken read (`§2.10a`) | 64 KB RMW write to the panel flash |
| `onyx_misc.0/support_regal`, `vcom_value`, `pmic_temp` | 0444 / 0666 / 0444 | outside this span (ONYX `onyx_misc` driver; see onyx-rc2-hardware) | 1 / live VCOM / always "25" | — / programs VCOM / — |

## 7. Corrections to `abi/` (the older ABI document)

[`abi/ebc-abi.md`](../abi/ebc-abi.md) and `abi/epd-modes.tsv` were written before this driver analysis. Where they disagree, the
statements below win.

1. **`ebc-abi.md` §3 / `epd-modes.tsv`: "7 TEXT → type 2".**
   - Stock `ebc_thread` **rejects** mode 7, as well as 13 and 14: `(1<<m) & 0x9f7e` [CONFIRMED-dis 0xc060fa54].
   - The `.uu` accepted 0–12. A 7 leaks a buffer exactly like 16 (`../reagl` §3).
   - The same holds for "13/14 → (2) if ever sent".
2. **`ebc-abi.md` §3: "the kernel switch accepts `buf_mode` 0..16".**
   - That switch (`ebc_register_update`) is reached only after the `ebc_thread` filter, so the real accepted set is {0–6, 8–12, 15}. 16 is internal only; this was already noted by `../reagl`.
3. **`ebc-abi.md` §1 mmap: "the mapping holds up to 8 frames [STRONG]".**
   - The pool is **4 slots of w·h bytes**: `bits_per_pixel` = 8 in probe, 8-bpp capacity for AUTO.
   - This closes the slot-count [VERIFY] with "4".
4. **`ebc-abi.md` §6: which waveform copy is used [VERIFY].**
   - The **ramdisk file `/ebc_waveform.bin`**, read by the kernel into the `waveform_addr` window, overwriting the loader's copy.
   - Missing file → the built-in V110 array (`§2.9`).
5. **`epd-modes.tsv` lut type column ("type 2 (windowed)" for 9, "type 2" for 11, "type 6" for 12).**
   - The types are right, but **9, 11 and 12 do not use the hardware LUT engine.** They are computed per frame on the CPU (direct mode, DSP_CTRL without bit 28).
   - Mode 0 is the CPU AUTO engine (type 5 = merged GC16+DU table).
   - Mode 9 honours the window; 11/12 ignore it.
6. **`epd-modes.tsv` "3 PART → GC16 (partial)" and "6 BLACK_WHITE ← gralloc A2 exit".**
   - The kernel itself also turns PART/OED_PART/DIRECT_PART into **DU (6)** when every changed pixel is pure 0/15 [CONFIRMED-log 79 DU builds].
   - It also **drops** them when nothing changed.
   - The "who sends it" for 6 is incomplete.
7. **Waveform decode (onyx-rc2-waveform): `lut_temp = 8` "is the range index".**
   - Correct. Add: temperatures ≥ 43 °C map to range **0** (`get_lut_temp` fall-through), and < 0 °C to 25 °C.
8. **`ebc-abi.md` §6: "`get_lut_mode` … 8/9 → map_to_pvi_mode(8) = 5".** Agreed. Add: **type 7 indexes with an uninitialised register** (dead path).
9. **`ebc-abi.md` §1 kernel addresses use `file offset + 0xc0008000`.** All VAs in this report and in `../reagl` are file offset + **0xc0408000** (the runtime VA).
10. **Stock gralloc auto-full: "the counter counts gralloc sends" (`abi/ebc-abi.md` §3).**
    - Also note that the kernel may **collapse** queued sends (`§2.2`), so gralloc sends ≠ panel updates even without the waveform-time throttling.

## 8. Notes for a userspace client or a new driver

**Rules a userspace client of this kernel must respect:**
- Send only modes **0–6, 8–12, 15** to 0x7001. Never 7, 13, 14 or ≥16: each one leaks one of 4 slots, and then GET_EBC_BUFFER blocks or recurses (`§2.2`).
- For LUT modes (1–6, 8, 10, 15) send the **full window** or at least **`y1 = 0`**. `ebc_image_addr_set` uses a 1024-px stride [CONFIRMED-dis 0xc060b4b4], so any
  other start row reads the wrong memory [STRONG].
  - Keep x1 a multiple of 4: DSP_ST uses x1/4 and the address uses x1/2.
  - The stock gralloc can violate this (auto-full turning an A2-exit FULL_WIN into mode 1 with the same window).
- Expect **at most 3 slots usable** by userspace (one is pinned as "old"). GET_EBC_BUFFER blocks while the thread is busy. Do not call it from a thread that may be signalled
  while slots could be leaking.
- **Not every posted frame is displayed.** Queued PART-class frames are collapsed; identical PART frames are dropped; PART with only black/white changes runs as DU.
  - Skipping updates whose pixels are unchanged is **already done by the kernel for modes 3/10/11**, before PMIC power-up.
  - What a userspace skip would still save: the conversion, the 100 ms busy-wait and the auto-full count.
- **Do not send OED_PART (10).** It builds no LUT, so it shows nothing (known).

**Costs** (useful for any settle/debounce design in userspace):
- **Idle → first update:**
  - 100 ms busy-wait (one CPU core spins);
  - PMIC power-up ~25 ms;
  - I²C temperature ≥ 10 ms;
  - waveform decode;
  - on a mode change, a 512 KB LUT rebuild;
  - then the waveform time (11.96 ms per frame: GC16 0.45 s, DU 0.26 s, A2 0.12 s at 24–27 °C).
- **Back to back:** one GC16 update per ~0.47 s [CONFIRMED-log].
- **Any mode switch** (e.g. 1 ↔ 3, 3 ↔ 6 through the DU promotion, 15 ↔ 16 inside REAGL) rebuilds the LUT. Alternating modes cost more than a steady mode.
- **CPU engines:**
  - modes 0, 9, 11 and 12 compute every waveform frame on the CPU (SCHED_FIFO 99) over the whole w·h frame;
  - mode 9 (the stock gralloc's A2-exit pass) is the heaviest common one;
  - FULL (1) or PART (3) are cheaper where the choice does not matter.
- **The kernel already has a ~100 ms debounce plus collapsing for PART-class frames.** A userspace settle timer adds on top of it.

**Latent bugs:**
- Temperature ≥ 43 °C → range-0 waveform; < 0 °C → 25 °C. A summer-heat or cold-start issue; it cannot be fixed without patching the kernel.
- The **`ebc_image_addr_set` stride** (above).
- **`ebc_empty_buf_get` recursion** on a signal while the pool is exhausted (`§2.2`).
- **VCOM EEPROM writable by any app** (`vcom_mv` 0666, `onyx_misc` `vcom_value` 0666) and by a USB host in mass-storage mode. Userspace should restrict the two nodes (e.g. in init.rc).
- **`/ebc_waveform.bin` is trusted blindly.** A ramdisk for this kernel must carry the stock file byte-identical (sha256 `fe72b4ba…`), and the stock parameter must keep `waveform_addr=`.
- **The power-up failure is swallowed.** A PG timeout gives a blank update with no error.
- **The kernel reads the pool through a cached mapping** while userspace writes through write-combining. `check_part_mode` does not flush first. A stale-cache false "unchanged"
  is theoretically possible [GUESS; not seen].
- **One `eink mode = %d` printk per frame** at KERN_WARNING. It fills the console log and costs a little per frame.

**Power policy:**
- The panel is powered only while frames run, so userspace power management needs nothing for the EBC.
- Suspend does not drain the queue; an update running at suspend time is cut [STRONG].
- The `ebc` wake lock is held only during updates.

## 9. Still [VERIFY]

1. DSP_CTRL bits 27/28/29 and INT bits: names come from rychly `ebc.h`; the meanings are inferred (A/B on the device as in `../reagl`).
2. Real CPU time of a mode-9/11/12 or AUTO frame (does it keep up with 11.96 ms?), and the length of the pause between 64-frame LUT chunks.
3. Whether the 1024-stride window bug is reachable in the stock 4.2 stack: needs auto-full to fire at an A2 exit. Visual check: a corrupted band after an A2 session.
4. UPSEQ 0x39/0x11 versus the ED060KD1 spec; the USB vendor command encoding for VCOM.
5. Who loads the loader copy at 0x7ff00000 (it is overwritten anyway).
6. The cache-coherency GUESS in `§8`.

## 10. Reproduce

```sh
# IMAGE    = the stock 2017 kernel Image (sha256 47a13cf3…, see the top README)
# KALLSYMS = its kallsyms:  python3 -I kernel/extract_kallsyms.py "$IMAGE" "$KALLSYMS"
# RK       = drivers/video/rockchip/rk_epd of the public rychly/rk3026-linux-sources tree (the .uu objects)
IMAGE=… KALLSYMS=… RK=… driver/tools/run.sh <scratch-dir>   # Ghidra (Image + .uu objects), objdump listings, objdiff, inventory -> <scratch-dir>/out/
python3 -I driver/tools/objdiff.py "$IMAGE" "$KALLSYMS" <scratch-dir>/out/uuobj -v --only ebc_thread
python3 -I driver/tools/kdis.py "$IMAGE" "$KALLSYMS" ebc_image_addr_set
python3 -I driver/tools/kdis.py "$IMAGE" "$KALLSYMS" --callers get_auto_image_sARM rk29_ebc_set_auto_power_off
uv run --script driver/tools/ebc_emu.py "$IMAGE" "$KALLSYMS" ebc_waveform.bin
```

- Requirements: Ghidra 12.1.4 + OpenJDK 21, GNU binutils (`OBJDUMP=`/`BINUTILS=` if not in the Homebrew location), uv.
  `run.sh` and `ebc_emu.py` check the Image sha256: they work only on the 2017 Image, because `ebc_emu.py` also pins its data/bss addresses.
- `ebc_waveform.bin` (sha256 `fe72b4ba…`) comes out of the public update with `extract_waveform.py` from [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform).
- Do not publish what the tools produce: the decompiles, uudecoded objects and their disassembly are vendor code.
