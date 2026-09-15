"""Work that is identical on the server and on the clients."""

from __future__ import annotations

import re
from pathlib import Path

from ltsp_setup import templates
from ltsp_setup.runner import StepFailed
from ltsp_setup.stages import Context

SOURCES_LIST = Path("/etc/apt/sources.list.d/official-package-repositories.list")
DCONF_PROFILE = Path("/etc/dconf/profile/user")
DCONF_LOCAL_DIR = Path("/etc/dconf/db/local.d")
AUTOSTART_DIR = Path("/etc/xdg/autostart")
CHROME_POLICY_DIR = Path("/etc/opt/chrome/policies/managed")
MIME_DIR = Path("/usr/share/mime")
MIMEAPPS_LIST = Path("/etc/xdg/mimeapps.list")
ICON_THEME_ROOT = Path("/usr/share/icons")
LOCAL_SBIN = Path("/usr/local/sbin")
PAM_LIGHTDM = Path("/etc/pam.d/lightdm")

# Marks whether the session-lock lines have already been inserted into
# /etc/pam.d/lightdm, so a re-run doesn't insert them twice.
SESSION_LOCK_MARKER = "# ltsp-setup: concurrent-login lock"

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


def _apt(ctx: Context, *args: str) -> list[str]:
    """An ``apt-get`` argv that waits for the dpkg lock rather than failing.

    Without ``DPkg::Lock::Timeout``, apt gives up the instant it finds the
    lock held and exits non-zero. ``unattended-upgrades`` holds it for
    minutes at a time, in the small hours, which is exactly when the weekly
    image rebuild runs -- so the default is a rebuild that fails for a
    reason that has nothing to do with the image. Waiting is the right
    answer; ``admin_user``-adjacent config carries how long (see
    ``Settings.apt_lock_timeout_s``).
    """
    return [
        "apt-get",
        "-o",
        f"DPkg::Lock::Timeout={ctx.settings.apt_lock_timeout_s}",
        *args,
    ]


def apt_update(ctx: Context) -> None:
    """Refresh the package lists."""
    ctx.runner.run(_apt(ctx, "update"))


def apt_upgrade(ctx: Context) -> None:
    """Refresh package lists and upgrade everything installed."""
    apt_update(ctx)
    ctx.runner.run(
        _apt(ctx, "upgrade", "-y"),
        env={"DEBIAN_FRONTEND": "noninteractive"},
    )


def apt_autoremove(ctx: Context) -> None:
    """Remove packages nothing needs any more, config files included.

    ``--purge`` because this runs against the client template, whose whole
    disk becomes the shipped image: a removed package's leftover config is
    dead weight on every thin client.

    Worth knowing what this does *not* do here, since it's the reason it
    was asked for: it will not remove old kernels. On Mint, kernels are
    marked manually installed (mintupdate installs ``linux-image-<version>``
    directly rather than letting the ``-hwe`` metapackage pull it in), and
    ``autoremove`` only ever touches automatically-installed packages. On
    this server, ``apt-get autoremove --dry-run`` reports "0 to remove"
    with seven kernels on disk. See ``purge_old_kernels`` for that job.
    """
    ctx.runner.run(
        _apt(ctx, "autoremove", "--purge", "-y"),
        env={"DEBIAN_FRONTEND": "noninteractive"},
    )


# linux-image-7.0.0-31-generic, linux-headers-7.0.0-31-generic,
# linux-modules-extra-7.0.0-31-generic, ... but deliberately NOT the
# unversioned metapackages (linux-image-generic-hwe-24.04), which are what
# pull the next kernel in and must survive. The alternation puts the longer
# prefixes first so "image-unsigned" isn't half-matched by "image".
_KERNEL_PACKAGE = re.compile(
    r"^linux-(?:image-unsigned|modules-extra|image|headers|modules|tools)-"
    r"(\d+(?:\.\d+)*-\d+)-"
)
_KERNEL_VERSION = re.compile(r"^(\d+(?:\.\d+)*-\d+)")


def _version_key(version: str) -> tuple[int, ...]:
    """Sortable form of a kernel version like ``7.0.0-31``.

    Compared numerically rather than as text, because "7.0.0-9" sorts after
    "7.0.0-31" as a string and picking the wrong "newest" here would purge
    the kernel the image is supposed to ship.
    """
    return tuple(int(part) for part in re.split(r"[.-]", version))


def running_kernel_version(ctx: Context) -> str | None:
    """The version part of ``uname -r``, e.g. ``7.0.0-31`` — or None."""
    match = _KERNEL_VERSION.match(ctx.runner.read_command(["uname", "-r"]).strip())
    return match.group(1) if match else None


def installed_kernels(ctx: Context) -> dict[str, list[str]]:
    """Installed kernel packages, grouped by the version they belong to."""
    # Patterns that match nothing make dpkg-query exit non-zero, which is not
    # an error here -- it just means no kernel of that shape is installed.
    listing = ctx.runner.read_command(
        [
            "dpkg-query",
            "-W",
            "-f=${db:Status-Abbrev}${binary:Package}\n",
            "linux-image-*",
            "linux-headers-*",
            "linux-modules-*",
            "linux-tools-*",
        ]
    )
    found: dict[str, list[str]] = {}
    for line in listing.splitlines():
        # "${db:Status-Abbrev}" is a three-character field, e.g. "ii ".
        # Anything but "ii" is half-installed, deconfigured or merely known
        # about, and has no files in /boot to reclaim.
        if not line.startswith("ii"):
            continue
        package = line[3:].strip()
        match = _KERNEL_PACKAGE.match(package)
        if match:
            found.setdefault(match.group(1), []).append(package)
    return found


def purge_old_kernels(ctx: Context) -> list[str]:
    """Purge every installed kernel except the newest and the running one.

    Old kernels are what actually fill ``/boot`` (Todd, 2026-08-27, after
    an ``autoremove`` left ``6.14.0-37`` sitting next to ``7.0.0-30``), and
    every one of them is carried in the shipped image at roughly a hundred
    megabytes apiece. ``apt autoremove`` cannot help: Mint marks kernels
    manually installed, so autoremove never considers them.

    Two versions are kept, not one, and the running kernel is never
    removed. Removing a running kernel means forcing dpkg past its own
    safety check, which is not something to do unattended at one in the
    morning against the machine that becomes every client's root
    filesystem.

    That leaves the template at two kernels after an upgrade rather than
    one -- the one it booted and the one just installed. It does not
    accumulate beyond that: ``image refresh`` starts the template cold
    every run, GRUB boots the newest, and so the *previous* run's kernel is
    no longer running and gets purged by the next one. Two is the steady
    state, against seven on this server today.

    Returns:
        The package names purged, newest-first by version.
    """
    running = running_kernel_version(ctx)
    by_version = installed_kernels(ctx)
    if running is None:
        ctx.runner.announce(
            "Could not tell which kernel is running; leaving old kernels alone"
        )
        return []
    if len(by_version) <= 1:
        return []

    newest = max(by_version, key=_version_key)
    doomed = sorted(set(by_version) - {newest, running}, key=_version_key, reverse=True)
    packages = [name for version in doomed for name in sorted(by_version[version])]
    if not packages:
        return []

    ctx.runner.announce(
        f"Purging {len(doomed)} old kernel(s) ({', '.join(doomed)}); keeping "
        f"{newest} (newest) and {running} (running)"
    )
    ctx.runner.run(
        _apt(ctx, "purge", "-y", *packages),
        env={"DEBIAN_FRONTEND": "noninteractive"},
    )
    return packages


def apt_install(ctx: Context, packages: list[str], *, recommends: bool = True) -> None:
    """Install packages non-interactively.

    Args:
        ctx: Settings and runner.
        packages: What to install.  An empty list is a no-op.
        recommends: Pass False to skip recommended packages.
    """
    if not packages:
        return
    argv = _apt(ctx, "install", "-y")
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


def _insert_after(content: str, after: str, new_lines: list[str], path: Path) -> str:
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == after:
            lines[i + 1 : i + 1] = new_lines
            return "\n".join(lines) + "\n"
    raise StepFailed(f"{path} has no {after!r} line to insert after.")


def configure_session_lock(ctx: Context) -> None:
    """Refuse a second concurrent login for the same student account.

    Both thin clients mount the same NFS-shared home directory, so two
    simultaneous logins as the same student corrupt things like browser
    profile locks -- see data/ltsp-session-lock-check.sh for the full
    mechanism (a pam_exec-driven lock directory, refreshed every 60s by an
    autostart heartbeat while the session is active, released cleanly on
    logout, and auto-recovered if a client goes away without logging out).

    Patches /etc/pam.d/lightdm rather than overwriting it wholesale: it's a
    package-owned conffile, and a full templated replacement would drift
    from whatever the lightdm package actually ships on the next upgrade
    (Todd, 2026-08-26) -- the same reasoning as image.py's DEFAULT_IMAGE
    line-patching versus configure_ltsp's full-file overwrite.
    """
    for name, mode in (
        ("ltsp-session-lock-check.sh", 0o755),
        ("ltsp-session-lock-release.sh", 0o755),
        ("ltsp-session-heartbeat.sh", 0o755),
    ):
        ctx.runner.write(LOCAL_SBIN / name, templates.read(name), mode=mode)
    ctx.runner.write(
        AUTOSTART_DIR / "ltsp-session-heartbeat.desktop",
        templates.read("ltsp-session-heartbeat.desktop"),
    )

    if not ctx.runner.exists(PAM_LIGHTDM):
        # lightdm isn't installed yet -- true during a from-scratch dry-run
        # preview, before the apps/ltsp stages have run. Nothing to patch
        # yet; a real run gets here only after lightdm genuinely exists.
        return
    content = ctx.runner.read_text(PAM_LIGHTDM)
    if SESSION_LOCK_MARKER in content:
        return
    content = _insert_after(
        content,
        "@include common-auth",
        [
            SESSION_LOCK_MARKER,
            "auth    requisite       pam_exec.so quiet stdout "
            f"{LOCAL_SBIN / 'ltsp-session-lock-check.sh'}",
        ],
        PAM_LIGHTDM,
    )
    content = _insert_after(
        content,
        "@include common-session",
        [
            "session optional        pam_exec.so quiet type=close_session "
            f"{LOCAL_SBIN / 'ltsp-session-lock-release.sh'}",
        ],
        PAM_LIGHTDM,
    )
    ctx.runner.write(PAM_LIGHTDM, content, mode=0o644)


def configure_chrome_singleton_cleanup(ctx: Context) -> None:
    """Remove Chrome's stale SingletonLock at every session start.

    Safe only because of configure_session_lock: a fresh login can't happen
    while a real session is genuinely still active elsewhere, so any lock
    still present at this point is always left over from a session that
    ended uncleanly (crash, power loss, forced logout), never one that's
    still using Chrome right now. Without configure_session_lock in place,
    unconditionally deleting this would risk pulling the rug out from under
    a real second session (Todd, 2026-08-26).
    """
    ctx.runner.write(
        LOCAL_SBIN / "chrome-singleton-cleanup.sh",
        templates.read("chrome-singleton-cleanup.sh"),
        mode=0o755,
    )
    ctx.runner.write(
        AUTOSTART_DIR / "chrome-singleton-cleanup.desktop",
        templates.read("chrome-singleton-cleanup.desktop"),
    )


def configure_chrome_cache_policy(ctx: Context) -> None:
    """Move Chrome's cache off NFS-mounted home and cap its size.

    The cache otherwise lives inside ~/.config/google-chrome, which is the
    NFS-mounted profile -- every cache read/write crosses the network, the
    likely cause of Chrome being slow to open when several students launch
    it at once, plus unbounded growth eating into each student's NFS-homed
    quota (flagged 2026-08-26, docs/desktop-polish-todo.md). DiskCacheDir
    points at /dev/shm (tmpfs, already mounted on every machine, no fstab
    entry needed) with Chrome's own ${user_name} policy-variable expansion
    so different students who use the same client over time never share a
    cache directory. Actual profile data (bookmarks, cookies, history) stays
    on NFS so it's still persistent across sessions -- only the cache moves.
    """
    size_bytes = ctx.settings.apps.chrome_disk_cache_mb * 1024 * 1024
    ctx.runner.write(
        CHROME_POLICY_DIR / "disk-cache.json",
        templates.render(
            "chrome-cache-policy.json", {"DISK_CACHE_SIZE_BYTES": size_bytes}
        ),
    )
