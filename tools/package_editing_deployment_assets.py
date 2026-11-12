"""Package verified private editing resources without env files or project data."""

import argparse
import copy
import io
import json
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.motion_library import MOTION_SHA256, read_json, sha256, verify_package
from app.motion_library_validation import EVIDENCE_SCHEMA
from app.motion_local_dependencies import local_dependencies
from app.video_editing_alignment import ALIGNMENT_MANIFEST
from app.video_editing_funasr import bundle_identity
from app.video_writing_rules import verify_writing_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--asr", type=Path, required=True)
    parser.add_argument("--alignment", type=Path, required=True)
    parser.add_argument("--writing", type=Path, required=True)
    parser.add_argument("--examples", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    verify_package(args.library)
    bundle_identity(args.asr)
    bundle_identity(args.alignment, manifest_path=ALIGNMENT_MANIFEST)
    verify_writing_package(args.writing)
    paths = {}

    def tree(root, prefix):
        for file in sorted(root.rglob("*")):
            if file.is_file() and not file.is_symlink():
                relative = file.relative_to(root)
                if any(
                    p in {".git", "__pycache__", ".pytest_cache"}
                    for p in relative.parts
                ):
                    continue
                paths[prefix + "/" + relative.as_posix()] = file

    tree(args.library, "motion")
    tree(args.asr, "asr")
    tree(args.alignment, "alignment")
    tree(args.writing, "writing")
    identities = {
        row["id"]: row
        for row in read_json(args.library / "catalog/external-resources.json")[
            "resources"
        ]
    }
    bindings = copy.deepcopy(read_json(args.bindings))
    for rid, file in local_dependencies(args.bindings).items():
        source = Path(file)
        if rid not in identities or sha256(source) != identities[rid]["sha256"]:
            raise ValueError("Unverified external resource: " + rid)
        relative = "resources/" + rid + source.suffix.lower()
        paths["dependencies/" + relative] = source
        bindings["resources"][rid] = "registry://" + relative
    # The active registry has no browser override images. Do not silently move
    # a future registry whose other host paths need their own verified intake.
    if set(bindings) - {"resources", "tools", "resource_intake"}:
        raise ValueError("Additional registry sections need explicit portable intake")
    bindings["tools"] = {}
    example_manifest = read_json(args.examples / "manifest.json")
    paths["examples/manifest.json"] = args.examples / "manifest.json"
    for collection in ("examples", "style_previews"):
        for entry in example_manifest[collection].values():
            for kind in ("video", "poster"):
                if kind in entry:
                    row = entry[kind]
                    file = args.examples / row["file"]
                    if file.parent != args.examples or sha256(file) != row["sha256"]:
                        raise ValueError("Installed example differs from manifest")
                    paths["examples/" + file.name] = file
    for file in args.evidence.rglob("*.json"):
        row = read_json(file)
        if row.get("schema") == EVIDENCE_SCHEMA and row.get("release") == MOTION_SHA256:
            paths["evidence/" + file.relative_to(args.evidence).as_posix()] = file
    hashes = {name: sha256(file) for name, file in paths.items()}
    total = sum(file.stat().st_size for file in paths.values())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise FileExistsError(args.output)
    with tarfile.open(args.output, "w:gz", compresslevel=1) as archive:
        for name, file in paths.items():
            archive.add(file, arcname=name, recursive=False)
        for name, value in {
            "dependencies/bindings.json": bindings,
            "asset-manifest.json": {
                "motion_release": MOTION_SHA256,
                "files": hashes,
                "source_bytes": total,
            },
        }.items():
            data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            archive.addfile(info, io.BytesIO(data))
    result = {
        "archive": str(args.output),
        "sha256": sha256(args.output),
        "bytes": args.output.stat().st_size,
        "source_bytes": total,
        "files": len(paths),
        "paid_calls": 0,
    }
    args.output.with_suffix(".json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
