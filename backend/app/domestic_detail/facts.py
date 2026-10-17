"""Fact-neutral helpers for domestic detail identity and evidence tokens."""
from __future__ import annotations


def text_tokens(value: object, *, field: str) -> list[str]:
    """Keep a scalar phrase intact; reject values that cannot carry text facts."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        result = []
        for index, item in enumerate(value):
            if not isinstance(item, str):
                raise ValueError(f"{field}/{index} must be a text token")
            if item.strip():
                result.append(item.strip())
        return result
    raise ValueError(f"{field} must be a text token or a list of text tokens")
