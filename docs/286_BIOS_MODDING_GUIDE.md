# Modding a 286 AMI BIOS: the FOX II method

**What this documents:** how the 1990 AMI 286 BIOS of the Octek FOX II
(Headland HT12/A) is mapped and modified. It builds on the SOYO
project's two guides (`SOYO_SY-019L1_504_Patch/docs/`
`CHS_TRANSLATION_PORTING_GUIDE.md` and `BIOS_MODDING_GUIDE.md`) and
records only what is **different on a 286, two-chip board**, plus every
step taken here. It grows with each step; the addresses are in
[`ROM_ANALYSIS.md`](ROM_ANALYSIS.md), the history in
[`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md).

---

## 1. What changes on a 286 board

| | SOYO 386 (1992) | FOX II 286 (1990) |
|---|---|---|
| ROM | one 27C512, 8-bit | two 27256 on a 16-bit bus (EVEN = low bytes, ODD = high bytes) |
| BIOS size | 64 KB | 64 KB (2 x 32 KB) |
| Burn images | the image as is | split into EVEN/ODD, each doubled to 64 KB for a 27C512 / 27SF512 |
| Checksum | 16-bit word sum over 64 KB | word sum over **8000-FFFF** (POST code 02) and XOR over the diagnostics module (0000-6FFF); 7000-7FFF unchecked |
| Free space | ~2 KB, then 4.5 KB of reclaimed dead code | ~1.5 KB, plus a 28 KB diagnostics module nobody calls |
| CPU for new code | 386: 32-bit registers allowed | **286 only**: no `EAX`, `MOVZX`, `PUSHAD`, `SETcc`, `FS/GS` |
| POST style | stack from early on | early POST runs **without RAM** (`MOV SP,table` + `JMP`) |
| Invalid opcode | no #UD issue for 386 code | INT 06h for every 386 instruction (see 5) |

## 2. From chips to an image

1. Dump both chips. Each dump of a 27256 is 32 KB; a 27C512 / 27SF512
   dump is 64 KB with the BIOS in the **upper** half, because pin 1
   (A15 on the 64 KB chip, VPP on a 27256) is tied high on this board.
2. Interleave: byte *n* of EVEN, then byte *n* of ODD.
3. **Prove the order, don't trust file names.** The last 16 bytes must
   be `EA xx xx 00 F0` (JMP FAR F000:xxxx) followed by the date; the
   swapped order gives garbage there and turns every string into
   pairs of swapped letters ("0o/4909/R0MOD"). `py/romtool.py join`
   refuses a swapped pair.
4. `romtool.py split` reverses it and doubles each half for burning.
   Check the round trip: splitting the joined original must give back
   the original dumps byte for byte.

## 3. Mapping

Read the SOYO porting guide §4 first; it applies. What was different here:

**3.1 Look for an option-ROM header at F000:0000.** This AMI BIOS
carries its ROM Diagnostics as an `AA 55` module in the lower 28 KB,
with two entry points (0003: the diagnostics, 0008: the configuration
box). Its "ROM checksum" covers only that module. Find the routine that
checks `AA55` at CS:0 to see how far the check reaches (here `C983`,
3800h words) and who calls it (here POST at `929B`, and the end of POST
at `97BC`, which also uses it as "is the module present?").

**3.1a Find every checksum, not the first one.** Step 0 found the
diagnostics XOR and stopped looking; the first board test then stopped at
POST code 02, which on AMI BIOSes of this age **is** the ROM checksum.
Two ways to find them all:

- Search for every loop that reads code space: `2E AC` (`lodsb cs:`)
  and `2E AD` (`lodsw cs:`), and look at what each one does with the
  values. Here that gives 9 hits: two checksums, two AMI tamper checks
  (copyright text compared with a second, inverted copy), a string
  printer and table walkers.
- Read the first POST checkpoints. Checkpoint 02 (`8143`) is a word sum
  of CS:8000-FFFF that must be zero.

Then **run the BIOS's own check routines** on every built image in the
emulator (`py/rom_checks.py`), rather than re-implementing them in the
build script: a reimplementation shares its author's misunderstanding.

**3.2 Linear disassembly fails; follow `MOV SP`.** Before RAM is tested
the POST "calls" subroutines with

```
mov sp, 833Eh     ; 833E holds the return address 8340h
jmp ee89          ; ... which ends in RET (pops [SS:SP], SS = CS)
```

or ends a routine with `JMP SP`. A recursive disassembler has to follow
both `imm` and the word at `imm`. `py/coverage_disasm.py` does that and
also follows the jump tables of INT 13h (`A1C0`), the shutdown codes
(`80D4`) and four others. It reaches ~9,700 instructions.

**3.3 Proving a region is dead.** Before planning to reuse the
diagnostics module, every near `CALL`/`JMP` from reached code was
checked for a target below 7000h. A blind byte scan finds 32 such
`E8`/`E9` patterns; the recursive pass leaves one, at `8341`, which is
an artifact of 3.2 (the table word at `833E` decoded as code). The only
real entries are the far ones: `MOV AX,3` / `MOV AX,8` + `CALL AX`.

**3.4 The INT 13h code is the 386 BIOS's ancestor.** Comparing the
disk code with the SOYO's (Python `difflib` on the two byte ranges)
showed about three quarters of it identical and all five ECHS sites with
the same instructions, just at other addresses. When a BIOS of the same
vendor has already been patched, compare before mapping from scratch.

## 4. Writing 286 code

- Assemble with `CPU 286` in NASM. **Unicorn runs 386 opcodes without
  complaint**, so the emulator will not catch a stray `MOVZX`; only the
  assembler does.
- 32-bit arithmetic is done in 16-bit halves: `MUL r16` gives DX:AX,
  `DIV r16` divides DX:AX but the quotient must fit in 16 bits, so a
  large dividend is divided in two steps (high word first, remainder
  carried into the low word).
- `PUSHA`/`POPA`, `PUSH imm`, `SHL r,imm`, `IMUL r,r,imm`, `ENTER`/`LEAVE`
  are fine: they are 186/286 instructions. The original BIOS itself uses
  `PUSH imm` and shifts by an immediate count.

## 5. ECHS on a 286 (Step 1)

The SOYO's `CHS_TRANSLATION_PORTING_GUIDE.md` applies unchanged: same
five sites, same contracts, same pitfalls. On this ROM, finding the sites
took minutes: the AH=08h body is byte-identical to the SOYO's, and the
other four sites are found with the byte patterns `80 E6 0F` and
`8A C1 C0 E8 06 ...` followed by `BA F5 01`.

What had to change is the arithmetic in `xlate_headcyl`:

```
; LBA = (logC * transH + logH) * S + logS - 1    (always < 2^24)
mov  ax, logC
mul  transH            ; dx:ax
add  ax, logH
adc  dx, 0
mov  bx, ax            ; low word
mov  ax, dx
mul  S                 ; high word * S: fits in 16 bits
mov  cx, ax
mov  ax, bx
mul  S                 ; low word * S
add  dx, cx            ; dx:ax = (logC*transH + logH) * S
...                    ; + logS - 1

div32:                 ; DX:AX / CX -> DX:AX quotient, BX remainder
push ax
mov  ax, dx
xor  dx, dx
div  cx                ; high word first
mov  bx, ax
pop  ax
div  cx                ; remainder of the high word carries into the low word
xchg bx, dx
ret
```

Save only the registers you change. `PUSHA` is legal on a 286, but it
puts 16 bytes on a POST stack that has a 160-byte budget.

## 6. The emulator harness on a 286 ROM

The SOYO's `py/ide_harness.py` ports by changing four addresses (the
INT 13h entry and the `rep insw` / `rep outsw` sites). Three changes made
it usable here, and they apply to the SOYO's harness too:

- **Don't hook every instruction.** A Python callback per emulated
  instruction makes long waits take minutes. Hook only the string
  transfer sites (`begin`/`end` of the hook), and measure the stack by
  **painting** it: fill the stack segment with a marker before the call,
  then find the lowest byte that changed.
- **A drive raises IRQ 14 for every sector.** Raise the "interrupt
  happened" flag (BDA 40:8E) again after each simulated transfer, or
  every multi-sector call times out.
- **DRQ ends with the last sector.** Write loops run "while DRQ". Count
  down the sectors of the current command and drop DRQ at zero.

When both ROMs fail a call identically, an A/B test can still report a
difference, for example in a leftover loop counter returned in CX. Look
at why the call failed before treating the difference as a bug.

**Prove the tests work.** Break the ROM on purpose (leave one site
unpatched, overwrite the AH=08h tail) and check that the tests fail. All
three such mutations failed here.

## 7. The invalid-opcode trap (Step 2)

A 286 raises INT 06h for any instruction it doesn't know, with the
return address at the faulting instruction. AMI's handler here deals
with `0F 05` (`LOADALL`, which this shared AMI code emulates on CPUs that
trap on it) and steps over `LOCK`, then passes everything else to the
generic "unexpected interrupt" handler, which IRETs. The CPU executes
the same opcode again and the board appears frozen with no message.
That is what happens with a boot sector containing 386 code.

The fix redirects the one `JMP` that passes the case on (`EB2E`) to a
handler that prints where it happened and halts. What it has to do
before printing, because the fault can come from anywhere:

- **Make Ctrl+Alt+Del work.** Mask every IRQ except the keyboard, send
  non-specific EOIs to both PICs (several: the fault may be nested inside
  interrupt handlers), and point INT 09h back at the BIOS keyboard
  handler. Take its offset from the ROM's own IVT template, not from a
  constant.
- **Make the message visible.** A game may be in a graphics mode: switch
  to mode 3, or 7 when the BIOS equipment word (0040:0010 bits 5:4 = 11)
  says monochrome. In a text mode, print below what is there: the
  program's last output may help.
- **Don't try to return.** The program cannot continue, and the fault may
  be inside DOS, a driver or an interrupt handler, where ending the
  program would corrupt DOS.

**Testing it in Unicorn.** Unicorn is a 386+ emulator: 386 opcodes run,
and an opcode that is invalid everywhere stops the emulation with
`UC_ERR_INSN_INVALID` instead of raising INT 06h. Play the CPU in the
test: catch that error (IP is on the faulting instruction), push FLAGS,
CS and IP, and continue at the INT 06h vector. Use `0F 0B` (UD2) as the
"386 instruction". On the board, a 3-byte `.COM` with `66 31 C0` (XOR
EAX,EAX) and `CD 20` is the real test.
