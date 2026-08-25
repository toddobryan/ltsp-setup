"""The ordered stages that make up a server setup and a client setup."""

from __future__ import annotations

from ltsp_setup.stages import Context, Plan, Stage
from ltsp_setup.steps import apps, client, common, server, students


def _server_networking(ctx: Context) -> None:
    server.configure_networking(ctx)


def _mirrors_and_upgrade(ctx: Context) -> None:
    common.set_mirrors(ctx)
    # Refresh the package index against the new mirrors before installing
    # anything from them -- otherwise install_prerequisites resolves
    # dependencies against the stale pre-switch index, which produced real
    # "unmet dependencies" failures on the first real run (git needing
    # liberror-perl, not visible in the old index).
    common.apt_update(ctx)
    common.install_prerequisites(ctx)
    common.apt_upgrade(ctx)


def _apps(ctx: Context) -> None:
    apps.install_all(ctx)


def _server_ltsp(ctx: Context) -> None:
    server.install_ltsp(ctx)
    server.configure_ltsp(ctx)
    server.configure_epoptes(ctx)


def _server_virt(ctx: Context) -> None:
    server.install_virt_tools(ctx)


def _client_ltsp(ctx: Context) -> None:
    client.install_ltsp(ctx)


def _desktop(ctx: Context) -> None:
    common.configure_dconf(ctx)
    common.configure_autostart(ctx)
    common.configure_racket_mime(ctx)


def _skel(ctx: Context) -> None:
    students.configure_skel(ctx)


SERVER = Plan(
    "server",
    [
        Stage(
            "networking",
            "hostname, /etc/hosts and a static address on the LTSP NIC",
            _server_networking,
        ),
        Stage(
            "mirrors",
            "point apt at our mirrors and upgrade everything",
            _mirrors_and_upgrade,
            reboot_after=True,
        ),
        Stage("apps", "Java, Racket, Chrome, VS Code and Rust", _apps),
        Stage(
            "ltsp",
            "LTSP server, dnsmasq, NFS and Epoptes",
            _server_ltsp,
            reboot_after=True,
        ),
        Stage(
            "virt",
            "KVM and libvirt, to host the client-template VM",
            _server_virt,
        ),
        Stage("desktop", "system-wide desktop defaults", _desktop, reboot_after=True),
        Stage(
            "skel",
            "point new-account creation (/etc/skel) at current student defaults",
            _skel,
        ),
    ],
)

CLIENT = Plan(
    "client",
    [
        Stage(
            "mirrors",
            "point apt at our mirrors and upgrade everything",
            _mirrors_and_upgrade,
            reboot_after=True,
        ),
        Stage("apps", "Java, Racket, Chrome, VS Code and Rust", _apps),
        Stage("ltsp", "LTSP client and the Epoptes agent", _client_ltsp),
        Stage("desktop", "system-wide desktop defaults", _desktop, reboot_after=True),
    ],
)

PLANS = {"server": SERVER, "client": CLIENT}
