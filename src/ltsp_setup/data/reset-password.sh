#!/bin/sh
# ltsp-setup: shorthand for `ltsp-setup student reset-password`, typed
# often enough that the full sudo/--no-debug/--config form was worth
# shortening to `reset-password <username>` (Todd, 2026-08-27). See
# steps/server.py::configure_admin_shortcuts.
set -eu
if [ "$#" -ne 1 ]; then
    echo "usage: reset-password <username>" >&2
    exit 1
fi
exec sudo /usr/local/bin/ltsp-setup student reset-password "$1" --no-debug
