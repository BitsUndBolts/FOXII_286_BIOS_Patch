#!/usr/bin/env python3
"""Build a FOX II ROM from the original 06/13/90 image.

    python3 py/build.py          the latest step (Step 4)
    python3 py/build.py 1        the Step 1 ROM (ECHS only), byte-identical to the
                                 one confirmed on the board
    python3 py/build.py 2        the Step 2 ROM, byte-identical to the one confirmed
                                 on the board
    python3 py/build.py 3 / 4    the Step 3 / Step 4 ROMs, likewise
    python3 py/build.py 5a       round 5a (branch stage2-5a-no-diagnostics): Step 4
                                 without the AMI ROM Diagnostics; not yet on the board
    python3 py/build.py 5b       round 5b (branch stage2-5b-post-screen): 5a + the
                                 POST screen; not yet on the board
    python3 py/build.py 6a       round 6a (branch stage3-6a-setup): 5b + the setup,
                                 the boot order, the auto-detect switch
    python3 py/build.py 6b       round 6b (branch stage3-6b-tools): 6a + the tools,
                                 HT12UMB.SYS at F000:6000, the boot key (0.7)

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
Step 3 (asm/step3.asm = the Step 2 code at F537 + autodet.asm in two blocks):
  - several sections, each at its ROM offset (from NASM's map file):
    .text at F537 (must equal the Step 2 code), auto1 at 7F0F, auto2 at E32D
  - CMOS 12h reads MOV AL,92h / CALL EE9F at 9447 (checkpoint 75h) and A894
    (the fixed-disk setup) -> CALL autodet / CALL drives12, NOP, NOP
Step 4 (asm/step4.asm = Step 3 + bootskip.asm in four blocks):
  - INT 19h 8F80 XOR AX,AX / MOV ES,AX -> CALL int19_entry, NOP
  - INT 19h 8FDF MOV DI,BX / MOV AX,ES:[DI] (A: path) -> CALL int19_a, NOP, NOP
  - INT 06h: the JMP at EB2E -> JMP int6_boot (which passes everything but a
    386 boot from A: on to Step 2's int6_halt)
Round 5a (asm/step4.asm, no new code):
  - the diagnostics module 0000-6FFF is removed: the header AA 55 40 and the
    JMP 7000 at 0008 (the configuration box) stay, 0003 becomes RET, the
    rest is cleared, and the module's XOR (C983) is balanced at 6FFE
  - E058 FFh -> 00h: AMI's own switch that leaves RUN DIAGNOSTICS out of
    the setup menu
Round 5b (asm/step5b.asm = Step 4 + post.asm in the 'diag' block 000B-6FFD):
  - 92C1 CALL F042 -> CALL bu_init; 76D0 -> JMP bu_idline; 766E -> RET
    (AMI's screen tamper check); ACDB -> CALL bu_mem / JMP AD01; AD05 ->
    CALL bu_escmsg / JMP AD1E; AB60 -> JMP bu_clrmsg; 93F6 -> CALL
    bu_delmsg; 96E7 MOV SI,7AB2 -> CALL bu_errors; 9791 (mode set) ->
    CALL bu_refresh; F000:0008 JMP 7000 -> JMP bu_final
Round 6a (asm/step6a.asm = 5b with ROUND6A + setup.asm):
  - BCFC MOV AL,CS:[E058] (setup menu) -> JMP BD61 (AMI's setup page code)
  - BD69 CLI / CLD / MOV AX,268Ah (after the page's mode set) -> CALL setup_dark,
    NOP, NOP: the display stays off while AMI draws its page (0.6.1)
  - AC2A, AC3A, AC8E (the memory test's reads of port 60h, which drop every
    key but ESC) -> CALL kbd_poll / CALL bu_memkey / JMP kbd_poll: a DEL is
    noted, "Entering Setup" shown, and put into the keyboard buffer at
    checkpoint 7Fh for AMI's DEL check (0.6.1)
  - C009 MOV BX,CA53 / JMP C011 (the page's editing loop) -> JMP bu_setup
  - 9447 CALL autodet -> CALL autodet_sw (the auto-detect switch)
  - 8F9B XOR DX,DX / XOR AX,AX / INT 13h / CALL 9005 (INT 19h, A:) -> CALL boot_seq
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
    # Step 3: the second build. The first (451fbb2b...) ran on the board; the second's
    # code runs on the board inside the Step 4 ROM (same blocks, checked by the build).
    3: dict(asm='step3', out='FOXII_STEP3', confirmed='1c05d1c2b53a2c5d7c72adc698e04770', sections=True),
    4: dict(asm='step4', out='FOXII_STEP4', confirmed='1e95b81057dc59e07d49f3f0d3993ecf', sections=True),
    # stages 2 and 3, one round per branch (docs/PLAN_STAGES_2_3.md); not yet on the board
    # 'built': the ROM of that round's branch; a later branch must rebuild it unchanged
    '5a': dict(asm='step4', out='FOXII_STEP5A', confirmed=None, sections=True,
               built='50e1a3bec4e2ee652377b7ab632640a3'),
    '5b': dict(asm='step5b', out='FOXII_STEP5B', confirmed=None, sections=True,
               built='1676da04973658527b52e0da40fcaf06'),
    # 6a: 0.6.1 (the board-test fixes); 0.6 was fa014dad81c7ad8016bd8e34c38dfa5c and ran on the board
    '6a': dict(asm='step6a', out='FOXII_STEP6A', confirmed=None, sections=True,
               built='39f360b612da32e4b4517abea2d15343'),
    # 6b: 0.7, the tools (branch stage3-6b-tools)
    '6b': dict(asm='step6b', out='FOXII_STEP6B', confirmed=None, sections=True),
}
ORDER = [1, 2, 3, 4, '5a', '5b', '6a', '6b']              # build order: a round contains everything before it
RANK = {k: i for i, k in enumerate(ORDER)}
LATEST = ORDER[-1]

CODE_BASE     = 0xF537
CHECKSUM_WORD = 0xF83E       # even offset, last word of the free block F537-F840 (F841 = INT 12h)
CODE_LIMIT    = CHECKSUM_WORD
# free blocks a sectioned build (Step 3 on) may fill: name -> (start, end exclusive)
# A run of 00h right after a string starts with that string's terminator:
# 7F0E ends the ID string "HT-11 286 BIOS", E32C ends the copyright line at
# E300 that POST prints (F042). Step 3's first build put code there and the
# line ran on into it on the screen. Blocks start after the terminator.
BLOCKS = {'.text': (CODE_BASE, CHECKSUM_WORD),   # F537-F83D
          'auto1': (0x7F0F, 0x8000),             # 7000-7FFF has no checksum
          'auto2': (0xE32D, 0xE3FE),             # stop before E3FE (IBM INT 13h entry address)
          'boot1': (0xF474, 0xF4FA),             # F473 and F500 are code
          'boot2': (0x7EBA, 0x7F00),             # 7F00: the ID string
          'boot3': (0xDFBB, 0xE000),
          'boot4': (0x7FD4, 0x8000)}             # after auto1
TERMINATORS = (0x7EB9, 0x7F0E, 0xDFBA, 0xE32C)    # string ends in front of the free runs: stay 00h
DIAG_HEAD  = bytes.fromhex('aa5540e99a0027fde9f56f')   # AA 55 40, JMP 00A0, 2 bytes, JMP 7000
DIAG_FREE  = (0x000B, 0x6FFE)          # round 5a on: free, after the header and both entries
DIAG_XOR   = 0x6FFE                    # word that balances C983's XOR of 0000-6FFF
BLOCKS['diag'] = DIAG_FREE
# Round 6b: HT12UMB.SYS in a fixed 2 KB slot at 6000-67FF (tag at 5FF0); the
# code ends below the tag, and 6800-6FFD is a block of its own
UMB_TAG, UMB_SLOT, UMB_LEN = 0x5FF0, 0x6000, 0x800
UMB_FILE = os.path.join(ROOT, 'extra', 'HT12UMB.SYS')
UMB_MD5  = 'ce87362d4f0b50ff6a3ba7fbaad9ddb4'    # HT12UMB 1.0, 1813 bytes
BLOCKS_6B = {'diag': (DIAG_FREE[0], UMB_TAG), 'umb': (UMB_TAG, UMB_SLOT + UMB_LEN),
             'diag2': (UMB_SLOT + UMB_LEN, DIAG_FREE[1])}

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

def nasm_sections(name):
    """Assemble a sectioned step (file offset = ROM offset - lowest section start).
    Returns {section: (start, bytes)} and the global labels, both from the map file."""
    asm = os.path.join(ROOT, 'asm', name + '.asm')
    bin_ = os.path.join(ROOT, 'asm', name + '.bin')
    lst = os.path.join(ROOT, 'asm', name + '.lst')
    map_ = os.path.join(ROOT, 'asm', name + '.map')
    try:
        subprocess.run(['nasm', '-f', 'bin', asm, '-o', bin_, '-l', lst, '-Werror',
                        '-i', os.path.join(ROOT, 'asm') + os.sep],
                       check=True, cwd=os.path.join(ROOT, 'asm'))   # [map ...] is cwd-relative
    except FileNotFoundError:
        sys.exit('nasm not found: install NASM (https://www.nasm.us)')
    blob, text = open(bin_, 'rb').read(), open(map_).read()
    secs = {}
    for m in re.finditer(r'^\s+([0-9A-F]+)\s+([0-9A-F]+)\s+([0-9A-F]+)\s+([0-9A-F]+)\s+progbits\s+(\S+)$',
                         text, re.M):
        start, length, sname = int(m.group(2), 16), int(m.group(4), 16), m.group(5)
        secs[sname] = [start, length]
    base = min(v[0] for v in secs.values())
    secs = {k: (st, blob[st - base:st - base + n]) for k, (st, n) in secs.items()}
    L = {}
    for m in re.finditer(r'^\s+([0-9A-F]+)\s+[0-9A-F]+\s+([A-Za-z_]\w*)$', text, re.M):
        L[m.group(2)] = int(m.group(1), 16)
    return secs, L

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
    R = RANK[step]
    at = lambda s_: R >= RANK[s_]        # does this build contain step/round s_?
    if cfg.get('sections'):
        secs, L = nasm_sections(cfg['asm'])
        code = secs['.text'][1]
        assert secs['.text'][0] == CODE_BASE
        # Steps 1 and 2 keep their code and addresses: .text must be the Step 2 code
        prev, _ = nasm(STEPS[2]['asm'])
        assert code == prev, 'the F537 block differs from the board-confirmed Step 2 code'
        if at(4):                        # and Step 3's blocks are Step 3's code, same addresses
            s3, _ = nasm_sections(STEPS[3]['asm'])
            for name in ('auto1', 'auto2'):
                assert secs[name] == s3[name], '%s differs from the Step 3 build' % name
        if at('5b'):                     # and Step 4's blocks are Step 4's code
            s4, _ = nasm_sections(STEPS[4]['asm'])
            for name in ('boot1', 'boot2', 'boot3', 'boot4'):
                assert secs[name] == s4[name], '%s differs from the Step 4 build' % name
    else:
        code, lst = nasm(cfg['asm'])
        L = labels(lst)
        secs = {'.text': (CODE_BASE, code)}
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
    if at(2):
        assert data[0xEB2A:0xEB2E] == bytes.fromhex('1f5b585d'), 'INT 06h handler tail'
        patch(0xEB2E, 'e954ff', rel16(0xE9, 0xEB2E,                      # was JMP EA85
                                      L['int6_boot'] if at(4) else L['int6_halt']))

    # ---- Step 3: IDE auto-detection ----
    if at(3):
        patch(0x9447, 'b092e8535a', rel16(0xE8, 0x9447,                   # checkpoint 75h: CMOS 12h
              L['autodet_sw'] if at('6a') else L['autodet']))
        patch(0xA894, 'b092e80646', rel16(0xE8, 0xA894, L['drives12']))   # fixed-disk setup: CMOS 12h

    # ---- Step 4: 386 code while booting from A: -> boot from C: ----
    if at(4):
        patch(0x8F80, '33c08ec0', rel16(0xE8, 0x8F80, L['int19_entry']))     # INT 19h entry
        patch(0x8FDF, '8bfb268b05', rel16(0xE8, 0x8FDF, L['int19_a']))       # A:'s sector read
        assert data[0x8FE4:0x8FE6] == bytes.fromhex('b980'), 'INT 19h A: path after 8FDF'
        assert data[0x8F84:0x8F87] == bytes.fromhex('b8c7ef'), 'INT 1Eh = EFC7 at 8F84 (DPT_ROM)'
        assert data[0x7DB3:0x7DCA] == b'  INVALID BOOT DISKETTE', 'S_BADDISK'
        # TAIL_LINE1 (bootskip.asm) = the first line of Step 2's msg_tail, up to its CR
        t = secs['.text'][1]; o = L['msg_tail'] - CODE_BASE
        assert t[o + 63] == 13 and t[o + 62:o + 63] == b'.' and 13 not in t[o + 2:o + 63], 'TAIL_LINE1'

    # ---- Round 5a: the AMI ROM Diagnostics removed ----
    if at('5a'):
        assert bytes(data[0:len(DIAG_HEAD)]) == DIAG_HEAD, 'diagnostics module header'
        assert data[0x7000:0x7003] == bytes.fromhex('e83100'), 'configuration box at 7000'
        assert data[0x97C1:0x97C6] == bytes.fromhex('b80800ffd0'), 'MOV AX,8 / CALL AX at 97C1'
        assert data[0xBD46:0xBD4B] == bytes.fromhex('b80300ffd0'), 'MOV AX,3 / CALL AX at BD46'
        assert data[0xBCFC:0xBD10] == bytes.fromhex('2ea058e00ac0bb43ca7409bb33cabeeed6e8490b'), \
            'the menu reads E058 (BCFC) and picks CA43 / CA33'
        data[3:6] = b'\xc3\x90\x90'                        # F000:0003: RET
        data[6:8] = b'\0\0'                                # 0006-0007 (module data)
        data[DIAG_FREE[0]:DIAG_XOR + 2] = bytes(DIAG_XOR + 2 - DIAG_FREE[0])   # 000B-6FFF
        assert bytes(data[8:11]) == DIAG_HEAD[8:11], 'JMP 7000 at 0008 kept'   # (5b redirects it below)
        patch(0xE058, 'ff', b'\x00')                      # no RUN DIAGNOSTICS in the menu

    # ---- Round 5b: the POST screen ----
    if at('5b'):
        def jmp_near(at_, to): return rel16(0xE9, at_, to)
        patch(0x92C1, 'e87e5d', rel16(0xE8, 0x92C1, L['bu_init']))          # cp 22h: copyright line
        patch(0x76D0, '60b403', jmp_near(0x76D0, L['bu_idline']))          # copyright + BIOS ID
        patch(0x766E, '60', b'\xc3')                                       # screen tamper check off
        patch(0xACDB, '3d9d007316b901003c107308b1023c027302b103b030e89ae0e2f95850e881febe557de874e0',
              rel16(0xE8, 0xACDB, L['bu_mem']) + rel8_jmp(0xACDE, 0xAD01))   # memory count
        assert data[0xAD01:0xAD05] == bytes.fromhex('58487519'), 'POP AX / DEC AX / JNE AD1E at AD01'
        patch(0xAD05, '8b166900b700b402e8e5c8be197ee85fe080ee02b402e8d7c8',
              rel16(0xE8, 0xAD05, L['bu_escmsg']) + rel8_jmp(0xAD08, 0xAD1E))   # ESC message
        patch(0xAB60, '8b1669', jmp_near(0xAB60, L['bu_clrmsg']))           # clear the message row
        patch(0x93F6, 'be3b7ee879f9', rel16(0xE8, 0x93F6, L['bu_delmsg']))  # DEL message
        patch(0x96E7, 'beb27a', rel16(0xE8, 0x96E7, L['bu_errors']))        # error list
        patch(0x9791, 'b40fcd1032e4cd10', rel16(0xE8, 0x9791, L['bu_refresh']))   # mode set
        assert data[0x97C1:0x97C6] == bytes.fromhex('b80800ffd0')
        data[8:11] = jmp_near(8, L['bu_final'])                             # F000:0008

    # ---- Round 6a: the setup, the boot order, the auto-detect switch ----
    if at('6a'):
        patch(0xBCFC, '2ea058e0', rel16(0xE9, 0xBCFC, 0xBD61))              # no menu: the page
        assert data[0xBD61:0xBD65] == bytes.fromhex('b40fcd10'), 'setup page entry BD61'
        assert data[0xBD65:0xBD69] == bytes.fromhex('b400cd10'), 'mode set of the setup page'
        patch(0xBD69, 'fafcb88a26', rel16(0xE8, 0xBD69, L['setup_dark']) + b'\x90\x90')  # display off
        patch(0xC009, 'bb53caeb03', rel16(0xE9, 0xC009, L['bu_setup']))     # the editing loop
        assert data[0xC0A0:0xC0A3] == bytes.fromhex('e82c10'), 'AMI save at C0A0 (CALL D0CF)'
        assert data[0xBD4D:0xBD51] == bytes.fromhex('b700b403'), 'AMI menu exit at BD4D'
        assert data[0xD0CF:0xD0D2] == bytes.fromhex('fa501e'), 'D0CF (setup hooks off)'
        patch(0x8F9B, '33d233c0cd13e86100', rel16(0xE8, 0x8F9B, L['boot_seq']))   # INT 19h: A:
        # 0.6.1: DEL during the memory test (AMI's own reads of port 60h)
        patch(0xAC2A, 'e460eb00', rel16(0xE8, 0xAC2A, L['kbd_poll']))       # IN AL,60h / JMP $+2
        patch(0xAC3A, 'e4603c01', rel16(0xE8, 0xAC3A, L['bu_memkey']))      # IN AL,60h / CMP AL,1
        assert data[0xAC3E:0xAC40] == bytes.fromhex('7451'), 'JE AC91 (ESC) after AC3A'
        patch(0xAC8E, 'e460c3', rel16(0xE9, 0xAC8E, L['kbd_poll']))         # IN AL,60h / RET
        assert data[0xFF53] == 0xCF, "AMI's INT 1Ch IRET at FF53"
        assert data[0x955B:0x955E] == bytes.fromhex('e80216') and data[0x9566:0x956D] == bytes.fromhex('b400cd1680fc53'), \
            'cp 7Fh: CALL AB60, then INT 16h and CMP AH,53h (the DEL check)'
        assert data[0x8FA4:0x8FA7] == bytes.fromhex('be9b7d'), 'INT 19h after the A: read'
        assert data[0x8FEE:0x8FF1] == bytes.fromhex('e80efe'), 'INT 19h boot jump at 8FEE'

    # ---- Round 6b: HT12UMB.SYS in the ROM ----
    blocks = dict(BLOCKS)
    if at('6b'):
        blocks.update(BLOCKS_6B)
        drv = open(UMB_FILE, 'rb').read()
        assert hashlib.md5(drv).hexdigest() == UMB_MD5, 'extra/HT12UMB.SYS is not HT12UMB 1.0'
        assert len(drv) <= UMB_LEN, 'HT12UMB.SYS does not fit the 2 KB slot'
        st, blob = secs['umb']
        assert st == UMB_TAG and len(blob) == UMB_SLOT + UMB_LEN - UMB_TAG, 'the umb section'
        assert blob[:6] == b'BUBUMB' and struct.unpack_from('<H', blob, 10)[0] == len(drv)
        slot = blob[UMB_SLOT - UMB_TAG:]
        assert slot[:len(drv)] == drv and not any(slot[len(drv):]), 'slot = driver + zeros'
        blob = bytearray(blob)           # the tag's check word: word sum of the slot + it = 0
        struct.pack_into('<H', blob, 12, (-sum(struct.unpack_from('<1024H', slot))) & 0xFFFF)
        secs['umb'] = (st, bytes(blob))

    # the new code, each section into its free block
    for name, (start, blob) in secs.items():
        lo, hi = blocks[name]
        assert lo <= start and start + len(blob) <= hi, \
            '%s (%04X, %d bytes) does not fit %04X-%04X' % (name, start, len(blob), lo, hi - 1)
        if name != '.text':
            assert not any(data[lo:hi]), 'free block %04X-%04X is not empty' % (lo, hi - 1)
        data[start:start + len(blob)] = blob

    for t in TERMINATORS:
        assert data[t] == 0 and data[t - 1] != 0, 'string terminator at %04X overwritten' % t

    # checksums
    if at('5a'):                         # the module's XOR (C983) over 0000-6FFF
        struct.pack_into('<H', data, DIAG_XOR, 0)
        struct.pack_into('<H', data, DIAG_XOR, diag_xor(data))
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
    print('Step %s -> binary/%s.BIN' % (step, cfg['out']))
    for name, (start, blob) in sorted(secs.items(), key=lambda kv: kv[1][0]):
        lo, hi = blocks[name]
        print('code %-5s: %d bytes at %04X-%04X (%d bytes of the block %04X-%04X left)'
              % (name, len(blob), start, start + len(blob) - 1, hi - start - len(blob), lo, hi - 1))
    print('checksum  : word at %04X = %04X (word sum of 8000-FFFF = 0)' % (CHECKSUM_WORD, fix))
    if at('5a'):
        print('module XOR: word at %04X = %04X (XOR of 0000-6FFF = 0); 000B-6FFD: %d bytes, %d free'
              % (DIAG_XOR, struct.unpack_from('<H', data, DIAG_XOR)[0], DIAG_FREE[1] - DIAG_FREE[0],
                 DIAG_FREE[1] - DIAG_FREE[0] - sum(len(b) for n, (st, b) in secs.items()
                                                   if n in ('diag', 'diag2', 'umb'))))
    for k in sorted(L, key=L.get):
        print('  %-16s @ %04X' % (k, L[k]))
    for suffix, blob in (('.BIN', img), ('_EVEN.BIN', even), ('_ODD.BIN', odd)):
        print('wrote binary/%s  MD5 %s' % (cfg['out'] + suffix, hashlib.md5(blob).hexdigest()))
    if cfg.get('built'):
        same = hashlib.md5(img).hexdigest() == cfg['built']
        print('MD5 matches the round\'s own build (%s).' % cfg['built'] if same else
              'NOTE: MD5 differs from the round\'s own build (%s).' % cfg['built'])
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
    a = sys.argv[1].lower() if len(sys.argv) > 1 else LATEST
    build(int(a) if isinstance(a, str) and a.isdigit() else a)
