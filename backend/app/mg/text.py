"""Verbatim-text helpers shared by MG validation and supplement planning."""

from __future__ import annotations

import re

_PUNCT = re.compile(r"[\s，。！？!?；;：:、,.“”\"'‘’（）()《》【】\[\]…—\-·~～]+")


def plain(text: str) -> str:
    return _PUNCT.sub("", text or "")


def is_quote(fragment: str, source: str) -> bool:
    """A card text must be verbatim speech (punctuation/space ignored)."""
    fragment = plain(fragment)
    return bool(fragment) and fragment in plain(source)
