#!/usr/bin/env python3
"""Run the ROM's own INT 19h boot path (F000:8F80) against a simulated hard
disk whose sector 0 carries an AA55 signature, with no diskette in A:.
The BIOS must give up on A:, read the MBR from LBA 0, accept it and jump
to 0000:7C00 - for the original ROM and for the ECHS ROM at every geometry.

    python3 py/boot_test.py      (pip install unicorn)
"""
import sys
from ide_harness import *

INT19 = 0x8F80
mbr = bytearray(512); mbr[0x1FE:0x200] = b'\x55\xaa'; mbr[0:2] = b'\xfa\x33'
cases = [('ORIGINAL', ORIG_ROM, (980, 16, 32))] + \
        [('ECHS', PATCHED_ROM, g) for g in ((980, 16, 32), (1986, 16, 63), (3875, 16, 63),
                                             (7773, 16, 63), (16000, 16, 63))]
fails = 0
for name, path, geo in cases:
    e = Emu(load_rom(path), *geo); e.d.img[0] = bytes(mbr)
    mu = e.mu
    mu.reg_write(UC_X86_REG_SS, 0x30); mu.reg_write(UC_X86_REG_SP, 0x100)
    mu.reg_write(UC_X86_REG_CS, 0xF000); mu.reg_write(UC_X86_REG_DS, 0x40)
    mu.reg_write(UC_X86_REG_ES, 0)
    mu.mem_write(lin(0x30, 0), PAINT * 0x100)
    try:
        mu.emu_start(lin(0xF000, INT19), 0x7C00, count=5000000)
        cs, ip = mu.reg_read(UC_X86_REG_CS), mu.reg_read(UC_X86_REG_IP)
        lbas = [x[-1] for x in e.d.log]
        sig = bytes(mu.mem_read(0x7DFE, 2)).hex()
        st = bytes(mu.mem_read(lin(0x30, 0), 0x100))
        depth = 0x100 - next(i for i in range(0x100) if st[i] != PAINT[0])
        ok = (cs << 4) + ip == 0x7C00 and sig == '55aa' and lbas == [0]
        print('%s %-8s %5d/%2d/%d  at %04x:%04x  MBR read from LBA %s  signature %s  stack %d bytes'
              % ('OK  ' if ok else 'FAIL', name, *geo, cs, ip, lbas, sig, depth))
    except UcError as ex:
        ok = False
        print('FAIL %-8s %s  emulator error %s at %04x' % (name, geo, ex, mu.reg_read(UC_X86_REG_IP)))
    fails += not ok
print('\nALL PASS' if not fails else '\n%d FAILED' % fails)
sys.exit(1 if fails else 0)
