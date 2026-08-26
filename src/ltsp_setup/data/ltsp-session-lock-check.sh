#!/bin/sh
# ltsp-setup: refuse logging a student account in on a second client while
# it's already active on another. Both clients mount the same NFS home
# directory, so a concurrent login corrupts things like browser profile
# locks (the exact Chrome singleton-lockfile problem already tracked in
# docs/desktop-polish-todo.md) and xfconf's config files. Wired in via
# pam_exec (auth phase) in /etc/pam.d/lightdm -- see
# steps/common.py::configure_session_lock.
#
# The lock is a directory (mkdir is atomic even over NFS) inside the
# student's own home, holding which client currently owns it and when that
# was last refreshed. A companion autostart entry
# (ltsp-session-heartbeat.desktop) refreshes it every 60s for the life of
# the session; ltsp-session-lock-release.sh removes it on a clean logout.
# If a client crashes or loses power without logging out, the lock goes
# stale after STALE_SECONDS and the next login (from any client) takes it
# over automatically. To clear one immediately instead of waiting, run on
# the server: sudo ltsp-setup student clear-lock <username>
set -eu

STALE_SECONDS=180

user="${PAM_USER:-}"
[ -n "$user" ] || exit 0

home=$(getent passwd "$user" | cut -d: -f6)
[ -n "$home" ] && [ -d "$home" ] || exit 0

lockdir="$home/.ltsp-session-lock"
me=$(hostname)

if mkdir "$lockdir" 2>/dev/null; then
    echo "$me" >"$lockdir/host"
    date +%s >"$lockdir/heartbeat"
    exit 0
fi

owner=$(cat "$lockdir/host" 2>/dev/null || echo "")
if [ "$owner" = "$me" ]; then
    # Same client re-authenticating (e.g. unlocking the screen saver).
    date +%s >"$lockdir/heartbeat"
    exit 0
fi

heartbeat=$(cat "$lockdir/heartbeat" 2>/dev/null || echo 0)
now=$(date +%s)
age=$((now - heartbeat))

if [ "$age" -gt "$STALE_SECONDS" ]; then
    # The owning client went away without logging out -- take it over.
    echo "$me" >"$lockdir/host"
    date +%s >"$lockdir/heartbeat"
    exit 0
fi

echo "Already logged in on $owner ($age""s ago). Log out there first, or ask your teacher to clear the lock." >&2
exit 1
