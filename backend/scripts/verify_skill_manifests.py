"""Verify installed skill sources against the bundled runtime manifests."""

from __future__ import annotations

import json

from app.config import default_masked_skill_root, default_xinghe_skill_root
from app.skill_runtime import SkillManifestRegistry


def main() -> None:
    registry = SkillManifestRegistry.bundled()
    source_roots = {
        "masked-image-repair": default_masked_skill_root(),
        "xinghe-ecommerce-detail": default_xinghe_skill_root(),
    }
    verified = {
        skill_id: registry.verify_source(skill_id, source_roots[skill_id])
        for skill_id in registry.skill_ids
    }
    print(json.dumps(verified, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
