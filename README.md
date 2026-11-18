# FOX II 286 BIOS Patch

**An upgraded AMI 286 BIOS (06/13/90) for the Octek FOX II (Headland HT12/A): disks up to 8.4 GB, IDE auto-detection, a boot-order option and a readable error instead of a silent hang, and later a POST screen and a new setup in the style of BUBios.**

This is the 286 sibling of the SOYO SY-019L1 project ([BitsUndBolts/SOYO_SY-019L1_504_Patch](https://github.com/BitsUndBolts/SOYO_SY-019L1_504_Patch), locally `P:\git\SOYO_SY-019L1_504_Patch`), which did the same for a 1992 AMI 386 BIOS. That project's guides and emulators are the starting point; this folder records what is different on a 286 and every step taken, so it can become a guide of its own.

**Status: Step 1 (ECHS) built and passing all emulator tests; waiting for the board test.**

## Plan

The work goes in small steps. Each one is tested in the emulator, then burned and tested on the board before the next starts.

| Stage | Step | What | Status |
|---|---|---|---|
| 0 | 0 | Map the original ROM, tools, this folder | done |
| 1 | 1 | **ECHS** translation: disks up to 8.4 GB through INT 13h CHS | **built, emulator tests pass; board test next** |
| 1 | 2 | **Readable INT 06h error**: a 386 boot sector or program shows a message and halts (Ctrl+Alt+Del) instead of hanging silently | |
| 1 | 3 | **IDE auto-detection** during POST, every boot: a drive set to "Not installed" in CMOS that answers IDENTIFY is written to CMOS as type 47 with its physical geometry; drives the user entered are never changed. Unplugged drives dropped. The setup tool and on/off switch come in stage 3. | |
| 2 | 4 | Full-screen POST display with boot countdown | |
| 3 | 5 | BUBios-style setup: tabs, Summary page, no three-item menu, **boot order** option; the AMI ROM Diagnostics are removed to make room | |

Out of scope: LBA / INT 13h extensions (DOS 6.22 doesn't use them), and a 128 KB ROM.

Stage 1 fits in the existing free space (about 1.5 KB). The 28 KB of AMI ROM Diagnostics stay untouched until stage 3.

## The ROMs

| ROM | What | MD5 (CPU image) | Status |
|---|---|---|---|
| `binary/FOXII_ECHS.BIN` | Step 1: ECHS | `6d0e13fb7f294c4396b2e4a847b6caa0` | emulator tests pass, **not yet on the board** |
| `base/FOXII_0613_ORIGINAL.BIN` | the original BIOS | `c74e174c716add49b1b686c70d8df83c` | |

Burn the doubled chip files, not the CPU image: `binary/FOXII_ECHS_EVEN.BIN` (MD5 `daae1cab8740cda8f3b2999f89bd76d4`) into the **EVEN** socket and `binary/FOXII_ECHS_ODD.BIN` (`686788f345fcf522185e51ded68b43f4`) into the **ODD** socket, on 27C512 / 27SF512 chips.

## Testing Step 1 on the board

In this order; each test depends on the one before. Keep the original chips at hand.

1. **An existing installation.** The 1 GB card with DOS 6.22 (SanDisk SDCFJ-1024, physical 1986/16/63). The ECHS ROM shows it to DOS as 992/32/63. What matters is the head count the partition was created with: read the MBR (DEBUG, INT 13h AH=02h of 0/0/1 to 0000:0200, then `d 3be l 10`) and look at the 6th byte of the first entry, the end head. `1F` = 32 heads: keep CMOS at 1986/16/63, and the card must boot as before. `0F` = 16 heads (partitioned under the original BIOS): enter 1024/16/63 instead, which the ECHS ROM does not translate. Never let a repair tool write to a card while the geometry is in doubt.
2. **Floppy boot with a disk configured** does not hang (SOYO pitfall 9.1 showed up exactly there).
3. **A translated disk: the 2 GB card.** Enter its **physical** geometry as type 47. The SOYO with BUBios shows it on its POST screen, or use the card's label. A 3875/16/63 card, for example, appears to DOS as 967/64/63. Then `FDISK` (one primary partition, active), `FORMAT C: /S`, boot from C:, copy files, `SCANDISK` with a surface scan.
4. **The far end of a large disk: the 8 GB card**, e.g. 16000/16/63 -> 1002/255/63, 7.68 GiB. DOS 6.22 limits each partition to 2 GB, so make a primary partition plus an extended partition with logical drives up to the end of the disk. Format, fill and surface-scan the **last** logical drive: that proves the high cylinder bytes.
5. Optional: the 4 GB card (128 heads).

What would point at the ROM: "C: drive error" or "C: drive failure" at POST, a hang during the floppy boot, "Invalid drive specification", or FDISK seeing a wrong size. Once a card's type-47 geometry has more than 1024 cylinders, changing it later changes the translation and its partitions become unreadable. The same happens if the 1 GB card is later given its real geometry (above 1024 cylinders): repartition it then.

## Folder

```
README.md                  this file: plan and status
CLAUDE.md                  notes for AI assistants working in this repository
docs/ROM_ANALYSIS.md       verified map of the original ROM (Step 0)
docs/286_BIOS_MODDING_GUIDE.md   the method, written as we go
docs/DEVELOPMENT_LOG.md    every step, every test, every bug
base/                      original chip dumps and the 64 KB CPU image
binary/                    built ROMs (CPU image + doubled EVEN/ODD chip files)
asm/echs.asm               Step 1: ECHS translation, 286 code (+ listing)
py/build.py                assemble + patch + split -> binary/FOXII_ECHS*.BIN
py/ide_harness.py          Unicorn emulator for the ROM's INT 13h code
py/regress.py              Step 1 tests: geometry, addressing, A/B identity, POST sequence, stack
py/boot_test.py            the ROM's INT 19h boot path from the simulated disk
py/romtool.py              join / split / check EVEN+ODD chip images
py/analyze_bios.py         asserts every fact in ROM_ANALYSIS.md
py/coverage_disasm.py      recursive disassembly; proves nothing calls the diagnostics
```

## Base ROM

| File | What | MD5 |
|---|---|---|
| `base/FOXII_0613_ORIGINAL.BIN` | 64 KB CPU image (F000:0000 = offset 0) | `c74e174c716add49b1b686c70d8df83c` |
| `base/ORIG_EVEN.BIN` | EVEN chip (low bytes), 64 KB doubled | `1bcd22853e656c19ee65670aad8fe1b7` |
| `base/ORIG_ODD.BIN` | ODD chip (high bytes), 64 KB doubled | `42824741ba95e0f09630d493d4e2371e` |

## Tools

Python 3. `py/analyze_bios.py` and `py/romtool.py` need nothing else. The builds need [NASM](https://www.nasm.us) (assembled with `CPU 286`, so a 386 instruction is an assembler error), and the emulator tests need Unicorn and Capstone (`pip install unicorn capstone`).

```sh
python3 py/build.py                        # -> binary/FOXII_ECHS.BIN + _EVEN/_ODD chip files
python3 py/regress.py                      # Step 1 tests (about 2 s)
python3 py/boot_test.py                    # INT 19h boot path
python3 py/analyze_bios.py                 # check the original ROM map
python3 py/romtool.py split binary/X.BIN binary/X   # -> X_EVEN.BIN / X_ODD.BIN to burn
```

**Burning:** EVEN file into the EVEN socket, ODD file into the ODD socket. Keep the original chips. This BIOS has no recovery block.

## License

The patch sources, scripts and documentation are released under the MIT License (see `LICENSE`).

The ROM images in `base/` and `binary/` contain AMI BIOS code, which remains the copyright of American Megatrends Inc. They are provided for the preservation and repair of this board only.
