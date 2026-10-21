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
from totp_ref import RFC_SECRET, decode_b32, midstates, totp  # noqa: E402

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
    hp.send(os.path.join(ROOT, "asm", "shac.bin"), "SHAC")
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

    def test_base32_decode(self):
        for b32 in ("GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ", "gezd gnbv gy3t qojq gezd gnbv gy3t qojq"):
            hp.eval(f'"{b32}" B32D')
            self.assertEqual(hp.result(), f'"{RFC_SECRET.decode()}"', b32)

    def test_midstates_on_calculator(self):
        t0 = time.time()
        hp.eval('"GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ" B32D MIDS HEX')
        print(f"\n  B32D + MIDS round trip: {time.time() - t0:.1f} s", file=sys.stderr)
        words = [int(w, 16) for w in __import__("re").findall(r"#\s*([0-9A-F]+)h", hp.result())]
        istate, ostate = midstates(RFC_SECRET)
        self.assertEqual(words, list(istate + ostate))
        hp.eval("DEC 0")
        hp.result()

    def test_fmt6_pads_zeros(self):
        hp.eval("50471 FMT6")
        self.assertEqual(hp.result(), '"050471"')


class Screen(unittest.TestCase):
    def test_account_screen_layout(self):
        labels = '{ "BACK" "PREV" "NEXT" "TZ" "" "QUIT" } LBLS'
        hp.eval(f'#131d #64d BLANK PICT STO "RFC 6238" "1/2 CEST" "110349" "287082" "902115" {labels} DDRAW 18 0 DTICK PICT RCL')
        bitmap = hpgrob.from_grob(hp.result())
        print("\n" + hpgrob.ascii_art(bitmap), file=sys.stderr)
        self.assertEqual((len(bitmap[0]), len(bitmap)), (131, 64))
        self.assertEqual(hpgrob.read_code(bitmap), "287082")
        self.assertEqual(sum(bitmap[51][:100]), 18 * 3, "countdown bar width")


ADD_NAME, ADD_SECRET = "TEST", "JBSWY3DPEHPK3PXP"


class LiveApp(unittest.TestCase):
    """One session through the whole app, driven by keys, checked on the screen."""

    @classmethod
    def setUpClass(cls):
        hp.eval('"0123456789" 2 \\->GROB')
        cls.digits = hpgrob.glyphs(hpgrob.from_grob(hp.result()))

    def screen(self):
        return hpgrob.from_tui(hp.screen())

    def poll(self, check, what, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            got = check(self.screen(), int(time.time()))
            if got is True:
                return
            time.sleep(0.5)
        self.fail(f"{what}: last saw {got}\n{hp.screen()}")

    def account_view(self, key, tz_shift=0):
        """The account view shows key's code; the calculator's time is pinned by the
        countdown bar (3 px per second left, row 51), since the emulated clock drifts."""
        def check(bm, now):
            got, left = hpgrob.read_code(bm), sum(bm[51][:100]) // 3
            want = {totp(key, t + tz_shift) for t in range(now - 40, now + 41) if 30 - t % 30 == left}
            return True if got in want else (got, sorted(want))
        self.poll(check, "account view")

    def home_view(self, keys, selected):
        """Each visible row shows its account's code (within 40 s of the host clock)."""
        def check(bm, now):
            rows = hpgrob.read_home(bm, self.digits)
            for k, key in enumerate(keys):
                code, sel = rows[k]
                if code not in {totp(key, t) for t in range(now - 40, now + 41, 10)} or sel != (k == selected):
                    return rows
            return True
        self.poll(check, "home view")

    def test_session(self):
        (_, k1), (_, k2) = RFC_ACCOUNTS
        k3 = decode_b32(ADD_SECRET)
        hp.leave_server()
        try:
            x48("type", "OTP")
            x48("keys", "Enter")
            self.home_view([k1, k2], selected=0)
            x48("keys", "Down")
            self.home_view([k1, k2], selected=1)
            x48("keys", "Enter")  # open account 2
            self.account_view(k2)
            x48("keys", "b")  # PREV
            self.account_view(k1)
            x48("keys", "d")  # TZ: the clock is now read one hour off
            self.account_view(k1, tz_shift=3600 if TZ == 2 else -3600)
            x48("keys", "d")
            x48("keys", "Left")  # back home
            self.home_view([k1, k2], selected=0)

            x48("keys", "a")  # ADD
            time.sleep(3)
            x48("keys", *ADD_NAME.lower(), "Enter")
            time.sleep(2)
            x48("keys", *ADD_SECRET.lower(), "Enter")
            self.account_view(k3)  # ADD opens the new account
            x48("keys", "a")  # BACK
            self.home_view([k1, k2, k3], selected=2)

            x48("keys", "d")  # MOVE: the new account goes up one place
            x48("keys", "Up", "Enter")
            self.home_view([k1, k3, k2], selected=1)

            x48("keys", "c")  # DEL the selected (new) account
            time.sleep(2)
            x48("keys", "Down", "Enter")  # "Yes"
            self.home_view([k1, k2], selected=1)
            x48("keys", "f")  # QUIT
        finally:
            time.sleep(2)
            hp.server()
        hp.eval("ACCTS SIZE")
        self.assertEqual(hp.result(), "2")


if __name__ == "__main__":
    unittest.main()
