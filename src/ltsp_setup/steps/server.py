"""Turning a fresh Mint install into the LTSP server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ltsp_setup import templates
from ltsp_setup.config import Networking
from ltsp_setup.stages import Context
from ltsp_setup.steps.common import apt_install, apt_update

NETPLAN_DIR = Path("/etc/netplan")
NETPLAN_FILE = NETPLAN_DIR / "01-ltsp.yaml"

LTSP_PPA = "ppa:ltsp"

SERVER_PACKAGES = [
    "ltsp",
    "ltsp-binaries",
    "dnsmasq",
    "nfs-kernel-server",
    "openssh-server",
    "squashfs-tools",
    "ethtool",
    "net-tools",
    "epoptes",
]


def set_hostname(ctx: Context) -> None:
    """Write /etc/hostname and /etc/hosts, and tell the running system."""
    net = ctx.settings.networking
    ctx.runner.write(
        Path("/etc/hostname"),
        templates.render("etc_hostname", {"HOSTNAME": net.hostname}),
    )
    ctx.runner.write(
        Path("/etc/hosts"),
        templates.render(
            "etc_hosts",
            {"HOSTNAME": net.hostname, "ALT_HOSTNAMES": " ".join(net.alt_hostnames)},
        ),
    )
    ctx.runner.run(["hostnamectl", "set-hostname", net.hostname])


def netplan_config(net: Networking) -> dict[str, Any]:
    """Build the netplan document for the server.

    The internet-facing NIC takes DHCP from the school network.  The
    LTSP-facing NIC gets a static address and is where dnsmasq hands out
    addresses to thin clients.

    ``link-local: []`` is set on both so no IPv6 link-local addresses appear;
    they confuse PXE clients that are looking for exactly one DHCP answer.
    """
    internet: dict[str, Any] = {
        "dhcp4": True,
        "wakeonlan": True,
        "link-local": [],
    }
    ltsp: dict[str, Any] = {
        "dhcp4": False,
        "addresses": [net.ltsp_cidr],
        "wakeonlan": True,
        "link-local": [],
    }
    if net.mac_for_internet:
        internet["match"] = {"macaddress": net.mac_for_internet.lower()}
        internet["set-name"] = net.nic_for_internet
    if net.mac_for_ltsp:
        ltsp["match"] = {"macaddress": net.mac_for_ltsp.lower()}
        ltsp["set-name"] = net.nic_for_ltsp

    ethernets: dict[str, Any] = {
        net.nic_for_internet: internet,
        net.nic_for_ltsp: ltsp,
    }
    for nic in net.nics_disabled:
        ethernets[nic] = {"activation-mode": "off"}
    return {
        "network": {
            "version": 2,
            "renderer": "networkd",
            "ethernets": ethernets,
        }
    }


def configure_networking(ctx: Context) -> None:
    """Replace whatever netplan config exists with ours, and apply it.

    Mint ships NetworkManager-managed config here.  Removing it and taking
    over with networkd is deliberate: the LTSP-side NIC must come up with a
    fixed address before dnsmasq starts, and NetworkManager's ordering makes
    that unreliable.
    """
    net = ctx.settings.networking
    set_hostname(ctx)

    existing = sorted(NETPLAN_DIR.glob("*.yaml")) + sorted(NETPLAN_DIR.glob("*.yml"))
    if existing:
        ctx.runner.announce(
            f"Removing {len(existing)} existing netplan file(s): "
            + ", ".join(p.name for p in existing)
        )
        ctx.runner.remove(existing)

    document = yaml.safe_dump(netplan_config(net), sort_keys=False, indent=2)
    # netplan warns loudly if these are readable by anyone but root.
    ctx.runner.write(NETPLAN_FILE, document, mode=0o600)
    ctx.runner.run(["netplan", "apply"])


def install_ltsp(ctx: Context) -> None:
    """Install the LTSP server stack from the LTSP PPA.

    The PPA supplies ``ltsp-binaries``, which is where the iPXE and other
    netboot binaries come from.  The older approach of cloning
    github.com/ltsp/binaries by hand is no longer needed.
    """
    ctx.runner.run(["add-apt-repository", "-y", LTSP_PPA])
    apt_update(ctx)
    apt_install(ctx, SERVER_PACKAGES, recommends=True)


LTSP_CONF = Path("/etc/ltsp/ltsp.conf")


def configure_ltsp(ctx: Context) -> None:
    """Generate the LTSP server configuration.

    ``--proxy-dhcp=0`` gives us a real DHCP server rather than proxy DHCP.
    That is right here because the LTSP NIC owns its own subnet and nothing
    else is answering DHCP on it.  On a network where the school's own DHCP
    server is also present, proxy DHCP would be the correct choice instead.

    ``ltsp.conf`` has to exist with ``DEFAULT_IMAGE`` set *before*
    ``ltsp ipxe`` runs, or the generated boot menu has nothing to default
    to -- confirmed on the first real netboot attempt (2026-08-19), where
    a built image sat unused because nothing told the menu about it.
    """
    ctx.runner.run(["ltsp", "dnsmasq", "--proxy-dhcp=0"])
    ctx.runner.run(["ltsp", "nfs"])
    ctx.runner.write(
        LTSP_CONF,
        templates.render(
            "ltsp.conf", {"DEFAULT_IMAGE": ctx.settings.client_template.image_name}
        ),
        mode=0o660,
    )
    ctx.runner.run(["ltsp", "ipxe"])
    ctx.runner.run(["ltsp", "initrd"])


def configure_epoptes(ctx: Context) -> None:
    """Let the admin account use Epoptes without becoming root."""
    ctx.runner.run(["gpasswd", "-a", ctx.settings.admin_user, "epoptes"])


VIRT_PACKAGES = [
    "qemu-kvm",
    "libvirt-daemon-system",
    "libvirt-clients",
    "virtinst",
    "qemu-utils",
]


def install_virt_tools(ctx: Context) -> None:
    """Install KVM and libvirt so the server can host the client-template VM.

    See ``steps/image.py``: the client template lives on the server itself
    and gets imaged locally, so the server needs to run KVM in its own
    right, not just serve netboot.
    """
    apt_install(ctx, VIRT_PACKAGES, recommends=True)
    ctx.runner.run(["systemctl", "enable", "--now", "libvirtd"])
    ctx.runner.run(["gpasswd", "-a", ctx.settings.admin_user, "libvirt"])
