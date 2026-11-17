"""Sound palettes and privately staged music for the two editorial templates."""

from pathlib import Path

from .video_editing_first_groups import KNOWLEDGE_GROUP_ID, PRODUCT_GROUP_ID

MUSIC_SUBDIRECTORY = "_template-audio"
VISIBLE_SHOT_START = "/tengli/visible-shot-start"
TEMPLATE_TRACKS = {
    KNOWLEDGE_GROUP_ID: "bgm-cdcabd54d1be8cce",
    PRODUCT_GROUP_ID: "bgm-67e34c31810aa039",
}
_TRACKS = {
    TEMPLATE_TRACKS[KNOWLEDGE_GROUP_ID]: (
        "慢摇节奏店铺BGM",
        "knowledge.m4a",
        "cdcabd54d1be8ccec2ed23d3d7b8240f62a8deb54fb910e7c948f4eda51aca17",
        29.93,
    ),
    TEMPLATE_TRACKS[PRODUCT_GROUP_ID]: (
        "轻松动感带货BGM",
        "product.m4a",
        "67e34c31810aa039b9c3c99a6a4531a12d17a0150e77a5a795d94978030e3895",
        29.93,
    ),
}

SoundSlice = tuple[str, float, float, float]
SCREEN_CLICK: SoundSlice = ("sfx-d1025b83b675b651", 0.0, 0.16, -26)
_HIT: SoundSlice = ("sfx-8c9f8442f4185ef2", 0.0, 0.45, -21)
_BOUNCE: SoundSlice = ("sfx-fa9ac3656bfbe46f", 0.0, 0.24, -25)
_DROP: SoundSlice = ("sfx-bdb886c9361538ad", 0.0, 0.28, -25)
_DING: SoundSlice = ("sfx-5389fdd416f97c14", 0.0, 0.44, -27)
_BUBBLE: SoundSlice = ("sfx-e2963eb28dfcc04b", 0.0, 0.17, -26)
_SWIPE: SoundSlice = ("sfx-22f661280569e8bc", 0.07, 0.32, -25)
SCREEN_ENTRY: SoundSlice = ("episode-v4-54c0a24233d6cede", 0.0, 0.34, -27)
_QUESTION: SoundSlice = ("sfx-51456eadc09497d3", 0.0, 1.465, -25)

# Only actual word-bound entrances are added. Exit, settle and total duration
# anchors remain silent unless the original recipe already uses them.
EXTRA_ENTRANCES = {
    "AHG-S02": (VISIBLE_SHOT_START,),
    "AH-S05": ("/events/emphasis_frame",),
    "AH-S08": ("/events/detail_frame",),
    "AH-S09": ("/events/type_frame",),
    "BG-S04": ("/events/focus_frame",),
    "BG-S06": ("/events/lower_start",),
    "JJ-S02": ("/events/front/0",),
    "JJ-S03": ("/events/emphasis/0",),
    "SG-S02": ("/events/select_start",),
    "SG-S03": ("/events/emphasis_start",),
    "SG-S06": ("/events/lower_start",),
    "SG-S09": ("/events/replace_start",),
    "YYO08": ("/events/image_in",),
    "Z-M13": ("/timing/events/title",),
    "Z-M16": ("/timing/events/question",),
}


def template_tracks(tasks_root: Path | None) -> dict[str, dict]:
    if tasks_root is None:
        return {}
    directory = (tasks_root / MUSIC_SUBDIRECTORY).resolve()
    result = {}
    for asset_id, (name, filename, digest, seconds) in _TRACKS.items():
        path = directory / filename
        if path.is_symlink() or not path.is_file():
            continue
        result[asset_id] = {
            "id": asset_id,
            "name": name,
            "path": str(path),
            "sha256": digest,
            "duration_seconds": seconds,
            "kind": "music",
            "bundled": True,
            "rights": {"local_use": "user-authorized"},
        }
    return result


def template_sound(
    template_id: str, group: str, *, material: bool, index: int, opening: bool
) -> SoundSlice:
    if template_id == KNOWLEDGE_GROUP_ID:
        if group in {"W-R18", "Z-M16"} and index == 0:
            return _QUESTION
        if material:
            return _SWIPE
        if opening and index == 0:
            return _HIT
        return (_DROP, _BOUNCE, _DING)[index % 3]
    if material:
        return SCREEN_ENTRY
    if opening and index == 0:
        return _BOUNCE
    return (_BUBBLE, _DING)[index % 2]
