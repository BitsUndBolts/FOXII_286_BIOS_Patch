"""ide_harness.py: Unicorn real-mode harness for the FOX II BIOS's INT 13h code.

Adapted from the SOYO project's py/ide_harness.py. Runs real INT 13h calls
through the ROM's own dispatcher (F000:A15F) against a simulated IDE drive,
with software-interrupt dispatch through the IVT, a log of every task-file
command with the LBA it addresses, and the stack depth (measured by painting
the stack area before the call and finding the lowest byte that changed). The stack is
the BIOS POST/boot stack SS:SP = 0030:0100.

    pip install unicorn

Limits: no PIC or timer model, so IRQ waits take their worst-case path, and
Unicorn executes 386 opcodes that a 286 would reject (the assembler's
CPU 286 is the guard for that). Compare the patched ROM with the original
under identical inputs rather than judging it alone.

    from ide_harness import *
    e = Emu(load_rom(PATCHED_ROM), 16000, 16, 63)   # simulated drive C/H/S
    r = e.call(0x0800, 0, 0x0080)                    # INT 13h AH=08h
    r = e.call(0x0201, 0x0001, 0x0080)               # read LBA 0
    print(r['ide'])
"""
import os, struct
from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_16, UC_HOOK_INSN, UC_HOOK_INTR, UC_HOOK_CODE
from unicorn.x86_const import *

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG_ROM    = os.path.join(ROOT, 'base', 'FOXII_0613_ORIGINAL.BIN')
# the ROM under test: $FOXII_ROM, else the newest step's build
PATCHED_ROM = os.environ.get('FOXII_ROM') or os.path.join(ROOT, 'binary', 'FOXII_STEP5B.BIN')

INT13_HD   = 0xA15F                 # INT 13h fixed-disk entry
INSW_SITES = (0xA428,)              # rep insw  (read)
OUTSW_SITES = (0xA33B, 0xA48C)      # rep outsw (format, write)
RET_STUB   = 0x0602                 # HLT written here; calls return to it
PAINT      = b'\xa5'                # stack paint byte

def load_rom(path): return open(path, 'rb').read()
def lin(s, o): return (s << 4) + o

class Drive:
    def __init__(s, C, H, S):
        s.C, s.H, s.S = C, H, S
        s.r = {2: 1, 3: 1, 4: 0, 5: 0, 6: 0xA0}
        s.log, s.img, s.cur_lba = [], {}, None
        s.left = 0          # sectors the current command still transfers (DRQ while > 0)
    def lba(s):
        c = s.r[4] | (s.r[5] << 8); h = s.r[6] & 0xF; sec = s.r[3]
        return c, h, sec, (c * s.H + h) * s.S + sec - 1

class Emu:
    def __init__(s, rom, C, H, S, floppy=False):
        s.mu = mu = Uc(UC_ARCH_X86, UC_MODE_16)
        mu.mem_map(0, 0x100000)
        mu.mem_write(lin(0xF000, 0), rom)
        # FDPT of drive 0 at 0060:0000 (type 47 style), INT 41h/46h point to it
        fd = bytearray(16); struct.pack_into('<H', fd, 0, C); fd[2] = H; fd[0xE] = S
        struct.pack_into('<H', fd, 0xC, C)
        mu.mem_write(lin(0x60, 0), bytes(fd))
        mu.mem_write(0x104, struct.pack('<HH', 0, 0x60))
        mu.mem_write(0x118, struct.pack('<HH', 0, 0x60))
        mu.mem_write(0x4C, struct.pack('<HH', INT13_HD, 0xF000))
        mu.mem_write(lin(0x40, 0x75), b'\x01')          # one fixed disk
        s.d = Drive(C, H, S); s.p61 = 0; s.floppy = floppy
        mu.hook_add(UC_HOOK_INSN, s.inp, aux1=UC_X86_INS_IN)
        mu.hook_add(UC_HOOK_INSN, s.outp, aux1=UC_X86_INS_OUT)
        mu.hook_add(UC_HOOK_INTR, s.intr)
        for site in INSW_SITES + OUTSW_SITES:      # only the string-transfer sites
            mu.hook_add(UC_HOOK_CODE, s.code, begin=lin(0xF000, site), end=lin(0xF000, site))
        mu.reg_write(UC_X86_REG_SS, 0x30); mu.reg_write(UC_X86_REG_SP, 0x100)

    def code(s, uc, addr, size, ud):
        off = addr - 0xF0000
        if off in INSW_SITES or off in OUTSW_SITES:
            # fake the string transfer (Unicorn hooks IN/OUT, not INS/OUTS)
            uc.reg_write(UC_X86_REG_CX, 0)
            if off in INSW_SITES:
                di = uc.reg_read(UC_X86_REG_DI); es = uc.reg_read(UC_X86_REG_ES)
                lba = s.d.cur_lba if s.d.cur_lba is not None else 0
                uc.mem_write(lin(es, di), s.d.img.get(lba, b'\x00' * 512))
                # Unicorn keeps translated code: drop it where the sector went, or code
                # that ran there before (a boot sector) runs again instead of the new one
                uc.ctl_remove_cache(lin(es, di), lin(es, di) + 512)
                s.d.cur_lba = lba + 1
                uc.reg_write(UC_X86_REG_DI, (di + 512) & 0xFFFF)
            else:
                si = uc.reg_read(UC_X86_REG_SI); uc.reg_write(UC_X86_REG_SI, (si + 512) & 0xFFFF)
            uc.reg_write(UC_X86_REG_IP, off + 2)
            # one sector done; a real drive raises IRQ 14 again for every sector
            s.d.left = max(0, s.d.left - 1)
            uc.mem_write(lin(0x40, 0x8E), b'\xff')

    def inp(s, uc, port, size, ud):
        if port == 0x1F7: return 0x58 if s.d.left else 0x50   # ready, seek complete (+DRQ)
        if port == 0x61: s.p61 ^= 0x10; return s.p61
        if port == 0x71: return 0
        if port == 0x1F1: return 1
        if port == 0x1F0: return 0
        return 0xFF

    def outp(s, uc, port, size, val, ud):
        if 0x1F2 <= port <= 0x1F6: s.d.r[port - 0x1F0] = val
        if port == 0x1F7:
            c, h, sec, l = s.d.lba()
            s.d.log.append((hex(val), 'cnt', s.d.r[2], 'C', c, 'H', h, 'S', sec,
                            'drvhd', hex(s.d.r[6]), 'LBA', l))
            s.d.cur_lba = l
            if val & 0xF0 in (0x20, 0x30):     # read / write (also long): data phase
                s.d.left = s.d.r[2] or 256
            elif val == 0x50:                  # format track: one sector of format data
                s.d.left = 1
            else:
                s.d.left = 0
            uc.mem_write(lin(0x40, 0x8E), b'\xff')  # "IRQ 14 happened"

    def intr(s, uc, intno, ud):
        fl = uc.reg_read(UC_X86_REG_EFLAGS)
        if intno == 0x40:                      # floppy
            if s.floppy:
                uc.reg_write(UC_X86_REG_EFLAGS, fl & ~1)
            else:                              # no diskette: timeout
                ax = uc.reg_read(UC_X86_REG_AX)
                if (ax >> 8) != 0:
                    uc.reg_write(UC_X86_REG_AX, 0x8000 | (ax & 0xFF))
                    uc.reg_write(UC_X86_REG_EFLAGS, fl | 1)
                else:
                    uc.reg_write(UC_X86_REG_EFLAGS, fl & ~1)
            return
        if intno in (0x15, 0x10, 0x16, 0x12, 0x11):
            uc.reg_write(UC_X86_REG_EFLAGS, fl & ~1); return
        vec = struct.unpack('<HH', bytes(uc.mem_read(intno * 4, 4)))
        if vec == (0, 0):
            uc.reg_write(UC_X86_REG_EFLAGS, fl & ~1); return
        sp = uc.reg_read(UC_X86_REG_SP); ss = uc.reg_read(UC_X86_REG_SS)
        cs = uc.reg_read(UC_X86_REG_CS); ip = uc.reg_read(UC_X86_REG_IP)
        for v in (fl & 0xFFFF, cs, ip):
            sp = (sp - 2) & 0xFFFF; uc.mem_write(lin(ss, sp), struct.pack('<H', v))
        uc.reg_write(UC_X86_REG_SP, sp)
        uc.reg_write(UC_X86_REG_CS, vec[1]); uc.reg_write(UC_X86_REG_IP, vec[0])

    def call(s, ax, cx, dx, bx=0x1000, es=0x2000, e32=0, sp=0x100):
        """INT 13h with the given registers, from SS:SP = 0030:sp. e32 marks the
        upper register halves (Unicorn is a 386): they must come back unchanged."""
        mu = s.mu
        mu.mem_write(lin(0xF000, RET_STUB), b'\xf4')
        mu.mem_write(lin(0x30, sp - 6), struct.pack('<HHH', RET_STUB, 0xF000, 0x0202))
        mu.reg_write(UC_X86_REG_SS, 0x30); mu.reg_write(UC_X86_REG_SP, sp - 6)
        for r, v in ((UC_X86_REG_EAX, ax | e32), (UC_X86_REG_ECX, cx | e32), (UC_X86_REG_EDX, dx | e32),
                     (UC_X86_REG_BX, bx), (UC_X86_REG_ES, es), (UC_X86_REG_DS, 0x40),
                     (UC_X86_REG_BP, 0x1234), (UC_X86_REG_SI, 0x5678), (UC_X86_REG_DI, 0x9ABC)):
            mu.reg_write(r, v)
        # stack painting: fill 0030:0000-sp with a marker, find the lowest byte changed
        mu.mem_write(lin(0x30, 0), PAINT * (sp - 6))
        s.d.log = []
        mu.reg_write(UC_X86_REG_CS, 0xF000)
        mu.emu_start(lin(0xF000, INT13_HD), lin(0xF000, RET_STUB), count=3000000)
        fl = mu.reg_read(UC_X86_REG_EFLAGS)
        regs = {n: hex(mu.reg_read(r)) for n, r in (
            ('eax', UC_X86_REG_EAX), ('ebx', UC_X86_REG_EBX), ('ecx', UC_X86_REG_ECX),
            ('edx', UC_X86_REG_EDX), ('esi', UC_X86_REG_ESI), ('edi', UC_X86_REG_EDI),
            ('ebp', UC_X86_REG_EBP), ('esp', UC_X86_REG_ESP), ('es', UC_X86_REG_ES),
            ('ds', UC_X86_REG_DS))}
        regs['fl'] = hex(fl & 0x8D5); regs['ide'] = list(s.d.log)
        regs['bda74'] = bytes(mu.mem_read(lin(0x40, 0x74), 4)).hex()
        st = bytes(mu.mem_read(lin(0x30, 0), sp - 6))
        low = next((i for i in range(len(st)) if st[i] != PAINT[0]), sp - 6)
        regs['stack_depth'] = sp - low
        return regs
