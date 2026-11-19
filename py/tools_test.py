#!/usr/bin/env python3
"""Round 6b tests: the tools of BUBios/286 0.7 and the POST screen changes.

    python3 py/tools_test.py              all parts (about 15 minutes)
    python3 py/tools_test.py umb boot     some parts
    FOXII_ROM=binary/X.BIN python3 py/tools_test.py

Parts:
  umb      HT12UMB.SYS in the slot F000:6000-67FF (the file, zeros, the tag,
           its check word) and the Tools page that shows the DEBUG recipe
  bar      the memory bar with the EMS size raised (17h/18h 2048, 30h/31h
           3072): full when AMI's count ends (6a stopped at 72%), and the
           Base / XMS / EMS line, from CMOS while counting and at the end
  screen   the end-of-POST screen against 6a: only the title, the BIOS row
           and the new memory row differ
  info     Disk info C: (IDENTIFY), D: (none), Enter = auto-detect as type 47
  part     Partition check: a table that fits, one made with 64 heads, a BPB
           with 16 heads, an extended chain; the POST warning line
  speed    Disk speed: three KB/s readings and an access time
  mem      Memory test: base, extended, EMS pages (HT12 window, emulated);
           a stuck bit in an EMS page is found with its address and bit
  stack    every tool in one setup visit, ESC back each time, then Exit
           without saving: POST must still reach INT 19h (setup's stack
           wraps to 0:FFxx-102FF; the tools must leave it alone)
  bootkey  A / C during POST: the memory test, the DEL window, after 7Fh
"""
import hashlib, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from post_emu import Post, make_cmos, fix_cmos
import setup_test as T

ROOT = os.path.dirname(HERE)
ROM  = os.environ.get('FOXII_ROM') or os.path.join(ROOT, 'binary', 'FOXII_STEP6B.BIN')
REF  = os.path.join(ROOT, 'binary', 'FOXII_STEP6A.BIN')
UMB  = os.path.join(ROOT, 'extra', 'HT12UMB.SYS')
TAB, DOWN, ENTER, ESC, KEY_Y = 0x0F, 0x50, 0x1C, 0x01, 0x15
TOOLS = ['infoc', 'infod', 'partc', 'partd', 'speedc', 'speedd', 'mem', 'umb']

fails = []
def check(ok, what):
    print('  %s  %s' % ('ok  ' if ok else 'FAIL', what))
    if not ok: fails.append(what)
    return ok
def rows(p): return [l.rstrip() for l in p.text().splitlines()] + [''] * 25
def norm(s): return ' '.join(s.split())

# ---------------------------------------------------------------- disks
def chs(lba, H, S):
    c = min(lba // (H * S), 1023); r = lba % (H * S)
    return bytes([r // S, (r % S + 1) | ((c >> 8) << 6), c & 0xFF])
def entry(boot, typ, start, size, H, S, rel=None):
    return (bytes([boot]) + chs(start, H, S) + bytes([typ]) + chs(start + size - 1, H, S)
            + struct.pack('<II', start if rel is None else rel, size))
def bootsec(H, S, hidden):
    b = bytearray(512); b[0:3] = b'\xeb\x3c\x90'; b[3:11] = b'MSDOS5.0'
    struct.pack_into('<HBHBHHBHHHII', b, 11, 512, 32, 1, 2, 512, 0, 0xF8, 250, S, H, hidden, 0)
    b[510:] = b'\x55\xaa'; return bytes(b)
def disk(H, S, logical=True, bpbH=None):
    """a FAT16 primary, and an extended partition with two logical drives,
    all on cylinder boundaries of H heads / S sectors"""
    cyl = H * S; secs = {}; mbr = bytearray(512)
    mbr[0x1BE:0x1CE] = entry(0x80, 0x06, S, 400 * cyl - S, H, S)
    secs[S] = bootsec(bpbH or H, S, S)
    if logical:
        es = 400 * cyl
        mbr[0x1CE:0x1DE] = entry(0, 0x05, es, 500 * cyl, H, S)
        e1 = bytearray(512)
        e1[0x1BE:0x1CE] = entry(0, 0x06, es + S, 200 * cyl - S, H, S, rel=S)
        e1[0x1CE:0x1DE] = entry(0, 0x05, es + 200 * cyl, 300 * cyl, H, S, rel=200 * cyl)
        e1[510:] = b'\x55\xaa'; secs[es] = bytes(e1); secs[es + S] = bootsec(bpbH or H, S, S)
        e2 = bytearray(512)
        e2[0x1BE:0x1CE] = entry(0, 0x06, es + 200 * cyl + S, 300 * cyl - S, H, S, rel=S)
        e2[510:] = b'\x55\xaa'; secs[es + 200 * cyl] = bytes(e2)
        secs[es + 200 * cyl + S] = bootsec(bpbH or H, S, S)
    mbr[510:] = b'\x55\xaa'; secs[0] = bytes(mbr)
    return secs
def bootcode(msg):
    code = bytes.fromhex('31c08ed8be217cb40eac08c07404cd10ebf7f4ebfd')
    b = bytearray(512); b[:len(code)] = code; b[0x21:0x21 + len(msg) + 1] = msg + b'\0'
    b[510:] = b'\x55\xaa'; return bytes(b)
def ems_cmos(ext=2048, ems=16, prev=None):
    c = make_cmos(ext_kb=ext, extra={0x35: 48, 0x36: ems})
    if prev: c[0x30:0x32] = struct.pack('<H', prev)
    fix_cmos(c); return bytes(c)

def tool(img, name, ms=600, secs=None, stuck=None, **kw):
    """setup, Tools page, Enter on a tool; returns the Post"""
    p = T.enter(img, **kw)
    if secs: p.ides[0].sectors.update(secs)
    if stuck: p.ems_stuck = stuck
    T.press(p, [TAB] * 4); T.press(p, [DOWN] * TOOLS.index(name)); T.press(p, [ENTER], ms)
    return p

# ---------------------------------------------------------------- parts
def umb_case(img, ref):
    print('HT12UMB.SYS in the ROM')
    drv = open(UMB, 'rb').read()
    check(hashlib.md5(drv).hexdigest() == 'ce87362d4f0b50ff6a3ba7fbaad9ddb4' and len(drv) == 1813,
          'extra/HT12UMB.SYS is HT12UMB 1.0 (1813 bytes)')
    check(img[0x6000:0x6000 + len(drv)] == drv, 'the driver at F000:6000')
    check(not any(img[0x6000 + len(drv):0x6800]), 'zeros after it up to 67FF')
    check(img[0x5FF0:0x5FF6] == b'BUBUMB' and img[0x5FF6:0x5FFA] == b'1.0\0'
          and struct.unpack_from('<H', img, 0x5FFA)[0] == len(drv), 'the tag at 5FF0: BUBUMB, 1.0, length')
    s = (sum(struct.unpack_from('<1024H', img, 0x6000)) + struct.unpack_from('<H', img, 0x5FFC)[0]) & 0xFFFF
    check(s == 0, 'the tag\'s check word balances the slot')
    p = tool(img, 'umb', 300)
    r = rows(p)
    check(norm(r[3]) == 'HT12UMB.SYS in this BIOS', 'page title')
    check(norm(r[5]) == 'Driver HT12UMB 1.0, 1813 bytes at F000:6000, checksum OK', r[5].strip())
    rec = [norm(x) for x in r[8:15]]
    check(rec == ['C:\\>DEBUG', '-N C:\\DOS\\HT12UMB.SYS', '-M F000:6000 L800 100', '-R CX', ':800', '-W', '-Q'],
          'the DEBUG recipe: %s' % ' | '.join(rec))
    check(norm(r[16]) == 'DEVICE=C:\\DOS\\HT12UMB.SYS' and norm(r[17]) == 'DOS=HIGH,UMB', 'CONFIG.SYS lines')
    check(norm(r[24]) == 'ESC:Back', 'key row: ESC:Back')
    T.press(p, [ESC], 300)
    check(norm(rows(p)[15]) == 'Get HT12UMB.SYS (UMB driver in this BIOS)', 'ESC: back on the Tools page')
    # a damaged slot is reported
    bad = bytearray(img); bad[0x6100] ^= 1; bad[0x6FFE] ^= 1    # (the module XOR 0000-6FFF still 0)
    p = tool(bytes(bad), 'umb', 300)
    check('checksum WRONG' in rows(p)[5], 'a changed byte in the slot: %s' % rows(p)[5].strip()[-16:])

def bar_case(img, ref):
    print('the memory bar after raising the EMS size; the Base / XMS / EMS line')
    def at_end_of_count(rom, cmos, ext):
        p = Post(rom, cmos=cmos, ext_kb=ext)
        p.run(max_ms=30000, until=lambda q: any(c == 0x50 for c, *_ in q.p80))
        u, t = struct.unpack('<HH', p.mu.mem_read(0x4F2, 4))
        return p, u, t
    p, u, t = at_end_of_count(ref, ems_cmos(prev=3072), 2048)
    check(u < t, '6a (the bug, for reference): %d of %d blocks when the count ends' % (u, t))
    p, u, t = at_end_of_count(img, ems_cmos(prev=3072), 2048)
    check(u == t == 42, 'EMS raised: the bar full when the count ends (%d of %d)' % (u, t))
    check(norm(rows(p)[8]) == 'Base 640 KB XMS 2048 KB EMS 1024 KB', 'while counting: %s' % norm(rows(p)[8]))
    p, u, t = at_end_of_count(img, ems_cmos(ext=3072, ems=0, prev=2048), 3072)
    check(u == t == 58, 'EMS lowered: full (%d of %d)' % (u, t))
    p = Post(img, cmos=ems_cmos(), ext_kb=2048); p.run(max_ms=30000)
    check(norm(rows(p)[7]).endswith('2688 KB') and norm(rows(p)[8]) == 'Base 640 KB XMS 2048 KB EMS 1024 KB',
          'end of POST, 1024K EMS: %s / %s' % (norm(rows(p)[7])[-8:], norm(rows(p)[8])))
    p = Post(img); p.run(max_ms=30000)
    check(norm(rows(p)[8]) == 'Base 640 KB XMS 3072 KB EMS None', 'end of POST, no EMS: %s' % norm(rows(p)[8]))

def screen_case(img, ref):
    print('the end-of-POST screen against 6a')
    a = Post(ref); a.run(max_ms=30000); b = Post(img); b.run(max_ms=30000)
    ra, rb = rows(a), rows(b)
    diff = [i for i in range(25) if ra[i] != rb[i]]
    check(diff == [0, 5, 8], 'rows that differ: %s (title, BIOS, memory line)' % diff)
    check(rb[0].startswith(' BUBios/286 0.7 ') and rb[5].strip().endswith('BUBios/286 0.7'), 'version 0.7')
    check(a.stop == b.stop == 'int19', 'both reach INT 19h')
    check(bytes(b.mu.mem_read(0x4F0, 16)) == bytes(16), '40:F0-FF cleared at INT 19h (no boot key)')

def info_case(img, ref):
    print('Disk info and auto-detect')
    p = tool(img, 'infoc')
    r = [norm(x) for x in rows(p)]
    check(r[3] == 'Hard disk C: (IDE master)', r[3])
    check(r[5] == 'Model SanDisk SDCFJ-1024 CF card', r[5])
    check(r[6] == 'Serial number BU20TEST0001' and r[7] == 'Firmware HDX 4.04', '%s / %s' % (r[6], r[7]))
    check(r[9] == 'Geometry 1986/16/63 default current 1986/16/63', r[9])
    check(r[10] == 'Capacity 2001888 sectors, 977 MB, LBA', r[10])
    check(r[11].startswith('Transfer PIO mode'), r[11])
    check(r[13] == 'Setup Type 47 1986/16/63', r[13])
    check(r[14] == 'BIOS gives DOS 992/32/63 (INT 13h, after ECHS)', r[14])
    check(r[16] == "Setup's geometry is the drive's own.", r[16])
    check(r[24] == 'Enter:Use as type 47 (auto-detect) ESC:Back', r[24])
    p = tool(img, 'infod')
    r = [norm(x) for x in rows(p)]
    check(r[5] == 'No drive answers IDENTIFY DEVICE here (none, or ATAPI).', r[5])
    check(r[13] == 'Setup Not Installed' and r[14] == 'BIOS gives DOS Not set up in this POST', '%s / %s' % (r[13], r[14]))
    p = tool(img, 'infoc', cmos=make_cmos(drive=2))
    r = [norm(x) for x in rows(p)]
    check(r[13].startswith('Setup Type 2 ') and r[16].startswith("Setup's geometry is not the drive's own"),
          'type 2 in setup: %s / %s' % (r[13], r[16][:40]))
    T.press(p, [ENTER], 800)
    check(rows(p)[22].strip().startswith('Found: written as type 47'), 'Enter: %s' % rows(p)[22].strip()[:40])
    T.press(p, [ENTER], 800)
    check(norm(rows(p)[13]) == 'Setup Type 47 1986/16/63' and
          norm(rows(p)[16]) == "Setup's geometry is the drive's own.", 'again: %s' % norm(rows(p)[13]))

def part_case(img, ref):
    print('Partition check')
    hdr = 'Partition check C:'
    p = tool(img, 'partc', secs=disk(32, 63))
    r = [norm(x) for x in rows(p)]
    check(r[3] == hdr and r[5] == 'BIOS gives DOS 992/32/63 (INT 13h, after ECHS)', r[5])
    exp = ['1 * 06 FAT16 0/1/1 399/31/63 393 MB 32/63 OK',
           '2 05 Extended 400/0/1 899/31/63 492 MB OK',
           '3 06 FAT16 400/1/1 599/31/63 196 MB 32/63 OK',
           '4 06 FAT16 600/1/1 899/31/63 295 MB 32/63 OK']
    check(r[8:12] == exp, 'made with 32/63: four rows OK')
    check(r[13] == 'The partitions fit the geometry this BIOS gives DOS.', r[13])
    p = tool(img, 'partc', secs=disk(64, 63))
    r = [norm(x) for x in rows(p)]
    check(r[8].endswith('64/63 !') and r[9].endswith('!'), 'made with 64 heads: rows marked: %s' % r[8][-8:])
    check('Made with 64 heads / 63 sectors, the BIOS 32 / 63' in ' '.join(r), 'the verdict names 64 / 63 and 32 / 63')
    p = tool(img, 'partc', secs=disk(32, 63, logical=False, bpbH=16))
    r = [norm(x) for x in rows(p)]
    check(r[8] == '1 * 06 FAT16 0/1/1 399/31/63 393 MB 16/63 !' and r[10].startswith('Made with 16 heads / 63 sectors'),
          'the MBR fits, the BPB says 16 heads: %s' % r[10][:40])
    p = tool(img, 'partc')
    check(norm(rows(p)[7]) == 'No partition table (no 55AA signature in the MBR).', norm(rows(p)[7]))
    p = tool(img, 'partd')
    check(norm(rows(p)[5]) == 'Not set up in this POST', 'D: %s' % norm(rows(p)[5]))
    print('  the POST line')
    for secs, want in ((disk(64, 63), 'C: partitions use 64 heads / 63 sectors, the BIOS 32 / 63 - see Setup, Tools'),
                       (disk(32, 63), ''), ({}, '')):
        p = Post(img); p.ides[0].sectors.update(secs); p.run(max_ms=30000)
        check(norm(rows(p)[14]) == want and p.stop == 'int19', 'row 14: "%s"' % norm(rows(p)[14]))

def speed_case(img, ref):
    print('Disk speed')
    p = tool(img, 'speedc', 12000, secs=disk(32, 63))
    r = [norm(x) for x in rows(p)]
    import re
    ok = all(re.fullmatch(r'Read, %s \d+ KB/s' % w, r[7 + i]) for i, w in enumerate(('start', 'middle', 'end')))
    check(ok, 'reads: %s | %s | %s' % (r[7], r[8], r[9]))
    check(re.fullmatch(r'Access time \d+\.\d ms \(random sector\)', r[11]) is not None, r[11])
    check(r[24] == 'ESC:Back', 'key row ESC:Back at the end')
    p = tool(img, 'speedd', 600)
    check(norm(rows(p)[5]) == 'Not set up in this POST', 'D: %s' % norm(rows(p)[5]))

def mem_case(img, ref):
    print('Memory test')
    p = tool(img, 'mem', 150000)
    r = [norm(x) for x in rows(p)]
    check(r[5:8] == ['Base memory 68 - 640 KB OK', 'Extended 1024 - 4096 KB OK', 'EMS pages None (EMS size 0)'],
          ' | '.join(r[5:8]))
    p = tool(img, 'mem', 150000, cmos=ems_cmos(), ext_kb=2048, ems_kb=1024)
    r = [norm(x) for x in rows(p)]
    check(r[6] == 'Extended 1024 - 3072 KB OK' and r[7] == 'EMS pages C0-FFh window D000 OK', '%s | %s' % (r[6], r[7]))
    p = tool(img, 'mem', 150000, cmos=ems_cmos(), ext_kb=2048, ems_kb=1024, stuck=(0xC5, 0x1234, 0x04))
    r = [norm(x) for x in rows(p)]
    check(r[7] == 'EMS pages C0-FFh window D000 1 error' and r[11] == 'First error at 315234h wrote AA55h bits 0004',
          '%s | %s' % (r[7], r[11]))
    check(p.ht12[0x19] == 0 and p.ht12[0x20] == 0, 'HT12 EMS registers restored (19h, 20h)')

def stack_case(img, ref):
    print('every tool, then Exit without saving: POST still reaches INT 19h')
    p = T.enter(img); p.ides[0].sectors.update(disk(32, 63))
    T.press(p, [TAB] * 4)
    for i, name in enumerate(TOOLS):
        T.press(p, [ENTER], 150000 if name == 'mem' else 12000 if name.startswith('speed') else 800)
        if name.startswith('info'):
            pass
        T.press(p, [ESC], 300)
        ok = norm(rows(p)[4]) == 'Hard disk C: info / auto-detect' and p.stop is None
        check(ok, '%s, ESC: the Tools page again' % name)
        if not ok: return
        T.press(p, [DOWN])
    T.press(p, [TAB], 200); T.press(p, [DOWN], 200); T.press(p, [ENTER], 300)
    check('Exit without saving (Y/N)?' in rows(p)[24], 'Exit without saving asks')
    T.press(p, [KEY_Y], 300)
    if p.stop is None: p.run(max_ms=30000)
    check(p.stop == 'int19', 'POST goes on to INT 19h (%s)' % p.stop)
    check(rows(p)[10].strip() == 'Disk C:  CF  SanDisk SDCFJ-1024', 'the POST screen again')

def bootkey_case(img, ref):
    print('the one-time boot key')
    def run(key=None, at=None, order=0, cp=None):
        cm = make_cmos(extra={0x3E: order, 0x3F: order ^ 0xA5}); fix_cmos(cm)
        p = Post(img, cmos=bytes(cm)); p.stop_at_int19 = False
        fl = bytearray(1474560); fl[:512] = bootcode(b'Floppy boot\r\n'); p.floppy = bytes(fl)
        p.ides[0].sectors[0] = bootcode(b'C: boot\r\n')
        if cp is not None:
            p.run(max_ms=40000, until=lambda q: q.p80 and q.p80[-1][0] == cp); p.type_key(key)
        elif key: p.type_key(key, at_ms=at)
        p.run(max_ms=40000)
        r = rows(p)
        st = next((x.split('│')[0].strip() for x in r if 'Booting' in x), '?')
        return st, ('Floppy boot' if any('Floppy boot' in x for x in r) else 'C: boot' if any('C: boot' in x for x in r) else '?'), \
               p.mu.mem_read(0x4FF, 1)[0], [x for x in r if 'DEL: Setup' in x]
    for args, st, boot, what in (
            (dict(), 'Booting: A: then C:', 'Floppy boot', 'no key, A: then C:'),
            (dict(order=1), 'Booting: C: then A:', 'C: boot', 'no key, C: then A:'),
            (dict(key=0x2E, at=2500), 'Booting: C: (this time)', 'C: boot', 'C during the memory test'),
            (dict(key=0x2E, cp=0x74), 'Booting: C: (this time)', 'C: boot', 'C in the DEL window'),
            (dict(key=0x1E, cp=0x74, order=1), 'Booting: A: (this time)', 'Floppy boot', 'A with C: then A:'),
            (dict(key=0x1E, at=9800, order=2), 'Booting: C: only', 'Floppy boot', 'A after 7Fh, C: only (INT 19h takes it)'),
            (dict(key=0x2E, at=9800), 'Booting: A: then C:', 'C: boot', 'C after 7Fh')):
        s, b, ff, _ = run(**args)
        check(s == st and b == boot and ff == 0, '%s: "%s", %s, 40:FF = %02X' % (what, s, b, ff))
    p = Post(img); p.run(max_ms=40000, until=lambda q: q.p80 and q.p80[-1][0] == 0x75)
    check('DEL: Setup   A/C: boot from A:/C:' in rows(p)[24], 'the DEL window says: %s' % rows(p)[24].strip()[:36])

PARTS = {'umb': umb_case, 'bar': bar_case, 'screen': screen_case, 'info': info_case, 'part': part_case,
         'speed': speed_case, 'mem': mem_case, 'stack': stack_case, 'bootkey': bootkey_case}

if __name__ == '__main__':
    img, ref = open(ROM, 'rb').read(), open(REF, 'rb').read()
    sel = sys.argv[1:] or list(PARTS)
    print('ROM %s  MD5 %s' % (os.path.basename(ROM), hashlib.md5(img).hexdigest()))
    for k in sel: PARTS[k](img, ref)
    print('\n%d checks failed' % len(fails) if fails else '\nall checks pass')
    for f in fails: print('  FAIL', f)
    sys.exit(1 if fails else 0)
