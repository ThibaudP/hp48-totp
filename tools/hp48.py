"""End-to-end driver: a booted x48ng (via tools/x48.sh) plus the Kermit link (tools/hpkermit.py).

    with Emulator() as hp:
        hp.send("asm/hello.bin", "HELLO")
        hp.eval("#41h HELLO")        # runs on the calculator, result left on the stack
        hp.result()                  # level 1 as text, e.g. "# 66d"

The calculator sits in Kermit server mode between calls; eval() leaves it,
types and runs a command line, and goes back to server mode.
"""
import os
import re
import subprocess
import sys
import tempfile

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
from hpkermit import Kermit, Port  # noqa: E402

X48 = os.path.join(TOOLS, "x48.sh")
HEADER = "%%HP: T(3)A(D)F(.);"


def x48(*args):
    return subprocess.run([X48, *args], check=True, capture_output=True, text=True).stdout


class Emulator:
    def __enter__(self):
        x48("start")
        self.kermit = None
        self.server()
        return self

    def __exit__(self, *exc):
        x48("stop")

    def server(self):
        x48("type", "SERVER")
        x48("keys", "Enter")
        if self.kermit is None:
            self.kermit = Kermit(Port(x48("pty").strip()))

    def leave_server(self):
        self.kermit.finish()

    def send(self, path, name):
        with open(path, "rb") as f:
            self.kermit.send(f.read(), name)

    def send_text(self, source, name):
        """Send RPL source (\\<< \\>> \\-> trigraphs allowed); stored on the calculator as NAME."""
        if not source.startswith("%%HP"):
            source = HEADER + "\n" + source
        self.kermit.send(source.encode("latin-1"), name)

    def get(self, name):
        """Variable NAME as the calculator's ASCII transfer text, header stripped."""
        text = self.kermit.get(name).decode("latin-1").replace("\r\n", "\n")
        return re.sub(r"^%%HP:[^\n]*\n", "", text).strip()

    def eval(self, rpl):
        """Run RPL on the calculator, then store level 1 in RSLT (fetch it with result())."""
        self.send_text(f"\\<< {rpl} 'RSLT' STO \\>>", "RUN")
        self.leave_server()
        x48("type", "RUN")
        x48("keys", "Enter")
        self.server()

    def result(self):
        return self.get("RSLT")

    def screen(self):
        return x48("screen")
