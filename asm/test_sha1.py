import os
import random
import re
import struct
import sys
import unittest

from saturn import ASM, Saturn, from_nibbles, nibbles

sys.path.insert(0, os.path.join(os.path.dirname(ASM), "ref"))
from sha1_trace import IV, compress, final_block  # noqa: E402
from totp_ref import RFC_SECRET, midstates  # noqa: E402

CODE = 0x80000
WORK = 0x90000
MASK = 0xFFFFFFFF


def labels(name):
    """Label -> address from the SASM listing (source text starts at column 18)."""
    out = {}
    with open(os.path.join(ASM, name + ".l"), encoding="latin-1") as f:
        for line in f:
            m = re.match(r"^ +\d+ ([0-9A-F]{5}) ", line)
            src = line[18:]
            if m and src[:1].isalpha():
                out[src.split()[0]] = CODE + int(m.group(1), 16)
    return out


L = labels("sha1")
rng = random.Random(48)


def rand32():
    return rng.getrandbits(32)


def words(ws):
    return "".join(nibbles(w, 8) for w in ws)


def run_compress(state, block, breaks=()):
    s = Saturn().load_asm("sha1", CODE)
    s.poke(WORK, words(state) + words(struct.unpack(">16I", block)))
    for b in breaks:
        s.lines.append(f"break {b:X}")
    s.reg("D0", f"{WORK:X}").call(L["SHA1C"]).dump(WORK, 40).dump(WORK + 40, 640)
    r = s.run_script()
    assert r.status == "done", r.out[-500:]
    out = tuple(from_nibbles(r.dumps[0][8 * i:8 * i + 8]) for i in range(5))
    sched = [from_nibbles(r.dumps[1][8 * i:8 * i + 8]) for i in range(80)]
    return out, sched, r


class Helpers(unittest.TestCase):
    def call(self, label, a, c=0):
        s = Saturn().load_asm("sha1", CODE).reg("MODE", "HEX").reg("P", "7")
        s.reg("A", f"{a:X}").reg("C", f"{c:X}").call(L[label]).regs()
        r = s.run_script()
        self.assertEqual(r.status, "done")
        return r.reg("A"), r.reg("C")

    def test_xor(self):
        for _ in range(50):
            x, y = rand32(), rand32()
            a, c = self.call("XOR", x, y)
            self.assertEqual((a, c), (x, x ^ y))

    def test_rotl5(self):
        for x in [0, 1, MASK, 0x80000000, 0xF8000000] + [rand32() for _ in range(50)]:
            self.assertEqual(self.call("ROTL5", x)[0], ((x << 5) | (x >> 27)) & MASK, hex(x))

    def test_rotl30(self):
        for x in [0, 1, 2, 3, MASK, 0x80000000] + [rand32() for _ in range(50)]:
            self.assertEqual(self.call("ROTL30", x)[0], ((x << 30) | (x >> 2)) & MASK, hex(x))


class Compress(unittest.TestCase):
    def check(self, state, block):
        want_w = []
        want_rounds = []
        want = compress(state, block, lambda t, w, *abcde: (want_w.append(w), want_rounds.append(abcde)))
        got, sched, r = run_compress(state, block, breaks=[L["ROUNDE"]])
        self.assertEqual(sched, want_w, "message schedule")
        rounds = [tuple(int(b[f"R{i}"], 16) for i in range(5)) for b in r.breaks]
        for t, (g, w) in enumerate(zip(rounds, want_rounds)):
            self.assertEqual(g, w, f"state after round {t}")
        self.assertEqual(got, want)
        return r.steps

    def test_iv_zero_block(self):
        self.check(IV, bytes(64))

    def test_random_blocks(self):
        for _ in range(10):
            self.check(tuple(rand32() for _ in range(5)), bytes(rng.getrandbits(8) for _ in range(64)))

    def test_rfc_hmac_blocks(self):
        istate, ostate = midstates(RFC_SECRET)
        inner = compress(istate, final_block(struct.pack(">Q", 1), 72))
        steps = self.check(istate, final_block(struct.pack(">Q", 1), 72))
        self.check(ostate, final_block(struct.pack(">5I", *inner), 84))
        print(f"\n  one compression: {steps} Saturn instructions", file=sys.stderr)


if __name__ == "__main__":
    unittest.main()
