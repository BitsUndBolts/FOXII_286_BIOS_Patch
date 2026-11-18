#!/usr/bin/env python3
"""Recursive (coverage) disassembly of the FOX II BIOS from every known entry point.

Prints how much code was reached and every near CALL/JMP from reached code into
the ROM Diagnostics module (0000-6FFF). Needs Capstone (pip install capstone).

Early POST runs without RAM and "returns" through MOV SP,table + JMP (the routine
ends in RET, which pops the word at the table) or JMP SP. So for every MOV SP,imm
both imm and the word at imm are followed. That over-approximates a little: a few
bytes inside free runs show up as "reached" (see ROM_ANALYSIS.md 9).
"""
import os, struct, sys
from capstone import Cs, CS_ARCH_X86, CS_MODE_16
from capstone.x86 import X86_OP_IMM, X86_GRP_JUMP, X86_GRP_CALL
HERE = os.path.dirname(os.path.abspath(__file__))
A = open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, '..', 'base', 'FOXII_0613_ORIGINAL.BIN'), 'rb').read()
w = lambda o: struct.unpack_from('<H', A, o)[0]
md = Cs(CS_ARCH_X86, CS_MODE_16); md.detail = True

TABLES = {0xA1C0: 0x1A,   # INT 13h HD dispatch, AH 00-19h
          0x80D4: 11,     # CMOS 0Fh shutdown codes 0-0Ah
          0x775E: 8, 0x84D0: 20, 0xADD0: 11, 0xCB5C: 18}
ENTRIES = [0xE05B, 0x7000, 0xA15F, 0xBCA6, 0xEB31]
ENTRIES += [w(0xFEE3 + 2 * i) for i in range(0x1F)]          # IVT template INT 00h-1Eh
for t, n in TABLES.items(): ENTRIES += [w(t + 2 * i) for i in range(n)]

def run(entries, lo=0x7000):
    seen, into, work = {}, [], list(entries)
    while work:
        pc = work.pop()
        while lo <= pc < 0x10000 and pc not in seen:
            ins = next(md.disasm(A[pc:pc + 16], pc), None)
            if ins is None: break
            seen[pc] = ins; m = ins.mnemonic
            if m == 'mov' and ins.op_str.startswith('sp, 0x'):
                v = int(ins.op_str[4:], 16); work += [v, w(v)]
            if ins.group(X86_GRP_JUMP) or ins.group(X86_GRP_CALL):
                if m in ('ljmp', 'lcall'):
                    if ins.operands[0].imm == 0xF000: work.append(ins.operands[1].imm)
                elif ins.operands[0].type == X86_OP_IMM:
                    t = ins.operands[0].imm & 0xFFFF
                    (into.append((pc, t, m)) if t < lo else work.append(t))
                if m in ('jmp', 'ljmp'): break
            if m in ('ret', 'retf', 'iret', 'hlt'): break
            pc += ins.size
    return seen, into

seen, into = run([e for e in ENTRIES if e])
nbytes = len({a + k for a, i in seen.items() for k in range(i.size)})
print('reached %d instructions, %d bytes of code in 7000-FFFF' % (len(seen), nbytes))
for pc, t, m in into: print('  %04X: %s %04X  -> into the diagnostics module (check by hand)' % (pc, m, t))
print('far references to F000:0003 / F000:0008 go through MOV AX,3/8 + CALL AX (BD46, 97C1)')
