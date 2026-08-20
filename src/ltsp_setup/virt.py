"""Low-level libvirt plumbing shared by the workstation test lab and the
production client-template VM.

Everything here talks to ``virsh`` through the shared
:class:`~ltsp_setup.runner.Runner`, so ``--debug`` prints the exact commands
instead of running them. This module knows nothing about any particular VM's
purpose (golden image, overlay, client template) — that lives in
``lab/virt.py`` and ``steps/image.py``, both of which compose a
:class:`Libvirt` instance for the plumbing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ltsp_setup.runner import Runner, StepFailed


@dataclass
class Libvirt:
    """A thin wrapper over the libvirt command line tools."""

    connect_uri: str
    runner: Runner

    def virsh(self, *args: str, check: bool = True) -> str:
        """Run virsh against the configured connection and return stdout."""
        result = self.runner.run(
            ["virsh", "--connect", self.connect_uri, *args],
            check=check,
            capture=True,
        )
        return (result.stdout or "").strip()

    def check_host_tools(self) -> None:
        """Fail early and clearly if the machine is not set up for this."""
        missing = [
            tool
            for tool in ("virsh", "virt-install", "qemu-img")
            if not self.runner.which(tool)
        ]
        if missing:
            raise StepFailed(
                "Missing host tools: " + ", ".join(missing) + ".\nInstall them with:\n"
                "  sudo apt install -y qemu-kvm libvirt-daemon-system "
                "libvirt-clients virtinst qemu-utils\n"
                '  sudo usermod -aG libvirt,kvm "$USER"   # then log out and back in'
            )
        if not Path("/dev/kvm").exists():
            raise StepFailed(
                "/dev/kvm does not exist, so the VM would run under slow "
                "software emulation. Check that virtualisation is enabled in "
                "the BIOS and that the kvm modules are loaded."
            )

    def domain_exists(self, name: str) -> bool:
        """True if a VM of this name is defined."""
        if self.runner.dry_run:
            return False
        result = self.runner.run(
            ["virsh", "--connect", self.connect_uri, "dominfo", name],
            check=False,
            capture=True,
        )
        return result.returncode == 0

    def domstate(self, name: str) -> str:
        """The VM's current state, e.g. "running" or "shut off"."""
        if self.runner.dry_run:
            return "shut off"
        return self.virsh("domstate", name, check=False)

    def network_exists(self, name: str) -> bool:
        """True if a libvirt network of this name is defined."""
        if self.runner.dry_run:
            return False
        result = self.runner.run(
            ["virsh", "--connect", self.connect_uri, "net-info", name],
            check=False,
            capture=True,
        )
        return result.returncode == 0
