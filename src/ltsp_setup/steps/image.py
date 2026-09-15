"""Building the client netboot image from the local client-template VM.

The client-template VM is a normal desktop Mint install with LTSP's client
packages, set up with the ``client`` plan (see ``steps/client.py``). It lives
on the server itself, under KVM, so imaging is always a local disk
operation: shut the template off, convert its qcow2 disk to the raw image
``ltsp image`` wants, build the squashfs, and clean the raw copy back up.

This is deliberately not a ``Stage`` in the ``SERVER`` plan. Creating the
template VM needs a human at the console for the interactive Mint install,
the same reason ``lab build-golden`` is a standalone command rather than a
plan stage. ``build_image`` is meant to be re-run on demand (and later, from
a cron job) once the template exists.
"""

from __future__ import annotations

import re
import subprocess
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from ltsp_setup import templates
from ltsp_setup.runner import StepFailed
from ltsp_setup.stages import Context, entry_point
from ltsp_setup.steps import smoke
from ltsp_setup.steps.server import LTSP_CONF
from ltsp_setup.virt import Libvirt

SOURCE_IMAGE_DIR = Path("/srv/ltsp")

# Where `ltsp image` actually publishes each build -- LTSP's own default
# IMAGE_DIR, not something this tool configures.
PUBLISHED_IMAGE_DIR = Path("/srv/ltsp/images")

# Where `ltsp image` extracts each build's kernel/initrd -- LTSP's own
# default TFTP_DIR/ltsp, not something this tool configures. Note this is
# NOT what generates the boot menu: `ltsp ipxe` builds its item list from
# PUBLISHED_IMAGE_DIR (`list_img_names -i`, sorted ascending by name), and
# each item then boots the kernel/initrd found here under the same name.
# So a leftover directory here is invisible in the menu, while a leftover
# squashfs over there is selectable -- see `prune_published_images`.
TFTP_IMAGE_DIR = Path("/srv/tftp/ltsp")

# How often to poll `virsh domstate` while waiting for a shutdown.
POLL_INTERVAL_S = 2


def _libvirt(ctx: Context) -> Libvirt:
    return Libvirt(ctx.settings.client_template.connect_uri, ctx.runner)


def create_client_template(ctx: Context) -> None:
    """Start the one-time interactive Mint install for the client template.

    Same shape as ``lab/virt.py::build_golden``: a qcow2 disk and a spice
    console for the operator to install through by hand. Attached to
    ``client_template.network`` (libvirt's NAT network by default) rather
    than the lab's isolated network, so the template can reach the internet
    for package installs and updates.
    """
    ct = ctx.settings.client_template
    lv = _libvirt(ctx)
    lv.check_host_tools()
    if not ctx.runner.dry_run and not ct.iso.is_file():
        raise StepFailed(
            f"Mint ISO not found at {ct.iso}. Download it, or point "
            "client_template.iso at it in your config file."
        )
    ctx.runner.mkdir(ct.disk_path.parent)

    network = f"network={ct.network},model=virtio"
    if ct.mac:
        network += f",mac={ct.mac}"

    ctx.runner.run(
        [
            "virt-install",
            "--connect",
            ct.connect_uri,
            "--name",
            ct.vm_name,
            "--ram",
            str(ct.ram_mb),
            "--vcpus",
            str(ct.vcpus),
            "--disk",
            f"path={ct.disk_path},size={ct.disk_gb},format=qcow2,bus=virtio",
            "--cdrom",
            str(ct.iso),
            "--network",
            network,
            "--graphics",
            "spice",
            "--video",
            "qxl",
            "--os-variant",
            ct.os_variant,
        ]
    )


def shutdown_client_template(ctx: Context) -> None:
    """Shut the template VM down cleanly, forcing it off if it won't.

    A no-op (but still prints the command) if the VM is already off or
    doesn't exist — ``virsh shutdown`` against either just fails quietly
    (``check=False``), which is fine since the caller decides whether a
    missing VM is actually an error.
    """
    ct = ctx.settings.client_template
    lv = _libvirt(ctx)
    ctx.runner.announce(f"Shutting down {ct.vm_name} if it is running")
    lv.virsh("shutdown", ct.vm_name, check=False)
    if ctx.runner.dry_run:
        return

    deadline = time.monotonic() + ct.shutdown_timeout_s
    while time.monotonic() < deadline:
        if lv.domstate(ct.vm_name) == "shut off":
            return
        time.sleep(POLL_INTERVAL_S)

    ctx.runner.announce(
        f"{ct.vm_name} did not shut down within {ct.shutdown_timeout_s}s; "
        "forcing it off"
    )
    lv.virsh("destroy", ct.vm_name, check=False)


def start_client_template(ctx: Context) -> None:
    """Boot the template VM, unless it is already running."""
    ct = ctx.settings.client_template
    lv = _libvirt(ctx)
    if not ctx.runner.dry_run and not lv.domain_exists(ct.vm_name):
        raise StepFailed(
            f"No client-template VM named {ct.vm_name!r} at {ct.connect_uri}.\n"
            "Create one first with:  ltsp-setup image create-template --no-debug"
        )
    if lv.domstate(ct.vm_name) == "running":
        ctx.runner.announce(f"{ct.vm_name} is already running")
        return
    lv.virsh("start", ct.vm_name)


def wait_for_template_ssh(ctx: Context) -> str:
    """Wait for the template to boot and start accepting SSH, and return its IP.

    Two separate waits, because they fail differently: the VM has no address
    at all until its DHCP client comes up, and then sshd isn't listening for
    a while after that. Polls rather than sleeping a fixed amount, since a
    template that has packages to configure on boot is much slower than one
    that doesn't.
    """
    ct = ctx.settings.client_template
    lv = _libvirt(ctx)
    if ctx.runner.dry_run:
        return "<template-ip>"

    deadline = time.monotonic() + ct.boot_timeout_s
    address: str | None = None
    while time.monotonic() < deadline:
        address = lv.domifaddr(ct.vm_name)
        if address:
            break
        time.sleep(POLL_INTERVAL_S)
    if not address:
        raise StepFailed(
            f"{ct.vm_name} had no IPv4 address within {ct.boot_timeout_s}s. "
            f"Check it booted: virsh --connect {ct.connect_uri} console {ct.vm_name}"
        )
    ctx.runner.announce(f"{ct.vm_name} is at {address}")

    key = template_ssh_key(ctx)
    if not ctx.runner.exists(key):
        raise StepFailed(
            f"No SSH key at {key} to reach {ct.vm_name} with. Point "
            "client_template.ssh_key at one, or generate it with ssh-keygen "
            "and authorize it on the template."
        )

    while time.monotonic() < deadline:
        result = _ssh(ctx, address, "true", check=False, capture=True)
        if result.returncode == 0:
            return address
        # Refused/unreachable means sshd isn't up yet, so keep waiting. A
        # rejected key never resolves by waiting, though -- failing straight
        # away beats repeating the same denial until the timeout.
        if "Permission denied" in (result.stderr or ""):
            raise StepFailed(
                f"{ct.vm_name} ({address}) rejected {key}: "
                f"{(result.stderr or '').strip()}\n"
                f"That key has to be in {ctx.settings.admin_user}'s "
                "authorized_keys on the template."
            )
        time.sleep(POLL_INTERVAL_S)
    raise StepFailed(
        f"{ct.vm_name} ({address}) did not accept SSH within {ct.boot_timeout_s}s. "
        f"This needs {ctx.settings.admin_user}'s key already authorized on the "
        "template, which the golden image is meant to bake in -- see README."
    )


def template_ssh_key(ctx: Context) -> Path:
    """The private key to reach the template with.

    Defaults to the admin user's own key, which is what the template
    authorizes (the golden image bakes it in). Named explicitly rather than
    left to ssh's own defaults because everything here runs under ``sudo``,
    so ssh would otherwise look in ``/root/.ssh`` and find nothing -- the
    "Permission denied (publickey,password)" this failed with on its first
    real run (2026-09-09).
    """
    configured = ctx.settings.client_template.ssh_key
    if configured:
        return Path(configured).expanduser()
    return Path("/home") / ctx.settings.admin_user / ".ssh" / "id_ed25519"


def _ssh(
    ctx: Context,
    address: str,
    command: str,
    *,
    check: bool = True,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run one command on the template over SSH, as the admin user.

    ``BatchMode=yes`` so a missing key fails immediately instead of hanging
    on a password prompt that nothing is there to answer -- this has to work
    unattended, from cron, in the middle of the night.
    """
    return ctx.runner.run(
        [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=10",
            "-i",
            str(template_ssh_key(ctx)),
            f"{ctx.settings.admin_user}@{address}",
            command,
        ],
        check=check,
        capture=capture,
    )


def update_client_template(ctx: Context, stages: Sequence[str]) -> None:
    """Re-install this tool on the template, run stages there, then clean up.

    The template deliberately doesn't keep a checkout or venv between builds
    (``client cleanup`` deletes both, since its whole disk becomes the
    shipped image), so every run re-clones and re-bootstraps from scratch.
    That costs a minute and means the template always runs exactly what's on
    the repo's default branch, never a stale local copy -- the very bug that
    silently shipped an image without the session-lock work in it
    (2026-08-26, see docs/desktop-polish-todo.md).

    Everything here runs passwordlessly through sudoers rules the template
    already has (``bootstrap.sh`` and ``/usr/local/bin/ltsp-setup *``), so
    no new root access has to be granted -- which matters more than usual
    here, because any sudoers change on the template ships to every thin
    client.
    """
    ct = ctx.settings.client_template
    address = wait_for_template_ssh(ctx)
    checkout = f"/home/{ctx.settings.admin_user}/ltsp-setup"

    ctx.runner.announce(f"Installing {ct.repo_url} on {ct.vm_name}")
    _ssh(ctx, address, f"rm -rf {checkout} && git clone -q {ct.repo_url} {checkout}")
    _ssh(ctx, address, f"sudo -n {checkout}/bootstrap.sh")

    for stage in stages:
        ctx.runner.announce(f"Running the client {stage!r} stage on {ct.vm_name}")
        _ssh(
            ctx,
            address,
            f"sudo -n /usr/local/bin/ltsp-setup client stage {stage} --no-debug",
        )

    ctx.runner.announce(f"Removing this tool from {ct.vm_name} again")
    _ssh(ctx, address, "sudo -n /usr/local/bin/ltsp-setup client cleanup --no-debug")


def refresh_image(ctx: Context, stages: Sequence[str], *, publish: bool = False) -> str:
    """Boot the template, bring it up to date, and build a fresh image.

    The whole by-hand routine as one command (Todd, 2026-09-09): start the
    VM, re-install this tool on it, run the stages that matter, strip the
    tooling back off, shut it down, and build.

    Stops there by default. Making the build live (``set_default_image``)
    and deleting what it supersedes (``prune_published_images``) stay
    separate, because "once we're sure it works" is a real gate -- a build
    that boots to a broken desktop should not be able to become the default
    without a human having looked at it first.

    ``publish=True`` is the unattended weekly rebuild, where no human is
    going to look at it. That gate does not simply disappear: it is replaced
    by ``publish_image``, which boots a real client against the new image
    and puts the old one back if it does not come up.

    Returns:
        The name this build was published under.
    """
    start_client_template(ctx)
    update_client_template(ctx, stages)
    name = build_image(ctx)
    if publish:
        publish_image(ctx, name)
    return name


def publish_image(ctx: Context, name: str, *, keep: int | None = None) -> None:
    """Make ``name`` live, prove it boots, and roll back if it doesn't.

    The unattended half of the weekly rebuild (Todd, 2026-09-12). The order
    here is the point: the image goes live *first*, because ``DEFAULT_IMAGE``
    is the only thing a netbooting client reads, so there is no way to test
    a build without pointing something at it. What makes that safe is that
    the previous ``DEFAULT_IMAGE`` is captured before the switch and put
    straight back if the smoke test fails -- so a bad build is live only for
    the few minutes it takes one VM to not boot, in the middle of the night,
    with nobody logged in.

    Pruning happens last and only on success, so the image being rolled back
    *to* still exists when it is needed. ``keep`` defaults to
    ``image_refresh.keep_rollback_images``: one superseded build survives, so
    next week's run has somewhere to fall back to as well.

    Raises:
        StepFailed: if the new build doesn't boot. ``DEFAULT_IMAGE`` has
            been restored by then, so the lab is left working; the failure
            is a report, not damage.
    """
    previous = current_default_image(ctx)
    if keep is None:
        keep = ctx.settings.image_refresh.keep_rollback_images

    ctx.runner.announce(f"Making {name} live (was {previous or 'unset'})")
    set_default_image(ctx, name)
    try:
        smoke.smoke_test_client(ctx)
    except StepFailed as exc:
        if previous is None:
            raise StepFailed(
                f"{name} failed its smoke test, and there was no previous "
                f"DEFAULT_IMAGE to roll back to -- it is still live.\n{exc}"
            ) from exc
        ctx.runner.announce(f"{name} failed its smoke test; rolling back to {previous}")
        set_default_image(ctx, previous)
        raise StepFailed(
            f"{name} failed its smoke test. DEFAULT_IMAGE has been rolled "
            f"back to {previous}, which was booting before this run, so the "
            f"clients are fine.\n{exc}"
        ) from exc

    prune_published_images(ctx, keep=keep)


def raw_image_path(ctx: Context, image_name: str | None = None) -> Path:
    """Where the raw source image for ``ltsp image`` lives.

    ``ltsp image <name>`` uses the *same* name for both its source
    (``/srv/ltsp/<name>.img``) and its published output
    (``/srv/ltsp/images/<name>.img``) -- see ``man ltsp-image``. Defaults to
    the configured ``client_template.image_name`` (undated) so the lab's
    cross-machine workflow (``convert_to_raw`` on one machine,
    ``import_raw_image``/``run_ltsp_image`` on another) keeps agreeing on
    the filename without anything explicit passed between them; pass
    ``image_name`` explicitly to use a specific (e.g. dated) build name
    instead.
    """
    name = image_name or ctx.settings.client_template.image_name
    return SOURCE_IMAGE_DIR / f"{name}.img"


def convert_to_raw(ctx: Context, image_name: str | None = None) -> Path:
    """Convert the template's qcow2 disk to the raw image ``ltsp image`` wants.

    Split out from ``build_image`` so it can run on a different machine than
    the one that builds the squashfs -- e.g. a disk-constrained lab VM,
    where the template lives on the workstation instead (a copy-on-write
    overlay on the golden image, for speed and disk space) and only the
    resulting raw file gets copied over to the server. See DECISIONS.md.

    ``-p`` shows a live progress percentage -- this step reads and writes
    tens of gigabytes and would otherwise sit silent for minutes at a time
    (Todd, 2026-08-26).
    """
    ct = ctx.settings.client_template
    raw_path = raw_image_path(ctx, image_name)
    ctx.runner.mkdir(raw_path.parent)
    ctx.runner.run(
        ["qemu-img", "convert", "-p", "-O", "raw", str(ct.disk_path), str(raw_path)]
    )
    return raw_path


def import_raw_image(ctx: Context, source: Path) -> Path:
    """Move an already-converted raw image into place for ``run_ltsp_image``.

    For the lab workflow where the template lives on the workstation (see
    ``convert_to_raw``): the raw file is copied to the server by hand
    (``scp``, since the workstation and the server VM aren't the same
    machine there), then moved into place from here.
    """
    dest = raw_image_path(ctx)
    ctx.runner.mkdir(dest.parent)
    ctx.runner.run(["mv", str(source), str(dest)])
    return dest


def dated_image_name(ctx: Context) -> str:
    """The name this build's squashfs/kernel/initrd get published under.

    Appends today's date to ``client_template.image_name`` (Todd's call,
    2026-08-19) so the currently published version is obvious at a glance
    under ``/srv/ltsp/images`` and ``/srv/tftp/ltsp`` -- matching this
    server's own pre-existing convention from before this tool existed
    (``mint-22.2-xfce-2026-04-23`` and friends).

    This only changes what the build is *called*; it doesn't revisit the
    "serve only one image, ever" rule below. ``DEFAULT_IMAGE`` in
    ``ltsp.conf`` is still the only thing that decides what clients actually
    netboot, so older dated builds are simply inert once superseded. But
    nothing prunes them automatically, so they'll accumulate on disk until
    something (a human, or the deferred overnight-rebuild cron job) cleans
    them up. See DECISIONS.md.

    If today's plain name is already published, appends ``-2``, ``-3``, ...
    (Todd, 2026-08-20: a same-day rebuild while iterating on the template is
    real and expected, and silently overwriting the day's earlier build via
    ``--backup 0`` would quietly remove the exact fallback the date-based
    naming exists to provide.) Only checked on a real run -- a dry run can't
    reliably read ``/srv/ltsp/images`` (root-owned ``0700``) without root,
    and failing a preview over that isn't worth it; the real run is the one
    that has to get uniqueness right.
    """
    base = f"{ctx.settings.client_template.image_name}-{date.today():%Y-%m-%d}"
    if ctx.runner.dry_run:
        return base
    published = set(list_published_images(ctx))
    if base not in published:
        return base
    n = 2
    while f"{base}-{n}" in published:
        n += 1
    return f"{base}-{n}"


def run_ltsp_image(ctx: Context, image_name: str | None = None) -> str:
    """Build the squashfs from the raw source image, then clean it up.

    Must run wherever ``ltsp`` is actually installed -- the server, not
    necessarily wherever ``convert_to_raw`` ran. ``image_name`` must match
    whatever name the raw source was actually written under (see
    ``raw_image_path``) -- ``ltsp image`` finds its source by that same
    name, so a mismatch here fails with "Image does not exist" rather than
    building from the wrong file. Defaults to ``dated_image_name`` for the
    single-machine production path; the lab's cross-machine workflow passes
    nothing so it falls back to the static configured name, matching
    whatever ``convert_to_raw``/``import_raw_image`` used.

    ``--backup=0``: Todd's operational rule (confirmed 2026-08-19) is to
    only ever serve one image *under a given name*. Since the name is now
    dated (see ``dated_image_name``), this mostly guards against leaving
    ``<name>.img.old`` cruft behind if a build is re-run after a same-day
    failure -- the real "only one image is live" guarantee still comes from
    ``DEFAULT_IMAGE`` in ``ltsp.conf`` naming exactly one of them.

    Returns:
        The name this build was published under, so the caller can report
        it (and pass it to ``set_default_image`` once it's been tested).
    """
    name = image_name or dated_image_name(ctx)
    raw_path = raw_image_path(ctx, name)
    ctx.runner.run(["ltsp", "image", "--backup", "0", name])
    # Runner.remove() only prints when the path already exists on disk,
    # which the raw file never does in a dry run (the convert is faked
    # there). Use `rm -f` directly so the cleanup step still shows up when
    # reviewing a plan with --debug.
    ctx.runner.run(["rm", "-f", str(raw_path)])
    return name


def build_image(ctx: Context) -> str:
    """Shut the template down and rebuild the client netboot image.

    Re-runnable on demand, and the one function a future cron job would
    call nightly once the "update the template's packages first" step
    exists (deliberately not built yet). Assumes the template and ``ltsp``
    are on the same machine -- true in production, not in the lab (see
    ``convert_to_raw``/``run_ltsp_image``).

    Deliberately does *not* update ``DEFAULT_IMAGE`` -- a fresh build isn't
    live until ``set_default_image`` says so, so it can be tested first.

    Returns:
        The name this build was published under.
    """
    ct = ctx.settings.client_template
    lv = _libvirt(ctx)
    if not ctx.runner.dry_run and not lv.domain_exists(ct.vm_name):
        raise StepFailed(
            f"No client-template VM named {ct.vm_name!r} at {ct.connect_uri}.\n"
            "Create one first with:  ltsp-setup image create-template --no-debug"
        )

    name = dated_image_name(ctx)
    shutdown_client_template(ctx)
    convert_to_raw(ctx, name)
    return run_ltsp_image(ctx, name)


_DEFAULT_IMAGE_LINE = re.compile(r"^(\s*)DEFAULT_IMAGE\s*=.*$", re.MULTILINE)


def _with_default_image(content: str, image_name: str) -> str:
    """Return ``ltsp.conf``'s content with ``DEFAULT_IMAGE`` set in ``[server]``.

    Patches just that one line -- or inserts it right after the ``[server]``
    header if it's missing -- and leaves everything else untouched. Unlike
    ``server.configure_ltsp``, which renders the whole file from a minimal
    template, this is safe to run against a server whose ``ltsp.conf`` has
    real hand-written content (NFS options, per-client sections, ...) that
    predates this tool and isn't reflected in ``data/ltsp.conf``.
    """
    new_line = f'DEFAULT_IMAGE="{image_name}"'
    lines = content.splitlines()
    section = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section = stripped[1:-1]
            continue
        if section == "server" and _DEFAULT_IMAGE_LINE.match(line):
            lines[i] = new_line
            return "\n".join(lines) + "\n"
    for i, line in enumerate(lines):
        if line.strip() == "[server]":
            lines.insert(i + 1, new_line)
            return "\n".join(lines) + "\n"
    raise StepFailed(
        f"{LTSP_CONF} has no [server] section to add DEFAULT_IMAGE to. "
        "Add one by hand first."
    )


def current_default_image(ctx: Context) -> str | None:
    """Whatever ``DEFAULT_IMAGE`` in ``ltsp.conf`` currently names, if any."""
    if not LTSP_CONF.is_file():
        return None
    match = _DEFAULT_IMAGE_LINE.search(ctx.runner.read_text(LTSP_CONF))
    if match is None:
        return None
    return match.group(0).split("=", 1)[1].strip().strip('"')


def set_default_image(ctx: Context, image_name: str) -> None:
    """Point ``DEFAULT_IMAGE`` at ``image_name`` and regenerate the iPXE menu.

    This is what actually makes a build live -- ``image build`` only
    publishes it. Also what a revert is: call this again with a previous,
    still-on-disk dated build's name. Only ``ltsp ipxe`` needs to re-run
    (it's what reads ``DEFAULT_IMAGE`` to generate the boot menu); the
    per-image kernel/initrd were already produced by ``ltsp image`` itself
    when that build ran.
    """
    if not ctx.runner.dry_run and not LTSP_CONF.is_file():
        raise StepFailed(
            f"{LTSP_CONF} does not exist yet. Run the server's `ltsp` stage "
            "first, or create it by hand with a [server] section."
        )
    current = ctx.runner.read_text(LTSP_CONF) if LTSP_CONF.is_file() else "[server]\n"
    ctx.runner.write(LTSP_CONF, _with_default_image(current, image_name), mode=0o660)
    ctx.runner.run(["ltsp", "ipxe"])


def list_published_images(ctx: Context) -> list[str]:
    """Every image ``ltsp image`` has published under ``/srv/ltsp/images``.

    Newest first, so a revert target is easy to spot. Doesn't touch the
    transient raw source (``raw_image_path``), which lives directly under
    ``/srv/ltsp``, not ``/srv/ltsp/images``, and never survives a build.

    Raises:
        StepFailed: if the directory exists but can't be read. It's
            root-owned ``0700`` on a real server, so this needs root.
            Deliberately not just ``Path.glob``, which swallows
            ``PermissionError`` internally and would silently report an
            empty list here -- indistinguishable from "nothing published
            yet" and actively misleading.
    """
    if not PUBLISHED_IMAGE_DIR.is_dir():
        return []
    try:
        names = [p.stem for p in PUBLISHED_IMAGE_DIR.iterdir() if p.suffix == ".img"]
    except PermissionError as exc:
        raise StepFailed(
            f"Can't read {PUBLISHED_IMAGE_DIR} ({exc}). "
            "Try: sudo ltsp-setup image list"
        ) from exc
    return sorted(names, reverse=True)


def prune_published_images(ctx: Context, *, keep: int = 1) -> list[str]:
    """Delete superseded builds, keeping the live one and ``keep`` rollbacks.

    Nothing prunes a build automatically after it's superseded (see
    ``dated_image_name``), so they accumulate on disk *and* in the PXE
    boot menu -- a student's client can netboot any of them, not just
    ``DEFAULT_IMAGE``, until this runs (Todd, 2026-08-27). Removes both
    halves of each stale build: the squashfs under ``PUBLISHED_IMAGE_DIR``
    and the kernel/initrd under ``TFTP_IMAGE_DIR``. The squashfs half is
    what removes the entry from the menu -- ``ltsp ipxe`` builds its item
    list from ``PUBLISHED_IMAGE_DIR``, not from TFTP -- and the TFTP half
    is the orphan that would otherwise be left behind. Works from the union
    of both directories' names rather than just one, since a half-cleaned
    or failed build may have only one of the pair.

    ``keep`` is how many *superseded* builds survive, newest first, on top
    of the live one, which is never a candidate for deletion. It defaults
    to 1 because the unattended weekly rebuild (see ``publish_image``)
    needs somewhere to roll back to: last week's proven-to-boot image stays
    on disk and in the menu, so recovering from a bad build is
    ``image set-default <name>`` and a reboot rather than an hour-long
    rebuild (Todd, 2026-09-12). Pass ``keep=0`` for the old behaviour of
    leaving only the live image behind.

    **Only a build with both halves can be kept as a rollback.** A name
    with a squashfs but no kernel, or a kernel but no squashfs, is a failed
    or half-cleaned build, and keeping it as "the rollback" would leave
    nothing bootable to roll back *to* -- while deleting the working build
    it outranked. This is not hypothetical: on 2026-09-15 the server had
    exactly that, an orphaned ``2026-09-09`` tftp directory whose squashfs
    was already gone, which sorts newer than the proven ``2026-08-28-2``
    and would have been kept in its place. Incomplete builds are always
    prune candidates, never keepers.

    Dated names sort chronologically, so "newest first" is just a reverse
    sort -- the same assumption ``dated_image_name`` already relies on.
    Builds predating this tool's naming scheme sort wherever they sort,
    which is fine: they're the oldest thing here either way, so they're
    pruned first.

    Refuses to run if ``DEFAULT_IMAGE`` can't be determined, rather than
    guess which build is safe to keep.
    """
    if keep < 0:
        raise StepFailed(f"keep must not be negative, got {keep}.")
    live = current_default_image(ctx)
    if live is None:
        raise StepFailed(
            f"{LTSP_CONF} has no DEFAULT_IMAGE set -- refusing to guess "
            "which published image is safe to keep."
        )
    published = set(list_published_images(ctx))
    tftp_names = {p.name for p in ctx.runner.list_dirs(TFTP_IMAGE_DIR)}
    superseded = (published | tftp_names) - {live}
    bootable = sorted(superseded & published & tftp_names, reverse=True)
    keepers = bootable[:keep]
    stale = sorted(superseded.difference(keepers), reverse=True)
    for name in keepers:
        ctx.runner.announce(f"Keeping {name} as a rollback target")

    for name in stale:
        ctx.runner.remove([PUBLISHED_IMAGE_DIR / f"{name}.img"])
        ctx.runner.remove_tree(TFTP_IMAGE_DIR / name)
    if stale:
        ctx.runner.run(["ltsp", "ipxe"])
    return stale


# ------------------------------------------------- the unattended rebuild

REFRESH_UNIT = "ltsp-setup-image"
REFRESH_SERVICE_PATH = Path("/etc/systemd/system") / f"{REFRESH_UNIT}.service"
REFRESH_TIMER_PATH = Path("/etc/systemd/system") / f"{REFRESH_UNIT}.timer"


def refresh_command(ctx: Context, config_file: Path | None) -> str:
    """The exact ``ltsp-setup`` invocation the timer should run.

    Built from config rather than hardcoded so that changing
    ``image_refresh.stages`` and re-running ``image schedule`` is enough --
    nobody has to remember that the real schedule lives in a unit file in
    /etc and not in the config they just edited.
    """
    refresh = ctx.settings.image_refresh
    argv = [entry_point(), "image", "refresh", "--publish", "--no-debug"]
    for stage in refresh.stages:
        argv += ["--stage", stage]
    if config_file is not None:
        argv += ["--config", str(config_file)]
    return " ".join(argv)


def install_refresh_timer(ctx: Context, config_file: Path | None = None) -> None:
    """Install and enable the weekly unattended rebuild.

    Two units, which is how systemd timers work: a oneshot service that does
    the job and a timer that decides when. The service has no ``[Install]``
    section of its own on purpose -- enabling the *timer* is what schedules
    it, and a service that could also be enabled independently is a way to
    accidentally run an hour-long image build at every boot.
    """
    refresh = ctx.settings.image_refresh
    description = "Weekly LTSP client image rebuild"
    ctx.runner.write(
        REFRESH_SERVICE_PATH,
        templates.render(
            f"{REFRESH_UNIT}.service",
            {"DESCRIPTION": description, "EXEC": refresh_command(ctx, config_file)},
        ),
        mode=0o644,
    )
    ctx.runner.write(
        REFRESH_TIMER_PATH,
        templates.render(
            f"{REFRESH_UNIT}.timer",
            {
                "DESCRIPTION": f"{description} ({refresh.on_calendar})",
                "ON_CALENDAR": refresh.on_calendar,
                "RANDOMIZED_DELAY": refresh.randomized_delay_s,
            },
        ),
        mode=0o644,
    )
    ctx.runner.run(["systemctl", "daemon-reload"])
    ctx.runner.run(["systemctl", "enable", "--now", f"{REFRESH_UNIT}.timer"])


def remove_refresh_timer(ctx: Context) -> None:
    """Turn the weekly rebuild off and delete its units. Safe to run twice."""
    ctx.runner.run(
        ["systemctl", "disable", "--now", f"{REFRESH_UNIT}.timer"], check=False
    )
    ctx.runner.remove([REFRESH_TIMER_PATH, REFRESH_SERVICE_PATH])
    ctx.runner.run(["systemctl", "daemon-reload"], check=False)


def refresh_timer_status(ctx: Context) -> str:
    """When the weekly rebuild last ran and when it runs next."""
    if not ctx.runner.exists(REFRESH_TIMER_PATH):
        return (
            "The weekly rebuild is not scheduled.\n"
            "Turn it on with:  sudo ltsp-setup image schedule --no-debug"
        )
    result = ctx.runner.run(
        ["systemctl", "list-timers", "--all", f"{REFRESH_UNIT}.timer"],
        check=False,
        capture=True,
    )
    return (result.stdout or "").strip()


def status(ctx: Context) -> str:
    """A short report on the client-template VM's current state."""
    return _libvirt(ctx).virsh(
        "dominfo", ctx.settings.client_template.vm_name, check=False
    )
