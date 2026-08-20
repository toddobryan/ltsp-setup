"""Dry-run behaviour of the shared desktop-configuration steps."""

from __future__ import annotations

import logging

import pytest

from ltsp_setup.config import Settings
from ltsp_setup.runner import Runner
from ltsp_setup.stages import Context
from ltsp_setup.steps import common


def test_panel_defaults_drops_power_manager(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))
    common.configure_panel_defaults(ctx)

    [record] = [r for r in caplog.records if str(common.PANEL_DEFAULT) in r.message]
    assert 'value="power-manager-plugin"' not in record.message


def test_autostart_hides_the_expected_entries(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))
    common.configure_autostart(ctx)

    written = {str(common.AUTOSTART_DIR / name) for name in common.HIDDEN_AUTOSTART}
    seen = {
        path
        for path in written
        for r in caplog.records
        if r.message.startswith(f"write {path}:") and "Hidden=true" in r.message
    }
    assert seen == written
