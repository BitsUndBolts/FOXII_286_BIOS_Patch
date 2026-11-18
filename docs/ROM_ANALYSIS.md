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

**The only checksum in this BIOS covers this module.** `C983` checks
the `AA55` header and that the XOR of the 3800h words F000:0000-6FFF is
zero. The main BIOS (7000-FFFF) is not checksummed at all.

`C983` is called twice:

- `929B`: during POST. On failure it jumps to `92EA`: "ROM-BIOS CHECKSUM ERROR / CHECK ROM (27256)? / SYSTEM HALTED".
- `97BC`: at the very end of POST. On success it calls **F000:0008** (the System Configuration box), then jumps to the boot code at `8F48`.

The setup menu shows "RUN DIAGNOSTICS" only if the byte at **E058** is
non-zero (it is FFh); the item calls F000:0003 (`BD46`).

A coverage disassembly from every entry point (reset, the IVT, the
INT 13h dispatch table, POST jump tables, setup) found **no other
reference** from the main BIOS into 0000-6FFF. The module can be
replaced as a whole.

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
| Type-47 table | template `E260` copied to **0000:0300** (`F1BA`, 30h words = 96 bytes, 0300h-035Fh) when the setup option "Scratch RAM option" is 1 ("BIOS stack area at 0030:0000"). Option 2 takes 1 KB from the top of base memory instead. |

With option 1 the stack may grow down from 0400h to 0360h before it
overwrites the table: **160 bytes**. Patched code that runs during
POST must stay within that budget (SOYO pitfall 4.8).

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
| F537-F840 | 778 | before INT 12h at F841 |
| **Total** | **~1.57 KB** | |

On top of that:

- **0000-6FFF (28,672 bytes)** if the diagnostics module is replaced.
  Keeping a valid `AA55` header and XOR there keeps `C983` happy, and
  turns F000:0008 into a free end-of-POST hook and F000:0003 into a
  free setup-menu hook.
- **7000-755F (~1.3 KB)** if the System Configuration box is replaced
  by the POST screen.

Compare the SOYO: ~2 KB free plus 4.5 KB of reclaimed dead code, and
13 bytes left at the end of BUBios.
