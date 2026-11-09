"""Read the original binder's private manifest and verify exact local dependencies."""

from pathlib import Path
from typing import Literal

from .motion_library import read_json, sha256

DependencyState = Literal[
    "not_registered", "file_missing", "identity_mismatch", "verified"
]


def local_dependencies(manifest: Path | None) -> dict[str, str]:
    if manifest is None:
        return {}
    try:
        if manifest.stat().st_size > 1_000_000:
            return {}
        resources = read_json(manifest)["resources"]
    except (OSError, ValueError, KeyError, TypeError):
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
