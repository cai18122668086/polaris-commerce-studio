"""Supply a measured live presenter to the original G04 image slot."""

import base64
import importlib
import importlib.util
import re
import sys
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageOps

from .motion_library import read_json, sha256
from .video_editing_browser_clocks import (
    FRUIT_LIST_FONTS,
    LIVE_SPLIT_GROUPS,
    SPLIT_VERTICAL,
    audit_card_family_engine,
    audit_split_engine,
)
from .video_editing_contracts import Transcript

ROTATION_GROUP = "CX-G04"
ROTATION_MATTE = "model-01eb6a29a5c4d8edb30b"
ROTATION_EVENTS = tuple(f"/items/{i}/at" for i in range(3))
ROTATION_IMAGES = tuple(f"/items/{i}/image" for i in range(3))
ROTATION_LABELS = tuple(f"/items/{i}/label" for i in range(3))
_ROTATION_REF = "tengli-card-rotation-"
_SPLIT_REF = "tengli-browser-split-"
_FPS = 30
_OWNER = Path("src/engines/workspace/商业口播_可编辑改造_20261104")
_MEDIA = _OWNER / "unified/core/media.py"
_MATTE = (
    _OWNER / "新增批次/晨曦_Broll画面排版_7704151605411546024/trial-CXBR02/matting.py"
)
_MEDIA_SHA = "3838f78d7e7062bda2365ff870dc64cb02493567b90378e09bb220712bd49fdf"
_MATTE_SHA = "6c02b92b3d8588d7e4c947bd9adbe3440d1d491a676456a80cc08d3beb00ea12"
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
    if group["id"] in LIVE_SPLIT_GROUPS:
        audit_split_engine(package, group)
    else:
        audit_card_family_engine(package, group)
    if sha256(package / _MEDIA) != _MEDIA_SHA or (
        group["id"] != SPLIT_VERTICAL and sha256(package / _MATTE) != _MATTE_SHA
    ):
        raise ValueError("Original video sampler or presenter matte changed")


def _first_motion_frame(at: float, index: int) -> int:
    return round(at * 1000) * _FPS // 1000 + (1 if index else 0)


def rotation_entry_frame(shot: dict, fps: int, path: str) -> int:
    if shot["group_id"] != ROTATION_GROUP or shot["layer"] != "scene" or fps != _FPS:
        raise ValueError("Rotating card sound needs the original 30 fps scene")
    index = ROTATION_EVENTS.index(path)
    start_ms = round(shot["start_seconds"] * 1000)
    local = _first_motion_frame(shot["config"]["items"][index]["at"], index)
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
            if split
            else "Rotating cards require their current, measured presenter"
        )
    prefix = _SPLIT_REF if split else _ROTATION_REF
    return {
        "policy": "native_split_presenter_window"
        if split
        else "native_rotation_presenter_window",
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
    return rotation_card_clock(config, native, assets)


def rotation_card_clock(
    config: dict, native: dict, assets: dict[str, dict]
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
    fitted = ImageOps.contain(image, (346, 559), Image.Resampling.LANCZOS)
    plate = Image.new("RGBA", (346, 559))
    plate.paste(fitted, ((346 - fitted.width) // 2, (559 - fitted.height) // 2))
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
    if not split and group != ROTATION_GROUP:
        return
    prefix = _SPLIT_REF if split else _ROTATION_REF
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
            "Rotating cards must use the pinned original browser and sampler"
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
            "media_capability": "original split draw with current presenter frames"
            if split
            else "original G04 draw with current matte frames",
        }

    special.browser_drawer = with_live_person
