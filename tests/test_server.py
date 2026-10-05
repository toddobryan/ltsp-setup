"""Dry-run behaviour of server-side admin conveniences."""

from __future__ import annotations

import logging

import pytest

from ltsp_setup.config import Settings
from ltsp_setup.runner import Runner
from ltsp_setup.stages import Context
from ltsp_setup.steps import server


def test_configure_admin_shortcuts_installs_reset_password(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    server.configure_admin_shortcuts(ctx)

    target = server.ADMIN_BIN / "reset-password"
    [record] = [r for r in caplog.records if r.message.startswith(f"write {target}:")]
    assert "student reset-password" in record.message
    assert "--no-debug" in record.message


def _written(caplog: pytest.LogCaptureFixture, path: object) -> str:
    [record] = [r for r in caplog.records if r.message.startswith(f"write {path}:")]
    return record.message


def test_configure_nat_turns_on_forwarding_persistently(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    server.configure_nat(Context(Settings(), Runner(dry_run=True)))

    assert "net.ipv4.ip_forward = 1" in _written(caplog, server.SYSCTL_IP_FORWARD)


def test_configure_nat_unit_masquerades_only_traffic_leaving_the_subnet(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    server.configure_nat(Context(Settings(), Runner(dry_run=True)))

    unit = _written(caplog, server.NAT_UNIT)
    rule = "POSTROUTING -s 192.168.67.0/24 ! -d 192.168.67.0/24 -j MASQUERADE"
    assert f"ExecStart=/usr/sbin/iptables -t nat -A {rule}" in unit


def test_configure_nat_unit_never_stacks_duplicate_rules(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Restarting the unit (re-running the stage) deletes before it adds."""
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    server.configure_nat(Context(Settings(), Runner(dry_run=True)))

    unit = _written(caplog, server.NAT_UNIT)
    assert "ExecStartPre=-/usr/sbin/iptables -t nat -D POSTROUTING" in unit
    assert "ExecStop=-/usr/sbin/iptables -t nat -D POSTROUTING" in unit
