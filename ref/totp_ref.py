#!/usr/bin/env python3
"""HOTP/TOTP reference: the standard HMAC path and the two-compression midstate path the HP will run.

Usage:
  totp_ref.py test     check the RFC 4226 / RFC 6238 vectors on both paths
  totp_ref.py now      prompt for a base32 secret and print the current code
"""
import base64
import getpass
import hashlib
import hmac
import struct
import sys
import time

from sha1_trace import IV, compress, final_block, sha1, words_to_bytes

RFC_SECRET = b"12345678901234567890"

# RFC 4226 appendix D: counters 0..9, 6 digits.
RFC4226 = ["755224", "287082", "359152", "969429", "338314",
           "254676", "287922", "162583", "399871", "520489"]

# RFC 6238 appendix B, SHA-1 rows: (unix time, 8-digit code).
RFC6238 = [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"),
           (1234567890, "89005924"), (2000000000, "69279037"), (20000000000, "65353130")]


def decode_b32(secret):
    """Accept secrets as authenticator QR codes give them: any case, spaces, no padding."""
    s = secret.upper().replace(" ", "").replace("-", "")
    return base64.b32decode(s + "=" * (-len(s) % 8))


def truncate(h, digits):
    offset = h[19] & 0x0F
    return (int.from_bytes(h[offset:offset + 4], "big") & 0x7FFFFFFF) % 10 ** digits


def hotp(key, counter, digits=6):
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    return f"{truncate(h, digits):0{digits}d}"


def totp(key, unix_time, step=30, digits=6):
    return hotp(key, unix_time // step, digits)


def midstates(key):
    """State after the first compression of HMAC's inner and outer hash. As sensitive as the key."""
    if len(key) > 64:
        key = sha1(key)
    key = key.ljust(64, b"\x00")
    istate = compress(IV, bytes(x ^ 0x36 for x in key))
    ostate = compress(IV, bytes(x ^ 0x5C for x in key))
    return istate, ostate


def hotp_midstate(istate, ostate, counter, digits=6):
    """What the calculator computes: two compressions, 72 and 84 bytes declared in the padding."""
    inner = compress(istate, final_block(struct.pack(">Q", counter), 72))
    outer = compress(ostate, final_block(words_to_bytes(inner), 84))
    return f"{truncate(words_to_bytes(outer), digits):0{digits}d}"


def run_tests():
    ist, ost = midstates(RFC_SECRET)
    failures = 0
    for counter, want in enumerate(RFC4226):
        for path, got in (("hmac", hotp(RFC_SECRET, counter)), ("midstate", hotp_midstate(ist, ost, counter))):
            ok = got == want
            failures += not ok
            print(f"{'ok  ' if ok else 'FAIL'} HOTP  counter={counter:<11} {path:<8} {got} (want {want})")
    for t, want in RFC6238:
        for path, got in (("hmac", totp(RFC_SECRET, t, digits=8)),
                          ("midstate", hotp_midstate(ist, ost, t // 30, digits=8))):
            ok = got == want
            failures += not ok
            print(f"{'ok  ' if ok else 'FAIL'} TOTP  T={t:<11} {path:<8} {got} (want {want})")
    print("all vectors pass" if not failures else f"{failures} failure(s)")
    return 1 if failures else 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["test"]:
        return run_tests()
    if argv == ["now"]:
        key = decode_b32(getpass.getpass("Base32 secret: "))
        now = int(time.time())
        print(f"{totp(key, now)}  ({30 - now % 30} s left)")
        return 0
    print(__doc__.strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
