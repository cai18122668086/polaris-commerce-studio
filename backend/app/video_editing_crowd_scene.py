"""Bind the original W-R09 crowd, its project images and its discrete clock."""

import importlib
import sys
from itertools import pairwise
from pathlib import Path
from typing import Any

from PIL import Image

from .motion_library import sha256
from .video_editing_contracts import SemanticBeat
from .video_editing_virtual_clock import first_visible_frame

CROWD_GROUP = "W-R09"
CROWD_TEMPLATE_ID = "unified-crowd-v1"
CROWD_PRESENTER = "/media/presenter/path"
CROWD_PAPER = "/media/previous_paper/path"
CROWD_SILHOUETTES = tuple(f"/media/silhouettes/{i}/path" for i in range(7))
CROWD_IMAGE_PATHS = (CROWD_PAPER, *CROWD_SILHOUETTES)
CROWD_IMAGE_SIZES = dict(
    zip(
        CROWD_IMAGE_PATHS,
        (
            (540, 960),
            (210, 240),
            (260, 240),
            (205, 400),
            (120, 310),
            (120, 320),
            (305, 425),
            (145, 410),
        ),
        strict=True,
    )
)
CROWD_SOUNDS = ("paper_exit", "title_in", "silhouette_entries/0")
CROWD_FULL_FRAME = [0, 0, 540, 960]
_EVENTS = "/timing/events/"
_CAPTION = "/content/captions/0/"
_OWNER = Path("src/engines/workspace/商业口播_可编辑改造_20261104")
_GLYPHS = Path("unified/editable_glyphs.py")
_SERIF = Path("assets/fonts/Source_Han_Serif_SC_Heavy--152bc1c4535b.ttf")
_GLYPH_IDENTITIES = (
    (
        _OWNER / _GLYPHS,
        "a463e8ec0c5eec7a36e45ed14b4997b630432e86ac54da6a5bdd0d3f57e3aac3",
    ),
    (
        _OWNER / "unified/core/text.py",
        "1aa8b98a1124f84c1e1a9d830549cc137807e5b93c706f00edbe38c829d45249",
    ),
    (
        _OWNER / "unified/core/typography.py",
        "5fbf8fff517ff0d9fd551d9d661356499950a2cd246258e0eef1d2ed07b83333",
    ),
    (_SERIF, "152bc1c4535b8bcb6ec52e0aa4563bced6f43206c59ba32fbfa34a6a192a8304"),
)


def crowd_image_slots(files: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    slots: dict[str, list[str]] = {path: [] for path in CROWD_IMAGE_PATHS}
    for asset_id, asset in sorted(files.items()):
        if asset.get("kind") != "image" or asset.get("source") != "project_upload":
            continue
        try:
            with Image.open(asset["path"]) as image:
                path = next(
                    (
                        key
                        for key, size in CROWD_IMAGE_SIZES.items()
                        if size == image.size
                    ),
                    None,
                )
                if path is None:
                    continue
                low, high = image.convert("RGBA").getchannel("A").getextrema()
                if not isinstance(low, int) or not isinstance(high, int):
                    continue
                if (path == CROWD_PAPER and low == 255) or (
                    path != CROWD_PAPER
                    and image.format == "PNG"
                    and low < 255
                    and high > 0
                ):
                    slots[path].append(asset_id)
        except (OSError, ValueError):
            continue
    return slots


def validate_crowd_images(
    media: dict[str, str], images: dict[str, str], slots: dict[str, list[str]] | None
) -> None:
    if (
        any(media.get(path) not in images for path in CROWD_IMAGE_PATHS)
        or len({images[media[path]] for path in CROWD_IMAGE_PATHS})
        != len(CROWD_IMAGE_PATHS)
        or slots is not None
        and any(media.get(path) not in slots[path] for path in CROWD_IMAGE_PATHS)
    ):
        raise ValueError("Crowd needs a verified paper and seven different alpha slots")


def validate_crowd_anchors(beat: SemanticBeat, native: dict) -> None:
    events = {row["path"]: row for row in native["events"]}
    text = {row["path"]: row for row in native["text"]}
    caption, title = text[_CAPTION + "text"], text["/content/title"]
    paper, heading = (events[_EVENTS + path] for path in CROWD_SOUNDS[:2])
    silhouettes = [events[_EVENTS + f"silhouette_entries/{i}"] for i in range(7)]
    begin, end = (events[_CAPTION + key] for key in ("start", "end"))
    start, finish = (native["clock"][key] for key in ("start_ms", "end_ms"))
    duration = (finish - start) / 1000
    if (
        beat.relation != "explanation"
        or beat.relation_items
        or not 0.12 <= paper["value"] <= 0.90
        or heading["edge"] != "start"
        or heading["token_id"] != title["token_ids"][0]
        or not paper["value"] + 0.08
        <= heading["value"]
        <= silhouettes[0]["value"] - 0.10
        or any(row["edge"] != "start" for row in silhouettes)
        or any(a["value"] + 1 / 30 > b["value"] for a, b in pairwise(silhouettes))
        or not silhouettes[-1]["value"] + 0.35 <= duration
        or not 1 <= len(title["text"]) <= 6
        or not 1 <= len(caption["text"]) <= 14
        or any(char.isspace() for char in title["text"] + caption["text"])
        or (begin["edge"], begin["token_id"]) != ("start", caption["token_ids"][0])
        or (end["edge"], end["token_id"]) != ("end", caption["token_ids"][-1])
        or not heading["value"] <= begin["value"] <= end["value"] - 0.45
    ):
        raise ValueError(
            "Original crowd needs ordered measured entries and spoken text"
        )


def crowd_title_native_frame(package: Path, config: dict) -> int:
    """Measure the original title ink that actually enters the left frame edge."""
    package = package.resolve()
    if any(sha256(package / path) != digest for path, digest in _GLYPH_IDENTITIES):
        raise ValueError("Original crowd title measurement sources changed")
    sys.path[:0] = [str(package), str(package / _OWNER)]
    try:
        glyphs: Any = importlib.import_module("unified.editable_glyphs")
    finally:
        del sys.path[:2]
    if (
        Path(glyphs.__file__).resolve() != package / _OWNER / _GLYPHS
        or glyphs.SERIF.resolve() != package / _SERIF
    ):
        raise ValueError("Crowd title needs the pinned original glyph engine")
    alpha = glyphs.canvas(
        {"_measurements": {}, "_layout_options": config["layout"]},
        config["content"]["title"],
        "title",
        (12, 120, 528, 250),
        preferred=110,
        path=glyphs.SERIF,
        slant=0.16,
    ).getchannel("A")
    for frame in range(10, 23):
        ease = 1 - (1 - min(1, (frame / 30 - 0.30) / 0.43)) ** 3
        left = round(540 * (1 - ease))
        _, highest = alpha.crop((left, 0, 540, 960)).getextrema()
        if round(highest * ease) > 0:
            return frame
    raise ValueError("Original crowd title never enters the canvas")


def crowd_action_frame(timing: dict, event: str, title_frame: int | None = None) -> int:
    # build12 interpolates the original virtual seconds then rounds to a frame.
    # The original draw eases from .22, .30 and .72 seconds, respectively.
    required = dict(zip(CROWD_SOUNDS, (7, title_frame, 22), strict=True))[event]
    if required is None:
        raise ValueError("Crowd title cue needs its measured original ink")
    events = timing["events"]
    actual = [
        0,
        events["paper_exit"],
        events["title_in"],
        *events["silhouette_entries"],
        timing["duration_seconds"],
    ]
    virtual = [0, 0.22, 0.30, *(0.72 + i * 0.035 for i in range(7)), 2]
    return first_visible_frame(actual, virtual, required)
