#!/usr/bin/env python3
"""Build dist/TOTP: the whole app as one binary directory object, for a one-file install.

Installs the app on a headless emulated 48GX (the text directory, HOTP and SHAC
machine code, an empty account list), then fetches the directory back in binary
transfer mode.  Users send that single file to the calculator, enter TOTP, run OTP
and add their accounts with ADD.  Needs `make asm app` and the full toolchain.
"""
import os
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
from hp48 import Emulator, x48  # noqa: E402

OUT = os.path.join(ROOT, "dist", "TOTP")


def main():
    with Emulator() as hp:
        with open(os.path.join(ROOT, "out", "TOTP")) as f:
            hp.send_text(f.read(), "TOTP")
        hp.eval("TOTP 0")  # enter the directory: the next transfers land in it
        hp.result()
        hp.send(os.path.join(ROOT, "asm", "hotp.bin"), "HOTP")
        hp.send(os.path.join(ROOT, "asm", "shac.bin"), "SHAC")
        hp.send_text("{ }", "ACCTS")
        # eval() leaves RUN and RSLT in the current directory: go back HOME by
        # hand, then clean TOTP from a RUN that lives in HOME.
        hp.leave_server()
        x48("type", "HOME")
        x48("keys", "Enter")
        hp.server()
        hp.eval("TOTP { RUN RSLT } PURGE VARS HOME")
        names = hp.result()
        hp.eval("-35 SF 0")  # binary transfers
        hp.result()
        data = hp.kermit_call(hp.kermit.get, "TOTP")
    if not data.startswith(b"HPHP48-"):
        sys.exit(f"expected a binary object, got {data[:40]!r}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        f.write(data)
    print(f"wrote {os.path.relpath(OUT, ROOT)} ({len(data)} bytes): {' '.join(names.strip('{} ').split())}")


if __name__ == "__main__":
    main()
