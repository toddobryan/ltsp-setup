"""The dry-run guarantee: nothing on disk changes, nothing is executed."""

from __future__ import annotations

import grp
import pwd
from pathlib import Path

import pytest

from ltsp_setup.runner import Runner, StepFailed


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "file.conf"
    Runner(dry_run=True).write(target, "hello\n")
    assert not target.exists()


def test_real_run_writes_and_sets_mode(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "file.conf"
    Runner(dry_run=False).write(target, "hello\n", mode=0o600)
    assert target.read_text() == "hello\n"
    assert target.stat().st_mode & 0o777 == 0o600


def test_dry_run_reports_success_without_executing() -> None:
    result = Runner(dry_run=True).run(["false"])
    assert result.returncode == 0


def test_failing_command_raises_with_the_command_in_the_message() -> None:
    with pytest.raises(StepFailed, match="false"):
        Runner(dry_run=False).run(["false"], capture=True)


def test_check_false_returns_the_failure_instead_of_raising() -> None:
    result = Runner(dry_run=False).run(["false"], check=False, capture=True)
    assert result.returncode != 0


def test_append_line_is_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "profile"
    target.write_text("existing\n")
    runner = Runner(dry_run=False)
    runner.append_line(target, "added")
    runner.append_line(target, "added")
    assert target.read_text().splitlines().count("added") == 1


def test_remove_skips_directories(tmp_path: Path) -> None:
    directory = tmp_path / "adir"
    directory.mkdir()
    Runner(dry_run=False).remove([directory])
    assert directory.exists()


def test_read_text_reads_for_real_even_in_a_dry_run(tmp_path: Path) -> None:
    target = tmp_path / "existing.conf"
    target.write_text("hello\n")
    assert Runner(dry_run=True).read_text(target) == "hello\n"


def test_exists_checks_for_real_even_in_a_dry_run(tmp_path: Path) -> None:
    target = tmp_path / "existing.conf"
    target.write_text("hello\n")
    assert Runner(dry_run=True).exists(target) is True
    assert Runner(dry_run=True).exists(tmp_path / "missing.conf") is False


def test_list_dirs_returns_only_subdirectories(tmp_path: Path) -> None:
    (tmp_path / "Theme-A").mkdir()
    (tmp_path / "Theme-B").mkdir()
    (tmp_path / "not-a-theme.txt").write_text("")
    assert Runner(dry_run=True).list_dirs(tmp_path) == [
        tmp_path / "Theme-A",
        tmp_path / "Theme-B",
    ]


def test_list_dirs_is_empty_for_a_missing_path(tmp_path: Path) -> None:
    assert Runner(dry_run=True).list_dirs(tmp_path / "missing") == []


def test_remove_tree_dry_run_leaves_the_directory_in_place(tmp_path: Path) -> None:
    target = tmp_path / "checkout"
    (target / "sub").mkdir(parents=True)
    (target / "sub" / "file.txt").write_text("hello")

    Runner(dry_run=True).remove_tree(target)

    assert target.is_dir()
    assert (target / "sub" / "file.txt").exists()


def test_remove_tree_real_run_deletes_it(tmp_path: Path) -> None:
    target = tmp_path / "checkout"
    (target / "sub").mkdir(parents=True)
    (target / "sub" / "file.txt").write_text("hello")

    Runner(dry_run=False).remove_tree(target)

    assert not target.exists()


def test_remove_tree_is_a_no_op_for_a_missing_path(tmp_path: Path) -> None:
    Runner(dry_run=False).remove_tree(tmp_path / "missing")


def test_ensure_block_appends_to_an_existing_file(tmp_path: Path) -> None:
    target = tmp_path / ".bashrc"
    target.write_text("existing content\n")

    Runner(dry_run=False).ensure_block(target, "# marker", "# marker\nsome line\n")

    text = target.read_text()
    assert text.startswith("existing content\n")
    assert "# marker\nsome line\n" in text


def test_ensure_block_creates_a_missing_file(tmp_path: Path) -> None:
    target = tmp_path / ".bashrc"

    Runner(dry_run=False).ensure_block(target, "# marker", "# marker\nsome line\n")

    assert target.read_text() == "# marker\nsome line\n"


def test_ensure_block_is_a_no_op_when_the_marker_is_already_present(
    tmp_path: Path,
) -> None:
    target = tmp_path / ".bashrc"
    target.write_text("# marker\nsome line, hand-edited\n")

    Runner(dry_run=False).ensure_block(target, "# marker", "# marker\nsome line\n")

    assert target.read_text() == "# marker\nsome line, hand-edited\n"


def test_ensure_block_dry_run_writes_nothing(tmp_path: Path) -> None:
    target = tmp_path / ".bashrc"

    Runner(dry_run=True).ensure_block(target, "# marker", "# marker\nsome line\n")

    assert not target.exists()


def test_copy_dry_run_writes_nothing(tmp_path: Path) -> None:
    src = tmp_path / "lab01-starter.odt"
    src.write_bytes(b"PK\x03\x04binary")
    dest = tmp_path / "desk" / "lab01-starter.odt"

    Runner(dry_run=True).copy(src, dest)

    assert not dest.exists()


def test_copy_real_run_copies_bytes_and_sets_mode(tmp_path: Path) -> None:
    src = tmp_path / "lab01-starter.odt"
    src.write_bytes(b"PK\x03\x04binary")
    dest = tmp_path / "desk" / "lab01-starter.odt"

    Runner(dry_run=False).copy(src, dest, mode=0o644)

    assert dest.read_bytes() == b"PK\x03\x04binary"
    assert dest.stat().st_mode & 0o777 == 0o644


def test_same_content_compares_for_real_even_in_a_dry_run(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.write_bytes(b"same")
    right.write_bytes(b"same")

    assert Runner(dry_run=True).same_content(left, right)

    right.write_bytes(b"different")
    assert not Runner(dry_run=True).same_content(left, right)


def test_same_content_is_false_when_either_side_is_missing(tmp_path: Path) -> None:
    present = tmp_path / "present"
    present.write_bytes(b"x")
    assert not Runner(dry_run=False).same_content(present, tmp_path / "absent")
    assert not Runner(dry_run=False).same_content(tmp_path / "absent", present)


def test_group_members_unions_primary_and_secondary_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole reason this method exists: grp lists only secondary members,
    so an account whose *primary* group is the section would be invisible.
    """

    class FakeGroup:
        gr_gid = 2001
        gr_mem = ["zwhite28"]

    class FakePasswd:
        def __init__(self, name: str, gid: int) -> None:
            self.pw_name = name
            self.pw_gid = gid

    monkeypatch.setattr(grp, "getgrnam", lambda name: FakeGroup())
    monkeypatch.setattr(
        pwd,
        "getpwall",
        lambda: [FakePasswd("aadams27", 2001), FakePasswd("elsewhere", 3000)],
    )

    assert Runner(dry_run=True).group_members("r1") == ["aadams27", "zwhite28"]


def test_group_members_is_empty_for_a_group_that_does_not_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> None:
        raise KeyError(name)

    monkeypatch.setattr(grp, "getgrnam", missing)

    assert Runner(dry_run=True).group_members("nope") == []
