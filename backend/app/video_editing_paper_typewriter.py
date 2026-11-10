"""Bind Z-M11 to the original moving alpha slot and measured character clock."""

import hashlib
import importlib
import os
import sys
from itertools import pairwise
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import ImageOps

from .motion_library import atomic_json, read_json, sha256
from .video_editing_contracts import SemanticBeat, Transcript
from .video_editing_hypit_foreground import FOREGROUND_MATTE, load_foreground_source
from .video_editing_word_bindings import emphasis_text

PAPER_GROUP = "Z-M11"
PAPER_TEMPLATE_ID = "unified-paper-typewriter-v1"
PAPER_PRESENTER = "/media/presenter/path"
PAPER_POLICY = "original_typewriter_alpha_sequence"
_FPS = 30
_SIZE = (540, 960)
_OWNER = "src/engines/workspace/商业口播_可编辑改造_20261104/"
_EDITORIAL_SHA = "532e286e95f6f024e73612f4c04de6564731d8da94efd5ddd0bfbbf5ebb8295a"
_NATIVE_SOURCES = dict(
    [
        (
            "unified/core/engine.py",
            "fc4d362751ec1f7adbe1ebcaee2481193805da3e5ee1b15239292235d5b3386c",
        ),
        (
            "unified/core/typography.py",
            "5fbf8fff517ff0d9fd551d9d661356499950a2cd246258e0eef1d2ed07b83333",
        ),
        (
            "unified/planning.py",
            "fad65d736665ab5198df3776d9c04103cdd38fb7e123ce4dfc9fe19eebba10b1",
        ),
        (
            "batch-Z-M10-M12/frozen/runtime.py",
            "5f76eb669347a44f4391ac3c44cadf9b33a329ab1e998d8195d169b33d1bc43f",
        ),
    ]
)


def paper_character_times(
    beat: SemanticBeat, native: dict, transcript: Transcript
) -> list[list[float]]:
    """All glyphs from one measured token appear on that token's own start."""
    tokens = {token.id: token for token in transcript.tokens}
    positions = {token_id: i for i, token_id in enumerate(tokens)}
    text = {row["path"]: row for row in native["text"]}
    events = {row["path"]: row for row in native["events"]}
    start, end = (native["clock"][key] for key in ("start_ms", "end_ms"))
    duration = round((end - start) * _FPS / 1000) / _FPS
    if beat.relation != "parallel" or len(beat.relation_items) != 2:
        raise ValueError("The paper requires two independently spoken rows")
    result = []
    for i, item in enumerate(beat.relation_items):
        label_path, body_path = (
            f"/content/rows/{i}/{key}" for key in ("label", "text")
        )
        label, body = text[label_path], text[body_path]
        event = events[f"/timing/events/row{i}"]
        pieces = [
            (emphasis_text(tokens[key].text, body["punctuation_policy"]), tokens[key])
            for key in body["token_ids"]
        ]
        values = [
            (token.start_ms - start) / 1000 for glyphs, token in pieces for _ in glyphs
        ]
        if (
            set(item.native_text_paths) != {label_path, body_path}
            or item.native_media_paths
            or item.asset_ids
            or not positions[item.first_token_id]
            <= positions[label["token_ids"][0]]
            <= positions[label["token_ids"][-1]]
            < positions[body["token_ids"][0]]
            <= positions[body["token_ids"][-1]]
            <= positions[item.last_token_id]
            or event["edge"] != "start"
            or event["token_id"] != label["token_ids"][0]
            or not 1 <= len(label["text"]) <= 3
            or not 1 <= len(body["text"]) <= 12
            or any(char.isspace() for char in label["text"] + body["text"])
            or "".join(glyphs for glyphs, _ in pieces) != body["text"]
            or not event["value"] <= values[0] <= values[-1] <= duration - 0.35
        ):
            raise ValueError(
                "Paper labels and glyphs need their own measured word range"
            )
        result.append(values)
    if (
        positions[beat.relation_items[0].last_token_id]
        >= positions[beat.relation_items[1].first_token_id]
        or result[0][-1] + 0.20 > events["/timing/events/row1"]["value"]
        or any(a > b for row in result for a, b in pairwise(row))
    ):
        raise ValueError("The original paper needs two ordered, readable rows")
    return result


def paper_source_clock(
    beat: SemanticBeat, native: dict, transcript: Transcript, assets: dict
) -> dict:
    if len(native["media"]) != 1 or native["media"][0]["path"] != PAPER_PRESENTER:
        raise ValueError("Use the original paper presenter slot")
    asset_id = native["media"][0]["asset_id"]
    asset = assets[asset_id]
    start, end = (native["clock"][key] for key in ("start_ms", "end_ms"))
    frames = round((end - start) * _FPS / 1000)
    if (
        asset["kind"] != "original_video"
        or asset["sha256"] != transcript.source_sha256
        or not 0 <= start < end <= transcript.duration_ms
        or not 15 <= frames <= 450
    ):
        raise ValueError("Paper foreground must use the measured current presenter")
    return {
        "policy": PAPER_POLICY,
        "media_path": PAPER_PRESENTER,
        "asset_id": asset_id,
        "binding_id": "paper-" + hashlib.sha256(beat.id.encode()).hexdigest()[:24],
        "source_sha256": transcript.source_sha256,
        "source_start_ms": start,
        "source_end_ms": end,
        "frames": frames,
        "fps": _FPS,
        "timing_review": "unreviewed",
    }


def stage_paper_sequences(package: Path, root: Path, kind: str) -> dict[str, Path]:
    sequences = {}
    receipts = (
        root.glob("compiled-native/*/compile-receipt.json")
        if kind == "episode"
        else (root / "compile-receipt.json",)
    )
    for receipt in receipts:
        if not receipt.is_file():
            continue
        compiled = read_json(receipt)
        if compiled["group_id"] != PAPER_GROUP:
            continue
        for clock in compiled["media_clocks"]:
            if clock["policy"] == PAPER_POLICY:
                sequences["input://" + clock["binding_id"]] = _stage_paper(
                    package, root, receipt.parent, compiled, clock
                )
    return sequences


def _stage_paper(
    package: Path, root: Path, part: Path, compiled: dict, clock: dict
) -> Path:
    job = part / "job.json"
    resources = read_json(root / "bindings.json")["resources"]
    rid = clock["binding_id"]
    destination = part / "paper-foreground"
    source = Path(resources[rid + "-source"]).resolve()
    model = Path(resources[FOREGROUND_MATTE]).resolve()
    descriptor = read_json(job)["config"]["media"]["presenter"]
    identity = next(
        row
        for row in read_json(package / "catalog/external-resources.json")["resources"]
        if row["id"] == FOREGROUND_MATTE
    )
    if (
        not part.resolve().is_relative_to(root)
        or sha256(job) != compiled["job_sha256"]
        or Path(resources[rid]).resolve() != destination
        or descriptor
        != {
            "kind": "frame_sequence",
            "path": "input://" + rid,
            "alpha": True,
            "frames": clock["frames"],
            "fps": _FPS,
            "end_policy": "error",
        }
        or sha256(source) != clock["source_sha256"]
        or sha256(model) != identity["sha256"]
        or any(
            sha256(package / (_OWNER + p)) != digest
            for p, digest in _NATIVE_SOURCES.items()
        )
    ):
        raise ValueError("Original paper sequence inputs or native code changed")
    expected: dict[str, Any] = {
        "clock": clock,
        "model_sha256": identity["sha256"],
        "size": list(_SIZE),
        "native_sequence_sources": _NATIVE_SOURCES,
    }
    names = [f"{i:04d}.png" for i in range(clock["frames"])]
    receipt = destination / "sequence.json"
    if destination.exists():
        old = read_json(receipt)
        if old == {
            **expected,
            "frames": {name: sha256(destination / name) for name in names},
        }:
            return receipt
        raise ValueError("Original paper foreground cache differs from its receipt")
    with TemporaryDirectory(prefix="paper-", dir=part) as work:
        stage = Path(work)
        media, matte = load_foreground_source(package, model, stage / "matte-cache")
        asset = media.inspect_asset(
            {
                "path": str(source),
                "kind": "video",
                "offset_seconds": clock["source_start_ms"] / 1000,
                "duration_seconds": clock["frames"] / _FPS,
                "end_policy": "error",
            }
        )
        frames = stage / "frames"
        frames.mkdir()
        hashes = {}
        for i, name in enumerate(names):
            frame = media.asset_frame(asset, i / _FPS, native_size=True)
            frame = ImageOps.contain(frame, _SIZE)
            cutout = matte.apply(
                frame, f"{clock['source_sha256']}-{clock['source_start_ms']}-{i}"
            )
            low, high = cutout.getchannel("A").getextrema()
            if low >= 255 or high <= 0:
                raise ValueError("Original paper frame has no usable presenter alpha")
            cutout.save(frames / name)
            hashes[name] = sha256(frames / name)
        atomic_json(frames / "sequence.json", {**expected, "frames": hashes})
        os.replace(frames, destination)
    return receipt


def install_paper_sequence_audit(package: Path, sequences: dict[str, Path]) -> None:
    """The original editorial audit accepts files; give it each verified index."""
    if not sequences:
        return
    path = package / "commercial_runtime/editorial.py"
    if sha256(path) != _EDITORIAL_SHA:
        raise ValueError("Original paper material audit changed")
    sys.path.insert(0, str(package))
    try:
        editorial: Any = importlib.import_module("commercial_runtime.editorial")
    finally:
        sys.path.pop(0)
    if Path(editorial.__file__).resolve() != path:
        raise ValueError("Paper materials require the original editorial audit")
    audit = editorial.audit

    def audit_with_sequences(episode: dict) -> dict:
        shots = []
        materials = list(episode["production"]["materials"])
        for shot in episode["shots"]:
            config = shot["config"]
            media = config.get("media", {})
            presenter = media.get("presenter", {})
            ref = presenter.get("path") if isinstance(presenter, dict) else None
            if shot["group_id"] == PAPER_GROUP and ref in sequences:
                receipt = sequences[ref]
                materials.append(
                    {
                        "id": ref.removeprefix("input://"),
                        "path": str(receipt),
                        "sha256": sha256(receipt),
                        "kind": "native_carrier",
                        "semantic_use": "同期原口播的逐帧透明人物。",
                    }
                )
                config = {
                    **config,
                    "media": {
                        **media,
                        "presenter": {**presenter, "path": str(receipt)},
                    },
                }
                shot = {**shot, "config": config}
            shots.append(shot)
        return audit(
            {
                **episode,
                "shots": shots,
                "production": {**episode["production"], "materials": materials},
            }
        )

    editorial.audit = audit_with_sequences
