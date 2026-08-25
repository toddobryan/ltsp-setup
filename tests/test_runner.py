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
