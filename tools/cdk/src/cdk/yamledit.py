"""Text-level edits to the `components:` block of a hand-written product.yaml.

Round-tripping YAML through a parser loses or moves comments, so add/remove
only touch the lines of one component and leave the rest of the file as written.
Callers re-parse the result to verify it.
"""

from __future__ import annotations

import re

_EMPTY_COMPONENTS = re.compile(r"^components:\s*\{\s*\}\s*(#.*)?$")


def _block(lines: list[str]) -> tuple[int, int] | None:
    """Index of the `components:` line and one past its last indented line."""
    start = next((i for i, line in enumerate(lines) if re.match(r"^components:", line)), None)
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


def _finish(lines: list[str]) -> str:
    """Keep one blank line between the components block and whatever follows."""
    block = _block(lines)
    if block and block[1] < len(lines) and lines[block[1]].strip():
        lines.insert(block[1], "")
    return "\n".join(lines).rstrip("\n") + "\n"


def insert_component(text: str, name: str, snippet: str) -> str:
    """Append `name:` with the (unindented) snippet as its body to the components block."""
    lines = text.splitlines()
    body = [f"  {name}:"] + [f"    {line}" if line else "" for line in snippet.rstrip().splitlines()]
    block = _block(lines)
    if block is None:
        lines += ["", "components:", *body]
    else:
        start, end = block
        if _EMPTY_COMPONENTS.match(lines[start]):
            lines[start] = "components:"
        elif end > start + 1:
            body = ["", *body]
        lines[end:end] = body
    return _finish(lines)


def delete_component(text: str, name: str) -> str | None:
    """Remove `name:` and its indented body. None if it isn't in the components block."""
    lines = text.splitlines()
    block = _block(lines)
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
    start, end = _block(lines) or (start, start + 1)  # the block still exists: we only removed lines inside it
    if not any(line.strip() and not line.strip().startswith("#") for line in lines[start + 1 : end]):
        lines[start] = "components: {}"
    return _finish(lines)
