# FOX II 286 BIOS Patch

**An upgraded AMI 286 BIOS (06/13/90) for the Octek FOX II (Headland HT12/A): disks up to 8.4 GB, IDE auto-detection, a boot-order option and a readable error instead of a silent hang, and later a POST screen and a new setup in the style of BUBios.**

This is the 286 sibling of the SOYO SY-019L1 project ([BitsUndBolts/SOYO_SY-019L1_504_Patch](https://github.com/BitsUndBolts/SOYO_SY-019L1_504_Patch), locally `P:\git\SOYO_SY-019L1_504_Patch`), which did the same for a 1992 AMI 386 BIOS. That project's guides and emulators are the starting point; this folder records what is different on a 286 and every step taken, so it can become a guide of its own.

**Status: Step 0 (analysis) done. Nothing is burned yet.**

## Plan

The work goes in small steps. Each one is tested in the emulator, then burned and tested on the board before the next starts.

| Stage | Step | What | Status |
|---|---|---|---|
| 0 | 0 | Map the original ROM, tools, this folder | **done** |
| 1 | 1 | **ECHS** translation: disks up to 8.4 GB through INT 13h CHS | next |
| 1 | 2 | **Readable INT 06h error**: a 386 boot sector or program shows a message instead of hanging | |
| 1 | 3 | **Boot order**: A:, C: or C:, A: | |
| 1 | 4 | **IDE auto-detection** at boot (IDENTIFY -> type 47), unplugged drives dropped | |
| 2 | 5 | Full-screen POST display with boot countdown | |
| 3 | 6 | BUBios-style setup: tabs, Summary page, no three-item menu | |

Out of scope: LBA / INT 13h extensions (DOS 6.22 doesn't use them), and a 128 KB ROM.

Stage 1 fits in the existing free space (about 1.5 KB). The 28 KB of AMI ROM Diagnostics stay untouched until stage 3 needs the room.

## Folder

```
README.md                  this file: plan and status
CLAUDE.md                  notes for AI assistants working in this repository
docs/ROM_ANALYSIS.md       verified map of the original ROM (Step 0)
docs/286_BIOS_MODDING_GUIDE.md   the method, written as we go
docs/DEVELOPMENT_LOG.md    every step, every test, every bug
base/                      original chip dumps and the 64 KB CPU image
binary/                    built ROMs (CPU image + doubled EVEN/ODD chip files)
py/romtool.py              join / split / check EVEN+ODD chip images
py/analyze_bios.py         asserts every fact in ROM_ANALYSIS.md
asm/                       NASM sources of the patches
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
python3 py/analyze_bios.py                 # check the original ROM map
python3 py/romtool.py check base/FOXII_0613_ORIGINAL.BIN
python3 py/romtool.py split binary/X.BIN binary/X   # -> X_EVEN.BIN / X_ODD.BIN to burn
```

**Burning:** EVEN file into the EVEN socket, ODD file into the ODD socket. Keep the original chips. This BIOS has no recovery block.

## License

The patch sources, scripts and documentation are released under the MIT License (see `LICENSE`).

The ROM images in `base/` and `binary/` contain AMI BIOS code, which remains the copyright of American Megatrends Inc. They are provided for the preservation and repair of this board only.
