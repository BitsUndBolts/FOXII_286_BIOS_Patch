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
- **Confirmed ROMs stay reproducible.** `py/build.py 1` to `py/build.py 4`
  must rebuild the board-confirmed ROMs of Steps 1-4 byte for byte (they
  check the MD5); later steps add code after the earlier steps' code, never in
  front of it.
- **Tests:** `py/tools_test.py` (6b), `py/setup_test.py` (6a), `py/regress.py`, `py/boot_test.py`, `py/int6_test.py`,
  `py/autodet_test.py`, `py/bootskip_test.py`, `py/rom_checks.py`,
  `py/analyze_bios.py` (all on the newest ROM; `FOXII_ROM=` picks another).
- **Unicorn caches translated code.** A harness that writes code into
  memory (a disk read into 0:7C00) must call `ctl_remove_cache` for that
  range, or the old code runs again (see DEVELOPMENT_LOG, Step 4).
- **Code blocks.** From Step 3 on, a step's `.asm` has one NASM section per
  free block (`start=` = `vstart=` = ROM offset); `build.py` places them from
  the map file and checks that the F537 block still equals the Step 2 code
  and (Step 4 on) that Step 3's blocks equal the Step 3 build.
- **Stages 2 and 3 follow `docs/PLAN_STAGES_2_3.md`:** rounds 5a (remove the
  AMI ROM Diagnostics), 5b (POST screen), 6a (setup), 6b (tools), each on
  its own branch built on the previous one. `main` holds only
  board-confirmed ROMs; a round is merged after Alex confirms it.
- **0.7.3** (works on the board, 2026-11-21) is in `main` on top of 0.7.2 (Alex: "just one change", no branch): with Auto-Detect On
  every drive that answers gets its own geometry (`autodet_all` / `same47` in setup.asm; Step 3's
  autodet.asm untouched), "Auto" whenever On, the memory test's key line, and DEL at AMI's F1 prompt
  (`bu_f1wait`, hook 9754; 40:69 is AMI's setup flag: 5555h DEL, AAAAh errors). Tests: `tools_test.py v073`.
- **Round 6b (0.7.2)** is in `main` (squash of branch `stage3-6b-tools`; 0.7.1 worked on the board):
  `asm/tools.asm`, `ROUND6B` in post.asm / setup.asm, HT12UMB.SYS in the
  fixed slot F000:6000-67FF (tag 5FF0; `extra/HT12UMB.SYS`, MD5 checked by
  build.py; never move it: the DEBUG recipe depends on it). Code must end
  below 5FF0; 6800-6FFD is a block of its own. Tests: `py/tools_test.py`.
- **Setup's stack wraps** to 0:FFxx-102FF (0030:FCxx). Tool buffers are at
  0:1000-90FF, the base memory test starts at 68 KB. Never use 0:F000-
  102FF while setup runs.
- **The user wants no waiting during boot**: no pauses, no countdowns
  unless asked for.
