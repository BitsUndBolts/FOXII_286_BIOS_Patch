; Step 1 ROM: ECHS translation only (confirmed on the board 2026-11-19)
BITS 16
CPU 286             ; the FOX II is an 80286: any 386 instruction is an assembler error
ORG 0xF537          ; free-space block F537-F83D in segment F000 (F83E: checksum word)

%include "echs.asm"
