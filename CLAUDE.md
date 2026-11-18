# Notes for AI assistants

This repository patches the AMI 286 BIOS 06/13/90 of the Octek FOX II
(Headland HT12/A, 80C286). It is the 286 sibling of the SOYO SY-019L1
project (GitHub `BitsUndBolts/SOYO_SY-019L1_504_Patch`), whose guides
and emulators are the reference for the method.

- **Start with [`README.md`](README.md)** (plan, status, stages), then
  [`docs/ROM_ANALYSIS.md`](docs/ROM_ANALYSIS.md) (every address) and
  [`docs/DEVELOPMENT_LOG.md`](docs/DEVELOPMENT_LOG.md) (what was done).
- **Record every step.** The user wants a guide like the SOYO's for this
  first 286 BIOS: add each step's work, tests and bugs to
  `docs/DEVELOPMENT_LOG.md`, and the reusable method to
  `docs/286_BIOS_MODDING_GUIDE.md`.
- **One step at a time.** Each step is tested in the emulator, then
  burned and confirmed on the board before the next one starts.
- **286 only.** All new code is assembled with `CPU 286`. Unicorn runs
  386 opcodes without complaint, so the assembler is the only guard.
- **EVEN = low bytes.** The EVEN chip holds the low byte of every word.
  Use `py/romtool.py` to join and split; it refuses a swapped pair.
- **Never change `base/`.** Builds read `base/FOXII_0613_ORIGINAL.BIN`
  (MD5 `c74e174c716add49b1b686c70d8df83c`) and check its MD5.
- **Assert, don't assume.** Builds check the original bytes at every
  patch site; `py/analyze_bios.py` checks every fact in the address map.
- **Free space starts after string terminators.** A run of 00h after text
  begins with that string's terminator (7EB9, 7F0E, DFBA, E32C stay 00h;
  see ROM_ANALYSIS section 9).
- **Two checksums.** POST checkpoint 02 needs the word sum of
  F000:8000-FFFF to be 0 (builds balance it with the word at F83E); the
  diagnostics module needs its XOR over 0000-6FFF. `py/rom_checks.py`
  runs the BIOS's own routines on the image; `build.py` runs it too.
- **POST stack budget.** With "Scratch RAM option" 1 the type-47 table
  sits at 0000:0300 under the POST stack (0030:0100): patched code that
  runs during POST must leave 160 bytes untouched below 0400h.
- **Confirmed ROMs stay reproducible.** `py/build.py 1` and `py/build.py 2`
  must rebuild the board-confirmed Step 1 and Step 2 ROMs byte for byte (they
  check the MD5); later steps add code after the earlier steps' code, never in
  front of it.
- **Tests:** `py/regress.py`, `py/boot_test.py`, `py/int6_test.py`,
  `py/autodet_test.py`, `py/bootskip_test.py`, `py/rom_checks.py`,
  `py/analyze_bios.py` (all on the newest ROM; `FOXII_ROM=` picks another).
- **Unicorn caches translated code.** A harness that writes code into
  memory (a disk read into 0:7C00) must call `ctl_remove_cache` for that
  range, or the old code runs again (see DEVELOPMENT_LOG, Step 4).
- **Code blocks.** From Step 3 on, a step's `.asm` has one NASM section per
  free block (`start=` = `vstart=` = ROM offset); `build.py` places them from
  the map file and checks that the F537 block still equals the Step 2 code
  and (Step 4 on) that Step 3's blocks equal the Step 3 build.
- The AMI ROM Diagnostics (0000-6FFF) stay until stage 3 (Step 6), which
  removes them to make room for BUBios.
- **The user wants no waiting during boot**: no pauses, no countdowns
  unless asked for.
