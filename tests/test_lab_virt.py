"""Safety behaviour of the workstation lab's VM management.

``check_host_tools()`` runs even during a dry run (see ``test_image.py``'s
module docstring for why), so these tests are skipped where virsh,
virt-install, qemu-img or /dev/kvm aren't all available.
"""

from __future__ import annotations

import dataclasses
import shutil
from pathlib import Path

import pytest

from ltsp_setup.config import Settings
from ltsp_setup.lab.virt import Virt
from ltsp_setup.runner import Runner, StepFailed

requires_host_tools = pytest.mark.skipif(
    not (
        all(shutil.which(tool) for tool in ("virsh", "virt-install", "qemu-img"))
        and Path("/dev/kvm").exists()
    ),
    reason="virsh, virt-install, qemu-img and /dev/kvm are not all available",
)


@requires_host_tools
def test_build_golden_refuses_to_overwrite_an_existing_golden_disk(
    tmp_path: Path,
) -> None:
    settings = dataclasses.replace(
        Settings(), lab=dataclasses.replace(Settings().lab, pool_dir=tmp_path)
    )
    virt = Virt(settings, Runner(dry_run=False))
    virt.golden_disk.write_text("pretend this is a finished install")

    with pytest.raises(StepFailed, match="already exists"):
        virt.build_golden()


@requires_host_tools
def test_create_client_template_dry_run_does_not_raise() -> None:
    Virt(Settings(), Runner(dry_run=True)).create_client_template()


@requires_host_tools
def test_reset_unknown_name_lists_all_three_lab_vms() -> None:
    virt = Virt(Settings(), Runner(dry_run=True))
    with pytest.raises(
        StepFailed, match="ltsp-server.*ltsp-client.*ltsp-client-template"
    ):
        virt.reset("not-a-real-vm")
