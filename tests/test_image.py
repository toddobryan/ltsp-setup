"""Dry-run behaviour of the client-template VM and image-build steps.

The steps here call ``Libvirt.check_host_tools()`` even during a dry run
(deliberately — see ``lab/virt.py``, which does the same thing, so you find
out you're missing virsh/virt-install/qemu-img/KVM before doing a bunch of
otherwise-pointless dry-run review). That makes these tests genuinely
dependent on the machine they run on, so they're skipped where those tools
or /dev/kvm aren't available, same as a real workstation without them.
"""

from __future__ import annotations

import dataclasses
import shutil
import time
from pathlib import Path

import pytest

from ltsp_setup.config import Settings
from ltsp_setup.runner import Runner, StepFailed
from ltsp_setup.stages import Context
from ltsp_setup.steps import image

HOST_TOOLS_AVAILABLE = (
    all(shutil.which(tool) for tool in ("virsh", "virt-install", "qemu-img"))
    and Path("/dev/kvm").exists()
)

requires_host_tools = pytest.mark.skipif(
    not HOST_TOOLS_AVAILABLE,
    reason="virsh, virt-install, qemu-img and /dev/kvm are not all available",
)


@requires_host_tools
def test_create_client_template_dry_run_does_not_raise() -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    image.create_client_template(ctx)


@requires_host_tools
def test_shutdown_client_template_does_not_poll_in_a_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("time.sleep should not run during a dry run")

    monkeypatch.setattr(time, "sleep", fail_if_called)
    ctx = Context(Settings(), Runner(dry_run=True))
    image.shutdown_client_template(ctx)


@requires_host_tools
def test_build_image_raises_when_the_template_does_not_exist() -> None:
    settings = dataclasses.replace(
        Settings(),
        client_template=dataclasses.replace(
            Settings().client_template, vm_name="definitely-not-a-real-domain-xyz"
        ),
    )
    ctx = Context(settings, Runner(dry_run=False))
    with pytest.raises(StepFailed, match="definitely-not-a-real-domain-xyz"):
        image.build_image(ctx)


def test_build_image_dry_run_prints_every_step_without_a_machine() -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    image.build_image(ctx)


def test_convert_to_raw_returns_the_configured_image_path() -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    raw_path = image.convert_to_raw(ctx)
    assert raw_path == image.raw_image_path(ctx)
    assert raw_path.name == "ltsp-client-template.img"


def test_run_ltsp_image_dry_run_does_not_raise() -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    image.run_ltsp_image(ctx)


def test_import_raw_image_moves_source_to_the_configured_path() -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    dest = image.import_raw_image(ctx, Path("/home/sysadmin/ltsp-client-template.img"))
    assert dest == image.raw_image_path(ctx)
