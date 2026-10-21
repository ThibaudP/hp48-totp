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
PC (Fedora)                                        HP 48G
───────────────────────────────────                ─────────────────────────────────
rpl/*.hp ── tools/build_app.py ──► out/TOTP ─┐
asm/{hotp,shac}.a ── sasm/sload ──► *.bin ───┼─ make dist (emulator) ──► dist/TOTP
                                             │                            │ Kermit
otpauth:// export (optional)                 │                            ▼
  └─ ref/make_hp_payload.py ──► out/ACCTS ───┘ ─ Kermit ──────────► TOTP directory
                                                                    ├─ OTP   the app
                                                                    ├─ HOTP  code (HMAC + truncation)
                                                                    ├─ SHAC  code (one compression)
                                                                    ├─ ACCTS accounts
                                                                    └─ helpers, font, TZ
```

- **The release:** a single binary directory, `dist/TOTP`. `make dist` builds
  it by installing the text directory and the two Code objects on an emulated
  48GX, then fetching the directory back in binary transfer mode.
- **Accounts:** they're added on the calculator, where `ADD` computes the
  midstates with `SHAC`, or imported in bulk from the PC.
- **Work per code:** the calculator turns its clock into a counter, runs two
  SHA-1 compressions and draws the screen.

## TOTP, and why only midstates are stored

1. `counter = floor(unix_time / 30)`, as 8 bytes big-endian.
2. `h = HMAC-SHA1(secret, counter)`, 20 bytes.
3. `offset = h[19] & 0x0F`, then
   `code = (int.from_bytes(h[offset:offset+4]) & 0x7FFFFFFF) % 10**6`.

HMAC-SHA1 is `SHA1((K ⊕ opad) ‖ SHA1((K ⊕ ipad) ‖ message))`, with K padded to
one 64-byte block. The first compression of each hash depends only on the key,
so it's done once, when the account is added (`MIDS` on the calculator, or
`ref/make_hp_payload.py` on the PC):

- `istate = SHA1_compress(IV, K ⊕ ipad)`
- `ostate = SHA1_compress(IV, K ⊕ opad)`

The calculator then needs **2 compressions per code** instead of 4:

- **Inner:** `compress(istate, counter ‖ 0x80 ‖ zeros ‖ length)`, declared total
  length 64 + 8 = 72 bytes (576 bits).
- **Outer:** `compress(ostate, inner_hash ‖ 0x80 ‖ zeros ‖ length)`, declared
  total length 64 + 20 = 84 bytes (672 bits).

The midstates are as sensitive as the secret: anyone holding them can compute
every code. They can't be turned back into the secret, or into a QR code for
another app, though.

Keys longer than 64 bytes are hashed first, as HMAC requires. The Python
reference handles that and the tests cover it. `MIDS` on the calculator refuses
them ("Secret too long"); base32 secrets from services are 10 to 32 bytes.

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

### SHAC Code object (`asm/shac.a`)

```
3: { h0 h1 h2 h3 h4 }   5 user binary integers, updated in place
2: block                64-character string: 16 words, each stored least
                        significant nibble first (bytes reversed per word)
1: scratch              string of at least 355 characters
→ 1: { h0..h4 }         the same list, compressed
```

`SHAC` uses the same conventions as `HOTP`: the registers are saved in the
scratch string and it includes the same `SHA1C`.

- **`PADB`:** builds the ipad or opad block in RPL. It zero-pads the key, XORs
  it with 0x36 or 0x5C, and reverses each 4-byte word, so the machine code never
  swaps bytes.
- **`MIDS`:** runs `SHAC` twice from the SHA-1 IV, giving the 10 words stored in
  `ACCTS`.
- **`B32D`:** decodes base32 in RPL.
- **Time:** computing one account's midstates takes a few seconds, mostly
  `PADB`'s character-by-character loop.

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

### Programs

The main program `OTP` is System RPL (`srpl/otp.s`), compiled by `rplcomp`,
assembled by `sasm` and linked by `sload` against the supported ROM entry
points. Its state lives in 22 numbered local variables (listed at the top of
the source). Everything else is User RPL, called by name:

| Variable | Role |
|---|---|
| `OTP` | The app (System RPL): main loop, keyboard (`GETTOUCH`), drawing into the display (`HARDBUFF`, `GROB!`, `GROB!ZERO`, `INVGROB`), codes (calls `HOTP`) |
| `INIT` | creates `WRK` and `ACCTS` if missing, puts `OTP` on the first soft key |
| `SECS`, `UNIX` | seconds within the minute (from `TIME`), Unix time |
| `W25`, `OFFH` | `.25 WAIT` and `OFF`, which have no supported System RPL entry |
| `LBLS`, `TZL`, `DIGS` | soft key labels, time zone label, the large digits (15×21 GROBs, a 5×7 font scaled ×3, generated in Python) |
| `ADDA`, `RENA`, `DELA`, `TIMEA`, `SWAP2` | ADD, REN, DEL, TIME and MOVE |
| `B32D`, `PADB`, `MIDS` | base32 decoding and midstates on the calculator (calls `SHAC`) |
| `CODE`, `FMT6`, `MKWRK` | a code from User RPL (kept for tests and by hand), 6-digit formatting, the scratch string |
| `TZ`, `ACCTS`, `HOTP`, `SHAC`, `WRK` | data, the machine code and the scratch string |

### Display

- **Full screen.** `RECLAIMDISP` then `TURNMENUOFF` give the program the whole
  131×64 display (`HARDBUFF`), including the soft key row, where it draws its
  own labels. On exit, `TURNMENUON` and `ClrDAsOK` hand the screen back.
- **Three levels of redraw:**
  - full screen: on an account change, a mode change, TZ, or an edit;
  - codes only: on a new 30 s window;
  - countdown only: every second. It clears the part of the bar that passed
    with `GROB!ZERO` and rewrites the 3-character seconds.
- **Selection moves in place.** In the home view, ▲▼ redraw the two rows
  concerned; the list is redrawn only when it scrolls, one page at a time.
- **Input screens.** ADD and REN use `INPUT` rather than `INFORM`: INPUT returns
  the typed text as is, while INFORM would parse a base32 secret as an object.
  DEL confirms with `CHOOSE`, and TIME is an `INFORM` with numeric fields.
- **Auto power-off.** After 3 minutes without a key press the calculator turns
  off; ON resumes the app, which redraws everything.

### Garbage collection

A 48G with the app and a few accounts has about 12 KB free. The 48 collects
garbage when temporary memory runs out, and a collection inside a busy program
takes one to several seconds. The first versions allocated so much that this
happened every few seconds, which showed up as freezes of 2–5 s.

- **Clock:** the countdown needs only the seconds within the minute (Unix time
  mod 30 equals local seconds mod 30, time zones being whole hours), read with
  `TIME`. The full Unix time is read once per 30 s window, to compute codes.
- **Codes:** the next window's codes are computed ahead, one per second, so a
  new window only redraws.
- **System RPL:** counters and coordinates are small binary integers, many of
  them built into the ROM, instead of 10.5-byte reals.
- **No forced collection.** Calling `MEM` to collect at a chosen moment took
  3.3 s inside the app, worse than letting the 48 collect when it must.

Measured on the emulator with 13 KB free, freezes longer than 1.5 s in 70 s
went from 19 (up to 5.6 s, first User RPL version) to 2 (up to 1.9 s). To
reproduce that, give the emulator the same free memory as a 48G: emulators are
usually 48GX with 128 KB, where none of this shows.

### Layouts (131×64)

| Rows (y) | Home view | Account view |
|---|---|---|
| 0–7 | `TOTP` · seconds, time zone | name · `3/9 CEST` |
| 0–7, x=80 | seconds | |
| 9–10 | countdown (2 px) | |
| 9–16 | | `prev  110 349` |
| 12–51 | 5 rows: name · code, the selected one inverted | |
| 18–38 | | current code, 15×21 digits |
| 40–47 | | `next  902 115` |
| 48–55 | | countdown bar, seconds |
| 56–63 | soft key labels | soft key labels |

### Timings at 48G speed

| Step | Time |
|---|---|
| One code (HOTP) | 0.05 s |
| ▲▼ in the home view | about 0.2 s |
| Opening an account | about 0.5 s |
| PREV / NEXT | about 0.7 s |
| BACK to the home view | about 0.4 s |
| Adding an account (midstates) | a few seconds |

### RAM

| Part | Size |
|---|---|
| `dist/TOTP` (programs, font, HOTP, SHAC, OTP) | about 10 KB; `OTP` alone is 4.6 KB |
| Each account | about 200 B |
| WRK | about 0.4 KB, created at run time |
| Temporaries while running | a few KB, collected now and then |

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
- When ncurses moves the cursor with hardware tabs, tmux captures a tab, and the
  cells it skipped are lost. The emulator therefore runs with a terminal type
  that has no tabs (`tools/x48.sh` builds it from `tmux-256color`).
- `INFORM` parses what you type; a text field needs `INPUT`.

## Prior art

No earlier TOTP on the HP 48 is known. There are implementations for the
TI-84 Plus (Z80 assembly, 2021) and the TI-89 / Voyage 200 (2021). On the HP 48,
hpcalc.org has a SHA-256 in User RPL (2023) and S/KEY.
