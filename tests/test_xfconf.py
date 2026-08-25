"""Property-level three-way merge for xfconf-perchannel XML."""

from __future__ import annotations

from ltsp_setup.steps import xfconf


def _channel(*properties: str) -> str:
    return f'<channel name="test" version="1.0">{"".join(properties)}</channel>'


def test_adds_a_property_missing_from_ours() -> None:
    theirs = _channel('<property name="A" type="string" value="a1"/>')
    ours = _channel()

    result = xfconf.merge(None, theirs, ours)

    assert result.applied == ["A"]
    assert result.skipped == []
    assert 'value="a1"' in result.xml


def test_updates_a_property_unchanged_since_base() -> None:
    base = _channel('<property name="A" type="string" value="old"/>')
    theirs = _channel('<property name="A" type="string" value="new"/>')
    ours = _channel('<property name="A" type="string" value="old"/>')

    result = xfconf.merge(base, theirs, ours)

    assert result.applied == ["A"]
    assert result.skipped == []
    assert 'value="new"' in result.xml


def test_skips_a_property_the_student_customized() -> None:
    base = _channel('<property name="A" type="string" value="old"/>')
    theirs = _channel('<property name="A" type="string" value="new"/>')
    ours = _channel('<property name="A" type="string" value="customized"/>')

    result = xfconf.merge(base, theirs, ours)

    assert result.applied == []
    assert result.skipped == [("A", "customized")]
    assert 'value="customized"' in result.xml
    assert 'value="new"' not in result.xml


def test_skips_a_property_with_no_recorded_base() -> None:
    theirs = _channel('<property name="A" type="string" value="new"/>')
    ours = _channel('<property name="A" type="string" value="something-else"/>')

    result = xfconf.merge(None, theirs, ours)

    assert result.applied == []
    assert result.skipped == [("A", "unknown")]
    assert 'value="something-else"' in result.xml


def test_no_op_when_already_matching_the_current_template() -> None:
    theirs = _channel('<property name="A" type="string" value="new"/>')
    ours = _channel('<property name="A" type="string" value="new"/>')

    result = xfconf.merge(None, theirs, ours)

    assert result.applied == []
    assert result.skipped == []


def test_recurses_into_a_container_updating_only_the_untouched_sibling() -> None:
    def group(b: str, c: str) -> str:
        return _channel(
            '<property name="Group" type="empty">'
            f'<property name="B" type="string" value="{b}"/>'
            f'<property name="C" type="string" value="{c}"/>'
            "</property>"
        )

    base = group("b1", "c1")
    theirs = group("b2", "c1")  # only B changed in the new template
    ours = group("b1", "c-customized")  # student changed C, never touched B

    result = xfconf.merge(base, theirs, ours)

    assert result.applied == ["Group/B"]
    assert result.skipped == [("Group/C", "customized")]
    assert 'value="b2"' in result.xml
    assert 'value="c-customized"' in result.xml


def test_array_is_atomic_and_a_reordered_one_is_left_alone() -> None:
    def arr(values: list[int]) -> str:
        items = "".join(f'<value type="int" value="{v}"/>' for v in values)
        return _channel(f'<property name="Arr" type="array">{items}</property>')

    base = arr([1, 2])
    theirs = arr([1, 2, 3])
    ours = arr([2, 1])  # student reordered it

    result = xfconf.merge(base, theirs, ours)

    assert result.applied == []
    assert result.skipped == [("Arr", "customized")]


def test_array_unchanged_since_base_is_updated_wholesale() -> None:
    def arr(values: list[int]) -> str:
        items = "".join(f'<value type="int" value="{v}"/>' for v in values)
        return _channel(f'<property name="Arr" type="array">{items}</property>')

    base = arr([1, 2])
    theirs = arr([1, 2, 3])
    ours = arr([1, 2])  # untouched

    result = xfconf.merge(base, theirs, ours)

    assert result.applied == ["Arr"]
    assert 'value="3"' in result.xml


def test_a_property_dropped_from_the_template_is_left_in_place() -> None:
    base = _channel('<property name="A" type="string" value="a1"/>')
    theirs = _channel()  # A no longer in the template
    ours = _channel('<property name="A" type="string" value="a1"/>')

    result = xfconf.merge(base, theirs, ours)

    assert result.applied == []
    assert result.skipped == []
    assert 'name="A"' in result.xml
