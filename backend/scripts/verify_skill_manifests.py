"""Verify installed skill sources against the bundled runtime manifests."""

from __future__ import annotations

import json
from pathlib import Path

from app.skill_runtime import SkillManifestRegistry


def main() -> None:
    registry = SkillManifestRegistry.bundled()
    skill_root = Path.home() / ".codex" / "skills"
    verified = {
        skill_id: registry.verify_source(skill_id, skill_root / skill_id)
        for skill_id in registry.skill_ids
    }
    print(json.dumps(verified, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
