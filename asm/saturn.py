"""Python driver for tools/satrun: build a script, run it, parse the results.

Memory helpers follow the Saturn's layout: values are stored least significant
nibble first, so a 5-nibble address #81000 is written "00018".
"""
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SATRUN = os.path.join(ROOT, "tools", "satrun", "satrun")
ASM = os.path.join(ROOT, "asm")

PROLOG_HXS = 0x02A4E  # user binary integer
PROLOG_CODE = 0x02DCC


def nibbles(value, n):
    """value as n nibbles in memory order (least significant first)."""
    return "".join(f"{(value >> (4 * i)) & 0xF:X}" for i in range(n))


def from_nibbles(s):
    return sum(int(c, 16) << (4 * i) for i, c in enumerate(s))


def hxs(value):
    """A user binary integer object: prolog, length 00015, 16-nibble value."""
    return nibbles(PROLOG_HXS, 5) + nibbles(0x15, 5) + nibbles(value, 16)


class Result:
    def __init__(self, out):
        self.out = out
        self.dumps = re.findall(r"^([0-9A-F]+)$", out, re.M)
        self.regs = [dict(re.findall(r"(\w+)=(\w+)", l)) for l in out.splitlines() if l.startswith(("A=", "brk "))]
        self.breaks = [dict(re.findall(r"(\w+)=(\w+)", l), at=l.split()[1]) for l in out.splitlines() if l.startswith("brk ")]
        m = re.search(r"^(done|timeout|illegal) (\w+)$", out, re.M)
        self.status, self.steps = (m.group(1), int(m.group(2), 16 if m.group(1) == "illegal" else 10)) if m else (None, None)

    def reg(self, name, i=-1):
        return int(self.regs[i][name], 16)


class Saturn:
    def __init__(self):
        self.lines = []

    def __getattr__(self, cmd):
        # s.poke(0x81000, "...") -> "poke 81000 ...", ints formatted as hex
        def add(*args):
            self.lines.append(" ".join([cmd] + [f"{a:X}" if isinstance(a, int) else str(a) for a in args]))
            return self
        return add

    def load_asm(self, name, addr):
        return self.load(os.path.join(ASM, name + ".bin"), addr)

    def run_script(self):
        p = subprocess.run([SATRUN], input="\n".join(self.lines) + "\n", capture_output=True, text=True)
        if p.returncode:
            raise RuntimeError(p.stderr.strip())
        return Result(p.stdout)

    def rpl_env(self, stack, stack_at=0x82000, ip_at=0x83000, stop=0x85000):
        """Fake just enough RPL for a Code object: data stack (D1) with pointers to
        `stack` objects (level 1 first), and an instruction pointer (D0) whose next
        object's prolog points at `stop`. Returns stop, for run()."""
        self.poke(stack_at, "".join(nibbles(a, 5) for a in stack))
        self.poke(ip_at, nibbles(ip_at + 0x1000, 5)).poke(ip_at + 0x1000, nibbles(stop, 5))
        self.reg("D1", f"{stack_at:X}").reg("D0", f"{ip_at:X}")
        return stop
