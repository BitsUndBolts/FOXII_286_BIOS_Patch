; Round 6a ROM: round 5b + the setup of BUBios/286 (setup.asm), the boot
; order and the auto-detect switch. post.asm is assembled with ROUND6A
; (version 0.6, the colour scheme from CMOS 3Eh, the boot order on the
; status line); without it, it is the 5b code byte for byte.
BITS 16
CPU 286             ; the FOX II is an 80286: any 386 instruction is an assembler error
[map all step6a.map]
%define ROUND6A

section .text start=0xF537 vstart=0xF537   ; free block F537-F83D (F83E: checksum word)
%include "echs.asm" ; first, so its code keeps the Step 1 addresses
%include "int6.asm"
text_end:

%include "autodet.asm"
%include "bootskip.asm"
%include "post.asm"
%include "setup.asm"
