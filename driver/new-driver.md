# Towards a new RK3026 EBC driver

Notes for whoever writes a new E-Ink driver for the RK3026 (mainline or out of tree): what Rockchip's later vendor driver offers,
and how small the kernel part can be. The register facts are in [`registers.md`](registers.md); the stock driver's behaviour in
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

What a simple LUT-firmware format needs: a header (magic, version, panel ID and CRC of the source WBF, number of modes and
temperature ranges, word size), then for each mode × range pair the frame count and the frames of 16 RK3026 LUT words. The
waveform file itself is not redistributable without a grant from its owner; see
[onyx-rc2-waveform](https://github.com/hsw/onyx-rc2-waveform#licensing-and-linux-firmware).
