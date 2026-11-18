; =====================================================================
;  Step 2: a readable invalid-opcode error instead of a silent hang
;
;  The 286 raises INT 06h for any instruction it does not know (a 386
;  instruction, for example), with the return address pointing at the
;  faulting instruction. AMI's handler (EB31) deals with LOADALL and a
;  LOCK prefix and passes everything else, at EB2E, to the generic
;  unexpected-interrupt handler EA85, which IRETs: the CPU executes the
;  same opcode again, forever, and the board looks frozen.
;
;  py/build.py turns the JMP EA85 at EB2E into JMP int6_halt. AMI's
;  LOADALL and LOCK handling in front of it stays as it was.
;
;  int6_halt:
;    - masks every IRQ except the keyboard and points INT 09h back at the
;      BIOS keyboard handler, and sends end-of-interrupt to both PICs (the
;      fault may have happened inside an interrupt handler), so that
;      Ctrl+Alt+Del works whatever the program did;
;    - switches to text mode if a graphics mode is active;
;    - prints where it happened and the bytes there;
;    - halts. There is no way back: the program cannot continue.
;
;  Entry (at EB2E, AMI's registers already restored):
;    [SP] = IP, [SP+2] = CS of the faulting instruction, [SP+4] = FLAGS
; =====================================================================

IVT_TEMPLATE equ 0xFEE3          ; ROM table of the INT 00h-1Fh offsets (segment F000)

int6_halt:
    cli
    cld
    mov  bp, sp
    mov  di, [ss:bp]             ; faulting IP
    mov  dx, [ss:bp+2]           ; faulting CS

    ; --- make Ctrl+Alt+Del work: keyboard only, BIOS INT 09h, no IRQ in service
    mov  al, 0xFD                ; master: only IRQ 1 (keyboard)
    out  0x21, al
    mov  al, 0xFF                ; slave: nothing
    out  0xA1, al
    mov  al, 0x20                ; non-specific EOI, enough for any nesting depth
    mov  cx, 8
.eoi:
    out  0xA0, al
    out  0x20, al
    loop .eoi
    xor  ax, ax
    mov  es, ax
    mov  ax, [cs:IVT_TEMPLATE + 9*2]
    mov  [es:9*4], ax
    mov  [es:9*4+2], cs

    ; --- a text mode the message can be read in
    mov  ah, 0x0F
    int  0x10                    ; AL = mode, BH = page
    cmp  al, 3
    jbe  .text
    cmp  al, 7
    je   .text
    push ds
    push 0x40
    pop  ds
    mov  al, [0x10]              ; equipment: initial video mode bits 5:4
    pop  ds
    and  al, 0x30
    cmp  al, 0x30
    mov  ax, 0x0003              ; colour 80x25
    jne  .setmode
    mov  al, 0x07                ; monochrome 80x25
.setmode:
    int  0x10
    xor  bh, bh
.text:
    mov  bl, 0x07

    ; --- the message
    mov  si, msg_head
    call .puts
    mov  ax, dx
    call .hex16
    mov  al, ':'
    call .putc
    mov  ax, di
    call .hex16
    ; a boot sector runs at 0000:7C00-7DFF (linear)
    mov  ax, dx
    mov  cl, 4
    shl  ax, cl                  ; low 16 bits of CS*16 (enough: compare the linear address < 64 KB)
    mov  cx, dx
    shr  cx, 12                  ; CS*16 >> 16
    add  ax, di
    adc  cx, 0                   ; cx:ax = linear address
    jcxz .lowseg
    jmp  .bytes
.lowseg:
    cmp  ax, 0x7C00
    jb   .bytes
    cmp  ax, 0x7E00
    jae  .bytes
    mov  si, msg_boot
    call .puts
.bytes:
    mov  si, msg_bytes
    call .puts
    mov  es, dx
    mov  cx, 6
.bl:
    mov  al, [es:di]
    call .hex8
    mov  al, ' '
    call .putc
    inc  di
    loop .bl
    mov  si, msg_tail
    call .puts

    sti                          ; only the keyboard is unmasked
.halt:
    hlt
    jmp  .halt

; --- helpers (BH = page, BL = colour for graphics modes) ---
.puts:                           ; CS:SI, zero-terminated
    mov  al, [cs:si]
    inc  si
    or   al, al
    jz   .ret
    call .putc
    jmp  .puts
.hex16:
    push ax
    mov  al, ah
    call .hex8
    pop  ax
.hex8:
    push ax
    shr  al, 4
    call .nib
    pop  ax
.nib:
    and  al, 0x0F
    add  al, '0'
    cmp  al, '9'
    jbe  .putc
    add  al, 7
.putc:
    push ax
    mov  ah, 0x0E
    int  0x10
    pop  ax
.ret:
    ret

msg_head  db 13, 10, 10, ' Invalid opcode at ', 0
msg_boot  db ' (boot sector)', 0
msg_bytes db 13, 10, ' Bytes: ', 0
msg_tail  db 13, 10, ' The 80286 cannot run this code. It needs a 386 or newer CPU.'
          db 13, 10, ' System halted. Press Ctrl+Alt+Del to restart.', 13, 10, 0
