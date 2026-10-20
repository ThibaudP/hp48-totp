#!/usr/bin/env python3
"""SHA-1 compression with a per-round trace, used as the reference for the Saturn code.

Usage:
  sha1_trace.py rfc [--counter N]     trace both HMAC compressions for the RFC secret
  sha1_trace.py block STATE BLOCK     trace one compression (STATE: 40 hex, BLOCK: 128 hex)
"""
import argparse
import struct
import sys

MASK = 0xFFFFFFFF
IV = (0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476, 0xC3D2E1F0)


def rotl(x, n):
    return ((x << n) | (x >> (32 - n))) & MASK


def compress(state, block, trace=None):
    """One SHA-1 compression of a 64-byte block. trace(t, w, a, b, c, d, e) is called after each round."""
    assert len(block) == 64
    w = list(struct.unpack(">16I", block))
    for t in range(16, 80):
        w.append(rotl(w[t - 3] ^ w[t - 8] ^ w[t - 14] ^ w[t - 16], 1))
    a, b, c, d, e = state
    for t in range(80):
        if t < 20:
            f, k = (b & c) | (~b & d), 0x5A827999
        elif t < 40:
            f, k = b ^ c ^ d, 0x6ED9EBA1
        elif t < 60:
            f, k = (b & c) | (b & d) | (c & d), 0x8F1BBCDC
        else:
            f, k = b ^ c ^ d, 0xCA62C1D6
        temp = (rotl(a, 5) + f + e + k + w[t]) & MASK
        e, d, c, b, a = d, c, rotl(b, 30), a, temp
        if trace:
            trace(t, w[t], a, b, c, d, e)
    return tuple((x + y) & MASK for x, y in zip(state, (a, b, c, d, e)))


def final_block(data, total_len):
    """Pad the last bytes of a message into one block; total_len counts every byte hashed so far, in bytes."""
    block = data + b"\x80"
    assert len(block) <= 56, "data does not fit in a single final block"
    block += b"\x00" * (56 - len(block)) + struct.pack(">Q", total_len * 8)
    return block


def sha1(msg):
    state = IV
    full = len(msg) - len(msg) % 64
    for i in range(0, full, 64):
        state = compress(state, msg[i:i + 64])
    tail = msg[full:]
    if len(tail) >= 56:
        # Padding spills into a second block.
        tail += b"\x80" + b"\x00" * (63 - len(tail))
        state = compress(state, tail)
        state = compress(state, b"\x00" * 56 + struct.pack(">Q", len(msg) * 8))
    else:
        state = compress(state, final_block(tail, len(msg)))
    return words_to_bytes(state)


def words_to_bytes(words):
    return struct.pack(f">{len(words)}I", *words)


def fmt_state(state):
    return " ".join(f"{x:08X}" for x in state)


def print_trace(label, state, block):
    print(f"== {label}")
    print(f"state in : {fmt_state(state)}")
    print(f"block    : {block.hex().upper()}")
    print(" t  W[t]     a        b        c        d        e")

    def show(t, w, a, b, c, d, e):
        print(f"{t:2d} {w:08X} {a:08X} {b:08X} {c:08X} {d:08X} {e:08X}")

    out = compress(state, block, show)
    print(f"state out: {fmt_state(out)}")
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rfc", help="trace the HMAC compressions for the RFC test secret")
    r.add_argument("--counter", type=int, default=1, help="HOTP counter (default 1, i.e. TOTP at T=59)")
    b = sub.add_parser("block", help="trace a single compression")
    b.add_argument("state", help="5 words as 40 hex digits")
    b.add_argument("block", help="64 bytes as 128 hex digits")
    args = p.parse_args(argv)

    if args.cmd == "block":
        state = struct.unpack(">5I", bytes.fromhex(args.state))
        print_trace("compress", state, bytes.fromhex(args.block))
        return 0

    from totp_ref import RFC_SECRET, midstates, truncate

    istate, ostate = midstates(RFC_SECRET)
    print(f"istate   : {fmt_state(istate)}")
    print(f"ostate   : {fmt_state(ostate)}")
    inner = print_trace("inner", istate, final_block(struct.pack(">Q", args.counter), 72))
    outer = print_trace("outer", ostate, final_block(words_to_bytes(inner), 84))
    print(f"code     : {truncate(words_to_bytes(outer), 6):06d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
