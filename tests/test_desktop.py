"""Dry-run behaviour of the shared desktop-configuration steps.

Panel/keyboard-layout defaults used to live here too, baked into the client
image. They're per-student settings now (steps/students.py::configure_skel,
via /etc/skel) -- see docs/DECISIONS.md, "Student default configuration".
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ltsp_setup.config import Settings
from ltsp_setup.runner import Runner, StepFailed
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


def test_configure_racket_mime_drops_the_icon_into_every_theme(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))
    theme_dirs = [Path("/usr/share/icons/Mint-Y"), Path("/usr/share/icons/hicolor")]
    monkeypatch.setattr(ctx.runner, "list_dirs", lambda path: theme_dirs)

    common.configure_racket_mime(ctx)

    for theme_dir in theme_dirs:
        target = theme_dir / "scalable" / "mimetypes" / "application-x-racket.svg"
        assert any(
            r.message.startswith(f"write {target}:") for r in caplog.records
        ), target


def _isolate_session_lock_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep a real (dry_run=False) configure_session_lock call off the
    real /usr/local/sbin and /etc/xdg/autostart.
    """
    monkeypatch.setattr(common, "LOCAL_SBIN", tmp_path / "usr-local-sbin")
    monkeypatch.setattr(common, "AUTOSTART_DIR", tmp_path / "autostart")


def test_configure_session_lock_writes_scripts_and_autostart(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    monkeypatch.setattr(common, "PAM_LIGHTDM", tmp_path / "does-not-exist")
    ctx = Context(Settings(), Runner(dry_run=True))

    common.configure_session_lock(ctx)

    for name in (
        "ltsp-session-lock-check.sh",
        "ltsp-session-lock-release.sh",
        "ltsp-session-heartbeat.sh",
    ):
        target = common.LOCAL_SBIN / name
        assert any(
            r.message.startswith(f"write {target}:") for r in caplog.records
        ), target
    autostart_target = common.AUTOSTART_DIR / "ltsp-session-heartbeat.desktop"
    assert any(
        r.message.startswith(f"write {autostart_target}:") for r in caplog.records
    )


def test_configure_session_lock_skips_pam_patch_when_lightdm_pam_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_session_lock_paths(monkeypatch, tmp_path)
    missing = tmp_path / "missing"
    monkeypatch.setattr(common, "PAM_LIGHTDM", missing)
    ctx = Context(Settings(), Runner(dry_run=False))

    common.configure_session_lock(ctx)  # must not raise

    assert not missing.exists()


def test_configure_session_lock_patches_pam_lightdm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_session_lock_paths(monkeypatch, tmp_path)
    pam_lightdm = tmp_path / "lightdm"
    pam_lightdm.write_text(
        "auth    requisite       pam_nologin.so\n"
        "@include common-auth\n"
        "-auth    optional        pam_gnome_keyring.so\n"
        "@include common-account\n"
        "session required        pam_limits.so\n"
        "@include common-session\n"
        "session required        pam_env.so readenv=1\n"
    )
    monkeypatch.setattr(common, "PAM_LIGHTDM", pam_lightdm)
    ctx = Context(Settings(), Runner(dry_run=False))

    common.configure_session_lock(ctx)

    text = pam_lightdm.read_text()
    assert common.SESSION_LOCK_MARKER in text
    assert "ltsp-session-lock-check.sh" in text
    assert "ltsp-session-lock-release.sh" in text
    assert "type=close_session" in text

    lines = text.splitlines()
    auth_idx = lines.index("@include common-auth")
    assert lines[auth_idx + 1] == common.SESSION_LOCK_MARKER
    session_idx = lines.index("@include common-session")
    assert "ltsp-session-lock-release.sh" in lines[session_idx + 1]


def test_configure_session_lock_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_session_lock_paths(monkeypatch, tmp_path)
    pam_lightdm = tmp_path / "lightdm"
    pam_lightdm.write_text("@include common-auth\n@include common-session\n")
    monkeypatch.setattr(common, "PAM_LIGHTDM", pam_lightdm)
    ctx = Context(Settings(), Runner(dry_run=False))

    common.configure_session_lock(ctx)
    first = pam_lightdm.read_text()
    common.configure_session_lock(ctx)
    second = pam_lightdm.read_text()

    assert first == second
    assert first.count(common.SESSION_LOCK_MARKER) == 1


def test_configure_session_lock_raises_when_common_auth_include_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _isolate_session_lock_paths(monkeypatch, tmp_path)
    pam_lightdm = tmp_path / "lightdm"
    pam_lightdm.write_text("auth requisite pam_nologin.so\n")
    monkeypatch.setattr(common, "PAM_LIGHTDM", pam_lightdm)
    ctx = Context(Settings(), Runner(dry_run=False))

    with pytest.raises(StepFailed, match="common-auth"):
        common.configure_session_lock(ctx)
