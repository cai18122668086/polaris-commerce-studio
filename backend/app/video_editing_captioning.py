"""Measured caption pages with lexical, punctuation and number/unit boundaries.

The tokenizer proposes text boundaries only. It never supplies timestamps,
changes spoken text, splits an ASR token, or certifies names/product facts.
"""

import importlib.metadata
import math
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from .motion_library import atomic_json, sha256
from .video_editing_contracts import Transcript, TranscriptToken

POLICY = "measured-lexical-clauses/1"
IMPLEMENTATION_SHA256 = sha256(Path(__file__))
MAX_CHARS = 20
DICTIONARY_SHA256 = "7197c3211ddd98962b036cdf40324d1ea2bfaa12bd028e68faa70111a88e12a8"
NUMBER = (
    r"(?:\d{1,3}(?:[,，]\d{3})+|\d+|"
    r"[零〇一二两三四五六七八九十百千万亿兆壹贰叁肆伍陆柒捌玖拾佰仟]+)"
    r"(?:[.．点][\d零〇一二三四五六七八九]+)?(?:[几多余来])?"
)
UNIT = (
    r"(?:千克|公斤|毫克|毫升|厘米|毫米|平方米|立方米|kg|mg|ml|mL|cm|mm|"
    r"克|斤|升|米|吨|瓶|袋|包|盒|支|件|个|片|倍|年|月|天|小时|分钟|秒|%|％)"
)
NUMBER_UNIT = re.compile(
    rf"[+＋−-]?{NUMBER}(?:(?:块钱|元钱|块|元|角|毛|分)(?:{NUMBER}(?:角|毛|分)?)?|{UNIT})?"
)
ASCII_WORD = re.compile(r"[A-Za-z0-9]+(?:[./:%％+'-][A-Za-z0-9]+)*(?:类|级|号|型)?")
CLAUSE_END = re.compile(r"[，,。.!！?？;；:：][\"'”’」』）)\]]*$")
LEADING_PUNCTUATION = set("，,。.!！?？;；:：、”’」』）)]%％")


class CaptionFailure(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@lru_cache(maxsize=1)
def tokenizer() -> Any:
    try:
        import jieba
    except ImportError:
        raise CaptionFailure("EDITING_CAPTION_DICTIONARY_MISSING") from None

    dictionary = Path(jieba.__file__).parent / "dict.txt"
    if (
        importlib.metadata.version("jieba") != "0.42.1"
        or sha256(dictionary) != DICTIONARY_SHA256
    ):
        raise CaptionFailure("EDITING_CAPTION_DICTIONARY_CHANGED")
    # A dedicated cache avoids both the global jieba cache and this machine's
    # nearly full D: TEMP. Linux workers use their ordinary temporary volume.
    parent = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
    cache = parent / "TengliEditing" / "text-cache"
    cache.mkdir(parents=True, exist_ok=True)
    engine = jieba.Tokenizer(dictionary=str(dictionary))
    engine.tmp_dir = str(cache)
    engine.cache_file = f"jieba-{DICTIONARY_SHA256[:16]}.cache"
    engine.initialize()
    return engine


def segmentation_metadata() -> dict[str, Any]:
    tokenizer()  # Verify the exact dictionary used by this process first.
    return {
        "policy": POLICY,
        "implementation_sha256": IMPLEMENTATION_SHA256,
        "max_characters": MAX_CHARS,
        "tokenizer": "jieba/0.42.1; HMM=False",
        "dictionary_sha256": DICTIONARY_SHA256,
        "spoken_tokens_changed": False,
        "display_whitespace": "outer whitespace trimmed per page",
        "timing_basis": "actual source token bounds only",
        "semantic_review": "unreviewed",
        "visual_review": "unreviewed",
    }


def _split_clause(
    tokens: list[TranscriptToken],
    safe: set[int],
    preferred: set[int],
    offsets: list[int],
    begin: int,
    end: int,
) -> list[list[TranscriptToken]]:
    """Choose balanced pages among actual-token and lexical boundaries."""
    if offsets[end] - offsets[begin] <= MAX_CHARS:
        return [tokens[begin:end]]
    target = (offsets[end] - offsets[begin]) / math.ceil(
        (offsets[end] - offsets[begin]) / MAX_CHARS
    )
    best: dict[int, tuple[float, int]] = {begin: (0, begin)}
    for stop in range(begin + 1, end + 1):
        if stop != end and stop not in safe:
            continue
        choices = []
        for start in range(stop - 1, begin - 1, -1):
            length = offsets[stop] - offsets[start]
            if length > MAX_CHARS:
                break
            if length <= 0 or start not in best:
                continue
            cost = best[start][0]
            # Fewer pages first, then avoid a long page plus a dangling suffix.
            choices.append(
                (
                    cost
                    + 1000
                    + (length - target) ** 2
                    + (200 if length < 4 else 0)
                    + (40 if stop != end and stop not in preferred else 0),
                    start,
                )
            )
        if choices:
            best[stop] = min(choices)
    if end not in best:
        raise CaptionFailure("EDITING_CAPTION_CAPACITY_REVIEW_REQUIRED")
    pages = []
    cursor = end
    while cursor > begin:
        start = best[cursor][1]
        pages.append(tokens[start:cursor])
        cursor = start
    return list(reversed(pages))


def text_boundaries(text: str) -> tuple[set[int], set[int]]:
    lexical = {end for _, _, end in tokenizer().tokenize(text, HMM=False)}
    interiors = {
        i
        for rule in (NUMBER_UNIT, ASCII_WORD)
        for match in rule.finditer(text)
        for i in range(match.start() + 1, match.end())
    }
    safe = {
        i for i in lexical - interiors if text[i : i + 1] not in LEADING_PUNCTUATION
    }
    preferred = {
        i for i in safe if CLAUSE_END.search(text[:i]) or text[:i].endswith("、")
    }
    return safe, preferred


def measured_caption_rows(transcript: Transcript) -> list[dict[str, Any]]:
    tokens = transcript.tokens
    if not tokens:
        raise CaptionFailure("EDITING_CAPTION_TEXT_REVIEW_REQUIRED")
    text = "".join(t.text for t in tokens)
    if not re.search(r"\w", text):
        raise CaptionFailure("EDITING_CAPTION_TEXT_REVIEW_REQUIRED")
    offsets = [0]
    for token in tokens:
        offsets.append(offsets[-1] + len(token.text))
    lexical, preferred_chars = text_boundaries(text)
    safe = {i for i in range(1, len(tokens)) if offsets[i] in lexical}
    preferred = {i for i in safe if offsets[i] in preferred_chars}
    rows = []
    begin = 0
    has_content = False
    for stop in range(1, len(tokens) + 1):
        actual_pause = (
            stop < len(tokens) and tokens[stop].start_ms - tokens[stop - 1].end_ms > 600
        )
        punctuation = bool(CLAUSE_END.search(tokens[stop - 1].text))
        has_content = has_content or bool(re.search(r"\w", tokens[stop - 1].text))
        if stop == len(tokens) or (
            stop in safe and has_content and (punctuation or actual_pause)
        ):
            rows.extend(_split_clause(tokens, safe, preferred, offsets, begin, stop))
            begin = stop
            has_content = False
    result: list[dict[str, Any]] = []
    for i, row in enumerate(rows):
        end_ms = row[-1].end_ms
        if i + 1 < len(rows):
            end_ms = min(end_ms, rows[i + 1][0].start_ms)
        if end_ms <= row[0].start_ms:
            raise CaptionFailure("EDITING_CAPTION_TIMING_INVALID")
        result.append(
            {
                "text": "".join(t.text for t in row).strip(),
                "start_seconds": row[0].start_ms / 1000,
                "end_seconds": end_ms / 1000,
                "token_ids": [t.id for t in row],
            }
        )
    if [tid for row in result for tid in row["token_ids"]] != [t.id for t in tokens]:
        raise CaptionFailure("EDITING_CAPTION_COVERAGE_CHANGED")
    return result


def write_caption_receipt(
    root: Path, transcript: Transcript, captions: list[dict], displayed: bool
) -> None:
    atomic_json(
        root / "caption-segmentation.json",
        {
            **segmentation_metadata(),
            "source_sha256": transcript.source_sha256,
            "transcript_sha256": sha256(root / "transcript.json"),
            "caption_anchors_sha256": sha256(root / "caption-anchors.json"),
            "token_count": len(transcript.tokens),
            "caption_count": len(captions),
            "main_captions_enabled": displayed,
        },
    )
