"""Dry-run behaviour of the shared low-level libvirt plumbing."""

from __future__ import annotations

from ltsp_setup.runner import Runner
from ltsp_setup.virt import Libvirt


def test_virsh_never_executes_in_a_dry_run() -> None:
    lv = Libvirt("qemu:///system", Runner(dry_run=True))
    result = lv.virsh("list", "--all")
    assert result == ""


def test_domain_exists_is_false_in_a_dry_run() -> None:
    lv = Libvirt("qemu:///system", Runner(dry_run=True))
    assert lv.domain_exists("anything") is False


def test_domstate_is_shut_off_in_a_dry_run() -> None:
    lv = Libvirt("qemu:///system", Runner(dry_run=True))
    assert lv.domstate("anything") == "shut off"


def test_network_exists_is_false_in_a_dry_run() -> None:
    lv = Libvirt("qemu:///system", Runner(dry_run=True))
    assert lv.network_exists("anything") is False
