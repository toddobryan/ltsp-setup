"""Work that is identical on the server and on the clients."""

from __future__ import annotations

from pathlib import Path

from ltsp_setup import templates
from ltsp_setup.stages import Context

SOURCES_LIST = Path("/etc/apt/sources.list.d/official-package-repositories.list")
DCONF_PROFILE = Path("/etc/dconf/profile/user")
DCONF_LOCAL_DIR = Path("/etc/dconf/db/local.d")

PANEL_DEFAULT = Path("/etc/xdg/xfce4/panel/default.xml")
AUTOSTART_DIR = Path("/etc/xdg/autostart")

# Autostart entries hidden for students: they have no privilege to act on
# any of them, so showing the icon/nag is just confusing clutter (Todd,
# 2026-08-19). Overwriting the packaged .desktop file directly (rather than
# a per-user override) matches the panel default below and needs no
# per-account setup -- fine here because the client image is squashfs and
# gets rebuilt from the template, not live-upgraded in place.
HIDDEN_AUTOSTART = [
    "mintupdate.desktop",  # Update Manager
    "mintreport.desktop",  # System Reports -- nags to set up Timeshift,
    # meaningless on a diskless squashfs client with no persistent disk.
    "blueman.desktop",  # Bluetooth applet
    "warpinator-autostart.desktop",  # LAN file sharing
]


def set_mirrors(ctx: Context) -> None:
    """Point apt at the mirrors we actually want to use.

    Mint's own installer picks a mirror by geography and it is often slow.
    This replaces the generated file wholesale.
    """
    mirrors = ctx.settings.mirrors
    content = templates.render(
        "official-package-repositories.list",
        {
            "MINT_MIRROR": mirrors.mint_mirror,
            "MINT_VERSION": mirrors.mint_version,
            "MINT_REPOS": mirrors.mint_repos,
            "UBUNTU_MIRROR": mirrors.ubuntu_mirror,
            "UBUNTU_VERSION": mirrors.ubuntu_version,
            "UBUNTU_REPOS": mirrors.ubuntu_repos,
            "UBUNTU_SECURITY_MIRROR": mirrors.ubuntu_security_mirror,
        },
    )
    ctx.runner.write(SOURCES_LIST, content)


def apt_update(ctx: Context) -> None:
    """Refresh the package lists."""
    ctx.runner.run(["apt-get", "update"])


def apt_upgrade(ctx: Context) -> None:
    """Refresh package lists and upgrade everything installed."""
    apt_update(ctx)
    ctx.runner.run(
        ["apt-get", "upgrade", "-y"],
        env={"DEBIAN_FRONTEND": "noninteractive"},
    )


def apt_install(ctx: Context, packages: list[str], *, recommends: bool = True) -> None:
    """Install packages non-interactively.

    Args:
        ctx: Settings and runner.
        packages: What to install.  An empty list is a no-op.
        recommends: Pass False to skip recommended packages.
    """
    if not packages:
        return
    argv = ["apt-get", "install", "-y"]
    if not recommends:
        argv.append("--no-install-recommends")
    argv.extend(packages)
    ctx.runner.run(argv, env={"DEBIAN_FRONTEND": "noninteractive"})


def install_prerequisites(ctx: Context) -> None:
    """The handful of packages the later steps need in order to work.

    No ``software-properties-common`` here: Mint replaces it with its own
    ``mintsources`` (the package doesn't even have an installation
    candidate), and ``mintsources`` -- already present on a stock Mint
    install -- already provides ``add-apt-repository``, which is the only
    thing later steps actually need from that package on Ubuntu.
    """
    apt_install(
        ctx,
        [
            "apt-transport-https",
            "ca-certificates",
            "curl",
            "wget",
            "gpg",
            "git",
        ],
    )


def configure_dconf(ctx: Context) -> None:
    """Set system-wide desktop defaults.

    Right now this is only the clock format.  Student defaults will land here
    too, which is why the profile and the local database are set up properly
    rather than being poked in as one-off gsettings calls.
    """
    ctx.runner.write(DCONF_PROFILE, templates.read("dconf-profile-user"))
    ctx.runner.mkdir(DCONF_LOCAL_DIR)
    ctx.runner.write(
        DCONF_LOCAL_DIR / "01-datetime", templates.read("dconf-01-datetime")
    )
    ctx.runner.run(["dconf", "update"])


def configure_panel_defaults(ctx: Context) -> None:
    """Replace the system panel default with the school's version.

    Verified against a live diff of a student's own edited panel (2026-08-19)
    rather than guessed from documentation: this is the stock Mint
    ``default.xml`` with the ``power-manager-plugin`` (``plugin-9``) removed
    from both its property block and panel-1's ``plugin-ids`` array.
    Students have no sudo to act on power settings, so it was just
    confusing clutter.
    """
    ctx.runner.write(PANEL_DEFAULT, templates.read("xfce4-panel-default.xml"))


def configure_autostart(ctx: Context) -> None:
    """Hide the autostart entries students can't do anything useful with."""
    hidden = templates.read("autostart-hidden.desktop")
    for name in HIDDEN_AUTOSTART:
        ctx.runner.write(AUTOSTART_DIR / name, hidden)
