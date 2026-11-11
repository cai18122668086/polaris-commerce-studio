"""Original AH-S03 inputs and their recorded bilingual question binding."""

import math
import re
from pathlib import Path
from typing import Any

from .motion_library import inside, read_json, sha256
from .motion_local_dependencies import dependency_state, local_dependencies
from .video_editing_contracts import SemanticBeat, Transcript

QUESTION_CARD_GROUP = "AH-S03"
QUESTION_CARD_A_DESIGN = "original-ah-s03-input-a"
QUESTION_CARD_B_DESIGN = "original-ah-s03-input-b"
QUESTION_CARD_A_SHA256 = (
    "947afceebfcaafa4cae09229c0cbb6f4e56d35e53b54c28ab454eb91de164e1e"
)
QUESTION_CARD_A_FONTS = ("font-baa251526d686271", "font-dab883d69fb71323")
QUESTION_CARD_B_SHA256 = (
    "dea5f092f20183f6c808c0a88332bcc3a74cdabfc0127756cd0d339e7f68f2ac"
)
QUESTION_CARD_B_FONTS = (
    "font-bc9cadc3746b487c",
    "font-56735cfcb1d3feac",
    "font-d8bbdb72e3f93015",
)
QUESTION_CARD_GLYPH = "/content/question"
QUESTION_CARD_ENGLISH = "/content/english"
QUESTION_CARD_EVENTS = tuple(
    f"/events/{name}_frame"
    for name in ("chinese", "english", "question", "exit", "clear")
)
QUESTION_CARD_ENTRANCES = frozenset(QUESTION_CARD_EVENTS[:3])
QUESTION_CARD_SOUND = QUESTION_CARD_EVENTS[2]
QUESTION_CARD_LABELS = ("/content/left", "/content/right")


def question_card_a_shot(shot: dict) -> bool:
    return (
        shot["group_id"] == QUESTION_CARD_GROUP
        and shot["layer"] == "subtitle"
        and shot["config"]["fonts"]["english"]["path"]
        == "input://" + QUESTION_CARD_A_FONTS[0]
        and shot["config"]["fonts"]["question"]["path"]
        == "input://" + QUESTION_CARD_A_FONTS[1]
    )


def question_card_b_shot(shot: dict) -> bool:
    return (
        shot["group_id"] == QUESTION_CARD_GROUP
        and shot["layer"] == "subtitle"
        and all(
            shot["config"]["fonts"][role]["path"] == "input://" + rid
            for role, rid in zip(
                ("chinese", "english", "question"), QUESTION_CARD_B_FONTS, strict=True
            )
        )
    )


def question_card_entry_frame(shot: dict, fps: int, path: str) -> int:
    if (
        not (question_card_a_shot(shot) or question_card_b_shot(shot))
        or fps != 30
        or path not in QUESTION_CARD_ENTRANCES
    ):
        raise ValueError("AH-S03 sound requires a 30 fps native entrance")
    events = shot["config"]["events"]
    frame = events[path.rsplit("/", 1)[1]]
    # The original easing starts at zero. Its first nonempty frame is the next one.
    if type(frame) is not int or not 0 <= frame < events["exit_frame"] - 1:
        raise ValueError("AH-S03 entrance has no visible frame")
    start_ms = round(shot["start_seconds"] * 1000)
    return start_ms * fps // 1000 + frame + 1


def question_card_a_input(package: Path, group: dict[str, Any]) -> Path:
    if group["id"] != QUESTION_CARD_GROUP:
        raise ValueError("Original AH-S03 input A only belongs to AH-S03")
    path = inside(package, str(Path(group["entry"]).with_name("input-A.json")))
    if sha256(path) != QUESTION_CARD_A_SHA256:
        raise ValueError("Original AH-S03 input A bytes changed")
    return path


def question_card_b_input(package: Path, group: dict[str, Any]) -> Path:
    if group["id"] != QUESTION_CARD_GROUP:
        raise ValueError("Original AH-S03 input B only belongs to AH-S03")
    path = inside(package, group["input_template"])
    archived = inside(package, str(Path(group["entry"]).with_name("input-B.json")))
    if (
        sha256(path) != QUESTION_CARD_B_SHA256
        or sha256(archived) != QUESTION_CARD_B_SHA256
    ):
        raise ValueError("Original AH-S03 input B bytes changed")
    return path


def require_question_card_fonts(
    package: Path, group: dict, config: dict, manifest: Path
) -> str:
    """Check the role identities before attributing a render to input A or B."""
    fonts = config.get("fonts")
    original_a = read_json(question_card_a_input(package, group))["fonts"]
    original_b = read_json(question_card_b_input(package, group))["fonts"]
    font_ids: tuple[str, ...]
    if fonts == original_a:
        branch, font_ids = "input-A", QUESTION_CARD_A_FONTS
    elif fonts == original_b:
        branch, font_ids = "input-B", QUESTION_CARD_B_FONTS
    else:
        raise ValueError(
            "AH-S03 evidence requires the exact original A or B font roles"
        )
    registered = local_dependencies(manifest)
    identities = {
        row["id"]: row
        for row in read_json(package / "catalog/external-resources.json")["resources"]
    }
    missing = [
        rid
        for rid in font_ids
        if dependency_state(identities[rid], registered.get(rid)) != "verified"
    ]
    if missing:
        raise ValueError(
            f"AH-S03 {branch} original fonts unavailable: {', '.join(missing)}"
        )
    return branch


def question_card_gloss(
    native: dict[str, Any], authored: Any, transcript: Transcript
) -> dict[str, Any]:
    spoken = {row["path"]: row for row in native["text"]}
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    left, right = (spoken.get(path) for path in QUESTION_CARD_LABELS)
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


def automatic_question_card_gloss(
    beat: SemanticBeat, native: dict[str, Any], transcript: Transcript
) -> dict[str, str]:
    text = {row["path"]: row for row in native["text"]}
    events = {row["path"]: row for row in native["events"]}
    if (
        beat.group_id != QUESTION_CARD_GROUP
        or beat.relation != "question"
        or beat.asset_ids
        or beat.native_media
        or beat.relation_items
        or beat.question_gloss is None
        or set(text) != set(QUESTION_CARD_LABELS)
        or set(events) != set(QUESTION_CARD_EVENTS)
    ):
        raise ValueError(
            "AH-S03 A needs two spoken question labels and all five events"
        )
    left, right = (text[path] for path in QUESTION_CARD_LABELS)
    chinese, english, question, exit_event, clear = (
        events[path] for path in QUESTION_CARD_EVENTS
    )
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    left_id, right_id = left["token_ids"][0], right["token_ids"][0]
    first, english_at, question_at, exit_at, clear_at = (
        events[path]["value"] for path in QUESTION_CARD_EVENTS
    )
    clock = native["clock"]
    frames = math.ceil(
        (clock["end_ms"] - clock["start_ms"]) * clock["native_fps"] / 1000
    )
    if (
        (chinese["token_id"], chinese["edge"]) != (left_id, "start")
        or (question["token_id"], question["edge"]) != (right_id, "start")
        or english["edge"] != "start"
        or not positions[left_id]
        <= positions[english["token_id"]]
        <= positions[right_id]
        or exit_event["measured_anchor_ms"] <= question["measured_anchor_ms"]
        or clear["measured_anchor_ms"] <= exit_event["measured_anchor_ms"]
        or not first <= english_at <= question_at
        or exit_at - question_at < 9
        or clear_at - exit_at < 2
        or clear_at >= frames
    ):
        raise ValueError(
            "AH-S03 A needs ordered spoken entrances, settling time and a clear"
        )
    glossary = {
        "source_text": left["text"] + right["text"],
        "display_text": beat.question_gloss,
    }
    question_card_gloss(native, glossary, transcript)
    return glossary
