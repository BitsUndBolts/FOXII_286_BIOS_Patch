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
    # to the "Press DEL" window (checkpoint 74h), then DEL as a user would
    p.run(max_ms=40000, until=lambda q: q.p80 and q.p80[-1][0] == 0x74)
    def insetup(s):
        a = bytes(s.mu.mem_read(s.vbase + 32, 10))[0::2]
        b = bytes(s.mu.mem_read(s.vbase + 160 * 12 + 62, 8))[0::2]
        return a == b'Setup' or b == b'RUN '
    for _ in range(20):
        p.type_key(DEL); p.run(max_ms=300, until=insetup)
        if p.stop == 'until': break
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

def start_cmos(choices):
    c38 = choices.pop('cmos38', None)
    return {} if c38 is None else {'cmos': make_cmos(extra={0x38: c38})}

def ami_run(rom, choices, **kw):
    choices = dict(choices); b3 = choices.pop('banks3', 0); kw.update(start_cmos(choices))
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
    choices = dict(choices); b3 = choices.pop('banks3', 0); kw.update(start_cmos(choices))
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
    # relocation already on: only the shadow changes the EMS maximum
    {'banks3': 1, 'cmos38': 0x80, 'shd': ('Main & video BIOS',) * 2, 'ems': ('0 KB',) * 2},
]

def ab_case(img, ref, only=None):
    print('every option: BUBios/286 and AMI\'s page write the same CMOS')
    for n, ch in enumerate(COMBOS):
        if only is not None and n not in only: continue
        a = our_run(img, ch); b = ami_run(ref, ch)
        what = 'set %d (%s)' % (n, ', '.join('HT12 3 banks' if k == 'banks3' else 'relocation on at the start'
                                             if k == 'cmos38' else '%s %s' % (k, v[0]) for k, v in ch.items()) or 'no change')
        if not check(a.saved is not None and b.saved is not None, '%s: both saved and restarted' % what[:60]): continue
        d = cmos_diff(a.saved, b.saved)
        check(not d, '%s: CMOS identical %s' % (what, d))


def saved_ok(c):
    """the checksum over 10h-2Dh in 2Eh/2Fh is right"""
    s = sum(c[0x10:0x2E]) & 0xFFFF
    return c[0x2E] == s >> 8 and c[0x2F] == s & 0xFF

def type47_case(img, ref):
    print('type 47: the parameters typed')
    p = enter(img)
    our_goto(p, 'c_cyl'); press(p, ['10'])
    check(our_value(p, 'c_cyl') == '10_', 'typing shows the digits so far (%s)' % our_value(p, 'c_cyl'))
    press(p, ['24', ENTER])
    for f, v in (('c_hd', '9'), ('c_wp', '300'), ('c_lz', '1023'), ('c_sec', '32')):
        our_goto(p, f); press(p, [v, ENTER])
    check(norm(row(p, 11)) == 'Cyln 1024 Head 9 WPcom 300 LZone 1023 Sect 32 144 MB', 'C: %s' % norm(row(p, 11)))
    for f, v, why in (('c_sec', '64', 'sectors 64'), ('c_sec', '0', 'sectors 0'), ('c_hd', '17', 'heads 17'),
                      ('c_hd', '0', 'heads 0'), ('c_cyl', '70000', 'cylinders 70000'), ('c_cyl', '0', 'cylinders 0')):
        our_goto(p, f); press(p, [v] + ([ENTER] if len(v) < {'c_sec': 2, 'c_hd': 2, 'c_cyl': 5}[f] else []))
        check(norm(row(p, 11)).startswith('Cyln 1024 Head 9 WPcom 300 LZone 1023 Sect 32') and
              row(p, 22).strip() == 'Not taken: out of range.', '%s not taken, said so' % why)
    our_goto(p, 'c_sec'); press(p, ['1', ENTER, PGUP])
    check(our_value(p, 'c_sec') == '1', 'PgUp stops at 1 sector')
    press(p, ['63', PGDN])
    check(our_value(p, 'c_sec') == '63', 'PgDn stops at 63 sectors')
    press(p, ['32', ENTER])
    press(p, [DOWN]); check(not row(p, 22).startswith('Not taken'), 'the message goes with the next key')
    # ESC and Backspace while typing
    our_goto(p, 'c_lz'); press(p, ['7', BKSP, '8', ESC])
    check(our_value(p, 'c_lz') == '1023' and frame(p)[0] == 1, 'ESC while typing: the value kept, still on the page')
    our_goto(p, 'c_lz'); press(p, ['9', BKSP, '1022', ENTER])
    check(our_value(p, 'c_lz') == '1022', 'Backspace while typing (1022)')
    # D: from Not Installed to 47 (PgUp, as AMI's page), its parameters typed
    our_set(p, 'hdd', '47', key=PGUP)
    check(norm(row(p, 14)) == 'Cyln 0 Head 0 WPcom 0 LZone 0 Sect 0 0 MB', 'D: type 47 starts empty, as on AMI\'s page')
    for f, v in (('d_cyl', '500'), ('d_hd', '4'), ('d_wp', '0'), ('d_lz', '500'), ('d_sec', '17')):
        our_goto(p, f); press(p, [v] + ([ENTER] if len(v) < 5 else []))
    c = our_save(p)
    if not check(c is not None, 'saved and restarted'): return
    check(c[0x12] == 0xFF and c[0x19] == 47 and c[0x1A] == 47, 'CMOS 12h = FFh, 19h = 1Ah = 47')
    check(c[0x1B:0x24] == struct.pack('<HBHBHB', 1024, 9, 300, 0x08, 1022, 32),
          'C: 1Bh-23h %s (control 08h: more than 8 heads)' % c[0x1B:0x24].hex())
    check(c[0x24:0x2D] == struct.pack('<HBHBHB', 500, 4, 0, 0x00, 500, 17), 'D: 24h-2Ch %s' % c[0x24:0x2D].hex())
    check(saved_ok(c), 'checksum 2Eh/2Fh right')
    # AMI's own encoding for the same drive (make_cmos follows AMI's field code)
    ami = make_cmos(drive=(1024, 9, 63))
    check(ami[0x20] == 0x08 == c[0x20], 'control byte as AMI writes it for 9 heads')

def rtc(p, *idx): return [p.cmos[i] for i in idx]

def datetime_case(img, ref):
    print('date and time, typed')
    p = enter(img)
    check(not (p.cmos[0x0B] & 0x80), 'the RTC runs in the setup: 0Bh SET bit clear')
    our_goto(p, 'date'); press(p, ['1231'])
    check(our_value(p, 'date') == '12/31/____', 'typing shows a mask (%s)' % our_value(p, 'date'))
    press(p, ['2025'])
    check(rtc(p, 9, 8, 7, 0x32) == [0x25, 0x12, 0x31, 0x20] and our_value(p, 'date') == '12/31/2025',
          'date 12/31/2025 set at once (CMOS 09/08/07/32 = %s)' % ' '.join('%02X' % v for v in rtc(p, 9, 8, 7, 0x32)))
    press(p, ['02292024'])
    check(rtc(p, 9, 8, 7, 0x32) == [0x24, 0x02, 0x29, 0x20], '02/29/2024 (a leap year) taken')
    for bad in ('02292025', '13012025', '04312025', '01011979', '01012100', '00102025'):
        press(p, [bad])
        check(rtc(p, 9, 8, 7) == [0x24, 0x02, 0x29] and row(p, 22).strip().startswith('Not taken'),
              '%s/%s/%s not taken, said so' % (bad[:2], bad[2:4], bad[4:]))
    press(p, ['0101', ENTER])
    check(rtc(p, 9, 8, 7) == [0x24, 0x02, 0x29], 'a date half typed, then Enter: not taken')
    press(p, ['0', '1', BKSP, '7', '04', '1999'])
    check(rtc(p, 9, 8, 7, 0x32) == [0x99, 0x07, 0x04, 0x19], 'Backspace while typing: 07/04/1999')
    press(p, ['1111', ESC])
    check(rtc(p, 9, 8, 7) == [0x99, 0x07, 0x04] and frame(p)[0] == 1 and our_value(p, 'date') == '07/04/1999',
          'ESC while typing: the date kept, still on the page')
    our_goto(p, 'time'); press(p, ['235958'])
    check(rtc(p, 4, 2, 0) == [0x23, 0x59, 0x58], 'time 23:59:58 set at once')
    for bad in ('240000', '236000', '235960'):
        press(p, [bad])
        check(rtc(p, 4, 2, 0) == [0x23, 0x59, 0x58] and row(p, 22).strip().startswith('Not taken'),
              '%s:%s:%s not taken' % (bad[:2], bad[2:4], bad[4:]))
    check(not (p.cmos[0x0B] & 0x80), 'the RTC still runs after setting date and time')

def exit_case(img, ref):
    print('saving and leaving')
    p = enter(img); c0 = bytes(p.cmos); arm_reset(p)
    check(frame(p)[0] == 0 and rows(p)[1].strip().startswith('Summary'), 'DEL: straight to the Summary page')
    press(p, [F10]); check('Save settings and exit (Y/N)?' in row(p, 24), 'F10 asks: %s' % row(p, 24).strip())
    press(p, [KEY_N]); check(p.saved is None and 'Tab:Page' in row(p, 24), 'N: back in the setup')
    press(p, [TAB, ESC]); check(frame(p)[0] == 5, 'ESC: to the Exit page')
    press(p, [ESC]); check(frame(p)[0] == 0, 'ESC on the Exit page: to the Summary')
    shift_tab(p); check(frame(p)[0] == 5, 'Shift-Tab: Summary -> Exit')
    our_set(p, 'fda', '720 KB, 3½"'); our_set(p, 'zws', 'Enabled')
    our_goto(p, 'quit'); press(p, [ENTER])
    check('Exit without saving (Y/N)?' in row(p, 24), 'Exit without saving asks')
    press(p, [KEY_Y], 300)
    if p.stop is None: p.run(max_ms=30000)
    check(p.saved is None, 'no restart')
    check(p.stop == 'int19', 'POST goes on to INT 19h (%s)' % p.stop)
    check(p.cmos[0x10:0x40] == c0[0x10:0x40], 'CMOS 10h-3Fh untouched')
    check(not (p.cmos[0x0B] & 0x80), 'RTC SET bit clear')
    check(row(p, 0).startswith(' BUBios/286 0.6') and 'Power-On Self Test' in row(p, 0)
          and row(p, 10).strip() == 'Disk C:  CF  SanDisk SDCFJ-1024' and row(p, 9).strip().startswith('Floppy A:    1.44 MB'),
          'the POST screen drawn again, with the old values')
    check(row(p, 17).strip().startswith('Booting: A: then C:'), 'status: %s' % row(p, 17).strip()[:30])
    print('F10 / Y: saved, the PC restarts')
    p = enter(img); our_set(p, 'fda', '720 KB, 3½"'); c = our_save(p)
    check(c is not None and c[0x10] >> 4 == 3, 'saved (A: 720 KB) and restarted')
    p.run(max_ms=30000)
    check(p.stop == 'int19' and row(p, 9).strip().startswith('Floppy A:    720 KB'),
          'POST again, to INT 19h, the new value on the POST screen')

def tools_case(img, ref):
    print('Tools: auto-detect')
    p = enter(img, cmos=make_cmos(drive=2))
    check(norm(row(p, 7)) == 'Chipset Headland HT12/A Hard disk C: 20 MB [2]', 'Summary: %s' % norm(row(p, 7)))
    our_goto(p, 'detc'); press(p, [ENTER], 600)
    check(row(p, 22).strip().startswith('Found: written as type 47'), 'C: found: %s' % row(p, 22).strip()[:50])
    our_goto(p, 'detd'); press(p, [ENTER], 600)
    check(row(p, 22).strip() == 'No drive answered.', 'D: no drive: %s' % row(p, 22).strip())
    our_goto(p, 'hdc')
    check(our_value(p, 'hdc') == '47 (user type)' and norm(row(p, 11)).startswith('Cyln 1986 Head 16 WPcom 65535 LZone 1986 Sect 63'),
          'Standard: C: %s / %s' % (our_value(p, 'hdc'), norm(row(p, 11))))
    c = our_save(p)
    check(c is not None and c[0x12] >> 4 == 0xF and c[0x19] == 47 and
          c[0x1B:0x24] == struct.pack('<HBHBHB', 1986, 16, 0xFFFF, 0x08, 1986, 63) and saved_ok(c),
          'saved: type 47, 1986/16/63, WPcom 65535, control 08h, LZone 1986')

def pages_case(img, ref):
    print('the pages')
    p = enter(img)
    t = rows(p)
    check(t[0].startswith(' BUBios/286 0.6 Setup') and t[0].rstrip().endswith('Headland HT12/A'), 'title: %s' % t[0].strip())
    check(norm(t[1]) == 'Summary Standard Advanced Chipset Tools Exit', 'tabs: %s' % norm(t[1]))
    key = row(p, 24)
    check(len(key) <= 79 and key.strip().endswith('ESC:Exit'), 'key row fits (%d columns)' % len(key))
    want = {4: 'Processor 80286 Floppy A: 1.44 MB, 3½"', 5: 'Clock 16 MHz Floppy B: 1.2 MB, 5¼"',
            6: 'Coprocessor None', 7: 'Chipset Headland HT12/A Hard disk C: 977 MB [47]',
            8: '├─ Physical 1986/16/63', 9: 'Base memory 640 KB └─ DOS (ECHS) 992/32/63',
            10: 'Extended memory 3072 KB', 11: 'EMS memory 0 KB Hard disk D: None', 12: 'Shadow RAM Disabled',
            13: 'Boot sequence A: then C:', 14: 'Auto-detect On', 15: 'Display VGA or EGA', 16: 'Keyboard Installed',
            18: 'BIOS AMI 06/13/90 ■ BUBios/286 0.6'}
    for r, w in want.items():
        check(norm(t[r]) == w, 'Summary row %2d: %s' % (r, norm(t[r])))
    pages = {1: ['Date (mm/dd/yyyy)', 'Time (hh:mm:ss)', 'Floppy drive A:', 'Floppy drive B:', 'Hard disk C: type',
                 'Hard disk D: type', 'Primary display', 'Keyboard'],
             2: ['Boot sequence', 'Auto-Detect Disks at Boot', 'Colour scheme'],
             3: ['BIOS shadow option', 'Scratch RAM option', 'EMS size option', '0 Wait State option', 'Memory relocation'],
             4: ['Auto-detect hard disk C: now', 'Auto-detect hard disk D: now'],
             5: ['Save settings and exit', 'Exit without saving']}
    for pg, labels_ in pages.items():
        press(p, [TAB]); txt = p.text()
        check(frame(p)[0] == pg and all(l in txt for l in labels_), 'page %d: %s' % (pg, ', '.join(labels_)))
        if pg == 1:
            check('Extended memory 3072 KB' in norm(txt) and 'Coprocessor None' in norm(txt), 'Standard: memory and coprocessor line')
        if pg == 3:
            check('Extended memory 3072 KB' in norm(txt) and 'EMS maximum 3072 KB' in norm(txt), 'Chipset: memory and EMS maximum')
    press(p, [TAB]); check(frame(p)[0] == 0, 'Tab after Exit: Summary again')
    # every option's help line
    press(p, [TAB])
    seen = set()
    for _ in range(14):
        seen.add(row(p, 22).strip()); press(p, [DOWN])
    check(len(seen) >= 9 and '' not in seen, 'Standard: a help text for every field (%d different)' % len(seen))

def scheme_attrs(img, n):
    """the scheme table in the ROM: BG TITLE LABEL VALUE FILL EMPTY ACCENT ERR STAT SEL TABA"""
    a = labels()['schemes']
    return img[a + 11 * n:a + 11 * n + 11]

def scheme_case(img, ref):
    print('colour schemes')
    p = enter(img)
    check(p.cells()[1][1] == scheme_attrs(img, 0)[1] == 0x30, 'Teal by default (title %02X)' % p.cells()[1][1])
    press(p, [F3])
    check(p.cells()[1][1] == scheme_attrs(img, 1)[1], 'F3: the next scheme at once (Amber, title %02X)' % p.cells()[1][1])
    press(p, [F2, F2])
    check(p.cells()[1][1] == scheme_attrs(img, 5)[1] and p.cells()[80 * 22 + 2][1] == scheme_attrs(img, 5)[0],
          'F2 twice: round to the last one (AMI)')
    our_set(p, 'sch', 'Green')
    check(p.cells()[1][1] == scheme_attrs(img, 2)[1], 'the Advanced field: Green, drawn at once')
    c = our_save(p)
    if not check(c is not None, 'saved'): return
    check((c[0x3E] >> 4) & 7 == 2 and c[0x3F] == c[0x3E] ^ 0xA5, 'CMOS 3Eh = %02X (scheme 2), 3Fh = 3Eh XOR A5h' % c[0x3E])
    check(saved_ok(c) and c[0x10:0x3E] == p.cmos[0x10:0x3E], 'the checksum over 10h-2Dh untouched by 3Eh')
    p.run(max_ms=30000)
    at = scheme_attrs(img, 2)
    check(p.stop == 'int19' and p.cells()[1][1] == at[1] and p.cells()[2 * 80 + 2][1] == at[2],
          'the next POST screen in Green (title %02X, labels %02X)' % (p.cells()[1][1], p.cells()[2 * 80 + 2][1]))
    print('a wrong check byte: the defaults')
    p = Post(img, cmos=make_cmos(extra={0x3E: 0x26, 0x3F: 0x00})); p.run(max_ms=30000)
    check(p.cells()[1][1] == 0x30 and row(p, 17).strip().startswith('Booting: A: then C:'),
          '3Eh with a wrong 3Fh is ignored: Teal, A: then C:')

def disk(msg):
    code = bytes.fromhex('31c08ed8be217cb40eac08c07404cd10ebf7f4ebfd')
    b = bytearray(512); b[:len(code)] = code; b[0x21:0x21 + len(msg) + 1] = msg + b'\0'; b[510:] = b'\x55\xaa'
    return bytes(b)

def boot_run(img, order, floppy=True, cdisk=True, drive=(1986, 16, 63), keys=(), floppy386=False):
    v = order | 0x00
    p = Post(img, cmos=make_cmos(drive=drive, extra={0x3E: v, 0x3F: v ^ 0xA5}), drive=drive)
    p.stop_at_int19 = False
    if floppy:
        fl = bytearray(1474560)
        if floppy386:
            bs = bytes.fromhex('fa31c08ed0bc007cfb') + b'\x0f\x0b'
            fl[:len(bs)] = bs; fl[510:512] = b'\x55\xaa'
        else:
            fl[:512] = disk(b'FLOPPY-BOOT\r\n')
        p.floppy = bytes(fl)
    if drive and cdisk: p.ides[0].sectors[0] = disk(b'DISK-BOOT\r\n')
    p.run(max_ms=40000)
    for k in keys:
        p.type_key(k); p.run(max_ms=20000)
    return p

def boot_case(img, ref):
    print('the boot order')
    names = {0: 'A: then C:', 1: 'C: then A:', 2: 'C: only'}
    for order, floppy, cdisk, want, fl in (
            (0, True, True, 'FLOPPY-BOOT', True), (0, False, True, 'DISK-BOOT', False),
            (1, True, True, 'DISK-BOOT', False), (1, True, False, 'FLOPPY-BOOT', True),
            (2, True, True, 'DISK-BOOT', False)):
        p = boot_run(img, order, floppy, cdisk)
        t = p.text()
        other = 'DISK-BOOT' if want == 'FLOPPY-BOOT' else 'FLOPPY-BOOT'
        reads = getattr(p, 'floppy_reads', 0)
        check(want in t and other not in t and (reads > 0) == fl and row(p, 17).strip().startswith('Booting: ' + names[order]),
              '%-11s floppy %-3s C: %-14s -> %s, A: %s, status "%s"' % (names[order], 'yes' if floppy else 'no',
              'boot sector' if cdisk else 'no boot sector', want, 'read' if reads else 'no sector read', row(p, 17).strip()[:20]))
    p = boot_run(img, 1, True, True, drive=None)
    check('FLOPPY-BOOT' in p.text(), 'C: then A:, no hard disk: A: boots')
    p = boot_run(img, 2, True, False, keys=[0x39])
    t = [l.strip() for l in p.text().splitlines()]
    n = sum(1 for l in t if l.startswith('No boot sector on C: (boot order: C: only'))
    check(n == 2 and 'Press any key to try again' in t and getattr(p, 'floppy_reads', 0) == 0
          and 'FLOPPY-BOOT' not in p.text(),
          'C: only, no boot sector on C:: the message, a key tries again (shown %d times), A: never read' % n)
    p = boot_run(img, 1, True, True, floppy386=True)
    check('DISK-BOOT' in p.text() and getattr(p, 'int6', 0) == 0 and getattr(p, 'floppy_reads', 0) == 0,
          'C: then A:, a 386 floppy in A:: C: boots, A: not touched')
    p = boot_run(img, 1, True, False, floppy386=True)
    t = p.text()
    check('Drive A: skipped.' in t and getattr(p, 'int6', 0) == 1,
          'C: then A:, C: without a boot sector, a 386 floppy: Step 4\'s message (%s)' % ' / '.join(
              l.strip() for l in t.splitlines()[18:25] if l.strip())[:90])

def ide_cmds(p): return [c for c in p.ides[0].log if not isinstance(c, tuple)] if p.ides[0] else []

def autodet_case(img, ref):
    print('Auto-Detect Disks at Boot')
    for name, extra in (('On (default, no setting)', {}), ('On', {0x3E: 0x00, 0x3F: 0xA5}), ('Off', {0x3E: 0x04, 0x3F: 0xA1})):
        p = Post(img, cmos=make_cmos(drive=None, extra=extra), drive=(3875, 16, 63), drive_model='SanDisk SDCFB-2048')
        p.run(max_ms=30000)
        on = name.startswith('On')
        t = row(p, 10).strip(); t2 = norm(row(p, 11))
        if on:
            check(t.startswith('Disk C:  CF  SanDisk SDCFB-2048') and t2.startswith('Auto 3875/16/63'),
                  '%s: a "Not installed" drive that answers is set up as type 47: %s / %s' % (name, t, t2))
        else:
            check(t == 'Disk C:  CF  SanDisk SDCFB-2048' and p.mu.mem_read(0x475, 1)[0] == 0,
                  '%s: the drive not set up (40:75 = %d), its model shown' % (name, p.mu.mem_read(0x475, 1)[0]))
        if on:
            c = p.cmos
            check(c[0x12] == 0xF0 and c[0x19] == 47 and saved_ok(c) and
                  c[0x1B:0x24] == struct.pack('<HBHBHB', 3875, 16, 0xFFFF, 0x08, 3875, 63),
                  '%s: written to CMOS as type 47 3875/16/63 (Step 3)' % name)
        else:
            check(p.cmos[0x12] == 0 and norm(row(p, 11)) == 'Not set up (Auto-Detect Disks at Boot is Off)',
                  '%s: CMOS 12h stays 0; the screen: %s' % (name, norm(row(p, 11))))
        cmds = ide_cmds(p)
        check((0x91 in cmds) == on and cmds.count(0xEC) == (2 if on else 1),
              '%s: IDE commands %s (%s)' % (name, ' '.join('%02X' % c for c in cmds),
              'the POST screen\'s IDENTIFY only' if not on else 'Step 3 sets the drive up'))
    for name, extra in (('On', {}), ('Off', {0x3E: 0x04, 0x3F: 0xA1})):
        a = Post(img, cmos=make_cmos(extra=extra)); a.run(max_ms=30000)
        check(row(a, 10).strip() == 'Disk C:  CF  SanDisk SDCFJ-1024' and a.mu.mem_read(0x475, 1)[0] == 1,
              '%s: a drive entered in CMOS is used as entered' % name)
        b = Post(img, cmos=make_cmos(extra=extra), drive=None); b.run(max_ms=30000)
        check(b.mu.mem_read(0x475, 1)[0] == 0 and b.cmos[0x12] == 0xF0,
              '%s: an entered drive that does not answer is left out (40:75 = 0), CMOS kept' % name)

def post_case(img, ref):
    print('POST without a setup visit: as round 5b')
    a = Post(img); stack_watch(a); a.run(max_ms=30000)
    b = Post(ref); b.run(max_ms=30000)
    check(a.stop == b.stop == 'int19', 'both reach INT 19h')
    check([c for c, _ in a.p80] == [c for c, _ in b.p80], 'the same POST checkpoints (%d)' % len(a.p80))
    check(a.cmos == b.cmos, 'the same CMOS')
    la, lb = bytes(a.mu.mem_read(0, 0x500)), bytes(b.mu.mem_read(0, 0x500))
    diff = [o for o in range(0x500) if la[o] != lb[o] and not (0x360 <= o < 0x400 or o == 0x440 or 0x46C <= o <= 0x470)]
    check(not diff, 'the same vectors and BDA (but stack leftovers, timer)%s' % ''.join(' %03X' % o for o in diff[:8]))
    ra, rb_ = rows(a), rows(b)
    d = [r for r in range(25) if ra[r] != rb_[r].replace('0.5', '0.6')]
    check(not d and all(a.cells()[i][1] == b.cells()[i][1] for i in range(2000)),
          'the same screen and colours (but the version) %s' % d)
    check(a.low_sp >= 0x400 - 160, 'stack: lowest 0030:%04X (budget 0030:%04X)' % (a.low_sp - 0x300, 0x400 - 160 - 0x300))

def stack_watch(p):
    p.low_sp = 0x10000
    def h(uc, addr, size, ud):
        if uc.reg_read(UC_X86_REG_SS) == 0x30:
            p.low_sp = min(p.low_sp, 0x300 + uc.reg_read(UC_X86_REG_SP))
    p.mu.hook_add(UC_HOOK_CODE, h, begin=0xF000B, end=0xF0000 + labels()['boot_seq'])

def mono_case(img, ref):
    print('the setup on a monochrome card')
    p = enter(img, video='mono', cmos=make_cmos(video='mono'))
    at = set(a for _, a in p.cells())
    check(p.vbase == 0xB0000 and row(p, 0).startswith(' BUBios/286 0.6 Setup'), 'the setup on the mono card (B000h)')
    check(at <= {0x07, 0x70, 0x0F, 0x08, 0x01, 0x09, 0x00, 0x78}, 'monochrome attributes only: %s' % ' '.join('%02X' % a for a in sorted(at)))
    press(p, [F3])
    check(set(a for _, a in p.cells()) == at, 'F2 / F3 do nothing on a mono card')
    press(p, [TAB])
    check(our_value(p, 'date') == '11/19/2026' and p.cells()[4 * 80 + 28][1] == 0x70, 'Standard: the selected field in inverse')

# ---------------------------------------------------------------- the parts
PARTS = {'ab': ab_case, 'type47': type47_case, 'datetime': datetime_case, 'exit': exit_case,
         'tools': tools_case, 'pages': pages_case, 'scheme': scheme_case, 'boot': boot_case,
         'autodet': autodet_case, 'post': post_case, 'mono': mono_case}

def run_all(img, ref, parts=None):
    t0 = time.time()
    for name in parts or PARTS:
        if ':' in name:                       # ab:3 = only that set of choices
            n, only = name.split(':'); PARTS[n](img, ref, only=[int(x) for x in only.split(',')])
        else:
            PARTS[name](img, ref)
    print('(%.0f s)' % (time.time() - t0))

# ---- mutations: each must fail ----------------------------------------------
def fix_sums(m):
    struct.pack_into('<H', m, 0xF83E, 0)
    struct.pack_into('<H', m, 0xF83E, (-sum(struct.unpack_from('<16384H', m, 0x8000))) & 0xFFFF)
    struct.pack_into('<H', m, 0x6FFE, 0)
    x = 0
    for v in struct.unpack_from('<14336H', m, 0): x ^= v
    struct.pack_into('<H', m, 0x6FFE, x)

def find(m, lo, pat, span=0x80):
    i = bytes(m).find(pat, lo)
    assert 0 <= i < lo + span, 'pattern %s not found after %04X' % (pat.hex(), lo)
    return i

def mutants(img):
    L = labels(); out = []
    def mk(name, label, pat, new, part):
        m = bytearray(img); i = find(m, L[label], pat); m[i:i + len(new)] = new
        fix_sums(m); out.append((name, m, part))
    mk('fd_fix: 14h bit 6 (two drives) not set', 'fd_fix', b'\x80\x4e\x14\x40', b'\x80\x4e\x14\x00', 'ab:4')
    mk('dsp_set: 37h bit 1 (display installed) lost', 'dsp_set', b'\x80\x4e\x37\x02', b'\x80\x4e\x37\x00', 'ab:2')
    mk('ems_fix: 17h/18h in 32 KB units', 'ems_fix', b'\xc1\xe0\x06', b'\xc1\xe0\x05', 'ab:1')
    mk('shd_set: no new EMS maximum', 'shd_set', b'\x08\x46\x38\xeb', b'\x08\x46\x38\xc3', 'ab:9')
    mk('param_set: no control byte 08h', 'param_set', b'\xc6\x42\x03\x08', b'\xc6\x42\x03\x00', 'type47')
    mk('date_set: every year a leap year', 'date_set', b'\xf6\xc1\x03', b'\xf6\xc1\x00', 'datetime')
    mk('time_set: 24:00:00 taken', 'time_set', b'\x80\xfd\x17', b'\x80\xfd\x18', 'datetime')
    mk('bub_set: wrong check byte', 'bub_set', b'\x34\xa5', b'\x34\xa4', 'scheme')
    mk('boot_seq: always A: first', 'boot_seq', b'\x24\x03', b'\x24\x00', 'boot')
    mk('autodet_sw: Off ignored', 'autodet_sw', b'\xa8\x04', b'\xa8\x00', 'autodet')
    return out

if __name__ == '__main__':
    img, ref = open(ROM, 'rb').read(), open(REF, 'rb').read()
    print('ROM %s\nreference %s' % (os.path.relpath(ROM, ROOT), os.path.relpath(REF, ROOT)))
    sel = [a for a in sys.argv[1:] if not a.startswith('--')]
    if '--mutants-only' not in sys.argv: run_all(img, ref, sel or None)
    n = len(fails)
    if '--mutants' in sys.argv or '--mutants-only' in sys.argv:
        print('\nmutations (each must fail)')
        bad = 0
        for name, m, part in mutants(img):
            fails.clear()
            out = sys.stdout; sys.stdout = open(os.devnull, 'w')
            try: run_all(bytes(m), ref, parts=(part,))
            except Exception as e: fails.append('exception %s' % e)
            finally: sys.stdout.close(); sys.stdout = out
            print('  %s  %-46s %d failures' % ('ok  ' if fails else 'FAIL', name, len(fails)))
            if not fails: bad += 1
        n += bad
    print('\n%s' % ('ALL PASS' if n == 0 else '%d FAILURES' % n))
    sys.exit(1 if n else 0)
