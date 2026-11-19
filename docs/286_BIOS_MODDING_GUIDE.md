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

## 8. IDE auto-detection in POST (Step 3)

**Find the two CMOS reads, not one.** AMI's POST reads the drive-type
byte (CMOS 12h) once to decide whether to run the fixed-disk setup at
all (checkpoint 75h, `9447`), and the setup reads it again (`A894`). A
hook only at the first read can add drives, but can't hide a drive from
the setup. Both are `MOV AL,92h / CALL EE9F`, 5 bytes, so each becomes a
3-byte `CALL` plus two NOPs.

To find them: list every call of the CMOS read routines with the index
loaded before it (the `92h` is 12h with the NMI bit). The POST
checkpoint written just before (`OUT 80h`) names the step.

**Replace a call, keep its contract.** The replaced `CALL EE9F` changes
only AL. The code after `A894` does `DEC AX` and `SHL AX,4` on the whole
register and relies on AH = 0, so the new routines keep every register
except AL. Test that directly, with AH = 00h and A5h going in.

**Write auto-detected drives, don't drop configured ones in CMOS.**
Writing "Not installed" for a missing drive looks tidy, but the next
boot auto-detects it with its physical geometry. If the user had
entered another one (a card partitioned under another BIOS), the ECHS
translation changes and the partitions are lost. Return a 12h value
without the missing drive to the setup instead: it lasts one boot.

**IDENTIFY by polling during POST:**
- Use the BIOS tick counter (40:6Ch) for timeouts when interrupts are
  on at the hook (here since `9439`); check that the original code
  around it relies on the ticks too (`A993` does).
- "Nothing answers" means status **FFh, 7Fh or 00h**. 00h is what a
  master answers for a missing slave (seen on the board's SanDisk card).
- **A drive ignores a device select while it is busy.** Wait for BSY
  to clear, then select again, before trusting the status of a slave.
  Otherwise a busy master answers the slave probe and is written into
  CMOS as D:.
- Read the status register at the end: it clears the drive's interrupt
  request while IRQ 14 is still masked.
- Accept only geometries the rest of the BIOS can handle (here 1-16383
  cylinders, 1-16 heads, 1-63 sectors).

**A zero run after a string starts with its terminator.** AMI's strings end at the first 00h, and a string followed by free space often has no 00h of its own: the free run supplies it. Here the copyright line at E300 ends at E32C, the first byte of a "free" block; code put there made the line run on into the code, which was only visible on a warm boot (the cold boot's memory count overwrote the line). Before using a block, look at the byte in front of it. If it is text, keep the first 00h and start one byte later. Then run the ROM's own printers on the image and compare their output with the original's (`rom_checks.py`).

**Several code blocks.** Step 3 doesn't fit one free block. Assemble one
file with a NASM section per block, `start=` = `vstart=` = the ROM
offset, write a map file (`[map all ...]`), and let the build copy each
section from the map into its block. Assert that each block was empty
and that the sections of earlier steps are unchanged. 7000-7FFF has no
ROM checksum here, which makes it the easiest place for new code.

**A POST emulator for one step.** `py/autodet_test.py` runs POST from one
checkpoint to the next, not from reset. It needs only:
- the register state at that point (DS = 40h, ES = 0, the POST stack
  with the word POST has on it);
- the BDA values the code reads (here 40:13 is still in 64 KB units
  until checkpoint 7Dh);
- simulated hardware: CMOS, a two-device IDE bus with busy times and
  ignored selects;
- a clock driven by the I/O accesses, so tick timeouts run as on the
  board.

Running the reference ROM through the same cases measured what the
patch removes: 40 s for an unplugged D:, about 9 s for a configured C:
on an empty bus.

## 9. Going on with the boot after a fault (Step 4)

A BIOS can recover from a fault in a boot sector, because nothing of the boot sector is needed any more: its job was only to load the system. The method:

**Know which drive is booting.** Find where INT 19h starts each drive's boot sector. Here A: and C: have separate code before a shared `JMP 0:7C00`. Hook each path (or only A:) to set a marker, and clear it at INT 19h's entry. A marker word in the BDA's intra-application area (40:F0) survives the boot sector, which typically only touches 0:0500-0:7FFF and its own stack.

**Know whether DOS is up.** POST fills all low interrupt vectors with one default handler. DOS replaces INT 21h, so INT 21h still at the default means nothing is loaded yet. That also covers a loader the boot sector started (IO.SYS).

**Put back what a boot sector changes,** then re-enter INT 19h at the point where the next drive is tried, with the registers that code expects there:
- INT 1Eh: DOS boot sectors point it at their own copy of the diskette parameters;
- the stack;
- the interrupt flag;
- an EOI to both PICs;
- here also ES = 0, BX = 7C00h, DH = 0 (the read uses DH as head), and SI = the message AMI prints if that drive fails too.

**Never twice.** Mark the drive as skipped, so a second fault halts as before instead of looping.

**Reuse, don't copy, the earlier step.** Step 2's message routines are subroutines with their own labels (`int6_halt.puts`, `.hex16`, `.putc`) and strings. A later step can call them across sections. A string without a terminator in the middle (`msg_tail` is two lines) can be printed partly by count; assert the count against the bytes in the build.

**Tiny free blocks.** When no free block is large enough, split the code into subroutines, one per block, and keep each block's entry clear with a `JMP` or `CALL`. Check every block's size in the build, and the byte before it (section 8).

**Testing a boot path in Unicorn: flush its code cache.** Unicorn keeps translated code per address. A test that loads a second boot sector to 0:7C00 after the first one ran there must remove the cached translation (`uc.ctl_remove_cache(start, end)`), or the first boot sector runs again. On a real CPU this cannot happen. The symptom looked like a ROM bug: the second boot "faulted" at an address holding zeros.

## 10. Removing a module to make room (round 5a)

An AMI BIOS of this age carries its ROM Diagnostics as an option-ROM-style module (`AA 55` header) inside the system BIOS. Removing it gave 28 KB. The method:

**Know every way in.** Here there were exactly three:
- the module check `C983` (header + XOR), called twice by POST;
- two far entries through `MOV AX,n / CALL AX`: F000:0003 (the diagnostics, from the setup menu) and F000:0008 (the configuration box, end of POST);
- nothing else: the coverage disassembly (section 3.3) found no near reference.

**Keep the frame, empty the inside.** Keep the header and the entry that is still used (0008: `JMP 7000`, outside the module), turn the dead entry into a `RET`, clear the rest, and balance the module's own check with one word. POST then runs exactly as before, and the module check now protects the new code that goes into the free space. Look for a switch the BIOS already has before patching code: this setup menu hides "RUN DIAGNOSTICS" when the byte at `E058` is 0.

**Clear around the entries, not over them.** The first 5a build cleared from 0006 to the end and wiped the `JMP 7000` at 0008. The A/B POST test caught it at once (the CPU ran into zeros at F000:000A); the image check now asserts the entry bytes.

**Prove it three ways:** the coverage disassembly, an execution and read watch on the removed range during every emulated POST (only `C983` may read it, only the kept entry may run), and A/B runs against the previous ROM (POST checkpoints, screen, CMOS, vectors and BDA must be identical at INT 19h, cold and warm, colour and mono, with errors). A setup visit leaves one difference: a stack leftover below 0400h from the menu code that read `E058`. Compare the stack area separately.

## 11. A full POST emulator for a 286 board

`py/post_emu.py` is the SOYO's `BUBios/py/post_emu.py` with the 386 and OPTi parts replaced. It runs the ROM from F000:FFF0 to INT 19h in about 8 s (10 s of virtual time). What had to change for this board:

- **Memory:** 640 KB + 3072 KB (the board), everything above reads FFh up to the 286's 16 MB. AMI's sizing counts 03712 KB as on the board.
- **Chipset:** the HT12's index/data ports 1EDh/1EFh as a register file.
- **Play a 286.** Unicorn is a 386+, so the BIOS's own CPU test says 80386 or 80486. Hook the instruction after each `PUSH AX / POPF / PUSHF` in the ROM and clear bits 12-15 of the pushed FLAGS, as a 286 in real mode does. The System Configuration box then reads `80286`.
- **Play a board without a 287.** Unicorn has an FPU. Hook the ROM's `FNINIT` (skip it) and `FNSTSW AX` (AX = FFFFh, the floating bus).
- **INT 10h without an INT instruction.** AMI calls the video BIOS through the vector (`PUSHF` / `CALL FAR [0:40h]`, at `75F5`). An emulator that serves INT 10h only for the INT instruction misses those calls; serve them at the stub video ROM's handler address too. Missing them looked like a ROM bug: with a cleared CMOS, POST crashed into the diagnostics module.

**That crash was AMI's tamper check.** With an invalid CMOS, `766E` (called at checkpoints 30h, and from `9534` and `CE64`) reads row 22, columns 0-33, through INT 10h and compares it with `     (C) American Megatrends Inc.,` (stored encoded at FF97: `NOT`, `ROL 3`). On a mismatch it jumps to a bare `RET` with `PUSHA` data on the stack: a deliberate crash into a random address. The same check exists on the SOYO (`F3DB`). Any new POST screen has to keep that line on row 22 or switch the check off.

## 12. A POST screen on this BIOS (round 5b)

**Map every print first.** Run a whole POST in the emulator and log every INT 10h call with the current checkpoint and the return addresses on the stack. On this BIOS that gave a short table (DEVELOPMENT_LOG, round 5b): the copyright line (`F042`), AMI's copyright/ID block (`76D0`), the memory count (`ACD4`), three status messages, the error list, the screen clear before the configuration box, and the box itself. Each becomes one same-length hook. Nothing else in POST prints.

**Two INT 10h paths.** AMI calls the video BIOS with `INT 10h` and also through the vector (`75F5`: `PUSHF` / `CALL FAR [0:40h]`). Both reach the same handler on the board; an emulator must serve both (section 11).

**State across a protected-mode memory test.** The memory count runs after a CPU reset for every 64 KB (shutdown code 6, `ACB8` / `ACC7`), and POST clears 0:0500-7BFF at checkpoint 7Fh. Only the BDA survives the whole POST: the 16 bytes of the intra-application area 40:F0-FF hold the state (screen up, memory units, CMOS 12h at the start, the disks' state, the start time, the clock, the status text). Clear them at the end; DOS programs may use them.

**Write to the text buffer directly**, B800h or B000h by the BIOS video mode (40:49 = 7). INT 10h is used only for the cursor. A redraw then needs nothing but the state, and the check "is the screen still ours" is a comparison of the title bar in video memory: after setup or a scroll, it is not, and the end of POST redraws.

**The screen tamper check is on with a normal CMOS.** `766E` compares row 22 with AMI's copyright line whenever CMOS is invalid **or** CMOS 37h bit 1 ("Primary display: installed") is set, which is the normal case. A POST screen without that line crashes there. Switch the check off (first byte `RET`), as on the SOYO.

**IDENTIFY at checkpoint 22h and at the end of POST, without IRQ 14 trouble.** At checkpoint 22h interrupts are off and the tick counter is not running: time with the port 61h refresh toggle (15 µs). At the end of POST, AMI's INT 13h has unmasked IRQ 14 and its handler sets 40:8E, which the next INT 13h command would take as its own completion. So: the drive's interrupt off (3F6h nIEN), IRQ 14 masked in the slave PIC while the command runs, the status read at the end, 40:8E cleared, the PIC mask restored, the master selected again. Don't wait for a busy drive early: show `...` and ask once more at the end. The emulator's drive model ignores selects and commands while busy, like a real drive, so a busy master cannot answer for the slave.

**Measure the clock on a 286.** The SOYO's loop (32 x `DIV BX` + `LOOP`, run from RAM at 0:7C00 and timed by PIT channel 2) works with 286 timings: `DIV r16` 22 clocks, `LOOP` 8 plus the queue refill (2 bytes): 714 clocks per pass, 250 passes (enough for 6 MHz to stay below 65,536 PIT ticks). Snap to a standard clock within 1/16; otherwise show "about n MHz" so that a board test reports the raw reading. The emulator charges those cycle times for code at 0:7C00, so the measurement is tested at 8, 12, 16 and 20 MHz.

**Use the BIOS's own probes and printers** where they exist: the port probes at `9808` (UART IIR) and `97FC` (printer latch, with BX = 0 as AMI calls it at `960D`), the encoded-string printer `75BB` and the KBC version code of `76D0` for the BIOS ID. The screen then shows exactly what AMI would have found.

**A/B against the previous round.** The POST checkpoint sequence, the CMOS and the vectors and BDA (but the cursor, the stack's leftovers and the timer) must be identical to round 5a in every case: the screen changes what is printed, never what POST does.

## 13. A new setup on AMI's setup code (round 6a)

**Let AMI prepare and save; replace only the editing.** AMI's setup page code reads CMOS 10h-3Fh into a buffer on its stack frame (`[BP+10h..3Fh]`) and normalises it (memory sizes from POST, floppy types from the BDA, the display from INT 11h, the EMS maximum from the HT12). Its save routine (`C0A0`) writes the buffer back, fixes the checksum and restarts. The new setup jumps in where AMI's editing loop would start (`C009`) and edits the same buffer. Everything around it (what is loaded, what is saved, the restart) stays AMI's, so a save writes exactly what AMI's page would have written for the same choices.

**Trace every option's encoding from AMI's field handlers**, not from a CMOS table found elsewhere: on this BIOS the display needs two bytes (37h bit 1 and 14h bits 5-4), two floppies set 14h bits 7-6, type-47 heads above 8 set a control byte, and the EMS size also rewrites 17h/18h. AMI's value records help: each value string is followed by its code byte.

**Then prove it A/B.** Drive both setups with keys in the POST emulator (BUBios/286 on the new ROM, AMI's page with PgUp/PgDn on the previous one), save, and compare the CMOS at the restart (a hook on F000:FFF0). Choose the sets of choices so that every value of every option appears at least once, and add the cases where options depend on each other (here: the HT12 with three banks, where shadow and relocation change the EMS maximum). On this BIOS ten saves cover it.

**Leaving without saving** is AMI's menu exit (`BD4D`: cursor, `MOV SP,BP`, `RET` to POST). AMI's page runs its own calendar clock: unhook AMI's INT 1Ch/1Ah/10h hooks (`D0CF`), make sure the RTC's SET bit is clear, and set a typed date or time through INT 1Ah, so the clock never stops.

**Free CMOS bytes for new settings:** list every CMOS access in POST and every buffer offset in setup first. Here 3Eh/3Fh were unused, outside the checksum (10h-2Dh) and saved by AMI's routine anyway; a check byte (3Fh = 3Eh XOR A5h) makes a cleared or random CMOS read as the defaults.

**Boot order at the INT 19h level.** The hook replaces "try A:" (`XOR DX,DX / XOR AX,AX / INT 13h / CALL 9005`) with one `CALL`: for C: first it does what AMI's C: path does (CMOS 0Eh bit 3, the read, 55AA) and jumps to AMI's boot jump; otherwise it falls through to AMI's own A: code. The stack depth stays the same (`CALL` for `CALL`), so Step 4's skip, which unwinds that stack, still works.

**Test harness notes.** A setup reacts to keys through the keyboard controller and AMI's INT 09h/16h: press keys one at a time with virtual time in between (150 ms is plenty). Read the setup's own state (its BP frame: page, selected field) instead of guessing from the screen. Press DEL at the "Press DEL" checkpoint (74h), not at fixed times: a key during AMI's keyboard test gives `Keyboard error`. Break the ROM on purpose for each part (a wrong bit, a missing recalculation, a wrong check byte, the boot order ignored) and check that the test fails. Here two mutations first survived: one showed a real gap (a recalculation the test always triggered twice), the other an instruction that AMI's code already made redundant. A surviving mutation is worth that look either way.

## 14. Polishing after the first board test (0.6.1)

**Hide a page drawn by code you reuse.** Round 6a lets AMI's page code prepare the setup buffer, and that code also draws AMI's whole page; on a real VGA it showed for a moment before the new setup replaced it (the emulator drew it too, nobody looked). Instead of picking AMI's drawing calls out of the preparation, switch the display off right after AMI's own mode set and on again once the new page is complete. On a VGA (INT 10h AX=1A00h answers 1Ah) that is sequencer register 1 bit 5 (Screen Off); on an MDA or CGA the mode control register (3B8h / 3D8h) bit 3, from the BIOS's copy at 40:65. A mode set turns the display on again, so the switch must come after it. The emulator models both switches and logs every change together with the screen's text at that moment; the test then proves that the display goes off before anything of AMI's page is drawn and comes on only with the new page complete.

**Know how the BIOS sees DEL before promising feedback.** The SOYO's AMI sets a CMOS flag the moment DEL arrives. This 286 AMI does not: it decides once, at checkpoint 7Fh, by emptying the keyboard buffer and looking for scan code 53h. Before that:
- During the memory test it reads port 60h itself (`AC2A`, `AC3A`, `AC8E`) and throws away every key but ESC, so a DEL pressed then is simply lost. That code runs in **protected mode** (the 286 leaves it by a CPU reset through the KBC). AMI's GDT at 0:0600 has selector 18h with base 400h, the BIOS data area, so state can be kept there; the screen cannot be reached and has to wait for the real-mode hook after each block (`bu_mem`). `SMSW` tells which mode the code runs in.
- From checkpoint 73h on, the keyboard interrupt fills the buffer and the timer runs. An INT 1Ch handler can look into the buffer on every tick (head 40:1A to tail 40:1C, 40:1E-3D). It must not touch CMOS (the interrupted code may be between `OUT 70h` and `IN 71h`) nor call INT 10h; the status bar is written to video memory directly. Hook it only if the vector is still AMI's default (F000:FF53, `IRET`) and put that back at checkpoint 7Fh.
- At checkpoint 7Fh, before AMI empties the buffer, a DEL noted during the memory test is put into the buffer (5300h), so AMI's own check sends POST to setup as usual.

**Early POST-screen values that a later POST step changes must say so.** The disk rows are drawn at checkpoint 22h, but Step 3's auto-detect runs at 75h: until then a "Not installed" drive is not set up whatever the switch says. The row says what will happen ("Auto-Detect sets it up after the memory test") and is drawn again right after the auto-detect. The emulator test reads the row during the memory test, right after checkpoint 75h and at the end.
