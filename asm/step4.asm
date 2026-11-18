; Step 4 ROM: Step 3 + "386 code while booting from A:: message, then boot from C:"
;
; Several code blocks, each a section placed at its ROM offset (file
; offset == ROM offset; py/build.py copies each section from NASM's map):
;   .text  F537-   Step 1 + Step 2, unchanged and at the same addresses
;   auto1  7F0F-   Step 3, part 1 (7000-7FFF: no ROM checksum covers it)
;   auto2  E32D-   Step 3, part 2
;   boot*          Step 4 (see bootskip.asm)
BITS 16
CPU 286             ; the FOX II is an 80286: any 386 instruction is an assembler error
[map all step4.map]

section .text start=0xF537 vstart=0xF537   ; free block F537-F83D (F83E: checksum word)
%include "echs.asm" ; first, so its code keeps the Step 1 addresses
%include "int6.asm"
text_end:

%include "autodet.asm"
%include "bootskip.asm"
