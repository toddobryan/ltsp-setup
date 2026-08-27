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
import time
from datetime import date
from pathlib import Path

from ltsp_setup.runner import StepFailed
from ltsp_setup.stages import Context
from ltsp_setup.steps.server import LTSP_CONF
from ltsp_setup.virt import Libvirt

SOURCE_IMAGE_DIR = Path("/srv/ltsp")

# Where `ltsp image` actually publishes each build -- LTSP's own default
# IMAGE_DIR, not something this tool configures.
PUBLISHED_IMAGE_DIR = Path("/srv/ltsp/images")

# Where `ltsp image` extracts each build's kernel/initrd, and what `ltsp
# ipxe` actually scans to generate the PXE boot menu -- LTSP's own default
# TFTP_DIR/ltsp, not something this tool configures.
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


def prune_published_images(ctx: Context) -> list[str]:
    """Delete every published image except the one currently live.

    Nothing prunes a build automatically after it's superseded (see
    ``dated_image_name``), so they accumulate on disk *and* in the PXE
    boot menu -- a student's client can netboot any of them, not just
    ``DEFAULT_IMAGE``, until this runs (Todd, 2026-08-27). Removes both
    halves of each stale build: the squashfs under ``PUBLISHED_IMAGE_DIR``
    and the kernel/initrd under ``TFTP_IMAGE_DIR`` -- the latter is what
    ``ltsp ipxe`` actually scans to generate the menu, so pruning only the
    squashfs half would leave stale entries selectable. Works from the
    union of both directories' names rather than just one, since a build
    from before this tool existed may only have one half of the pair.

    Refuses to run if ``DEFAULT_IMAGE`` can't be determined, rather than
    guess which build is safe to keep.
    """
    live = current_default_image(ctx)
    if live is None:
        raise StepFailed(
            f"{LTSP_CONF} has no DEFAULT_IMAGE set -- refusing to guess "
            "which published image is safe to keep."
        )
    published = set(list_published_images(ctx))
    tftp_names = {p.name for p in ctx.runner.list_dirs(TFTP_IMAGE_DIR)}
    stale = sorted((published | tftp_names) - {live}, reverse=True)

    for name in stale:
        ctx.runner.remove([PUBLISHED_IMAGE_DIR / f"{name}.img"])
        ctx.runner.remove_tree(TFTP_IMAGE_DIR / name)
    if stale:
        ctx.runner.run(["ltsp", "ipxe"])
    return stale


def status(ctx: Context) -> str:
    """A short report on the client-template VM's current state."""
    return _libvirt(ctx).virsh(
        "dominfo", ctx.settings.client_template.vm_name, check=False
    )
