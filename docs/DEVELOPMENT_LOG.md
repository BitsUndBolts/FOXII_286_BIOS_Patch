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

### Result

**ROM:** `binary/FOXII_STEP5A.BIN` MD5 `50e1a3bec4e2ee652377b7ab632640a3`; chips `_EVEN` `c2828b72e1be1acf65461ece0295f3ce`, `_ODD` `0bdf5ffd23c34c464de6f8c3272146ab` (joined back by `romtool.py join` to the same image). Module XOR word at 6FFE = F3FCh, POST word sum word at F83E = 7477h. **Status: all emulator tests pass, not yet on the board.** `build.py 1` to `4` still give the confirmed MD5s.

**`py/nodiag_test.py`: all pass** (3 minutes; 10 with `--mutants`):

| Case | Compared with Step 4 at INT 19h |
|---|---|
| cold boot, the board | same 78 POST checkpoints, screen (characters and attributes), CMOS, vectors and BDA |
| warm boot (40:72 = 1234h) | same |
| monochrome adapter | same |
| no hard disk | same |
| master + 2 GB slave | same |
| setup: DEL, menu | `EXIT FOR BOOT` / `RUN CMOS SETUP` (Step 4 has the third item); RUN CMOS SETUP shows the same page; ESC -> `Write data into CMOS and exit (Y/N)?`; N + Enter back to the page; Y + Enter saves, a full POST follows, same screen, checkpoints and CMOS as Step 4 |
| setup: EXIT FOR BOOT | INT 19h, same as Step 4 |
| cleared CMOS | AMI's `CMOS battery state low`, `CMOS system options not set`, `RUN SETUP UTILITY`, `Press <F1> to RESUME`, the same screen as Step 4; F1 -> setup menu (two items); EXIT FOR BOOT -> INT 19h with the same screen, checkpoints, CMOS, vectors and BDA. One stack byte at 0:03B2 differs: the menu code's leftover of the `E058` byte |

In every run, no instruction ran in F000:0003-6FFF except the `JMP 7000` at 0008, and only `C991` (in `C983`) read the range. The image checks: header and entries, 0006-6FFD all 00h, both checksums, differences from Step 4 only in 0003-6FFF, E058 and F83E/F; `rom_checks.py`; the coverage disassembly (no near reference into 0000-6FFF, only the known table artifact at 8341).

**Mutations, each caught:**

| Mutation | Failures |
|---|---|
| XOR word left out | 32 (POST stops with `ROM-BIOS CHECKSUM ERROR`) |
| `E058` left FFh | 1 (RUN DIAGNOSTICS in the menu) |
| `JMP 7000` at 0008 cleared | 18 (no configuration box; the CPU runs into zeros) |
| header cleared | 32 |
| two stray bytes in 0006-6FFD | 1 |

All earlier tests pass on the 5a ROM (`regress.py`, `boot_test.py`, `int6_test.py`, `autodet_test.py`, `bootskip_test.py`, `rom_checks.py`, `analyze_bios.py`); they now default to it.

**Screenshots** (`py/shots.py 5a`, in `shots/`): `5a_0_step4_menu` (reference), `5a_1_menu`, `5a_2_setup_page`, `5a_3_end_of_post`, `5a_4_end_of_post_mono`.

**Bugs on the way:**
1. **In the build, found by the tests:** the first build cleared 0006-6FFF in one go and wiped the `JMP 7000` at 0008. The A/B test showed the CPU running into zeros at F000:000A, and the screens differed. Now 0006-0007 and 000B-6FFF are cleared separately and the build asserts the entry.
2. **In the emulator:** AMI calls the video BIOS through the INT 10h vector as well (`PUSHF` / `CALL FAR`, at `75F5`). The emulator served INT 10h only for the `INT` instruction, so those calls reached the stub's `IRET` and printed nothing. With a cleared CMOS, AMI's screen tamper check (`766E`, see ROM_ANALYSIS 2b) then found no copyright line on row 22 and crashed on purpose, into the old diagnostics code, on both ROMs. The emulator now serves INT 10h at the stub's handler too; the cleared-CMOS case runs as on the board.
3. **In the test:** the exec watch first reported the wrong address (Unicorn's IP at hook time); it now uses the hook's address.

**Noticed for 5b:** POST's DEL message still says `Press <DEL> If you want to run SETUP or DIAGS` (string at `7E3B`). Round 5a leaves it, as it changes nothing else visible; round 5b replaces the message with its status line.

### Handover (round 5a)

- **State:** done in the emulator; branch `stage2-5a-no-diagnostics` pushed. Not merged into `main`.
- **Board test:** README, "Testing round 5a on the board".
- **Next:** round 5b on `stage2-5b-post-screen`, built on this branch.
- **If the board test fails:** fix on this branch and rebase 5b and 6a on it (`docs/PLAN_STAGES_2_3.md`).

---

## Round 5b: the POST screen (2026-11-19, branch `stage2-5b-post-screen`, built on 5a)

### Decisions for Alex to review

1. **Name and version.** The screen calls the BIOS **BUBios/286** with version **0.5** (round 5b; 0.6 for 6a, 1.0 once the rounds are confirmed on the board). Title bar: `BUBios/286 0.5 ■ Power-On Self Test` on the left, `Bits und Bolts ■ Headland HT12/A` on the right.
2. **AMI's screen tamper check is switched off**, as on the SOYO (`F3DB` there): the first byte of `766E` becomes `RET`. Reason: with a valid CMOS and "Primary display: installed" (CMOS 37h bit 1, as on any normal setup) the check is **active on every boot**: it reads row 22 for `     (C) American Megatrends Inc.,` and crashes on purpose when it is not there. The POST screen does not keep that line; the AMI copyright texts stay in the ROM untouched, and the other three checks (8000-FFFF sum, module XOR, the two ROM tamper checks) stay.
3. **No countdown, no pause** (as asked). The POST screen stays up when POST hands over to INT 19h. At that moment the status bar moves up to row 17 (in place of the separator line) and rows 18-24 become grey on black with the cursor at row 18, so Step 4's "Drive A: skipped" message and `Starting MS-DOS...` appear below the POST information, and the screen scrolls up as DOS writes more. (First version: the status bar stayed on row 24, and the boot's text landed on it before the screen scrolled; found by the boot test, see below.) Nothing waits.
4. **Colours:** the teal scheme of BUBios (title bar black on cyan, labels cyan, values bright white, bar cyan); monochrome attributes on an MDA. The colour schemes and their CMOS byte come with the setup in 6a; 5b reads no scheme byte.
5. **"Auto"** is shown for a drive that POST auto-detected in this boot (Step 3: CMOS said Not installed, the drive answered). From the next boot on, the drive is type 47 in CMOS like one entered by hand, and the screen says `Type 47`. Round 6a can keep an "auto" mark in CMOS if you want the label to stay.
6. **Disk models** are read with IDENTIFY when the screen is first drawn (checkpoint 22h), without waiting for a drive that is still busy: such a drive shows `...` and is asked again at the end of POST. Both times IRQ 14 is kept away: the drive's interrupt is disabled (3F6h nIEN), the slave PIC's IRQ 14 is masked while the command runs, the status is read at the end, the BDA flag 40:8E is cleared, and the master is selected again (SOYO lesson).
7. **The DEL message** (`Press <DEL> If you want to run SETUP or DIAGS`) is replaced by the status line `Press DEL to run Setup`; the ESC message of the memory test by `Press ESC to skip the memory test`. DEL works exactly as before (AMI's keyboard handler, same window).
8. **What the screen does not show:** the CPU's real clock only if the reading is within 1/16 of a standard clock (6, 8, 10, 12, 16, 20, 25 MHz), else `...`; no cache (the HT12 has none); no LBA (Step 1 has none).

### Plan

**Where AMI prints during POST** (traced in the emulator with a log of every INT 10h call, its checkpoint and its caller):

| Checkpoint | Caller | What | 5b |
|---|---|---|---|
| 19h | video BIOS | mode 3 | kept |
| 22h | `92C1 CALL F042` | `286-BIOS (C)1989 American Megatrends Inc` at row 1 | `CALL bu_init`: the whole screen |
| 24h, 42h, 7Ch | `76D0` | `     (C) American Megatrends Inc.,` row 22, BIOS ID + KBC version row 24 | `JMP bu_idline`: the BIOS ID and KBC version in the status bar |
| 30h, `9534`, `CE64` | `766E` | tamper check of row 22 | `RET` (decision 2) |
| 3Ah-3Ch | `ACCF-AD00` | `nnnnn KB OK` per 64 KB (after each return from protected mode) | `CALL bu_mem`: bar and count |
| 3Ah | `AD05-AD1D` | `Press <ESC> to bypass MEMORY test` at [40:69] | `CALL bu_escmsg`: status line |
| 43h, 7Fh | `AB60` | clears the message row | `JMP bu_clrmsg`: status `Checking devices ...` |
| 73h | `93F6` | `Press <DEL> If you want to run SETUP or DIAGS` | `CALL bu_delmsg`: status `Press DEL to run Setup` |
| 85h | `96E7` | error list (`7AB2`), `RUN SETUP UTILITY`, `Press <F1> to RESUME` (teletype, CR LF before each) | `CALL bu_errors` first: cursor into the message rows, rows painted in the error colour, status `POST found a problem` |
| 85h | `9791-9798` | mode set = clear screen before the box | `CALL bu_refresh`: redraws only if the screen is no longer ours (after setup, or scrolled) |
| 00h | `97C1` -> F000:0008 | System Configuration box (`JMP 7000`) | `JMP bu_final`: late values, status `Booting: A: then C:` and the POST time, cursor to the message rows |

**Mockup** (colour; `■` = FEh):

```
 BUBios/286 0.5 ■ Power-On Self Test              Bits und Bolts ■ Headland HT12/A
 
  Processor    80286                       Coprocessor  None
  Clock        16 MHz                      Shadow RAM   Main + Video
  Chipset      Headland HT12/A             RTC battery  OK
  BIOS         AMI 06/13/90 ■ BUBios/286 0.5

  Memory       ████████████████████████████████████████  3712 KB

  Floppy A:    1.44 MB, 3½"                Floppy B:    None
  Disk C:  CF  SanDisk SDCFJ-1024
               Auto  1986/16/63 → DOS 992/32/63    977 MB
  Disk D:      None

  Ports        COM1 3F8  COM2 2F8  LPT1 378
  Option ROMs  C000 2K
 ────────────────────────────────────────────────────────────────────────────────
  (rows 18-23: AMI's errors in red; then the boot: Step 4's message, Starting MS-DOS...)

 Booting: A: then C:       │ POST 9 s        DH12-1112-061390-K0
```

**Values and where they come from:**
- Processor: AMI's own 286 test (`PUSH F000h / POPF / PUSHF`: bits 12-15 clear on a 286), `80286` or `80386+`.
- Clock: 500 passes of 32 x `DIV BX` + `LOOP` built at 0:7C00 and timed by PIT channel 2 (as the SOYO, with 286 timings: DIV r16 22 clocks, LOOP 10 with the refill: 714 clocks per pass), snapped to a standard clock.
- Coprocessor: AMI's probe at checkpoint 83h (40:10 bit 1), shown at the end; `...` until then.
- Shadow RAM: what the HT12 really has (reg 13h bits 4-7 main BIOS, reg 12h bits 0-1 video BIOS), at the end.
- RTC battery: CMOS 0Dh bit 7.
- Memory: AMI's count of 64 KB blocks; the bar's total is 640 KB + CMOS 17h/18h, grown if AMI counts more.
- Floppies: CMOS 10h. Disks: CMOS 12h/19h/1Ah and the type-47 bytes or the ROM table (`E401`), IDENTIFY words 27-46 (model), 0 / 83 (CF), the ECHS geometry from Step 1's `xlate_getparams` arithmetic (`calc_factor`), the size in MB. `Auto` when CMOS 12h had the nibble 0 at checkpoint 22h and has it set at the end.
- Ports: the BDA (40:00-0F) at the end; at checkpoint 22h probed as AMI does (UART IIR, printer latch) so they show at once.
- Option ROMs: a scan of C000-EFFF for `55 AA` in 2 KB steps with the size byte.
- POST time: RTC seconds from checkpoint 22h to the end (not shown after a setup visit).

**State** between the hooks: BDA 40:F0-FF (POST clears 0:0500-7BFF at checkpoint 7Fh, so nothing below 7C00 survives; 40:F0 is Step 4's marker only from INT 19h on, and `bu_final` clears the area). The clock loop runs at 0:7C00 at checkpoint 22h.

**Space:** the code goes into the old module area (`diag` block, 000B-6FFD); the hooks are same-length `CALL`/`JMP` + NOPs in 7000-FFFF. The F000:0008 entry stays the far entry, now to `bu_final`; the configuration box code (7000-755F) is no longer called and stays as it is for now (6a can reclaim it).

**Tests** (`py/postscreen_test.py`): the screen in the normal case (every value), during the memory test, with errors (cleared CMOS, F1), monochrome, no disk, two disks, an auto-detected disk, a busy disk, warm boot, a setup visit (DEL, save; DEL, no save); the POST checkpoint sequence identical to round 5a; the boot unchanged (A/B with 5a from INT 19h: Step 4's skip message readable below the POST screen); the IDE state at INT 19h (no IRQ 14 pending, 40:8E = 0, master selected); stack within the 160-byte budget; registers kept by every hook. Mutations that must fail.

### Result

**ROM:** `binary/FOXII_STEP5B.BIN` MD5 `1676da04973658527b52e0da40fcaf06`; chips `_EVEN` `c1e01cbb2ff41c99fbc06672548756bc`, `_ODD` `a7c58aadd63e858784bdf70b8ba0e55f`. The POST screen is 3,577 bytes at 000B-0E03 (25,082 bytes of the old module area left). **Status: all emulator tests pass, not yet on the board.** `build.py 1` to `4` still give the confirmed MD5s, `build.py 5a` the 5a ROM; the build asserts that the Step 1-4 blocks are unchanged.

**`py/postscreen_test.py`: 202 checks, all pass** (5 minutes; 13 with `--mutants`). Each case runs the whole POST, most of them on the 5a ROM too:

| Case | What is checked |
|---|---|
| the board, cold boot | every row of the screen (text and colours), the status bar moved up at the end, rows 18-24 blank for the boot, the cursor visible again, none of AMI's POST texts left; the same POST checkpoints (78), CMOS, vectors and BDA as 5a; 40:F0-FF cleared, 40:8E = 0, master selected, nIEN off, no IRQ 14 pending; every hook keeps the registers (11 sites; 96E7 returns SI = 7AB2); stack within budget |
| during the memory test | the bar partly filled, the count in KB, status `Press ESC to skip the memory test`, processor/clock/model already shown, coprocessor and shadow `...` |
| clocks | 8, 12, 16 and 20 MHz read as such; 14 MHz as `about 14 MHz` |
| monochrome, no disk, two disks, auto-detected C:, C: configured but absent, a ROM drive type, a hard disk | the rows for each, A/B with 5a, the hand-over state |
| C: busy 3 s at power-on | `...` early, the model read at the end of POST with one IDENTIFY (checkpoint 00h), A/B with 5a |
| warm boot | `3712 KB` although AMI skips the count; A/B with 5a |
| cleared CMOS | AMI's four messages in rows 18-21, in red; status `POST found a problem`; `RTC battery Low`; F1 -> AMI's setup menu -> EXIT FOR BOOT -> the screen drawn again, no POST time; A/B with 5a |
| DEL | AMI's setup menu appears (DEL still works), EXIT FOR BOOT -> the screen again with the disk model; A/B with 5a; the status in the DEL window |
| the boot | a C: boot sector with 386 code: Step 2's message below the POST information, grey on black, the information intact; a 386 floppy in A:: Step 4's four lines, then C: boots (its text appears below) |

**Mutations, each caught:** the tamper check left on (25 failures: POST crashes on purpose with "Primary display: installed"), AMI's memory count left in (2), 40:F0-FF not cleared (2), the master not selected again after IDENTIFY (4), IDENTIFY without nIEN and without clearing 40:8E (1: 40:8E = FFh at INT 19h), F000:0008 back to the configuration box (18), AMI's DEL message left in (1), `bu_errors` without SI = 7AB2 (1).

All earlier tests pass on the 5b ROM (`regress.py`, `boot_test.py`, `int6_test.py`, `autodet_test.py`, `bootskip_test.py`, `rom_checks.py`, `analyze_bios.py`), and `nodiag_test.py` still passes on 5a after the emulator changes below. They now default to the 5b ROM.

**Screenshots** (`py/shots.py 5b`): `5b_1_memory_test`, `5b_2_end_of_post`, `5b_3_mono`, `5b_4_errors_cleared_cmos`, `5b_5_auto_and_two_disks`, `5b_6_boot_386_floppy_skipped`, `5b_7_disk_still_busy`, `5b_8_warm_boot_hard_disk`.

**Bugs found by the tests, all fixed before this build:**
1. The LPT probe found nothing: AMI's `97FC` calls `CF2D`, which tests BX (0 at AMI's call site `960D`). `early_ports` now clears BX first.
2. The second `...` placeholder printed `None`: `pstr` leaves SI after the string, and the next field's text was the next string in the ROM. SI is reloaded.
3. `Type 3887`: the type number was printed with the attribute byte still in AH.
4. The POST time came out in the wrong colour: `rtc_now` uses BX, which held the attribute.
5. After a warm boot the memory showed `...`: AMI skips the count, so `bu_final` now takes 40:13 + INT 15h AH=88h.
6. The boot's first line landed on the status bar (row 24) before the screen scrolled: the status bar now moves up to row 17 at the end of POST.

**Emulator changes (`post_emu.py`), each needed for a case above:** the KBC input port's display bit as this AMI BIOS reads it (bit 6 = 1 with a mono adapter; before, a mono run stopped at `Display switch not proper`); CMOS 37h = 03h in `make_cmos` (display and keyboard "Installed", as on any real setup; this is what turns AMI's screen tamper check on); a drive busy until a given time (status 80h, selects and commands ignored); 286 cycle times for code at 0:7C00 (`cpu_mhz`); the 286's INT 06h for UD2; a floppy controller that reads a 1.44 MB image (READ ID, READ DATA through DMA channel 2); Unicorn's code cache dropped for every range a disk read writes (the clock loop ran at 0:7C00 before the boot sector is loaded there).

### Handover (round 5b)

- **State:** done in the emulator; branch `stage2-5b-post-screen` (on top of 5a) pushed. Not merged.
- **Board test:** README, "Testing round 5b on the board". What the emulator cannot show: the real clock reading (`about n MHz` means the 714-clocks-per-pass figure needs calibrating: note n and the board's crystal), the Paradise ROM's size, the KBC version letter, and whether the CF card honours nIEN (the IRQ 14 safety also masks the PIC and clears 40:8E, so it does not depend on it).
- **Next:** round 6a on `stage3-6a-setup`, built on this branch.

---

## Round 6a: the setup of BUBios/286 (2026-11-19, branch `stage3-6a-setup`, built on 5b)

### Decisions for Alex to review

1. **AMI's setup code still prepares and saves; BUBios/286 replaces what is in between.** AMI's setup page code first fills its CMOS buffer (it reads CMOS 10h-3Fh and normalises it: memory sizes from POST, floppy bits, display from INT 11h, the EMS maximum from the HT12) and AMI's own save routine (`C0A0`) writes CMOS 10h-3Fh, the checksum, clears 0Eh/0Fh and restarts. BUBios/286 skips AMI's three-item menu and takes over at the point where AMI's page would start its editing loop (`C009`). Every option edits AMI's buffer with exactly AMI's encodings, each traced from AMI's field handlers (table below). So the CMOS a save writes is what AMI's setup would have written for the same choices; the tests compare both. Side effect: AMI's page is drawn for a moment (a few ms on the board) before BUBios/286's screen replaces it (visible on the board; hidden in 0.6.1, see below).
2. **Tabs:** Summary, Standard, Advanced, Chipset, Tools, Exit. Standard has AMI's standard options (date, time, floppies, hard disks with the type-47 parameters, display, keyboard; base/extended memory and the coprocessor as information). Chipset is AMI's HT12 group (BIOS shadow, Scratch RAM, **EMS size**, 0 wait state, memory relocation). Advanced has the new options.
3. **New settings in CMOS 3Eh, with a check byte in 3Fh** (= 3Eh XOR A5h). Nothing in this BIOS uses 3Eh/3Fh (every CMOS access in POST and every buffer offset in setup was listed), both are outside AMI's checksum (10h-2Dh), and AMI's save writes them from the buffer like any other byte. A cleared or random CMOS reads as the defaults.
   - bits 1-0 boot order: 0 = A: then C: (AMI's, default), 1 = C: then A:, 2 = C: only
   - bit 2: Auto-Detect Disks at Boot **Off** (0 = On, the default)
   - bits 6-4: colour scheme 0-5 (teal, amber, green, classic blue, grey, AMI), used by setup and the POST screen
4. **Boot order** (hook at `8F9B`, where INT 19h tries A:): "C: then A:" tries C: first (CMOS 0Eh bit 3, the read, the 55AA signature, as AMI's C: path), and goes on to AMI's A: path if C: does not boot. "C: only" never touches A:; if C: does not boot it says `No boot sector on C: (boot order: C: only)` and `Press any key to try again`, waits for a key and starts INT 19h again (no "Insert BOOT diskette in A:", which would be wrong here). Step 4 (a 386 floppy skipped) works unchanged in "A: then C:" and "C: then A:".
5. **Auto-Detect Disks at Boot** (hook: Step 3's `CALL autodet` at `9447` now goes through `autodet_sw`): On = Step 3 exactly (a "Not installed" drive that answers becomes type 47; entered drives never change). Off = Step 3 does not set up a "Not installed" drive (no IDENTIFY, no CMOS write); the POST screen still asks the drive for its model (its own IDENTIFY, as in 5b) and then says `Not set up (Auto-Detect Disks at Boot is Off)`, so a forgotten switch is visible. Either way a configured drive that does not answer is left out for that boot (Step 3's `drives12`), because that only saves the wait and never changes CMOS.
6. **The clock keeps running in setup.** AMI's page runs its own calendar clock through INT 1Ch; BUBios/286 turns AMI's hooks off (`D0CF`, the routine AMI's save calls), shows the RTC's time, and sets typed date and time through INT 1Ah (AH=05h, AH=03h). AMI's page writes 0Bh = 82h (SET bit) at `BD71`, but its own date write at `BDF6` (INT 1Ah AH=05h) clears the bit again before `C009`; BUBios/286 clears it once more at its start, which costs nothing and does not rely on that order.
7. **Exit without saving** is new: AMI's page could only be left by saving (or a reset). It returns to POST like AMI's old menu item EXIT FOR BOOT; the POST screen is drawn again and the boot follows.
8. **Tools:** "Auto-detect hard disk C: / D: now" asks the drive (Step 3's IDENTIFY, with the IRQ 14 safety of 5b) and puts its physical geometry into the setup as type 47; nothing is written before Save.
9. **EMS maximum:** AMI recomputes the EMS maximum (CMOS 35h) from the shadow and relocation options only when the EMS field is visited; BUBios/286 recomputes it whenever one of them changes, and keeps 36h (EMS size) and 17h/18h (extended memory = maximum - EMS) consistent, as AMI's EMS field does.
10. **Keys:** Tab / Shift-Tab change the page; ↑↓ select; PgUp/PgDn, ←/→ or +/- change a value; digits type numbers, the date and the time (Enter accepts, Backspace deletes, ESC cancels); Enter runs a Tools or Exit entry; F2/F3 change the colour scheme; F10 asks "Save settings and exit (Y/N)?"; ESC goes to the Exit page.
11. Version **0.6** on the POST screen and in setup.
12. **Typed numbers have limits** (found while testing): type-47 cylinders 1-65535, heads 1-16, sectors 1-63, write precompensation and landing zone 0-65535, a disk type 0-47 (not 15). A value outside them, or an impossible date or time (02/29/2025, 13/01, 24:00:00; years 1980-2099 as AMI's page), is not taken and the help line says `Not taken: ...`; PgUp/PgDn stop at the limits. AMI's page has no such limits for heads and sectors; a type-47 drive with 17+ heads or 64+ sectors cannot work with this BIOS's INT 13h anyway.
13. **Disk sizes in MB are rounded** as on AMI's page (615/6/17 is 31 MB there, 30.6 MB exactly); the Summary and Standard pages show the same number as AMI's page did.
14. **Summary page layout:** left column the machine (CPU, clock, 287, chipset, memory, EMS, shadow), right column the drives and the boot settings, the BIOS line at the bottom.

### Plan

**Hooks:**

| Site | Original | 6a |
|---|---|---|
| `BCFC` | `MOV AL,CS:[E058]` (the menu) | `JMP BD61`: AMI's setup page directly |
| `C009` | `MOV BX,CA53 / JMP C011` (the page's editing loop) | `JMP bu_setup` |
| `9447` | `CALL autodet` (Step 3) | `CALL autodet_sw` |
| `8F9B` | `XOR DX,DX / XOR AX,AX / INT 13h / CALL 9005` (try A:) | `CALL boot_seq`, NOPs |

Leaving setup: Save -> `JMP C0A0` (AMI's save, restart). Exit without saving -> RTC SET bit cleared, `JMP BD4D` (AMI's menu exit: cursor, stack frame, `RET` to POST at `978E`).

**AMI's encodings** (the setup buffer is `[BP+10h..3Fh]` = CMOS 10h-3Fh):

| Option | CMOS | AMI's handler |
|---|---|---|
| Floppy A: / B: | 10h high / low nibble: 0 none, 1 360K, 2 1.2M, 3 720K, 4 1.44M; then 14h bits 7-6 = 01 if both drives are set, else 00 | `C361`, `C377` (`C385`) |
| Hard disk C: / D: type | 12h nibble = type (1-14) or 0Fh with 19h/1Ah = type (16-47); 15 is skipped; 0 = Not installed | `C39F`, `C3D7`, `C409` |
| Type 47 parameters | 1Bh/24h: cylinders (word), heads, write precomp (word), control byte (08h if heads > 8, else 00h), landing zone (word), sectors | `C6D1-C73D` |
| Primary display | code 01h VGA/EGA, 11h Color 40x25, 21h Color 80x25, 31h Monochrome, 00h Not Installed: 37h bit 1 = (code != 0), 14h bits 5-4 = code bits 5-4 | `C113` |
| Keyboard | 37h bit 0 (1 = Installed) | `C14C` |
| BIOS shadow option | 38h bits 6-5: 0 Disabled, 1 Video BIOS, 2 Main BIOS, 3 Main & video BIOS | `C210` |
| Scratch RAM option | 38h bit 4 (0 = option 1, 1 = option 2) | `C1D4` |
| EMS size option | 36h in 64 KB units, at most 35h; 17h/18h = (35h - 36h) x 64 KB | `C24E` |
| EMS maximum (35h) | HT12 reg 10h bits 2-0 (banks): < 3: 0; 3: 0 without relocation, else 4 + (main shadow off) + (video shadow off), but 2 with only the video shadow; 4: 18h; 5: 10h; >= 6: 30h | `BF6D`, `C254` |
| 0 Wait State option | 37h bit 5 (1 = Enabled) | `C1F5` |
| Memory relocation | 38h bit 7 (1 = Enabled) | `C202` |

The codes come from AMI's own value records: each value string is followed by its code byte (`C1B3` returns the byte after the string's 00h).

**Mockup** (Standard page, colour):

```
 BUBios/286 0.6 Setup                             Bits und Bolts  ■  Headland HT12/A
  Summary   Standard   Advanced   Chipset   Tools   Exit
 ────────────────────────────────────────────────────────────────────────────────
   Date (mm/dd/yyyy)        11/19/2026
   Time (hh:mm:ss)          04:36:12
   Floppy drive A:          1.44 MB, 3½"
   Floppy drive B:          Not Installed
   Hard disk C: type        47 (user type)
     Cyln  Head  WPcom  LZone  Sect      1986  16  65535  1986  63     977 MB
   Hard disk D: type        Not Installed
   Primary display          VGA or EGA
   Keyboard                 Installed
   Base memory 640 KB    Extended memory 3072 KB    Numeric processor None
 ────────────────────────────────────────────────────────────────────────────────
  (help for the selected option, two lines)
 Tab:Page  ↑↓:Select  PgUp/PgDn:Change  0-9:Type  F2/F3:Colours  F10:Save  ESC:Exit
```

**Tests** (`py/setup_test.py`): the setup is reached with DEL in the POST emulator and driven by keys. Every option is set through BUBios/286 and, for the same choice, through AMI's own page (on the 5b ROM, PgUp/PgDn), then saved; the CMOS after the restart must be identical. Also: every page (screenshots, colour and mono), the Summary values, typed date and time (valid, invalid, Backspace, ESC), type 47 entry, F10/Y and Exit without saving (CMOS untouched, POST goes on, the POST screen is drawn again, the RTC runs), Tools auto-detect, colour schemes on the POST screen, the boot orders in INT 19h (with a floppy and a C: disk in the emulator), Auto-Detect Off, and that POST without a setup visit is unchanged from 5b. Mutations that must fail.

### Result

`binary/FOXII_STEP6A.BIN`, MD5 `fa014dad81c7ad8016bd8e34c38dfa5c` (EVEN `03059fc511bf44e1f26bf581bf194930`, ODD `d5e94ac05ecf96953077994ff3ba38fb`). The code block 000B-6FFD holds 11,008 bytes (POST screen and setup); **17,651 bytes are left** for round 6b. `py/build.py 1`-`4` still give the confirmed MD5s, `5a` and `5b` their own builds; 6a checks that Steps 1-4's blocks are unchanged.

**Tests** (`py/setup_test.py`, 145 checks in about 16 minutes, ALL PASS on the final ROM; `--mutants`: ten broken ROMs, each caught):

| Part | What it proves |
|---|---|
| `ab` | Ten sets of choices, together every value of every AMI option (floppies, disk types, display, keyboard, shadow, scratch RAM, EMS size, 0 wait state, relocation; five sets with an HT12 reporting three banks, where the EMS maximum depends on shadow and relocation, one of them with relocation already on), set through BUBios/286 on the 6a ROM and through AMI's page on the 5b ROM: the CMOS each save writes (read at the restart, F000:FFF0) is identical, byte for byte, 0Ah-3Fh |
| `type47` | typed type-47 parameters for C: and D: (control byte 08h for 9 heads, as AMI), limits and the `Not taken` message, PgUp/PgDn stops, ESC and Backspace while typing, checksum |
| `datetime` | typed date and time set at once through INT 1Ah (CMOS 09/08/07/32h, 04/02/00h), 02/29 in a leap year, six impossible dates and three times refused, half-typed + Enter refused, Backspace, ESC; the RTC runs (SET bit clear) |
| `exit` | DEL goes straight to the Summary; F10/N stays, F10/Y saves and restarts (the new value on the next POST screen); ESC / Shift-Tab; Exit without saving: no restart, CMOS 10h-3Fh untouched, POST goes on to INT 19h with its screen drawn again |
| `tools` | auto-detect C: over a type-2 entry gives type 47 1986/16/63 (saved, checksum right); D: without a drive says so |
| `pages` | every page and label, the Summary's values, the key row fits in 79 columns, a help text for every field |
| `scheme` | F2/F3 and the Advanced field change the scheme at once; saved as 3Eh bits 6-4 with 3Fh = 3Eh XOR A5h, outside AMI's checksum; the next POST screen uses it; a wrong check byte gives the defaults |
| `boot` | A: then C: / C: then A: / C: only with a boot floppy and a C: boot sector (which one boots, whether A: is read, the status line); C: then A: without a hard disk; C: only without a boot sector (message, a key tries again, A: never read); a 386 floppy with C: then A: (C: boots, A: untouched; without a C: boot sector Step 4's message) |
| `autodet` | On (also with no setting in CMOS): Step 3 as before (type 47 written, `Auto` on the screen). Off: no set-up commands to the drive (only the POST screen's IDENTIFY), CMOS 12h stays 0, the screen says `Not set up (Auto-Detect Disks at Boot is Off)`. Entered drives are used as entered with both, and an entered drive that does not answer is left out for that boot with both |
| `post` | POST without a setup visit against 5b: the same checkpoints, CMOS, vectors and BDA, the same screen and colours but the version; POST stack lowest 0030:00BA (budget 0030:0060) |
| `mono` | the setup on an MDA (B000h), attributes 07h/0Fh/70h only, F2/F3 ignored, the selected field inverse |

Also on the 6a ROM: `regress.py`, `boot_test.py`, `int6_test.py`, `autodet_test.py`, `bootskip_test.py` (boot-path stack 82 bytes as Step 3: `boot_seq` replaces a CALL with a CALL), `rom_checks.py`, `analyze_bios.py`: all pass.

**Bugs the tests found:**

- **Digits did nothing.** `s_key` called `s_fld` (which returns its result in AX) before handing the key to the typing code, so the digit was lost. Found by the first typing test.
- **Values out of range were taken silently or not at all**: now limits for heads and sectors, a minimum of 1, and a message (decision 12).
- **A rejected date looked like a taken one**: `date_set` / `time_set` now return CF.
- **The message stayed when moving to another field**: Up/Down and the first digit clear it.
- **The Summary's BIOS line ran into the right column**: layout changed (decision 14).
- **With Auto-Detect Off the POST screen showed the drive's model with an empty row below**: now `Not set up (Auto-Detect Disks at Boot is Off)`.
- Disk size 30 MB where AMI's page says 31 MB: rounded now (decision 13).

**The mutations found one blind spot in the tests and one redundant instruction.** The EMS maximum after a shadow change was always followed by a relocation change, which recomputes it too, so a missing recalculation after a shadow change passed; a set with relocation already on now changes only the shadow. And removing BUBios/286's own clearing of the RTC's SET bit changed nothing: AMI's page has already cleared it (its INT 1Ah AH=05h at `BDF6`, after setting it at `BD71`). That instruction stays as a safeguard; the mutation was replaced by one the date/time test must catch (24:00:00 accepted).

**Test harness lessons:** pressing DEL at fixed times can hit AMI's keyboard test (a monochrome POST is slower and got `Keyboard error`); the harness now runs to the "Press DEL" checkpoint (74h) and presses DEL there, like a user. After "Exit without saving" POST reaches INT 19h within 300 ms, so the stop must be checked right after the key, not after another `run`. A Ctrl+Alt+Del followed by DEL does not reach the setup in the emulator with any ROM, the original included (an emulator limit, not a 6a change).

**Screenshots** (`py/shots.py 6a`): `6a_1_summary` to `6a_6_exit` in colour and `_mono`, `6a_7_typing_the_date`, `6a_8_not_taken`, `6a_9_exit_question`, `6a_10_post_<scheme>` (the POST screen in amber, green, classic blue, grey, AMI), `6a_11_setup_<scheme>`, `6a_12_post_boot_c_then_a`, `6a_13_c_only_no_boot_sector`, `6a_14_post_autodetect_off`, `6a_15_tools_detect_c`, `6a_16_warm_boot`.

### Handover (round 6a)

- **State:** branch `stage3-6a-setup` (built on 5b), ROM `FOXII_STEP6A` ready to burn, all emulator tests pass. Not on the board yet. 5a and 5b are not on the board either: burn them in order (5a, 5b, 6a) or go straight to 6a, which contains both.
- **Board test:** README, "Testing round 6a on the board".
- **Next:** round 6b (the tools) waits for Alex's answers: the questions are in README and below in "Round 6b: questions for Alex". 17,651 bytes are free in 000B-6FFD.

### Board test (2026-11-19)

Alex burned `FOXII_STEP6A` (0.6, with 5a and 5b inside). **The BIOS works well: no major bugs; with `C: then A:` the board boots from C:.** Findings:

1. **Floppy B:** the board shows `None` on the POST screen and `Not Installed` on both setup pages, which is right (no drive B). The emulator's `1.2 MB` came from the emulator's BDA, not from the ROM: nothing to change.
2. **AMI's page flashes** for a split second after DEL, before the Summary page (decision 1 above said it would; on the board it is visible, with artifacts).
3. **No empty row** between the POST screen's status bar and `Starting MS-DOS...`.
4. **Auto-Detect On, C: Not Installed:** during the memory test the POST screen said `Not set up (Auto-Detect Disks at Boot is Off)` although the switch was On. The logic was right (the drive was set up and booted), the text was wrong: the disk rows are drawn at checkpoint 22h, Step 3's auto-detect runs at 75h, and until then CMOS 12h is 0 whatever the switch says. With the switch Off the same text is right (and the model is shown, decision 5).
5. **No feedback for DEL:** nothing on the screen changes until the setup appears (the SOYO's BUBios says `Entering Setup`).

### 0.6.1: the fixes (same branch)

Version **0.6.1** on the POST screen and in setup, so the two builds can be told apart on the board.

1. **AMI's page is never shown.** `BD69` (`CLI / CLD / MOV AX,268Ah`, right after the page's mode set at `BD65`) -> `CALL setup_dark`, NOP, NOP: the display goes off (`v_screen`: VGA sequencer register 1 bit 5; MDA/CGA mode control 3B8h/3D8h bit 3 from 40:65) and `bu_setup` switches it on after `s_redraw` has drawn the Summary page. AMI's page code runs straight from `BD61` to `C009` (no other exit), so the display always comes back. Between DEL and the Summary page the screen is dark for the few ms AMI's code takes.
2. **One empty row before the boot's text.** `bu_final` puts the cursor on row 19 instead of 18 (still row 24 below AMI's error messages). Step 2's and Step 4's messages, the `C: only` message and DOS all start there.
3. **The disk row before auto-detect.** A drive that answers but is not set up shows `Auto-Detect sets it up after the memory test` (switch On, before checkpoint 75h), `Not set up (Auto-Detect Disks at Boot is Off)` (switch Off), or `Not set up` (On, it ran, and the drive is still not set up). `autodet_sw` now draws the disk rows again right after Step 3's auto-detect (`adet_drawn`), so `Auto 1986/16/63 ...` appears at checkpoint 75h, not only at the end of POST.
4. **DEL feedback, and DEL during the memory test.** This AMI has no DEL flag: at checkpoint 7Fh (`9550`) it empties the keyboard buffer and looks for scan code 53h. Before that:
   - during the memory test it reads port 60h itself (`AC2A`, `AC3A`, `AC8E`) and drops every key but ESC, so **a DEL pressed during the memory test was lost** (the emulator shows it with the 5b ROM). Those reads now go through `kbd_poll` (`AC3A` through `bu_memkey`, which keeps the ESC compare). The code runs in protected mode: `del_seen` uses selector 18h (base 400h in AMI's GDT, the BDA) for the note, and `bu_mem` draws the status after the block;
   - from checkpoint 73h the keyboard interrupt fills the buffer: `bu_tick` on INT 1Ch (only if the vector is AMI's F000:FF53) looks for 53h on every tick and calls `del_seen` (no CMOS, no INT 10h, direct video writes);
   - at checkpoint 7Fh (`bu_clrmsg`, before AMI empties the buffer) `del_7f` puts INT 1Ch back and, if DEL was seen, writes 5300h into the buffer, so AMI's own check goes to setup.
   Once DEL is seen, the status bar says `Entering Setup ...` until the setup appears (the later status texts give way to it; AMI's error status does not).

**Emulator (`post_emu.py`):** the display switch (sequencer register 1 via 3C4h/3C5h on the VGA, 3B8h bit 3 on the MDA, on again with a mode set, 40:65 = 29h after a mode set), with `screen_log`: every change with the screen's text at that moment. An MDA no longer answers INT 10h AX=1A00h (it has no VGA BIOS).

**Tests (`py/setup_test.py`):**

| Part | What it proves |
|---|---|
| `dark` (new) | colour and mono: from `BD61` on the display goes off once and on once; off before anything of AMI's page is drawn, on with the Summary page complete and nothing of AMI's page on it; Exit without saving: the POST screen visible at INT 19h |
| `del` (new) | DEL during the memory test, in AMI's window (73h) and while the disks are set up (74h): 120 ms later the status bar says `Entering Setup ...`, and the setup follows; with the 5b ROM the DEL in the memory test is lost (the old behaviour). Without DEL: INT 1Ch watches from 73h and is AMI's F000:FF53 again from 7Fh and at INT 19h. ESC still ends the memory test at the same moment as on 5b |
| `autodet` | also: the second row during the memory test (On: `Auto-Detect sets it up after the memory test`; Off: the Off text) and the `Auto` row right after checkpoint 75h |
| `boot` | also: rows 17-19 are the status bar, an empty row, the boot's first line |

Mutations added: `setup_dark` not switching off, `bu_setup` leaving the display off, no empty row, `kbd_poll` not noticing DEL, INT 1Ch never hooked, no DEL handed to AMI at 7Fh, no redraw after auto-detect: each must fail.

**Test harness fixes:** a wait for a checkpoint now means "has been passed" (`reached`): checkpoints such as 7Fh-81h pass within one emulator step, and a wait for the last one to equal 80h ran on to INT 19h. The "is a setup up" probe (`in_setup`) looks for a title ending in ` Setup`, not for `Setup` at column 16 (the version is longer now).

**Result:** `binary/FOXII_STEP6A.BIN` 0.6.1, MD5 `39f360b612da32e4b4517abea2d15343` (EVEN `ceefb346c0457b7e8f6ae5d2d710ad6f`, ODD `5a1e26cda886db81c73325137479337b`). The code block 000B-6FFD holds 11,572 bytes; **17,087 bytes are left** for round 6b. `py/build.py 1`-`5b` still give their MD5s. `py/setup_test.py`: **176 checks, all pass** (the new parts `dark` and `del`, and the extended `autodet` and `boot`); `--mutants`: **17 broken ROMs, each caught** (the ten of 0.6 and seven new ones). The one check that failed in the first full run was the A/B with 5b in `post`: BDA 40:51, the cursor row, is 19 now (18 on 5b), as intended; the check now expects exactly that. The POST stack's lowest point is unchanged (0030:00BA): `bu_tick` does not run at the deepest point. Also on 0.6.1: `regress.py`, `boot_test.py`, `int6_test.py`, `autodet_test.py`, `bootskip_test.py`, `rom_checks.py`, `analyze_bios.py`; `nodiag_test.py` on 5a and `postscreen_test.py` on 5b with the changed emulator: all pass. Screenshots (`py/shots.py 6a`) redone with 0.6.1, plus `6a_17_del_in_memory_test`, `6a_18_autodetect_pending`, `6a_19_boot_below_post_screen`. (The emulator's POST time reads `0 s`, with the 0.6 ROM too: its RTC does not tick; the board shows the real time.)

### Handover (0.6.1)

- **State:** branch `stage3-6a-setup`, ROM `FOXII_STEP6A` 0.6.1 ready to burn, all emulator tests pass. Not merged into `main`.
- **Board test:** README, "Testing 0.6.1 on the board".
- **Next:** round 6b (the tools) after Alex's answers.

## Open bug after 0.6.1: the memory bar stops at about 70% after EMS is raised (2026-11-19)

**Seen on the board (0.6):** with the EMS size raised (0 -> 1024K) and saved, the next POST's bar stopped at about 70% (2688 KB) and jumped to 100% at the end of POST. Lowering the EMS size does not show it.

**Cause (found in the code, not yet tested in the emulator):** `mem_total` (post.asm) takes the bar's total as 640 KB + the **larger** of CMOS 17h/18h and 30h/31h. Setup writes 17h/18h = EMS maximum - EMS size (2048 KB for 1024K EMS out of 3072 KB), and AMI's count stops there (2688 KB). But 30h/31h still holds what the previous POST counted (3072 KB), so the total is 3712 KB and the bar ends at 2688/3712 = 72%; `bu_final` then fills it. After that boot 30h/31h is 2048 too, so only the first boot after an increase shows it. Lowering EMS makes 17h/18h the larger value, and the bar's "grow if AMI counts more" covers it.

**Fix to make (next session):** the total from 17h/18h alone (what setup configured, which is also what AMI counts up to), 30h/31h only if 17h/18h is 0; keep the growing for added RAM. Emulator test: CMOS 17h/18h = 2048, 30h/31h = 3072, 36h = 16 (1024K EMS): the bar full when the count ends (before `bu_final`); and the reverse (17h/18h 3072, 30h/31h 2048). Check against what the HT12 reports with EMS on (`post_emu.py`'s HT12 register file, reg 18h from `F261`).

## Round 6b: decisions (2026-11-19, Alex)

Alex's answers to the questions below (the old question list is kept after this section for reference). **Space:** 17,087 bytes free in F000:000B-6FFD after 0.6.1.

| # | Tool | Decision | Notes for the design |
|---|---|---|---|
| 1 | **Disk info** | **yes** | Replaces running WHATIDE in DOS. Tools' "Auto-detect hard disk C:/D: now" only takes the geometry and writes type 47; Disk info shows everything IDENTIFY says: model, serial, firmware, default and current CHS, LBA size, PIO modes, multiple-sector count, CF signature (word 0 = 848Ah), capabilities, plus the CMOS entry, the ECHS geometry DOS sees, and whether they match. Proposal: one page per drive, with Enter = "use as type 47" there, so auto-detect and info are one tool |
| 2 | **Partition check** | **yes, with the POST warning line** | MBR entries (type, CHS, LBA, size), the extended chain, each FAT boot sector's BPB; a warning when the partitions were made with another head count than the BIOS now shows. On the POST screen: one line under C:, read once at the end of POST, no waiting |
| 3 | HT12 chipset view | **replaced by: HT12UMB.SYS inside the ROM** | Alex's driver is done ([BitsUndBolts/HT12UMB](https://github.com/BitsUndBolts/HT12UMB)). Put the driver into the ROM with a way to get it out from DOS: see "HT12UMB.SYS in the ROM" below. A read-only register view stays possible later (about 0.6 KB) if Alex wants it |
| 4 | CMOS backup | **dropped** | Alex sees no use for it (Auto-Detect covers the disk entry, the other settings are few) |
| 5 | Surface scan | **dropped** | ScanDisk does it |
| 6 | **Memory test** | **yes, with the HT12's EMS pages** | Base and extended (INT 15h AH=87h), patterns, walking ones, address in address, quick / thorough, the failing address, bits and HT12 bank; then each EMS page through the HT12 page registers (what HT12UMB relies on) |
| 7 | **Disk speed** | **yes** | Through the BIOS's own path (INT 13h, PIO over the ISA bus): for a CF card the bus is the limit, and the number shows what this 286 and its I/O card can do; for an old hard disk the drive is. Read MB/s at the start, middle and end, average seek time |
| - | **One-time boot key** | **yes** | A key during POST overrides the boot order once; CMOS is not changed. Reuse 0.6.1's DEL watch (memory test through `kbd_poll`, then `bu_tick`). Proposal: **A** or **C** (boot that drive this once), not a function key: an 84-key AT keyboard may have only F1-F10, and F5/F8 are DOS's own keys right after POST. Status bar: `Booting: A: (this time)`. AMI empties the buffer at checkpoint 7Fh, so a key from 7Fh to INT 19h has to be looked for in `boot_seq` too |
| - | Floppy info line, "Auto" mark | not needed | |

**Order (proposal):** HT12UMB.SYS in the ROM (small, useful at once), the EMS bar fix, Disk info, Partition check (+ POST line), the one-time boot key, Memory test, Disk speed.

### HT12UMB.SYS in the ROM (proposal for the next session; Alex to confirm)

The driver (1,813 bytes, `HT12UMB 1.0`, MD5 `ce87362d4f0b50ff6a3ba7fbaad9ddb4` for the file Alex attached on 2026-11-19) goes into the ROM so the BIOS and its UMB driver are in one place. DOS can only load a driver from a file, so it has to be written out once; MS-DOS 6.22 has DEBUG for that, and nothing has to be downloaded.

- **A fixed place and size:** a 2 KB slot at **F000:6000-67FF** (inside the free block, covered by the module XOR), the driver followed by zeros. The DEBUG recipe then never changes between BIOS or driver versions (the zeros after the driver do no harm: DOS keeps only what the driver's init says it needs). `build.py` takes the file from a path in the repo (e.g. `extra/HT12UMB.SYS`, with its MD5 checked), asserts it fits, and places it; later code must leave 6000-67FF alone.
- **Getting it out (MS-DOS 6.22):**
  ```
  DEBUG
  -N C:\DOS\HT12UMB.SYS
  -M F000:6000 L800 100
  -R CX
  :0800
  -W
  -Q
  ```
  `M` copies the 2 KB from the ROM to DEBUG's buffer at 100h, `R CX` sets the length, `W` writes the file. Then `DEVICE=C:\DOS\HT12UMB.SYS` after HIMEM.SYS and `DOS=HIGH,UMB` as usual.
- **Where the recipe is shown:** the README, and a page in setup's Tools ("Get HT12UMB.SYS") with the six lines, the driver's version and size, read from the slot, so a user without the README has it on the screen.
- **A tag** before the driver (e.g. `BUBUMB` + version + length at F000:5FF0) lets the setup page and a test find and check it.
- **Also possible, not proposed:** writing the file from setup straight to a floppy (needs a FAT12 writer, several KB, and a formatted disk) or a DOS-side helper program (would have to be downloaded, which is what this avoids).
- **Licence:** the same author; mention the HT12UMB repo and version in the README.

## Handover for the next session

- **Repository:** check out `git@github.com:BitsUndBolts/FOXII_286_BIOS_Patch.git` in the cloud (with push access) and continue on branch **`stage3-6a-setup`** (0.6.1, commit `ed3057d` and this handover on top). On 2026-11-19 attaching the repository to the session was refused by the session's permission check (not by GitHub); the work was then done on a `git bundle` of Alex's local copy (Documents\FOXII_286_BIOS_Patch, through the device bridge) and the commits were brought back the same way, for Alex to push from his PC. If attaching fails again, do the same: `git bundle create` on the PC, stage it, clone it in the cloud, build and test there (the PC shell has no NASM or Unicorn), bundle the new commits back, `git merge --ff-only` on the PC (git there needs the delete permission for its lock files), and ask Alex to push.
- **Tools in the cloud:** `pip install unicorn capstone pillow --break-system-packages`; NASM 2.16. `py/build.py 1`-`6a` must give the MD5s in README.
- **Waiting for Alex:** the board test of 0.6.1 (README, "Testing 0.6.1 on the board"); confirmation of the HT12UMB proposal above.
- **Then:** round 6b on a new branch `stage3-6b-tools` built on `stage3-6a-setup`, starting with the EMS bar fix and HT12UMB.SYS, then the tools in the order above. Version 0.7 for 6b. (Done the same day, before 0.6.1's board test: see "Round 6b (0.7)" above.)

## Round 6b (0.7): the tools, HT12UMB.SYS in the ROM, the boot key (2026-11-19)

Branch `stage3-6b-tools`, built on `stage3-6a-setup` (0.6.1). Started while Alex tests 0.6.1 on the board, so it is not merged until both are confirmed. `asm/step6b.asm` = 6a with `ROUND6B` + `asm/tools.asm` + the `umb` section; `post.asm` and `setup.asm` keep their 6a code byte for byte without `ROUND6B` (`py/build.py 6a` still gives `39f360b6...`).

### Decided with Alex in this session

- The driver goes into the **fixed 2 KB slot at F000:6000**, zero-padded (confirmed).
- New request: **EMS and XMS on the POST screen**, since this board can set the EMS size in the BIOS.

### What 0.7 does

| Part | Where | What |
|---|---|---|
| EMS bar fix | `post.asm`, `mem_total` | The bar's total is 640 KB + CMOS 17h/18h alone (what setup configured, net of EMS, and what AMI counts up to); 30h/31h only if 17h/18h is 0. 6a took the larger of the two, and after raising the EMS size 30h/31h still held the previous POST's larger count. Emulator: 6a stops at 42 of 58 blocks (72%, as on the board), 0.7 at 42 of 42 |
| Base / XMS / EMS line | `post.asm`, `draw_memline` (row 8, under the bar) | `Base 640 KB   XMS 2048 KB   EMS 1024 KB`. While POST counts: CMOS 15h/16h, 17h/18h; at the end what POST found (40:13, INT 15h AH=88h). EMS: CMOS 36h x 64 KB (at most 35h), `None` for 0. "XMS" is the extended memory HIMEM.SYS will offer |
| HT12UMB.SYS | `step6b.asm`, section `umb`; `build.py` | Tag at F000:5FF0 (`BUBUMB`, `1.0`, length 1813, a check word), the driver at 6000, zeros to 67FF. `build.py` takes `extra/HT12UMB.SYS` (MD5 `ce87362d...`, HT12UMB 1.0), asserts it fits, that the slot is driver + zeros, and sets the check word so that the slot's word sum + it = 0. The code ends below 5FF0; 6800-6FFD is a block of its own |
| Tools page | `setup.asm`, `fields` | Eight entries (below) instead of the two auto-detect entries |
| Disk info + auto-detect | `tools.asm`, `t_info` | IDENTIFY DEVICE into a buffer: model (CF card mark), serial, firmware, default and current C/H/S, capacity (LBA sectors or C x H x S) in MB, LBA, PIO mode (51, 53/64), multiple sectors (47), IORDY, DMA; then setup's entry (the buffer) and what INT 13h AH=08h gives DOS now (after ECHS); the verdict whether setup's C/H/S is the drive's own. **Enter** = Step 3's auto-detect as type 47 (`act_det`), as the old Tools entry did |
| Partition check | `t_part`, `p_entry`, `p_chk` | The MBR (55AA), the four entries, the extended chain (up to 16 EBRs), per row: number, active, type and name, start and end C/H/S, size, the BPB's heads/sectors for FAT partitions, OK or `!`. Checks: start and end C/H/S against the LBA fields with the geometry the BIOS gives DOS (not for cylinders of 1023: CHS full), and the BPB's heads/sectors against it. Verdict: `Made with 64 heads / 63 sectors, the BIOS 32 / 63` + `DOS would read the wrong sectors: set the old geometry, or repartition.` Nothing is written |
| POST warning | `part_post` from `bu_final` | The same checks on C:'s primary entries and the first FAT BPB, two sector reads at the end of POST, no waiting. Only on a mismatch, row 14: `C: partitions use 64 heads / 63 sectors, the BIOS 32 / 63 - see Setup, Tools` |
| Disk speed | `t_speed`, `s_read`, `s_access` | INT 13h AH=02h, one whole track per read, for 2 s (36 ticks) at cylinder 0, C/2 and C - C/16: KB/s = sectors x 18.2065 / 2 / ticks. Access time: one sector at a random cylinder and head (LCG), for 2 s: ms with one decimal. ESC stops |
| Memory test | `t_mem`, `m_run` | Four patterns, each written over the whole area before it is read back: 55AAh, AA55h, walking one (bit = word number mod 16), address in address (word number, its high byte mixed into the low). Base memory 68 KB to 40:13; extended 1 MB to 1 MB + INT 15h AH=88h in 32 KB blocks through INT 15h AH=87h; the EMS pages: from (1024 + extended KB) / 16, CMOS 36h x 4 pages, each through the HT12's window 0 (reg 20h = page, reg 19h = 80h + frame position x 10h + 1) at the first free 16 KB block C000-DC00 (no shadow bit in reg 12h, FFFFh every 2 KB, nothing that keeps a byte: HT12UMB's test). Regs 19h and 20h are restored. Errors are counted; the first is shown with its linear (DRAM) address, the word written and the bits that differ. ESC stops. The HT12 bank of a failing address (planned) is not shown: the bank layout is not known well enough |
| HT12UMB page | `t_umb` | The tag, version, length, `checksum OK` (or `WRONG`), the DEBUG recipe, the CONFIG.SYS lines |
| Boot key | `post.asm` (`bk_seen`, `bk_scan`, `bk_stat`), `setup.asm` (`bk_order`) | **A** or **C** during POST boots that drive first this time (A: = "A: then C:", C: = "C: then A:"), CMOS unchanged. Seen like DEL: in the memory test through `kbd_poll` (protected mode: only the note, at 18h:FF), from checkpoint 73h by `bu_tick` in the keyboard buffer, by `del_7f` once more before AMI empties the buffer, and from 7Fh to INT 19h by `bk_order` (which also empties the buffer so DOS does not get the letter). 40:FF holds the key; `bu_final` keeps it while it clears 40:F0-FF, `bk_order` clears it. Status: `Booting: C: (this time)`; the DEL window says `DEL: Setup   A/C: boot from A:/C:` |

**Space:** the code block 000B-5FEF holds 19.5 KB, about 5 KB are left there and 2 KB at 6800-6FFD.

### Findings

1. **Setup's stack wraps.** At the Tools page SS:SP was 0030:FCF4: the POST stack is 0030:0100, and AMI's setup frame takes it below 0030:0000, so SP wraps around within segment 0030 and the stack lives at 0:FFxx-102FF. The first build put the tools' 32 KB buffer at 0:8000-FFFF and started the base memory test at 64 KB: the extended test's first block overwrote the return addresses (the CPU ran into the zeros after the code and on into the HT12UMB slot). Now: buffers 0:1000-8FFF, GDT 0:9000, variables 0:9040, base test from 68 KB. `tools_test.py stack` runs every tool in one setup visit and then needs POST to reach INT 19h.
2. **The emulator raised IRQ 14 once per command.** A real drive interrupts for every sector of a multi-sector READ SECTORS; AMI's INT 13h waits for each. One-sector reads worked, a 63-sector track read hung. `post_emu.py` now raises IRQ 14 after each sector's REP INSW while data is left.
3. **The emulator had no EMS window.** `post_emu.py` maps D000-DFFF as MMIO: an empty bus (FFh, writes vanish) unless reg 19h enables a window there; then the window shows the DRAM page of reg 20h-23h (base, the hidden 384 KB, extended memory, or `ems_kb` of pages above it). `ems_stuck = (page, offset, bits)` makes bits read 0 for the fault test. C000-CFFF stays RAM, so the test's frame search lands on D000 there (C000 is the video ROM stub, C400-CC00 keep a written byte).
4. **POST must hand INT 19h the same BDA.** `part_post`'s INT 13h reads leave the disk's status and error registers in 40:8C-8D; `setup_test.py post` (A/B with 5b) caught it. `part_post` now restores them.
5. **`t_wait` returned with BX changed**, so Enter on "Hard disk C: info" auto-detected D: (`No drive answered.`). Found by `tools_test.py info`; the helper now keeps BX.
6. **A size print clobbered SI** (the partition row's `t_mb` ends with `MOV SI,s_mb`): every row after the first was checked against garbage. Found by the first partition test; the helpers' register use is now in their comments.

### Tests

`py/tools_test.py` (new, parts `umb bar screen info part speed mem stack bootkey`). Also on the 0.7 ROM: `regress.py`, `boot_test.py`, `int6_test.py`, `autodet_test.py`, `bootskip_test.py`, `rom_checks.py`, `analyze_bios.py` (all pass), and `setup_test.py` (now follows the ROM: map and version): every part passes but the two that check the old Tools page (`pages` page 4, `tools`), as intended.

**Result:** `binary/FOXII_STEP6B.BIN` 0.7, MD5 `dc2bae308a7d14a3ac7d8baa7b4036b0` (EVEN `1ed7914f599a6587aa3d662e29bab33c`, ODD `9f813cd76e91e0aaf8c8d3f1318ce24c`). `py/tools_test.py`: **75 checks, all pass** (on this ROM). `setup_test.py` on 0.7 (parts `post exit mono dark del pages boot ab`, run on the build before the `t_wait` fix, which only touches the tool pages; `type47 datetime scheme autodet` earlier): 105 + 4 parts pass, the one failure is `pages`' check of the old Tools page, as intended. `regress.py`, `boot_test.py`, `int6_test.py`, `autodet_test.py`, `bootskip_test.py`, `rom_checks.py`, `analyze_bios.py` on 0.7: all pass. `py/build.py 1`-`6a` still give their MD5s. Screenshots: `py/shots.py 6b` (`shots/6b_*.png`). No mutation runs for 6b yet (the fault test of the memory test is the one deliberate failure path).

- **Board test:** README, "Testing round 6b (0.7) on the board". The disk speed and memory test timings are the emulator's and mean nothing; the board gives the first real numbers.
- **Next:** Alex's board tests of 0.6.1 and 0.7; then merge 6a and 6b into `main`.

## Round 6b: questions for Alex (not started)

Round 6b waits for these answers (`docs/PLAN_STAGES_2_3.md`, "The tools"). **Space:** after round 6a, **17,651 bytes** are free in F000:000B-6FFD, and perhaps about 1.3 KB more at 7000-755F (AMI's System Configuration box: F000:0008 no longer jumps there since 5b; whether other code calls into it is not checked yet). The seven candidates together are about 6.5 KB plus about 0.5 KB for running them from the setup's Tools page, so **all of them fit**, with about 10 KB to spare. Each tool would be an entry on the Tools page (next to "Auto-detect hard disk C:/D: now"), run there and return to the page with ESC.

| # | Tool | Size | Open question |
|---|---|---|---|
| 1 | **Disk info**: full IDENTIFY (model, serial, firmware, default/current CHS, LBA size, PIO modes, multiple, CF), the ECHS geometry, the CMOS entry and whether they match | ~1 KB | - |
| 2 | **Partition check**: MBR entries (type, CHS, LBA, size), extended chain, each FAT boot sector's BPB; warns when the partitions were made with another head count than the BIOS now shows (the Step 1 trap) | ~1.5 KB | Also one warning line on the POST screen when C:'s partitions do not match (no waiting)? |
| 3 | **Surface scan**: READ VERIFY (40h) over the whole drive, progress, time, list of bad sectors, ESC stops | ~0.6 KB | Also a "read" scan that transfers the data (slower, tests the data path)? |
| 4 | **Memory test**: base and extended (INT 15h AH=87h), patterns 00/FF/55/AA, walking ones, address in address; quick / thorough; failing address, bits and HT12 bank | ~1.5 KB | Also test the HT12's EMS pages (registers 20h-23h)? |
| 5 | **HT12 chipset view**: registers 10h, 12h-14h, 18h, 19h, 20h-23h decoded, read-only | ~0.6 KB | - |
| 6 | **CMOS backup / restore**: shows the differences before writing, signature and checksum | ~0.7 KB | Where to keep the copy: (1) a dedicated floppy, raw sector (overwrites that disk); (2) a file on a FAT12 floppy (friendliest, much more code); (3) the unused sectors after the MBR on C: (LBA 1-62; needs a check that the gap is empty) |
| 7 | **Disk speed**: read MB/s at start, middle and end; average seek time | ~0.5 KB | - |

**Also to decide:**

- **Which tools, and in which order** (the plan suggests 1, 2, 3, then 5, 6, 4, 7)?
- **A one-time boot choice** (a key such as F11 held or pressed during POST gives `Boot from: A / C` once, no delay without the key). With the boot order now in setup, still wanted?
- **A floppy info line** on the POST screen (what INT 13h reports for A:/B:)?
- **"Auto" mark** (5b decision 5): keep a bit in CMOS so the POST screen keeps saying `Auto` for a drive that was auto-detected, instead of `Type 47` from the second boot on?
- From round 6a, the **decisions to review** above (especially 3: the CMOS bytes 3Eh/3Fh; 5: Off still shows the model; 9: the EMS maximum recomputed at once; 12: the limits for typed values).
