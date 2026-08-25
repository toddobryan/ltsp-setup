"""Property-level three-way merge for xfconf-perchannel XML files.

xfconfd rewrites a channel's ENTIRE file on any single property change --
reordering properties, dropping comments, minor reformatting (confirmed by
testing a real session, 2026-08-19/20; see steps/common.py). That makes a
plain line-based diff/patch unreliable: an unrelated change elsewhere in
the file breaks the surrounding context a text patch depends on.

This compares by property NAME and VALUE instead of by line, recursing
through named-property containers (xfconf's ``type="empty"`` grouping
properties, and named ``plugin-N``-style groups) and treating leaves and
arrays (unnamed ``<value>`` children, e.g. panel-1's ``plugin-ids``) as
atomic units. That also means a hand-reordered array is correctly treated
as "customized, leave alone" rather than silently patched -- list
membership/order isn't independently addressable the way named properties
are, so patching one entry out of an array a student rearranged would
produce a state they never asked for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

XML_DECLARATION = '<?xml version="1.0" encoding="UTF-8"?>\n\n'


@dataclass
class MergeResult:
    """The outcome of merging one template's current version into one
    student's file.

    ``xml`` is the full resulting file content, whether or not anything
    changed. ``applied`` and ``skipped`` are property paths ("/"-joined
    names from the channel root), skipped entries paired with why:
    "customized" (differs from the version we last shipped) or "unknown"
    (exists, but we have no record of ever shipping it).
    """

    xml: str
    applied: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _is_container(elem: ET.Element) -> bool:
    """True if every child is a named property -- i.e. this is a grouping
    node to recurse into, not a leaf value or an array to treat atomically.
    """
    children = list(elem)
    return bool(children) and all("name" in child.attrib for child in children)


def _canonical(elem: ET.Element | None) -> object:
    """A comparable, order-of-attributes-independent snapshot of a subtree."""
    if elem is None:
        return None
    return (
        elem.tag,
        tuple(sorted(elem.attrib.items())),
        tuple(_canonical(child) for child in elem),
    )


def _copy(elem: ET.Element) -> ET.Element:
    return ET.fromstring(ET.tostring(elem))


def _named_children(elem: ET.Element | None) -> dict[str, ET.Element]:
    if elem is None:
        return {}
    return {c.attrib["name"]: c for c in elem if "name" in c.attrib}


def _merge_children(
    base: ET.Element | None,
    theirs: ET.Element | None,
    ours: ET.Element,
    path: str,
    result: MergeResult,
) -> None:
    base_children = _named_children(base)
    theirs_children = _named_children(theirs)
    ours_children = _named_children(ours)

    for name in sorted(theirs_children.keys() | ours_children.keys()):
        b = base_children.get(name)
        t = theirs_children.get(name)
        o = ours_children.get(name)
        child_path = f"{path}/{name}" if path else name

        if o is None:
            if t is not None:
                ours.append(_copy(t))
                result.applied.append(child_path)
            continue

        if _canonical(o) == _canonical(t):
            continue  # already matches the current template, nothing to do

        unchanged_since_base = b is not None and _canonical(o) == _canonical(b)
        # A container worth looking inside even when it's drifted from
        # base -- a student changing one sub-property shouldn't block an
        # unrelated new sub-property from being added.
        can_recurse = _is_container(o) and (t is None or _is_container(t))

        if can_recurse:
            _merge_children(b, t, o, child_path, result)
        elif unchanged_since_base:
            if t is not None:
                ours.remove(o)
                ours.append(_copy(t))
                result.applied.append(child_path)
            # else: property was dropped from the template. Leaving it in
            # place rather than deleting something a student might use.
        else:
            result.skipped.append(
                (child_path, "customized" if b is not None else "unknown")
            )


def merge(base_xml: str | None, theirs_xml: str, ours_xml: str) -> MergeResult:
    """Merge ``theirs_xml`` (the template's current content) into
    ``ours_xml`` (a student's file), touching only properties that are
    missing or unchanged since ``base_xml`` (the template as it stood last
    time this ran -- None the very first time, before any baseline has
    been recorded).
    """
    base_root = ET.fromstring(base_xml) if base_xml else None
    theirs_root = ET.fromstring(theirs_xml)
    ours_root = _copy(ET.fromstring(ours_xml))

    result = MergeResult(xml="")
    _merge_children(base_root, theirs_root, ours_root, "", result)
    result.xml = XML_DECLARATION + ET.tostring(ours_root, encoding="unicode") + "\n"
    return result
