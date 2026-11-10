"""Ground the original W-R04 evidence layers and linked label entrances."""

from itertools import pairwise
from typing import Any

from PIL import Image

from .video_editing_contracts import SemanticBeat, Transcript
from .video_editing_crowd_scene import CROWD_SILHOUETTES, crowd_image_slots
from .video_editing_virtual_clock import first_visible_frame

COLLAGE_GROUP = "W-R04"
COLLAGE_TEMPLATE_ID = "unified-evidence-collage-v1"
COLLAGE_SOURCE = "/media/background/path"
COLLAGE_LAYERS = tuple(
    f"/media/{key}/path"
    for key in ("evidence_top", "person_right", "photo_left", "chat")
)
COLLAGE_IMAGES = (*COLLAGE_LAYERS, *CROWD_SILHOUETTES)
COLLAGE_SOUNDS = tuple(f"layer_entries/{i}" for i in range(4))
_LABELS = tuple(f"/content/labels/{i}" for i in range(7))
_EVENTS = "/timing/events/"
_CAPTION = "/content/captions/0/"
_LAYER_SIZES = ((365, 240), (275, 345), (270, 280), (390, 240))
_NATIVE_LAYERS = (0.08, 0.38, 0.62, 1.04)
# The renderer draws the pairs on the same virtual clock.
_NATIVE_LABELS = (0.25, 0.45, 0.52, 0.75, 0.75, 1.08, 1.08)


def collage_image_slots(files: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    silhouettes = crowd_image_slots(files)
    slots: dict[str, list[str]] = {
        **{path: [] for path in COLLAGE_LAYERS},
        **{path: silhouettes[path] for path in CROWD_SILHOUETTES},
    }
    for asset_id, asset in sorted(files.items()):
        if asset.get("kind") != "image" or asset.get("source") != "project_upload":
            continue
        try:
            with Image.open(asset["path"]) as image:
                low, high = image.convert("RGBA").getchannel("A").getextrema()
                for i, (path, size) in enumerate(
                    zip(COLLAGE_LAYERS, _LAYER_SIZES, strict=True)
                ):
                    if i == 1:
                        valid = (
                            image.format == "PNG"
                            and isinstance(low, int)
                            and isinstance(high, int)
                            and low < 255
                            and high > 0
                            and image.width >= size[0]
                            and image.height >= size[1]
                        )
                    else:
                        valid = image.size == size and low == 255
                    if valid:
                        slots[path].append(asset_id)
        except (OSError, ValueError):
            continue
    return slots


def validate_collage_images(
    media: dict[str, str], images: dict[str, str], slots: dict[str, list[str]] | None
) -> None:
    if (
        any(media.get(path) not in images for path in COLLAGE_IMAGES)
        or len({images[media[path]] for path in COLLAGE_IMAGES}) != len(COLLAGE_IMAGES)
        or slots is not None
        and any(media.get(path) not in slots[path] for path in COLLAGE_IMAGES)
    ):
        raise ValueError(
            "Evidence collage needs four current layers and seven separate silhouettes"
        )


def _actual_order(layers: list[float], labels: list[float]) -> list[float]:
    return [
        layers[0],
        labels[0],
        layers[1],
        labels[1],
        labels[2],
        layers[2],
        labels[3],
        layers[3],
        labels[5],
    ]


def validate_collage_anchors(
    beat: SemanticBeat, native: dict, transcript: Transcript
) -> None:
    events = {row["path"]: row for row in native["events"]}
    text = {row["path"]: row for row in native["text"]}
    media = {row["path"]: row["asset_id"] for row in native["media"]}
    layers = [events[_EVENTS + key] for key in COLLAGE_SOUNDS]
    labels = [events[_EVENTS + f"label_entries/{i}"] for i in range(7)]
    caption = text[_CAPTION + "text"]
    begin, end = (events[_CAPTION + key] for key in ("start", "end"))
    start, finish = (native["clock"][key] for key in ("start_ms", "end_ms"))
    duration = (finish - start) / 1000
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    layer_times = [row["value"] for row in layers]
    label_times = [row["value"] for row in labels]
    order = _actual_order(layer_times, label_times)
    if (
        beat.relation != "explanation"
        or not 2 <= duration <= 15
        or len(beat.relation_items) != 4
        or any(
            item.asset_ids != [media[path]]
            or item.native_media_paths != [path]
            or item.native_text_paths
            or event["token_id"] != item.first_token_id
            for item, path, event in zip(
                beat.relation_items, COLLAGE_LAYERS, layers, strict=True
            )
        )
        or any(row["edge"] != "start" for row in (*layers, *labels))
        or any(
            positions[a.last_token_id] >= positions[b.first_token_id]
            for a, b in pairwise(beat.relation_items)
        )
        or any(
            positions[text[a]["token_ids"][-1]] >= positions[text[b]["token_ids"][0]]
            for a, b in pairwise(_LABELS)
        )
        or any(a["value"] + 0.25 > b["value"] for a, b in pairwise(layers))
        or any(
            row["token_id"] != text[_LABELS[j]]["token_ids"][0]
            for row, j in zip(labels, (0, 1, 2, 4, 4, 6, 6), strict=True)
        )
        or order[0] < 1 / 30
        or order[-1] > duration - 0.30
        or any(a + 1 / 30 > b for a, b in pairwise(order))
        or any(
            not 1 <= len(text[path]["text"]) <= 3 or "\n" in text[path]["text"]
            for path in _LABELS
        )
        or not 1 <= len(caption["text"]) <= 14
        or (begin["edge"], begin["token_id"]) != ("start", caption["token_ids"][0])
        or (end["edge"], end["token_id"]) != ("end", caption["token_ids"][-1])
        or not begin["value"] + 0.40 <= end["value"] <= duration
    ):
        raise ValueError(
            "Original collage needs four spoken evidence slots and linked labels"
        )
    timing = {
        "duration_seconds": duration,
        "events": {"layer_entries": layer_times, "label_entries": label_times},
    }
    if any(
        abs(collage_action_frame(timing, event) / 30 - seconds) > 0.35
        for event, seconds in zip(COLLAGE_SOUNDS, layer_times, strict=True)
    ):
        raise ValueError(
            "Original retiming moves the evidence too far from its spoken cue"
        )


def collage_action_frame(timing: dict, event: str) -> int:
    actual = timing["events"]
    return first_visible_frame(
        [
            0,
            *_actual_order(actual["layer_entries"], actual["label_entries"]),
            timing["duration_seconds"],
        ],
        [0, *_actual_order(list(_NATIVE_LAYERS), list(_NATIVE_LABELS)), 2],
        (3, 12, 19, 32)[COLLAGE_SOUNDS.index(event)],
    )
