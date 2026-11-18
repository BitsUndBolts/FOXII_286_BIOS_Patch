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
- **Two checksums.** POST checkpoint 02 needs the word sum of
  F000:8000-FFFF to be 0 (builds balance it with the word at F83E); the
  diagnostics module needs its XOR over 0000-6FFF. `py/rom_checks.py`
  runs the BIOS's own routines on the image; `build.py` runs it too.
- **POST stack budget.** With "Scratch RAM option" 1 the type-47 table
  sits at 0000:0300 under the POST stack (0030:0100): patched code that
  runs during POST must leave 160 bytes untouched below 0400h.
- The AMI ROM Diagnostics (0000-6FFF) stay until stage 3, which removes
  them to make room for BUBios.
