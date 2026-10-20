#!/usr/bin/env python3
"""Build out/TOTP: the app as one HP 48 directory in text form, ready for Kermit.

Each rpl/NAME.hp becomes variable NAME; '@' comment lines are dropped.
Also adds TZ (default offset) and DIGS (the big digit GROBs, 0..9).
HOTP (machine code) and ACCTS (secrets) are sent separately into the directory.
"""
import glob
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
from hpgrob import digit_bitmap, to_grob  # noqa: E402

HEADER = "%%HP: T(3)A(D)F(.);"
DEFAULT_TZ = 2


def strip(text):
    return "\n".join(l for l in text.splitlines() if not l.lstrip().startswith(("@", "%%HP"))).strip()


def build():
    parts = [HEADER, "DIR"]
    # OTP first: it's the only variable the user needs, so it gets the first soft key.
    paths = sorted(glob.glob(os.path.join(ROOT, "rpl", "*.hp")), key=lambda p: (not p.endswith("OTP.hp"), p))
    for path in paths:
        name = os.path.basename(path)[:-3]
        with open(path) as f:
            parts += [f"{name}", strip(f.read())]
    parts += [f"TZ {DEFAULT_TZ}"]
    parts += ["DIGS {"] + [to_grob(digit_bitmap(str(d))) for d in range(10)] + ["}"]
    parts += ["END"]
    return "\n".join(parts) + "\n"


def main():
    out = os.path.join(ROOT, "out", "TOTP")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", newline="\n") as f:
        f.write(build())
    print(f"wrote {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
