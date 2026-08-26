#!/bin/sh
# ltsp-setup: remove Chrome's SingletonLock/SingletonCookie/SingletonSocket
# at session start. NFS home + the concurrent-login lock
# (steps/common.py::configure_session_lock) together guarantee any lock
# still here is stale: a fresh login can't happen while a real session is
# genuinely still active elsewhere, so if we're here, whatever session
# created these left uncleanly (crash, power loss, forced logout) rather
# than being a session still using Chrome right now. Without this, a
# student who lost power mid-session comes back to Chrome refusing to
# start at all.
set -eu

rm -f "$HOME/.config/google-chrome/SingletonLock" \
    "$HOME/.config/google-chrome/SingletonCookie" \
    "$HOME/.config/google-chrome/SingletonSocket"
