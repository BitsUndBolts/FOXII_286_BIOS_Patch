#!/usr/bin/env python3
"""Write bubios286.py for the retro knowledge base: our bytes only.

    python3 py/kb_patch.py OUT.py

The knowledge base never hosts BIOS images. bubios286.py holds, for each
ROM, only the bytes where it differs from AMI's 06/13/90 image (runs of
differing bytes; runs of zeros as fill records). The reader's own dump
supplies everything else; the script checks the dump's SHA-256 before and
the result's SHA-256 after.
"""
import hashlib, os, sys, textwrap
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIG = open(os.path.join(ROOT, 'base', 'FOXII_0613_ORIGINAL.BIN'), 'rb').read()
ROMS = [('BUBIOS286', 'binary/FOXII_STEP6B.BIN', 'BUBios/286 0.7.4: ECHS (8.4 GB), IDE auto-detect, POST screen, setup with boot order, tools, boot key, HT12UMB.SYS at F000:6000'),
        ('ECHS', 'binary/FOXII_ECHS.BIN', 'ECHS large-disk patch only (Step 1): drives up to 8.4 GB, everything else as AMI made it')]

def records(new):
    out, i = [], 0
    while i < 65536:
        if ORIG[i] == new[i]:
            i += 1; continue
        j = i
        while j < 65536 and ORIG[j] != new[j]: j += 1
        k = i                                  # split the run into zero fills and data
        while k < j:
            z = k
            while z < j and new[z] == 0: z += 1
            if z - k >= 16:
                out.append((k, None, z - k)); k = z; continue
            d = k
            while d < j and not (new[d] == 0 and d + 16 <= j and not any(new[d:d + 16])): d += 1
            out.append((k, new[k:d].hex(), None)); k = d
        i = j
    return out

def main(path):
    lines = []
    for name, f, what in ROMS:
        new = open(os.path.join(ROOT, f), 'rb').read()
        recs = records(new)
        img = bytearray(ORIG)                  # prove the records rebuild it
        for a, h, z in recs:
            b = bytes(z) if h is None else bytes.fromhex(h)
            img[a:a + len(b)] = b
        assert bytes(img) == new
        lines.append("    %r: dict(\n        what=%r,\n        result_sha256=%r,\n        records=[" %
                     (name, what, hashlib.sha256(new).hexdigest()))
        for a, h, z in recs:
            if h is None:
                lines.append("            (0x%04X, None, %d)," % (a, z))
            else:
                parts = textwrap.wrap(h, 96)
                lines.append("            (0x%04X, %s, None)," % (a, "\n                     ".join('"%s"' % p for p in parts)))
        lines.append("        ]),")
    tmpl = open(os.path.join(ROOT, 'py', 'kb_patch_template.py')).read()
    open(path, 'w').write(tmpl.replace('# @@PATCHES@@', '\n'.join(lines)))
    print('wrote', path)

if __name__ == '__main__':
    main(sys.argv[1])
