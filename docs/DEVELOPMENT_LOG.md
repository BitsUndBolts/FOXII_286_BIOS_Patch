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
