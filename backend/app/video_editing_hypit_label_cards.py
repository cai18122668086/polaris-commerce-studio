"""Bind spoken labels and entry frames to the original HY-A1 card tracks."""

import math
import re
from pathlib import Path

from .motion_library import inside, read_json, sha256
from .motion_local_dependencies import (
    component_use_state,
    dependency_state,
    local_dependencies,
)
from .video_editing_hypit import NATIVE_FILES

LABEL_CARD_GROUP = "HY-A1"
LABEL_CARD_PROFILE = "hypit-original-label-cards/1"
LABEL_CARD_FONT = "font-6dbc774369f7c6ee"
LABEL_CARD_TEXT = tuple(f"/hypit_label_cards/{i}/text" for i in range(3))
LABEL_CARD_EVENTS = tuple(f"/hypit_label_cards/{i}/entry_frame" for i in range(3))
_NODES = ("xiu", "ti", "li")
_ORIGINAL_ENTRY = (0, 22, 43)
_ORIGINAL_END = 63
# Original label-card BOX bottom and half the dashed border's stroke.
_CARD_BOTTOM = 194.5 - 98.5 + 3.5 / 2
_CANVAS_HEIGHT = 1920
_CAPTION_REFERENCE_HEIGHT = 1280
_CAPTION_BASELINE = 1230
_SOURCE_SHA256 = "36b68002e858de5901f2516b15157b595bd3a2487eaf11c0c0a20024b929c9a7"
_COMPONENTS = {
    "s03.svs": "1fbf037597f57041055dfbd674316a229c0904cdba9ca6c835faf3878fcc8c18",
    "packages/label-card/dist/activation.js": (
        "76e760a9dc24f228671fd856fd0c0d0d2c2c943d333d24c88008d7e547ca6223"
    ),
    "packages/label-card/dist/render.js": (
        "ab310779f5f15748db229a4f7807f5cc33c0a3b0d9a083f2a7738e64be8afc11"
    ),
}


def require_label_card_component_font(
    package: Path, config: dict, task_bindings: Path, registry: Path | None
) -> None:
    if config.get("fonts") != {"junya": "input://" + LABEL_CARD_FONT}:
        raise ValueError("HY-A1 needs the original Junya font slot")
    identity = next(
        row
        for row in read_json(package / "catalog/external-resources.json")["resources"]
        if row["id"] == LABEL_CARD_FONT
    )
    if (
        dependency_state(
            identity, local_dependencies(task_bindings).get(LABEL_CARD_FONT)
        )
        != "verified"
    ):
        raise ValueError("HY-A1 needs the exact original font bytes")
    if component_use_state(identity, registry) != "reference_recorded":
        raise ValueError("HY-A1 needs an original-font component use reference")


def _card_tag(node: str) -> re.Pattern[str]:
    return re.compile(rf'<card:Card id="{node}"[^>]*?/>')


def _card_attribute(tag: str, name: str, default: str | None = None) -> str:
    found = re.search(rf'(?<=\s){name}="([^"]+)"', tag)
    if found:
        return found[1]
    if default is not None:
        return default
    raise ValueError("Original label card parameter is unavailable")


def label_card_attributes(package: Path, group: dict, data: dict) -> dict:
    entry = inside(package, group["entry"])
    special = "commercial_runtime/special.py"
    if (
        sha256(entry) != _SOURCE_SHA256
        or sha256(package / special) != NATIVE_FILES[special]
        or any(
            sha256(entry.parent / path) != digest
            for path, digest in _COMPONENTS.items()
        )
    ):
        raise ValueError("Audited original Hypit label cards changed")
    scene = entry.read_text(encoding="utf-8")
    starts, frames, labels = data["entry_frames"], data["frames"], data["labels"]
    if (
        len(starts) != 3
        or any(type(frame) is not int for frame in starts)
        or starts[0] != 0
        or starts[1] <= 4
        or starts[2] - starts[1] <= 11
        or type(frames) is not int
        or not starts[2] + (_ORIGINAL_END - _ORIGINAL_ENTRY[2]) <= frames <= 450
        or len(labels) != 3
        or any(not re.fullmatch(r"[\u3400-\u9fff]{1,4}", label) for label in labels)
    ):
        raise ValueError(
            "Three ordered spoken labels must leave room for original moves"
        )

    def retime(frame: int) -> int:
        # The gap between slides follows the spoken spacing. Each slide keeps
        # its original frame offsets relative to the next card's arrival.
        if frame == 0:
            return 0
        if frame == _ORIGINAL_END:
            return frames
        anchor = 1 if frame <= 29 else 2
        return starts[anchor] + frame - _ORIGINAL_ENTRY[anchor]

    attributes = {"t": {"end": f"{frames}f"}}
    for node, label, start, old_start in zip(
        _NODES, labels, starts, _ORIGINAL_ENTRY, strict=True
    ):
        match = _card_tag(node).search(scene)
        if not match:
            raise ValueError("Original Hypit label card track is unavailable")
        move = [
            pair.split(":") for pair in _card_attribute(match[0], "move").split(",")
        ]
        attributes[node] = {
            "text": label,
            "reveal": str(start + int(_card_attribute(match[0], "reveal")) - old_start),
            "move": ",".join(f"{retime(int(at))}:{y}" for at, y in move),
            **({"from": str(start)} if old_start else {}),
        }
    return attributes


def compile_label_cards(package: Path, group: dict, native: dict) -> dict:
    text = {row["path"]: row for row in native["text"]}
    events = {row["path"]: row for row in native["events"]}
    if set(text) != set(LABEL_CARD_TEXT) or set(events) != set(LABEL_CARD_EVENTS):
        raise ValueError("Each original Hypit card needs its own spoken text and entry")
    labels = [text[path] for path in LABEL_CARD_TEXT]
    arrivals = [events[path] for path in LABEL_CARD_EVENTS]
    if any(
        event["edge"] != "start" or event["token_id"] != label["token_ids"][0]
        for label, event in zip(labels, arrivals, strict=True)
    ):
        raise ValueError("Enter each original card at its own spoken label")
    clock = native["clock"]
    data = {
        "profile": LABEL_CARD_PROFILE,
        "group_id": LABEL_CARD_GROUP,
        "entry_frames": [event["value"] for event in arrivals],
        "labels": [label["text"] for label in labels],
        "frames": math.ceil((clock["end_ms"] - clock["start_ms"]) * 30 / 1000),
        "plate": native["media_clocks"][0],
    }
    attrs = label_card_attributes(package, group, data)
    lowest_center = max(
        float(pair.split(":", 1)[1])
        for node in _NODES
        for pair in attrs[node]["move"].split(",")
    )
    data["caption_lane"] = {
        "reference_height": _CAPTION_REFERENCE_HEIGHT,
        "min_ink_y": math.ceil(
            (lowest_center + _CARD_BOTTOM) * _CAPTION_REFERENCE_HEIGHT / _CANVAS_HEIGHT
        ),
        "baseline_y": _CAPTION_BASELINE,
    }
    return data


def patch_label_cards(scene: str, attributes: dict) -> str:
    # The original materializer accepts the timeline end. Apply the content and
    # the two native from attributes only to its task-local copy.
    for node in _NODES:
        matches = list(_card_tag(node).finditer(scene))
        if len(matches) != 1:
            raise ValueError("Original Hypit label card track must occur once")
        match = matches[0]
        tag = match[0]
        for key, value in attributes[node].items():
            old = _card_attribute(tag, key)
            tag = tag.replace(f'{key}="{old}"', f'{key}="{value}"', 1)
        scene = scene[: match.start()] + tag + scene[match.end() :]
    return scene


def label_card_scene_entries(scene: str) -> list[int]:
    """Read the first visible panel frames from the actual materialized tracks."""
    entries = []
    for node in _NODES:
        matches = list(_card_tag(node).finditer(scene))
        if len(matches) != 1:
            raise ValueError("Original Hypit label card track must occur once")
        entries.append(
            int(
                _card_attribute(
                    matches[0][0], "from", "0" if node == _NODES[0] else None
                )
            )
        )
    return entries
