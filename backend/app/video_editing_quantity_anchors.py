"""Keep spoken amounts intact unless the original template binds their parts."""

import re
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from itertools import accumulate

from .video_editing_captioning import NUMBER, UNIT
from .video_editing_contracts import TranscriptToken

_SIGNED_NUMBER = rf"[+＋−-]?{NUMBER}"
_UNITS = rf"(?:克拉|{UNIT}|[大小][瓶袋包盒支件个片桶])(?![A-Za-z])"
_NUMERAL = r"\d零〇一二两三四五六七八九十百千万亿兆壹贰叁肆伍陆柒捌玖拾佰仟"
# A trailing number with its own unit is another amount, not a fractional price.
_PRICE_MINOR = rf"\s*{NUMBER}(?:角|毛|分)?(?![{_NUMERAL}]|\s*{_UNITS})"
_QUANTITY = re.compile(
    rf"(?<![A-Za-z{_NUMERAL}])(?:"
    rf"[¥￥]\s*{_SIGNED_NUMBER}(?:[块元角毛](?:{_PRICE_MINOR})?|{_UNITS})?"
    rf"|{_SIGNED_NUMBER}\s*(?:(?P<currency>[块元角毛])(?P<minor>{_PRICE_MINOR})?|(?P<unit>{_UNITS}))"
    r"|[+＋−-]?(?:\d{1,3}(?:[,，]\d{3})+|\d+)(?:[.．点]\d+)?(?![A-Za-z\d]))",
    re.I,
)
_COUNT_UNIT_GROUPS = frozenset(f"YY6O{i:02}" for i in range(1, 7))
_COUNT_PATH, _UNIT_PATH = "/content/count", "/content/unit"


class IncompleteQuantity(ValueError):
    code = "EDITING_QUANTITY_ANCHOR_INCOMPLETE"


@dataclass(frozen=True)
class SpokenQuantity:
    first: int
    last: int
    unit_start: int | None

    def covers(self, span: tuple[int, int]) -> bool:
        return span[0] <= self.first <= self.last <= span[1]

    def cut_by(self, span: tuple[int, int]) -> bool:
        return span[0] <= self.last and self.first <= span[1] and not self.covers(span)


def measured_quantities(tokens: list[TranscriptToken]) -> list[SpokenQuantity]:
    text = "".join(token.text for token in tokens)
    offsets = list(accumulate((len(token.text) for token in tokens), initial=0))
    quantities = []
    for match in _QUANTITY.finditer(text):
        first = bisect_right(offsets, match.start()) - 1
        last = bisect_left(offsets, match.end()) - 1
        if first >= last:
            continue
        unit_offset = match.start("unit")
        if match.group("currency") and not match.group("minor"):
            unit_offset = match.start("currency")
        unit = bisect_left(offsets, unit_offset)
        quantities.append(
            SpokenQuantity(first, last, unit if offsets[unit] == unit_offset else None)
        )
    return quantities


def _original_paired_slot(
    group: str, path: str, spans: dict[str, tuple[int, int]], quantity: SpokenQuantity
) -> bool:
    if quantity.unit_start is None:
        return False
    if group in _COUNT_UNIT_GROUPS and path in {_COUNT_PATH, _UNIT_PATH}:
        return spans.get(_COUNT_PATH) == (
            quantity.first,
            quantity.unit_start - 1,
        ) and spans.get(_UNIT_PATH) == (quantity.last, quantity.last)
    if group == "Z-M10" and path == "/content/number":
        return spans[path] == (
            quantity.first,
            quantity.unit_start - 1,
        ) and quantity.covers(spans.get("/content/body", (-1, -1)))
    if group == "W-R07" and path == "/content/label":
        return spans[path] == (quantity.unit_start, quantity.last) and any(
            quantity.covers(spans.get(f"/content/numbers/{i}", (-1, -1)))
            for i in range(2)
        )
    return False


def validate_quantity_slots(
    group: str, spans: dict[str, tuple[int, int]], quantities: list[SpokenQuantity]
) -> None:
    for path, span in spans.items():
        for quantity in quantities:
            if quantity.cut_by(span) and not _original_paired_slot(
                group, path, spans, quantity
            ):
                raise IncompleteQuantity("原生文字须保留同一次实录的完整数值和单位")
