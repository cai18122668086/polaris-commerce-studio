"""Bind current text and timing to the original Hypit stagger scenes."""

import hashlib
import importlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from .motion_library import atomic_json, read_json, sha256
from .video_editing_contracts import Transcript
from .video_editing_hypit import NATIVE_FILES
from .video_editing_hypit_foreground import attach_foreground_track, render_foreground

STRIP_PROFILE = "hypit-original-strips/1"
SLANT_GROUP = "HY-A2"
SLANT_PROFILE = "hypit-original-slant-cards/1"
SLANT_BACKGROUND = "/component_assets/stagger#mkbg3"
SLANT_FOREGROUND = "/component_assets/stagger#mkfg1"
SLANT_IMAGES = tuple(f"/component_assets/stagger#mkpic{i}" for i in range(1, 4))
SLANT_CAPTION_BASELINE = 1208
PRICE_CARD_GROUP = "HY-A6"
PRICE_CARD_PROFILE = "hypit-original-price-cards/1"
PRICE_CARD_INSET_TYPE = "larger-inset-type-v1"
LIVE_STRIP_GROUP = "HY-A5"
LIVE_STAGE_GROUPS = frozenset((LIVE_STRIP_GROUP, PRICE_CARD_GROUP))
LIVE_STAGE_PROFILE = "hypit-live-stage/1"
FLOW_GROUP = "HY-A7"
FLOW_PROFILE = "hypit-original-flow-labels/1"
FLOW_PLATE = "/media/plate-clip"
_FLOW_COMPONENTS = {
    "packages/stagger/dist/render.js": (
        "306f69356e311ff971f94a5458c3d2e0eb3b0ffd7716a7a9c7987a8c027dddd4"
    ),
    "packages/pie/dist/render.js": (
        "609e283839fc908fbd1904eba91173e05bf217745dfce51160189d552b6d51cd"
    ),
}
STRIP_SIDECAR = "hypit-strips/component.json"
STAGGER_GROUPS = {
    SLANT_GROUP: (
        "a2m",
        "b98b222286255520885ece7059ff2d9fbf3cd0bea6c26c8d12ba521365d29938",
    ),
    "HY-A4": (
        "a4m",
        "b02ffa4c994e697eb3af1405483df2fd2d2e42d02fa035bdfb4663b49c416ddb",
    ),
    LIVE_STRIP_GROUP: (
        "a5m",
        "aefef4aa6e1f9d10c58bc9c50b5df4538c68ed2352af00a0f6e5d32fa4cb4ed6",
    ),
    FLOW_GROUP: (
        "a7m",
        "d2acbbc738a27280b9b5350d0fd9a2542985dce2b910c61ca229fe0591a9f03d",
    ),
    PRICE_CARD_GROUP: (
        "a6m",
        "f4ecb63d767564b2eb9e910f9b7c902a453450c4e3dc9208611556ce29e8281f",
    ),
}
STRIP_IMAGE = "/component_assets/stagger#mkstage1"
STRIP_TEXT = tuple(f"/hypit_labels/{i}/text" for i in range(3))
STRIP_EVENTS = tuple(f"/hypit_labels/{i}/entry_frame" for i in range(3))
CARD_TITLES = tuple(f"/hypit_cards/{i}/title" for i in range(3))
CARD_DETAILS = tuple(f"/hypit_cards/{i}/detail" for i in range(3))
CARD_EVENTS = tuple(f"/hypit_cards/{i}/entry_frame" for i in range(3))
CARD_IMAGES = tuple(f"/component_assets/stagger#mka6c{i}" for i in (3, 2, 1))
_HAN_LABEL = re.compile(r"[\u3400-\u9fff]{1,3}")
_CARD_LINE = re.compile(r"[\u3400-\u9fff0-9]{1,9}")
_SLANT_ENGLISH = re.compile(r"[A-Z][A-Z ]{0,9}")


def stagger_profile(group_id: str) -> str:
    if group_id == FLOW_GROUP:
        return FLOW_PROFILE
    if group_id == SLANT_GROUP:
        return SLANT_PROFILE
    return PRICE_CARD_PROFILE if group_id == PRICE_CARD_GROUP else STRIP_PROFILE


def stagger_events(group_id: str) -> tuple[str, ...]:
    return CARD_EVENTS if group_id == PRICE_CARD_GROUP else STRIP_EVENTS


def stagger_audio_frame(group_id: str, entry_frame: int) -> int:
    # In the pinned wipe and zoom profiles, the entry marker still has zero
    # visibility. The original component first changes pixels on the next frame.
    return entry_frame + int(
        group_id in {SLANT_GROUP, LIVE_STRIP_GROUP, PRICE_CARD_GROUP, FLOW_GROUP}
    )


def strip_fields(group_id: str) -> list[dict[str, str]]:
    price_cards = group_id == PRICE_CARD_GROUP
    return [
        {
            "path": path,
            "category": "text",
            "value_type": "str",
            "binding_surface": "website_sidecar",
        }
        for path in (CARD_TITLES + CARD_DETAILS if price_cards else STRIP_TEXT)
    ] + [
        {
            "path": path,
            "category": "event",
            "unit": "frames",
            "value_type": "int",
            "binding_surface": "website_sidecar",
        }
        for path in stagger_events(group_id)
    ]


def strip_config_sha256(config: dict) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def compile_flow_plate(
    native: dict,
    assets: dict[str, dict[str, Any]],
    transcript: Transcript,
    *,
    live_stage: bool = False,
    media_path: str = FLOW_PLATE,
    profile_id: str = FLOW_PROFILE,
) -> dict:
    path = STRIP_IMAGE if live_stage else media_path
    media = [row for row in native["media"] if row["path"] == path]
    if len(media) != 1 or (path == FLOW_PLATE and len(native["media"]) != 1):
        raise ValueError("Hypit needs its original moving media slot")
    asset = assets[media[0]["asset_id"]]
    start, end = native["clock"]["start_ms"], native["clock"]["end_ms"]
    frames = math.ceil((end - start) * 30 / 1000)
    if (
        asset.get("kind") != "original_video"
        or asset.get("sha256") != transcript.source_sha256
        or not 0 <= start < end <= transcript.duration_ms
        or start * 30 + frames * 1000 > transcript.duration_ms * 30
    ):
        raise ValueError("Hypit requires this episode's actual moving source window")
    return {
        "media_path": path,
        "asset_id": media[0]["asset_id"],
        "source_sha256": transcript.source_sha256,
        "source_start_ms": start,
        "source_end_ms": round(start + frames * 1000 / 30, 6),
        "frames": frames,
        "policy": "transcript_source_window",
        "profile_id": LIVE_STAGE_PROFILE if live_stage else profile_id,
        "native_sampling_expression": (
            "30fps task-local source trim, native plate from frame zero"
        ),
        "timing_review": "unreviewed",
    }


def _flow_moves(tag: str, entries: list[int], frames: int) -> str:
    # The second and third arrivals trigger movement on earlier labels before
    # they appear. Keep the original lead/lag, distances and segment lengths.
    cues = ((0, 0), (1, -5), (2, -2), (1, 0), (2, -1), (2, 9), (2, 0))
    field = re.search(r'(?<=\s)moves="([^"]+)"', tag)
    if field is None:
        raise ValueError("Original Hypit flow moves are unavailable")
    original = field[1].split("; ")
    limits = [0, 0, 0]
    moves = []
    for segment, (anchor, offset) in zip(original, cues, strict=True):
        track, _, motion = segment.split(":")
        index = int(track)
        start = entries[anchor] + offset
        end = start + int(motion.rsplit(",", 1)[1])
        if not limits[index] <= start < end < frames:
            raise ValueError(
                "Spoken flow entries leave too little room for original moves"
            )
        limits[index] = end
        moves.append(f"{track}:{start}:{motion}")
    return "; ".join(moves)


def _live_stage_items(items: str, *, price_cards: bool) -> str:
    placed = []
    for i, item in enumerate(items.split(";")):
        label, at = item.strip().split("@", 1)
        box, marker, direction = at.partition(">")
        x, y, w, h = map(int, box.split(","))
        if price_cards:
            # Fit all three cards between the centered face and main captions.
            y, h = (1420, 1148, 876)[i], 238
        else:
            y += 465
        placed.append(f"{label}@{x},{y},{w},{h}{marker}{direction}")
    return "; ".join(placed)


def _native_attributes(package: Path, group: dict, data: dict) -> dict:
    node, expected = STAGGER_GROUPS[group["id"]]
    special = "commercial_runtime/special.py"
    entry = package / group["entry"]
    if (
        not entry.resolve().is_relative_to(package)
        or sha256(entry) != expected
        or sha256(package / special) != NATIVE_FILES[special]
    ):
        raise ValueError("Audited original Hypit strip source changed")
    flow = group["id"] == FLOW_GROUP
    slant = group["id"] == SLANT_GROUP
    if flow and any(
        sha256(entry.parent / path) != expected
        for path, expected in _FLOW_COMPONENTS.items()
    ):
        raise ValueError("Audited original Hypit flow components changed")
    if (
        slant
        and sha256(entry.parent / "packages/stagger/dist/render.js")
        != (_FLOW_COMPONENTS["packages/stagger/dist/render.js"])
    ):
        raise ValueError("Audited original Hypit slant card component changed")
    scene = entry.read_text(encoding="utf-8")
    match = _stagger_tag(node).search(scene)
    tag = re.search(r'(?<=\s)items="([^"]*)"', match[0]) if match else None
    # The item directions contain > characters. Read the original items
    # attribute, preserving its native geometry and direction verbatim.
    if tag is None:
        raise ValueError("Original Hypit strip item layout is unavailable")
    parts = tag.group(1).split(";")
    starts, frames = data["entry_frames"], data["frames"]
    if (
        len(parts) != 3
        or len(starts) != 3
        or any(type(n) is not int for n in starts)
        or starts != sorted(set(starts))
        or type(frames) is not int
        or not 0 <= starts[0] < starts[-1] <= frames - 9
        or frames > 450
    ):
        raise ValueError("Hypit stagger scenes need three ordered entry frames")
    if group["id"] == PRICE_CARD_GROUP:
        lines = data["cards"]
        if len(lines) != 3 or any(
            not isinstance(row, list)
            or len(row) != 2
            or any(not isinstance(s, str) or not _CARD_LINE.fullmatch(s) for s in row)
            for row in lines
        ):
            raise ValueError(
                "Original Hypit cards need two short spoken lines per card"
            )
        slot = {"caps": "; ".join("|".join(row) for row in lines)}
        if (type_profile := data.get("price_card_layout")) is not None:
            if type_profile != PRICE_CARD_INSET_TYPE or any(
                len(line) > 6 for row in lines for line in row
            ):
                raise ValueError("The larger price-card type needs short spoken lines")
            # The 271 px original card can hold these two lines plus its 17 px
            # gap. Keep the black original serif and the right-edge alignment.
            slot.update({"cap-size": "96", "cap-en-size": "100", "cap-dy": "-8"})
    elif slant:
        labels = data["labels"]
        glosses = data["glosses"]
        if (
            len(labels) != 3
            or len(glosses) != 3
            or any(not _HAN_LABEL.fullmatch(label) for label in labels)
            or any(gloss and not _SLANT_ENGLISH.fullmatch(gloss) for gloss in glosses)
            or starts[-1] + 12 >= frames
        ):
            raise ValueError("Slant cards need three short titles and time to settle")
        slot = {
            "caps": "; ".join(
                f"{label}|{gloss}" if gloss else label
                for label, gloss in zip(labels, glosses, strict=True)
            ),
            # Keep the same foreground role and layer. A native media track
            # supplies current motion at the original position.
            "fg": "",
        }
    else:
        labels = data["labels"]
        if len(labels) != 3 or any(
            not isinstance(s, str) or not _HAN_LABEL.fullmatch(s) for s in labels
        ):
            raise ValueError("Hypit strips need three short labels")
        slot = {
            "items": "; ".join(
                f"{label}@{item.split('@', 1)[1]}"
                for label, item in zip(labels, parts, strict=True)
            )
        }
        if flow:
            assert match is not None
            slot.update({"moves": _flow_moves(match[0], starts, frames), "text-en": ""})
    if data.get("live_stage"):
        if group["id"] not in LIVE_STAGE_GROUPS:
            raise ValueError(
                "Live stage requires the original strip or price-card canvas"
            )
        slot["bg"] = ""
        slot["items"] = _live_stage_items(
            slot.get("items", tag[1]), price_cards=group["id"] == PRICE_CARD_GROUP
        )
    return {
        node: {**slot, "frames": ",".join(map(str, starts))},
        "t": {"end": f"{frames}f"},
    }


def compile_strips(
    package: Path,
    group: dict,
    native: dict,
    assets: dict[str, dict[str, Any]],
    *,
    price_card_layout: str | None = None,
    live_stage: bool = False,
    slant_glosses: list[dict[str, str]] | None = None,
) -> dict:
    text = {row["path"]: row for row in native["text"]}
    events = {row["path"]: row for row in native["events"]}
    media = {row["path"]: row["asset_id"] for row in native["media"]}
    price_cards = group["id"] == PRICE_CARD_GROUP
    slant = group["id"] == SLANT_GROUP
    if price_card_layout is not None and (
        not price_cards or price_card_layout != PRICE_CARD_INSET_TYPE
    ):
        raise ValueError("The larger price-card type requires its audited native group")
    titles = CARD_TITLES if price_cards else STRIP_TEXT
    detail = CARD_DETAILS if price_cards else ()
    anchors = stagger_events(group["id"])
    if slant:
        images = (SLANT_BACKGROUND, SLANT_FOREGROUND, *SLANT_IMAGES)
    else:
        images = (STRIP_IMAGE, *CARD_IMAGES) if price_cards else (STRIP_IMAGE,)
    flow = group["id"] == FLOW_GROUP
    media_paths = (FLOW_PLATE,) if flow else images
    if (
        set(text) != set(titles + detail)
        or set(events) != set(anchors)
        or set(media) != set(media_paths)
        or len(set(media.values())) != len(media_paths)
    ):
        raise ValueError("Bind all original Hypit text roles and distinct media slots")
    if not flow and any(
        assets[aid].get("kind") != "image"
        or assets[aid].get("source") != "project_upload"
        for path, aid in media.items()
        if not (live_stage and path == STRIP_IMAGE)
        and not (slant and path == SLANT_FOREGROUND)
    ):
        raise ValueError(
            "Hypit stages and cards require registered current project images"
        )
    if (price_cards or slant) and len(
        {assets[aid]["sha256"] for aid in media.values()}
    ) != len(images):
        raise ValueError("Original Hypit cards need distinct current image bytes")
    if any(
        events[at]["token_id"] != text[label]["token_ids"][0]
        or events[at]["edge"] != "start"
        for label, at in zip(detail if price_cards else titles, anchors, strict=True)
    ):
        raise ValueError("Each Hypit strip entrance must use its spoken label start")
    clock = native["clock"]
    data = {
        "profile": stagger_profile(group["id"]),
        "group_id": group["id"],
        "entry_frames": [events[path]["value"] for path in anchors],
        "frames": math.ceil((clock["end_ms"] - clock["start_ms"]) * 30 / 1000),
    }
    if price_cards:
        data["cards"] = [
            [text[title]["text"], text[line]["text"]]
            for title, line in zip(titles, detail, strict=True)
        ]
        if price_card_layout:
            data["price_card_layout"] = price_card_layout
    else:
        data["labels"] = [text[path]["text"] for path in titles]
    if slant:
        labels = data["labels"]
        glosses = [""] * len(labels)
        if slant_glosses is not None:
            if not isinstance(slant_glosses, list) or len(slant_glosses) != len(labels):
                raise ValueError("Slant card glosses must bind each spoken title")
            for i, (label, row) in enumerate(zip(labels, slant_glosses, strict=True)):
                if (
                    not isinstance(row, dict)
                    or set(row) != {"source_text", "display_text"}
                    or row["source_text"] != label
                    or not isinstance(row["display_text"], str)
                    or not _SLANT_ENGLISH.fullmatch(row["display_text"])
                ):
                    raise ValueError("Slant card gloss must match its own spoken title")
                glosses[i] = row["display_text"]
        data["glosses"] = glosses
    if flow or live_stage or slant:
        data["plate"] = native["media_clocks"][0]
    if live_stage:
        data["live_stage"] = True
    _native_attributes(package, group, data)
    return data


def _stagger_tag(node: str) -> re.Pattern[str]:
    return re.compile(rf'<stagger:Entry id="{node}"(?:[^">]|"[^"]*")*>')


def verify_stagger_entry(root: Path, ref: dict) -> None:
    """Verify a sound anchor against the task-local scene that was rendered."""
    group_id, stem, index = ref["group_id"], ref["shot"], ref["index"]
    if (
        group_id not in STAGGER_GROUPS
        or not re.fullmatch(rf"\d{{3,}}-{group_id}", stem)
        or type(index) is not int
        or not 0 <= index < 3
    ):
        raise ValueError("Unknown Hypit label sound reference")
    sidecar = root / "hypit-strips" / f"{stem}.json"
    work = root / "hypit-strips" / "work" / stem
    receipt = read_json(work / "tengli-strip-materialization.json")
    scene = work / "hypit" / group_id / "scene.svml"
    data = read_json(sidecar)
    if (
        sha256(sidecar) != ref["sidecar_sha256"]
        or receipt["sidecar_sha256"] != ref["sidecar_sha256"]
        or data["group_id"] != group_id
        or data["entry_frames"][index] != ref["frame"]
        or stagger_audio_frame(group_id, ref["frame"]) != ref["audible_frame"]
        or sha256(scene) != receipt["scene_sha256"]
    ):
        raise ValueError("Rendered Hypit sound reference no longer matches the scene")
    tag = _stagger_tag(STAGGER_GROUPS[group_id][0]).search(scene.read_text("utf-8"))
    attribute = re.search(r'(?<=\s)frames="([^"]+)"', tag[0]) if tag else None
    if not attribute or attribute[1] != ",".join(map(str, data["entry_frames"])):
        raise ValueError("Native Hypit entry frames differ from the sound plan")


def _render_plate_clip(original: Any, source_ref: str, data: dict, clip: Path) -> dict:
    plate = data["plate"]
    source = Path(original.resolve(source_ref, True))
    if sha256(source) != plate["source_sha256"] or data["frames"] != plate["frames"]:
        raise ValueError("Hypit plate differs from the compiled source window")
    clip.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            original.resolve("tool://ffmpeg", True),
            "-nostdin",
            "-protocol_whitelist",
            "file,pipe",
            "-v",
            "error",
            "-y",
            "-ss",
            f"{plate['source_start_ms'] / 1000:.3f}",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            "fps=30",
            "-frames:v",
            str(data["frames"]),
            "-c:v",
            "libx264",
            "-crf",
            "14",
            "-pix_fmt",
            "yuv420p",
            str(clip),
        ],
        check=True,
        timeout=90,
    )
    probe = subprocess.check_output(
        [
            original.resolve("tool://ffprobe", True),
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "csv=p=0",
            str(clip),
        ],
        timeout=60,
    )
    if int(probe) != data["frames"]:
        raise ValueError("Moving Hypit plate does not cover the complete native window")
    return {**plate, "clip_sha256": sha256(clip)}


def _attach_live_stage(scene: str) -> str:
    # Use the same original Hypit media pipeline and fit as the moving HY-A7 plate.
    imports = (
        '  <import as="pipeline" from="@hypit/media-pipeline@1"/>\n'
        '  <import as="media-track" from="@hypit/media-track@1"/>\n'
    )
    track = """  <spatial:Frame id="tengli-full" within={canvas}
    left="0%" top="0%" right="100%" bottom="100%"/>
  <asset:Video id="tengli-clip" src="./inputs/current-plate.mp4"/>
  <pipeline:Normalize id="tengli-plate" source={tengli-clip} video="primary-moving"
    audio="none" span-authority="video" clock={clock}/>
  <media-track:Track id="tengli-track" timeline={t.timeline} canvas={canvas}>
    <media-track:Item id="tengli-plate-item" frame={tengli-full}
      media={tengli-plate.media}
      appearance={style.media.plate} during="program"/>
  </media-track:Track>
"""
    asset = '  <import as="asset" from="@hypit/media@1"/>\n'
    canvas = '  <spatial:Canvas id="canvas" width="1080" height="1920"/>\n'
    film = "    <film:Track source={a"
    if any(scene.count(marker) != 1 for marker in (asset, canvas, film)):
        raise ValueError("Original Hypit full-frame track anchors changed")
    return (
        scene.replace(asset, asset + imports)
        .replace(canvas, canvas + track)
        .replace(film, "    <film:Track source={tengli-track.visual}/>\n" + film)
    )


def install_native_strips(package: Path, root: Path) -> None:
    """Supply validated scalar parameters to the original materializer."""
    if "--job" not in sys.argv:
        return
    job_path = Path(sys.argv[sys.argv.index("--job") + 1]).resolve()
    if job_path.parent != root / "plans":
        return
    job = read_json(job_path)
    if job["group_id"] not in STAGGER_GROUPS:
        return
    output = Path(job["output"]).resolve()
    sidecar = root / "hypit-strips" / f"{output.stem}.json"
    if (
        not output.is_relative_to(root)
        or not sidecar.resolve().is_relative_to(root)
        or not sidecar.is_file()
    ):
        raise ValueError("Native Hypit strips need an instance-bound compiler receipt")
    binding = read_json(root / "bindings.json").get("tengli_hypit_strips", {})
    digest = sha256(sidecar)
    if binding.get(output.stem) != digest or job["config"].get("attributes") != {}:
        raise ValueError("Hypit strip input differs from its compiled binding")
    data = read_json(sidecar)
    if (
        data.get("profile") != stagger_profile(job["group_id"])
        or data.get("group_id") != job["group_id"]
        or data.get("config_sha256") != strip_config_sha256(job["config"])
    ):
        raise ValueError("Hypit strip receipt belongs to another job")
    sys.path.insert(0, str(package))
    try:
        special = importlib.import_module("commercial_runtime.special")
    finally:
        sys.path.pop(0)
    source = special.__file__
    if (
        source is None
        or Path(source).resolve() != package / "commercial_runtime/special.py"
    ):
        raise ValueError("Hypit strip materializer must be the original runtime")
    original = cast(Any, special)
    materialize = original.hypit_materialize
    work = root / "hypit-strips" / "work" / output.stem
    if not work.resolve().is_relative_to(root):
        raise ValueError("Hypit strip workspace leaves its current instance")
    receipt = work / "tengli-strip-materialization.json"
    if (receipt.is_file() and read_json(receipt).get("sidecar_sha256") != digest) or (
        output.is_file() and not receipt.is_file()
    ):
        raise ValueError("Preserve previous Hypit output; compile a new instance")

    def bind(card: dict, config: dict) -> Any:
        if card["id"] != data["group_id"] or config.get("attributes") != {}:
            raise ValueError("Native strip job changed before materialization")
        attrs = _native_attributes(package, card, data)
        plate, live_source, foreground_source = None, None, None
        if card["id"] == FLOW_GROUP:
            clip = work / "current-plate.mp4"
            plate = _render_plate_clip(
                original, config["media"]["plate-clip"], data, clip
            )
            config = {**config, "media": {"plate-clip": str(clip)}}
        elif card["id"] == SLANT_GROUP:
            components = config["component_assets"].copy()
            foreground_source = components.pop("stagger#mkfg1")
            config = {**config, "component_assets": components}
        elif data.get("live_stage"):
            components = config["component_assets"].copy()
            live_source = components.pop("stagger#mkstage1")
            config = {**config, "component_assets": components}
        instance = original.instance
        original.instance = lambda: work
        try:
            result = materialize(card, {**config, "attributes": {"t": attrs["t"]}})
        finally:
            original.instance = instance
        node = STAGGER_GROUPS[card["id"]][0]
        scene = result[0] / "scene.svml"
        # The original attribute reader stops at the '>' inside item direction
        # strings. Supply these two parameters on the instance copy it produced.
        tag = _stagger_tag(node)

        def patch_tag(match: re.Match[str]) -> str:
            current = match[0]
            for key, value in attrs[node].items():
                replacement = f'{key}="{value}"'.replace("\\", "\\\\")
                current, count = re.subn(
                    rf'(?<=\s){key}="[^"]*"',
                    replacement,
                    current,
                )
                if count != 1:
                    raise ValueError("Original instance attribute was not found once")
            return current

        updated, count = tag.subn(patch_tag, scene.read_text(encoding="utf-8"))
        if count != 1:
            raise ValueError("Original instance stagger node was not found once")
        if live_source is not None:
            plate = _render_plate_clip(
                original, live_source, data, scene.parent / "inputs/current-plate.mp4"
            )
            updated = _attach_live_stage(updated)
        foreground = None
        if foreground_source is not None:
            foreground = render_foreground(
                package,
                original,
                foreground_source,
                data["plate"],
                scene.parent / "inputs/current-foreground.webm",
            )
            updated = attach_foreground_track(updated, scene.parent / "s03.svs")
        scene.write_text(updated, encoding="utf-8")
        atomic_json(
            receipt,
            {
                "sidecar_sha256": digest,
                "scene_sha256": sha256(scene),
                "materialized_attributes": attrs,
                **({"plate": plate} if plate is not None else {}),
                **({"foreground": foreground} if foreground is not None else {}),
            },
        )
        return result

    original.hypit_materialize = bind
