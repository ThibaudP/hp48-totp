"""End-to-end tests on an emulated HP 48GX (x48ng). Slow: one boot for the module."""
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
from hp48 import Emulator  # noqa: E402

hp = None


def setUpModule():
    global hp
    hp = Emulator().__enter__()


def tearDownModule():
    hp.__exit__(None, None, None)


class Toolchain(unittest.TestCase):
    def test_hello_code_object(self):
        hp.send(os.path.join(ROOT, "asm", "hello.bin"), "HELLO")
        hp.eval("HEX #41h HELLO")
        self.assertEqual(hp.result(), "# 42h")


class Hotp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, os.path.join(ROOT, "ref"))
        from make_hp_payload import hp_source
        from totp_ref import RFC_SECRET, midstates
        hp.send(os.path.join(ROOT, "asm", "hotp.bin"), "HOTP")
        hp.send_text(hp_source(*midstates(RFC_SECRET)), "KT")
        # Scratch string for HOTP: 360 characters, modified in place.
        hp.eval("\"\" 1 360 START \"0\" + NEXT 'WRK' STO 0")

    def code(self, counter_rpl):
        hp.eval(f"KT {counter_rpl} R\\->B WRK HOTP B\\->R 1000000 MOD")
        return int(float(hp.result()))

    def test_rfc4226_counter_1(self):
        self.assertEqual(self.code("1"), 287082)

    def test_rfc6238_t59_and_large_counter(self):
        # T = 1111111111 s -> counter 37037037 -> 050471 (RFC 6238, 6 digits)
        self.assertEqual(self.code("37037037"), 50471)


if __name__ == "__main__":
    unittest.main()
