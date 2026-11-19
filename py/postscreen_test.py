#!/usr/bin/env python3
"""Round 5b tests: the POST screen.

    python3 py/postscreen_test.py              the round 5b ROM (about 6 minutes)
    python3 py/postscreen_test.py --mutants    also prove the tests catch broken ROMs
    FOXII_ROM=binary/X.BIN python3 py/postscreen_test.py

Every case runs the whole POST in py/post_emu.py (reset to INT 19h) on the
5b ROM, and most of them also on the round 5a ROM (AMI's own screens, the
reference) with the same inputs:

  - what the screen shows, row by row, in the normal case (the board:
    80C286 at 16 MHz, no 287, 640 + 3072 KB, the SanDisk 1 GB card as C:
    type 47, a 1.44 MB A:, VGA, COM1 COM2 LPT1), during the memory test,
    at other clocks, on a monochrome card, with no disk, with two disks,
    with an auto-detected disk, a configured disk that is not there, a
    disk still busy at checkpoint 22h, a cleared CMOS (AMI's errors, F1,
    setup menu), a setup visit with DEL, and a warm boot;
  - that POST itself is unchanged: the same POST checkpoint sequence, the
    same CMOS, and the same interrupt vectors and BDA (but the cursor, the
    stack's leftovers and the intra-application area) as round 5a;
  - the state POST hands to INT 19h: 40:F0-FF cleared, 40:8E = 0, the IDE
    master selected, the drive's interrupt enabled (3F6h), IRQ 14's mask as
    on 5a, the cursor at row 18 and visible;
  - the boot: a C: boot sector with 386 code shows Step 2's message below
    the POST information, readable (grey on black), the information intact;
  - every hook keeps the registers (96E7: SI = 7AB2 as the MOV it replaces),
    and the POST stack stays within its 160-byte budget.
"""
import os, struct, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from post_emu import Post, make_cmos
from unicorn import UC_HOOK_CODE
from unicorn.x86_const import *

ROOT = os.path.dirname(HERE)
ROM  = os.environ.get('FOXII_ROM') or os.path.join(ROOT, 'binary', 'FOXII_STEP5B.BIN')
REF  = os.path.join(ROOT, 'binary', 'FOXII_STEP5A.BIN')
MAP  = os.path.join(ROOT, 'asm', 'step5b.map')
DEL, ENTER, F1 = 0x53, 0x1C, 0x3B
BUDGET_LOW = 0x0400 - 160            # POST stack 0030:0100: nothing below 0360h

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

def rows(p): return p.text().splitlines() + [''] * 25
def row(p, r): return rows(p)[r].rstrip()
def rb(p, r):
    """row r as CP437 bytes, without the blanks around it"""
    return bytes(c for c, _ in p.cells()[r * 80:r * 80 + 80]).strip(b' ')
def attr(p, r, c): return p.cells()[r * 80 + c][1]

def post(rom, keys=(), max_ms=30000, watch_stack=False, hooks=False, **kw):
    p = Post(rom, **kw)
    for t, k in keys: p.type_key(k, at_ms=t)
    if watch_stack: stack_watch(p)
    if hooks: hook_watch(p)
    p.run(max_ms=max_ms)
    return p

# ---- stack: the lowest SS:SP (SS = 0030h) while the new code runs -----------
def stack_watch(p):
    p.low_sp = 0x10000
    def h(uc, addr, size, ud):
        if uc.reg_read(UC_X86_REG_SS) == 0x30:
            p.low_sp = min(p.low_sp, 0x300 + uc.reg_read(UC_X86_REG_SP))
    end = labels().get('post_end', 0x7000)
    p.mu.hook_add(UC_HOOK_CODE, h, begin=0xF000B, end=0xF0000 + end)

# ---- registers across every hook: (call site, return address, what may change)
REGS = [('AX', UC_X86_REG_AX), ('BX', UC_X86_REG_BX), ('CX', UC_X86_REG_CX), ('DX', UC_X86_REG_DX),
        ('SI', UC_X86_REG_SI), ('DI', UC_X86_REG_DI), ('BP', UC_X86_REG_BP), ('SP', UC_X86_REG_SP),
        ('DS', UC_X86_REG_DS), ('ES', UC_X86_REG_ES)]
SITES = [(0x92C1, 0x92C4, ()), (0xACDB, 0xACDE, ()), (0xAD05, 0xAD08, ()), (0x93F6, 0x93F9, ()),
         (0x96E7, 0x96EA, ('SI',)), (0x9791, 0x9794, ()),
         (0xAB4B, 0xAB4E, ()), (0x955B, 0x955E, ()),                    # AB60 -> bu_clrmsg
         (0x92DA, 0x92DD, ()), (0x94C5, 0x94C8, ()), (0xAB44, 0xAB47, ()),   # 76D0 -> bu_idline
         (0x97C4, 0x97C6, ())]                                          # F000:0008 -> bu_final
def hook_watch(p):
    p.reg_bad, p.reg_seen, pend = [], set(), {}
    def at_call(site):
        def h(uc, addr, size, ud):
            pend[site] = [uc.reg_read(r) for _, r in REGS]
        return h
    def at_ret(site, ret, may):
        def h(uc, addr, size, ud):
            if site not in pend: return
            before = pend.pop(site); p.reg_seen.add(site)
            for (n, r), v in zip(REGS, before):
                now = uc.reg_read(r)
                if n == 'SI' and site == 0x96E7:
                    if now != 0x7AB2: p.reg_bad.append('%04X: SI = %04X, not 7AB2' % (site, now))
                    continue
                if n in may: continue
                if now != v: p.reg_bad.append('%04X: %s %04X -> %04X' % (site, n, v, now))
        return h
    for site, ret, may in SITES:
        p.mu.hook_add(UC_HOOK_CODE, at_call(site), begin=0xF0000 + site, end=0xF0000 + site)
        p.mu.hook_add(UC_HOOK_CODE, at_ret(site, ret, may), begin=0xF0000 + ret, end=0xF0000 + ret)

# ---- what POST hands to INT 19h ---------------------------------------------
def handover_checks(p, what, ref=None):
    low = bytes(p.mu.mem_read(0, 0x500))
    check(not any(low[0x4F0:0x500]), '%s: 40:F0-FF cleared for DOS' % what)
    check(low[0x48E] == 0, '%s: 40:8E = 0 (no IRQ 14 left over)' % what)
    if ref is None:
        check(not (p.ide_r6 & 0x10), '%s: IDE master selected' % what)
    else:                                  # with two drives AMI's disk setup ends on the slave
        check(p.ide_r6 == ref.ide_r6, '%s: IDE drive select as on 5a (%02X)' % (what, p.ide_r6))
    check(not (p.ide_ctl & 0x02), "%s: the drive's interrupt enabled (3F6h nIEN = 0)" % what)
    check(not (p.pic[1]['irr'] & 0x40), '%s: no IRQ 14 pending in the slave PIC' % what)
    check(p.cur == (18, 0) or p.cur == (23, 0), '%s: cursor at row 18 (23 with errors) (%d,%d)' % ((what,) + p.cur))

def ab(name, a, b, stack_ok=True):
    check(a.stop == b.stop == 'int19', '%s: reaches INT 19h (5b: %s, 5a: %s)' % (name, a.stop, b.stop))
    check([c for c, _ in a.p80] == [c for c, _ in b.p80],
          '%s: the same POST checkpoint sequence as 5a (%d codes)' % (name, len(a.p80)))
    check(a.cmos == b.cmos, '%s: the same CMOS as 5a' % name)
    la, lb = bytes(a.mu.mem_read(0, 0x500)), bytes(b.mu.mem_read(0, 0x500))
    # allowed: the stack's leftovers (0360-03FF), the cursor position and shape
    # (40:50-51, 40:60-61), 40:F0-FF (5a: Step 4's marker area, both zero here)
    diff = [o for o in range(0x500) if la[o] != lb[o]
            and not (0x360 <= o < 0x400 or o in (0x450, 0x451, 0x460, 0x461)
                     or o == 0x440 or 0x46C <= o <= 0x470)]   # (and the timer: POST takes longer)
    check(not diff, '%s: the same vectors and BDA as 5a (but cursor, stack, timer)%s'
          % (name, '' if not diff else ': ' + ' '.join('%03X' % o for o in diff[:10])))

# =============================================================================
def normal_case(img, ref):
    print('the board, cold boot')
    a = post(img, watch_stack=True, hooks=True); b = post(ref)
    ab('cold boot', a, b)
    handover_checks(a, 'cold boot')
    exp = {0: 'BUBios/286 0.5  \xfe  Power-On Self Test      Bits und Bolts  \xfe  Headland HT12/A',
           2: 'Processor    80286                           Coprocessor  None',
           3: 'Clock        16 MHz                          Shadow RAM   Disabled',
           4: 'Chipset      Headland HT12/A                 RTC battery  OK',
           5: 'BIOS         AMI 06/13/90 \xfe BUBios/286 0.5',
           9: 'Floppy A:    1.44 MB, 3\xab"                    Floppy B:    None',
           10: 'Disk C:  CF  SanDisk SDCFJ-1024',
           11: 'Type 47  1986/16/63 \x1a DOS 992/32/63    977 MB',
           12: 'Disk D:      None',
           15: 'Ports        COM1 3F8  COM2 2F8  LPT1 378',
           16: 'Option ROMs  C000 2K'}
    for r, t in exp.items():
        got = row(a, r).strip().encode('cp437', 'replace').decode('latin-1')
        want = t.encode('latin-1').decode('latin-1')
        check(got == want.strip() if r else got == want.strip(), 'row %2d: %s' % (r, row(a, r).strip()))
    check(row(a, 7).strip() == 'Memory       ' + '█' * 40 + '  3712 KB', 'row  7: the bar full, 3712 KB')
    check(row(a, 24).strip().startswith('Booting: A: then C:') and row(a, 24).rstrip().endswith('DH12-1112-061390-K'),
          'row 24: status "Booting: A: then C:", the BIOS ID')
    check(all(attr(a, 0, c) == 0x30 for c in range(80)), 'title bar black on cyan')
    check(attr(a, 2, 2) == 0x03 and attr(a, 2, 15) == 0x0F, 'labels cyan, values bright white')
    check(attr(a, 10, 10) == 0x30, 'the CF badge in the title colours')
    check(all(a.cells()[r * 80 + c] == (0x20, 0x07) for r in range(18, 24) for c in range(80)),
          'rows 18-23 blank, grey on black, for the boot')
    check(a.curshape == 0x0607, 'cursor visible again (0607h)')
    check(not [t for t in a.text().splitlines() if 'KB OK' in t or 'DIAGS' in t or 'Megatrends' in t],
          "none of AMI's POST texts left on the screen")
    check(a.low_sp >= BUDGET_LOW, 'stack: lowest 0030:%04X, budget 0030:%04X' % (a.low_sp - 0x300, BUDGET_LOW - 0x300))
    check(not a.reg_bad, 'every hook keeps the registers (%d sites seen)%s'
          % (len(a.reg_seen), '' if not a.reg_bad else ': ' + '; '.join(a.reg_bad[:4])))
    check(len(a.reg_seen) >= 11, 'hooks reached: %s' % ' '.join('%04X' % s for s in sorted(a.reg_seen)))
    return a

def memtest_case(img):
    print('during the memory test')
    p = Post(img)
    p.run(max_ms=10000, until=lambda q: q.p80 and q.p80[-1][0] == 0x3C and
          sum(1 for c, _ in q.p80 if c == 0x3C) >= 1 and q.t > 4.0e9)
    t = rows(p)
    bar = t[7][15:55]
    filled = bar.count('█')
    check(0 < filled < 40, 'bar partly filled (%d of 40): %s' % (filled, t[7].strip()[:70]))
    check(t[7].strip().endswith(' KB') and t[7][57:].strip()[:-3].isdigit(), 'count in KB: %s' % t[7][57:].strip())
    check(t[24].strip().startswith('Press ESC to skip the memory test'), 'status: %s' % t[24].strip()[:40])
    check(t[2].strip().startswith('Processor    80286') and t[3].strip().startswith('Clock        16 MHz'),
          'processor and clock already shown')
    check('...' in t[2] and '...' in t[3], 'coprocessor and shadow RAM: "..." until the end of POST')
    check(t[10].strip() == 'Disk C:  CF  SanDisk SDCFJ-1024', 'the disk model already shown')

def clock_cases(img):
    print('other clocks (emulated 286 cycle times in the timing loop)')
    for mhz, want in ((12, '12 MHz'), (20, '20 MHz'), (8, '8 MHz'), (14, '...')):
        p = Post(img, cpu_mhz=mhz); p.run(max_ms=4000)
        check(row(p, 3).strip().startswith('Clock        ' + want), '%d MHz -> %s' % (mhz, row(p, 3).strip()[:25]))

def variant_cases(img, ref):
    cases = [
        ('monochrome', dict(video='mono', cmos=make_cmos(video='mono')),
         [(0, 'BUBios/286 0.5  \u25a0  Power-On Self Test      Bits und Bolts  \u25a0  Headland HT12/A'),
          (10, 'Disk C:  CF  SanDisk SDCFJ-1024'), (16, 'Option ROMs  None')]),
        ('no hard disk', dict(drive=None, cmos=make_cmos(drive=None)),
         [(10, 'Disk C:      None'), (11, ''), (12, 'Disk D:      None')]),
        ('two disks (2 GB card as D:)', dict(slave=(3875, 16, 63), slave_model='SanDisk SDCFB-2048',
                                           cmos=make_cmos(drive_d=(3875, 16, 63))),
         [(12, 'Disk D:  CF  SanDisk SDCFB-2048'), (13, 'Type 47  3875/16/63 \x1a DOS 967/64/63    1907 MB')]),
        ('auto-detected C: (CMOS 12h = 0)', dict(cmos=make_cmos(drive=None)),
         [(10, 'Disk C:  CF  SanDisk SDCFJ-1024'), (11, 'Auto  1986/16/63 \x1a DOS 992/32/63    977 MB')]),
        ('C: type 47 in CMOS, nothing on the bus', dict(drive=None, cmos=make_cmos()),
         [(10, 'Disk C:      Not found (left out for this boot)'), (11, 'Type 47  1986/16/63 \x1a DOS 992/32/63    977 MB')]),
        ('a ROM drive type (type 2, 615/4/17)', dict(cmos=make_cmos(drive=2), drive=(615, 4, 17), drive_model='ST225'),
         [(10, 'Disk C:      ST225'), (11, 'Type 2  615/4/17 \x1a DOS 614/4/17    20 MB')]),
        ('a hard disk (no CF badge)', dict(drive_model='WDC AC2850F'),
         [(10, 'Disk C:      WDC AC2850F')]),
    ]
    for name, kw, want in cases:
        print(name)
        a = post(img, **kw); b = post(ref, **kw)
        ab(name, a, b)
        handover_checks(a, name, b)
        for r, t in want:
            got = rb(a, r).decode('cp437')
            check(got == t, 'row %2d: %s' % (r, got))
        if name == 'monochrome':
            check(a.vbase == 0xB0000 and attr(a, 0, 0) == 0x70 and a.curshape == 0x0B0C,
                  'mono: B000h, title inverse, cursor 0B0Ch')
        if name.startswith('auto'):
            check(a.cmos[0x12] == 0xF0 and a.cmos[0x19] == 47, 'CMOS: 12h = F0, 19h = 47 (Step 3)')

def busy_case(img, ref):
    print('C: busy for 3 s at power-on (spinning up)')
    a = Post(img); a.ides[0].busy_until = int(3e9); a.run(max_ms=30000)
    b = Post(ref); b.ides[0].busy_until = int(3e9); b.run(max_ms=30000)
    ab('busy C:', a, b)
    handover_checks(a, 'busy C:')
    check(row(a, 10).strip() == 'Disk C:  CF  SanDisk SDCFJ-1024', 'model read at the end of POST: %s' % row(a, 10).strip())
    ids = [cp for v, cp in a.ides[0].cmds if v == 0xEC]
    check(ids == [0x00], 'one IDENTIFY, at the end of POST (checkpoint 00h): %s' % ids)
    print('C: busy for 3 s, early screen')
    p = Post(img); p.ides[0].busy_until = int(3e9); p.run(max_ms=1500)
    check(row(p, 10).strip() == 'Disk C:      ...', 'while busy: "..." (%s)' % row(p, 10).strip())

def warm_case(img, ref):
    print('warm boot (40:72 = 1234h)')
    a = post(img); a.warm_boot(); a.run(max_ms=30000)
    b = post(ref); b.warm_boot(); b.run(max_ms=30000)
    ab('warm boot', a, b)
    handover_checks(a, 'warm boot')
    check(row(a, 7).strip().endswith('3712 KB'), 'memory 3712 KB although the count was skipped: %s' % row(a, 7).strip()[-10:])
    check(row(a, 10).strip() == 'Disk C:  CF  SanDisk SDCFJ-1024', 'disk model')

def error_case(img, ref):
    print('cleared CMOS: AMI\'s errors, F1, setup menu, EXIT FOR BOOT')
    a = Post(img, cmos=bytes(128)); b = Post(ref, cmos=bytes(128))
    for p in (a, b): p.run(max_ms=15000)
    t = rows(a)
    msgs = [l.strip() for l in t[18:24] if l.strip()]
    check(msgs == ['CMOS battery state low', 'CMOS system options not set', 'RUN SETUP UTILITY', 'Press <F1> to RESUME'],
          'AMI\'s messages in rows 18-23: %s' % ' / '.join(msgs))
    check(attr(a, 19, 0) == 0x0C, 'in red')
    check(t[24].strip().startswith('POST found a problem'), 'status: POST found a problem')
    check(t[4].strip().endswith('RTC battery  Low (CMOS lost)'), 'RTC battery: Low (CMOS lost)')
    check(t[0].startswith(' BUBios/286'), 'the POST screen stays up (title bar row 0)')
    for p in (a, b): p.type_key(F1); p.run(max_ms=3000)
    menu = [l.strip() for l in a.text().splitlines() if l.strip()]
    check(menu == ['EXIT FOR BOOT', 'RUN CMOS SETUP'], 'F1: AMI\'s setup menu (%s)' % ' / '.join(menu))
    for p in (a, b): p.type_key(ENTER); p.run(max_ms=20000)
    ab('cleared CMOS', a, b)
    handover_checks(a, 'cleared CMOS')
    check(row(a, 0).startswith('BUBios/286') or rows(a)[0].startswith(' BUBios/286'), 'after setup: the POST screen drawn again')
    check('POST' not in row(a, 24)[38:48], 'no POST time after a setup visit')

def setup_case(img, ref):
    print('DEL during POST: setup menu, EXIT FOR BOOT')
    keys = [(t, DEL) for t in range(1000, 7000, 500)]
    a = post(img, keys=keys, max_ms=12000); b = post(ref, keys=keys, max_ms=12000)
    menu = [l.strip() for l in a.text().splitlines() if l.strip()]
    check(menu == ['EXIT FOR BOOT', 'RUN CMOS SETUP'], 'DEL works: setup menu (%s)' % ' / '.join(menu))
    for p in (a, b): p.type_key(ENTER); p.run(max_ms=20000)
    ab('setup visit', a, b)
    handover_checks(a, 'setup visit')
    check(rows(a)[0].startswith(' BUBios/286') and row(a, 10).strip() == 'Disk C:  CF  SanDisk SDCFJ-1024',
          'the POST screen drawn again, with the disk model')
    print('status line in the DEL window (checkpoint 73h)')
    p = Post(img); p.run(max_ms=10000, until=lambda q: q.p80 and q.p80[-1][0] == 0x74)
    check(row(p, 24).strip().startswith('Press DEL to run Setup'), 'status: %s' % row(p, 24).strip()[:30])

def boot_case(img):
    print('the boot: a C: boot sector with 386 code (UD2)')
    p = Post(img); p.stop_at_int19 = False
    mbr = bytearray(512); mbr[0:2] = b'\x0f\x0b'; mbr[510:512] = b'\x55\xaa'
    p.ides[0].sectors[0] = bytes(mbr)
    p.run(max_ms=60000)
    t = rows(p)
    check(getattr(p, 'int6', 0) == 1, 'one INT 06h')
    msg = [l.strip() for l in t[18:24] if l.strip()]
    check(msg[:2] == ['Invalid opcode at 0000:7C00 (boot sector)', 'Bytes: 0F 0B 00 00 00 00'] and
          'System halted' in ' '.join(msg), "Step 2's message below the POST information: %s" % ' / '.join(msg)[:80])
    check(all(a == 0x07 for r in range(18, 24) for _, a in p.cells()[r * 80:r * 80 + 80]), 'grey on black')
    check(t[10].strip() == 'Disk C:  CF  SanDisk SDCFJ-1024' and t[0].startswith(' BUBios/286'),
          'the POST information above is intact')

def run_all(img, ref, parts=('normal', 'memtest', 'clock', 'variants', 'busy', 'warm', 'errors', 'setup', 'boot')):
    t0 = time.time()
    if 'normal' in parts: normal_case(img, ref)
    if 'memtest' in parts: memtest_case(img)
    if 'clock' in parts: clock_cases(img)
    if 'variants' in parts: variant_cases(img, ref)
    if 'busy' in parts: busy_case(img, ref)
    if 'warm' in parts: warm_case(img, ref)
    if 'errors' in parts: error_case(img, ref)
    if 'setup' in parts: setup_case(img, ref)
    if 'boot' in parts: boot_case(img)
    print('(%.0f s)' % (time.time() - t0))

# ---- mutations: each must fail ----------------------------------------------
def fix_sums(m):
    struct.pack_into('<H', m, 0xF83E, 0)
    struct.pack_into('<H', m, 0xF83E, (-sum(struct.unpack_from('<16384H', m, 0x8000))) & 0xFFFF)
    struct.pack_into('<H', m, 0x6FFE, 0)
    x = 0
    for v in struct.unpack_from('<14336H', m, 0): x ^= v
    struct.pack_into('<H', m, 0x6FFE, x)

def find(m, lo, pat):
    i = bytes(m).find(pat, lo)
    assert i >= 0 and i < lo + 0x200, 'pattern %s not found after %04X' % (pat.hex(), lo)
    return i

def mutants(img):
    L = labels(); out = []
    def mk(name, fn, part):
        m = bytearray(img); fn(m); fix_sums(m); out.append((name, m, part))
    mk('766E: tamper check left on', lambda m: m.__setitem__(0x766E, 0x60), 'normal')
    mk('ACDB: AMI\'s memory count printed', lambda m: m.__setitem__(slice(0xACDB, 0xACE0),
       bytes.fromhex('3d9d007316')), 'memtest')
    mk('bu_final: 40:F0-FF not cleared', lambda m: m.__setitem__(
       slice(find(m, L['bu_final.clr'], b'\xb9\x08\x00'), find(m, L['bu_final.clr'], b'\xb9\x08\x00') + 3),
       b'\xb9\x00\x00'), 'normal')
    mk('ide_identify: master not selected again', lambda m: m.__setitem__(
       find(m, L['ide_identify.end'], b'\xb0\xa0') + 1, 0xB0), 'variants')
    mk('ide_identify: no nIEN, 40:8E not cleared', lambda m: (m.__setitem__(
       find(m, L['ide_identify'], b'\xb0\x02\xee') + 1, 0x00), m.__setitem__(
       slice(find(m, L['ide_identify.end'], b'\xc6\x06\x8e\x00\x00'), find(m, L['ide_identify.end'], b'\xc6\x06\x8e\x00\x00') + 5),
       b'\x90' * 5)), 'busy')
    mk('F000:0008 back to the configuration box', lambda m: m.__setitem__(slice(8, 11), bytes.fromhex('e9f56f')), 'normal')
    mk('93F6: AMI\'s DEL message', lambda m: m.__setitem__(slice(0x93F6, 0x93FC), bytes.fromhex('be3b7ee879f9')), 'setup')
    mk('bu_errors: SI not set to 7AB2', lambda m: m.__setitem__(
       slice(find(m, L['bu_errors'], b'\xbe\xb2\x7a'), find(m, L['bu_errors'], b'\xbe\xb2\x7a') + 3), b'\x90\x90\x90'), 'errors')
    return out

if __name__ == '__main__':
    img, ref = open(ROM, 'rb').read(), open(REF, 'rb').read()
    print('ROM %s\nreference %s' % (os.path.relpath(ROM, ROOT), os.path.relpath(REF, ROOT)))
    if '--mutants-only' not in sys.argv: run_all(img, ref)
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
            print('  %s  %-44s %d failures' % ('ok  ' if fails else 'FAIL', name, len(fails)))
            if not fails: bad += 1
        n += bad
    print('\n%s' % ('ALL PASS' if n == 0 else '%d FAILURES' % n))
    sys.exit(1 if n else 0)
