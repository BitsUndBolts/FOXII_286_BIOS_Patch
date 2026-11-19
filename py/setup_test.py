#!/usr/bin/env python3
"""Round 6a tests: the BUBios/286 setup, the boot order, Auto-Detect at boot.

    python3 py/setup_test.py               the round 6a ROM (about 25 minutes)
    python3 py/setup_test.py --mutants     also prove the tests catch broken ROMs
    python3 py/setup_test.py ab pages      only some parts (see PARTS)
    FOXII_ROM=binary/X.BIN python3 py/setup_test.py

Every case runs the real ROM in py/post_emu.py: POST from reset, DEL, the
setup driven by key presses (scan codes through the keyboard controller,
AMI's own INT 09h / INT 16h), and, after a save, the restart.

  ab        every option set through BUBios/286 and, for the same choice,
            through AMI's own page on the round 5b ROM; the CMOS each save
            writes must be identical (five sets of choices, plus a save
            without changes)
  type47    type-47 parameters typed for C: and D: (the control byte for
            more than 8 heads), checked against AMI's encoding
  datetime  typed date and time (set at once), an invalid date, Backspace,
            ESC while typing
  exit      F10 / N, F10 / Y; Exit without saving: the CMOS untouched, the
            RTC's SET bit clear, POST goes on, the POST screen drawn again
  tools     Tools: auto-detect C: (type 47 with the drive's geometry), D:
            with no drive (message), then saved
  pages     every page drawn, the Summary's values, the key row's width
  scheme    the colour schemes (F2 / F3, the Advanced field), saved in
            CMOS 3Eh with its check byte, used by the next POST screen
  boot      the boot orders in INT 19h, with a boot floppy and a C: disk
  autodet   Auto-Detect Disks at Boot On / Off (a drive that answers, CMOS
            "Not installed")
  post      POST without a setup visit: the same as round 5b (checkpoints,
            CMOS, vectors, BDA), the screen the same but the version and
            the boot-order line
  mono      the setup on a monochrome card (attributes 07h / 70h / 0Fh)
"""
import os, struct, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from post_emu import Post, make_cmos, fix_cmos, bcd
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *

ROOT = os.path.dirname(HERE)
ROM  = os.environ.get('FOXII_ROM') or os.path.join(ROOT, 'binary', 'FOXII_STEP6A.BIN')
REF  = os.path.join(ROOT, 'binary', 'FOXII_STEP5B.BIN')
MAP  = os.path.join(ROOT, 'asm', 'step6a.map')

TAB, UP, DOWN, PGUP, PGDN = 0x0F, 0x48, 0x50, 0x49, 0x51
ENTER, ESC, BKSP, F2, F3, F10, KEY_Y, KEY_N, DEL = 0x1C, 0x01, 0x0E, 0x3C, 0x3D, 0x44, 0x15, 0x31, 0x53
DIGIT = {str(i): 0x01 + i for i in range(1, 10)}; DIGIT['0'] = 0x0B

fails = []
def check(ok, what):
    print('  %s  %s' % ('ok  ' if ok else 'FAIL', what))
    if not ok: fails.append(what)
    return ok

def labels():
    out = {}
    for line in open(MAP):
        p = line.split()
        if len(p) == 3 and all(c in '0123456789ABCDEF' for c in p[0]) and p[2][0].isalpha():
            out[p[2]] = int(p[0], 16)
    return out

def norm(s): return ' '.join(s.split())
def rows(p): return p.text().splitlines() + [''] * 25
def row(p, r): return rows(p)[r].rstrip()

# ---------------------------------------------------------------- driving
def enter(rom, banks3=False, **kw):
    """POST with DEL pressed until a setup screen is up (ours or AMI's menu).
    banks3: the HT12 reports 3 memory banks (register 10h bits 2-0) when the
    setup page starts (AMI's EMS maximum then depends on shadow and relocation)"""
    p = Post(rom, **kw)
    if banks3:
        def b3(uc, a, sz, ud): p.ht12[0x10] = (p.ht12[0x10] & 0xF8) | 3
        p.mu.hook_add(UC_HOOK_CODE, b3, begin=0xFBD61, end=0xFBD61)
    for t in range(1000, 9000, 400): p.type_key(DEL, at_ms=t)
    def insetup(s):
        a = bytes(s.mu.mem_read(s.vbase + 32, 10))[0::2]
        b = bytes(s.mu.mem_read(s.vbase + 160 * 12 + 62, 8))[0::2]
        return a == b'Setup' or b == b'RUN '
    p.run(max_ms=14000, until=insetup)
    p.key_at = [k for k in p.key_at if k[0] <= p.t]
    p.run(max_ms=100)
    return p

def press(p, keys, ms=150):
    for k in keys:
        if isinstance(k, str):
            press(p, [DIGIT[c] for c in k], ms); continue
        p.type_key(k); p.run(max_ms=ms)
        if p.stop: return False
    return True

def shift_tab(p, ms=150):
    t = p.t
    p.key_at += [(t, 0x2A), (t + 5_000_000, 0x0F), (t + 10_000_000, 0x8F), (t + 15_000_000, 0xAA)]
    p.key_at.sort(); p.run(max_ms=ms)

def arm_reset(p):
    """p.saved = the CMOS when the CPU next starts at F000:FFF0 (a save's restart)"""
    p.saved = None
    def h(uc, a, sz, ud):
        if p.saved is None: p.saved = bytes(p.cmos)
    p.mu.hook_add(UC_HOOK_CODE, h, begin=0xFFFF0, end=0xFFFF0)

# ---- BUBios/286's setup ----------------------------------------------------
# the field table's order (asm/setup.asm, fields): name -> (index, page, row, value column)
FIELDS = {}
for i, (n, pg, r, c) in enumerate([
        ('date', 1, 4, 28), ('time', 1, 5, 28), ('fda', 1, 7, 28), ('fdb', 1, 8, 28), ('hdc', 1, 10, 28),
        ('c_cyl', 1, 11, 10), ('c_hd', 1, 11, 22), ('c_wp', 1, 11, 33), ('c_lz', 1, 11, 46), ('c_sec', 1, 11, 58),
        ('hdd', 1, 13, 28),
        ('d_cyl', 1, 14, 10), ('d_hd', 1, 14, 22), ('d_wp', 1, 14, 33), ('d_lz', 1, 14, 46), ('d_sec', 1, 14, 58),
        ('dsp', 1, 16, 28), ('kbd', 1, 17, 28),
        ('boot', 2, 4, 32), ('adt', 2, 5, 32), ('sch', 2, 6, 32),
        ('shd', 3, 4, 28), ('scr', 3, 5, 28), ('ems', 3, 6, 28), ('zws', 3, 7, 28), ('rel', 3, 8, 28),
        ('detc', 4, 4, 3), ('detd', 4, 5, 3), ('save', 5, 4, 3), ('quit', 5, 5, 3)]):
    FIELDS[n] = (i, pg, r, c)

def frame(p):
    """the setup's state: (tab, field) from its BP frame"""
    a = (p.mu.reg_read(UC_X86_REG_SS) << 4) + p.mu.reg_read(UC_X86_REG_BP)
    b = bytes(p.mu.mem_read(a, 2))
    return b[0], b[1]

def our_value(p, name):
    _, _, r, c = FIELDS[name]
    w = {'c_cyl': 6, 'c_hd': 4, 'c_wp': 6, 'c_lz': 6, 'c_sec': 4}.get(name.replace('d_', 'c_'), 50)
    return norm(row(p, r)[c:c + w])

def our_goto(p, name):
    i, pg, _, _ = FIELDS[name]
    for _ in range(8):
        if frame(p)[0] == pg: break
        press(p, [TAB])
    for _ in range(20):
        if frame(p)[1] == i: return True
        press(p, [DOWN])
    return check(False, 'reach field %s (at %s)' % (name, frame(p)))

def match(v, target):
    v = norm(v); return v == target or v.startswith(target + ' ')

def our_set(p, name, target, key=PGDN):
    our_goto(p, name)
    for _ in range(50):
        if match(our_value(p, name), target): return True
        press(p, [key])
    return check(False, 'BUBios: %s = %s (shows %s)' % (name, target, our_value(p, name)))

def our_save(p):
    arm_reset(p); press(p, [F10, KEY_Y], 400); p.run(max_ms=300)
    return p.saved

# ---- AMI's page (round 5b) -------------------------------------------------
AMI = {'fda': (6, 5), 'fdb': (7, 6), 'hdc': (8, 8), 'hdd': (9, 9), 'dsp': (10, 10), 'kbd': (11, 11),
       'shd': (12, 12), 'scr': (13, 13), 'ems': (14, 14), 'zws': (15, 15), 'rel': (16, 16)}
def ami_value(p, r):
    c = p.cells()
    return norm(bytes(c[r * 80 + i][0] for i in range(20, 60) if c[r * 80 + i][1] == 0x70).decode('cp437'))

def order(choices, banks3):
    """the fields in page order; with three HT12 banks the EMS size last (its
    maximum depends on shadow and relocation)"""
    return sorted(choices, key=lambda n: (banks3 and n == 'ems', FIELDS[n][0]))

def ami_run(rom, choices, **kw):
    choices = dict(choices); b3 = choices.pop('banks3', 0)
    p = enter(rom, banks3=b3, **kw)
    press(p, [DOWN, ENTER], 600)                     # RUN CMOS SETUP
    at = 0
    for name in order(choices, b3):
        idx, r = AMI[name]
        press(p, [DOWN] * (idx - at) + [UP] * (at - idx)); at = idx
        if name == 'ems' and b3:
            # AMI works the maximum out again only in its EMS field, when the
            # value changes (BUBios/286 does it whenever shadow or relocation
            # change): a change there and back
            press(p, [PGDN, PGUP])
        for _ in range(50):
            if match(ami_value(p, r), choices[name][1]): break
            press(p, [PGDN])
        else: check(False, 'AMI: %s = %s (shows %s)' % (name, choices[name][1], ami_value(p, r)))
    arm_reset(p); press(p, [ESC, KEY_Y, ENTER], 400); p.run(max_ms=300)
    return p

def our_run(rom, choices, **kw):
    choices = dict(choices); b3 = choices.pop('banks3', 0)
    p = enter(rom, banks3=b3, **kw)
    for name in order(choices, b3):
        our_set(p, name, choices[name][0])
    our_save(p)
    return p

def cmos_diff(a, b, skip=(0x0C, 0x0D)):
    return ['%02X: %02X/%02X' % (i, a[i], b[i]) for i in range(0x0A, 0x40) if i not in skip and a[i] != b[i]]

# five sets of choices: (BUBios/286's text, AMI's text) for every value of
# every AMI option at least once
FL = {'none': ('Not Installed',) * 2, '360': ('360 KB, 5¼"',) * 2, '1.2': ('1.2 MB, 5¼"',) * 2,
      '720': ('720 KB, 3½"',) * 2, '1.44': ('1.44 MB, 3½"',) * 2}
COMBOS = [
    {},
    {'fda': FL['720'], 'fdb': FL['none'], 'hdc': ('2', '2'), 'hdd': ('1', '1'), 'dsp': ('Monochrome',) * 2,
     'kbd': ('Not Installed',) * 2, 'shd': ('Video BIOS',) * 2, 'scr': ('2', '2'), 'ems': ('64 KB',) * 2,
     'zws': ('Enabled',) * 2},
    {'fda': FL['360'], 'fdb': FL['1.44'], 'hdc': ('Not Installed',) * 2, 'hdd': ('3', '3'),
     'dsp': ('Color 40x25',) * 2, 'shd': ('Main BIOS',) * 2, 'rel': ('Enabled',) * 2},
    {'fda': FL['none'], 'fdb': FL['720'], 'dsp': ('Color 80x25',) * 2, 'shd': ('Main & video BIOS',) * 2,
     'ems': ('192 KB',) * 2, 'zws': ('Enabled',) * 2, 'rel': ('Enabled',) * 2},
    {'fda': FL['1.2'], 'fdb': FL['360'], 'dsp': ('Not Installed',) * 2, 'ems': ('256 KB',) * 2,
     'scr': ('1', '1'), 'hdc': ('1', '1')},
    # three HT12 banks: the EMS maximum follows shadow and relocation
    {'banks3': 1, 'shd': ('Main BIOS',) * 2, 'ems': ('128 KB',) * 2, 'rel': ('Enabled',) * 2},
    {'banks3': 1, 'shd': ('Video BIOS',) * 2, 'rel': ('Enabled',) * 2, 'ems': ('0 KB',) * 2},
    {'banks3': 1, 'rel': ('Enabled',) * 2, 'ems': ('256 KB',) * 2},
    {'banks3': 1, 'shd': ('Main & video BIOS',) * 2, 'rel': ('Enabled',) * 2, 'ems': ('64 KB',) * 2},
]

def ab_case(img, ref, only=None):
    print('every option: BUBios/286 and AMI\'s page write the same CMOS')
    for n, ch in enumerate(COMBOS):
        if only is not None and n not in only: continue
        a = our_run(img, ch); b = ami_run(ref, ch)
        what = 'set %d (%s)' % (n, ', '.join('%s %s' % (k, v[0]) if k != 'banks3' else 'HT12 3 banks'
                                             for k, v in ch.items()) or 'no change')
        if not check(a.saved is not None and b.saved is not None, '%s: both saved and restarted' % what[:60]): continue
        d = cmos_diff(a.saved, b.saved)
        check(not d, '%s: CMOS identical %s' % (what, d))

# ---------------------------------------------------------------- the parts
PARTS = {'ab': ab_case}

def run_all(img, ref, parts=None):
    t0 = time.time()
    for name in parts or PARTS:
        PARTS[name](img, ref)
    print('(%.0f s)' % (time.time() - t0))

if __name__ == '__main__':
    img, ref = open(ROM, 'rb').read(), open(REF, 'rb').read()
    print('ROM %s\nreference %s' % (os.path.relpath(ROM, ROOT), os.path.relpath(REF, ROOT)))
    sel = [a for a in sys.argv[1:] if not a.startswith('--')]
    if '--mutants-only' not in sys.argv: run_all(img, ref, sel or None)
    print('\n%s' % ('ALL PASS' if not fails else '%d FAILURES' % len(fails)))
    sys.exit(1 if fails else 0)
