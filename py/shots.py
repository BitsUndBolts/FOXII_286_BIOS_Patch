#!/usr/bin/env python3
"""Screenshots (PNG) from the emulators, one set per round, into shots/.

    python3 py/shots.py 5a          round 5a: setup menu without RUN DIAGNOSTICS
    python3 py/shots.py             every round this branch has

The screens are rendered by post_emu.py with the IBM VGA 9x16 font
(vgafont.py), 720x400 scaled to 1440x960 (4:3), like the SOYO's shots.
The emulated board is the FOX II: 80C286, no 287, 640 + 3072 KB, the
SanDisk 1 GB card as C: (type 47, 1986/16/63), a 1.44 MB A:, VGA (or MDA).
"""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from post_emu import Post, make_cmos

ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, 'shots')
BIN = lambda n: open(os.path.join(ROOT, 'binary', n), 'rb').read()
DEL, DOWN, ENTER = 0x53, 0x50, 0x1C

def shot(p, name):
    path = os.path.join(OUT, name + '.png')
    p.png(path); print('  shots/%s.png' % name)

def menu(rom, name, **kw):
    p = Post(rom, **kw)
    for t in range(1000, 7000, 500): p.type_key(DEL, at_ms=t)
    p.run(max_ms=12000); shot(p, name)
    return p

def round_5a():
    print('round 5a')
    rom, ref = BIN('FOXII_STEP5A.BIN'), BIN('FOXII_STEP4.BIN')
    menu(ref, '5a_0_step4_menu')
    p = menu(rom, '5a_1_menu')
    p.type_key(DOWN); p.run(max_ms=800); p.type_key(ENTER); p.run(max_ms=1500)
    shot(p, '5a_2_setup_page')
    p = Post(rom); p.run(max_ms=30000); shot(p, '5a_3_end_of_post')
    p = Post(rom, video='mono', cmos=make_cmos(video='mono')); p.run(max_ms=30000)
    shot(p, '5a_4_end_of_post_mono')

def boot_disks(p, floppy386=True):
    """a 386 boot floppy in A: (Step 4 skips it), DOS-like boot sector on C:"""
    p.stop_at_int19 = False
    if floppy386:
        fl = bytearray(1474560)
        bs = bytes.fromhex('fa31c08ed0bc007cfb') + b'\x0f\x0b'
        fl[0:len(bs)] = bs; fl[510:512] = b'\x55\xaa'
        p.floppy = bytes(fl)
    msg = b'Starting MS-DOS...\r\n'
    code = bytes.fromhex('31c08ed8be217cb40eac08c07404cd10ebf7f4ebfd')
    mbr = bytearray(512); mbr[:len(code)] = code; mbr[0x21:0x21 + len(msg) + 1] = msg + b'\0'; mbr[510:] = b'\x55\xaa'
    p.ides[0].sectors[0] = bytes(mbr)

def round_5b():
    print('round 5b')
    rom = BIN('FOXII_STEP5B.BIN')
    p = Post(rom); p.run(max_ms=10000, until=lambda q: q.p80 and q.p80[-1][0] == 0x3C and q.t > 4.0e9)
    shot(p, '5b_1_memory_test')
    p = Post(rom); p.run(max_ms=30000); shot(p, '5b_2_end_of_post')
    p = Post(rom, video='mono', cmos=make_cmos(video='mono')); p.run(max_ms=30000); shot(p, '5b_3_mono')
    p = Post(rom, cmos=bytes(128)); p.run(max_ms=15000); shot(p, '5b_4_errors_cleared_cmos')
    p = Post(rom, cmos=make_cmos(drive=None, drive_d=(3875, 16, 63)), slave=(3875, 16, 63),
             slave_model='SanDisk SDCFB-2048'); p.run(max_ms=30000); shot(p, '5b_5_auto_and_two_disks')
    p = Post(rom); boot_disks(p); p.run(max_ms=40000); shot(p, '5b_6_boot_386_floppy_skipped')
    p = Post(rom); p.ides[0].busy_until = int(3e9); p.run(max_ms=1500); shot(p, '5b_7_disk_still_busy')
    p = Post(rom, drive_model='WDC AC2850F'); p.run(max_ms=30000); p.warm_boot(); p.run(max_ms=30000)
    shot(p, '5b_8_warm_boot_hard_disk')

ROUNDS = {'5a': round_5a, '5b': round_5b}

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for r in (sys.argv[1:] or ROUNDS):
        ROUNDS[r]()
