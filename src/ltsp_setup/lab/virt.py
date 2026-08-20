"""Building and resetting the test VMs with libvirt.

Everything here talks to ``virsh``, ``virt-install`` and ``qemu-img`` through
the shared :class:`~ltsp_setup.runner.Runner`, so ``--debug`` prints the exact
commands instead of running them.

The shape of the lab:

* A golden qcow2 holding a pristine Mint install.  Built once, by hand,
  then never booted again.
* ``ltsp-server`` and ``ltsp-client``, each a copy-on-write overlay on top of
  that golden disk.  Making one takes about a second and discarding one takes
  less, so re-testing a change from a genuinely clean machine is cheap.
* An isolated ``ltsp`` network with no DHCP of its own, joining the server's
  second NIC to the client's only NIC.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ltsp_setup import templates
from ltsp_setup.config import Lab, Settings
from ltsp_setup.runner import Runner, StepFailed
from ltsp_setup.virt import Libvirt

# Stable MACs so netplan can match on them instead of guessing at interface
# names. 52:54:00 is the QEMU/KVM prefix; the rest is ours.
MAC_SERVER_INTERNET = "52:54:00:67:00:01"
MAC_SERVER_LTSP = "52:54:00:67:00:02"
MAC_CLIENT = "52:54:00:67:00:10"


@dataclass
class Virt:
    """A thin wrapper over the libvirt command line tools."""

    settings: Settings
    runner: Runner
    libvirt: Libvirt = field(init=False)

    def __post_init__(self) -> None:
        self.libvirt = Libvirt(self.lab.connect_uri, self.runner)

    @property
    def lab(self) -> Lab:
        return self.settings.lab

    # ------------------------------------------------------------- plumbing

    def virsh(self, *args: str, check: bool = True) -> str:
        """Run virsh against the configured connection and return stdout."""
        return self.libvirt.virsh(*args, check=check)

    def check_host_tools(self) -> None:
        """Fail early and clearly if the workstation is not set up for this."""
        self.libvirt.check_host_tools()

    def domain_exists(self, name: str) -> bool:
        """True if a VM of this name is defined."""
        return self.libvirt.domain_exists(name)

    def network_exists(self, name: str) -> bool:
        """True if a libvirt network of this name is defined."""
        return self.libvirt.network_exists(name)

    # -------------------------------------------------------------- network

    def ensure_networks(self) -> None:
        """Make sure both the NAT network and the isolated LTSP one are up."""
        self.runner.announce("Making sure the 'default' NAT network is running")
        self.virsh("net-start", "default", check=False)
        self.virsh("net-autostart", "default", check=False)

        name = self.lab.network_name
        if self.network_exists(name):
            self.runner.announce(f"Network {name!r} already exists")
        else:
            self.runner.announce(f"Defining the isolated {name!r} network")
            xml = templates.render(
                "network-ltsp.xml",
                {"NAME": name, "BRIDGE": f"virbr-{name}"[:15]},
            )
            xml_path = Path(f"/tmp/ltsp-network-{name}.xml")
            self.runner.write(xml_path, xml)
            self.virsh("net-define", str(xml_path))
        self.virsh("net-start", name, check=False)
        self.virsh("net-autostart", name, check=False)

    # ----------------------------------------------------------------- disk

    @property
    def golden_disk(self) -> Path:
        return self.lab.pool_dir / f"{self.lab.golden_name}.qcow2"

    def overlay_disk(self, name: str) -> Path:
        return self.lab.pool_dir / f"{name}.qcow2"

    def require_golden(self) -> None:
        """Fail with instructions if the golden image is not there yet."""
        if self.runner.dry_run or self.golden_disk.is_file():
            return
        raise StepFailed(
            f"No golden image at {self.golden_disk}.\n"
            "Build one first with:  ltsp-setup lab build-golden --no-debug\n"
            "That walks you through a one-time manual Mint install."
        )

    def make_overlay(self, name: str, size_gb: int) -> Path:
        """Create a copy-on-write overlay on top of the golden disk.

        Through the libvirt storage pool (``virsh vol-create-as``), not a
        raw ``qemu-img create``: ``lab.pool_dir`` is root-owned 0711, so only
        libvirtd -- running as root -- can create files there. A plain
        subprocess run by this (unprivileged) CLI can't, which is exactly
        the permission error this sidesteps.
        """
        overlay = self.overlay_disk(name)
        pool = self.lab.pool_name
        self.virsh("vol-delete", "--pool", pool, overlay.name, check=False)
        self.virsh(
            "vol-create-as",
            pool,
            overlay.name,
            f"{size_gb}G",
            "--format",
            "qcow2",
            "--backing-vol",
            str(self.golden_disk),
            "--backing-vol-format",
            "qcow2",
        )
        return overlay

    # ------------------------------------------------------------------ VMs

    def build_golden(self) -> None:
        """Start the one-time interactive Mint install for the golden image."""
        self.check_host_tools()
        lab = self.lab
        if not self.runner.dry_run and self.golden_disk.is_file():
            raise StepFailed(
                f"{self.golden_disk} already exists. build-golden is one-time "
                "setup; running virt-install against an existing disk would "
                "reinstall over your finished golden image and corrupt every "
                "overlay built from it.\n"
                "If you really mean to start over, chmod it writable and "
                "remove it by hand first."
            )
        if not self.runner.dry_run and not lab.iso.is_file():
            raise StepFailed(
                f"Mint ISO not found at {lab.iso}. Download it, or point "
                "lab.iso at it in your config file."
            )
        self.ensure_networks()
        self.runner.mkdir(lab.pool_dir)
        self.runner.run(
            [
                "virt-install",
                "--connect",
                lab.connect_uri,
                "--name",
                lab.golden_name,
                "--ram",
                str(4096),
                "--vcpus",
                str(2),
                "--disk",
                f"path={self.golden_disk},size={lab.golden_disk_gb},"
                "format=qcow2,bus=virtio",
                "--cdrom",
                str(lab.iso),
                "--network",
                "network=default,model=virtio",
                "--graphics",
                "spice",
                "--video",
                "qxl",
                "--os-variant",
                "ubuntu24.04",
            ]
        )

    def create_server(self) -> None:
        """Create the server VM as a clone of the golden image."""
        self.check_host_tools()
        self.require_golden()
        self.ensure_networks()
        lab = self.lab
        self.destroy(lab.server_name)
        overlay = self.make_overlay(lab.server_name, lab.golden_disk_gb)
        self.runner.run(
            [
                "virt-install",
                "--connect",
                lab.connect_uri,
                "--name",
                lab.server_name,
                "--ram",
                str(lab.server_ram_mb),
                "--vcpus",
                str(lab.server_vcpus),
                "--disk",
                f"path={overlay},format=qcow2,bus=virtio",
                "--import",
                "--network",
                f"network=default,model=virtio,mac={MAC_SERVER_INTERNET}",
                "--network",
                f"network={lab.network_name},model=virtio,mac={MAC_SERVER_LTSP}",
                "--graphics",
                "spice",
                "--video",
                "qxl",
                "--os-variant",
                "ubuntu24.04",
                "--noautoconsole",
            ]
        )

    def create_client(self) -> None:
        """Create the client VM: one NIC, on the isolated network, PXE first.

        The e1000 model is deliberate.  virtio's PXE ROM works most of the
        time, but e1000's is the one every netboot stack has been tested
        against for twenty years, and a thin client that silently fails to
        find the server is a miserable thing to debug.
        """
        self.check_host_tools()
        self.require_golden()
        self.ensure_networks()
        lab = self.lab
        self.destroy(lab.client_name)
        overlay = self.make_overlay(lab.client_name, lab.client_disk_gb)
        self.runner.run(
            [
                "virt-install",
                "--connect",
                lab.connect_uri,
                "--name",
                lab.client_name,
                "--ram",
                str(lab.client_ram_mb),
                "--vcpus",
                str(lab.client_vcpus),
                "--disk",
                f"path={overlay},format=qcow2,bus=virtio",
                "--import",
                "--network",
                f"network={lab.network_name},model=e1000,mac={MAC_CLIENT}",
                "--boot",
                "hd,network",
                "--graphics",
                "spice",
                "--video",
                "qxl",
                "--os-variant",
                "ubuntu24.04",
                "--noautoconsole",
            ]
        )

    def create_client_template(self) -> None:
        """Create the client-template VM as an overlay on the golden image.

        Production builds the template with a fresh interactive install
        (``steps/image.py::create_client_template``) because it lives on the
        server itself, where disk is plentiful. In the lab, the server VM's
        disk is 40GB total and can't also hold a full second Mint install,
        so this reuses the same golden-image overlay trick as
        ``create_server``/``create_client`` instead -- seconds instead of a
        full install, and it lives on the workstation, not nested inside
        the server VM. Attached to the ``default`` NAT network (not the
        isolated lab network) so it can actually reach the internet to run
        the ``client`` plan against it.
        """
        self.check_host_tools()
        self.require_golden()
        self.ensure_networks()
        ct = self.settings.client_template
        self.destroy(ct.vm_name)
        overlay = self.make_overlay(ct.vm_name, ct.disk_gb)
        network = f"network={ct.network},model=virtio"
        if ct.mac:
            network += f",mac={ct.mac}"
        self.runner.run(
            [
                "virt-install",
                "--connect",
                self.lab.connect_uri,
                "--name",
                ct.vm_name,
                "--ram",
                str(ct.ram_mb),
                "--vcpus",
                str(ct.vcpus),
                "--disk",
                f"path={overlay},format=qcow2,bus=virtio",
                "--import",
                "--network",
                network,
                "--graphics",
                "spice",
                "--video",
                "qxl",
                "--os-variant",
                ct.os_variant,
                "--noautoconsole",
            ]
        )

    def set_netboot(self, name: str, network_first: bool) -> None:
        """Flip a VM between booting from its disk and netbooting."""
        order = "network,hd" if network_first else "hd,network"
        self.runner.announce(f"Setting {name} boot order to {order}")
        self.runner.run(
            [
                "virt-xml",
                "--connect",
                self.lab.connect_uri,
                name,
                "--edit",
                "--boot",
                order,
            ]
        )

    def destroy(self, name: str, *, remove_disk: bool = False) -> None:
        """Stop and undefine a VM if it exists.  Quiet when it does not."""
        if not self.domain_exists(name):
            return
        self.runner.announce(f"Removing existing VM {name!r}")
        self.virsh("destroy", name, check=False)
        args = ["undefine", name, "--nvram"]
        if remove_disk:
            args.append("--remove-all-storage")
        self.virsh(*args, check=False)

    def reset(self, name: str) -> None:
        """Throw a VM away and rebuild it from the golden image."""
        lab = self.lab
        if name == lab.server_name:
            self.create_server()
        elif name == lab.client_name:
            self.create_client()
        elif name == self.settings.client_template.vm_name:
            self.create_client_template()
        else:
            raise StepFailed(
                f"{name!r} is not one of the lab VMs "
                f"({lab.server_name}, {lab.client_name}, "
                f"{self.settings.client_template.vm_name})."
            )

    def status(self) -> str:
        """A short report on what the lab currently looks like."""
        lines = [self.virsh("list", "--all"), "", self.virsh("net-list", "--all")]
        return "\n".join(lines)
