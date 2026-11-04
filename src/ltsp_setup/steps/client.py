"""Turning a fresh Mint install into the client template.

The client VM is not a machine students ever log into directly.  It is the
template: you install it, set it up with this, shut it down, and then the
server turns its disk into the squashfs image that real thin clients netboot
from.
"""

from __future__ import annotations

from pathlib import Path

from ltsp_setup import templates
from ltsp_setup.stages import Context
from ltsp_setup.steps.common import (
    AUTOSTART_DIR,
    LOCAL_SBIN,
    apt_install,
    apt_update,
)
from ltsp_setup.steps.server import LTSP_PPA

# Not LTSP-related, but this template is always edited through a libvirt
# console, so it's worth just always having: with no SPICE channel to talk
# to (i.e. real thin-client hardware), spice-vdagentd finds nothing and sits
# idle -- harmless there, and saves reinstalling it by hand on every fresh
# template VM (Todd, 2026-08-26).
CLIENT_PACKAGES = ["ltsp", "epoptes-client", "spice-vdagent"]

# Where this project's own venv lives on the template while running
# `client stage ...` by hand -- see cleanup_setup_tooling. The checkout
# itself lives directly under the admin user's home (Settings.admin_user)
# as ~/ltsp-setup -- Todd's usual ~/code/python/... layout is for his real
# projects, not a throwaway template VM checkout (2026-08-26).
VENV_DIR = Path("/opt/ltsp-setup")

# bootstrap.sh symlinks the venv's entry point here. Removing the venv
# without removing this leaves a dangling symlink in the shipped image
# (found 2026-09-09) -- harmless, but it's dead weight, and `image refresh`
# re-runs bootstrap.sh anyway, which recreates it.
ENTRY_POINT_LINK = Path("/usr/local/bin/ltsp-setup")

MONITOR_TABLE = Path("/etc/ltsp-monitor-layout.tsv")
LIGHTDM_CONF_DIR = Path("/etc/lightdm/lightdm.conf.d")


def install_ltsp(ctx: Context) -> None:
    """Install the client half of LTSP from the LTSP PPA."""
    ctx.runner.run(["add-apt-repository", "-y", LTSP_PPA])
    apt_update(ctx)
    apt_install(ctx, CLIENT_PACKAGES, recommends=True)


def configure_monitors(ctx: Context) -> None:
    """Give every desk its real monitor layout, and stop saved ones roaming.

    Client-only: the server console has one monitor and is not in the table.
    See docs/DECISIONS.md, "Monitor layout", for why this goes by EDID hash.
    """
    for name in ("ltsp-monitor-layout.sh", "ltsp-clear-display-settings.sh"):
        ctx.runner.write(LOCAL_SBIN / name, templates.read(name), mode=0o755)
    ctx.runner.write(MONITOR_TABLE, templates.read("lab-monitors.tsv"))
    ctx.runner.write(
        LIGHTDM_CONF_DIR / "60-ltsp-monitor-layout.conf",
        templates.read("ltsp-monitor-layout.conf"),
    )
    ctx.runner.write(
        AUTOSTART_DIR / "ltsp-monitor-layout.desktop",
        templates.read("ltsp-monitor-layout.desktop"),
    )


def cleanup_setup_tooling(ctx: Context) -> None:
    """Remove this project's own checkout and venv from the template.

    Not a plan stage -- run by hand as the last step before shutting the
    template down, after `client stage ...` has been used to configure it.
    The whole disk becomes the client image (steps/image.py), so anything
    left here ships to every real thin client, not just the template. Real
    students never touch it (they log in as `student` over NFS, not locally
    as this account), but there's no reason to carry the dead weight, and
    it's a bad habit to get into before anything more sensitive lands in
    this checkout (Todd, 2026-08-26).
    """
    checkout_dir = Path("/home") / ctx.settings.admin_user / "ltsp-setup"
    ctx.runner.remove_tree(checkout_dir)
    ctx.runner.remove_tree(VENV_DIR)
    ctx.runner.remove([ENTRY_POINT_LINK])
