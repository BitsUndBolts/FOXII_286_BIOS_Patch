#!/usr/bin/env python3
"""Round 5a tests: the AMI ROM Diagnostics removed, nothing else changed.

    python3 py/nodiag_test.py              the round 5a ROM (about 3 minutes)
    python3 py/nodiag_test.py --mutants    also prove the tests catch broken ROMs
    FOXII_ROM=binary/X.BIN python3 py/nodiag_test.py

Runs the whole POST in py/post_emu.py, from the reset vector to INT 19h,
on the round 5a ROM and on the board-confirmed Step 4 ROM (the reference),
with identical inputs, and compares:
  - the POST checkpoint sequence (port 80h), the screen (characters and
    attributes), the CMOS, and memory 0000-04FF (interrupt vectors, BDA)
    when INT 19h is reached,
for a cold and a warm boot, colour and monochrome, no hard disk, and a
cleared CMOS (POST shows its errors and waits for F1: the test presses it).
Each 5a run also watches the old module range F000:0003-6FFF: no instruction
may run there except the JMP 7000 at 0008, and only C983 (the module's own
checksum) may read it.

Then: the setup menu (DEL during POST) lists EXIT FOR BOOT and RUN CMOS
SETUP and no RUN DIAGNOSTICS; RUN CMOS SETUP shows the same page as on Step
4, and EXIT FOR BOOT goes on to INT 19h. The image itself: header and
entries, 0006-6FFD all 00h, the XOR and word sums, differences from Step 4
only where 5a changes something, the ROM's own checks (rom_checks.py), and
the coverage disassembly (no reference into 0000-6FFF).
"""
import os, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from post_emu import Post, make_cmos

ROOT = os.path.dirname(HERE)
ROM  = os.environ.get('FOXII_ROM') or os.path.join(ROOT, 'binary', 'FOXII_STEP5A.BIN')
REF  = os.path.join(ROOT, 'binary', 'FOXII_STEP4.BIN')
DEL, UP, DOWN, ENTER, ESC, F1, KEY_N = 0x53, 0x48, 0x50, 0x1C, 0x01, 0x3B, 0x31

fails = []
def check(ok, what):
    print('  %s  %s' % ('ok  ' if ok else 'FAIL', what))
    if not ok: fails.append(what)
    return ok

def wsum(img): return sum(struct.unpack_from('<16384H', img, 0x8000)) & 0xFFFF
def dxor(img):
    x = 0
    for v in struct.unpack_from('<14336H', img, 0): x ^= v
    return x

def post(rom, watch=False, keys=(), warm=False, max_ms=30000, **kw):
    p = Post(rom, **kw)
    if watch: p.watch(0x0003, 0x7000, allow_exec=(0x0008,))
    for at, k in keys: p.type_key(k, at_ms=at)
    p.run(max_ms=max_ms)
    if warm and p.stop == 'int19':
        p.warm_boot(); p.run(max_ms=max_ms)
    return p

def module_watch(p, what):
    check(not p.exec_in, '%s: nothing executed in 0003-6FFF but the JMP 7000 at 0008%s'
          % (what, '' if not p.exec_in else ' (%s ...)' % p.exec_in[:3]))
    readers = sorted(p.read_by)
    check(set(readers) <= {0xC985, 0xC991}, '%s: only C983 reads 0003-6FFF (readers %s)'
          % (what, ' '.join('%04X' % r for r in readers) or 'none'))

def image_checks(img, ref):
    print('the image')
    check(img[0:3] == b'\xaa\x55\x40', 'header AA 55 40 kept')
    check(img[3:6] == b'\xc3\x90\x90', 'F000:0003 = RET (the old diagnostics entry)')
    check(img[8:11] == bytes.fromhex('e9f56f'), 'F000:0008 = JMP 7000 (the configuration box)')
    check(not any(img[6:8]) and not any(img[0xB:0x6FFE]), '0006-0007 and 000B-6FFD are 00h')
    check(img[0xE058] == 0, 'E058 = 00h (no RUN DIAGNOSTICS)')
    check(dxor(img) == 0 and wsum(img) == 0, 'XOR of 0000-6FFF = 0, word sum of 8000-FFFF = 0')
    diff = [o for o in range(0x10000) if img[o] != ref[o]]
    outside = [o for o in diff if not (3 <= o < 0x7000 or o == 0xE058 or o in (0xF83E, 0xF83F))]
    check(not outside, 'differs from Step 4 only in 0003-6FFF, E058 and the checksum word F83E'
          + ('' if not outside else ' (also %s)' % ' '.join('%04X' % o for o in outside[:8])))
    from rom_checks import run_checks
    check(run_checks(img), "the ROM's own integrity checks (rom_checks.py)")
    out = subprocess.run([sys.executable, os.path.join(HERE, 'coverage_disasm.py'), ROM_PATH],
                         capture_output=True, text=True).stdout
    into = [l for l in out.splitlines() if 'into the diagnostics module' in l]
    check(into == ['  8341: call 46CF  -> into the diagnostics module (check by hand)'],
          'coverage disassembly: no reference into 0000-6FFF (only the known table artifact at 8341)')

CASES = [('cold boot, the board (C: 1986/16/63, VGA)', {}),
         ('warm boot (40:72 = 1234h)', dict(warm=True)),
         ('monochrome adapter', dict(video='mono', cmos=make_cmos(video='mono'))),
         ('no hard disk', dict(drive=None, cmos=make_cmos(drive=None))),
         ('master + slave (2 GB card as D:)', dict(slave=(3875, 16, 63), cmos=make_cmos(drive_d=(3875, 16, 63))))]

def ab_checks(img, ref):
    for name, kw in CASES:
        print(name)
        t0 = time.time()
        a = post(img, watch=True, **kw); b = post(ref, **kw)
        sa, sb = a.snapshot(), b.snapshot()
        check(sa['stop'] == sb['stop'] == 'int19', 'reaches INT 19h (5a: %s, Step 4: %s)' % (sa['stop'], sb['stop']))
        check(sa['p80'] == sb['p80'], 'same POST checkpoint sequence (%d codes)' % len(sa['p80']))
        check(sa['cells'] == sb['cells'], 'same screen, characters and attributes')
        check(sa['cmos'] == sb['cmos'], 'same CMOS')
        check(sa['low'] == sb['low'], 'same interrupt vectors and BDA (0000-04FF)')
        module_watch(a, name)
        print('     (%.0f s)' % (time.time() - t0))

def cleared_cmos_checks(img, ref):
    print('cleared CMOS: AMI\'s errors, F1 -> setup menu, EXIT FOR BOOT')
    a = Post(img, cmos=bytes(128)); a.watch(0x0003, 0x7000, allow_exec=(0x0008,)); b = Post(ref, cmos=bytes(128))
    for p in (a, b): p.run(max_ms=15000)
    check('Press <F1> to RESUME' in a.text() and 'CMOS system options not set' in a.text(),
          'errors shown, waiting for F1')
    check(a.cells() == b.cells(), 'the same screen as on Step 4')
    check('     (C) American Megatrends Inc.,' == a.text().splitlines()[22],
          "row 22 holds AMI's copyright line (the tamper check at 766E reads it with an invalid CMOS)")
    for p in (a, b): p.type_key(F1); p.run(max_ms=3000)
    check(menu(a) == ['EXIT FOR BOOT', 'RUN CMOS SETUP'], 'F1: setup menu %s' % ' / '.join(menu(a)))
    for p in (a, b): p.type_key(ENTER); p.run(max_ms=20000)
    check(a.stop == b.stop == 'int19', 'EXIT FOR BOOT: INT 19h (5a: %s, Step 4: %s)' % (a.stop, b.stop))
    sa, sb = a.snapshot(), b.snapshot()
    stk = lambda m: m[:0x360] + m[0x400:]      # without the stack's leftovers (0360-03FF)
    diff = [o for o in range(0x500) if sa['low'][o] != sb['low'][o]]
    check(sa['cells'] == sb['cells'] and sa['p80'] == sb['p80'] and sa['cmos'] == sb['cmos']
          and stk(sa['low']) == stk(sb['low']), 'then the same screen, checkpoints, CMOS, vectors and BDA as Step 4')
    check(all(0x360 <= o < 0x400 for o in diff),
          'memory 0000-04FF differs only in stack leftovers below 0400 (%s): the menu code saw E058 = 00h'
          % ' '.join('%04X' % o for o in diff))
    module_watch(a, 'cleared CMOS')

def menu(p):
    t = p.text()
    return [l.strip() for l in t.splitlines() if l.strip()]

def setup_checks(img, ref):
    print('setup menu (DEL during POST)')
    keys = [(t, DEL) for t in range(1000, 7000, 500)]
    a = post(img, watch=True, keys=keys, max_ms=12000); b = post(ref, keys=keys, max_ms=12000)
    check(menu(a) == ['EXIT FOR BOOT', 'RUN CMOS SETUP'], 'menu: %s' % ' / '.join(menu(a)))
    check(menu(b) == ['EXIT FOR BOOT', 'RUN CMOS SETUP', 'RUN DIAGNOSTICS'], 'Step 4 menu: %s' % ' / '.join(menu(b)))
    cells = a.cells()
    check(all(cells[11 * 80 + c][1] == 0x70 for c in range(31, 44)), 'EXIT FOR BOOT highlighted')
    for p in (a, b):
        p.type_key(DOWN); p.run(max_ms=800); p.type_key(ENTER); p.run(max_ms=1500)
    check('CMOS SETUP (C) Copyright 1985-1990' in a.text(), 'RUN CMOS SETUP opens the setup page')
    check(a.cells() == b.cells(), 'the setup page is the same as on Step 4')
    for p in (a, b):
        p.type_key(ESC); p.run(max_ms=1500)
    check('Write data into CMOS and exit (Y/N)?' in a.text() and a.cells() == b.cells(),
          'ESC: AMI asks "Write data into CMOS and exit (Y/N)?", as on Step 4')
    for p in (a, b):
        p.type_key(KEY_N); p.run(max_ms=800); p.type_key(ENTER); p.run(max_ms=1500)
    check('Write data' not in a.text() and a.cells() == b.cells(), 'N, Enter: back to the setup page, as on Step 4')
    r0 = a.resets
    for p in (a, b):
        p.type_key(ESC); p.run(max_ms=1000); p.type_key(0x15); p.run(max_ms=800)   # Y
        p.type_key(ENTER); p.run(max_ms=30000)
    check(a.stop == 'int19' and a.resets > r0, 'ESC, Y, Enter: CMOS written, full POST, INT 19h (%s)' % a.stop)
    check(a.cells() == b.cells() and [c for c, _ in a.p80] == [c for c, _ in b.p80] and a.cmos == b.cmos,
          'the new POST as on Step 4 (screen, checkpoints, CMOS)')
    module_watch(a, 'setup')
    print('setup menu: EXIT FOR BOOT')
    a = post(img, watch=True, keys=keys, max_ms=12000); b = post(ref, keys=keys, max_ms=12000)
    for p in (a, b):
        p.type_key(ENTER); p.run(max_ms=20000)
    check(a.stop == b.stop == 'int19', 'EXIT FOR BOOT: on to INT 19h (5a: %s, Step 4: %s)' % (a.stop, b.stop))
    check(a.cells() == b.cells() and [c for c, _ in a.p80] == [c for c, _ in b.p80] and a.cmos == b.cmos,
          'the rest of POST as on Step 4 (screen, checkpoints, CMOS)')
    module_watch(a, 'setup, exit for boot')

def mutants(img):
    """Broken ROMs: each must fail at least one check."""
    def fixsum(m):
        struct.pack_into('<H', m, 0xF83E, 0); struct.pack_into('<H', m, 0xF83E, (-wsum(m)) & 0xFFFF)
    def fixxor(m):
        struct.pack_into('<H', m, 0x6FFE, 0); struct.pack_into('<H', m, 0x6FFE, dxor(m))
    out = []
    m = bytearray(img); struct.pack_into('<H', m, 0x6FFE, 0); out.append(('XOR word left out', m, 'post'))
    m = bytearray(img); m[0xE058] = 0xFF; fixsum(m); out.append(('E058 left FFh', m, 'setup'))
    m = bytearray(img); m[8:11] = b'\0\0\0'; fixxor(m); out.append(('JMP 7000 at 0008 cleared', m, 'post'))
    m = bytearray(img); m[0:3] = b'\0\0\0'; fixxor(m); out.append(('header cleared', m, 'post'))
    m = bytearray(img); m[0x5000] = 0x90; m[0x5001] = 0x90; fixxor(m); out.append(('two stray bytes in 0006-6FFD', m, 'image'))
    return out

def run_all(img, ref, parts=('image', 'post', 'setup')):
    if 'image' in parts: image_checks(img, ref)
    if 'post' in parts: ab_checks(img, ref)
    if 'setup' in parts: setup_checks(img, ref)
    if 'post' in parts: cleared_cmos_checks(img, ref)

if __name__ == '__main__':
    ROM_PATH = ROM
    img, ref = open(ROM, 'rb').read(), open(REF, 'rb').read()
    print('ROM %s\nreference %s' % (os.path.relpath(ROM, ROOT), os.path.relpath(REF, ROOT)))
    if '--mutants-only' not in sys.argv: run_all(img, ref)
    n = len(fails)
    if '--mutants' in sys.argv or '--mutants-only' in sys.argv:
        print('\nmutations (each must fail)')
        import tempfile
        bad = 0
        for name, m, part in mutants(img):
            fails.clear()
            with tempfile.NamedTemporaryFile(suffix='.BIN', delete=False) as f: f.write(m)
            ROM_PATH = f.name
            out = sys.stdout; sys.stdout = open(os.devnull, 'w')
            try: run_all(bytes(m), ref, parts=(part,))
            except Exception as e: fails.append('exception %s' % e)
            finally: sys.stdout.close(); sys.stdout = out
            os.unlink(f.name)
            print('  %s  %-32s %d failures' % ('ok  ' if fails else 'FAIL', name, len(fails)))
            if not fails: bad += 1
        n += bad
    print('\n%s' % ('ALL PASS' if n == 0 else '%d FAILURES' % n))
    sys.exit(1 if n else 0)
