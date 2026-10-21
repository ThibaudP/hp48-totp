#!/usr/bin/env python3
"""Minimal Kermit client for an HP 48 in server mode (emulator pty or real serial port).

Usage:
  hpkermit.py PORT send FILE [NAME]   send FILE, stored on the calculator as NAME
  hpkermit.py PORT get NAME [FILE]    fetch variable NAME into FILE (default NAME)
  hpkermit.py PORT host COMMAND       evaluate COMMAND on the calculator (REMOTE HOST)
  hpkermit.py PORT finish             leave server mode

Plain Kermit with type-1 checksums, no sliding windows or long packets; the channel
is assumed 8-bit clean, so bytes with the high bit set are sent as is.
"""
import os
import re
import select
import sys
import termios
import time

MARK, EOL, QCTL = 0x01, 0x0D, ord("#")
MAXL = 90


def tochar(x):
    return x + 32


def unchar(c):
    return c - 32


def ctl(c):
    return c ^ 64


class KermitError(Exception):
    pass


class Port:
    def __init__(self, path, baud=termios.B9600):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY)
        a = termios.tcgetattr(self.fd)
        a[0] = a[1] = a[3] = 0  # raw
        a[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        a[4] = a[5] = baud
        a[6][termios.VMIN], a[6][termios.VTIME] = 0, 0
        termios.tcsetattr(self.fd, termios.TCSANOW, a)
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        self.buf = b""

    def write(self, data):
        os.write(self.fd, data)

    def read_packet(self, timeout):
        """Next packet as (seq, type, data), or None on timeout. Bad checksums are skipped."""
        end = time.time() + timeout
        while True:
            start = self.buf.find(bytes([MARK]))
            if start >= 0:
                self.buf = self.buf[start:]
                if len(self.buf) >= 2:
                    n = unchar(self.buf[1])
                    if len(self.buf) >= n + 2:
                        pkt, self.buf = self.buf[:n + 2], self.buf[n + 2:]
                        body, check = pkt[1:-1], pkt[-1]
                        if check == checksum(body):
                            return unchar(pkt[2]), chr(pkt[3]), pkt[4:-1]
                        continue
            left = end - time.time()
            if left <= 0:
                return None
            r, _, _ = select.select([self.fd], [], [], left)
            if r:
                self.buf += os.read(self.fd, 1024)


def checksum(body):
    s = sum(body)
    return tochar((s + ((s & 192) >> 6)) & 63)


def make_packet(seq, typ, data=b""):
    body = bytes([tochar(len(data) + 3), tochar(seq % 64), ord(typ)]) + data
    return bytes([MARK]) + body + bytes([checksum(body), EOL])


def encode(data):
    out = bytearray()
    for b in data:
        low = b & 0x7F
        if low < 32 or low == 127:
            out += bytes([QCTL, ctl(b)])
        elif low == QCTL:
            out += bytes([QCTL, b])
        else:
            out.append(b)
    return bytes(out)


def decode(data):
    out = bytearray()
    i = 0
    while i < len(data):
        b = data[i]
        if b == QCTL:
            i += 1
            c = data[i]
            # '?'..'_' after the prefix are controlified characters; anything else is literal.
            out.append(ctl(c) if 63 <= (c & 0x7F) <= 95 else c)
        else:
            out.append(b)
        i += 1
    return bytes(out)


def chunks(data, size):
    """Split raw data so each encoded chunk fits in `size` bytes."""
    out, cur = [], b""
    for b in data:
        enc = encode(bytes([b]))
        if len(encode(cur)) + len(enc) > size:
            out.append(cur)
            cur = b""
        cur += bytes([b])
    if cur:
        out.append(cur)
    return out


SEND_INIT = bytes([tochar(MAXL), tochar(5), tochar(0), ctl(0), tochar(EOL), QCTL, ord("N"), ord("1")])


class Kermit:
    def __init__(self, port, timeout=2, retries=5, verbose=False):
        self.port, self.timeout, self.retries, self.verbose = port, timeout, retries, verbose

    def log(self, *a):
        if self.verbose:
            print(*a, file=sys.stderr)

    def exchange(self, seq, typ, data=b""):
        """Send a packet until it is ACKed; return the ACK's data."""
        pkt = make_packet(seq, typ, data)
        for _ in range(self.retries):
            self.log(">", seq, typ, data[:40])
            self.port.write(pkt)
            r = self.port.read_packet(self.timeout)
            if r is None:
                continue
            rseq, rtyp, rdata = r
            self.log("<", rseq, rtyp, rdata[:40])
            if rtyp == "E":
                raise KermitError(f"calculator error: {rdata.decode('latin-1')}")
            if rtyp == "Y" and rseq == seq % 64:
                return rdata
        raise KermitError(f"no ACK for {typ} packet {seq}")

    def send(self, data, name):
        self.exchange(0, "S", SEND_INIT)
        seq = 1
        self.exchange(seq, "F", name.encode("latin-1"))
        for chunk in chunks(data, MAXL - 6):
            seq += 1
            self.exchange(seq, "D", encode(chunk))
        seq += 1
        self.exchange(seq, "Z")
        seq += 1
        self.exchange(seq, "B")

    def get(self, name):
        # R (receive-init) asks the server to start sending NAME.
        return self.receive(make_packet(0, "R", name.encode("latin-1")), name)

    def host(self, command, wait=30):
        """REMOTE HOST: the server evaluates `command` as a command line and sends
        back the result (level 1, as transfer text) like a file."""
        from hp2emu import TRIGRAPHS
        text = re.sub(r"\\(\d{3}|..)", lambda m: chr(int(m.group(1))) if m.group(1).isdigit()
                      else chr(TRIGRAPHS.get(m.group(1), ord("?"))), command)
        # Never re-sent after silence: the server would evaluate it again.  It
        # answers once the command has run, which can take a while.  "Invalid
        # Server Cmd." means it arrived while the server was still finishing the
        # previous transfer and was not run, so that one is safe to retry.
        for attempt in range(5):
            try:
                return self.receive(make_packet(0, "C", encode(text.encode("latin-1"))), command,
                                    resend=False, wait=wait)
            except KermitError as e:
                if "Invalid Server Cmd" not in str(e) or attempt == 4:
                    raise
                time.sleep(1.5)

    def receive(self, request, name, resend=True, wait=None):
        """Send a request packet, then receive the transfer the server answers with.
        Before the transfer starts, silence is answered by re-sending the request
        (if `resend`) or by waiting up to `wait` seconds."""
        self.port.write(request)
        data, expect, started, requests = bytearray(), 0, False, 1
        # The deadline only covers silence: big objects take a while to decompile and send.
        deadline = time.time() + (wait or self.timeout * self.retries)
        while time.time() < deadline:
            r = self.port.read_packet(self.timeout)
            if r is None:
                # Before the transfer starts, ask again (a NAK would read as an unknown
                # server command); during it, NAK the packet we wait for so it is resent.
                if started:
                    self.port.write(make_packet(expect, "N"))
                elif resend:
                    self.port.write(request)
                continue
            deadline = time.time() + self.timeout * self.retries
            seq, typ, pdata = r
            self.log("<", seq, typ, pdata[:40])
            if typ == "E" and not started and resend and requests < self.retries:
                # The server may still be finishing the previous transaction when the
                # request arrives ("Invalid Server Cmd."): give it a moment and retry.
                time.sleep(1)
                self.port.buf = b""
                self.port.write(request)
                requests += 1
                continue
            if typ == "E":
                raise KermitError(f"calculator error: {pdata.decode('latin-1')}")
            started = True
            ack = SEND_INIT if typ == "S" else b""
            self.port.write(make_packet(seq, "Y", ack))
            if seq != expect:
                continue  # duplicate, already ACKed again
            expect = (expect + 1) % 64
            if typ == "D":
                data += decode(pdata)
            elif typ == "B":
                return bytes(data)
        raise KermitError(f"timed out receiving {name}")

    def finish(self):
        self.exchange(0, "G", b"F")


def main(argv):
    if len(argv) < 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    k = Kermit(Port(argv[1]), verbose=bool(os.environ.get("HPKERMIT_VERBOSE")))
    cmd = argv[2]
    if cmd == "send" and len(argv) in (4, 5):
        with open(argv[3], "rb") as f:
            k.send(f.read(), argv[4] if len(argv) == 5 else os.path.basename(argv[3]).split(".")[0].upper())
    elif cmd == "get" and len(argv) in (4, 5):
        data = k.get(argv[3])
        with open(argv[4] if len(argv) == 5 else argv[3], "wb") as f:
            f.write(data)
    elif cmd == "host" and len(argv) == 4:
        sys.stdout.write(k.host(argv[3]).decode("latin-1"))
    elif cmd == "finish":
        k.finish()
    else:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
