#!/usr/bin/env python3
"""Step 1 regression: the ECHS ROM run through the ROM's own INT 13h code.

    python3 py/regress.py        (pip install unicorn)
    FOXII_ROM=binary/FOXII_ECHS.BIN python3 py/regress.py    another ROM (default: the newest)

0. The BIOS's own integrity checks (POST checkpoint 02 word sum, the
   diagnostics XOR, two AMI tamper checks) run on the image (rom_checks.py).
1. Geometry: for each simulated drive, AH=08h must report the expected
   translated geometry (pinned: changing it makes partitions unreadable),
   DL = 1 drive, AL = sectors, CF = 0.
2. Addressing: 44 AH=02h reads per drive (corners + random) must reach
   exactly the LBA the logical CHS implies, never beyond the end of the
   disk, and return CX/DX unchanged (upper halves included).
3. A/B identity: for drives of up to 1024 cylinders the patched ROM must
   behave exactly like the original for EVERY INT 13h function 00h-19h:
   all registers, flags, BDA status bytes and the IDE command sequence.
4. POST sequence: what POST does to a disk (AH=14h, 09h, 11h, 08h, then
   AH=04h on the last sector AH=08h reported) must succeed everywhere.
5. Stack: the deepest stack use of any call, patched vs original, must
   fit the POST budget (ROM_ANALYSIS.md 4).
"""
import random, sys
from ide_harness import *

orig, patched = load_rom(ORIG_ROM), load_rom(PATCHED_ROM)
print('ROM under test:', os.path.relpath(PATCHED_ROM, ROOT))

GEOMETRIES = {                         # physical C/H/S -> AH=08h cylinders, heads
    (980, 16, 32):   (979, 16),        # 256 MB CF class: no translation
    (1024, 16, 63):  (1023, 16),       # 504 MB: the old limit, no translation
    (1986, 16, 63):  (992, 32),        # 1 GB CF
    (2100, 16, 63):  (524, 64),
    (3875, 16, 63):  (967, 64),        # 2 GB CF (confirmed on the SOYO)
    (7773, 16, 63):  (970, 128),       # 4 GB CF
    (8912, 15, 63):  (556, 240),       # WD Caviar 24300 (confirmed on the SOYO)
    (15506, 16, 63): (971, 255),
    (16000, 16, 63): (1002, 255),      # 8 GB CF (confirmed on the SOYO)
    (16383, 16, 63): (1024, 255),      # largest ATA CHS geometry (clamped)
}
HI = 0x55550000
POST_BUDGET = 160                      # bytes of stack below 0400h (type-47 table at 0300h-035Fh)
SOYO_CONFIRMED = 96                    # the SOYO's ECHS ROM used 96 bytes the same way, fine on hardware
fails = 0

def decode_08(r):
    cx = int(r['ecx'], 16) & 0xFFFF; dx = int(r['edx'], 16) & 0xFFFF
    return (cx >> 8) | ((cx & 0xC0) << 2), (dx >> 8) + 1, cx & 0x3F, dx & 0xFF

def chs(c, h, s): return ((c & 0xFF) << 8) | ((c >> 8) << 6) | s, (h << 8) | 0x80

def report(name, problems):
    global fails
    print(('OK   ' if not problems else 'FAIL ') + name + ('' if not problems else '  ' + '; '.join(problems)))
    fails += bool(problems)

from rom_checks import run_checks
print('0. The BIOS\'s own integrity checks')
report('checksums and tamper checks as the BIOS runs them', [] if run_checks(patched) else ['the BIOS would reject this ROM'])

print('\n1-2. Geometry and addressing')
deepest = {'orig': 0, 'patched': 0}
for (C, H, S), (ec, eh) in GEOMETRIES.items():
    e = Emu(patched, C, H, S)
    g = e.call(0x0800, 0, 0x0080, e32=HI)
    maxc, nh, ns, dl = decode_08(g)
    al = int(g['eax'], 16) & 0xFF; cf = int(g['fl'], 16) & 1
    p = []
    if (maxc + 1, nh, ns) != (ec, eh, S): p.append('geometry %d/%d/%d, expected %d/%d/%d' % (maxc + 1, nh, ns, ec, eh, S))
    if dl != 1 or al != S or cf: p.append('DL=%d AL=%d CF=%d' % (dl, al, cf))
    random.seed(2)
    pts = [(0, 0, 1), (0, 1, 1), (maxc, nh - 1, ns)] + \
          [(random.randrange(maxc + 1), random.randrange(nh), random.randrange(1, ns + 1)) for _ in range(41)]
    bad = oob = dmg = 0
    for c, h, s in pts:
        cx, dx = chs(c, h, s)
        r = e.call(0x0201, cx, dx, e32=HI)
        deepest['patched'] = max(deepest['patched'], r['stack_depth'])
        got = r['ide'][-1][-1] if r['ide'] else None
        bad += got != (c * nh + h) * ns + s - 1
        oob += got is not None and got >= C * H * S
        dmg += int(r['edx'], 16) != (HI | dx) or int(r['ecx'], 16) != (HI | cx)
    if bad or oob or dmg: p.append('reads: wrong LBA %d, beyond end %d, register damage %d' % (bad, oob, dmg))
    gib = (maxc + 1) * nh * ns * 512 / 2**30
    report('%5d/%2d/%d -> %4d/%3d/%d  %5.2f GiB  %d reads' % (C, H, S, maxc + 1, nh, ns, gib, len(pts)), p)

print('\n3. A/B identity with the original ROM (drives <= 1024 cylinders)')
KEYS = ('eax', 'ebx', 'ecx', 'edx', 'esi', 'edi', 'ebp', 'esp', 'es', 'ds', 'fl', 'bda74', 'ide')
for (C, H, S) in [g for g in GEOMETRIES if g[0] <= 1024]:
    p = []
    random.seed(7)
    cases = []
    for ah in range(0x1A):
        for _ in range(6):
            c = random.randrange(C); h = random.randrange(H); s = random.randrange(1, S + 1)
            cx, dx = chs(c, h, s)
            cases.append(((ah << 8) | random.randrange(1, 4), cx, dx))
    cases += [(0x0201, *chs(C - 1, H - 1, S)), (0x0401, *chs(C - 2, H - 1, S)), (0x0C00, *chs(C - 1, 0, 1))]
    for ax, cx, dx in cases:
        ro = Emu(orig, C, H, S).call(ax, cx, dx, e32=HI)
        rp = Emu(patched, C, H, S).call(ax, cx, dx, e32=HI)
        deepest['orig'] = max(deepest['orig'], ro['stack_depth'])
        deepest['patched'] = max(deepest['patched'], rp['stack_depth'])
        diff = [k for k in KEYS if ro[k] != rp[k]]
        if diff:
            p.append('AX=%04X CX=%04X DX=%04X: %s' % (ax, cx, dx, ','.join(diff)))
    report('%4d/%2d/%d  %d calls, AH=00h-19h' % (C, H, S, len(cases)), p[:4] + (['... %d more' % (len(p) - 4)] if len(p) > 4 else []))

print('\n4. POST disk sequence (AH=14h, 09h, 11h, 08h, 04h on the last sector)')
for (C, H, S) in GEOMETRIES:
    p = []
    for rom, name in ((patched, 'patched'),):
        e = Emu(rom, C, H, S)
        for ax in (0x1400, 0x0900, 0x1100):
            r = e.call(ax, 0, 0x0080)
            if int(r['fl'], 16) & 1: p.append('AH=%02Xh CF=1' % (ax >> 8))
        g = e.call(0x0800, 0, 0x0080)
        cx = int(g['ecx'], 16) & 0xFFFF; dh = (int(g['edx'], 16) >> 8) & 0xFF
        r = e.call(0x0401, cx, (dh << 8) | 0x80)
        if int(r['fl'], 16) & 1: p.append('verify last sector CF=1 AH=%s' % r['eax'])
        maxc, nh, ns, _ = decode_08(g)
        if r['ide'] and r['ide'][-1][-1] >= C * H * S: p.append('verify beyond the end of the disk')
    report('%5d/%2d/%d' % (C, H, S), p)

print('\n5. Stack (deepest use by one INT 13h call from 0030:0100)')
print('     original %d bytes, patched %d bytes, POST budget %d bytes' % (deepest['orig'], deepest['patched'], POST_BUDGET))
report('patched depth <= %d bytes (SOYO ECHS, confirmed on hardware with the same layout)' % SOYO_CONFIRMED,
       [] if deepest['patched'] <= SOYO_CONFIRMED else ['%d bytes' % deepest['patched']])

print('\nALL PASS' if not fails else '\n%d FAILED' % fails)
sys.exit(1 if fails else 0)
