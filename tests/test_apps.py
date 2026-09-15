"""Dry-run behaviour of the simple, no-repo-setup-needed app installers."""

from __future__ import annotations

import dataclasses
import logging
import subprocess
from collections.abc import Sequence

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


class TestKernelHousekeeping:
    """Old kernels are what actually fill /boot and bloat the shipped image.

    `apt autoremove` cannot touch them: Mint marks kernels manually
    installed, so autoremove never considers them -- which is exactly why
    Todd's manual autoremove left 6.14.0-37 sitting next to 7.0.0-30
    (2026-08-27). This is the code that does that job instead.
    """

    def _ctx(
        self, monkeypatch: pytest.MonkeyPatch, *, running: str, installed: list[str]
    ) -> tuple[Context, list[list[str]]]:
        ctx = Context(Settings(), Runner(dry_run=False))
        calls: list[list[str]] = []
        status = "".join(f"ii {name}\n" for name in installed)

        def fake_read(argv: Sequence[str]) -> str:
            if str(argv[0]) == "uname":
                return running + "\n"
            return status

        def fake_run(
            argv: Sequence[str], **kwargs: object
        ) -> subprocess.CompletedProcess[str]:
            calls.append([str(a) for a in argv])
            return subprocess.CompletedProcess([], 0, "", "")

        monkeypatch.setattr(ctx.runner, "read_command", fake_read)
        monkeypatch.setattr(ctx.runner, "run", fake_run)
        return ctx, calls

    def test_keeps_the_newest_and_the_running_kernel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Todd's exact case: the template booted 6.14.0-37 and the upgrade
        installed 7.0.0-30. Neither can go -- one is running, one is the
        image's reason for existing -- but anything older can.
        """
        ctx, _ = self._ctx(
            monkeypatch,
            running="6.14.0-37",
            installed=[
                "linux-image-6.14.0-36-generic",
                "linux-headers-6.14.0-36-generic",
                "linux-image-6.14.0-37-generic",
                "linux-image-7.0.0-30-generic",
            ],
        )

        purged = common.purge_old_kernels(ctx)

        assert purged == [
            "linux-headers-6.14.0-36-generic",
            "linux-image-6.14.0-36-generic",
        ]

    def test_the_previous_runs_kernel_goes_once_it_is_not_running(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Why two kernels is a steady state and not a slow leak: `image
        refresh` starts the template cold, GRUB boots the newest, and so
        last run's kernel is purgeable on this one.
        """
        ctx, _ = self._ctx(
            monkeypatch,
            running="7.0.0-30",
            installed=[
                "linux-image-6.14.0-37-generic",
                "linux-image-7.0.0-30-generic",
                "linux-image-7.0.0-31-generic",
            ],
        )

        assert common.purge_old_kernels(ctx) == ["linux-image-6.14.0-37-generic"]

    def test_never_purges_the_unversioned_metapackages(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """linux-image-generic-hwe-24.04 is what pulls the *next* kernel in.
        Removing it would quietly stop the image ever getting a new kernel
        again."""
        ctx, _ = self._ctx(
            monkeypatch,
            running="7.0.0-31",
            installed=[
                "linux-image-generic-hwe-24.04",
                "linux-headers-generic-hwe-24.04",
                "linux-image-6.14.0-37-generic",
                "linux-image-7.0.0-31-generic",
            ],
        )

        purged = common.purge_old_kernels(ctx)

        assert purged == ["linux-image-6.14.0-37-generic"]
        assert not any("hwe" in name for name in purged)

    def test_versions_compare_numerically_not_as_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ "7.0.0-9" sorts after "7.0.0-31" as a string. Picking the wrong
        newest would purge the kernel the image is meant to ship."""
        ctx, _ = self._ctx(
            monkeypatch,
            running="7.0.0-9",
            installed=[
                "linux-image-7.0.0-9-generic",
                "linux-image-7.0.0-31-generic",
            ],
        )

        assert common.purge_old_kernels(ctx) == []

    def test_does_nothing_with_a_single_kernel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, calls = self._ctx(
            monkeypatch, running="7.0.0-31", installed=["linux-image-7.0.0-31-generic"]
        )

        assert common.purge_old_kernels(ctx) == []
        assert not any("purge" in argv for argv in calls)

    def test_leaves_kernels_alone_when_uname_says_nothing_useful(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without knowing what is running, there is no safe choice to make,
        and keeping cruft beats removing the wrong thing."""
        ctx, calls = self._ctx(
            monkeypatch,
            running="",
            installed=[
                "linux-image-6.14.0-37-generic",
                "linux-image-7.0.0-31-generic",
            ],
        )

        assert common.purge_old_kernels(ctx) == []
        assert not any("purge" in argv for argv in calls)

    def test_ignores_packages_that_are_not_fully_installed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, _ = self._ctx(
            monkeypatch,
            running="7.0.0-31",
            installed=["linux-image-7.0.0-31-generic"],
        )
        monkeypatch.setattr(
            ctx.runner,
            "read_command",
            lambda argv: (
                "7.0.0-31-generic\n"
                if str(argv[0]) == "uname"
                else "un linux-image-3.0\nii linux-image-7.0.0-31-generic\n"
            ),
        )

        assert common.purge_old_kernels(ctx) == []

    def test_autoremove_purges_config_files_too(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO, logger="ltsp-setup")
        common.apt_autoremove(Context(Settings(), Runner(dry_run=True)))
        assert any("autoremove --purge -y" in r.message for r in caplog.records)
