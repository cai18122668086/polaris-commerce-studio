"""Bind original boards, examples and three-way media layouts to project inputs."""

from itertools import pairwise

from .video_editing_contracts import SemanticBeat, Transcript
from .video_editing_materials import project_image_digests

PANEL_TEMPLATE_ID = "media-panels-v1"
TRIPTYCH = "W-R13"
PANEL_GROUPS = {
    "Z-M07": (
        "同期人物窗和原生四图板同时展示一组用途或例子。",
        "title、window 锚定本段首词，body、board 锚定后续实录说明首词。"
        "原板整体进场，四张图按四个实录项一一绑定。",
    ),
    "Z-M08": (
        "在同期人物原景上依次增加四张用途图及标签。",
        "item0 至 item3 逐项对应四个实录标签的首词。"
        "原短字幕绑定实际首尾词，英语仅在有对应原声时另选专门入口。",
    ),
    TRIPTYCH: (
        "将同期人物与两份本期项目素材放入原生三路并置。",
        "clips 第一路是同期原片，另两路分别选择图片或完整覆盖本段的独立视频。"
        "caption 从本段首词起，caption_switch 锚定后句首词。",
    ),
}
PANEL_BOARDS = frozenset({"Z-M07", "Z-M08"})
BOARD_IMAGES = tuple(
    f"/media/{key}/path" for key in ("vegetables", "grains", "dairy", "fish")
)
TRIPTYCH_PROJECT = ("/media/clips/1/path", "/media/clips/2/path")
PANEL_SOURCE = {
    **dict.fromkeys(PANEL_BOARDS, "/media/presenter/path"),
    TRIPTYCH: "/media/clips/0/path",
}
TRIPTYCH_ENTRY = "/timing/events/enter_duration"
PANEL_SOUNDS = {
    "Z-M07": {"window": "ease", "board": "visible"},
    "Z-M08": {f"item{i}": "ease" for i in range(4)},
    TRIPTYCH: {"enter_duration": "scene"},
}
PANEL_CAPTION_BANDS = {"Z-M07": (840, 960), "Z-M08": (825, 960), TRIPTYCH: (825, 960)}


def panel_project_paths(group: str) -> tuple[str, ...]:
    return TRIPTYCH_PROJECT if group == TRIPTYCH else BOARD_IMAGES


def project_panel_videos(cards: list[dict], source_sha: str) -> dict[str, dict]:
    return {
        row["id"]: row
        for row in cards
        if row["id"].startswith("material-")
        and row["kind"] == "video"
        and row["sha256"] != source_sha
        and type(row.get("duration_ms")) is int
    }


def panel_blockers(
    template: dict | None,
    cards: list[dict],
    source_sha: str,
    unavailable: dict,
) -> None:
    if not template or template["id"] != PANEL_TEMPLATE_ID:
        return
    images = set(project_image_digests(cards).values())
    if len(images) < 4:
        for group in PANEL_BOARDS:
            unavailable.setdefault(group, []).append("four_panel_images_required")
    clips = {
        row["sha256"]
        for row in project_panel_videos(cards, source_sha).values()
        if row["duration_ms"] >= 800
    }
    if len(images | clips) < 2:
        unavailable.setdefault(TRIPTYCH, []).append(
            "independent_triptych_materials_required"
        )


def triptych_template(template: dict, video_slots: set[int]) -> dict:
    clips = [dict(row) for row in template["media"]["clips"]]
    for i in video_slots:
        clips[i].update(
            kind="video", offset_seconds=0, duration_seconds=1, end_policy="error"
        )
    return {**template, "media": {**template["media"], "clips": clips}}


def triptych_entrance(beat: SemanticBeat, start_ms: int, config: dict) -> dict:
    return {
        "path": TRIPTYCH_ENTRY,
        "value": config["timing"]["events"]["enter_duration"],
        "unit": "seconds",
        "token_id": beat.first_token_id,
        "edge": "start",
        "measured_anchor_ms": start_ms,
        "frame_quantization_ms": 0,
        "native_action_basis": "entry begins at zero, using the original transition",
    }


def validate_panel_anchors(
    beat: SemanticBeat,
    anchors: dict,
    transcript: Transcript,
    images: dict[str, str],
    videos: dict[str, dict],
) -> None:
    group = beat.group_id
    media = {row["path"]: row["asset_id"] for row in anchors["media"]}
    events = {row["path"]: row for row in anchors["events"]}
    text = {row["path"]: row for row in anchors["text"]}
    positions = {t.id: i for i, t in enumerate(transcript.tokens)}
    start, end = (anchors["clock"][key] for key in ("start_ms", "end_ms"))
    duration = (end - start) / 1000
    project = panel_project_paths(group)
    items = beat.relation_items
    paths = (PANEL_SOURCE[group], *project) if group == TRIPTYCH else project
    if (
        not 0.8 <= duration <= 15
        or beat.relation != "parallel"
        or len(items) != len(paths)
        or any(
            item.asset_ids != [media[path]] or item.native_media_paths != [path]
            for item, path in zip(items, paths, strict=True)
        )
        or any(
            positions[a.last_token_id] >= positions[b.first_token_id]
            for a, b in pairwise(items)
        )
        or any(
            not 1 <= len(row["text"]) <= 18 or "\n" in row["text"]
            for row in text.values()
        )
    ):
        raise ValueError(
            "Each visual item needs its own ordered spoken span and media slot"
        )
    digests = []
    for path in project:
        asset_id = media[path]
        if group == TRIPTYCH and asset_id in videos:
            video = videos[asset_id]
            if video["duration_ms"] < end - start:
                raise ValueError(
                    "Triptych project video is shorter than its concurrent scene"
                )
            digests.append(video["sha256"])
        else:
            digests.append(images[asset_id])
    if len(set(digests)) != len(paths) - int(group == TRIPTYCH):
        raise ValueError("Each panel role needs different project material bytes")

    def starts(event: str, role: str) -> bool:
        e = events[f"/timing/events/{event}"]
        return (
            e["edge"] == "start"
            and e["token_id"] == text[f"/content/{role}"]["token_ids"][0]
        )

    if group == TRIPTYCH:
        if not (
            text["/content/caption"]["token_ids"][0] == beat.first_token_id
            and starts("caption_switch", "caption_after")
            and 0.35
            <= events["/timing/events/caption_switch"]["value"]
            <= duration - 0.3
        ):
            raise ValueError("Triptych captions must follow their actual spoken phases")
    elif group == "Z-M07":
        if not (
            starts("window", "title")
            and starts("board", "body")
            and text["/content/title"]["token_ids"][0] == beat.first_token_id
            and events["/timing/events/board"]["token_id"] == items[0].first_token_id
            and 0.30 <= events["/timing/events/board"]["value"] <= duration - 0.5
        ):
            raise ValueError(
                "Four-image board needs its measured window and board phases"
            )
    else:
        for i, item in enumerate(items):
            label = f"items/{i}/label"
            if (
                not starts(f"item{i}", label)
                or text[f"/content/{label}"]["token_ids"][0] != item.first_token_id
                or item.native_text_paths != [f"/content/{label}"]
            ):
                raise ValueError("Each original picture enters on its own spoken label")
        cuts = [events[f"/timing/events/item{i}"]["value"] for i in range(4)]
        cap = text["/content/captions/0/text"]["token_ids"]
        a, b = (events[f"/content/captions/0/{edge}"] for edge in ("start", "end"))
        if (
            any(y - x < 0.15 for x, y in pairwise([*cuts, duration]))
            or (a["token_id"], a["edge"]) != (cap[0], "start")
            or (b["token_id"], b["edge"]) != (cap[-1], "end")
            or b["value"] - a["value"] < 0.16
        ):
            raise ValueError(
                "Original picture and caption phases need their measured reading times"
            )
