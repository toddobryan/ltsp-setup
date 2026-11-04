"""Operations on student accounts.

Unlike the client-image steps, these run against the LTSP server itself:
student accounts are NFS-exported from here, not baked into the squashfs
image, so a fix to an already-created account has to land in the home
directory directly rather than through a rebuilt image (see
``steps/image.py`` and ``docs/desktop-polish-todo.md``).

Three very different risk levels live in this module, and the split is
deliberate (Todd, 2026-08-24): resetting a *setting* back to a default is
cheap and reversible -- worst case, a student notices and changes it back.
Deleting a *file with content* is not reversible at all. ``reset_defaults``
and ``apply_defaults`` only ever touch the fixed allowlist in
``RESETTABLE_DEFAULTS`` -- pure settings files this project generates, never
anything a student created. ``remove_all`` is the one function here that
deletes real content (whole home directories), which is why it reports a
file count per account before touching anything, real run or not.

``push_files`` is the third: it writes files this project didn't
generate into a place students keep their own work, so unlike everything
above it could in principle land on top of something a student made. That
is why it never writes over a file that is already there, adding a
numbered copy beside it instead unless explicitly told to overwrite --
see that function's docstring.

``collect_assignment`` is the fourth. It deletes nothing, but it runs as root
inside folders students control, so it treats every name in there as
hostile -- see that function's docstring.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ltsp_setup import templates
from ltsp_setup.runner import StepFailed
from ltsp_setup.stages import STATE_DIR, Context
from ltsp_setup.steps import racket_prefs, xfconf

# Standard Linux username rules, enforced before any path is built from the
# argument -- the only thing standing between a typo and deleting outside
# HOME_ROOT.
_USERNAME = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

# Per-user settings files this project manages, and the template used to
# (re)write each one. The single source of truth for all three consumers:
# configure_skel below (new accounts, via /etc/skel), apply_defaults
# (already-existing accounts), and reset_defaults (delete to reseed from
# whatever's in the account already, e.g. after a skel copy).
#
# Not baked into the client image (2026-08-24 correction) -- these are
# per-student, NFS-homed files, and the image is shared read-only across
# every client, so putting a "system default" there only ever mattered for
# an account with no per-user file of its own yet. /etc/skel handles that
# case more directly: it's what useradd -m already copies into a brand new
# home directory, no custom step or pam_mkhomedir needed.
RESETTABLE_DEFAULTS: dict[Path, str] = {
    Path(
        ".config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml"
    ): "xfce4-panel-default.xml",
    Path(
        ".config/xfce4/xfconf/xfce-perchannel-xml/keyboard-layout.xml"
    ): "keyboard-layout-default.xml",
    Path(".config/xfce4/xfconf/xfce-perchannel-xml/xfwm4.xml"): "xfwm4-default.xml",
    Path(".config/racket/racket-prefs.rktd"): "racket-prefs-default.rktd",
}

SKEL_ROOT = Path("/etc/skel")

# An opt-in convenience, not a default -- appended once via
# Runner.ensure_block rather than tracked in RESETTABLE_DEFAULTS, since it's
# meant for a student to hand-edit (uncomment the setxkbmap line) rather
# than something reset_defaults should ever delete or apply_defaults treat
# as "customized" (Todd, 2026-08-26).
BASHRC_CTRL_SWAP_MARKER = "# --- ltsp-setup: ctrl-alt-swap ---"


def _ensure_bashrc_snippet(ctx: Context, bashrc_path: Path) -> None:
    ctx.runner.ensure_block(
        bashrc_path,
        BASHRC_CTRL_SWAP_MARKER,
        templates.read("bashrc-ctrl-swap-snippet"),
    )


# A snapshot of each template's content as of the last apply_defaults(_all)
# run, kept so the next run can tell "the template changed this" apart from
# "the student changed this" -- see steps/xfconf.py. One snapshot per
# template file, not per student: every student is compared against the
# same "what we shipped last time."
TEMPLATE_BASELINE_DIR = STATE_DIR / "template-baseline"


def _home_dir(ctx: Context, username: str) -> Path:
    if not _USERNAME.match(username):
        raise StepFailed(f"{username!r} doesn't look like a real account name")
    return ctx.settings.students.home_root / username


def reset_defaults(ctx: Context, username: str) -> None:
    """Delete a student's overrides for the settings this project manages.

    Destructive but narrow: only the files in RESETTABLE_DEFAULTS, not the
    rest of the account -- documents, code, browser profile, and everything
    else the student owns is untouched. Raises if the account's home
    directory doesn't exist, rather than silently doing nothing on a
    typo'd username.
    """
    home = _home_dir(ctx, username)
    if not ctx.runner.exists(home):
        raise StepFailed(f"No home directory at {home} -- check the username")
    ctx.runner.remove(home / rel for rel in RESETTABLE_DEFAULTS)


def clear_session_lock(ctx: Context, username: str) -> bool:
    """Forcibly release a student's concurrent-login lock.

    See data/ltsp-session-lock-check.sh: a client that crashes or loses
    power without logging out leaves a lock that only clears itself after
    ~3 minutes of no heartbeat. For when Todd doesn't want to wait that
    long (Todd, 2026-08-26: "make it easy for me to clear a lock").

    Returns:
        True if a lock was actually present and removed, False if there
        was nothing to clear.
    """
    home = _home_dir(ctx, username)
    if not ctx.runner.exists(home):
        raise StepFailed(f"No home directory at {home} -- check the username")
    lockdir = home / ".ltsp-session-lock"
    existed = ctx.runner.exists(lockdir)
    ctx.runner.remove_tree(lockdir)
    return existed


KEYRING_DIR_REL = Path(".local/share/keyrings")


def reset_password(ctx: Context, username: str) -> bool:
    """Reset a student's Unix password, and clear their now-stale keyring.

    An admin-driven ``passwd`` has no way to re-encrypt the student's
    existing GNOME keyring -- that needs the *old* password, which is
    exactly what an admin reset doesn't have -- so the keyring is left
    permanently locked afterwards. Deleting it here makes GNOME create a
    fresh one, auto-unlocked with the new password, at the student's next
    login (Todd, 2026-08-26).

    Runs ``passwd`` interactively, same as running it directly: meant to be
    used with the student present to enter and confirm the new password.

    Returns:
        True if a stale keyring was actually present and removed, False if
        there was nothing to clear.
    """
    home = _home_dir(ctx, username)
    if not ctx.runner.exists(home):
        raise StepFailed(f"No home directory at {home} -- check the username")
    ctx.runner.run(["passwd", username])
    keyring_dir = home / KEYRING_DIR_REL
    existed = ctx.runner.exists(keyring_dir)
    ctx.runner.remove_tree(keyring_dir)
    return existed


def configure_skel(ctx: Context) -> None:
    """Point new-account creation at the current student defaults.

    ``useradd -m`` copies ``/etc/skel`` into a brand new home directory
    itself, at creation time -- no ``pam_mkhomedir`` needed (that only
    matters for re-populating an *existing* account's home directory on
    login, which this server doesn't do and a fresh account doesn't need).
    Reuses RESETTABLE_DEFAULTS's own template mapping, so skel can never
    drift out of sync with what apply_defaults/reset_defaults use.
    """
    for rel, template_name in RESETTABLE_DEFAULTS.items():
        ctx.runner.write(SKEL_ROOT / rel, templates.read(template_name))
    _ensure_bashrc_snippet(ctx, SKEL_ROOT / ".bashrc")


# ------------------------------------------------------------- enumeration


def real_student_accounts(ctx: Context) -> list[str]:
    """Every local account that's a student, not staff or a test account.

    Normal-UID-range accounts (Students.uid_min..uid_max) minus
    Students.protected_usernames and Settings.admin_user -- the admin
    account is always excluded even if a config mistake left it out of
    protected_usernames.
    """
    protected = set(ctx.settings.students.protected_usernames) | {
        ctx.settings.admin_user
    }
    uid_min = ctx.settings.students.uid_min
    uid_max = ctx.settings.students.uid_max
    return sorted(
        name
        for name, uid in ctx.runner.passwd_entries()
        if uid_min <= uid <= uid_max and name not in protected
    )


# ------------------------------------------------------------ stale wipe


def remove_all(ctx: Context) -> list[str]:
    """Delete every real student account and its entire home directory.

    This is the one operation in this module that destroys actual student
    content, not just settings -- so every account is announced with its
    file count before it's touched, in both a dry run and a real one, so a
    surprisingly non-empty "stale" account is visible before it's gone
    rather than after.
    """
    names = real_student_accounts(ctx)
    for name in names:
        count = ctx.runner.count_files(_home_dir(ctx, name))
        ctx.runner.announce(f"{name}: {count} file(s) in home directory")
        ctx.runner.run(["userdel", "-r", name])
    if names:
        # The generic LTSP boot initrd embeds a snapshot of /etc/passwd and
        # /etc/group (man ltsp-initrd) -- without this, a client still shows
        # a just-deleted account as loginable until something else happens
        # to regenerate it.
        ctx.runner.run(["ltsp", "initrd"])
    return names


# -------------------------------------------------------- property-level apply


@dataclass
class AppliedResult:
    """What happened when defaults were applied to one account.

    Entries are "<filename>:<property path>" (e.g.
    "keyboard-layout.xml:XkbVariant"), or "<filename>: created" when the
    whole file didn't exist yet.
    """

    applied: list[str] = field(default_factory=list)
    # (path, reason) where reason is "customized" (differs from what we
    # last shipped) or "unknown" (exists, but we have no record of ever
    # shipping it).
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _baseline_path(template_name: str) -> Path:
    return TEMPLATE_BASELINE_DIR / template_name


def _baseline_content(ctx: Context, template_name: str) -> str | None:
    path = _baseline_path(template_name)
    if not ctx.runner.exists(path):
        return None
    return ctx.runner.read_text(path)


def _template_snapshot(ctx: Context) -> dict[str, tuple[str | None, str]]:
    """The (last-shipped, current) content of every managed template.

    Read once per apply_defaults/apply_defaults_all call so every account
    processed in that call is compared against the same baseline -- if it
    advanced mid-loop, accounts processed later would be compared against
    a baseline that already equals the new template, making an untouched
    file look "customized" by comparison.
    """
    return {
        name: (_baseline_content(ctx, name), templates.read(name))
        for name in set(RESETTABLE_DEFAULTS.values())
    }


def _advance_baseline(
    ctx: Context, snapshot: dict[str, tuple[str | None, str]]
) -> None:
    ctx.runner.mkdir(TEMPLATE_BASELINE_DIR)
    for template_name, (_, current) in snapshot.items():
        ctx.runner.write(_baseline_path(template_name), current, show=False)


def _merge(
    template_name: str, base: str | None, theirs: str, ours: str
) -> tuple[str, list[str], list[tuple[str, str]]]:
    """Dispatch to the right property-level merge for this template's format."""
    if template_name.endswith(".rktd"):
        racket_result = racket_prefs.merge(base, theirs, ours)
        return racket_result.content, racket_result.applied, racket_result.skipped
    xfconf_result = xfconf.merge(base, theirs, ours)
    return xfconf_result.xml, xfconf_result.applied, xfconf_result.skipped


def _apply_defaults_using(
    ctx: Context, username: str, snapshot: dict[str, tuple[str | None, str]]
) -> AppliedResult:
    home = _home_dir(ctx, username)
    if not ctx.runner.exists(home):
        raise StepFailed(f"No home directory at {home} -- check the username")

    result = AppliedResult()
    for rel, template_name in RESETTABLE_DEFAULTS.items():
        target = home / rel
        base, theirs = snapshot[template_name]

        if not ctx.runner.exists(target):
            ctx.runner.write(target, theirs)
            result.applied.append(f"{rel.name}: created")
            continue

        content, applied, skipped = _merge(
            template_name, base, theirs, ctx.runner.read_text(target)
        )
        if applied:
            ctx.runner.write(target, content)
        result.applied.extend(f"{rel.name}:{p}" for p in applied)
        result.skipped.extend((f"{rel.name}:{p}", reason) for p, reason in skipped)
    _ensure_bashrc_snippet(ctx, home / ".bashrc")
    return result


def apply_defaults(ctx: Context, username: str) -> AppliedResult:
    """Write current defaults into one account, patching only the
    properties that are missing or unchanged since we last shipped them --
    see steps/xfconf.py for how "unchanged since" is decided at the
    individual-property level rather than whole-file.
    """
    snapshot = _template_snapshot(ctx)
    result = _apply_defaults_using(ctx, username, snapshot)
    _advance_baseline(ctx, snapshot)
    return result


def apply_defaults_all(ctx: Context) -> dict[str, AppliedResult]:
    """Run apply_defaults across every real student account.

    Computes one template snapshot up front and reuses it for every
    account, rather than calling apply_defaults per account, so the
    baseline doesn't advance partway through the run.
    """
    snapshot = _template_snapshot(ctx)
    results = {
        name: _apply_defaults_using(ctx, name, snapshot)
        for name in real_student_accounts(ctx)
    }
    _advance_baseline(ctx, snapshot)
    return results


# ------------------------------------------------------------- pushing out

# How many same-named copies of one handout may pile up in an account before
# push_files gives up and says so. A student who really has 99 versions of
# lab01-activity.html on their desktop has a different problem, and silently
# adding a hundredth is not the answer.
MAX_SUFFIXED_COPIES = 99


@dataclass
class PushResult:
    """What a push did, as "<username>: <filename>" entries.

    A file that had to be renamed out of the way of a student's own copy
    appears in ``pushed`` under the name it actually landed as, e.g.
    "aadams27: lab01-activity-2.html". ``skipped`` pairs each entry with
    why, the same shape as :class:`AppliedResult` -- either a whole account
    ("aadams27") that couldn't be written to, or one file within one
    account.
    """

    pushed: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _recipients(ctx: Context, group: str | None) -> tuple[list[str], list[str]]:
    """Which accounts a push goes to, and which group members it won't.

    With no group, every real student account. With one, that group's
    members -- by primary *or* secondary membership, see
    ``Runner.group_members`` -- narrowed to the ones that are real student
    accounts. The narrowing is what keeps a push aimed at a section from
    also dropping files in Todd's own home directory, since his account is
    in these groups too; the excluded names are returned rather than
    silently dropped so the report can say who was passed over and why.
    """
    students_only = real_student_accounts(ctx)
    if group is None:
        return students_only, []
    if not ctx.runner.group_exists(group):
        raise StepFailed(f"No such group: {group}")
    eligible = set(students_only)
    members = ctx.runner.group_members(group)
    return (
        [name for name in members if name in eligible],
        [name for name in members if name not in eligible],
    )


def _checked_dest(dest: Path) -> Path:
    """Validate a destination directory given relative to a home directory.

    Absolute paths and ``..`` are refused rather than resolved: this path
    is joined onto every targeted student's home directory, so anything
    that can climb out of one is a way to write across the whole server by
    typo. Same fail-closed reasoning as ``_USERNAME`` above.
    """
    if dest.is_absolute():
        raise StepFailed(
            f"The destination must be relative to the student's home directory, "
            f"so it can't start with '/': {dest}"
        )
    if ".." in dest.parts:
        raise StepFailed(
            f"The destination must stay inside the student's home directory, "
            f"so it can't contain '..': {dest}"
        )
    return dest


def _suffixed(name: str, index: int) -> str:
    """``lab01-activity.html`` at index 2 -> ``lab01-activity-2.html``.

    The number goes before the extension, not after, so the file still
    opens in the right application when a student double-clicks it.
    """
    stem, dot, extension = name.partition(".")
    return f"{stem}-{index}{dot}{extension}" if dot else f"{name}-{index}"


def _existing_copy(
    ctx: Context, src: Path, dest_dir: Path, name: str | None = None
) -> Path | None:
    """A copy of ``src`` already sitting in ``dest_dir``, under ``name``
    (default: its own) or any of the numbered names derived from it.

    What makes re-running a push idempotent rather than a way to accumulate
    ``-2``, ``-3``, ``-4``: if this file was already delivered -- under its
    own name, or renamed out of the way of the student's version on an
    earlier run -- there is nothing left to do.
    """
    for candidate in _candidate_names(name or src.name):
        target = dest_dir / candidate
        if not ctx.runner.exists(target):
            return None
        if ctx.runner.same_content(src, target):
            return target
    return None


def _candidate_names(name: str) -> Iterator[str]:
    """``name``, then ``name-2``, ``name-3``, ... up to the cap."""
    yield name
    for index in range(2, MAX_SUFFIXED_COPIES + 1):
        yield _suffixed(name, index)


def _free_name(
    ctx: Context, src: Path, dest_dir: Path, name: str | None = None
) -> Path:
    """The first name in ``dest_dir``, starting from ``name`` (default: its
    own), that ``src`` can be written to without displacing anything.
    """
    wanted = name or src.name
    for candidate in _candidate_names(wanted):
        target = dest_dir / candidate
        if not ctx.runner.exists(target):
            return target
    raise StepFailed(
        f"{dest_dir} already holds {MAX_SUFFIXED_COPIES} copies of "
        f"{wanted} -- look at that account before running this again"
    )


def push_files(
    ctx: Context,
    sources: Sequence[Path],
    *,
    group: str | None = None,
    dest: Path | None = None,
    overwrite: bool = False,
) -> PushResult:
    """Copy files into every targeted student's handout directory.

    Generalises the one-off ``push-lab.sh`` (Todd, 2026-08-28), which
    hardcoded two lab filenames and took a section name. Each file lands at
    ``<home>/<dest>/<filename>``, owned by the student and mode 644, so
    they can open it, edit it, and delete it. ``dest`` defaults to
    ``students.push_dest`` from config, and is always relative to the
    student's own home directory.

    Every source and the destination are checked before anything is
    written, so a typo fails with nothing half-pushed.

    **A student's own file is never written over.** They may well have
    opened the handout, done the work in it and saved it in place under the
    same name, and that loss is not recoverable. So:

    - Already there with identical content -- under its own name or under
      an earlier run's ``-2`` name -- and nothing happens; the file has
      been delivered.
    - Already there and *different*, and the new copy lands beside it as
      ``lab01-activity-2.html`` (then ``-3``, ...). The student keeps their
      work and still gets the new file.
    - ``overwrite=True`` replaces the file in place instead. For the case
      the renaming is meant to protect against being impossible -- you
      fixed a typo in a starter file minutes after pushing it -- and never
      the default.

    Args:
        ctx: Settings and runner.
        sources: Files to push. Directories are not handled.
        group: Push to this Unix group's student members, or every student
            account when None.
        dest: Directory inside each home directory, relative to it.
            Defaults to ``students.push_dest``.
        overwrite: Replace a differing file in place rather than writing
            alongside it.

    Returns:
        A :class:`PushResult` naming what happened to every file in every
        account, including the name each one actually landed under.
    """
    missing = [str(src) for src in sources if not ctx.runner.exists(src)]
    if missing:
        raise StepFailed(
            "Nothing was pushed -- these files don't exist: " + ", ".join(missing)
        )
    dest_rel = _checked_dest(dest or ctx.settings.students.push_dest)

    result = PushResult()
    recipients, not_students = _recipients(ctx, group)
    for name in not_students:
        result.skipped.append((name, "not a student account"))

    for username in recipients:
        home = _home_dir(ctx, username)
        if not ctx.runner.exists(home):
            result.skipped.append((username, f"no home directory at {home}"))
            continue

        dest_dir = home / dest_rel
        if not ctx.runner.exists(dest_dir):
            # Only when it doesn't exist: an existing Desktop is already
            # the student's own, and re-chowning it every push would be
            # noise at best and a surprise at worst.
            ctx.runner.mkdir(dest_dir)
            ctx.runner.chown(dest_dir, username, ctx.runner.primary_group(username))

        for src in sources:
            # With overwrite, only the file's own name is considered: the
            # point of asking for it is to fix what is sitting under that
            # exact name, so an identical -2 copy from an earlier run is
            # not a reason to call the job done.
            named = dest_dir / src.name
            if overwrite:
                if ctx.runner.same_content(src, named):
                    result.unchanged.append(f"{username}: {named.name}")
                    continue
                target, replacing = named, ctx.runner.exists(named)
            else:
                already = _existing_copy(ctx, src, dest_dir)
                if already is not None:
                    result.unchanged.append(f"{username}: {already.name}")
                    continue
                target, replacing = _free_name(ctx, src, dest_dir), False

            ctx.runner.copy(src, target)
            ctx.runner.chown(target, username, ctx.runner.primary_group(username))
            entry = f"{username}: {target.name}"
            (result.replaced if replacing else result.pushed).append(entry)

    return result


# --------------------------------------------------------------- collecting


@dataclass
class CollectResult:
    """What a collection did, one entry per student.

    ``collected`` holds "<group>/<filename>" paths under the assignment's
    folder, under the name each one actually landed as, so a resubmission
    shows up as "r1/jsmith30-2.rkt". ``already_collected`` and ``missing``
    are "<group>/<username>", the second being who to chase. ``skipped``
    pairs a username with why, the same shape as :class:`PushResult`.
    """

    collected: list[str] = field(default_factory=list)
    already_collected: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _notice_path(ctx: Context, relative: Path) -> Path:
    """Where a student's missing-file notice goes, relative to their home.

    Next to where the turned-in copy would be, so two assignments with the
    same name in different folders don't share a notice.
    """
    folder = ctx.settings.students.turned_in_dir / relative.parent
    return folder / f"missing-{relative.name}.txt"


def _checked_assignment_path(path: str) -> Path:
    """Validate a file to collect, given relative to each home directory.

    Fail-closed for the same reason as ``_checked_dest``: this is joined onto
    every student's home, and ``../sysadmin/notes`` would climb out of it.
    Anything starting with a dot is refused along with ``..``, because
    what's in there is settings and keys rather than assignments, and
    ``.ssh/id_ed25519`` shouldn't be one typo away from a folder of them.
    """
    relative = Path(path)
    if (
        not relative.parts
        or relative.is_absolute()
        or any(part.startswith(".") for part in relative.parts)
    ):
        raise StepFailed(
            f"Give a path inside each home directory, like image-exercises.rkt "
            f"or labs/fall/programs.py: {path!r}"
        )
    return relative


def _sections_by_student(ctx: Context, groups: Sequence[str]) -> dict[str, list[str]]:
    """Each student in these sections, with which of them they're in.

    Usually one, but ``course_groups`` allows more, and a student in two gets
    a copy in both folders rather than vanishing from one section's list.
    Every group is resolved here, before anything is touched, so a mistyped
    section fails with nothing half-collected.
    """
    sections: dict[str, list[str]] = {}
    for group in groups:
        for username in _recipients(ctx, group)[0]:
            sections.setdefault(username, []).append(group)
    return sections


def _prepare_assignment_dirs(
    ctx: Context, assignment: str, groups: Sequence[str]
) -> Path:
    """Create the assignment's folder tree and return the assignment's folder.

    The top ``assignments`` folder is forced to 0700 on every run, whatever
    it was before: ``/home`` is NFS-mounted on every client, so if this
    folder were readable, every submission would be there for classmates to
    copy. The folders under it need no mode of their own for that reason.
    """
    admin = ctx.settings.admin_user
    admin_home = _home_dir(ctx, admin)
    if not ctx.runner.exists(admin_home):
        raise StepFailed(f"No home directory for {admin} at {admin_home}")
    admin_group = ctx.runner.primary_group(admin)

    root = admin_home / ctx.settings.students.assignments_dir
    assignment_dir = root / assignment
    group_dirs = [assignment_dir / group for group in groups]
    for directory in [root, assignment_dir, *group_dirs]:
        if not ctx.runner.exists(directory):
            ctx.runner.mkdir(directory, mode=0o700)
            ctx.runner.chown(directory, admin, admin_group)
    ctx.runner.run(["chmod", "700", str(root)])
    return assignment_dir


def _collect_from(
    ctx: Context,
    home: Path,
    relative: Path,
    username: str,
    groups: Sequence[str],
    assignment_dir: Path,
    result: CollectResult,
) -> None:
    """File one student's submission and give them a copy in ``turned-in``.

    A failure part way leaves nothing to clean up: re-running recognises
    the copies already made by their content rather than making them twice.
    """
    admin = ctx.settings.admin_user
    admin_group = ctx.runner.primary_group(admin)
    src = home / relative
    filed: list[Path] = []
    for group in groups:
        dest_dir = assignment_dir / group
        name = f"{username}{relative.suffix}"
        target = _existing_copy(ctx, src, dest_dir, name)
        if target is not None:
            result.already_collected.append(f"{group}/{username}")
        else:
            target = _free_name(ctx, src, dest_dir, name)
            ctx.runner.copy_nofollow(
                home, relative, target.parent, Path(target.name), mode=0o600
            )
            ctx.runner.chown(target, admin, admin_group)
            result.collected.append(f"{group}/{target.name}")
        filed.append(target)

    receipt_dir = home / ctx.settings.students.turned_in_dir / relative.parent
    if _existing_copy(ctx, src, receipt_dir) is None:
        # From our own copy rather than src, so that what the student sees
        # as turned in is what was actually collected, even if they saved
        # again in the last few milliseconds.
        receipt = _free_name(ctx, src, receipt_dir)
        ctx.runner.copy_nofollow(
            filed[0].parent, Path(filed[0].name), home, receipt.relative_to(home)
        )
    ctx.runner.remove_nofollow(home, _notice_path(ctx, relative))


def collect_assignment(
    ctx: Context, path: str, *, groups: Sequence[str] | None = None
) -> CollectResult:
    """Gather one file from every student into the admin account's home.

    ``labs/fall/programs.py`` in the home of jsmith30, who is in r1, is
    copied to ``~sysadmin/assignments/programs/r1/jsmith30.py``, owned by
    the admin account, and to ``~jsmith30/turned-in/labs/fall/programs.py``.
    The original stays where it is, so this never deletes anything.

    ``turned-in`` is created for every student in the sections collected,
    whether or not they've turned anything in. Root owns that folder and
    everything in it, so students can read it and can't change what's in
    there. They can still rename the folder, since it sits in a directory
    they own; the copy that gets graded is out of their reach either way.

    A student with no such file, who hasn't turned one in before, gets
    ``turned-in/labs/fall/missing-programs.py.txt`` saying so and warning of
    a zero. Each collection that still finds nothing updates its time, and
    the one that finds the file removes it.

    **Nothing is ever written over.** A file that has changed since it was
    last collected may be a fix or may be a mistake, and that is the
    teacher's call. So the new version lands beside the old one as
    ``jsmith30-2.py`` (and ``programs-2.py`` in ``turned-in``). An
    unchanged file adds nothing, so re-running is safe.

    **Everything in a student's home is treated as hostile**, since this
    runs as root in a folder they control. A file that isn't plain, or is
    reached through a symlink, is skipped: following one could read
    something they can't, or a classmate's work, and file it under their
    name. So is a student whose ``turned-in`` is anything other than the
    folder this made, because writing into it could land anywhere. One
    student's trouble never stops the rest of the class.

    Args:
        ctx: Settings and runner.
        path: The file, relative to each home directory.
        groups: Sections to collect from, or ``students.collect_groups``
            when None.

    Returns:
        A :class:`CollectResult` accounting for every student in the
        collected sections.
    """
    relative = _checked_assignment_path(path)
    settings = ctx.settings.students
    selected = settings.collect_groups if groups is None else groups
    sections = _sections_by_student(ctx, selected)
    assignment_dir = _prepare_assignment_dirs(ctx, relative.stem, selected)
    notice = templates.render(
        "missing-assignment.txt",
        {
            "ASSIGNMENT_PATH": relative,
            "COLLECTED_AT": datetime.now().strftime("%-I:%M %p on %A, %B %-d, %Y"),
        },
    )

    result = CollectResult()
    for username, student_groups in sorted(sections.items()):
        home = _home_dir(ctx, username)
        if not ctx.runner.exists(home):
            result.skipped.append((username, f"no home directory at {home}"))
            continue

        turned_in = home / settings.turned_in_dir
        try:
            kind = ctx.runner.kind_nofollow(home, relative)
            if not ctx.runner.ensure_readonly_dir(turned_in):
                result.skipped.append(
                    (username, f"{turned_in} isn't the folder this tool made")
                )
            elif kind == "file":
                _collect_from(
                    ctx,
                    home,
                    relative,
                    username,
                    student_groups,
                    assignment_dir,
                    result,
                )
            elif kind == "other":
                result.skipped.append(
                    (
                        username,
                        f"{home / relative} isn't a plain file in a real folder",
                    )
                )
            else:
                name = f"{username}{relative.suffix}"
                entries = [f"{group}/{username}" for group in student_groups]
                if any(
                    ctx.runner.exists(assignment_dir / group / name)
                    for group in student_groups
                ):
                    result.already_collected.extend(entries)
                else:
                    # All the same text, so only the first is worth printing.
                    ctx.runner.write_nofollow(
                        home,
                        _notice_path(ctx, relative),
                        notice,
                        show=not result.missing,
                    )
                    result.missing.extend(entries)
        except (StepFailed, OSError) as failure:
            result.skipped.append((username, str(failure)))
    # By section, which is how the teacher will read it.
    result.collected.sort()
    result.already_collected.sort()
    result.missing.sort()
    return result
