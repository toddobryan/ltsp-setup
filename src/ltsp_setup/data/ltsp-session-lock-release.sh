#!/bin/sh
# ltsp-setup: release this client's concurrent-login lock on logout. See
# ltsp-session-lock-check.sh for the full mechanism. Wired in via pam_exec
# (close_session) in /etc/pam.d/lightdm.
set -eu

user="${PAM_USER:-}"
[ -n "$user" ] || exit 0

home=$(getent passwd "$user" | cut -d: -f6)
[ -n "$home" ] && [ -d "$home" ] || exit 0

lockdir="$home/.ltsp-session-lock"
me=$(hostname)

if [ -d "$lockdir" ] && [ "$(cat "$lockdir/host" 2>/dev/null || echo "")" = "$me" ]; then
    rm -rf "$lockdir"
fi
