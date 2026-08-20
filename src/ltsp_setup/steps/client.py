"""Turning a fresh Mint install into the client template.

The client VM is not a machine students ever log into directly.  It is the
template: you install it, set it up with this, shut it down, and then the
server turns its disk into the squashfs image that real thin clients netboot
from.
"""

from __future__ import annotations

from ltsp_setup.stages import Context
from ltsp_setup.steps.common import apt_install, apt_update
from ltsp_setup.steps.server import LTSP_PPA

CLIENT_PACKAGES = ["ltsp", "epoptes-client"]


def install_ltsp(ctx: Context) -> None:
    """Install the client half of LTSP from the LTSP PPA."""
    ctx.runner.run(["add-apt-repository", "-y", LTSP_PPA])
    apt_update(ctx)
    apt_install(ctx, CLIENT_PACKAGES, recommends=True)
