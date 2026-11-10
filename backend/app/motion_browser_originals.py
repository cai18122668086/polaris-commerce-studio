"""Verify original browser images and freeze supplemental originals per attempt."""

import hashlib
import os
import re
from collections import Counter
from io import BytesIO
from pathlib import Path
from typing import Literal
from uuid import uuid4

from PIL import Image

from .motion_library import (
    MOTION_SHA256,
    inside,
    read_json,
    sha256,
    verify_package,
)
from .motion_local_dependencies import (
    read_dependency_manifest,
    save_dependency_manifest,
)
from .video_editing_browser_clocks import (
    FRUIT_LIST_GROUP,
    FRUIT_LIST_SOLID_BACKGROUND,
    fruit_list_uses_solid_background,
)

_G05_BACKGROUND = ("g05-assets/base-{i:03d}.jpg", 69)
_G05_ACTOR = ("g05-assets/actor-{i:03d}.png", 69)
_G05_PHOTOS = ("g05-assets/photo-{i}.jpg", 3)
_LEGACY_ACTOR = ("legacy/assets/img/person.png", 1)
_G06_BACKGROUND = ("legacy/assets/img/g06-bg.png", 1)
_G09_TEXTURES = ("assets/material-{i}.png", 3)
_G09_BACKGROUND = ("assets/g09-bg/{i:03d}.jpg", 66)
_G10_BACKGROUND = ("assets/G10-background-clean.jpg", 1)
_G10_ACTOR = ("assets/G10-person-clean.png", 1)
_G04_G06_STARTUP = (
    _G05_BACKGROUND,
    _G05_ACTOR,
    _G05_PHOTOS,
    _LEGACY_ACTOR,
    _G06_BACKGROUND,
)
_G08_G10_STARTUP = (
    _G09_TEXTURES,
    _G09_BACKGROUND,
    _G10_BACKGROUND,
    _G10_ACTOR,
    _LEGACY_ACTOR,
    _G06_BACKGROUND,
)
STARTUP_ASSETS = {
    **dict.fromkeys(("CX-G04", "CX-G05", FRUIT_LIST_GROUP), _G04_G06_STARTUP),
    **dict.fromkeys(("CX-G08", "CX-G09", "CX-G10"), _G08_G10_STARTUP),
}

# The shared entry loads every group's startup images. Only these paths are
# drawn in the requested branch, depending on the current presenter binding.
_ALWAYS_DRAWN = {"CX-G05": (_G05_BACKGROUND,), "CX-G09": (_G09_TEXTURES,)}
_DRAWN_WITHOUT_PRESENTER = {
    "CX-G04": (_LEGACY_ACTOR,),
    "CX-G05": (_G05_ACTOR,),
    FRUIT_LIST_GROUP: (_LEGACY_ACTOR,),
    "CX-G08": (_LEGACY_ACTOR,),
    "CX-G09": (_G09_BACKGROUND,),
    "CX-G10": (_G10_BACKGROUND, _G10_ACTOR),
}
RENDER_GROUPS = frozenset(_ALWAYS_DRAWN | _DRAWN_WITHOUT_PRESENTER)
BROWSER_ORIGINALS_REQUIRED = "EDITING_ORIGINAL_BROWSER_ASSETS_REQUIRED"
BROWSER_ORIGINALS_KEY = "tengli_browser_originals"
_IMAGE_LIMIT = 16 * 1024 * 1024
DeliveryScope = Literal["original_delivery", "diagnostic"]


class BrowserOriginalsMissing(ValueError):
    def __init__(self, group_id: str, missing: dict[str, int]) -> None:
        self.missing = missing
        super().__init__(
            f"{group_id}: missing verified original browser images {missing}"
        )


def _needed(group_id: str, config: dict) -> dict[str, list[int]]:
    needed: tuple[tuple[str, int], ...] = _ALWAYS_DRAWN.get(group_id, ())
    if group_id == FRUIT_LIST_GROUP and not fruit_list_uses_solid_background(config):
        needed += (_G06_BACKGROUND,)
    if not config.get("presenter"):
        needed += _DRAWN_WITHOUT_PRESENTER.get(group_id, ())
    result = {pattern: list(range(count)) for pattern, count in needed}
    if group_id == "CX-G05":
        # The original state() falls back to photo-j when that item has no image.
        photos = [
            i for i, item in enumerate(config.get("items", [])) if not item.get("image")
        ]
        if photos:
            result[_G05_PHOTOS[0]] = photos
    return result


def _original_index(package: Path) -> tuple[dict, dict, dict]:
    return (
        read_json(package / "integrity.json")["files"],
        read_json(package / "catalog/native-relative-assets.json"),
        {
            row["id"]: row
            for row in read_json(package / "catalog/external-resources.json")[
                "resources"
            ]
        },
    )


def _original_image(
    package: Path,
    relative: str,
    index: tuple[dict, dict, dict],
    supplied: dict,
    stage: Path | None,
    *,
    allow_diagnostic: bool = False,
) -> dict[str, str] | None:
    archived, aliases, identities = index
    expected = archived.get(relative)
    if expected is not None:
        if sha256(inside(package, relative)) != expected:
            raise ValueError("Packaged browser image changed")
        return None
    alias = aliases.get(relative, "")
    if alias and not alias.startswith("input://"):
        raise ValueError("Unsupported original browser image alias")
    identity = identities[alias[8:]] if alias else None
    return _verified_supplement(
        relative, supplied[relative], identity, stage, allow_diagnostic=allow_diagnostic
    )


_IMAGE_ERRORS = (
    OSError,
    ValueError,
    KeyError,
    TypeError,
    SyntaxError,
    Image.DecompressionBombError,
)


def _selection(
    package: Path,
    group: dict,
    needed: dict[str, list[int]],
    supplied: dict,
    stage: Path | None,
    *,
    allow_diagnostic: bool,
) -> dict[str, dict[str, str]]:
    index = (
        _original_index(package)
        if supplied
        else (read_json(package / "integrity.json")["files"], {}, {})
    )
    missing = {}
    selected = {}
    for pattern, indices in needed.items():
        missing_count = 0
        for i in indices:
            relative = f"{group['browser_directory']}/{pattern.format(i=i)}"
            try:
                original = _original_image(
                    package,
                    relative,
                    index,
                    supplied,
                    stage,
                    allow_diagnostic=allow_diagnostic,
                )
                if original is not None:
                    selected[relative] = original
            except _IMAGE_ERRORS:
                missing_count += 1
        if missing_count:
            missing[pattern] = missing_count
    if missing:
        raise BrowserOriginalsMissing(group["id"], missing)
    return selected


def _verified_supplement(
    relative: str,
    row: dict,
    identity: dict | None,
    stage: Path | None,
    *,
    allow_diagnostic: bool,
) -> dict[str, str]:
    if not isinstance(row, dict):
        raise ValueError("Invalid supplemental browser image registration")
    scope = row.get("use_scope")
    if scope == "diagnostic":
        if not allow_diagnostic:
            raise ValueError("Diagnostic browser images cannot be used as originals")
    elif scope != "original_delivery" and (scope is not None or identity is None):
        # Legacy entries can still prove their origin with a pinned catalog digest.
        raise ValueError("Unindexed browser images need an explicit delivery scope")
    digest, origin = row["sha256"], row["original_source"]
    source = Path(row["path"])
    if (
        not source.is_absolute()
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not isinstance(origin, str)
        or not origin.strip()
        or len(origin) > 240
    ):
        raise ValueError(
            "A supplemental browser image needs exact bytes and provenance"
        )
    if identity and (identity["kind"] != "media" or identity["sha256"] != digest):
        raise ValueError("Supplement differs from the indexed original browser image")
    data = verified_image_bytes(source, digest)
    extension = Path(relative).suffix
    if identity and len(data) != identity["bytes"]:
        raise ValueError("Supplement length differs from the indexed original")
    with Image.open(BytesIO(data)) as image:
        if image.format != {".jpg": "JPEG", ".png": "PNG"}[extension]:
            raise ValueError("Supplement format differs from the original filename")
        image.verify()
    if stage is not None:
        stage.mkdir(parents=True, exist_ok=True)
        target = inside(stage, digest + extension)
        if not target.exists():
            pending = stage / f".{uuid4().hex}.tmp"
            try:
                pending.write_bytes(data)
                os.replace(pending, target)
            finally:
                pending.unlink(missing_ok=True)
        elif sha256(target) != digest:
            raise ValueError("Frozen browser image changed")
        source = target
    return {
        "path": str(source.resolve()),
        "sha256": digest,
        "original_source": origin,
        "identity": (
            "catalog_sha256"
            if identity
            else "diagnostic"
            if scope == "diagnostic"
            else "operator_attested"
        ),
        **({"use_scope": scope} if scope is not None else {}),
    }


def verified_image_bytes(path: Path, digest: str) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(_IMAGE_LIMIT + 1)
    if len(data) > _IMAGE_LIMIT or hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Supplemental browser image bytes changed")
    return data


def _registry_files(document: dict) -> dict:
    registry = document.get("browser_startup_originals")
    if registry is None:
        return {}
    if (
        not isinstance(registry, dict)
        or registry.get("library_release") != MOTION_SHA256
        or not isinstance(registry.get("files"), dict)
    ):
        raise ValueError("Browser originals belong to another library release")
    return registry["files"]


def _registered_originals(manifest: Path | None) -> dict:
    return _registry_files(read_dependency_manifest(manifest))


def _incoming_image(
    source: Path, relative: str, origin: str, scope: DeliveryScope
) -> dict | None:
    path = inside(source, relative)
    if not path.exists():
        return None
    if not path.is_file() or path.stat().st_size > _IMAGE_LIMIT:
        raise ValueError("Invalid supplemental browser image file")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "original_source": origin,
        "use_scope": scope,
    }


def _save_intake(manifest: Path, previous: dict, files: dict) -> None:
    updated = {
        **previous,
        "browser_startup_originals": {
            **(previous.get("browser_startup_originals") or {}),
            "library_release": MOTION_SHA256,
            "files": files,
        },
    }
    save_dependency_manifest(manifest, previous, updated)


def intake_browser_originals(
    package: Path,
    manifest: Path,
    *,
    source: Path | None = None,
    origin: str = "",
    scope: DeliveryScope | None = None,
    apply: bool = False,
) -> dict:
    """Check a private delivery tree at the package-relative native paths."""
    package, manifest = package.resolve(), manifest.resolve()
    source = source.resolve() if source is not None else None
    origin = origin.strip()
    if manifest.is_relative_to(package) or manifest.is_dir():
        raise ValueError("Private bindings must be a file outside the original library")
    if source is not None and (
        source.is_relative_to(package)
        or not source.is_dir()
        or not 0 < len(origin) <= 240
    ):
        raise ValueError("Supply an external delivery directory and its provenance")
    if source is not None and scope not in ("original_delivery", "diagnostic"):
        raise ValueError("Classify the delivery as original or diagnostic")
    if apply and source is None:
        raise ValueError("Registering originals requires a delivery directory")
    verify_package(package)
    document = read_dependency_manifest(manifest)
    registered = _registry_files(document)
    index = _original_index(package)
    archived, aliases, identities = index
    slots: dict[str, list[str]] = {}
    for group in read_json(package / "catalog/groups.json")["groups"]:
        for pattern, count in STARTUP_ASSETS.get(group["id"], ()):
            for i in range(count):
                relative = f"{group['browser_directory']}/{pattern.format(i=i)}"
                slots.setdefault(relative, []).append(group["id"])

    accepted = {}
    report = []
    for relative, groups in sorted(slots.items()):
        row: dict = {"native_path": relative, "groups": groups, "status": "missing"}
        report.append(row)
        if relative in archived:
            row["status"] = "verified_bundled"
            continue
        alias = aliases.get(relative, "")
        if alias.startswith("input://"):
            identity = identities[alias[8:]]
            row["catalog_identity"] = {
                key: identity[key] for key in ("id", "sha256", "bytes")
            }
        if relative in registered:
            try:
                checked = _original_image(
                    package, relative, index, registered, None, allow_diagnostic=True
                )
            except _IMAGE_ERRORS:
                row["status"] = "invalid_registration"
            else:
                assert checked is not None
                diagnostic = checked.get("use_scope") == "diagnostic"
                row.update(
                    status="diagnostic_registered"
                    if diagnostic
                    else "verified_registered",
                    identity=checked["identity"],
                    sha256=checked["sha256"],
                )
                if not diagnostic or scope != "original_delivery":
                    continue
        if source is None or scope is None:
            continue
        try:
            candidate = _incoming_image(source, relative, origin, scope)
            if candidate is None:
                continue
            checked = _original_image(
                package,
                relative,
                index,
                {relative: candidate},
                None,
                allow_diagnostic=True,
            )
        except _IMAGE_ERRORS:
            row["status"] = "rejected_candidate"
        else:
            assert checked is not None
            prior = registered.get(relative)
            if (
                isinstance(prior, dict)
                and prior.get("use_scope") == "diagnostic"
                and checked["identity"] == "operator_attested"
                and prior.get("sha256") == checked["sha256"]
            ):
                row["status"] = "rejected_diagnostic_candidate"
                continue
            accepted[relative] = candidate
            row.update(
                status="registered" if apply else "ready_to_register",
                identity=checked["identity"],
                sha256=checked["sha256"],
                use_scope=scope,
            )
    if apply and accepted:
        _save_intake(manifest, document, {**registered, **accepted})
    return {
        "scope": "browser_original_intake",
        "library_release": MOTION_SHA256,
        "counts": dict(Counter(row["status"] for row in report)),
        "files": report,
    }


def original_startup_assets(
    package: Path, group: dict, manifest: Path | None = None
) -> list[dict]:
    """Report which original paths can be resolved without exposing host paths."""
    group_id = group["id"]
    paths = STARTUP_ASSETS.get(group_id)
    if not paths:
        return []
    index = _original_index(package)
    archived, aliases, _ = index
    try:
        supplied = _registered_originals(manifest)
        registry_invalid = False
    except (OSError, ValueError, KeyError, TypeError):
        supplied = {}
        registry_invalid = True
    result = []
    for pattern, count in paths:
        requirement = (pattern, count)
        expected = [
            f"{group['browser_directory']}/{pattern.format(i=i)}" for i in range(count)
        ]
        verified_packaged, verified_supplement = 0, 0
        missing = []
        for relative in expected:
            try:
                original = _original_image(package, relative, index, supplied, None)
                if original is None:
                    verified_packaged += 1
                else:
                    verified_supplement += 1
            except _IMAGE_ERRORS:
                missing.append(relative)
        if requirement in _ALWAYS_DRAWN.get(group_id, ()):
            usage = "drawn"
        elif requirement in _DRAWN_WITHOUT_PRESENTER.get(group_id, ()):
            usage = "without_presenter"
        elif group_id == "CX-G05" and requirement == _G05_PHOTOS:
            usage = "without_item_image"
        elif group_id == FRUIT_LIST_GROUP and requirement == _G06_BACKGROUND:
            usage = "unless_native_solid_background"
        else:
            usage = "shared_startup"
        result.append(
            {
                "native_path_pattern": pattern,
                "expected_count": count,
                "bundled_count": sum(relative in archived for relative in expected),
                "verified_bundled_count": verified_packaged,
                "verified_supplement_count": verified_supplement,
                "missing_paths": missing,
                "usage": usage,
                "supplement_registry_invalid": registry_invalid,
                "indexed_external_ids": [
                    aliases[relative][8:]
                    for relative in expected
                    if aliases.get(relative, "").startswith("input://")
                ],
            }
        )
    return result


def compile_browser_originals(
    package: Path,
    group: dict,
    config: dict,
    manifest: Path | None,
    stage: Path,
    *,
    allow_diagnostic: bool = False,
) -> dict[str, dict[str, str]]:
    needed = _needed(group["id"], config)
    if not needed:
        return {}
    supplied = _registered_originals(manifest)
    if supplied and (stage.resolve() != stage or stage.is_relative_to(package)):
        raise ValueError("Frozen browser images must remain inside the task")
    return _selection(
        package, group, needed, supplied, stage, allow_diagnostic=allow_diagnostic
    )


def require_drawn_browser_assets(
    package: Path, group_id: str, manifest: Path | None
) -> None:
    """Check originals used with a current presenter and current project images."""
    needed = {
        pattern: list(range(count))
        for pattern, count in _ALWAYS_DRAWN.get(group_id, ())
    }
    if needed:
        group = next(
            (
                row
                for row in read_json(package / "catalog/groups.json")["groups"]
                if row["id"] == group_id
            ),
            None,
        )
        if group is None:
            raise ValueError("Original browser group is unavailable")
        _selection(
            package,
            group,
            needed,
            _registered_originals(manifest),
            None,
            allow_diagnostic=False,
        )


def require_browser_originals(
    package: Path,
    group: dict,
    config: dict,
    frozen: dict | None = None,
    stage: Path | None = None,
    *,
    allow_diagnostic: bool = False,
) -> dict[str, dict[str, str]]:
    needed = _needed(group["id"], config)
    if not needed:
        return {}
    supplied = {}
    if frozen and stage is not None:
        if stage.resolve() != stage or stage.is_relative_to(package):
            raise ValueError("Frozen browser images must remain inside the task")
        for name, row in (frozen or {}).items():
            digest = row["sha256"]
            if re.fullmatch(r"[0-9a-f]{64}", digest) and Path(row["path"]) == inside(
                stage, digest + Path(name).suffix
            ):
                supplied[name] = row
    return _selection(
        package, group, needed, supplied, None, allow_diagnostic=allow_diagnostic
    )


def browser_original_evidence(selected: dict[str, dict[str, str]]) -> dict:
    return {
        path: {key: value for key, value in row.items() if key != "path"}
        for path, row in selected.items()
    }


def validate_browser_original_receipt(
    group_id: str, config: dict, selected: dict[str, dict[str, str]], native: dict
) -> None:
    if native.get(BROWSER_ORIGINALS_KEY, {}) != browser_original_evidence(selected):
        raise ValueError("Native receipt lacks matching original browser images")
    if (
        group_id == FRUIT_LIST_GROUP
        and fruit_list_uses_solid_background(config)
        and native.get("background") != FRUIT_LIST_SOLID_BACKGROUND
    ):
        raise ValueError("Native receipt lacks the original fruit-list solid mode")
