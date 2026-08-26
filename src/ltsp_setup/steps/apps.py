"""Installing the applications students and staff actually use.

Each installer is written to be safe to run twice, because a stage can be
re-run after a failed boot.
"""

from __future__ import annotations

from pathlib import Path

from ltsp_setup import templates
from ltsp_setup.stages import Context
from ltsp_setup.steps.common import apt_install, apt_update

KEYRING_DIR = Path("/usr/share/keyrings")
SOURCES_DIR = Path("/etc/apt/sources.list.d")
PROFILE_D = Path("/etc/profile.d")

RACKET_DOWNLOAD_PAGE = "https://download.racket-lang.org"


def install_all(ctx: Context) -> None:
    """Install everything turned on in the ``[apps]`` settings."""
    apps = ctx.settings.apps
    if apps.java:
        install_java(ctx)
    if apps.racket:
        install_racket(ctx)
    if apps.chrome:
        install_chrome(ctx)
    if apps.vscode:
        install_vscode(ctx)
    if apps.rust:
        install_rust(ctx)
    if apps.gimp:
        install_gimp(ctx)
    if apps.shotcut:
        install_shotcut(ctx)
    if apps.simplescreenrecorder:
        install_simplescreenrecorder(ctx)
    if apps.extra_packages:
        apt_install(ctx, list(apps.extra_packages))


def install_java(ctx: Context) -> None:
    """Install the JDK from Ubuntu's own repositories."""
    apt_install(ctx, [ctx.settings.apps.java_package])


def install_racket(ctx: Context) -> None:
    """Install Racket, either from the PPA or from the upstream installer."""
    apps = ctx.settings.apps
    if apps.racket_source == "ppa":
        _install_racket_from_ppa(ctx)
    else:
        _install_racket_from_upstream(ctx)


def _install_racket_from_ppa(ctx: Context) -> None:
    """Add ppa:plt/racket and install from it.

    This is the maintained Racket PPA.  It runs a release or two behind
    upstream, but it upgrades along with everything else on the machine
    instead of needing a re-run of an installer script.
    """
    ctx.runner.run(["add-apt-repository", "-y", ctx.settings.apps.racket_ppa])
    apt_update(ctx)
    apt_install(ctx, ["racket"])


def _install_racket_from_upstream(ctx: Context) -> None:
    """Fetch and run the newest official Racket installer.

    The version is resolved at install time from the download site rather
    than pinned here, so this always lands on the current release.
    """
    version = _latest_racket_version(ctx)
    installer = f"racket-{version}-x86_64-linux-cs.sh"
    url = f"{RACKET_DOWNLOAD_PAGE}/installers/{version}/{installer}"
    ctx.runner.run(["wget", "-q", "-O", f"/tmp/{installer}", url])
    ctx.runner.run(
        ["sh", f"/tmp/{installer}", "--unix-style", "--create-dir", "--dest", "/usr/"]
    )
    ctx.runner.remove([Path(f"/tmp/{installer}")])


def _latest_racket_version(ctx: Context) -> str:
    """Ask the download site which release is current.

    Returns:
        A version string such as ``"9.3"``.  During a dry run, when nothing
        is actually fetched, this returns ``"<latest>"`` so the printed
        commands still read sensibly.
    """
    if ctx.runner.dry_run:
        return "<latest>"
    result = ctx.runner.run(
        ["curl", "-fsSL", f"{RACKET_DOWNLOAD_PAGE}/all-versions.html"], capture=True
    )
    import re

    versions: list[str] = re.findall(r"/releases/(\d+\.\d+(?:\.\d+)?)/", result.stdout)
    if not versions:
        raise RuntimeError(
            "Could not work out the current Racket version from "
            f"{RACKET_DOWNLOAD_PAGE}. Pin one with apps.racket_source = 'ppa' "
            "or report this."
        )

    def key(v: str) -> tuple[int, ...]:
        return tuple(int(part) for part in v.split("."))

    return max(set(versions), key=key)


def install_chrome(ctx: Context) -> None:
    """Install Google Chrome from Google's .deb.

    The .deb drops in Google's own apt source, so Chrome updates with the
    rest of the system afterwards.
    """
    deb = Path("/tmp/google-chrome-stable_current_amd64.deb")
    ctx.runner.run(
        [
            "wget",
            "-q",
            "-O",
            str(deb),
            "https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb",
        ]
    )
    apt_install(ctx, [str(deb)])
    ctx.runner.remove([deb])


def install_vscode(ctx: Context) -> None:
    """Install VS Code from Microsoft's apt repository.

    Uses the deb822 ``.sources`` form and a keyring under
    ``/usr/share/keyrings``, which is what current Debian/Ubuntu practice
    wants; the old ``apt-key``/``.list`` approach is deprecated.
    """
    keyring = KEYRING_DIR / "microsoft.gpg"
    ctx.runner.run_shell(
        "wget -qO- https://packages.microsoft.com/keys/microsoft.asc "
        f"| gpg --dearmor --yes -o {keyring}"
    )
    ctx.runner.run(["chmod", "0644", str(keyring)])
    ctx.runner.write(SOURCES_DIR / "vscode.sources", templates.read("vscode.sources"))
    apt_update(ctx)
    apt_install(ctx, ["code"])


def install_rust(ctx: Context) -> None:
    """Install one shared Rust toolchain that every user can run.

    rustup normally installs per-user, which on a lab machine means every
    student downloads their own several-hundred-megabyte toolchain into a
    home directory that lives on the server's NFS share.  Instead the
    toolchain goes in ``/usr/local`` once, owned by root and read-only to
    students, and a ``profile.d`` snippet puts it on everyone's PATH.

    Students can still ``cargo install`` their own crates: CARGO_HOME is
    left unset for them, so cargo falls back to ``~/.cargo`` as usual.
    """
    apps = ctx.settings.apps
    rustup_home = apps.rustup_home
    cargo_home = apps.cargo_home

    ctx.runner.mkdir(rustup_home)
    ctx.runner.mkdir(cargo_home)
    ctx.runner.run_shell(
        "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs "
        "| env RUSTUP_HOME=" + str(rustup_home) + " CARGO_HOME=" + str(cargo_home) + " "
        "sh -s -- -y --no-modify-path --profile default"
    )
    # World-readable and executable, but only root can change it.
    ctx.runner.run(["chmod", "-R", "a+rX", str(rustup_home), str(cargo_home)])
    ctx.runner.write(
        PROFILE_D / "rust.sh",
        templates.render(
            "rust.sh",
            {"RUSTUP_HOME": rustup_home, "CARGO_BIN": cargo_home / "bin"},
        ),
        mode=0o644,
    )


def install_gimp(ctx: Context) -> None:
    """Install GIMP."""
    apt_install(ctx, ["gimp"])


def install_shotcut(ctx: Context) -> None:
    """Install Shotcut, for the AP project's required video demos."""
    apt_install(ctx, ["shotcut"])


def install_simplescreenrecorder(ctx: Context) -> None:
    """Install SimpleScreenRecorder, for the AP project's required video demos."""
    apt_install(ctx, ["simplescreenrecorder"])
