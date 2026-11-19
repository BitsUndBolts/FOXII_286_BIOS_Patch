; =====================================================================
;  Round 5b: the POST screen of BUBios/286
;
;  A full-screen POST display in the style of BUBios (the SOYO's
;  BUBios/asm/post.asm), rewritten for the 286 and this AMI BIOS. AMI's
;  POST still does all the work in the same order; this code replaces
;  what POST prints, through same-length CALL / JMP hooks that
;  py/build.py applies and asserts (docs/DEVELOPMENT_LOG.md, round 5b):
;
;    92C1  CALL F042 (copyright line, cp 22h)   -> CALL bu_init
;    76D0  copyright + BIOS ID (cp 24h/42h/7Ch) -> JMP bu_idline
;    766E  screen tamper check                  -> RET
;    ACDB  memory count print (cp 3Ah-3Ch)      -> CALL bu_mem, JMP AD01
;    AD05  "Press <ESC> to bypass MEMORY test"  -> CALL bu_escmsg, JMP AD1E
;    AB60  clear the message row (cp 43h, 7Fh)  -> JMP bu_clrmsg
;    93F6  "Press <DEL> ... SETUP or DIAGS"     -> CALL bu_delmsg, NOPs
;    96E7  MOV SI,7AB2 (error list, cp 85h)     -> CALL bu_errors
;    9791  mode set before the configuration box -> CALL bu_refresh, NOPs
;    0008  JMP 7000 (configuration box)         -> JMP bu_final
;
;  State between the hooks lives in the BDA's intra-application area
;  40:F0-FF: POST clears 0:0500-7BFF at checkpoint 7Fh. bu_final clears
;  the area again before INT 19h (Step 4 uses 40:F0 from INT 19h on).
;
;  Everything here runs with CS = F000; DS = 0040h inside the routines,
;  ES = the text buffer (B800h, or B000h in mode 7). 286 code only.
; =====================================================================

; ---- AMI routines ------------------------------------------------------
A_CMOSRD   equ 0xEE9F     ; AL = index -> AL (other registers kept)
A_PUTENC   equ 0x75BB     ; print the encoded string CS:SI at the cursor, attribute BL
A_PUTC     equ 0x7618     ; AL at the cursor, attribute BL, cursor advanced
A_VIDEO    equ 0x75F5     ; INT 10h through the vector
A_KBCCMD   equ 0x8E7A     ; KBC command AL (ZF = 1: sent)
A_KBCOBF   equ 0x8E58     ; wait for the KBC output buffer
A_KBCEND   equ 0x8EB3     ; KBC back to normal (as 76D0 ends)
A_LPTTEST  equ 0x97FC     ; AMI's LPT probe: DX = port, DI = index, DS = 40h
A_COMTEST  equ 0x9808     ; AMI's COM probe: DX = port, DI = index, DS = 40h
S_BIOSID   equ 0x9818     ; encoded "          DH12-1112-061390-K" (then the KBC version)
DRV_TABLE  equ 0xE401     ; drive types 1-46, 16 bytes each (as an FDPT)
ERR_TABLE  equ 0x7AB2     ; AMI's error message table (96E7: MOV SI,7AB2)

; ---- state, BDA 40:F0-FF ------------------------------------------------
ST_FLAG    equ 0xF0       ; FLAG_UP while our screen is up (this POST)
FLAG_UP    equ 0xB2
ST_SCH     equ 0xF1       ; attribute table: 0 = teal ... 6 = monochrome
ST_UNITS   equ 0xF2       ; word: 64 KB blocks AMI has counted
ST_TOTAL   equ 0xF4       ; word: 64 KB blocks expected
ST_CM12    equ 0xF6       ; CMOS 12h when the screen was first drawn
ST_DISK    equ 0xF7       ; bits 1-0 C:, 3-2 D: (D_*), bit 4/5: C:/D: is a CF card
D_NONE     equ 0          ;   nothing answered
D_OK       equ 1          ;   identified, the model is on the screen
D_BUSY     equ 2          ;   busy at the first try: ask again at the end
D_FAIL     equ 3          ;   it answered but IDENTIFY failed (ATAPI, timeout)
ST_T0      equ 0xF8       ; word: RTC minute * 60 + second at checkpoint 22h
ST_MHZ     equ 0xFA       ; measured clock in MHz (0: not a standard clock)
ST_MISC    equ 0xFB       ; bit 0: screen redrawn (setup visited: no POST time)
                          ; bit 1: errors shown, bit 2: end of POST
ST_STAT    equ 0xFC       ; word: status line text
ST_KBCV    equ 0xFE       ; the KBC version character (bu_idline)

; ---- attribute indices ----------------------------------------------------
AT_BG      equ 0
AT_TITLE   equ 1
AT_LABEL   equ 2
AT_VALUE   equ 3
AT_FILL    equ 4
AT_EMPTY   equ 5
AT_ACCENT  equ 6
AT_ERR     equ 7
AT_STAT    equ 8
%ifdef ROUND6A
AT_SEL     equ 9          ; setup: the selected field
AT_TABA    equ 10         ; setup: the active tab
NATTR      equ 11
%else
NATTR      equ 9
%endif
SCH_MONO   equ 6

; ---- layout -----------------------------------------------------------------
R_SYS      equ 2          ; rows 2..5: processor / system
R_MEM      equ 7
R_FDD      equ 9
R_HDC      equ 10         ; rows 10-11: C:, 12-13: D:
R_PORTS    equ 15
R_ROMS     equ 16
R_LINE     equ 17
R_MSG      equ 18         ; rows 18..23: AMI's messages, then the boot's
R_STAT     equ 24
C_LBL      equ 2
C_VAL      equ 15
C_RLBL     equ 47
C_RVAL     equ 60
C_CF       equ 10         ; " CF " badge on a CF card's model row
BAR_W      equ 40
C_TIME     equ 40         ; status bar: text 1-36, | 38, "POST n s" 40, | 48, ID 50-78
C_ID       equ 50

%define POS(r,c) (((r) << 8) | (c))

TLOOP      equ 0x7C00     ; the clock loop is built at 0:7C00 (cleared at cp 7Fh)
T_PASSES   equ 250        ; passes of 32 x DIV BX + LOOP
CLOCK_K    equ 2129830    ; 250 x 714 clocks x 1.193182 MHz x 10: MHz x 10 = K / PIT ticks
T_MS       equ 66         ; port 61h bit 4 toggles per millisecond (15.09 us each)

section diag start=0x000B vstart=0x000B   ; the old diagnostics module (round 5a)

; =====================================================================
; bu_init -- 92C1 (checkpoint 22h), in place of AMI's copyright line.
; Draws the whole screen. The cursor ends two rows lower, as after
; AMI's line and its CR LF CR LF (92C8 reads it).
; =====================================================================
bu_init:
    pusha
    push ds
    push es
    push 0x40
    pop  ds
    cld
    xor  ax, ax                    ; fresh state (also after a warm boot)
    mov  [ST_UNITS], ax
    mov  [ST_DISK], al
    mov  [ST_MISC], al
    mov  [ST_KBCV], al
    mov  word [ST_STAT], s_st_wait
    mov  al, 0x12
    call A_CMOSRD
    mov  [ST_CM12], al
    call rtc_now
    mov  [ST_T0], ax
    call mem_total
    call measure_clock
    call early_ports
    call draw_all
    mov  byte [ST_FLAG], FLAG_UP
    call ident_all                 ; models of the drives that are ready
    mov  ah, 3                     ; cursor: two rows down, column 0
    xor  bh, bh
    int  0x10
    add  dh, 2
    xor  dl, dl
    mov  ah, 2
    int  0x10
    pop  es
    pop  ds
    popa
    ret

; =====================================================================
; bu_idline -- 76D0 (checkpoints 24h, 42h, 7Ch). AMI printed its
; copyright line on row 22 and the BIOS ID with the keyboard
; controller's version on row 24: the ID goes into the status bar,
; with AMI's own printer and KBC code (76E8-7715). Same frame as 76D0.
; =====================================================================
bu_idline:
    pusha
    push ds
    push 0x40
    pop  ds
    cmp  byte [ST_FLAG], FLAG_UP
    jne  .out
    mov  ah, 3
    xor  bh, bh
    call A_VIDEO
    push dx
    mov  dx, POS(R_STAT, C_ID)
    mov  ah, 2
    call A_VIDEO
    mov  al, AT_STAT
    call attr
    mov  bl, ah
    xor  bh, bh
    mov  si, S_BIOSID
    call A_PUTENC
    in   al, 0x60                  ; the KBC's version (76FD-7715)
    mov  al, 0xA1
    call A_KBCCMD
    jne  .v0
    mov  cx, 1
    call A_KBCOBF
    in   al, 0x60
    jne  .v
.v0:mov  al, '0'
.v: mov  [ST_KBCV], al
    call A_PUTC
    call A_KBCEND
    pop  dx
    xor  bh, bh
    mov  ah, 2
    call A_VIDEO
.out:
    pop  ds
    popa
    ret

; =====================================================================
; bu_mem -- ACDB, after each 64 KB block (AX = blocks counted, 1 first).
; Replaces AMI's "nnnnn KB OK" print. Keeps every register.
; =====================================================================
bu_mem:
    pusha
    push ds
    push es
    push 0x40
    pop  ds
    cld
    cmp  byte [ST_FLAG], FLAG_UP
    jne  .out
    mov  [ST_UNITS], ax
    cmp  ax, [ST_TOTAL]
    jbe  .d
    mov  [ST_TOTAL], ax
.d: call vid_es
    call draw_memory
.out:
    pop  es
    pop  ds
    popa
    ret

; =====================================================================
; status line hooks: ESC (cp 3Ah), AB60 clears the message row (cp 43h,
; 7Fh), DEL (cp 73h). All keep every register.
; =====================================================================
bu_escmsg:
    push si
    mov  si, s_st_esc
    jmp  short status_set
bu_clrmsg:
    push si
    mov  si, s_st_dev
    jmp  short status_set
bu_delmsg:
    push si
    mov  si, s_st_del
status_set:
    pusha
    push ds
    push es
    push 0x40
    pop  ds
    cld
    cmp  byte [ST_FLAG], FLAG_UP
    jne  .out
    mov  [ST_STAT], si
    call vid_es
    call draw_status
.out:
    pop  es
    pop  ds
    popa
    pop  si
    ret

; =====================================================================
; bu_errors -- 96E7 (checkpoint 85h), before AMI prints its error list:
; SI = 7AB2 as the replaced MOV, the message rows in the error colour
; (AMI's teletype keeps the attribute), the cursor above them (every
; message starts with CR LF). BX and BP (AMI's error flags) are kept.
; =====================================================================
bu_errors:
    pusha
    push ds
    push es
    push 0x40
    pop  ds
    cld
    cmp  byte [ST_FLAG], FLAG_UP
    jne  .out
    call vid_es
    or   byte [ST_MISC], 2
    mov  word [ST_STAT], s_st_err
    call draw_status
    mov  al, ' '
    mov  bl, AT_ERR
    mov  cx, 80 * (R_STAT - R_MSG)
    mov  dx, POS(R_MSG, 0)
    call fill_at
    mov  dx, POS(R_MSG - 1, 0)
    mov  ah, 2
    xor  bh, bh
    int  0x10
.out:
    pop  es
    pop  ds
    popa
    mov  si, ERR_TABLE
    ret

; =====================================================================
; bu_refresh -- 9791 (checkpoint 85h): AMI set the video mode again (=
; cleared the screen) before its configuration box. Redraw only if the
; screen is no longer ours: after setup, or when errors scrolled it.
; =====================================================================
bu_refresh:
    pusha
    push ds
    push es
    push 0x40
    pop  ds
    cld
    cmp  byte [ST_FLAG], FLAG_UP
    jne  .out
    call redraw_if_gone
.out:
    pop  es
    pop  ds
    popa
    ret

redraw_if_gone:
    call vid_es
    call screen_ours
    je   .r
    or   byte [ST_MISC], 1         ; redrawn: the POST time would include setup
    and  byte [ST_MISC], 0xFD      ; (and AMI's messages are gone)
    mov  ah, 0x0F
    int  0x10
    xor  ah, ah
    int  0x10
    call draw_all
    call ident_all
.r: ret

; ZF = 1 if the title bar is still ours (ES = text buffer)
screen_ours:
    push si
    push di
    push ax
    mov  al, AT_TITLE
    call attr
    mov  si, ps_title
    mov  di, 2
.c: cs lodsb
    or   al, al
    jz   .y
    cmp  [es:di], ax
    jne  .n
    inc  di
    inc  di
    jmp  short .c
.y: xor  al, al                    ; ZF = 1
.n: pop  ax
    pop  di
    pop  si
    ret

; =====================================================================
; bu_final -- F000:0008 (AMI's configuration box, the end of POST),
; reached through MOV AX,8 / CALL AX at 97C1; returns to 97C6 (JMP 8F48:
; the boot). No pause.
; =====================================================================
bu_final:
    pusha
    push ds
    push es
    push 0x40
    pop  ds
    cld
    cmp  byte [ST_FLAG], FLAG_UP
    jne  .clr
    or   byte [ST_MISC], 4
    call redraw_if_gone
    mov  ax, 1                     ; the bar full
    mov  [ST_UNITS], ax
    mov  [ST_TOTAL], ax
    call draw_memory
    mov  bl, 0                     ; a drive that was busy at the start: once more
    call ident_late
    mov  bl, 1
    call ident_late
    mov  bl, 0
    call draw_disk
    mov  bl, 1
    call draw_disk
    call draw_late
%ifdef ROUND6A
    call bub_cfg                   ; the boot order chosen in setup
    and  al, 3
    mov  si, s_st_boot
    jz   .bo
    mov  si, s_st_bootc
    dec  al
    jz   .bo
    mov  si, s_st_bootco
.bo:mov  [ST_STAT], si
%else
    mov  word [ST_STAT], s_st_boot
%endif
    call draw_status
    ; the status bar moves up in place of the separator (row 17), so that
    ; the boot's messages (Step 4, DOS) have rows 18-24, grey on black,
    ; and scroll the screen up from row 24 as usual. AMI's error messages
    ; stay; the boot continues below them.
    push ds
    push es
    pop  ds
    mov  si, R_STAT * 160
    mov  di, R_LINE * 160
    mov  cx, 80
    rep  movsw
    pop  ds
    mov  dx, POS(R_MSG, 0)
    test byte [ST_MISC], 2
    jz   .clear
    mov  dx, POS(R_STAT, 0)
.clear:
    push dx
    call goto
    mov  ax, ((R_STAT + 1) << 8)   ; cells from DX to the end of the screen
    sub  ax, dx
    mov  cl, 8
    shr  ax, cl
    mov  cl, 80
    mul  cl
    mov  cx, ax
    mov  ax, 0x0720
    rep  stosw
    pop  dx
    mov  ah, 2
    xor  bh, bh
    int  0x10
    mov  cx, 0x0607                ; cursor visible again (0B0Ch on a mono card)
    cmp  byte [ST_SCH], SCH_MONO
    jne  .shape
    mov  cx, 0x0B0C
.shape:
    mov  ah, 1
    int  0x10
.clr:
    push ds                        ; leave the intra-application area clean
    pop  es
    mov  di, ST_FLAG
    mov  cx, 8
    xor  ax, ax
    rep  stosw
    pop  es
    pop  ds
    popa
    ret

; ---------------------------------------------------------------------
; values that are only known at the end of POST
; ---------------------------------------------------------------------
draw_late:
    mov  si, s_none                ; coprocessor: AMI's probe at cp 83h
    test byte [0x10], 2            ; (equipment bit 1)
    jz   .fpu
    mov  si, s_287
.fpu:
    mov  dx, POS(R_SYS, C_RVAL)
    call value_clr
    ; shadow RAM as the HT12 has it: reg 13h bits 4-7 (F000, main BIOS),
    ; reg 12h bits 0-1 (C000-C7FF, video BIOS)
    mov  dx, POS(R_SYS + 1, C_RVAL)
    mov  cx, 18
    call clear_at
    call value_goto
    mov  al, 0x13
    call ht12_rd
    mov  bl, al
    mov  al, 0x12
    call ht12_rd
    mov  bh, al
    xor  cx, cx                    ; CX = something shown
    test bl, 0xF0
    jz   .nm
    mov  si, s_main
    call pstr
    inc  cx
.nm:test bh, 0x03
    jz   .nv
    jcxz .v1
    mov  si, s_plus
    call pstr
.v1:mov  si, s_video
    call pstr
    inc  cx
.nv:or   cx, cx
    jnz  .p
    mov  si, s_disabled
    call pstr
.p: call draw_ports
    jmp  draw_roms

; =====================================================================
; the screen
; =====================================================================
draw_all:
    call vid_es
    mov  ah, 1                     ; no cursor while POST draws
    mov  cx, 0x2000
    int  0x10
    mov  cx, 80 * 25               ; clear
    xor  dx, dx
    call clear_at
    mov  al, ' '                   ; title bar
    mov  bl, AT_TITLE
    mov  cx, 80
    xor  dx, dx
    call fill_at
    mov  si, labels
.lab:
    cs lodsw
    or   ax, ax
    jz   .labd
    xchg ax, dx                    ; DX = row:column
    cs lodsb                       ; AL = attribute index
    push si
    mov  si, [cs:si]
    call text_at
    pop  si
    inc  si
    inc  si
    jmp  short .lab
.labd:
    mov  al, 0xC4                  ; separator above the messages
    mov  bl, AT_EMPTY
    mov  cx, 80
    mov  dx, POS(R_LINE, 0)
    call fill_at
    ; processor: AMI's own test (71F3): a 286 never sets FLAGS bits 12-15
    mov  si, s_286
    pushf
    cli
    mov  ax, 0xF000
    push ax
    popf
    pushf
    pop  ax
    popf
    test ah, 0xF0
    jz   .cpu
    mov  si, s_386
.cpu:
    mov  dx, POS(R_SYS, C_VAL)
    call value_at
    ; clock
    mov  dx, POS(R_SYS + 1, C_VAL)
    call value_goto
    mov  al, [ST_MHZ]
    xor  ah, ah
    mov  si, s_dots
    or   al, al
    jz   .clk
    jns  .std
    mov  si, s_about               ; a reading that is not a standard clock
    call value_goto_keep
    call pstr
    and  ax, 0x7F
.std:
    call pnum_v
    mov  si, s_mhz
.clk:
    call value_goto_keep           ; AH = value attribute again
    call pstr
    ; RTC battery: CMOS 0Dh bit 7 (valid RAM and time)
    mov  al, 0x0D
    call A_CMOSRD
    mov  si, s_ok
    test al, 0x80
    jnz  .rtc
    mov  si, s_low
.rtc:
    mov  dx, POS(R_SYS + 2, C_RVAL)
    call value_at
    call draw_memory
    call draw_floppies
    mov  bl, 0
    call draw_disk
    mov  bl, 1
    call draw_disk
    call draw_ports
    call draw_roms
    test byte [ST_MISC], 4         ; a redraw at the end of POST: all of it
    jz   .early
    call draw_late
    jmp  short draw_status
.early:
    mov  si, s_dots                ; coprocessor and shadow: at the end
    mov  dx, POS(R_SYS, C_RVAL)
    call value_at
    mov  si, s_dots
    mov  dx, POS(R_SYS + 1, C_RVAL)
    call value_at
draw_status:
    mov  al, ' '
    mov  bl, AT_STAT
    mov  cx, 80
    mov  dx, POS(R_STAT, 0)
    call fill_at
    mov  al, AT_STAT
    call attr                      ; AH = status attribute from here on
    mov  bh, ah
    mov  dx, POS(R_STAT, 1)
    call goto
    mov  si, [ST_STAT]
    call pstr
    mov  dx, POS(R_STAT, C_TIME - 2)
    call goto
    mov  al, 0xB3
    stosw
    mov  dx, POS(R_STAT, C_ID - 2)
    call goto
    mov  al, 0xB3
    stosw
    inc  di
    inc  di
    mov  si, S_BIOSID              ; the BIOS ID as bu_idline prints it
.id:cs lodsb
    not  al
    rol  al, 5
    push ax
    and  al, 0x7F
    mov  ah, bh
    stosw
    pop  ax
    test al, 0x80
    jz   .id
    mov  al, [ST_KBCV]
    or   al, al
    jz   .t
    mov  ah, bh
    stosw
.t: test byte [ST_MISC], 4         ; at the end: how long POST took
    jz   .r
    test byte [ST_MISC], 1         ; (not after a setup visit)
    jnz  .r
    call rtc_now
    sub  ax, [ST_T0]
    jns  .p
    add  ax, 3600
.p: cmp  ax, 600                   ; an implausible time (RTC not set): no
    jae  .r
    push ax
    mov  al, AT_STAT
    call attr
    mov  bh, ah
    mov  dx, POS(R_STAT, C_TIME)
    call goto
    mov  si, s_post
    call pstr
    pop  ax
    call pnum                      ; BH = status attribute
    mov  ah, bh
    mov  si, s_sec
    call pstr
.r: ret

; ---------------------------------------------------------------------
; memory: bar and count from ST_UNITS / ST_TOTAL
; ---------------------------------------------------------------------
draw_memory:
    mov  cx, [ST_TOTAL]
    mov  bx, [ST_UNITS]
    xor  ax, ax
    jcxz .bar
    mov  ax, BAR_W
    mul  bx
    div  cx
    cmp  ax, BAR_W
    jbe  .bar
    mov  ax, BAR_W
.bar:
    push ax
    xchg ax, cx
    mov  al, 0xDB
    mov  bl, AT_FILL
    mov  dx, POS(R_MEM, C_VAL)
    call fill_at
    pop  ax
    mov  cx, BAR_W
    sub  cx, ax
    mov  al, AT_EMPTY
    call attr
    mov  al, 0xB0
    rep  stosw
    mov  dx, POS(R_MEM, C_VAL + BAR_W + 2)
    mov  cx, 12
    call clear_at
    call value_goto
    mov  ax, [ST_UNITS]
    mov  cl, 6
    shl  ax, cl
    test byte [ST_MISC], 4         ; at the end: what POST found, in KB
    jz   .c                        ; (also after a warm boot, which skips
    push di                        ; the count): 40:13 + INT 15h AH=88h
    mov  ah, 0x88
    int  0x15
    pop  di
    add  ax, [0x13]
.c: mov  si, s_dots
    or   ax, ax
    jz   .p
    call pnum_v
    mov  si, s_kb
.p: call value_goto_keep
    jmp  pstr

; bar total: 640 KB + the extended memory CMOS knows (17h/18h or 30h/31h)
mem_total:
    mov  al, 0x18
    call A_CMOSRD
    mov  ah, al
    mov  al, 0x17
    call A_CMOSRD
    mov  bx, ax
    mov  al, 0x31
    call A_CMOSRD
    mov  ah, al
    mov  al, 0x30
    call A_CMOSRD
    cmp  ax, bx
    jae  .m
    xchg ax, bx
.m: mov  cl, 6
    shr  ax, cl
    add  ax, 10                    ; + 640 KB
    mov  [ST_TOTAL], ax
    ret

; ---------------------------------------------------------------------
; floppies: CMOS 10h (high nibble A:, low nibble B:)
; ---------------------------------------------------------------------
draw_floppies:
    mov  al, 0x10
    call A_CMOSRD
    push ax
    mov  cl, 4
    shr  al, cl
    mov  dx, POS(R_FDD, C_VAL)
    call .one
    pop  ax
    mov  dx, POS(R_FDD, C_RVAL)
.one:
    and  ax, 0x0F
    cmp  al, 5
    jb   .k
    mov  al, 5
.k: mov  bx, ax
    shl  bx, 1
    mov  si, [cs:bx + fdd_names]
    jmp  value_at

; ---------------------------------------------------------------------
; ports: the BDA (40:00-07 COM1-4, 40:08-0D LPT1-3)
; ---------------------------------------------------------------------
draw_ports:
    mov  dx, POS(R_PORTS, C_VAL)
    mov  cx, 64
    call clear_at
    call value_goto
    mov  bh, ah                    ; BH = value attribute
    xor  si, si                    ; SI = BDA offset
    xor  dx, dx                    ; DX = ports shown
.p: mov  ax, [si]
    or   ax, ax
    jz   .nx
    inc  dx
    push si
    push ax
    shl  si, 1
    add  si, port_names
    mov  cx, 4
    mov  ah, bh
.nm:cs lodsb
    stosw
    loop .nm
    mov  al, ' '
    stosw
    pop  ax
    mov  cx, 3
    call phex
    mov  ah, bh
    mov  al, ' '
    stosw
    stosw
    pop  si
.nx:inc  si
    inc  si
    cmp  si, 14
    jb   .p
    or   dx, dx
    jnz  .r
    mov  ah, bh
    mov  si, s_none
    call pstr
.r: ret

; ---------------------------------------------------------------------
; option ROMs: 55 AA in C000-EFFF in 2 KB steps, "C000 32K"
; ---------------------------------------------------------------------
draw_roms:
    mov  dx, POS(R_ROMS, C_VAL)
    mov  cx, 64
    call clear_at
    call value_goto
    mov  bh, ah                    ; BH = value attribute
    xor  dx, dx                    ; DX = ROMs shown
    mov  si, 0xC000                ; SI = segment
.r: push ds
    mov  ds, si
    mov  cx, [0]
    mov  al, [2]                   ; size in 512-byte blocks
    pop  ds
    cmp  cx, 0xAA55
    jne  .nx
    or   al, al
    jz   .nx
    cmp  dx, 6                     ; six fit on the row
    jae  .nx
    inc  dx
    xor  ah, ah
    inc  ax                        ; -> KB, rounded up
    shr  ax, 1
    push ax
    mov  ax, si
    mov  cx, 4
    call phex
    mov  ah, bh
    mov  al, ' '
    stosw
    pop  ax
    push ax
    call pnum
    mov  ah, bh
    mov  al, 'K'
    stosw
    mov  al, ' '
    stosw
    stosw
    pop  ax                        ; skip the ROM: KB -> 2 KB steps of 80h paragraphs
    inc  ax
    shr  ax, 1
    dec  ax
    mov  cl, 7
    shl  ax, cl
    add  si, ax
.nx:add  si, 0x80
    cmp  si, 0xF000
    jb   .r
    or   dx, dx
    jnz  .e
    mov  ah, bh
    mov  si, s_none
    call pstr
.e: ret

; =====================================================================
; disks
; =====================================================================
; draw_disk: BL = 0 (C:) or 1 (D:). Row 2 (type, geometry, size) from
; CMOS; the model row only when no model is on the screen (None, ...,
; Not found, no answer). BL kept.
draw_disk:
    push bx
    call disk_state                ; AL = D_* of this drive
    mov  bh, al
    call disk_geo                  ; AX = type (0 none), CX, DL = heads, SI
    push si
    push dx
    push cx
    push ax                        ; [type] [cyl] [heads] [sectors]
    call disk_rows                 ; DH = model row (BX kept)
    cmp  bh, D_OK
    je   .row2
    push dx
    mov  dl, C_CF
    mov  cx, 80 - C_CF
    call clear_at
    pop  dx
    mov  dl, C_VAL
    mov  si, s_dots
    cmp  bh, D_BUSY
    je   .t
    mov  si, s_noans
    cmp  bh, D_FAIL
    je   .t
    mov  si, s_none
    pop  ax
    push ax
    or   ax, ax
    jz   .t
    mov  si, s_notfound            ; configured, but nothing on the bus
.t: call value_at
.row2:
    inc  dh
    xor  dl, dl
    mov  cx, 80
    call clear_at
    mov  dl, C_VAL
    call value_goto
    pop  ax                        ; type
    pop  cx                        ; cylinders
    pop  dx                        ; DL = heads
    pop  si                        ; sectors
    or   ax, ax
    jz   .r
    ; "Auto": the drive's nibble in CMOS 12h was 0 when POST began
    push ax
    mov  al, [ST_CM12]
    or   bl, bl
    jnz  .lo
    shr  al, 4
.lo:and  al, 0x0F
    pop  ax
    jnz  .typ
    push si
    mov  si, s_auto
    call value_goto_keep
    call pstr
    pop  si
    jmp  short .geo
.typ:
    push si
    push ax
    mov  si, s_type
    call value_goto_keep
    call pstr
    pop  ax
    pop  si
    call pnum_v
.geo:
    call spc2
    mov  ax, cx                    ; physical C/H/S
    call pnum_v
    call slash
    mov  al, dl
    xor  ah, ah
    call pnum_v
    call slash
    mov  ax, si
    call pnum_v
    push si
    mov  si, s_arrow
    call value_goto_keep
    call pstr
    pop  si
    ; the geometry DOS sees through ECHS (Step 1): heads doubled until the
    ; cylinders fit in 1024 (calc_factor), cylinders - 1, at most 1024
    push cx
    push dx
    mov  ax, cx
    mov  cl, dl
    xor  ch, ch
    call calc_factor               ; AX = translated heads (CX kept)
    mov  bx, ax
    pop  dx
    pop  cx
    push cx
    push dx
    mov  ax, cx
    xor  dh, dh
    mul  dx                        ; DX:AX = cylinders x heads
    div  bx                        ; AX = logical cylinders
    dec  ax
    cmp  ax, 1024
    jbe  .dc
    mov  ax, 1024
.dc:call pnum_v
    call slash
    mov  ax, bx
    call pnum_v
    call slash
    mov  ax, si
    call pnum_v
    call spc2
    call spc2
    ; size in MB: cylinders x heads x sectors / 2048
    pop  dx
    pop  ax
    xor  dh, dh
    mul  dx                        ; DX:AX = C x H
    mov  bx, dx
    mul  si                        ; low word x S
    push dx
    push ax
    mov  ax, bx
    mul  si                        ; high word x S (fits 16 bits)
    pop  bx
    pop  dx
    add  dx, ax                    ; DX:BX = sectors
    mov  ax, bx
    mov  cx, 11
.mb:shr  dx, 1
    rcr  ax, 1
    loop .mb
    call pnum_v
    mov  si, s_mb
    call value_goto_keep
    call pstr
.r: pop  bx
    ret

slash:
    push ax
    mov  al, '/'
    jmp  short spc_c
spc2:
    push ax
    mov  al, ' '
    call value_goto_keep
    stosw
spc_c:
    call value_goto_keep
    stosw
    pop  ax
    ret

; disk_rows: BL = drive -> DH = its model row, DL = 0; BX kept
disk_rows:
    mov  dh, bl
    shl  dh, 1
    add  dh, R_HDC
    xor  dl, dl
    ret

; disk_state: BL = drive -> AL = its D_* state; BX kept
disk_state:
    mov  al, [ST_DISK]
    or   bl, bl
    jz   .c
    shr  al, 2
.c: and  al, 3
    ret

; set_state: BL = drive, AL = D_* -> ST_DISK; BX kept
set_state:
    push cx
    mov  ah, 3
    mov  cl, bl
    shl  cl, 1
    shl  ah, cl
    shl  al, cl
    not  ah
    and  [ST_DISK], ah
    or   [ST_DISK], al
    pop  cx
    ret

; disk_geo: BL = drive -> AX = type (0: none), CX = cylinders, DL = heads,
; SI = sectors (from CMOS, or AMI's table for types 1-46); BX, DH kept
disk_geo:
    push bx
    push dx
    mov  al, 0x12
    call A_CMOSRD
    or   bl, bl
    jnz  .d
    shr  al, 4
.d: and  ax, 0x0F
    jz   .none
    cmp  al, 0x0F
    jne  .tab
    mov  al, 0x19
    add  al, bl
    call A_CMOSRD
    xor  ah, ah
    or   al, al
    jz   .none
    cmp  al, 47
    ja   .none
    jb   .tab
    ; type 47: CMOS 1Bh (C:) / 24h (D:): cylinders, heads, ..., sectors at +8
    mov  al, 9
    mul  bl
    add  al, 0x1B
    mov  bh, al
    call A_CMOSRD
    mov  cl, al
    mov  al, bh
    inc  ax
    call A_CMOSRD
    mov  ch, al
    mov  al, bh
    add  al, 2
    call A_CMOSRD
    pop  dx
    mov  dl, al
    push dx
    mov  al, bh
    add  al, 8
    call A_CMOSRD
    xor  ah, ah
    mov  si, ax
    mov  ax, 47
    jmp  short .chk
.tab:                              ; ROM table: type 1 at E401, 16 bytes each
    push ax
    dec  ax
    mov  cl, 4
    shl  ax, cl
    mov  si, ax
    mov  cx, [cs:si + DRV_TABLE]
    mov  al, [cs:si + DRV_TABLE + 2]
    pop  dx                        ; DX = type
    pop  bx                        ; BX = caller's DX
    mov  bl, al                    ; heads
    push bx
    push dx
    mov  al, [cs:si + DRV_TABLE + 14]
    xor  ah, ah
    mov  si, ax
    pop  ax                        ; type
.chk:
    pop  dx
    jcxz .none1
    or   si, si
    jz   .none1
    or   dl, dl
    jz   .none1
    pop  bx
    ret
.none:
    pop  dx
.none1:
    xor  ax, ax
    pop  bx
    ret

; ---------------------------------------------------------------------
; ident_all: IDENTIFY both drives without waiting for a busy one; the
; model goes onto the screen. ident_late: BL = drive, once more at the
; end of POST if it was busy at the first try (up to 2 s).
; ---------------------------------------------------------------------
ident_all:
    mov  bl, 0
    call ident_one
    mov  bl, 1
    call ident_one
    mov  bl, 0
    call draw_disk
    mov  bl, 1
    jmp  draw_disk

ident_late:
    call disk_state
    cmp  al, D_BUSY
    jne  ident_r
    mov  cx, 2000
    jmp  short ident_w
ident_one:
    xor  cx, cx
ident_w:
    call ide_identify              ; AL = D_*
    call set_state
ident_r:
    ret

; ide_identify: BL = drive, CX = ms to wait for a busy drive -> AL = D_*
; (D_OK: the model and the CF badge are on the screen). BX kept.
; IRQ 14 is kept away: the drive's interrupt is off (3F6h nIEN), IRQ 14
; is masked in the slave PIC while the command runs, the status is read
; at the end and 40:8E cleared; the master is selected again at the end.
ide_identify:
    push bx
    push cx
    push dx
    push si
    push di
    push bp
    in   al, 0xA1                  ; mask IRQ 14
    push ax
    or   al, 0x40
    out  0xA1, al
    mov  dx, 0x3F6
    mov  al, 0x02                  ; nIEN
    out  dx, al
    mov  dx, 0x1F6
    mov  al, bl
    shl  al, 4
    or   al, 0xA0
    out  dx, al
    call toggle                    ; > 400 ns for the status to settle
    mov  dl, 0xF7
    in   al, dx
    mov  bp, D_NONE
    cmp  al, 0xFF                  ; nothing on the bus
    je   .end
    cmp  al, 0x7F
    je   .end
    or   al, al                    ; a master answering for a missing slave
    jz   .end
    ; wait up to CX ms (0: no wait) for BSY = 0 and DRDY = 1
    mov  bp, D_BUSY
    inc  cx
.rd:in   al, dx
    and  al, 0xC0
    cmp  al, 0x40
    je   .ready
    dec  cx
    jz   .end
    call ms1
    jmp  short .rd
.ready:
    mov  bp, D_FAIL
    mov  al, 0xEC                  ; IDENTIFY DEVICE
    out  dx, al
    mov  cx, 2000                  ; 2 s for the data
.dq:call ms1
    in   al, dx
    test al, 0x80
    jnz  .dn
    test al, 0x01                  ; ERR: ATAPI, or not supported
    jnz  .end
    test al, 0x08
    jnz  .data
.dn:loop .dq
    jmp  short .end
.data:
    ; the 256 words: the model (words 27-46) straight onto the screen; a CF
    ; card: word 0 = 848Ah, or word 83 bits 15:14 = 01 with bit 2 (CFA) set
    call disk_rows
    push dx
    mov  dl, C_CF
    mov  cx, 80 - C_CF
    call clear_at
    pop  dx
    mov  dl, C_VAL
    call value_goto                ; ES:DI, AH = value attribute
    mov  bh, ah
    mov  dx, 0x1F0
    xor  cx, cx                    ; word number
    xor  si, si                    ; SI = 1: a CF card
.w: in   ax, dx
    or   cx, cx
    jnz  .w1
    cmp  ax, 0x848A
    jne  .nx
    inc  si
    jmp  short .nx
.w1:cmp  cx, 83
    jne  .w2
    and  ax, 0xC004
    cmp  ax, 0x4004
    jne  .nx
    inc  si
    jmp  short .nx
.w2:cmp  cx, 27
    jb   .nx
    cmp  cx, 46
    ja   .nx
    push ax                        ; AH = first character, AL = second
    mov  al, ah
    call .ch
    pop  ax
    call .ch
.nx:inc  cx
    cmp  cx, 256
    jb   .w
    mov  dl, 0xF7
    in   al, dx                    ; status read: clears the drive's IRQ
    mov  bp, D_OK
    or   si, si
    jz   .end
    mov  al, 0x10                  ; CF: badge and ST_DISK bit 4 (C:) / 5 (D:)
    mov  cl, bl
    shl  al, cl
    or   [ST_DISK], al
    call disk_rows
    mov  dl, C_CF
    mov  al, AT_TITLE
    mov  si, s_cf
    call text_at
.end:
    mov  dx, 0x1F6                 ; the master selected again
    mov  al, 0xA0
    out  dx, al
    mov  dx, 0x3F6                 ; the drive's interrupt on again
    xor  al, al
    out  dx, al
    mov  byte [0x8E], 0            ; no IRQ 14 seen
    pop  ax                        ; IRQ 14 mask as it was
    out  0xA1, al
    mov  ax, bp
    pop  bp
    pop  di
    pop  si
    pop  dx
    pop  cx
    pop  bx
    ret
.ch:or   al, al                    ; a model character, 00h as a space
    jnz  .c1
    mov  al, ' '
.c1:mov  ah, bh
    stosw
    ret

; =====================================================================
; measurements and probes
; =====================================================================
; measure_clock -> [ST_MHZ]: 250 passes of 32 x DIV BX + LOOP, built at
; 0:7C00 (RAM: the ROM has wait states) and timed by PIT channel 2.
; 80286: DIV r16 22 clocks, LOOP 8 + the queue refill (2 bytes): 714 per
; pass. Shown only within 1/16 of a standard clock.
measure_clock:
    push es
    push 0
    pop  es
    mov  di, TLOOP
    mov  si, tl_head
    mov  cx, tl_head_end - tl_head
    rep  cs movsb
    mov  ax, 0xF3F7                ; 32 x DIV BX
    mov  cx, 32
    rep  stosw
    mov  ax, 0xBEE2                ; LOOP back to the first DIV (-66)
    stosw
    mov  al, 0xCB                  ; RETF
    stosb
    pop  es
    pushf
    cli
    in   al, 0x61
    push ax
    and  al, 0xFC
    out  0x61, al
    mov  al, 0xB0                  ; channel 2, mode 0, 16 bits
    out  0x43, al
    mov  al, 0xFF
    out  0x42, al
    out  0x42, al
    in   al, 0x61
    or   al, 1                     ; gate on, speaker off
    out  0x61, al
    call 0:TLOOP
    mov  al, 0x80                  ; latch channel 2
    out  0x43, al
    in   al, 0x42
    mov  ah, al
    in   al, 0x42
    xchg al, ah
    not  ax                        ; elapsed ticks
    xchg ax, cx
    pop  ax
    out  0x61, al
    popf
    mov  byte [ST_MHZ], 0
    jcxz .r
    mov  ax, CLOCK_K & 0xFFFF
    mov  dx, CLOCK_K >> 16
    call div32                     ; DX:AX = MHz x 10
    or   dx, dx
    jnz  .r
    cmp  ax, 1000                  ; (more than 100 MHz: not a reading)
    jae  .r
    mov  si, clock_std             ; snap to a standard clock within 1/16
.sn:mov  cx, [cs:si]
    jcxz .raw
    inc  si
    inc  si
    mov  dx, ax
    sub  dx, cx
    jns  .abs
    neg  dx
.abs:
    mov  bx, cx
    shr  bx, 4
    cmp  dx, bx
    ja   .sn
    mov  ax, cx
    mov  cl, 10
    div  cl
    mov  [ST_MHZ], al
.r: ret
.raw:                              ; not a standard clock: "about n MHz" (bit 7)
    add  ax, 5
    mov  cl, 10
    div  cl
    or   al, 0x80
    mov  [ST_MHZ], al
    ret

tl_head:                           ; MOV CX,T_PASSES / MOV BX,1 / XOR DX,DX / MOV AX,1234h
    db 0xB9
    dw T_PASSES
    db 0xBB, 0x01, 0x00, 0x31, 0xD2, 0xB8, 0x34, 0x12
tl_head_end:
clock_std:  dw 60, 80, 100, 120, 160, 200, 250, 0

; early_ports: COM and LPT into the BDA with AMI's own probes (9808,
; 97FC, as at checkpoint 81h-82h), so the row is filled at once
early_ports:
    xor  bx, bx                    ; (CF2D, under 97FC, expects BX = 0 as at 960D)
    xor  di, di
    mov  si, lpt_list
    call .list
    xor  di, di
    mov  si, com_list
.list:
    mov  dx, [cs:si]
    or   dx, dx
    jz   .r
    inc  si
    inc  si
    push si
    cmp  si, com_list
    ja   .com
    call A_LPTTEST
    jmp  short .n
.com:
    call A_COMTEST
.n: pop  si
    jmp  short .list
.r: ret
lpt_list:   dw 0x3BC, 0x378, 0x278, 0
com_list:   dw 0x3F8, 0x2F8, 0x3E8, 0x2E8, 0

; rtc_now -> AX = minute * 60 + second (RTC, BCD)
rtc_now:
    mov  al, 0x02
    call bcd_cmos
    mov  bl, 60
    mul  bl
    push ax
    mov  al, 0x00
    call bcd_cmos
    pop  bx
    add  ax, bx
    ret
bcd_cmos:                          ; AL = CMOS register (BCD) -> AX binary
    call A_CMOSRD
    mov  ah, al
    shr  ah, 4
    and  al, 0x0F
    aad
    xor  ah, ah
    ret

; ht12_rd: AL = HT12 register -> AL (as F458)
ht12_rd:
    push dx
    mov  dx, 0x1ED
    out  dx, al
    jmp  short $+2
    jmp  short $+2
    inc  dx
    inc  dx
    in   al, dx
    pop  dx
    ret

; toggle: wait for one change of port 61h bit 4 (refresh, every 15 us)
toggle:
    push ax
    push cx
    in   al, 0x61
    and  al, 0x10
    mov  ah, al
    mov  cx, 2000                  ; (bounded: refresh not running)
.t: in   al, 0x61
    and  al, 0x10
    cmp  al, ah
    loope .t
    pop  cx
    pop  ax
    ret
ms1:                               ; about 1 ms
    push cx
    mov  cx, T_MS
.m: call toggle
    loop .m
    pop  cx
    ret

; =====================================================================
; video helpers
; =====================================================================
vid_es:                            ; ES = text buffer, ST_SCH = the attribute table
    push ax
    mov  ax, 0xB000
    mov  byte [ST_SCH], SCH_MONO
    cmp  byte [0x49], 7
    je   .s
%ifdef ROUND6A
    call bub_cfg                   ; the colour scheme chosen in setup (CMOS 3Eh)
    shr  al, 4
    and  al, 7
    cmp  al, 6
    jb   .c
    xor  al, al
.c: mov  [ST_SCH], al
    mov  ax, 0xB800
%else
    mov  ax, 0xB800
    mov  byte [ST_SCH], 0          ; teal (the scheme byte comes with setup, 6a)
%endif
.s: mov  es, ax
    pop  ax
    ret

attr:                              ; AL = attribute index -> AH = attribute, AL = ' '
    push bx
    mov  bl, al
    mov  al, NATTR
    mul  byte [ST_SCH]
    add  al, bl
    xor  ah, ah
    mov  bx, ax
    mov  ah, [cs:bx + schemes]
    mov  al, ' '
    pop  bx
    ret

goto:                              ; DX = row:column -> DI
    push ax
    mov  al, 160
    mul  dh
    mov  di, ax
    mov  al, dl
    xor  ah, ah
    shl  ax, 1
    add  di, ax
    pop  ax
    ret

text_at:                           ; CS:SI at DX, attribute index AL
    call attr
    call goto
pstr:                              ; CS:SI -> ES:DI, attribute AH
    push ax
.l: cs lodsb
    or   al, al
    jz   .r
    stosw
    jmp  short .l
.r: pop  ax
    ret

fill_at:                           ; CX x character AL at DX, attribute index BL
    push ax
    mov  al, bl
    call attr
    pop  bx
    mov  al, bl
    call goto
    rep  stosw
    ret

clear_at:                          ; CX blanks at DX in the background colour
    push bx
    mov  al, ' '
    mov  bl, AT_BG
    call fill_at
    pop  bx
    ret

value_at:                          ; CS:SI at DX in the value colour
    mov  al, AT_VALUE
    jmp  text_at

value_clr:                         ; the same, after clearing 18 cells
    push si
    push dx
    mov  cx, 18
    call clear_at
    pop  dx
    pop  si
    jmp  value_at

value_goto:                        ; DX -> DI, AH = value attribute
    call goto
value_goto_keep:                   ; AH = value attribute (DI kept)
    push bx
    mov  bl, al
    mov  al, AT_VALUE
    call attr
    mov  al, bl
    pop  bx
    ret

; pnum: AX unsigned -> decimal at ES:DI, attribute BH; BX CX DX SI kept
pnum:
    push cx
    push dx
    push bx
    mov  bx, 10
    xor  cx, cx
.d: xor  dx, dx
    div  bx
    push dx
    inc  cx
    or   ax, ax
    jnz  .d
    mov  bx, sp
    add  bx, cx
    add  bx, cx
    mov  bh, [ss:bx + 1]           ; the caller's BH, pushed under the digits
.o: pop  ax
    add  al, '0'
    mov  ah, bh
    stosw
    loop .o
    pop  bx
    pop  dx
    pop  cx
    ret

pnum_v:                            ; pnum in the value colour; BX kept
    push bx
    push ax
    mov  al, AT_VALUE
    call attr
    mov  bh, ah
    pop  ax
    call pnum
    pop  bx
    ret

; phex: the low CX hex digits of AX at ES:DI, attribute BH; AX CX kept
phex:
    push ax
    push cx
    push dx
    mov  dx, ax
    mov  ah, 4
    sub  ah, cl
.s: or   ah, ah                    ; skip the digits not shown
    jz   .l
    rol  dx, 4
    dec  ah
    jmp  short .s
.l: rol  dx, 4
    mov  al, dl
    and  al, 0x0F
    add  al, 0x90                  ; 0-9 / A-F
    daa
    adc  al, 0x40
    daa
    mov  ah, bh
    stosw
    loop .l
    pop  dx
    pop  cx
    pop  ax
    ret

; =====================================================================
; tables and texts
; =====================================================================
; attributes per scheme: BG TITLE LABEL VALUE FILL EMPTY ACCENT ERR STAT
%ifdef ROUND6A
; BG TITLE LABEL VALUE FILL EMPTY ACCENT ERR STAT  SEL  TABA
schemes:
    db 0x07, 0x30, 0x03, 0x0F, 0x0B, 0x08, 0x0A, 0x0C, 0x30, 0x30, 0x20   ; teal
    db 0x07, 0x60, 0x06, 0x0E, 0x0E, 0x08, 0x0F, 0x0C, 0x60, 0x60, 0x70   ; amber
    db 0x07, 0x20, 0x02, 0x0A, 0x0A, 0x08, 0x0F, 0x0C, 0x20, 0x20, 0x70   ; green
    db 0x17, 0x70, 0x17, 0x1F, 0x1E, 0x19, 0x1A, 0x1C, 0x70, 0x70, 0x30   ; classic blue
    db 0x07, 0x70, 0x07, 0x0F, 0x0F, 0x08, 0x0A, 0x0C, 0x70, 0x70, 0x0F   ; grey
    db 0x17, 0x70, 0x17, 0x1F, 0x1E, 0x19, 0x1A, 0x1C, 0x70, 0x70, 0x4F   ; AMI
    db 0x07, 0x70, 0x07, 0x0F, 0x0F, 0x07, 0x0F, 0x0F, 0x70, 0x70, 0x0F   ; monochrome
%else
schemes:
    db 0x07, 0x30, 0x03, 0x0F, 0x0B, 0x08, 0x0A, 0x0C, 0x30   ; teal
    db 0x07, 0x60, 0x06, 0x0E, 0x0E, 0x08, 0x0F, 0x0C, 0x60   ; amber
    db 0x07, 0x20, 0x02, 0x0A, 0x0A, 0x08, 0x0F, 0x0C, 0x20   ; green
    db 0x17, 0x70, 0x17, 0x1F, 0x1E, 0x19, 0x1A, 0x1C, 0x70   ; classic blue
    db 0x07, 0x70, 0x07, 0x0F, 0x0F, 0x08, 0x0A, 0x0C, 0x70   ; grey
    db 0x17, 0x70, 0x17, 0x1F, 0x1E, 0x19, 0x1A, 0x1C, 0x70   ; AMI
    db 0x07, 0x70, 0x07, 0x0F, 0x0F, 0x07, 0x0F, 0x0F, 0x70   ; monochrome
%endif

; row:column, attribute index, text
%macro LBL 4
    dw POS(%1, %2)
    db %3
    dw %4
%endmacro
labels:
    LBL 0, 1, AT_TITLE, ps_title
    LBL 0, 44, AT_TITLE, ps_title_r
    LBL R_SYS, C_LBL, AT_LABEL, pl_cpu
    LBL R_SYS, C_RLBL, AT_LABEL, pl_fpu
    LBL R_SYS + 1, C_LBL, AT_LABEL, pl_clock
    LBL R_SYS + 1, C_RLBL, AT_LABEL, pl_shadow
    LBL R_SYS + 2, C_LBL, AT_LABEL, pl_chip
    LBL R_SYS + 2, C_VAL, AT_VALUE, s_chipset
    LBL R_SYS + 2, C_RLBL, AT_LABEL, pl_rtc
    LBL R_SYS + 3, C_LBL, AT_LABEL, pl_bios
    LBL R_SYS + 3, C_VAL, AT_VALUE, s_bioscore
    LBL R_MEM, C_LBL, AT_LABEL, pl_mem
    LBL R_FDD, C_LBL, AT_LABEL, pl_fda
    LBL R_FDD, C_RLBL, AT_LABEL, pl_fdb
    LBL R_HDC, C_LBL, AT_LABEL, pl_diskc
    LBL R_HDC + 2, C_LBL, AT_LABEL, pl_diskd
    LBL R_PORTS, C_LBL, AT_LABEL, pl_ports
    LBL R_ROMS, C_LBL, AT_LABEL, pl_roms
    dw 0

port_names: db "COM1COM2COM3COM4LPT1LPT2LPT3"
fdd_names:  dw s_none, s_fd360, s_fd12, s_fd720, s_fd144, s_unknown

%ifdef ROUND6A
%define BUB_VER "0.6"
%else
%define BUB_VER "0.5"
%endif
ps_title:   db "BUBios/286 ", BUB_VER, "  ", 0xFE, "  Power-On Self Test", 0
ps_title_r: db "Bits und Bolts  ", 0xFE, "  Headland HT12/A", 0
pl_cpu:     db "Processor", 0
pl_fpu:     db "Coprocessor", 0
pl_clock:   db "Clock", 0
pl_shadow:  db "Shadow RAM", 0
pl_chip:    db "Chipset", 0
pl_rtc:     db "RTC battery", 0
pl_bios:    db "BIOS", 0
pl_mem:     db "Memory", 0
pl_fda:     db "Floppy A:", 0
pl_fdb:     db "Floppy B:", 0
pl_diskc:   db "Disk C:", 0
pl_diskd:   db "Disk D:", 0
pl_ports:   db "Ports", 0
pl_roms:    db "Option ROMs", 0
s_chipset:  db "Headland HT12/A", 0
s_bioscore: db "AMI 06/13/90 ", 0xFE, " BUBios/286 ", BUB_VER, 0
s_286:      db "80286", 0
s_386:      db "80386 or newer", 0
s_287:      db "287 present", 0
s_mhz:      db " MHz", 0
s_about:    db "about ", 0
s_ok:       db "OK", 0
s_low:      db "Low (CMOS lost)", 0
s_dots:     db "...", 0
s_none:     db "None", 0
s_unknown:  db "Unknown", 0
s_notfound: db "Not found (left out for this boot)", 0
s_noans:    db "No answer to IDENTIFY", 0
s_fd360:    db "360 KB, 5", 0xAC, '"', 0
s_fd12:     db "1.2 MB, 5", 0xAC, '"', 0
s_fd720:    db "720 KB, 3", 0xAB, '"', 0
s_fd144:    db "1.44 MB, 3", 0xAB, '"', 0
s_main:     db "Main", 0
s_video:    db "Video", 0
s_plus:     db " + ", 0
s_disabled: db "Disabled", 0
s_kb:       db " KB", 0
s_mb:       db " MB", 0
s_type:     db "Type ", 0
s_auto:     db "Auto", 0
s_cf:       db " CF ", 0
s_arrow:    db " ", 0x1A, " DOS ", 0
s_post:     db "POST ", 0
s_sec:      db " s", 0
s_st_wait:  db "Power-on self test", 0
s_st_esc:   db "Press ESC to skip the memory test", 0
s_st_dev:   db "Checking devices ...", 0
s_st_del:   db "Press DEL to run Setup", 0
s_st_err:   db "POST found a problem", 0
s_st_boot:  db "Booting: A: then C:", 0
%ifdef ROUND6A
s_st_bootc: db "Booting: C: then A:", 0
s_st_bootco:db "Booting: C: only", 0
%endif
post_end:
