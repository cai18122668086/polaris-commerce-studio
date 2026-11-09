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

STRIP_PROFILE = "hypit-original-strips/1"
PRICE_CARD_GROUP = "HY-A6"
PRICE_CARD_PROFILE = "hypit-original-price-cards/1"
PRICE_CARD_INSET_TYPE = "larger-inset-type-v1"
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
    "HY-A4": (
        "a4m",
        "b02ffa4c994e697eb3af1405483df2fd2d2e42d02fa035bdfb4663b49c416ddb",
    ),
    "HY-A5": (
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


def stagger_profile(group_id: str) -> str:
    if group_id == FLOW_GROUP:
        return FLOW_PROFILE
    return PRICE_CARD_PROFILE if group_id == PRICE_CARD_GROUP else STRIP_PROFILE


def stagger_events(group_id: str) -> tuple[str, ...]:
    return CARD_EVENTS if group_id == PRICE_CARD_GROUP else STRIP_EVENTS


def stagger_audio_frame(group_id: str, entry_frame: int) -> int:
    # In the pinned wipe and zoom profiles, the entry marker still has zero
    # visibility. The original component first changes pixels on the next frame.
    return entry_frame + int(group_id in {"HY-A5", PRICE_CARD_GROUP, FLOW_GROUP})


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
    native: dict, assets: dict[str, dict[str, Any]], transcript: Transcript
) -> dict:
    media = native["media"]
    if len(media) != 1 or media[0]["path"] != FLOW_PLATE:
        raise ValueError("Flow labels need the original moving plate slot")
    asset = assets[media[0]["asset_id"]]
    start, end = native["clock"]["start_ms"], native["clock"]["end_ms"]
    frames = math.ceil((end - start) * 30 / 1000)
    if (
        asset.get("kind") != "original_video"
        or asset.get("sha256") != transcript.source_sha256
        or not 0 <= start < end <= transcript.duration_ms
        or start * 30 + frames * 1000 > transcript.duration_ms * 30
    ):
        raise ValueError(
            "Flow labels require this episode's actual moving source window"
        )
    return {
        "media_path": FLOW_PLATE,
        "asset_id": media[0]["asset_id"],
        "source_sha256": transcript.source_sha256,
        "source_start_ms": start,
        "source_end_ms": round(start + frames * 1000 / 30, 6),
        "frames": frames,
        "policy": "transcript_source_window",
        "profile_id": FLOW_PROFILE,
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
    if flow and any(
        sha256(entry.parent / path) != expected
        for path, expected in _FLOW_COMPONENTS.items()
    ):
        raise ValueError("Audited original Hypit flow components changed")
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
) -> dict:
    text = {row["path"]: row for row in native["text"]}
    events = {row["path"]: row for row in native["events"]}
    media = {row["path"]: row["asset_id"] for row in native["media"]}
    price_cards = group["id"] == PRICE_CARD_GROUP
    if price_card_layout is not None and (
        not price_cards or price_card_layout != PRICE_CARD_INSET_TYPE
    ):
        raise ValueError("The larger price-card type requires its audited native group")
    titles = CARD_TITLES if price_cards else STRIP_TEXT
    detail = CARD_DETAILS if price_cards else ()
    anchors = stagger_events(group["id"])
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
        for aid in media.values()
    ):
        raise ValueError(
            "Hypit stages and cards require registered current project images"
        )
    if price_cards and len({assets[aid]["sha256"] for aid in media.values()}) != len(
        images
    ):
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
    if flow:
        data["plate"] = native["media_clocks"][0]
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


def _flow_clip(
    original: Any, config: dict, data: dict, work: Path
) -> tuple[dict, dict]:
    plate = data["plate"]
    source = Path(original.resolve(config["media"]["plate-clip"], True))
    if sha256(source) != plate["source_sha256"] or data["frames"] != plate["frames"]:
        raise ValueError("Flow plate differs from the compiled source window")
    work.mkdir(parents=True, exist_ok=True)
    clip = work / "current-plate.mp4"
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
    return (
        {**config, "media": {"plate-clip": str(clip)}},
        {**plate, "clip_sha256": sha256(clip)},
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
        plate = None
        if card["id"] == FLOW_GROUP:
            config, plate = _flow_clip(original, config, data, work)
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
        scene.write_text(updated, encoding="utf-8")
        atomic_json(
            receipt,
            {
                "sidecar_sha256": digest,
                "scene_sha256": sha256(scene),
                "materialized_attributes": attrs,
                **({"plate": plate} if plate is not None else {}),
            },
        )
        return result

    original.hypit_materialize = bind
