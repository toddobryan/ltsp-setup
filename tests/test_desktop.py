"""Dry-run behaviour of the shared desktop-configuration steps.

Panel/keyboard-layout defaults used to live here too, baked into the client
image. They're per-student settings now (steps/students.py::configure_skel,
via /etc/skel) -- see docs/DECISIONS.md, "Student default configuration".
"""

from __future__ import annotations

import logging

import pytest

from ltsp_setup.config import Settings
from ltsp_setup.runner import Runner
from ltsp_setup.stages import Context
from ltsp_setup.steps import common


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


def test_configure_racket_mime_registers_the_type_and_default_app(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))
    common.configure_racket_mime(ctx)

    [mime_record] = [
        r for r in caplog.records if "racket.xml" in r.message and "write" in r.message
    ]
    assert 'pattern="*.rkt"' in mime_record.message

    [apps_record] = [
        r for r in caplog.records if str(common.MIMEAPPS_LIST) in r.message
    ]
    assert "application/x-racket=drracket.desktop" in apps_record.message

    assert any(
        r.message == "run: update-mime-database /usr/share/mime" for r in caplog.records
    )
