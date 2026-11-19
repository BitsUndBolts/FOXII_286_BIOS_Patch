#!/usr/bin/env python3
"""bubios286.py - build BUBios/286 for the Octek FOX II from YOUR OWN BIOS dump.

The AMI BIOS code is not included here. This script only holds our own bytes: for each ROM,
the places where it differs from AMI's 286 BIOS 06/13/90 (the new code, the hooks into it,
the cleared diagnostics area, the HT12UMB.SYS driver and the checksum words). It checks that
your dump is that BIOS, puts our bytes in, and checks that the result is exactly the ROM
that was tested on the board.

Usage:
  python3 bubios286.py list
  python3 bubios286.py build BUBIOS286 MY_EVEN.BIN MY_ODD.BIN [--out DIR]
  python3 bubios286.py build ECHS      MY_EVEN.BIN MY_ODD.BIN [--out DIR]

Input: the two BIOS chips as dumped, 32 KB (27C256) or 64 KB with both halves identical
("doubled", 27C512 / 27SF512), or a single 64 KB CPU image as MY_EVEN.BIN with "-" as
MY_ODD.BIN. EVEN = the chip with the low data byte (D0-D7). Swapped chips are noticed
from the reset vector.

Output (in --out, default: current folder):
  <NAME>_EVEN.BIN / <NAME>_ODD.BIN       64 KB, doubled, for 27C512 / 27SF512
  <NAME>_EVEN32.BIN / <NAME>_ODD32.BIN   32 KB, for 27C256

Sources: the .asm files in bubios286/ next to this script. The full build (NASM + Python,
from the AMI image), the emulator and the tests: github.com/BitsUndBolts/FOXII_286_BIOS_Patch
Bits und Bolts retro knowledge base. Needs Python 3 and nothing else.
"""
import hashlib, os, struct, sys

BASE = 'c1be448f36fa735d0b488dcaa71ceb0243cd6a29f4955aec3449b9f791929cac'  # AMI 286 BIOS 06/13/90, DH12-1112-061390-KF (FOX II, as dumped)

# (offset in F000, our bytes as hex, None) or (offset, None, length of zeros)
PATCHES = {
# @@PATCHES@@
}


def die(msg):
    print("error: " + msg)
    sys.exit(2)


def load_chip(path):
    data = open(path, "rb").read()
    if len(data) == 65536:
        if data[:32768] != data[32768:]:
            die(f"{path}: 64 KB file, but the two halves differ - expected a doubled 32 KB image")
        data = data[32768:]
    if len(data) != 32768:
        die(f"{path}: size {len(data)} bytes, expected 32768 or 65536")
    return data


def interleave(even, odd):
    return bytearray(x for pair in zip(even, odd) for x in pair)


def word_sum(img):
    return sum(struct.unpack("<16384H", bytes(img[0x8000:]))) & 0xFFFF


def load_image(even_path, odd_path):
    if odd_path == "-":
        img = bytearray(open(even_path, "rb").read())
        if len(img) != 65536:
            die(f"{even_path}: a CPU image must be 64 KB")
        return img
    even, odd = load_chip(even_path), load_chip(odd_path)
    img = interleave(even, odd)
    if img[0xFFF0] != 0xEA and interleave(odd, even)[0xFFF0] == 0xEA:
        print("note: EVEN and ODD look swapped (reset vector) - using them the other way round")
        img = interleave(odd, even)
    return img


def cmd_list():
    for name, p in PATCHES.items():
        n = sum(len(h) // 2 if h else z for _, h, z in p["records"])
        print(f"{name:10} {p['what']}")
        print(f"{'':10} {len(p['records'])} records, {n} bytes of ours")


def cmd_build(name, even_path, odd_path, out):
    if name not in PATCHES:
        die(f"unknown ROM {name}; run 'bubios286.py list'")
    p = PATCHES[name]
    img = load_image(even_path, odd_path)
    if hashlib.sha256(bytes(img)).hexdigest() != BASE:
        die("this dump is not the AMI 286 BIOS 06/13/90 of the FOX II (sha256 " + BASE + ")\n"
            "(its date at F000:FFF5: " + bytes(img[0xFFF5:0xFFFD]).decode("latin1") + ")")
    if word_sum(img) != 0:
        die("your dump fails the AMI ROM checksum already - check the dump")
    for addr, hexbytes, zeros in p["records"]:
        b = bytes(zeros) if hexbytes is None else bytes.fromhex(hexbytes)
        img[addr:addr + len(b)] = b
    if word_sum(img) != 0:
        die("internal error: ROM checksum")
    if hashlib.sha256(bytes(img)).hexdigest() != p["result_sha256"]:
        die("result does not match the tested build - not writing anything")
    os.makedirs(out, exist_ok=True)
    e, o = bytes(img[0::2]), bytes(img[1::2])
    files = {f"{name}_EVEN.BIN": e + e, f"{name}_ODD.BIN": o + o,
             f"{name}_EVEN32.BIN": e, f"{name}_ODD32.BIN": o}
    for fn, data in files.items():
        open(os.path.join(out, fn), "wb").write(data)
    print(f"{name} built from AMI 06/13/90; ROM word checksum 0000h; matches the tested build.")
    for fn in files:
        print("  " + os.path.join(out, fn))
    print("Burn EVEN where the original EVEN (low byte) chip was, ODD where ODD was.")


def main(argv):
    if len(argv) >= 2 and argv[1] == "list":
        return cmd_list()
    if len(argv) >= 5 and argv[1] == "build":
        out = "."
        if "--out" in argv:
            out = argv[argv.index("--out") + 1]
        return cmd_build(argv[2].upper(), argv[3], argv[4], out)
    print(__doc__)
    sys.exit(1)


if __name__ == "__main__":
    main(sys.argv)
