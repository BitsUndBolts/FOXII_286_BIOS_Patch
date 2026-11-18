#!/usr/bin/env python3
"""Step 4 tests: 386 code while booting from A: -> message, then boot from C:.

    python3 py/bootskip_test.py        (pip install unicorn)
    FOXII_ROM=binary/X.BIN python3 py/bootskip_test.py     another ROM

The ROM's own INT 19h (8F80) boots with a simulated diskette in A: (INT 40h
reads return its boot sector) and the simulated IDE disk as C:. The 286's
INT 06h is played as in int6_test.py. A diskette boot sector here does what
a DOS boot sector does first (stack at 0000:7C00, INT 1Eh -> its own copy of
the diskette parameters at 0000:0522), then runs a 386 instruction (UD2,
which no CPU knows: Unicorn stops on it like a 286 on any 386 opcode).

The Step 3 ROM (no skipping) runs the cases that must not change as the
reference.
"""
import struct, sys
from int6_harness import Emu6, run_286, mbr_with, UD2
from ide_harness import *

STEP3 = os.path.join(ROOT, 'binary', 'FOXII_STEP3.BIN')
FLAG = 0x4F0
fails = 0

def report(name, problems):
    global fails
    print(('OK   ' if not problems else 'FAIL ') + name + ('' if not problems else '  ' + '; '.join(problems)))
    fails += bool(problems)

# what a DOS boot sector does first, then a 386 instruction (at 0000:7C14)
DOS_LIKE = bytes.fromhex('fa' '33c0' '8ed0' 'bc007c' '8ed8'      # cli, ss:sp = 0:7C00, ds = 0
                         'c70678002205' 'a37a00' 'fb')          # INT 1Eh -> 0000:0522, sti
FAULT_AT = len(DOS_LIKE)
assert FAULT_AT == 0x14
C_MBR = mbr_with(b'\xf4' + b'C: MBR')          # HLT: the C: boot sector ran

class Emu4(Emu6):
    """Emu6 with a diskette in A: (or none): INT 40h AH=02h copies its boot sector to ES:BX."""
    def __init__(s, rom, floppy=None, stop_at_key=False, **kw):
        super().__init__(rom, **kw)
        s.fd = floppy; s.fdreads = 0; s.stop_at_key = stop_at_key
    def intr(s, uc, intno, ud):
        if intno == 0x16 and s.stop_at_key:                    # "Press any key": stop there
            uc.emu_stop(); return
        if intno == 0x40:
            fl = uc.reg_read(UC_X86_REG_EFLAGS); ax = uc.reg_read(UC_X86_REG_AX)
            if s.fd is None:                                   # no diskette: not ready
                if ax >> 8: uc.reg_write(UC_X86_REG_AX, 0x8000 | (ax & 0xFF)); uc.reg_write(UC_X86_REG_EFLAGS, fl | 1)
                else: uc.reg_write(UC_X86_REG_EFLAGS, fl & ~1)
                return
            if ax >> 8 == 0x02:
                es, bx = uc.reg_read(UC_X86_REG_ES), uc.reg_read(UC_X86_REG_BX)
                uc.mem_write(lin(es, bx), s.fd); s.fdreads += 1
                uc.ctl_remove_cache(lin(es, bx), lin(es, bx) + 512)   # (see ide_harness.py)
                uc.reg_write(UC_X86_REG_AX, 0x0001)
            uc.reg_write(UC_X86_REG_EFLAGS, fl & ~1)
            return
        super().intr(uc, intno, ud)

def boot(rom, floppy=None, disk=C_MBR, preset_flag=None, max_faults=5, stop_at_key=False, **kw):
    e = Emu4(load_rom(rom), floppy=floppy, stop_at_key=stop_at_key, **kw); e.d.img[0] = disk; e.err = None
    mu = e.mu
    # what POST leaves: INT 20h-77h -> F000:EA85 (90BC); INT 1Eh is set by INT 19h itself
    for n in range(0x20, 0x78): mu.mem_write(n * 4, struct.pack('<HH', 0xEA85, 0xF000))
    mu.mem_write(0x4C, struct.pack('<HH', INT13_HD, 0xF000))
    if preset_flag is not None: mu.mem_write(FLAG, struct.pack('<H', preset_flag))
    mu.mem_write(lin(0x30, 0), b'\xa5' * 0xFC)
    mu.reg_write(UC_X86_REG_SS, 0x30); mu.reg_write(UC_X86_REG_SP, 0xFC)
    mu.reg_write(UC_X86_REG_DS, 0x40); mu.reg_write(UC_X86_REG_ES, 0)
    mu.reg_write(UC_X86_REG_CS, 0xF000); mu.reg_write(UC_X86_REG_EFLAGS, 0x0202)
    run_286(e, lin(0xF000, 0x8F80), max_faults=max_faults)
    e.cs, e.ip = mu.reg_read(UC_X86_REG_CS), mu.reg_read(UC_X86_REG_IP)
    e.dl = mu.reg_read(UC_X86_REG_DX) & 0xFF
    e.flag = struct.unpack('<H', bytes(mu.mem_read(FLAG, 2)))[0]
    e.v1e = struct.unpack('<HH', bytes(mu.mem_read(0x78, 4)))
    e.if_ = bool(mu.reg_read(UC_X86_REG_EFLAGS) & 0x200)
    e.ss, e.sp = mu.reg_read(UC_X86_REG_SS), mu.reg_read(UC_X86_REG_SP)
    e.at7c00 = bytes(mu.mem_read(0x7C00, 8))
    e.hdreads = [x for x in e.d.log if x[0] in ('0x20', '0x21')]    # AMI reads with 21h
    st = bytes(mu.mem_read(lin(0x30, 0), 0xFC))
    e.depth = 0x100 - next((i for i in range(len(st)) if st[i] != 0xA5), 0xFC)
    return e

def where(e): return '%04X:%04X' % (e.cs, e.ip)
rom = PATCHED_ROM
print('ROM under test: %s   reference: %s' % (os.path.relpath(rom, ROOT), os.path.relpath(STEP3, ROOT)))

print('\n1. A 386 boot floppy in A:, a bootable C:')
e = boot(rom, floppy=mbr_with(DOS_LIKE + UD2))
p = []
for want in ('Invalid opcode at 0000:7C14 (boot sector)', 'Bytes: 0F 0B 00 00 00 00',
             'The 80286 cannot run this code. It needs a 386 or newer CPU.', 'Drive A: skipped. Booting from C: ...'):
    if want not in e.text: p.append('no %r' % want)
if 'System halted' in e.text: p.append('halted')
report('the message, without "System halted", ends with "Drive A: skipped. Booting from C: ..."', p)
report('then C:\'s boot sector runs: stopped at %s on its HLT, DL=%02Xh, sector %r' % (where(e), e.dl, e.at7c00[1:7]),
       [] if (e.cs, e.ip) == (0, 0x7C01) and e.dl == 0x80 and e.at7c00 == C_MBR[:8] and not e.err else [str(e.err)])
report('one INT 06h; C: read once; A: read once', [] if e.int6 == 1 and len(e.hdreads) == 1 and e.fdreads == 1
       else ['int6 %d, C: reads %d, A: reads %d' % (e.int6, len(e.hdreads), e.fdreads)])
report('INT 1Eh back at F000:EFC7 (the boot sector had moved it to 0000:0522), interrupts on, stack 0030:%04X'
       % e.sp, [] if e.v1e == (0xEFC7, 0xF000) and e.if_ and e.ss == 0x30 else ['INT 1Eh %04X:%04X IF %d SS %04X' % (e.v1e[1], e.v1e[0], e.if_, e.ss)])
report('marker 0000:04F0 = "A-" (A: skipped)', [] if e.flag == 0x2D41 else ['%04X' % e.flag])
print('     message as shown:' + e.text.replace('\r\n', '\n     ').replace('\n\n', '\n'))

print('\n2. Cases that must still halt (Step 2\'s message)')
e = boot(rom, floppy=mbr_with(DOS_LIKE + UD2), disk=mbr_with(UD2))
report('A: and C: both with 386 boot sectors: A: skipped once, C: halts (%d INT 06h)' % e.int6,
       [] if e.text.count('Drive A: skipped') == 1 and e.text.endswith('System halted. Press Ctrl+Alt+Del to restart.\r\n')
       and e.int6 == 2 and 'Invalid opcode at 0000:7C00 (boot sector)' in e.text else [repr(e.text[-120:])])
e = boot(rom, floppy=None, disk=mbr_with(UD2), preset_flag=0x3A41)
report('no diskette, 386 boot sector on C:, a stale "A:" marker left in RAM: halts (INT 19h clears it)',
       [] if 'skipped' not in e.text and 'System halted' in e.text and e.flag == 0 else [repr(e.text[-80:]), '%04X' % e.flag])
DOS_UP = DOS_LIKE + bytes.fromhex('c70684007856' 'c7068600' '3412')  # INT 21h -> 1234:5678 ("DOS is loaded")
e = boot(rom, floppy=mbr_with(DOS_UP + UD2))
report('booted from A:, but INT 21h no longer POST\'s default (DOS loaded): halts',
       [] if 'skipped' not in e.text and 'System halted' in e.text else [repr(e.text[-80:])])

print('\n3. C: does not boot either')
e = boot(rom, floppy=mbr_with(DOS_LIKE + UD2), disk=bytes(512), max_faults=2)
i1 = e.text.find('Drive A: skipped'); i2 = e.text.find('INVALID BOOT DISKETTE'); i3 = e.text.find('Insert BOOT diskette in A:')
report('A: skipped, C: has no boot sector: AMI\'s "INVALID BOOT DISKETTE" / "Insert BOOT diskette in A:" / key, '
       'then INT 19h again from the start (A: skipped again: %d times)' % e.text.count('Drive A: skipped'),
       [] if 0 <= i1 < i2 < i3 and e.text.count('Drive A: skipped') == 2 else [repr(e.text[:300])])

print('\n4. Graphics mode at the fault')
G = DOS_LIKE + bytes.fromhex('b81300cd10')                        # mode 13h, then the 386 instruction
for mono, mode in ((False, 3), (True, 7)):
    e = boot(rom, floppy=mbr_with(G + UD2), mono=mono)
    report('%s: mode %d set before the message, then C: boots' % ('monochrome' if mono else 'colour', mode),
           [] if e.modesets[-1:] == [mode] and 'Drive A: skipped' in e.text and (e.cs, e.ip) == (0, 0x7C01) else [str(e.modesets)])

print('\n5. Everything else as in Step 3 (A/B)')
GOOD_A = mbr_with(b'\xf4' + b'A: boot')
for name, kw in (('a good boot floppy in A:', dict(floppy=GOOD_A)),
                 ('no diskette, C: boots', dict(floppy=None)),
                 ('no diskette, C: has no boot sector', dict(floppy=None, disk=bytes(512), stop_at_key=True))):
    a, b = boot(rom, **kw), boot(STEP3, **kw)
    same = (a.text, where(a), a.dl, a.at7c00, a.v1e, a.int6, len(a.hdreads), a.fdreads) == \
           (b.text, where(b), b.dl, b.at7c00, b.v1e, b.int6, len(b.hdreads), b.fdreads)
    report('%s: same as Step 3 (stopped at %s, DL=%02Xh), boot-path stack %d bytes (Step 3: %d)'
           % (name, where(a), a.dl, a.depth, b.depth), [] if same and a.depth <= 160 else ['differs'])

print('\n%s' % ('ALL PASS' if not fails else '%d FAILED' % fails))
sys.exit(1 if fails else 0)
