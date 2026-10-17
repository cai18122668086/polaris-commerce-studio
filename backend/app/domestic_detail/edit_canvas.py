"""Transport the exact native edit canvas as an image, never as a product fact."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..aurora_detail_runtime import AuroraDetailHarnessRunner
from ..provider import ProviderArtifact
from .generation import (
    DetailGenerationError,
    verify_accepted_canvas,
    verify_original_invocation,
)
from .pixels import load_native_pair_pixels


def resolve_native_edit_canvas(
    runner: AuroraDetailHarnessRunner,
    workspace: Path,
    state: Mapping[str, Any],
    request: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> tuple[ProviderArtifact, dict[str, Any]] | None:
    """Verify the first current-cycle draft or explicitly inherited original pair."""
    try:
        modules = {row["id"]: row for row in state["modules"]}
        pair = [modules[name] for name in request["module_ids"]]
        if len(pair) != 2:
            raise ValueError("An edit requires its exact approved pair")
        first = pair[0]
        cycle = first.get("cycle_id", 1)
        attempts = [
            a for a in first.get("attempts", []) if a.get("cycle_id", 1) == cycle
        ]
        raw_path = request.get("edit_target")
        if raw_path is None:
            if attempts or first.get("user_adjustment"):
                raise ValueError(
                    "A repair or local revision must carry its original edit canvas"
                )
            return None
        path = Path(raw_path)
        if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
            raise ValueError("An edit canvas cannot traverse links")
        if attempts:
            if len(attempts) != 1 or any(
                m.get("cycle_attempt_count", 0) != 1 for m in pair
            ):
                raise ValueError(
                    "Only the first current-cycle draft may open the one repair"
                )
            base = attempts[0]
            if path.resolve() != Path(base["pair_canvas"]).resolve():
                raise ValueError(
                    "Repair canvas differs from the first current-cycle draft"
                )
            roots = [workspace]
            lineage = runner.run(
                "inspect-pair-artifacts",
                workspace,
                {
                    "session": workspace / "session.json",
                    "pair-id": request["pair_id"],
                    "selection": "LATEST_RECORDED",
                },
            )
            verify_original_invocation(
                roots,
                binding,
                pair_id=request["pair_id"],
                artifact_sha256=lineage["source"]["sha256"],
                token=lineage["token"],
                signed_request_sha256=lineage["signed_request_sha256"],
            )
        else:
            fork = state.get("revision_fork") or {}
            source = workspace / "source-session.json"
            if hashlib.sha256(source.read_bytes()).hexdigest() != fork.get(
                "source_session_sha256"
            ):
                raise ValueError("Original local revision snapshot changed")
            original = json.loads(source.read_bytes())
            intent = json.loads((workspace / "local-revision-intent.json").read_bytes())
            root = Path(original["session_dir"])
            original_binding = json.loads(
                (root / "generation-binding.json").read_bytes()
            )
            if original_binding["sha256"] != intent.get(
                "source_generation_binding_sha256"
            ):
                raise ValueError(
                    "Local revision needs its verified original generation binding"
                )
            prior = next(m for m in original["modules"] if m["id"] == first["id"])
            base = next(
                a
                for a in reversed(prior["attempts"])
                if a["image"] == prior["accepted_asset"]
            )
            if path.resolve() != Path(base["pair_canvas"]).resolve():
                raise ValueError(
                    "Local revision canvas differs from the original accepted pair"
                )
            roots = [root]
            lineage = verify_accepted_canvas(
                roots,
                original_binding,
                pair_id=request["pair_id"],
                artifact_sha256=base["normalized_image_sha256"],
            )
        pixels = load_native_pair_pixels(
            lineage, roots, group_key=request.get("pair_id", "edit")
        )
        if (
            path.resolve() != Path(lineage["canvas"]["path"]).resolve()
            or pixels.canvas.sha256 != base["normalized_image_sha256"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != pixels.canvas.sha256
        ):
            raise ValueError(
                "Actual edit canvas differs from its paid native pixel lineage"
            )
        proof = {
            "path": str(path.resolve()),
            "sha256": pixels.canvas.sha256,
            "pixel_lineage_sha256": lineage["sha256"],
            "original_response_sha256": lineage["source"]["sha256"],
            "signed_request_sha256": lineage["signed_request_sha256"],
            "source_role": "generated_edit_canvas",
        }
        return pixels.canvas, proof
    except DetailGenerationError:
        raise
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        raise DetailGenerationError(
            "NATIVE_DETAIL_EDIT_CANVAS_INVALID", str(exc)
        ) from exc
