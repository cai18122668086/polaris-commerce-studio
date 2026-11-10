"""Check original browser images that reach the active native frame."""

from pathlib import Path

from .motion_library import inside, read_json, sha256

_G05_BACKGROUND = ("g05-assets/base-{i:03d}.jpg", 69)
_G05_ACTOR = ("g05-assets/actor-{i:03d}.png", 69)
_G09_TEXTURES = ("assets/material-{i}.png", 3)
_G09_BACKGROUND = ("assets/g09-bg/{i:03d}.jpg", 66)
_G10_BACKGROUND = ("assets/G10-background-clean.jpg", 1)
_G10_ACTOR = ("assets/G10-person-clean.png", 1)
_SHARED_STARTUP = (_G09_TEXTURES, _G09_BACKGROUND, _G10_BACKGROUND, _G10_ACTOR)
STARTUP_ASSETS = {
    "CX-G05": (_G05_BACKGROUND, _G05_ACTOR, ("g05-assets/photo-{i}.jpg", 3)),
    "CX-G08": _SHARED_STARTUP,
    "CX-G09": _SHARED_STARTUP,
    "CX-G10": _SHARED_STARTUP,
}

# The shared entry loads every group's startup images. Only these paths are
# drawn in the requested branch, depending on the current presenter binding.
_ALWAYS_DRAWN = {"CX-G05": (_G05_BACKGROUND,), "CX-G09": (_G09_TEXTURES,)}
_DRAWN_WITHOUT_PRESENTER = {
    "CX-G05": (_G05_ACTOR,),
    "CX-G09": (_G09_BACKGROUND,),
    "CX-G10": (_G10_BACKGROUND, _G10_ACTOR),
}
RENDER_GROUPS = frozenset(_ALWAYS_DRAWN | _DRAWN_WITHOUT_PRESENTER)
BROWSER_ORIGINALS_REQUIRED = "EDITING_ORIGINAL_BROWSER_ASSETS_REQUIRED"


class BrowserOriginalsMissing(ValueError):
    def __init__(self, group_id: str, missing: dict[str, int]) -> None:
        self.missing = missing
        super().__init__(
            f"{group_id}: missing verified original browser images {missing}"
        )


def require_browser_originals(package: Path, group: dict, config: dict) -> None:
    group_id = group["id"]
    needed: tuple[tuple[str, int], ...] = _ALWAYS_DRAWN.get(group_id, ())
    if not config.get("presenter"):
        needed += _DRAWN_WITHOUT_PRESENTER.get(group_id, ())
    if not needed:
        return
    archived = read_json(package / "integrity.json")["files"]
    missing = {}
    for pattern, count in needed:
        missing_count = 0
        for i in range(count):
            relative = f"{group['browser_directory']}/{pattern.format(i=i)}"
            expected = archived.get(relative)
            path = inside(package, relative)
            try:
                verified = bool(
                    expected and path.is_file() and sha256(path) == expected
                )
            except OSError:
                verified = False
            if not verified:
                missing_count += 1
        if missing_count:
            missing[pattern] = missing_count
    if missing:
        raise BrowserOriginalsMissing(group_id, missing)
