#!/bin/bash
# Install ltsp-setup on a fresh Mint machine and put it on PATH as root.
#
# Copy this repository onto the machine, then:
#     sudo bash bootstrap.sh
#
# It installs into its own virtualenv under /opt so nothing here can disturb
# the system Python that Mint's own tools depend on, and symlinks the command
# into /usr/local/bin, which is where the systemd unit looks for it.
set -euo pipefail

PREFIX=/opt/ltsp-setup
LINK=/usr/local/bin/ltsp-setup
SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $EUID -ne 0 ]]; then
    echo "This needs to run as root: sudo bash bootstrap.sh" >&2
    exit 1
fi

echo ":: Installing build prerequisites"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-pip

echo ":: Creating the virtualenv at $PREFIX"
python3 -m venv "$PREFIX"
"$PREFIX/bin/pip" install --quiet --upgrade pip
"$PREFIX/bin/pip" install --quiet "$SOURCE_DIR"

ln -sf "$PREFIX/bin/ltsp-setup" "$LINK"

echo
echo ":: Installed. $("$LINK" --help >/dev/null 2>&1 && echo 'ltsp-setup is on PATH')"
echo
echo "Next, review what the setup would do (this changes nothing):"
echo "    ltsp-setup server start --config $SOURCE_DIR/examples/lab.toml --no-reboot"
echo
echo "Then, when it looks right:"
echo "    sudo ltsp-setup server start --config $SOURCE_DIR/examples/lab.toml --no-debug"
