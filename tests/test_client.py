"""Cleaning up this project's own tooling from the client template."""

from __future__ import annotations

from pathlib import Path

import pytest

from ltsp_setup.config import Settings
from ltsp_setup.runner import Runner
from ltsp_setup.stages import Context
from ltsp_setup.steps import client


def test_cleanup_removes_the_checkout_and_the_venv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = Context(Settings(admin_user="sysadmin"), Runner(dry_run=True))
    removed: list[Path] = []
    monkeypatch.setattr(ctx.runner, "remove_tree", removed.append)
    monkeypatch.setattr(ctx.runner, "remove", lambda paths: removed.extend(paths))

    client.cleanup_setup_tooling(ctx)

    assert removed == [
        Path("/home/sysadmin/ltsp-setup"),
        client.VENV_DIR,
        client.ENTRY_POINT_LINK,
    ]


def test_cleanup_unlinks_a_dangling_entry_point_symlink(tmp_path: Path) -> None:
    """Regression test: the symlink bootstrap.sh leaves at
    /usr/local/bin/ltsp-setup points into the venv that cleanup deletes, so
    by the time it's removed it's already dangling. Runner.remove() has to
    unlink it anyway rather than skipping it as "missing" -- found on the
    real template 2026-09-09, where it had shipped in every image so far.
    """
    link = tmp_path / "ltsp-setup"
    link.symlink_to(tmp_path / "definitely-not-there")
    assert not link.exists() and link.is_symlink()

    Runner(dry_run=False).remove([link])

    assert not link.is_symlink()
