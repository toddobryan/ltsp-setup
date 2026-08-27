"""Create student accounts in bulk from a roster CSV export.

Runs against the LTSP server, same as ``steps/students.py`` -- see that
module's docstring. The roster is an external, per-semester export (course,
room, names, student number, graduation cohort year, ...); only the columns
actually needed to create an account are read here, everything else in the
export is ignored.
"""

from __future__ import annotations

import csv
import html
import io
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path

from ltsp_setup import templates
from ltsp_setup.runner import StepFailed
from ltsp_setup.stages import STATE_DIR, Context
from ltsp_setup.steps import students

HANDOUT_DIR = STATE_DIR / "handouts"

# No ambiguous glyphs (no 0/O, 1/l/I, C -- easily misread as G on some
# fonts). Digits appear three times each, biasing generated passwords
# toward being easier to read aloud/copy from a printed slip.
_PASSWORD_ALPHABET = (
    "234567892345678923456789abcdefghijkmnopqrstuvwxyzABDEFGHIJKLMNPQRSTUVWXYZ"
)


def random_password(length: int = 8) -> str:
    return "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(length))


@dataclass(frozen=True)
class RosterStudent:
    last_name: str
    first_name: str
    preferred_name: str | None
    student_id: str
    grad_year: int
    # Unix groups this student belongs to, unioned across every roster row
    # naming them (a student enrolled in more than one mapped course
    # section).
    groups: frozenset[str] = field(default_factory=frozenset)

    @property
    def display_name(self) -> str:
        first = self.preferred_name or self.first_name
        return f"{first} {self.last_name}"


def parse_roster(text: str, course_groups: Mapping[str, str]) -> list[RosterStudent]:
    """Parse a roster CSV export into one :class:`RosterStudent` per unique
    ``Student Number``, unioning ``groups`` across every row naming them.

    Pure function, no I/O -- the caller reads the file via
    :meth:`Runner.read_text`.
    """
    by_id: dict[str, RosterStudent] = {}
    order: list[str] = []

    for row in csv.DictReader(io.StringIO(text)):
        student_id = row["Student Number"].strip()
        course_code = row["Course"].strip().split()[0]
        group = course_groups.get(course_code)
        groups = frozenset({group}) if group else frozenset()

        existing = by_id.get(student_id)
        if existing is not None:
            by_id[student_id] = replace(existing, groups=existing.groups | groups)
            continue

        by_id[student_id] = RosterStudent(
            last_name=row["Last Name"].strip(),
            first_name=row["First Name"].strip(),
            preferred_name=row["Alias"].strip() or None,
            student_id=student_id,
            grad_year=int(row["Graduation Cohort Year"].strip()),
            groups=groups,
        )
        order.append(student_id)

    return [by_id[student_id] for student_id in order]


def _collision_key(student: RosterStudent) -> tuple[str, str, int]:
    return (
        student.first_name[0].lower(),
        student.last_name.replace(" ", "")[:7].lower(),
        student.grad_year % 100,
    )


def assign_logins(roster: list[RosterStudent]) -> dict[str, str]:
    """Compute each student's login, keyed by ``student_id``.

    The plain scheme is first-initial + first 7 letters of last name + last
    two digits of graduation year. Students who'd collide under that scheme
    (same first initial, same first 7 letters of last name, same graduation
    year -- typically siblings) instead each get a digit inserted between
    the initial and a 6-letter last name (Todd's rule, 2026-08-26):
    Vasundhara and Vishal Kakarla, both graduating 2030, become
    ``v1kakarl30`` and ``v2kakarl30`` rather than colliding on
    ``vkakarla30``. The digit is assigned by alphabetical first-name order
    within the colliding group, not CSV row order, so it doesn't depend on
    how the roster happens to be sorted.
    """
    groups: dict[tuple[str, str, int], list[RosterStudent]] = {}
    for student in roster:
        groups.setdefault(_collision_key(student), []).append(student)

    logins: dict[str, str] = {}
    for (first_initial, last_seven, year_suffix), members in groups.items():
        if len(members) == 1:
            logins[members[0].student_id] = f"{first_initial}{last_seven}{year_suffix}"
            continue
        ordered = sorted(members, key=lambda s: s.first_name.lower())
        for index, student in enumerate(ordered, start=1):
            last_six = student.last_name.replace(" ", "")[:6].lower()
            logins[student.student_id] = (
                f"{first_initial}{index}{last_six}{year_suffix}"
            )
    return logins


@dataclass
class RosterImportResult:
    created: list[str] = field(default_factory=list)
    skipped_existing: list[str] = field(default_factory=list)
    handout_path: Path | None = None


def _handout_html(created: list[tuple[RosterStudent, str, str]]) -> str:
    cards = "".join(
        templates.render(
            "roster-handout-card.html",
            {
                "NAME": html.escape(student.display_name),
                "USERNAME": html.escape(login),
                "PASSWORD": html.escape(password),
            },
        )
        for student, login, password in created
    )
    return templates.render(
        "roster-handout.html",
        {
            "TITLE": "New Student Accounts",
            "GENERATED_AT": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            "COUNT": len(created),
            "CARDS": cards,
        },
    )


def import_roster(ctx: Context, csv_path: Path) -> RosterImportResult:
    """Create a Unix account for every student in a roster CSV export.

    Idempotent: a computed login that already exists as a real account is
    skipped, not recreated or touched, so this is safe to re-run later in
    the year against an updated roster. ``assign_logins`` already resolves
    the common case of two students colliding on the same login; this is
    a backstop for anything that still ends up identical (e.g. a
    disambiguated login coinciding with an unrelated student's plain one)
    -- fail closed, before any account exists, rather than partway through.
    """
    text = ctx.runner.read_text(csv_path)
    roster = parse_roster(text, ctx.settings.students.course_groups)
    logins = assign_logins(roster)

    existing_logins = {name for name, _ in ctx.runner.passwd_entries()}
    to_create = [s for s in roster if logins[s.student_id] not in existing_logins]
    skipped_existing = sorted(
        {
            logins[s.student_id]
            for s in roster
            if logins[s.student_id] in existing_logins
        }
    )

    logins_by_id: dict[str, list[str]] = {}
    for student in to_create:
        logins_by_id.setdefault(logins[student.student_id], []).append(
            student.student_id
        )
    collisions = {
        login: ids for login, ids in logins_by_id.items() if len(set(ids)) > 1
    }
    if collisions:
        detail = ", ".join(
            f"{login} ({', '.join(ids)})" for login, ids in sorted(collisions.items())
        )
        raise StepFailed(
            f"Two different students would get the same login -- fix the "
            f"roster and re-run. Nothing has been created. {detail}"
        )

    needed_groups = sorted({group for s in to_create for group in s.groups})
    for group in needed_groups:
        if not ctx.runner.group_exists(group):
            ctx.runner.run(["groupadd", group])

    result = RosterImportResult(skipped_existing=skipped_existing)
    created_with_passwords: list[tuple[RosterStudent, str, str]] = []
    home_root = ctx.settings.students.home_root

    for student in to_create:
        login = logins[student.student_id]
        ctx.runner.run(
            [
                "useradd",
                "-m",
                "-c",
                f"{student.display_name},,,",
                "-d",
                str(home_root / login),
                "-s",
                "/bin/bash",
                login,
            ]
        )
        password = random_password()
        ctx.runner.run(["chpasswd"], input_text=f"{login}:{password}\n")
        if student.groups:
            ctx.runner.run(["usermod", "-aG", ",".join(sorted(student.groups)), login])
        if not ctx.runner.dry_run:
            # A dry run only *previews* `useradd -m` above -- the home
            # directory genuinely doesn't exist yet, and apply_defaults
            # rightly refuses to run against one that isn't there.
            students.apply_defaults(ctx, login)
        result.created.append(login)
        created_with_passwords.append((student, login, password))

    if result.created:
        ctx.runner.run(["ltsp", "initrd"])
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        handout_path = HANDOUT_DIR / f"{csv_path.stem}-{timestamp}.html"
        ctx.runner.write_secret(handout_path, _handout_html(created_with_passwords))
        result.handout_path = handout_path

    return result
