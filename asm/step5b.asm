; Round 5b ROM: round 5a (Step 4 without the AMI ROM Diagnostics) + the
; POST screen (post.asm, in the old module area 000B-6FFD).
;
; Several code blocks, each a section placed at its ROM offset (file
; offset == ROM offset - the lowest section start; py/build.py copies
; each section from NASM's map):
;   .text  F537-   Step 1 + Step 2, unchanged and at the same addresses
;   auto1  7F0F-   Step 3, part 1
;   auto2  E32D-   Step 3, part 2
;   boot*          Step 4 (see bootskip.asm)
;   diag   000B-   round 5b: the POST screen
BITS 16
CPU 286             ; the FOX II is an 80286: any 386 instruction is an assembler error
[map all step5b.map]

section .text start=0xF537 vstart=0xF537   ; free block F537-F83D (F83E: checksum word)
%include "echs.asm" ; first, so its code keeps the Step 1 addresses
%include "int6.asm"
text_end:

%include "autodet.asm"
%include "bootskip.asm"
%include "post.asm"
