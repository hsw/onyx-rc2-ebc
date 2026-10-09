# Stock RC2 kernel Image: layout, vendor code map, how to decompile a piece

Written 2026-10-08. This is a static map built from the kallsyms recovered with [`extract_kallsyms.py`](extract_kallsyms.py) and the two public trees (§1).
Use it to find where something lives in the Image and whether public source exists. Use it before starting a decompile.

## 1. The Image

| Fact | Value |
|---|---|
| File | The stock kernel Image: the KRNL payload of the device's `kernel` partition (the same kernel is in `recovery.img`). 7 766 052 B, sha256 `47a13cf3…30af` (see the [top README](../README.md#the-analysed-kernel)) |
| Format | Uncompressed ARM Image (not a zImage), ARMv7 little-endian, ARM mode (Thumb only in a few lib routines). No IKCFG. Version `3.0.36+ … Tue Nov 7 21:44:55 CST 2017` |
| Mapping | Loaded at PA 0x60408000; **VA = file offset + 0xc0408000**. File end = VA 0xc0b70024 |
| Symbols | kallsyms (text, init, rodata and markers; **no data/bss symbols**, KALLSYMS_ALL off) → 38 721 entries, recovered with `extract_kallsyms.py` |
| Closest public source | rychly `rk3026-linux-sources` (Rockchip RK3026 E-Ink SDK, 2013) → `linux-rockchip` stable-3.0 (2014; ≈ Nu3001 base). 568/569 `__FILE__` paths exist there |

## 2. Section map

ARM 3.0 linker order: init first, then text, then read-only data, then data. The bss is not in the file.

| VA range | File offset | Size | Content |
|---|---|---|---|
| 0xc0408000–0xc0429358 | 0x000000–0x021358 | 133 KB | **init text** (`_sinittext`…`_einittext`), freed after boot. Head, `start_kernel`, `setup_arch`, the machine/board init and DVFS tables (`board_clock_init` 0xc040eaa8, `rk3026_pm_init` 0xc040db44), early `__setup` handlers (`onyx_bootmedia_setup`/`onyx_pcb_ver_setup` 0xc040e2f8), and every driver `*_init` (for example `rk29_ebc_init` 0xc0419b1c, `cyttsp4_*_init` 0xc041d278, `cw_bat_init` 0xc041e2ec, ONYX `gpio_led_init` 0xc041eda8 for `leds-ctl`; `leds_init` 0xc041ed50 is the standard LED class). Order: arch/arm → init → kernel → mm → fs → drivers → net |
| 0xc0429358–0xc042a228 | | 3.8 KB | `__tagtable`, `__setup` table 0xc04293e0, **initcall table** 0xc042983c–0xc042a228 (635 pointer slots, 7 of them early; names in `image-initcalls.txt`) |
| 0xc042a228–0xc042a428 | | 512 B | Built-in initramfs (the default empty cpio; the real ramdisk comes from the boot partition) |
| 0xc042a428–0xc0443000 | | ~100 KB | init data (`tmp_cmdline`, percpu setup buffers…), `__start_ftrace_events` 0xc0441f88 |
| 0xc0443000–0xc0444b40 | | 7 KB | per-cpu template |
| **0xc0445000–0xc08c16a8** | 0x03d000–0x4b96a8 | **4.5 MB** | **.text** (`_text`). Exception text first, then the link order in §3. Ends with `__sched_text` 0xc08be470–0xc08c0d24, `__lock_text` …0xc08c16a4, `__kprobes_text` (empty) |
| 0xc08c16a8–0xc0a02000 | 0x4b96a8–0x5fa000 | 1.3 MB | Const data still inside `.text`, marked `t` in kallsyms: `linux_banner` 0xc08c1fc1, `__func__`, `print_fmt_*`, `CSWTCH`, ops tables, and the **kallsyms tables** (addresses 0xc090d740, names 0xc0933460, markers 0xc09a2860, token_table 0xc09a2ac0, token_index 0xc09a2e50) |
| 0xc0a02000–0xc0a28000 | 0x5fa000–0x620000 | 152 KB | `__start_rodata`: tracepoint ptrs, `__ksymtab` 0xc0a036b4, ksymtab_gpl, kcrctab (empty, MODVERSIONS off), `__ksymtab_strings`, `__param` 0xc0a26cd8, `__modver` |
| 0xc0a28000–0xc0a52818 | | 170 KB | ARM unwind tables (`__start_unwind_idx`, `__start_unwind_tab`) → `_etext` 0xc0a52818 |
| 0xc0a54000–0xc0b70024 | 0x64c000–0x768024 | 1.1 MB | **.data** (starts with `init_thread_union`). Platform data, `struct device_attribute`/`file_operations` tables, waveform/LUT tables live here. No symbols: reach them through literal pools or `sysfs_attrs.py` |
| 0xc0b70024–… | not in file | ≥1.2 MB | **.bss**. Examples: the EBC global block ~0xc0ca31e0 ([`reagl/README.md`](../reagl/README.md)) and the `/proc/idle` cell pointer 0xc0c76488. The Ghidra import maps bss up to 0xc1600000 |

## 3. Link order inside .text (approximate, ±1 KB)

Directory runs were computed with a layout script over kallsyms and the public trees (§6; working files, not published).

| VA range | What |
|---|---|
| 0xc0445000–0xc04653fc | arch/arm (entry, traps, VFP, mm, cache; mach-rk3026 + plat-rk runtime code: clocks, DVFS 0xc045d90c, **ONYX board-file functions 0xc045de28–0xc045f428**, `rk3026_pm_*` 0xc045c470, SRAM/DDR code) |
| 0xc04653fc–0xc04ce8fc | kernel/ (sched, signal, time, module, cgroup, **power: `kernel/power` 0xc04aff38–0xc04b06e8 incl. ONYX/RK `idle_proc_*`, `suspend_irqwake_set`**, trace) |
| 0xc04ce8fc–0xc0503454 | mm/ |
| 0xc0503454–0xc05b7be0 | fs/ (VFS, proc, sysfs, ext3, **ext4 208 KB**, jbd, jbd2, fat, fuse) |
| 0xc05b7be0–0xc05f6c64 | crypto/, block/, lib/ |
| 0xc05f6c64–0xc05f9c68 | drivers/gpio |
| 0xc05f9c68–0xc0617604 | drivers/video, broken down below |
| | 0xc05f9c68–0xc0602670: fbmem, backlight (`rk29_backlight.c` 0xc06003a4), cfb* |
| | 0xc0602670–0xc0607148: `rockchip/rk_fb.c`, `rkfb_sysfs.c`, `lcdc/rk3188_lcdc.c`, `rk3026_lvds.c` |
| | 0xc0607148–0xc060b29c: RGA |
| | **0xc060b29c–0xc06165d4: E-Ink core, no public source.** Contents: `hardware_ebc` (ebc_thread, ioctl, REAGL), `epd_lut`, `buf_manage`, `epd_spi_flash`, `boot_ani` |
| | 0xc06165d4–0xc06166c0: `ebc_dbg` |
| | 0xc06166c0–0xc0617604: `rk_epd/epdpower/tps65185.c` (papyrus_*) |
| 0xc0617604–0xc061c0a8 | drivers/regulator (core, `act8931.c`, `charge-regulater-adc.c` with **ONYX `act8931_charge_*` 0xc061bbb0**) |
| 0xc061c0a8–0xc0640594 | drivers/tty, char, base (+ firmware, power) |
| 0xc0640594–0xc0640a14 | **ONYX `onyx_misc`** (drivers/misc) |
| 0xc06427fc–0xc06ac334 | scsi, mtd (+ rknand glue), spi, net (usbnet, axusbnet…), usb (core, dwc_otg, gadget/android) |
| 0xc06ac334–0xc06cd3bc | drivers/input. Keyboard `rk29_keys` with **ONYX patches 0xc06b1a28**; touchscreens: Goodix gt9xx 0xc06bae6c–0xc06bd46c, **cyttsp4 0xc06beb84–0xc06c82cc (~38 KB)**; keychord |
| 0xc06cd3bc–0xc070f5d0 | rtc (`hym8563`, ONYX `hym8563_disable_alarm` 0xc06d1324), i2c, media (IR, v4l2), power_supply (**CW2015 `cw_bat_*` 0xc06e8420**, ONYX `cw_disable_batt_low_irq`), md/dm, cpufreq, mmc, **ONYX `leds-ctl` fops 0xc070efa8** (status LED GPIO2_B7) |
| 0xc070f5d0–0xc0730ed8 | hid, staging/android (binder 0xc07295a4, ashmem, logger, lmk, timed_output; **ONYX `onyx_vibrator_enable` 0xc07308b0**) |
| 0xc0730ed8–0xc0753180 | sound/ (core, soc; `codec_get_spk` 0xc074f0c8) |
| 0xc0753180–0xc08affa0 | net/ (core, sched, netlink, netfilter, ipv4, xfrm, unix, ipv6, packet, key, bridge, **bluetooth 138 KB**, phonet, wireless/cfg80211, mac80211) |
| 0xc08affa0–0xc08c16a8 | `.cpuinit`/`.meminit`/`.devinit` leftovers (exit paths, probe functions like `spi_flash_probe` 0xc08b4604, `cyttsp4_i2c_probe` 0xc08b5c48, `gup_init_panel`), then sched/lock text |

## 4. Code without public source (vendor map)

The layout script lists clusters of text functions whose names occur in neither public tree; macro-generated names are filtered. Total ≈ 87 KB in 585 functions. More than 70 % of it is EBC + cyttsp4.

| Block | VA | Size | Origin | Status |
|---|---|---|---|---|
| E-Ink core (EBC, LUT, REAGL, buffers, SPI flash, boot animation) | 0xc060b29c–0xc06165d4 | ~45 KB | Rockchip + ONYX; older `.uu` objects exist in rychly | REAGL: [`reagl/README.md`](../reagl/README.md). Full driver: done, [`driver/README.md`](../driver/README.md) (203 functions: 80 same as `.uu`, 36 changed, 32 new, 55 public C) |
| cyttsp4 touch (bus/core/i2c/mt/device_access) | 0xc06beb84–0xc06c82cc + init/probe | ~38 KB | Cypress TTDA Gen4 "bus" driver. **No public source for this version was found**: rychly has only headers and a prebuilt `cyttsp4.uu` (238 text symbols, 114 shared with the Image). 60 Image functions are not in that object, including the bus/adapter layer and **`cyttsp4_cal_store/show`** (the `cyttsp4_cal` node; the `.uu` has a different `cyttsp4_calibrate_store` in device_access). Mainline 3.13 `cyttsp4_core.c` is a different rewrite. A public TTDA 2.x source with the bus API was not searched for [VERIFY] | Only `cyttsp4_cal_store` decoded. The rest is low value while touch works |
| Goodix gt9xx (`gtp_*`, `gup_*`) | 0xc06bae6c–0xc06bd46c, 0xc08bd478 | ~6 KB | Goodix GPL driver; alternative touch for other boards | Not needed |
| ONYX board file (`onyx_*` power rails, pins, pcb version, Wi-Fi/BT power, Hall, EBC board power) | 0xc045de28–0xc045f428 (mixed with RK board code) | ~6 KB | ONYX | Done: see [onyx-rc2-hardware](https://github.com/hsw/onyx-rc2-hardware) (pcb V1.73; also leds-ctl, `codec_get_spk`, vibrator) |
| Power management (`rk3026_pm_*`, `rk_soc_pm_ctr`, suspend voltages, `kernel/power` idle/irqwake, `act8931_charge_*`, CW2015 patches, HYM8563 alarm) | 0xc040db44…, 0xc045c470…, 0xc04b03e4–0xc04b06cc, 0xc061bbb0… | ~5 KB | mostly public in rychly (`mach-rk3026/pm.c`, `kernel/power/irqwake.c`, `idle_control.c`); stock-only deltas: GPLL kept on in suspend, ONYX wake-IRQ choice for idle, `hym8563_disable_alarm` hook | Done: see [onyx-rc2-hardware](https://github.com/hsw/onyx-rc2-hardware) |
| `onyx_misc` sysfs | 0xc0640594–0xc0640a14 | 1.1 KB | ONYX | Done (sysfs contract analysed separately; not in this repository) |
| Keypad patches (`key_switching`, touchkey, vibrator) | 0xc06b1a28–0xc06b1f50 | 1 KB | ONYX | Done (analysed separately; not in this repository) |
| cmdline `onyx_emmc=`, `pcb_ver=` | 0xc040e2f8 | 0.3 KB | ONYX | Analysed separately (kernel config reconstruction, board file) |

Loadable modules, outside the Image:
- source exists: `mali.ko`/`ump.ko` (ARM r3p2), `8723bu.ko` (Realtek), `vpu_service`, `rk29-ipp`;
- only `rk30xxnand_ko.ko` (NAND FTL, loaded from the boot ramdisk) is closed. Nothing to gain from decompiling it.

## 5. How to decompile a piece when needed

Rule: the Image is **only read**, never executed natively. Decompiled ONYX/Rockchip code, uudecoded `.o` files and full listings go into a scratch directory outside any repository. **Never commit or publish them.** Reports may quote a few lines to back up a claim.

1. **Locate.** Use the function map (§3–4): VA, size, guessed source file, and whether public source exists. If the source exists, read it in rychly/rk3026-linux-sources or Rockchip's linux stable-3.0 and only confirm the differences in the binary. Find callers with `python3 -I reagl/tools/kdis.py IMAGE KALLSYMS --callers <sym>`.
2. **Quick disassembly** (the arbiter for every claim):
   `objdump -D -b binary -marm --adjust-vma=0xc0408000 --start-address=0x… --stop-address=0x… IMAGE` (GNU binutils).
   `reagl/tools/kdis.py IMAGE KALLSYMS <sym|VA> [stop]` does the same, annotated with symbol names, branch targets and literal-pool strings.
3. **Data structures.** There are no data symbols, so follow literal-pool words (`ldr rX, [pc, #…]`) to .data/.bss addresses.
   - A small scanner (not published) decodes `struct device_attribute` tables and their references.
   - Strings: VA = offset + 0xc0408000.
   - Platform data: follow the pointer passed to `platform_device_register`, `i2c_register_board_info` or `spi_register_board_info` in init text.
4. **Ghidra headless** (C-like pseudocode, about 10 s per run):
   - Copy `reagl/tools/{run.sh,ImportKallsymsRaw.java,DecompileList.java}` into your own `tools/`.
   - Set the address range for which functions are created; it is a postScript argument, e.g. `0xc060b29c 0xc0616700`.
   - Put the function names into a `.list` file and point the output to a scratch directory.
   - The import is `-loader BinaryLoader -loader-baseAddr 0xc0408000 -processor ARM:LE:32:v7 -noanalysis`. `ImportKallsymsRaw.java` splits text/rodata/data, adds bss up to 0xc1600000, labels all kallsyms names, and creates functions only in the requested range plus direct callees, because full auto-analysis of 7.7 MB is slow and noisy.
   - Ghidra 12.1.4 `analyzeHeadless` (Homebrew: `/opt/homebrew/opt/ghidra/libexec/support/analyzeHeadless`), JAVA_HOME = OpenJDK 21.
   - Known Ghidra mistakes on this Image (wrong loop bounds, folded literal pools) are listed in [`reagl/README.md`](../reagl/README.md) and [`driver/README.md`](../driver/README.md) §2.11, so check loops and constants with objdump.
5. **Behaviour checks.** Pixel and LUT code is verified in Unicorn, function by function, as in `reagl/tools/reagl_emu.py`:
   - map the Image read-only;
   - stub kernel calls (`memcpy`, `printk`, cache flushes) as `bx lr` handled in Python;
   - abort on any unmapped access;
   - compare against a Python reference;
   - add a mutation test so the check demonstrably discriminates.
   Extra modules: put a PEP 723 header in the script (`# /// script` / `dependencies = ["unicorn==2.1.4"]` / `# ///`) and run it with `uv run --script <file>`.
6. **Older public objects** for the E-Ink core: rychly `drivers/video/rockchip/rk_epd/*.uu`. uudecode them into scratch (do not execute). They have symbols and relocations, so diffing their objdump against the Image is the cheapest way to separate unchanged Rockchip code from ONYX changes.

## 6. Reproduce

The maps in §3–4 were produced by a layout script over kallsyms and the two public trees (about 40 s). The script and its outputs are
working files and are not published. It produces three files:
- `function-map.tsv`: every init/text function with its size, the source file guessed from the public trees, and whether the name exists in public source;
- `dirs.txt`: directory runs;
- `sourceless.txt`: vendor clusters.

The file guess follows link order: when a name is defined in several files, the one continuing the previous function's file or directory wins. Functions with no definition inherit the previous directory in `dirs.txt`. Treat both as approximate.
