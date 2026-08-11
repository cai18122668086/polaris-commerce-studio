from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SKILL_ID = "aurora-domestic-ecommerce-main-image"
SKILL_VERSION = "0.1.17"
LOCK_SCHEMA = "polaris-frozen-skill-lock-v1"
HASH_ALGORITHM = "sha256-ordered-path-nul-file-sha256-lf-v1"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_lock(source_root: Path, source_zip: Path) -> dict[str, object]:
    files = [
        {
            "path": path.relative_to(source_root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(source_root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
    ]
    files.sort(key=lambda item: str(item["path"]))
    canonical = "".join(f"{item['path']}\0{item['sha256']}\n" for item in files).encode(
        "utf-8"
    )
    return {
        "schema_version": LOCK_SCHEMA,
        "skill_name": SKILL_ID,
        "skill_version": SKILL_VERSION,
        "content_hash_algorithm": HASH_ALGORITHM,
        "skill_digest": hashlib.sha256(canonical).hexdigest(),
        "source_zip_sha256": sha256_file(source_zip),
        "file_count": len(files),
        "total_bytes": sum(int(item["bytes"]) for item in files),
        "harness_entrypoint": "scripts/harness.py",
        "immutable_paths": [
            "SKILL.md",
            "agents/**",
            "references/**",
            "schemas/**",
            "scripts/harness.py",
            "scripts/runtime/**",
            "legacy_v013/**",
            "vendor/**",
        ],
        "files": files,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_lock(args.source_root.resolve(), args.source_zip.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
