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
