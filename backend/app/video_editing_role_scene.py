"""Bind original W-R15 artwork to the narration around its native entrances."""

from .video_editing_contracts import SemanticBeat, Transcript
from .video_editing_native_content import role_scene_chain, role_scene_contract
from .video_editing_virtual_clock import first_visible_frame

ROLE_TEMPLATE_ID = "unified-role-chain-v1"
ROLE_IMAGES = tuple(row["path"] for row in role_scene_contract()["image_slots"])
ROLE_SOUNDS = {"door_close": 149, "handoff": 173, "prohibition_in": 472}
_VIRTUAL = [
    0,
    1.25,
    2.85,
    4.4,
    4.95,
    5.75,
    6.35,
    7.35,
    7.95,
    8.8,
    9.25,
    10.8,
    11.35,
    13,
    15,
    15.7,
    17,
]
# The preserved drawer includes blends and a four-image montage between cuts.
_ART_ENTRY_FRAMES = (
    0,
    38,
    86,
    132,
    149,
    173,
    221,
    239,
    265,
    325,
    356,
    390,
    401,
    417,
    432,
    450,
)


def role_action_frame(timing: dict, event: str) -> int:
    actual = [*timing["events"]["scene_boundaries"], timing["duration_seconds"]]
    return first_visible_frame(actual, _VIRTUAL, ROLE_SOUNDS[event])


def bind_role_scene(
    beat: SemanticBeat, native: dict, transcript: Transcript, assets: dict
) -> dict:
    result = role_scene_chain(native, assets)
    start, end = (native["clock"][key] for key in ("start_ms", "end_ms"))
    duration = (end - start) / 1000
    actions = result["boundaries"]
    words = {word.id: word for word in transcript.tokens}
    ids = result["scene_asset_ids"]
    text = {row["path"]: row for row in native["text"]}
    labels = [text[f"/content/role_terms/{i}"] for i in range(3)]
    sign = text["/content/prohibition_text"]
    events = {row["path"]: row for row in native["events"]}
    caption = text["/content/captions/0/text"]
    begin, finish = (events[f"/content/captions/0/{edge}"] for edge in ("start", "end"))
    if (
        beat.relation != "sequence"
        or not 0.5 <= duration <= 30
        or len(beat.relation_items) != len(ROLE_IMAGES)
        or len({assets[asset_id]["sha256"] for asset_id in ids}) != len(ROLE_IMAGES)
        or any(action["edge"] != "start" for action in actions)
        or any(
            row["token_ids"][0] != action["token_id"] or not 1 <= len(row["text"]) <= 4
            for row, action in zip(labels, actions[:3], strict=True)
        )
        or sign["token_ids"][0] != actions[-1]["token_id"]
        or not 1 <= len(sign["text"]) <= 8
        or not sign["text"].startswith(
            ("禁止", "不得", "不能", "不要", "不许", "严禁", "切勿", "别", "勿")
        )
        or duration - actions[-1]["start_seconds"] < 0.5
        or not 1 <= len(caption["text"]) <= 14
        or (begin["token_id"], begin["edge"]) != (caption["token_ids"][0], "start")
        or (finish["token_id"], finish["edge"]) != (caption["token_ids"][-1], "end")
    ):
        raise ValueError(
            "Role chain needs sixteen different project images and spoken roles"
        )
    actual = [*(action["start_seconds"] for action in actions), duration]
    entries = []
    for item, asset_id, path, native_frame in zip(
        beat.relation_items, ids, ROLE_IMAGES, _ART_ENTRY_FRAMES, strict=True
    ):
        frame = (
            first_visible_frame(actual, _VIRTUAL, native_frame) if native_frame else 0
        )
        first, last = words[item.first_token_id], words[item.last_token_id]
        if (
            item.asset_ids != [asset_id]
            or item.native_media_paths != [path]
            or item.native_text_paths
            or not start <= first.start_ms < last.end_ms <= end
            or not first.start_ms - 350
            <= start + frame * 1000 / 30
            <= last.end_ms + 350
        ):
            raise ValueError("Role artwork must enter beside its own spoken range")
        entries.append(
            {
                "path": path,
                "asset_id": asset_id,
                "frame": frame,
                "first_token_id": item.first_token_id,
                "last_token_id": item.last_token_id,
            }
        )
    return {**result, "art_entrances": entries}
