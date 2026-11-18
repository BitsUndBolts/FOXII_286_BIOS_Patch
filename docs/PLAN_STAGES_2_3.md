# Plan: stages 2 and 3 (BUBios for the 286)

**What this is:** the agreed plan for the work after Step 4. It was written on 2026-11-19, after Steps 1-4 were confirmed on the board. It replaces the separate "Step 5 = POST screen, Step 6 = setup" plan: both are UI work, both need the diagnostics module's space, and they share display code. So they are done together, in rounds.

## Rounds and branches

| Round | Branch | What | Base |
|---|---|---|---|
| 5a | `stage2-5a-no-diagnostics` | Remove the AMI ROM Diagnostics (0000-6FFF, 28 KB): handle `C983`'s AA55/XOR check (POST `929B`, end of POST `97BC`), the entry points F000:0003 (setup menu "RUN DIAGNOSTICS", `BD46`, enabled by the byte at `E058`) and F000:0008 (the System Configuration box at 7000, called at `97C1`). Prove nothing else calls into the module. No visible change except the menu item | `main` |
| 5b | `stage2-5b-post-screen` | The POST screen in the style of BUBios, replacing the System Configuration box (7000-755F) | 5a |
| 6a | `stage3-6a-setup` | The setup program in the style of BUBios, with boot order and the auto-detect switch | 5b |
| 6b | `stage3-6b-tools` | Our own tools instead of AMI's (see below). **Ask Alex first** | 6a |

- **`main`** holds only board-confirmed ROMs. A round's branch is merged into `main` only after Alex has burned and confirmed its ROM.
- **Branches build on each other.** If a board test of an earlier round needs a fix, make the fix on that round's branch and rebase the later branches on it.
- **Everything is tested in the emulators** (POST from reset, the setup driven by keys, the boot path) before Alex burns anything.

## The tools (round 6b): candidates, to decide with Alex

**Before writing any tool code, ask Alex:** which tools, in what order, what to add or drop, and the open questions listed with each tool. Present this list with sizes once rounds 5a-6a show how much space is left.

AMI's diagnostics are mostly MFM-era: low-level format, interleave, a bad-track editor, and floppy, keyboard and video tests. None of that fits IDE drives or CF cards. Their surface scan, seek and performance tests can still guide the code. The original ROM stays in `base/`, so that code remains available as reference after round 5a removes it. In round 5a, record in `ROM_ANALYSIS.md` where those routines are.

All tools are read-only unless noted. Nothing writes to a disk except, if Alex wants it, the CMOS backup.

### 1. Disk info
- **Shows:** the full IDENTIFY data of each drive:
  - model, serial, firmware;
  - default CHS (words 1/3/6) and current CHS (54-58);
  - LBA capacity (60-61), LBA support (49), PIO modes (51, 64), max multiple (47);
  - CompactFlash (word 0 = 848Ah, or word 83 bit 2).
- **Also:** the geometry DOS sees through ECHS, the CMOS type-47 entry, and whether the two match.
- **Why:** this is the information you need before partitioning a card, and the POST screen only has room for the model and geometry.
- **Size:** about 1 KB. Reuses Step 3's `identify`.

### 2. Partition check
- **Shows:** the MBR's four entries:
  - active flag, type (named: FAT12, FAT16, BIGDOS, extended, FAT32, other), start and end CHS, start LBA and size;
  - the extended partition chain;
  - each FAT partition's boot sector BPB (heads, sectors per track, hidden sectors).
- **Checks:** works out the head count and sectors per track each partition was made with (end head + 1 of a partition ending on a cylinder boundary, end sector) and compares them with the geometry the BIOS reports now (ECHS). On a mismatch it shows a clear warning, for example: "Partition made with 16 heads; this BIOS shows 32 heads: DOS would read the wrong sectors. Enter 1024/16/63 as the type-47 geometry, or repartition."
- **Why:** this is the trap from Step 1 board test 1 (a card partitioned elsewhere with another head count). The BIOS can catch it before DOS or FDISK writes anything.
- **Size:** about 1-1.5 KB.
- **Ask Alex:** should the POST screen also warn when C:'s partition table doesn't match (one short line, no waiting)?

### 3. Surface scan
- **Does:** verifies every sector of a drive without transferring data: IDE READ VERIFY SECTORS (40h), up to 256 sectors per command, by CHS through the translation.
- **Shows:** a progress bar, the elapsed time and an estimate, and a list of bad sectors (LBA and logical CHS). Esc stops it. Never writes.
- **Size:** about 600 bytes. AMI's media analysis is the guidance.
- **Ask Alex:** should there also be a "read" scan that transfers the data (slower, also tests the data path)?

### 4. Memory test
- **Tests:** base memory (except what the test itself uses) and extended memory, through INT 15h AH=87h block moves. A 286 needs protected mode for memory above 1 MB, and returning from it means a reset; AMI's INT 15h already does that.
- **Patterns:** 00/FF/55/AA, walking ones, address in address (finds address-line faults).
- **Modes:** quick (one pass, two patterns) and thorough (all patterns, repeat until Esc).
- **Reports:** the failing address and bits, and, from the HT12's bank registers, which memory bank that is.
- **Size:** about 1.5 KB.
- **Ask Alex:** also test the HT12's EMS pages (through the window registers 20h-23h)?

### 5. HT12 chipset view
- **Shows:** what the chipset is actually set to, decoded into text (ROM_ANALYSIS section 8 has the meanings):
  - reg 10h: banks and relocation;
  - 12h/13h: shadow blocks;
  - 14h, 18h: EMS/extended boundary;
  - 19h: EMS enable and frame base;
  - 20h-23h: EMS page registers.
- **Read-only.**
- **Why:** useful for the HT12UMB / EMS work, and for checking that setup options really reach the chipset.
- **Size:** about 600 bytes.

### 6. CMOS backup and restore
- **Why:** old boards lose their CMOS when the battery dies, and a hand-entered type-47 geometry is exactly what must not get lost.
- **Restore:** shows the differences against the current CMOS before writing, checks a signature and a checksum, then writes CMOS and fixes the CMOS checksum.
- **Ask Alex where to keep the copy:**
  1. **A dedicated floppy, raw sector.** Small and simple, but overwrites that disk.
  2. **A file on a FAT12 floppy.** The friendliest option, but writing FAT is a lot of code in a BIOS.
  3. **The unused sectors after the MBR on C:** (LBA 1-62 on DOS-partitioned disks). No extra disk needed, but boot managers sometimes use that gap. It would need a check that the gap is empty, plus a signature.
- **Size:** about 700 bytes (options 1 or 3).

### 7. Disk speed
- **Measures:**
  - the read throughput in MB/s: READ SECTORS with `REP INSW`, timed by the PIT, at the start, middle and end of the disk;
  - the average seek time: random single-sector verifies.
- **Size:** about 500 bytes. AMI's performance and seek tests are the guidance.

### More ideas to raise with Alex
- **A one-time boot choice** without waiting: a key held or pressed during POST (for example F11) gives a one-line "Boot from: A / C" choice. No delay when no key is pressed. (This could go into round 6a instead.)
- **A floppy drive info line** on the POST screen (what INT 13h reports for A:/B:).

### Deliberately left out
- Keyboard, serial and parallel port tests: they cost space and aren't needed on this board.
- Low-level format, interleave, bad-track editor: meaningless on IDE and CF.
- Anything that writes to a disk (except possibly the CMOS backup, option 1 or 3).
