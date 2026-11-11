"""Ground original HY-A7 pie sectors in a corrected spoken total and breakdown."""

import re
from unicodedata import normalize

from .video_editing_contracts import SemanticBeat, Transcript
from .video_editing_word_bindings import emphasis_text

FLOW_CHART_TEMPLATE_ID = "hypit-flow-chart-v1"
FLOW_CHART_DESIGN = "tengli-" + FLOW_CHART_TEMPLATE_ID
FLOW_CHART_CAPTION_BASELINE = 150
_DIGITS = dict(zip("一二两三四五六七八九", (1, 2, 2, 3, 4, 5, 6, 7, 8, 9), strict=True))
_AMOUNT = re.compile(r"([0-9一二两三四五六七八九零十百]+)(组|项|条|个|人|件|次)")
_SECTOR = re.compile(r"(?<=\):)[0-9]+(?:\.[0-9]+)?(?=@)")


def confirmed_chart_words(transcript: Transcript) -> bool:
    return transcript.text_status == "user_corrected" and bool(
        transcript.text_revision_id
    )


def _integer(text: str) -> int:
    if re.fullmatch(r"[1-9][0-9]{0,2}", text):
        return int(text)
    if text in _DIGITS:
        return _DIGITS[text]
    if tens := re.fullmatch(r"([一二三四五六七八九]?)十([一二三四五六七八九]?)", text):
        return _DIGITS.get(tens[1], 1) * 10 + _DIGITS.get(tens[2], 0)
    if hundreds := re.fullmatch(r"([一二两三四五六七八九])百(.*)", text):
        base = _DIGITS[hundreds[1]] * 100
        rest = hundreds[2]
        if not rest:
            return base
        if rest.startswith("零") and rest[1:] in _DIGITS:
            return base + _DIGITS[rest[1:]]
        if re.fullmatch(r"[一二三四五六七八九]十[一二三四五六七八九]?", rest):
            return base + _integer(rest)
    raise ValueError("Chart counts must be unambiguous positive integers from 1 to 999")


def _amount(text: str) -> tuple[int, str]:
    match = _AMOUNT.fullmatch(normalize("NFKC", text))
    if not match:
        raise ValueError("Chart requires a spoken integer and its unit")
    return _integer(match[1]), match[2]


def compile_flow_chart(
    beat: SemanticBeat,
    native: dict,
    transcript: Transcript,
    label_paths: tuple[str, ...],
) -> dict:
    if (
        not confirmed_chart_words(transcript)
        or beat.relation != "parallel"
        or len(beat.relation_items) != len(label_paths)
    ):
        raise ValueError("Flow chart needs three parts from the corrected transcript")
    tokens = transcript.tokens
    positions = {token.id: i for i, token in enumerate(tokens)}
    labels = {row["path"]: row for row in native["text"]}

    def spoken(begin: int, end: int) -> str:
        return emphasis_text(
            "".join(t.text for t in tokens[begin:end]), "omit_sentence_punctuation"
        )

    start = positions[beat.first_token_id]
    next_part = positions[beat.relation_items[0].first_token_id]
    end = positions[beat.last_token_id]
    total_text = re.fullmatch(r"(?:合计|总计|一共|共)(.+)", spoken(start, next_part))
    if not total_text:
        raise ValueError("Flow chart must start at its spoken total")
    total, unit = _amount(total_text[1])
    parts = []
    for item, path in zip(beat.relation_items, label_paths, strict=True):
        label = labels[path]
        begin, finish = positions[item.first_token_id], positions[item.last_token_id]
        label_end = begin + len(label["token_ids"])
        if (
            item.asset_ids
            or item.native_media_paths
            or item.native_text_paths != [path]
            or not start < begin == next_part < label_end <= finish <= end
            or label["token_ids"] != [t.id for t in tokens[begin:label_end]]
        ):
            raise ValueError(
                "Bind each chart label and count to its own consecutive spoken part"
            )
        count, part_unit = _amount(spoken(label_end, finish + 1))
        if part_unit != unit:
            raise ValueError("Chart parts must use the same unit as their total")
        parts.append(
            {
                "label": label["text"],
                "count": count,
                "count_token_ids": [t.id for t in tokens[label_end : finish + 1]],
            }
        )
        next_part = finish + 1
    if (
        len({part["label"] for part in parts}) != 3
        or sum(part["count"] for part in parts) != total
    ):
        raise ValueError(
            "Chart needs distinct labels and parts that sum to the spoken total"
        )
    return {
        "total": total,
        "unit": unit,
        "parts": parts,
        "total_token_ids": [
            t.id
            for t in tokens[start : positions[beat.relation_items[0].first_token_id]]
        ],
        "transcript_revision_id": transcript.text_revision_id,
    }


def patch_flow_slices(scene: str, chart: dict) -> str:
    match = re.search(r'<pie:View id="b1"\s+[^>]*?\bslices="([^"]+)"', scene)
    counts = [part["count"] for part in chart["parts"]]
    if (
        not match
        or len(counts) != 3
        or any(type(count) is not int or not 1 <= count <= 999 for count in counts)
        or sum(counts) != chart["total"]
    ):
        raise ValueError("Original pie slices or their compiled data changed")
    # The original renderer normalizes these weights and keeps the native growth clock.
    numbers = iter(counts)
    slices, replacements = _SECTOR.subn(lambda _: str(next(numbers)), match[1], count=3)
    if replacements != 3 or len(_SECTOR.findall(match[1])) != 3:
        raise ValueError("Expected exactly three original pie sectors")
    return scene[: match.start(1)] + slices + scene[match.end(1) :]
