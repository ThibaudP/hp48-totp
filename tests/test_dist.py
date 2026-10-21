"""The one-file install: dist/TOTP alone on a fresh emulated 48GX, then ADD an account.

Needs dist/TOTP (make dist).  Slow: one boot.
"""
import os
import sys
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "ref"))
import hpgrob  # noqa: E402
from hp48 import Emulator, x48  # noqa: E402
from totp_ref import decode_b32, totp  # noqa: E402

SECRET = "JBSWY3DPEHPK3PXP"


class OneFileInstall(unittest.TestCase):
    def test_install_and_add(self):
        tz = time.localtime().tm_gmtoff // 3600
        with Emulator() as hp:
            hp.eval("MEM")
            free = float(hp.result())
            hp.send(os.path.join(ROOT, "dist", "TOTP"), "TOTP")
            hp.eval(f"MEM TOTP {tz} 'TZ' STO ACCTS SIZE 2 \\->LIST")
            mem, n = hp.result().strip("{} ").split()
            print(f"\n  installed: {free - float(mem):.0f} bytes", file=sys.stderr)
            self.assertEqual(n, "0", "ships without accounts")
            hp.leave_server()
            x48("type", "OTP")
            x48("keys", "Enter")
            time.sleep(8)
            x48("keys", "a")  # ADD
            time.sleep(3)
            x48("keys", "g", "h", "Enter")
            time.sleep(2)
            x48("keys", *SECRET.lower(), "Enter")
            key = decode_b32(SECRET)
            end = time.time() + 60
            while time.time() < end:
                bm = hpgrob.from_tui(hp.screen())
                got, left = hpgrob.read_code(bm), sum(bm[51][:100]) // 3
                now = int(time.time())
                if got in {totp(key, t) for t in range(now - 40, now + 41) if 30 - t % 30 == left}:
                    break
                time.sleep(1)
            else:
                self.fail(f"account view shows {got}\n{hp.screen()}")
            x48("keys", "f")  # QUIT
            time.sleep(2)
            hp.server()


if __name__ == "__main__":
    unittest.main()
