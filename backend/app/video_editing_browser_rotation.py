"""Supply a measured live presenter to the original browser layouts."""

import base64
import importlib
import importlib.util
import math
import re
import sys
from io import BytesIO
from itertools import pairwise
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageOps

from .motion_library import read_json, sha256
from .video_editing_browser_boot import audit_browser_boot_engine
from .video_editing_browser_clocks import (
    FRUIT_LIST_FONTS,
    LIVE_SPLIT_GROUPS,
    SPLIT_VERTICAL,
    audit_card_family_engine,
    audit_split_engine,
)
from .video_editing_contracts import SemanticBeat, Transcript

ROTATION_GROUP = "CX-G04"
STRIP_CARD_GROUP = "CX-G05"
STRIP_CARD_DESIGN = "tengli-strip-cards-v1"
BROWSER_CARD_GROUPS = (ROTATION_GROUP, STRIP_CARD_GROUP)
ANALYSIS_BOARD_GROUP = "CX-G08"
TEXTURE_WORD_GROUP = "CX-G09"
CIRCULAR_MEDIA_GROUP = "CX-G10"
THREE_ITEM_SCENE_GROUPS = (
    ANALYSIS_BOARD_GROUP,
    TEXTURE_WORD_GROUP,
    CIRCULAR_MEDIA_GROUP,
)
THREE_ITEM_SCENE_DESIGN = "tengli-browser-three-item-v1"
CLEAN_BROWSER_SCENE_GROUPS = (STRIP_CARD_GROUP, *THREE_ITEM_SCENE_GROUPS)
ROTATION_MATTE = "model-01eb6a29a5c4d8edb30b"
ROTATION_EVENTS = tuple(f"/items/{i}/at" for i in range(3))
ROTATION_IMAGES = tuple(f"/items/{i}/image" for i in range(3))
ROTATION_LABELS = tuple(f"/items/{i}/label" for i in range(3))
_ROTATION_REF = "tengli-card-rotation-"
_STRIP_CARD_REF = "tengli-strip-card-"
_SPLIT_REF = "tengli-browser-split-"
_PRESENTER_BINDINGS = {
    ROTATION_GROUP: (_ROTATION_REF, "native_rotation_presenter_window"),
    STRIP_CARD_GROUP: (_STRIP_CARD_REF, "native_strip_card_presenter_window"),
    ANALYSIS_BOARD_GROUP: (
        "tengli-analysis-board-",
        "native_analysis_board_presenter_window",
    ),
    TEXTURE_WORD_GROUP: (
        "tengli-texture-word-",
        "native_texture_word_presenter_window",
    ),
    CIRCULAR_MEDIA_GROUP: (
        "tengli-circular-media-",
        "native_circular_media_presenter_window",
    ),
}
_FPS = 30
_OWNER = Path("src/engines/workspace/商业口播_可编辑改造_20261104")
_MEDIA = _OWNER / "unified/core/media.py"
_MATTE = (
    _OWNER / "新增批次/晨曦_Broll画面排版_7704151605411546024/trial-CXBR02/matting.py"
)
_MEDIA_SHA = "3838f78d7e7062bda2365ff870dc64cb02493567b90378e09bb220712bd49fdf"
_MATTE_SHA = "6c02b92b3d8588d7e4c947bd9adbe3440d1d491a676456a80cc08d3beb00ea12"
_STRIP_TIMELINE_SHA = "b3d9bf69f9f11a8a1b699eacede74baad1bb379cb0b3d3d9fc71e4593a0e1194"
_CIRCULAR_TRACK_ANCHORS = (6, 21, 40)
_CIRCULAR_FIRST_VISIBLE = (7, 22, 42)
_STRIP_ENTRIES = (9, 26, 48)
# Native G05 draws the presenter at (130, 500) with this size.
_STRIP_PRESENTER_SIZE = (500, 780)
# The shared native draw interprets the input as a 1600 x 2400 image
# before applying each scene's uniform scale and translation.
_THREE_ITEM_PRESENTER_SIZE = (800, 1200)
_SPECIAL = Path("commercial_runtime/special.py")
_DRAW = (
    '([g,f])=>{engine.draw(exportCanvas,g,f/30,"B");'
    'return exportCanvas.toDataURL("image/png").split(",")[1]}'
)
_LIVE_DRAW = """
async ([group, frame, uri, slot, liveBackground]) => {
  const person = new Image();
  person.src = uri;
  await person.decode();
  const state = engine.states[group].B;
  state[slot] = person;
  if (liveBackground) state.background = person;
  engine.draw(exportCanvas, group, frame / 30, "B");
  return exportCanvas.toDataURL("image/png").split(",")[1];
}
"""


def _audit(package: Path, group: dict) -> None:
    if group["id"] in THREE_ITEM_SCENE_GROUPS:
        audit_browser_boot_engine(package, group)
    elif group["id"] in LIVE_SPLIT_GROUPS:
        audit_split_engine(package, group)
    else:
        audit_card_family_engine(package, group)
    if group["id"] == STRIP_CARD_GROUP:
        timeline = (package / group["entry"]).with_name("g05-timeline.json")
        if sha256(timeline) != _STRIP_TIMELINE_SHA:
            raise ValueError("Original G05 strip-card timeline changed")
    if sha256(package / _MEDIA) != _MEDIA_SHA or (
        group["id"] != SPLIT_VERTICAL and sha256(package / _MATTE) != _MATTE_SHA
    ):
        raise ValueError("Original video sampler or presenter matte changed")


def _first_motion_frame(at: float, index: int) -> int:
    return round(at * 1000) * _FPS // 1000 + (1 if index else 0)


def browser_sound_entry_key(shot: dict) -> str | None:
    group = shot["group_id"]
    if group == STRIP_CARD_GROUP:
        return "strip_card_entry"
    if group == ROTATION_GROUP:
        return "rotation_entry"
    if group in THREE_ITEM_SCENE_GROUPS:
        presenter = shot["config"].get("presenter")
        if isinstance(presenter, str) and presenter.startswith(
            "input://" + _PRESENTER_BINDINGS[group][0]
        ):
            return "three_item_entry"
    return None


def browser_card_entry_frame(shot: dict, fps: int, path: str) -> int:
    key = browser_sound_entry_key(shot)
    if key is None or shot["layer"] != "scene" or fps != _FPS:
        raise ValueError("Browser card sound needs the original 30 fps scene")
    index = ROTATION_EVENTS.index(path)
    start_ms = round(shot["start_seconds"] * 1000)
    config = shot["config"]
    if key == "strip_card_entry":
        local = _strip_card_entries(
            [item["at"] for item in config["items"]],
            round(config["duration"] * _FPS),
        )[index]
    elif key == "three_item_entry":
        local = three_item_entry_frame(
            shot["group_id"], config["items"][index]["at"], index
        )
    else:
        local = _first_motion_frame(config["items"][index]["at"], index)
    # The original overlay enable waits for the first output frame at or after
    # the shot boundary. The secondary stream's setpts truncates its origin.
    return max((start_ms * fps + 999) // 1000, start_ms * fps // 1000 + local)


def rotation_source_clock(
    native: dict,
    assets: dict[str, dict],
    transcript: Transcript,
    *,
    split: bool = False,
) -> dict[str, Any]:
    slots = {row["path"]: row["asset_id"] for row in native["media"]}
    source_id = slots.get("/presenter")
    asset = assets.get(source_id, {}) if source_id else {}
    clock = native["clock"]
    start, end = clock["start_ms"], clock["end_ms"]
    if (
        asset.get("kind") != "original_video"
        or asset.get("sha256") != transcript.source_sha256
        or not 0 <= start < end <= transcript.duration_ms
        or clock["native_fps"] != _FPS
    ):
        raise ValueError(
            "Original browser scene requires its current measured presenter"
            if split or native.get("group_id") in THREE_ITEM_SCENE_GROUPS
            else "Rotating cards require their current, measured presenter"
        )
    prefix, policy = (
        (_SPLIT_REF, "native_split_presenter_window")
        if split
        else _PRESENTER_BINDINGS[native.get("group_id", ROTATION_GROUP)]
    )
    return {
        "policy": policy,
        "media_path": "/presenter",
        "asset_id": source_id,
        "source_sha256": transcript.source_sha256,
        "source_start_ms": start,
        "source_end_ms": end,
        "binding_id": f"{prefix}{transcript.source_sha256}-{start}-{end}",
        **(
            {"native_matte_id": ROTATION_MATTE}
            if not split or native["group_id"] != SPLIT_VERTICAL
            else {}
        ),
    }


def compile_rotation_clock(
    package: Path,
    group: dict,
    config: dict,
    resources: dict[str, str],
    native: dict,
    assets: dict[str, dict],
) -> dict[str, Any]:
    _audit(package, group)
    if set((*FRUIT_LIST_FONTS, ROTATION_MATTE)) - resources.keys():
        raise ValueError("Bind the original card fonts and presenter matte explicitly")
    return rotation_card_clock(
        config, native, assets, strip=group["id"] == STRIP_CARD_GROUP
    )


def three_item_entry_frame(group_id: str, at: float, index: int) -> int:
    milliframes = round(at * 1000) * _FPS
    if group_id != CIRCULAR_MEDIA_GROUP:
        return (milliframes + 999) // 1000
    anchor = _CIRCULAR_TRACK_ANCHORS[index]
    first = _CIRCULAR_FIRST_VISIBLE[index]
    # G10 rounds the current track position to the nearest frame. Match the
    # browser's floating-point expression at the half-frame boundary.
    frame = (milliframes + 1000 * (first - anchor) + 499) // 1000
    track_position = (frame / _FPS - at) * _FPS + anchor
    return frame + int(track_position < first - 0.5)


def validate_three_item_scene(
    config: dict,
    native: dict,
    resources: dict[str, str],
    assets: dict[str, dict],
    beat: SemanticBeat,
) -> dict[str, Any]:
    """Check the original two-character labels and current presenter/media slots."""
    if ROTATION_MATTE not in resources:
        raise ValueError("Three-item scene needs the original presenter matte")
    duration, items = config["duration"], config["items"]
    if not 0 < duration <= 30 or len(items) != 3 or config["background"] is not None:
        raise ValueError(
            "Three-item scene needs its original background and three items"
        )
    circular = beat.group_id == CIRCULAR_MEDIA_GROUP
    media = {row["path"]: row["asset_id"] for row in native["media"]}
    required_paths = {"/presenter", *ROTATION_IMAGES} if circular else {"/presenter"}
    if media.keys() != required_paths:
        raise ValueError("Three-item scene needs its current presenter and media slots")
    text = {row["path"]: row for row in native["text"]}
    events = {row["path"]: row for row in native["events"]}
    frames = round(duration * _FPS)
    first_frames: list[int] = []
    previous_at = -1.0
    for index, (item, label_path, event_path) in enumerate(
        zip(items, ROTATION_LABELS, ROTATION_EVENTS, strict=True)
    ):
        label, event = text.get(label_path), events.get(event_path)
        at, enter = item["at"], item["enter"]
        frame = three_item_entry_frame(beat.group_id, at, index)
        if (
            not label
            or not event
            or event["edge"] != "start"
            or event["token_id"] != label["token_ids"][0]
            or not 1 <= len(item["label"]) <= 2
            or bool(item["image"]) != circular
            or not 0 <= at < duration
            or at <= previous_at
            or (first_frames and frame <= first_frames[-1])
            or frame >= frames
            or not 0 < enter < duration - at
        ):
            raise ValueError(
                "Three-item labels need separate measured frames and room to appear"
            )
        first_frames.append(frame)
        previous_at = at
    if circular:
        picture_ids = [media[path] for path in ROTATION_IMAGES]
        pictures = [assets.get(aid, {}) for aid in picture_ids]
        if (
            any(
                p.get("kind") != "image" or p.get("source") != "project_upload"
                for p in pictures
            )
            or len({p["sha256"] for p in pictures}) != 3
            or len(beat.relation_items) != 3
            or any(
                item.asset_ids != [aid]
                or item.native_text_paths != [label_path]
                or item.native_media_paths != [image_path]
                or item.first_token_id != text[label_path]["token_ids"][0]
                or item.last_token_id != text[label_path]["token_ids"][-1]
                for item, aid, label_path, image_path in zip(
                    beat.relation_items,
                    picture_ids,
                    ROTATION_LABELS,
                    ROTATION_IMAGES,
                    strict=True,
                )
            )
        ):
            raise ValueError(
                "Circle media needs three distinct current images "
                "matched to the spoken items"
            )
    return {"fps": _FPS, "frames": frames, "first_visible_frames": first_frames}


def rotation_card_clock(
    config: dict, native: dict, assets: dict[str, dict], *, strip: bool = False
) -> dict[str, Any]:
    """Validate the card geometry's current image and measured focus inputs."""
    duration = config["duration"]
    items = config["items"]
    frames = round(duration * _FPS)
    events = {row["path"]: row for row in native["events"]}
    texts = {row["path"]: row for row in native["text"]}
    media = {row["path"]: row["asset_id"] for row in native["media"]}
    if (
        not 0 < duration <= 30
        or len(items) != 3
        or config["background"] is not None
        or set(media) != {"/presenter", *ROTATION_IMAGES}
        or any(
            assets.get(media[path], {}).get("kind") != "image"
            or assets[media[path]].get("source") != "project_upload"
            for path in ROTATION_IMAGES
        )
        or len({assets[media[path]]["sha256"] for path in ROTATION_IMAGES}) != 3
    ):
        raise ValueError("Rotating cards need three distinct current pictures")
    for i, item in enumerate(items):
        event = events.get(ROTATION_EVENTS[i])
        text = texts.get(ROTATION_LABELS[i])
        if (
            not event
            or not text
            or event["edge"] != "start"
            or event["token_id"] != text["token_ids"][0]
            or not 1 <= len(item["label"]) <= 4
            or not 0 < item["enter"] <= 2
            or item["at"] + item["enter"] >= duration
        ):
            raise ValueError(
                "Each rotating card needs a short spoken label at its focus"
            )
    if strip:
        starts = [item["at"] for item in items]
        if (
            starts[0] < 0
            or any(a >= b for a, b in pairwise(starts))
            or starts[-1] + items[-1]["enter"] > (frames - 1) / _FPS
        ):
            raise ValueError(
                "The three original G05 cards need ordered, visible entries"
            )
        return {
            "policy": "original_g05_strip_card_clock",
            "timeline_sha256": _STRIP_TIMELINE_SHA,
            "frames": frames,
            "entry_seconds": starts,
            "first_visible_frames": _strip_card_entries(starts, frames),
            "timing_review": "unreviewed",
        }
    if (
        items[0]["at"] != 0
        or items[1]["at"] <= 0
        or items[1]["at"] + items[1]["enter"] >= items[2]["at"]
        or items[2]["at"] + items[2]["enter"] > (frames - 1) / _FPS
    ):
        raise ValueError(
            "The first card starts with speech and both switches must settle"
        )
    return {
        "policy": "original_three_card_focus_switches",
        "frames": frames,
        "first_card_visible_on_open": True,
        "opening_expansion_frames": 14,
        "focus_seconds": [item["at"] for item in items],
        "first_motion_frames": [
            _first_motion_frame(item["at"], i) for i, item in enumerate(items)
        ],
        "timing_review": "unreviewed",
    }


def _strip_card_entries(starts: list[float], frames: int) -> list[int]:
    # G05 mapClock maps measured word times to the original 9, 26, 48 frames.
    # The original browser rounds the source time to its nearest frame.
    keys = [(0.0, 0.0), *zip(starts, (n / _FPS for n in _STRIP_ENTRIES), strict=True)]
    visible: list[int] = []
    for frame in range(frames):
        time = frame / _FPS
        source = keys[-1][1] + time - keys[-1][0]
        for (previous_at, previous), (at, entry) in pairwise(keys):
            if time <= at:
                source = previous + (entry - previous) * (
                    (time - previous_at) / (at - previous_at or 1)
                )
                break
        source_frame = math.floor(source * _FPS + 0.5)
        while len(visible) < len(_STRIP_ENTRIES) and (
            source_frame >= _STRIP_ENTRIES[len(visible)]
        ):
            visible.append(frame)
    if len(set(visible)) != len(_STRIP_ENTRIES):
        raise ValueError(
            "Original G05 card entrances must occupy separate output frames"
        )
    return visible


def _png_uri(image: Image.Image) -> str:
    data = BytesIO()
    image.save(data, format="PNG", compress_level=1)
    return "data:image/png;base64," + base64.b64encode(data.getvalue()).decode("ascii")


def _presenter_plate(image: Image.Image) -> Image.Image:
    # G04 draws its 1600 x 2400 input at 0.78 scale, translated by (-287, -79).
    # Place the live matte on a half-resolution plate in that input space.
    scale = 0.78 * 2
    width, height = round(720 / scale), round(1280 / scale)
    fitted = ImageOps.contain(image, (width, height), Image.Resampling.LANCZOS)
    plate = Image.new("RGBA", (800, 1200))
    plate.paste(
        fitted,
        (
            round(287 / scale) + (width - fitted.width) // 2,
            round(79 / scale) + (height - fitted.height) // 2,
        ),
    )
    return plate


def _split_presenter(image: Image.Image, group: str) -> Image.Image:
    if group == SPLIT_VERTICAL:
        return ImageOps.fit(image, (540, 960), Image.Resampling.LANCZOS)
    # The original outlined person occupies a 346 x 559 input rectangle.
    return _presenter_in_slot(image, (346, 559))


def _presenter_in_slot(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    width, height = size
    fitted = ImageOps.contain(image, size, Image.Resampling.LANCZOS)
    plate = Image.new("RGBA", size)
    plate.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return plate


def install_rotation_export(package: Path, root: Path) -> None:
    if "--job" not in sys.argv:
        return
    path = Path(sys.argv[sys.argv.index("--job") + 1]).resolve()
    if path.parent != root / "plans":
        return
    job = read_json(path)
    group = job["group_id"]
    split = group in LIVE_SPLIT_GROUPS
    strip = group == STRIP_CARD_GROUP
    three_item = group in THREE_ITEM_SCENE_GROUPS
    if not split and group not in _PRESENTER_BINDINGS:
        return
    prefix = _SPLIT_REF if split else _PRESENTER_BINDINGS[group][0]
    reference = job["config"].get("presenter", "")
    if not isinstance(reference, str) or not reference.startswith("input://" + prefix):
        return
    match = re.fullmatch(
        r"input://" + prefix + r"([a-f0-9]{64})-(\d+)-(\d+)", reference
    )
    if not match:
        raise ValueError("Invalid original browser presenter window")
    digest, start, end = match[1], int(match[2]), int(match[3])

    from playwright.sync_api import Page

    sys.path[:0] = [str(package), str(package / _OWNER)]
    try:
        special: Any = importlib.import_module("commercial_runtime.special")
        media: Any = importlib.import_module("unified.core.media")
    finally:
        del sys.path[:2]
    if (
        Path(special.__file__).resolve() != package / _SPECIAL
        or Path(media.__file__).resolve() != package / _MEDIA
    ):
        raise ValueError(
            "Live browser scenes must use the pinned original browser and sampler"
        )
    browser_drawer, evaluate = special.browser_drawer, Page.evaluate

    def with_live_person(card: dict, config: dict) -> tuple[Any, dict]:
        if card["id"] != group:
            return browser_drawer(card, config)
        _audit(package, card)
        source = Path(special.resolve(config["presenter"], True))
        if sha256(source) != digest or config["duration"] != (end - start) / 1000:
            raise ValueError("Original browser presenter identity or duration changed")
        matte = None
        if group != SPLIT_VERTICAL:
            spec = importlib.util.spec_from_file_location(
                "tengli_browser_presenter_matte", package / _MATTE
            )
            if spec is None or spec.loader is None:
                raise ValueError("Cannot load the original presenter matte")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            matte = module.HumanMatte(
                special.resolve("input://" + ROTATION_MATTE, True),
                root / "cache" / "browser-rotation" / path.stem,
            )
        asset = media.inspect_asset(
            {
                "path": str(source),
                "offset_seconds": start / 1000,
                "duration_seconds": (end - start) / 1000,
                "end_policy": "error",
            }
        )
        boot = _png_uri(Image.new("RGBA", (1, 1)))
        draw, meta = browser_drawer(card, {**config, "presenter": boot})

        def draw_live(frame: int) -> Image.Image:
            source_frame = media.asset_frame(asset, frame / _FPS, native_size=True)
            if matte is not None:
                source_frame = matte.apply(
                    source_frame, f"{digest}-{start}-{end}-{frame}"
                )
            plate = (
                _split_presenter(source_frame, group)
                if split
                else _presenter_in_slot(source_frame, _STRIP_PRESENTER_SIZE)
                if strip
                else _presenter_in_slot(source_frame, _THREE_ITEM_PRESENTER_SIZE)
                if three_item
                else _presenter_plate(source_frame)
            )
            uri = _png_uri(plate)
            applied = False

            def evaluate_live(page: Page, expression: str, arg: Any = None) -> Any:
                nonlocal applied
                if expression == _DRAW:
                    applied = True
                    return evaluate(
                        page,
                        _LIVE_DRAW,
                        [
                            *arg,
                            uri,
                            "presenter" if split else "person",
                            group == SPLIT_VERTICAL,
                        ],
                    )
                return evaluate(page, expression, arg)

            cast(Any, Page).evaluate = evaluate_live
            try:
                image = draw(frame)
            finally:
                cast(Any, Page).evaluate = evaluate
            if not applied:
                raise ValueError("Original browser draw did not receive a live frame")
            return image

        return draw_live, {
            **meta,
            **(
                {
                    "tengli_three_item_entries": [
                        three_item_entry_frame(group, item["at"], i)
                        for i, item in enumerate(config["items"])
                    ]
                }
                if three_item
                else {}
            ),
            "media_capability": "original split draw with current presenter frames"
            if split
            else "original G05 draw with current matte frames"
            if strip
            else f"original {group.removeprefix('CX-')} draw with current matte frames"
            if three_item
            else "original G04 draw with current matte frames",
        }

    special.browser_drawer = with_live_person
