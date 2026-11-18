#!/usr/bin/env python3
"""Reproduces every fact in docs/ROM_ANALYSIS.md from the original ROM, with asserts.

Run from the project folder:  python3 py/analyze_bios.py
Needs only Python 3. Every address is an offset in segment F000 (file offset == IP).
"""
import hashlib, struct, sys, os
HERE = os.path.dirname(os.path.abspath(__file__))
ROM = os.path.join(HERE, '..', 'base', 'FOXII_0613_ORIGINAL.BIN')
A = open(ROM, 'rb').read()
MD5 = 'c74e174c716add49b1b686c70d8df83c'
w = lambda o: struct.unpack_from('<H', A, o)[0]
fails = 0
def check(name, cond, info=''):
    global fails
    print(('  ok   ' if cond else '  FAIL ') + name + (('  ' + info) if info else ''))
    if not cond: fails += 1
def at(off, hexbytes):
    return A[off:off + len(bytes.fromhex(hexbytes))] == bytes.fromhex(hexbytes)
def near_target(off):            # E8/E9 rel16
    return (off + 3 + struct.unpack_from('<h', A, off + 1)[0]) & 0xFFFF

print('1. Image')
check('size 64 KB', len(A) == 65536)
check('md5 ' + MD5, hashlib.md5(A).hexdigest() == MD5)
check('reset vector FFF0: JMP F000:E05B', at(0xFFF0, 'ea5be000f0'))
check('date 06/13/90 at FFF5', A[0xFFF5:0xFFFD] == b'06/13/90')
check('BIOS ID "HT-11 286 BIOS" at 7F00', A[0x7F00:0x7F0E] == b'HT-11 286 BIOS')
check('E05B: JMP 806C (POST start)', at(0xE05B, 'e9') and near_target(0xE05B) == 0x806C)

print('2. ROM Diagnostics module F000:0000-6FFF')
check('header AA 55, size byte 40h (32 KB)', at(0, 'aa5540'))
check('entry 0003: JMP 00A0 (diagnostics program)', at(3, 'e9') and near_target(3) == 0x00A0)
check('entry 0008: JMP 7000 (System Configuration box)', at(8, 'e9') and near_target(8) == 0x7000)
check('signature "04/09/90ROM DIAGNOSTICS" at 000B', A[0xB:0x22] == b'04/09/90ROM DIAGNOSTICS')
x = 0
for v in struct.unpack_from('<14336H', A, 0): x ^= v
check('XOR of all words 0000-6FFF == 0', x == 0)
check('C983: module check = AA55 header + XOR of 3800h words', at(0xC983, '33f62ead3daa55750bb9ff37'))
check('929E: JNZ 92EA "ROM-BIOS CHECKSUM ERROR" after CALL C983 (POST)', at(0x929B, 'e8') and near_target(0x929B) == 0xC983 and at(0x929E, '754a'))
check('92EA: MOV SI,D6B2 (message) -> 8D50', at(0x92EA, 'beb2d6e9'))
check('97BC: CALL C983, JNZ, MOV AX,8 / CALL AX (end of POST -> F000:0008)', at(0x97BC, 'e8') and near_target(0x97BC) == 0xC983 and at(0x97BF, '7505b80800ffd0'))
check('97C6: JMP 8F48 (-> boot)', at(0x97C6, 'e9') and near_target(0x97C6) == 0x8F48)
check('E058: diagnostics-present flag = FFh (read by setup menu)', A[0xE058] == 0xFF)
check('BCFC: setup menu reads CS:[E058]', at(0xBCFC, '2ea058e00ac0'))
check('BD46: MOV AX,3 / CALL AX (menu "RUN DIAGNOSTICS")', at(0xBD46, 'b80300ffd0'))
# no near call/jmp from code above 7000 lands below 7000, except data false positives
print('2b. POST ROM checksum (checkpoint 02) and AMI tamper checks')
check('8143: checkpoint 02, word sum of CS:8000-FFFF (4000h words) must be 0',
      at(0x8143, 'b002e68033dbb90040be00802ead03d8e2fa7406bd0900e9'))
check('original word sum 8000-FFFF == 0', sum(struct.unpack_from('<16384H', A, 0x8000)) & 0xFFFF == 0)
check('76BC: tamper check, 24h bytes 7649 vs FF97', at(0x76BC, 'be4976b92400bb96ff2eac432e3207e1f8'))
check('FA4F: tamper check, 4Ch bytes FF70 vs NOT FA00', at(0xFA4F, 'be70ffb94c00bbfff92eac43f6d02e3207e1f6'))

print('3. INT 13h fixed disk (same AMI code base as the SOYO 11/11/92)')
check('A15F: CMP DL,80h / STI / CLD (INT 13h HD entry)', at(0xA15F, '80fa80fbfc'))
check('A171: push ax cx dx bx si di ds es / sub sp,8 / push bp / mov bp,sp', at(0xA171, '50515253565f1e0683ec08558bec'.replace('565f','5657')))
check('A18F: CALL CS:[DI+A1C0] (dispatch, AH 00-19h)', at(0xA18F, '2eff95c0a1') and at(0xA188, '3c19'))
check('A357-A383: AH=08h reporting body', at(0xA357, '268a7702fece268b072d02003dff037603b8ff03'))
check('A384-A38E: AH=08h tail (DL=[75h], AH=0, [74h]=AH, RET)', at(0xA384, '8a167500b40088267400c3'))
check('A65A: AND DH,0Fh in drive-select A619 (the 4-bit head limit)', at(0xA65A, '80e60f0ace') and A.count(bytes.fromhex('80e60f')) == 1)
check('A619 pushes ES,BX,DX,CX before it', at(0xA631, '06535251'))
cylhi16 = '8ac1c0e8068a5615c0ea0480e20c0ac2'
check('A30C-A31C: cylinder-high builder (format path), then [bp+6]/1F5h', at(0xA30C, '8ac1c0e8068ad08a4615c0e804240c0ac2') and at(0xA31D, '884606baf501ee'))
check('A4DF-A4EE: cylinder-high builder (seek path)', at(0xA4DF, cylhi16) and at(0xA4EF, 'baf501884606ee'))
check('A832-A841: cylinder-high builder (shared read/write/verify)', at(0xA832, cylhi16) and at(0xA842, 'baf501884606ee'))
check('only three OUT 1F5h sites', A.count(bytes.fromhex('baf501')) == 3)
check('A60C/A611: FDPT through INT 41h (0:104) / INT 46h (0:118)', at(0xA60C, 'bb0401') and at(0xA611, 'bb1801'))
check('E401: drive type table, type 1 = 306/4', at(0xE401, '320104'))

print('4. POST stack and type-47 RAM area')
check('F1B2: SS:SP = 0030:0100', at(0xF1B2, 'b830008ed0bc0001'))
check('F1BA: AMI\'s GDT template E260 copied to 0000:0300 (30h words), its own alias base = 0300h',
      at(0xF1BA, 'bf000357be60e2b93000') and at(0xF1C8, 'c7440a0003'))
check('E260: the template is a GDT (descriptor 1 = limit 60h, base 0FE260h, data 93h)', at(0xE268, '600060e20f93'))
check('E2C0 bit 6 clear: the type-47 table placement follows CMOS 38h bit 4', not A[0xE2C0] & 0x40)
check('984E: CMOS 38h bit 4 clear -> type-47 tables in segment 002Dh (0:030D C:, 0:031D D:)',
      at(0x984E, 'b0b8e8') and at(0x9853, 'a810b82d00740b') and at(0x9867, 'b83d0080fd9b7403b84d00'))

print('5. INT 06h (invalid opcode) and the 386 boot-sector hang')
check('IVT template FEE3: INT 06h -> EB31', w(0xFEE3 + 6 * 2) == 0xEB31)
check('EB31: LOADALL (0F 05) emulation / LOCK skip', at(0xEB3A, '8b073cf074e13d0f0575e5'))
check('EB2E: everything else -> JMP EA85 (unexpected-interrupt handler, IRETs to the same opcode)', at(0xEB2E, 'e9') and near_target(0xEB2E) == 0xEA85)

print('6. Boot (INT 19h path)')
check('8F9B: reset, try A: (DL=0)', at(0x8F9B, '33d233c0cd13e8'))
check('8FB1: CMOS 0Eh bit 3 set -> skip C:', at(0x8FB1, 'b00ee8') and at(0x8FB6, 'a8087509'))
check('8FBA: try C: (DL=80h)', at(0x8FBA, 'b280e8'))

print('7. Setup')
check('978B: CALL BCA6 (setup) when DEL was seen ([0069h] != 0)', at(0x9784, '833e690000') and near_target(0x978B) == 0xBCA6)
check('D6F0: menu " RUN DIAGNOSTICS "', A[0xD6F0:0xD701] == b' RUN DIAGNOSTICS ')

print('8. HT12 chipset')
check('F458: HT12 read  (AL=index -> AL)', at(0xF458, 'baed01eeeb00eb004242ecc3'))
check('F464: HT12 write (AL=index, AH=value)', at(0xF464, 'baed01eeeb00eb00424286c4ee86c4c3'))
check('F104: init table 10h=0Eh 12h=00 13h=00 14h=18h 18h=3Fh', at(0xF104, '100e120013001418183f'))

print('9. Free space (runs of 00h, >= 64 bytes, outside the diagnostics module)')
runs = []
i = 0x7000
while i < 0x10000:
    if A[i] == 0:
        j = i
        while j < 0x10000 and A[j] == 0: j += 1
        if j - i >= 64: runs.append((i, j - i))
        i = j
    else: i += 1
for s, n in runs: print('       %04X-%04X  %4d bytes' % (s, s + n - 1, n))
print('       total %d bytes' % sum(n for _, n in runs))
print('       Use E32C-E3FD and F474-F4F9 only: E3FE is the IBM-compatible INT 13h entry\n'
      '       address (zero here, but keep it clear), and F4FA-F4FF borders code at F500.')

print('10. CMOS drive types and the fixed-disk setup (Step 3)')
check('EE89 / EE92: CMOS read (AL=index -> AL) / write (AL=index, AH=value)', at(0xEE89, 'e670eb00eb00e471c3') and at(0xEE92, 'e67086c4eb00eb00e67186c4c3'))
check('EE9F / EEAE: the same with NMI disabled (index | 80h), keep every register but AL',
      at(0xEE9F, '9cfa22c078030c80f9e8deff50eb0d') and at(0xEEAE, '9cfa5022c078030c80f9e8d7ff'))
check('93FD: checkpoint 73h: IDE soft reset (3F6h = 4, then 0, ~1 s)', at(0x93FD, 'b004baf603eeb90001e8') and at(0x9409, 'b000eeb9f0ffe8'))
check('943E: checkpoint 75h: CMOS 0Eh bits 7:6 set -> skip the disk setup',
      at(0x943A, 'b075e680b08ee8') and at(0x9443, 'a8c07515'))
check('9447: MOV AL,92h / CALL EE9F: CMOS 12h; zero -> no disk setup (Step 3 hook 1)',
      at(0x9447, 'b092e8') and near_target(0x9449) == 0xEE9F and at(0x944C, '0ac0740c'))
check('9450: checkpoint 76h: CALL A857 (the fixed-disk setup)', at(0x9450, 'b076e680e8') and near_target(0x9454) == 0xA857)
check('A894: MOV AL,92h / CALL EE9F in A857 (Step 3 hook 2); AH = 0 there (A87A XOR AX,AX)',
      at(0xA894, 'b092e8') and near_target(0xA896) == 0xEE9F and at(0xA87A, '33c0'))
check('A899: C: = high nibble, 0Fh -> type in 19h (A8A5), 47 -> CALL 9834',
      at(0xA899, '8ac8c0e804') and at(0xA8A5, 'b099e8') and at(0xA8AA, '2c01720b3c2e7707') and near_target(0xA8B4) == 0x9834)
check('A8D6: D: = low nibble, 0Fh -> type in 1Ah (A8E2), 47 -> CALL 983C',
      at(0xA8D6, '8ac1250f00') and at(0xA8E2, 'b09ae8') and near_target(0xA8F1) == 0x983C)
check('9834 / 983C: type-47 parameters from CMOS 1Bh (C:) / 24h (D:)', at(0x9834, '51bf0401b59b') and at(0x983C, '51bf1801b5a4'))
check('9880: FDPT from CMOS: cyl lo/hi, heads, 0000, precomp lo/hi, 00, control, 000000, LZ lo/hi, sectors',
      at(0x9880, 'e82f00e82c00e8290033c0abe82300e8200032c0aae81a0033c0abaae81300e81000e80d00'))
check('A905: INT 13h AH=14h, then 09h/11h retried for 2D8h ticks (40 s) per drive (A993)',
      at(0xA905, 'b280b414cd13') and at(0xA993, '8b366c00b409cd13') and at(0xA9A3, 'a16c002bc63dd802'))
check('A910: failure -> CMOS 0Eh bit 3 (INT 19h then skips C:)', at(0xA910, 'b88e8ee8') and at(0xA916, '0c08'))
check('82B2: POST CMOS checksum: byte sum 10h-2Dh against 2Eh (high) / 2Fh (low)', at(0x82B2, 'b89090') and at(0x82C6, '3cae'))
check('C0B9: setup writes the checksum: sum 10h-2Dh -> 2Eh, 2Fh', at(0xC0B9, '33c933d2b89090e8') and at(0xC0CB, '3cae') and at(0xC0D6, 'b0af'))
check('C0F0: setup saves, then JMP F000:FFF0 (full POST again)', at(0xC0F0, 'eaf0ff00f0'))

print('\n%s' % ('ALL CHECKS PASSED' if not fails else '%d CHECK(S) FAILED' % fails))
sys.exit(1 if fails else 0)
