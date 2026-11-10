"""Retain explicit spoken conditions on independently displayed Motion text."""

import re
from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import accumulate

from .video_editing_contracts import TranscriptToken

_BREAK = re.compile(r"[。！？；!?;]|(?<!\d)[.,，]|[.,，](?!\d)")
_MARKER = re.compile(r"如果|假如|倘若|要是|只有|只要|除非|一旦|仅限|仅适用于|只适用于")
_LIMITS = {"仅限", "仅适用于", "只适用于"}
_COLLOQUIAL_IF = {"如果", "假如", "倘若", "要是"}
_OUTCOME_NEGATION = r"(?:\s*(?:不可以|不能|不得|不会|不予|不))?"
_INLINE = {
    "只有": re.compile(
        rf"(?:才(?=能|可|会|有|是|包邮|免运费|享|送|退|下单|生效)|方可){_OUTCOME_NEGATION}"
    ),
    "除非": re.compile(rf"(?:否则|不然|才){_OUTCOME_NEGATION}"),
}
_DEFAULT_INLINE = re.compile(
    rf"(?:就(?!业|职|医|诊|学|座|餐|读|近)|便(?!宜|利)|(?<!规|原|法|准)则|即可)"
    rf"{_OUTCOME_NEGATION}"
)
_FOLLOWING_OUTCOME = re.compile(
    rf"\s*(?:那(?:么)?|这样)?(?:(?P<connector>(?:才|就|便|则|即可|方可|否则|不然){_OUTCOME_NEGATION})|"
    r"赶紧|马上|直接|可以(?!考虑|试试|看看)|可领取|可享|包邮|免运费)"
)


class IncompleteCondition(ValueError):
    code = "EDITING_CONDITION_ANCHOR_INCOMPLETE"


@dataclass(frozen=True)
class SpokenCondition:
    first: int
    premise_last: int
    last: int
    connector: tuple[int, int] | None = None

    def touched_by(self, span: tuple[int, int]) -> bool:
        return span[0] <= self.last and self.first <= span[1]


def measured_conditions(tokens: list[TranscriptToken]) -> list[SpokenCondition]:
    text = "".join(token.text for token in tokens)
    offsets = list(accumulate((len(token.text) for token in tokens), initial=0))
    clauses: list[tuple[int, int, str]] = []
    start = 0
    for mark in _BREAK.finditer(text):
        clauses.append((start, mark.start(), mark.group()))
        start = mark.end()
    clauses.append((start, len(text), ""))

    result = []
    for index, (start, end, separator) in enumerate(clauses):
        marker = _MARKER.search(text, start, end)
        if marker is None or marker.end() == end:
            continue
        word = marker.group()
        premise_end, outcome_end = end, end
        connector_chars = None
        if word not in _LIMITS:
            following = clauses[index + 1] if separator in {",", "，"} else None
            outcome = (
                _FOLLOWING_OUTCOME.match(text, following[0], following[1])
                if following
                else None
            )
            if following and outcome:
                outcome_end = following[1]
                if (
                    word in _COLLOQUIAL_IF
                    and end - marker.end() > 1
                    and text[end - 1] == "的"
                ):
                    premise_end -= 1
                if outcome.group("connector"):
                    connector_chars = outcome.span("connector")
            else:
                connector = _INLINE.get(word, _DEFAULT_INLINE).search(
                    text, marker.end() + 1, end
                )
                if connector is None or connector.end() == end:
                    continue
                premise_end = connector.start()
                connector_chars = connector.span()
        first = bisect_right(offsets, marker.start()) - 1
        premise_last = bisect_left(offsets, premise_end) - 1
        last = bisect_left(offsets, outcome_end) - 1
        if first < last:
            connector_tokens = (
                (
                    bisect_right(offsets, connector_chars[0]) - 1,
                    bisect_left(offsets, connector_chars[1]) - 1,
                )
                if connector_chars
                else None
            )
            result.append(SpokenCondition(first, premise_last, last, connector_tokens))
    return result


def omits_spoken_condition(
    spans: Iterable[tuple[int, int]], conditions: list[SpokenCondition]
) -> bool:
    visible = tuple(spans)
    for condition in conditions:
        if not any(condition.touched_by(span) for span in visible):
            continue
        required = list(range(condition.first, condition.premise_last + 1))
        if condition.connector:
            start, end = condition.connector
            if any(
                first <= condition.last and last >= start for first, last in visible
            ):
                required.extend(range(start, end + 1))
        if any(
            not any(first <= i <= last for first, last in visible) for i in required
        ):
            return True
    return False


def validate_condition_coverage(
    spans: Iterable[tuple[int, int]], conditions: list[SpokenCondition]
) -> None:
    if omits_spoken_condition(spans, conditions):
        raise IncompleteCondition("动效文字须保留同一次实录的完整适用条件")
