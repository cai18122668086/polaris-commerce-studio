"""Original AH-S03 input A and its recorded bilingual question binding."""

import re
from pathlib import Path
from typing import Any

from .motion_library import inside, sha256
from .video_editing_contracts import Transcript

QUESTION_CARD_GROUP = "AH-S03"
QUESTION_CARD_A_DESIGN = "original-ah-s03-input-a"
QUESTION_CARD_A_SHA256 = (
    "947afceebfcaafa4cae09229c0cbb6f4e56d35e53b54c28ab454eb91de164e1e"
)
QUESTION_CARD_A_FONTS = ("font-baa251526d686271", "font-dab883d69fb71323")
QUESTION_CARD_B_FONTS = (
    "font-bc9cadc3746b487c",
    "font-56735cfcb1d3feac",
    "font-d8bbdb72e3f93015",
)
QUESTION_CARD_GLYPH = "/content/question"
QUESTION_CARD_ENGLISH = "/content/english"
QUESTION_CARD_ENTRANCES = {
    "/events/chinese_frame",
    "/events/english_frame",
    "/events/question_frame",
}


def question_card_a_shot(shot: dict) -> bool:
    return (
        shot["group_id"] == QUESTION_CARD_GROUP
        and shot["layer"] == "subtitle"
        and shot["config"]["fonts"]["english"]["path"]
        == "input://" + QUESTION_CARD_A_FONTS[0]
        and shot["config"]["fonts"]["question"]["path"]
        == "input://" + QUESTION_CARD_A_FONTS[1]
    )


def question_card_entry_frame(shot: dict, fps: int, path: str) -> int:
    if (
        not question_card_a_shot(shot)
        or fps != 30
        or path not in QUESTION_CARD_ENTRANCES
    ):
        raise ValueError("AH-S03 A sound requires a 30 fps native entrance")
    events = shot["config"]["events"]
    frame = events[path.rsplit("/", 1)[1]]
    # The original easing starts at zero. Its first nonempty frame is the next one.
    if type(frame) is not int or not 0 <= frame < events["exit_frame"] - 1:
        raise ValueError("AH-S03 A entrance has no visible frame")
    start_ms = round(shot["start_seconds"] * 1000)
    return start_ms * fps // 1000 + frame + 1


def question_card_a_input(package: Path, group: dict[str, Any]) -> Path:
    if group["id"] != QUESTION_CARD_GROUP:
        raise ValueError("Original AH-S03 input A only belongs to AH-S03")
    path = inside(package, str(Path(group["entry"]).with_name("input-A.json")))
    if sha256(path) != QUESTION_CARD_A_SHA256:
        raise ValueError("Original AH-S03 input A bytes changed")
    return path


def question_card_gloss(
    native: dict[str, Any], authored: Any, transcript: Transcript
) -> dict[str, Any]:
    spoken = {row["path"]: row for row in native["text"]}
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    left = spoken.get("/content/left")
    right = spoken.get("/content/right")
    if (
        left is None
        or right is None
        or positions[left["token_ids"][-1]] + 1 != positions[right["token_ids"][0]]
        or any(not 1 <= len(row["text"]) <= 2 for row in (left, right))
        or QUESTION_CARD_ENGLISH in spoken
        or not isinstance(authored, dict)
        or set(authored) != {"source_text", "display_text"}
        or authored["source_text"] != left["text"] + right["text"]
        or not isinstance(authored["display_text"], str)
        or not re.fullmatch(r"[A-Z][A-Z '?-]{0,23}", authored["display_text"])
    ):
        raise ValueError("AH-S03 A requires an English gloss of both spoken labels")
    return {
        "path": QUESTION_CARD_ENGLISH,
        "source_text": authored["source_text"],
        "source_token_ids": [*left["token_ids"], *right["token_ids"]],
        "display_text": authored["display_text"],
        "origin": "trusted_recipe",
        "semantic_review": "unreviewed",
    }
