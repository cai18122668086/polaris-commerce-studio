"""Export pinned native card pixels with alpha over the episode's source clock."""

import base64
import importlib
import sys
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from PIL import Image

from .motion_library import read_json, sha256
from .video_editing_browser_clocks import CARD_ENGINE_SHA, CARD_GROUP, SPLIT_WRAPPER_SHA
from .video_editing_contracts import Transcript

CARD_LIVE_PREFIX = "tengli-card-live-"
_ORIGINAL_DRAW = (
    'f=>{engine.draw(exportCanvas,f,"city",true);'
    'return exportCanvas.toDataURL("image/png").split(",")[1]}'
)
_ALPHA_DRAW = """
f => {
  const context = exportCanvas.getContext("2d");
  const fillRect = context.fillRect;
  let plates = 0;
  context.fillRect = function (x, y, w, h) {
    if (x === 0 && y === 0 && w === exportCanvas.width && h === exportCanvas.height) {
      plates++;
      return;
    }
    fillRect.call(this, x, y, w, h);
  };
  try {
    engine.draw(exportCanvas, f, "city", false);
  } finally {
    delete context.fillRect;
  }
  if (plates !== 1) throw Error("Original three-card plate changed");
  return exportCanvas.toDataURL("image/png").split(",")[1];
}
"""


def card_live_clock(
    package: Path, native: dict, assets: dict[str, dict], transcript: Transcript
) -> dict[str, Any]:
    videos = {
        row["path"]: row["asset_id"]
        for row in native["media"]
        if assets[row["asset_id"]].get("kind")
        in {"original_video", "video", "generated_video"}
    }
    source_id = videos.get("/background", "")
    asset = assets.get(source_id, {})
    clock = native["clock"]
    if (
        len(videos) != 1
        or not source_id.startswith("source-")
        or asset.get("kind") != "original_video"
        or asset.get("sha256") != transcript.source_sha256
        or not 0 <= clock["start_ms"] < clock["end_ms"] <= transcript.duration_ms
        or clock["native_fps"] != 30
        or sha256(package / "commercial_runtime/special.py") != SPLIT_WRAPPER_SHA
    ):
        raise ValueError(
            "Live cards require the audited browser and current source clock"
        )
    return {
        "policy": "native_card_alpha_on_continuous_episode_source",
        "media_path": "/background",
        "asset_id": source_id,
        "source_sha256": transcript.source_sha256,
        **clock,
    }


def install_live_card_export(package: Path, root: Path) -> None:
    if "--job" not in sys.argv:
        return
    job_path = Path(sys.argv[sys.argv.index("--job") + 1]).resolve()
    if job_path.parent != root / "plans":
        return
    job = read_json(job_path)
    reference = job["config"].get("background")
    prefix = "input://" + CARD_LIVE_PREFIX
    if (
        job["group_id"] != CARD_GROUP
        or not isinstance(reference, str)
        or not reference.startswith(prefix)
    ):
        return
    if sha256(package / "commercial_runtime/special.py") != SPLIT_WRAPPER_SHA:
        raise ValueError("Original browser export changed")

    from playwright.sync_api import Page

    sys.path.insert(0, str(package))
    try:
        native: Any = importlib.import_module("commercial_runtime.native")
        special: Any = importlib.import_module("commercial_runtime.special")
    finally:
        sys.path.pop(0)
    if Path(special.__file__).resolve() != package / "commercial_runtime/special.py":
        raise ValueError("Live cards must use the pinned browser runtime")
    load_card, browser_drawer = native.load_card, special.browser_drawer
    evaluate = Page.evaluate

    def alpha_card(group_id: str) -> dict:
        card = load_card(group_id)
        if group_id != CARD_GROUP:
            return card
        if sha256(package / card["entry"]) != CARD_ENGINE_SHA:
            raise ValueError("Original three-card draw engine changed")
        # The original worker emits RGBA frame sequences for this export mode.
        return {**card, "kind": "subtitle"}

    def alpha_drawer(card: dict, config: dict) -> tuple[Any, dict]:
        if card["id"] != CARD_GROUP:
            return browser_drawer(card, config)
        if sha256(Path(config["background"]))[:24] != reference.removeprefix(prefix):
            raise ValueError("Current three-card source binding changed")
        # The original browser initializes its image slot before drawing.
        # The compositor supplies the visible background from its original source track.
        boot = BytesIO()
        Image.new("RGBA", (1, 1)).save(boot, format="PNG")
        boot_uri = "data:image/png;base64," + base64.b64encode(boot.getvalue()).decode()
        draw, meta = browser_drawer(card, {**config, "background": boot_uri})

        def draw_alpha(frame: int) -> Image.Image:
            applied = False

            def evaluate_alpha(page: Page, expression: str, arg: Any = None) -> Any:
                nonlocal applied
                if expression == _ORIGINAL_DRAW:
                    applied = True
                    expression = _ALPHA_DRAW
                return evaluate(page, expression, arg)

            cast(Any, Page).evaluate = evaluate_alpha
            try:
                image = draw(frame)
            finally:
                cast(Any, Page).evaluate = evaluate
            if not applied:
                raise ValueError("Original three-card frame export did not run")
            return image

        return draw_alpha, {
            **meta,
            "media_capability": "original card RGBA over continuous episode source",
        }

    native.load_card = alpha_card
    special.browser_drawer = alpha_drawer
