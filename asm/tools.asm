; =====================================================================
;  Round 6b: the tools of BUBios/286 (setup's Tools page)
;
;  Each tool is an action on the Tools page (setup.asm, fields): it draws
;  its own page over rows 3-23, runs, waits for ESC (or Enter where the
;  key row offers it) and returns; s_key then redraws the Tools page.
;
;    t_info    Hard disk C:/D: info and auto-detect (IDENTIFY DEVICE)
;    t_part    Partition check (MBR, extended chain, each FAT BPB) against
;              the geometry the BIOS gives DOS (INT 13h AH=08h)
;    t_speed   Disk speed through INT 13h (read at start / middle / end,
;              access time)
;    t_mem     Memory test: base 64-640 KB, extended (INT 15h AH=87h),
;              the EMS pages through the HT12's window 0
;    t_umb     HT12UMB.SYS in this ROM (F000:6000) and the DEBUG recipe
;  and, for the POST screen (post.asm, bu_final):
;    part_post one warning line when C:'s partitions do not fit the BIOS
;
;  Runs in setup (DS = 40h, ES = the text buffer, BP = AMI's setup frame
;  with the CMOS buffer at [BP+10h..3Fh]) or at the end of POST (DS = 40h).
;  Memory the tools use, all free while setup runs (POST has cleared
;  0:0500-7BFF; DOS is not loaded):
;    0:1000-8FFF   disk and test buffers (TBUF, 32 KB)
;    0:9000-902F   the GDT for INT 15h AH=87h (TGDT)
;    0:9040-90FF   variables (40:8C40-, so they are reached with DS = 40h)
;  Not 0:F000-102FF: setup's stack is 0030:0100, and AMI's setup frame
;  takes it below 0030:0000, so SP wraps to 0030:FCxx (0:FFxx-102FF).
;  The base memory test starts at 68 KB, above all of them.
; =====================================================================

TGDT       equ 0x0900     ; segment of the INT 15h AH=87h GDT (0:9000)
TBUF       equ 0x0100     ; segment of the buffers (0:1000-8FFF)
TV         equ 0x8C40     ; variables, DS = 40h (0:9040)
M_BASE0    equ 68         ; KB: where the base memory test starts
V_C        equ TV + 0     ; word: cylinders the BIOS gives DOS (INT 13h AH=08h)
V_H        equ TV + 2     ; word: heads
V_S        equ TV + 4     ; word: sectors per track
V_DRV      equ TV + 6     ; byte: 80h / 81h
V_ROW      equ TV + 7     ; byte: next row of a list
V_BAD      equ TV + 8     ; byte: mismatches found (partition check)
V_MH       equ TV + 9     ; byte: heads the partitions were made with
V_MS       equ TV + 10    ; byte: sectors per track they were made with
V_NUM      equ TV + 11    ; byte: partition number shown
V_EXT      equ TV + 12    ; dword: LBA of the extended partition
V_EBR      equ TV + 16    ; dword: LBA of the current EBR
V_P        equ TV + 20    ; dword: partition start (absolute LBA)
V_N        equ TV + 24    ; dword: partition size
V_T0       equ TV + 28    ; word: timer tick at the start
V_CNT      equ TV + 30    ; word: sectors / operations counted
V_CYL      equ TV + 32    ; word
V_HD       equ TV + 34    ; word
V_RND      equ TV + 36    ; word: random number
V_ERR      equ TV + 38    ; dword: errors (memory test)
V_PAT      equ TV + 42    ; byte: pattern number
V_FR       equ TV + 43    ; byte: EMS frame position 0-7 (0FFh: none)
V_E19      equ TV + 44    ; byte: HT12 reg 19h before the test
V_E20      equ TV + 45    ; byte: HT12 reg 20h before the test
V_PG       equ TV + 46    ; word: first EMS page
V_NPG      equ TV + 48    ; word: EMS pages
V_FAIL     equ TV + 50    ; 3 words: first error: segment, offset, XOR (bits)
V_FAILW    equ TV + 56    ; word: what was written there
V_LIN      equ TV + 58    ; dword: linear address of the first error
V_STOP     equ TV + 62    ; byte: ESC pressed
V_KB       equ TV + 64    ; word: KB of the area being tested
V_END      equ TV + 66    ; word: end segment / KB

C_TV       equ 20         ; value column of a tool page
R_T1       equ 5          ; first row of a tool's content
T_SECS     equ 36         ; 2 s of timer ticks for each speed measurement

; ---------------------------------------------------------------------
; the Tools page's actions (setup.asm, fields, ROUND6B)
; ---------------------------------------------------------------------
tl_infoc:  mov  bl, 0
           jmp  t_info
tl_infod:  mov  bl, 1
           jmp  t_info
tl_partc:  mov  bl, 0
           jmp  t_part
tl_partd:  mov  bl, 1
           jmp  t_part
tl_speedc: mov  bl, 0
           jmp  t_speed
tl_speedd: mov  bl, 1
           jmp  t_speed
tl_mem:    jmp  t_mem
tl_umb:    jmp  t_umb

; =====================================================================
; page helpers
; =====================================================================
; t_open: SI = title, BX = key row text. Clears rows 3-23, draws the
; title in the accent colour and the key row.
t_open:
    push bx
    push si
    call vid_es_s
    mov  dx, POS(R_TOP, 0)
    mov  cx, 80 * (R_LINE2 - R_TOP)
    call clear_at
    mov  dx, POS(R_HELP, 0)
    mov  cx, 160
    call clear_at
    pop  si
    mov  dx, POS(R_TOP, C_SLBL)
    mov  al, AT_ACCENT
    call text_at
    pop  si
t_keys:                            ; SI = key row text
    push si
    mov  al, ' '
    mov  bl, AT_STAT
    mov  cx, 80
    mov  dx, POS(R_KEYS, 0)
    call fill_at
    pop  si
    mov  dx, POS(R_KEYS, 1)
    mov  al, AT_STAT
    jmp  text_at

; t_line: DH = row, SI = label: the label at column 3, DI at C_TV
t_line:
    mov  dl, C_SLBL
    mov  al, AT_LABEL
    call text_at
    mov  dl, C_TV
    jmp  goto

t_lbl:                             ; CS:SI at DI in the label colour
    mov  al, AT_LABEL
    jmp  short t_col
t_val:                             ; ... in the value colour
    mov  al, AT_VALUE
    jmp  short t_col
t_acc:                             ; ... in the accent colour
    mov  al, AT_ACCENT
    jmp  short t_col
t_err:                             ; ... in the error colour
    mov  al, AT_ERR
t_col:
    call attr
    jmp  pstr

t_chr:                             ; AL at DI in the value colour; BX kept
    push bx
    push ax
    mov  al, AT_VALUE
    call attr
    pop  bx
    mov  al, bl
    stosw
    pop  bx
    ret

t_slash:
    mov  al, '/'
    jmp  t_chr

t_hex2:                            ; AL as two hex digits, value colour
    push cx
    push bx
    push ax
    mov  al, AT_VALUE
    call attr
    mov  bh, ah
    pop  ax
    mov  cx, 2
    call phex
    pop  bx
    pop  cx
    ret

t_hex4:                            ; AX as four hex digits, value colour
    push cx
    push bx
    push ax
    mov  al, AT_VALUE
    call attr
    mov  bh, ah
    pop  ax
    mov  cx, 4
    call phex
    pop  bx
    pop  cx
    ret

; t_d32: DX:AX unsigned at DI in the value colour; BX CX SI kept
t_d32:
    push bx
    push cx
    push si
    mov  si, 10
    xor  cx, cx
.l: push ax
    mov  ax, dx
    xor  dx, dx
    div  si
    mov  bx, ax
    pop  ax
    div  si
    push dx
    inc  cx
    mov  dx, bx
    or   bx, ax
    jnz  .l
    mov  al, AT_VALUE
    call attr
.o: pop  bx
    mov  al, bl
    add  al, '0'
    stosw
    loop .o
    pop  si
    pop  cx
    pop  bx
    ret

; t_mb: DX:AX sectors -> "n MB" at DI
t_mb:
    mov  cx, 11
.s: shr  dx, 1
    rcr  ax, 1
    loop .s
    call t_d32
    mov  si, s_mb
    jmp  t_val

; t_wait: wait for ESC (CF = 0) or, if AL = 1, Enter too (CF = 1).
; BX CX DX SI DI kept.
t_wait:
    push bx
    mov  bl, al
.k: xor  ah, ah
    int  0x16
    cmp  ah, 0x01
    je   .esc
    cmp  bl, 1
    jne  .k
    cmp  ah, 0x1C
    jne  .k
    pop  bx
    stc
    ret
.esc:
    pop  bx
    clc
    ret

; t_esc: CF = 1 if ESC was pressed (other keys are dropped)
t_esc:
    mov  ah, 1
    int  0x16
    jz   .n
    xor  ah, ah
    int  0x16
    cmp  ah, 0x01
    jne  .n
    mov  byte [V_STOP], 1
    stc
    ret
.n: clc
    ret

; tb_w: AX = word TBUF:SI;  tb_b: AL = byte
tb_w:
    push ds
    push TBUF
    pop  ds
    mov  ax, [si]
    pop  ds
    ret
tb_b:
    push ds
    push TBUF
    pop  ds
    mov  al, [si]
    pop  ds
    ret

; mul32: DX:AX = DX:AX x BX (low 32 bits); BX CX kept
mul32:
    push cx
    mov  cx, ax
    mov  ax, dx
    mul  bx
    xchg ax, cx
    mul  bx
    add  dx, cx
    pop  cx
    ret

; =====================================================================
; geometry and sector reads through INT 13h
; =====================================================================
; t_geo: BL = drive -> [V_C], [V_H], [V_S], [V_DRV]; CF = 1: the BIOS has
; no such drive in this POST
t_geo:
    push bx
    mov  dl, bl
    or   dl, 0x80
    mov  [V_DRV], dl
    mov  ah, 0x08
    push es
    push di
    int  0x13
    pop  di
    pop  es
    jc   .r
    mov  al, [V_DRV]               ; DL = number of drives
    and  al, 0x7F
    cmp  al, dl
    jae  .no
    mov  al, cl                    ; cylinders: CH + CL bits 7-6, + 1
    shl  ax, 2
    mov  al, ch
    and  ax, 0x03FF
    inc  ax
    mov  [V_C], ax
    mov  al, dh
    xor  ah, ah
    inc  ax
    mov  [V_H], ax
    mov  al, cl
    and  ax, 0x3F
    jz   .no
    mov  [V_S], ax
    clc
.r: pop  bx
    ret
.no:stc
    pop  bx
    ret

; rd_chs: read one sector, CX/DH as INT 13h, to TBUF:BX -> CF, AH. Tries 3x.
rd_chs:
    push di
    mov  di, 3
.t: push es
    push bx
    push cx
    push dx
    push TBUF
    pop  es
    mov  dl, [V_DRV]
    mov  ax, 0x0201
    int  0x13
    pop  dx
    pop  cx
    pop  bx
    pop  es
    jnc  .r
    push ax
    xor  ah, ah                    ; reset, then again
    mov  dl, [V_DRV]
    int  0x13
    pop  ax
    dec  di
    jnz  .t
    stc
.r: pop  di
    ret

; rd_lba: DX:AX = LBA -> one sector to TBUF:BX (CHS from [V_H]/[V_S]);
; CF = 1: beyond what CHS reaches, or a read error
rd_lba:
    push cx
    push dx
    push ax
    push bx
    mov  bx, [V_S]
    push ax                        ; sector = LBA mod S + 1
    mov  ax, dx
    xor  dx, dx
    div  bx                        ; (DX:AX / S in two steps)
    mov  cx, ax
    pop  ax
    div  bx
    inc  dx
    push dx                        ; [sector]
    mov  dx, cx                    ; DX:AX = LBA / S
    mov  bx, [V_H]
    cmp  dx, bx                    ; quotient / H must fit 16 bits
    jae  .far
    div  bx                        ; AX = cylinder, DX = head
    cmp  ax, [V_C]
    jae  .far
    mov  ch, al
    mov  cl, ah
    shl  cl, 6
    pop  ax
    or   cl, al
    mov  dh, dl
    pop  bx
    call rd_chs
    pop  ax
    pop  dx
    pop  cx
    ret
.far:
    pop  ax
    pop  bx
    pop  ax
    pop  dx
    pop  cx
    stc
    ret

; =====================================================================
; Disk info and auto-detect
; =====================================================================
t_info:
    push bx
    mov  si, tt_infoc
    or   bl, bl
    jz   .t
    mov  si, tt_infod
.t: mov  bx, k_info
    call t_open
    pop  bx
    push bx
    call t_ident                   ; CF = 0: the 256 words at TBUF:0
    pop  bx
    jnc  .data
    mov  dx, POS(R_T1, C_SLBL)
    call goto
    mov  si, ti_none
    call t_err
    jmp  .bios
.data:
    ; model, serial, firmware
    mov  dh, R_T1
    mov  si, tl_model
    call t_line
    mov  si, 27 * 2
    mov  cx, 20
    call t_idstr
    xor  si, si                    ; a CF card: word 0 = 848Ah
    call tb_w
    cmp  ax, 0x848A
    jne  .ncf
    mov  si, ti_cf
    call t_acc
.ncf:
    mov  dh, R_T1 + 1
    mov  si, tl_serial
    call t_line
    mov  si, 10 * 2
    mov  cx, 10
    call t_idstr
    mov  dh, R_T1 + 2
    mov  si, tl_fw
    call t_line
    mov  si, 23 * 2
    mov  cx, 4
    call t_idstr
    ; geometry: default (1, 3, 6), current (53 bit 0: 54-56)
    mov  dh, R_T1 + 4
    mov  si, tl_geo
    call t_line
    mov  si, 1 * 2
    call t_chs_w
    mov  si, ti_default
    call t_lbl
    mov  si, 53 * 2
    call tb_w
    test al, 1
    jz   .lba
    mov  si, ti_current
    call t_lbl
    mov  si, 54 * 2
    call t_chs_w
.lba:
    ; capacity: LBA sectors (49 bit 9, 60-61), else C x H x S of words 1/3/6
    mov  dh, R_T1 + 5
    mov  si, tl_cap
    call t_line
    mov  si, 49 * 2
    call tb_w
    test ah, 0x02
    jz   .chs
    mov  si, 61 * 2
    call tb_w
    mov  dx, ax
    mov  si, 60 * 2
    call tb_w
    jmp  short .cap
.chs:
    mov  si, 1 * 2
    call tb_w
    mov  bx, ax
    mov  si, 3 * 2
    call tb_w
    mul  bx
    push dx
    push ax
    mov  si, 6 * 2
    call tb_w
    mov  bx, ax
    pop  ax
    pop  dx
    call mul32
.cap:
    push dx
    push ax
    call t_d32
    mov  si, ti_sect
    call t_lbl
    pop  ax
    pop  dx
    call t_mb
    mov  si, 49 * 2                ; LBA or not
    call tb_w
    mov  si, ti_lba
    test ah, 0x02
    jnz  .l1
    mov  si, ti_nolba
.l1:call t_lbl
    ; transfer: PIO mode (51 high byte; 53 bit 1: 64 bits 0/1 = modes 3/4),
    ; multiple sectors (47 low byte, 59), IORDY (49 bit 11), DMA (49 bit 8)
    mov  dh, R_T1 + 6
    mov  si, tl_xfer
    call t_line
    mov  si, ti_pio
    call t_val
    mov  si, 51 * 2
    call tb_w
    mov  al, ah
    xor  ah, ah
    cmp  al, 2
    jbe  .p1
    mov  al, 2
.p1:push ax
    mov  si, 53 * 2
    call tb_w
    test al, 2
    pop  ax
    jz   .p2
    push ax
    mov  si, 64 * 2
    call tb_w
    mov  bl, al
    pop  ax
    test bl, 1
    jz   .p3
    mov  al, 3
.p3:test bl, 2
    jz   .p2
    mov  al, 4
.p2:call pnum_v
    mov  si, ti_mult
    call t_lbl
    mov  si, 47 * 2
    call tb_w
    xor  ah, ah
    or   al, al
    jnz  .m1
    mov  si, ti_no
    call t_val
    jmp  short .m2
.m1:call pnum_v
.m2:mov  si, 49 * 2
    call tb_w
    push ax
    test ah, 0x08
    jz   .io
    mov  si, ti_iordy
    call t_lbl
.io:pop  ax
    test ah, 0x01
    jz   .bios
    mov  si, ti_dma
    call t_lbl
.bios:
    ; what setup has (the buffer) and what the BIOS gives DOS now
    mov  dh, R_T1 + 8
    mov  si, tl_setup
    call t_line
    call hd_type
    or   ax, ax
    jnz  .typ
    mov  si, s_notinst
    call t_val
    jmp  short .now
.typ:
    push ax
    mov  si, s_type
    call t_val
    pop  ax
    call pnum_v
    mov  al, ' '
    call t_chr
    mov  al, ' '
    call t_chr
    call p_cyl
    call pnum_v
    call t_slash
    call p_hd
    call pnum_v
    call t_slash
    call p_sec
    call pnum_v
.now:
    mov  dh, R_T1 + 9
    mov  si, tl_dos
    call t_line
    push bx
    call t_geo
    pop  bx
    jnc  .g
    mov  si, ti_notup
    call t_val
    jmp  short .cmp
.g: call t_chs_v
    mov  si, ti_echs
    call t_lbl
.cmp:
    ; the verdict: setup's C/H/S against IDENTIFY's default C/H/S
    mov  dx, POS(R_T1 + 11, C_SLBL)
    call goto
    call t_idok                    ; (no drive: TBUF:0 was cleared)
    jc   .nodrv
    call hd_type
    or   ax, ax
    jz   .diff
    call p_cyl
    mov  cx, ax
    mov  si, 1 * 2
    call tb_w
    cmp  ax, cx
    jne  .diff
    call p_hd
    mov  cx, ax
    mov  si, 3 * 2
    call tb_w
    cmp  ax, cx
    jne  .diff
    call p_sec
    mov  cx, ax
    mov  si, 6 * 2
    call tb_w
    cmp  ax, cx
    jne  .diff
    mov  si, ti_match
    call t_acc
    jmp  short .wait
.diff:
    mov  si, ti_differ
    call t_err
.wait:
    mov  al, 1                     ; ESC, or Enter: auto-detect
    call t_wait
    jnc  .r
    jmp  act_det                   ; BL = drive: type 47 in the buffer
.nodrv:
    xor  al, al
    call t_wait
.r: ret

; t_idok: CF = 1 if TBUF:0 holds no IDENTIFY data (t_ident failed)
t_idok:
    push si
    mov  si, 1 * 2
    call tb_w
    pop  si
    or   ax, ax
    jnz  .y
    stc
    ret
.y: clc
    ret

; t_idstr: CX words of IDENTIFY text from TBUF:SI (the first character
; in each word's high byte), trailing blanks left out. BX kept.
t_idstr:
    push bx
    shl  cx, 1                     ; CX = characters
.b: jcxz .r
    mov  bx, cx
    dec  bx
    call .ch
    cmp  al, ' '
    je   .tr
    or   al, al
    jne  .go
.tr:dec  cx
    jmp  short .b
.go:xor  bx, bx
.c: call .ch
    or   al, al
    jnz  .p
    mov  al, ' '
.p: call t_chr
    inc  bx
    cmp  bx, cx
    jb   .c
.r: pop  bx
    ret
.ch:                               ; AL = character BX of the text
    push si
    push bx
    xor  bx, 1
    add  si, bx
    call tb_b
    pop  bx
    pop  si
    ret

; t_chs_w: three IDENTIFY words at TBUF:SI, +4, +10 (C, H, S of 1/3/6
; or 54/55/56) as "C/H/S"
t_chs_w:
    call tb_w
    call pnum_v
    call t_slash
    add  si, 2
    cmp  si, 55 * 2
    je   .h
    add  si, 2                     ; words 1 -> 3
.h: call tb_w
    call pnum_v
    call t_slash
    add  si, 2
    cmp  si, 56 * 2
    je   .s
    add  si, 4                     ; words 3 -> 6
.s: call tb_w
    jmp  pnum_v

; t_chs_v: [V_C]/[V_H]/[V_S] as "C/H/S"
t_chs_v:
    mov  ax, [V_C]
    call pnum_v
    call t_slash
    mov  ax, [V_H]
    call pnum_v
    call t_slash
    mov  ax, [V_S]
    jmp  pnum_v

; t_ident: BL = drive -> CF = 0: IDENTIFY DEVICE's 256 words at TBUF:0.
; CF = 1: no drive, no answer, ATAPI (TBUF:0-1FF cleared). As act_det:
; IRQ 14 kept away, the master selected again at the end.
t_ident:
    push es
    push TBUF
    pop  es
    xor  di, di
    mov  cx, 256
    xor  ax, ax
    rep  stosw
    pop  es
    in   al, 0xA1
    push ax
    or   al, 0x40
    out  0xA1, al
    mov  dx, 0x3F6
    mov  al, 0x02
    out  dx, al
    call select
    jc   .end
    mov  ax, 0x8000
    mov  cx, T_READY
    call ide_wait
    jc   .end
    call select
    jc   .end
    mov  ax, 0xC040
    mov  cx, T_ID
    call ide_wait
    jc   .end
    mov  al, 0xEC
    out  dx, al
    mov  ax, 0x8908
    call ide_wait
    jc   .end
    push es
    push TBUF
    pop  es
    xor  di, di
    mov  cx, 256
    mov  dl, 0xF0
    rep  insw
    pop  es
    mov  dl, 0xF7
    in   al, dx
    clc
.end:
    pushf
    mov  dx, 0x3F6
    xor  al, al
    out  dx, al
    mov  dx, 0x1F6
    mov  al, 0xA0
    out  dx, al
    mov  byte [0x8E], 0
    popf
    pop  ax
    pushf
    out  0xA1, al
    popf
    ret

; =====================================================================
; Partition check
; =====================================================================
t_part:
    push bx
    mov  si, tt_partc
    or   bl, bl
    jz   .t
    mov  si, tt_partd
.t: mov  bx, k_back
    call t_open
    pop  bx
    call t_geo
    jnc  .g
    mov  dx, POS(R_T1, C_SLBL)
    call goto
    mov  si, ti_notup
    call t_err
    jmp  .w
.g: mov  dh, R_T1
    mov  si, tl_dos
    call t_line
    call t_chs_v
    mov  si, ti_echs
    call t_lbl
    xor  bx, bx                    ; the MBR
    xor  cx, cx
    inc  cx
    xor  dh, dh
    call rd_chs
    jnc  .rd
    push ax
    mov  dx, POS(R_T1 + 2, C_SLBL)
    call goto
    mov  si, tp_rderr
    call t_err
    pop  ax
    mov  al, ah
    call t_hex2
    jmp  .w
.rd:mov  si, 0x1FE
    call tb_w
    cmp  ax, 0xAA55
    je   .tab
    mov  dx, POS(R_T1 + 2, C_SLBL)
    call goto
    mov  si, tp_nosig
    call t_err
    jmp  .w
.tab:
    mov  si, tp_head               ; the table's header
    mov  dx, POS(R_T1 + 2, C_SLBL)
    mov  al, AT_LABEL
    call text_at
    mov  byte [V_ROW], R_T1 + 3
    xor  ax, ax
    mov  [V_BAD], al
    mov  [V_NUM], al
    mov  [V_EXT], ax
    mov  [V_EXT + 2], ax
    mov  si, 0x1BE                 ; the four primary entries
.pe:push si
    xor  ax, ax                    ; relative to LBA 0
    xor  dx, dx
    xor  bx, bx                    ; (in the MBR at TBUF:0)
    call p_entry
    pop  si
    add  si, 16
    cmp  si, 0x1FE
    jb   .pe
    ; the extended chain: EBRs at TBUF:200
    mov  ax, [V_EXT]
    mov  dx, [V_EXT + 2]
    mov  cx, ax
    or   cx, dx
    jz   .sum
    mov  [V_EBR], ax
    mov  [V_EBR + 2], dx
    mov  cx, 16                    ; at most 16 logical drives
.ebr:
    push cx
    cmp  byte [V_ROW], R_LINE2 - 3
    jae  .full
    mov  ax, [V_EBR]
    mov  dx, [V_EBR + 2]
    mov  bx, 0x200
    call rd_lba
    jc   .ebrerr
    mov  si, 0x3FE
    call tb_w
    cmp  ax, 0xAA55
    jne  .ebrerr
    mov  si, 0x3BE                 ; the logical drive: relative to this EBR
    mov  ax, [V_EBR]
    mov  dx, [V_EBR + 2]
    mov  bx, 0x200
    call p_entry
    mov  si, 0x3D2                 ; the link's type (entry 2 at 3CEh)
    call tb_b
    cmp  al, 0x05
    je   .lnk
    cmp  al, 0x0F
    jne  .full
.lnk:
    mov  si, 0x3D6
    call tb_w
    add  ax, [V_EXT]
    push ax
    mov  si, 0x3D8
    call tb_w
    adc  ax, [V_EXT + 2]
    mov  [V_EBR + 2], ax
    pop  ax
    mov  [V_EBR], ax
    pop  cx
    loop .ebr
    jmp  short .sum
.ebrerr:
    mov  dh, [V_ROW]
    mov  dl, C_SLBL
    call goto
    mov  si, tp_ebrerr
    call t_err
    inc  byte [V_ROW]
.full:
    pop  cx
.sum:
    ; the verdict
    mov  dh, [V_ROW]
    inc  dh
    mov  dl, C_SLBL
    call goto
    cmp  byte [V_NUM], 0
    jne  .some
    mov  si, tp_empty
    call t_val
    jmp  short .w
.some:
    cmp  byte [V_BAD], 0
    jne  .bad
    mov  si, tp_ok
    call t_acc
    jmp  short .w
.bad:
    push dx
    call p_badmsg
    pop  dx
    inc  dh
    mov  dl, C_SLBL
    call goto
    mov  si, tp_bad2
    call t_err
.w: xor  al, al
    call t_wait
    ret

; p_badmsg: "Made with 32 heads / 63 sectors, the BIOS 16 / 63" at DI
p_badmsg:
    mov  si, tp_bad
    call t_err
p_badmsg2:
    mov  al, [V_MH]
    xor  ah, ah
    call t_errnum
    mov  si, tp_heads
    call t_err
    mov  al, [V_MS]
    xor  ah, ah
    call t_errnum
    mov  si, tp_bios
    call t_err
    mov  ax, [V_H]
    call t_errnum
    mov  si, tp_slash
    call t_err
    mov  ax, [V_S]
t_errnum:                          ; AX in the error colour
    push bx
    push ax
    mov  al, AT_ERR
    call attr
    mov  bh, ah
    pop  ax
    call pnum
    pop  bx
    ret

; p_entry: one partition entry at TBUF:SI; DX:AX = the LBA its start is
; relative to; BX = 0 (MBR) or 200h (an EBR). Shows a row (not for
; empty entries or the link in an EBR), notes an extended partition,
; checks CHS against LBA with the BIOS geometry, and a FAT partition's BPB.
p_entry:
    push ax
    push dx
    push si
    add  si, 4
    call tb_b                      ; type
    pop  si
    or   al, al
    jnz  .used
    pop  dx
    pop  ax
    ret
.used:
    cmp  al, 0x05                  ; extended (in the MBR): note it, one row
    je   .ext
    cmp  al, 0x0F
    jne  .part
.ext:
    or   bx, bx
    jnz  .part
    push si
    add  si, 8
    call tb_w
    mov  [V_EXT], ax
    add  si, 2
    call tb_w
    mov  [V_EXT + 2], ax
    pop  si
.part:
    pop  dx
    pop  ax
    push si
    add  si, 8                     ; start = relative + base
    push ax
    call tb_w
    mov  cx, ax
    pop  ax
    add  ax, cx
    adc  dx, 0
    push ax
    add  si, 2
    call tb_w
    add  dx, ax
    pop  ax
    mov  [V_P], ax
    mov  [V_P + 2], dx
    add  si, 2
    call tb_w
    mov  [V_N], ax
    add  si, 2
    call tb_w
    mov  [V_N + 2], ax
    pop  si
    inc  byte [V_NUM]
    ; the row
    mov  dh, [V_ROW]
    mov  dl, C_SLBL
    call goto
    mov  al, [V_NUM]
    xor  ah, ah
    call pnum_v
    mov  dl, C_SLBL + 3            ; active
    call goto
    call tb_b
    mov  ah, al
    mov  al, ' '
    test ah, 0x80
    jz   .a
    mov  al, '*'
.a: call t_chr
    mov  dl, C_SLBL + 5            ; type
    call goto
    push si
    add  si, 4
    call tb_b
    pop  si
    push ax
    call t_hex2
    mov  al, ' '
    call t_chr
    pop  ax
    push si
    call p_tname
    call t_val
    pop  si
    mov  dl, C_SLBL + 20           ; start C/H/S
    call goto
    push si
    inc  si
    call p_chs
    pop  si
    mov  dl, C_SLBL + 33           ; end C/H/S
    call goto
    push si
    add  si, 5
    call p_chs
    pop  si
    mov  dl, C_SLBL + 46           ; size
    call goto
    push si
    mov  ax, [V_N]
    mov  dx, [V_N + 2]
    call t_mb
    pop  si
    ; checks: start and end CHS against LBA (where the CHS is below 1023)
    mov  dh, [V_ROW]
    mov  dl, C_SLBL + 69
    push dx
    xor  cl, cl                    ; CL = 1: a mismatch on this row
    push si
    inc  si
    mov  ax, [V_P]
    mov  dx, [V_P + 2]
    call p_chk
    pop  si
    jc   .m1
    push si
    add  si, 5
    mov  ax, [V_N]
    mov  dx, [V_N + 2]
    sub  ax, 1
    sbb  dx, 0
    add  ax, [V_P]
    adc  dx, [V_P + 2]
    call p_chk
    pop  si
    jnc  .bpb
.m1:mov  cl, 1
    push si                        ; made with: end head + 1, end sector
    add  si, 6
    call tb_b
    and  al, 0x3F
    mov  [V_MS], al
    dec  si
    call tb_b
    inc  al
    mov  [V_MH], al
    pop  si
.bpb:
    ; a FAT partition: its boot sector's BPB
    push si
    add  si, 4
    call tb_b
    pop  si
    mov  ah, al
    cmp  ah, 0x01
    je   .fat
    cmp  ah, 0x04
    je   .fat
    cmp  ah, 0x06
    je   .fat
    cmp  ah, 0x0E
    jne  .mark
.fat:
    push si
    push bx
    push cx
    mov  ax, [V_P]
    mov  dx, [V_P + 2]
    mov  bx, 0x400
    call rd_lba
    pop  cx
    jc   .nob
    mov  si, 0x5FE
    call tb_w
    cmp  ax, 0xAA55
    jne  .nob
    mov  si, 0x40B                 ; 512 bytes per sector
    call tb_w
    cmp  ax, 512
    jne  .nob
    mov  dh, [V_ROW]               ; "H/S" of the BPB
    mov  dl, C_SLBL + 58
    call goto
    mov  si, 0x41A
    call tb_w
    push ax
    call pnum_v
    call t_slash
    mov  si, 0x418
    call tb_w
    push ax
    call pnum_v
    pop  ax                        ; sectors
    pop  dx                        ; heads
    cmp  ax, [V_S]
    jne  .bb
    cmp  dx, [V_H]
    je   .nob
.bb:mov  cl, 1
    mov  [V_MS], al
    mov  [V_MH], dl
.nob:
    pop  bx
    pop  si
.mark:
    pop  dx
    call goto
    or   cl, cl
    jnz  .bad
    mov  si, tp_rowok
    call t_acc
    jmp  short .nx
.bad:
    inc  byte [V_BAD]
    mov  si, tp_rowbad
    call t_err
.nx:inc  byte [V_ROW]
    ret

; p_chs: the CHS triple at TBUF:SI (head, sector + cyl bits, cyl) as C/H/S
p_chs:
    push dx
    call p_rdchs
    push dx
    push cx
    call pnum_v                    ; AX = cylinder
    call t_slash
    pop  ax                        ; head
    call pnum_v
    call t_slash
    pop  ax                        ; sector
    call pnum_v
    pop  dx
    ret

; p_rdchs: TBUF:SI -> AX = cylinder, CX = head, DX = sector
p_rdchs:
    call tb_b
    xor  ah, ah
    mov  cx, ax
    inc  si
    call tb_w                      ; AL = sector + cyl bits 9-8, AH = cyl 7-0
    dec  si
    mov  dl, al
    and  dx, 0x3F
    shr  al, 6
    xchg al, ah                    ; AX = cylinder
    ret

; p_chk: CHS at TBUF:SI against the LBA DX:AX with the BIOS geometry.
; CF = 1: they differ. A cylinder of 1023 (CHS full) is not checked.
p_chk:
    push bx
    push cx
    push ax
    push dx
    call p_rdchs                   ; AX cyl, CX head, DX sector
    cmp  ax, 1023
    jae  .ok
    push dx
    mul  word [V_H]                ; (cyl x H + head) x S + sector - 1
    add  ax, cx
    adc  dx, 0
    mov  bx, [V_S]
    call mul32
    pop  cx
    dec  cx
    add  ax, cx
    adc  dx, 0
    pop  cx                        ; the LBA's high word
    pop  bx                        ; and low word
    push bx
    push cx
    cmp  ax, bx
    jne  .bad
    cmp  dx, cx
    jne  .bad
.ok:clc
    jmp  short .r
.bad:
    stc
.r: pop  dx
    pop  ax
    pop  cx
    pop  bx
    ret

; p_tname: AL = partition type -> CS:SI = its name
p_tname:
    mov  si, pt_names
.l: cmp  byte [cs:si], 0xFF
    je   .r
    cmp  al, [cs:si]
    je   .f
.n: inc  si
    cmp  byte [cs:si], 0
    jne  .n
    inc  si
    jmp  short .l
.f: inc  si
    ret
.r: inc  si                        ; 0FFh: "Other" follows it
    ret
pt_names:
    db 0x01, "FAT12", 0
    db 0x04, "FAT16 <32M", 0
    db 0x05, "Extended", 0
    db 0x06, "FAT16", 0
    db 0x07, "NTFS/HPFS", 0
    db 0x0B, "FAT32", 0
    db 0x0C, "FAT32 LBA", 0
    db 0x0E, "FAT16 LBA", 0
    db 0x0F, "Extend LBA", 0
    db 0x82, "Linux swap", 0
    db 0x83, "Linux", 0
    db 0xFF, "Other", 0

; ---------------------------------------------------------------------
; part_post -- end of POST (post.asm, bu_final): one line under the
; disks when C:'s primary partitions or the first FAT BPB do not fit
; the geometry the BIOS gives DOS. Two sector reads, no waiting; nothing
; on the screen when all is well or C: cannot be read. DS = 40h, ES =
; the text buffer. All registers kept.
; ---------------------------------------------------------------------
R_PART     equ 14         ; the POST screen's row under the disks

part_post:
    pusha
    push es
    push word [0x8C]               ; 40:8C-8D (the disk's status and error
    call vid_es                    ; registers, INT 13h writes them) as POST
    call .chk                      ; left them: INT 19h gets the same BDA
    pop  word [0x8C]
    pop  es
    popa
    ret
.chk:
    mov  bl, 0
    call t_geo
    jc   .r
    xor  bx, bx
    mov  cx, 1
    xor  dh, dh
    call rd_chs
    jc   .r
    mov  si, 0x1FE
    call tb_w
    cmp  ax, 0xAA55
    jne  .r
    mov  si, 0x1BE
.e: push si
    add  si, 4
    call tb_b
    pop  si
    or   al, al
    jz   .nx
    cmp  al, 0x05                  ; the extended partition's own entry:
    je   .nx                       ; only its logical drives would tell
    cmp  al, 0x0F
    je   .nx
    push ax
    push si                        ; start CHS against start LBA
    add  si, 8
    call tb_w
    mov  cx, ax
    add  si, 2
    call tb_w
    mov  dx, ax
    mov  [V_P], cx
    mov  [V_P + 2], dx
    add  si, 2
    call tb_w
    mov  [V_N], ax
    add  si, 2
    call tb_w
    mov  [V_N + 2], ax
    pop  si
    push si
    inc  si
    mov  ax, cx
    call p_chk
    pop  si
    jc   .badc
    push si                        ; end CHS against the last LBA
    add  si, 5
    mov  ax, [V_N]
    mov  dx, [V_N + 2]
    sub  ax, 1
    sbb  dx, 0
    add  ax, [V_P]
    adc  dx, [V_P + 2]
    call p_chk
    pop  si
    jc   .badc
    pop  ax
    cmp  al, 0x01                  ; the first FAT partition's BPB
    je   .fat
    cmp  al, 0x04
    je   .fat
    cmp  al, 0x06
    je   .fat
    cmp  al, 0x0E
    je   .fat
.nx:add  si, 16
    cmp  si, 0x1FE
    jb   .e
    jmp  short .r
.fat:
    mov  ax, [V_P]
    mov  dx, [V_P + 2]
    mov  bx, 0x400
    call rd_lba
    jc   .r
    mov  si, 0x5FE
    call tb_w
    cmp  ax, 0xAA55
    jne  .r
    mov  si, 0x40B
    call tb_w
    cmp  ax, 512
    jne  .r
    mov  si, 0x418
    call tb_w
    mov  cx, ax
    mov  si, 0x41A
    call tb_w
    cmp  cx, [V_S]
    jne  .badb
    cmp  ax, [V_H]
    je   .r
.badb:
    mov  [V_MS], cl
    mov  [V_MH], al
    jmp  short .show
.badc:
    pop  ax
    add  si, 5                     ; made with: end head + 1, end sector
    call tb_b
    inc  al
    mov  [V_MH], al
    inc  si
    call tb_b
    and  al, 0x3F
    mov  [V_MS], al
.show:
    mov  dx, POS(R_PART, C_LBL)
    mov  cx, 78
    call clear_at
    mov  dx, POS(R_PART, C_LBL)
    mov  si, pp_label
    mov  al, AT_ERR
    call text_at
    call p_badmsg2
    mov  si, pp_tail
    call t_err
.r: ret

; =====================================================================
; Disk speed (INT 13h: the BIOS's own path, one track per read)
; =====================================================================
t_speed:
    push bx
    mov  si, tt_speedc
    or   bl, bl
    jz   .t
    mov  si, tt_speedd
.t: mov  bx, k_stop
    call t_open
    pop  bx
    mov  byte [V_STOP], 0
    call t_geo
    jnc  .g
    mov  dx, POS(R_T1, C_SLBL)
    call goto
    mov  si, ti_notup
    call t_err
    jmp  .w
.g: mov  dh, R_T1
    mov  si, tl_dos
    call t_line
    call t_chs_v
    mov  si, ts_how
    call t_lbl
    mov  dh, R_T1 + 2              ; read at the start
    mov  si, ts_start
    xor  ax, ax
    call s_read
    jc   .w
    mov  dh, R_T1 + 3              ; the middle
    mov  si, ts_mid
    mov  ax, [V_C]
    shr  ax, 1
    call s_read
    jc   .w
    mov  dh, R_T1 + 4              ; the last sixteenth
    mov  si, ts_end
    mov  ax, [V_C]
    mov  cl, 4
    shr  ax, cl
    neg  ax
    add  ax, [V_C]
    call s_read
    jc   .w
    mov  dh, R_T1 + 6              ; access time
    mov  si, ts_acc
    call s_access
.w: mov  si, k_back
    call t_keys
    xor  al, al
    call t_wait
    ret

; s_read: DH = row, SI = label, AX = first cylinder: whole tracks for 2 s
; (or to the last cylinder); KB/s on the row. CF = 1: ESC, or stop.
s_read:
    cmp  ax, [V_C]
    jb   .c0
    mov  ax, [V_C]
    dec  ax
.c0:mov  [V_CYL], ax
    push dx
    call t_line
    mov  si, s_dots
    call t_val
    pop  dx
    push dx
    xor  ax, ax
    mov  [V_HD], ax
    mov  [V_CNT], ax
    call t_sync
    mov  [V_T0], ax
.rd:mov  ax, [V_CYL]
    mov  ch, al
    mov  cl, ah
    shl  cl, 6
    or   cl, 1
    mov  dh, [V_HD]
    mov  dl, [V_DRV]
    mov  al, [V_S]
    mov  ah, 0x02
    push es
    push TBUF
    pop  es
    xor  bx, bx
    int  0x13
    pop  es
    jc   .err
    mov  ax, [V_S]
    add  [V_CNT], ax
    inc  word [V_HD]
    mov  ax, [V_HD]
    cmp  ax, [V_H]
    jb   .tm
    mov  word [V_HD], 0
    inc  word [V_CYL]
    mov  ax, [V_CYL]
    cmp  ax, [V_C]
    jae  .done
.tm:mov  ax, [0x6C]
    sub  ax, [V_T0]
    cmp  ax, T_SECS
    jae  .done
    call t_esc
    jnc  .rd
    pop  dx
    jmp  s_stopped
.done:
    mov  cx, [0x6C]
    sub  cx, [V_T0]
    jnz  .c
    inc  cx
.c: mov  ax, [V_CNT]               ; KB/s = sectors x 18.2065 / 2 / ticks
    mov  bx, 9103
    mul  bx
    push ax
    mov  ax, 1000
    push dx
    mul  cx
    mov  cx, ax                    ; ticks x 1000
    pop  dx
    pop  ax
    cmp  dx, cx
    jae  .err                      ; (cannot happen)
    div  cx
    pop  dx
    push ax
    mov  dl, C_TV
    mov  cx, 30
    call clear_at
    call goto
    pop  ax
    call pnum_v
    mov  si, ts_kbs
    call t_val
    clc
    ret
.err:
    pop  dx
    push ax
    mov  dl, C_TV
    mov  cx, 30
    call clear_at
    call goto
    mov  si, tp_rderr
    call t_err
    pop  ax
    mov  al, ah
    call t_hex2
    stc
    ret

s_stopped:                         ; DX = row: "Stopped"
    mov  dl, C_TV
    mov  cx, 30
    call clear_at
    call goto
    mov  si, ts_stopped
    call t_err
    stc
    ret

; s_access: DH = row, SI = label: one sector at a random cylinder and
; head, for 2 s; the average time per read
s_access:
    push dx
    call t_line
    mov  si, s_dots
    call t_val
    pop  dx
    push dx
    mov  word [V_CNT], 0
    call t_sync
    mov  [V_T0], ax
    mov  [V_RND], ax
.rd:call s_rand
    mul  word [V_C]                ; DX = random cylinder
    mov  ax, dx
    mov  ch, al
    mov  cl, ah
    shl  cl, 6
    or   cl, 1
    push cx
    call s_rand
    mul  word [V_H]
    mov  dh, dl
    pop  cx
    xor  bx, bx
    call rd_chs
    jc   .err
    inc  word [V_CNT]
    mov  ax, [0x6C]
    sub  ax, [V_T0]
    cmp  ax, T_SECS
    jae  .done
    call t_esc
    jnc  .rd
    pop  dx
    jmp  s_stopped
.done:
    mov  ax, [0x6C]                ; tenths of ms = ticks x 549.25 / reads
    sub  ax, [V_T0]
    mov  bx, 5493
    mul  bx
    mov  cx, 10
    div  cx
    xor  dx, dx
    div  word [V_CNT]
    pop  dx
    push ax
    mov  dl, C_TV
    mov  cx, 30
    call clear_at
    call goto
    pop  ax
    xor  dx, dx
    mov  cx, 10
    div  cx
    push dx
    call pnum_v
    mov  al, '.'
    call t_chr
    pop  ax
    call pnum_v
    mov  si, ts_ms
    jmp  t_val
.err:
    pop  dx
    push ax
    mov  dl, C_TV
    mov  cx, 30
    call clear_at
    call goto
    mov  si, tp_rderr
    call t_err
    pop  ax
    mov  al, ah
    jmp  t_hex2

s_rand:                            ; AX = the next random number
    mov  ax, [V_RND]
    mov  bx, 25173
    mul  bx
    add  ax, 13849
    mov  [V_RND], ax
    ret

; t_sync: wait for the next timer tick -> AX = 40:6C
t_sync:
    mov  ax, [0x6C]
.w: cmp  ax, [0x6C]
    je   .w
    mov  ax, [0x6C]
    ret

; =====================================================================
; Memory test
; =====================================================================
; Four patterns, each written over a whole area before it is read back
; (so an address line fault shows): 55AAh, AA55h, a walking one (bit
; n = word number mod 16) and the address of each word (address in
; address). The first error is shown with its address and the bits.
M_PATS     equ 4

t_mem:
    mov  si, tt_mem
    mov  bx, k_stop
    call t_open
    mov  byte [V_STOP], 0
    mov  dx, POS(R_T1 + 8, C_SLBL)
    mov  si, tm_how
    mov  al, AT_LABEL
    call text_at
    mov  dx, POS(R_T1 + 9, C_SLBL)
    mov  al, AT_LABEL
    call text_at
    ; base memory, 68 KB to 40:13
    mov  dh, R_T1
    mov  si, tm_base
    call t_line
    mov  word [V_KB], M_BASE0
    mov  ax, [0x13]
    mov  [V_END], ax
    call m_range
    mov  dh, R_T1
    mov  bx, m_base
    call m_run
    jc   .w
    ; extended memory, 1024 KB + INT 15h AH=88h
    mov  dh, R_T1 + 1
    mov  si, tm_ext
    call t_line
    push di
    mov  ah, 0x88
    int  0x15
    pop  di
    mov  word [V_KB], 1024
    add  ax, 1024
    mov  [V_END], ax
    cmp  ax, 1024
    jne  .x
    mov  si, s_none
    call t_val
    jmp  short .ems
.x: call m_range
    mov  dh, R_T1 + 1
    mov  bx, m_ext
    call m_run
    jc   .w
.ems:
    ; the EMS pages: from the end of extended memory, CMOS 36h x 4
    mov  dh, R_T1 + 2
    mov  si, tm_ems
    call t_line
    call m_emsprep
    jnc  .e
    call t_val                     ; SI = why not
    jmp  short .w
.e: mov  dh, R_T1 + 2
    mov  bx, m_ems
    call m_run
.w: mov  si, k_back
    call t_keys
    xor  al, al
    call t_wait
    ret

; m_range: "nnn - mmm KB" at DI from [V_KB], [V_END]
m_range:
    mov  ax, [V_KB]
    call pnum_v
    mov  si, tm_dash
    call t_val
    mov  ax, [V_END]
    call pnum_v
    mov  si, s_kb
    jmp  t_val

; m_run: DH = row, BX = the area's routine (AL = 0: write, 1: verify;
; DL = pattern). All patterns; the result after the range. CF = 1: ESC.
m_run:
    push dx
    xor  ax, ax
    mov  [V_ERR], ax
    mov  [V_ERR + 2], ax
    mov  [V_PAT], al
.p: pop  dx
    push dx
    push bx
    mov  dl, C_TV + 24             ; "pattern n of 4"
    mov  cx, 30
    call clear_at
    call goto
    mov  si, tm_pat
    call t_val
    mov  al, [V_PAT]
    xor  ah, ah
    inc  ax
    call pnum_v
    mov  si, tm_of
    call t_val
    pop  bx
    push bx
    xor  al, al                    ; write
    mov  dl, [V_PAT]
    call bx
    pop  bx
    jc   .stop
    push bx
    mov  al, 1                     ; verify
    mov  dl, [V_PAT]
    call bx
    pop  bx
    jc   .stop
    inc  byte [V_PAT]
    cmp  byte [V_PAT], M_PATS
    jb   .p
    pop  dx                        ; the result
    mov  dl, C_TV + 24
    mov  cx, 34
    call clear_at
    call goto
    mov  ax, [V_ERR]
    or   ax, [V_ERR + 2]
    jnz  .bad
    mov  si, tm_ok
    call t_acc
    clc
    ret
.bad:
    push dx
    mov  ax, [V_ERR]
    mov  dx, [V_ERR + 2]
    call t_d32
    mov  si, tm_errs
    cmp  word [V_ERR], 1
    jne  .es
    cmp  word [V_ERR + 2], 0
    jne  .es
    mov  si, tm_err1
.es:call t_err
    pop  dx
    inc  dh                        ; the first error, on the next free row
    add  dh, 3
    mov  dl, C_SLBL
    call goto
    mov  si, tm_first
    call t_err
    mov  ax, [V_LIN]               ; linear address
    mov  dx, [V_LIN + 2]
    mov  al, dl
    call t_hex2
    mov  ax, [V_LIN]
    call t_hex4
    mov  si, tm_wrote
    call t_lbl
    mov  ax, [V_FAILW]
    call t_hex4
    mov  si, tm_bits
    call t_lbl
    mov  ax, [V_FAIL + 4]
    call t_hex4
    clc
    ret
.stop:
    pop  dx
    mov  dl, C_TV + 24
    mov  cx, 34
    call clear_at
    call goto
    mov  si, ts_stopped
    call t_err
    stc
    ret


; m_pat: the pattern word for word number DX:AX (linear address / 2)
; and pattern [V_PAT] -> AX. BX CX DX SI DI kept.
m_pat:
    cmp  byte [V_PAT], 1
    jb   .p0
    je   .p1
    cmp  byte [V_PAT], 3
    je   .p3
    push cx                        ; walking one: bit (word mod 16)
    mov  cl, al
    and  cl, 15
    mov  ax, 1
    shl  ax, cl
    pop  cx
    ret
.p0:mov  ax, 0x55AA
    ret
.p1:mov  ax, 0xAA55
    ret
.p3:xor  al, dl                    ; address in address: low word, high
    ret                            ; byte mixed in (catches A16-A23)

; m_fill / m_check: CX words at ES:0, the first one's number DX:AX.
; m_check counts errors and notes the first.
m_fill:
    push ax
    push dx
    xor  di, di
.f: push ax
    call m_pat
    mov  [es:di], ax
    pop  ax
    add  ax, 1
    adc  dx, 0
    inc  di
    inc  di
    loop .f
    pop  dx
    pop  ax
    ret
m_check:
    push ax
    push dx
    xor  di, di
.c: push ax
    call m_pat
    mov  si, ax
    xor  si, [es:di]
    pop  ax
    jz   .n
    call m_note
.n: add  ax, 1
    adc  dx, 0
    inc  di
    inc  di
    loop .c
    pop  dx
    pop  ax
    ret

; m_note: an error: SI = bits, DX:AX = word number, ES:DI where. Counts it;
; the first one is kept ([V_LIN] = word number x 2).
m_note:
    push ds
    push 0x40
    pop  ds
    add  word [V_ERR], 1
    adc  word [V_ERR + 2], 0
    cmp  word [V_ERR], 1
    jne  .r
    cmp  word [V_ERR + 2], 0
    jne  .r
    mov  [V_FAIL + 4], si
    push ax
    push dx
    shl  ax, 1
    rcl  dx, 1
    mov  [V_LIN], ax
    mov  [V_LIN + 2], dx
    pop  dx
    pop  ax
    push ax
    call m_pat
    mov  [V_FAILW], ax
    pop  ax
.r: pop  ds
    ret

; m_base: AL = 0 write, 1 verify: base memory from 68 KB to [V_END] KB,
; 32 KB at a time. CF = 1: ESC.
m_base:
    mov  bl, al
    mov  ax, [V_END]
    shl  ax, 6                     ; KB -> end segment
    mov  [V_CYL], ax
    mov  cx, M_BASE0 * 64
.s: cmp  cx, [V_CYL]
    jae  .d
    push cx
    push bx
    push es
    mov  es, cx
    mov  ax, [V_CYL]               ; words: 16 K, or what is left
    sub  ax, cx
    cmp  ax, 0x800
    jb   .part
    mov  ax, 0x800
.part:
    shl  ax, 3
    push ax
    mov  ax, cx                    ; word number = segment x 8
    xor  dx, dx
    mov  cx, 3
.w: shl  ax, 1
    rcl  dx, 1
    loop .w
    pop  cx
    or   bl, bl
    jnz  .v
    call m_fill
    jmp  short .n
.v: call m_check
.n: pop  es
    pop  bx
    pop  cx
    add  cx, 0x800
    call t_esc
    jnc  .s
    ret
.d: clc
    ret

; m_ext: AL = 0 write, 1 verify: extended memory from [V_KB] to [V_END]
; KB, 32 KB blocks moved between TBUF:0 and the block by INT 15h AH=87h.
; CF = 1: ESC.
m_ext:
    mov  bl, al
    mov  cx, [V_KB]
.b: cmp  cx, [V_END]
    jae  .d
    push cx
    push bx
    mov  ax, cx                    ; word number = KB x 512
    xor  dx, dx
    push cx
    mov  cx, 9
.wn:shl  ax, 1
    rcl  dx, 1
    loop .wn
    pop  cx
    push es
    push TBUF
    pop  es
    or   bl, bl
    jnz  .v
    push cx
    mov  cx, 0x4000
    call m_fill
    pop  cx
    mov  bl, 1                     ; TBUF -> the block
    call m_move
    jmp  short .n
.v: push ax
    push dx
    xor  bl, bl                    ; the block -> TBUF
    call m_move
    pop  dx
    pop  ax
    jc   .n
    push cx
    mov  cx, 0x4000
    call m_check
    pop  cx
    clc
.n: pop  es
    pop  bx
    pop  cx
    jnc  .ok
    add  word [V_ERR], 1           ; the move failed: one error, go on
    adc  word [V_ERR + 2], 0
.ok:add  cx, 32
    call t_esc
    jnc  .b
    ret
.d: clc
    ret

; m_move: CX = KB of the extended block; BL = 1: TBUF:0 -> it, 0: it ->
; TBUF:0. 32 KB through INT 15h AH=87h. CF = 1: failed. BX CX DX kept.
m_move:
    push cx
    push dx
    push si
    push di
    push es
    push TGDT
    pop  es
    xor  di, di
    push cx
    mov  cx, 24
    xor  ax, ax
    rep  stosw
    pop  cx
    mov  ax, cx                    ; KB -> address: KB x 1024
    mov  dx, cx
    shl  ax, 10
    shr  dx, 6
    mov  di, 0x10                  ; descriptor 2: source, 3: destination
    or   bl, bl
    jnz  .tx
    call .desc                     ; source: the block
    mov  ax, TBUF << 4             ; destination: TBUF (below 64 KB)
    xor  dx, dx
    call .desc
    jmp  short .go
.tx:push ax
    push dx
    mov  ax, TBUF << 4
    xor  dx, dx
    call .desc
    pop  dx
    pop  ax
    call .desc
.go:xor  si, si
    mov  cx, 0x4000                ; words
    mov  ah, 0x87
    int  0x15
    pop  es
    pop  di
    pop  si
    pop  dx
    pop  cx
    ret
.desc:                             ; DX:AX = base: a data descriptor at ES:DI
    mov  word [es:di], 0xFFFF
    mov  [es:di + 2], ax
    mov  [es:di + 4], dl
    mov  byte [es:di + 5], 0x93
    add  di, 8
    ret

; m_emsprep: the EMS pages and a frame for window 0 -> CF = 0, or CF = 1
; and SI = why the test cannot run
m_emsprep:
    mov  al, 0x35
    call A_CMOSRD
    mov  ah, al
    mov  al, 0x36
    call A_CMOSRD
    cmp  al, ah
    jbe  .c
    mov  al, ah
.c: xor  ah, ah
    shl  ax, 2                     ; 64 KB -> 16 KB pages
    mov  si, tm_noems
    or   ax, ax
    jz   .no
    mov  [V_NPG], ax
    push di
    mov  ah, 0x88                  ; first page: (1024 + extended KB) / 16
    int  0x15
    pop  di
    add  ax, 1024
    shr  ax, 4
    mov  [V_PG], ax
    add  ax, [V_NPG]
    mov  si, tm_emsbig
    cmp  ax, 0x100                 ; the page registers have 8 bits
    ja   .no
    ; a free 16 KB block for window 0: C000 + pos x 16 KB, not shadowed,
    ; no ROM, a floating bus, nothing that keeps a byte
    mov  al, 0x12
    call ht12_rd
    mov  bl, al
    xor  cx, cx
.f: test bl, 1
    jnz  .nf
    push cx
    call m_free
    pop  cx
    jnc  .ok
.nf:shr  bl, 1
    inc  cx
    cmp  cl, 8
    jb   .f
    mov  si, tm_noframe
.no:stc
    ret
.ok:mov  [V_FR], cl
    mov  ax, [V_PG]                ; "pages nn-mm, window at segment"
    call t_hex2
    mov  al, '-'
    call t_chr
    mov  ax, [V_PG]
    add  ax, [V_NPG]
    dec  ax
    call t_hex2
    mov  al, 'h'
    call t_chr
    mov  si, tm_at
    call t_lbl
    call m_frseg
    mov  ax, cx
    call t_hex4
    clc
    ret

m_frseg:                           ; CX = the window's segment
    mov  cl, [V_FR]
    xor  ch, ch
    shl  cx, 10
    add  cx, 0xC000
    ret

; m_free: CX = position 0-7 -> CF = 0 if C000 + pos x 16 KB is empty
m_free:
    push di
    push es
    shl  cx, 10
    add  cx, 0xC000
    mov  es, cx
    xor  di, di
    mov  cx, 8                     ; every 2 KB
.c: cmp  word [es:di], 0xFFFF
    jne  .busy
    mov  al, [es:di + 0x7FF]
    mov  byte [es:di + 0x7FF], 0x5A
    mov  ah, [es:di + 0x7FF]
    mov  [es:di + 0x7FF], al
    cmp  ah, 0x5A
    je   .busy
    add  di, 0x800
    loop .c
    clc
    pop  es
    pop  di
    ret
.busy:
    stc
    pop  es
    pop  di
    ret

; m_ems: AL = 0 write, 1 verify: every EMS page through window 0
m_ems:
    mov  bl, al
    mov  al, 0x19                  ; keep the EMS registers
    call ht12_rd
    mov  [V_E19], al
    mov  al, 0x20
    call ht12_rd
    mov  [V_E20], al
    mov  ah, [V_FR]                ; window 0 on, at the frame
    shl  ah, 4
    or   ah, 0x81
    mov  al, 0x19
    call ht12_wr
    mov  cx, [V_PG]
.p: mov  ax, [V_PG]
    add  ax, [V_NPG]
    cmp  cx, ax
    jae  .d
    mov  ah, cl
    mov  al, 0x20
    call ht12_wr
    push es
    push bx
    push cx
    mov  ax, cx                    ; word number = page x 8192
    xor  dx, dx
    mov  cx, 13
.w: shl  ax, 1
    rcl  dx, 1
    loop .w
    call m_frseg
    mov  es, cx
    mov  cx, 0x2000                ; 16 KB
    or   bl, bl
    jnz  .v
    call m_fill
    jmp  short .n
.v: call m_check
.n: pop  cx
    pop  bx
    pop  es
    inc  cx
    call t_esc
    jnc  .p
    call .rest
    stc
    ret
.d: call .rest
    clc
    ret
.rest:
    mov  ah, [V_E20]
    mov  al, 0x20
    call ht12_wr
    mov  ah, [V_E19]
    mov  al, 0x19
    jmp  ht12_wr

; ht12_wr: AL = index, AH = value
ht12_wr:
    push dx
    mov  dx, 0x1ED
    out  dx, al
    jmp  short $+2
    jmp  short $+2
    inc  dx
    inc  dx
    xchg al, ah
    out  dx, al
    xchg al, ah
    pop  dx
    ret

; =====================================================================
; HT12UMB.SYS in this ROM
; =====================================================================
UMB_TAG    equ 0x5FF0
UMB_DRV    equ 0x6000

t_umb:
    mov  si, tt_umb
    mov  bx, k_back
    call t_open
    mov  dh, R_T1
    mov  si, tu_drv
    call t_line
    cmp  word [cs:UMB_TAG], 'BU'
    jne  .none
    cmp  word [cs:UMB_TAG + 2], 'BU'
    jne  .none
    cmp  word [cs:UMB_TAG + 4], 'MB'
    jne  .none
    mov  si, tu_name
    call t_val
    mov  si, UMB_TAG + 6           ; the version text
    call t_val
    mov  si, tu_comma
    call t_val
    mov  ax, [cs:UMB_TAG + 10]
    call pnum_v
    mov  si, tu_bytes
    call t_val
    mov  si, UMB_DRV               ; word sum of the slot + the check word
    mov  cx, 0x400
    mov  ax, [cs:UMB_TAG + 12]
.s: add  ax, [cs:si]
    inc  si
    inc  si
    loop .s
    mov  si, tu_ok
    or   ax, ax
    jz   .k
    mov  si, tu_bad
    call t_err
    jmp  short .rec
.k: call t_acc
.rec:
    mov  si, tu_text               ; the recipe, line by line from row 7
    mov  dx, POS(R_T1 + 2, C_SLBL)
.l: push dx
    cmp  byte [cs:si], 1           ; 1: the next lines in the value colour
    jne  .t
    inc  si
    mov  byte [V_PAT], AT_VALUE
    jmp  short .dr
.t: cmp  byte [cs:si], 2           ; 2: back to the label colour
    jne  .dr0
    inc  si
.dr0:
    mov  byte [V_PAT], AT_LABEL
.dr:mov  al, [V_PAT]
    call text_at
    pop  dx
    inc  dh
    cmp  byte [cs:si], 0           ; two zeros: the end
    jne  .l
    jmp  short .w
.none:
    mov  si, tu_none
    call t_err
.w: xor  al, al
    call t_wait
    ret

; =====================================================================
; texts
; =====================================================================
a_infoc:    db "Hard disk C: info / auto-detect", 0
a_infod:    db "Hard disk D: info / auto-detect", 0
a_partc:    db "Partition check C:", 0
a_partd:    db "Partition check D:", 0
a_speedc:   db "Disk speed C:", 0
a_speedd:   db "Disk speed D:", 0
a_mem:      db "Memory test", 0
a_umb:      db "Get HT12UMB.SYS (UMB driver in this BIOS)", 0
h_info:     db "What the drive says about itself (IDENTIFY DEVICE). Enter there takes", 10
            db "its geometry as type 47, as Auto-Detect does.", 0
h_part:     db "Reads the partition table and each FAT boot sector and checks them", 10
            db "against the geometry this BIOS gives DOS. Nothing is written.", 0
h_speed:    db "Reads through the BIOS (INT 13h, PIO over the ISA bus) for 2 s at the", 10
            db "start, middle and end of the disk, then random reads. Nothing is written.", 0
h_mem:      db "Tests base memory from 68 KB, extended memory and the HT12's EMS pages", 10
            db "with four patterns. ESC stops it.", 0
h_umb:      db "Shows how to write the HT12UMB driver from this BIOS to a file with", 10
            db "DEBUG (MS-DOS 5 / 6.22), and checks the copy in the ROM.", 0

tt_infoc:   db "Hard disk C: (IDE master)", 0
tt_infod:   db "Hard disk D: (IDE slave)", 0
tt_partc:   db "Partition check C:", 0
tt_partd:   db "Partition check D:", 0
tt_speedc:  db "Disk speed C:", 0
tt_speedd:  db "Disk speed D:", 0
tt_mem:     db "Memory test", 0
tt_umb:     db "HT12UMB.SYS in this BIOS", 0
k_back:     db "ESC:Back", 0
k_stop:     db "ESC:Stop", 0
k_info:     db "Enter:Use as type 47 (auto-detect)  ESC:Back", 0

tl_model:   db "Model", 0
tl_serial:  db "Serial number", 0
tl_fw:      db "Firmware", 0
tl_geo:     db "Geometry", 0
tl_cap:     db "Capacity", 0
tl_xfer:    db "Transfer", 0
tl_setup:   db "Setup", 0
tl_dos:     db "BIOS gives DOS", 0
ti_none:    db "No drive answers IDENTIFY DEVICE here (none, or ATAPI).", 0
ti_cf:      db "  CF card", 0
ti_default: db " default", 0
ti_current: db "   current ", 0
ti_sect:    db " sectors, ", 0
ti_lba:     db ", LBA", 0
ti_nolba:   db ", no LBA", 0
ti_pio:     db "PIO mode ", 0
ti_mult:    db "   multiple sectors: ", 0
ti_no:      db "no", 0
ti_iordy:   db "   IORDY", 0
ti_dma:     db "   DMA", 0
ti_notup:   db "Not set up in this POST", 0
ti_echs:    db "   (INT 13h, after ECHS)", 0
ti_match:   db "Setup's geometry is the drive's own.", 0
ti_differ:  db "Setup's geometry is not the drive's own: Enter takes the drive's.", 0

tp_rderr:   db "Read error ", 0
tp_nosig:   db "No partition table (no 55AA signature in the MBR).", 0
tp_head:    db "#  A Type           Start C/H/S  End C/H/S    Size        BPB H/S", 0
tp_ebrerr:  db "The extended partition's chain cannot be read here.", 0
tp_empty:   db "The partition table is empty.", 0
tp_ok:      db "The partitions fit the geometry this BIOS gives DOS.", 0
tp_bad:     db "Made with ", 0
tp_heads:   db " heads / ", 0
tp_bios:    db " sectors, the BIOS ", 0
tp_slash:   db " / ", 0
tp_bad2:    db "DOS would read the wrong sectors: set the old geometry, or repartition.", 0
tp_rowok:   db "OK", 0
tp_rowbad:  db "!", 0
pp_label:   db "C: partitions use ", 0
pp_tail:    db " - see Setup, Tools", 0

ts_how:     db "   whole tracks", 0
ts_start:   db "Read, start", 0
ts_mid:     db "Read, middle", 0
ts_end:     db "Read, end", 0
ts_acc:     db "Access time", 0
ts_kbs:     db " KB/s", 0
ts_ms:      db " ms (random sector)", 0
ts_stopped: db "Stopped", 0

tm_base:    db "Base memory", 0
tm_ext:     db "Extended", 0
tm_ems:     db "EMS pages", 0
tm_how:     db "Patterns 55AAh, AA55h, walking one, address in address; each is written", 0
            db "over the whole area before it is read back.", 0
tm_dash:    db " - ", 0
tm_pat:     db "pattern ", 0
tm_of:      db " of 4", 0
tm_ok:      db "OK", 0
tm_errs:    db " errors", 0
tm_err1:    db " error", 0
tm_first:   db "First error at ", 0
tm_wrote:   db "h  wrote ", 0
tm_bits:    db "h  bits ", 0
tm_noems:   db "None (EMS size 0)", 0
tm_emsbig:  db "Beyond the 8-bit page registers", 0
tm_noframe: db "No free 16 KB block at C000-DFFF for the window", 0
tm_at:      db "  window ", 0

tu_drv:     db "Driver", 0
tu_name:    db "HT12UMB ", 0
tu_comma:   db ", ", 0
tu_bytes:   db " bytes at F000:6000, ", 0
tu_ok:      db "checksum OK", 0
tu_bad:     db "checksum WRONG", 0
tu_none:    db "Not in this BIOS.", 0
tu_text:    db "To write it to a file, type in DOS (MS-DOS 5 or 6.22):", 0
            db 1, "  C:\>DEBUG", 0
            db 1, "  -N C:\DOS\HT12UMB.SYS", 0
            db 1, "  -M F000:6000 L800 100", 0
            db 1, "  -R CX", 0
            db 1, "  :800", 0
            db 1, "  -W", 0
            db 1, "  -Q", 0
            db 2, "Then in CONFIG.SYS, after HIMEM.SYS and without HT12MM.SYS:", 0
            db 1, "  DEVICE=C:\DOS\HT12UMB.SYS", 0
            db 1, "  DOS=HIGH,UMB", 0
            db 0
