#!/bin/sh
# Build the local toolchain into $HP48_EMU_HOME (default ~/.local/share/hp48-emu).
#
#   scripts/setup-toolchain.sh            HP Tools + x48ng (built) + 48GX ROM: everything
#                                         `make check` and `make e2e` need
#   scripts/setup-toolchain.sh --minimal  HP Tools + x48ng sources only: enough for
#                                         `make check` (used by CI)
#
# Needs: a C compiler, make, autoconf, automake, curl, unzip, git.
# The full build also needs x48ng's dependencies (Fedora: lua-devel readline-devel
# ncurses-devel gtk4-devel; Debian/Ubuntu: liblua5.4-dev libreadline-dev
# libncurses-dev libgtk-4-dev) and tmux to run the end-to-end tests.
#
# Safe to re-run: finished steps are skipped.
set -eu

H="${HP48_EMU_HOME:-$HOME/.local/share/hp48-emu}"
MINIMAL=0
[ "${1:-}" = --minimal ] && MINIMAL=1

HPCALC=https://www.hpcalc.org/hp48/pc
X48NG_REPO=https://codeberg.org/gwh/x48ng.git
X48NG_TAG=1.3.1

mkdir -p "$H/dl" "$H/src"
LOG="$H/setup.log"
: > "$LOG"
quiet() { "$@" >> "$LOG" 2>&1 || { tail -20 "$LOG"; echo "failed: $* (full log: $LOG)" >&2; exit 1; }; }
fetch() { [ -s "$H/dl/$2" ] || curl -fsSL -o "$H/dl/$2" "$1/$2"; }

# HP Tools 3.0.8 (sasm, sload, rplcomp), with Jonathan Busby's patch for modern
# Linux. The 2002 C code also needs gnu89 and -fcommon with current GCC.
if [ ! -x "$H/hptools/bin/sasm" ]; then
    echo "== HP Tools"
    fetch "$HPCALC/programming" hptools-src-3.0.8.tar.gz
    fetch "$HPCALC/programming" hptools-patch-0.3.2.1.zip
    b="$H/src/hptools"
    rm -rf "$b" && mkdir -p "$b"
    tar -C "$b" -xzf "$H/dl/hptools-src-3.0.8.tar.gz"
    unzip -q -o "$H/dl/hptools-patch-0.3.2.1.zip" -d "$b/patch"
    chmod -R u+rw "$b"
    (
        cd "$b/Hptools"
        gzip -dc ../patch/hptools.patch.gz | patch -p2 -s --batch
        sh ../patch/fixperms.sh
        quiet ./autogen.sh
        quiet ./configure
        quiet make all CFLAGS="-O2 -pipe -std=gnu89 -fcommon -w"
    )
    mkdir -p "$H/hptools/bin"
    for t in sasm sload rplcomp makerom; do
        cp "$(find "$b/Hptools" -type f -name "$t" -perm -u+x | head -1)" "$H/hptools/bin/"
    done
fi

# x48ng: its CPU core is compiled into tools/satrun; the full emulator runs `make e2e`.
if [ ! -d "$H/src/x48ng/src/core" ]; then
    echo "== x48ng $X48NG_TAG"
    git -c advice.detachedHead=false clone -q --recursive --depth 1 --branch "$X48NG_TAG" "$X48NG_REPO" "$H/src/x48ng"
fi
[ $MINIMAL = 1 ] && { echo "toolchain (minimal) ready in $H"; exit 0; }

if [ ! -x "$H/src/x48ng/dist/x48ng" ]; then
    echo "== building x48ng"
    # Upstream's no-SDL build forgets the key bitmaps; add them back.
    quiet make -C "$H/src/x48ng" WITH_SDL=no SDL_SRC=src/sdl_bitmaps.c
fi

# 48GX ROM revision R. hpcalc.org distributes HP 48 ROMs for emulators: per the
# site, "HP graciously began allowing this to be downloaded in mid-2000".
D="$H/x48ng-data"
if [ ! -s "$D/rom" ]; then
    echo "== 48GX ROM"
    fetch "$HPCALC/emulators" gxrom-r.zip
    mkdir -p "$D"
    unzip -q -o "$H/dl/gxrom-r.zip" -d "$H/dl"
    cp "$H/dl/gxrom-r" "$D/rom"
fi
if [ ! -s "$D/config.lua" ]; then
    "$H/src/x48ng/dist/x48ng" --48gx --tui --datadir="$D" --print-config 2>/dev/null | grep -v '^Lua error' > "$D/config.lua"
fi

echo "toolchain ready in $H"
