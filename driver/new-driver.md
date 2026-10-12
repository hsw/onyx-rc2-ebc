# Towards a new RK3026 EBC driver

Notes for whoever writes a new E-Ink driver for the RK3026 (mainline or out of tree): what Rockchip's later vendor driver offers,
how small the kernel part can be, and which precedents and public references to follow (§3: mainline `repaper`, E Ink's mode
definitions, the Kindle Paperwhite 3 kernel, epdiy). The register facts are in [`registers.md`](registers.md); the stock driver's behaviour in
[`README.md`](README.md). Confidence marks as in [`registers.md`](registers.md).

The stock RC2 driver cannot simply be rebuilt: there is no source, it is written against kernel 3.0 interfaces (fbdev, wake
locks, rk29 platform data, fixed addresses), and decompiled vendor code is not something to publish as a new driver. A new
driver has to be written from a description such as this repository.

## 1. Rockchip's later vendor driver (`ebc-dev`, 6.1 tree)

Rockchip's kernel trees carry a newer EBC driver for the RK3566/RK3568 in `drivers/gpu/drm/rockchip/ebc-dev/`. Read in the
`develop-6.1` branch (and the identical copy in a public RK3506 SDK, Linux 6.1.99), compared with `develop-4.19`/`-5.10`/`-6.12`
[CONFIRMED-src unless marked]:

- **The core is prebuilt.** `ebc_dev_v8.S` (the driver core: probe, ioctl, threads, direct/AUTO engines, LUT building) and the
  waveform parsers `epdlut/pvi_waveform_v8.S` and `epdlut/rkf_waveform_v8.S` are **AArch64 compiler output** (Linaro GCC 6.3,
  built against 4.19-era headers; core version string "1.05"), not source. They are linked only for `CONFIG_ARM64`, so they are
  useless on the 32-bit RK3026 in any case. In 6.1 the directory is not even referenced by the DRM Makefile/Kconfig (only
  `develop-4.19` builds it), and the blob calls a 4.19-only atomic helper, so it would probably not link [STRONG].
- **Only the glue is C** (GPL-2.0, Rockchip 2020): the TCON layer `tcon/ebc_tcon.c` (the EBC registers), a TPS65185 driver, a
  buffer manager, the waveform-file loader and a notifier.
- **The 1.05 core does not use the LUT engine.** Its debug information shows the mode setter called only with zeros (direct
  mode), and the LUT-upload and frame-address functions never called [STRONG]. The LUT-mode sequence for the RK3026 still has to
  come from the stock RC2 driver ([`registers.md`](registers.md) §3.7).
- **The TCON layer does not fit the RK3026 as is.** Registers 0x00–0x50 are the same block and the `DSP_CTRL` value for an 8-bit
  panel is bit for bit the RC2 one; the V timings match and the H timings differ by 1–2 SDCLK. But on the RK3026:
  - `INT` has three sources, not four: the RK3566 handler clears bit 9 instead of bit 7, so the interrupt is never acknowledged;
  - `WIN_CTRL` enable is bit 17, not 18: the RK3566 value leaves the window disabled and sets unknown bits;
  - `DSP_START` has a 6-bit frame count (≤ 64), not 8 bits; the RK3566 upper bits (`SDCE_WIDTH`, `EINK_MODE`, `OUT_LOW`) are unknown;
  - the LUT holds 64 frames × 16 words (4 KB): the RK3566 upload check of "≤ 256 frames" would write past it;
  - `CONFIG_DONE` is written as 0xFFFF by stock, 1 by RK3566 [VERIFY whether 1 is enough];
  - there is no `VNUM` / `WIN_MST2` (no three-window mode).
- **The `/dev/ebc` ABI is the same family but incompatible**: other meanings for 0x7002–0x7004, a 44-byte buffer-info struct
  instead of 56, a different mode numbering. A client written for the RC2 stock ABI ([`../abi/ebc-abi.md`](../abi/ebc-abi.md)) does
  not run on it.
- **Waveform:** the PVI parser inside the blob accepts mode version 0x19 (the RC2's R110 file would pass), but it picks a
  temperature range one step warmer than the RK3026 driver and never uses the last range [STRONG]. The open decoder in
  [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform) already matches the stock RC2 tables.
- **Its TPS65185 driver is not safe on the RC2**: without a PWRUP GPIO it keeps the panel rails on after the first update until
  system sleep, requires an `int-gpios`, reprograms the VCOM EEPROM from vendor storage, and its VCOM-programming loop has no
  timeout. Use the mainline `tps65185` regulator driver instead (it needs a small patch if PWR_GOOD is not wired to a GPIO; see
  [onyx-rc2-hardware](https://github.com/hsw/onyx-rc2-hardware) `mainline/README.md`).

What is worth taking (GPL-2.0, keep Rockchip's copyright if text is carried over): the names and offsets of the shared registers,
the shape of the TCON layer (a cached MMIO regmap with a short volatile list, the IRQ requested disabled and enabled at power-up,
the start order "mask the other sources → write the count with bit 0 = 0 → `CONFIG_DONE` → bit 0 = 1"), and the panel-timing
property names as a vocabulary. Everything else (the update core, LUT chunks, direct and AUTO engines, the waveform decoder,
buffers, ABI, PMIC) has to be written anew or taken from mainline.

## 2. A minimal in-kernel E-Ink driver

The RK3026 has a **hardware LUT**: the per-pixel "old level → new level" work is done by the controller, not by the CPU. So the
kernel does not need to compute frames, and the driver can be small, which also makes it easier to review.

**What has to stay in the kernel:**
- the controller: timings, frame start, the interrupt;
- loading the LUT in 64-frame chunks from the interrupt: the timing is hard, and a late chunk drives the panel with the wrong
  voltages;
- the old and the new image for DMA, and the update window;
- panel power: the TPS65185 sequence, VCOM, power-off after a timeout; mistakes here can damage the panel;
- protection against overlap: a new update must not start on top of a running one in the same area;
- the temperature used to choose the waveform range (hwmon; it could come from userspace, but the kernel is more reliable).

**What can live in userspace:**
- **parsing the waveform** (WBF/PVI, RKF): a tool turns the file into plain tables "mode × temperature range → frames of 16 LUT
  words"; the kernel loads them as firmware and parses nothing (this also settles the "where to parse the format" question);
- **choosing the mode** (GC16 / DU / A2, and when to do a full refresh against ghosting), as e-reader software already does;
- conversion to 16 grey levels and dithering;
- rotation, merging of regions, the queue policy (stock collapses queued frames and busy-waits 100 ms in the kernel; both belong
  upstairs);
- REAGL and other "smart" modes.

**The remaining API is five items:**
1. a buffer with the image (a DRM dumb buffer or a dma-buf, 4 or 8 bits per pixel);
2. per update: a rectangle (damage clip) and a mode number;
3. an event or fence "update finished on the panel";
4. the LUT tables as firmware in a simple format;
5. the panel temperature for reading (hwmon).

In DRM terms this is a plane with `FB_DAMAGE_CLIPS`, one "update mode" property and a completion event. The only new UAPI is the
mode property, which is exactly where the 2022 RFCs (Samuel Holland's `rockchip_ebc` for the RK3568, Andreas Kemnade's i.MX6 EPDC)
stopped; a small interface is easier to agree between vendors than a driver that parses waveforms and picks modes itself. A
compatible `/dev/ebc` for existing clients of the stock ABI can be a thin out-of-tree wrapper over the same driver core.
Both RFCs, and Rockchip's vendor drivers, are compared with the RK3026 in [`other-controllers.md`](other-controllers.md).

What a simple LUT-firmware format needs: a header (magic, version, panel ID and CRC of the source WBF, number of modes and
temperature ranges, word size), then for each mode × range pair the frame count and the frames of 16 RK3026 LUT words. The
waveform file itself is not redistributable without a grant from its owner; see
[onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform#licensing-and-linux-firmware).

## 3. Precedents and references for the first series

### 3.1 `repaper`: e-paper in mainline DRM without new UAPI

`drivers/gpu/drm/tiny/repaper.c` (in mainline since 2017; GPL-2.0+, Pervasive Displays and Noralf Trønnes; about 1150 lines in
v7.2) drives Pervasive Displays' small black-and-white e-paper panels, which have their own controller on the panel and sit on
SPI. Read in the v7.2 tree [CONFIRMED-src]:

- **Plain DRM, no own UAPI:** a `drm_simple_display_pipe` with the single format `DRM_FORMAT_XRGB8888` and fbdev emulation, so
  ordinary programs and the console work; no ioctls and no "update mode" property.
- **Conversion in the kernel:** `drm_fb_xrgb8888_to_mono()` turns each frame into 1 bit per pixel; the driver keeps the
  previous frame itself.
- **Update policy inside the driver:** the first update clears the panel and draws the image in several stages, later updates
  go from the previous frame to the new one. It always updates the whole screen (a comment says the panel "can't do partial
  updates").
- **Temperature from a thermal zone named in the DT** (`pervasive,thermal-zone`), used to stretch the stage times when cold.
  This is what reviewers asked the 2022 `rockchip_ebc` RFC to do.
- **No waveform:** the stage sequence is fixed in the code; the CPU pushes every frame over SPI.

How a first RK3026 EBC series could follow it [STRONG as a proposal]:
- a DRM driver with fbdev emulation and XRGB8888 (or `R8`) input, converted to 4-bit grey in the kernel;
- the policy inside the driver: full GC16 updates first; later DU for changes that are only black and white inside the damage
  clips, as the stock driver does;
- the temperature from the TPS65185's thermal zone, by DT reference;
- the panel rails and VCOM through the mainline `tps65185` regulators;
- no update-mode property yet: that is the contested part and can come as a separate series once there is agreement. Existing
  e-reader software then runs through fbdev or KMS without its own backend, at the price of no mode choice.

What does not carry over: `repaper` has 1 bit, no greys, no waveform and no hardware controller. For the EBC, with 16 greys, a LUT
memory and a separate PMIC, it is a model for the interface and the shape of the driver, not for the algorithm.

### 3.2 E Ink's mode definitions match the RC2 waveform

E Ink's user manual for its 6" ePaper display kit (ED060KC1, public on E Ink's web shop) defines four standard modes and their
update times at 85 Hz: **INIT** (full erase), **DU** (no flash, any grey to black or white, changed pixels only; 260 ms),
**GC16** (flashing, 16 greys, all pixels; 450 ms) and **GL16** (16 greys, little flashing, white staying white is not driven;
450 ms). The RC2's waveform at 24–27 °C has **DU 22 frames** and **GC16 38 frames**; at the stock 11.96 ms per frame that is
**≈ 263 ms** and **≈ 454 ms**, at 85 Hz 259 and 447 ms [CONFIRMED-device for frame counts and frame time]. GL16 is GC16 without
the 15 → 15 drive, as defined.

For an upstream "update mode" property this gives a vendor-neutral vocabulary: INIT / DU / GC16 / GL16 with E Ink's own short
definitions, mapped by the driver to the mode numbers of its waveform. A2 and DU4 (the stock RC2's fast modes) are not in the
manual and can stay driver extensions.

### 3.3 The Kindle approach (Amazon's GPL kernel)

Amazon publishes the Kindle Paperwhite 3 kernel under the GPL ("Kindle Source Code Notice", release 5.16.2.1.1,
`Kindle_src_5.16.2.1.1_4097470002.tar.gz`, `linux-3.0.35`; EPDC driver `drivers/video/mxc/mxc_epdc_fb.c` with Amazon's
`mxc_epdc_fb_lab126.c`, PMIC `drivers/regulator/max77696-epd.c`). It drives i.MX6 SoloLite's EPDC, not an EBC, but the
division of work is instructive [CONFIRMED-src]:

- **The kernel parses no waveform streams.** From the WBF it reads only the header, the panel name and the voltage-control data;
  the display runs on pre-converted per-mode tables (`imx/epdc_<mode>.fw`) loaded with `request_firmware()`, with a small
  built-in fallback. The converter is userspace and is not in the GPL release. The mode table for mode version 0x19 is the RC2's
  (init, du, gc16, gl16, reagl, reagld, a2, du4); "reagl"/"reagld" are GL16 drive plus image processing in a separate,
  unpublished module.
- **Power:** one regulator for the panel rails, then a wait for PWR_GOOD on an interrupt with a **250 ms timeout**; VCOM is a
  separate regulator enabled **only after PWR_GOOD**, set before each update from the panel passport plus the waveform's
  per-mode offset. On a PMIC fault: off, 1 ms, on again. Power-off order: VCOM first, then the rails.
- **Deferred power-off:** a power-down delay (settable from userspace) keeps the rails up between closely spaced updates.
- **Temperature** is read from the panel's NTC through the PMIC ADC about once a minute, not on every update. Its range lookup
  never selects the hottest range (see [onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform)); an EBC driver should use
  the full table.
- **Panel data from the panel:** the passport in the panel's SPI flash (E Ink's generic layout, the same as on the RC2, see
  [onyx-rc2-hardware](https://github.com/hsw/onyx-rc2-hardware) `panel-flash/`) gives VCOM and the panel identity.

For the RK3026 this is the same model as the mainline `tps65185` regulators plus §2: firmware tables made in userspace, VCOM
after power-good with a timeout and a retry, a deferred power-off. The waveform's voltage-control blocks (VGH +25 V, VPOS/VNEG
±15 V, VGL −20 V on the RC2) let a driver check the PMIC setup at probe.

### 3.4 A userspace converter that exists: epdiy

[epdiy](https://github.com/vroland/epdiy) (LGPL-3.0, an open board and library that drives E Ink panels directly from an ESP32)
already does the split proposed in §2: a `.wbf` goes through its fork of inkwave to a JSON description of the phases, and
`scripts/waveform_hdrgen.py` picks modes and temperature ranges and packs the transitions into per-frame tables as a C header
(`doc/source/filegen.rst`). Its panel list names the ED060KD1 as "should work as ED060XC3", i.e. untested and without its own
timings or waveform. For the RK3026 the same pipeline would end in the LUT-firmware format of §2; the open decoder in
[onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform) already produces tables identical to the stock RC2 kernel's.
