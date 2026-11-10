"""Resolve the exact fonts awaited by the original CX-G08–10 browser entry."""

from pathlib import Path

from .motion_library import inside, read_json, sha256
from .motion_local_dependencies import DependencyState, dependency_state
from .video_editing_browser_clocks import SPLIT_WRAPPER_SHA

BROWSER_BOOT_FONT_GROUPS = frozenset(("CX-G08", "CX-G09", "CX-G10"))
BROWSER_BOOT_FONTS_REQUIRED = "EDITING_ORIGINAL_BROWSER_FONTS_REQUIRED"
_FONT_ALIASES = {
    "assets/zhixiang.ttf": "font-db575410c0444da5",
    "assets/chaocu.ttf": "font-500d96e599576ffb",
    "legacy/assets/fonts/simsun.ttc": "font-346c3d9c8c827faa",
    "legacy/assets/fonts/segoesc.ttf": "font-b24aa49a4bcb99a0ffc6",
    "legacy/assets/fonts/simhei.ttf": "font-aa4560dd8fe56457",
    "legacy/assets/fonts/msyh.ttc": "font-e4b3b9d058750fb8",
}
BROWSER_BOOT_FONT_IDS = tuple(_FONT_ALIASES.values())
_BUNDLED_ALIAS = "legacy/assets/fonts/SHSerifHeavy.ttf"
_BUNDLED_FONT = "assets/fonts/Source_Han_Serif_SC_Heavy--152bc1c4535b.ttf"
_ENGINE = "924e38d4f3efc727158f2d6d0abb08a583d59edcfbe37e5e508c1bb0b2406e76"
_LEGACY = "6e41fa0ad6e1cc32120e5df820d0c458af2ad8331f6a9ed7c8d8f5c492472c80"


class BrowserBootFontsMissing(ValueError):
    def __init__(self, group_id: str, states: dict[str, DependencyState]) -> None:
        self.states = states
        super().__init__(
            f"{group_id}: original browser startup fonts unavailable {states}"
        )


def require_browser_boot_fonts(
    package: Path, group: dict, resources: dict
) -> dict[str, str]:
    if group["id"] not in BROWSER_BOOT_FONT_GROUPS:
        return {}
    if not isinstance(resources, dict):
        raise ValueError("Invalid original browser startup font bindings")
    directory = group["browser_directory"]
    pinned = {
        group["entry"]: _ENGINE,
        f"{directory}/legacy/src/renderer.html": _LEGACY,
        "commercial_runtime/special.py": SPLIT_WRAPPER_SHA,
    }
    if any(sha256(inside(package, path)) != digest for path, digest in pinned.items()):
        raise ValueError("Original browser font loader changed")
    aliases = read_json(package / "catalog/native-relative-assets.json")
    expected = {path: "input://" + rid for path, rid in _FONT_ALIASES.items()}
    expected[_BUNDLED_ALIAS] = "pkg://" + _BUNDLED_FONT
    for alias, ref in expected.items():
        relative = f"{directory}/{alias}"
        if aliases.get(relative) != ref or inside(package, relative).exists():
            raise ValueError("Original browser font alias changed or was overridden")
    files = read_json(package / "integrity.json")["files"]
    if sha256(inside(package, _BUNDLED_FONT)) != files[_BUNDLED_FONT]:
        raise ValueError("Bundled original browser startup font changed")

    identities = {
        row["id"]: row
        for row in read_json(package / "catalog/external-resources.json")["resources"]
    }
    missing: dict[str, DependencyState] = {}
    resolved = {}
    for rid in BROWSER_BOOT_FONT_IDS:
        binding = resources.get(rid)
        path = binding.get("path") if isinstance(binding, dict) else binding
        identity = identities[rid]
        if identity["kind"] != "font" or not identity.get("sha256"):
            raise ValueError("Original browser startup font identity changed")
        if not isinstance(path, str) or not Path(path).is_absolute():
            missing[rid] = "not_registered"
            continue
        state = dependency_state(identity, path)
        if state == "verified":
            resolved[rid] = str(Path(path).resolve())
        else:
            missing[rid] = state
    if missing:
        raise BrowserBootFontsMissing(group["id"], missing)
    return resolved
