"""Read and merge exact local dependencies without replacing original registrations."""

import json
import os
from pathlib import Path
from typing import Any, Literal

from .motion_library import (
    MOTION_SHA256,
    atomic_json,
    inside,
    read_json,
    sha256,
    verify_package,
)

DependencyState = Literal[
    "not_registered", "file_missing", "identity_mismatch", "verified"
]
ComponentUseState = Literal["reference_required", "reference_recorded"]
FontUseScope = Literal["component", "episode"]
NONCOMMERCIAL_FONT = "noncommercial_marked_no_commercial_or_redistribution_claim"
_MANIFEST_LIMIT = 1_000_000
_REGISTRY_PREFIX = "registry://"


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


def resolve_local_binding(manifest: Path | None, value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    if Path(value).is_absolute():
        return value
    if manifest is None or not value.startswith(_REGISTRY_PREFIX):
        return None
    relative = value.removeprefix(_REGISTRY_PREFIX)
    if (
        not relative
        or "\\" in relative
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        return None
    try:
        return str(inside(manifest.resolve().parent, relative))
    except (OSError, ValueError, RuntimeError):
        return None


def local_binding_reference(manifest: Path, path: Path, *, portable: bool) -> str:
    if not portable:
        return str(path)
    try:
        relative = path.relative_to(manifest.parent).as_posix()
    except ValueError as exc:
        raise ValueError(
            "Portable dependencies must be stored under the bindings directory"
        ) from exc
    reference = _REGISTRY_PREFIX + relative
    if resolve_local_binding(manifest, reference) != str(path):
        raise ValueError("Portable dependency path escapes the registry")
    return reference


def local_dependencies(manifest: Path | None) -> dict[str, str]:
    try:
        resources = read_dependency_manifest(manifest).get("resources")
    except (OSError, ValueError):
        return {}
    if not isinstance(resources, dict):
        return {}
    return {
        rid: path
        for rid, value in resources.items()
        if (path := resolve_local_binding(manifest, value)) is not None
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


def _requires_component_reference(identity: dict) -> bool:
    return (
        identity.get("kind") == "font" and identity.get("rights") == NONCOMMERCIAL_FONT
    )


def _font_use_reference(
    identity: dict, intake: dict, scope: FontUseScope
) -> str | None:
    if not _requires_component_reference(identity):
        return None
    receipt = intake.get(identity["id"])
    if (
        not isinstance(receipt, dict)
        or receipt.get("library_release") != MOTION_SHA256
        or receipt.get("sha256") != identity["sha256"]
    ):
        return None
    reference = receipt.get(f"{scope}_use_reference")
    return (
        reference
        if isinstance(reference, str) and 0 < len(reference.strip()) <= 240
        else None
    )


def component_use_state(
    identity: dict, manifest: Path | None
) -> ComponentUseState | None:
    return font_use_state(identity, manifest, "component")


def font_use_state(
    identity: dict, manifest: Path | None, scope: FontUseScope
) -> ComponentUseState | None:
    if not _requires_component_reference(identity):
        return None
    try:
        receipts = read_dependency_manifest(manifest).get("resource_intake")
    except (OSError, ValueError):
        receipts = None
    if isinstance(receipts, dict) and _font_use_reference(identity, receipts, scope):
        return "reference_recorded"
    return "reference_required"


def intake_local_dependencies(
    package: Path,
    manifest: Path,
    candidates: dict[str, Path],
    *,
    origin: str = "",
    component_references: dict[str, str] | None = None,
    episode_references: dict[str, str] | None = None,
    apply: bool = False,
    portable: bool = False,
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
    references: dict[FontUseScope, dict[str, str]] = {
        "component": component_references or {},
        "episode": episode_references or {},
    }
    for scope, supplied in references.items():
        if not supplied.keys() <= candidates.keys() or any(
            not _requires_component_reference(identities[rid])
            or not 0 < len(value.strip()) <= 240
            for rid, value in supplied.items()
        ):
            raise ValueError(
                f"A {scope} use reference needs a matching restricted font"
            )
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
        binding = local_binding_reference(manifest, candidate, portable=portable)
        identity = identities[rid]
        state = dependency_state(identity, str(candidate))
        current = resolve_local_binding(manifest, resources.get(rid))
        retain = dependency_state(identity, current) == "verified"
        change_path = not retain or (portable and resources.get(rid) != binding)
        rows.append(
            {
                "id": rid,
                "kind": identity["kind"],
                "sha256": identity["sha256"],
                "bytes": identity.get("bytes"),
                "original_rights": identity.get("rights"),
                "candidate": state,
                "retains_verified_binding": not change_path,
            }
        )
        if state != "verified":
            continue
        if change_path:
            merged[rid] = binding
        if change_path or any(rid in supplied for supplied in references.values()):
            prior = receipts.get(rid) if retain else None
            intake[rid] = {
                "delivery_reference": origin,
                **(prior if isinstance(prior, dict) else {}),
                "library_release": MOTION_SHA256,
                "sha256": identity["sha256"],
                **{
                    f"{scope}_use_reference": reference
                    for scope, supplied in references.items()
                    if (
                        reference := supplied.get(rid, "").strip()
                        or _font_use_reference(identity, receipts, scope)
                    )
                },
            }
    ready = all(row["candidate"] == "verified" for row in rows)
    changed = apply and ready and (merged != resources or intake != receipts)
    if changed:
        save_dependency_manifest(
            manifest,
            previous,
            {**previous, "resources": merged, "resource_intake": intake},
        )
    for row in rows:
        identity = identities[row["id"]]
        if _requires_component_reference(identity):
            for scope, supplied in references.items():
                row[f"{scope}_use_state"] = (
                    "reference_recorded"
                    if _font_use_reference(
                        identity, intake if changed else receipts, scope
                    )
                    else "reference_required"
                )
                row[f"{scope}_use_reference_supplied"] = row["id"] in supplied
    return {
        "scope": "exact_local_dependency_intake",
        "library_release": MOTION_SHA256,
        "ready": ready,
        "manifest_updated": changed,
        "resources": rows,
    }
