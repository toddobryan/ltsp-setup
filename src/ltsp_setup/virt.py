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

    def domifaddr(self, name: str) -> str | None:
        """The VM's first IPv4 address, or None if it doesn't have one yet.

        A running VM has no address until its guest DHCP client has actually
        come up, so this returns None for a while after ``virsh start`` --
        callers poll. Returns a placeholder during a dry run so the printed
        commands that use it still read sensibly.
        """
        if self.runner.dry_run:
            return "<template-ip>"
        output = self.virsh("domifaddr", name, check=False)
        for line in output.splitlines():
            fields = line.split()
            # e.g. "vnet0  52:54:00:78:4f:68  ipv4  192.168.122.99/24"
            if len(fields) >= 4 and fields[2] == "ipv4":
                return fields[3].split("/")[0]
        return None

    def mac_address(self, name: str) -> str:
        """The MAC of the VM's first network interface.

        Read from libvirt rather than kept in config, so there is only one
        place a VM's MAC is written down and no way for the two to drift.
        The smoke-test client is bridged onto the LTSP network rather than
        a libvirt-managed one, so ``domifaddr`` can't see its address --
        the MAC is the only handle on it, and its address has to be looked
        up in dnsmasq's leases instead. See ``steps/smoke.py``.
        """
        output = self.virsh("domiflist", name)
        for line in output.splitlines():
            fields = line.split()
            # e.g. "vnet3  bridge  br0  e1000  52:54:00:2c:5d:65"
            if len(fields) >= 5 and fields[4].count(":") == 5:
                return fields[4]
        raise StepFailed(f"Could not find a MAC address for {name!r} in:\n{output}")

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
