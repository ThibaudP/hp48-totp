# Design notes

How hp48-totp works and why it's built this way. For installing and using it,
see the [README](README.md).

## Goal and constraints

Turn an HP 48G into an offline two-factor token: it displays TOTP codes
(RFC 6238, HMAC-SHA1, 6 digits, 30 s period) that match a phone authenticator,
computed from the calculator's own clock. It serves as an air-gapped backup if
the phone is lost.

- **32 KB of RAM**, and the 48G has no expansion ports. The app has to stay
  small enough to leave room for other programs.
- **No network.** Secrets are loaded once over the serial cable.
- **CPU:** a 4-bit Saturn at about 4 MHz. A SHA-256 in User RPL takes around 80 s
  on a real 48G, so a pure-RPL SHA-1 would take more than a minute per code.
  The hashing has to be machine code.

## Architecture

```
PC (Fedora)                                   HP 48G
──────────────────────────────                ─────────────────────────────────
otpauth:// export or base32 secret
  └─ ref/make_hp_payload.py ──► out/ACCTS ──┐
rpl/*.hp ── tools/build_app.py ──► out/TOTP ─┼─ Kermit ──► TOTP directory
asm/hotp.a ── sasm/sload ──► asm/hotp.bin ───┘  (serial)    ├─ OTP   the app
                                                            ├─ HOTP  machine code
                                                            ├─ ACCTS accounts
                                                            └─ helpers, font, TZ
```

The PC does everything that's done once (midstates, building the app). The
calculator only turns its clock into a counter, runs two SHA-1 compressions and
draws the screen.

## TOTP, and why only midstates are sent

1. `counter = floor(unix_time / 30)`, as 8 bytes big-endian.
2. `h = HMAC-SHA1(secret, counter)`, 20 bytes.
3. `offset = h[19] & 0x0F`, then
   `code = (int.from_bytes(h[offset:offset+4]) & 0x7FFFFFFF) % 10**6`.

HMAC-SHA1 is `SHA1((K ⊕ opad) ‖ SHA1((K ⊕ ipad) ‖ message))`, with K padded to
one 64-byte block. The first compression of each hash depends only on the key,
so it's done once on the PC:

- `istate = SHA1_compress(IV, K ⊕ ipad)`
- `ostate = SHA1_compress(IV, K ⊕ opad)`

The calculator then needs **2 compressions per code** instead of 4:

- **Inner:** `compress(istate, counter ‖ 0x80 ‖ zeros ‖ length)`, declared total
  length 64 + 8 = 72 bytes (576 bits).
- **Outer:** `compress(ostate, inner_hash ‖ 0x80 ‖ zeros ‖ length)`, declared
  total length 64 + 20 = 84 bytes (672 bits).

The midstates are as sensitive as the secret: anyone holding them can compute
every code. The secret itself never leaves the PC, though, and the midstates
can't be turned back into a QR code for another app.

Keys longer than 64 bytes are hashed first, as HMAC requires; the Python
reference handles this and the tests cover it.

**Test vectors** (secret `12345678901234567890` in ASCII):
- RFC 4226, counter 0 → `755224`, counter 1 → `287082`.
- RFC 6238, T = 59 s → `94287082` (8 digits), so `287082` in 6 digits.
- RFC 6238, T = 1111111111 → `050471`.

## Clock

```
« 1.011970 DATE DDAYS 86400 * TIME HMS→ 3600 * + TZ 3600 * - IP »
```

- `1.011970` is January 1st 1970 in both of the 48's date formats (M/D/Y and D.MY).
- `DDAYS` counts the days since then.
- `TZ` is the UTC offset of the calculator's clock in hours: 1 in winter (CET),
  2 in summer (CEST). The app's TZ key toggles it.
- `UNIX` reads `DATE` until it is stable, so a call just at midnight can't pair
  the new day with the old time.

The 48's clock drifts, so set it from time to time. Most services accept a
code from the previous or next 30 s window.

## Saturn machine code

### CPU facts that shaped the code

- **Registers:** A–D are 64-bit (16 nibbles), and R0–R4 are scratch registers
  that can only be copied to and from A and C. D0 and D1 are the two memory
  pointers.
- **32-bit arithmetic** uses field WP with P=7 (nibbles 0–7). Sums then wrap
  modulo 2³². Every 32-bit value keeps nibbles 8–15 at zero, so whole-register
  bit shifts (`ASRB`) bring in zeros from the top.
- **No XOR instruction.** XOR is computed as `(x | y) & ~(x & y)`.
- **Rotations:**
  - `rotl5`: one nibble shift left, one doubling, OR'd with a right shift by 27
    (6 nibbles plus 3 bits).
  - `rotl30`: a right shift by 2, OR'd with a left shift by 30.
  - `rotl1`: `A=A+A`, plus the carry fed back in.
- **Memory is read least significant nibble first.** SHA-1 is big-endian, but
  every word here is produced on our side (midstates, counter, padding), so
  they're all stored in the Saturn's own order and no load or store needs a
  byte swap.
- **Constants** are loaded with `LCHEX` at P=0, then P goes back to 7.
- **Mode:** `SETHEX` at entry. The code returns with P=0 and HEX mode, as RPL
  expects.

### SHA1C (`asm/sha1.a`)

- **Work area:** 680 nibbles: H0–H4 (40), then W0–W79 (640). The block is
  written into W0–W15 and the rest is scratch.
- **Message schedule:** W16–W79 are expanded first. D0 walks W[t−16]; the other
  three words sit at fixed offsets.
- **Rounds:** a–e live in R0–R4, D1 walks W[t], and D0 stays on the state.
  There are four loops of 20 rounds. Each loop computes f and K, then calls a
  shared `ROUND` (temp, then the register shift).
- **Size and speed:** about 8,800 instructions per compression and 3 RSTK levels
  (the hardware return stack has 8).

### HOTP Code object (`asm/hotp.a`)

```
3: { istate0..4 ostate0..4 }   10 user binary integers
2: counter                     user binary integer, overwritten with the result
1: scratch                     string of at least 355 characters
→ 1: truncated value (< 2³¹); RPL takes it mod 10⁶
```

- **No ROM entry points.** The RPL registers (D0 = I, D1 = stack, B = return
  stack, D = free memory) are saved at the start of the scratch string, so the
  object doesn't depend on the ROM version and can be unit-tested without a ROM.
- **Scratch layout:** saved registers at +0..+19, then the SHA1C work area at +30.
- **Truncation:** the offset is H4's lowest nibble. With k = offset / 4 and
  r = offset % 4, the 4 bytes at the offset are the top 32 bits of
  `(H[k] : H[k+1]) << 8r`.
- **Exit:** two stack levels are dropped (D1 += 10, D += 2), then `LOOP`
  (`A=DAT0 A, D0=D0+5, PC=(A)`).
- **Speed:** about 17,900 instructions, roughly 0.05 s on a 48G.

### Object layouts in memory

| Object | Prolog | Layout (nibbles) |
|---|---|---|
| User binary integer | `02A4E` | prolog 5, length 5 (`00015`, it counts itself), value 16: **26 in total** |
| String | `02A2C` | prolog 5, length 5 (5 + 2 × characters), characters |
| List | `02A74` | prolog, objects…, `0312B` (SEMI) |
| Code | `02DCC` | prolog 5, length 5, machine code (execution starts at +10) |

Binary files for Kermit start with the 8-byte header `HPHP48-E`, followed by the
object packed two nibbles per byte, low nibble first.

### Writing objects in place

`HOTP` writes into its scratch string and into the counter. The counter must
therefore be a fresh object (`R→B`), never one that is also stored somewhere.
`CODE` checks that `WRK` is a string of at least 355 characters before calling
`HOTP`: without that check, a missing `WRK` evaluates to the bare name `'WRK'`,
and `HOTP` would write over whatever object that is.

## The app

| Variable | Role |
|---|---|
| `OTP` | The app: the main loop, `KEY` polling, `PVIEW`. It moves itself to the first soft key. |
| `CODE` | account index, counter → 6-digit string (calls `HOTP`) |
| `UNIX` | clock → Unix time |
| `SCRN` | name, header, code, labels → 131×64 screen GROB without the countdown |
| `TICK` | seconds left → countdown bar and seconds drawn into PICT in one `REPL` |
| `LBLS` | the soft key labels, built once per run |
| `FMT6` | number → 6 digits with leading zeros |
| `DIGS` | the large digits 0–9 as 15×21 GROBs (a 5×7 font scaled ×3, generated in Python) |
| `TZ`, `ACCTS`, `HOTP`, `WRK` | data, the machine code and the scratch string |

### Display

- **Drawing in PICT.** `→LCD` only covers the 56 stack lines, so the soft key row
  would stay the system menu. The app draws in PICT and shows it with
  `{ #0 #0 } PVIEW`, which covers all 64 lines, including its own key labels.
- **PICT is only changed in place** (`PICT … REPL`), never re-stored while it's
  on screen. Re-storing it caused a second of garbage at each new code.
- **The countdown is drawn in one `REPL`:** it's composed off screen, so the bar
  never flickers.

### Timings at 48G speed

| Step | Time |
|---|---|
| HOTP | 0.05 s |
| Large digits | 0.35 s |
| Menu labels (once per run) | 0.5 s |
| Full screen | about 1 s, only on a new code, an account change or TZ |
| Countdown, each second | 0.06 s |

### RAM

| Part | Size |
|---|---|
| TOTP directory | 2.9 KB |
| HOTP | 0.8 KB |
| WRK and PICT | about 1.4 KB |
| Each account | about 200 B |
| Headroom while running | about 3 KB |

### Names

User variable names must not be built-in commands. `DRAW`, `MENU` and `RES`
were each tried and rejected ("Invalid Syntax" when the directory is received,
or when storing).

## Serial link

### Cable

A 4-pin JST PH 2.0 connector (filed down to fit, in the 3D-printed housing
Printables 380219) goes to a USB–RS232 adapter with real RS-232 levels, not TTL.
A Prolific PL2303 adapter works. Use its stable name under `/dev/serial/by-id/`
rather than `/dev/ttyUSB0`, which can change between plug-ins.

The HP's pins are numbered from the outside in:

| HP pin | PC side |
|---|---|
| 2 (HP TX) | PC RX: pin 2 of a DB9, or the jack tip on a jack cable |
| 3 (HP RX) | PC TX: pin 3 of the DB9, or the jack ring |
| 4 (ground) | pin 5 of the DB9, or the jack sleeve |
| 1 (shield) | not connected |

If nothing gets through, swap wires 2 and 3 first. On Fedora your user must be
in the `dialout` group (`sudo usermod -aG dialout $USER`, then log in again).

### Calculator settings

Wire mode (`-33 CF`), `IOPAR { 9600 0 0 0 3 1 }`: 9600 baud, no parity,
checksum 3, translate code 1.

### Kermit client

`tools/hpkermit.py` handles `send`, `get` and `finish`. It is plain Kermit with
type-1 checksums and an 8-bit clean channel. C-Kermit works on the real cable
but gets no replies through the emulator's pty, so one small client serves both.
It handles the HP 48 server's quirks:

- **Requests after a transfer:** a request sent right after a transfer can
  arrive before the server is listening again ("Invalid Server Cmd."), so `get`
  re-sends its request.
- **NAKs:** before a transfer starts, the server reads a NAK as an unknown
  command, so `get` only sends NAKs once data is flowing.
- **Silence:** decompiling a big object can take seconds, so the timeout only
  counts silence.
- **Existing names:** a received file doesn't replace an existing variable
  unless flag −36 is set. Run `PURGE` first, or set the flag.
- **Format of fetched variables:** they come back as ASCII transfer text, in the
  calculator's current display base (e.g. `# 739449472d`).

## Toolchain choices

| Need | Choice | Why |
|---|---|---|
| Assembler | HP Tools 3.0.8 (`sasm`/`sload`) built from source | Native, command line, so it runs from the Makefile; HP mnemonics; produces the object files Emu48's debugger reads for symbols. Debug4x is GUI-only and Windows-only. |
| Automated tests | x48ng's CPU core (`satrun`) and headless x48ng in tmux | Scriptable from top to bottom: unit tests in milliseconds, end-to-end tests through the emulated serial port. |
| Debugging by hand | Emu48 under Wine | A mature Saturn debugger with a GUI. |
| Reference | Python standard library only | Nothing to install. |

The x48ng quirks worked around in `tools/` (dark boots, a clock that runs fast
when unthrottled, dropped keys, a stalled port) are listed in the README.

## Pitfalls hit along the way

- A user binary integer is 26 nibbles: the length field (`00015`) counts itself
  plus the value. Skipping 5 nibbles instead of 10, or walking a list with a
  stride of 21 instead of 26, silently corrupts the data.
- Listing addresses include the 16-nibble `HPHP48-E` header, which isn't part of
  the object in memory.
- `→LCD` doesn't cover the menu row, and `TMENU` only takes effect after the
  program ends.
- `STR→` is slow (it runs the full parser); `NUM 47 -` is enough to read a digit.
- tmux turns runs of spaces into tabs when it captures a pane, so captures must
  be passed through `expandtabs(8)` before decoding the screen.

## Prior art

No earlier TOTP on the HP 48 is known. There are implementations for the
TI-84 Plus (Z80 assembly, 2021) and the TI-89 / Voyage 200 (2021). On the HP 48,
hpcalc.org has a SHA-256 in User RPL (2023) and S/KEY.
