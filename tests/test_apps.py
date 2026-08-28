"""Dry-run behaviour of the simple, no-repo-setup-needed app installers."""

from __future__ import annotations

import logging

import pytest

from ltsp_setup.config import Apps, Settings
from ltsp_setup.runner import Runner
from ltsp_setup.stages import Context
from ltsp_setup.steps import apps


def test_install_gimp_installs_the_gimp_package(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    apps.install_gimp(ctx)

    assert any("apt-get install -y gimp" in r.message for r in caplog.records)


def test_install_shotcut_installs_the_shotcut_package(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    apps.install_shotcut(ctx)

    assert any("apt-get install -y shotcut" in r.message for r in caplog.records)


def test_install_simplescreenrecorder_installs_the_package(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    apps.install_simplescreenrecorder(ctx)

    assert any(
        "apt-get install -y simplescreenrecorder" in r.message for r in caplog.records
    )


def test_install_tree_installs_the_package(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    apps.install_tree(ctx)

    assert any("apt-get install -y tree" in r.message for r in caplog.records)


def test_install_cowsay_installs_the_package(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    apps.install_cowsay(ctx)

    assert any("apt-get install -y cowsay" in r.message for r in caplog.records)


def test_install_figlet_installs_the_package(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    apps.install_figlet(ctx)

    assert any("apt-get install -y figlet" in r.message for r in caplog.records)


def test_install_all_skips_disabled_apps(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    settings = Settings(
        apps=Apps(
            java=False,
            racket=False,
            chrome=False,
            vscode=False,
            rust=False,
            gimp=False,
            shotcut=False,
            simplescreenrecorder=True,
            tree=False,
            cowsay=False,
            figlet=True,
        )
    )
    ctx = Context(settings, Runner(dry_run=True))

    apps.install_all(ctx)

    messages = [r.message for r in caplog.records]
    assert any("simplescreenrecorder" in m for m in messages)
    assert any("figlet" in m for m in messages)
    assert not any("gimp" in m for m in messages)
    assert not any("shotcut" in m for m in messages)
    assert not any(" tree" in m for m in messages)
    assert not any("cowsay" in m for m in messages)
