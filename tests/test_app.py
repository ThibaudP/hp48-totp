"""The TOTP app on an emulated HP 48GX: programs, screen rendering, and the live app.

Needs `make asm app` first (make e2e does it).  Slow: one boot for the module.
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
from make_hp_payload import RFC_ACCOUNTS, accounts_source  # noqa: E402
from totp_ref import totp  # noqa: E402

hp = None
TZ = time.localtime().tm_gmtoff // 3600


def setUpModule():
    global hp
    hp = Emulator().__enter__()
    with open(os.path.join(ROOT, "out", "TOTP")) as f:
        hp.send_text(f.read(), "TOTP")
    hp.eval(f"TOTP {TZ} 'TZ' STO 0")  # enter the directory; later sends land in it
    hp.result()
    hp.send(os.path.join(ROOT, "asm", "hotp.bin"), "HOTP")
    hp.send_text(accounts_source(RFC_ACCOUNTS), "ACCTS")


def tearDownModule():
    hp.__exit__(None, None, None)


class Programs(unittest.TestCase):
    def test_unix_time_matches_host(self):
        hp.eval("UNIX")
        # Checks the formula (epoch, TZ, units), not the emulator's clock accuracy.
        self.assertLess(abs(int(float(hp.result())) - time.time()), 30)

    def test_code_for_each_account(self):
        for i, (name, key) in enumerate(RFC_ACCOUNTS, 1):
            hp.eval(f"{i} 1 CODE")
            self.assertEqual(hp.result(), f'"{totp(key, 59)}"', name)

    def test_fmt6_pads_zeros(self):
        hp.eval("50471 FMT6")
        self.assertEqual(hp.result(), '"050471"')


class Screen(unittest.TestCase):
    def test_screen_layout(self):
        hp.eval('"RFC 6238" "1/2 CEST" "287082" LBLS SCRN PICT STO 18 TICK PICT RCL')
        bitmap = hpgrob.from_grob(hp.result())
        print("\n" + hpgrob.ascii_art(bitmap), file=sys.stderr)
        self.assertEqual((len(bitmap[0]), len(bitmap)), (131, 64))
        self.assertEqual(hpgrob.read_code(bitmap), "287082")
        bar = bitmap[44]
        self.assertEqual(sum(bar[:100]), 18 * 3, "countdown bar width")


class LiveApp(unittest.TestCase):
    def screen_code(self):
        return hpgrob.read_code(hpgrob.from_tui(hp.screen()))

    def wait_code(self, key, tz_shift=0, timeout=15):
        """Poll the emulator screen until the app shows the right code for `key`.

        The emulated clock drifts while the app runs, so the calculator's time is
        taken from the screen: the bar is 3 px per second left, which pins down
        unix % 30; any such time within 40 s of the host clock is accepted."""
        end = time.time() + timeout
        got = want = None
        while time.time() < end:
            bitmap = hpgrob.from_tui(hp.screen())
            got, left = hpgrob.read_code(bitmap), sum(bitmap[44][:100]) // 3
            now = int(time.time())
            want = {totp(key, t + tz_shift) for t in range(now - 40, now + 41) if 30 - t % 30 == left}
            if got in want:
                return got
            time.sleep(0.5)
        self.fail(f"screen shows {got}, expected one of {sorted(want)}\n{hp.screen()}")

    def test_navigation_and_tz(self):
        (n1, k1), (n2, k2) = RFC_ACCOUNTS
        hp.leave_server()
        try:
            x48("type", "OTP")
            x48("keys", "Enter")
            self.wait_code(k1)
            bar = lambda: sum(hpgrob.from_tui(hp.screen())[44][:100])
            w1 = bar()
            time.sleep(2.5)
            self.assertNotEqual(bar(), w1, "countdown bar should move every second")
            x48("keys", "b")  # NEXT
            self.wait_code(k2)
            x48("keys", "Left")  # back to account 1 with the arrow
            self.wait_code(k1)
            x48("keys", "d")  # TZ toggle: the clock is now read one hour off
            self.wait_code(k1, tz_shift=3600 if TZ == 2 else -3600)
            x48("keys", "d")
            x48("keys", "f")  # QUIT
        finally:
            time.sleep(1)
            hp.server()


if __name__ == "__main__":
    unittest.main()
