"""Text-level edits to one section (apps:, apis:, jobs:, ...) of a hand-written product.yaml.

Round-tripping YAML through a parser loses or moves comments, so add/remove
only touch the lines of one component and leave the rest of the file as written.
Callers re-parse the result to verify it.
"""

from __future__ import annotations

import re


def _empty(section: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(section)}:\s*(\{{\s*\}})?\s*(#.*)?$")


def _block(lines: list[str], section: str) -> tuple[int, int] | None:
    """Index of the `<section>:` line and one past its last indented line."""
    start = next((i for i, line in enumerate(lines) if re.match(rf"^{re.escape(section)}:", line)), None)
    if start is None:
        return None
    last = start
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if line.strip() and not line.startswith(" "):
            break  # next top-level key, or a column-0 comment belonging to it
        if line.strip():
            last = i
    return start, last + 1


def _finish(lines: list[str], section: str) -> str:
    """Keep one blank line between the section and whatever follows."""
    block = _block(lines, section)
    if block and block[1] < len(lines) and lines[block[1]].strip():
        lines.insert(block[1], "")
    return "\n".join(lines).rstrip("\n") + "\n"


def _new_section_at(lines: list[str]) -> int:
    """Where a missing section goes: before `overrides:` (and the comments above it), else the end."""
    i = next((n for n, line in enumerate(lines) if re.match(r"^overrides:", line)), None)
    if i is None:
        # a commented-out overrides example counts too
        i = next((n for n, line in enumerate(lines) if re.match(r"^#\s*overrides:", line)), len(lines))
    while i > 0 and lines[i - 1].startswith("#"):
        i -= 1
    return i


def insert_component(text: str, section: str, name: str, snippet: str) -> str:
    """Append `name:` with the (unindented) snippet as its body to `section`."""
    lines = text.splitlines()
    body = [f"  {name}:"] + [f"    {line}" if line else "" for line in snippet.rstrip().splitlines()]
    block = _block(lines, section)
    if block is None:
        at = _new_section_at(lines)
        lines[at:at] = [f"{section}:", *body, ""]
        if at > 0 and lines[at - 1].strip():
            lines.insert(at, "")
    else:
        start, end = block
        m = _empty(section).match(lines[start])
        if m and (m.group(1) or end == start + 1):  # `apps: {}` or `apps:` with nothing under it
            # drop `{}` but keep the trailing `# description` exactly where it was
            lines[start] = re.sub(r"\{\s*\}", "", lines[start], count=1).rstrip() if m.group(1) else lines[start]
        elif end > start + 1:
            body = ["", *body]
        lines[end:end] = body
    return _finish(lines, section)


def delete_component(text: str, section: str, name: str) -> str | None:
    """Remove `name:` and its indented body from `section`. None if it isn't there."""
    lines = text.splitlines()
    block = _block(lines, section)
    if block is None:
        return None
    start, end = block
    i = next((j for j in range(start + 1, end) if re.match(rf"^  {re.escape(name)}:", lines[j])), None)
    if i is None:
        return None
    j = i + 1
    while j < end and (not lines[j].strip() or lines[j].startswith("   ")):
        j += 1
    while j > i + 1 and not lines[j - 1].strip():
        j -= 1  # keep the blank line that separates the next component
    del lines[i:j]
    while 0 < i < len(lines) and not lines[i - 1].strip() and not lines[i].strip():
        del lines[i]
    while start + 1 < len(lines) and not lines[start + 1].strip():
        del lines[start + 1]
    start, end = _block(lines, section) or (start, start + 1)  # still there: we only removed lines inside it
    if not any(line.strip() and not line.strip().startswith("#") for line in lines[start + 1 : end]):
        rest = lines[start][len(section) + 1 :]  # whatever followed `apps:` (spaces + comment)
        tail = rest[1:] if rest[1:].startswith("  ") else "  " + rest.strip()  # >= 2 spaces before `#`
        lines[start] = f"{section}: {{}}" + (tail if rest.strip() else "")
    return _finish(lines, section)
