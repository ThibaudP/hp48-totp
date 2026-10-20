#!/usr/bin/env python3
"""Write an HP 48 text file holding one account's HMAC midstates, ready to send with Kermit.

The file contains a list of 10 binary integers: istate (5 words) then ostate (5 words).
Kermit names the variable after the file, so --name is the variable name on the calculator.

Usage:
  make_hp_payload.py --name K1          prompt for a base32 secret (not echoed)
  make_hp_payload.py --name KT --rfc    use the RFC test secret instead
"""
import argparse
import getpass
import os
import sys
import time

from totp_ref import RFC_SECRET, decode_b32, hotp_midstate, midstates

HEADER = "%%HP: T(3)A(D)F(.);"


def hp_source(istate, ostate, header=True):
    words = " ".join(f"#{w:08X}h" for w in istate + ostate)
    return (f"{HEADER}\n" if header else "") + f"{{ {words} }}\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--name", required=True, help="variable name on the calculator (file name)")
    p.add_argument("--rfc", action="store_true", help="use the RFC test secret 12345678901234567890")
    p.add_argument("--emu", action="store_true",
                   help="write NAME.txt without the %%%%HP header: Emu48's Load Object puts it on the stack "
                        "as a string, then STR→ 'NAME' STO")
    p.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "..", "out"))
    args = p.parse_args(argv)

    key = RFC_SECRET if args.rfc else decode_b32(getpass.getpass("Base32 secret: "))
    istate, ostate = midstates(key)

    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, args.name + (".txt" if args.emu else ""))
    # 0600: the midstates are as good as the secret.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", newline="\n") as f:
        f.write(hp_source(istate, ostate, header=not args.emu))

    now = int(time.time())
    print(f"wrote {os.path.normpath(path)}")
    print(f"current code from midstates: {hotp_midstate(istate, ostate, now // 30)} "
          f"({30 - now % 30} s left), compare with your authenticator app")
    return 0


if __name__ == "__main__":
    sys.exit(main())
