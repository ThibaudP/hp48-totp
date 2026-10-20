import hashlib
import hmac
import os
import random
import struct
import sys
import unittest

from saturn import ASM, Saturn, from_nibbles, hxs, nibbles

sys.path.insert(0, os.path.join(os.path.dirname(ASM), "ref"))
from totp_ref import RFC_SECRET, midstates  # noqa: E402

CODE = 0x80000
LIST, COUNTER, SCRATCH = 0x81000, 0x82000, 0x83000
STACK, IP, STOP = 0x84000, 0x85000, 0x87000
RPL_B, RPL_D = 0xABCDE, 0x00100

PROLOG_LIST, SEMI, PROLOG_STR = 0x02A74, 0x0312B, 0x02A2C
SCRATCH_CHARS = 360

rng = random.Random(4226)


def truncated(key, counter):
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = h[19] & 0x0F
    return int.from_bytes(h[off:off + 4], "big") & 0x7FFFFFFF


def run_hotp(key, counter):
    istate, ostate = midstates(key)
    lst = nibbles(PROLOG_LIST, 5) + "".join(hxs(w) for w in istate + ostate) + nibbles(SEMI, 5)
    scratch = nibbles(PROLOG_STR, 5) + nibbles(5 + 2 * SCRATCH_CHARS, 5) + "0" * (2 * SCRATCH_CHARS)
    s = Saturn().load_asm("hotp", CODE)
    s.poke(LIST, lst).poke(COUNTER, hxs(counter)).poke(SCRATCH, scratch)
    s.rpl_env([SCRATCH, COUNTER, LIST], stack_at=STACK, ip_at=IP, stop=STOP)
    s.reg("B", f"{RPL_B:X}").reg("D", f"{RPL_D:X}")
    s.run(CODE + 10, STOP).regs().dump(COUNTER + 10, 16).dump(STACK + 10, 5).dump(LIST, 5)
    r = s.run_script()
    return r


class Hotp(unittest.TestCase):
    def check(self, key, counter):
        r = run_hotp(key, counter)
        self.assertEqual(r.status, "done", r.out[-300:])
        self.assertEqual(from_nibbles(r.dumps[0]), truncated(key, counter), f"counter {counter}")
        # RPL state: two levels dropped, counter now level 1, registers restored.
        self.assertEqual(r.reg("D1") , STACK + 10)
        self.assertEqual(from_nibbles(r.dumps[1]), COUNTER)
        self.assertEqual(r.reg("B") & 0xFFFFF, RPL_B)
        self.assertEqual(r.reg("D") & 0xFFFFF, RPL_D + 2)
        self.assertEqual(r.reg("D0"), IP + 5)
        self.assertEqual(r.reg("P"), 0)
        self.assertEqual(r.dumps[2], nibbles(PROLOG_LIST, 5), "list untouched")
        return r.steps

    def test_rfc4226_counters(self):
        for c in range(10):
            steps = self.check(RFC_SECRET, c)
        print(f"\n  one HOTP: {steps} Saturn instructions", file=sys.stderr)

    def test_random_keys_and_counters(self):
        for n in (1, 10, 20, 32, 64, 65, 100):
            key = os.urandom(n)
            for c in (0, 1, 2**31, 2**32 + 7, 2**63 - 1, rng.getrandbits(64)):
                self.check(key, c)


if __name__ == "__main__":
    unittest.main()
