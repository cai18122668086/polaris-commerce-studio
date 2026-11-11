"""Measured inputs for the original Chenxi independent B-roll layouts."""

import math
from pathlib import Path

from .motion_library import read_json
from .video_editing_contracts import Transcript, TranscriptToken
from .video_editing_materials import PREFIX
from .video_editing_word_bindings import measured_clause_windows

CXBR_TEMPLATE_ID = "chenxi-broll-v1"
CXBR_DESIGN_ID = "tengli-chenxi-broll-v1"
CXBR_CAPTION_INTENT = "chenxi-broll-caption-intent.json"
CXBR_PRESENTER = "/media/presenter/path"
CXBR_PAPER = "/media/paper/path"
CXBR_PURPOSES = {
    "CXBR01": "上方展开本期补充视频，下方的同期人物逐渐收进圆窗。",
    "CXBR02": "把本期补充视频放大为全幅，同期人物抠像落到侧下方。",
    "CXBR03": "用本期纸纹分隔上方同期人物窗和下方补充视频。",
    "CXBR04": "在本期补充视频上收起同期人物窗，再翻出实录纸条。",
    "CXBR05": "先出现本期补充视频带，再滑入同期人物圆窗。",
}
CXBR_DEPENDENCIES = {
    "CXBR01": ("font-43a890795ad133d7",),
    "CXBR02": ("model-01eb6a29a5c4d8edb30b",),
}
CXBR_PAPER_GROUPS = frozenset({"CXBR01", "CXBR03", "CXBR05"})
CXBR_CLIP_START = {
    "CXBR01": "room_in",
    "CXBR02": "broll_in",
    "CXBR03": "window_in",
    "CXBR04": None,
    "CXBR05": "band_in",
}
CXBR_SOUNDS = {
    "CXBR01": {"/content/captions/0/at": 0},
    "CXBR02": {"/timing/broll_in": 0},
    "CXBR03": {"/timing/window_in": 0},
    "CXBR04": {"/timing/portrait_in": 0, "/timing/strip_in": 0},
    "CXBR05": {"/timing/band_in": 0, "/timing/circle_in": 1},
}
_CAPTION_COUNT = {"CXBR01": 3, "CXBR02": 1, "CXBR03": 1, "CXBR04": 1, "CXBR05": 2}
_MIN_FRAMES = {"CXBR01": 84, "CXBR02": 40, "CXBR03": 40, "CXBR04": 64, "CXBR05": 55}
_MIN_CLIP_FRAMES = {
    "CXBR01": 45,
    "CXBR02": 18,
    "CXBR03": 18,
    "CXBR04": 64,
    "CXBR05": 27,
}
_TAIL = 10
_INACTIVE_TEXT = {"CXBR01": ("title", "description", "product", "product_sub")}
_TIMING_HINTS: dict[str, dict[str, int | str]] = {
    "CXBR01": {
        "title_in": 0,
        "title_detail": 5,
        "title_move": 20,
        "title_move_end": "room_settle",
        "room_in": 30,
        "room_settle": 43,
        "portrait_reframe": "room_in",
        "portrait_reframe_end": "room_settle",
        "portrait_shrink": 54,
        "portrait_settle": 65,
        "caption_move": "portrait_settle",
        "caption_settle": 74,
        "caption_plate": 82,
    },
    "CXBR02": {
        "broll_in": 30,
        "broll_settle": 49,
        "person_in": "broll_in",
        "person_settle": 62,
    },
    "CXBR03": {"window_in": 28, "window_settle": 48},
    "CXBR04": {
        "portrait_in": 0,
        "portrait_settle": 29,
        "strip_in": 49,
        "strip_settle": 76,
    },
    "CXBR05": {"band_in": 21, "circle_in": 49, "circle_settle": 62},
}
_CAPTION_HINTS: dict[str, tuple[tuple[str, int | None], ...]] = {
    "CXBR01": (("room_in", None), ("portrait_shrink", None), ("caption_plate", None)),
    "CXBR02": (("broll_in", 70),),
    "CXBR03": (("window_in", 71),),
    "CXBR04": (("portrait_in", 38),),
    "CXBR05": (("portrait_in", 39), ("circle_settle", 92)),
}


def cxbr_clip_path(group: str) -> str:
    return "/media/room/path" if group == "CXBR01" else "/media/broll/path"


def cxbr_empty_paths(group: str) -> dict[str, str]:
    return {
        f"/content/{name}": "原教程和水印开关保持关闭。"
        for name in _INACTIVE_TEXT.get(group, ())
    }


def cxbr_text_paths(group: str) -> tuple[str, ...]:
    return tuple(
        f"/content/captions/{i}/text" for i in range(_CAPTION_COUNT[group])
    ) + (("/content/strip",) if group == "CXBR04" else ())


def cxbr_binding(group: str) -> str:
    return (
        "presenter 使用同期原片，独立补充视频须与当前语义相关并覆盖自身原生时钟。"
        + ("paper 另用一张本期图片。" if group in CXBR_PAPER_GROUPS else "")
        + ("reference 绑定同一原片，教程和水印文字留空。" if group == "CXBR01" else "")
        + "可参考 chenxi_broll_windows 的实录范围和动作边界。"
        "从实录选完整短语，并把对应入场事件一起移到其首词。"
        "补充视频从对应槽的可用 ID 中选择。原生标签最多 12 字，纸条最多 8 字。"
    )


def cxbr_project_media(cards: list[dict], source_sha: str) -> tuple[dict, dict]:
    project = [
        row
        for row in cards
        if row["id"].startswith(PREFIX) and row["sha256"] != source_sha
    ]
    return (
        {row["id"]: row for row in project if row["kind"] == "video"},
        {row["id"]: row for row in project if row["kind"] == "image"},
    )


def cxbr_clip_ids(videos: dict, frames: int) -> list[str]:
    required = math.ceil(frames * 1000 / 30)
    return sorted(
        key
        for key, row in videos.items()
        if type(row.get("duration_ms")) is int and row["duration_ms"] >= required
    )


def cxbr_blockers(
    template: dict | None,
    source_subtitles: str,
    cards: list[dict],
    source_sha: str,
    unavailable: dict[str, list[str]],
) -> None:
    if not template or template["id"] != CXBR_TEMPLATE_ID:
        return
    videos, images = cxbr_project_media(cards, source_sha)
    for group in CXBR_PURPOSES:
        for code, missing in (
            ("clean_source_required", source_subtitles != "none"),
            (
                "independent_video_required",
                not cxbr_clip_ids(videos, _MIN_CLIP_FRAMES[group]),
            ),
            ("paper_image_required", group in CXBR_PAPER_GROUPS and not images),
        ):
            if missing:
                unavailable.setdefault(group, []).append(code)


def _timing_values(group: str, values: dict[str, int], frames: int) -> int:
    """Reject clocks which cannot show all of the original scene's phases."""

    def t(name: str) -> int:
        return values[f"/timing/{name}"]

    def c(i: int, edge: str = "at") -> int:
        return values[f"/content/captions/{i}/{edge}"]

    if group == "CXBR01":
        valid = (
            t("title_in")
            <= t("title_detail")
            < t("title_move")
            <= t("room_in")
            == t("portrait_reframe")
            == c(0)
            < t("room_settle")
            == t("portrait_reframe_end")
            and t("title_move") < t("title_move_end") <= t("room_settle")
            and t("room_settle")
            <= t("portrait_shrink")
            == c(1)
            < t("portrait_settle")
            <= t("caption_move")
            < t("caption_settle")
            <= t("caption_plate")
            == c(2)
            and min(c(1) - c(0), c(2) - c(1), frames - c(2)) >= _TAIL
        )
    elif group == "CXBR02":
        valid = (
            c(0) == t("broll_in") == t("person_in")
            and c(0) + 6 <= min(t("broll_settle"), t("person_settle"))
            and max(t("broll_settle"), t("person_settle")) + _TAIL <= frames
        )
    elif group == "CXBR03":
        valid = (
            c(0) == t("window_in") and c(0) + 6 <= t("window_settle") <= frames - _TAIL
        )
    elif group == "CXBR04":
        valid = (
            t("portrait_in") == 0
            and 6 <= t("portrait_settle") <= t("strip_in")
            and c(0, "end") <= t("strip_in")
            and t("strip_settle") - t("strip_in") >= 12
            and t("strip_settle") + _TAIL <= frames
        )
    else:
        valid = (
            c(0) < t("band_in") < t("circle_in") < t("circle_settle")
            and t("circle_in") - t("band_in") >= 8
            and c(0, "end") <= c(1)
            and t("circle_in") <= c(1)
            and max(c(1), t("circle_settle")) + _TAIL <= frames
        )
    clip_start = CXBR_CLIP_START[group]
    clip_frames = frames - (t(clip_start) if clip_start else 0)
    if (
        not valid
        or frames < _MIN_FRAMES[group]
        or clip_frames < _MIN_CLIP_FRAMES[group]
        or any(value < 0 or value > frames for value in values.values())
        or any(
            c(i, "end") - c(i) < _TAIL
            for i in range(_CAPTION_COUNT[group])
            if f"/content/captions/{i}/end" in values
        )
    ):
        raise ValueError(
            "Measured words do not leave room for the original B-roll phases"
        )
    return clip_frames


def validate_cxbr_anchors(
    group: str, anchors: dict, videos: dict, images: dict, transcript: Transcript
) -> None:
    clock = anchors["clock"]
    frames = math.ceil((clock["end_ms"] - clock["start_ms"]) * 30 / 1000)
    events = {row["path"]: row for row in anchors["events"]}
    media = {row["path"]: row["asset_id"] for row in anchors["media"]}
    if media.get("/reference", media[CXBR_PRESENTER]) != media[CXBR_PRESENTER]:
        raise ValueError("Reference and presenter must be the same measured original")
    if group in CXBR_PAPER_GROUPS and media[CXBR_PAPER] not in images:
        raise ValueError("Original paper slot requires a project still")
    clip_frames = _timing_values(
        group, {path: row["value"] for path, row in events.items()}, frames
    )
    if media[cxbr_clip_path(group)] not in cxbr_clip_ids(videos, clip_frames):
        raise ValueError("Independent B-roll does not cover its original clock window")
    if any(events[path]["edge"] != "start" for path in CXBR_SOUNDS[group]):
        raise ValueError("Original scene entrance needs an actual word start")
    token_ends = {token.id: token.end_ms for token in transcript.tokens}
    for row in anchors["text"]:
        path = row["path"]
        strip = path == "/content/strip"
        first = events[
            "/timing/strip_in" if strip else path.removesuffix("/text") + "/at"
        ]
        end = events.get(path.removesuffix("/text") + "/end")
        if group == "CXBR01":
            i = int(path.split("/")[3])
            end = events.get(f"/content/captions/{i + 1}/at")
        if (
            not 1 <= len(row["text"]) <= (8 if strip else 12)
            or "\n" in row["text"]
            or first["edge"] != "start"
            or first["token_id"] != row["token_ids"][0]
            or (end and end["measured_anchor_ms"] < token_ends[row["token_ids"][-1]])
        ):
            raise ValueError("Scene label must fit and enter on its actual first word")


def _window_hint(
    group: str, tokens: list[TranscriptToken], frames: int
) -> tuple[list[dict], int]:
    origin = tokens[0].start_ms
    starts = [round((token.start_ms - origin) * 30 / 1000) for token in tokens]
    ends = [round((token.end_ms - origin) * 30 / 1000) for token in tokens]

    def nearest(ticks: list[int], fraction: int) -> int:
        return min(
            range(len(ticks)), key=lambda i: abs(100 * ticks[i] - fraction * frames)
        )

    stages = {
        name: nearest(starts, fraction)
        for name, fraction in _TIMING_HINTS[group].items()
        if isinstance(fraction, int)
    }
    stages.update(
        {
            name: stages[alias]
            for name, alias in _TIMING_HINTS[group].items()
            if isinstance(alias, str)
        }
    )
    picks = {f"/timing/{name}": (index, "start") for name, index in stages.items()}
    for i, (start, end) in enumerate(_CAPTION_HINTS[group]):
        base = f"/content/captions/{i}"
        first = stages.get(start, 0)
        picks[f"{base}/at"] = (first, "start")
        if end is not None:
            picks[f"{base}/end"] = (nearest(ends, end), "end")
    required = _timing_values(
        group,
        {
            path: (starts if edge == "start" else ends)[i]
            for path, (i, edge) in picks.items()
        },
        frames,
    )
    return (
        [
            {"path": path, "token_id": tokens[i].id, "edge": edge}
            for path, (i, edge) in picks.items()
        ],
        required,
    )


def cxbr_windows(
    template: dict | None, transcript: Transcript, cards: list[dict], unavailable: dict
) -> dict[str, list[dict]]:
    if not template or template["id"] != CXBR_TEMPLATE_ID:
        return {}
    videos, images = cxbr_project_media(cards, transcript.source_sha256)
    candidates: dict[str, list[dict]] = {
        group: [] for group in CXBR_PURPOSES if group not in unavailable
    }
    for tokens in measured_clause_windows(transcript):
        frames = math.ceil((tokens[-1].end_ms - tokens[0].start_ms) * 30 / 1000)
        for group, options in candidates.items():
            if frames < _MIN_FRAMES[group]:
                continue
            try:
                events, required = _window_hint(group, tokens, frames)
            except ValueError:
                continue
            clips = cxbr_clip_ids(videos, required)
            if clips:
                options.append(
                    {
                        "first_token_id": tokens[0].id,
                        "last_token_id": tokens[-1].id,
                        "native_events": events,
                        "material_ids_by_path": {
                            cxbr_clip_path(group): clips,
                            **(
                                {CXBR_PAPER: sorted(images)}
                                if group in CXBR_PAPER_GROUPS
                                else {}
                            ),
                        },
                    }
                )
    return {
        group: [options[i * (len(options) - 1) // 7] for i in range(8)]
        if len(options) > 8
        else options
        for group, options in candidates.items()
        if options
    }


def cxbr_entry_frame(shot: dict, fps: int, path: str) -> int:
    if fps != 30 or shot["layer"] != "scene" or shot["rect"] != [0, 0, 1, 1]:
        raise ValueError("B-roll sound requires an original full-frame scene")
    config = shot["config"]
    local = (
        config["timing"][path.rsplit("/", 1)[1]]
        if path.startswith("/timing/")
        else config["content"]["captions"][0]["at"]
    ) + CXBR_SOUNDS[shot["group_id"]][path]
    origin = shot["start_seconds"] / (1 / fps)
    frame = max(math.ceil(origin - 1e-6), math.floor(origin) + local)
    if frame >= math.ceil(shot["end_seconds"] * fps - 1e-6):
        raise ValueError("B-roll sound falls after the last visible native frame")
    return frame


def verify_cxbr_captions(root: Path, report: dict) -> dict:
    episode = read_json(root / "episode.json")
    indices = read_json(root / CXBR_CAPTION_INTENT)["shots"]
    from .video_editing_caption_presentation import verify_reserved_caption_lane

    if contained := verify_reserved_caption_lane(root, report, indices):
        return contained
    rows = report["caption_ink"]
    if (
        not indices
        or report["status"] != "passed"
        or len(rows) != len(episode["captions"])
        or any(
            (row["start"], row["end"]) != (cap["start_seconds"], cap["end_seconds"])
            or len(row["box"]) != 4
            for row, cap in zip(rows, episode["captions"], strict=True)
        )
    ):
        raise ValueError("Original B-roll needs actual caption ink on its timeline")
    # The highest native lower extent is CXBR04's paper strip, including its warp.
    bottom = math.ceil(episode["output"]["height"] * 970 / 1280)
    checks = []
    for index in indices:
        shot = episode["shots"][index]
        active = [
            row["box"][1]
            for row in rows
            if row["start"] < shot["end_seconds"] and shot["start_seconds"] < row["end"]
        ]
        if (
            shot["group_id"] not in CXBR_PURPOSES
            or shot["layer"] != "scene"
            or shot["rect"] != [0, 0, 1, 1]
            or not active
            or min(active) < bottom
        ):
            raise ValueError("Main caption ink enters the original B-roll text band")
        checks.append(
            {"group_id": shot["group_id"], "smallest_gap_px": min(active) - bottom}
        )
    return {"status": "passed", "native_text_band_end_px": bottom, "shots": checks}
