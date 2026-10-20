import unittest

from saturn import Saturn, from_nibbles, hxs

CODE = 0x80000
BODY = CODE + 10  # past the Code prolog and length field


class Hello(unittest.TestCase):
    def test_increments_binary_integer_in_level_1(self):
        s = Saturn().load_asm("hello", CODE).poke(0x81000, hxs(0x41))
        stop = s.rpl_env([0x81000])
        r = s.run(BODY, stop).dump(0x8100A, 16).dump(0x81005, 5).regs().run_script()
        self.assertEqual(r.status, "done")
        self.assertEqual(from_nibbles(r.dumps[0]), 0x42)
        self.assertEqual(from_nibbles(r.dumps[1]), 0x15, "length field must be untouched")
        self.assertEqual(r.reg("D1"), 0x82000, "stack pointer restored")


if __name__ == "__main__":
    unittest.main()
