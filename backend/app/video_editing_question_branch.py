"""Use the original W-R18 question branch independently of the smoke ending."""

import importlib
import sys
from collections.abc import Callable
from functools import cached_property
from pathlib import Path
from typing import Any, cast

from PIL import Image

from .motion_library import atomic_json, read_json, sha256
from .video_editing_media_clocks import clock_profile

QUESTION_GROUP = "W-R18"
QUESTION_BRANCH = "question"
QUESTION_ENTRY = "/timing/events/question_in"
QUESTION_FONT = "font-06b2048c592b1dae"
_OWNER = Path("src/engines/workspace/商业口播_可编辑改造_20261104")
_ORIGINAL_SCENE = Path(
    "src/engines/workspace/雯羽_小羽毛_两条拆解_20261103/experiments"
    "/final-three-rework/build.py"
)


def question_variant_template(template: dict, *, embedded_caption: bool = True) -> dict:
    """Describe the exposed original question inputs alongside the smoke defaults."""
    presenter = {k: v for k, v in template["media"]["presenter"].items() if k != "crop"}
    return {
        **template,
        "branch": QUESTION_BRANCH,
        "content": {
            "question": "",
            "captions": [{"start": 0.0, "end": 1.0, "text": ""}]
            if embedded_caption
            else [],
        },
        "media": {"presenter": presenter},
        "layout": {**template["layout"], "minimum_font_px": 31},
        "timing": {
            **template["timing"],
            "events": {"question_in": 0.0, "dissolve_in": 1.1},
        },
    }


def question_overlay_entry_frame(shot: dict, fps: int) -> int:
    if (
        shot["group_id"] != QUESTION_GROUP
        or shot["layer"] != "overlay"
        or shot["config"].get("branch") != QUESTION_BRANCH
        or shot["config"]["timing"]["events"]["question_in"] != 0
        or fps != 30
    ):
        raise ValueError("Question sound needs the original inset entry at local zero")
    # The pinned episode compositor enables an overlay with gte(t, shot_start).
    start_ms = round(shot["start_seconds"] * 1000)
    return (start_ms * fps + 999) // 1000


class _DeferredOriginalImage:
    def __init__(self, loader: Callable[[str], Image.Image], path: str) -> None:
        self._loader = loader
        self._path = path

    @cached_property
    def image(self) -> Image.Image:
        return self._loader(self._path)

    def __getattr__(self, name: str) -> Any:
        # If a future draw does use the image, the original loader still has to
        # read the exact original file. This object supplies no pixels itself.
        return getattr(self.image, name)


def install_native_question_branch(package: Path, root: Path) -> None:
    if "--job" not in sys.argv:
        return
    job_path = Path(sys.argv[sys.argv.index("--job") + 1]).resolve()
    if job_path.parent != root / "plans":
        return
    job = read_json(job_path)
    if (
        job["group_id"] != QUESTION_GROUP
        or job["config"].get("branch") != QUESTION_BRANCH
        or "smoke_alpha_sequence" in job["config"].get("media", {})
    ):
        return
    profile = clock_profile(QUESTION_GROUP)
    originals = [
        _OWNER / "unified/build12.py",
        _OWNER / "unified/core/media.py",
        _ORIGINAL_SCENE,
    ]
    if not profile or any(
        sha256(package / path) != profile["source_files"][path.as_posix()]
        for path in originals
    ):
        raise ValueError("Original question and smoke branch code changed")

    sys.path[:0] = [str(package / _OWNER), str(package)]
    try:
        media = importlib.import_module("unified.core.media")
    finally:
        del sys.path[:2]
    if (
        media.__file__ is None
        or Path(media.__file__).resolve() != package / originals[1]
    ):
        raise ValueError("Question branch must use the original media loader")

    load_image = media.load_image
    directory = package / _ORIGINAL_SCENE.parent / "assets"
    smoke_files = {directory / f"smoke-{i:02}.png" for i in range(18)}
    recorded = False

    def defer_unused_smoke(path: str) -> Image.Image | _DeferredOriginalImage:
        nonlocal recorded
        if Path(path) not in smoke_files:
            return cast(Image.Image, load_image(path))
        if not recorded:
            atomic_json(
                root / "compatibility" / f"{job_path.stem}-inactive-smoke.json",
                {
                    "group_id": QUESTION_GROUP,
                    "branch": QUESTION_BRANCH,
                    "input_sha256": sha256(job_path),
                    "policy": "defer original smoke file reads until pixel access",
                },
            )
            recorded = True
        return _DeferredOriginalImage(load_image, path)

    cast(Any, media).load_image = defer_unused_smoke
