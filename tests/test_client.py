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

    client.cleanup_setup_tooling(ctx)

    assert removed == [
        Path("/home/sysadmin/ltsp-setup"),
        client.VENV_DIR,
    ]
