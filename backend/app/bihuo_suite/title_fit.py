"""Fit opening title/subtitle to each installed suite's reading width.

Installed suites reject a title wider than their design (bihuo-09
``Shorter Orange title/support required`` at compile, bihuo-10 ``Title
requires meaningful wrapping`` per rendered frame). The text comes from a
paid plan, so the host fits it before compiling: keep the longest whole-word
form (trailing punctuation removed, leading words such as 「这款」 dropped
before trailing ones) that fits the measured width. Suites already shrink
their font down to their own minimum; the limits below use that minimum.
Frozen bundles are not changed.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)

# bundle -> field -> (font roles in preference order, font px, max advance px).
# Derived from each bundle's own width check, with the smallest size it
# shrinks to and a margin for stroke/slant/rotation padding.
RULES: dict[str, dict[str, tuple[tuple[str, ...], int, float]]] = {
    "tpl_27d83f66e3_c6af1d0": {  # bihuo-09 runtime.py:25
        "title": (("title", "bold"), 110, 925),
        "subtitle": (("title", "bold"), 28, 860),
    },
    "fk-1017-share-paper": {  # bihuo-10 primitives.py:83 (ink + slant + 2deg)
        "title": (("title", "main", "caption_bold"), 100, 730),
    },
    "tpl_81019325e3_c6d9175": {"title": (("title",), 124, 980)},
    "fk-1112-qingbai-bilingual": {
        "title": (("title", "bold"), 48, 950),
        "subtitle": (("title", "bold"), 24, 950),
    },
    "fk-1021-news-vibrant": {
        "title": (("main", "body"), 32, 480),
        "subtitle": (("main", "body"), 24, 960),
    },
    "tpl_b8230dc09b_cd0cc1a": {"title": (("main", "body"), 40, 980)},
    "tpl_6c9775d0ad": {
        "title": (("main", "body"), 28, 620),
        "subtitle": (("main", "body"), 28, 620),
    },
    "tpl_da5635d242_cdbce6c": {"title": (("title",), 110, 940)},
    "tpl_ee351f0cce_c74832a": {
        "title": (("title", "bold"), 100, 995),
        "subtitle": (("title", "bold"), 24, 940),
    },
    "tpl_27d83f66e3": {"title": (("main", "body"), 40, 900)},
    "tpl_dc421f64d0": {"title": (("title",), 54, 980)},
}
MARGIN = 0.97
# Width errors raised by installed suites; any other error is not ours to fix.
TITLE_ERRORS = (
    "title/support",
    "title requires meaningful wrapping",
    "shorter multimedia title",
    "title exceeds",
    "opening title exceeds",
    "opening topic needs shorter",
    "shorter qingci title",
    "title needs shorter wording",
    "paper title exceeds",
)
SUPPORT_ERRORS = ("support exceeds", "shorter support required")
PUNCTUATION = "，。、；：！？,.;:!?…·—-~（）()《》「」\"' "


@lru_cache(maxsize=32)
def _font(path: str, size: int) -> Any:
    from PIL import ImageFont

    return ImageFont.truetype(path, size)


def _width(text: str, path: str, size: int) -> float:
    return float(_font(path, size).getlength(text))


def word_forms(text: str) -> list[str]:
    """Whole-word shortenings, best first; never cuts inside a jieba word.

    Dropping leading words keeps the head noun (「白色头戴耳机」 from
    「这款白色头戴耳机，」), so it ranks before dropping trailing words at the
    same length. A form never starts or ends on a stray one-character word
    such as 「款」.
    """
    from ..video_editing_captioning import text_boundaries, tokenizer

    clean = text.strip().rstrip(PUNCTUATION).strip()
    if not clean:
        return []
    safe, _ = text_boundaries(clean)
    words = [
        (start, end)
        for _, start, end in tokenizer().tokenize(clean, HMM=False)
        if clean[start:end].strip(PUNCTUATION)
    ]

    def solid(start: int, end: int) -> bool:
        piece = clean[start:end]
        return len(piece) >= 2 or bool(re.fullmatch(r"[A-Za-z0-9]+", piece))

    forms: dict[str, tuple[int, int]] = {clean: (len(clean), 2)}
    for start, end in words[1:]:  # Drop leading words.
        if start in safe and solid(start, end):
            form = clean[start:].strip(PUNCTUATION)
            forms.setdefault(form, (len(form), 1))
    for start, end in words[:-1]:  # Drop trailing words.
        if end in safe and solid(start, end):
            form = clean[:end].strip(PUNCTUATION)
            forms.setdefault(form, (len(form), 0))
    return sorted(
        (k for k in forms if re.search(r"[\w\u3400-\u9fff]", k)),
        key=lambda k: (-len(k), -forms[k][1]),
    )


def fit_text(text: str, fits: Callable[[str], bool]) -> str:
    if not text or fits(text):
        return text
    return next((form for form in word_forms(text) if fits(form)), "")


def _fits(path: str, size: int, limit: float) -> Callable[[str], bool]:
    return lambda text: _width(text, path, size) <= limit * MARGIN


def fit_inputs(
    bundle: str, resolved: dict, options: dict | None, fonts: dict[str, str]
) -> tuple[dict, dict | None, list[dict]]:
    rules = RULES.get(bundle, {})
    resolved = dict(resolved)
    options = dict(options) if options is not None else None
    changes = []
    for field, (roles, size, limit) in rules.items():
        path = next((fonts[r] for r in roles if fonts.get(r)), None)
        if path is None:
            continue
        for target in (options, resolved):
            if target is None or not isinstance(target.get(field), str):
                continue
            before = target[field]
            after = fit_text(before.strip(), _fits(path, size, limit))
            if after != before.strip():
                target[field] = after
                changes.append({"field": field, "from": before, "to": after})
    return resolved, options, changes


def _shorten(value: Any) -> str:
    text = value.strip() if isinstance(value, str) else ""
    forms = [f for f in word_forms(text) if len(f) < len(text.rstrip(PUNCTUATION))]
    return forms[0] if forms else ""


def fitted_compiler(
    compiler: Callable[..., dict], bundle_of: Callable[[str], str]
) -> Callable[..., dict]:
    """Wrap a suite compiler: pre-fit by measurement, then shorten on reject."""

    def compile_fitted(template_id: str, resolved: dict, **kwargs: Any) -> dict:
        from .registry import fonts

        bundle = bundle_of(template_id)
        options = kwargs.get("creative_options")
        resolved, options, changes = fit_inputs(
            bundle, resolved, options, fonts(template_id)
        )
        for _ in range(8):
            try:
                result = compiler(
                    template_id, resolved, **{**kwargs, "creative_options": options}
                )
                break
            except ValueError as error:
                message = str(error).lower()
                field = (
                    "subtitle"
                    if any(m in message for m in SUPPORT_ERRORS)
                    else "title"
                    if any(m in message for m in TITLE_ERRORS)
                    else None
                )
                if field is None or not (
                    resolved.get(field) or (options or {}).get(field)
                ):
                    raise
                if field == "title" and "title/support" in message:
                    # Combined check: shorten whichever is visually longer.
                    title = (options or {}).get("title") or resolved.get("title", "")
                    support = (options or {}).get("subtitle") or resolved.get(
                        "subtitle", ""
                    )
                    field = "title" if len(title) * 4 >= len(support) else "subtitle"
                current = (options or {}).get(field) or resolved.get(field, "")
                shorter = _shorten(current)
                changes.append({"field": field, "from": current, "to": shorter})
                resolved = {**resolved, field: shorter}
                if options is not None and options.get(field):
                    options = {**options, field: shorter}
        else:
            raise ValueError("Suite title could not be fitted to its width")
        if changes:
            logger.info(
                "suite title fitted",
                extra={"template_id": template_id, "changes": changes},
            )
        return result

    return compile_fitted
