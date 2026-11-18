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
