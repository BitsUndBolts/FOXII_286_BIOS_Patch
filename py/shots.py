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

ROUNDS = {'5a': round_5a}

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for r in (sys.argv[1:] or ROUNDS):
        ROUNDS[r]()
