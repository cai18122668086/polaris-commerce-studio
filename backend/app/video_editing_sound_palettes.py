"""Action-bound sound candidates shared by template audio and internal previews."""

import hashlib

from .video_editing_template_audio import SoundSlice

_NEWS_HIT: SoundSlice = ("sfx-8c9f8442f4185ef2", 0, 0.42, -21)
_LIGHT_HIT: SoundSlice = ("sfx-69dba3f8f41f94e1", 0.03, 0.26, -25)
_SOFT_DROP: SoundSlice = ("sfx-bdb886c9361538ad", 0, 0.26, -25)
_POP: SoundSlice = ("sfx-e2963eb28dfcc04b", 0, 0.17, -26)
_HOP: SoundSlice = ("sfx-fa9ac3656bfbe46f", 0, 0.23, -25)
_HOP_TWO: SoundSlice = ("sfx-f99403e674396f22", 0, 0.25, -26)
_TICK: SoundSlice = ("sfx-b7c8520fb352bfac", 0, 0.21, -27)
_DING: SoundSlice = ("sfx-5389fdd416f97c14", 0, 0.44, -26)
_NOTIFY: SoundSlice = ("sfx-0e44878ef86e8a1b", 0.25, 0.29, -28)
_SHINE: SoundSlice = ("sfx-060726feb797f274", 0.44, 0.41, -26)
_SHIMMER: SoundSlice = ("sfx-aaaeb1c1239fe4a5", 0, 0.45, -26)
_SWIPE: SoundSlice = ("sfx-22f661280569e8bc", 0.07, 0.31, -25)
_WHOOSH: SoundSlice = ("sfx-b463e8e5850a4329", 0, 0.37, -24)
_WHIP: SoundSlice = ("sfx-31528299b43be54e", 0, 0.37, -26)
_PAGE: SoundSlice = ("episode-v4-54c0a24233d6cede", 0, 0.34, -26)
_PAPER: SoundSlice = ("episode-v4-e5b4dd6219a96b9e", 0, 0.32, -28)
_TYPING: SoundSlice = ("sfx-888e8f34bf30f1c0", 0, 0.28, -27)
_KEYS: SoundSlice = ("sfx-31fef1615e1ded4d", 0.44, 0.24, -28)
_CLICK: SoundSlice = ("sfx-d1025b83b675b651", 0, 0.16, -24)
_SINGLE_CLICK: SoundSlice = ("sfx-dbafeebc3f7297da", 0.04, 0.16, -27)
_QUESTION: SoundSlice = ("sfx-51456eadc09497d3", 0, 1.465, -25)

PALETTES: dict[str, dict[str, tuple[SoundSlice, ...]]] = {
    "news": {
        "opening": (_NEWS_HIT,),
        "text": (_LIGHT_HIT, _SOFT_DROP, _TICK),
        "emphasis": (_HOP, _DING),
        "media": (_WHOOSH, _SWIPE),
        "transition": (_SWIPE, _WHOOSH),
        "click": (_CLICK,),
        "type": (_TYPING,),
        "question": (_QUESTION,),
        "confirm": (_DING,),
        "closing": (_NOTIFY,),
    },
    "application": {
        "opening": (_SOFT_DROP,),
        "text": (_POP, _HOP, _TICK),
        "emphasis": (_DING, _HOP_TWO, _NOTIFY),
        "media": (_SWIPE, _PAGE, _WHIP),
        "transition": (_SWIPE, _WHOOSH),
        "click": (_CLICK,),
        "type": (_KEYS, _TYPING, _SINGLE_CLICK),
        "question": (_TICK,),
        "confirm": (_DING,),
        "closing": (_SHINE,),
    },
    "lifestyle": {
        "opening": (_PAPER,),
        "text": (_POP, _HOP, _HOP_TWO),
        "emphasis": (_DING, _TICK),
        "media": (_PAGE, _PAPER),
        "transition": (_SWIPE, _PAGE),
        "click": (_CLICK,),
        "type": (_KEYS,),
        "question": (_POP,),
        "confirm": (_SHINE, _SHIMMER),
        "closing": (_DING,),
    },
}


def overlay_family(template_id: str) -> str:
    if any(
        word in template_id
        for word in ("browser", "steps", "flow-chart", "panels", "handoff")
    ):
        return "application"
    if any(
        word in template_id
        for word in (
            "paper",
            "line-story",
            "film",
            "collage",
            "subtitle-story",
            "package",
        )
    ):
        return "lifestyle"
    return "news"


def select_sound(
    family: str,
    action: str,
    series: str,
    occurrence: int,
    *,
    previous: str = "",
    avoided: set[str] | None = None,
) -> SoundSlice | None:
    palette = PALETTES[family]
    candidates = [
        cue
        for cue in palette.get(action, palette["text"])
        if cue[0] not in (avoided or ())
    ]
    if not candidates:
        return None
    digest = hashlib.sha256(f"{series}|{family}|{action}".encode()).digest()
    index = (int.from_bytes(digest[:4], "big") + occurrence) % len(candidates)
    if len(candidates) > 1 and candidates[index][0] == previous:
        index = (index + 1) % len(candidates)
    return candidates[index]
