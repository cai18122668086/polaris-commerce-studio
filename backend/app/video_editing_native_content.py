"""Compile original native labels from current source anchors."""

import re
from datetime import datetime
from itertools import pairwise
from pathlib import Path
from typing import Any

from PIL import Image

from .video_editing_contracts import SemanticBeat, Transcript

CHAPTER_GROUPS = frozenset(("Z-M05", "Z-M15"))
CHAPTER_PATH = "/content/ordinal"
NUMBER_GROUP = "W-R07"
YEAR_GROUP = "AH-S07"
YEAR_PATH = "/content/year"
TRANSLATION_GROUP = "W-R02"
ROLE_CHAIN_GROUP = "W-R15"
PACKAGE_GROUP = "Z-M12"
FILM_FEEDBACK_GROUP = "W-R01"
WHY_GROUP = "W-R17"
WHY_FONT = "font-baa251526d686271"
WHY_TEXT = "/content/english_question"
WHY_PROPS = ("media-33e4cf54d9f6175ef4cd", "media-4eba1bafe09821cb8a23")
WHY_PROP_PATHS = tuple(f"/media/question_props/{i}/path" for i in range(2))
_WHY_GLOSSES = {
    "为什么": "Why?",
    "为何": "Why?",
    "为啥": "Why?",
    "怎么": "How?",
    "如何": "How?",
    "谁": "Who?",
}
_ROLE_SCENE_ORDER = (
    "scene0",
    "profile",
    "doctor",
    "door",
    "closed",
    "apart",
    "apart_clean",
    "operator_only",
    "operating",
    "trust_clean",
    "trust",
    "lying",
    "seated",
    "patient",
    "patient_large",
    "assembly",
)
_ROLE_SCENE_SHARED_EVENTS = {"door_close": 4, "handoff": 5, "prohibition_in": 15}
_ORDINALS = (
    "First",
    "Second",
    "Third",
    "Fourth",
    "Fifth",
    "Sixth",
    "Seventh",
    "Eighth",
    "Ninth",
    "Tenth",
)
_DIGITS = dict(zip("零一二三四五六七八九两", "01234567892", strict=True))
_YEAR_DIGITS = str.maketrans(
    "零〇一二三四五六七八九０１２３４５６７８９", "001234567890123456789"
)
_YEAR = re.compile(r"(?:[0-9]{4}|[０-９]{4}|[零〇一二三四五六七八九]{4})年")
_NUMBER = re.compile(
    r"([0-9]{1,3}|[零一二两三四五六七八九十])"
    r"(千克|公斤|毫升|斤|克|升|瓶|件|个|包|盒|元|块|条|天)?"
)
_ENGLISH_LABEL = re.compile(r"[A-Z]+(?:[ -][A-Z]+)*")


def chapter_ordinal(
    beat: SemanticBeat, transcript: Transcript, markers: Any
) -> dict[str, Any]:
    positions = {token.id: index for index, token in enumerate(transcript.tokens)}
    if (
        beat.group_id not in CHAPTER_GROUPS
        or not isinstance(markers, list)
        or not 1 <= len(markers) <= len(_ORDINALS)
        or any(
            not isinstance(token, str) or token not in positions for token in markers
        )
    ):
        raise ValueError("Original chapter ordinal requires measured outline anchors")
    ordered = [positions[token] for token in markers]
    if ordered[0] != 0 or ordered != sorted(set(ordered)):
        raise ValueError(
            "Chapter outline must start at the first word and follow source order"
        )
    if beat.first_token_id not in markers:
        raise ValueError("Native chapter must start on its saved outline anchor")
    index = markers.index(beat.first_token_id)
    if index + 1 < len(ordered) and positions[beat.last_token_id] >= ordered[index + 1]:
        raise ValueError("Native chapter leaves its saved outline interval")
    return {
        "chapter_number": index + 1,
        "chapter_start_token_ids": markers,
        "current_start_token_id": beat.first_token_id,
        "display_text": _ORDINALS[index],
    }


def number_glyphs(native: dict[str, Any]) -> list[dict[str, Any]]:
    rows = {row["path"]: row for row in native["text"]}
    events = {row["path"]: row for row in native["events"]}
    readings = []
    for index in range(2):
        path = f"/content/numbers/{index}"
        number = rows.get(path)
        caption = rows.get(f"/content/captions/{index}")
        if not number or not caption:
            raise ValueError("Each native number needs a spoken amount and its caption")
        match = _NUMBER.fullmatch(number["text"])
        caption_tokens = caption["token_ids"]
        amount_tokens = number["token_ids"]
        if not match or not any(
            caption_tokens[start : start + len(amount_tokens)] == amount_tokens
            for start in range(len(caption_tokens))
        ):
            raise ValueError("Bind a supported spoken integer within its own caption")
        event_name = "black_in" if index == 0 else "second_number"
        event = events.get(f"/timing/events/{event_name}")
        if (
            not event
            or event["token_id"] != amount_tokens[0]
            or event["edge"] != "start"
        ):
            raise ValueError(
                "Each original number reveal needs its spoken amount start"
            )
        spoken, unit = match.groups()
        digits = "10" if spoken == "十" else _DIGITS.get(spoken, spoken)
        readings.append({**number, "display_text": digits, "unit": unit})
    label = rows.get("/content/label", {}).get("text")
    first, second = readings
    if first["unit"] != second["unit"] or (first["unit"] and label != first["unit"]):
        raise ValueError("Native comparison must preserve the same spoken unit")
    return readings


def year_glyphs(native: dict[str, Any]) -> dict[str, Any]:
    year = next((row for row in native["text"] if row["path"] == YEAR_PATH), None)
    if not year or not _YEAR.fullmatch(year["text"]):
        raise ValueError("Native year needs four spoken digits followed by 年")
    entry = next(
        (row for row in native["events"] if row["path"] == "/events/year_frame"), None
    )
    if (
        not entry
        or entry["token_id"] != year["token_ids"][0]
        or entry["edge"] != "start"
    ):
        raise ValueError("Native year reveal must use the spoken year's first digit")
    return {**year, "display_text": year["text"].translate(_YEAR_DIGITS)}


def translation_labels(native: dict[str, Any], authored: Any) -> list[dict[str, Any]]:
    """Keep the trusted recipe's English glosses separate from spoken words."""
    sides = ("before", "after")
    if (
        native["group_id"] != TRANSLATION_GROUP
        or not isinstance(authored, dict)
        or set(authored) != set(sides)
    ):
        raise ValueError(
            "Native translation requires the original two-sided label group"
        )
    spoken = {row["path"]: row for row in native["text"]}
    result = []
    for side in sides:
        path = f"/content/english_{side}"
        source_path = f"/content/{side}"
        source = spoken.get(source_path)
        caption = spoken.get(f"/content/caption_{side}")
        row = authored[side]
        if (
            path in spoken
            or not source
            or not caption
            or not isinstance(row, dict)
            or set(row) != {"source_text", "display_text"}
            or row["source_text"] != source["text"]
            or not set(source["token_ids"]) <= set(caption["token_ids"])
        ):
            raise ValueError(
                "Each translation must reference its own spoken label and caption"
            )
        display = row["display_text"]
        if (
            not isinstance(display, str)
            or len(display) > 24
            or not _ENGLISH_LABEL.fullmatch(display)
        ):
            raise ValueError(
                "Use a short uppercase English label in the native translation"
            )
        result.append(
            {
                "path": path,
                "source_path": source_path,
                "source_text": source["text"],
                "source_token_ids": source["token_ids"],
                "display_text": display,
                "origin": "trusted_recipe",
                "semantic_review": "unreviewed",
            }
        )
    return result


def film_feedback_entries(
    native: dict[str, Any],
    assets: dict[str, dict[str, Any]],
    observations: Any,
) -> list[dict[str, Any]]:
    """Bind each displayed reaction count to a current, dated evidence image."""
    if not isinstance(observations, list) or len(observations) != 3:
        raise ValueError("Film feedback requires three dated evidence records")
    text = {row["path"]: row for row in native["text"]}
    media = {row["path"]: row["asset_id"] for row in native["media"]}
    events = {row["path"]: row for row in native["events"]}
    entries = []
    for index, observed in enumerate(observations):
        asset_id = media.get(f"/media/photos/{index}/path", "")
        asset = assets.get(asset_id, {})
        label = text.get(f"/content/comments/{index}/text")
        event = events.get(f"/timing/events/comments/{index}")
        if (
            not isinstance(observed, dict)
            or set(observed)
            != {"asset_id", "label", "likes", "source_ref", "observed_at"}
            or asset.get("kind") != "image"
            or asset.get("source") != "project_upload"
            or asset.get("source_image_result")
            or not label
            or not event
            or observed["asset_id"] != asset_id
            or observed["label"] != label["text"]
            or type(observed["likes"]) is not int
            or observed["likes"] < 0
            or not isinstance(observed["source_ref"], str)
            or not 1 <= len(observed["source_ref"].strip()) <= 400
            or not isinstance(observed["observed_at"], str)
            or event["edge"] != "start"
            or event["token_id"] != label["token_ids"][0]
        ):
            raise ValueError(
                "Film feedback count needs matching project evidence and words"
            )
        if datetime.fromisoformat(observed["observed_at"]).utcoffset() is None:
            raise ValueError("Film feedback observation time needs a timezone")
        entries.append(
            {
                **observed,
                "path": f"/content/comments/{index}/likes",
                "asset_sha256": asset["sha256"],
                "token_id": event["token_id"],
                "semantic_review": "unreviewed",
            }
        )
    return entries


def why_template(template: dict, *, embedded_caption: bool = True) -> dict:
    return {
        **template,
        "content": {
            **template["content"],
            "captions": template["content"]["captions"] if embedded_caption else [],
        },
        "media": {
            **template["media"],
            "question_props": [
                {"kind": "image", "path": f"input://{rid}", "alpha": True}
                for rid in WHY_PROPS
            ],
        },
    }


def why_word_bindings(native: dict, assets: dict[str, dict]) -> dict:
    source = next((row for row in native["text"] if row["path"] == WHY_TEXT), None)
    events = {row["path"]: row for row in native["events"]}
    keys = tuple(
        "/timing/events/" + key
        for key in ("props_in/0", "props_in/1", "english_in", "blur_exit")
    )
    duration = (native["clock"]["end_ms"] - native["clock"]["start_ms"]) / 1000
    if not source or not all(key in events for key in keys):
        raise ValueError("Anchor both props, the spoken question and the blur exit")
    display = _WHY_GLOSSES.get(source["text"].rstrip("?？"), source["text"])
    times = [events[key]["value"] for key in keys]
    english = events[keys[2]]
    if (
        not re.fullmatch(r"[A-Za-z]{1,3}\?", display)
        or english["edge"] != "start"
        or english["token_id"] != source["token_ids"][0]
        or not 0 < times[0] < times[1] < times[2] < times[3] < duration
    ):
        raise ValueError("Use a short spoken question and four ordered W-R17 events")

    media = {row["path"]: row["asset_id"] for row in native["media"]}
    props = []
    for path in WHY_PROP_PATHS:
        aid = media.get(path, "")
        asset = assets.get(aid, {})
        if asset.get("kind") != "image" or asset.get("source") != "project_upload":
            raise ValueError("Select two registered transparent question props")
        with Image.open(Path(asset["path"])) as image:
            if (
                image.format != "PNG"
                or image.size != (540, 960)
                or "A" not in image.getbands()
                or image.getchannel("A").getextrema() != (0, 255)
            ):
                raise ValueError("Question props need the native 540×960 alpha canvas")
        props.append({"path": path, "asset_id": aid, "sha256": asset["sha256"]})
    if len({row["sha256"] for row in props}) != 2:
        raise ValueError("Select two distinct question prop images")
    return {
        "path": WHY_TEXT,
        "source_text": source["text"],
        "source_token_ids": source["token_ids"],
        "display_text": display,
        "props": props,
        "semantic_review": "unreviewed",
    }


def live_package_template(template: dict[str, Any]) -> dict[str, Any]:
    return {
        **template,
        "layout": {**template["layout"], "mode": "native", "overflow": "reject"},
        "media": {
            **template["media"],
            "presenter": {
                **template["media"]["presenter"],
                "kind": "video",
                "offset_seconds": 0,
                "duration_seconds": 1,
                "end_policy": "error",
            },
        },
    }


def package_entries(
    native: dict[str, Any], assets: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    labels = {row["path"]: row for row in native["text"]}
    events = {row["path"]: row for row in native["events"]}
    media = {row["path"]: row["asset_id"] for row in native["media"]}
    entries: list[dict[str, Any]] = []
    for index in range(4):
        asset_id = media.get(f"/media/product_images/{index}/path", "")
        asset = assets.get(asset_id, {})
        label = labels.get(f"/content/items/{index}/label")
        event = events.get(f"/timing/events/item{index}")
        if (
            asset.get("kind") != "image"
            or asset.get("source") != "project_upload"
            or not label
            or not event
            or event["token_id"] != label["token_ids"][0]
            or event["edge"] != "start"
            or (entries and entries[-1]["local_seconds"] >= event["value"])
        ):
            raise ValueError(
                "Each package image needs an ordered entry at its spoken label"
            )
        entries.append(
            {
                "asset_id": asset_id,
                "label": label["text"],
                "token_id": event["token_id"],
                "local_seconds": event["value"],
            }
        )
    return entries


def role_scene_contract() -> dict[str, Any]:
    return {
        "image_slots": [
            {"path": f"/media/scene_layers/{index}/path", "native_role": role}
            for index, role in enumerate(_ROLE_SCENE_ORDER)
        ],
        "role_label_overlay": {
            "native_roles": ["profile", "doctor"],
            "canvas_px": [540, 960],
            "label_boxes_xyxy_px": [
                [20, 45, 250, 145],
                [290, 45, 520, 145],
                [130, 760, 410, 860],
            ],
            "binding": "在原生角色字的位置避免给配图再印同层标题。",
        },
        "shared_word_events": {
            f"/timing/events/{event}": f"/timing/events/scene_boundaries/{index}"
            for event, index in _ROLE_SCENE_SHARED_EVENTS.items()
        },
        "binding": (
            "素材序号保留原生角色顺序，scene_boundaries 只驱动原动作时钟。"
            "角色名字来自原场景，素材内容按本期语义选用。"
            "第一个切点绑定本段首词，关门、交接和禁行各与对应切点共用词点。"
            "交叉淡化、留屏及连续换图仍按原引擎。"
        ),
    }


def role_scene_chain(
    native: dict[str, Any], assets: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Check the original sixteen scene roles and three coincident transitions."""
    events = {row["path"]: row for row in native["events"]}
    media = {row["path"]: row["asset_id"] for row in native["media"]}
    prefix = "/timing/events/"
    boundaries = [
        events.get(f"{prefix}scene_boundaries/{index}")
        for index in range(len(_ROLE_SCENE_ORDER))
    ]
    image_ids = [
        media.get(f"/media/scene_layers/{index}/path")
        for index in range(len(_ROLE_SCENE_ORDER))
    ]
    if any(
        asset_id is None or assets[asset_id].get("kind") != "image"
        for asset_id in image_ids
    ):
        raise ValueError("Bind all sixteen original role scene image slots")
    anchors = [event for event in boundaries if event is not None]
    if (
        len(anchors) != len(_ROLE_SCENE_ORDER)
        or anchors[0]["value"] != 0
        or any(left["value"] >= right["value"] for left, right in pairwise(anchors))
    ):
        raise ValueError("Role scene boundaries must start at zero and follow speech")
    for key, index in _ROLE_SCENE_SHARED_EVENTS.items():
        shared = events.get(prefix + key, {})
        if any(
            shared.get(field) != anchors[index][field] for field in ("token_id", "edge")
        ):
            raise ValueError("Bind " + key + " to its original shared scene boundary")
    return {
        "scene_asset_ids": image_ids,
        "boundaries": [
            {
                "token_id": event["token_id"],
                "edge": event["edge"],
                "start_seconds": event["value"],
            }
            for event in anchors
        ],
        "semantic_review": "unreviewed",
    }
