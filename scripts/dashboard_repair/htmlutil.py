"""Small HTML slicing helpers for the post-build dashboard repair."""

from __future__ import annotations

import html
import re


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def balanced_element_end(source: str, start: int) -> int:
    """End offset (exclusive) of the element that begins at `start`."""
    match = re.match(r"<(\w+)", source[start:])
    if not match:
        raise ValueError("balanced_element_end start is not a tag")
    tag = match.group(1)
    token = re.compile(rf"</?{tag}\b[^>]*>", re.IGNORECASE)
    depth = 0
    for found in token.finditer(source, start):
        piece = found.group(0)
        if piece.startswith("</"):
            depth -= 1
        elif piece.endswith("/>"):
            if depth == 0:
                return found.end()
            continue
        else:
            depth += 1
        if depth == 0:
            return found.end()
    raise ValueError(f"unbalanced <{tag}>")


def replace_element_containing(source: str, needle: str, replacement: str) -> str:
    index = source.find(needle)
    if index < 0:
        raise ValueError(f"missing anchor {needle}")
    start = source.rfind("<", 0, index)
    if start < 0:
        raise ValueError(f"missing tag before {needle}")
    end = balanced_element_end(source, start)
    return source[:start] + replacement + source[end:]


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) < 1:
        return source
    return source.replace(old, new, 1)
