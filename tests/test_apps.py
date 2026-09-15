"""Dry-run behaviour of the simple, no-repo-setup-needed app installers."""

from __future__ import annotations

import dataclasses
import logging

import pytest

from ltsp_setup.config import Apps, Settings
from ltsp_setup.runner import Runner
from ltsp_setup.stages import Context
from ltsp_setup.steps import apps, common


def test_install_gimp_installs_the_gimp_package(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    apps.install_gimp(ctx)

    assert any("install -y gimp" in r.message for r in caplog.records)


def test_install_shotcut_installs_the_shotcut_package(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    apps.install_shotcut(ctx)

    assert any("install -y shotcut" in r.message for r in caplog.records)


def test_install_simplescreenrecorder_installs_the_package(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    apps.install_simplescreenrecorder(ctx)

    assert any("install -y simplescreenrecorder" in r.message for r in caplog.records)


def test_install_tree_installs_the_package(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    apps.install_tree(ctx)

    assert any("install -y tree" in r.message for r in caplog.records)


def test_install_cowsay_installs_the_package(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    apps.install_cowsay(ctx)

    assert any("install -y cowsay" in r.message for r in caplog.records)


def test_install_figlet_installs_the_package(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))

    apps.install_figlet(ctx)

    assert any("install -y figlet" in r.message for r in caplog.records)


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


class TestAptLockTimeout:
    """Every apt-get this tool runs has to wait for the dpkg lock rather
    than fail on it. `unattended-upgrades` holds that lock for minutes at a
    time in the small hours, which is exactly when the weekly image rebuild
    runs -- without this, a rebuild fails for a reason that has nothing to
    do with the image (Todd, 2026-09-12).
    """

    def _messages(self, caplog: pytest.LogCaptureFixture) -> str:
        return " ".join(r.message for r in caplog.records)

    def test_install_waits_for_the_lock(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, logger="ltsp-setup")
        common.apt_install(Context(Settings(), Runner(dry_run=True)), ["tree"])
        assert "apt-get -o DPkg::Lock::Timeout=600 install -y tree" in self._messages(
            caplog
        )

    def test_update_waits_for_the_lock(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, logger="ltsp-setup")
        common.apt_update(Context(Settings(), Runner(dry_run=True)))
        assert "apt-get -o DPkg::Lock::Timeout=600 update" in self._messages(caplog)

    def test_upgrade_waits_for_the_lock(self, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, logger="ltsp-setup")
        common.apt_upgrade(Context(Settings(), Runner(dry_run=True)))
        assert "apt-get -o DPkg::Lock::Timeout=600 upgrade -y" in self._messages(caplog)

    def test_the_timeout_comes_from_config(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO, logger="ltsp-setup")
        settings = dataclasses.replace(Settings(), apt_lock_timeout_s=30)
        common.apt_update(Context(settings, Runner(dry_run=True)))
        assert "DPkg::Lock::Timeout=30" in self._messages(caplog)
