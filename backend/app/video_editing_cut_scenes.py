"""Website bindings for original cut-relative media scenes."""

from itertools import pairwise

from .video_editing_contracts import SemanticBeat, Transcript
from .video_editing_materials import project_image_digests

CUT_TEMPLATE_ID = "material-cut-v1"
CUT_GROUPS = {
    "Z-M06": (
        "实拍和本期图片按三段实录硬切，随后回到同期原片。",
        "shots 依次绑定同期原片、本期图片、同期原片。每段绑定中文短句及实际首尾词。",
    ),
    "W-R08": (
        "用原连续撕纸展示三个不同的本期图片。",
        "photos 依次绑定三张对应实录的图片；overlay 取实录两字，caption 取实录主题。",
    ),
    "W-R10": (
        "手机画面依次展示同期原片与两张本期素材。",
        "screen_clips 依次绑定同期原片及两张图。"
        "原屏内短字幕按本地 0、1.36、3.30 秒分段，"
        "选对应实录短语，bottom 取两字，exit 取最后一段之后的实录词点。",
    ),
    "W-R16": (
        "用原生表盘贯穿实际口播中的五段画面。",
        "background_clips 首尾使用同期原片，中间是三张本期图。"
        "clock_in 取首词，clock_out 取最后一段内的实录词点。",
    ),
}
_MEDIA_KEYS = {
    "Z-M06": "shots",
    "W-R08": "photos",
    "W-R10": "screen_clips",
    "W-R16": "background_clips",
}
_SOURCES = {"Z-M06": (0, 2), "W-R08": (), "W-R10": (0,), "W-R16": (0, 4)}
CUT_IMAGE_COUNTS = {"Z-M06": 1, "W-R08": 3, "W-R10": 2, "W-R16": 3}
CUT_SOUND_MODES = {
    "Z-M06": {"cuts/0": "scene"},
    "W-R08": {"cuts/0": "scene", "cuts/1": "visible", "cuts/2": "visible"},
    "W-R10": {
        "cuts/0": "scene",
        "cuts/1": "visible",
        "cuts/2": "visible",
        "exit": "ease",
    },
    "W-R16": {"clock_in": "ease"},
}
CUT_CAPTION_BANDS = {
    "Z-M06": (830, 960),
    "W-R08": (850, 960),
    "W-R10": (865, 960),
    "W-R16": (860, 960),
}
_EVENT = "/timing/events/"


def cut_source_paths(group: str) -> tuple[str, ...]:
    return tuple(f"/media/{_MEDIA_KEYS[group]}/{i}/path" for i in _SOURCES[group])


def cut_media_paths(group: str) -> set[str]:
    return {
        f"/media/{_MEDIA_KEYS[group]}/{i}/path"
        for i in range(len(_SOURCES[group]) + CUT_IMAGE_COUNTS[group])
    }


def cut_scene_blockers(
    template: dict | None, cards: list[dict], unavailable: dict
) -> None:
    if not template:
        return
    slots = {slot["group_id"] for slot in template["slots"]}
    count = len(set(project_image_digests(cards).values()))
    for group, needed in CUT_IMAGE_COUNTS.items():
        if group in slots and count < needed:
            unavailable.setdefault(group, []).append("distinct_cut_images_required")


def _check_cut_text(
    group: str,
    text: dict,
    events: dict,
    times: list[float],
    duration: float,
    transcript: Transcript,
    start_ms: int,
) -> None:
    if group == "Z-M06":
        for i, (a, b) in enumerate(pairwise(times)):
            path = f"/content/captions/{i}"
            tokens = text[path + "/text"]["token_ids"]
            begin, end = (events[path + edge] for edge in ("/start", "/end"))
            if (
                (begin["token_id"], begin["edge"], begin["value"])
                != (tokens[0], "start", a)
                or (end["token_id"], end["edge"]) != (tokens[-1], "end")
                or not a + 0.16 <= end["value"] <= b
            ):
                raise ValueError(
                    "Native cut captions must cover measured words within their cut"
                )
        return
    if group == "W-R10":
        positions = {t.id: t for t in transcript.tokens}
        for i, (a, b) in enumerate(pairwise((0, 1.36, 3.30, duration))):
            tokens = text[f"/content/captions/{i}"]["token_ids"]
            if not (
                a - 1 / 30 <= (positions[tokens[0]].start_ms - start_ms) / 1000
                and (positions[tokens[-1]].end_ms - start_ms) / 1000 <= b + 1 / 30
            ):
                raise ValueError(
                    "Phone captions must fit the three original caption phases"
                )
        if (
            not max(3.30, times[-2]) + 0.24
            <= events[_EVENT + "exit"]["value"]
            <= duration - 0.16
        ):
            raise ValueError("Leave time for the final phone image and its native exit")
        two = "bottom"
    elif group == "W-R08":
        two = "overlay"
    else:
        if not (
            events[_EVENT + "clock_in"]["value"] == 0
            and times[-2] <= events[_EVENT + "clock_out"]["value"] <= duration - 0.10
        ):
            raise ValueError(
                "Clock must enter at the first cut and fade during the final cut"
            )
        return
    if len(text["/content/" + two]["text"]) != 2:
        raise ValueError("The native two-character role requires two spoken characters")


def validate_cut_anchors(
    beat: SemanticBeat,
    anchors: dict,
    transcript: Transcript,
    presenters: set[str],
    images: dict[str, str],
) -> None:
    group = beat.group_id
    count = len(_SOURCES[group]) + CUT_IMAGE_COUNTS[group]
    media = {row["path"]: row["asset_id"] for row in anchors["media"]}
    events = {row["path"]: row for row in anchors["events"]}
    text = {row["path"]: row for row in anchors["text"]}
    cuts = [events[f"{_EVENT}cuts/{i}"] for i in range(count)]
    duration = (anchors["clock"]["end_ms"] - anchors["clock"]["start_ms"]) / 1000
    times = [*(r["value"] for r in cuts), duration]
    positions = {t.id: i for i, t in enumerate(transcript.tokens)}
    if (
        not 0.8 <= duration <= 15
        or times[0] != 0
        or any(b - a < 0.16 for a, b in pairwise(times))
        or beat.relation not in {"sequence", "parallel", "contrast"}
        or len(beat.relation_items) != count
        or any(
            not 1 <= len(row["text"]) <= 22 or "\n" in row["text"]
            for row in text.values()
        )
    ):
        raise ValueError("Use the original number of ordered, readable spoken cuts")
    picture_digests = []
    for i, (cut, item) in enumerate(zip(cuts, beat.relation_items, strict=True)):
        path = f"/media/{_MEDIA_KEYS[group]}/{i}/path"
        asset_id = media[path]
        if (
            item.asset_ids != [asset_id]
            or item.native_media_paths != [path]
            or item.first_token_id != cut["token_id"]
            or cut["edge"] != "start"
            or not positions[item.first_token_id]
            <= positions[item.last_token_id]
            <= positions[beat.last_token_id]
            or i + 1 < count
            and positions[item.last_token_id] >= positions[cuts[i + 1]["token_id"]]
        ):
            raise ValueError("Each media cut must bind its own ordered spoken item")
        if i in _SOURCES[group]:
            if asset_id not in presenters:
                raise ValueError("Live cut must use the exact current narration video")
        else:
            picture_digests.append(images[asset_id])
    if len(set(picture_digests)) != CUT_IMAGE_COUNTS[group]:
        raise ValueError("Each picture cut needs different current project image bytes")
    _check_cut_text(
        group, text, events, times, duration, transcript, anchors["clock"]["start_ms"]
    )
