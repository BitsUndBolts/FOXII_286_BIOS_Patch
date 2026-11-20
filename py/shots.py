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

def round_6a():
    print('round 6a')
    import setup_test as T
    rom = BIN('FOXII_STEP6A.BIN')
    names = ['summary', 'standard', 'advanced', 'chipset', 'tools', 'exit']
    for video, tag in (('vga', ''), ('mono', '_mono')):
        kw = dict(video='mono', cmos=make_cmos(video='mono')) if video == 'mono' else {}
        p = T.enter(rom, **kw)
        for i, n in enumerate(names):
            shot(p, '6a_%d_%s%s' % (i + 1, n, tag)); T.press(p, [T.TAB])
    p = T.enter(rom)                                   # typing a date; a message
    T.our_goto(p, 'date'); T.press(p, ['0704']); shot(p, '6a_7_typing_the_date')
    T.press(p, [T.ESC]); T.our_goto(p, 'c_sec'); T.press(p, ['64', T.ENTER]); shot(p, '6a_8_not_taken')
    T.press(p, [T.TAB, T.TAB, T.TAB, T.TAB]); T.our_goto(p, 'quit'); T.press(p, [T.ENTER]); shot(p, '6a_9_exit_question')
    for n, sch in enumerate(['teal', 'amber', 'green', 'classic_blue', 'grey', 'ami']):
        if n == 0: continue
        v = n << 4
        p = Post(rom, cmos=make_cmos(extra={0x3E: v, 0x3F: v ^ 0xA5})); p.run(max_ms=30000)
        shot(p, '6a_10_post_%s' % sch)
        if n in (1, 3, 5):
            p = T.enter(rom, cmos=make_cmos(extra={0x3E: v, 0x3F: v ^ 0xA5})); T.press(p, [T.TAB])
            shot(p, '6a_11_setup_%s' % sch)
    v = 0x01
    p = Post(rom, cmos=make_cmos(extra={0x3E: v, 0x3F: v ^ 0xA5})); p.run(max_ms=30000)
    shot(p, '6a_12_post_boot_c_then_a')
    v = 0x02
    p = T.boot_run(rom, 2, True, False); shot(p, '6a_13_c_only_no_boot_sector')
    v = 0x04
    p = Post(rom, cmos=make_cmos(drive=None, extra={0x3E: v, 0x3F: v ^ 0xA5}), drive=(3875, 16, 63),
             drive_model='SanDisk SDCFB-2048'); p.run(max_ms=30000)
    shot(p, '6a_14_post_autodetect_off')
    p = T.enter(rom, cmos=make_cmos(drive=2)); T.press(p, [T.TAB, T.TAB, T.TAB, T.TAB, T.ENTER], 600)
    shot(p, '6a_15_tools_detect_c')
    p = Post(rom); p.run(max_ms=30000); p.warm_boot(); p.run(max_ms=30000); shot(p, '6a_16_warm_boot')
    # 0.6.1: DEL feedback, the auto-detect row before checkpoint 75h, the boot below the screen
    reached = lambda c: (lambda q: any(x == c for x, _ in q.p80))
    p = Post(rom); p.run(max_ms=30000, until=reached(0x3C)); p.run(max_ms=500)
    p.type_key(DEL); p.run(max_ms=150); shot(p, '6a_17_del_in_memory_test')
    p = Post(rom, cmos=make_cmos(drive=None), drive=(3875, 16, 63), drive_model='SanDisk SDCFB-2048')
    p.run(max_ms=30000, until=reached(0x3C)); p.run(max_ms=500); shot(p, '6a_18_autodetect_pending')
    p = T.boot_run(rom, 1, True, True); shot(p, '6a_19_boot_below_post_screen')

def round_6b():
    print('round 6b')
    import tools_test as TT
    import setup_test as T
    rom = BIN('FOXII_STEP6B.BIN')
    p = Post(rom, cmos=TT.ems_cmos(), ext_kb=2048); p.run(max_ms=30000); shot(p, '6b_1_post_ems_xms')
    p = Post(rom); p.ides[0].sectors.update(TT.disk(64, 63)); p.run(max_ms=30000)
    shot(p, '6b_2_post_partition_warning')
    p = T.enter(rom); T.press(p, [T.TAB] * 4); shot(p, '6b_3_tools')
    p = TT.tool(rom, 'infoc'); shot(p, '6b_4_disk_info')
    p = TT.tool(rom, 'partc', secs=TT.disk(32, 63)); shot(p, '6b_5_partition_check')
    p = TT.tool(rom, 'partc', secs=TT.disk(64, 63)); shot(p, '6b_6_partition_check_64_heads')
    p = TT.tool(rom, 'speedc', 12000, secs=TT.disk(32, 63)); shot(p, '6b_7_disk_speed')
    p = TT.tool(rom, 'mem', 150000, cmos=TT.ems_cmos(), ext_kb=2048, ems_kb=1024); shot(p, '6b_8_memory_test')
    p = TT.tool(rom, 'umb', 300); shot(p, '6b_9_ht12umb')
    p = Post(rom); p.run(max_ms=40000, until=lambda q: q.p80 and q.p80[-1][0] == 0x74)
    p.type_key(0x2E); p.run(max_ms=400); shot(p, '6b_10_boot_key_c')

def round_073():
    print('0.7.3')
    from post_emu import fix_cmos
    rom = BIN('FOXII_STEP6B.BIN')
    p = Post(rom); p.run(max_ms=1200); shot(p, '073_1_memory_test_keys')
    cm = make_cmos(drive=(4000, 16, 63), extra={0x3E: 0x04, 0x3F: 0x04 ^ 0xA5}); fix_cmos(cm)
    p = Post(rom, cmos=bytes(cm)); p.run(max_ms=12000); shot(p, '073_2_f1_prompt_del')
    p = Post(rom); p.run(max_ms=30000); shot(p, '073_3_post_auto')

ROUNDS = {'5a': round_5a, '5b': round_5b, '6a': round_6a, '6b': round_6b, '073': round_073}

if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    for r in (sys.argv[1:] or ROUNDS):
        ROUNDS[r]()
