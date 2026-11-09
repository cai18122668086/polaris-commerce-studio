"""Bind current labels to two original Hypit strip scenes."""

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
STRIP_SIDECAR = "hypit-strips/component.json"
STRIP_GROUPS = {
    "HY-A4": (
        "a4m",
        "b02ffa4c994e697eb3af1405483df2fd2d2e42d02fa035bdfb4663b49c416ddb",
    ),
    "HY-A5": (
        "a5m",
        "aefef4aa6e1f9d10c58bc9c50b5df4538c68ed2352af00a0f6e5d32fa4cb4ed6",
    ),
}
STRIP_IMAGE = "/component_assets/stagger#mkstage1"
STRIP_TEXT = tuple(f"/hypit_labels/{i}/text" for i in range(3))
STRIP_EVENTS = tuple(f"/hypit_labels/{i}/entry_frame" for i in range(3))
_HAN_LABEL = re.compile(r"[\u3400-\u9fff]{1,3}")


def strip_fields() -> list[dict[str, str]]:
    return [
        {
            "path": path,
            "category": "text",
            "value_type": "str",
            "binding_surface": "website_sidecar",
        }
        for path in STRIP_TEXT
    ] + [
        {
            "path": path,
            "category": "event",
            "unit": "frames",
            "value_type": "int",
            "binding_surface": "website_sidecar",
        }
        for path in STRIP_EVENTS
    ]


def strip_config_sha256(config: dict) -> str:
    return hashlib.sha256(
        json.dumps(config, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _native_attributes(package: Path, group: dict, data: dict) -> dict:
    node, expected = STRIP_GROUPS[group["id"]]
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
    labels, starts, frames = data["labels"], data["entry_frames"], data["frames"]
    if (
        len(parts) != 3
        or len(labels) != 3
        or any(not isinstance(s, str) or not _HAN_LABEL.fullmatch(s) for s in labels)
        or len(starts) != 3
        or any(type(n) is not int for n in starts)
        or starts != sorted(set(starts))
        or type(frames) is not int
        or not 0 <= starts[0] < starts[-1] <= frames - 9
        or frames > 450
    ):
        raise ValueError(
            "Hypit strips need three short labels and ordered entry frames"
        )
    items = "; ".join(
        f"{label}@{item.split('@', 1)[1]}"
        for label, item in zip(labels, parts, strict=True)
    )
    return {
        node: {"items": items, "frames": ",".join(map(str, starts))},
        "t": {"end": f"{frames}f"},
    }


def compile_strips(
    package: Path, group: dict, native: dict, assets: dict[str, dict[str, Any]]
) -> dict:
    text = {row["path"]: row for row in native["text"]}
    events = {row["path"]: row for row in native["events"]}
    media = native["media"]
    if (
        set(text) != set(STRIP_TEXT)
        or set(events) != set(STRIP_EVENTS)
        or len(media) != 1
        or media[0]["path"] != STRIP_IMAGE
    ):
        raise ValueError("Bind the three original Hypit strip roles and stage image")
    image = assets[media[0]["asset_id"]]
    if image.get("kind") != "image" or image.get("source") != "project_upload":
        raise ValueError(
            "Hypit strip stage requires a registered current project image"
        )
    if any(
        events[at]["token_id"] != text[label]["token_ids"][0]
        or events[at]["edge"] != "start"
        for label, at in zip(STRIP_TEXT, STRIP_EVENTS, strict=True)
    ):
        raise ValueError("Each Hypit strip entrance must use its spoken label start")
    clock = native["clock"]
    data = {
        "profile": STRIP_PROFILE,
        "group_id": group["id"],
        "labels": [text[path]["text"] for path in STRIP_TEXT],
        "entry_frames": [events[path]["value"] for path in STRIP_EVENTS],
        "frames": math.ceil((clock["end_ms"] - clock["start_ms"]) * 30 / 1000),
    }
    _native_attributes(package, group, data)
    return data


def install_native_strips(package: Path, root: Path) -> None:
    """Supply validated scalar parameters to the original materializer."""
    if "--job" not in sys.argv:
        return
    job_path = Path(sys.argv[sys.argv.index("--job") + 1]).resolve()
    if job_path.parent != root / "plans":
        return
    job = read_json(job_path)
    if job["group_id"] not in STRIP_GROUPS:
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
        data.get("profile") != STRIP_PROFILE
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
        node = STRIP_GROUPS[card["id"]][0]
        scene = result[0] / "scene.svml"
        # The original attribute reader stops at the '>' inside item direction
        # strings. Supply these two parameters on the instance copy it produced.
        items = re.compile(
            rf'(<stagger:Entry id="{node}"[^>]*?\n    items=")[^"]*("'
            r'\s+frames=")[^"]*(")'
        )
        updated, count = items.subn(
            lambda match: (
                f"{match[1]}{attrs[node]['items']}{match[2]}"
                f"{attrs[node]['frames']}{match[3]}"
            ),
            scene.read_text(encoding="utf-8"),
        )
        if count != 1:
            raise ValueError("Original instance strip attributes were not found once")
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
