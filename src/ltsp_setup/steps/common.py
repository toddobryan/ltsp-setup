"""Work that is identical on the server and on the clients."""

from __future__ import annotations

from pathlib import Path

from ltsp_setup import templates
from ltsp_setup.stages import Context

SOURCES_LIST = Path("/etc/apt/sources.list.d/official-package-repositories.list")
DCONF_PROFILE = Path("/etc/dconf/profile/user")
DCONF_LOCAL_DIR = Path("/etc/dconf/db/local.d")
AUTOSTART_DIR = Path("/etc/xdg/autostart")
MIME_DIR = Path("/usr/share/mime")
MIMEAPPS_LIST = Path("/etc/xdg/mimeapps.list")
ICON_THEME_ROOT = Path("/usr/share/icons")

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

    Right now this is only the clock format -- system-wide, not per-student
    (see steps/students.py::configure_skel for per-student defaults, which
    go through /etc/skel instead since dconf's own system database applies
    the same values to every account regardless).
    """
    ctx.runner.write(DCONF_PROFILE, templates.read("dconf-profile-user"))
    ctx.runner.mkdir(DCONF_LOCAL_DIR)
    ctx.runner.write(
        DCONF_LOCAL_DIR / "01-datetime", templates.read("dconf-01-datetime")
    )
    ctx.runner.run(["dconf", "update"])


def configure_autostart(ctx: Context) -> None:
    """Hide the autostart entries students can't do anything useful with."""
    hidden = templates.read("autostart-hidden.desktop")
    for name in HIDDEN_AUTOSTART:
        ctx.runner.write(AUTOSTART_DIR / name, hidden)


def configure_racket_mime(ctx: Context) -> None:
    """Make .rkt files open in DrRacket by default, with a real file icon.

    System-wide, not per-student (steps/students.py) -- which app opens a
    .rkt file isn't something a student ever needs to customize, and the
    MIME database and icon themes live outside /home entirely, so
    /etc/skel can't reach either.

    The icon (data/application-x-racket.svg) is the same one already found
    installed by hand into every icon theme on the real server -- icon
    themes resolve a mime type's icon by name (application/x-racket ->
    application-x-racket), and nothing here ships that icon on its own, so
    without this a .rkt file just shows a generic file icon. Matches the
    server's own already-working approach of dropping it into every theme's
    scalable/mimetypes rather than relying on hicolor-fallback inheritance,
    since that's what's actually proven to work on this desktop stack.
    """
    ctx.runner.write(
        MIME_DIR / "packages" / "racket.xml", templates.read("racket-mime-type.xml")
    )
    ctx.runner.run(["update-mime-database", str(MIME_DIR)])
    ctx.runner.write(MIMEAPPS_LIST, templates.read("mimeapps-default.list"))

    icon = templates.read("application-x-racket.svg")
    for theme_dir in ctx.runner.list_dirs(ICON_THEME_ROOT):
        ctx.runner.write(
            theme_dir / "scalable" / "mimetypes" / "application-x-racket.svg",
            icon,
            show=False,
        )
