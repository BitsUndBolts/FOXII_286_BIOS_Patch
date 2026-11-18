; =====================================================================
;  Step 3: IDE auto-detection during POST
;
;  POST checkpoint 75h (943E) reads CMOS 12h at 9447 and runs the
;  fixed-disk setup A857 (checkpoint 76h) only if it is non-zero. A857
;  reads CMOS 12h again at A894. py/build.py turns both reads
;  (MOV AL,92h / CALL EE9F, 5 bytes) into a CALL and two NOPs:
;
;    9447: CALL autodet     auto-detect, then AL = CMOS 12h as drives12
;    A894: CALL drives12    AL = CMOS 12h without the drives that are gone
;
;  autodet: for each drive whose type in CMOS 12h is 0 ("Not installed")
;  and that answers IDENTIFY DEVICE, write type 47 with the geometry the
;  drive reports (IDENTIFY words 1, 3, 6) and fix the CMOS checksum
;  (10h-2Dh -> 2Eh/2Fh). Drives the user set up are never touched: no
;  command is sent to them.
;
;  drives12: CMOS 12h with the type nibble of every configured drive for
;  which nothing answers on the bus (status FFh, 7Fh or 00h) cleared.
;  CMOS itself is not changed: the drop lasts for this boot only, so a
;  type the user entered survives a boot with the drive unplugged, and
;  AMI does not wait about a minute for the drive and then stop with
;  "HDD controller failure". A drive that answers but is busy is left
;  to AMI, which waits for it as before.
;
;  Both entries keep every register except AL, as the CMOS read they
;  replace does (A857 needs AH = 0 after A894). The CMOS is only read
;  here when AMI found it valid: checkpoint 75h skips the disk setup,
;  and with it both hooks, when CMOS 0Eh bits 7:6 are set.
;
;  Timing: at 9447 interrupts are on and the BIOS tick counter 40:6Ch
;  runs (A857 relies on it too); waits are counted in ticks (55 ms).
;  IRQ 14 is still masked (AMI's INT 13h reset unmasks it later), so
;  the drive is polled; reading the status register at the end clears
;  the drive's interrupt request.
; =====================================================================

CMOS_RD   equ 0xEE9F             ; AL = index -> AL (AMI, keeps the NMI bit)
CMOS_WR   equ 0xEEAE             ; AL = index, AH = value (AMI)
T_READY   equ 182                ; 10 s: a drive spinning up becomes ready
T_ID      equ 36                 ; 2 s: a ready drive answers IDENTIFY
MAX_CYL   equ 16383              ; the largest ATA CHS cylinder count

section auto1 start=0x7F0F vstart=0x7F0F   ; 7F0F-7FFF (no checksum covers it; 7F0E ends the ID string)

; ---------------------------------------------------------------------
; autodet -- hook at 9447 (checkpoint 75h)
; ---------------------------------------------------------------------
autodet:
    sti                          ; (already on: the tick counter must run)
    pusha
    push ds
    push 0x40
    pop  ds
    xor  bx, bx                  ; BL = 0: C:, then 1: D:
.drive:
    mov  al, 0x12
    call CMOS_RD
    or   bl, bl
    jnz  .lo
    shr  al, 4
.lo:and  al, 0x0F
    jnz  .next                   ; set up by the user: never touched
    call identify
    jc   .next
    call set47
.next:
    inc  bx
    cmp  bl, 2
    jb   .drive
    pop  ds
    popa
    ; fall through: AL = CMOS 12h for AMI's test at 944C

; ---------------------------------------------------------------------
; drives12 -- hook at A894: AL = CMOS 12h without the drives that do not
; answer at all. Keeps every other register.
; ---------------------------------------------------------------------
drives12:
    push cx
    push dx
    push bx
    mov  al, 0x12
    call CMOS_RD
    mov  cl, al
    xor  bx, bx
.d: mov  ch, 0xF0                ; C: is the high nibble
    or   bl, bl
    jz   .m
    mov  ch, 0x0F
.m: test cl, ch
    jz   .n                      ; not set up: nothing to drop
    call select
    jnc  .n                      ; something answers (ready or busy)
    not  ch
    and  cl, ch                  ; gone: "Not installed" for this boot
.n: inc  bx
    cmp  bl, 2
    jb   .d
    xor  bl, bl                  ; leave the master selected: a missing
    call select                  ; slave must not stay selected
    mov  al, cl
    pop  bx
    pop  dx
    pop  cx
    ret

; ---------------------------------------------------------------------
; select -- BL = drive: select it, wait 400 ns, read the status.
; Out: DX = 1F7h, AL = status; CF=1 if nothing answers (FFh: floating
; bus, 7Fh: floating with DD7 pulled down, 00h: the master answering for
; a slave that is not there).
; ---------------------------------------------------------------------
select:
    mov  dx, 0x1F6
    mov  al, bl
    shl  al, 4
    or   al, 0xA0
    out  dx, al
    inc  dx
    in   al, dx                  ; four reads: the 400 ns the drive may
    in   al, dx                  ; take before its status is valid
    in   al, dx
    in   al, dx
    cmp  al, 0xFF
    je   .none
    cmp  al, 0x7F
    je   .none
    cmp  al, 1                   ; CF=1 if 00h
    ret
.none:
    stc
    ret

; ---------------------------------------------------------------------
; ide_wait -- poll 1F7h until (status AND AH) = AL, at most CX ticks.
; If AH has bit 0, ERR with BSY clear ends the wait as a failure.
; In: DX = 1F7h, DS = 40h. Out: CF=1 on timeout or error.
; ---------------------------------------------------------------------
ide_wait:
    push bx
    push si
    mov  bx, ax
    mov  si, [0x6C]
.l: in   al, dx
    test bh, 1
    jz   .t
    mov  ah, al
    and  ah, 0x81
    cmp  ah, 0x01
    je   .e
.t: and  al, bh
    cmp  al, bl
    je   .ok                     ; (CF=0)
    mov  ax, [0x6C]
    sub  ax, si
    cmp  ax, cx
    jb   .l
.e: stc
.ok:pop  si
    pop  bx
    ret
; ---------------------------------------------------------------------
; cmos_sum -- the CMOS checksum AMI checks at POST (82B2) and setup
; writes (C0B9): byte sum of 10h-2Dh, high byte to 2Eh, low byte to 2Fh
; ---------------------------------------------------------------------
cmos_sum:
    xor  dx, dx
    mov  al, 0x10
.sum:
    push ax
    call CMOS_RD
    xor  ah, ah
    add  dx, ax
    pop  ax
    inc  ax
    cmp  al, 0x2E
    jb   .sum
    mov  ah, dh                  ; 2Eh = high byte
    call CMOS_WR
    mov  al, 0x2F
    mov  ah, dl
    jmp  CMOS_WR

; cmos_wr_next -- write AH to CMOS index AL, then AL = AL + 1
cmos_wr_next:
    call CMOS_WR
    inc  ax
    ret
auto1_end:

section auto2 start=0xE32D vstart=0xE32D   ; E32D-E3FD (E32C ends the copyright line at E300)

; ---------------------------------------------------------------------
; identify -- BL = drive: IDENTIFY DEVICE by polling.
; Out: CF=0: CX = cylinders, DL = heads, DH = sectors (words 1, 3, 6;
; 1-16383 / 1-16 / 1-63). CF=1: no drive, no answer, or an ATAPI
; device (it aborts IDENTIFY DEVICE). BL is kept.
; ---------------------------------------------------------------------
identify:
    call select
    jc   .r
    mov  ax, 0x8000              ; not busy: a drive may still spin up.
    mov  cx, T_READY             ; The master ignores a new drive select
    call ide_wait                    ; while it is busy, so select again
    jc   .r                      ; once it is not.
    call select
    jc   .r
    mov  ax, 0xC040              ; BSY=0, DRDY=1
    mov  cx, T_ID
    call ide_wait
    jc   .r
    mov  al, 0xEC                ; IDENTIFY DEVICE
    out  dx, al
    mov  ax, 0x8908              ; BSY=0, DRQ=1; ERR ends the wait
    call ide_wait                    ; (CX = T_ID still)
    jc   .r
    mov  dl, 0xF0
    xor  cx, cx
.w: in   ax, dx                  ; all 256 words, keep three
    cmp  cl, 1
    jne  .h
    mov  si, ax                  ; word 1: cylinders
.h: cmp  cl, 3
    jne  .s
    mov  di, ax                  ; word 3: heads
.s: cmp  cl, 6
    jne  .n
    mov  bh, al                  ; word 6: sectors per track
.n: inc  cx
    cmp  cx, 256
    jb   .w
    mov  dl, 0xF7
    in   al, dx                  ; status read: clears the drive's IRQ
    mov  cx, si
    jcxz .bad                    ; cylinders 1-16383
    cmp  cx, MAX_CYL
    ja   .bad
    mov  dx, di
    cmp  dx, 16                  ; heads 1-16
    ja   .bad
    or   dl, dl
    jz   .bad
    mov  dh, bh
    or   dh, dh                  ; sectors 1-63
    jz   .bad
    cmp  dh, 63
    ja   .bad
    clc
.r: ret
.bad:
    stc
    ret

; ---------------------------------------------------------------------
; set47 -- BL = drive, CX/DL/DH = cylinders/heads/sectors: CMOS type 47
; (nibble 0Fh in 12h, 47 in 19h/1Ah, parameters at 1Bh/24h in AMI's
; order: cylinders, heads, write precompensation (none), control byte,
; landing zone (= cylinders), sectors), then the CMOS checksum.
; ---------------------------------------------------------------------
set47:
    mov  al, 0x12
    call CMOS_RD
    mov  ah, 0xF0
    or   bl, bl
    jz   .c
    mov  ah, 0x0F
.c: or   ah, al                  ; the other drive's nibble stays
    mov  al, 0x12
    call CMOS_WR
    mov  al, 0x19
    add  al, bl
    mov  ah, 47
    call CMOS_WR
    mov  al, 0x1B                ; C: 1Bh-23h, D: 24h-2Ch
    or   bl, bl
    jz   .p
    mov  al, 0x24
.p: mov  ah, cl
    call cmos_wr_next                     ; cylinders
    mov  ah, ch
    call cmos_wr_next
    mov  ah, dl
    call cmos_wr_next                     ; heads
    mov  ah, 0xFF
    call cmos_wr_next                     ; write precompensation: none
    call cmos_wr_next
    mov  ah, 0
    cmp  dl, 8
    jbe  .cb
    mov  ah, 8                   ; control byte: more than 8 heads
.cb:call cmos_wr_next
    mov  ah, cl
    call cmos_wr_next                     ; landing zone = cylinders
    mov  ah, ch
    call cmos_wr_next
    mov  ah, dh
    call cmos_wr_next                     ; sectors
    jmp  cmos_sum
auto2_end:
