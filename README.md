# hp48-totp

Offline TOTP codes on an HP 48G. Plan and technical notes: [HANDOFF.md](HANDOFF.md).

## Make targets

| Target | What it does |
|---|---|
| `make test` | Python reference: SHA-1, HOTP/TOTP via HMAC and via midstates, payload format |
| `make trace` | SHA-1 state after every round for the RFC vector (reference for the asm) |
| `make asm` | Assemble `asm/*.a` with HP Tools into `asm/*.bin` (HPHP48 binary objects) |
| `make asm-test` | Run asm routines on x48ng's CPU core (`tools/satrun`), no ROM or UI |
| `make e2e` | Boot a headless 48GX in x48ng, transfer over the emulated wire port, run, fetch results (~70 s) |
| `make emu` | Emu48 under Wine, for poking around by hand |

## Test layers

1. **`asm-test`**: `tools/satrun` is x48ng's Saturn core with flat memory, driven by
   `asm/saturn.py`. Load a routine, set registers and memory (including a fake RPL
   stack), run, read back. Breakpoints print registers, for round-by-round checks.
2. **`e2e`**: `tools/hp48.py` runs x48ng in tmux (`tools/x48.sh`), types on the
   keyboard, and moves objects with `tools/hpkermit.py`, a small Kermit client.
   `hp.eval("...")` runs RPL on the calculator and `hp.result()` returns level 1.
3. Real calculator: `hpkermit.py /dev/ttyUSB0 send ...` once the cable exists.

## Local toolchain (not in the repo)

Everything lives in `~/.local/share/hp48-emu/`:

- `hptools/bin/`: HP Tools 3.0.8 (`sasm`, `sload`, `rplcomp`) built from
  hpcalc.org source + Jonathan Busby's 0.3.2.1 Linux patch (`patch -p2`), with
  `CFLAGS="-O2 -std=gnu89 -fcommon -w"`.
- `src/x48ng/`: x48ng 1.3.1 from codeberg.org/gwh/x48ng (`git clone --recursive`), built with
  `make WITH_SDL=no SDL_SRC=src/sdl_bitmaps.c` (upstream's no-SDL build misses the key bitmaps).
  Needs `lua-devel readline-devel ncurses-devel gtk4-devel`.
  Its `-t` flag enables IR and crashes; `--serial=pty` is what opens the wire port.
- `x48ng-data/`: ROM (`gxrom-r` from hpcalc.org) and config for x48ng.
- `wine/`: Emu48 1.68 in its own Wine prefix, with the same ROM as `ROM.48G`.

C-Kermit cannot talk to x48ng's pty (no replies get through), while raw termios
works, hence `tools/hpkermit.py`.

x48ng quirks handled by `tools/x48.sh` / `tools/hp48.py`:
- cold boots sometimes stay dark (stuck-on-OFF bug): restart until the screen shows;
  `--inhibit-shutdown` would avoid it but makes the clock drift;
- unthrottled emulation runs the calculator clock fast while busy: `--throttle`;
- the wire port sometimes stops answering after a transfer: press ON, `SERVER` again, retry;
- flag -36 is set so received files overwrite existing variables.

## Calling HOTP

`KT counter R->B WRK HOTP B->R 1000000 MOD`, where `KT` is the payload from
`ref/make_hp_payload.py` and `WRK` a string of at least 355 characters used as
scratch memory (modified in place). About 0.05 s per code at 48GX speed.
