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
import time
from datetime import date
from pathlib import Path

import pytest

from ltsp_setup.config import Settings
from ltsp_setup.runner import Runner, StepFailed
from ltsp_setup.stages import Context
from ltsp_setup.steps import image

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
    def test_deletes_everything_except_the_live_image(
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

        pruned = image.prune_published_images(ctx)

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

        pruned = image.prune_published_images(ctx)

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

        pruned = image.prune_published_images(ctx)

        assert pruned == []
        assert calls == []  # ltsp ipxe not re-run when nothing changed

    def test_raises_when_default_image_is_not_set(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        ctx = _setup_prune(tmp_path, monkeypatch, live=None)
        (image.PUBLISHED_IMAGE_DIR / "mint-2026-08-27.img").write_text("x")

        with pytest.raises(StepFailed, match="DEFAULT_IMAGE"):
            image.prune_published_images(ctx)
