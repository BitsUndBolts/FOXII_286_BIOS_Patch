# Development Log

Every step: what was done, how it was tested, and what went wrong. Newest at the bottom.

---

## Step 0: map the original ROM (2026-11-18)

**Goal:** know the ROM well enough to estimate what is possible, and set up the tools.

**Done:**

- Built the 64 KB CPU image from the board's chip dumps (`Original\ORIG_EVEN.BIN` / `ORIG_ODD.BIN`, upper 32 KB of each, EVEN first). `romtool.py join` -> `split` reproduces both chip files byte for byte.
- Checked the EVEN/ODD naming of all 20 ROM pairs in the Documents folder: in every pair the EVEN file holds the low bytes. Corrected the note in `UMB_session_prompt.md`, which said the opposite.
- Mapped the ROM (`docs/ROM_ANALYSIS.md`), with every fact asserted by `py/analyze_bios.py`.
- Compared the INT 13h code with the SOYO's original ROM: same AMI code base, same frame, same five ECHS sites.
- Disassembled HT12MM.SYS (Quadtel EMS 4.00) for the EMS register layout.

**Findings that shape the plan:**

1. **Room.** About 1.5 KB of free space, plus 28 KB of AMI ROM Diagnostics that nothing else in the BIOS calls. Stage 1 fits in the free space; the diagnostics can make room for stages 2 and 3.
2. **ECHS is a port, not new work.** The five patch sites match the SOYO's. The SOYO code uses 386 instructions (`PUSHAD`, `MOVZX`, 32-bit `IMUL`/`DIV`) and must be rewritten for the 286.
3. **The 386 boot-sector hang is explained.** INT 06h goes to AMI's handler for `LOADALL` and `LOCK`, which passes anything else to an IRET-only handler, so the bad opcode is executed again forever.
4. **The only checksum covers the diagnostics module** (XOR, 0000-6FFF). The main BIOS has none. **Wrong:** POST checkpoint 02 checksums 8000-FFFF; found on the first board test of Step 1 (see there).
5. **The POST stack and the type-47 table share 0300h-03FFh** when "Scratch RAM option" is 1: 160 bytes of stack budget.
6. **UMBs:** the HT12 has four EMS window registers (64 KB frame), and shadow blocks are never read-write. 64 KB is the hardware limit.

**Method notes for the guide:**

- A plain linear disassembly is useless on this ROM: early POST runs without RAM and "returns" through `MOV SP,table` + `JMP`. A recursive disassembler that follows `MOV SP,imm` and the word tables (`A1C0`, `80D4`, `84D0`, `775E`, `ADD0`, `CB5C`) reached about 9,600 instructions, enough to prove that nothing calls into the diagnostics module.
- Scanning for `E8`/`E9` targets below 7000h gave 32 hits; every one turned out to be data or a misaligned decode. Only the recursive pass (`py/coverage_disasm.py`) separates them. It still reports one, `8341`: the word at `833E` (a `MOV SP` return table) decoded as code. Checked by hand: not a call.

---

## Step 1: ECHS translation, disks up to 8.4 GB (2026-11-18)

**Goal:** lift the 504 MB limit to the INT 13h CHS ceiling (1024 x 255 x 63 = 8.42 GB) the way the SOYO's ECHS patch v5 did, without changing anything else.

**ROM:** `binary/FOXII_ECHS.BIN` (MD5 `6d0e13fb7f294c4396b2e4a847b6caa0`), chips `binary/FOXII_ECHS_EVEN.BIN` (`daae1cab8740cda8f3b2999f89bd76d4`) and `binary/FOXII_ECHS_ODD.BIN` (`686788f345fcf522185e51ded68b43f4`). **Status: passes all emulator tests, not yet tested on the board.**

**What changed (447 bytes):**

| Site | Original | Now |
|---|---|---|
| `A357-A383` | AH=08h reporting body | `CALL xlate_getparams`, `JMP A384`, NOPs (tail `A384` untouched) |
| `A65A` | `AND DH,0Fh` | `CALL xlate_headcyl` |
| `A30C-A31C` | cylinder-high builder (format) | `MOV AL,[BP+6]`, NOPs |
| `A4DF-A4EE` | cylinder-high builder (seek) | `MOV AL,[BP+6]`, NOPs |
| `A832-A841` | cylinder-high builder (read/write/verify) | `MOV AL,[BP+6]`, NOPs |
| `F537-F69D` | free | `asm/echs.asm`, 359 bytes (419 bytes of the block left) |

No checksum to fix: the main BIOS has none. The build checks that the diagnostics module's XOR still holds. **(Wrong: see "First board test" below.)**

**The 286 port of the SOYO code (`asm/echs.asm`):**

- `calc_factor` and `xlate_getparams` were already pure 16-bit code; only `CPU 286` changed.
- `xlate_headcyl` computed the LBA with `MOVZX`/`IMUL`/`DIV` on EAX/ECX/EDX and saved them with `PUSHAD`. Now:
  - `LBA = (logC x transH + logH) x S + logS - 1` with two `MUL r16` (the result is below 2^24, so the high word times S fits in 16 bits).
  - `div32`: a 32-by-16 division in two steps (high word first, its remainder carried into the low word), because a 286 `DIV` only produces a 16-bit quotient. Used twice: LBA / sectors, then / heads.
  - Saves only AX, BX, CX, DX and SI instead of `PUSHA`: 6 bytes less on the POST stack.
- Same contracts as the SOYO's v5: only AH=02h, 03h, 04h, 05h, 0Ah, 0Bh, 0Ch are translated; everything else gets the original arithmetic; the caller's DH in the frame is only read; never 256 heads.

**Tests (all pass):**

- `py/regress.py` (1.4 s):
  1. AH=08h geometry pinned for 10 drives from 256 MB to 8.4 GB (the 2, 8 and 8.4 GB values are the SOYO's hardware-confirmed ones).
  2. 44 reads per drive reach exactly the LBA the logical CHS implies, never past the end, and leave CX/DX intact.
  3. A/B identity: for drives up to 1024 cylinders, 159 calls covering every function AH=00h-19h give identical registers, flags, BDA status and IDE commands on both ROMs.
  4. The POST disk sequence (14h, 09h, 11h, 08h, then 04h on the last sector) succeeds at every geometry.
  5. Stack: 74 bytes deepest per INT 13h call (original 60), below the 96 bytes the SOYO's ECHS ROM uses on hardware with the same table layout.
- `py/boot_test.py`: the ROM's own INT 19h path, no diskette, MBR at LBA 0: reaches 0000:7C00 on the original and on the ECHS ROM at five geometries. Boot-path stack 78 bytes (original 60) of the 160-byte budget.
- **The tests catch real mistakes.** Three deliberately broken ROMs all fail: the shared 1F5h site left original (8 failures), `AND DH,0Fh` left original (22), the AH=08h tail overwritten, which was SOYO pitfall 9.1 (12).

**Bugs, all in the test harness, none in the ROM:**

1. **One Python callback per emulated instruction made the tests unusable** (over 10 minutes for the first run). The SOYO harness tracked the stack low-water mark that way. Now the code hook covers only the three string-transfer sites, and the stack depth is measured by painting 0030:0000-00FF with A5h before each call and finding the lowest changed byte: 1.4 s for everything.
2. **Every multi-sector call timed out, in both ROMs.** The read and write loops wait for IRQ 14 before every sector, and the harness raised it once per command. Both ROMs then returned the same timeout with different leftover CX values, which looked like a difference. The simulated drive now raises the IRQ again after every sector.
3. **Every write ran into the instruction limit.** The write loop continues while the drive shows DRQ, and the simulated drive showed DRQ forever. It now counts down the sectors of the current command and drops DRQ after the last one.

Long read/write (AH=0Ah/0Bh) still time out in the harness, because it does not supply the 4 ECC bytes; they time out identically in both ROMs, and no DOS uses them.

**Board test plan:** see README, "Testing Step 1 on the board".

### First board test: POST stops at 02 (2026-11-19)

The first ECHS ROM (MD5 `6d0e13fb...`) stopped with POST codes **02** (current) / **01** (previous).

**Cause:** a second ROM checksum that Step 0 missed. POST checkpoint 02 (`8143`) adds up the 4000h words of F000:8000-FFFF and requires 0; on failure it beeps code 9 and stops. The ECHS changes in A3xx-A8xx and F5xx moved the sum to 2BF4h. Step 0 had found the diagnostics module's XOR check through its `AA55` header and wrongly concluded it was the only checksum. The emulator tests could not see it: they start at the INT 13h entry and never run POST.

**Fix:**
- The build balances the sum with the word at **F83E** (last word of the free block) and asserts both checksums.
- `py/rom_checks.py` runs the BIOS's **own** check routines from the image in the emulator: checkpoint 02, the diagnostics XOR, and two AMI tamper checks (`76BC`, `FA4F`). The build deletes its output if any of them fails, and `regress.py` runs them as section 0. Run on the ROM that failed on the board, it reports exactly that failure: checkpoint 02.
- `analyze_bios.py` and `ROM_ANALYSIS.md` (new section 2b) now cover all four checks. A search for every loop that reads CS: (`2E AC` / `2E AD`) found nothing else: the remaining hits are a string printer and an error-message table.

New ROM: `binary/FOXII_ECHS.BIN` MD5 `16c21a46d4effa9a62beca3349633fc7`, chips `_EVEN` `7a30d68611e1514da46828cb3d792dbf`, `_ODD` `1b163bb1704f834ada271f769e6c923e`. The code is unchanged; only the word at F83E differs.

### Second board test: the checksum-fixed ROM (2026-11-19)

ROM `16c21a46...` on the board (checked in memory: `CALL` at A357 and A65A, code at F537, checksum word D40C at F83E). Booted MS-DOS 5 from A:, tested through DOSAI.

**Card:** SanDisk SDCFJ-1024, physical 1986/16/63 (WhatIDE), CMOS type 47 = 1986/16/63. It is the DOS 6.22 card of the P2B, partitioned there with **32 heads**: MBR partition 1 end head 31, BPB 32 heads / 63 sectors (read on Windows before the test).

| Test | Result |
|---|---|
| POST | passes (the first ROM stopped at 02) |
| Boot from A: with the hard disk configured | no hang (SOYO pitfall 9.1) |
| INT 13h AH=08h | CX=DFFF DX=1F01 AL=3Fh: **992/32/63**, 1 drive, CF=0, as the emulator predicted |
| MBR (0/0/1) | read, signature 55AA, partition 1 active, type 06 |
| Partition end: logical 992/16/16 = LBA 2,000,895 | read, CF=0 (the P2B made the partition with 993 cylinders; DOS addresses its last 0.5 MB as cylinder 992, one past the reported maximum, and ECHS translates it like any other) |
| Last physical sector: logical 992/31/63 = LBA 2,001,887 | read, CF=0 |
| One past the end: logical 993/0/1 | **AH=04h, CF=1** (sector not found): the translation ends exactly at the card's last sector |
| `CHKDSK C:` (DOS 5, read only) | 976 MB FAT16, 688 files in 54 directories, consistent; 4 lost clusters (64 KB), the usual leftovers of an interrupted write, not a geometry fault |
| Write test | 11 files (614 KB) copied to C:, compared byte for byte with a QBASIC program: all identical |

**Still to test:** booting MS-DOS 6.22 from C:, a full surface scan (`SCANDISK /SURFACE`), the 2 GB and 8 GB cards.

The card's CONFIG.SYS / AUTOEXEC.BAT (EMM386, an AWE64 init, a PS/2 mouse driver, DOSAI on COM1) were for the P2B; they are kept as `CONFIG.P2B` / `AUTOEXEC.P2B`, and the card now has a minimal 286 setup (HIMEM, DOS=HIGH, DOSAI on LPT1 from `C:\PIGEON`).

### Third board test: MS-DOS 6.22 boots from C: (2026-11-19)

With minimal 286 startup files on the card (HIMEM, DOS=HIGH, DOSAI from `C:\PIGEON`), MS-DOS 6.22 boots from the 1 GB card through the ECHS translation: DOS high, 622 KB free, DOSAI back by itself. **Step 1 works on the board.** Still to test: the 2 GB and 8 GB cards (translation with 64 and 255 heads, the far end of a large disk).

---

## Step 2: a readable invalid-opcode error (2026-11-19)

**Goal:** a boot sector or program with 386 code shows a message and halts, instead of freezing the board with no feedback.

**Cause of the freeze (from Step 0):** INT 06h -> AMI's handler `EB31` (LOADALL / LOCK) -> `EB2E JMP EA85`, the generic unexpected-interrupt handler, which finds no IRQ in service and IRETs to the same opcode. Reproduced in the emulator: 200 INT 06h in a row on the same instruction, nothing on the screen.

**Change:** `EB2E` `JMP EA85` -> `JMP int6_halt` (`asm/int6.asm`, at `F69E`). AMI's LOADALL and LOCK handling in front of it stays. The handler:

1. masks every IRQ except the keyboard, sends 8 non-specific EOIs to both PICs (the fault may have happened inside an interrupt handler) and points INT 09h back at the BIOS keyboard handler (from the ROM's IVT template), so Ctrl+Alt+Del works whatever the program had done;
2. switches to text mode 3 (7 on monochrome, from the BIOS equipment word) if a graphics mode is active, otherwise prints below what is on the screen;
3. prints `Invalid opcode at CS:IP`, `(boot sector)` when the address is in 0000:7C00-7DFF, the six bytes there, "The 80286 cannot run this code. It needs a 386 or newer CPU." and "System halted. Press Ctrl+Alt+Del to restart.";
4. halts with only the keyboard interrupt enabled.

No way back to the program or to DOS: the user decided against an "Esc to return to DOS" (the fault can be inside DOS, a driver or an interrupt handler).

**ROM:** `binary/FOXII_STEP2.BIN` MD5 `7b4a6577251b60668f24a6b80eb29af8`; chips `_EVEN` `1fc04e39a559d26077f597791497f5bf`, `_ODD` `d02f56715ff84b076395f6004758a494`. It differs from the Step 1 ROM only at `EB2F-EB30`, `F69E-F81D` and the checksum word. **Status: emulator tests pass, not yet on the board.**

**Build:** `asm/step1.asm` and `asm/step2.asm` say what each ROM contains; `build.py 1` still produces the board-confirmed Step 1 ROM byte for byte.

**Tests:**
- `py/int6_test.py`:
  1. The ROM's own INT 19h path boots a disk whose boot sector starts with an invalid opcode. Original ROM: endless INT 06h loop at 0000:7C00. Step 2 ROM: the message with `0000:7C00 (boot sector)` and `Bytes: 0F 0B ...`, one INT 06h, halted inside the handler, PIC masks FDh/FFh, EOIs sent, INT 09h = F000:E987.
  2. Graphics mode 13h: switched to mode 3 before the message; with a monochrome equipment word, to mode 7.
  3. AMI's LOCK case (handler entered with `F0 90` at the fault address): stepped over on both ROMs alike.
- `regress.py`, `boot_test.py`, `rom_checks.py` pass on the Step 2 ROM too (they now test the newest ROM; `FOXII_ROM=` picks another).

**Emulator note:** Unicorn emulates a 386 or later, so it runs 386 instructions without a fault, and for an opcode invalid on every CPU it does not raise INT 06h either: it stops with `UC_ERR_INSN_INVALID`, IP on the faulting instruction. `int6_test.py` plays the 286: it pushes FLAGS, CS and IP and continues at the INT 06h vector. The test uses `0F 0B` (UD2), which no CPU knows. A real LOCK prefix never faults on a 286; AMI's LOCK skip is code shared with its 386 BIOSes.

**Space:** Step 2 leaves 31 bytes in the free block F537-F83D. Step 3 (auto-detect) needs the other free blocks (about 750 bytes in pieces: 7F0E, E32C, F474, 7EB9, DFBA, E7E8), or moving the message text out of this block.

**Board test:** see README, "Testing Step 2 on the board". Two test programs are on the C: card: `C:\TEMP\T386.COM` (`66 31 C0 CD 20`) and `C:\TEMP\T386G.COM` (mode 13h, then the same).

### Board test (2026-11-19)

ROM `7b4a6577...` burned. Booting an **MS-DOS 7.1 boot floppy** (a 386-only boot sector) showed:

```
Invalid opcode at 0000:7DF6 (boot sector)
Bytes: 66 6A 00 E9 3B FF
The 80286 cannot run this code. It needs a 386 or newer CPU.
System halted. Press Ctrl+Alt+Del to restart.
```

`66 6A 00` is `PUSH DWORD 0`, the first 386 instruction in that boot sector. **Step 2 works on the board.** Not yet tried: `C:\TEMP\T386.COM` / `T386G.COM` (a program at the DOS prompt, and the switch out of graphics mode) and Ctrl+Alt+Del from the halt.

---

## Step 3: IDE auto-detection during POST (2026-11-19)

**Goal (as agreed):**
- At every boot, before the BIOS sets up the disks, a drive set to "Not installed" in CMOS that answers IDENTIFY is written to CMOS as type 47 with its physical geometry, and the CMOS checksum is fixed.
- Drives the user entered are never changed.
- A configured drive that doesn't answer at all is dropped, so POST doesn't wait and stop with an error.
- No setup changes: the setup tool and an on/off switch come in stage 3 with BUBios.

**Research first (ROM_ANALYSIS.md section 10):**

- **CMOS:** the same layout as the SOYO's 1992 BIOS:
  - 12h holds the type nibbles; 0Fh means the type is in 19h / 1Ah;
  - the type-47 parameters are in 1Bh-23h / 24h-2Ch;
  - the checksum is the byte sum of 10h-2Dh, stored in 2Eh/2Fh.
- **Where POST sets up the disks:** checkpoint 75h (`943E`) skips the disk setup if CMOS is invalid, reads CMOS 12h at `9447`, and runs `A857` (checkpoint 76h) only if 12h is non-zero. `A857` reads 12h again at `A894`. Both reads are `MOV AL,92h / CALL EE9F`, 5 bytes: ideal hook sites.
- **The waits being removed:** `A857` retries INT 13h 09h/11h for 2D8h ticks (40 s) per drive.

**Design decision: drop for this boot only.** The SOYO drops a missing drive by writing "Not installed" to CMOS. Here that would break "never change my drives":
1. Boot once with a card that has a hand-entered 1024/16/63 unplugged: CMOS now says Not installed.
2. On the next boot the card answers and is auto-detected with its physical geometry: a different ECHS translation, unreadable partitions.

So the second hook gives `A857` a 12h value without the missing drive, and CMOS keeps the user's entry. The user agreed.

**Change (`asm/autodet.asm`, 402 bytes in two blocks):**

| Site | Original | Now |
|---|---|---|
| `9447` | `MOV AL,92h / CALL EE9F` | `CALL autodet`, NOP, NOP |
| `A894` | `MOV AL,92h / CALL EE9F` | `CALL drives12`, NOP, NOP |
| `7F0E-7FD2` (second build: `7F0F-7FD3`) | free (7000-7FFF: no checksum) | `autodet`, `drives12`, `select`, `ide_wait`, `cmos_sum`, `cmos_wr_next` (197 bytes, 45 left) |
| `E32C-E3F8` (second build: `E32D-E3F9`) | free | `identify`, `set47` (205 bytes, 5 left before E3FE) |

- `autodet`: for each drive whose nibble in 12h is 0, `identify`; on success `set47`: nibble 0Fh, 19h/1Ah = 47, the 9 parameter bytes, the checksum. The values written:
  - geometry from IDENTIFY words 1/3/6 (the same geometry as the SOYO and WhatIDE use);
  - precomp FFFFh, control byte 08h above 8 heads, landing zone = cylinders;
  - only 1-16383 cylinders, 1-16 heads and 1-63 sectors are accepted.
- `drives12` (also the tail of `autodet`): 12h with the nibble of every configured drive cleared if nothing answers on the bus. "Nothing answers" means status FFh (floating), 7Fh (floating, DD7 pulled down) or 00h (the master answering for a missing slave). A busy drive is left to AMI.
- `identify` by polling, timed with the BIOS tick counter. It waits up to 10 s for BSY to clear (a drive spinning up), selects the drive again (a drive ignores a select while busy, so a slave probe would otherwise reach the master), then allows 2 s for DRDY and 2 s for the IDENTIFY data. All 256 words are read, then the status, which clears the drive's interrupt request (IRQ 14 is still masked here).
- Both hooks keep every register except AL, like the `CALL EE9F` they replace; `A857` needs AH = 0 after `A894`. With an invalid CMOS, checkpoint 75h skips the disk setup and both hooks with it, so the checksum is never fixed over a cleared CMOS.

**ROM:** `binary/FOXII_STEP3.BIN` MD5 `451fbb2be9846265815ee8343a263b4b`; chips `_EVEN` `72b8d85d33f7513096054a561a04d2c8`, `_ODD` `640c4d51fe65cb79e0cd12443ef038a6`. It differs from the Step 2 ROM at `9447-944B`, `A894-A898`, `7F0E-7FD2`, `E32C-E3F8` and the checksum word. (This is the first build; see "First board test" below for the second.)

**Build:** `asm/step3.asm` is the first sectioned build. Each section sits at its ROM offset (`.text` at F537, `auto1` at 7F0E, `auto2` at E32C), and `build.py` places them from NASM's map file. It asserts that the F537 block is byte for byte the Step 2 code, and that each new block was empty and fits. `build.py 1` and `build.py 2` still give the board-confirmed MD5s.

**Tests, `py/autodet_test.py` (35 s):** a small POST emulator runs the ROM from checkpoint 75h to the end of 76h. That covers both hooks and all of `A857` with its INT 13h calls, against:
- a CMOS;
- a two-device IDE bus: busy times, ATAPI devices, how a missing slave and an empty bus read, and selects ignored while busy;
- simulated time: 1 µs per I/O access and 7.5 µs per port 61h read, with 40:6Ch counting 55 ms ticks.

The Step 2 ROM runs every case as the reference. All pass:

1. C: Not installed, the SanDisk 1986/16/63 answers. CMOS 12h=F0, 19h=47, 1Bh-23h = `C2 07 10 FF FF 08 C2 07 3F`, checksum valid. One IDENTIFY. `A857` sets the drive up in the same boot (INT 41h -> 002D:003D = 1986/16/63), and INT 13h AH=08h reports 992/32/63 through ECHS. Simulated time under 1 ms.
2. Both Not installed with a 2 GB slave (3875/16/63): 12h=FF, both blocks, 2 drives, D: reports 967/64/63.
3. Drives the user set up: a hand-entered 1024/16/63 on a 1986/16/63 card, a table type, both drives by hand. CMOS, BDA, drive tables, POST flags and IDE commands are identical to Step 2, and no IDENTIFY is sent to a configured drive.
4. Dropped for this boot:
   - C: configured, empty bus (FFh or 7Fh): Step 3 takes no time; Step 2 waits 8-9 s and sets flag 0004h (controller failure).
   - D: configured but unplugged: Step 3 sets up C: only; Step 2 waits **40 s** and sets flag 0040h.
   - CMOS is unchanged in every case, and the next boot with D: plugged in has both drives back.
5. Not detected:
   - an ATAPI slave;
   - a missing slave whose master echoes its own status (costs 2 s waiting for the IDENTIFY answer);
   - an empty bus (no command at all);
   - IDENTIFY values out of range (0 or above 16383 cylinders, 0 or 17 heads, 0 or 64 sectors). 16383/16/63 is accepted.
6. Spinning up:
   - busy 6 s: detected; busy 15 s: not detected (the 10 s limit), CMOS untouched;
   - a busy user-set C: plus a Not installed D: with no slave: the slave probe waits and does not take the master for D:;
   - a configured C: busy 8 s: kept, and AMI waits for it as before.
7. Invalid CMOS: nothing written, no command, same as Step 2.
8. Stack: hook 1 alone 36 bytes; checkpoints 75h-76h 82 bytes on both ROMs (AMI's INT 13h calls are the deepest part). Budget 160. Both hooks keep every register except AL, with AH = 00h and A5h going in.

**The test catches real mistakes:** five deliberately broken ROMs all fail.

| Mutation | Failures |
|---|---|
| no checksum | 3 |
| `A894` left original | 1 (the 40 s D: wait is back) |
| configured drives probed too | 6 |
| no second select in `identify` | 2 (the busy master is written as D:) |
| 00h counted as a drive | 5 |

`regress.py`, `boot_test.py`, `int6_test.py`, `rom_checks.py` and `analyze_bios.py` pass on the Step 3 ROM. `ide_harness.py`, `rom_checks.py` and `int6_test.py` now default to the newest ROM; `int6_test.py` had stayed on the Step 2 file.

**On the board, read through DOSAI (Step 2 ROM running):** with the SanDisk card as master, selecting the slave reads status 00h, the ATA answer for a missing slave. So a Not installed D: costs nothing at boot on this board; the 2 s case in test 5 does not apply to this card.

**Mistakes on the way, none in the ROM:**

1. `wait` as a label: NASM takes it as the `WAIT` (FWAIT) mnemonic. Renamed `ide_wait`.
2. Part 2 first came to 237 bytes, more than the 210 free at E32C. The checksum and the CMOS write helper moved to part 1.
3. During the research I misread `E2C0` (BFh) as having bit 6 set, which would put the type-47 tables at the top of base memory. The first test run put them at 002D:003D: bit 6 is clear, and CMOS 38h bit 4 decides. ROM_ANALYSIS section 4 was right about the place; it was wrong in calling `E260` a type-47 template (it is AMI's GDT). Corrected, and both facts are now asserted.
4. In the test: expected AH=08h values off by one; a chained comparison that always failed; a stack check that compared with a Step 2 run that had set up no drives. Each fixed after reading the failing values.

**What the emulator cannot show:** whether an IRQ 14 edge latched while the line is masked surprises AMI's first INT 13h call. The status read at the end of `identify` clears the drive's request. The SOYO polled the same way in front of the same AMI disk code on hardware. The board test settles it: the C: card detected and booting in the same POST.

**Board test:** see README, "Testing Step 3 on the board".

### First board test (2026-11-19)

ROM `451fbb2b...` (the first build) burned.

| Test | Result |
|---|---|
| C: set to "Not installed" in setup | detected; the System Configuration box shows type 47; POST passes and DOS boots |
| CF card removed, C: still type 47 in CMOS | POST continues, no wait, no "HDD controller failure"; the box still shows type 47 (CMOS keeps the user's entry, as designed) |
| `T386.COM` (Step 2) | message shown, system halted |
| **Warm boot (Ctrl+Alt+Del)** | **garbage** on the line after `286-BIOS (C)1989 American Megatrends Inc`: `Φ9£rk╕` (on a cold boot the memory count overwrites that line) |

**Cause: a string terminator taken for free space.** The copyright line at E300 (`286-BIOS (C)1989 American Megatrends Inc`, CR LF CR LF) has no 00h of its own: the first byte of the zero run at E32C ends it. POST prints it at `F042` (checkpoint 22h) up to that byte. Step 3 put `identify` at E32C, so the printer ran on into the code: `E8 39 9C 72 6B B8` is the first instruction (`CALL`) and the next bytes, and `B8` ... is where a 00h in the code stopped it. Step 0 listed the zero runs as free space without checking what ends in front of them. Four runs follow text: 7EB9 ("PARITY ERROR ????"), 7F0E (the ID string "HT-11 286 BIOS"; also used by Step 3), DFBA ("Dec") and E32C.

**Fix (second build):** both Step 3 blocks start one byte later, at 7F0F and E32D. The code is unchanged; the hook targets moved with it.
- `build.py` refuses to overwrite the four terminator bytes.
- `analyze_bios.py` asserts them.
- `rom_checks.py` now also runs the BIOS's own printer at `F042` on the image and compares the text with the original ROM's. On the first build it reports exactly what the board showed (`\r\n\r\n` followed by `E8 39 9C 72 6B B8`); on the second build it passes. All other tests pass unchanged.

**ROM:** `binary/FOXII_STEP3.BIN` MD5 `1c05d1c2b53a2c5d7c72adc698e04770`; chips `_EVEN` `231810220033982169dc8fb92d64a7cf`, `_ODD` `b2c6a76b5261b385ffea925f3244078d`. **Status: to burn.** Still to test: a warm boot (clean copyright line), and README Step 3 test 4 (a configured D: with no slave).

### Second board test (2026-11-19)

| Test | Result |
|---|---|
| D: set up as type 2 with no slave | POST goes through without the wait and without an error; the System Configuration box still shows D: type 2 (CMOS keeps the user's entry, as designed) |

**Step 3 works on the board.** The second build (`1c05d1c2...`) differs only in where the code sits; it is carried by the Step 4 ROM, whose board test includes the warm-boot check.

---

## Step 4: a 386 boot floppy in A: no longer stops the PC (2026-11-19)

**Goal (the user's request after testing Step 2):** a boot floppy with 386 code in A: (MS-DOS 7.1, Windows 9x) halted the PC with Step 2's message. The user wants the message, but then the boot should go on with C:, without waiting. The POST screen moves to Step 5 and the setup to Step 6.

**Research (ROM_ANALYSIS section 6, asserted in `analyze_bios.py` section 11):**
- **One entry:** INT 19h -> `E6F2` -> `JMP 8F80`, and the end of POST calls INT 19h (`F530`).
- **Separate A: and C: paths:** `8FDF` is reached only after A:'s sector was read; C: goes through `8FB1`/`8FFA`. Both end in the same `JMP 0000:7C00`.
- **The C: attempt** at `8FB1` needs ES = 0, BX = 7C00h and DH = 0 (`9005` reads with head DH), and SI = the message AMI's INT 18h path prints if C: fails too.
- **"DOS not loaded":** POST fills INT 00h-77h with F000:EA85 (`90B9`), and DOS replaces INT 21h.
- **Spare memory:** 40:F0 (the BDA's intra-application area) is not used by the BIOS.

**Design:**
- **Marker:** a word at 0000:04F0 says which drive INT 19h is starting. It is cleared at `8F80`, set to "A:" at `8FDF`, and set to "A-" (skipped) when A: is skipped, so A: is skipped at most once per INT 19h.
- **The fault:** the `JMP` at `EB2E` (Step 2: `JMP int6_halt`) now goes to `int6_boot`. Only if the marker is "A:" and INT 21h is still F000:EA85 does it take the new path; everything else goes to Step 2's `int6_halt`, whose code is unchanged.
- **The new path:**
  - prints Step 2's message with Step 2's own helpers and strings: the first line of `msg_tail` by count (63 bytes; the build checks the CR at its end), then `Drive A: skipped. Booting from C: ...`;
  - sends an EOI to both PICs;
  - puts INT 1Eh back to F000:EFC7 (DOS boot sectors point it at their own copy of the diskette parameters);
  - resets the stack to 0030:0100 and turns interrupts on;
  - sets DX = 0, BX = 7C00h, SI = "INVALID BOOT DISKETTE";
  - `JMP 8FB1`: AMI's C: attempt, with its CMOS 0Eh bit 3 test.
- **If C: fails too:** AMI's own path follows (message, "Insert BOOT diskette in A:", a key, INT 19h from the start).
- **No pause**, as the user wants.

| Site | Original | Now |
|---|---|---|
| `8F80` | `XOR AX,AX / MOV ES,AX` | `CALL int19_entry`, NOP |
| `8FDF` | `MOV DI,BX / MOV AX,ES:[DI]` | `CALL int19_a`, NOP, NOP |
| `EB2E` | `JMP int6_halt` (Step 2) | `JMP int6_boot` |
| `F474-F4EF` | free | hooks, `int6_boot`, the message (124 bytes) |
| `7EBA-7EFF` | free (7EB9 ends "PARITY ERROR ????") | `skip_mode`, `skip_go` (70 bytes) |
| `DFBB-DFF6` | free (DFBA ends "Dec") | `skip_where` (60 bytes) |
| `7FD4-7FFE` | free (after Step 3) | `msg_skip` (43 bytes) |

297 bytes in four pieces: the largest free block left had 134 bytes. The message text was shortened to fit 7FD4-7FFF.

**ROM:** `binary/FOXII_STEP4.BIN` MD5 `1e95b81057dc59e07d49f3f0d3993ecf`; chips `_EVEN` `5c31714b2db90007750c23530960e402`, `_ODD` `397fd67df97f56b363ab57014556c0e9`. **Status: emulator tests pass, not yet on the board.** The build checks that the F537 block is the Step 2 code and that Step 3's blocks are the Step 3 build; `build.py 1` and `2` give the confirmed MD5s, and `build.py 3` gives the second Step 3 build.

**Tests, `py/bootskip_test.py`** (the ROM's INT 19h from `8F80`; a diskette in A: whose boot sector does what a DOS one does first, then UD2; the IDE disk as C:):
1. **The 386 floppy in A:, C: bootable:**
   - the message ends with `Drive A: skipped. Booting from C: ...`, without "System halted";
   - C:'s boot sector runs with DL = 80h after one INT 06h, with A: and C: read once each;
   - INT 1Eh is F000:EFC7 again, interrupts are on, the stack is 0030:0100, the marker is "A-".
2. **Still halts:**
   - A: and C: both with 386 code: A: is skipped once and C: halts with Step 2's message;
   - no diskette, a stale "A:" marker in RAM and a 386 C: boot sector: halts (`8F80` clears the marker);
   - INT 21h already changed (DOS loaded): halts.
3. **C: not bootable:** after the message, AMI's "INVALID BOOT DISKETTE" and "Insert BOOT diskette in A:", then the next round.
4. **Graphics mode 13h at the fault:** mode 3 (colour) or 7 (monochrome) before the message, then C: boots.
5. **A/B against Step 3:** a good boot floppy, a C: boot without a diskette, and a C: without a boot sector are identical (text, stop address, DL, sector, INT 1Eh, reads, boot-path stack 14 / 82 bytes).

**The tests catch real mistakes:** five broken ROMs fail.

| Mutation | Failures |
|---|---|
| marker not cleared at `8F80` | 1 |
| no "skipped" marker | 2 |
| INT 1Eh not restored | 1 |
| `EB2E` back to Step 2's handler | 9 |
| INT 21h test removed (both halves) | 1 |

Removing only the INT 21h offset test passed. The segment test alone catches "DOS loaded", so the mutation had to remove both halves.

All earlier tests pass on the Step 4 ROM. `int6_test.py`'s 286 trap and video stub moved to `py/int6_harness.py`, shared with the new test.

**Bug in the harness, not the ROM: Unicorn's code cache.** The first run of test 1 looked like a ROM bug:
- C: never seemed to boot, and INT 1Eh and SS were back at the floppy's values;
- a second "invalid opcode" appeared at 0000:7C14, where memory held zeros.

Unicorn translates code in blocks and keeps them. When the harness wrote C:'s sector to 0:7C00 with `mem_write`, the translated floppy boot sector was still cached for that address and ran again, faulting on its cached UD2. A real CPU runs what is in memory. The harness now drops the cache for every range a disk read writes (`ctl_remove_cache`, in `ide_harness.py` and the diskette model). Also wrong in the first run: the test looked for read command 20h, but AMI reads with 21h.

**Board test:** see README, "Testing Step 4 on the board".

### Board test (2026-11-19)

ROM `1e95b810...` burned. Checked in memory through DOSAI:
- the hooks at `9447`, `A894`, `8F80`, `8FDF` and `EB2E` and the checksum word `7378` match the build;
- the 00h at E32C (the copyright line's end) is in place.

| Test | Result |
|---|---|
| Boot with the MS-DOS 7.1 floppy in A: | `Invalid opcode at 0000:7DF6 (boot sector)`, `Bytes: 66 6A 00 E9 3B FF`, the 386 line, `Drive A: skipped. Booting from C: ...`, then `Starting MS-DOS...` from C: with no pause; DOS 6.22 and DOSAI came up. The marker at 0:04F0 read `A-` afterwards |
| `DIR A:` under DOS | works |
| CMOS after Step 3's auto-detection (read through DOSAI) | 12h = F0, 19h = 2Fh (47), 1Bh-23h = `C2 07 10 FF FF 08 C2 07 3F` (1986/16/63), D: Not installed, 0Eh = 00, checksum 2Eh/2Fh = 05D5h = the byte sum of 10h-2Dh |

**Step 4 works on the board**, and with it the second Step 3 build. `build.py 3` and `build.py 4` now check the MD5s of these ROMs like Steps 1 and 2.

---

## Round 5a: remove the AMI ROM Diagnostics (2026-11-19, branch `stage2-5a-no-diagnostics`)

Stage 2 starts here (`docs/PLAN_STAGES_2_3.md`). Worked on unattended overnight: no board, no DOSAI, everything proven in the emulators.

### Decisions for Alex to review

1. **The module's checksum stays.** `C983` (AA55 header + XOR of 0000-6FFF) keeps running at `929B` and `97BC` as before; the build balances the XOR with the word at **6FFE**. POST is unchanged, and the new code that rounds 5b-6b put into 0000-6FFF is protected by the same check (a bad burn of the low 28 KB still shows "ROM-BIOS CHECKSUM ERROR" instead of crashing). The alternative, patching both calls out, gains nothing.
2. **"RUN DIAGNOSTICS" is hidden with AMI's own switch**, the byte at `E058` (FFh -> 00h). The menu code at `BCFC` then uses its two-item list (`CA43` instead of `CA33`). No code change in the menu.
3. **F000:0003** (the diagnostics entry) becomes a `RET`, in case anything ever calls it; **F000:0008** keeps its `JMP 7000` (the System Configuration box), which round 5b redirects to the POST screen.
4. **Everything else in 000B-6FFD is cleared to 00h**: 28,659 bytes free for rounds 5b-6b. The header `AA 55 40` and both entries (0000-000A) stay where `C983` and `97C1` expect them.
5. The new ROM is `binary/FOXII_STEP5A.BIN` (`py/build.py 5a`); the later rounds follow as `STEP5B` and `STEP6A`.

### Plan

| Where | Original | 5a |
|---|---|---|
| `0000-0002` | `AA 55 40` | unchanged |
| `0003-0005` | `JMP 00A0` (diagnostics) | `RET`, NOP, NOP |
| `0008-000A` | `JMP 7000` (configuration box) | unchanged |
| `0006-0007`, `000B-6FFD` | the diagnostics program | 00h (`0006-0007` is data of the old module, cleared too) |
| `6FFE-6FFF` | module code | XOR balance word |
| `E058` | FFh | 00h (menu without RUN DIAGNOSTICS; 8000-FFFF word sum rebalanced at F83E as always) |

Before clearing: `ROM_ANALYSIS.md` section 2a records where AMI's surface scan (media analysis, read/verify), performance and seek tests are, as a reference for round 6b.

**Proof that nothing uses the module** (three ways, as on the SOYO):
1. Recursive disassembly (`py/coverage_disasm.py`) of the new ROM: no near reference into 0000-6FFF.
2. Every POST run of the tests watches the module range: no instruction may execute in 0003-6FFF, and the only reads allowed come from `C983` (the checksum).
3. A/B against the Step 4 ROM in the new full POST emulator.

**The full POST emulator** (`py/post_emu.py`, from the SOYO's `BUBios/py/post_emu.py`): it runs the ROM from F000:FFF0 to INT 19h with PICs, PIT, KBC (with the CPU reset for leaving protected mode), DMA, CMOS, the HT12 register file, FDC, two IDE drives, ports and a VGA or MDA. For this board it plays an 80C286 without a 287: AMI's CPU test (`71F3`: `PUSH AX/POPF/PUSHF`) gets FLAGS bits 12-15 as 0, and the 287 probe (`9656`: `FNINIT/FNSTSW AX`) reads FFFFh. With that, the System Configuration box reads `80286`, `None`, 640 KB, 3072 KB, type 47, 3F8,2F8, 378, as on the board. A cold POST takes 10 s of virtual time and 8 s real.

**Tests (`py/nodiag_test.py`):**
- A/B with the Step 4 ROM, cold and warm boot (40:72 = 1234h), colour and monochrome, with and without a disk: the same POST checkpoint sequence, the same screen (characters and attributes), the same CMOS, BDA and interrupt vectors at INT 19h.
- Setup via DEL: the menu shows RUN CMOS SETUP and EXIT FOR BOOT, not RUN DIAGNOSTICS; both items work (setup page shown, ESC back; EXIT FOR BOOT continues to INT 19h).
- The ROM's own checks (`rom_checks.py`), the coverage disassembly, and the execution/read watch.
- Mutations that must fail: the XOR word left out (POST stops with "ROM-BIOS CHECKSUM ERROR"), `E058` left FFh (the menu shows RUN DIAGNOSTICS), the `JMP 7000` cleared (no configuration box), the header cleared.
