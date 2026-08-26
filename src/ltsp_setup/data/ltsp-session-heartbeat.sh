#!/bin/sh
# ltsp-setup: refresh this session's concurrent-login lock every 60s so a
# genuinely active session is never mistaken for an abandoned one. Started
# at session start by ltsp-session-heartbeat.desktop (XFCE autostart); runs
# for the life of the session and is killed when it ends. See
# ltsp-session-lock-check.sh for the full mechanism.
set -eu

lockdir="$HOME/.ltsp-session-lock"
me=$(hostname)

while sleep 60; do
    if [ "$(cat "$lockdir/host" 2>/dev/null || echo "")" = "$me" ]; then
        date +%s >"$lockdir/heartbeat"
    fi
done
