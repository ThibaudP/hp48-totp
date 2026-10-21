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
import shutil
import subprocess
import sys
import tempfile
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOOLS)
from hpkermit import Kermit, KermitError, Port  # noqa: E402

X48 = os.path.join(TOOLS, "x48.sh")
HEADER = "%%HP: T(3)A(D)F(.);"


class CalcError(Exception):
    pass


EMU_HOME = os.environ.get("HP48_EMU_HOME") or os.path.expanduser("~/.local/share/hp48-emu")
DATA = os.path.join(EMU_HOME, "x48ng-data")
ENV = dict(os.environ)


def x48(*args):
    return subprocess.run([X48, *args], check=True, capture_output=True, text=True, env=ENV).stdout


class Emulator:
    def __enter__(self):
        # Own tmux session and data directory, so parallel runs (other shells,
        # other sessions) never drive or reset each other's emulator.
        self.data = tempfile.mkdtemp(prefix="hp48-")
        for f in ("rom", "config.lua"):
            shutil.copy(os.path.join(DATA, f), self.data)
        ENV["HP48_SESSION"] = f"hp48-{os.getpid()}"
        ENV["HP48_X48NG_DATA"] = self.data
        x48("start")
        self.kermit = None
        # -36 SF: received files overwrite existing variables (RUN is re-sent each eval).
        x48("keys", "3", "6", "y")
        x48("type", "SF")
        x48("keys", "Enter")
        self.server()
        return self

    def __exit__(self, *exc):
        x48("stop")
        shutil.rmtree(self.data, ignore_errors=True)

    def server(self):
        x48("type", "SERVER")
        x48("keys", "Enter")
        if self.kermit is None:
            self.kermit = Kermit(Port(x48("pty").strip()))

    def leave_server(self):
        self.kermit.finish()

    def kermit_call(self, fn, *args):
        """Run a Kermit transaction; if the server stopped answering (x48ng's wire
        port sometimes stalls after a transfer), restart server mode and retry once."""
        try:
            return fn(*args)
        except KermitError as e:
            if "no ACK for S" not in str(e) and "timed out" not in str(e):
                raise
            x48("keys", "F5")
            self.server()
            return fn(*args)

    def host(self, command):
        """Evaluate a command line on the calculator (Kermit REMOTE HOST) and
        return the stack it shows afterwards, as text."""
        for attempt in range(3):
            try:
                return self.kermit.host(command).decode("latin-1").replace("\r\n", "\n")
            except KermitError as e:
                if "Invalid Server Cmd" in str(e):  # still finishing the last transfer
                    time.sleep(1)
                    continue
                if attempt == 2 or ("timed out" not in str(e) and "no ACK" not in str(e)):
                    raise
                x48("keys", "F5")  # wire port stalled: restart server mode
                self.server()
        raise KermitError(f"host command failed: {command}")

    def send(self, path, name):
        with open(path, "rb") as f:
            self.kermit_call(self.kermit.send, f.read(), name)

    def send_text(self, source, name):
        """Send RPL source (\\<< \\>> \\-> trigraphs allowed); stored on the calculator as NAME."""
        if not source.startswith("%%HP"):
            source = HEADER + "\n" + source
        self.kermit_call(self.kermit.send, source.encode("latin-1"), name)

    def get(self, name):
        """Variable NAME as the calculator's ASCII transfer text, header stripped."""
        text = self.kermit_call(self.kermit.get, name).decode("latin-1").replace("\r\n", "\n")
        return re.sub(r"^%%HP:[^\n]*\n", "", text).strip()

    def eval(self, rpl):
        """Run RPL on the calculator, then store level 1 in RSLT (fetch it with result())."""
        self.send_text(f"\\<< IFERR {rpl} THEN \"ERROR: \" ERRM + END 'RSLT' STO \\>>", "RUN")
        self.leave_server()
        x48("type", "RUN")
        x48("keys", "Enter")
        self.server()

    def result(self):
        r = self.get("RSLT")
        if r.startswith('"ERROR: '):
            raise CalcError(r.strip('"'))
        return r

    def screen(self):
        return x48("screen")
