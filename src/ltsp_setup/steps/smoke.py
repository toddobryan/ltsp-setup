"""Netbooting a throwaway client to prove a fresh image actually works.

``image build`` publishes a squashfs. Nothing about that says the thing
boots. Up to now the check was Todd walking to a lab machine and turning it
on, which is fine for a rebuild he started by hand and impossible for one
that runs at two in the morning on a Saturday. This module is the automated
stand-in: boot the diskless ``pxe-test-client`` VM, which is a thin client
in every respect except that it lives on the server, and watch for evidence
that it came all the way up.

The evidence comes in two stages, because they fail differently and the
difference is the whole diagnosis:

1. **A fresh DHCP lease.** dnsmasq handed the client an address, which means
   PXE and DHCP work. Not much more than that -- iPXE gets a lease of its
   own well before any kernel runs.
2. **An epoptes-client connection back to the server.** ``epoptes-client``
   is a systemd service in ``CLIENT_PACKAGES``, so it is in every image this
   tool builds, and it connects at boot rather than at login. Seeing it
   means the squashfs mounted, the kernel booted it, and userspace came up
   far enough to start services. iPXE cannot produce this, so it is not a
   signal that can pass by accident.

Neither stage proves the *desktop* is usable -- a client that boots to a
broken greeter would still pass. That is a deliberate limit: this is a smoke
test, not a login test, and its job is to catch the failure that actually
happens (an image that does not boot at all) before the whole lab meets it
on Monday morning.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ltsp_setup.runner import StepFailed
from ltsp_setup.stages import Context
from ltsp_setup.virt import Libvirt

# Slower than the template's SSH poll: this waits on a cold netboot of a
# multi-gigabyte squashfs over NFS, where a couple of seconds either way
# makes no difference and the extra `ss` invocations do.
POLL_INTERVAL_S = 5

# What a dry run reports instead of an address it cannot look up.
DRY_RUN_ADDRESS = "<test-client-ip>"


@dataclass(frozen=True)
class Lease:
    """One of dnsmasq's IPv4 leases."""

    address: str
    expires_at: int


def _libvirt(ctx: Context) -> Libvirt:
    return Libvirt(ctx.settings.smoke_test.connect_uri, ctx.runner)


def leases_for(ctx: Context, mac: str) -> list[Lease]:
    """Every IPv4 lease dnsmasq currently holds for ``mac``.

    More than one is normal, not a bug to clean up: iPXE and the booted
    kernel send different DHCP client-ids for the same MAC, so dnsmasq
    tracks them as separate leases and hands out separate addresses. Both
    are returned, because which one the running system ends up on isn't
    knowable from here -- callers watch all of them.

    The lease file is world-readable, which is what makes this work without
    root during a dry run.
    """
    path = ctx.settings.smoke_test.lease_file
    if not ctx.runner.exists(path):
        return []
    found: list[Lease] = []
    for line in ctx.runner.read_text(path).splitlines():
        fields = line.split()
        # "1789518860 b0:0c:d1:5d:e6:03 192.168.67.62 hostname 01:b0:0c:..."
        if len(fields) < 3 or fields[1].lower() != mac.lower():
            continue
        if ":" in fields[2]:  # an IPv6 lease; the clients boot over v4
            continue
        try:
            expires_at = int(fields[0])
        except ValueError:
            continue
        found.append(Lease(fields[2], expires_at))
    return found


def agent_peers(ctx: Context, addresses: set[str]) -> set[str]:
    """``"address:port"`` for every established epoptes connection from ``addresses``.

    The port matters as much as the address: it is what distinguishes a
    connection this boot just made from one the kernel is still showing as
    ESTABLISHED for a client that has already been powered off. Without it,
    a smoke test could pass on the corpse of the previous run.
    """
    if not addresses:
        return set()
    result = ctx.runner.run(
        [
            "ss",
            "-H",
            "-tn",
            "state",
            "established",
            "sport",
            "=",
            f":{ctx.settings.smoke_test.agent_port}",
        ],
        check=False,
        capture=True,
    )
    peers = set()
    for line in (result.stdout or "").splitlines():
        fields = line.split()
        # "0  0  192.168.67.1:789  192.168.67.107:37598"
        if len(fields) < 4:
            continue
        peer = fields[3]
        if peer.rsplit(":", 1)[0] in addresses:
            peers.add(peer)
    return peers


def _force_off(ctx: Context, lv: Libvirt, name: str) -> None:
    """Get the test client to "shut off", politely first, then not.

    It is diskless and its ``/home`` is the server's own, so a hard power
    off costs nothing but an NFS server-side cleanup -- but ask nicely
    first anyway, since a clean unmount is one fewer stale lock for the
    next login to trip over.
    """
    st = ctx.settings.smoke_test
    if lv.domstate(name) == "shut off":
        return
    lv.virsh("shutdown", name, check=False)
    deadline = time.monotonic() + st.shutdown_timeout_s
    while time.monotonic() < deadline:
        if lv.domstate(name) == "shut off":
            return
        time.sleep(POLL_INTERVAL_S)
    ctx.runner.announce(f"{name} ignored the shutdown request; forcing it off")
    lv.virsh("destroy", name, check=False)


def _wait_for_lease(ctx: Context, mac: str, baseline: int, deadline: float) -> set[str]:
    """Wait for dnsmasq to hand ``mac`` a lease newer than ``baseline``.

    Compares expiry timestamps rather than merely checking that a lease
    exists, because one almost always already does -- the test client has
    booted before, and dnsmasq keeps leases for twelve hours. A renewed or
    newly issued lease pushes the expiry forward; a leftover one from last
    week's run does not.
    """
    st = ctx.settings.smoke_test
    while time.monotonic() < deadline:
        leases = leases_for(ctx, mac)
        if leases and max(lease.expires_at for lease in leases) > baseline:
            addresses = {lease.address for lease in leases}
            ctx.runner.announce(
                f"{st.vm_name} got a DHCP lease: {', '.join(sorted(addresses))}"
            )
            return addresses
        time.sleep(POLL_INTERVAL_S)
    raise StepFailed(
        f"{st.vm_name} never asked for a DHCP lease. It did not get as far "
        "as PXE, so this is a DHCP, TFTP or iPXE problem rather than an "
        "image problem -- the new image has not been proven bad.\n"
        f"Watch it boot with:  virsh --connect {st.connect_uri} "
        f"console {st.vm_name}"
    )


def _wait_for_agent(
    ctx: Context, mac: str, addresses: set[str], ignore: set[str], deadline: float
) -> str:
    """Wait for a *new* epoptes connection from ``addresses`` or a later lease.

    The lease file is re-read on every poll, not just once. iPXE's lease is
    what ``_wait_for_lease`` sees first; the booted kernel asks for its own
    a few seconds later, often gets a different address, and that later one
    is the address epoptes connects from.
    """
    st = ctx.settings.smoke_test
    while time.monotonic() < deadline:
        addresses = addresses | {lease.address for lease in leases_for(ctx, mac)}
        new = agent_peers(ctx, addresses) - ignore
        if new:
            peer = sorted(new)[0]
            return peer.rsplit(":", 1)[0]
        time.sleep(POLL_INTERVAL_S)
    raise StepFailed(
        f"{st.vm_name} got an address ({', '.join(sorted(addresses))}) but "
        f"never connected to epoptes on port {st.agent_port}. It reached "
        "PXE and then stopped, which points at the image itself: a squashfs "
        "that will not mount, a kernel that panics, or a userspace that "
        "does not come up.\n"
        f"Watch it boot with:  virsh --connect {st.connect_uri} "
        f"console {st.vm_name}"
    )


def smoke_test_client(ctx: Context) -> str:
    """Netboot the test client against whatever image is currently live.

    This tests ``DEFAULT_IMAGE``, not a name passed in, because that is the
    only thing a netbooting client will actually pick up -- which is why
    ``publish_image`` sets the new build live *first* and keeps a rollback
    ready, rather than trying to test an image that nothing is pointed at.

    Always leaves the VM shut off, pass or fail.

    Returns:
        The address the client came up on.

    Raises:
        StepFailed: if it never booted far enough to prove anything.
    """
    st = ctx.settings.smoke_test
    lv = _libvirt(ctx)

    if ctx.runner.dry_run:
        ctx.runner.announce(
            f"Would netboot {st.vm_name} and wait up to {st.boot_timeout_s}s "
            f"for it to connect to epoptes on port {st.agent_port}"
        )
        return DRY_RUN_ADDRESS

    if not lv.domain_exists(st.vm_name):
        raise StepFailed(
            f"No smoke-test VM named {st.vm_name!r} at {st.connect_uri}.\n"
            "It should be a diskless VM bridged onto the LTSP network, with "
            "<boot dev='network'/> and no disk -- a thin client that happens "
            "to live on the server. Create one, or point "
            "smoke_test.vm_name at an existing one."
        )

    mac = lv.mac_address(st.vm_name)
    _force_off(ctx, lv, st.vm_name)

    # Everything already true before the VM boots is not evidence. Both
    # baselines are taken while it is definitely off, so anything seen
    # afterwards belongs to this boot.
    before = leases_for(ctx, mac)
    baseline_expiry = max((lease.expires_at for lease in before), default=0)
    stale_peers = agent_peers(ctx, {lease.address for lease in before})

    ctx.runner.announce(f"Netbooting {st.vm_name} ({mac}) to smoke-test the image")
    lv.virsh("start", st.vm_name)
    try:
        deadline = time.monotonic() + st.boot_timeout_s
        addresses = _wait_for_lease(ctx, mac, baseline_expiry, deadline)
        address = _wait_for_agent(ctx, mac, addresses, stale_peers, deadline)
    finally:
        _force_off(ctx, lv, st.vm_name)
    ctx.runner.announce(f"{st.vm_name} booted the live image and came up at {address}")
    return address
