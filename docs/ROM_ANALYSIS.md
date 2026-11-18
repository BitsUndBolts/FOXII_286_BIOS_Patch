# ROM Analysis: AMI 286 BIOS 06/13/90 (Octek FOX II, Headland HT12/A)

**What this is:** the verified map of the original BIOS that the FOX II
runs, written before any byte was changed (Step 0). Every fact in
sections 1-9 is asserted by `py/analyze_bios.py` against
`base/FOXII_0613_ORIGINAL.BIN`. If you change an address here, change
the script too.

All addresses are offsets in segment F000 (file offset == IP).

| | |
|---|---|
| BIOS | AMI 286 BIOS, date 06/13/90, ID string `HT-11 286 BIOS` (POST shows `DH12-1112-061390-KF`) |
| Board | Octek FOX II rev 3.4, Headland HT12/A, Harris CS80C286-20 |
| Chips | two 27256 (32 KB each): EVEN = low byte of every word, ODD = high byte |
| CPU image | 64 KB, F000:0000-FFFF, MD5 `c74e174c716add49b1b686c70d8df83c` |
| Chip dumps | `base/ORIG_EVEN.BIN` `1bcd22853e656c19ee65670aad8fe1b7`, `base/ORIG_ODD.BIN` `42824741ba95e0f09630d493d4e2371e` (64 KB doubled) |

Why this BIOS and not the 11/30/90 image in `Original\`: only 06/13/90
has the **EMS size** setup option, which HT12MM.SYS and the HT12UMB
driver rely on. (11/30/90 has "Fast I/O BUS speed" instead.)

---

## 1. The image: two chips, one 64 KB BIOS

The 286 reads 16-bit words. The EVEN chip answers for A0 = 0 (low byte),
the ODD chip for A0 = 1 (high byte). Two 32 KB chips therefore make one
**64 KB** BIOS at F0000-FFFFF, the same size as the SOYO's single
27C512.

- **JP1** selects 27256 (1-2, factory) or 27128 (2-3). It does not add
  address lines.
- **Pin 1** of a 28-pin socket is VPP on a 27256 and is held high. On a
  27C512 / 27SF512 pin 1 is A15, so the board reads the **upper 32 KB**
  of a 64 KB chip. That is why burnable images are "doubled".
- A 128 KB BIOS would need A16 wired to pin 1 and ROM decoding at
  E0000-EFFFF. That segment is where EMS and the UMBs live, and we don't
  need the space (see 9). Not pursued.
- `py/romtool.py join` builds the CPU image from the two chip files and
  refuses a swapped pair (it checks the reset vector). `split` writes
  doubled 64 KB chip files for a 27C512 / 27SF512.

**Naming check (2026-11-18):** in every pair in the Documents folder,
including `Original\ORIG_EVEN.BIN` and all DIAG builds, the EVEN file
holds the low bytes. The files were always right; only an earlier note
said otherwise and has been corrected.

## 2. The ROM Diagnostics module (0000-6FFF, 28 KB)

The lower part of the ROM is AMI's **ROM Diagnostics** (04/09/90): a
separate program with an option-ROM header.

| Offset | Content |
|---|---|
| 0000 | `AA 55 40` header (size byte 40h = 32 KB, but only 28 KB are checked) |
| 0003 | `JMP 00A0`: the diagnostics program (menu "RUN DIAGNOSTICS") |
| 0008 | `JMP 7000`: the **System Configuration** box shown at the end of POST |
| 000B | `04/09/90ROM DIAGNOSTICS` |
| 0000-6FFF | hard disk utility (low-level format, interleave, surface scan, performance, seek), floppy, keyboard and video tests |

`C983` checks the module: the `AA55` header and that the XOR of the
3800h words F000:0000-6FFF is zero. The upper half has its own checksum
(see 2b); 7000-7FFF is covered by neither.

`C983` is called twice:

- `929B`: during POST. On failure it jumps to `92EA`: "ROM-BIOS CHECKSUM ERROR / CHECK ROM (27256)? / SYSTEM HALTED".
- `97BC`: at the very end of POST. On success it calls **F000:0008** (the System Configuration box), then jumps to the boot code at `8F48`.

The setup menu shows "RUN DIAGNOSTICS" only if the byte at **E058** is
non-zero (it is FFh); the item calls F000:0003 (`BD46`).

A coverage disassembly from every entry point (reset, the IVT, the
INT 13h dispatch table, POST jump tables, setup) found **no other
reference** from the main BIOS into 0000-6FFF. The module can be
replaced as a whole.

## 2a. AMI's disk tests inside the diagnostics module (reference for round 6b)

Recorded in round 5a, before the module was removed from the ROM. The
original stays in `base/FOXII_0613_ORIGINAL.BIN`; these are its offsets.
They were found from the module's INT 13h calls and strings, not traced
line by line, so treat them as a starting point.

| What | Where |
|---|---|
| Entry (menu "RUN DIAGNOSTICS") | `0003 JMP 00A0`: own stack 0000:FFEE, clears 0:0600-FFED, own main menu |
| Hard disk utility menu texts | `1C2C`: Hard Disk Format, Auto Interleave, Media Analysis, Performance Test, Seek Test, Read/Verify Test, Check Test Cyl., Force Bad Tracks, Floppy Format, Drive Speed Test, Random R/W Test, Sequential ...; titles at `27C1` (Auto Interleave Detection, Hard Disk Surface Analysis, Hard Disk Seek Test, Hard Disk Read/Verify Test ...) |
| Its data | segment 0000 (DS = SS = 0): current drive at `0:0626`, a cylinder counter at `0:0629`, the last INT 13h status at `0:28A6` |
| INT 13h wrapper | `4ED3` (`4D84` / `5288` prepare the call when `[0626] >= 80h`) |
| Drive reset + verify | `523F-5287`: AH=00h twice, then AH=04h (verify) of one sector at a few places, retried; CF on failure |
| Media analysis / Read-Verify | the verify loop around `5513-558E` (AH=04h, AL=1 per sector, status kept in `[28A6]`; `558C` retries status 06h) |
| Performance test | `62D0-6360`: masks IRQ 1, reads 15 x 64 KB with AH=02h AL=80h (`62FE`), the time from the BIOS tick counter 40:6Ch; screen `2B33` ("Transfer size : 64 KB", "Data Transfer Rate"); result printed as `KB/sec` / `ms` at `6456-6476` |
| Seek test (track to track) | `6381-63D7`: AH=0Ch seeks over 200 (C8h) cylinders one by one, timed with 40:6Ch |
| Low-level format, interleave, bad tracks | the rest of 2000-6xxx: MFM only, not useful on IDE / CF |

None of this code is used by the new tools as it is: it runs the drive
through the BIOS's CHS calls with AMI's own screen code, and times with
the 55 ms tick. The useful ideas are the loop structure (verify per
sector, retry on status 06h) and the timing with 40:6Ch around 64 KB
reads.

## 2b. The POST ROM checksum and the tamper checks

**Corrected after the first board test.** Step 0 missed this checksum,
and the first ECHS ROM stopped at POST code 02.

| Where | What | On failure |
|---|---|---|
| `8143-8155` | POST checkpoint **02**: 16-bit word sum of F000:**8000-FFFF** (4000h words) must be 0 | `BP=9` -> `8D14`: beep code 9 ("ROM-BIOS checksum failure"), POST stops showing 02 |
| `C983` | diagnostics module: `AA55` + XOR of 0000-6FFF = 0 | "ROM-BIOS CHECKSUM ERROR", halt |
| `76BC` | AMI tamper check: 24h bytes at 7649 equal those at FF97 | |
| `FA4F` | AMI tamper check: 4Ch bytes at FF70 equal the inverted bytes at FA00 | |

So every change in 8000-FFFF needs a balancing word (the builds use
**F83E**, the last word of the free block F537-F840), changes in
0000-6FFF need a balancing XOR word, and changes in 7000-7FFF need
nothing. The four regions of the tamper checks must stay unchanged.
`py/rom_checks.py` runs all four routines from the ROM in the emulator.

## 3. INT 13h fixed disk

This is the same AMI disk code as the SOYO's 11/11/92 BIOS: about 74 %
of the bytes match in long runs, and the stack frame and all five ECHS
patch sites have the same shape. The SOYO's `CHS_TRANSLATION_PORTING_GUIDE.md`
§4 applies almost word for word.

| Item | FOX II 06/13/90 | SOYO 11/11/92 |
|---|---|---|
| INT 13h HD entry (`cmp dl,80h`) | `A15F` | `A3E7` |
| Frame: push ax cx dx bx si di ds es, `sub sp,8`, push bp | `A171` | same |
| Dispatch `call cs:[di+A1C0]`, AH 00h-19h | `A18F`, table `A1C0` | `A44B` |
| AH=08h reporting body | `A357-A383` | `A659-A685` |
| AH=08h tail (`DL=[75h]`, `AH=0`, `[74h]=AH`, `RET`) | `A384-A38E`, keep | `A686-A690` |
| Drive-select (pushes ES BX DX CX) | `A619` | |
| `AND DH,0Fh`, the only one in the ROM | **`A65A`** | `A965` |
| Cylinder-high builder, format path (17 bytes) | `A30C-A31C` | `A60E` |
| Cylinder-high builder, seek path (16 bytes) | `A4DF-A4EE` | `A7EA` |
| Cylinder-high builder, read/write/verify (16 bytes) | `A832-A841` | `AB3D` |
| FDPT vectors | INT 41h `0:104` (`A60C`), INT 46h `0:118` (`A611`) | same |
| Drive type table (type 1 = 306/4) | `E401` | |

Each cylinder-high builder is `CL bits 7:6` OR (`[bp+15]` >> 4 & 0Ch),
stored to `[bp+06]` and written to 1F5h. `[bp+15]` is the caller's DH.
This is the AMI convention of passing cylinder bits 11:10 in DH bits
7:6, exactly as on the SOYO (pitfall 9.3 there: never write to it).

AH=08h reports cylinders - 2 (`sub ax,2`), clamped to 3FFh.

## 4. POST stack and the type-47 RAM area

| | |
|---|---|
| POST/boot stack | `SS:SP = 0030:0100` (`F1B2`), linear 0300h-03FFh |
| 0000:0300-035F | AMI's **GDT** for its protected-mode memory work: the template at `E260` (30h words) is copied there at `F1BA` on every POST, and its alias descriptor is pointed at 0300h |
| Type-47 drive tables | built by `9834` / `983C` from CMOS. The ROM byte `E2C0` has bit 6 clear, so CMOS 38h bit 4 decides: clear ("Scratch RAM option" 1, "BIOS stack area at 0030:0000") -> segment 002Dh, **0:030D (C:) and 0:031D (D:)**, inside the GDT area; set (option 2) -> the top 1 KB of base memory, which checkpoint 7Dh then reserves |

With option 1 the stack may grow down from 0400h to 0360h before it
reaches the table area: **160 bytes**. Patched code that runs during
POST must stay within that budget (SOYO pitfall 4.8).

(Corrected in Step 3: this section called `E260` the type-47 template.
It is a GDT; the type-47 tables are built separately, at 030Dh/031Dh
with option 1. The budget is unchanged.)

## 5. INT 06h: why a 386 boot sector hangs the board

The 286 raises INT 06h (invalid opcode) for any 386 instruction (`66h`
and `67h` prefixes, `0F xx` opcodes it doesn't know, and so on). The
return address points at the faulting instruction.

| | |
|---|---|
| IVT template | `FEE3` (INT 00h-1Fh), INT 06h -> **`EB31`** |
| `EB31` | handles `0F 05` (`LOADALL`, emulated for CPUs that trap on it) and steps over a `LOCK` prefix |
| `EB2E` | everything else: `JMP EA85`, the unexpected-interrupt handler |
| `EA85` | finds no IRQ in service and IRETs |

The IRET returns to the same invalid opcode, which faults again,
forever. The machine appears frozen and nothing is printed. That is the
hang seen with boot sectors that contain 386 code. Redirecting the
3-byte `JMP` at `EB2E` to a new handler can print a message instead.

## 6. Boot (INT 19h)

| | |
|---|---|
| `8F80` | INT 1Eh vector, clear 0000:7C00 |
| `8F9B` | reset, **try A:** (`DL=0`) through `9005` |
| `8FB1` | CMOS 0Eh bit 3 set (fixed-disk init failed in POST) -> **skip C: silently** |
| `8FBA` | try C: (`DL=80h`) |
| `8FC3` | INT 18h |

There is no boot-order option: A: is always tried first.

More of the boot path, used by Step 4 (asserted in `analyze_bios.py` section 11):

| | |
|---|---|
| INT 19h | IVT template -> `E6F2` -> `JMP 8F80`: the only entry. The end of POST calls `INT 19h` at `F530` |
| `8F80` | `XOR AX,AX / MOV ES,AX`, INT 1Eh = F000:**EFC7** |
| `8FDF` | A: path: A:'s sector read; the first 128 bytes all equal -> INT 18h, else `8FEE` -> `JMP 0000:7C00` (`8FF5`) |
| `9005` | read sector 1 of DL with head **DH**, up to 4 tries with a reset in between |
| `8FFA` | C: path: `55AA` test, then the same jump |
| `8F63` / `8FC7` | AMI's INT 18h, when called from `8FC3`: prints SI's message (`7D9B` DISKETTE BOOT FAILURE, `7DB3` INVALID BOOT DISKETTE, `7DCB` DRIVE NOT READY ERROR), then "Insert BOOT diskette in A: / Press any key when ready", waits for a key and starts again at `8F80`. From elsewhere: "NO ROM BASIC" and halt |
| `90B9` | POST (checkpoint 12h) fills INT 00h-77h with F000:**EA85**; DOS replaces INT 21h, so INT 21h = F000:EA85 means DOS is not loaded |

## 7. POST and setup

- POST starts at `806C` (`E05B` jumps there). The early part runs
  without RAM: subroutines return through `MOV SP,table / JMP` and
  `JMP SP` (see `8D4E`), so a disassembler has to follow `MOV SP,imm`.
- End of POST: checkpoint 86h at `97A2` (option ROM at E000 scanned by
  `8EFD`), checkpoint 00h at `97B8`, F000:0008 (the configuration box),
  then the boot at `8F48`.
- Setup is called at `978B` (`CALL BCA6`) when DEL was pressed (word
  `[0069h]` non-zero). It shows a three-item menu (RUN DIAGNOSTICS / RUN
  CMOS SETUP / EXIT FOR BOOT, strings at `D6F0`) and one options page
  (strings from `D72C`). The menu records are `row, column, attribute,
  text, 0`; the printer is `C859`.
- The POST error messages are in `7AF2-7EB8`; the System Configuration
  box code is at `7000-726A`, with its strings at `726A-755F`.

## 8. HT12 chipset (index 1EDh, data 1EFh)

| | |
|---|---|
| `F458` | read: AL = index -> AL |
| `F464` | write: AL = index, AH = value |
| `F104` | init table: 10h=0Eh, 12h=00h, 13h=00h, 14h=18h, 18h=3Fh |
| `F327-F42F` | main and video BIOS shadow |
| `F432-F457` | memory relocation: reg 10h bits 3-5 from CMOS 37h |
| `F261-F29A` | reg 18h = 0Fh + CMOS 35h - CMOS 36h (EMS/extended boundary, inferred) |
| `F2BF` | reg 14h bit 2 from CMOS 38h bit 7 when reg 10h banks = 3 |

What the shadow code shows: with a block enabled in reg 12h/13h and
**reg 14h bit 1 clear, reads come from ROM and writes go to RAM**; with
bit 1 set, reads come from RAM and writes are blocked. The video shadow
copies C000 onto itself in the first mode and compares in the second,
which only works with these semantics. There is no read-write state for
shadow blocks, and bit 1 is global.

From HT12MM.SYS (Quadtel 4.00): EMS window page registers are index
**20h-23h** (four windows of 16 KB). Reg **19h**: bits 0-3 enable each
window, bits 4-6 pick the frame base (C000, C400, C800, CC00, D000),
bit 7 is the master enable. Reg 14h bit 2 makes HT12MM add 24 pages
(the 384 KB behind A0000-FFFFF) to the EMS pool. **The EMS frame, and
so a read-write UMB area, is limited to 64 KB by the hardware.**

## 9. Free space

Runs of 00h outside the diagnostics module:

| Block | Bytes | Note |
|---|---|---|
| 7EB9-7EFF | 71 | after the POST messages |
| 7F0E-7FFF | 242 | after the ID string |
| DFBA-DFFF | 70 | after the setup strings |
| E32C-E3FD | 210 | stop before E3FE (IBM INT 13h entry address) |
| E7E8-E82D | 70 | before INT 16h at E82E |
| F474-F4F9 | 134 | after the HT12 helpers; F500 is code |
| F537-F840 | 778 | before INT 12h at F841; F83E-F83F is the checksum word of the builds |
| **Total** | **~1.57 KB** | |

**The first 00h of a run that follows text is that string's terminator.** 7EB9 ends "PARITY ERROR ????", 7F0E ends the ID string "HT-11 286 BIOS", DFBA ends "Dec", and E32C ends the copyright line at E300 that POST prints at `F042` (`286-BIOS (C)1989 American Megatrends Inc` CR LF CR LF, no 00h of its own). These four bytes stay 00h: the usable blocks start one byte later (7EBA, 7F0F, DFBB, E32D). Step 3's first build put code at E32C, and on a warm boot the line ran on into it on the screen.

Used so far:

| Block | Step | Left |
|---|---|---|
| F537-F81E | 1, 2 | 31 bytes before F83E |
| 7F0F-7FD3, E32D-E3F9 | 3 | E3FA-E3FD: 4 |
| F474-F4EF, 7EBA-7EFF, DFBB-DFF6, 7FD4-7FFE | 4 | F4F0-F4F9: 10, DFF7-DFFF: 9, 7FFF: 1 |

What is left outside the diagnostics module is about 55 bytes plus E7E8-E82D (70 bytes; not used yet: the bytes in front of it are data whose purpose is not known). Stage 2 (the POST screen) needs the System Configuration box's space (7000-755F) or the diagnostics module.

On top of that:

- **0000-6FFF (28,672 bytes)** if the diagnostics module is replaced.
  Keeping a valid `AA55` header and XOR there keeps `C983` happy, and
  turns F000:0008 into a free end-of-POST hook and F000:0003 into a
  free setup-menu hook.
- **7000-755F (~1.3 KB)** if the System Configuration box is replaced
  by the POST screen.

Compare the SOYO: ~2 KB free plus 4.5 KB of reclaimed dead code, and
13 bytes left at the end of BUBios.

## 10. CMOS drive types and the fixed-disk setup

Found for Step 3 (IDE auto-detection); asserted by `py/analyze_bios.py`
section 10.

**CMOS access.** `EE89` reads (AL = index -> AL), `EE92` writes (AL =
index, AH = value). `EE9F` / `EEAE` do the same with NMI disabled
(index OR 80h) and keep every register except AL. The setup and the disk
code use `EE9F` / `EEAE`.

| CMOS | Meaning |
|---|---|
| 12h | high nibble = C: type, low nibble = D: type: 0 = Not installed, 1-14 = that type, 0Fh = the type is in 19h / 1Ah |
| 19h / 1Ah | C: / D: type 16-47 (47 = user type); 0 or anything above 47 counts as none (`A8AA`, `A8E7`) |
| 1Bh-23h / 24h-2Ch | C: / D: type-47 parameters: cylinders lo, hi, heads, write precompensation lo, hi, control byte, landing zone lo, hi, sectors (`9880` builds the drive table from them in this order) |
| 2Eh / 2Fh | checksum: byte sum of **10h-2Dh**, high byte in 2Eh. POST checks it at `82B2` (a sum of 0 counts as bad); setup writes it at `C0B9` |
| 0Eh | POST status: bits 7:6 = RTC power lost / checksum bad; bit 3 = fixed-disk setup failed (INT 19h then skips C:) |

Drive types 1-46 come from the table at `E401` (16 bytes per type,
type 1 first).

**Setup** writes 10h-3Fh, the checksum, clears 0Eh and 0Fh and jumps to
F000:FFF0 (`C0F0`): every saved change goes through a full POST.

**POST, from the IDE reset to the disk setup:**

| Where | What |
|---|---|
| `93FD` | checkpoint 73h: IDE soft reset (3F6h = 04h, then 00h), then about 1 s |
| `9412` | checkpoint 74h: floppy |
| `943A` | checkpoint 75h: CMOS 0Eh bits 7:6 set -> skip the disk setup |
| `9447` | `MOV AL,92h / CALL EE9F`: CMOS 12h; zero -> skip the disk setup (**Step 3 hook 1**) |
| `9450` | checkpoint 76h: `CALL A857` |
| `A857` | the fixed-disk setup: INT 13h vector -> `A15F`, INT 76h -> `E845`, clears 40:42-48, 74-76, 8C-8E |
| `A894` | `MOV AL,92h / CALL EE9F`: CMOS 12h again (**Step 3 hook 2**; AH must stay 0, `A8C5` uses AX) |
| `A899-A901` | INT 41h / 46h -> the type table or, for type 47, `9834` / `983C`; 40:75 = number of drives |
| `A905` | INT 13h AH=14h (controller diagnostic); failure -> POST flag 0004h, CMOS 0Eh bit 3, return |
| `A993` | per drive: AH=09h / AH=11h, retried until 2D8h ticks (**40 s**) have passed; failure -> flag 0020h (C:) / 0040h (D:) |
| `A95F` | AH=08h, then AH=04h verify of the last sector |

At checkpoint 75h interrupts are on and the BIOS tick counter 40:6Ch
runs; `A857` itself starts with `CLI`. IRQ 14 is still masked in the
slave PIC (`CEF9` / `EF1C` mask everything); INT 13h's reset unmasks it
(`A79D`).

**Measured in the emulator (`py/autodet_test.py`) with the original
disk code:** a configured C: on an empty bus costs about 9 s (AH=14h
times out, flag 0004h); a configured D: that is not there costs 40 s
(the `A993` retries, flag 0040h).
