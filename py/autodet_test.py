#!/usr/bin/env python3
"""Step 3 tests: IDE auto-detection, run through the ROM's own POST code.

    python3 py/autodet_test.py        (pip install unicorn)
    FOXII_ROM=binary/X.BIN python3 py/autodet_test.py     another ROM

Every case runs POST checkpoint 75h (943E) to the end of checkpoint 76h
(945C): the CMOS test, the hook at 9447, and AMI's whole fixed-disk setup
A857 with the second hook at A894 and all of A857's INT 13h calls, against
  - a CMOS (ports 70h/71h, NMI bit ignored),
  - an IDE bus with a master and a slave: present or not, busy for a while
    after the start (spinning up), ATA or ATAPI (aborts IDENTIFY DEVICE),
    what an absent slave reads as (00h, or the master's status echoed) and
    what an empty bus reads as (FFh or 7Fh); writes to 1F6h are ignored
    while the selected drive is busy, as on a real drive,
  - simulated time: every IN/OUT is 1 us, a port 61h read toggles the
    refresh bit and is 7.5 us, and the BIOS tick counter 40:6Ch counts
    55 ms ticks of that time (IRQ 0 itself is not modelled).
The Step 2 ROM (no auto-detection) runs the same cases as the reference.

Checked: CMOS before and after (type 47 written only for "Not installed"
drives that answer, checksum valid; user entries byte for byte
unchanged), what A857 then set up (number of drives, the type-47 drive
parameter table, INT 13h AH=08h through the ECHS translation), AMI's
failure flags, how long POST spends there, the IDE commands sent, the
stack, and that both hooks keep every register except AL.
"""
import os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from unicorn import Uc, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INSN, UC_HOOK_INTR
from unicorn.x86_const import *

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROM   = os.environ.get('FOXII_ROM') or os.path.join(ROOT, 'binary', 'FOXII_STEP6A.BIN')   # the newest step
REF   = os.path.join(ROOT, 'binary', 'FOXII_STEP2.BIN')
CP75, CP76_END = 0x943E, 0x945C
STOP  = 0x0602                     # HLT stub for direct hook calls
PAINT = 0xA5
BUDGET = 160                       # POST stack budget below 0400h (CLAUDE.md)
TICK_US = 54925
lin = lambda s, o: (s << 4) + o

def chs_param(c, h, s, precomp=0xFFFF, ctrl=None, lz=None):
    """the 9 type-47 bytes as AMI's setup stores them"""
    ctrl = (8 if h > 8 else 0) if ctrl is None else ctrl
    lz = c if lz is None else lz
    return struct.pack('<HBHBHB', c, h, precomp, ctrl, lz, s)

def cmos_image(t12=0, t19=0, t1a=0, p_c=None, p_d=None, bad=False):
    c = bytearray(128)
    c[0x0E] = 0xC0 if bad else 0
    c[0x10] = 0x40; c[0x14] = 0x41                     # 1.44 MB floppy, equipment
    c[0x15], c[0x16] = 0x80, 0x02                      # 640 KB base memory
    c[0x12], c[0x19], c[0x1A] = t12, t19, t1a
    if p_c: c[0x1B:0x24] = p_c
    if p_d: c[0x24:0x2D] = p_d
    fix_sum(c)
    return c

def fix_sum(c):
    s = sum(c[0x10:0x2E]); c[0x2E], c[0x2F] = s >> 8, s & 0xFF

def sum_ok(c): return bool(sum(c[0x10:0x2E])) and sum(c[0x10:0x2E]) == (c[0x2E] << 8 | c[0x2F])

class Dev:
    def __init__(s, C=0, H=0, S=0, atapi=False, busy_s=0.0, model='SIM DRIVE'):
        s.C, s.H, s.S, s.atapi, s.busy_until = C, H, S, atapi, busy_s * 1e6
        s.model, s.queue, s.err, s.errreg = model, [], False, 1
    def identify(s):
        w = [0] * 256
        w[0] = 0x045A; w[1] = s.C; w[3] = s.H; w[6] = s.S
        w[4], w[5] = 512 * s.S, 512
        m = s.model.ljust(40).encode()
        for i in range(20): w[27 + i] = (m[2 * i] << 8) | m[2 * i + 1]
        w[49] = 0x0200
        n = s.C * s.H * s.S; w[60], w[61] = n & 0xFFFF, n >> 16
        return w

class Bus:
    def __init__(s, master=None, slave=None, absent_slave=0x00, empty=0xFF):
        s.dev = [master, slave]
        s.absent_slave = absent_slave      # 0x00 (ATA), or 'echo': the master's status
        s.empty = empty                    # FFh floating, 7Fh with DD7 pulled down
        s.sel, s.r = 0, {1: 0, 2: 1, 3: 1, 4: 0, 5: 0, 6: 0xA0}

class Post:
    def __init__(s, rom, cmos, bus):
        s.rom, s.cmos, s.bus = rom, bytearray(cmos), bus
        s.us, s.idx, s.p61, s.log = 0.0, 0, 0, []
        s.mu = mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x100000)
        mu.mem_write(0xF0000, rom)
        mu.mem_write(0x300, rom[0xE260:0xE2C0])          # F1BA: AMI's GDT at 0:0300
        mu.mem_write(lin(0x40, 0x13), struct.pack('<H', 10))   # base memory in 64 KB units until cp 7Dh
        mu.mem_write(lin(0x40, 0x10), struct.pack('<H', 0x0021))
        mu.mem_write(lin(0xF000, STOP), b'\xf4')
        mu.hook_add(UC_HOOK_INSN, s.inp, aux1=UC_X86_INS_IN)
        mu.hook_add(UC_HOOK_INSN, s.outp, aux1=UC_X86_INS_OUT)
        mu.hook_add(UC_HOOK_INTR, s.intr)

    # --- time -------------------------------------------------------------
    def tick(s, dt):
        before = int(s.us // TICK_US); s.us += dt; after = int(s.us // TICK_US)
        if after != before:
            t = struct.unpack('<I', bytes(s.mu.mem_read(lin(0x40, 0x6C), 4)))[0]
            s.mu.mem_write(lin(0x40, 0x6C), struct.pack('<I', (t + after - before) & 0xFFFFFFFF))

    # --- the IDE bus ------------------------------------------------------
    def busy(s, d): return d is not None and s.us < d.busy_until
    def status(s):
        b = s.bus; d = b.dev[b.sel]
        if d is None:
            other = b.dev[1 - b.sel]
            if other is None: return b.empty
            if b.sel == 1 and b.absent_slave == 'echo':
                b.sel = 0; st = s.status(); b.sel = 1; return st
            return 0x00
        if s.busy(d): return 0x80
        if d.queue: return 0x58
        if d.err: return 0x51
        return 0x50

    def inp(s, uc, port, size, ud):
        s.tick(1)
        b = s.bus
        if port == 0x71: return s.cmos[s.idx]
        if port == 0x61:
            s.tick(6.5); s.p61 ^= 0x10; return s.p61
        if port == 0x1F7 or port == 0x3F6: return s.status()
        if port == 0x1F0:
            d = b.dev[b.sel]
            if d is None or not d.queue: return 0xFFFF if size == 2 else 0xFF
            return d.queue.pop(0)
        if port == 0x1F1:
            d = b.dev[b.sel]; return d.errreg if d else b.empty
        if 0x1F2 <= port <= 0x1F6: return b.r[port - 0x1F0]
        return 0xFF

    def outp(s, uc, port, size, val, ud):
        s.tick(1)
        b = s.bus
        if port == 0x70: s.idx = val & 0x7F; return
        if port == 0x71: s.cmos[s.idx] = val & 0xFF; return
        if 0x1F1 <= port <= 0x1F5: b.r[port - 0x1F0] = val; return
        if port == 0x1F6:
            if not s.busy(b.dev[b.sel]):           # ignored while the drive is busy
                b.r[6] = val; b.sel = (val >> 4) & 1
            return
        if port == 0x1F7:
            d = b.dev[b.sel]
            s.log.append((b.sel, val, d is not None))
            if d is None or s.busy(d): return
            d.queue, d.err, d.errreg = [], False, 1
            if val == 0xEC:
                if d.atapi: d.err, d.errreg = True, 0x04
                else: d.queue = d.identify()
            elif val == 0x90:
                d.errreg = 1
            s.mu.mem_write(lin(0x40, 0x8E), b'\xff')   # IRQ 14 (pessimistic: also for ECh)

    def intr(s, uc, intno, ud):
        fl = uc.reg_read(UC_X86_REG_EFLAGS)
        if intno != 0x13:                          # INT 15h 90h/91h, video: nothing to do
            uc.reg_write(UC_X86_REG_EFLAGS, fl & ~1); return
        vec = struct.unpack('<HH', bytes(uc.mem_read(0x13 * 4, 4)))
        sp = uc.reg_read(UC_X86_REG_SP); ss = uc.reg_read(UC_X86_REG_SS)
        for v in (fl & 0xFFFF, uc.reg_read(UC_X86_REG_CS), uc.reg_read(UC_X86_REG_IP)):
            sp = (sp - 2) & 0xFFFF; uc.mem_write(lin(ss, sp), struct.pack('<H', v))
        uc.reg_write(UC_X86_REG_SP, sp)
        uc.reg_write(UC_X86_REG_CS, vec[1]); uc.reg_write(UC_X86_REG_IP, vec[0])

    # --- running ----------------------------------------------------------
    def paint(s): s.mu.mem_write(0x360, bytes([PAINT]) * (0x3FC - 0x360))
    def depth(s):
        st = bytes(s.mu.mem_read(0x360, 0x3FC - 0x360))
        low = next((i for i in range(len(st)) if st[i] != PAINT), len(st))
        return 0x400 - (0x360 + low)

    def run_post(s, stop=CP76_END):
        """checkpoint 75h to 945C, as POST runs it: DS = 40h, ES = 0, SS:SP = 0030:00FC
        (POST has one word on its stack here: 945C pops it), BP = POST error flags"""
        mu = s.mu
        mu.mem_write(lin(0x30, 0xFC), struct.pack('<H', 0x1111))
        s.paint()
        for r, v in ((UC_X86_REG_SS, 0x30), (UC_X86_REG_SP, 0xFC), (UC_X86_REG_DS, 0x40),
                     (UC_X86_REG_ES, 0), (UC_X86_REG_BP, 0), (UC_X86_REG_CS, 0xF000)):
            mu.reg_write(r, v)
        mu.reg_write(UC_X86_REG_EFLAGS, 0x0202)
        mu.emu_start(lin(0xF000, CP75), lin(0xF000, stop), count=1_000_000_000)
        ip = mu.reg_read(UC_X86_REG_IP)
        assert ip == stop, 'did not reach %04X (IP %04X)' % (stop, ip)
        return s

    def int13(s, ax, dx):
        mu = s.mu
        mu.mem_write(lin(0x30, 0xF6), struct.pack('<HHH', STOP, 0xF000, 0x0202))
        for r, v in ((UC_X86_REG_AX, ax), (UC_X86_REG_DX, dx), (UC_X86_REG_CX, 0),
                     (UC_X86_REG_SP, 0xF6), (UC_X86_REG_DS, 0x40), (UC_X86_REG_CS, 0xF000)):
            mu.reg_write(r, v)
        vec = struct.unpack('<HH', bytes(mu.mem_read(0x4C, 4)))
        mu.emu_start(lin(vec[1], vec[0]), lin(0xF000, STOP), count=5_000_000)
        return mu.reg_read(UC_X86_REG_CX), mu.reg_read(UC_X86_REG_DX), mu.reg_read(UC_X86_REG_EFLAGS) & 1

    # --- results ----------------------------------------------------------
    def bda(s, off, n=1): return bytes(s.mu.mem_read(lin(0x40, off), n))
    def fdpt(s, vec):
        o, sg = struct.unpack('<HH', bytes(s.mu.mem_read(vec * 4, 4)))
        p = bytes(s.mu.mem_read(lin(sg, o), 16))
        return (sg, o), (struct.unpack_from('<H', p, 0)[0], p[2], p[14])
    def drives(s): return s.bda(0x75)[0]
    def bp(s): return s.mu.reg_read(UC_X86_REG_BP)
    def ids(s): return [(d, hex(c)) for d, c, present in s.log if c == 0xEC]

fails = 0
def check(name, problems):
    global fails
    print(('  ok   ' if not problems else '  FAIL ') + name + ('' if not problems else ': ' + '; '.join(problems)))
    fails += bool(problems)

def run(rom, cmos, bus, stop=CP76_END): return Post(rom, cmos, bus).run_post(stop)
def ata(C, H, S, **k): return Dev(C, H, S, **k)

def decode08(cx, dx): return (cx >> 8 | (cx & 0xC0) << 2) + 1, (dx >> 8) + 1, cx & 0x3F

rom, ref = open(ROM, 'rb').read(), open(REF, 'rb').read()
print('ROM under test: %s   reference: %s' % (os.path.relpath(ROM, ROOT), os.path.relpath(REF, ROOT)))

# ---------------------------------------------------------------------------
print('\n1. C: "Not installed", a CF card answers (SanDisk SDCFJ-1024, 1986/16/63)')
cm = cmos_image()
p = run(rom, cm, Bus(ata(1986, 16, 63)))
want = bytearray(cm); want[0x12] = 0xF0; want[0x19] = 47; want[0x1B:0x24] = chs_param(1986, 16, 63); fix_sum(want)
pr = []
if p.cmos != want: pr.append('CMOS %s, want %s' % (p.cmos[0x10:0x30].hex(), want[0x10:0x30].hex()))
if not sum_ok(p.cmos): pr.append('checksum')
check('CMOS: 12h=F0, 19h=47, 1Bh-23h = 1986/16/63, precomp none, control 08h, LZ 1986, checksum fixed', pr)
check('IDENTIFY sent once, to the master', [] if p.ids() == [(0, '0xec')] else [str(p.ids())])
(seg, off), geo = p.fdpt(0x41)
check('A857 set the drive up in the same boot: 1 drive, INT 41h -> %04X:%04X = %s' % (seg, off, geo),
      [] if p.drives() == 1 and geo == (1986, 16, 63) else ['drives %d, %s' % (p.drives(), geo)])
check('no POST error flags, CMOS 0Eh bit 3 (disk init failed) clear',
      [] if p.bp() == 0 and not p.cmos[0x0E] & 8 else ['BP %04X, 0Eh %02X' % (p.bp(), p.cmos[0x0E])])
cx, dx, cf = p.int13(0x0800, 0x80)
check('INT 13h AH=08h through ECHS: %d/%d/%d' % decode08(cx, dx),
      [] if decode08(cx, dx) == (992, 32, 63) and not cf else ['CF %d' % cf])
check('detection took %.2f s of simulated time' % (p.us / 1e6), [] if p.us < 1e6 else ['too slow'])
r = run(ref, cm, Bus(ata(1986, 16, 63)))
check('reference (Step 2): CMOS untouched, no drive set up', [] if r.cmos == cm and r.drives() == 0 else ['?'])

# ---------------------------------------------------------------------------
print('\n2. Both "Not installed", master 1986/16/63 and slave 3875/16/63 (2 GB card)')
cm = cmos_image()
p = run(rom, cm, Bus(ata(1986, 16, 63), ata(3875, 16, 63)))
want = bytearray(cm); want[0x12] = 0xFF; want[0x19] = want[0x1A] = 47
want[0x1B:0x24] = chs_param(1986, 16, 63); want[0x24:0x2D] = chs_param(3875, 16, 63); fix_sum(want)
check('CMOS: 12h=FF, 19h/1Ah=47, both parameter blocks, checksum', [] if p.cmos == want and sum_ok(p.cmos) else [p.cmos[0x10:0x30].hex()])
check('A857 set up 2 drives: INT 41h %s, INT 46h %s' % (p.fdpt(0x41)[1], p.fdpt(0x46)[1]),
      [] if p.drives() == 2 and p.fdpt(0x46)[1] == (3875, 16, 63) and p.bp() == 0 else ['?'])
cx, dx, cf = p.int13(0x0800, 0x81)
check('INT 13h AH=08h DL=81h: %d/%d/%d' % decode08(cx, dx), [] if decode08(cx, dx) == (967, 64, 63) else ['?'])

# ---------------------------------------------------------------------------
print('\n3. Drives the user set up are never changed (A/B against Step 2)')
cases = [
    ('C: type 47 = 1024/16/63 entered by hand, the card is 1986/16/63',
     cmos_image(0xF0, 47, 0, chs_param(1024, 16, 63, precomp=0, ctrl=0)), Bus(ata(1986, 16, 63))),
    ('C: type 47 = 1986/16/63, D: "Not installed", no slave',
     cmos_image(0xF0, 47, 0, chs_param(1986, 16, 63)), Bus(ata(1986, 16, 63))),
    ('C: table type 2 (615/4/17), a drive that says 1986/16/63',
     cmos_image(0x20), Bus(ata(1986, 16, 63))),
    ('C: and D: type 47 by hand, both present',
     cmos_image(0xFF, 47, 47, chs_param(1024, 16, 63), chs_param(980, 16, 32)), Bus(ata(1986, 16, 63), ata(980, 16, 32))),
]
for name, cm, mk in cases:
    import copy
    p, r = run(rom, cm, copy.deepcopy(mk)), run(ref, cm, copy.deepcopy(mk))
    pr = []
    st_p = (bytes(p.cmos), p.bda(0, 0x100), p.drives(), p.bp(), [c for c in p.log if c[1] != 0xEC], p.fdpt(0x41), p.fdpt(0x46))
    st_r = (bytes(r.cmos), r.bda(0, 0x100), r.drives(), r.bp(), r.log, r.fdpt(0x41), r.fdpt(0x46))
    if bytes(p.cmos) != bytes(cm): pr.append('CMOS changed')
    if st_p != st_r: pr.append('differs from Step 2')
    if any(d == 0 for d, _ in p.ids()) or (cm[0x12] & 0x0F and p.ids()): pr.append('IDENTIFY sent to a configured drive %s' % p.ids())
    check(name + ': CMOS byte for byte, BDA, drive tables, flags, IDE commands = Step 2', pr)

# ---------------------------------------------------------------------------
print('\n4. A configured drive that is not there is dropped for this boot (CMOS unchanged)')
for empty in (0xFF, 0x7F):
    cm = cmos_image(0xF0, 47, 0, chs_param(1986, 16, 63))
    p, r = run(rom, cm, Bus(empty=empty)), run(ref, cm, Bus(empty=empty))
    check('C: type 47, empty bus (%02Xh): Step 3 %.2f s, Step 2 %.1f s with POST flags %04X'
          % (empty, p.us / 1e6, r.us / 1e6, r.bp()),
          [] if bytes(p.cmos) == bytes(cm) and p.bp() == 0 and p.drives() == 0 and p.us < 1e6
          and r.us > 5e6 and r.bp() else ['CMOS %s BP %04X drives %d %.1fs' % (p.cmos[0x10:0x30].hex(), p.bp(), p.drives(), p.us / 1e6)])
cm = cmos_image(0xFF, 47, 47, chs_param(1986, 16, 63), chs_param(3875, 16, 63))
p, r = run(rom, cm, Bus(ata(1986, 16, 63))), run(ref, cm, Bus(ata(1986, 16, 63)))
check('D: type 47 unplugged, C: present (absent slave reads 00h): C: set up, D: dropped, '
      'Step 3 %.2f s, Step 2 %.1f s with POST flags %04X' % (p.us / 1e6, r.us / 1e6, r.bp()),
      [] if bytes(p.cmos) == bytes(cm) and p.drives() == 1 and p.bp() == 0 and p.fdpt(0x41)[1] == (1986, 16, 63)
      and r.us > 30e6 and r.bp() else ['drives %d BP %04X' % (p.drives(), p.bp())])
p2 = Post(rom, p.cmos, Bus(ata(1986, 16, 63), ata(3875, 16, 63))).run_post()
check('the next boot with D: plugged in again: both drives back, CMOS still the user\'s',
      [] if p2.drives() == 2 and bytes(p2.cmos) == bytes(cm) and p2.bp() == 0 else ['drives %d' % p2.drives()])

# ---------------------------------------------------------------------------
print('\n5. Devices that must not be auto-detected')
cm = cmos_image(0xF0, 47, 0, chs_param(1986, 16, 63))
p = run(rom, cm, Bus(ata(1986, 16, 63), Dev(atapi=True)))
check('ATAPI slave (aborts IDENTIFY DEVICE): D: stays "Not installed", C: as before',
      [] if bytes(p.cmos) == bytes(cm) and p.drives() == 1 and p.ids() == [(1, '0xec')] else [p.cmos[0x10:0x30].hex()])
p = run(rom, cm, Bus(ata(1986, 16, 63), absent_slave='echo'))
check('no slave, the master answers for it with its own status: nothing written, %.2f s lost '
      'waiting for the IDENTIFY answer' % (p.us / 1e6),
      [] if bytes(p.cmos) == bytes(cm) and p.drives() == 1 and 1.9e6 < p.us < 2.5e6 else ['%.2f s' % (p.us / 1e6)])
cm0 = cmos_image()
for bus, what in ((Bus(), 'empty bus'), (Bus(empty=0x7F), 'empty bus reading 7Fh')):
    p = run(rom, cm0, bus)
    check('both "Not installed", %s: nothing written, no command, %.3f s' % (what, p.us / 1e6),
          [] if bytes(p.cmos) == bytes(cm0) and not p.log and p.us < 0.01e6 else ['?'])
for C, H, S in ((0, 16, 63), (1986, 0, 63), (1986, 17, 63), (1986, 16, 0), (1986, 16, 64), (16384, 16, 63)):
    p = run(rom, cm0, Bus(ata(C, H, S)))
    check('IDENTIFY says %d/%d/%d: rejected, CMOS untouched' % (C, H, S), [] if bytes(p.cmos) == bytes(cm0) else ['written'])
p = run(rom, cm0, Bus(ata(16383, 16, 63)))
check('IDENTIFY says 16383/16/63 (a disk over 8.4 GB): accepted', [] if p.cmos[0x12] == 0xF0 and p.drives() == 1 else ['?'])

# ---------------------------------------------------------------------------
print('\n6. A drive that is still spinning up')
for busy, found in ((6, True), (15, False)):
    p = run(rom, cm0, Bus(ata(1986, 16, 63, busy_s=busy)))
    check('master busy for %d s after checkpoint 75h: %s after %.1f s' % (busy, 'detected' if found else 'not detected (10 s limit)', p.us / 1e6),
          [] if (p.cmos[0x12] == 0xF0) == found and (bytes(p.cmos) != bytes(cm0)) == found and sum_ok(p.cmos)
          else [p.cmos[0x10:0x30].hex()])
cm = cmos_image(0xF0, 47, 0, chs_param(1986, 16, 63))
p = run(rom, cm, Bus(ata(1986, 16, 63, busy_s=3)))
check('C: set up by the user and busy for 3 s, D: "Not installed", no slave: the slave probe waits for '
      'the master (a select is ignored while it is busy) and does not mistake it for D:',
      [] if bytes(p.cmos) == bytes(cm) and p.drives() == 1 and not p.ids() else [p.cmos[0x10:0x30].hex(), str(p.ids())])
cm = cmos_image(0xF0, 47, 0, chs_param(1986, 16, 63))
p = run(rom, cm, Bus(ata(1986, 16, 63, busy_s=8)))
r = run(ref, cm, Bus(ata(1986, 16, 63, busy_s=8)))
check('C: set up and busy for 8 s: not dropped, AMI waits for it as before (Step 3 %.1f s, Step 2 %.1f s)'
      % (p.us / 1e6, r.us / 1e6), [] if p.drives() == 1 and p.bp() == r.bp() == 0 else ['drives %d BP %04X' % (p.drives(), p.bp())])

# ---------------------------------------------------------------------------
print('\n7. CMOS invalid (0Eh bits 7:6 set): POST skips the disk setup, and both hooks with it')
cm = cmos_image(bad=True)
p, r = run(rom, cm, Bus(ata(1986, 16, 63))), run(ref, cm, Bus(ata(1986, 16, 63)))
check('nothing written, no command sent, same as Step 2', [] if bytes(p.cmos) == bytes(cm) and not p.log and bytes(r.cmos) == bytes(cm) else ['?'])

# ---------------------------------------------------------------------------
print('\n8. Stack and registers')
cm = cmos_image()
for name, bus in (('auto-detect of both drives', Bus(ata(1986, 16, 63), ata(3875, 16, 63))),
                  ('auto-detect, slave probe times out', Bus(ata(1986, 16, 63), absent_slave='echo'))):
    p = Post(rom, cm, bus); p.run_post(stop=0x944C)        # hook 1 alone (944C: OR AL,AL)
    d = p.depth()
    check('%s, hook at 9447 alone: %d bytes below 0400h (budget %d)' % (name, d, BUDGET), [] if d <= BUDGET else ['over'])
for name, cm, bus in (('detect + A857', cmos_image(), Bus(ata(1986, 16, 63), ata(3875, 16, 63))),
                      ('user drives + A857', cmos_image(0xFF, 47, 47, chs_param(1986, 16, 63), chs_param(980, 16, 32)),
                       Bus(ata(1986, 16, 63), ata(980, 16, 32)))):
    import copy
    p, r = run(rom, cm, copy.deepcopy(bus)), run(ref, cm, copy.deepcopy(bus))
    check('%s, checkpoints 75h-76h: Step 3 %d bytes, Step 2 %d bytes (the deepest is AMI\'s own INT 13h calls)'
          % (name, p.depth(), r.depth()), [] if p.depth() <= BUDGET else ['over'])

import re
labels = {}
_map = os.path.join(ROOT, 'asm', 'step4.map' if 'STEP4' in os.path.basename(ROM).upper() else 'step3.map')
for line in open(_map) if os.path.exists(_map) else []:
    m = re.match(r'\s+([0-9A-F]+)\s+[0-9A-F]+\s+(autodet|drives12)$', line)
    if m: labels[m.group(2)] = int(m.group(1), 16)
REGS = ((UC_X86_REG_BX, 0x1357), (UC_X86_REG_CX, 0x2468), (UC_X86_REG_DX, 0x369C), (UC_X86_REG_SI, 0x4812),
        (UC_X86_REG_DI, 0x5A5A), (UC_X86_REG_BP, 0x6B6B), (UC_X86_REG_DS, 0x40), (UC_X86_REG_ES, 0x0000))
for name in ('autodet', 'drives12'):
    if name not in labels: check('%s keeps the registers' % name, ['no map file: run py/build.py']); continue
    for ah in (0x00, 0xA5):
        q = Post(rom, cmos_image(0xF0, 47, 0, chs_param(1986, 16, 63)), Bus(ata(1986, 16, 63), ata(980, 16, 32)))
        mu = q.mu
        mu.mem_write(lin(0x30, 0xFA), struct.pack('<H', STOP))
        for r_, v in REGS + ((UC_X86_REG_SS, 0x30), (UC_X86_REG_SP, 0xFA), (UC_X86_REG_AX, ah << 8 | 0x92),
                             (UC_X86_REG_CS, 0xF000)):
            mu.reg_write(r_, v)
        mu.reg_write(UC_X86_REG_EFLAGS, 0x0202)
        mu.emu_start(lin(0xF000, labels[name]), lin(0xF000, STOP), count=10_000_000)
        bad = ['%s' % r_ for r_, v in REGS if mu.reg_read(r_) != v]
        if mu.reg_read(UC_X86_REG_AX) >> 8 != ah: bad.append('AH')
        if mu.reg_read(UC_X86_REG_SP) != 0xFC: bad.append('SP')
        al = mu.reg_read(UC_X86_REG_AX) & 0xFF
        if name == 'autodet' and al != 0xFF: bad.append('AL %02X (want FF: D: detected)' % al)
        if name == 'drives12' and al != q.cmos[0x12]: bad.append('AL %02X' % al)
        check('%s keeps every register except AL (AH=%02X in), AL = CMOS 12h = %02X' % (name, ah, al), bad)

print('\n%s' % ('ALL PASS' if not fails else '%d FAILED' % fails))
sys.exit(1 if fails else 0)
