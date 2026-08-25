"""Property-level three-way merge for racket-prefs.rktd."""

from __future__ import annotations

from ltsp_setup.steps import racket_prefs


def _prefs(*entries: str) -> str:
    body = "\n".join(f" {e}" for e in entries)
    return f"(\n{body}\n)\n"


def test_adds_an_entry_missing_from_ours() -> None:
    theirs = _prefs("(a 1)")
    ours = _prefs()

    result = racket_prefs.merge(None, theirs, ours)

    assert result.applied == ["a"]
    assert result.skipped == []
    assert "(a 1)" in result.content


def test_updates_an_entry_unchanged_since_base() -> None:
    base = _prefs("(a old)")
    theirs = _prefs("(a new)")
    ours = _prefs("(a old)")

    result = racket_prefs.merge(base, theirs, ours)

    assert result.applied == ["a"]
    assert result.skipped == []
    assert "(a new)" in result.content


def test_skips_an_entry_the_student_customized() -> None:
    base = _prefs("(a old)")
    theirs = _prefs("(a new)")
    ours = _prefs("(a customized)")

    result = racket_prefs.merge(base, theirs, ours)

    assert result.applied == []
    assert result.skipped == [("a", "customized")]
    assert "(a customized)" in result.content
    assert "(a new)" not in result.content


def test_skips_an_entry_with_no_recorded_base() -> None:
    theirs = _prefs("(a new)")
    ours = _prefs("(a something-else)")

    result = racket_prefs.merge(None, theirs, ours)

    assert result.applied == []
    assert result.skipped == [("a", "unknown")]
    assert "(a something-else)" in result.content


def test_no_op_when_already_matching_the_current_template() -> None:
    theirs = _prefs("(a new)")
    ours = _prefs("(a new)")

    result = racket_prefs.merge(None, theirs, ours)

    assert result.applied == []
    assert result.skipped == []


def test_an_entry_dropped_from_the_template_is_left_in_place() -> None:
    base = _prefs("(a 1)")
    theirs = _prefs()  # a no longer in the template
    ours = _prefs("(a 1)")

    result = racket_prefs.merge(base, theirs, ours)

    assert result.applied == []
    assert result.skipped == []
    assert "(a 1)" in result.content


def test_bar_quoted_keys_with_spaces_are_matched_correctly() -> None:
    base = _prefs("(|plt:DrRacket 9.1-splash-max-width| 1000)")
    theirs = _prefs("(|plt:DrRacket 9.1-splash-max-width| 1052)")
    ours = _prefs("(|plt:DrRacket 9.1-splash-max-width| 1000)")

    result = racket_prefs.merge(base, theirs, ours)

    assert result.applied == ["plt:DrRacket 9.1-splash-max-width"]
    assert "1052" in result.content


def test_values_containing_parens_and_strings_stay_intact() -> None:
    entry = '(plt:framework-pref:drracket:most-recent-lang-line "#lang htdp/bsl\\n")'
    theirs = _prefs(entry)
    ours = _prefs()

    result = racket_prefs.merge(None, theirs, ours)

    assert result.applied == ["plt:framework-pref:drracket:most-recent-lang-line"]
    assert entry in result.content


def test_multiple_entries_are_each_evaluated_independently() -> None:
    base = _prefs("(a 1)", "(b 1)")
    theirs = _prefs("(a 2)", "(b 2)")
    ours = _prefs("(a 1)", "(b customized)")  # a untouched, b customized

    result = racket_prefs.merge(base, theirs, ours)

    assert result.applied == ["a"]
    assert result.skipped == [("b", "customized")]
    assert "(a 2)" in result.content
    assert "(b customized)" in result.content
