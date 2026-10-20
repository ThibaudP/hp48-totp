#!/usr/bin/env python3
"""Write ACCTS, the account list for the calculator app, ready to send with Kermit.

ACCTS is { { "name" { istate0..4 ostate0..4 } } ... }: per account, the HMAC
midstates as 10 binary integers.  They are as sensitive as the secrets.

Usage:
  make_hp_payload.py                  prompt for accounts (name, then base32 secret, not
                                      echoed); an empty name finishes
  make_hp_payload.py --import FILE    accounts from otpauth:// URIs, one per line (e.g. an
                                      Ente Auth or Aegis plain-text export); asks which to keep
  make_hp_payload.py --rfc            test accounts built from the RFC secret
"""
import argparse
import getpass
import os
import sys
import time
import urllib.parse

from totp_ref import RFC_SECRET, decode_b32, hotp_midstate, midstates

HEADER = "%%HP: T(3)A(D)F(.);"
NAME_MAX = 12  # fits left of "1/9 CEST" in the app's header line
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


def parse_otpauth(uri):
    """(name, key bytes) from an otpauth://totp/ URI, or (name, reason) if the
    calculator can't use it (it only does SHA-1, 6 digits, 30 s)."""
    u = urllib.parse.urlparse(uri.strip())
    q = {k.lower(): v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
    label = urllib.parse.unquote(u.path.lstrip("/"))
    issuer = q.get("issuer") or (label.split(":", 1)[0] if ":" in label else "")
    account = label.split(":", 1)[-1].strip()
    name = issuer or account or "?"
    if u.scheme != "otpauth" or u.netloc.lower() != "totp":
        return name, f"not TOTP ({u.netloc})"
    if q.get("algorithm", "SHA1").upper() != "SHA1":
        return name, f"algorithm {q['algorithm']}"
    if q.get("digits", "6") != "6" or q.get("period", "30") != "30":
        return name, f"{q.get('digits', '6')} digits / {q.get('period', '30')} s"
    if "secret" not in q:
        return name, "no secret"
    return name, decode_b32(q["secret"])


def import_accounts(path):
    with open(path, encoding="utf-8") as f:
        uris = [l for l in f if l.strip().startswith("otpauth://")]
    usable = []
    for uri in uris:
        name, key = parse_otpauth(uri)
        if isinstance(key, str):
            print(f"  skipped {name}: {key}")
        else:
            usable.append((name, key))
    for i, (name, _) in enumerate(usable, 1):
        print(f"  {i:2}. {name}")
    pick = input("Accounts to put on the calculator (e.g. 1,3,4; empty = all): ").strip()
    if pick:
        usable = [usable[int(n) - 1] for n in pick.replace(" ", "").split(",")]
    accounts = []
    for name, key in usable:
        short = input(f"Name for {name} [{name[:NAME_MAX]}]: ").strip() or name[:NAME_MAX]
        accounts.append((short[:NAME_MAX].replace('"', "'"), key))
    return accounts


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
    p.add_argument("--import", dest="import_file", metavar="FILE", help="otpauth:// URIs, one per line")
    p.add_argument("--out-dir", default=os.path.join(os.path.dirname(__file__), "..", "out"))
    args = p.parse_args(argv)

    if args.rfc:
        accounts = RFC_ACCOUNTS
    elif args.import_file:
        accounts = import_accounts(args.import_file)
    else:
        accounts = prompt_accounts()
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
