"""Behaviour of roster-CSV-driven bulk student account creation."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ltsp_setup.config import Settings, Students
from ltsp_setup.runner import Runner, StepFailed
from ltsp_setup.stages import Context
from ltsp_setup.steps import roster, students

HEADER = (
    "Course,Room,Term(s),Last Name,First Name,Middle Name,Suffix,Alias,"
    "Gender,Grade,Start Date,End Date,Student Number,Date of Birth,"
    "Graduation Cohort Year"
)


def _row(
    course: str,
    last: str,
    first: str,
    student_id: str,
    grad_year: str,
    alias: str = "",
) -> str:
    # Course,Room,Term(s),Last Name,First Name,Middle Name,Suffix,Alias,
    # Gender,Grade,Start Date,End Date,Student Number,Date of Birth,
    # Graduation Cohort Year
    return (
        f"{course},231,1; 2,{last},{first},,,{alias},F,09,,,"
        f"{student_id},01/01/2011,{grad_year},"
    )


@pytest.fixture(autouse=True)
def _isolated_state_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Both apply_defaults' template-baseline dir and the handout dir
    default to real system paths -- redirect them into tmp_path so no test
    ever touches real state.
    """
    state_dir = tmp_path / "var-lib-ltsp-setup"
    monkeypatch.setattr(students, "STATE_DIR", state_dir)
    monkeypatch.setattr(
        students, "TEMPLATE_BASELINE_DIR", state_dir / "template-baseline"
    )
    monkeypatch.setattr(roster, "HANDOUT_DIR", state_dir / "handouts")


def _ctx(
    tmp_path: Path, *, dry_run: bool, course_groups: dict[str, str] | None = None
) -> Context:
    return Context(
        Settings(
            students=Students(home_root=tmp_path, course_groups=course_groups or {})
        ),
        Runner(dry_run=dry_run),
    )


# --------------------------------------------------------------- parse_roster


def test_parse_roster_dedupes_by_student_number_and_unions_groups() -> None:
    text = "\n".join(
        [
            HEADER,
            _row("C1 FOO", "Adams", "Amy", "1001", "2030"),
            _row("C2 BAR", "Adams", "Amy", "1001", "2030"),
        ]
    )
    result = roster.parse_roster(text, {"C1": "g1", "C2": "g2"})

    assert len(result) == 1
    assert result[0].student_id == "1001"
    assert result[0].groups == frozenset({"g1", "g2"})


def test_parse_roster_unmapped_course_gets_no_group() -> None:
    text = "\n".join([HEADER, _row("C3 UNMAPPED", "Cole", "Cara", "1003", "2029")])

    result = roster.parse_roster(text, {"C1": "g1"})

    assert result[0].groups == frozenset()


def test_parse_roster_reads_grad_year_directly_not_computed_from_grade() -> None:
    text = "\n".join([HEADER, _row("C1 FOO", "Adams", "Amy", "1001", "2035")])

    result = roster.parse_roster(text, {})

    assert result[0].grad_year == 2035


def test_assign_logins_plain_scheme_for_a_student_with_no_collision() -> None:
    student = roster.RosterStudent(
        last_name="Bransford",
        first_name="Amy",
        preferred_name=None,
        student_id="1001",
        grad_year=2028,
    )
    assert roster.assign_logins([student]) == {"1001": "abransfo28"}


def test_assign_logins_disambiguates_a_collision_by_alphabetical_first_name() -> None:
    """Real case, 2026-08-26: Vasundhara and Vishal Kakarla, siblings, both
    graduating 2030, collide on the plain scheme (vkakarla30). Todd's rule:
    insert a digit between the initial and a 6-letter last name, assigned by
    alphabetical first-name order -- "Vasundhara" sorts before "Vishal".
    """
    vasundhara = roster.RosterStudent(
        last_name="Kakarla",
        first_name="Vasundhara",
        preferred_name=None,
        student_id="998385499",
        grad_year=2030,
    )
    vishal = roster.RosterStudent(
        last_name="Kakarla",
        first_name="Vishal",
        preferred_name=None,
        student_id="998385498",
        grad_year=2030,
    )

    # Order in the list must not matter -- the digit comes from alphabetical
    # first-name order, not CSV row order.
    logins = roster.assign_logins([vishal, vasundhara])

    assert logins == {
        "998385499": "v1kakarl30",
        "998385498": "v2kakarl30",
    }


def test_assign_logins_leaves_an_unrelated_student_alone() -> None:
    vasundhara = roster.RosterStudent(
        last_name="Kakarla",
        first_name="Vasundhara",
        preferred_name=None,
        student_id="998385499",
        grad_year=2030,
    )
    vishal = roster.RosterStudent(
        last_name="Kakarla",
        first_name="Vishal",
        preferred_name=None,
        student_id="998385498",
        grad_year=2030,
    )
    unrelated = roster.RosterStudent(
        last_name="Adams",
        first_name="Amy",
        preferred_name=None,
        student_id="1001",
        grad_year=2030,
    )

    logins = roster.assign_logins([vishal, vasundhara, unrelated])

    assert logins["1001"] == "aadams30"


def test_display_name_prefers_alias_over_first_name() -> None:
    student = roster.RosterStudent(
        last_name="Corfman",
        first_name="Lily",
        preferred_name="Lil",
        student_id="1001",
        grad_year=2029,
    )
    assert student.display_name == "Lil Corfman"


# --------------------------------------------------------------- import_roster


def test_import_roster_creates_accounts_and_assigns_groups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "roster.csv"
    csv_path.write_text(
        "\n".join([HEADER, _row("C1 FOO", "Adams", "Amy", "1001", "2030")])
    )
    ctx = _ctx(tmp_path, dry_run=False, course_groups={"C1": "g1"})
    monkeypatch.setattr(ctx.runner, "passwd_entries", lambda: [])
    monkeypatch.setattr(ctx.runner, "group_exists", lambda name: False)
    (tmp_path / "aadams30").mkdir()  # what `useradd -m` would have made

    calls: list[tuple[list[str], str | None]] = []
    monkeypatch.setattr(
        ctx.runner,
        "run",
        lambda argv, **kw: calls.append((list(argv), kw.get("input_text"))),
    )

    result = roster.import_roster(ctx, csv_path)

    assert result.created == ["aadams30"]
    assert result.skipped_existing == []
    argvs = [c[0] for c in calls]
    assert ["groupadd", "g1"] in argvs
    assert [
        "useradd",
        "-m",
        "-c",
        "Amy Adams,,,",
        "-d",
        str(tmp_path / "aadams30"),
        "-s",
        "/bin/bash",
        "aadams30",
    ] in argvs
    assert ["usermod", "-aG", "g1", "aadams30"] in argvs
    assert ["ltsp", "initrd"] in argvs

    # The password only ever travels as chpasswd's stdin, never an argv.
    chpasswd_calls = [c for c in calls if c[0] == ["chpasswd"]]
    assert len(chpasswd_calls) == 1
    input_text = chpasswd_calls[0][1]
    assert input_text is not None
    assert input_text.startswith("aadams30:")
    assert not any("aadams30:" in " ".join(argv) for argv in argvs)


def test_import_roster_dry_run_completes_without_a_real_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dry run only *previews* `useradd -m` -- the home directory never
    actually gets created, so apply_defaults (which requires one) must be
    skipped rather than raising StepFailed partway through every student.
    """
    csv_path = tmp_path / "roster.csv"
    csv_path.write_text(
        "\n".join([HEADER, _row("C1 FOO", "Adams", "Amy", "1001", "2030")])
    )
    ctx = _ctx(tmp_path, dry_run=True, course_groups={"C1": "g1"})
    monkeypatch.setattr(ctx.runner, "passwd_entries", lambda: [])
    # No (tmp_path / "aadams30").mkdir() -- deliberately absent.

    result = roster.import_roster(ctx, csv_path)

    assert result.created == ["aadams30"]
    assert not (tmp_path / "aadams30").exists()
    assert result.handout_path is not None
    assert not result.handout_path.exists()  # dry run writes nothing real


def test_import_roster_skips_an_already_existing_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "roster.csv"
    csv_path.write_text(
        "\n".join([HEADER, _row("C1 FOO", "Adams", "Amy", "1001", "2030")])
    )
    ctx = _ctx(tmp_path, dry_run=False, course_groups={"C1": "g1"})
    monkeypatch.setattr(ctx.runner, "passwd_entries", lambda: [("aadams30", 1010)])
    calls: list[list[str]] = []
    monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: calls.append(list(argv)))

    result = roster.import_roster(ctx, csv_path)

    assert result.created == []
    assert result.skipped_existing == ["aadams30"]
    assert calls == []
    assert result.handout_path is None


def test_import_roster_refuses_a_login_collision_and_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """assign_logins already resolves the common (e.g. sibling) collision
    case -- this is a backstop for anything that still ends up identical,
    exercised directly by forcing assign_logins to return a duplicate
    rather than trying to construct real roster data that reaches it.
    """
    csv_path = tmp_path / "roster.csv"
    csv_path.write_text(
        "\n".join(
            [
                HEADER,
                _row("C1 FOO", "Smith", "Sam", "2001", "2027"),
                _row("C1 FOO", "Jones", "Jill", "2002", "2028"),
            ]
        )
    )
    ctx = _ctx(tmp_path, dry_run=False, course_groups={"C1": "g1"})
    monkeypatch.setattr(ctx.runner, "passwd_entries", lambda: [])
    monkeypatch.setattr(
        roster, "assign_logins", lambda students: {"2001": "dupe", "2002": "dupe"}
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: calls.append(list(argv)))

    with pytest.raises(StepFailed, match="dupe"):
        roster.import_roster(ctx, csv_path)

    assert calls == []


def test_import_roster_writes_a_handout_with_the_password_never_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    csv_path = tmp_path / "roster.csv"
    csv_path.write_text(
        "\n".join([HEADER, _row("C1 FOO", "Adams", "Amy", "1001", "2030")])
    )
    ctx = _ctx(tmp_path, dry_run=False, course_groups={"C1": "g1"})
    monkeypatch.setattr(ctx.runner, "passwd_entries", lambda: [])
    monkeypatch.setattr(ctx.runner, "group_exists", lambda name: True)
    monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: None)
    (tmp_path / "aadams30").mkdir()

    result = roster.import_roster(ctx, csv_path)

    assert result.handout_path is not None
    content = result.handout_path.read_text()
    assert "Amy Adams" in content
    assert "aadams30" in content
    assert '<span class="group-badge">g1</span>' in content

    password = content.split('<span class="label">Password</span><br>')[1].split("<")[0]
    assert len(password) == 8
    assert not any(password in r.message for r in caplog.records)
    assert oct(result.handout_path.stat().st_mode & 0o777) == "0o600"


def test_import_roster_handout_shows_none_badge_for_ungrouped_student(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    csv_path = tmp_path / "roster.csv"
    csv_path.write_text(
        "\n".join([HEADER, _row("C9 UNMAPPED", "Adams", "Amy", "1001", "2030")])
    )
    ctx = _ctx(tmp_path, dry_run=False, course_groups={"C1": "g1"})
    monkeypatch.setattr(ctx.runner, "passwd_entries", lambda: [])
    monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: None)
    (tmp_path / "aadams30").mkdir()

    result = roster.import_roster(ctx, csv_path)

    assert result.handout_path is not None
    content = result.handout_path.read_text()
    assert '<span class="group-badge none">none</span>' in content
