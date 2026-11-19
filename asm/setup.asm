; =====================================================================
;  Round 6a: the setup of BUBios/286, the boot order and the
;  auto-detect switch
;
;  AMI's setup code still prepares and saves (docs/DEVELOPMENT_LOG.md,
;  round 6a): BCA6 builds the stack frame and reads CMOS 10h-3Fh into
;  [BP+10h..3Fh]; AMI's page code (BD61-C006) normalises that buffer; at
;  C009, where AMI's editing loop began, bu_setup takes over. Every option
;  edits AMI's buffer with AMI's encodings. Save: JMP C0A0 (AMI writes
;  CMOS 10h-3Fh, the checksum, clears 0Eh/0Fh and restarts). Exit without
;  saving: JMP BD4D (AMI's menu exit back to POST).
;
;  py/build.py patches:
;    BCFC  MOV AL,CS:[E058] (the menu)        -> JMP BD61 (the page)
;    C009  MOV BX,CA53 / JMP C011             -> JMP bu_setup
;    9447  CALL autodet (Step 3)              -> CALL autodet_sw
;    8F9B  XOR DX,DX / XOR AX,AX / INT 13h / CALL 9005 (A:) -> CALL boot_seq
;
;  New settings: CMOS 3Eh, check byte 3Fh = 3Eh XOR A5h (else defaults):
;    bits 1-0 boot order (0 A: C:, 1 C: A:, 2 C: only), bit 2 auto-detect
;    off, bits 6-4 colour scheme.
; =====================================================================

A_CMOSWR   equ 0xEEAE     ; AL = index, AH = value
A_SAVE     equ 0xC0A0     ; AMI's save: CMOS from [BP+10h..], checksum, restart
A_EXIT     equ 0xBD4D     ; AMI's menu exit: cursor, stack frame, RET to POST
A_UNHOOK   equ 0xD0CF     ; AMI's setup hooks of INT 10h/1Ah/1Ch off (its calendar clock)
A_READ1    equ 0x9005     ; INT 19h: read sector 1 of DL, head DH, 4 tries (CX = 0: failed)
A_BOOTGO   equ 0x8FEE     ; INT 19h: jump to 0:7C00
A_INT19    equ 0x8F80     ; INT 19h from the start
A_CRLF     equ 0x8D83
A_PUTS     equ 0x8D75     ; CS:SI teletype
CM_BUB     equ 0x3E
CM_CHK     equ 0x3F
BUB_KEY    equ 0xA5

; setup state in AMI's frame (BP; [BP+10h..3Fh] is the CMOS buffer)
F_TAB      equ 0
F_FLD      equ 1          ; selected field (index into the table, 0FFh: none)
F_EDIT     equ 2          ; digits typed so far (0: not typing)
F_SEC      equ 3          ; RTC second last shown
F_DIG      equ 4          ; 4..0Dh: the typed digits
F_MSG      equ 0x0E       ; word: message for the help rows (0: the field's help)

NTABS      equ 6
T_CHOICE   equ 1
T_NUM      equ 2
T_DATE     equ 3
T_TIME     equ 4
T_ACT      equ 5
T_HDT      equ 6
T_EMS      equ 7
F_PARAMC   equ 0x80       ; type flag: a C: type-47 parameter (editable only with type 47)
F_PARAMD   equ 0x40       ; type flag: a D: type-47 parameter

R_TABS     equ 1
R_TOP      equ 3
R_LINE2    equ 21
R_HELP     equ 22
R_KEYS     equ 24
C_SLBL     equ 3
C_SVAL     equ 28

; ---------------------------------------------------------------------
; bub_cfg -> AL = the BUBios settings byte (CMOS 3Eh), 0 if its check
; byte (3Fh) does not match. Other registers kept.
; ---------------------------------------------------------------------
bub_cfg:
    push bx
    mov  al, CM_CHK
    call A_CMOSRD
    mov  bl, al
    mov  al, CM_BUB
    call A_CMOSRD
    xor  bl, BUB_KEY
    cmp  al, bl
    je   .ok
    xor  al, al
.ok:pop  bx
    ret

; ---------------------------------------------------------------------
; autodet_sw -- 9447 (checkpoint 75h), in place of Step 3's CALL autodet:
; "Auto-Detect Disks at Boot" On -> autodet, Off -> drives12 (no IDENTIFY,
; but a configured drive that does not answer is still left out).
; Keeps every register except AL, as both of Step 3's entries do.
; ---------------------------------------------------------------------
autodet_sw:
    push ax
    call bub_cfg
    test al, 4
    pop  ax
    jnz  .off
    jmp  autodet
.off:
    jmp  drives12

; ---------------------------------------------------------------------
; boot_seq -- 8F9B (INT 19h, ES = 0, BX = 7C00h), in place of the A:
; attempt (XOR DX,DX / XOR AX,AX / INT 13h / CALL 9005). Returns to
; 8F9E (NOPs, then 8FA4: AMI's A: result) like the CALL 9005 it ends with.
; ---------------------------------------------------------------------
boot_seq:
    call bub_cfg
    and  al, 3
    jz   .a                        ; A: then C: (AMI's own order)
    push ax
    mov  al, 0x0E                  ; as AMI's C: path (8FB1): no C: when the
    call A_CMOSRD                  ; fixed-disk setup failed in POST
    test al, 8
    jnz  .cno
    mov  dx, 0x0080                ; C:, head 0
    call A_READ1
    jcxz .cno
    jc   .cno
    cmp  word [es:bx + 0x1FE], 0xAA55
    jne  .cno
    pop  ax
    add  sp, 2                     ; (our return address)
    jmp  A_BOOTGO                  ; DL = 80h
.cno:
    pop  ax
    cmp  al, 2
    je   .conly
.a: xor  dx, dx                    ; A:, as the original
    xor  ax, ax
    int  0x13
    jmp  A_READ1
.conly:                            ; C: only and C: did not boot: say so,
    add  sp, 2                     ; wait for a key, INT 19h again
    sti
    call A_CRLF
    mov  si, s_conly
    call A_PUTS
    call A_CRLF
    mov  si, s_anykey
    call A_PUTS
    xor  ah, ah
    int  0x16
    call A_CRLF
    jmp  A_INT19

s_conly:    db "  No boot sector on C: (boot order: C: only, see Setup)", 0
s_anykey:   db "Press any key to try again ", 0

; =====================================================================
; bu_setup -- C009: AMI's page has filled and normalised its buffer
; =====================================================================
bu_setup:
    cld
    call A_UNHOOK                  ; AMI's calendar clock and video hooks off
    mov  al, 0x0B                  ; and the RTC running again (AMI's page
    call A_CMOSRD                  ; set the SET bit, 0Bh = 82h)
    and  al, 0x7F
    mov  ah, al
    mov  al, 0x0B
    call A_CMOSWR
    sti
    push 0x40
    pop  ds
    xor  ax, ax
    mov  [bp + F_TAB], al          ; Summary first
    mov  [bp + F_EDIT], al
    mov  [bp + F_MSG], ax
    mov  byte [bp + F_FLD], 0xFF
    mov  byte [bp + F_SEC], 0xFF
    call s_redraw
.loop:
    call s_tick
    mov  ah, 1
    int  0x16
    jz   .loop
    xor  ah, ah
    int  0x16
    call s_key
    jmp  short .loop

; ---------------------------------------------------------------------
; keys
; ---------------------------------------------------------------------
s_key:
    cmp  byte [bp + F_EDIT], 0
    je   .nedit
    call s_editkey                 ; CF = 1: the key was used by the entry
    jnc  .nedit
    ret
.nedit:
    cmp  ax, 0x0F09                ; Tab
    jne  .k1
    mov  al, [bp + F_TAB]
    inc  ax
    cmp  al, NTABS
    jb   .tab
    xor  al, al
    jmp  short .tab
.k1:cmp  ax, 0x0F00                ; Shift-Tab
    jne  .k2
    mov  al, [bp + F_TAB]
    dec  al
    jns  .tab
    mov  al, NTABS - 1
.tab:
    mov  [bp + F_TAB], al
    mov  word [bp + F_MSG], 0
    call s_first
    jmp  s_redraw
.k2:cmp  ah, 0x01                  ; ESC: to Exit; on Summary or Exit: the other
    jne  .k3
    mov  al, 5
    cmp  byte [bp + F_TAB], 5
    jne  .tab
    xor  al, al
    jmp  short .tab
.k3:cmp  ah, 0x44                  ; F10
    jne  .k4
    jmp  s_save_q
.k4:cmp  ah, 0x3C                  ; F2 / F3: colour scheme
    je   .sch
    cmp  ah, 0x3D
    jne  .k5
.sch:
    cmp  byte [0x49], 7
    je   .r
    push ax
    call bub_get
    mov  bl, al
    shr  al, 4
    and  al, 7
    pop  cx
    cmp  ch, 0x3C
    je   .sdn
    inc  ax
    cmp  al, 6
    jb   .sset
    xor  al, al
    jmp  short .sset
.sdn:
    dec  al
    jns  .sset
    mov  al, 5
.sset:
    shl  al, 4
    and  bl, 0x8F
    or   al, bl
    call bub_set
    jmp  s_redraw
.k5:cmp  byte [bp + F_FLD], 0xFF
    je   .r
    cmp  ah, 0x48                  ; up
    jne  .k6
    mov  dl, -1
    jmp  short .mv
.k6:cmp  ah, 0x50                  ; down
    jne  .k7
    mov  dl, 1
.mv:call s_move
    jmp  s_redraw
.k7:mov  dl, 1                     ; +1: PgDn, right, '+'
    cmp  ah, 0x51
    je   .ch
    cmp  ah, 0x4D
    je   .ch
    cmp  al, '+'
    je   .ch
    mov  dl, -1                    ; -1: PgUp, left, '-'
    cmp  ah, 0x49
    je   .ch
    cmp  ah, 0x4B
    je   .ch
    cmp  al, '-'
    je   .ch
    cmp  ah, 0x1C                  ; Enter: run an action
    jne  .k8
    call s_fld
    cmp  byte [cs:si + 4], T_ACT
    jne  .r
    call [cs:si + 10]
    jmp  s_redraw
.k8:cmp  al, '0'                   ; a digit: start typing
    jb   .r
    cmp  al, '9'
    ja   .r
    call s_fld
    mov  cl, [cs:si + 4]
    and  cl, 0x0F
    cmp  cl, T_NUM
    je   .typ
    cmp  cl, T_DATE
    je   .typ
    cmp  cl, T_TIME
    je   .typ
    cmp  cl, T_HDT
    jne  .r
.typ:
    mov  byte [bp + F_EDIT], 0
    call s_editkey
    jmp  s_redraw
.ch:call s_change
    jmp  s_redraw
.r: ret

; s_fld -> CS:SI = the selected field's record
s_fld:
    mov  al, [bp + F_FLD]
    xor  ah, ah
    shl  ax, 4
    mov  si, ax
    add  si, fields
    ret

; s_first: the first selectable field of the tab (0FFh: none)
s_first:
    mov  byte [bp + F_FLD], 0xFF
    mov  dl, 1
    jmp  short s_move_from

; s_move: DL = +1 / -1: the next selectable field of this tab, round
s_move:
    mov  al, [bp + F_FLD]
s_move_go:
    mov  cx, NFIELDS + 1
.l: add  al, dl
    cmp  al, 0xFF
    jne  .w
    mov  al, NFIELDS - 1
.w: cmp  al, NFIELDS
    jb   .c
    xor  al, al
.c: push ax
    xor  ah, ah
    shl  ax, 4
    mov  si, ax
    add  si, fields
    pop  ax
    call s_selectable
    je   .ok
    loop .l
    mov  al, 0xFF
.ok:mov  [bp + F_FLD], al
    ret
s_move_from:
    mov  al, 0xFF                  ; (so that the first step lands on 0)
    jmp  short s_move_go

; ZF = 1 if the field CS:SI is on this tab and can be selected
s_selectable:
    push ax
    mov  al, [cs:si]
    cmp  al, [bp + F_TAB]
    jne  .n
    mov  al, [cs:si + 4]
    test al, F_PARAMC | F_PARAMD
    jz   .y
    mov  bl, 0
    test al, F_PARAMC
    jnz  .d
    mov  bl, 1
.d: call hd_type
    cmp  ax, 47
    jne  .n
.y: xor  al, al
    pop  ax
    ret
.n: or   al, 1                     ; ZF = 0
    pop  ax
    ret

; s_change: DL = +1 / -1 on the selected field
s_change:
    call s_fld
    mov  word [bp + F_MSG], 0
    mov  cl, [cs:si + 4]
    and  cl, 0x0F
    cmp  cl, T_CHOICE
    je   .choice
    cmp  cl, T_NUM
    je   .num
    cmp  cl, T_HDT
    je   .hdt
    cmp  cl, T_EMS
    je   .ems
    ret
.choice:
    push dx
    call [cs:si + 8]               ; AX = index
    pop  dx
    mov  bx, [cs:si + 12]          ; the list: count, then the texts
    mov  cl, [cs:bx]
    add  al, dl
    cmp  al, 0xFF
    jne  .c1
    mov  al, cl
    dec  ax
.c1:cmp  al, cl
    jb   .set
    xor  al, al
.set:
    xor  ah, ah
    jmp  [cs:si + 10]
.num:
    push dx
    call [cs:si + 8]
    pop  dx
    mov  bx, [cs:si + 12]          ; maximum
    or   dl, dl
    js   .nd
    cmp  ax, bx
    jae  .r
    inc  ax
    jmp  [cs:si + 10]
.nd:or   ax, ax
    jz   .r
    dec  ax
    jmp  [cs:si + 10]
.hdt:
    push dx
    call [cs:si + 8]               ; 0 .. 47, 15 never
    pop  dx
.h1:add  al, dl
    cmp  al, 0xFF
    jne  .h2
    mov  al, 47
.h2:cmp  al, 48
    jb   .h3
    xor  al, al
.h3:cmp  al, 15
    je   .h1
    xor  ah, ah
    jmp  [cs:si + 10]
.ems:
    push dx
    call [cs:si + 8]               ; AX = 64 KB units, max [35h]
    pop  dx
    mov  bl, [bp + 0x35]
    xor  bh, bh
    or   dl, dl
    js   .ed
    cmp  ax, bx
    jae  .r
    inc  ax
    jmp  [cs:si + 10]
.ed:or   ax, ax
    jz   .r
    dec  ax
    jmp  [cs:si + 10]
.r: ret

; ---------------------------------------------------------------------
; typing: numbers, the hard disk type, the date and the time.
; In: AX = key. CF = 1 if the key was used. [F_EDIT] = digits so far.
; ---------------------------------------------------------------------
s_editkey:
    push ax
    call s_fld
    pop  ax
    mov  cl, [cs:si + 4]
    and  cl, 0x0F
    mov  ch, 8                     ; digits: date 8, time 6, type 2, else the width
    cmp  cl, T_DATE
    je   .n
    mov  ch, 6
    cmp  cl, T_TIME
    je   .n
    mov  ch, 2
    cmp  cl, T_HDT
    je   .n
    mov  ch, [cs:si + 5]
.n: cmp  ah, 0x01                  ; ESC: cancel
    jne  .e1
    mov  byte [bp + F_EDIT], 0
    jmp  short .used
.e1:cmp  ah, 0x0E                  ; Backspace
    jne  .e2
    cmp  byte [bp + F_EDIT], 0
    je   .used
    dec  byte [bp + F_EDIT]
    jmp  short .used
.e2:cmp  ah, 0x1C                  ; Enter: accept what is there
    je   .accept
    cmp  al, '0'
    jb   .other
    cmp  al, '9'
    ja   .other
    mov  bl, [bp + F_EDIT]
    cmp  bl, ch
    jae  .used
    xor  bh, bh
    sub  al, '0'
    push di
    mov  di, bx
    mov  [bp + di + F_DIG], al
    pop  di
    inc  byte [bp + F_EDIT]
    inc  bl
    cmp  bl, ch                    ; full: accept
    je   .accept
.used:
    call s_redraw_fields
    stc
    ret
.other:                            ; any other key: entry cancelled, key passed on
    mov  byte [bp + F_EDIT], 0
    clc
    ret
.accept:
    mov  bl, [bp + F_EDIT]
    mov  byte [bp + F_EDIT], 0
    or   bl, bl
    jz   .used
    cmp  cl, T_DATE
    je   .date
    cmp  cl, T_TIME
    je   .time
    ; a number: the digits as typed
    push si
    xor  ax, ax
    xor  bh, bh
    xor  si, si
.d: cmp  si, bx
    jae  .dv
    mov  dx, 10
    mul  dx
    jc   .big
    push bx
    mov  bl, [bp + si + F_DIG]
    xor  bh, bh
    add  ax, bx
    pop  bx
    jc   .big
    inc  si
    jmp  short .d
.big:
    pop  si
    jmp  short .used
.dv:pop  si
    cmp  cl, T_HDT
    jne  .num
    cmp  ax, 47                    ; a type: 0-47 but 15
    ja   .used
    cmp  ax, 15
    je   .used
    jmp  short .go
.num:
    cmp  ax, [cs:si + 12]
    ja   .used
.go:call [cs:si + 10]
    jmp  short .used
.date:
    cmp  bl, 8
    jne  .used
    call date_set
    jmp  short .used
.time:
    cmp  bl, 6
    jne  .used
    call time_set
    jmp  short .used

; two typed digits at F_DIG + SI -> AL (0-99)
dig2:
    mov  al, [bp + si + F_DIG]
    mov  ah, 10
    mul  ah
    add  al, [bp + si + F_DIG + 1]
    ret
; AL (0-99) -> BCD
bcd:
    aam
    shl  ah, 4
    or   al, ah
    ret

; date_set: mm dd yyyy typed (1980-2099, a day that exists) -> INT 1Ah AH=05h
date_set:
    push si
    xor  si, si
    call dig2                      ; month
    mov  dh, al
    mov  si, 2
    call dig2                      ; day
    mov  dl, al
    mov  si, 4
    call dig2                      ; century
    mov  ch, al
    mov  si, 6
    call dig2                      ; year
    mov  cl, al
    pop  si
    cmp  dh, 1
    jb   .r
    cmp  dh, 12
    ja   .r
    cmp  dl, 1
    jb   .r
    mov  al, ch                    ; 1980-2099
    cmp  al, 19
    jb   .r
    cmp  al, 20
    ja   .r
    jb   .c19
    jmp  short .cy
.c19:
    cmp  cl, 80
    jb   .r
.cy:mov  bl, dh                    ; days in the month
    xor  bh, bh
    mov  al, [cs:bx + mdays - 1]
    cmp  dh, 2
    jne  .dm
    test cl, 3                     ; February in a leap year (2000 is one)
    jnz  .dm
    inc  ax
.dm:cmp  dl, al
    ja   .r
    mov  al, ch
    call bcd
    mov  ch, al
    mov  al, cl
    call bcd
    mov  cl, al
    mov  al, dh
    call bcd
    mov  dh, al
    mov  al, dl
    call bcd
    mov  dl, al
    mov  ah, 5
    int  0x1A
.r: ret
mdays:      db 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31

; time_set: hh mm ss typed -> INT 1Ah AH=03h
time_set:
    push si
    xor  si, si
    call dig2
    mov  ch, al
    mov  si, 2
    call dig2
    mov  cl, al
    mov  si, 4
    call dig2
    mov  dh, al
    pop  si
    cmp  ch, 23
    ja   .r
    cmp  cl, 59
    ja   .r
    cmp  dh, 59
    ja   .r
    mov  al, ch
    call bcd
    mov  ch, al
    mov  al, cl
    call bcd
    mov  cl, al
    mov  al, dh
    call bcd
    mov  dh, al
    xor  dl, dl                    ; no daylight saving
    mov  ah, 3
    int  0x1A
.r: ret

; ---------------------------------------------------------------------
; s_tick: the time on the Standard page, once a second
; ---------------------------------------------------------------------
s_tick:
    cmp  byte [bp + F_TAB], 1
    jne  .r
    mov  ah, 2
    int  0x1A
    jc   .r
    cmp  dh, [bp + F_SEC]
    je   .r
    mov  [bp + F_SEC], dh
    call s_redraw_fields
.r: ret

; ---------------------------------------------------------------------
; save / quit, with a question on the key row
; ---------------------------------------------------------------------
s_save_q:
    mov  si, s_q_save
    call s_ask
    jne  .r
    jmp  A_SAVE                    ; AMI writes CMOS and restarts
.r: jmp  s_redraw
s_quit_q:
    mov  si, s_q_quit
    call s_ask
    jne  .r
    call vid_es                    ; leave as AMI's EXIT FOR BOOT did: back
    mov  al, 0x0B                  ; to POST (the RTC already runs)
    call A_CMOSRD
    and  al, 0x7F
    mov  ah, al
    mov  al, 0x0B
    call A_CMOSWR
    jmp  A_EXIT
.r: ret

; s_ask: CS:SI question on the key row -> ZF = 1 for Y
s_ask:
    push si
    call vid_es_s
    mov  dx, POS(R_KEYS, 0)
    mov  al, ' '
    mov  bl, AT_TABA
    mov  cx, 80
    call fill_at
    pop  si
    mov  dx, POS(R_KEYS, 2)
    mov  al, AT_TABA
    call text_at
.k: xor  ah, ah
    int  0x16
    or   al, 0x20
    cmp  al, 'y'
    je   .r
    cmp  al, 'n'
    je   .no
    cmp  ah, 0x01
    jne  .k
.no:or   al, 1                     ; ZF = 0
.r: ret

; ---------------------------------------------------------------------
; actions (Tools, Exit)
; ---------------------------------------------------------------------
act_save:
    jmp  s_save_q
act_quit:
    jmp  s_quit_q
act_detc:
    mov  bl, 0
    jmp  short act_det
act_detd:
    mov  bl, 1
act_det:                           ; IDENTIFY (Step 3) -> type 47 in the buffer
    in   al, 0xA1                  ; IRQ 14 kept away, as in 5b
    push ax
    or   al, 0x40
    out  0xA1, al
    mov  dx, 0x3F6
    mov  al, 0x02
    out  dx, al
    push bx
    call identify                  ; CF = 0: CX/DL/DH = cylinders/heads/sectors
    pop  bx
    pushf
    push dx
    mov  dx, 0x3F6
    xor  al, al
    out  dx, al
    mov  dx, 0x1F6
    mov  al, 0xA0
    out  dx, al
    mov  byte [0x8E], 0
    pop  dx
    popf
    pop  ax
    pushf
    out  0xA1, al
    popf
    mov  word [bp + F_MSG], s_m_none
    jc   .r
    push cx                        ; [SP+2] cylinders, [SP] heads/sectors
    push dx
    mov  ax, 47
    call hd_tset
    mov  si, sp
    mov  ax, [ss:si + 2]
    call p_cyl_set
    mov  ax, [ss:si + 2]
    call p_lz_set
    mov  al, [ss:si]
    xor  ah, ah
    call p_hd_set
    mov  al, [ss:si + 1]
    xor  ah, ah
    call p_sec_set
    mov  ax, 0xFFFF
    call p_wp_set
    pop  dx
    pop  cx
    mov  word [bp + F_MSG], s_m_found
.r: ret

; =====================================================================
; get / set of every option, on AMI's buffer ([BP+N] = CMOS N)
; =====================================================================
; floppies: 10h nibbles; 14h bits 7-6 = 01 if both drives are set (C385)
fda_get:
    mov  al, [bp + 0x10]
    shr  al, 4
    jmp  short fd_clamp
fdb_get:
    mov  al, [bp + 0x10]
    and  al, 0x0F
fd_clamp:
    xor  ah, ah
    cmp  al, 4
    jbe  .r
    mov  al, 0
.r: ret
fda_set:
    shl  al, 4
    and  byte [bp + 0x10], 0x0F
    or   [bp + 0x10], al
    jmp  short fd_fix
fdb_set:
    and  byte [bp + 0x10], 0xF0
    or   [bp + 0x10], al
fd_fix:
    and  byte [bp + 0x14], 0x3F
    mov  al, [bp + 0x10]
    test al, 0xF0
    jz   .r
    test al, 0x0F
    jz   .r
    or   byte [bp + 0x14], 0x40
.r: ret

; hard disk types: 12h nibble, or 0Fh and 19h / 1Ah (C3BA)
hdc_get:
    mov  bl, 0
    jmp  short hd_type
hdd_get:
    mov  bl, 1
hd_type:                           ; BL = drive -> AX = type 0-47
    mov  al, [bp + 0x12]
    or   bl, bl
    jnz  .d
    shr  al, 4
.d: and  ax, 0x0F
    cmp  al, 0x0F
    jne  .r
    push di
    mov  di, bx
    and  di, 0xFF
    mov  al, [bp + di + 0x19]
    pop  di
    cmp  al, 47
    jbe  .r
    xor  al, al
.r: ret
hdc_set:
    mov  bl, 0
    jmp  short hd_tset
hdd_set:
    mov  bl, 1
hd_tset:                           ; BL = drive, AL = type
    push bx
    push cx
    xor  bh, bh
    mov  cl, al                    ; CL = nibble, CH = 19h/1Ah value
    xor  ch, ch
    cmp  al, 15
    jb   .n
    mov  cl, 0x0F
    mov  ch, al
.n: push di
    mov  di, bx
    mov  [bp + di + 0x19], ch
    pop  di
    mov  al, [bp + 0x12]
    or   bl, bl
    jnz  .dd
    and  al, 0x0F
    shl  cl, 4
    jmp  short .w
.dd:and  al, 0xF0
.w: or   al, cl
    mov  [bp + 0x12], al
    pop  cx
    pop  bx
    ret

; type-47 parameters: [1Bh + 9 x drive]: cylinders, heads, write precomp,
; control (08h with more than 8 heads), landing zone, sectors. For types
; 1-46 the value comes from AMI's table (E401) and cannot be changed.
%macro PARAM 4                     ; name, CMOS offset, table offset, 1 = byte
p_%1_c: mov bl, 0
        jmp short p_%1
p_%1_d: mov bl, 1
p_%1:   mov  dl, %2
        mov  dh, %3
        mov  cl, %4
        jmp  param_get
%endmacro
    PARAM cyl, 0, 0, 0
    PARAM hd, 2, 2, 1
    PARAM wp, 3, 5, 0
    PARAM lz, 6, 0x0C, 0
    PARAM sec, 8, 0x0E, 1

; param_get: BL = drive, DL = CMOS offset, DH = table offset, CL = 1: byte
param_get:
    push si
    call hd_type
    or   ax, ax
    jz   .r
    cmp  ax, 47
    jne  .tab
    mov  al, 9
    mul  bl
    add  al, dl
    add  al, 0x1B
    mov  si, ax
    mov  ax, [bp + si]
    jmp  short .w
.tab:
    dec  ax
    shl  ax, 4
    mov  si, ax
    mov  al, dh
    xor  ah, ah
    add  si, ax
    mov  ax, [cs:si + DRV_TABLE]
.w: or   cl, cl
    jz   .r
    xor  ah, ah
.r: pop  si
    ret

%macro PSET 3                      ; name, CMOS offset, 1 = byte
p_%1_set_c: mov bl, 0
            jmp short p_%1_set
p_%1_set_d: mov bl, 1
p_%1_set:   mov  dl, %2
            mov  cl, %3
            jmp  param_set
%endmacro
    PSET cyl, 0, 0
    PSET hd, 2, 1
    PSET wp, 3, 0
    PSET lz, 6, 0
    PSET sec, 8, 1

; param_set: BL = drive, DL = CMOS offset, CL = 1: byte, AX = value
param_set:
    push si
    push ax
    mov  al, 9
    mul  bl
    add  al, dl
    add  al, 0x1B
    xor  ah, ah
    mov  si, ax
    pop  ax
    or   cl, cl
    jnz  .b
    mov  [bp + si], ax
    pop  si
    ret
.b: mov  [bp + si], al
    cmp  dl, 2                     ; heads: the control byte follows (C6FD)
    jne  .r
    mov  byte [bp + si + 3], 0
    cmp  al, 8
    jbe  .r
    mov  byte [bp + si + 3], 8
.r: pop  si
    ret

; primary display (C113): 37h bit 1 = installed, 14h bits 5-4 = the adapter
dsp_get:
    mov  al, 4                     ; Not Installed
    test byte [bp + 0x37], 2
    jz   .r
    mov  al, [bp + 0x14]
    shr  al, 4
    and  al, 3
.r: xor  ah, ah
    ret
dsp_set:
    and  byte [bp + 0x14], 0xCF
    and  byte [bp + 0x37], 0xFD
    cmp  al, 4
    jae  .r
    shl  al, 4
    or   [bp + 0x14], al
    or   byte [bp + 0x37], 2
.r: ret

; one bit of the buffer: index 0 = bit set ("Installed" / "Enabled" first in its list)
%macro BIT 5                       ; name, CMOS byte, mask, 1 = the first value means set, 1 = EMS
%1_get:
    xor  ax, ax
    test byte [bp + %2], %3
%if %4
    jnz  .r
%else
    jz   .r
%endif
    inc  ax
.r: ret
%1_set:
    and  byte [bp + %2], ~%3 & 0xFF
    or   al, al
%if %4
    jnz  .r
%else
    jz   .r
%endif
    or   byte [bp + %2], %3
%if %5
.r: jmp  ems_recalc
%else
.r: ret
%endif
%endmacro
    BIT kbd, 0x37, 0x01, 1, 0      ; Installed / Not Installed
    BIT scr, 0x38, 0x10, 0, 0      ; 1 / 2
    BIT zws, 0x37, 0x20, 1, 0      ; Enabled / Disabled
    BIT rel, 0x38, 0x80, 1, 1      ; Enabled / Disabled (changes the EMS maximum)

; BIOS shadow (C210): 38h bits 6-5
shd_get:
    mov  al, [bp + 0x38]
    shr  al, 5
    and  ax, 3
    ret
shd_set:
    shl  al, 5
    and  byte [bp + 0x38], 0x9F
    or   [bp + 0x38], al
    jmp  ems_recalc

; EMS size (C24E): 36h in 64 KB units, at most 35h; 17h/18h = the rest
ems_get:
    mov  al, [bp + 0x36]
    xor  ah, ah
    ret
ems_set:
    mov  [bp + 0x36], al
ems_fix:
    mov  al, [bp + 0x36]
    cmp  al, [bp + 0x35]
    jbe  .k
    mov  al, [bp + 0x35]
    mov  [bp + 0x36], al
.k: mov  ah, [bp + 0x35]
    sub  ah, al
    mov  al, ah
    xor  ah, ah
    shl  ax, 6
    mov  [bp + 0x17], ax
    ret

; ems_recalc: the EMS maximum (35h) from the HT12 banks and 38h, as AMI's
; EMS field does (C254-C28B) for 3 banks; then ems_fix
ems_recalc:
    mov  al, 0x10
    call ht12_rd
    and  al, 7
    cmp  al, 3
    jne  ems_fix
    mov  al, [bp + 0x38]
    xor  bl, bl
    test al, 0x80                  ; relocation off: nothing above 1 MB for EMS
    jz   .s
    mov  bl, 4
    test al, 0x40
    jnz  .m
    inc  bl
.m: test al, 0x20
    jnz  .v
    inc  bl
    jmp  short .s
.v: test al, 0x40
    jnz  .s
    sub  bl, 3
.s: mov  [bp + 0x35], bl
    jmp  ems_fix

; BUBios settings (CMOS 3Eh / 3Fh in the buffer)
bub_get:
    mov  al, [bp + CM_BUB]
    mov  ah, al
    xor  ah, BUB_KEY
    cmp  ah, [bp + CM_CHK]
    je   .r
    xor  al, al
.r: xor  ah, ah
    ret
bub_set:
    mov  [bp + CM_BUB], al
    xor  al, BUB_KEY
    mov  [bp + CM_CHK], al
    ret
boot_get:
    call bub_get
    and  al, 3
    cmp  al, 2
    jbe  .r
    xor  al, al
.r: ret
boot_set:
    mov  dl, al
    call bub_get
    and  al, 0xFC
    or   al, dl
    jmp  bub_set
adt_get:
    call bub_get
    shr  al, 2
    and  al, 1
    ret
adt_set:
    mov  dl, al
    call bub_get
    and  al, 0xFB
    shl  dl, 2
    or   al, dl
    jmp  bub_set
sch_get:
    call bub_get
    shr  al, 4
    and  al, 7
    cmp  al, 5
    jbe  .r
    xor  al, al
.r: ret
sch_set:
    mov  dl, al
    call bub_get
    and  al, 0x8F
    shl  dl, 4
    or   al, dl
    jmp  bub_set

date_get:
time_get:
nop_set:
    ret

; =====================================================================
; drawing
; =====================================================================
vid_es_s:                          ; vid_es with the scheme from the buffer
    call vid_es
    cmp  byte [ST_SCH], SCH_MONO
    je   .r
    push ax
    call sch_get
    mov  [ST_SCH], al
    pop  ax
.r: ret

s_redraw:
    call vid_es_s
    mov  ah, 1                     ; no cursor
    mov  cx, 0x2000
    int  0x10
    mov  cx, 80 * 25
    xor  dx, dx
    call clear_at
    mov  al, ' '                   ; title bar
    mov  bl, AT_TITLE
    mov  cx, 80
    xor  dx, dx
    call fill_at
    mov  si, st_title
    mov  dx, POS(0, 1)
    mov  al, AT_TITLE
    call text_at
    mov  si, ps_title_r
    mov  dx, POS(0, 44)
    mov  al, AT_TITLE
    call text_at
    ; tabs
    xor  bx, bx
.t: mov  dl, [cs:bx + tab_col]
    mov  dh, R_TABS
    mov  al, AT_LABEL
    cmp  bl, [bp + F_TAB]
    jne  .t1
    mov  al, AT_TABA
.t1:push bx
    shl  bx, 1
    mov  si, [cs:bx + tab_names]
    call text_at
    pop  bx
    inc  bx
    cmp  bx, NTABS
    jb   .t
    mov  al, 0xC4
    mov  bl, AT_EMPTY
    mov  cx, 80
    mov  dx, POS(R_TABS + 1, 0)
    call fill_at
    mov  al, 0xC4
    mov  bl, AT_EMPTY
    mov  cx, 80
    mov  dx, POS(R_LINE2, 0)
    call fill_at
    mov  al, ' '                   ; key row
    mov  bl, AT_STAT
    mov  cx, 80
    mov  dx, POS(R_KEYS, 0)
    call fill_at
    mov  si, s_keys
    mov  dx, POS(R_KEYS, 1)
    mov  al, AT_STAT
    call text_at
    cmp  byte [bp + F_TAB], 0
    jne  s_redraw_fields
    call s_summary
    ; (falls through: no fields on the Summary page)

; the fields of this tab, the page's extra lines, the help rows
s_redraw_fields:
    call vid_es_s
    xor  bx, bx
.f: mov  si, bx
    shl  si, 4
    add  si, fields
    mov  al, [cs:si]
    cmp  al, [bp + F_TAB]
    jne  .nx
    push bx
    call s_draw_field
    pop  bx
.nx:inc  bx
    cmp  bx, NFIELDS
    jb   .f
    call s_extras
    ; help rows
    mov  dx, POS(R_HELP, 0)
    mov  cx, 160
    call clear_at
    mov  si, [bp + F_MSG]
    or   si, si
    jnz  .h
    cmp  byte [bp + F_FLD], 0xFF
    je   .r
    call s_fld
    mov  si, [cs:si + 14]
    or   si, si
    jz   .r
.h: mov  dx, POS(R_HELP, 2)
    mov  al, AT_LABEL
    call attr
    call goto
.hl:cs lodsb
    or   al, al
    jz   .r
    cmp  al, 10
    jne  .hc
    mov  dx, POS(R_HELP + 1, 2)
    call goto
    jmp  short .hl
.hc:stosw
    jmp  short .hl
.r: ret

; s_draw_field: BX = index, CS:SI = record
s_draw_field:
    mov  al, [cs:si + 4]           ; a type-47 parameter of a drive that is
    test al, F_PARAMC | F_PARAMD   ; not installed: nothing on its row
    jz   .show
    push bx
    mov  bl, 0
    test al, F_PARAMC
    jnz  .pd
    mov  bl, 1
.pd:call hd_type
    pop  bx
    or   ax, ax
    jnz  .show
    mov  dh, [cs:si + 1]
    mov  dl, [cs:si + 2]
    mov  cl, [cs:si + 3]
    sub  cl, dl
    add  cl, [cs:si + 5]
    xor  ch, ch
    jmp  clear_at
.show:
    mov  dh, [cs:si + 1]
    mov  dl, [cs:si + 2]
    push si
    mov  si, [cs:si + 6]
    mov  al, AT_LABEL
    or   si, si
    jz   .nl
    call text_at
.nl:pop  si
    mov  dl, [cs:si + 3]
    mov  cl, [cs:si + 5]           ; clear the value
    xor  ch, ch
    push dx
    call clear_at
    pop  dx
    call goto
    mov  al, AT_VALUE              ; the value's colour: selected or not
    cmp  bl, [bp + F_FLD]
    jne  .a
    mov  al, AT_SEL
.a: call attr
    mov  bh, ah
    mov  cl, [cs:si + 4]
    and  cl, 0x0F
    cmp  bl, [bp + F_FLD]          ; being typed?
    jne  .v
    cmp  byte [bp + F_EDIT], 0
    jne  .typed
.v: cmp  cl, T_ACT
    je   .act
    cmp  cl, T_DATE
    je   .date
    cmp  cl, T_TIME
    je   .time
    push cx
    push si
    call [cs:si + 8]               ; AX = value / index
    pop  si
    pop  cx
    cmp  cl, T_CHOICE
    je   .ch
    cmp  cl, T_HDT
    je   .hdt
    cmp  cl, T_EMS
    je   .ems
    call pnum                      ; T_NUM
    ret
.ch:push bx
    mov  bx, [cs:si + 12]
    inc  bx
    shl  ax, 1
    add  bx, ax
    mov  si, [cs:bx]
    pop  bx
    jmp  .str_bh
.hdt:
    or   ax, ax
    jnz  .h1
    mov  si, s_notinst
    jmp  .str_bh
.h1:push ax
    call pnum
    pop  ax
    cmp  ax, 47
    jne  .r
    mov  si, s_user
    jmp  .str_bh
.ems:
    shl  ax, 6
    call pnum
    mov  si, s_kb
    jmp  .str_bh
.act:
    mov  si, [cs:si + 12]          ; the action's text, as the value
    jmp  .str_bh
.date:
    mov  ah, 4
    int  0x1A                      ; CH century, CL year, DH month, DL day (BCD)
    mov  al, dh
    call .bcd2
    mov  al, '/'
    call .c
    mov  al, dl
    call .bcd2
    mov  al, '/'
    call .c
    mov  al, ch
    call .bcd2
    mov  al, cl
    jmp  .bcd2
.time:
    mov  ah, 2
    int  0x1A                      ; CH hour, CL minute, DH second (BCD)
    mov  al, ch
    call .bcd2
    mov  al, ':'
    call .c
    mov  al, cl
    call .bcd2
    mov  al, ':'
    call .c
    mov  al, dh
    jmp  .bcd2
.typed:                            ; the digits so far, then underscores
    mov  [bp + 0x40], bh           ; (the attribute)
    mov  bx, mask_date
    cmp  cl, T_DATE
    je   .tm
    mov  bx, mask_time
    cmp  cl, T_TIME
    je   .tm
    xor  bx, bx                    ; a number
.tm:xor  si, si                    ; SI = digit number
.tl:or   bx, bx
    jz   .tnum
    mov  al, [cs:bx]
    inc  bx
    or   al, al
    jz   .r
    cmp  al, '#'
    je   .tdig
    call .c2
    jmp  short .tl
.tdig:
    mov  ax, si
    cmp  al, [bp + F_EDIT]
    mov  al, '_'
    jae  .tput
    mov  al, [bp + si + F_DIG]
    add  al, '0'
.tput:
    call .c2
    inc  si
    jmp  short .tl
.tnum:                             ; a number: the digits, then _
    mov  ax, si
    cmp  al, [bp + F_EDIT]
    jae  .tend
    mov  al, [bp + si + F_DIG]
    add  al, '0'
    call .c2
    inc  si
    jmp  short .tnum
.tend:
    mov  al, '_'
.c2:mov  ah, [bp + 0x40]
    stosw
    ret
.str_bh:
    mov  ah, bh
.str:
    jmp  pstr
.bcd2:
    push ax
    shr  al, 4
    add  al, '0'
    call .c
    pop  ax
    and  al, 0x0F
    add  al, '0'
.c: mov  ah, bh
    stosw
.r: ret

; s_extras: what a page shows besides its fields
s_extras:
    mov  al, [bp + F_TAB]
    cmp  al, 1
    je   x_standard
    cmp  al, 3
    je   x_chipset
    ret

x_standard:
    ; sizes of the two disks, after their parameter rows
    mov  bl, 0
    mov  dx, POS(11, 64)
    call x_size
    mov  bl, 1
    mov  dx, POS(14, 64)
    call x_size
    ; base / extended memory, coprocessor
    mov  dx, POS(19, C_SLBL)
    mov  si, sx_base
    mov  al, AT_LABEL
    call text_at
    mov  ax, [bp + 0x15]
    call x_kb
    mov  dx, POS(19, 30)
    mov  si, sx_ext
    mov  al, AT_LABEL
    call text_at
    mov  ax, [bp + 0x17]
    call x_kb
    mov  dx, POS(19, 58)
    mov  si, sx_fpu
    mov  al, AT_LABEL
    call text_at
    mov  si, s_none
    test byte [0x10], 2
    jz   .f
    mov  si, s_287
.f: mov  al, AT_VALUE
    call attr
    inc  di
    inc  di
    jmp  pstr

x_kb:                              ; AX KB after the label, in the value colour
    push ax
    mov  al, AT_VALUE
    call attr
    mov  bh, ah
    pop  ax
    inc  di
    inc  di
    call pnum
    mov  si, s_kb
    mov  ah, bh
    jmp  pstr

; x_size: BL = drive, DX = where: "nnn MB"
x_size:
    push bx
    push dx
    mov  cx, 12
    call clear_at
    pop  dx
    call hd_type
    or   ax, ax
    jz   .r
    push dx
    call p_cyl
    push ax
    call p_hd
    push ax
    call p_sec
    mov  si, ax
    pop  cx                        ; heads
    pop  ax                        ; cylinders
    pop  dx
    call goto
    mul  cx                        ; DX:AX = C x H
    mov  bx, dx
    mul  si
    push dx
    push ax
    mov  ax, bx
    mul  si
    pop  bx
    pop  dx
    add  dx, ax
    mov  ax, bx
    add  ax, 1024                  ; MB rounded, as AMI's page shows it
    adc  dx, 0
    mov  cx, 11
.mb:shr  dx, 1
    rcr  ax, 1
    loop .mb
    push ax
    mov  al, AT_VALUE
    call attr
    mov  bh, ah
    pop  ax
    call pnum
    mov  si, s_mb
    mov  ah, bh
    call pstr
.r: pop  bx
    ret

x_chipset:
    mov  dx, POS(10, C_SLBL)
    mov  si, sx_ext
    mov  al, AT_LABEL
    call text_at
    mov  ax, [bp + 0x17]
    call x_kb
    mov  dx, POS(11, C_SLBL)
    mov  si, sx_emsmax
    mov  al, AT_LABEL
    call text_at
    mov  al, [bp + 0x35]
    xor  ah, ah
    shl  ax, 6
    call x_kb
    mov  dx, POS(13, C_SLBL)
    mov  si, sx_chipnote
    mov  al, AT_LABEL
    jmp  text_at

; ---------------------------------------------------------------------
; the Summary page
; ---------------------------------------------------------------------
s_summary:
    mov  si, sum_labels
.l: cs lodsw
    or   ax, ax
    jz   .v
    xchg ax, dx
    cs lodsw
    push si
    xchg ax, si
    mov  al, AT_LABEL
    call text_at
    pop  si
    jmp  short .l
.v: ; left column
    mov  dx, POS(4, 21)
    mov  si, s_286
    call value_at
    mov  dx, POS(5, 21)
    call value_goto
    mov  al, [ST_MHZ]
    xor  ah, ah
    mov  si, s_dots
    or   al, al
    jz   .k
    jns  .std
    mov  si, s_about
    call value_goto_keep
    call pstr
    and  ax, 0x7F
.std:
    call pnum_v
    mov  si, s_mhz
.k: call value_goto_keep
    call pstr
    mov  si, s_none
    test byte [0x10], 2
    jz   .f
    mov  si, s_287
.f: mov  dx, POS(6, 21)
    call value_at
    mov  dx, POS(7, 21)
    mov  si, s_chipset
    call value_at
    mov  dx, POS(9, 21)
    call value_goto
    mov  ax, [bp + 0x15]
    call x_kb0
    mov  dx, POS(10, 21)
    call value_goto
    mov  ax, [bp + 0x17]
    call x_kb0
    mov  dx, POS(11, 21)
    call value_goto
    mov  al, [bp + 0x36]
    xor  ah, ah
    shl  ax, 6
    call x_kb0
    mov  dx, POS(12, 21)
    call shd_get
    mov  si, l_shadow
    call x_choice
    mov  dx, POS(14, 21)
    mov  si, s_bioscore
    call value_at
    ; right column
    mov  dx, POS(4, 60)
    call fda_get
    mov  si, l_floppy
    call x_choice
    mov  dx, POS(5, 60)
    call fdb_get
    mov  si, l_floppy
    call x_choice
    mov  bl, 0
    mov  dh, 7
    call sum_disk
    mov  bl, 1
    mov  dh, 11
    call sum_disk
    mov  dx, POS(15, 60)
    call boot_get
    mov  si, l_boot
    call x_choice
    mov  dx, POS(16, 60)
    call adt_get
    mov  si, l_onoff
    call x_choice
    mov  dx, POS(17, 60)
    call dsp_get
    mov  si, l_display
    call x_choice
    mov  dx, POS(18, 60)
    call kbd_get
    mov  si, l_kbd
    jmp  x_choice

x_kb0:                             ; AX KB at DI (value colour in AH)
    push ax
    mov  al, AT_VALUE
    call attr
    mov  bh, ah
    pop  ax
    call pnum
    mov  si, s_kb
    mov  ah, bh
    jmp  pstr

; x_choice: AX = index in the list SI, at DX, value colour
x_choice:
    inc  si
    shl  ax, 1
    add  si, ax
    mov  si, [cs:si]
    jmp  value_at

; sum_disk: BL = drive, DH = row: size [type], physical, DOS (ECHS)
sum_disk:
    mov  dl, 60
    call hd_type
    or   ax, ax
    jnz  .there
    mov  si, s_none
    jmp  value_at
.there:
    push dx
    call x_size                    ; "977 MB" at DX
    mov  al, AT_VALUE
    call attr
    mov  bh, ah
    mov  al, ' '
    stosw
    mov  al, '['
    stosw
    call hd_type
    call pnum
    mov  al, ']'
    mov  ah, bh
    stosw
    pop  dx
    inc  dh                        ; physical
    push dx
    mov  dl, 46
    mov  si, sx_phys
    mov  al, AT_LABEL
    call text_at
    pop  dx
    push dx
    call p_cyl
    push ax
    call p_hd
    push ax
    call p_sec
    mov  si, ax                    ; SI = sectors
    pop  cx                        ; CX = heads
    pop  ax                        ; AX = cylinders
    pop  dx
    push dx
    push ax
    push cx
    mov  dl, 60
    call value_goto
    mov  bh, ah
    pop  cx
    pop  ax
    push ax
    call pnum
    call slash_bh
    mov  ax, cx
    call pnum
    call slash_bh
    mov  ax, si
    call pnum
    pop  ax
    pop  dx
    inc  dh                        ; DOS (ECHS)
    push ax
    push cx
    push dx
    push si
    mov  dl, 46
    mov  si, sx_dos
    mov  al, AT_LABEL
    call text_at
    pop  si
    pop  dx
    mov  dl, 60
    call goto
    pop  cx                        ; heads
    pop  ax                        ; cylinders
    push ax
    call calc_factor               ; AX = translated heads (CX kept)
    mov  bx, ax
    pop  ax
    push bx
    mul  cx
    div  bx                        ; logical cylinders
    dec  ax
    cmp  ax, 1024
    jbe  .c
    mov  ax, 1024
.c: call pnum_v
    push ax
    mov  al, AT_VALUE
    call attr
    mov  bh, ah
    pop  ax
    call slash_bh
    pop  ax                        ; translated heads
    call pnum
    call slash_bh
    mov  ax, si
    jmp  pnum

slash_bh:
    push ax
    mov  al, '/'
    mov  ah, bh
    stosw
    pop  ax
    ret

; =====================================================================
; the field table: page, row, label column, value column, type, width,
; label, get, set (or action), list / maximum / action text, help
; =====================================================================
%macro FLD 11
    db %1, %2, %3, %4, %5, %6
    dw %7, %8, %9, %10, %11
%endmacro
fields:
    FLD 1,  4, C_SLBL, C_SVAL, T_DATE,   10, f_date,  date_get, nop_set, 0, h_date
    FLD 1,  5, C_SLBL, C_SVAL, T_TIME,    8, f_time,  time_get, nop_set, 0, h_time
    FLD 1,  7, C_SLBL, C_SVAL, T_CHOICE, 20, f_fda,   fda_get, fda_set, l_floppy, h_floppy
    FLD 1,  8, C_SLBL, C_SVAL, T_CHOICE, 20, f_fdb,   fdb_get, fdb_set, l_floppy, h_floppy
    FLD 1, 10, C_SLBL, C_SVAL, T_HDT,    20, f_hdc,   hdc_get, hdc_set, 0, h_hdt
    FLD 1, 11, 5,  10, T_NUM | F_PARAMC, 5, f_cyl,  p_cyl_c, p_cyl_set_c, 65535, h_cyl
    FLD 1, 11, 17, 22, T_NUM | F_PARAMC, 3, f_hd,   p_hd_c,  p_hd_set_c, 255, h_hd
    FLD 1, 11, 27, 33, T_NUM | F_PARAMC, 5, f_wp,   p_wp_c,  p_wp_set_c, 65535, h_wp
    FLD 1, 11, 40, 46, T_NUM | F_PARAMC, 5, f_lz,   p_lz_c,  p_lz_set_c, 65535, h_lz
    FLD 1, 11, 53, 58, T_NUM | F_PARAMC, 3, f_sec,  p_sec_c, p_sec_set_c, 255, h_sec
    FLD 1, 13, C_SLBL, C_SVAL, T_HDT,    20, f_hdd,   hdd_get, hdd_set, 0, h_hdt
    FLD 1, 14, 5,  10, T_NUM | F_PARAMD, 5, f_cyl,  p_cyl_d, p_cyl_set_d, 65535, h_cyl
    FLD 1, 14, 17, 22, T_NUM | F_PARAMD, 3, f_hd,   p_hd_d,  p_hd_set_d, 255, h_hd
    FLD 1, 14, 27, 33, T_NUM | F_PARAMD, 5, f_wp,   p_wp_d,  p_wp_set_d, 65535, h_wp
    FLD 1, 14, 40, 46, T_NUM | F_PARAMD, 5, f_lz,   p_lz_d,  p_lz_set_d, 65535, h_lz
    FLD 1, 14, 53, 58, T_NUM | F_PARAMD, 3, f_sec,  p_sec_d, p_sec_set_d, 255, h_sec
    FLD 1, 16, C_SLBL, C_SVAL, T_CHOICE, 20, f_dsp,   dsp_get, dsp_set, l_display, h_display
    FLD 1, 17, C_SLBL, C_SVAL, T_CHOICE, 20, f_kbd,   kbd_get, kbd_set, l_kbd, h_kbd
    FLD 2,  4, C_SLBL, C_SVAL+4, T_CHOICE, 20, f_boot, boot_get, boot_set, l_boot, h_boot
    FLD 2,  5, C_SLBL, C_SVAL+4, T_CHOICE, 20, f_adt,  adt_get, adt_set, l_onoff, h_adt
    FLD 2,  6, C_SLBL, C_SVAL+4, T_CHOICE, 20, f_sch,  sch_get, sch_set, l_scheme, h_sch
    FLD 3,  4, C_SLBL, C_SVAL, T_CHOICE, 20, f_shd,   shd_get, shd_set, l_shadow, h_shd
    FLD 3,  5, C_SLBL, C_SVAL, T_CHOICE, 36, f_scr,   scr_get, scr_set, l_scratch, h_scr
    FLD 3,  6, C_SLBL, C_SVAL, T_EMS,    20, f_ems,   ems_get, ems_set, 0, h_ems
    FLD 3,  7, C_SLBL, C_SVAL, T_CHOICE, 20, f_zws,   zws_get, zws_set, l_endis, h_zws
    FLD 3,  8, C_SLBL, C_SVAL, T_CHOICE, 20, f_rel,   rel_get, rel_set, l_endis, h_rel
    FLD 4,  4, C_SLBL, C_SLBL, T_ACT,    40, 0,       0, act_detc, a_detc, h_det
    FLD 4,  5, C_SLBL, C_SLBL, T_ACT,    40, 0,       0, act_detd, a_detd, h_det
    FLD 5,  4, C_SLBL, C_SLBL, T_ACT,    40, 0,       0, act_save, a_save, h_save
    FLD 5,  5, C_SLBL, C_SLBL, T_ACT,    40, 0,       0, act_quit, a_quit, h_quit
fields_end:
NFIELDS     equ (fields_end - fields) / 16

; ---------------------------------------------------------------------
; texts
; ---------------------------------------------------------------------
st_title:   db "BUBios/286 ", BUB_VER, " Setup", 0
tab_names:  dw t_sum, t_std, t_adv, t_chip, t_tools, t_exit
tab_col:    db 2, 13, 25, 37, 48, 57
t_sum:      db " Summary ", 0
t_std:      db " Standard ", 0
t_adv:      db " Advanced ", 0
t_chip:     db " Chipset ", 0
t_tools:    db " Tools ", 0
t_exit:     db " Exit ", 0
s_keys:     db "Tab:Page  ", 0x18, 0x19, ":Select  PgUp/PgDn:Set  0-9:Type  F2/F3:Colour  F10:Save  ESC:Exit", 0

f_date:     db "Date (mm/dd/yyyy)", 0
f_time:     db "Time (hh:mm:ss)", 0
f_fda:      db "Floppy drive A:", 0
f_fdb:      db "Floppy drive B:", 0
f_hdc:      db "Hard disk C: type", 0
f_hdd:      db "Hard disk D: type", 0
f_cyl:      db "Cyln", 0
f_hd:       db "Head", 0
f_wp:       db "WPcom", 0
f_lz:       db "LZone", 0
f_sec:      db "Sect", 0
f_dsp:      db "Primary display", 0
f_kbd:      db "Keyboard", 0
f_boot:     db "Boot sequence", 0
f_adt:      db "Auto-Detect Disks at Boot", 0
f_sch:      db "Colour scheme", 0
f_shd:      db "BIOS shadow option", 0
f_scr:      db "Scratch RAM option", 0
f_ems:      db "EMS size option", 0
f_zws:      db "0 Wait State option", 0
f_rel:      db "Memory relocation", 0
a_detc:     db "Auto-detect hard disk C: now", 0
a_detd:     db "Auto-detect hard disk D: now", 0
a_save:     db "Save settings and exit", 0
a_quit:     db "Exit without saving", 0

; choice lists: count, then the texts (index = the value get/set use)
l_floppy:   db 5
            dw s_notinst, s_fd360, s_fd12, s_fd720, s_fd144
l_display:  db 5
            dw s_d_vga, s_d_c40, s_d_c80, s_d_mono, s_notinst
l_kbd:      db 2
            dw s_inst, s_notinst
l_endis:    db 2
            dw s_enabled, s_disabled
l_shadow:   db 4
            dw s_disabled, s_v_bios, s_m_bios, s_mv_bios
l_scratch:  db 2
            dw s_scr1, s_scr2
l_boot:     db 3
            dw s_b_ac, s_b_ca, s_b_c
l_onoff:    db 2
            dw s_on, s_off
l_scheme:   db 6
            dw s_c_teal, s_c_amber, s_c_green, s_c_blue, s_c_grey, s_c_ami

s_notinst:  db "Not Installed", 0
s_inst:     db "Installed", 0
s_enabled:  db "Enabled", 0
s_user:     db " (user type)", 0
s_d_vga:    db "VGA or EGA", 0
s_d_c40:    db "Color 40x25", 0
s_d_c80:    db "Color 80x25", 0
s_d_mono:   db "Monochrome", 0
s_v_bios:   db "Video BIOS", 0
s_m_bios:   db "Main BIOS", 0
s_mv_bios:  db "Main & video BIOS", 0
s_scr1:     db "1 (BIOS stack area 0030:0000)", 0
s_scr2:     db "2 (base memory - 1 KB)", 0
s_b_ac:     db "A: then C:", 0
s_b_ca:     db "C: then A:", 0
s_b_c:      db "C: only", 0
s_on:       db "On", 0
s_off:      db "Off", 0
s_c_teal:   db "Teal", 0
s_c_amber:  db "Amber", 0
s_c_green:  db "Green", 0
s_c_blue:   db "Classic blue", 0
s_c_grey:   db "Grey", 0
s_c_ami:    db "AMI", 0
mask_date:  db "##/##/####", 0
mask_time:  db "##:##:##", 0
s_q_save:   db "Save settings and exit (Y/N)?", 0
s_q_quit:   db "Exit without saving (Y/N)?", 0
s_m_found:  db "Found: written as type 47 with the drive's own geometry.", 10
            db "Save to keep it.", 0
s_m_none:   db "No drive answered.", 0

sx_base:    db "Base memory", 0
sx_ext:     db "Extended memory", 0
sx_fpu:     db "Coprocessor", 0
sx_emsmax:  db "EMS maximum", 0
sx_chipnote:db "Headland HT12/A: shadow and relocation change the EMS maximum.", 0
sx_phys:    db 0xC3, 0xC4, " Physical", 0
sx_dos:     db 0xC0, 0xC4, " DOS (ECHS)", 0

sum_labels:
    dw POS(4, C_SLBL), sl_cpu
    dw POS(5, C_SLBL), sl_clock
    dw POS(6, C_SLBL), sl_fpu
    dw POS(7, C_SLBL), sl_chip
    dw POS(9, C_SLBL), sl_base
    dw POS(10, C_SLBL), sl_ext
    dw POS(11, C_SLBL), sl_ems
    dw POS(12, C_SLBL), sl_shadow
    dw POS(14, C_SLBL), sl_bios
    dw POS(4, 44), sl_fda
    dw POS(5, 44), sl_fdb
    dw POS(7, 44), sl_hdc
    dw POS(11, 44), sl_hdd
    dw POS(15, 44), sl_boot
    dw POS(16, 44), sl_adt
    dw POS(17, 44), sl_dsp
    dw POS(18, 44), sl_kbd
    dw 0
sl_cpu:     db "Processor", 0
sl_clock:   db "Clock", 0
sl_fpu:     db "Coprocessor", 0
sl_chip:    db "Chipset", 0
sl_base:    db "Base memory", 0
sl_ext:     db "Extended memory", 0
sl_ems:     db "EMS memory", 0
sl_shadow:  db "Shadow RAM", 0
sl_bios:    db "BIOS", 0
sl_fda:     db "Floppy A:", 0
sl_fdb:     db "Floppy B:", 0
sl_hdc:     db "Hard disk C:", 0
sl_hdd:     db "Hard disk D:", 0
sl_boot:    db "Boot sequence", 0
sl_adt:     db "Auto-detect", 0
sl_dsp:     db "Display", 0
sl_kbd:     db "Keyboard", 0

h_date:     db "Type the date as mm dd yyyy (1980-2099). It is set at once.", 0
h_time:     db "Type the time as hh mm ss (24 hours). It is set at once.", 0
h_floppy:   db "The drive's type: 360 KB / 1.2 MB 5", 0xAC, '"', ", 720 KB / 1.44 MB 3", 0xAB, '"', ".", 0
h_hdt:      db "1-46: AMI's table. 47: enter cylinders, heads, write precompensation,", 10
            db "landing zone, sectors (the drive's PHYSICAL geometry; ECHS does the rest).", 0
h_cyl:      db "Physical cylinders. Changing the geometry of a used disk makes its", 10
            db "partitions unreadable (the ECHS translation changes).", 0
h_hd:       db "Physical heads (1-16 for an IDE drive).", 0
h_wp:       db "Write precompensation: 65535 = none (IDE drives ignore it).", 0
h_lz:       db "Landing zone (IDE drives ignore it).", 0
h_sec:      db "Sectors per track (1-63).", 0
h_display:  db "The primary display adapter. Not Installed: POST does not check it.", 0
h_kbd:      db "Not Installed: POST does not test the keyboard.", 0
h_boot:     db "A: then C: (AMI's order), C: then A:, or C: only (A: is never tried).", 0
h_adt:      db "On: a drive set to Not Installed that answers at boot is set up as", 10
            db "type 47 with its own geometry. Drives you entered never change.", 0
h_sch:      db "Colours of the setup and the POST screen (also F2/F3).", 0
h_shd:      db "Copies the main and/or video BIOS into RAM (faster).", 0
h_scr:      db "Where the BIOS keeps 256 bytes (type-47 tables): 1 = BIOS stack area", 10
            db "at 0030:0000, 2 = the top 1 KB of base memory (base memory - 1 KB).", 0
h_ems:      db "Memory for EMS (HT12MM.SYS, HT12UMB) in 64 KB steps. What is not", 10
            db "EMS stays extended memory.", 0
h_zws:      db "Enabled: RAM accessed with 0 wait states.", 0
h_rel:      db "Enabled: unused shadow RAM (384 KB) relocated above 1 MB / to EMS.", 0
h_det:      db "Asks the drive for its geometry and enters it as type 47.", 0
h_save:     db "Writes the settings to CMOS and restarts the PC.", 0
h_quit:     db "Leaves setup without changing anything; the boot continues.", 0
setup_end:
