; Step 2 ROM: Step 1 + a readable invalid-opcode (INT 06h) error
BITS 16
CPU 286             ; the FOX II is an 80286: any 386 instruction is an assembler error
ORG 0xF537          ; free-space block F537-F83D in segment F000 (F83E: checksum word)

%include "echs.asm" ; first, so its code keeps the Step 1 addresses
%include "int6.asm"
