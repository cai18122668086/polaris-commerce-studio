"""Stage measured presenter sequences for pinned original unified slots."""

import hashlib
import importlib
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from PIL import ImageOps

from .motion_library import atomic_json, read_json, sha256
from .video_editing_contracts import SemanticBeat, Transcript
from .video_editing_hypit_foreground import FOREGROUND_MATTE, load_foreground_source
from .video_editing_paper_typewriter import PAPER_GROUP

PAPER_CHAPTER_GROUP = "Z-M05"
GHOST_GROUP = "Z-M17"
ALPHA_PRESENTER = "/media/presenter/path"
_ALPHA_POLICIES = {
    PAPER_GROUP: "original_typewriter_alpha_sequence",
    PAPER_CHAPTER_GROUP: "original_chapter_alpha_sequence",
    GHOST_GROUP: "original_ghost_alpha_sequence",
}
ALPHA_GROUPS = frozenset(_ALPHA_POLICIES)
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


_COMMON_BATCH_SOURCES = {
    path: digest
    for path, digest in _NATIVE_SOURCES.items()
    if path.startswith("unified/")
}
_GHOST_RUNTIME = (
    "src/engines/workspace/郑涵文_商业口播_三条拆解_20261103/"
    "experiments/mechanism-library/runtime.py"
)
_BATCH_RUNTIME_SHA = "8f716e5cfcd6ae297c0f0050ef1b0b9fdf5598827f97b7cd7f59de55e9b7c2aa"
_RUNTIME11_SHA = "0991fd851fb222f8b56ca427cc69e678b0bb8034668802b6b1fc7258d7c33310"
_PROFILE_SOURCES = {
    PAPER_GROUP: _NATIVE_SOURCES,
    PAPER_CHAPTER_GROUP: {
        **_COMMON_BATCH_SOURCES,
        "batch-Z-M04-M06/frozen/runtime.py": _BATCH_RUNTIME_SHA,
    },
    GHOST_GROUP: {
        "unified/runtime11.py": _RUNTIME11_SHA,
        "unified/planning.py": _NATIVE_SOURCES["unified/planning.py"],
        "unified/core/typography.py": _NATIVE_SOURCES["unified/core/typography.py"],
        _GHOST_RUNTIME: _BATCH_RUNTIME_SHA,
    },
}


def alpha_presenter_directory(group_id: str) -> str:
    return "paper-foreground" if group_id == PAPER_GROUP else "presenter-foreground"


def alpha_source_clock(
    beat: SemanticBeat, native: dict, transcript: Transcript, assets: dict
) -> dict:
    if len(native["media"]) != 1 or native["media"][0]["path"] != ALPHA_PRESENTER:
        raise ValueError("Use the original unified alpha presenter slot")
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
        raise ValueError("Foreground must use the measured current presenter")
    prefix = "paper-" if beat.group_id == PAPER_GROUP else "unified-alpha-"
    return {
        "policy": _ALPHA_POLICIES[beat.group_id],
        "media_path": ALPHA_PRESENTER,
        "asset_id": asset_id,
        "binding_id": prefix + hashlib.sha256(beat.id.encode()).hexdigest()[:24],
        "source_sha256": transcript.source_sha256,
        "source_start_ms": start,
        "source_end_ms": end,
        "frames": frames,
        "fps": _FPS,
        "timing_review": "unreviewed",
    }


def stage_unified_sequences(package: Path, root: Path, kind: str) -> dict[str, Path]:
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
        group = compiled["group_id"]
        if group not in ALPHA_GROUPS:
            continue
        for clock in compiled["media_clocks"]:
            if clock["policy"] == _ALPHA_POLICIES[group]:
                sequences["input://" + clock["binding_id"]] = _stage_sequence(
                    package, root, receipt.parent, compiled, clock
                )
    return sequences


def _stage_sequence(
    package: Path, root: Path, part: Path, compiled: dict, clock: dict
) -> Path:
    job = part / "job.json"
    resources = read_json(root / "bindings.json")["resources"]
    rid = clock["binding_id"]
    group = compiled["group_id"]
    native_sources = _PROFILE_SOURCES[group]
    separate_alpha = group == GHOST_GROUP
    destination = part / alpha_presenter_directory(group)
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
            sha256(package / (p if p.startswith("src/") else _OWNER + p)) != digest
            for p, digest in native_sources.items()
        )
    ):
        raise ValueError("Original sequence inputs or native code changed")
    expected: dict[str, Any] = {
        "clock": clock,
        "model_sha256": identity["sha256"],
        "size": list(_SIZE),
        "native_sequence_sources": native_sources,
    }
    names = [f"{i:04d}.png" for i in range(clock["frames"])]
    masks = (
        [name.removesuffix(".png") + "-alpha.png" for name in names]
        if separate_alpha
        else []
    )
    receipt = destination / "sequence.json"
    if destination.exists():
        old = read_json(receipt)
        if old == {
            **expected,
            "frames": {name: sha256(destination / name) for name in (*names, *masks)},
        }:
            return receipt
        raise ValueError("Original foreground cache differs from its receipt")
    with TemporaryDirectory(prefix="alpha-", dir=part) as work:
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
                raise ValueError(
                    "Original sequence frame has no usable presenter alpha"
                )
            if separate_alpha:
                mask_name = masks[i]
                frame.convert("RGB").save(frames / name)
                cutout.getchannel("A").save(frames / mask_name)
                hashes[mask_name] = sha256(frames / mask_name)
            else:
                cutout.save(frames / name)
            hashes[name] = sha256(frames / name)
        atomic_json(frames / "sequence.json", {**expected, "frames": hashes})
        os.replace(frames, destination)
    return receipt


def install_unified_sequence_audit(package: Path, sequences: dict[str, Path]) -> None:
    """The original editorial audit accepts files; give it each verified index."""
    if not sequences:
        return
    path = package / "commercial_runtime/editorial.py"
    if sha256(path) != _EDITORIAL_SHA:
        raise ValueError("Original alpha sequence material audit changed")
    sys.path.insert(0, str(package))
    try:
        editorial: Any = importlib.import_module("commercial_runtime.editorial")
    finally:
        sys.path.pop(0)
    if Path(editorial.__file__).resolve() != path:
        raise ValueError("Alpha sequences require the original editorial audit")
    audit = editorial.audit

    def audit_with_sequences(episode: dict) -> dict:
        shots = []
        materials = list(episode["production"]["materials"])
        for shot in episode["shots"]:
            config = shot["config"]
            media = config.get("media", {})
            presenter = media.get("presenter", {})
            ref = presenter.get("path") if isinstance(presenter, dict) else None
            if shot["group_id"] in ALPHA_GROUPS and ref in sequences:
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
