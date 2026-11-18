"""int6_harness.py: the 286's invalid-opcode trap in Unicorn, shared by
int6_test.py (Step 2) and bootskip_test.py (Step 4).

Emu6 adds to ide_harness.Emu a video BIOS stub (teletype text capture,
modes), PIC port capture and the ROM's own IVT template; run_286 plays the
286's INT 06h (Unicorn is a 386+ and stops on an opcode no CPU knows).
"""
import struct
from ide_harness import *
from unicorn import UC_ERR_INSN_INVALID

UD2 = b'\x0f\x0b'

class Emu6(Emu):
    """Adds a video BIOS stub (teletype text capture, modes), PIC port capture and INT 06h."""
    def __init__(s, rom, mode=3, mono=False):
        super().__init__(rom, 980, 16, 32)
        s.text = ''; s.mode = mode; s.modesets = []; s.ports = []; s.int6 = 0
        ivt = struct.unpack_from('<32H', rom, 0xFEE3)
        for n in range(0x20):                       # the BIOS's own IVT template
            if ivt[n]: s.mu.mem_write(n * 4, struct.pack('<HH', ivt[n], 0xF000))
        s.mu.mem_write(0x4C, struct.pack('<HH', INT13_HD, 0xF000))
        s.mu.mem_write(0x24, struct.pack('<HH', 0x5678, 0x1234))   # INT 09h hooked by "a program"
        s.mu.mem_write(lin(0x40, 0x10), struct.pack('<H', 0x30 if mono else 0x20))

    def outp(s, uc, port, size, val, ud):
        if port in (0x20, 0x21, 0xA0, 0xA1): s.ports.append((port, val))
        super().outp(uc, port, size, val, ud)

    def intr(s, uc, intno, ud):
        if intno == 0x10:
            ax = uc.reg_read(UC_X86_REG_AX); ah = ax >> 8
            if ah == 0x0E: s.text += chr(ax & 0xFF)
            elif ah == 0x0F: uc.reg_write(UC_X86_REG_AX, (ax & 0xFF00) | s.mode)
            elif ah == 0x00: s.mode = ax & 0x7F; s.modesets.append(s.mode)
            return
        if intno == 6: s.int6 += 1
        super().intr(uc, intno, ud)

def run_286(e, begin, max_faults=200):
    """Run until HLT, taking INT 06h for an invalid opcode the way the 286 does:
    Unicorn stops with UC_ERR_INSN_INVALID and IP on the faulting instruction;
    push FLAGS, CS, IP and continue at the INT 06h vector."""
    mu = e.mu
    while True:
        try:
            mu.emu_start(begin, 0, count=3000000)
            return
        except UcError as ex:
            if ex.errno != UC_ERR_INSN_INVALID or e.int6 >= max_faults:
                e.err = str(ex); return
        cs, ip = mu.reg_read(UC_X86_REG_CS), mu.reg_read(UC_X86_REG_IP)
        fl = mu.reg_read(UC_X86_REG_EFLAGS) & 0xFFFF
        ss, sp = mu.reg_read(UC_X86_REG_SS), mu.reg_read(UC_X86_REG_SP)
        for v in (fl, cs, ip):
            sp = (sp - 2) & 0xFFFF; mu.mem_write(lin(ss, sp), struct.pack('<H', v))
        mu.reg_write(UC_X86_REG_SP, sp)
        mu.reg_write(UC_X86_REG_EFLAGS, fl & ~0x0300)       # IF and TF cleared, as for any interrupt
        off, seg = struct.unpack('<HH', bytes(mu.mem_read(6 * 4, 4)))
        mu.reg_write(UC_X86_REG_CS, seg)
        e.int6 += 1
        begin = lin(seg, off)

def mbr_with(code):
    m = bytearray(512); m[0:len(code)] = code; m[0x1FE:0x200] = b'\x55\xaa'
    return bytes(m)
