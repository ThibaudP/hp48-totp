#!/usr/bin/env python3
"""Write ACCTS, the account list for the calculator app, ready to send with Kermit.

ACCTS is { { "name" { istate0..4 ostate0..4 } } ... }: per account, the HMAC
midstates as 10 binary integers.  They are as sensitive as the secrets.

Usage:
  make_hp_payload.py          prompt for accounts (name, then base32 secret, not echoed);
                              an empty name finishes
  make_hp_payload.py --rfc    test accounts built from the RFC secret
"""
import argparse
import getpass
import os
import sys
import time

from totp_ref import RFC_SECRET, decode_b32, hotp_midstate, midstates

HEADER = "%%HP: T(3)A(D)F(.);"
RFC_ACCOUNTS = [("RFC 6238", RFC_SECRET), ("RFC x2", RFC_SECRET * 2)]


def keys_source(istate, ostate):
    return "{ " + " ".join(f"#{w:08X}h" for w in istate + ostate) + " }"


def hp_source(istate, ostate, header=True):
    """A single key list (used by the HOTP tests)."""
    return (f"{HEADER}\n" if header else "") + keys_source(istate, ostate) + "\n"


def accounts_source(accounts):
    """accounts: [(name, key bytes)]"""
    lines = [HEADER, "{"]
    for name, key in accounts:
        if '"' in name:
            raise ValueError("account names cannot contain double quotes")
        lines.append(f'  {{ "{name}" {keys_source(*midstates(key))} }}')
    lines.append("}")
    return "\n".join(lines) + "\n"


def prompt_accounts():
    accounts = []
    while True:
        name = input("Account name (empty to finish): ").strip()
        if not name:
            return accounts
        key = decode_b32(getpass.getpass(f"Base32 secret for {name}: "))
        now = int(time.time())
        print(f"  current code: {hotp_midstate(*midstates(key), now // 30)} ({30 - now % 30} s left), "
              "compare with your authenticator app")
        accounts.append((name, key))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rfc", action="store_true", help="test accounts from the RFC secret")
    p.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "..", "out"))
    args = p.parse_args(argv)

    accounts = RFC_ACCOUNTS if args.rfc else prompt_accounts()
    if not accounts:
        print("no accounts, nothing written", file=sys.stderr)
        return 1
    os.makedirs(args.out_dir, exist_ok=True)
    path = os.path.join(args.out_dir, "ACCTS")
    # 0600: the midstates are as good as the secrets.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", newline="\n") as f:
        f.write(accounts_source(accounts))
    print(f"wrote {os.path.normpath(path)} ({len(accounts)} accounts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
