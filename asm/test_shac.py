import os
import random
import struct
import sys
import unittest

from saturn import ASM, Saturn, from_nibbles, hxs, nibbles

sys.path.insert(0, os.path.join(os.path.dirname(ASM), "ref"))
from sha1_trace import IV, compress  # noqa: E402
from totp_ref import RFC_SECRET, midstates  # noqa: E402

CODE = 0x80000
LIST, BLOCK, SCRATCH = 0x81000, 0x82000, 0x83000
STACK, IP, STOP = 0x84000, 0x85000, 0x87000
RPL_B, RPL_D = 0xABCDE, 0x00100
PROLOG_LIST, SEMI, PROLOG_STR = 0x02A74, 0x0312B, 0x02A2C

rng = random.Random(6238)


def string(nibs):
    return nibbles(PROLOG_STR, 5) + nibbles(5 + len(nibs), 5) + nibs


def native_block(block):
    """64 bytes -> the string body SHAC expects: 16 words, least significant nibble first."""
    return "".join(nibbles(w, 8) for w in struct.unpack(">16I", block))


def run_shac(state, block):
    lst = nibbles(PROLOG_LIST, 5) + "".join(hxs(w) for w in state) + nibbles(SEMI, 5)
    s = Saturn().load_asm("shac", CODE)
    s.poke(LIST, lst).poke(BLOCK, string(native_block(block))).poke(SCRATCH, string("0" * 720))
    s.rpl_env([SCRATCH, BLOCK, LIST], stack_at=STACK, ip_at=IP, stop=STOP)
    s.reg("B", f"{RPL_B:X}").reg("D", f"{RPL_D:X}")
    s.run(CODE + 10, STOP).regs().dump(LIST + 15, 26 * 5).dump(STACK + 10, 5)
    return s.run_script()


class Shac(unittest.TestCase):
    def check(self, state, block):
        r = run_shac(state, block)
        self.assertEqual(r.status, "done", r.out[-300:])
        got = tuple(from_nibbles(r.dumps[0][26 * i:26 * i + 8]) for i in range(5))
        self.assertEqual(got, compress(state, block))
        self.assertEqual(r.reg("D1"), STACK + 10, "two levels dropped")
        self.assertEqual(from_nibbles(r.dumps[1]), LIST, "the list is now level 1")
        self.assertEqual(r.reg("B") & 0xFFFFF, RPL_B)
        self.assertEqual(r.reg("D") & 0xFFFFF, RPL_D + 2)
        self.assertEqual(r.reg("D0"), IP + 5)
        self.assertEqual(r.reg("P"), 0)

    def test_random(self):
        for _ in range(10):
            self.check(tuple(rng.getrandbits(32) for _ in range(5)), bytes(rng.getrandbits(8) for _ in range(64)))

    def test_midstates_from_iv(self):
        key = RFC_SECRET.ljust(64, b"\0")
        istate, ostate = midstates(RFC_SECRET)
        self.check(IV, bytes(b ^ 0x36 for b in key))
        self.assertEqual(compress(IV, bytes(b ^ 0x36 for b in key)), istate)
        self.assertEqual(compress(IV, bytes(b ^ 0x5C for b in key)), ostate)


if __name__ == "__main__":
    unittest.main()
