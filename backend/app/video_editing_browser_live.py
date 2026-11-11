"""Set explicit compositing modes at the pinned original browser entry."""

import base64
import importlib
import sys
from io import BytesIO
from pathlib import Path
from typing import Any, cast

from PIL import Image

from .motion_library import read_json, sha256
from .video_editing_browser_clocks import (
    CARD_ENGINE_SHA,
    FRUIT_LIST_GROUP,
    FRUIT_LIST_PREFIX,
    FRUIT_LIST_SOLID_BACKGROUND,
    LIVE_BROWSER_SOURCE_FIELDS,
    NUMBERED_GROUP,
    SPLIT_WRAPPER_SHA,
    audit_card_family_engine,
    audit_split_engine,
    fruit_list_uses_solid_background,
)
from .video_editing_contracts import Transcript

CARD_LIVE_PREFIX = "tengli-card-live-"
_ORIGINAL_DRAW = (
    'f=>{engine.draw(exportCanvas,f,"city",true);'
    'return exportCanvas.toDataURL("image/png").split(",")[1]}'
)
_SPLIT_DRAW = (
    '([g,f])=>{engine.draw(exportCanvas,g,f/30,"B");'
    'return exportCanvas.toDataURL("image/png").split(",")[1]}'
)
_ALPHA_DRAW = """
([frame, numbered]) => {
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
  if (numbered) {
    const images = engine.states[frame[0]].B.images;
    for (const name of ["strokeText", "fillText"]) {
      const paint = context[name];
      context[name] = function (text, x, y, ...rest) {
        // Fit two glyphs inside the pinned G03 title clip at x=302..452.
        if (this.font === "italic 78px NativeSerif" && x === 0 && y === 0) {
          return paint.call(this, text, x, y, 118);
        }
        return paint.call(this, text, x, y, ...rest);
      };
    }
    const drawImage = context.drawImage;
    context.drawImage = function (image, ...args) {
      if (images.includes(image) && args.length === 4 && args[0] < 453) {
        const [x, y, w, h] = args;
        const scale = (x + w - 453) / w;
        if (scale <= 0) throw Error("Original numbered image slot changed");
        args = [453, y + h * (1 - scale), w * scale, h * scale];
      }
      return drawImage.call(this, image, ...args);
    };
  }
  try {
    if (numbered) {
      engine.draw(exportCanvas, frame[0], frame[1] / 30, "B");
    } else {
      engine.draw(exportCanvas, frame, "city", false);
    }
  } finally {
    delete context.fillRect;
    if (numbered) {
      delete context.strokeText;
      delete context.fillText;
      delete context.drawImage;
    }
  }
  if (plates !== 1) throw Error("Original browser plate changed");
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
    field = LIVE_BROWSER_SOURCE_FIELDS[native["group_id"]]
    source_id = videos.get(field, "")
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
        "media_path": field,
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
    group = job["group_id"]
    field = LIVE_BROWSER_SOURCE_FIELDS.get(group)
    if field is None:
        return
    numbered = group == NUMBERED_GROUP
    reference = job["config"].get(field[1:])
    prefix = "input://" + CARD_LIVE_PREFIX
    if not isinstance(reference, str) or not reference.startswith(prefix):
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
        if group_id != group:
            return card
        if numbered:
            audit_split_engine(package, card)
        elif sha256(package / card["entry"]) != CARD_ENGINE_SHA:
            raise ValueError("Original three-card draw engine changed")
        # The original worker emits RGBA frame sequences for this export mode.
        return {**card, "kind": "subtitle"}

    def alpha_drawer(card: dict, config: dict) -> tuple[Any, dict]:
        if card["id"] != group:
            return browser_drawer(card, config)
        if sha256(Path(config[field[1:]]))[:24] != reference.removeprefix(prefix):
            raise ValueError("Current browser source binding changed")
        # The original browser initializes its image slot before drawing.
        # The compositor supplies the visible background from its original source track.
        boot = BytesIO()
        Image.new("RGBA", (1, 1)).save(boot, format="PNG")
        boot_uri = "data:image/png;base64," + base64.b64encode(boot.getvalue()).decode()
        alpha_config = {**config, "background": boot_uri}
        if numbered:
            alpha_config["presenter"] = boot_uri
        draw, meta = browser_drawer(card, alpha_config)
        original_draw = _SPLIT_DRAW if numbered else _ORIGINAL_DRAW

        def draw_alpha(frame: int) -> Image.Image:
            applied = False

            def evaluate_alpha(page: Page, expression: str, arg: Any = None) -> Any:
                nonlocal applied
                if expression == original_draw:
                    applied = True
                    return evaluate(page, _ALPHA_DRAW, [arg, numbered])
                return evaluate(page, expression, arg)

            cast(Any, Page).evaluate = evaluate_alpha
            try:
                image = draw(frame)
            finally:
                cast(Any, Page).evaluate = evaluate
            if not applied:
                raise ValueError("Original browser frame export did not run")
            return image

        return draw_alpha, {
            **meta,
            "media_capability": "original card RGBA over continuous episode source",
            **(
                {"numbered_label_width": 118, "numbered_image_left": 453}
                if numbered
                else {}
            ),
        }

    native.load_card = alpha_card
    special.browser_drawer = alpha_drawer


def install_fruit_list_export(package: Path, root: Path) -> None:
    if "--job" not in sys.argv:
        return
    path = Path(sys.argv[sys.argv.index("--job") + 1]).resolve()
    if path.parent != root / "plans":
        return
    job = read_json(path)
    reference = job["config"].get("presenter")
    prefix = "input://" + FRUIT_LIST_PREFIX
    if job["group_id"] != FRUIT_LIST_GROUP or not fruit_list_uses_solid_background(
        job["config"]
    ):
        return
    assert isinstance(reference, str)

    from playwright.sync_api import Page

    sys.path.insert(0, str(package))
    try:
        special: Any = importlib.import_module("commercial_runtime.special")
    finally:
        sys.path.pop(0)
    if Path(special.__file__).resolve() != package / "commercial_runtime/special.py":
        raise ValueError("Fruit list must use the pinned browser runtime")
    browser_drawer, evaluate = special.browser_drawer, Page.evaluate

    def with_solid_plate(card: dict, config: dict) -> tuple[Any, dict]:
        if card["id"] != FRUIT_LIST_GROUP:
            return browser_drawer(card, config)
        audit_card_family_engine(package, card)
        if sha256(Path(config["presenter"]))[:24] != reference.removeprefix(prefix):
            raise ValueError("Current fruit list header binding changed")
        applied = False

        def evaluate_setup(page: Page, expression: str, arg: Any = None) -> Any:
            nonlocal applied
            result = evaluate(page, expression, arg)
            if expression == 'async ([g,c])=>await engine.replace(g,c,"B")':
                # CONFIG belongs to the original iframe. Its existing solid
                # branch paints a fresh canvas before the moving rows.
                applied = (
                    evaluate(
                        page,
                        "()=>document.querySelector('iframe').contentWindow.eval("
                        "\"CONFIG.g06bg = 'solid'\")",
                    )
                    == "solid"
                )
            return result

        cast(Any, Page).evaluate = evaluate_setup
        try:
            draw, meta = browser_drawer(card, config)
        finally:
            cast(Any, Page).evaluate = evaluate
        if not applied:
            raise ValueError("Original fruit list setup did not run")
        return draw, {**meta, "background": FRUIT_LIST_SOLID_BACKGROUND}

    special.browser_drawer = with_solid_plate
