"""Install the author's entire byte-pinned archive, without changing its engines."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4

MOTION_SHA256 = "c10429057a862cd8bd9e24280e5dd3f04448a3829b8b10646dd5d341ca0969bc"
WRITING_SHA256 = "3b4d100ebf6ce41a233f4c994c1f779502ef568a206e7fc9c26cc9507c0baf17"
_MOTION_METADATA = (
    (
        "integrity.json",
        "c5be1f5241b3557006f6ea1e123c5518af48b883b59690d80fef47c738801b51",
    ),
    (
        "分享说明.md",
        "1b1547fc02ab1b4ac0080a6e9a09c3165e3b07008a63cab2efa3ebb3b116812d",
    ),
)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def inside(root: Path, relative: str) -> Path:
    # ZIP paths use POSIX separators, including when installed on Windows.
    normalized = relative.replace("\\", "/")
    parts = PurePosixPath(normalized)
    if parts.is_absolute() or ".." in parts.parts or ":" in normalized:
        raise ValueError("Archive contains an unsafe path")
    result = (root / normalized).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError("Path escapes its root")
    return result


def verify_package(package: Path) -> dict:
    # These original ZIP entries are outside the author's file manifest.
    for relative, expected in _MOTION_METADATA:
        path = inside(package, relative)
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"Original library metadata integrity failed: {relative}")
    integrity = read_json(package / "integrity.json")
    if integrity["algorithm"] != "sha256":
        raise ValueError("Unsupported package integrity algorithm")
    for relative, expected in integrity["files"].items():
        path = inside(package, relative)
        if not path.is_file() or sha256(path) != expected:
            raise ValueError(f"Original library integrity failed: {relative}")
    catalog = read_json(package / "catalog/groups.json")
    groups = catalog["groups"]
    assets = read_json(package / "asset-manifest.json")["assets"]
    external = read_json(package / "catalog/external-resources.json")["resources"]
    if len(groups) != 132 or len(assets) != 197 or len(external) != 699:
        raise ValueError("The full original catalog is required")
    if len({g["id"] for g in groups}) != len(groups):
        raise ValueError("Duplicate original group ID")
    for group in groups:
        for key in ("entry", "input_schema", "input_template", "contract"):
            if group.get(key) and not inside(package, group[key]).is_file():
                raise ValueError(f"Missing {key} for {group['id']}")
    for asset in assets:
        path = inside(package, asset["path"])
        if not path.is_file() or sha256(path) != asset["sha256"]:
            raise ValueError(f"Original asset integrity failed: {asset['id']}")
    return {
        "integrity_files": len(integrity["files"]),
        "groups": len(groups),
        "backends": dict(Counter(g["backend"] for g in groups)),
        "assets": len(assets),
        "external_resources": len(external),
        "runtime_verified_groups": 0,
    }


def install_archive(archive: Path, destination: Path, expected: str) -> Path:
    if sha256(archive) != expected:
        raise ValueError("Original ZIP SHA256 differs from the approved baseline")
    destination = destination.resolve()
    receipt = destination.parent / (destination.name + ".installation.json")
    if destination.exists():
        saved = read_json(receipt)
        if saved["archive_sha256"] != expected:
            raise ValueError("Installed library identity differs")
        if expected == MOTION_SHA256:
            verify_package(destination)
        return destination
    staging = destination.with_name(".s-" + uuid4().hex[:8])
    staging.mkdir(parents=True)
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if sum(item.file_size for item in entries) > 1024**3:
            raise ValueError("Unexpected expanded archive size")
        targets = set()
        for item in entries:
            target = inside(staging, item.filename)
            if target in targets or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError("Duplicate path or symlink in original archive")
            targets.add(target)
        for item in entries:
            target = inside(staging, item.filename)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(item) as stream, target.open("xb") as output:
                    import shutil

                    shutil.copyfileobj(stream, output)
    counts = verify_package(staging) if expected == MOTION_SHA256 else {}
    for path in staging.rglob("*"):
        if path.is_file():
            path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    staging.rename(destination)
    atomic_json(
        receipt,
        {
            "archive_sha256": expected,
            "archive_bytes": archive.stat().st_size,
            "extracted_files": sum(1 for x in destination.rglob("*") if x.is_file()),
            "static_verification": counts,
            "runtime_verification": "not_performed",
        },
    )
    return destination


def registry(package: Path) -> dict:
    """Preserve every original record; website evidence is a separate object."""
    return {
        "release_id": MOTION_SHA256,
        "template": read_json(package / "motion.json")["template"],
        "catalog": read_json(package / "catalog/groups.json"),
        "asset_manifest": read_json(package / "asset-manifest.json"),
        "external_resources": read_json(package / "catalog/external-resources.json"),
        "method_files": [
            p.relative_to(package).as_posix()
            for p in sorted((package / "methods").iterdir())
        ],
        "website_status": {
            g["id"]: {
                "status": "registered",
                "runtime": "unverified",
                "visual": "unreviewed",
            }
            for g in read_json(package / "catalog/groups.json")["groups"]
        },
    }
