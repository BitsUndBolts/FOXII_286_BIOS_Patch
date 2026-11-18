; =====================================================================
;  Step 4: 386 code while booting from A: -> message, then boot from C:
;
;  Step 2 shows a message and halts on any invalid opcode. That is
;  right for a program, but annoying when a boot floppy for a 386 (an
;  MS-DOS 7.1 or Windows 9x disk) is left in A:: the PC never gets to C:.
;
;  Now, when the fault happens while the BIOS is booting from A: and DOS
;  is not loaded yet, the message ends with "Drive A: skipped. Booting
;  from drive C: ..." and AMI's boot code continues with C:, as if A:
;  had held no disk. Every other invalid opcode still halts in Step 2's
;  handler, unchanged.
;
;  "Booting from A:": AMI's INT 19h (8F80, the only entry: INT 19h ->
;  E6F2 -> 8F80, and the end of POST calls INT 19h) clears a marker word,
;  and the A: path sets it just before it checks and starts the boot
;  sector (8FDF). "DOS not loaded yet": INT 21h still holds the default
;  vector POST gave INT 00h-77h (F000:EA85, set at 90BC); DOS replaces
;  it. That also covers a loader (IO.SYS) the boot sector started.
;  A: is skipped once per INT 19h: the marker then says "skipped", so a
;  386 boot sector on C: halts instead of going round in circles.
;
;  py/build.py patches:
;    8F80  XOR AX,AX / MOV ES,AX          -> CALL int19_entry, NOP
;    8FDF  MOV DI,BX / MOV AX,ES:[DI]     -> CALL int19_a, NOP, NOP
;    EB2E  JMP int6_halt (Step 2)         -> JMP int6_boot
;
;  Before going on to C:, what a boot sector typically changes is put
;  back: INT 1Eh (DOS boot sectors point it at their own copy of the
;  diskette parameters; 8F80 sets the same value), the stack (0030:0100,
;  as POST boots with), interrupts on, and an end-of-interrupt to both
;  PICs. If C: does not boot either, AMI's own path follows: "INVALID
;  BOOT DISKETTE", "Insert BOOT diskette in A:", a key, and INT 19h again
;  from the start (which tries A: again: the disk may have been changed).
; =====================================================================

BOOT_FLAG  equ 0x04F0            ; 0000:04F0 = BDA 40:F0 (intra-application area, unused by the BIOS)
FLAG_A     equ 0x3A41            ; "A:" the A: boot sector is being started
FLAG_SKIP  equ 0x2D41            ; "A-" A: was skipped (never twice per INT 19h)
INT_DEF    equ 0xEA85            ; POST's default vector F000:EA85 (90BC)
BOOT_C     equ 0x8FB1            ; INT 19h: CMOS 0Eh bit 3 test, then try C:
S_BADDISK  equ 0x7DB3            ; "  INVALID BOOT DISKETTE" (AMI's message if C: fails too)
DPT_ROM    equ 0xEFC7            ; diskette parameter table, INT 1Eh (8F84)
TAIL_LINE1 equ 63                ; CR LF + " The 80286 cannot run this code. It needs a 386 or newer CPU."
                                 ; (the first line of Step 2's msg_tail; build.py checks it)

section boot1 start=0xF474 vstart=0xF474   ; F474-F4F9 (code before and after)

; ---------------------------------------------------------------------
; int19_entry -- hook at 8F80 (INT 19h): no drive started yet.
; Does what it replaces: AX = 0, ES = 0.
; ---------------------------------------------------------------------
int19_entry:
    xor  ax, ax
    mov  es, ax
    mov  [es:BOOT_FLAG], ax
    ret

; ---------------------------------------------------------------------
; int19_a -- hook at 8FDF: A:'s boot sector was read (ES = 0, BX = 7C00)
; and is about to be checked and started. Does what it replaces:
; DI = BX, AX = the first word of the sector.
; ---------------------------------------------------------------------
int19_a:
    mov  word [es:BOOT_FLAG], FLAG_A
    mov  di, bx
    mov  ax, [es:di]
    ret

; ---------------------------------------------------------------------
; int6_boot -- at EB2E, for every invalid opcode AMI does not handle
; itself (LOADALL, LOCK). [SP] = IP, [SP+2] = CS, [SP+4] = FLAGS, all
; registers as the program left them.
; ---------------------------------------------------------------------
int6_boot:
    push ds
    push ax
    xor  ax, ax
    mov  ds, ax
    cmp  word [BOOT_FLAG], FLAG_A          ; booting from A:?
    jne  .halt
    cmp  word [0x21 * 4], INT_DEF          ; and DOS not loaded yet?
    jne  .halt
    mov  ax, cs
    cmp  [0x21 * 4 + 2], ax
    je   .skip
.halt:
    pop  ax
    pop  ds
    jmp  int6_halt                         ; Step 2: message and halt

; --- A: is skipped: the message, then on to C:. DS = 0. Nothing of the
; boot sector is needed any more (its AX and DS stay on the stack).
.skip:
    mov  word [BOOT_FLAG], FLAG_SKIP       ; once per INT 19h
    pop  ax                                ; (the stack is reset before C:)
    pop  ax
    pop  di                                ; faulting IP
    pop  dx                                ; faulting CS
    mov  al, 0x20                          ; end of interrupt, in case
    out  0xA0, al
    out  0x20, al
    call skip_mode
    mov  si, msg_head                      ; Step 2's text and helpers
    call int6_halt.puts
    mov  ax, dx
    call int6_halt.hex16
    mov  al, ':'
    call int6_halt.putc
    mov  ax, di
    call int6_halt.hex16
    call skip_where
    mov  si, msg_tail                      ; Step 2's text, first line only
    mov  cx, TAIL_LINE1
.l1:
    mov  al, [cs:si]
    inc  si
    call int6_halt.putc
    loop .l1
    mov  si, msg_skip
    call int6_halt.puts
    jmp  skip_go

section boot2 start=0x7EBA vstart=0x7EBA   ; 7EBA-7EFF (7EB9 ends "PARITY ERROR ????"; no checksum here)

; ---------------------------------------------------------------------
; skip_go -- on to C:, as AMI's INT 19h does when A: holds no boot disk
; ---------------------------------------------------------------------
skip_go:
    cli
    xor  ax, ax
    mov  es, ax
    mov  word [es:0x1E * 4], DPT_ROM       ; INT 1Eh, as 8F84 sets it
    mov  [es:0x1E * 4 + 2], cs
    mov  ax, 0x30                          ; the stack POST boots with
    mov  ss, ax
    mov  sp, 0x100
    sti
    xor  dx, dx                            ; (9005 reads with head DH)
    mov  bx, 0x7C00
    mov  si, S_BADDISK
    jmp  BOOT_C

; ---------------------------------------------------------------------
; skip_mode -- a text mode the message can be read in, as in Step 2.
; Out: BH = page, BL = 07h. DS = 0.
; ---------------------------------------------------------------------
skip_mode:
    mov  ah, 0x0F
    int  0x10
    cmp  al, 3
    jbe  .text
    cmp  al, 7
    je   .text
    mov  al, [0x410]                       ; equipment: initial video mode bits 5:4
    and  al, 0x30
    cmp  al, 0x30
    mov  ax, 0x0003
    jne  .set
    mov  al, 0x07
.set:
    int  0x10
    xor  bh, bh
.text:
    mov  bl, 0x07
    ret

section boot4 start=0x7FD4 vstart=0x7FD4   ; 7FD4-7FFF, after Step 3's code

msg_skip db 13, 10, ' Drive A: skipped. Booting from C: ...', 13, 10, 0

section boot3 start=0xDFBB vstart=0xDFBB   ; DFBB-DFFF (DFBA ends "Dec")

; ---------------------------------------------------------------------
; skip_where -- after "Invalid opcode at CS:IP": " (boot sector)" if
; it is in 0000:7C00-7DFF, and the bytes there. DX:DI = CS:IP.
; ---------------------------------------------------------------------
skip_where:
    mov  ax, dx                            ; linear address in 0000:7C00-7DFF?
    shl  ax, 4
    mov  cx, dx
    shr  cx, 12
    add  ax, di
    adc  cx, 0
    sub  ax, 0x7C00
    sbb  cx, 0
    jnz  .bytes
    cmp  ax, 0x200
    jae  .bytes
    mov  si, msg_boot
    call int6_halt.puts
.bytes:
    mov  si, msg_bytes
    call int6_halt.puts
    mov  es, dx
    mov  cx, 6
.bl:
    mov  al, [es:di]
    call int6_halt.hex8
    mov  al, ' '
    call int6_halt.putc
    inc  di
    loop .bl
    ret
