#!/bin/sh
# Launch Emu48 (Windows build) in its own Wine prefix. Extra args go to Emu48, e.g. a .e48 state file.
export WINEPREFIX="${HP48_WINEPREFIX:-$HOME/.local/share/hp48-emu/wine}"
export WINEDEBUG=-all
EMU="$WINEPREFIX/drive_c/Program Files (x86)/HP-Emulators/Emu48"
cd "$EMU" && exec wine Emu48.exe "$@"
