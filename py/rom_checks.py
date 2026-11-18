#!/usr/bin/env python3
"""Run the BIOS's OWN integrity checks on a ROM image in the emulator.

    python3 py/rom_checks.py [image]     (default: the newest build, binary/FOXII_STEP4.BIN)

Each check executes the original routine from the ROM and reads its result,
so the test cannot share a mistake with a reimplementation in Python:

  POST checkpoint 02  8147-8155  word sum of F000:8000-FFFF must be 0
                                 (fails: beep code 9, POST stops at 02)
  diagnostics module  C983-C997  AA55 header + XOR of 0000-6FFF must be 0
                                 (fails: "ROM-BIOS CHECKSUM ERROR", halt)
  AMI tamper check 1  76BC-76CD  24h bytes at 7649 == bytes at FF97
  AMI tamper check 2  FA4F-FA62  4Ch bytes at FF70 == NOT bytes at FA00

and, since Step 3, the text POST prints with its own printer:

  copyright line      F042-F053  the string at E300 up to its 00h (E32C) must
                                 print exactly as on the original ROM (Step 3's
                                 first build overwrote that 00h: on a warm boot
                                 the line ran on into the new code)
"""
import os, sys
from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INTR
from unicorn.x86_const import UC_X86_REG_CS, UC_X86_REG_SS, UC_X86_REG_SP, UC_X86_REG_EFLAGS, UC_X86_REG_IP, UC_X86_REG_AX

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECKS = (('POST checkpoint 02: word sum 8000-FFFF', 0x8147, 0x8155),
          ('diagnostics module: AA55 + XOR 0000-6FFF', 0xC983, 0xC997),
          ('AMI tamper check at 76BC', 0x76BC, 0x76CD),
          ('AMI tamper check at FA4F', 0xFA4F, 0xFA62))

TEXTS = (('POST copyright line (F042, string at E300)', 0xF042, 0xF053),)
ORIG = os.path.join(ROOT, 'base', 'FOXII_0613_ORIGINAL.BIN')

def printed(img, start, stop):
    """What the ROM's printer at start prints through INT 10h AH=0Eh until it reaches stop."""
    mu = Uc(UC_ARCH_X86, UC_MODE_16); mu.mem_map(0, 0x100000)
    mu.mem_write(0xF0000, img)
    out = bytearray()
    def intr(uc, n, ud):
        ax = uc.reg_read(UC_X86_REG_AX)
        if n == 0x10 and ax >> 8 == 0x0E: out.append(ax & 0xFF)
    mu.hook_add(UC_HOOK_INTR, intr)
    mu.reg_write(UC_X86_REG_CS, 0xF000); mu.reg_write(UC_X86_REG_SS, 0x30); mu.reg_write(UC_X86_REG_SP, 0x100)
    try:
        mu.emu_start(0xF0000 + start, 0xF0000 + stop, count=200000)
    except UcError:
        pass
    return bytes(out), mu.reg_read(UC_X86_REG_IP) == stop

def run_checks(img, verbose=True):
    ok_all = True
    for name, start, stop in CHECKS:
        mu = Uc(UC_ARCH_X86, UC_MODE_16); mu.mem_map(0, 0x100000)
        mu.mem_write(0xF0000, img)
        mu.reg_write(UC_X86_REG_CS, 0xF000); mu.reg_write(UC_X86_REG_SS, 0x30); mu.reg_write(UC_X86_REG_SP, 0x100)
        try:
            mu.emu_start(0xF0000 + start, 0xF0000 + stop, count=200000)
        except UcError:
            pass
        reached = mu.reg_read(UC_X86_REG_IP) == stop
        zf = bool(mu.reg_read(UC_X86_REG_EFLAGS) & 0x40)
        ok = reached and zf
        ok_all &= ok
        if verbose: print('  %s %s' % ('ok  ' if ok else 'FAIL', name))
    orig = open(ORIG, 'rb').read()
    for name, start, stop in TEXTS:
        want, _ = printed(orig, start, stop)
        got, reached = printed(img, start, stop)
        ok = reached and got == want
        ok_all &= ok
        if verbose: print('  %s %s%s' % ('ok  ' if ok else 'FAIL', name,
                                        '' if ok else ': prints %r' % got[len(want) - 4:len(want) + 12]))
    return ok_all

if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'binary', 'FOXII_STEP4.BIN')
    img = open(path, 'rb').read()
    assert len(img) == 65536, 'not a 64 KB CPU image'
    print(os.path.relpath(path, ROOT))
    ok = run_checks(img)
    print('ALL PASS' if ok else 'FAILED')
    sys.exit(0 if ok else 1)
