#!/bin/sh
# Drive a headless x48ng (48GX, no ports) in a tmux session.
#   x48.sh start [gdb]   fresh boot (memory cleared), answers "Try To Recover Memory?" with NO
#   x48.sh keys K...     press keys one at a time (tmux key names: a-z 0-9 Enter BSpace F2-F6 ...)
#                        F2/F3 = left/right shift, F4 = alpha, F5 = ON, F6 = ENTER
#   x48.sh type TEXT     type letters/digits/space with alpha lock, then leave alpha
#   x48.sh screen        print the LCD as rendered by the small TUI
#   x48.sh pty           print the emulated wire port's device (for Kermit)
#   x48.sh stop          quit
set -eu
DATA="${HP48_X48NG_DATA:-$HOME/.local/share/hp48-emu/x48ng-data}"
BIN="${HP48_X48NG_BIN:-$HOME/.local/share/hp48-emu/src/x48ng/dist/x48ng}"
S=hp48
DELAY=0.4

keys() {
    for k in "$@"; do
        tmux send-keys -t $S "$k"
        sleep $DELAY
    done
}

case "${1:-}" in
start)
    tmux kill-session -t $S 2>/dev/null || true
    rm -f "$DATA/state" "$DATA/ram"
    cmd="$BIN --datadir=$DATA --tui-small --reset --serial=pty"
    # --serial (not -t, which enables IR and crashes) opens the wire port as a pty.
    if [ "${2:-}" = gdb ]; then
        cmd="gdb -q -iex 'set debuginfod enabled off' -x $DATA/gdb.cmd --args $cmd"
    fi
    tmux new-session -d -s $S -x 80 -y 40 "$cmd"
    sleep 5
    keys f
    sleep 2
    ;;
keys)
    shift
    keys "$@"
    ;;
type)
    shift
    keys F4 F4
    for w in $(echo "$*" | sed 's/./& /g'); do keys "$(echo "$w" | tr 'A-Z' 'a-z')"; done
    keys F4
    ;;
screen)
    tmux capture-pane -p -t $S | sed -n '1,34p'
    ;;
pty)
    for p in $(pgrep -x x48ng); do
        for fd in /proc/$p/fd/*; do
            t=$(readlink "$fd")
            case "$t" in /dev/pts/*) [ "$fd" != /proc/$p/fd/0 ] && [ "$fd" != /proc/$p/fd/1 ] && [ "$fd" != /proc/$p/fd/2 ] && echo "$t" ;; esac
        done
    done | head -1
    ;;
stop)
    keys F7 2>/dev/null || true
    sleep 1
    tmux kill-session -t $S 2>/dev/null || true
    ;;
*)
    sed -n '2,10p' "$0"
    exit 2
    ;;
esac
