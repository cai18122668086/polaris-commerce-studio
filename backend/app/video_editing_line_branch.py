"""Bind explicitly selected transparent hand art to the original line scene."""

import importlib
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import Image

from .motion_library import atomic_json, read_json, sha256
from .video_editing_media_clocks import clock_profile

LINE_GROUP = "W-R11"
LINE_BRUSH_FONT = "font-06b2048c592b1dae"
LINE_HAND_PATH = "/media/hand_sequence/path"
LINE_HAND_PREFIX = "tengli-line-hand-"
LINE_SHEET_FRAMES = 24
_LINE_SHEET_COLUMNS = 6
_LINE_FRAME = (540, 960)
_OWNER = Path("src/engines/workspace/商业口播_可编辑改造_20261104")
_BUILD = _OWNER / "unified/build12.py"
_MEDIA = _OWNER / "unified/core/media.py"
_NATIVE = Path("commercial_runtime/native.py")
_LEGACY_ART = Path(
    "src/engines/workspace/雯羽_小羽毛_两条拆解_20261103"
    "/experiments/pending-three-rework/assets"
)


def line_template(
    template: dict[str, Any], *, embedded_caption: bool = True
) -> dict[str, Any]:
    return {
        **template,
        "content": {
            **template["content"],
            "captions": template["content"]["captions"] if embedded_caption else [],
        },
        "media": {
            **template["media"],
            "presenter": {**template["media"]["presenter"], "end_policy": "error"},
            "director_ink": {
                "kind": "image",
                "alpha": True,
                "path": "input://media-c1270c63854048c9a6fe",
            },
            "hand_sequence": {
                "kind": "frame_sequence",
                "alpha": True,
                "fps": 30,
                "frames": LINE_SHEET_FRAMES,
                "path": "input://tengli-current-hand-sheet",
            },
        },
    }


def stage_line_sheet(root: Path, source: Path, digest: str) -> tuple[Path, str]:
    """Split the selected RGBA sheet into the original sequence's frame size."""
    width, height = _LINE_FRAME
    directory = root / ("hand-" + digest[:24])
    rows = []
    pixels = set()
    root.mkdir(parents=True, exist_ok=True)
    with (
        Image.open(source) as sheet,
        TemporaryDirectory(prefix="line-sheet-", dir=root) as temporary,
    ):
        if (
            sheet.format != "PNG"
            or getattr(sheet, "n_frames", 1) != 1
            or sheet.mode != "RGBA"
            or sheet.size
            != (
                _LINE_SHEET_COLUMNS * width,
                (LINE_SHEET_FRAMES // _LINE_SHEET_COLUMNS) * height,
            )
        ):
            raise ValueError(
                "Line hand art needs a 6 by 4 transparent 540×960 PNG sheet"
            )
        staged = Path(temporary) / "frames"
        staged.mkdir()
        for index in range(LINE_SHEET_FRAMES):
            y, x = divmod(index, _LINE_SHEET_COLUMNS)
            frame = sheet.crop(
                (x * width, y * height, (x + 1) * width, (y + 1) * height)
            )
            minimum, maximum = frame.getchannel("A").getextrema()
            if minimum != 0 or maximum == 0:
                raise ValueError(
                    "Every hand frame needs visible art and transparent space"
                )
            file = staged / f"{index:03}.png"
            frame.save(file)
            pixels.add(digest_frame := sha256(file))
            rows.append({"path": file.name, "sha256": digest_frame})
        if len(pixels) < 2:
            raise ValueError("The line hand sheet needs actual frame variation")
        manifest = staged / "sequence-binding.json"
        atomic_json(manifest, {"sheet_sha256": digest, "frames": rows})
        binding = sha256(manifest)
        staged.rename(directory)
    return directory, binding


def install_native_line_branch(package: Path, root: Path) -> None:
    if "--job" not in sys.argv:
        return
    job_path = Path(sys.argv[sys.argv.index("--job") + 1]).resolve()
    if job_path.parent != root / "plans":
        return
    job = read_json(job_path)
    if job["group_id"] != LINE_GROUP:
        return
    reference = job["config"]["media"].get("hand_sequence", {}).get("path", "")
    prefix = "input://" + LINE_HAND_PREFIX
    if not reference.startswith(prefix):
        return
    profile = clock_profile(LINE_GROUP)
    if not profile or any(
        sha256(package / path) != profile["source_files"][path.as_posix()]
        for path in (_BUILD, _MEDIA, _NATIVE)
    ):
        raise ValueError("Original line draw or media loader changed")
    resources = read_json(Path(os.environ["COMMERCIAL_BINDINGS"]))["resources"]
    rid = reference.removeprefix("input://")
    sheet = Path(resources[rid]).resolve()
    directory = Path(resources[rid + "-frames"]).resolve()
    manifest = directory / "sequence-binding.json"
    expected = reference.removeprefix(prefix).split("-", 1)[0]
    if not directory.is_relative_to(root) or sha256(manifest)[:24] != expected:
        raise ValueError("Line hand sequence binding changed")
    bound = read_json(manifest)
    if sha256(sheet) != bound["sheet_sha256"]:
        raise ValueError("Current line hand sheet changed after compilation")
    frames = bound["frames"]
    if len(frames) != LINE_SHEET_FRAMES:
        raise ValueError("Incomplete line hand sequence")
    replacements = {}
    for index, row in enumerate(frames):
        path = directory / f"{index:03}.png"
        if row["path"] != path.name or sha256(path) != row["sha256"]:
            raise ValueError("A bound line hand frame changed")
        original = package / _LEGACY_ART / f"hand-motion-{index + 11:02}.png"
        replacements[original] = str(path)

    sys.path[:0] = [str(package / _OWNER), str(package)]
    try:
        build: Any = importlib.import_module("unified.build12")
        media: Any = importlib.import_module("unified.core.media")
        native: Any = importlib.import_module("commercial_runtime.native")
    finally:
        del sys.path[:2]
    if any(
        Path(module.__file__).resolve() != package / path
        for module, path in ((build, _BUILD), (media, _MEDIA), (native, _NATIVE))
    ):
        raise ValueError("Line scene must use the pinned native draw and media modules")
    setup, load_image, drawer = build.Engine.setup, media.load_image, native.drawer

    def current_line_drawer(card: dict, config: dict) -> Any:
        if card["id"] != LINE_GROUP:
            return drawer(card, config)
        slots = config["media"]
        hand = slots["hand_sequence"]
        if hand["path"] != reference:
            raise ValueError(
                "Native line input must retain the project sheet reference"
            )
        # The original episode audits the uploaded file. Only its native worker
        # receives the verified frame sequence derived from that file.
        return drawer(
            card,
            {
                **config,
                "media": {
                    **slots,
                    "hand_sequence": {**hand, "path": reference + "-frames"},
                },
            },
        )

    def load_hand_frame(path: str) -> Image.Image:
        return load_image(replacements.get(Path(path), path))

    def setup_current_line(engine: Any) -> None:
        if engine.gid != LINE_GROUP:
            setup(engine)
            return
        slots = engine.active["media"]
        if Path(slots["hand_sequence"]["path"]) != directory:
            raise ValueError("Native line scene did not receive the selected sequence")
        # Use the original paper mask, editable brush text and placement with
        # the explicitly selected current frames instead of historical pixels.
        hand = slots.pop("hand_sequence")
        media.load_image = load_hand_frame
        try:
            setup(engine)
        finally:
            media.load_image = load_image
            slots["hand_sequence"] = hand

    build.Engine.setup = setup_current_line
    native.drawer = current_line_drawer
