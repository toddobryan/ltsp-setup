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
