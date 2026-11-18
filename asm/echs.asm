BITS 16
CPU 286             ; the FOX II is an 80286: any 386 instruction is an assembler error
ORG 0xF537          ; free-space block F537-F840 in segment F000

; =====================================================================
;  ECHS (CHS translation) for the AMI 286 BIOS 06/13/90, Octek FOX II
;
;  A 286 port of the SOYO SY-019L1 patch (asm/xlate.asm there, v5,
;  confirmed on hardware). The algorithm, the five patch sites and their
;  contracts are the same; only the 32-bit arithmetic of xlate_headcyl
;  is redone in 16-bit pieces, because the 286 has no EAX/MOVZX/PUSHAD.
;
;  Drives up to 1024 x 255 x 63 x 512 = 8.42 GB (7.84 GiB) through
;  classic INT 13h CHS, instead of 1024 x 16 x 63 = 504 MB.
;
;  Reached from five patch sites (applied and asserted by py/build.py):
;    A357-A383   AH=08h reporting body -> CALL xlate_getparams / JMP A384
;    A65A        AND DH,0Fh            -> CALL xlate_headcyl
;    A30C, A4DF, A832  cylinder-high builders before OUT 1F5h
;                -> MOV AL,[BP+6] + NOP fill (the byte xlate_headcyl stores)
;  This BIOS has no checksum over this area (see docs/ROM_ANALYSIS.md 2).
; =====================================================================

; ---------------------------------------------------------------
; calc_factor
;   In:  AX = RealCyl, CX = RealHeads
;   Out: AX = TranslatedHeads: RealHeads * 2^n until the cylinders fit
;        in 1024, never more than 255 (16, 32, 64, 128, then 255).
;        256 heads breaks DOS (SOYO pitfall 9.6).
;   Preserves everything else.
; ---------------------------------------------------------------
calc_factor:
    push bx
    mov  bx, ax            ; bx = working cylinder count
    mov  ax, cx            ; ax = candidate head count
.loop:
    cmp  bx, 1024
    jbe  .done
    cmp  ax, 127
    ja   .max
    shl  ax, 1
    shr  bx, 1
    jmp  .loop
.max:
    mov  ax, 255
.done:
    pop  bx
    ret

; ---------------------------------------------------------------
; div32: DX:AX / CX  (CX != 0)
;   Out: DX:AX = quotient (32 bit), BX = remainder
;   A 286 DIV only takes a 16-bit quotient, so divide the high word
;   first and carry its remainder into the low word.
; ---------------------------------------------------------------
div32:
    push ax
    mov  ax, dx
    xor  dx, dx
    div  cx                ; ax = high quotient, dx = remainder
    mov  bx, ax
    pop  ax
    div  cx                ; ax = low quotient, dx = remainder
    xchg bx, dx            ; dx = high quotient, bx = remainder
    ret

; ---------------------------------------------------------------
; xlate_getparams  (replaces the AH=08h reporting body A357-A383,
;                   which is byte-identical to the SOYO's A659-A685)
;   In:  ES:BX -> FDPT (+0 cylinders, +2 heads, +0Eh sectors)
;   Out: CH/CL/DH = translated geometry, AL = sectors per track.
;        The original tail at A384 sets DL = number of drives and AH = 0.
; ---------------------------------------------------------------
xlate_getparams:
    push bx
    push si
    push di
    mov  dx, word [es:bx]         ; RealCyl
    xor  ch, ch
    mov  cl, byte [es:bx+2]       ; RealHeads
    mov  al, byte [es:bx+0x0e]    ; RealSectors
    xor  ah, ah
    push ax                       ; RealSectors
    push cx                       ; RealHeads
    push dx                       ; RealCyl
    mov  ax, dx
    call calc_factor
    mov  di, ax                   ; TranslatedHeads

    pop  ax                       ; RealCyl
    pop  cx                       ; RealHeads
    mul  cx                       ; dx:ax = RealCyl * RealHeads
    div  di                       ; ax = logical cylinders (<= RealCyl, fits)

    sub  ax, 2                    ; original "-2" convention
    cmp  ax, 0x3ff
    jbe  .cylok
    mov  ax, 0x3ff
.cylok:
    mov  ch, al
    mov  bl, ah
    shl  bl, 6
    mov  cl, bl
    pop  ax                       ; RealSectors
    or   cl, al

    push ax
    mov  ax, di
    dec  ax
    mov  dh, al                   ; max head index
    pop  ax                       ; AL = sectors, AH = 0

    pop  di
    pop  si
    pop  bx
    ret

; ---------------------------------------------------------------
; xlate_headcyl  (replaces "AND DH,0Fh" at A65A in drive-select A619)
;
;   Entry, exactly as at the original instruction:
;     DH    = caller's (logical) head
;     DI    = INT 13h function * 2
;     ES:BX = FDPT of the drive
;     Stack: [ret][orig CX][orig DX][BX][ES] (pushed at A631)
;     BP    = INT 13h frame
;   Exit:
;     DH         = physical head
;     saved CX   = physical cylinder low / bits 9:8 / sector
;     frame [bp+6] = physical cylinder high byte (port 1F5h value)
;   The caller's DH in the frame ([bp+15h]) is only read, never written.
;
;   Only AH=02,03,04,05,0A,0B,0C (DI=04,06,08,0A,14,16,18) carry an
;   address. Everything else gets the original behaviour.
; ---------------------------------------------------------------
xlate_headcyl:
    push bp
    mov  bp, sp                   ; [bp+0] frame bp, [bp+4] orig CX, [bp+6] orig DX
    cmp  di, 0x04
    je   .xl
    cmp  di, 0x06
    je   .xl
    cmp  di, 0x08
    je   .xl
    cmp  di, 0x0a
    je   .xl
    cmp  di, 0x14
    je   .xl
    cmp  di, 0x16
    je   .xl
    cmp  di, 0x18
    je   .xl

    ; ---- not translated: the original ROM's arithmetic ----
    push ax
    push bx
    mov  bx, [bp+0]
    mov  al, [bp+4]               ; orig CL
    shr  al, 6
    mov  ah, [ss:bx+0x15]         ; frame DH: AMI cylinder bits 11:10 in bits 7:6
    shr  ah, 4
    and  ah, 0x0c
    or   al, ah
    mov  [ss:bx+6], al
    pop  bx
    pop  ax
    and  dh, 0x0f
    pop  bp
    ret

.xl:
    sub  sp, 12                   ; -2 logC -4 logH -6 logS -8 realH -10 realS -12 transH
    push ax                       ; only what this path changes (not PUSHA:
    push bx                       ;  every byte counts on the POST stack)
    push cx
    push dx
    push si

    mov  si, word [es:bx]         ; RealCyl
    mov  cl, byte [es:bx+2]
    xor  ch, ch
    mov  [bp-8], cx               ; RealHeads
    mov  dl, byte [es:bx+0x0e]
    xor  dh, dh
    mov  [bp-10], dx              ; RealSectors
    mov  ax, si
    call calc_factor
    mov  [bp-12], ax              ; TranslatedHeads

    mov  ax, [bp+4]               ; orig CX
    mov  bl, al
    and  bl, 0x3f
    xor  bh, bh
    mov  [bp-6], bx               ; logical sector
    mov  bl, al
    and  bl, 0xc0
    shr  bl, 6
    xor  bh, bh
    mov  dl, ah
    xor  dh, dh
    shl  bx, 8
    or   bx, dx
    mov  [bp-2], bx               ; logical cylinder (10 bit)
    mov  al, [bp+7]               ; orig DH
    xor  ah, ah
    mov  [bp-4], ax               ; logical head

    ; LBA = (logC * transH + logH) * S + logS - 1   (< 2^24, 32-bit in DX:AX)
    mov  ax, [bp-2]
    mul  word [bp-12]             ; dx:ax = logC * transH (<= 1023*255)
    add  ax, [bp-4]
    adc  dx, 0
    mov  bx, ax                   ; bx = low word
    mov  ax, dx
    mul  word [bp-10]             ; high word * S (fits: result < 2^24)
    mov  cx, ax                   ; cx = high part
    mov  ax, bx
    mul  word [bp-10]             ; dx:ax = low word * S
    add  dx, cx
    mov  cx, [bp-6]
    dec  cx
    add  ax, cx
    adc  dx, 0                    ; dx:ax = LBA

    ; sector = LBA mod S + 1,  rest = LBA / S
    mov  cx, [bp-10]
    call div32                    ; dx:ax = LBA / S, bx = LBA mod S
    inc  bx
    mov  [bp-6], bx               ; physical sector
    ; head = rest mod realH, cylinder = rest / realH
    mov  cx, [bp-8]
    call div32                    ; ax = physical cylinder, bx = physical head
    mov  [bp-4], bx
    mov  [bp-2], ax

    mov  bx, [bp+0]
    mov  [ss:bx+6], ah            ; cylinder high byte -> frame [bp+6]

    mov  ax, [bp-2]
    mov  bh, al                   ; CH = cylinder low
    mov  bl, ah
    shl  bl, 6                    ; CL 7:6 = cylinder bits 9:8
    mov  cx, [bp-6]
    or   bl, cl                   ; CL 5:0 = sector
    mov  [bp+4], bx               ; saved CX := physical CX

    pop  si
    pop  dx
    pop  cx
    pop  bx
    pop  ax
    mov  dh, byte [bp-4]          ; physical head
    add  sp, 12
    pop  bp
    ret
