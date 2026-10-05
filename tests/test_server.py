"""Dry-run behaviour of server-side admin conveniences."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

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


def test_nfsd_threads_go_in_a_drop_in_not_the_package_conffile(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    server.configure_nfsd_threads(Context(Settings(), Runner(dry_run=True)))

    assert server.NFS_CONF_DROPIN.parent == Path("/etc/nfs.conf.d")
    written = _written(caplog, server.NFS_CONF_DROPIN)
    assert "[nfsd]\nthreads=64\n" in written


def test_nfsd_threads_resize_the_running_server_without_a_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = Context(Settings(nfsd_threads=96), Runner(dry_run=True))
    calls: list[list[str]] = []

    def record(argv: Sequence[str], **kwargs: object) -> None:
        calls.append(list(argv))

    monkeypatch.setattr(ctx.runner, "run", record)
    server.configure_nfsd_threads(ctx)

    assert calls == [["rpc.nfsd", "96"]]
