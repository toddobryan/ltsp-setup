"""The dry-run guarantee: nothing on disk changes, nothing is executed."""

from __future__ import annotations

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
