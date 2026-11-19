#!/usr/bin/env python3
"""ROM image tool for the Octek FOX II 286 BIOS (two 8-bit EPROMs on a 16-bit bus).

The 286 fetches words: the EVEN chip holds the low byte of every word (A0=0),
the ODD chip the high byte. Each chip is a 27256 (32 KB), together 64 KB at
F000:0000-FFFF. JP1 selects 27256/27128 only; pin 1 of the socket (VPP on a
27256, A15 on a 27C512/27SF512) is high, so a 64 KB chip serves its UPPER
half. That is why the burnable images are "doubled" (both halves identical).

  romtool.py join  EVEN.BIN ODD.BIN out.bin   -> 64 KB CPU image (F000:0000 = offset 0)
  romtool.py split image.bin outprefix        -> outprefix_EVEN.BIN / _ODD.BIN, each
                                                 64 KB doubled (27C512 / 27SF512), and
                                                 outprefix_EVEN_32K.BIN / _ODD_32K.BIN,
                                                 32 KB each (27C256, the board's own chip)
  romtool.py check image.bin                  -> reset vector, date, ID string
"""
import sys, hashlib

def load_half(path):
    d = open(path, 'rb').read()
    if len(d) == 65536:
        if d[:32768] != d[32768:]:
            print(f'warning: {path}: halves differ, using the upper 32 KB (what the board reads)')
        d = d[32768:]
    if len(d) != 32768:
        sys.exit(f'{path}: expected 32 KB or 64 KB, got {len(d)}')
    return d

def join(even, odd):
    e, o = load_half(even), load_half(odd)
    img = bytes(b for pair in zip(e, o) for b in pair)
    check_image(img)          # refuses a swapped pair
    return img

def split(img):
    assert len(img) == 65536
    even, odd = img[0::2], img[1::2]
    return even * 2, odd * 2

def chip_files(img):
    """(suffix, bytes) of every chip file: doubled 64 KB for a 27C512 /
    27SF512, plain 32 KB for a 27C256"""
    even, odd = img[0::2], img[1::2]
    return [('_EVEN.BIN', even * 2), ('_ODD.BIN', odd * 2),
            ('_EVEN_32K.BIN', even), ('_ODD_32K.BIN', odd)]

def check_image(img, verbose=False):
    ok = img[0xFFF0] == 0xEA and img[0xFFF3:0xFFF5] == b'\x00\xf0'
    if not ok:
        sys.exit('reset vector at FFF0 is not JMP FAR F000:xxxx - EVEN/ODD swapped or wrong file?')
    if verbose:
        print('reset  : JMP F000:%04X' % int.from_bytes(img[0xFFF1:0xFFF3], 'little'))
        print('date   :', img[0xFFF5:0xFFFD].decode('ascii', 'replace'))
        print('id     :', img[0x7F00:0x7F10].split(b'\0')[0].decode('ascii', 'replace'))
        print('md5    :', hashlib.md5(img).hexdigest())

if __name__ == '__main__':
    a = sys.argv[1:]
    if len(a) == 4 and a[0] == 'join':
        img = join(a[1], a[2]); open(a[3], 'wb').write(img); check_image(img, True)
    elif len(a) == 3 and a[0] == 'split':
        img = open(a[1], 'rb').read(); check_image(img)
        for suffix, blob in chip_files(img):
            open(a[2] + suffix, 'wb').write(blob)
            print('wrote %-40s %s' % (a[2] + suffix, hashlib.md5(blob).hexdigest()))
    elif len(a) == 2 and a[0] == 'check':
        check_image(open(a[1], 'rb').read(), True)
    else:
        print(__doc__)
