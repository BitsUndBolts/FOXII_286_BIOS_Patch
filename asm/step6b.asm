; Round 6b ROM: round 6a + the tools of BUBios/286 (tools.asm), the EMS
; memory-bar fix, the Base / XMS / EMS line on the POST screen, the
; one-time boot key and HT12UMB.SYS in a fixed 2 KB slot at F000:6000.
; post.asm and setup.asm are assembled with ROUND6A and ROUND6B (version
; 0.7); without ROUND6B they are the 6a code byte for byte.
BITS 16
CPU 286             ; the FOX II is an 80286: any 386 instruction is an assembler error
[map all step6b.map]
%define ROUND6A
%define ROUND6B

section .text start=0xF537 vstart=0xF537   ; free block F537-F83D (F83E: checksum word)
%include "echs.asm" ; first, so its code keeps the Step 1 addresses
%include "int6.asm"
text_end:

%include "autodet.asm"
%include "bootskip.asm"
%include "post.asm"
%include "setup.asm"
%include "tools.asm"

; HT12UMB.SYS (BitsUndBolts/HT12UMB) in a fixed slot: a 16-byte tag at
; F000:5FF0, the driver at F000:6000, zeros up to 67FF. The DEBUG recipe
; (README) copies F000:6000 L800 to a file; it never changes.
section umb start=0x5FF0 vstart=0x5FF0
umb_tag:    db "BUBUMB"            ; +0 signature
            db "1.0", 0            ; +6 driver version (text)
            dw umb_end - umb_drv   ; +10 driver length
umb_sum:    dw 0                   ; +12 word sum of the 2 KB slot (build.py), 0 = unchecked
            dw 0                   ; +14
umb_drv:    incbin "../extra/HT12UMB.SYS"
umb_end:
            times 0x800 - (umb_end - umb_drv) db 0
