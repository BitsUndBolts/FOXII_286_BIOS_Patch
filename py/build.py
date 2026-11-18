#!/usr/bin/env python3
"""Build a FOX II ROM from the original 06/13/90 image.

    python3 py/build.py          the latest step (Step 2)
    python3 py/build.py 1        the Step 1 ROM (ECHS only), byte-identical to the
                                 one confirmed on the board

Needs NASM on the PATH; the BIOS's own checksum routines are run on the result
when Unicorn is installed (pip install unicorn).

Step 1 (asm/step1.asm = echs.asm):
  - code into the free block at F537
  - AH=08h body A357-A383 -> CALL xlate_getparams / JMP A384 / NOPs
  - AND DH,0Fh at A65A    -> CALL xlate_headcyl
  - cylinder-high builders A30C, A4DF, A832 -> MOV AL,[BP+6] / NOPs
Step 2 (asm/step2.asm = echs.asm + int6.asm):
  - everything of Step 1, same addresses
  - INT 06h: the JMP EA85 at EB2E -> JMP int6_halt
Every step:
  - balance the POST checksum (checkpoint 02 at 8143: word sum of
    F000:8000-FFFF must be 0) with the word at F83E, and check the
    diagnostics module's XOR (0000-6FFF) is untouched
  - write binary/<name>.BIN and the doubled chip files <name>_EVEN.BIN /
    <name>_ODD.BIN (27C512 / 27SF512)

The original bytes at every patch site are asserted before they are
overwritten, and entry points come from NASM's listing.
"""
import hashlib, os, re, struct, subprocess, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from romtool import split, check_image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(ROOT, 'base', 'FOXII_0613_ORIGINAL.BIN')
ORIG_MD5 = 'c74e174c716add49b1b686c70d8df83c'

STEPS = {
    1: dict(asm='step1', out='FOXII_ECHS',  confirmed='16c21a46d4effa9a62beca3349633fc7'),
    2: dict(asm='step2', out='FOXII_STEP2', confirmed='7b4a6577251b60668f24a6b80eb29af8'),
}
LATEST = max(STEPS)

CODE_BASE     = 0xF537
CHECKSUM_WORD = 0xF83E       # even offset, last word of the free block F537-F840 (F841 = INT 12h)
CODE_LIMIT    = CHECKSUM_WORD

def nasm(name):
    asm = os.path.join(ROOT, 'asm', name + '.asm')
    bin_ = os.path.join(ROOT, 'asm', name + '.bin')
    lst = os.path.join(ROOT, 'asm', name + '.lst')
    try:
        subprocess.run(['nasm', '-f', 'bin', asm, '-o', bin_, '-l', lst, '-Werror',
                        '-i', os.path.join(ROOT, 'asm') + os.sep], check=True)
    except FileNotFoundError:
        sys.exit('nasm not found: install NASM (https://www.nasm.us)')
    return open(bin_, 'rb').read(), lst

def labels(lst):
    """Global labels from the listing: the address of the first instruction after each."""
    out, pending = {}, []
    for line in open(lst):
        lab = re.match(r'\s*\d+\s+(?:[0-9A-F]{8}\s+[0-9A-F]+\s+)?(?:<\d+>\s+)?([A-Za-z_]\w*):', line)
        if lab: pending.append(lab.group(1))
        m = re.match(r'\s*\d+\s+([0-9A-F]{8})\s+[0-9A-F]+', line)
        if m and pending:
            for p in pending: out[p] = CODE_BASE + int(m.group(1), 16)
            pending = []
    return out

def rel16(op, at, to):
    return bytes([op]) + struct.pack('<H', (to - (at + 3)) & 0xFFFF)

def rel8_jmp(at, to):
    d = to - (at + 2); assert -128 <= d <= 127
    return bytes([0xEB, d & 0xFF])

def post_sum(buf):
    """What POST checkpoint 02 (F000:8143) computes: word sum of 8000-FFFF."""
    return sum(struct.unpack_from('<16384H', buf, 0x8000)) & 0xFFFF

def diag_xor(buf):
    x = 0
    for v in struct.unpack_from('<14336H', buf, 0): x ^= v
    return x

def build(step):
    cfg = STEPS[step]
    code, lst = nasm(cfg['asm'])
    L = labels(lst)
    data = bytearray(open(SRC, 'rb').read())
    assert hashlib.md5(data).hexdigest() == ORIG_MD5, 'unexpected original ROM'
    assert CODE_BASE + len(code) <= CODE_LIMIT, 'code does not fit F537-F83D'
    assert not any(data[CODE_BASE:CHECKSUM_WORD + 2]), 'free block F537-F83F is not empty'
    assert post_sum(data) == 0 and diag_xor(data) == 0, 'original checksums do not hold'

    def patch(start, orig_hex, new):
        orig = bytes.fromhex(orig_hex)
        assert bytes(data[start:start + len(orig)]) == orig, 'unexpected bytes at %04X' % start
        assert len(new) <= len(orig)
        data[start:start + len(orig)] = new + b'\x90' * (len(orig) - len(new))

    # ---- Step 1: ECHS ----
    # AH=08h body (45 bytes); the tail A384-A38E must survive (SOYO pitfall 9.1)
    assert data[0xA384:0xA38F] == bytes.fromhex('8a167500b40088267400c3'), 'AH=08h tail'
    body = '268a7702fece268b072d02003dff037603b8ff038ad48ae8c0e4068acc8ae2c0e40480e4c00af4268a470e0ac8'
    patch(0xA357, body, rel16(0xE8, 0xA357, L['xlate_getparams']) + rel8_jmp(0xA357 + 3, 0xA384))
    patch(0xA65A, '80e60f', rel16(0xE8, 0xA65A, L['xlate_headcyl']))       # the 4-bit head mask
    # cylinder-high builders: "mov al,[bp+6]" + NOPs; the "mov [bp+6],al" after each is kept
    LOAD = bytes.fromhex('8a4606')
    patch(0xA30C, '8ac1c0e8068ad08a4615c0e804240c0ac2', LOAD)   # format, 17 bytes
    patch(0xA4DF, '8ac1c0e8068a5615c0ea0480e20c0ac2', LOAD)     # seek, 16 bytes
    patch(0xA832, '8ac1c0e8068a5615c0ea0480e20c0ac2', LOAD)     # read/write/verify, 16 bytes

    # ---- Step 2: INT 06h ----
    if step >= 2:
        assert data[0xEB2A:0xEB2E] == bytes.fromhex('1f5b585d'), 'INT 06h handler tail'
        patch(0xEB2E, 'e954ff', rel16(0xE9, 0xEB2E, L['int6_halt']))   # was JMP EA85

    # the new code
    data[CODE_BASE:CODE_BASE + len(code)] = code

    # checksums
    struct.pack_into('<H', data, CHECKSUM_WORD, 0)
    fix = (-post_sum(data)) & 0xFFFF
    struct.pack_into('<H', data, CHECKSUM_WORD, fix)
    assert post_sum(data) == 0
    assert diag_xor(data) == 0 and data[0:2] == b'\xaa\x55'
    check_image(bytes(data))

    img = bytes(data)
    out = os.path.join(ROOT, 'binary', cfg['out'])
    even, odd = split(img)
    for suffix, blob in (('.BIN', img), ('_EVEN.BIN', even), ('_ODD.BIN', odd)):
        open(out + suffix, 'wb').write(blob)
    print('Step %d -> binary/%s.BIN' % (step, cfg['out']))
    print('code      : %d bytes at %04X-%04X (%d bytes left before the checksum word)'
          % (len(code), CODE_BASE, CODE_BASE + len(code) - 1, CODE_LIMIT - CODE_BASE - len(code)))
    print('checksum  : word at %04X = %04X (word sum of 8000-FFFF = 0)' % (CHECKSUM_WORD, fix))
    for k in sorted(L, key=L.get):
        print('  %-16s @ %04X' % (k, L[k]))
    for suffix, blob in (('.BIN', img), ('_EVEN.BIN', even), ('_ODD.BIN', odd)):
        print('wrote binary/%s  MD5 %s' % (cfg['out'] + suffix, hashlib.md5(blob).hexdigest()))
    if cfg['confirmed']:
        same = hashlib.md5(img).hexdigest() == cfg['confirmed']
        print('MD5 matches the ROM confirmed on the board.' if same else
              'NOTE: MD5 differs from the ROM confirmed on the board (%s).' % cfg['confirmed'])
    try:
        from rom_checks import run_checks
    except ImportError:
        print('NOTE: unicorn not installed, the ROM\'s own checksum routines were not run')
        return
    print('the ROM\'s own integrity checks, run in the emulator:')
    if not run_checks(img):
        for suffix in ('.BIN', '_EVEN.BIN', '_ODD.BIN'): os.remove(out + suffix)
        sys.exit('BUILD FAILED: the BIOS would reject this ROM (outputs deleted)')

if __name__ == '__main__':
    build(int(sys.argv[1]) if len(sys.argv) > 1 else LATEST)
