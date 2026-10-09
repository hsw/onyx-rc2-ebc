# Source availability

The EBC driver described in this repository is part of the Linux kernel that ONYX ships on the BOOX Robinson Crusoe 2. The kernel
is GPLv2. This page lists what in the RC2 firmware is GPL-licensed kernel code, what source for it we could find, and what we could
not. Status as of 2026-10-09.

## The kernel

| | |
|---|---|
| What | Linux 3.0.36+, raw ARM Image in the `boot` and `recovery` images |
| Firmware 1.8.2 (on the device) | built 2017-11-07, sha256 `47a13cf3bf642c7daf8ab1b3716db56fae7d1b85f7b4e552bdb97edd062030af` |
| Firmware 1.9.1 (public update, [support page](https://onyx-boox.ru/support/boox_robinson-crusoe2)) | built 2019-11-05, sha256 `56bb7228a064f6a1…` |
| License | GPLv2 (Linux) |
| Corresponding source | **none found** |

The EBC driver is **built into the kernel**, not a module: its initcalls (`rk29_ebc_init`, `tps65185_init`, `onyx_misc_driver_init`) are
in the Image's initcall table ([`kernel/image-initcalls.txt`](kernel/image-initcalls.txt)).

The kernel carries **vendor changes that are not in any public tree**:
- EBC driver: compared with the older public `.uu` objects, 32 functions are new and 36 changed
  ([`driver/README.md`](driver/README.md) §0, §3). ONYX-specific parts include the REAGL key `onYxeNCy`, `/proc/panel_info`, the
  panel SPI-flash layout and VCOM auto-fix, the TPS65185 power-up sequence override, and ioctl 0x7004.
- Board code: ONYX functions such as `onyx_pcb_ver_setup`, `onyx_get_pcb_version`, `onyx_bootmedia_setup`, `onyx_vibrator_enable`,
  `onyx_hall_sensor_power`, `onyx_tp_power_enable`, `onyx_wifi_bt_module_power` and the `last_log_*` functions (names from the
  Image's kallsyms; see [onyx-rc2-hardware](https://github.com/hsw/onyx-rc2-hardware)).

## Kernel modules

Shipped in `/system/lib/modules` of both firmware versions; the license is the module's own `MODULE_LICENSE` string.

| Module | Declared license |
|---|---|
| `mali.ko`, `ump.ko` (ARM Mali-400 r3p2 kernel driver) | GPL |
| `8188eu.ko`, `8189es.ko`, `8192cu.ko`, `8723as.ko`, `8723au.ko`, `8723bu.ko` (Realtek Wi-Fi), `mt5931.ko` (MediaTek Wi-Fi) | GPL |
| `rtk_btusb.ko` (Realtek Bluetooth) | GPL |
| `rk29-ipp.ko` | GPL |
| `rkwifi.ko`, `rkwifi.oob.ko` | GPL v2 |
| `wlan.ko` | Dual BSD/GPL |
| `vpu_service.ko` | no license string |
| `rk30xxnand_ko.ko` (NAND/eMMC driver, in the boot ramdisk) | empty license string |

Upstream releases exist for some of these drivers (ARM's Mali r3p2 code drops, Realtek drivers in various vendor trees), but no source
for these builds has been published.

## Where we looked

- **ONYX** publishes no RK3026 kernel. The `onyx-intl` GitHub organization (30 repositories) has kernels for older non-Rockchip devices
  and an old Rockchip SDK without the kernel; nothing for RK3026 and no EBC code.
- **The firmware itself** has no written offer for the kernel or modules. `/system/etc/NOTICE.html.gz` reproduces license texts for
  Android components; the kernel, the modules and their source are not mentioned.
- **Other RK3026 trees** ([rychly/rk3026-linux-sources](https://github.com/rychly/rk3026-linux-sources),
  [ridi/linux-paper](https://github.com/ridi/linux-paper)) contain the EBC core (`hardware_ebc`, `epd_lut`, `bufmanage`) only as
  precompiled `.uu` objects of an older generation. No tree with its source is known to us.
- **Users have asked.** On the 4PDA forum, a firmware modder reports asking ONYX for sources with no response
  ([2017-09-19](https://4pda.to/forum/index.php?showtopic=678336&view=findpost&p=65195248)); users note that the vendor shares nothing
  and that the kernel source should be published ([2018-03-07](https://4pda.to/forum/index.php?showtopic=841755&view=findpost&p=71090245));
  the official ONYX Russia account was asked to publish GPL sources
  ([2019-03-30](https://4pda.to/forum/index.php?showtopic=748886&view=findpost&p=83911172)). We found no reply.

## What this means for this repository

The vendor kernel code described here was distributed in binary form, and its source was not available from the vendor. To run
other software on the device and to write new drivers for its hardware, we studied the binary. This repository publishes descriptions
(behaviour, data layouts, register use, defects) and our own tools. It contains no vendor code and no vendor binaries.
