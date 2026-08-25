"""Property-level three-way merge for DrRacket's racket-prefs.rktd file.

racket-prefs.rktd is a single Racket association list -- ``(key1 val1)
(key2 val2) ...`` -- and DrRacket rewrites the whole file on any single
preference change, the same whole-file-rewrite behavior that made a plain
text diff useless for xfconf (see steps/xfconf.py). Unlike xfconf's nested
property tree, every entry here is already flat and atomic, so no recursion
is needed: each ``(key value)`` entry is compared as a single unit, keyed by
its first token (a bare symbol, or a ``|...|``-quoted one for keys with
spaces, e.g. ``|plt:DrRacket 9.1-splash-max-width|``).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MergeResult:
    content: str
    applied: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)


def _unwrap(content: str) -> str:
    stripped = content.strip()
    if not (stripped.startswith("(") and stripped.endswith(")")):
        raise ValueError("not a racket-prefs.rktd association list")
    return stripped[1:-1]


def _entry_key(entry: str) -> str:
    inner = entry[1:].lstrip()
    if inner.startswith("|"):
        return inner[1 : inner.index("|", 1)]
    end = 0
    while end < len(inner) and not inner[end].isspace() and inner[end] not in "()[]":
        end += 1
    return inner[:end]


def _split_entries(body: str) -> dict[str, str]:
    """Split a list body into ``{key: "(key value...)"}``, in file order."""
    entries: dict[str, str] = {}
    i, n = 0, len(body)
    while i < n:
        while i < n and body[i].isspace():
            i += 1
        if i >= n:
            break
        start = i
        depth = 0
        in_string = False
        while i < n:
            ch = body[i]
            if in_string:
                if ch == "\\":
                    i += 2
                    continue
                if ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
                if depth == 0:
                    i += 1
                    break
            i += 1
        entry = body[start:i]
        entries[_entry_key(entry)] = entry
    return entries


def merge(
    base_content: str | None, theirs_content: str, ours_content: str
) -> MergeResult:
    base = _split_entries(_unwrap(base_content)) if base_content else {}
    theirs = _split_entries(_unwrap(theirs_content))
    ours = dict(_split_entries(_unwrap(ours_content)))

    applied: list[str] = []
    skipped: list[tuple[str, str]] = []

    for key, their_entry in theirs.items():
        our_entry = ours.get(key)
        if our_entry is None:
            ours[key] = their_entry
            applied.append(key)
            continue
        if our_entry == their_entry:
            continue
        base_entry = base.get(key)
        if base_entry is not None and our_entry == base_entry:
            ours[key] = their_entry
            applied.append(key)
        else:
            skipped.append((key, "customized" if base_entry is not None else "unknown"))

    body = "\n".join(f" {entry}" for entry in ours.values())
    return MergeResult(content=f"(\n{body}\n)\n", applied=applied, skipped=skipped)
