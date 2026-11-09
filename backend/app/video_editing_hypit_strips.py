"""Bind current text and timing to the original Hypit stagger scenes."""

import hashlib
import importlib
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, cast

from .motion_library import atomic_json, read_json, sha256
from .video_editing_hypit import NATIVE_FILES

STRIP_PROFILE = "hypit-original-strips/1"
PRICE_CARD_GROUP = "HY-A6"
PRICE_CARD_PROFILE = "hypit-original-price-cards/1"
PRICE_CARD_INSET_TYPE = "larger-inset-type-v1"
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
    return PRICE_CARD_PROFILE if group_id == PRICE_CARD_GROUP else STRIP_PROFILE


def stagger_events(group_id: str) -> tuple[str, ...]:
    return CARD_EVENTS if group_id == PRICE_CARD_GROUP else STRIP_EVENTS


def stagger_audio_frame(group_id: str, entry_frame: int) -> int:
    # In the pinned wipe and zoom profiles, the entry marker still has zero
    # visibility. The original component first changes pixels on the next frame.
    return entry_frame + int(group_id in {"HY-A5", PRICE_CARD_GROUP})


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
    scene = entry.read_text(encoding="utf-8")
    tag = re.search(rf'<stagger:Entry id="{node}"[^>]*?\n    items="([^"]*)"', scene)
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
    if (
        set(text) != set(titles + detail)
        or set(events) != set(anchors)
        or set(media) != set(images)
        or len(set(media.values())) != len(images)
    ):
        raise ValueError("Bind all original Hypit text roles and distinct media slots")
    if any(
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
            },
        )
        return result

    original.hypit_materialize = bind
