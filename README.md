# FOX II 286 BIOS Patch

**An upgraded AMI 286 BIOS (06/13/90) for the Octek FOX II (Headland HT12/A): disks up to 8.4 GB, IDE auto-detection, a boot-order option and a readable error instead of a silent hang, and later a POST screen and a new setup in the style of BUBios.**

This is the 286 sibling of the SOYO SY-019L1 project ([BitsUndBolts/SOYO_SY-019L1_504_Patch](https://github.com/BitsUndBolts/SOYO_SY-019L1_504_Patch), locally `P:\git\SOYO_SY-019L1_504_Patch`), which did the same for a 1992 AMI 386 BIOS. That project's guides and emulators are the starting point; this folder records what is different on a 286 and every step taken, so it can become a guide of its own.

**Status: Step 1 (ECHS) works on the board (1 GB card: existing DOS 6.22 install, reads, writes, boot from C:; the 2 GB and 8 GB cards are still to test). Step 2 (INT 06h message) works on the board (MS-DOS 7.1 boot floppy). Step 3 (IDE auto-detection) passes the emulator tests and is ready for the board.**

## Plan

The work goes in small steps. Each one is tested in the emulator, then burned and tested on the board before the next starts.

| Stage | Step | What | Status |
|---|---|---|---|
| 0 | 0 | Map the original ROM, tools, this folder | done |
| 1 | 1 | **ECHS** translation: disks up to 8.4 GB through INT 13h CHS | **works on the board** (1 GB card); 2 GB / 8 GB cards to test |
| 1 | 2 | **Readable INT 06h error**: a 386 boot sector or program shows a message and halts (Ctrl+Alt+Del) instead of hanging silently | **works on the board** (MS-DOS 7.1 boot sector) |
| 1 | 3 | **IDE auto-detection** during POST, every boot: a drive set to "Not installed" in CMOS that answers IDENTIFY is written to CMOS as type 47 with its physical geometry; drives the user entered are never changed. Unplugged drives dropped. The setup tool and on/off switch come in stage 3. | emulator tests pass; **to test on the board** |
| 2 | 4 | Full-screen POST display with boot countdown | |
| 3 | 5 | BUBios-style setup: tabs, Summary page, no three-item menu, **boot order** option; the AMI ROM Diagnostics are removed to make room | |

Out of scope: LBA / INT 13h extensions (DOS 6.22 doesn't use them), and a 128 KB ROM.

Stage 1 fits in the existing free space (about 1.5 KB; Steps 1-3 use 1,146 bytes of it). The 28 KB of AMI ROM Diagnostics stay untouched until stage 3.

## The ROMs

| ROM | What | MD5 (CPU image) | Status |
|---|---|---|---|
| `binary/FOXII_STEP3.BIN` | Step 3: Step 2 + IDE auto-detection | `451fbb2be9846265815ee8343a263b4b` | emulator tests pass, to test on the board |
| `binary/FOXII_STEP2.BIN` | Step 2: Step 1 + INT 06h message | `7b4a6577251b60668f24a6b80eb29af8` | **works on the board** (`python3 py/build.py 2` rebuilds it byte for byte) |
| `binary/FOXII_ECHS.BIN` | Step 1: ECHS | `16c21a46d4effa9a62beca3349633fc7` | **works on the board** (`python3 py/build.py 1` rebuilds it byte for byte) |
| `base/FOXII_0613_ORIGINAL.BIN` | the original BIOS | `c74e174c716add49b1b686c70d8df83c` | |

Burn the doubled chip files, not the CPU image, on 27C512 / 27SF512 chips: `<name>_EVEN.BIN` into the **EVEN** socket, `<name>_ODD.BIN` into the **ODD** socket.

| Chip file | MD5 |
|---|---|
| `binary/FOXII_STEP3_EVEN.BIN` | `72b8d85d33f7513096054a561a04d2c8` |
| `binary/FOXII_STEP3_ODD.BIN` | `640c4d51fe65cb79e0cd12443ef038a6` |
| `binary/FOXII_STEP2_EVEN.BIN` | `1fc04e39a559d26077f597791497f5bf` |
| `binary/FOXII_STEP2_ODD.BIN` | `d02f56715ff84b076395f6004758a494` |
| `binary/FOXII_ECHS_EVEN.BIN` | `7a30d68611e1514da46828cb3d792dbf` |
| `binary/FOXII_ECHS_ODD.BIN` | `1b163bb1704f834ada271f769e6c923e` |

## Testing Step 3 on the board

What Step 3 does at every boot:
- **Not installed and answering:** a drive set to "Not installed" that answers IDENTIFY is written to CMOS as type 47 with its physical geometry, and the CMOS checksum is fixed. This happens before the BIOS sets up the disks, so it boots in the same POST.
- **Your entries:** drives you entered are never touched.
- **Configured but silent:** a drive for which nothing answers on the bus is left out **for this boot only**. CMOS keeps your entry. POST then does not wait (40 s for a missing D: in the emulator) and stops with no error.

Nothing changes on screen, and setup is unchanged.

**Keep the 1 GB card's geometry in mind.** It was partitioned with 32 heads under ECHS from its physical 1986/16/63, which is exactly what auto-detection writes, so setting it to "Not installed" is safe. Never do that with a card partitioned under another geometry (for example one entered as 1024/16/63): auto-detection would give it its physical geometry and its partitions would no longer be readable.

In this order:

1. **Nothing changed for your entries.** Burn `FOXII_STEP3_EVEN/ODD.BIN`. CMOS still says C: type 47 = 1986/16/63, D: Not installed: POST and boot from C: as before, with no extra delay.
2. **Auto-detect C:.** In setup set C: to "Not installed", save. The PC restarts, and POST must detect the card and boot DOS 6.22 from C: in the same boot. Then check that:
   - setup shows C: as type 47, 1986/16/63;
   - through DOSAI, CMOS 12h = F0h, 19h = 2Fh, 1Bh-23h = `C2 07 10 FF FF 08 C2 07 3F`, and no "CMOS checksum error".
3. **Unplugged C:** (power off, unplug the card or the cable). POST must go through without the long wait and without "HDD controller failure", and then boot from A: or report no boot disk. Setup must still show C: as type 47, 1986/16/63. Power off, plug the card back in: boots from C:.
4. **Unplugged D:.** With the card as C:, set D: to any type 47 (for example 980/16/32) and save. POST must not wait 40 s or show a D: error, and C: boots. Set D: back to "Not installed".
5. Optional, together with the open Step 1 test: the **2 GB card** set to "Not installed" must be detected with its physical geometry (e.g. 3875/16/63, DOS sees 967/64/63); then FDISK, FORMAT, SCANDISK as in Step 1 test 3.

What would point at the ROM: a hang or a long pause at POST, "CMOS checksum error" after a detection, a drive detected with the wrong geometry, a hand-entered type that changed, or C: not booting in the same POST it was detected in.

## Testing Step 2 on the board

Two tiny programs on the C: card (`C:\TEMP`), each a 386 instruction (`66 31 C0`, XOR EAX,EAX) and an exit:

1. `C:\TEMP\T386.COM`: with the Step 1 ROM the PC freezes silently; with the Step 2 ROM it must show `Invalid opcode at xxxx:0100`, the bytes `66 31 C0 CD 20 ..`, the 386 notice, and halt. **Ctrl+Alt+Del** must restart the PC.
2. `C:\TEMP\T386G.COM`: switches to VGA mode 13h first; the message must appear in text mode.
3. Optional: a boot floppy (Gotek image) whose boot sector contains 386 code must show the message with `(boot sector)`.
4. Everything from Step 1 still works: boot from C:, `DIR`, a file copy.

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
asm/step1.asm .. step3.asm what each step's ROM contains (+ listings; step3.map: where its sections went)
asm/echs.asm               Step 1: ECHS translation, 286 code
asm/int6.asm               Step 2: the invalid-opcode message
asm/autodet.asm            Step 3: IDE auto-detection (two blocks: 7F0E, E32C)
py/build.py                assemble + patch + split; build.py 1 / 2 = the confirmed ROMs, no argument = newest
py/ide_harness.py          Unicorn emulator for the ROM's INT 13h code
py/regress.py              Step 1 tests: geometry, addressing, A/B identity, POST sequence, stack
py/boot_test.py            the ROM's INT 19h boot path from the simulated disk
py/int6_test.py            Step 2 tests: 386 boot sector, graphics mode, AMI's LOCK case
py/autodet_test.py         Step 3 tests: POST checkpoints 75h-76h with simulated CMOS, IDE bus and clock
py/rom_checks.py           runs the BIOS's own checksum and tamper-check routines on an image
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
python3 py/build.py                        # newest step -> binary/FOXII_STEP3.BIN + _EVEN/_ODD chip files
python3 py/build.py 1                      # Step 1 ROM, checked against the board-confirmed MD5
python3 py/build.py 2                      # Step 2 ROM, checked against the board-confirmed MD5
python3 py/regress.py                      # ECHS tests on the newest ROM (FOXII_ROM=... for another)
python3 py/int6_test.py                    # Step 2 tests
python3 py/autodet_test.py                 # Step 3 tests (about 35 s)
python3 py/boot_test.py                    # INT 19h boot path
python3 py/rom_checks.py                   # the BIOS's own checksum routines (also run by build.py)
python3 py/analyze_bios.py                 # check the original ROM map
python3 py/romtool.py split binary/X.BIN binary/X   # -> X_EVEN.BIN / X_ODD.BIN to burn
```

**Burning:** EVEN file into the EVEN socket, ODD file into the ODD socket. Keep the original chips. This BIOS has no recovery block.

## License

The patch sources, scripts and documentation are released under the MIT License (see `LICENSE`).

The ROM images in `base/` and `binary/` contain AMI BIOS code, which remains the copyright of American Megatrends Inc. They are provided for the preservation and repair of this board only.
