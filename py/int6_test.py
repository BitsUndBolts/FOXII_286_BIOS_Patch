#!/usr/bin/env python3
"""Step 2 test: an invalid opcode stops with a message instead of looping.

    python3 py/int6_test.py      (pip install unicorn)

Unicorn emulates a 386 or later, so 386 instructions run fine in it. The test
uses UD2 (0F 0B), undefined on every CPU including the 286: Unicorn raises
INT 06h for it like the 286 does for a 386 instruction, with the return
address on the faulting instruction.

1. Boot sector: the ROM's own INT 19h path loads an MBR that starts with UD2
   from the simulated disk and jumps to it. The original ROM must loop on the
   opcode (the hang seen on the board); the Step 2 ROM must print the message
   with the address and "(boot sector)", leave only the keyboard IRQ unmasked,
   point INT 09h back at the BIOS and halt.
2. A program in a graphics mode (mode 13h): the handler switches to text mode
   3 first, or mode 7 when the BIOS equipment word says monochrome.
3. AMI's own cases are unchanged: a LOCK prefix is stepped over and the
   program continues, on both ROMs alike.
"""
import struct, sys
from ide_harness import *
from int6_harness import Emu6, run_286, mbr_with, UD2

STEP2_ROM = PATCHED_ROM          # the ROM under test: the newest step, FOXII_ROM= picks another
fails = 0

def report(name, problems):
    global fails
    print(('OK   ' if not problems else 'FAIL ') + name + ('' if not problems else '  ' + '; '.join(problems)))
    fails += bool(problems)

def boot(rom_path, mbr, **kw):
    e = Emu6(load_rom(rom_path), **kw); e.d.img[0] = mbr; e.err = None
    mu = e.mu
    mu.reg_write(UC_X86_REG_SS, 0x30); mu.reg_write(UC_X86_REG_SP, 0x100)
    mu.reg_write(UC_X86_REG_DS, 0x40); mu.reg_write(UC_X86_REG_ES, 0)
    mu.reg_write(UC_X86_REG_CS, 0xF000)
    run_286(e, lin(0xF000, 0x8F80))
    e.cs, e.ip = mu.reg_read(UC_X86_REG_CS), mu.reg_read(UC_X86_REG_IP)
    return e

print('1. A boot sector with an invalid opcode')
e = boot(ORIG_ROM, mbr_with(UD2))
report('original ROM loops on the opcode (stopped after %d times INT 06h, at %04X:%04X)' % (e.int6, e.cs, e.ip),
       [] if e.int6 >= 200 and (e.cs << 4) + e.ip == 0x7C00 and not e.text else ['expected an endless INT 06h loop'])

e = boot(STEP2_ROM, mbr_with(UD2))
p = []
t = e.text
for want in ('Invalid opcode at 0000:7C00', '(boot sector)', 'Bytes: 0F 0B 00 00 00 00',
             'It needs a 386 or newer CPU', 'Press Ctrl+Alt+Del'):
    if want not in t: p.append('missing "%s"' % want)
if e.int6 != 1: p.append('INT 06h %d times' % e.int6)
if not (0xF0000 + 0xF69E <= (e.cs << 4) + e.ip < 0xF0000 + 0xF83E): p.append('stopped at %04X:%04X, not in the handler' % (e.cs, e.ip))
masks = dict((pt, v) for pt, v in e.ports if pt in (0x21, 0xA1))
if masks.get(0x21) != 0xFD or masks.get(0xA1) != 0xFF: p.append('PIC masks %s' % masks)
if sum(1 for pt, v in e.ports if pt in (0x20, 0xA0) and v == 0x20) < 2: p.append('no EOI')
v9 = struct.unpack('<HH', bytes(e.mu.mem_read(0x24, 4)))
if v9 != (0xE987, 0xF000): p.append('INT 09h = %04X:%04X' % (v9[1], v9[0]))
if e.modesets: p.append('changed the video mode in text mode')
report('the patched ROM (%s) prints the message and halts' % os.path.basename(STEP2_ROM), p)
print('       ' + t.strip().replace('\r\n', '\n       ').replace('\r', ''))

print('\n2. Graphics mode')
e = boot(STEP2_ROM, mbr_with(UD2), mode=0x13)
report('colour: mode 13h -> mode 3 before the message', [] if e.modesets == [3] and 'Invalid opcode' in e.text else ['modes set %s' % e.modesets])
e = boot(STEP2_ROM, mbr_with(UD2), mode=0x13, mono=True)
report('monochrome: mode 13h -> mode 7', [] if e.modesets == [7] and 'Invalid opcode' in e.text else ['modes set %s' % e.modesets])

print('\n3. AMI\'s LOCK handling is unchanged')
# A real 286 never faults on LOCK; AMI's LOCK skip is code shared with 386 BIOSes.
# Enter AMI's INT 06h handler as if a LOCK NOP at 0000:7C00 had faulted: it must
# step over the prefix and IRET to 7C01, on both ROMs alike.
for name, path in (('original', ORIG_ROM), (os.path.basename(STEP2_ROM), STEP2_ROM)):
    e = Emu6(load_rom(path)); e.err = None
    mu = e.mu
    mu.mem_write(0x7C00, b'\xf0\x90\xf4')            # LOCK NOP HLT
    mu.mem_write(lin(0x30, 0xFA), struct.pack('<HHH', 0x7C00, 0x0000, 0x0202))
    mu.reg_write(UC_X86_REG_SS, 0x30); mu.reg_write(UC_X86_REG_SP, 0xFA)
    mu.reg_write(UC_X86_REG_CS, 0xF000); mu.reg_write(UC_X86_REG_DS, 0)
    run_286(e, lin(0xF000, 0xEB31))
    stop = (mu.reg_read(UC_X86_REG_CS) << 4) + mu.reg_read(UC_X86_REG_IP)
    report('%s: LOCK stepped over, the program goes on and reaches its HLT' % name,
           [] if stop == 0x7C03 and not e.text else ['stopped at %05X, text %r' % (stop, e.text)])

print('\nALL PASS' if not fails else '\n%d FAILED' % fails)
sys.exit(1 if fails else 0)
