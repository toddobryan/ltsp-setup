"""Operations on student accounts.

Unlike the client-image steps, these run against the LTSP server itself:
student accounts are NFS-exported from here, not baked into the squashfs
image, so a fix to an already-created account has to land in the home
directory directly rather than through a rebuilt image (see
``steps/image.py`` and ``docs/desktop-polish-todo.md``).

Two very different risk levels live in this module, and the split is
deliberate (Todd, 2026-08-24): resetting a *setting* back to a default is
cheap and reversible -- worst case, a student notices and changes it back.
Deleting a *file with content* is not reversible at all. ``reset_defaults``
and ``apply_defaults`` only ever touch the fixed allowlist in
``RESETTABLE_DEFAULTS`` -- pure settings files this project generates, never
anything a student created. ``remove_all`` is the one function here that
deletes real content (whole home directories), which is why it reports a
file count per account before touching anything, real run or not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
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
