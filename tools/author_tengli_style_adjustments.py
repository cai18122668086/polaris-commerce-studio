"""Explicit operator adjustments to captured demos; never claims model first-pass.

Only selected real speech ranges are bound. The original response stays intact.
Uses the existing strict native recipe compiler, then the public preview API.
"""

import argparse
import json
import sqlite3
import sys
from bisect import bisect_right
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import build_database
from app.motion_library import atomic_json, read_json, sha256
from app.video_editing_contracts import (
    NativeEventAnchor,
    NativeMediaAnchor,
    NativeTextAnchor,
    SemanticPlan,
    SemanticRelationItem,
    Transcript,
)
from app.video_editing_first_groups import PAIR_PROFILES, ShotChoice, _pair
from app.video_editing_native_plans import content_digest, register_operator_plan
from app.video_editing_overlay_recipes import _TEXT_ENTRY_WORDS, build_overlay_recipes
from app.video_editing_template_styles import validate_template_style
from app.video_editing_word_bindings import emphasis_text
from tengli_site_demo_runtime import settings_for

REPLACEMENTS = {
    "presenter-openings-v1": {
        "beat-recreate": {"main": "一键复刻", "detail": "自己的商品"},
        "beat-detail-images": {"main": "套图", "detail": "视觉内容"},
        "beat-inspiration-condition": {"title": "灵感专区", "detail": "没有明确方向时"},
        "beat-selection-principle": {"body": "你这次", "emphasis": "交付什么"},
        "beat-next-actions": {"title": "产品信息", "detail": "看结果"},
    },
    "rotation-cards-v1": {
        "replicate-two-aspects": {"body": "构图", "focus": "自己的商品"},
        "three-other-entrances": {"_item1": "详情图"},
        "preserve-negation": {"main": "入口", "detail": "不是四种商品"},
        "selection-conclusion": {"body": "你这次", "emphasis": "交付什么"},
        "prerequisite-and-next-actions": {"title": "产品信息", "detail": "看结果"},
    },
    "azl-panels-v1": {
        "beat-recreate": {
            "title": "一键复刻",
            "tagline": "自己的商品",
            "subtitle": "一键复刻",
        },
        "beat-inspiration-condition": {"title": "灵感专区", "detail": "没有明确方向时"},
        "beat-creative-direction": {"body": "创作", "keyword": "思路"},
        "beat-correct-classification": {
            "_group": "AH-S08",
            "title": "四个入口",
            "detail": "不是四种商品",
        },
        "beat-selection-rule": {"body": "你这次", "focus": "交付什么"},
        "beat-prepare-inputs": {
            "_group": "AH-S09",
            "title": "确定",
            "detail": "目标后，上传原图",
        },
        "beat-closing": {"main": "任务中心", "detail": "看结果"},
    },
    "unified-chapter-v1": {
        "beat-inspiration-condition": {
            "_group": "AH-S08",
            "title": "灵感专区",
            "detail": "没有明确方向时",
        },
        "beat-entry-not-product": {
            "_group": "AH-S08",
            "title": "四个入口",
            "detail": "不是四种商品",
        },
        "beat-delivery-decision": {"phrases/0": "你这次", "phrases/1": "交付什么"},
        "beat-upload-and-information": {
            "_group": "AH-S09",
            "title": "确定",
            "detail": "目标后，上传原图",
        },
        "beat-task-center-close": {"body": "任务中心", "keyword": "看结果"},
    },
    "unified-paper-typewriter-v1": {
        "beat-opening": {"_group": "AH-S09", "title": "极光商绘", "detail": "四个入口"},
        "beat-core-selling-point": {"body": "突出", "emphasis": "核心卖点"},
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--provider-env", type=Path, required=True)
    parser.add_argument("--template", choices=list(REPLACEMENTS), required=True)
    parser.add_argument("--submit", action="store_true")
    args = parser.parse_args()
    root, tid = args.root, args.template
    flow = read_json(root / "flow.json")
    pid = flow["plans"][tid]
    directory = root / "tasks/_planning" / pid
    seed_pid = (
        flow["plans"]["unified-chapter-v1"]
        if tid == "unified-paper-typewriter-v1"
        else pid
    )
    seed_directory = root / "tasks/_planning" / seed_pid
    response_path = seed_directory / "provider/semantic-response.json"
    plan = (
        SemanticPlan.model_validate(
            read_json(root / "adjustments/unified-chapter-v1/semantic.json")
        )
        if tid == "unified-paper-typewriter-v1"
        else SemanticPlan.model_validate_json(read_json(response_path)["content"])
    )
    transcript = Transcript.model_validate(
        read_json(next(directory.rglob("transcript.json")))
    )
    positions = {t.id: i for i, t in enumerate(transcript.tokens)}
    with sqlite3.connect(root / "site.db") as db:
        raw_snapshot, transcript_sha = db.execute(
            "select snapshot,base_transcript_sha256 "
            "from video_editing_planning_tasks where id=?",
            (pid,),
        ).fetchone()
        snapshot = json.loads(raw_snapshot)

    def span(beat, phrase):
        begin, end = positions[beat.first_token_id], positions[beat.last_token_id]
        offsets, text = [0], ""
        for token in transcript.tokens[begin : end + 1]:
            text += token.text
            offsets.append(len(text))
        start = text.index(phrase)
        stop = start + len(phrase)
        first = bisect_right(offsets, start) - 1
        last = bisect_right(offsets, stop - 1) - 1
        actual = "".join(
            token.text for token in transcript.tokens[begin + first : begin + last + 1]
        )
        if emphasis_text(actual, "omit_sentence_punctuation") != emphasis_text(
            phrase, "omit_sentence_punctuation"
        ):
            raise ValueError("Operator phrase cuts a measured token: " + phrase)
        return begin + first, begin + last

    changed = []
    if tid == "unified-paper-typewriter-v1":
        plan.chapter_start_token_ids = []
        plan.argument_outline = [
            "入口概览",
            "复刻与主图",
            "详情与灵感",
            "按目标准备素材",
        ]
        by_id = {beat.id: beat for beat in plan.beats}

        def paper(seed_id, end, rows):
            beat = by_id[seed_id].model_copy(deep=True)
            beat.group_id, beat.relation = "Z-M11", "parallel"
            beat.last_token_id = transcript.tokens[end].id
            beat.native_text, beat.native_events, beat.relation_items = [], [], []
            for index, (label, body) in enumerate(rows):
                a, b = span(beat, label)
                c, d = span(beat, body)
                paths = [f"/content/rows/{index}/label", f"/content/rows/{index}/text"]
                for path, first, last in [(paths[0], a, b), (paths[1], c, d)]:
                    beat.native_text.append(
                        NativeTextAnchor(
                            path=path,
                            first_token_id=transcript.tokens[first].id,
                            last_token_id=transcript.tokens[last].id,
                            punctuation="omit_sentence_punctuation",
                        )
                    )
                beat.native_events.append(
                    NativeEventAnchor(
                        path=f"/timing/events/row{index}",
                        token_id=transcript.tokens[a].id,
                        edge="start",
                    )
                )
                beat.relation_items.append(
                    SemanticRelationItem(
                        id=f"paper-row-{index}",
                        first_token_id=transcript.tokens[a].id,
                        last_token_id=transcript.tokens[d].id,
                        native_text_paths=paths,
                    )
                )
            beat.asset_ids = ["source-" + flow["source"]]
            beat.native_media = [
                NativeMediaAnchor(
                    path="/media/presenter/path", asset_id=beat.asset_ids[0]
                )
            ]
            beat.reason = (
                "人工按本期完整实录将两项说明绑定到原生方格纸两行；"
                "逐字时钟由原引擎驱动。"
            )
            return beat

        first_paper = paper(
            "beat-replication-chapter",
            58,
            [("复刻", "借鉴参考的构图和风格"), ("主图", "用于搜索主图和轮播")],
        )
        second_paper = paper(
            "beat-detail-components",
            119,
            [("详情", "商品信息、细节和场景"), ("灵感", "在没有明确方向时")],
        )
        selling = by_id["beat-core-selling-point"]
        selling.first_token_id = transcript.tokens[59].id
        plan.beats = [
            by_id["beat-opening"],
            first_paper,
            selling,
            second_paper,
            by_id["beat-entry-not-product"],
            by_id["beat-delivery-decision"],
            by_id["beat-upload-and-information"],
            by_id["beat-task-center-close"],
        ]
        changed.extend([first_paper.id, second_paper.id, selling.id])
    if tid == "unified-chapter-v1":
        for beat in plan.beats:
            heading = {
                "beat-opening": "四个入口",
                "beat-replication-chapter": "构图和风格",
                "beat-main-image-purpose": "搜索主图",
                "beat-detail-components": "商品信息",
            }.get(beat.id)
            if not heading:
                continue
            first, last = span(beat, heading)
            begin = positions[beat.first_token_id]
            move = next(
                i
                for i in range(begin, first + 1)
                if transcript.tokens[i].start_ms
                >= transcript.tokens[begin].start_ms + 220
            )
            beat.group_id, beat.relation = "Z-M15", "explanation"
            beat.emphasis_token_ids = [
                v.id for v in transcript.tokens[first : last + 1]
            ]
            beat.native_text = [
                NativeTextAnchor(
                    path="/content/title",
                    first_token_id=transcript.tokens[first].id,
                    last_token_id=transcript.tokens[last].id,
                    punctuation="omit_sentence_punctuation",
                )
            ]
            beat.native_events = [
                NativeEventAnchor(
                    path="/timing/events/" + key,
                    token_id=transcript.tokens[i].id,
                    edge="start",
                )
                for key, i in [("ordinal", begin), ("move", move), ("title", first)]
            ]
            beat.asset_ids = ["source-" + flow["source"]]
            beat.native_media = [
                NativeMediaAnchor(
                    path="/media/presenter/path", asset_id=beat.asset_ids[0]
                )
            ]
            changed.append(beat.id)
    for beat in plan.beats:
        # The adjusted visible highlights are the explicit native_text fields;
        # do not retain a second, inconsistent model emphasis annotation.
        beat.emphasis_token_ids = []
        changes = REPLACEMENTS[tid].get(beat.id)
        if changes:
            changes = dict(changes)
            if "_group" in changes:
                beat.group_id = changes.pop("_group")
                beat.native_media = []
                beat.asset_ids = []
        if beat.group_id == "CX-G04" and changes:
            first, last = span(beat, changes["_item1"])
            anchor = next(a for a in beat.native_text if a.path == "/items/1/label")
            anchor.first_token_id, anchor.last_token_id = (
                transcript.tokens[first].id,
                transcript.tokens[last].id,
            )
            changed.append(beat.id)
            changes = None
        for anchor in beat.native_text:
            anchor.punctuation = "omit_sentence_punctuation"
        if tid == "rotation-cards-v1" and beat.id == "preserve-negation":
            # JJ-S01's detail is five characters, so retain the full denial in a
            # wider native conclusion instead of truncating the actual quantity.
            beat.group_id = "AH-S09"
            changes = {"title": "四个入口", "detail": "不是四种商品"}
        if changes:
            old = {a.path: a for a in beat.native_text}
            ranges = {
                "/content/" + key: span(beat, phrase) for key, phrase in changes.items()
            }
            beat.native_text = [
                NativeTextAnchor(
                    path=path,
                    first_token_id=transcript.tokens[a].id,
                    last_token_id=transcript.tokens[b].id,
                    punctuation="omit_sentence_punctuation",
                )
                for path, (a, b) in ranges.items()
            ]
            if beat.group_id in PAIR_PROFILES:
                left, right, *_ = PAIR_PROFILES[beat.group_id]
                words = [ranges["/content/" + left], ranges["/content/" + right]]
                native = _pair(
                    ShotChoice(
                        group=beat.group_id,
                        span=(
                            positions[beat.first_token_id],
                            positions[beat.last_token_id],
                        ),
                        words=words,
                        why="人工按原生字槽选取完整实录短语",
                    ),
                    transcript,
                    "source-" + flow["source"],
                    align_line_entrance=True,
                )
                beat.native_events = [
                    NativeEventAnchor(
                        path=path, token_id=transcript.tokens[i].id, edge=edge
                    )
                    for path, (i, edge) in native.events.items()
                ]
            elif beat.group_id in {"JJ-S01", "JJ-S04"}:
                beat.native_events = [
                    NativeEventAnchor(
                        path=f"/events/{role}/{edge_index}",
                        token_id=transcript.tokens[bound].id,
                        edge=edge,
                    )
                    for role in (
                        ("main", "detail")
                        if beat.group_id == "JJ-S01"
                        else ("body", "keyword")
                    )
                    for edge_index, bound, edge in (
                        (0, ranges["/content/" + role][0], "start"),
                        (1, ranges["/content/" + role][1], "end"),
                    )
                ]
            elif beat.group_id == "BG-S05":
                beat.native_events = [
                    NativeEventAnchor(
                        path="/events/" + role + "_frame",
                        token_id=transcript.tokens[ranges["/content/" + role][0]].id,
                        edge="start",
                    )
                    for role in ("body", "focus")
                ]
            else:
                mapping = {}
                for path, anchor in old.items():
                    if path in ranges:
                        a, b = ranges[path]
                        mapping[anchor.first_token_id] = transcript.tokens[a].id
                        mapping[anchor.last_token_id] = transcript.tokens[b].id
                for event in beat.native_events:
                    event.token_id = mapping.get(event.token_id, event.token_id)
                for event, role in _TEXT_ENTRY_WORDS.get(beat.group_id, {}).items():
                    anchor = next(
                        a for a in beat.native_text if a.path == "/content/" + role
                    )
                    target = next(
                        (e for e in beat.native_events if e.path == "/events/" + event),
                        None,
                    )
                    if target:
                        target.token_id, target.edge = anchor.first_token_id, "start"
            changed.append(beat.id)
        # The operator is fitting complete displayed phrases, not claiming that
        # a paragraph-sized slot is several independently animated sub-items.
        if beat.group_id == "AZL06":
            beat.relation = "parallel"
            beat.relation_items = [
                SemanticRelationItem(
                    id=f"operator-card-{i}",
                    first_token_id=a.first_token_id,
                    last_token_id=a.last_token_id,
                    native_text_paths=[a.path],
                )
                for i in range(3)
                for a in beat.native_text
                if a.path == f"/content/cards/{i}"
            ]
        elif beat.group_id not in {"CX-G04", "Z-M11"}:
            if beat.relation == "parallel":
                beat.relation = "explanation"
            beat.relation_items = [
                SemanticRelationItem(
                    id=f"operator-slot-{i}",
                    first_token_id=a.first_token_id,
                    last_token_id=a.last_token_id,
                    native_text_paths=[a.path],
                )
                for i, a in enumerate(beat.native_text)
            ]
        elif beat.group_id == "CX-G04":
            for item in beat.relation_items:
                anchor = next(
                    a for a in beat.native_text if a.path == item.native_text_paths[0]
                )
                item.first_token_id, item.last_token_id = (
                    anchor.first_token_id,
                    anchor.last_token_id,
                )
    plan.style_reason = (
        "人工核对真实网关响应后，按原生字槽容量和实录完整短语调整；非无修改首轮直出。"
    )
    plan.warnings.append(
        "本版为已保存真实响应的人工调整候选；首轮响应、字段修改、语义与视听验收单独保留。"
    )
    if tid == "unified-paper-typewriter-v1":
        plan.style_reason = (
            "本款模型请求结果未知；人工复用本期同一实录词轴和章节候选，"
            "编排原生方格纸场景，不代表本款模型成功。"
        )
        plan.warnings.append("本款未捕获模型响应；种子来自另一款已保存候选。")
    validate_template_style(plan, snapshot["planning_runtime"])
    settings = settings_for(root, args.provider_env)
    recipes = build_overlay_recipes(
        settings.video_editing_library_dir,
        plan,
        transcript,
        transcript_sha,
        snapshot["overlay_template"],
        snapshot["choice_snapshot"],
        snapshot["asset_cards"],
    )
    recipes = recipes.model_copy(
        update={
            "planning_origin": "operator_candidate",
            "source_review": "真实口播与公开官网配图，人工调整版；待完整视听核对。",
        }
    )
    out = root / "adjustments" / tid
    out.mkdir(parents=True, exist_ok=True)
    atomic_json(out / "semantic.json", plan.model_dump(mode="json"))
    atomic_json(out / "recipes.json", recipes.model_dump(mode="json"))
    atomic_json(
        out / "adjustment-record.json",
        {
            "origin": "operator_candidate",
            "parent_planning_id": pid,
            "seed_planning_id": seed_pid,
            "model_response_for_this_template": tid != "unified-paper-typewriter-v1",
            "parent_response_sha256": sha256(response_path),
            "changed_beats": changed,
            "unmodified_first_pass": False,
            "paid_calls": 0,
            "source_sha256": transcript.source_sha256,
        },
    )
    if args.submit:
        engine, factory = build_database(settings.database_url)
        with factory() as session:
            native = register_operator_plan(
                session,
                settings,
                "ws_development",
                "usr_development",
                flow["alignment"],
                str(
                    uuid5(
                        NAMESPACE_URL,
                        tid + content_digest(plan.model_dump(mode="json")),
                    )
                ),
                plan,
                recipes,
            )
            native_id = native.id
        engine.dispose()
        request_id = str(
            uuid5(NAMESPACE_URL, "tengli-site-adjusted-preview:" + native_id)
        )
        r = httpx.post(
            "http://127.0.0.1:8018/api/v1/video-studio/workspaces/ws_development/editing-tasks",
            headers={"X-User-Id": "usr_development"},
            json={
                "request_id": request_id,
                "source_id": flow["source"],
                "options": {
                    "mode": "native_plan",
                    "native_plan_id": native_id,
                    "source_subtitles": "none",
                    "delivery": "preview_first",
                },
            },
            timeout=60,
        )
        r.raise_for_status()
        atomic_json(out / "preview-task.json", r.json())
        print(
            json.dumps(
                {
                    "template": tid,
                    "native_plan": native_id,
                    "task": r.json()["id"],
                    "origin": "operator_candidate",
                    "paid_calls": 0,
                }
            )
        )
    else:
        print(
            json.dumps(
                {
                    "template": tid,
                    "strict_native_recipe_check": "passed",
                    "origin": "operator_candidate",
                    "paid_calls": 0,
                }
            )
        )


if __name__ == "__main__":
    main()
