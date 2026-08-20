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

import time
from pathlib import Path

from ltsp_setup.runner import StepFailed
from ltsp_setup.stages import Context
from ltsp_setup.virt import Libvirt

SOURCE_IMAGE_DIR = Path("/srv/ltsp")

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


def raw_image_path(ctx: Context) -> Path:
    """Where the raw source image for ``ltsp image`` lives."""
    return SOURCE_IMAGE_DIR / f"{ctx.settings.client_template.image_name}.img"


def convert_to_raw(ctx: Context) -> Path:
    """Convert the template's qcow2 disk to the raw image ``ltsp image`` wants.

    Split out from ``build_image`` so it can run on a different machine than
    the one that builds the squashfs -- e.g. a disk-constrained lab VM,
    where the template lives on the workstation instead (a copy-on-write
    overlay on the golden image, for speed and disk space) and only the
    resulting raw file gets copied over to the server. See DECISIONS.md.
    """
    ct = ctx.settings.client_template
    raw_path = raw_image_path(ctx)
    ctx.runner.mkdir(raw_path.parent)
    ctx.runner.run(
        ["qemu-img", "convert", "-O", "raw", str(ct.disk_path), str(raw_path)]
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


def run_ltsp_image(ctx: Context) -> None:
    """Build the squashfs from the raw source image, then clean it up.

    Must run wherever ``ltsp`` is actually installed -- the server, not
    necessarily wherever ``convert_to_raw`` ran.

    ``--backup=0``: Todd's operational rule (confirmed 2026-08-19) is to
    only ever serve one image. Students don't pick from a boot menu, so a
    second image sitting in the images directory (``ltsp image``'s default
    is to keep the previous one as ``<name>.img.old``) is just a way for
    some clients to end up booting a stale version by accident.
    """
    ct = ctx.settings.client_template
    ctx.runner.run(["ltsp", "image", "--backup", "0", ct.image_name])
    # Runner.remove() only prints when the path already exists on disk,
    # which the raw file never does in a dry run (the convert is faked
    # there). Use `rm -f` directly so the cleanup step still shows up when
    # reviewing a plan with --debug.
    ctx.runner.run(["rm", "-f", str(raw_image_path(ctx))])


def build_image(ctx: Context) -> None:
    """Shut the template down and rebuild the client netboot image.

    Re-runnable on demand, and the one function a future cron job would
    call nightly once the "update the template's packages first" step
    exists (deliberately not built yet). Assumes the template and ``ltsp``
    are on the same machine -- true in production, not in the lab (see
    ``convert_to_raw``/``run_ltsp_image``).
    """
    ct = ctx.settings.client_template
    lv = _libvirt(ctx)
    if not ctx.runner.dry_run and not lv.domain_exists(ct.vm_name):
        raise StepFailed(
            f"No client-template VM named {ct.vm_name!r} at {ct.connect_uri}.\n"
            "Create one first with:  ltsp-setup image create-template --no-debug"
        )

    shutdown_client_template(ctx)
    convert_to_raw(ctx)
    run_ltsp_image(ctx)


def status(ctx: Context) -> str:
    """A short report on the client-template VM's current state."""
    return _libvirt(ctx).virsh(
        "dominfo", ctx.settings.client_template.vm_name, check=False
    )
