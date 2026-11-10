"""Bind original flash and comment handoffs to the recorded words and project media."""

import math
import re
from itertools import pairwise

from .video_editing_contracts import SemanticBeat, Transcript
from .video_editing_materials import project_image_digests

HANDOFF_TEMPLATE_ID = "unified-handoff-v1"
FLASH = "W-R03"
COMMENT = "W-R06"
HANDOFF_GROUPS = {
    FLASH: (
        "用原生闪亮拉伸把前一项同期实录交接给本期已登记的后项配图。",
        "flash.before 从本段首词取短句，flash.after 从后项首词取短句，"
        "header 来自前项。transition_start 与后项首词同钟，"
        "transition_peak、transition_end 从该处之后依序取实录词点。"
        "两个 relation_items 依序对应文字和媒体，after 需对应后项的独立项目图。",
    ),
    COMMENT: (
        "按实录中明确的评论邀请和指定关键词启动原生输入框。",
        "rise_in 锚定口播中评论邀请短句的首词，submitted_in 锚定明确说出的关键词首词。"
        "输入框前使用同期原片，提交后使用本期已登记的独立图片。"
        "缺少评论邀请、输入指令或词点时跳过。",
    ),
}
HANDOFF_SOURCE = {FLASH: "/media/before/path", COMMENT: "/media/background_before/path"}
HANDOFF_IMAGE = {FLASH: "/media/after/path", COMMENT: "/media/background_after/path"}
HANDOFF_SOUNDS = {
    FLASH: {"transition_start": "virtual"},
    COMMENT: {"rise_in": "virtual", "submitted_in": "visible"},
}
HANDOFF_CAPTION_BANDS = {FLASH: (825, 960), COMMENT: (850, 960)}
_INVITATION = ("评论", "留言")
_INPUT = ("输入", "回复", "打出", "打上", "留下")
_NEGATED = (
    "不要",
    "不用",
    "无需",
    "不必",
    "不能",
    "禁止",
    "别在",
    "别去",
    "别评论",
    "别留言",
    "别输入",
    "别回复",
)


def handoff_blockers(
    template: dict | None,
    transcript: Transcript,
    cards: list[dict],
    unavailable: dict,
) -> None:
    if not template or template["id"] != HANDOFF_TEMPLATE_ID:
        return
    if not project_image_digests(cards):
        for group in HANDOFF_GROUPS:
            unavailable.setdefault(group, []).append("handoff_image_required")
    recorded = "".join(token.text for token in transcript.tokens)
    if not (
        any(word in recorded for word in _INVITATION)
        and any(word in recorded for word in _INPUT)
    ):
        unavailable.setdefault(COMMENT, []).append(
            "spoken_comment_instruction_required"
        )


def handoff_virtual_frame(group: str, timing: dict) -> int:
    # build12 maps each actual frame back to the original discrete effect frame.
    # The flash first draws at native frame 13, after the 12.5 boundary.
    if group == FLASH:
        return math.floor(timing["transition_start"] * 30 * 12.5 / 13 + 1e-8) + 1
    # The comment easing starts after native 0.18s. Native frame 6 is its first
    # visible frame. At the 5.5 boundary, the original rounds to even (6).
    seconds = timing["rise_in"] + timing["rise_duration"] * (5.5 / 30 - 0.18) / 0.42
    return math.ceil(seconds * 30 - 1e-8)


def validate_handoff_anchors(
    beat: SemanticBeat, anchors: dict, transcript: Transcript, images: dict[str, str]
) -> None:
    group = beat.group_id
    bound = {row["path"]: row["asset_id"] for row in anchors["media"]}
    if bound[HANDOFF_IMAGE[group]] not in images:
        raise ValueError("The after phase must use a registered project image")
    text = {row["path"].removeprefix("/content/"): row for row in anchors["text"]}
    events = {
        row["path"].removeprefix("/timing/events/"): row for row in anchors["events"]
    }
    times = {name: row["value"] for name, row in events.items()}
    clock = anchors["clock"]
    duration = (clock["end_ms"] - clock["start_ms"]) / 1000
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    if (
        not 0.8 <= duration <= 12
        or any("\n" in row["text"] or len(row["text"]) > 14 for row in text.values())
        or any(row["edge"] != "start" for row in events.values())
    ):
        raise ValueError("Original handoff needs short measured on-screen phases")

    if group == FLASH:
        first, second, header = (
            text[f"flash/{key}"] for key in ("before", "after", "header")
        )
        parts = beat.relation_items
        start, peak, end = (
            times[f"transition_{key}"] for key in ("start", "peak", "end")
        )
        first_visible = handoff_virtual_frame(group, times) / 30
        valid = (
            beat.relation in {"sequence", "contrast"}
            and len(parts) == 2
            and positions[parts[0].last_token_id] < positions[parts[1].first_token_id]
            and first["token_ids"][0] == beat.first_token_id
            and set(header["token_ids"]).issubset(first["token_ids"])
            and second["token_ids"][0] == events["transition_start"]["token_id"]
            and all(
                events[f"transition_{phase}"]["token_id"] in second["token_ids"]
                for phase in ("peak", "end")
            )
            and all(
                item.native_text_paths == [f"/content/flash/{role}"]
                and item.native_media_paths == [path]
                and item.asset_ids == [bound[path]]
                and item.first_token_id == row["token_ids"][0]
                and item.last_token_id == row["token_ids"][-1]
                for item, role, path, row in zip(
                    parts,
                    ("before", "after"),
                    (HANDOFF_SOURCE[group], HANDOFF_IMAGE[group]),
                    (first, second),
                    strict=True,
                )
            )
            and start >= max(0.27, len(first["text"]) / 15)
            and abs(first_visible - start) <= 1 / 30 + 1e-6
            and all(a + 1 / 30 <= b for a, b in pairwise((start, peak, end)))
            and peak - start <= 0.30
            and end - start <= 0.80
            and end + max(0.25, len(second["text"]) / 15) <= duration
        )
    else:
        invitation, keyword = text["placeholder"], text["word"]
        word_start = positions[keyword["token_ids"][0]]
        instruction_start = positions[invitation["token_ids"][-1]] + 1
        instruction = "".join(
            token.text for token in transcript.tokens[instruction_start:word_start]
        ).rstrip(" ，、：,:。")
        spoken_invitation = "".join(
            token.text
            for token in transcript.tokens[
                positions[beat.first_token_id] : instruction_start
            ]
        ).rstrip(" ，、：,:。！？.!?")
        invitation_clause = re.split(r"[，。！？,!?.]", spoken_invitation)[-1]
        valid = (
            beat.relation == "call_to_action"
            and any(word in invitation["text"] for word in _INVITATION)
            and instruction.endswith(_INPUT)
            and not any(
                word in invitation_clause or word in instruction for word in _NEGATED
            )
            and len(keyword["text"]) <= 8
            and events["rise_in"]["token_id"] == invitation["token_ids"][0]
            and events["submitted_in"]["token_id"] == keyword["token_ids"][0]
            and 0.12 <= times["rise_in"] <= times["submitted_in"] - 0.80
            and times["submitted_in"] <= duration - 0.45
        )
    if not valid:
        raise ValueError(
            "Handoff phase or relation does not follow the actual spoken cues"
        )
