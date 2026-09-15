"""Dry-run behaviour of the client-template VM and image-build steps.

The steps here call ``Libvirt.check_host_tools()`` even during a dry run
(deliberately — see ``lab/virt.py``, which does the same thing, so you find
out you're missing virsh/virt-install/qemu-img/KVM before doing a bunch of
otherwise-pointless dry-run review). That makes these tests genuinely
dependent on the machine they run on, so they're skipped where those tools
or /dev/kvm aren't available, same as a real workstation without them.
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import time
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

from ltsp_setup.config import Settings
from ltsp_setup.runner import Runner, StepFailed
from ltsp_setup.stages import Context
from ltsp_setup.steps import image, smoke
from ltsp_setup.virt import Libvirt

HOST_TOOLS_AVAILABLE = (
    all(shutil.which(tool) for tool in ("virsh", "virt-install", "qemu-img"))
    and Path("/dev/kvm").exists()
)

requires_host_tools = pytest.mark.skipif(
    not HOST_TOOLS_AVAILABLE,
    reason="virsh, virt-install, qemu-img and /dev/kvm are not all available",
)


@requires_host_tools
def test_create_client_template_dry_run_does_not_raise() -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    image.create_client_template(ctx)


@requires_host_tools
def test_shutdown_client_template_does_not_poll_in_a_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("time.sleep should not run during a dry run")

    monkeypatch.setattr(time, "sleep", fail_if_called)
    ctx = Context(Settings(), Runner(dry_run=True))
    image.shutdown_client_template(ctx)


@requires_host_tools
def test_build_image_raises_when_the_template_does_not_exist() -> None:
    settings = dataclasses.replace(
        Settings(),
        client_template=dataclasses.replace(
            Settings().client_template, vm_name="definitely-not-a-real-domain-xyz"
        ),
    )
    ctx = Context(settings, Runner(dry_run=False))
    with pytest.raises(StepFailed, match="definitely-not-a-real-domain-xyz"):
        image.build_image(ctx)


def test_build_image_dry_run_prints_every_step_without_a_machine() -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    image.build_image(ctx)


def test_build_image_converts_and_builds_under_the_same_name(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Regression test: a real run once failed with "Image does not exist"
    because the raw source was written under one name (the static
    configured one) while `ltsp image` was asked to build a different
    (dated) name -- see man ltsp-image, "Images can be specified as simple
    names": source and published output share one name, always.
    """
    ctx = Context(Settings(), Runner(dry_run=True))
    name = image.build_image(ctx)
    printed = capsys.readouterr().out
    assert f"/srv/ltsp/{name}.img" in printed
    assert f"ltsp image --backup 0 {name}" in printed


def test_convert_to_raw_returns_the_configured_image_path() -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    raw_path = image.convert_to_raw(ctx)
    assert raw_path == image.raw_image_path(ctx)
    assert raw_path.name == "ltsp-client-template.img"


def test_run_ltsp_image_dry_run_does_not_raise() -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    image.run_ltsp_image(ctx)


def test_import_raw_image_moves_source_to_the_configured_path() -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    dest = image.import_raw_image(ctx, Path("/home/sysadmin/ltsp-client-template.img"))
    assert dest == image.raw_image_path(ctx)


def test_dated_image_name_appends_todays_date() -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    name = image.dated_image_name(ctx)
    assert name.startswith("ltsp-client-template-")
    date.fromisoformat(name.removeprefix("ltsp-client-template-"))


def test_dated_image_name_avoids_a_same_day_collision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: a second same-day rebuild once would have silently
    overwritten the first (identical dated name, ``--backup 0``), removing
    the exact fallback dated names exist to provide.
    """
    monkeypatch.setattr(image, "PUBLISHED_IMAGE_DIR", tmp_path)
    ctx = Context(Settings(), Runner(dry_run=False))
    base = image.dated_image_name(ctx)
    (tmp_path / f"{base}.img").write_text("x")
    assert image.dated_image_name(ctx) == f"{base}-2"
    (tmp_path / f"{base}-2.img").write_text("x")
    assert image.dated_image_name(ctx) == f"{base}-3"


def test_dated_image_name_skips_collision_check_in_a_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image, "PUBLISHED_IMAGE_DIR", tmp_path / "nope")
    ctx = Context(Settings(), Runner(dry_run=True))
    # PUBLISHED_IMAGE_DIR doesn't even exist -- would raise if this tried
    # to check it for real.
    assert image.dated_image_name(ctx) == image.dated_image_name(ctx)


def test_run_ltsp_image_returns_the_dated_name() -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    assert image.run_ltsp_image(ctx) == image.dated_image_name(ctx)


class TestWithDefaultImage:
    """Pure-function tests for the surgical ltsp.conf patch.

    This has to preserve everything else in the file -- a production
    ltsp.conf has real hand-written content (NFS options, per-client MAC
    sections) that predates this tool and that a full-file template render
    would destroy.
    """

    SAMPLE = (
        "# a comment\n"
        "[server]\n"
        "NFS_HOME=1\n"
        "\n"
        "[clients]\n"
        'FSTAB_HOME="server:/home /home nfs defaults 0 0"\n'
    )

    def test_inserts_when_missing(self) -> None:
        result = image._with_default_image(self.SAMPLE, "mint-2026-08-20")
        assert 'DEFAULT_IMAGE="mint-2026-08-20"' in result
        assert "NFS_HOME=1" in result
        assert 'FSTAB_HOME="server:/home /home nfs defaults 0 0"' in result

    def test_replaces_in_place(self) -> None:
        first = image._with_default_image(self.SAMPLE, "mint-2026-08-20")
        second = image._with_default_image(first, "mint-2026-08-21")
        assert 'DEFAULT_IMAGE="mint-2026-08-21"' in second
        assert "mint-2026-08-20" not in second
        assert second.count("DEFAULT_IMAGE") == 1

    def test_raises_without_a_server_section(self) -> None:
        with pytest.raises(StepFailed, match=r"\[server\]"):
            image._with_default_image("[clients]\nFOO=1\n", "mint-2026-08-20")


def test_current_default_image_reads_the_live_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conf = tmp_path / "ltsp.conf"
    conf.write_text('[server]\nDEFAULT_IMAGE="mint-2026-08-20"\n')
    monkeypatch.setattr(image, "LTSP_CONF", conf)
    ctx = Context(Settings(), Runner(dry_run=True))
    assert image.current_default_image(ctx) == "mint-2026-08-20"


def test_current_default_image_none_when_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image, "LTSP_CONF", tmp_path / "does-not-exist.conf")
    ctx = Context(Settings(), Runner(dry_run=True))
    assert image.current_default_image(ctx) is None


def test_set_default_image_preserves_other_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conf = tmp_path / "ltsp.conf"
    conf.write_text("[server]\nNFS_HOME=1\n")
    monkeypatch.setattr(image, "LTSP_CONF", conf)
    ctx = Context(Settings(), Runner(dry_run=False))
    image.set_default_image(ctx, "mint-2026-08-20")
    written = conf.read_text()
    assert 'DEFAULT_IMAGE="mint-2026-08-20"' in written
    assert "NFS_HOME=1" in written


def test_set_default_image_raises_when_conf_missing_for_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image, "LTSP_CONF", tmp_path / "does-not-exist.conf")
    ctx = Context(Settings(), Runner(dry_run=False))
    with pytest.raises(StepFailed, match="does-not-exist.conf"):
        image.set_default_image(ctx, "mint-2026-08-20")


def test_list_published_images_newest_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image, "PUBLISHED_IMAGE_DIR", tmp_path)
    (tmp_path / "mint-2026-08-18.img").write_text("x")
    (tmp_path / "mint-2026-08-20.img").write_text("x")
    (tmp_path / "mint-2026-08-19.img").write_text("x")
    ctx = Context(Settings(), Runner(dry_run=True))
    assert image.list_published_images(ctx) == [
        "mint-2026-08-20",
        "mint-2026-08-19",
        "mint-2026-08-18",
    ]


def test_list_published_images_raises_when_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression test: a real run showed "No images published yet" for a
    directory that in fact had two images in it -- Path.glob() silently
    swallows PermissionError instead of raising, and /srv/ltsp/images is
    root-owned 0700 on a real server, so an unprivileged run always hit
    this. Must raise instead of returning an empty (and wrong) list.
    """
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permission bits")
    unreadable = tmp_path / "images"
    unreadable.mkdir(mode=0o000)
    monkeypatch.setattr(image, "PUBLISHED_IMAGE_DIR", unreadable)
    ctx = Context(Settings(), Runner(dry_run=True))
    try:
        with pytest.raises(StepFailed, match="Can't read"):
            image.list_published_images(ctx)
    finally:
        unreadable.chmod(0o700)


def test_list_published_images_empty_when_dir_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(image, "PUBLISHED_IMAGE_DIR", tmp_path / "nope")
    ctx = Context(Settings(), Runner(dry_run=True))
    assert image.list_published_images(ctx) == []


def _record_calls(ctx: Context, monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture every argv the runner is asked to execute, running nothing."""
    calls: list[list[str]] = []

    def record(
        argv: Sequence[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append([str(a) for a in argv])
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(ctx.runner, "run", record)
    return calls


class TestDomifaddr:
    """Parsing `virsh domifaddr` output, which has a header and a blank line
    around the row that actually matters.
    """

    SAMPLE = (
        " Name       MAC address          Protocol     Address\n"
        "----------------------------------------------------------\n"
        " vnet0      52:54:00:78:4f:68    ipv4         192.168.122.99/24\n"
    )

    def _libvirt(self, monkeypatch: pytest.MonkeyPatch, output: str) -> Libvirt:
        lv = Libvirt("qemu:///system", Runner(dry_run=False))
        monkeypatch.setattr(lv, "virsh", lambda *a, **kw: output)
        return lv

    def test_returns_the_address_without_its_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lv = self._libvirt(monkeypatch, self.SAMPLE)
        assert lv.domifaddr("template") == "192.168.122.99"

    def test_none_before_the_guest_has_a_lease(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        no_address = (
            " Name       MAC address          Protocol     Address\n"
            "----------------------------------------------------------\n"
        )
        lv = self._libvirt(monkeypatch, no_address)
        assert lv.domifaddr("template") is None

    def test_ignores_ipv6_only_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ipv6 = (
            " Name       MAC address          Protocol     Address\n"
            " vnet0      52:54:00:78:4f:68    ipv6         fe80::1/64\n"
        )
        lv = self._libvirt(monkeypatch, ipv6)
        assert lv.domifaddr("template") is None


class TestUpdateClientTemplate:
    """The remote half of `image refresh`, which drives the template over
    SSH using only sudoers rules it already has.
    """

    def _ctx_and_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> tuple[Context, list[list[str]]]:
        ctx = Context(Settings(), Runner(dry_run=True))
        calls = _record_calls(ctx, monkeypatch)
        return ctx, calls

    def _remote_commands(self, calls: list[list[str]]) -> list[str]:
        return [argv[-1] for argv in calls if argv[0] == "ssh"]

    def test_reclones_bootstraps_runs_stages_then_cleans_up(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, calls = self._ctx_and_calls(monkeypatch)

        image.update_client_template(ctx, ["mirrors", "apps"])

        commands = self._remote_commands(calls)
        assert "rm -rf /home/sysadmin/ltsp-setup" in commands[0]
        assert "git clone" in commands[0]
        assert commands[1] == "sudo -n /home/sysadmin/ltsp-setup/bootstrap.sh"
        assert commands[2].endswith("client stage mirrors --no-debug")
        assert commands[3].endswith("client stage apps --no-debug")
        assert commands[4].endswith("client cleanup --no-debug")

    def test_every_remote_command_is_passwordless(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anything needing an interactive sudo password would hang a cron
        run forever, so every elevated command has to use `sudo -n`.
        """
        ctx, calls = self._ctx_and_calls(monkeypatch)

        image.update_client_template(ctx, ["mirrors"])

        for command in self._remote_commands(calls):
            if "sudo" in command:
                assert "sudo -n " in command, command

    def test_ssh_never_falls_back_to_a_password_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx, calls = self._ctx_and_calls(monkeypatch)

        image.update_client_template(ctx, ["mirrors"])

        for argv in calls:
            if argv[0] == "ssh":
                assert "BatchMode=yes" in argv

    def test_ssh_names_the_admin_users_key_explicitly(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regression test: everything here runs under sudo, so leaving the
        identity to ssh's defaults means root's empty ~/.ssh and an instant
        "Permission denied (publickey,password)" -- how this failed on its
        first real run (2026-09-09).
        """
        ctx, calls = self._ctx_and_calls(monkeypatch)

        image.update_client_template(ctx, ["mirrors"])

        for argv in calls:
            if argv[0] == "ssh":
                assert "-i" in argv
                assert argv[argv.index("-i") + 1] == "/home/sysadmin/.ssh/id_ed25519"


class TestTemplateSshKey:
    def test_defaults_to_the_admin_users_key(self) -> None:
        ctx = Context(Settings(admin_user="sysadmin"), Runner(dry_run=True))
        assert image.template_ssh_key(ctx) == Path("/home/sysadmin/.ssh/id_ed25519")

    def test_configured_key_wins(self) -> None:
        settings = dataclasses.replace(
            Settings(),
            client_template=dataclasses.replace(
                Settings().client_template, ssh_key="/etc/ltsp-setup/template.key"
            ),
        )
        ctx = Context(settings, Runner(dry_run=True))
        assert image.template_ssh_key(ctx) == Path("/etc/ltsp-setup/template.key")


def test_refresh_image_stops_short_of_publishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh build must not become live on its own -- "once we're sure it
    works" is a real gate (Todd, 2026-09-09).
    """
    ctx = Context(Settings(), Runner(dry_run=True))
    calls = _record_calls(ctx, monkeypatch)
    monkeypatch.setattr(image, "set_default_image", _must_not_be_called)
    monkeypatch.setattr(image, "prune_published_images", _must_not_be_called)

    image.refresh_image(ctx, ["mirrors"])

    flattened = " ".join(" ".join(argv) for argv in calls)
    assert "ltsp image --backup 0" in flattened
    assert "ipxe" not in flattened  # set_default_image's tell


def _must_not_be_called(*args: object, **kwargs: object) -> None:
    raise AssertionError("refresh_image must not publish the build itself")


class TestPublishImage:
    """The unattended half: go live, prove it boots, put it back if it doesn't.

    A bad build going live unnoticed is the failure Todd actually worried
    about when he asked for the weekly rebuild (2026-09-12), so the rollback
    path gets more attention here than the happy one.
    """

    def _ctx(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, live: str
    ) -> Context:
        conf = tmp_path / "ltsp.conf"
        conf.write_text(f'[server]\nDEFAULT_IMAGE="{live}"\n')
        monkeypatch.setattr(image, "LTSP_CONF", conf)
        monkeypatch.setattr(image, "PUBLISHED_IMAGE_DIR", tmp_path / "images")
        monkeypatch.setattr(image, "TFTP_IMAGE_DIR", tmp_path / "tftp")
        ctx = Context(Settings(), Runner(dry_run=False))
        monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: None)
        return ctx

    def test_makes_the_build_live_then_prunes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = self._ctx(tmp_path, monkeypatch, live="mint-2026-09-07")
        monkeypatch.setattr(smoke, "smoke_test_client", lambda _c: "192.168.67.99")
        pruned: list[int] = []

        def record_prune(_c: Context, *, keep: int) -> list[str]:
            pruned.append(keep)
            return []

        monkeypatch.setattr(image, "prune_published_images", record_prune)

        image.publish_image(ctx, "mint-2026-09-14")

        assert image.current_default_image(ctx) == "mint-2026-09-14"
        assert pruned == [1]  # image_refresh.keep_rollback_images

    def test_rolls_default_image_back_when_the_build_does_not_boot(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = self._ctx(tmp_path, monkeypatch, live="mint-2026-09-07")
        monkeypatch.setattr(smoke, "smoke_test_client", _fails_to_boot)

        with pytest.raises(StepFailed, match="rolled back to mint-2026-09-07"):
            image.publish_image(ctx, "mint-2026-09-14")

        assert image.current_default_image(ctx) == "mint-2026-09-07"

    def test_does_not_prune_the_rollback_it_just_fell_back_to(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Pruning after a failed smoke test would delete the very image
        DEFAULT_IMAGE was just pointed back at."""
        ctx = self._ctx(tmp_path, monkeypatch, live="mint-2026-09-07")
        monkeypatch.setattr(smoke, "smoke_test_client", _fails_to_boot)
        monkeypatch.setattr(image, "prune_published_images", _must_not_be_called)

        with pytest.raises(StepFailed):
            image.publish_image(ctx, "mint-2026-09-14")

    def test_says_so_when_there_is_nothing_to_roll_back_to(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conf = tmp_path / "ltsp.conf"
        conf.write_text("[server]\n")
        monkeypatch.setattr(image, "LTSP_CONF", conf)
        ctx = Context(Settings(), Runner(dry_run=False))
        monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: None)
        monkeypatch.setattr(smoke, "smoke_test_client", _fails_to_boot)

        with pytest.raises(StepFailed, match="no previous DEFAULT_IMAGE"):
            image.publish_image(ctx, "mint-2026-09-14")


def _fails_to_boot(*args: object, **kwargs: object) -> str:
    raise StepFailed("never connected to epoptes")


@requires_host_tools
def test_refresh_image_publishes_only_when_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = Context(Settings(), Runner(dry_run=True))
    _record_calls(ctx, monkeypatch)
    published: list[str] = []
    monkeypatch.setattr(image, "publish_image", lambda _c, name: published.append(name))

    image.refresh_image(ctx, ["mirrors"], publish=True)

    assert published == [image.dated_image_name(ctx)]


class TestRefreshTimer:
    def test_the_scheduled_command_publishes_and_never_prompts(self) -> None:
        """--publish is the whole reason the timer exists, and --no-debug is
        what makes it do anything at all rather than print a preview into
        the journal."""
        ctx = Context(Settings(), Runner(dry_run=True))
        command = image.refresh_command(ctx, None)
        assert " image refresh --publish --no-debug --stage mirrors" in command

    def test_the_scheduled_command_carries_the_config_file_through(self) -> None:
        ctx = Context(Settings(), Runner(dry_run=True))
        command = image.refresh_command(ctx, Path("/etc/ltsp-setup.toml"))
        assert command.endswith("--config /etc/ltsp-setup.toml")

    def test_every_configured_stage_reaches_the_command(self) -> None:
        settings = dataclasses.replace(
            Settings(),
            image_refresh=dataclasses.replace(
                Settings().image_refresh, stages=("mirrors", "apps")
            ),
        )
        command = image.refresh_command(Context(settings, Runner(dry_run=True)), None)
        assert "--stage mirrors --stage apps" in command

    def test_installing_enables_the_timer_but_not_the_service(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An enabled oneshot service would run an hour-long image build at
        every boot. Only the timer gets enabled."""
        ctx = Context(Settings(), Runner(dry_run=True))
        calls = _record_calls(ctx, monkeypatch)
        written: dict[Path, str] = {}
        monkeypatch.setattr(
            ctx.runner, "write", lambda path, text, **kw: written.update({path: text})
        )

        image.install_refresh_timer(ctx)

        assert set(written) == {image.REFRESH_SERVICE_PATH, image.REFRESH_TIMER_PATH}
        assert "[Install]" not in written[image.REFRESH_SERVICE_PATH]
        assert ["systemctl", "enable", "--now", "ltsp-setup-image.timer"] in calls

    def test_the_timer_carries_the_configured_schedule(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        settings = dataclasses.replace(
            Settings(),
            image_refresh=dataclasses.replace(
                Settings().image_refresh, on_calendar="Sat *-*-* 23:00:00"
            ),
        )
        ctx = Context(settings, Runner(dry_run=True))
        _record_calls(ctx, monkeypatch)
        written: dict[Path, str] = {}
        monkeypatch.setattr(
            ctx.runner, "write", lambda path, text, **kw: written.update({path: text})
        )

        image.install_refresh_timer(ctx)

        assert "OnCalendar=Sat *-*-* 23:00:00" in written[image.REFRESH_TIMER_PATH]
        # A caught-up run means starting a rebuild whenever the server next
        # boots, most likely Monday morning. Skipping a week is cheaper.
        directives = [
            line
            for line in written[image.REFRESH_TIMER_PATH].splitlines()
            if line.strip() and not line.startswith("#")
        ]
        assert not any(line.startswith("Persistent=") for line in directives)

    def test_removing_disables_and_deletes_both_units(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = Context(Settings(), Runner(dry_run=True))
        calls = _record_calls(ctx, monkeypatch)
        removed: list[list[Path]] = []
        monkeypatch.setattr(
            ctx.runner, "remove", lambda paths: removed.append(list(paths))
        )

        image.remove_refresh_timer(ctx)

        assert ["systemctl", "disable", "--now", "ltsp-setup-image.timer"] in calls
        assert removed == [[image.REFRESH_TIMER_PATH, image.REFRESH_SERVICE_PATH]]


def _setup_prune(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, live: str | None
) -> Context:
    images_dir = tmp_path / "images"
    images_dir.mkdir()
    tftp_dir = tmp_path / "tftp"
    tftp_dir.mkdir()
    conf = tmp_path / "ltsp.conf"
    if live is not None:
        conf.write_text(f'[server]\nDEFAULT_IMAGE="{live}"\n')
    else:
        conf.write_text("[server]\n")
    monkeypatch.setattr(image, "PUBLISHED_IMAGE_DIR", images_dir)
    monkeypatch.setattr(image, "TFTP_IMAGE_DIR", tftp_dir)
    monkeypatch.setattr(image, "LTSP_CONF", conf)
    return Context(Settings(), Runner(dry_run=False))


class TestPrunePublishedImages:
    def test_keep_zero_deletes_everything_except_the_live_image(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _setup_prune(tmp_path, monkeypatch, live="mint-2026-08-27")
        for name in ["mint-2026-08-25", "mint-2026-08-26", "mint-2026-08-27"]:
            (image.PUBLISHED_IMAGE_DIR / f"{name}.img").write_text("x")
            (image.TFTP_IMAGE_DIR / name).mkdir()
            (image.TFTP_IMAGE_DIR / name / "vmlinuz").write_text("x")
        calls: list[list[str]] = []
        monkeypatch.setattr(
            ctx.runner, "run", lambda argv, **kw: calls.append(list(argv))
        )

        pruned = image.prune_published_images(ctx, keep=0)

        assert pruned == ["mint-2026-08-26", "mint-2026-08-25"]
        assert not (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-25.img").exists()
        assert not (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-26.img").exists()
        assert not (image.TFTP_IMAGE_DIR / "mint-2026-08-25").exists()
        assert not (image.TFTP_IMAGE_DIR / "mint-2026-08-26").exists()
        assert (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-27.img").exists()
        assert (image.TFTP_IMAGE_DIR / "mint-2026-08-27").exists()
        assert calls == [["ltsp", "ipxe"]]

    def test_handles_a_build_with_only_one_half_of_the_pair(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A build from before this tool existed may have only a squashfs
        or only a tftp dir, not both -- pruning must still work off the
        union of names, not just one directory.
        """
        ctx = _setup_prune(tmp_path, monkeypatch, live="mint-2026-08-27")
        (image.PUBLISHED_IMAGE_DIR / "squashfs-only.img").write_text("x")
        (image.TFTP_IMAGE_DIR / "tftp-only").mkdir()
        (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-27.img").write_text("x")
        (image.TFTP_IMAGE_DIR / "mint-2026-08-27").mkdir()
        monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: None)

        pruned = image.prune_published_images(ctx, keep=0)

        assert set(pruned) == {"squashfs-only", "tftp-only"}
        assert not (image.PUBLISHED_IMAGE_DIR / "squashfs-only.img").exists()
        assert not (image.TFTP_IMAGE_DIR / "tftp-only").exists()

    def test_does_nothing_when_only_the_live_image_is_published(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _setup_prune(tmp_path, monkeypatch, live="mint-2026-08-27")
        (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-27.img").write_text("x")
        (image.TFTP_IMAGE_DIR / "mint-2026-08-27").mkdir()
        calls: list[list[str]] = []
        monkeypatch.setattr(
            ctx.runner, "run", lambda argv, **kw: calls.append(list(argv))
        )

        pruned = image.prune_published_images(ctx, keep=0)

        assert pruned == []
        assert calls == []  # ltsp ipxe not re-run when nothing changed

    def test_raises_when_default_image_is_not_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _setup_prune(tmp_path, monkeypatch, live=None)
        (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-27.img").write_text("x")

        with pytest.raises(StepFailed, match="DEFAULT_IMAGE"):
            image.prune_published_images(ctx)

    def test_keeps_the_newest_superseded_build_as_a_rollback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The whole point of the weekly rebuild keeping a rollback: last
        week's proven-to-boot image has to survive the prune that follows
        this week's (Todd, 2026-09-12).
        """
        ctx = _setup_prune(tmp_path, monkeypatch, live="mint-2026-08-27")
        for name in ["mint-2026-08-24", "mint-2026-08-25", "mint-2026-08-26"]:
            (image.PUBLISHED_IMAGE_DIR / f"{name}.img").write_text("x")
            (image.TFTP_IMAGE_DIR / name).mkdir()
        (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-27.img").write_text("x")
        (image.TFTP_IMAGE_DIR / "mint-2026-08-27").mkdir()
        monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: None)

        pruned = image.prune_published_images(ctx, keep=1)

        assert pruned == ["mint-2026-08-25", "mint-2026-08-24"]
        # Both halves of the rollback survive -- the squashfs is useless if
        # `ltsp ipxe` can't find a kernel to go with it.
        assert (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-26.img").exists()
        assert (image.TFTP_IMAGE_DIR / "mint-2026-08-26").exists()
        assert (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-27.img").exists()

    def test_defaults_to_keeping_one_rollback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _setup_prune(tmp_path, monkeypatch, live="mint-2026-08-27")
        for name in ["mint-2026-08-25", "mint-2026-08-26", "mint-2026-08-27"]:
            (image.PUBLISHED_IMAGE_DIR / f"{name}.img").write_text("x")
            (image.TFTP_IMAGE_DIR / name).mkdir()
        monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: None)

        assert image.prune_published_images(ctx) == ["mint-2026-08-25"]

    def test_keeping_more_than_exist_prunes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _setup_prune(tmp_path, monkeypatch, live="mint-2026-08-27")
        for name in ["mint-2026-08-26", "mint-2026-08-27"]:
            (image.PUBLISHED_IMAGE_DIR / f"{name}.img").write_text("x")
            (image.TFTP_IMAGE_DIR / name).mkdir()
        monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: None)

        assert image.prune_published_images(ctx, keep=5) == []

    def test_a_half_build_is_never_kept_as_the_rollback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Found on the real server, 2026-09-15: an orphaned 2026-09-09 tftp
        directory whose squashfs was already gone. It sorts newer than the
        proven 2026-08-28-2, so keeping "the newest superseded build" would
        have kept something unbootable and deleted the working fallback --
        the exact failure the rollback exists to prevent.
        """
        ctx = _setup_prune(tmp_path, monkeypatch, live="mint-2026-09-15")
        (image.PUBLISHED_IMAGE_DIR / "mint-2026-09-15.img").write_text("x")
        (image.TFTP_IMAGE_DIR / "mint-2026-09-15").mkdir()
        # The proven fallback: both halves present.
        (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-28.img").write_text("x")
        (image.TFTP_IMAGE_DIR / "mint-2026-08-28").mkdir()
        # The orphan: a kernel with no squashfs behind it.
        (image.TFTP_IMAGE_DIR / "mint-2026-09-09").mkdir()
        monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: None)

        pruned = image.prune_published_images(ctx, keep=1)

        assert pruned == ["mint-2026-09-09"]
        assert (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-28.img").exists()
        assert (image.TFTP_IMAGE_DIR / "mint-2026-08-28").exists()
        assert not (image.TFTP_IMAGE_DIR / "mint-2026-09-09").exists()

    def test_a_squashfs_with_no_kernel_is_not_kept_either(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The mirror image of the case above: `ltsp ipxe` would offer this
        one in the menu, but choosing it finds no kernel to boot.
        """
        ctx = _setup_prune(tmp_path, monkeypatch, live="mint-2026-09-15")
        (image.PUBLISHED_IMAGE_DIR / "mint-2026-09-15.img").write_text("x")
        (image.TFTP_IMAGE_DIR / "mint-2026-09-15").mkdir()
        (image.PUBLISHED_IMAGE_DIR / "mint-2026-09-09.img").write_text("x")
        (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-28.img").write_text("x")
        (image.TFTP_IMAGE_DIR / "mint-2026-08-28").mkdir()
        monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: None)

        assert image.prune_published_images(ctx, keep=1) == ["mint-2026-09-09"]
        assert (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-28.img").exists()

    def test_negative_keep_is_refused(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A negative slice index would silently keep the *newest* builds and
        delete the rest, which is the opposite of what was asked for.
        """
        ctx = _setup_prune(tmp_path, monkeypatch, live="mint-2026-08-27")
        (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-26.img").write_text("x")

        with pytest.raises(StepFailed, match="negative"):
            image.prune_published_images(ctx, keep=-1)
