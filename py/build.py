#!/usr/bin/env python3
"""Build the FOX II ECHS ROM (Step 1) from the original 06/13/90 image.

    python3 py/build.py        (needs NASM on the PATH)

  0. assemble asm/echs.asm (CPU 286) -> asm/echs.bin + asm/echs.lst
  1. splice it into the free block F537-F840
  2. AH=08h body A357-A383 -> CALL xlate_getparams / JMP A384 / NOPs
  3. AND DH,0Fh at A65A    -> CALL xlate_headcyl
  4. the three cylinder-high builders (A30C, A4DF, A832) -> MOV AL,[BP+6] / NOPs
  5. check the diagnostics module's XOR is untouched (the only checksum)
  6. write binary/FOXII_ECHS.BIN and the doubled chip files
     binary/FOXII_ECHS_EVEN.BIN / _ODD.BIN (27C512 / 27SF512)

The original bytes at every patch site are asserted before they are
overwritten, and entry points come from NASM's listing.
"""
import hashlib, os, re, struct, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from romtool import split, check_image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(ROOT, 'base', 'FOXII_0613_ORIGINAL.BIN')
ASM  = os.path.join(ROOT, 'asm', 'echs.asm')
BIN  = os.path.join(ROOT, 'asm', 'echs.bin')
LST  = os.path.join(ROOT, 'asm', 'echs.lst')
OUT  = os.path.join(ROOT, 'binary', 'FOXII_ECHS')

ORIG_MD5   = 'c74e174c716add49b1b686c70d8df83c'
CODE_BASE  = 0xF537
CODE_LIMIT = 0xF841          # INT 12h entry; the block ends at F840

def nasm():
    try:
        subprocess.run(['nasm', '-f', 'bin', ASM, '-o', BIN, '-l', LST, '-Werror'], check=True)
    except FileNotFoundError:
        sys.exit('nasm not found: install NASM (https://www.nasm.us)')

def labels():
    """Labels from the listing: the address of the first instruction after each label."""
    out, pending = {}, []
    for line in open(LST):
        m = re.match(r'\s*\d+\s+([0-9A-F]{8})\s+([0-9A-F]+)\s*(.*)', line)
        lab = re.match(r'\s*\d+\s+(?:[0-9A-F]{8}\s+[0-9A-F]+\s+)?([A-Za-z_][\w]*):', line)
        if lab: pending.append(lab.group(1))
        if m and pending:
            for p in pending: out[p] = CODE_BASE + int(m.group(1), 16)
            pending = []
    return out

def rel16(op, at, to):
    return bytes([op]) + struct.pack('<H', (to - (at + 3)) & 0xFFFF)

def rel8_jmp(at, to):
    d = to - (at + 2); assert -128 <= d <= 127
    return bytes([0xEB, d & 0xFF])

def diag_xor(buf):
    x = 0
    for v in struct.unpack_from('<14336H', buf, 0): x ^= v
    return x

def build():
    nasm()
    L = labels()
    code = open(BIN, 'rb').read()
    data = bytearray(open(SRC, 'rb').read())
    assert hashlib.md5(data).hexdigest() == ORIG_MD5, 'unexpected original ROM'
    assert CODE_BASE + len(code) <= CODE_LIMIT, 'code does not fit F537-F840'
    assert not any(data[CODE_BASE:CODE_LIMIT]), 'free block F537-F840 is not empty'

    def patch(start, orig_hex, new):
        orig = bytes.fromhex(orig_hex)
        assert bytes(data[start:start + len(orig)]) == orig, 'unexpected bytes at %04X' % start
        assert len(new) <= len(orig)
        data[start:start + len(orig)] = new + b'\x90' * (len(orig) - len(new))

    # 2. AH=08h body (45 bytes); the tail A384-A38E must survive (SOYO pitfall 9.1)
    assert data[0xA384:0xA38F] == bytes.fromhex('8a167500b40088267400c3'), 'AH=08h tail'
    body = '268a7702fece268b072d02003dff037603b8ff038ad48ae8c0e4068acc8ae2c0e40480e4c00af4268a470e0ac8'
    call = rel16(0xE8, 0xA357, L['xlate_getparams'])
    patch(0xA357, body, call + rel8_jmp(0xA357 + 3, 0xA384))

    # 3. the 4-bit head mask
    patch(0xA65A, '80e60f', rel16(0xE8, 0xA65A, L['xlate_headcyl']))

    # 4. cylinder-high builders: "mov al,[bp+6]" + NOPs. The store
    #    "mov [bp+6],al" that follows each one is kept (it rewrites the same value).
    LOAD = bytes.fromhex('8a4606')
    patch(0xA30C, '8ac1c0e8068ad08a4615c0e804240c0ac2', LOAD)   # format, 17 bytes
    patch(0xA4DF, '8ac1c0e8068a5615c0ea0480e20c0ac2', LOAD)     # seek, 16 bytes
    patch(0xA832, '8ac1c0e8068a5615c0ea0480e20c0ac2', LOAD)     # read/write/verify, 16 bytes

    # 1. the new code
    data[CODE_BASE:CODE_BASE + len(code)] = code

    # 5. the only checksum in this BIOS must still hold
    assert diag_xor(data) == 0 and data[0:2] == b'\xaa\x55'
    check_image(bytes(data))

    img = bytes(data)
    open(OUT + '.BIN', 'wb').write(img)
    even, odd = split(img)
    open(OUT + '_EVEN.BIN', 'wb').write(even)
    open(OUT + '_ODD.BIN', 'wb').write(odd)
    print('code      : %d bytes at %04X-%04X (block ends F840, %d bytes left)'
          % (len(code), CODE_BASE, CODE_BASE + len(code) - 1, CODE_LIMIT - CODE_BASE - len(code)))
    for k in ('xlate_getparams', 'xlate_headcyl', 'calc_factor', 'div32'):
        print('%-16s@ %04X' % (k, L[k]))
    for suffix, blob in (('.BIN', img), ('_EVEN.BIN', even), ('_ODD.BIN', odd)):
        print('wrote binary/%s  MD5 %s' % (os.path.basename(OUT) + suffix, hashlib.md5(blob).hexdigest()))

if __name__ == '__main__':
    build()
