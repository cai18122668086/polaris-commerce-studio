"""Regenerate the source lock for the vendored aurora detail Skill v2.3.0.

The source tree is the owner-supplied v2.3.0 Skill copied byte for byte. Its
planning references are read by the one-pass authored detail planner; the
harness scripts are kept for provenance only and are not executed.
"""

import hashlib
import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
TEMPLATE = "xinghe-ecommerce-detail-domestic-4-fast"
SKILL_ID = "aurora-domestic-ecommerce-detail-page-v23"


def main() -> None:
    root = BACKEND / "skill_sources" / SKILL_ID
    files = sorted(
        (
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        ),
        key=lambda entry: entry["path"],
    )
    source = BACKEND / "app" / "skill_manifests" / f"{TEMPLATE}.json"
    manifest = json.loads(source.read_text(encoding="utf-8"))
    manifest.update(
        skill_id=SKILL_ID,
        files=files,
        content_hash=hashlib.sha256(
            "".join(f"{entry['path']}\0{entry['sha256']}\n" for entry in files).encode()
        ).hexdigest(),
    )
    manifest["policy"]["policy_version"] = "aurora-domestic-detail-v2.3-authored-v1"
    for key in ("input_contract", "output_contract"):
        schema_id = manifest[key]["schema_id"]
        manifest[key]["schema_id"] = schema_id.replace(TEMPLATE, SKILL_ID)
    target = BACKEND / "app" / "skill_manifests" / f"{SKILL_ID}.json"
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
