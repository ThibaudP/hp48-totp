#!/usr/bin/env python3
"""Turn a %%HP translate-mode-3 source into what Emu48's Load Object needs.

Drops the %%HP header and @ comment lines, and replaces trigraphs (\\<< \\>> \\-> ...)
with HP 48 character codes. The emulator loads the result as a string; OBJ\\-> parses it.

Usage: hp2emu.py SOURCE.hp OUTPUT.txt
"""
import re
import sys

# HP 48 character codes for the trigraphs we use; extend as needed.
TRIGRAPHS = {
    "<<": 171, ">>": 187, "->": 141,
    "<=": 137, ">=": 138, "=/": 139, "Ga": 140, "pi": 135, "GS": 133, "oo": 159,
}


def convert(text):
    lines = text.splitlines()
    if lines and lines[0].startswith("%%HP"):
        lines = lines[1:]
    body = "\n".join(l for l in lines if not l.lstrip().startswith("@")) + "\n"

    def sub(m):
        tok = m.group(1)
        if tok.isdigit():
            return chr(int(tok))
        if tok in TRIGRAPHS:
            return chr(TRIGRAPHS[tok])
        raise ValueError(f"unknown trigraph \\{tok}")

    out = re.sub(r"\\(\d{3}|..)", sub, body)
    return out.encode("latin-1")


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    with open(argv[1], encoding="ascii") as f:
        data = convert(f.read())
    with open(argv[2], "wb") as f:
        f.write(data)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
