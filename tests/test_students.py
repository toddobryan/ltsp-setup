"""Behaviour of the per-student and whole-roster account operations."""

from __future__ import annotations

import logging
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from ltsp_setup import templates
from ltsp_setup.config import Settings, Students
from ltsp_setup.runner import Runner, StepFailed
from ltsp_setup.stages import Context
from ltsp_setup.steps import students, xfconf


@pytest.fixture(autouse=True)
def _isolated_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """apply_defaults persists the last-shipped template snapshot to a real
    system path by default (``/var/lib/ltsp-setup``) -- redirect it into
    tmp_path so no test ever touches real state.
    """
    state_dir = tmp_path / "var-lib-ltsp-setup"
    monkeypatch.setattr(students, "STATE_DIR", state_dir)
    monkeypatch.setattr(
        students, "TEMPLATE_BASELINE_DIR", state_dir / "template-baseline"
    )


def _set_property_value(xml_text: str, name: str, new_value: str) -> str:
    """Hand-edit one property's value, the way a student's own settings
    dialog would -- without assuming anything about the rest of the file.
    """
    root = ET.fromstring(xml_text)
    for elem in root.iter("property"):
        if elem.attrib.get("name") == name:
            elem.set("value", new_value)
            break
    else:
        raise AssertionError(f"property {name!r} not found in {xml_text}")
    return xfconf.XML_DECLARATION + ET.tostring(root, encoding="unicode") + "\n"


def _ctx(home_root: Path, *, dry_run: bool, **student_kwargs: object) -> Context:
    return Context(
        Settings(students=Students(home_root=home_root, **student_kwargs)),  # type: ignore[arg-type]
        Runner(dry_run=dry_run),
    )


# --------------------------------------------------------------- reset_defaults


def test_reset_defaults_removes_only_the_managed_files(tmp_path: Path) -> None:
    home = tmp_path / "pat"
    for rel in students.RESETTABLE_DEFAULTS:
        path = home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("customized")
    keep = home / "Documents" / "essay.txt"
    keep.parent.mkdir(parents=True)
    keep.write_text("real student work")

    students.reset_defaults(_ctx(tmp_path, dry_run=False), "pat")

    for rel in students.RESETTABLE_DEFAULTS:
        assert not (home / rel).exists()
    assert keep.exists()


def test_reset_defaults_dry_run_deletes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "pat"
    target = home / next(iter(students.RESETTABLE_DEFAULTS))
    target.parent.mkdir(parents=True)
    target.write_text("customized")

    students.reset_defaults(_ctx(tmp_path, dry_run=True), "pat")

    assert target.exists()


def test_reset_defaults_raises_when_home_directory_is_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(StepFailed, match="No home directory"):
        students.reset_defaults(_ctx(tmp_path, dry_run=False), "nobody")


def test_reset_defaults_raises_on_a_path_traversal_attempt(tmp_path: Path) -> None:
    with pytest.raises(StepFailed, match="doesn't look like a real account name"):
        students.reset_defaults(_ctx(tmp_path, dry_run=False), "../../etc")


def test_reset_defaults_is_fine_with_a_missing_resettable_file(
    tmp_path: Path,
) -> None:
    home = tmp_path / "pat"
    home.mkdir()
    students.reset_defaults(_ctx(tmp_path, dry_run=False), "pat")


# ------------------------------------------------------------- clear_session_lock


def test_clear_session_lock_removes_an_existing_lock(tmp_path: Path) -> None:
    home = tmp_path / "pat"
    lockdir = home / ".ltsp-session-lock"
    lockdir.mkdir(parents=True)
    (lockdir / "host").write_text("client-01\n")

    existed = students.clear_session_lock(_ctx(tmp_path, dry_run=False), "pat")

    assert existed is True
    assert not lockdir.exists()


def test_clear_session_lock_reports_false_when_nothing_to_clear(
    tmp_path: Path,
) -> None:
    (tmp_path / "pat").mkdir()

    existed = students.clear_session_lock(_ctx(tmp_path, dry_run=False), "pat")

    assert existed is False


def test_clear_session_lock_raises_when_home_directory_is_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(StepFailed, match="No home directory"):
        students.clear_session_lock(_ctx(tmp_path, dry_run=False), "nobody")


def test_clear_session_lock_dry_run_deletes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "pat"
    lockdir = home / ".ltsp-session-lock"
    lockdir.mkdir(parents=True)

    students.clear_session_lock(_ctx(tmp_path, dry_run=True), "pat")

    assert lockdir.exists()


# ------------------------------------------------------------------- reset_password


def test_reset_password_runs_passwd_and_clears_a_stale_keyring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "pat"
    keyring_dir = home / students.KEYRING_DIR_REL
    keyring_dir.mkdir(parents=True)
    (keyring_dir / "login.keyring").write_text("stale")
    ctx = _ctx(tmp_path, dry_run=False)
    calls: list[list[str]] = []
    monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: calls.append(list(argv)))

    existed = students.reset_password(ctx, "pat")

    assert existed is True
    assert not keyring_dir.exists()
    assert calls == [["passwd", "pat"]]


def test_reset_password_reports_false_when_no_keyring_to_clear(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "pat").mkdir()
    ctx = _ctx(tmp_path, dry_run=False)
    monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: None)

    existed = students.reset_password(ctx, "pat")

    assert existed is False


def test_reset_password_raises_when_home_directory_is_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(StepFailed, match="No home directory"):
        students.reset_password(_ctx(tmp_path, dry_run=False), "nobody")


def test_reset_password_dry_run_deletes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "pat"
    keyring_dir = home / students.KEYRING_DIR_REL
    keyring_dir.mkdir(parents=True)
    ctx = _ctx(tmp_path, dry_run=True)
    calls: list[list[str]] = []
    monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: calls.append(list(argv)))

    students.reset_password(ctx, "pat")

    assert keyring_dir.exists()
    assert calls == [["passwd", "pat"]]


# ------------------------------------------------------------------ configure_skel


def test_configure_skel_writes_both_files_under_skel_root(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))
    students.configure_skel(ctx)

    for rel in students.RESETTABLE_DEFAULTS:
        path = students.SKEL_ROOT / rel
        [record] = [r for r in caplog.records if str(path) in r.message]
        assert record  # written at all -- content assertions below


def test_configure_skel_panel_drops_power_manager_and_has_launchers_in_order(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))
    students.configure_skel(ctx)

    panel_rel = next(
        rel
        for rel, name in students.RESETTABLE_DEFAULTS.items()
        if name == "xfce4-panel-default.xml"
    )
    path = students.SKEL_ROOT / panel_rel
    [record] = [r for r in caplog.records if str(path) in r.message]

    assert 'value="power-manager-plugin"' not in record.message
    assert 'value="xkb"' in record.message
    launchers = [
        "thunar.desktop",
        "google-chrome.desktop",
        "drracket.desktop",
        "code.desktop",
        "xfce4-terminal.desktop",
    ]
    positions = [record.message.index(name) for name in launchers]
    assert positions == sorted(positions)
    assert "%S" in record.message  # clock shows seconds


def test_configure_skel_keyboard_layout_is_altgr_intl(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``altgr-intl``, not ``alt-intl`` -- ``alt-intl`` puts dead keys on the
    base level of the quote/apostrophe key, so typing a plain `"` silently
    waited for a second keystroke; ``altgr-intl`` keeps the plain character
    on the base level and moves the dead key behind AltGr where it belongs.
    """
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))
    students.configure_skel(ctx)

    keyboard_rel = next(
        rel
        for rel, name in students.RESETTABLE_DEFAULTS.items()
        if name == "keyboard-layout-default.xml"
    )
    path = students.SKEL_ROOT / keyboard_rel
    [record] = [r for r in caplog.records if str(path) in r.message]
    assert 'value="altgr-intl,dvorak-alt-intl"' in record.message


def test_configure_skel_racket_prefs_highlights_spring_parens_and_bsl(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="ltsp-setup")
    ctx = Context(Settings(), Runner(dry_run=True))
    students.configure_skel(ctx)

    racket_rel = next(
        rel
        for rel, name in students.RESETTABLE_DEFAULTS.items()
        if name == "racket-prefs-default.rktd"
    )
    path = students.SKEL_ROOT / racket_rel
    [record] = [r for r in caplog.records if str(path) in r.message]
    assert "framework:paren-color-scheme spring" in record.message
    assert '"#lang htdp/bsl\\n"' in record.message
    # No personal file-history from whoever's account the template was
    # captured from -- only ever the (empty) placeholders below.
    assert "framework:last-opened-files ()" in record.message
    assert "drracket:recently-closed-tabs ()" in record.message


def test_configure_skel_appends_the_ctrl_swap_snippet_commented_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    skel = tmp_path / "etc-skel"
    monkeypatch.setattr(students, "SKEL_ROOT", skel)
    skel.mkdir()
    (skel / ".bashrc").write_text("# stock bashrc\n")
    ctx = Context(Settings(), Runner(dry_run=False))

    students.configure_skel(ctx)

    text = (skel / ".bashrc").read_text()
    assert text.startswith("# stock bashrc\n")
    assert "#setxkbmap -option ctrl:swap_lalt_lctl" in text


# ---------------------------------------------------------- real_student_accounts


def test_real_student_accounts_excludes_admin_and_protected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path, dry_run=True, protected_usernames=("student",))
    monkeypatch.setattr(
        ctx.runner,
        "passwd_entries",
        lambda: [
            ("root", 0),
            ("sysadmin", 1000),
            ("student", 1002),
            ("aadams27", 1003),
            ("zwhite28", 1004),
            ("nobody", 65534),
        ],
    )
    assert students.real_student_accounts(ctx) == ["aadams27", "zwhite28"]


# ---------------------------------------------------------------------- remove_all


def test_remove_all_dry_run_calls_nothing_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path, dry_run=True)
    monkeypatch.setattr(ctx.runner, "passwd_entries", lambda: [("aadams27", 1003)])
    (tmp_path / "aadams27").mkdir()
    (tmp_path / "aadams27" / "essay.txt").write_text("real work")

    names = students.remove_all(ctx)

    assert names == ["aadams27"]
    assert (tmp_path / "aadams27" / "essay.txt").exists()


def test_remove_all_runs_userdel_and_ltsp_initrd_for_real(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path, dry_run=False)
    monkeypatch.setattr(
        ctx.runner, "passwd_entries", lambda: [("aadams27", 1003), ("zwhite28", 1004)]
    )
    calls: list[list[str]] = []
    monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: calls.append(list(argv)))

    names = students.remove_all(ctx)

    assert names == ["aadams27", "zwhite28"]
    assert calls == [
        ["userdel", "-r", "aadams27"],
        ["userdel", "-r", "zwhite28"],
        ["ltsp", "initrd"],
    ]


def test_remove_all_skips_ltsp_initrd_when_nobody_to_remove(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path, dry_run=False)
    monkeypatch.setattr(ctx.runner, "passwd_entries", lambda: [])
    calls: list[list[str]] = []
    monkeypatch.setattr(ctx.runner, "run", lambda argv, **kw: calls.append(list(argv)))

    assert students.remove_all(ctx) == []
    assert calls == []


# ------------------------------------------------------------------ apply_defaults


def test_apply_defaults_writes_missing_files(tmp_path: Path) -> None:
    home = tmp_path / "pat"
    home.mkdir()
    ctx = _ctx(tmp_path, dry_run=False)

    result = students.apply_defaults(ctx, "pat")

    assert sorted(result.applied) == [
        "keyboard-layout.xml: created",
        "racket-prefs.rktd: created",
        "xfce4-panel.xml: created",
        "xfwm4.xml: created",
    ]
    assert result.skipped == []
    for rel in students.RESETTABLE_DEFAULTS:
        assert (home / rel).exists()


def test_apply_defaults_adds_the_ctrl_swap_snippet_to_an_existing_account(
    tmp_path: Path,
) -> None:
    home = tmp_path / "pat"
    home.mkdir()
    (home / ".bashrc").write_text("# pat's own bashrc\n")
    ctx = _ctx(tmp_path, dry_run=False)

    students.apply_defaults(ctx, "pat")

    text = (home / ".bashrc").read_text()
    assert text.startswith("# pat's own bashrc\n")
    assert "#setxkbmap -option ctrl:swap_lalt_lctl" in text


def test_apply_defaults_does_not_duplicate_an_already_uncommented_snippet(
    tmp_path: Path,
) -> None:
    home = tmp_path / "pat"
    home.mkdir()
    (home / ".bashrc").write_text(
        "# --- ltsp-setup: ctrl-alt-swap ---\n"
        "setxkbmap -option ctrl:swap_lalt_lctl\n"
        "# --- end ltsp-setup ---\n"
    )
    ctx = _ctx(tmp_path, dry_run=False)

    students.apply_defaults(ctx, "pat")

    text = (home / ".bashrc").read_text()
    assert text.count("ltsp-setup: ctrl-alt-swap") == 1
    assert "setxkbmap -option ctrl:swap_lalt_lctl" in text
    assert "#setxkbmap" not in text


def test_apply_defaults_second_call_is_a_no_op_when_nothing_changed(
    tmp_path: Path,
) -> None:
    home = tmp_path / "pat"
    home.mkdir()
    ctx = _ctx(tmp_path, dry_run=False)
    students.apply_defaults(ctx, "pat")  # creates the files, advances baseline

    result = students.apply_defaults(ctx, "pat")  # nothing changed in between

    assert result.applied == []
    assert result.skipped == []


def test_apply_defaults_skips_a_property_the_student_customized(
    tmp_path: Path,
) -> None:
    home = tmp_path / "pat"
    home.mkdir()
    ctx = _ctx(tmp_path, dry_run=False)
    students.apply_defaults(ctx, "pat")  # creates the files, advances baseline

    rel = next(
        rel
        for rel, name in students.RESETTABLE_DEFAULTS.items()
        if name == "keyboard-layout-default.xml"
    )
    target = home / rel
    customized = _set_property_value(target.read_text(), "XkbVariant", "us,us")
    target.write_text(customized)

    result = students.apply_defaults(ctx, "pat")

    assert result.skipped == [("keyboard-layout.xml:Default/XkbVariant", "customized")]
    assert target.read_text() == customized


def test_apply_defaults_skips_an_unrecorded_property_but_adds_a_missing_one(
    tmp_path: Path,
) -> None:
    """A file that exists before we've ever run apply_defaults against it
    (base=None): a property with an unexpected value is left alone
    ("unknown" provenance), but a property genuinely missing from it still
    gets added -- there's nothing to lose by adding something that was
    never there.
    """
    home = tmp_path / "pat"
    home.mkdir()
    rel = next(
        rel
        for rel, name in students.RESETTABLE_DEFAULTS.items()
        if name == "keyboard-layout-default.xml"
    )
    target = home / rel
    target.parent.mkdir(parents=True)

    root = ET.fromstring(templates.read("keyboard-layout-default.xml"))
    default_group = next(
        e for e in root.iter("property") if e.attrib.get("name") == "Default"
    )
    for child in list(default_group):
        if child.attrib.get("name") == "XkbVariant":
            child.set("value", "something-else-entirely")
        if child.attrib.get("name") == "XkbDisable":
            default_group.remove(child)  # simulate a property added later
    target.write_text(
        xfconf.XML_DECLARATION + ET.tostring(root, encoding="unicode") + "\n"
    )
    ctx = _ctx(tmp_path, dry_run=False)

    result = students.apply_defaults(ctx, "pat")

    assert ("keyboard-layout.xml:Default/XkbVariant", "unknown") in result.skipped
    assert "keyboard-layout.xml:Default/XkbDisable" in result.applied
    assert 'value="something-else-entirely"' in target.read_text()


def test_apply_defaults_raises_when_home_directory_is_missing(
    tmp_path: Path,
) -> None:
    with pytest.raises(StepFailed, match="No home directory"):
        students.apply_defaults(_ctx(tmp_path, dry_run=False), "nobody")


def test_apply_defaults_dry_run_creates_nothing_and_does_not_advance_baseline(
    tmp_path: Path,
) -> None:
    home = tmp_path / "pat"
    home.mkdir()
    ctx = _ctx(tmp_path, dry_run=True)

    result = students.apply_defaults(ctx, "pat")

    assert sorted(result.applied) == [
        "keyboard-layout.xml: created",
        "racket-prefs.rktd: created",
        "xfce4-panel.xml: created",
        "xfwm4.xml: created",
    ]
    for rel in students.RESETTABLE_DEFAULTS:
        assert not (home / rel).exists()
    assert not students.TEMPLATE_BASELINE_DIR.exists()


def test_apply_defaults_all_covers_every_real_student_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _ctx(tmp_path, dry_run=False)
    monkeypatch.setattr(
        ctx.runner, "passwd_entries", lambda: [("aadams27", 1003), ("zwhite28", 1004)]
    )
    (tmp_path / "aadams27").mkdir()
    (tmp_path / "zwhite28").mkdir()

    results = students.apply_defaults_all(ctx)

    assert set(results) == {"aadams27", "zwhite28"}
    for result in results.values():
        assert sorted(result.applied) == [
            "keyboard-layout.xml: created",
            "racket-prefs.rktd: created",
            "xfce4-panel.xml: created",
            "xfwm4.xml: created",
        ]


def test_apply_defaults_all_compares_every_account_against_the_same_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The template snapshot must not advance mid-loop: if it did, whichever
    account is processed first would make later accounts in the same run
    look "customized" by comparison, even though neither student touched
    anything.
    """
    ctx = _ctx(tmp_path, dry_run=False)
    monkeypatch.setattr(
        ctx.runner, "passwd_entries", lambda: [("aadams27", 1003), ("zwhite28", 1004)]
    )
    (tmp_path / "aadams27").mkdir()
    (tmp_path / "zwhite28").mkdir()
    students.apply_defaults_all(ctx)  # both accounts get v1, baseline -> v1

    real_read = templates.read
    v2_variant = "v2-changed-variant"

    def v2_read(name: str) -> str:
        content = real_read(name)
        if name == "keyboard-layout-default.xml":
            return _set_property_value(content, "XkbVariant", v2_variant)
        return content

    monkeypatch.setattr(templates, "read", v2_read)

    results = students.apply_defaults_all(ctx)

    for username, result in results.items():
        assert "keyboard-layout.xml:Default/XkbVariant" in result.applied, username
        rel = next(
            rel
            for rel, name in students.RESETTABLE_DEFAULTS.items()
            if name == "keyboard-layout-default.xml"
        )
        assert f'value="{v2_variant}"' in (tmp_path / username / rel).read_text()


# ---------------------------------------------------------------------- push_files


def _sources(tmp_path: Path) -> list[Path]:
    """The two handout files push-lab.sh used to carry, one of them binary."""
    source_dir = tmp_path / "from-todd"
    source_dir.mkdir()
    starter = source_dir / "lab01-starter.odt"
    starter.write_bytes(b"PK\x03\x04 odt container")
    activity = source_dir / "lab01-activity.html"
    activity.write_text("<h1>Lab 01</h1>\n")
    return [starter, activity]


def _push_ctx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dry_run: bool,
    accounts: list[tuple[str, int]],
    group_members: dict[str, list[str]] | None = None,
) -> tuple[Context, list[tuple[Path, str, str]]]:
    """A context whose account, group and ownership lookups are all faked.

    Returns the context and a list that records every chown, since a test
    running as an ordinary user can't chown to accounts that don't exist.
    """
    home_root = tmp_path / "home"
    home_root.mkdir()
    ctx = _ctx(home_root, dry_run=dry_run)
    members = group_members or {}
    chowns: list[tuple[Path, str, str]] = []

    monkeypatch.setattr(ctx.runner, "passwd_entries", lambda: accounts)
    monkeypatch.setattr(ctx.runner, "group_exists", lambda name: name in members)
    monkeypatch.setattr(ctx.runner, "group_members", lambda name: members.get(name, []))
    monkeypatch.setattr(ctx.runner, "primary_group", lambda username: username)
    monkeypatch.setattr(
        ctx.runner,
        "chown",
        lambda path, user, group=None: chowns.append((path, user, group or user)),
    )
    return ctx, chowns


def _make_home(ctx: Context, username: str) -> Path:
    home = ctx.settings.students.home_root / username
    home.mkdir(parents=True)
    return home


def test_push_files_copies_every_source_to_every_student(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, chowns = _push_ctx(
        tmp_path,
        monkeypatch,
        dry_run=False,
        accounts=[("aadams27", 1003), ("zwhite28", 1004)],
    )
    for name in ("aadams27", "zwhite28"):
        _make_home(ctx, name)
    sources = _sources(tmp_path)

    result = students.push_files(ctx, sources)

    for name in ("aadams27", "zwhite28"):
        desktop = ctx.settings.students.home_root / name / "Desktop"
        assert (desktop / "lab01-starter.odt").read_bytes() == sources[0].read_bytes()
        assert (desktop / "lab01-activity.html").read_text() == "<h1>Lab 01</h1>\n"
    assert sorted(result.pushed) == [
        "aadams27: lab01-activity.html",
        "aadams27: lab01-starter.odt",
        "zwhite28: lab01-activity.html",
        "zwhite28: lab01-starter.odt",
    ]
    assert result.skipped == []


def test_push_files_gives_every_file_and_directory_to_the_student(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A handout the student can't edit or delete is worse than no handout."""
    ctx, chowns = _push_ctx(
        tmp_path, monkeypatch, dry_run=False, accounts=[("aadams27", 1003)]
    )
    _make_home(ctx, "aadams27")
    sources = _sources(tmp_path)

    students.push_files(ctx, sources)

    desktop = ctx.settings.students.home_root / "aadams27" / "Desktop"
    assert chowns == [
        (desktop, "aadams27", "aadams27"),
        (desktop / "lab01-starter.odt", "aadams27", "aadams27"),
        (desktop / "lab01-activity.html", "aadams27", "aadams27"),
    ]
    for name in ("lab01-starter.odt", "lab01-activity.html"):
        assert (desktop / name).stat().st_mode & 0o777 == 0o644


def test_push_files_dry_run_copies_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _push_ctx(
        tmp_path, monkeypatch, dry_run=True, accounts=[("aadams27", 1003)]
    )
    _make_home(ctx, "aadams27")

    result = students.push_files(ctx, _sources(tmp_path))

    assert not (ctx.settings.students.home_root / "aadams27" / "Desktop").exists()
    assert result.pushed == [
        "aadams27: lab01-starter.odt",
        "aadams27: lab01-activity.html",
    ]


def test_push_files_leaves_an_identical_file_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, chowns = _push_ctx(
        tmp_path, monkeypatch, dry_run=False, accounts=[("aadams27", 1003)]
    )
    home = _make_home(ctx, "aadams27")
    sources = _sources(tmp_path)
    desktop = home / "Desktop"
    desktop.mkdir()
    (desktop / "lab01-activity.html").write_text("<h1>Lab 01</h1>\n")

    result = students.push_files(ctx, sources)

    assert result.unchanged == ["aadams27: lab01-activity.html"]
    assert result.pushed == ["aadams27: lab01-starter.odt"]
    assert chowns == [(desktop / "lab01-starter.odt", "aadams27", "aadams27")]


def test_push_files_never_writes_over_a_students_own_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case the renaming exists for: the student did the lab *in* the
    file they were given, under the same name.
    """
    ctx, _ = _push_ctx(
        tmp_path, monkeypatch, dry_run=False, accounts=[("aadams27", 1003)]
    )
    home = _make_home(ctx, "aadams27")
    sources = _sources(tmp_path)
    desktop = home / "Desktop"
    desktop.mkdir()
    theirs = desktop / "lab01-activity.html"
    theirs.write_text("<h1>Lab 01</h1>\n<p>my answers</p>\n")

    result = students.push_files(ctx, sources)

    assert theirs.read_text() == "<h1>Lab 01</h1>\n<p>my answers</p>\n"
    assert (desktop / "lab01-activity-2.html").read_text() == "<h1>Lab 01</h1>\n"
    assert sorted(result.pushed) == [
        "aadams27: lab01-activity-2.html",
        "aadams27: lab01-starter.odt",
    ]
    assert result.skipped == []


def test_push_files_numbers_before_the_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """So the copy still opens in the right application when double-clicked."""
    assert students._suffixed("lab01-activity.html", 2) == "lab01-activity-2.html"
    assert students._suffixed("notes.tar.gz", 3) == "notes-3.tar.gz"
    assert students._suffixed("README", 2) == "README-2"


def test_push_files_re_run_does_not_pile_up_more_numbered_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pushing the same file twice to a student who customised theirs leaves
    one numbered copy, not one per run.
    """
    ctx, _ = _push_ctx(
        tmp_path, monkeypatch, dry_run=False, accounts=[("aadams27", 1003)]
    )
    home = _make_home(ctx, "aadams27")
    sources = _sources(tmp_path)
    desktop = home / "Desktop"
    desktop.mkdir()
    (desktop / "lab01-activity.html").write_text("my answers\n")

    students.push_files(ctx, sources)
    result = students.push_files(ctx, sources)

    assert not (desktop / "lab01-activity-3.html").exists()
    assert sorted(result.unchanged) == [
        "aadams27: lab01-activity-2.html",
        "aadams27: lab01-starter.odt",
    ]
    assert result.pushed == []


def test_push_files_climbs_past_several_existing_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _push_ctx(
        tmp_path, monkeypatch, dry_run=False, accounts=[("aadams27", 1003)]
    )
    home = _make_home(ctx, "aadams27")
    sources = _sources(tmp_path)
    desktop = home / "Desktop"
    desktop.mkdir()
    (desktop / "lab01-activity.html").write_text("draft one\n")
    (desktop / "lab01-activity-2.html").write_text("draft two\n")

    result = students.push_files(ctx, sources)

    assert (desktop / "lab01-activity-3.html").read_text() == "<h1>Lab 01</h1>\n"
    assert "aadams27: lab01-activity-3.html" in result.pushed


def test_push_files_replaces_in_place_when_told_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _push_ctx(
        tmp_path, monkeypatch, dry_run=False, accounts=[("aadams27", 1003)]
    )
    home = _make_home(ctx, "aadams27")
    sources = _sources(tmp_path)
    desktop = home / "Desktop"
    desktop.mkdir()
    (desktop / "lab01-activity.html").write_text("stale draft\n")

    result = students.push_files(ctx, sources, overwrite=True)

    assert (desktop / "lab01-activity.html").read_text() == "<h1>Lab 01</h1>\n"
    assert not (desktop / "lab01-activity-2.html").exists()
    assert result.replaced == ["aadams27: lab01-activity.html"]
    assert result.pushed == ["aadams27: lab01-starter.odt"]


def test_overwrite_fixes_the_named_file_even_when_a_numbered_copy_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An earlier run left the new version at -2 beside the student's own.
    --overwrite is then asking about the named file, so an identical -2 is
    not a reason to call the job done.
    """
    ctx, _ = _push_ctx(
        tmp_path, monkeypatch, dry_run=False, accounts=[("aadams27", 1003)]
    )
    home = _make_home(ctx, "aadams27")
    sources = _sources(tmp_path)
    desktop = home / "Desktop"
    desktop.mkdir()
    (desktop / "lab01-activity.html").write_text("my answers\n")
    (desktop / "lab01-activity-2.html").write_text("<h1>Lab 01</h1>\n")

    result = students.push_files(ctx, sources, overwrite=True)

    assert (desktop / "lab01-activity.html").read_text() == "<h1>Lab 01</h1>\n"
    assert result.replaced == ["aadams27: lab01-activity.html"]


def test_push_files_gives_up_rather_than_adding_a_hundredth_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _push_ctx(
        tmp_path, monkeypatch, dry_run=False, accounts=[("aadams27", 1003)]
    )
    home = _make_home(ctx, "aadams27")
    activity = _sources(tmp_path)[1]
    desktop = home / "Desktop"
    desktop.mkdir()
    (desktop / "lab01-activity.html").write_text("different 1\n")
    for index in range(2, students.MAX_SUFFIXED_COPIES + 1):
        (desktop / f"lab01-activity-{index}.html").write_text(f"different {index}\n")

    with pytest.raises(StepFailed, match="copies of lab01-activity.html"):
        students.push_files(ctx, [activity])


def test_push_files_to_a_group_covers_primary_and_secondary_members(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _push_ctx(
        tmp_path,
        monkeypatch,
        dry_run=False,
        accounts=[("aadams27", 1003), ("zwhite28", 1004), ("bbrown29", 1005)],
        group_members={"r1": ["aadams27", "zwhite28"]},
    )
    for name in ("aadams27", "zwhite28", "bbrown29"):
        _make_home(ctx, name)

    result = students.push_files(ctx, _sources(tmp_path), group="r1")

    assert not (ctx.settings.students.home_root / "bbrown29" / "Desktop").exists()
    assert sorted(result.pushed) == [
        "aadams27: lab01-activity.html",
        "aadams27: lab01-starter.odt",
        "zwhite28: lab01-activity.html",
        "zwhite28: lab01-starter.odt",
    ]


def test_push_files_to_a_group_skips_the_teachers_own_account(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Todd is in his own sections' groups; a push aimed at a section
    shouldn't drop files on his desktop.
    """
    ctx, _ = _push_ctx(
        tmp_path,
        monkeypatch,
        dry_run=False,
        accounts=[("aadams27", 1003), ("toddobryan", 1001)],
        group_members={"r1": ["aadams27", "toddobryan"]},
    )
    _make_home(ctx, "aadams27")
    _make_home(ctx, "toddobryan")

    result = students.push_files(ctx, _sources(tmp_path), group="r1")

    assert not (ctx.settings.students.home_root / "toddobryan" / "Desktop").exists()
    assert result.skipped == [("toddobryan", "not a student account")]


def test_push_files_raises_on_a_group_that_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _push_ctx(
        tmp_path, monkeypatch, dry_run=False, accounts=[("aadams27", 1003)]
    )
    _make_home(ctx, "aadams27")

    with pytest.raises(StepFailed, match="No such group: r9"):
        students.push_files(ctx, _sources(tmp_path), group="r9")


def test_push_files_pushes_nothing_when_a_source_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Checked up front, so a typo'd filename can't leave half a class with
    one of the two files.
    """
    ctx, _ = _push_ctx(
        tmp_path, monkeypatch, dry_run=False, accounts=[("aadams27", 1003)]
    )
    _make_home(ctx, "aadams27")
    sources = _sources(tmp_path) + [tmp_path / "from-todd" / "lab01-typo.html"]

    with pytest.raises(StepFailed, match="lab01-typo.html"):
        students.push_files(ctx, sources)

    assert not (ctx.settings.students.home_root / "aadams27" / "Desktop").exists()


def test_push_files_skips_an_account_with_no_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _push_ctx(
        tmp_path,
        monkeypatch,
        dry_run=False,
        accounts=[("aadams27", 1003), ("nohome30", 1006)],
    )
    _make_home(ctx, "aadams27")

    result = students.push_files(ctx, _sources(tmp_path))

    assert result.skipped == [
        ("nohome30", f"no home directory at {ctx.settings.students.home_root}/nohome30")
    ]
    assert len(result.pushed) == 2


def test_push_files_honours_a_configured_destination(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home_root = tmp_path / "home"
    home_root.mkdir()
    ctx = Context(
        Settings(students=Students(home_root=home_root, push_dest=Path("handouts/cs"))),
        Runner(dry_run=False),
    )
    monkeypatch.setattr(ctx.runner, "passwd_entries", lambda: [("aadams27", 1003)])
    monkeypatch.setattr(ctx.runner, "primary_group", lambda username: username)
    monkeypatch.setattr(ctx.runner, "chown", lambda path, user, group=None: None)
    (home_root / "aadams27").mkdir()

    students.push_files(ctx, _sources(tmp_path))

    assert (home_root / "aadams27" / "handouts" / "cs" / "lab01-starter.odt").is_file()


def test_push_files_takes_a_destination_per_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _push_ctx(
        tmp_path, monkeypatch, dry_run=False, accounts=[("aadams27", 1003)]
    )
    home = _make_home(ctx, "aadams27")

    students.push_files(ctx, _sources(tmp_path), dest=Path("Documents/labs"))

    assert (home / "Documents" / "labs" / "lab01-starter.odt").is_file()
    assert not (home / "Desktop").exists()


def test_push_files_refuses_a_destination_that_escapes_the_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This path is joined onto every targeted home directory, so a '..' in
    it is a way to write across the server by typo.
    """
    ctx, _ = _push_ctx(
        tmp_path, monkeypatch, dry_run=False, accounts=[("aadams27", 1003)]
    )
    _make_home(ctx, "aadams27")
    sources = _sources(tmp_path)

    with pytest.raises(StepFailed, match=r"can't contain '\.\.'"):
        students.push_files(ctx, sources, dest=Path("../../etc"))

    with pytest.raises(StepFailed, match=r"can't start with '/'"):
        students.push_files(ctx, sources, dest=Path("/etc/skel"))


# --------------------------------------------------------------- collecting

_CLASS = {
    "r1": ["jsmith30"],
    "r4": ["aadams27"],
    "w2": [],
    "w3": [],
    "w4": [],
}


def _collect_ctx(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dry_run: bool = False,
    group_members: dict[str, list[str]] | None = None,
) -> tuple[Context, list[tuple[Path, str, str]]]:
    """A class of two with real home directories, plus the admin's."""
    members = _CLASS if group_members is None else group_members
    names = sorted({name for group in members.values() for name in group})
    ctx, chowns = _push_ctx(
        tmp_path,
        monkeypatch,
        dry_run=dry_run,
        accounts=[(name, 1003 + i) for i, name in enumerate(names)],
        group_members=members,
    )
    for name in {ctx.settings.admin_user, *names}:
        _make_home(ctx, name)
    return ctx, chowns


def _submit(ctx: Context, username: str, text: str = "(define x 1)") -> Path:
    path = ctx.settings.students.home_root / username / "image-exercises.rkt"
    path.write_text(text)
    return path


def _filed(ctx: Context, *parts: str) -> Path:
    return ctx.settings.students.home_root.joinpath(
        "sysadmin", "assignments", "image-exercises", *parts
    )


def test_collect_files_by_section_and_username_and_leaves_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    original = _submit(ctx, "jsmith30", "mine")
    _submit(ctx, "aadams27", "theirs")

    result = students.collect_assignment(ctx, "image-exercises.rkt")

    assert _filed(ctx, "r1", "jsmith30.rkt").read_text() == "mine"
    assert _filed(ctx, "r4", "aadams27.rkt").read_text() == "theirs"
    assert original.read_text() == "mine"
    receipt = original.parent / "turned-in" / "image-exercises.rkt"
    assert receipt.read_text() == "mine"
    assert sorted(result.collected) == ["r1/jsmith30.rkt", "r4/aadams27.rkt"]
    assert result.missing == [] and result.skipped == []


def test_collect_makes_a_folder_for_every_section_even_an_empty_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)

    students.collect_assignment(ctx, "image-exercises.rkt")

    for group in ("r1", "r4", "w2", "w3", "w4"):
        assert _filed(ctx, group).is_dir()


def test_collect_gives_every_student_a_readable_unwritable_turned_in_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Including one with nothing to hand in yet. Owned by whoever runs this
    (root, for real), so what the student is left with is the "other" bits.
    """
    ctx, chowns = _collect_ctx(tmp_path, monkeypatch)
    original = _submit(ctx, "jsmith30")

    students.collect_assignment(ctx, "image-exercises.rkt")

    for name in ("jsmith30", "aadams27"):
        folder = ctx.settings.students.home_root / name / "turned-in"
        assert folder.stat().st_mode & 0o777 == 0o755
        assert folder not in [path for path, _, _ in chowns]
    receipt = original.parent / "turned-in" / "image-exercises.rkt"
    assert receipt.stat().st_mode & 0o777 == 0o644
    assert receipt not in [path for path, _, _ in chowns]


def test_collect_keeps_submissions_away_from_classmates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """/home is on every client, so a readable folder here is a cheat sheet."""
    ctx, chowns = _collect_ctx(tmp_path, monkeypatch)
    root = ctx.settings.students.home_root / "sysadmin" / "assignments"
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    _submit(ctx, "jsmith30")

    students.collect_assignment(ctx, "image-exercises.rkt")

    assert root.stat().st_mode & 0o777 == 0o700
    filed = _filed(ctx, "r1", "jsmith30.rkt")
    assert filed.stat().st_mode & 0o777 == 0o600
    assert (filed, "sysadmin", "sysadmin") in chowns
    assert (_filed(ctx, "r1"), "sysadmin", "sysadmin") in chowns


def test_collect_reports_who_has_not_turned_anything_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    _submit(ctx, "jsmith30")

    result = students.collect_assignment(ctx, "image-exercises.rkt")

    assert result.missing == ["r4/aadams27"]


def test_collect_again_tells_collected_apart_from_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    original = _submit(ctx, "jsmith30")
    students.collect_assignment(ctx, "image-exercises.rkt")
    original.unlink()

    result = students.collect_assignment(ctx, "image-exercises.rkt")

    assert result.collected == []
    assert result.already_collected == ["r1/jsmith30"]
    assert result.missing == ["r4/aadams27"]


def test_collect_keeps_both_versions_of_a_resubmission(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    original = _submit(ctx, "jsmith30", "first")
    students.collect_assignment(ctx, "image-exercises.rkt")
    _submit(ctx, "jsmith30", "second")

    result = students.collect_assignment(ctx, "image-exercises.rkt")

    assert result.collected == ["r1/jsmith30-2.rkt"]
    assert _filed(ctx, "r1", "jsmith30.rkt").read_text() == "first"
    assert _filed(ctx, "r1", "jsmith30-2.rkt").read_text() == "second"
    turned_in = original.parent / "turned-in"
    assert (turned_in / "image-exercises.rkt").read_text() == "first"
    assert (turned_in / "image-exercises-2.rkt").read_text() == "second"


def test_collect_of_an_unchanged_file_adds_no_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    original = _submit(ctx, "jsmith30", "same")
    students.collect_assignment(ctx, "image-exercises.rkt")
    _submit(ctx, "jsmith30", "same")

    result = students.collect_assignment(ctx, "image-exercises.rkt")

    assert result.collected == []
    assert "r1/jsmith30" in result.already_collected
    assert not _filed(ctx, "r1", "jsmith30-2.rkt").exists()
    assert not (original.parent / "turned-in" / "image-exercises-2.rkt").exists()


def test_collect_files_a_student_in_two_sections_in_both(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(
        tmp_path,
        monkeypatch,
        group_members={**_CLASS, "w2": ["jsmith30"]},
    )
    original = _submit(ctx, "jsmith30", "mine")

    students.collect_assignment(ctx, "image-exercises.rkt")

    assert _filed(ctx, "r1", "jsmith30.rkt").read_text() == "mine"
    assert _filed(ctx, "w2", "jsmith30.rkt").read_text() == "mine"
    assert len(list((original.parent / "turned-in").iterdir())) == 1


def test_collect_leaves_staff_in_a_section_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(
        tmp_path,
        monkeypatch,
        group_members={**_CLASS, "r1": ["jsmith30", "sysadmin"]},
    )
    admin_home = ctx.settings.students.home_root / "sysadmin"
    (admin_home / "image-exercises.rkt").write_text("answer key")

    result = students.collect_assignment(ctx, "image-exercises.rkt")

    assert (admin_home / "image-exercises.rkt").read_text() == "answer key"
    assert not (admin_home / "turned-in").exists()
    assert result.missing == ["r1/jsmith30", "r4/aadams27"]


def test_collect_dry_run_changes_nothing_but_reports_the_same(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch, dry_run=True)
    original = _submit(ctx, "jsmith30")

    result = students.collect_assignment(ctx, "image-exercises.rkt")

    assert result.collected == ["r1/jsmith30.rkt"]
    assert result.missing == ["r4/aadams27"]
    assert original.exists()
    assert not (original.parent / "turned-in").exists()
    assert not (ctx.settings.students.home_root / "sysadmin" / "assignments").exists()


@pytest.mark.parametrize(
    "filename",
    ["", ".", ".bashrc", ".ssh/id_ed25519", "labs/../../sysadmin/x", "/etc/shadow"],
)
def test_collect_refuses_a_path_that_leaves_the_home_or_is_hidden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, filename: str
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)

    with pytest.raises(StepFailed, match="Give a path inside"):
        students.collect_assignment(ctx, filename)

    assert not (ctx.settings.students.home_root / "sysadmin" / "assignments").exists()


def test_collect_touches_nothing_when_a_section_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    members = {name: group for name, group in _CLASS.items() if name != "w4"}
    ctx, _ = _collect_ctx(tmp_path, monkeypatch, group_members=members)
    original = _submit(ctx, "jsmith30")

    with pytest.raises(StepFailed, match="No such group: w4"):
        students.collect_assignment(ctx, "image-exercises.rkt")

    assert original.exists()
    assert not (ctx.settings.students.home_root / "sysadmin" / "assignments").exists()


def test_collect_fails_without_the_admin_home_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    (ctx.settings.students.home_root / "sysadmin").rmdir()

    with pytest.raises(StepFailed, match="No home directory for sysadmin"):
        students.collect_assignment(ctx, "image-exercises.rkt")


def test_collect_will_not_read_through_a_symlink_a_student_planted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root following this would put /etc/shadow in a folder they can read."""
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    secret = tmp_path / "shadow"
    secret.write_text("root:hash")
    planted = ctx.settings.students.home_root / "jsmith30" / "image-exercises.rkt"
    planted.symlink_to(secret)
    _submit(ctx, "aadams27", "honest work")

    result = students.collect_assignment(ctx, "image-exercises.rkt")

    assert [name for name, _ in result.skipped] == ["jsmith30"]
    assert planted.is_symlink()
    assert not _filed(ctx, "r1", "jsmith30.rkt").exists()
    assert list((planted.parent / "turned-in").iterdir()) == []
    assert _filed(ctx, "r4", "aadams27.rkt").read_text() == "honest work"


def test_collect_will_not_write_through_a_symlinked_turned_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root following this would drop a file anywhere the student points it."""
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    elsewhere = tmp_path / "etc"
    elsewhere.mkdir()
    original = _submit(ctx, "jsmith30")
    (original.parent / "turned-in").symlink_to(elsewhere)

    result = students.collect_assignment(ctx, "image-exercises.rkt")

    assert [name for name, _ in result.skipped] == ["jsmith30"]
    assert list(elsewhere.iterdir()) == []
    assert original.exists()
    assert not _filed(ctx, "r1", "jsmith30.rkt").exists()


def test_collect_skips_a_turned_in_folder_the_student_made_themselves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    original = _submit(ctx, "jsmith30")
    theirs = original.parent / "turned-in"
    theirs.mkdir()
    monkeypatch.setattr("os.geteuid", lambda: theirs.stat().st_uid + 1)

    result = students.collect_assignment(ctx, "image-exercises.rkt")

    assert "isn't the folder this tool made" in result.skipped[0][1]
    assert original.exists()


def test_collect_skips_a_directory_with_the_assignment_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    folder = ctx.settings.students.home_root / "jsmith30" / "image-exercises.rkt"
    folder.mkdir()

    result = students.collect_assignment(ctx, "image-exercises.rkt")

    assert result.skipped == [
        ("jsmith30", f"{folder} isn't a plain file in a real folder")
    ]
    assert folder.is_dir()


def test_collect_carries_on_with_the_class_if_one_copy_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    _submit(ctx, "jsmith30")
    _submit(ctx, "aadams27", "theirs")
    real_copy = ctx.runner.copy_nofollow

    def fail_for_jsmith(
        src_root: Path,
        src_rel: Path,
        dest_root: Path,
        dest_rel: Path,
        *,
        mode: int = 0o644,
    ) -> None:
        if "jsmith30" in str(src_root):
            raise StepFailed("disk full")
        real_copy(src_root, src_rel, dest_root, dest_rel, mode=mode)

    monkeypatch.setattr(ctx.runner, "copy_nofollow", fail_for_jsmith)

    result = students.collect_assignment(ctx, "image-exercises.rkt")

    assert result.skipped == [("jsmith30", "disk full")]
    assert _filed(ctx, "r4", "aadams27.rkt").read_text() == "theirs"


def test_collect_finishes_the_job_after_a_failure_between_the_two_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    original = _submit(ctx, "jsmith30", "mine")
    real_copy = ctx.runner.copy_nofollow

    def fail_on_the_receipt(
        src_root: Path,
        src_rel: Path,
        dest_root: Path,
        dest_rel: Path,
        *,
        mode: int = 0o644,
    ) -> None:
        if "turned-in" in str(dest_rel):
            raise StepFailed("disk full")
        real_copy(src_root, src_rel, dest_root, dest_rel, mode=mode)

    with monkeypatch.context() as patch:
        patch.setattr(ctx.runner, "copy_nofollow", fail_on_the_receipt)
        students.collect_assignment(ctx, "image-exercises.rkt")
    assert not (original.parent / "turned-in" / "image-exercises.rkt").exists()

    students.collect_assignment(ctx, "image-exercises.rkt")

    assert not _filed(ctx, "r1", "jsmith30-2.rkt").exists()
    assert (original.parent / "turned-in" / "image-exercises.rkt").read_text() == "mine"


def _submit_at(ctx: Context, username: str, rel: str, text: str) -> Path:
    path = ctx.settings.students.home_root / username / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_collect_from_a_path_files_by_name_and_mirrors_it_in_turned_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    original = _submit_at(ctx, "jsmith30", "labs/fall/programs.py", "print(1)")

    result = students.collect_assignment(ctx, "labs/fall/programs.py")

    home_root = ctx.settings.students.home_root
    filed = home_root / "sysadmin/assignments/programs/r1/jsmith30.py"
    assert filed.read_text() == "print(1)"
    receipt = home_root / "jsmith30/turned-in/labs/fall/programs.py"
    assert receipt.read_text() == "print(1)"
    assert original.read_text() == "print(1)"
    assert result.collected == ["r1/jsmith30.py"]
    assert result.missing == ["r4/aadams27"]


def test_collect_numbers_a_changed_file_inside_the_mirrored_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    _submit_at(ctx, "jsmith30", "labs/programs.py", "first")
    students.collect_assignment(ctx, "labs/programs.py")
    _submit_at(ctx, "jsmith30", "labs/programs.py", "second")

    result = students.collect_assignment(ctx, "labs/programs.py")

    assert result.collected == ["r1/jsmith30-2.py"]
    receipts = ctx.settings.students.home_root / "jsmith30/turned-in/labs"
    assert (receipts / "programs.py").read_text() == "first"
    assert (receipts / "programs-2.py").read_text() == "second"


def test_collect_will_not_walk_through_a_symlink_into_a_classmates_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Root following this files one student's work under another's name."""
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    theirs = _submit_at(ctx, "aadams27", "labs/programs.py", "aadams's work")
    home = ctx.settings.students.home_root / "jsmith30"
    (home / "labs").symlink_to(theirs.parent)

    result = students.collect_assignment(ctx, "labs/programs.py")

    assert [name for name, _ in result.skipped] == ["jsmith30"]
    assert result.collected == ["r4/aadams27.py"]
    assignment = ctx.settings.students.home_root / "sysadmin/assignments/programs"
    assert list((assignment / "r1").iterdir()) == []
    assert list((home / "turned-in").iterdir()) == []


def test_collect_will_not_write_through_a_symlink_inside_turned_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    elsewhere = tmp_path / "etc"
    elsewhere.mkdir()
    _submit_at(ctx, "jsmith30", "labs/programs.py", "print(1)")
    turned_in = ctx.settings.students.home_root / "jsmith30/turned-in"
    turned_in.mkdir()
    (turned_in / "labs").symlink_to(elsewhere)

    result = students.collect_assignment(ctx, "labs/programs.py")

    assert [name for name, _ in result.skipped] == ["jsmith30"]
    assert list(elsewhere.iterdir()) == []


def test_collect_with_groups_touches_only_those_sections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    _submit(ctx, "jsmith30", "mine")
    other = _submit(ctx, "aadams27", "theirs")

    result = students.collect_assignment(ctx, "image-exercises.rkt", groups=["r1"])

    assert result.collected == ["r1/jsmith30.rkt"]
    assert result.missing == []
    assert _filed(ctx, "r1").is_dir()
    assert not _filed(ctx, "r4").exists()
    assert not (other.parent / "turned-in").exists()


def test_collect_with_several_groups_covers_each_of_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)
    _submit(ctx, "jsmith30")
    _submit(ctx, "aadams27")

    result = students.collect_assignment(
        ctx, "image-exercises.rkt", groups=["r1", "r4"]
    )

    assert result.collected == ["r1/jsmith30.rkt", "r4/aadams27.rkt"]


def test_collect_refuses_a_group_that_does_not_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _ = _collect_ctx(tmp_path, monkeypatch)

    with pytest.raises(StepFailed, match="No such group: r9"):
        students.collect_assignment(ctx, "image-exercises.rkt", groups=["r1", "r9"])

    assert not (ctx.settings.students.home_root / "sysadmin" / "assignments").exists()
