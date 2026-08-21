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


def test_panel_defaults_writes_all_three_candidate_paths(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Regression test: writing only the standard XDG panel bootstrap file
    (`PANEL_DEFAULT`) turned out not to be enough -- a real fresh login
    still showed Mint's stock panel (Firefox launcher and all), traced to
    `mint-artwork`'s own XFCE-specific override at
    `PANEL_MINT_ARTWORK_SOURCE`. See the comment above `PANEL_DEFAULT` in
    steps/common.py.
    """
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))
    common.configure_panel_defaults(ctx)

    for path in (
        common.PANEL_DEFAULT,
        common.PANEL_XFCONF_SYSTEM_DEFAULT,
        common.PANEL_MINT_ARTWORK_SOURCE,
    ):
        [record] = [r for r in caplog.records if str(path) in r.message]
        assert "thunar.desktop" in record.message


def test_panel_defaults_has_the_four_dock_launchers_in_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))
    common.configure_panel_defaults(ctx)

    [record] = [r for r in caplog.records if str(common.PANEL_DEFAULT) in r.message]
    launchers = [
        "thunar.desktop",
        "google-chrome.desktop",
        "drracket.desktop",
        "xfce4-terminal.desktop",
    ]
    positions = [record.message.index(name) for name in launchers]
    assert positions == sorted(positions)


def test_panel_defaults_clock_shows_seconds(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))
    common.configure_panel_defaults(ctx)

    [record] = [r for r in caplog.records if str(common.PANEL_DEFAULT) in r.message]
    assert "%S" in record.message


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
