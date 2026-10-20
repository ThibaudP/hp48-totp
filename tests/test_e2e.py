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


class Clock(unittest.TestCase):
    def test_unix_time_matches_host(self):
        with open(os.path.join(ROOT, "rpl", "CLOCK.hp")) as f:
            hp.send_text(f.read(), "CLK")
        # The emulator's clock follows the host's local time, so TZ is the host's offset.
        tz = time.localtime().tm_gmtoff // 3600
        hp.eval(f"CLK {tz} 'TZ' STO UNIX")
        unix = int(float(hp.result()))
        self.assertLess(abs(unix - time.time()), 10)


if __name__ == "__main__":
    unittest.main()
