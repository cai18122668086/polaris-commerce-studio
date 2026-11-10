"""Read and merge exact local dependencies without replacing original registrations."""

import json
import os
from pathlib import Path
from typing import Any, Literal

from .motion_library import (
    MOTION_SHA256,
    atomic_json,
    read_json,
    sha256,
    verify_package,
)

DependencyState = Literal[
    "not_registered", "file_missing", "identity_mismatch", "verified"
]
_MANIFEST_LIMIT = 1_000_000


def read_dependency_manifest(manifest: Path | None) -> dict[str, Any]:
    if manifest is None or not manifest.is_file():
        return {}
    if manifest.stat().st_size > _MANIFEST_LIMIT:
        raise ValueError("Private original dependency manifest is too large")
    document = read_json(manifest)
    if not isinstance(document, dict):
        raise ValueError("Invalid private original dependency manifest")
    return document


def save_dependency_manifest(manifest: Path, previous: dict, updated: dict) -> None:
    payload = json.dumps(updated, ensure_ascii=False, indent=2) + "\n"
    if len(payload.replace("\n", os.linesep).encode("utf-8")) > _MANIFEST_LIMIT:
        raise ValueError("Private original dependency manifest is too large")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    # Share the original browser intake lock, including older local operators.
    lock = manifest.with_name(manifest.name + ".browser-intake.lock")
    lock.open("x", encoding="utf-8").close()
    try:
        if read_dependency_manifest(manifest) != previous:
            raise ValueError("Private bindings changed during intake; run again")
        atomic_json(manifest, updated)
    finally:
        lock.unlink()


def local_dependencies(manifest: Path | None) -> dict[str, str]:
    try:
        resources = read_dependency_manifest(manifest).get("resources")
    except (OSError, ValueError):
        return {}
    if not isinstance(resources, dict):
        return {}
    return {
        rid: value
        for rid, value in resources.items()
        if isinstance(value, str) and Path(value).is_absolute()
    }


def dependency_state(identity: dict, binding: str | None) -> DependencyState:
    if not binding:
        return "not_registered"
    path = Path(binding)
    try:
        if not path.is_file():
            return "file_missing"
        if (
            identity.get("kind") not in {"font", "model"}
            or (
                identity.get("bytes") is not None
                and path.stat().st_size != identity["bytes"]
            )
            or sha256(path) != identity.get("sha256")
        ):
            return "identity_mismatch"
    except (OSError, ValueError):
        return "file_missing"
    return "verified"


def intake_local_dependencies(
    package: Path,
    manifest: Path,
    candidates: dict[str, Path],
    *,
    origin: str = "",
    apply: bool = False,
) -> dict[str, Any]:
    """Match explicitly supplied font/model bytes and merge an all-valid batch."""
    package, manifest = package.resolve(), manifest.resolve()
    origin = origin.strip()
    if manifest.is_relative_to(package) or manifest.is_dir():
        raise ValueError("Private bindings must be a file outside the original library")
    if not candidates or (apply and not 0 < len(origin) <= 240):
        raise ValueError("Supply exact candidates and a delivery reference to register")
    verify_package(package)
    identities = {
        row["id"]: row
        for row in read_json(package / "catalog/external-resources.json")["resources"]
        if row["kind"] in {"font", "model"} and row.get("sha256")
    }
    if not candidates.keys() <= identities.keys():
        raise ValueError("Each candidate needs an indexed original font or model ID")
    previous = read_dependency_manifest(manifest)
    resources = previous.get("resources", {})
    receipts = previous.get("resource_intake", {})
    if not isinstance(resources, dict) or not isinstance(receipts, dict):
        raise ValueError("Invalid private original dependency manifest")
    merged, intake = resources.copy(), receipts.copy()
    rows = []
    for rid, candidate in sorted(candidates.items()):
        candidate = candidate.resolve()
        if candidate.is_relative_to(package):
            raise ValueError("Original deliveries must remain outside the library")
        identity = identities[rid]
        state = dependency_state(identity, str(candidate))
        current = resources.get(rid)
        retain = (
            isinstance(current, str)
            and Path(current).is_absolute()
            and dependency_state(identity, current) == "verified"
        )
        rows.append(
            {
                "id": rid,
                "kind": identity["kind"],
                "sha256": identity["sha256"],
                "bytes": identity.get("bytes"),
                "original_rights": identity.get("rights"),
                "candidate": state,
                "retains_verified_binding": retain,
            }
        )
        if state == "verified" and not retain:
            merged[rid] = str(candidate)
            intake[rid] = {
                "library_release": MOTION_SHA256,
                "sha256": identity["sha256"],
                "delivery_reference": origin,
            }
    ready = all(row["candidate"] == "verified" for row in rows)
    changed = apply and ready and merged != resources
    if changed:
        save_dependency_manifest(
            manifest,
            previous,
            {**previous, "resources": merged, "resource_intake": intake},
        )
    return {
        "scope": "exact_local_dependency_intake",
        "library_release": MOTION_SHA256,
        "ready": ready,
        "manifest_updated": changed,
        "resources": rows,
    }
