import hashlib
import hmac
import os
import struct
import unittest

from make_hp_payload import hp_source
from sha1_trace import sha1
from totp_ref import RFC4226, RFC6238, RFC_SECRET, decode_b32, hotp, hotp_midstate, midstates, totp


class Sha1(unittest.TestCase):
    def test_matches_hashlib_across_padding_boundaries(self):
        for n in list(range(0, 130)) + [1000]:
            msg = os.urandom(n)
            self.assertEqual(sha1(msg), hashlib.sha1(msg).digest(), n)


class Rfc(unittest.TestCase):
    def test_rfc4226(self):
        ist, ost = midstates(RFC_SECRET)
        for counter, want in enumerate(RFC4226):
            self.assertEqual(hotp(RFC_SECRET, counter), want)
            self.assertEqual(hotp_midstate(ist, ost, counter), want)

    def test_rfc6238(self):
        ist, ost = midstates(RFC_SECRET)
        for t, want in RFC6238:
            self.assertEqual(totp(RFC_SECRET, t, digits=8), want)
            self.assertEqual(hotp_midstate(ist, ost, t // 30, digits=8), want)
        self.assertEqual(totp(RFC_SECRET, 59), "287082")


class Midstate(unittest.TestCase):
    def test_matches_hmac_for_random_keys_and_counters(self):
        # Includes keys longer than a block, which HMAC hashes first.
        for n in (1, 10, 20, 32, 63, 64, 65, 100):
            key = os.urandom(n)
            ist, ost = midstates(key)
            for counter in (0, 1, 2**31, 2**63 - 1, struct.unpack(">Q", os.urandom(8))[0]):
                h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
                off = h[19] & 0x0F
                want = f"{(int.from_bytes(h[off:off + 4], 'big') & 0x7FFFFFFF) % 10**6:06d}"
                self.assertEqual(hotp_midstate(ist, ost, counter), want, (n, counter))


class Base32(unittest.TestCase):
    def test_qr_style_secret(self):
        # RFC secret in base32, lowercased, spaced and unpadded as apps show it.
        self.assertEqual(decode_b32("gezd gnbv gy3t qojq gezd gnbv gy3t qojq"), RFC_SECRET)


class Payload(unittest.TestCase):
    def test_format(self):
        src = hp_source(*midstates(RFC_SECRET))
        lines = src.splitlines()
        self.assertEqual(lines[0], "%%HP: T(3)A(D)F(.);")
        self.assertTrue(lines[1].startswith("{ #") and lines[1].endswith("h }"))
        self.assertEqual(lines[1].count("#"), 10)


class Import(unittest.TestCase):
    def test_otpauth_uris(self):
        from make_hp_payload import parse_otpauth
        b32 = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
        self.assertEqual(parse_otpauth(f"otpauth://totp/GitHub:me?secret={b32}&issuer=GitHub"), ("GitHub", RFC_SECRET))
        self.assertEqual(parse_otpauth(f"otpauth://totp/me%40x.com?secret={b32.lower()}"), ("me@x.com", RFC_SECRET))
        self.assertEqual(parse_otpauth(f"otpauth://totp/A:b?secret={b32}&algorithm=SHA256")[1], "algorithm SHA256")
        self.assertEqual(parse_otpauth(f"otpauth://totp/A:b?secret={b32}&digits=8")[1], "8 digits / 30 s")
        self.assertEqual(parse_otpauth(f"otpauth://hotp/A:b?secret={b32}")[1], "not TOTP (hotp)")


if __name__ == "__main__":
    unittest.main()
