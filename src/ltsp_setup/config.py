"""Settings for an LTSP deployment.

Defaults live here.  Any of them can be overridden in a TOML file, which is
looked for at ``$LTSP_SETUP_CONFIG``, then ``./ltsp-setup.toml``, then
``/etc/ltsp-setup.toml``.  Only the keys you want to change need to appear::

    admin_user = "sysadmin"

    [networking]
    hostname = "200-231-server.dupontmanual.org"

    [mirrors]
    mint_version = "zena"
"""

from __future__ import annotations

import ipaddress
import os
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any, get_origin, get_type_hints

CONFIG_ENV_VAR = "LTSP_SETUP_CONFIG"

CONFIG_SEARCH_PATH = (
    Path("ltsp-setup.toml"),
    Path("/etc/ltsp-setup.toml"),
)


@dataclass(frozen=True)
class Mirrors:
    """Package mirrors written to official-package-repositories.list."""

    # Purdue Linux Users Group (plug-mirror.rcac.purdue.edu): geographically
    # close to the school district, likely on a fast link, and confirmed to
    # carry both "zena" and "noble" by browsing its directory listing.
    mint_mirror: str = "https://plug-mirror.rcac.purdue.edu/mint"
    # Mint 22.3 is "zena"; 22.2 was "zara", 22.1 "xia", 22 "wilma".
    mint_version: str = "zena"
    mint_repos: str = "main upstream import backport"
    ubuntu_mirror: str = "https://plug-mirror.rcac.purdue.edu/ubuntu"
    # Mint 22.x is built on Ubuntu 24.04 "noble".
    ubuntu_version: str = "noble"
    ubuntu_repos: str = "main restricted universe multiverse"
    # Purdue mirrors noble-security too (synced 4x/day), so security updates
    # come from the same fast mirror rather than security.ubuntu.com.
    ubuntu_security_mirror: str = "https://plug-mirror.rcac.purdue.edu/ubuntu"


@dataclass(frozen=True)
class Networking:
    """Server networking.

    ``nic_for_internet`` gets its address by DHCP from the school network.
    ``nic_for_ltsp`` is the static-addressed NIC facing the thin clients.
    """

    nic_for_internet: str = "enp1s0"
    nic_for_ltsp: str = "enp2s0"
    hostname: str = "200-231-server.dupontmanual.org"
    alt_hostnames: tuple[str, ...] = ("200-231-server",)
    ltsp_address: str = "192.168.67.1"
    ltsp_prefix: int = 24
    # NICs to define but leave down (extra ports on a multi-port card).
    nics_disabled: tuple[str, ...] = ()

    # Optional, and worth setting.  Interface names are assigned from PCI
    # enumeration order, so they differ between the test VM and the real
    # server, and can move when a card is reseated.  Give a MAC address here
    # and netplan matches on that instead, renaming the interface to the
    # name above.  The lab assigns these MACs to the server VM, so the test
    # VM and the real machine can then share one config.
    mac_for_internet: str = ""
    mac_for_ltsp: str = ""

    @property
    def ltsp_cidr(self) -> str:
        return f"{self.ltsp_address}/{self.ltsp_prefix}"

    @property
    def ltsp_subnet(self) -> str:
        """The thin clients' whole network, e.g. ``192.168.67.0/24``."""
        return str(ipaddress.ip_interface(self.ltsp_cidr).network)


@dataclass(frozen=True)
class Apps:
    """Which applications to install on both the server and the clients."""

    java: bool = True
    java_package: str = "openjdk-17-jdk"

    racket: bool = True
    # "ppa"      -> ppa:plt/racket, apt-managed, currently 9.1 on noble
    # "upstream" -> racket-lang.org installer, always the newest release
    racket_source: str = "ppa"
    racket_ppa: str = "ppa:plt/racket"

    chrome: bool = True
    # Chrome's cache otherwise lives inside the NFS-mounted profile, so every
    # cache read/write crosses the network -- likely cause of slow concurrent
    # cold starts (Todd, 2026-08-26). Capped and moved to tmpfs instead; see
    # steps/common.py::configure_chrome_cache_policy.
    chrome_disk_cache_mb: int = 100
    vscode: bool = True

    rust: bool = True
    # Shared rustup/cargo roots so every student gets rustc and cargo on PATH
    # without a per-user multi-hundred-megabyte toolchain download.
    rustup_home: Path = field(default_factory=lambda: Path("/usr/local/rustup"))
    cargo_home: Path = field(default_factory=lambda: Path("/usr/local/cargo"))

    # Students need to record video of their running programs for the AP
    # project (Todd, 2026-08-26) -- carried over from last year's image.
    gimp: bool = True
    shotcut: bool = True
    simplescreenrecorder: bool = True

    # Used by a separate Claude session's intro-to-Linux material
    # (Todd, 2026-08-27).
    tree: bool = True
    cowsay: bool = True
    figlet: bool = True

    extra_packages: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.racket_source not in ("ppa", "upstream"):
            raise ValueError(
                f"apps.racket_source must be 'ppa' or 'upstream', "
                f"not {self.racket_source!r}."
            )


@dataclass(frozen=True)
class Lab:
    """Settings for the libvirt test lab that runs on your workstation."""

    # Both of these live under libvirt's own storage directory on purpose.
    # With qemu:///system, QEMU runs as the libvirt-qemu user under an
    # AppArmor profile that grants access here and denies it in home
    # directories, so an ISO or disk under ~ fails with a permission error
    # that looks nothing like a permission error.
    pool_dir: Path = field(default_factory=lambda: Path("/var/lib/libvirt/images"))
    # The libvirt storage pool whose target directory is pool_dir. Overlay
    # disks are created through this pool (`virsh vol-create-as`) rather than
    # a raw `qemu-img create`, because pool_dir is root-owned 0711 -- only
    # libvirtd, running as root, can create files there directly.
    pool_name: str = "default"
    iso: Path = field(
        default_factory=lambda: Path("/var/lib/libvirt/images")
        / "linuxmint-22.3-xfce-64bit.iso"
    )
    golden_name: str = "mint-22.3-fresh"
    server_name: str = "ltsp-server"
    client_name: str = "ltsp-client"
    network_name: str = "ltsp"
    golden_disk_gb: int = 40
    server_ram_mb: int = 8192
    server_vcpus: int = 4
    client_ram_mb: int = 4096
    client_vcpus: int = 2
    client_disk_gb: int = 40
    connect_uri: str = "qemu:///system"


@dataclass(frozen=True)
class ClientTemplate:
    """The client-template VM the server hosts locally and images from.

    Todd's call (2026-08-19): the production server runs KVM itself and
    hosts the client template as a local libvirt VM, so imaging is always a
    local disk operation. The VM's own disk stays qcow2 (COW, snapshotting);
    ``ltsp image`` wants a raw or VMDK source, so it's converted to raw with
    ``qemu-img convert`` right before each image build, then deleted again —
    see ``steps/image.py::build_image``.
    """

    vm_name: str = "ltsp-client-template"
    disk_path: Path = field(
        default_factory=lambda: Path(
            "/var/lib/libvirt/images/ltsp-client-template.qcow2"
        )
    )
    disk_gb: int = 40
    ram_mb: int = 4096
    vcpus: int = 2
    # libvirt's built-in NAT network, for internet access while the template
    # is being set up and updated. Not the isolated lab "ltsp" network.
    network: str = "default"
    # Optional stable MAC, same idea as Networking.mac_for_*.
    mac: str = ""
    os_variant: str = "ubuntu24.04"
    connect_uri: str = "qemu:///system"
    iso: Path = field(
        default_factory=lambda: Path("/var/lib/libvirt/images")
        / "linuxmint-22.3-xfce-64bit.iso"
    )
    # Name of the raw source image built under /srv/ltsp for `ltsp image`.
    image_name: str = "ltsp-client-template"
    shutdown_timeout_s: int = 120

    # Public HTTPS clone URL. The template has no deploy key and shouldn't
    # need one -- `image refresh` re-clones the checkout on every run, since
    # `client cleanup` deletes it again before each build (2026-09-09).
    repo_url: str = "https://github.com/toddobryan/ltsp-setup.git"
    # How long to wait for the template to boot far enough to accept SSH.
    boot_timeout_s: int = 300
    # Private key to reach the template with. Empty means the admin user's
    # own ~/.ssh/id_ed25519, which is what the template authorizes. Named
    # explicitly rather than left to ssh's defaults because `image refresh`
    # runs under sudo, and root's ~/.ssh has no key in it at all -- which is
    # exactly how this failed the first time (2026-09-09).
    ssh_key: str = ""


@dataclass(frozen=True)
class SmokeTest:
    """The netboot check run against a fresh build before it is left live.

    ``vm_name`` is a diskless libvirt VM bridged onto the LTSP network, with
    ``<boot dev='network'/>`` and no disk at all -- a thin client in every
    respect except that it lives on the server. Booting it is the only way
    to find out whether an image actually works without walking to a lab
    machine, which an unattended rebuild obviously can't do.

    The check watches for two things in turn, because they fail differently
    and the difference is the whole diagnosis: a *fresh DHCP lease* (PXE,
    TFTP and the kernel got that far) and then an *epoptes-client
    connection* back to the server (the squashfs mounted and userspace came
    all the way up). iPXE itself never does the second one, so it can't
    produce a false pass.
    """

    vm_name: str = "pxe-test-client"
    connect_uri: str = "qemu:///system"
    # dnsmasq's lease database -- world-readable, and the only place the
    # test client's address can be looked up before it answers anything.
    lease_file: Path = field(
        default_factory=lambda: Path("/var/lib/misc/dnsmasq.leases")
    )
    # What epoptes-client connects back to. It is in CLIENT_PACKAGES, so
    # every image this tool builds has it; see steps/client.py.
    agent_port: int = 789
    # A cold netboot of a several-gigabyte squashfs over NFS is not quick.
    boot_timeout_s: int = 600
    shutdown_timeout_s: int = 120


@dataclass(frozen=True)
class ImageRefresh:
    """The unattended rebuild that runs from a systemd timer.

    Todd's ask (2026-09-12): apt-upgrade the template, rebuild, and make the
    result live over the weekend, "keeping the last proven-to-boot image
    available for quick rollback". That last clause is what
    ``keep_rollback_images`` buys -- see steps/image.py::prune_published_images.
    """

    # systemd OnCalendar= expression. Saturday small hours: nobody is logged
    # in, and a failure has the whole weekend of slack before Monday.
    on_calendar: str = "Sat *-*-* 02:00:00"
    # Spread over half an hour so a rebuild never lands at exactly the same
    # instant as every other timer on the box.
    randomized_delay_s: int = 1800
    # Which client stages to run on the template first. Just `mirrors` (apt
    # update and upgrade) -- `apps` and `desktop` change what is installed
    # or configured, which is a human's decision, not a weekly one.
    stages: tuple[str, ...] = ("mirrors",)
    # How many superseded builds to keep alongside the live one. 1 means
    # last week's image stays on disk and in the PXE menu, so reverting is
    # `image set-default <name>` and a reboot, with no rebuild.
    keep_rollback_images: int = 1


@dataclass(frozen=True)
class Students:
    """Where student accounts live on the server, and how to tell them apart
    from admin accounts.

    NFS-exported to the clients, but account and settings operations run
    here on the server itself -- see ``steps/students.py``. ``uid_min``/
    ``uid_max`` bound the normal-user range (below it: system accounts;
    ``nobody`` and friends sit at 65534 and above on Debian/Ubuntu, hence
    60000 rather than the UINT_MAX default some distros use).
    ``protected_usernames`` are real accounts inside that range that are
    never students -- always unioned with ``Settings.admin_user``, so a
    config mistake can't accidentally make the admin account eligible for
    bulk student operations.
    """

    home_root: Path = field(default_factory=lambda: Path("/home"))
    uid_min: int = 1000
    uid_max: int = 60000
    protected_usernames: tuple[str, ...] = ("toddobryan", "student")

    # Where `student push` drops a file inside each account. Relative to
    # the student's home directory: on a thin client the Desktop is where a
    # handout is actually in front of them when they log in.
    push_dest: Path = field(default_factory=lambda: Path("Desktop"))

    # Maps the first whitespace-delimited token of a roster CSV row's
    # "Course" field to a comma-joinable Unix group name (or names, for a
    # student enrolled in more than one mapped section) -- see
    # steps/roster.py::import_roster. Fall 2026: alternating Red/White days,
    # 4 periods each -- Todd's own r3/w1 are his planning periods.
    course_groups: dict[str, str] = field(
        default_factory=lambda: {
            "45639741-1": "r1",
            "45639741-2": "r4",
            "45639741-3": "w2",
            "45639741-4": "w3",
            "45639741-5": "w4",
            "42300011-7": "r2",
            "45229711-1012": "hr",
            "45000011-2315": "sa",
            "45000011-2415": "sa",
            "85000013-421": "sa",
        }
    )


@dataclass(frozen=True)
class Settings:
    """Everything the setup commands need to know."""

    admin_user: str = "sysadmin"

    # Passed to every apt-get invocation as -o DPkg::Lock::Timeout=. Without
    # it, apt exits immediately if another process holds the dpkg lock --
    # which unattended-upgrades routinely does in the middle of the night,
    # exactly when the weekly image rebuild runs. Waiting ten minutes for
    # the lock beats failing the whole rebuild over a few seconds of
    # contention.
    apt_lock_timeout_s: int = 600

    # NFS server threads (/etc/nfs.conf.d/ltsp-setup.conf). The default of 8
    # was saturating on 2026-10-05: with ~20 clients booting and logging in,
    # about 3% of requests found no idle thread, while the /home disks sat at
    # 92-96% busy. Threads are cheap (~1MB each); 64 is the floor Todd chose.
    nfsd_threads: int = 64

    # MENU_TIMEOUT in ltsp.conf's [server] section: how long, in
    # milliseconds, `ltsp ipxe`'s generated boot menu waits before booting
    # DEFAULT_IMAGE. -1 is special -- it hides the menu entirely and boots
    # DEFAULT_IMAGE straight away.
    #
    # Hidden by default (Todd, 2026-09-15). The menu's only real audience is
    # a student at a thin client, and the only thing it lets them do is pick
    # an image that isn't the one they are supposed to be on -- which is why
    # old builds were being deleted in the first place (2026-08-27). Now that
    # `image prune` deliberately keeps a rollback around, there is always a
    # second entry to pick wrongly, so hiding the menu matters more than it
    # did. Set it to 5000 to get the menu back while debugging a bad build at
    # a machine; the rollback path itself (`image set-default`, reboot) does
    # not need it.
    pxe_menu_timeout_ms: int = -1

    # What `image show-menu` sets MENU_TIMEOUT to when the menu has to come
    # back -- a bad image is live and someone at a client needs to pick the
    # rollback, or needs iPXE's own options (shell, memtest, boot from local
    # disk) with no working LTSP image at all. Long enough to read and act
    # on at a machine that is booting, short enough not to hold up a room
    # full of clients that are fine.
    pxe_menu_visible_timeout_ms: int = 10000

    mirrors: Mirrors = field(default_factory=Mirrors)
    networking: Networking = field(default_factory=Networking)
    apps: Apps = field(default_factory=Apps)
    lab: Lab = field(default_factory=Lab)
    client_template: ClientTemplate = field(default_factory=ClientTemplate)
    smoke_test: SmokeTest = field(default_factory=SmokeTest)
    image_refresh: ImageRefresh = field(default_factory=ImageRefresh)
    students: Students = field(default_factory=Students)


def _coerce(value: Any, target_type: Any) -> Any:
    """Convert a TOML value to the type a dataclass field wants.

    TOML has no tuple or path types, so a ``tuple[str, ...]`` field arrives as
    a list and a ``Path`` field as a string.  Both are converted here so the
    rest of the code can rely on the annotated types being the real ones.
    """
    if target_type is Path:
        return Path(str(value)).expanduser()
    if get_origin(target_type) is tuple and isinstance(value, list):
        return tuple(value)
    return value


def _apply(instance: Any, overrides: dict[str, Any], where: str) -> Any:
    """Return a copy of ``instance`` with ``overrides`` applied recursively."""
    by_name = {f.name for f in fields(instance)}
    # Resolved rather than read off the fields: this module uses postponed
    # annotations, so ``field.type`` is the string "tuple[str, ...]" and not
    # anything you can compare against.
    hints = get_type_hints(type(instance))
    changes: dict[str, Any] = {}
    for key, value in overrides.items():
        if key not in by_name:
            known = ", ".join(sorted(by_name))
            raise ValueError(
                f"Unknown setting {where}{key!r}. Known settings here: {known}."
            )
        current = getattr(instance, key)
        if is_dataclass(current) and not isinstance(current, type):
            if not isinstance(value, dict):
                raise ValueError(f"Setting {where}{key!r} must be a TOML table.")
            changes[key] = _apply(current, value, f"{where}{key}.")
        else:
            changes[key] = _coerce(value, hints[key])
    return replace(instance, **changes)


def find_config_file() -> Path | None:
    """The first config file that exists, or None."""
    from_env = os.environ.get(CONFIG_ENV_VAR)
    if from_env:
        path = Path(from_env).expanduser()
        if not path.is_file():
            raise FileNotFoundError(
                f"{CONFIG_ENV_VAR} points at {path}, which does not exist."
            )
        return path
    for candidate in CONFIG_SEARCH_PATH:
        if candidate.is_file():
            return candidate
    return None


def load(config_file: Path | None = None) -> Settings:
    """Load settings, applying overrides from a TOML file if there is one."""
    path = config_file or find_config_file()
    if path is None:
        return Settings()
    with open(path, "rb") as handle:
        overrides = tomllib.load(handle)
    settings: Settings = _apply(Settings(), overrides, "")
    return settings
