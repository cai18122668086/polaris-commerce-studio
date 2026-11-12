"""Retrieve sentence candidates once, before the single full-script planning call.

Descriptions are owner supplied data. Retrieval proposes locations, never facts
or instructions. The semantic planner chooses the final placement; the renderer
uses the frozen word anchors and does no vision/API replanning.
"""

import hashlib
import json
import math
import re
import unicodedata

from .video_editing_contracts import SemanticPlan, Transcript, TranscriptToken

ALIGNMENT_VERSION = "tengli.material-alignment/2"
# Action names often are the only description of a screen recording. Keep
# 上传/点击/复制: removing them loses legitimate matches such as 上传实拍图.
STOP = frozenset(
    [
        "这个",
        "那个",
        "一张",
        "一段",
        "图片",
        "视频",
        "素材",
        "这里",
        "进行",
        "内容",
        "可以",
        "我们",
        "自己",
        "使用",
        "对应",
    ]
)


def terms(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", text).lower()
    for word in STOP:
        normalized = normalized.replace(word, " ")
    result = set(re.findall(r"[a-z0-9][a-z0-9_.+-]+", normalized))
    for run in re.findall(r"[\u3400-\u9fff]+", normalized):
        result.update(run[i : i + 2] for i in range(len(run) - 1))
    return result


def sentence_rows(transcript: Transcript) -> list[dict]:
    """ASR utterance IDs are stable anchors, including when punctuation is absent."""
    if transcript.utterances:
        return [
            {
                "id": row.id,
                "text": row.text,
                "first_token_id": row.token_ids[0],
                "last_token_id": row.token_ids[-1],
            }
            for row in transcript.utterances
        ]
    # Some measured imports have tokens only. Split by pauses and punctuation.
    rows: list[list[TranscriptToken]] = []
    current: list[TranscriptToken] = []
    for token in transcript.tokens:
        if current and token.start_ms - current[-1].end_ms >= 650:
            rows.append(current)
            current = []
        current.append(token)
        if re.search(r"[。！？!?；;]$", token.text):
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    return [
        {
            "id": f"sentence-{i + 1}",
            "text": "".join(t.text for t in row),
            "first_token_id": row[0].id,
            "last_token_id": row[-1].id,
        }
        for i, row in enumerate(rows)
    ]


def alignment_input(transcript: Transcript, cards: list[dict]) -> dict:
    rows = sentence_rows(transcript)
    vocab = [terms(row["text"]) for row in rows]
    idf = {
        term: math.log(1 + len(rows) / (1 + sum(term in v for v in vocab)))
        for term in set().union(*vocab)
    }
    materials = []
    for card in cards:
        if card["kind"] not in {"image", "video"}:
            continue
        name = str(card.get("viewed_identity", ""))
        description = str(card.get("semantic_use", ""))
        query = terms(name + " " + description)
        subject = name
        for generic in (
            "商品",
            "展示",
            "官网",
            "示例",
            "案例",
            "素材",
            "图片",
            "视频",
            "截图",
            "参考",
            "画面",
        ):
            subject = subject.replace(generic, " ")
        named = terms(subject)
        ranked = []
        for row, words in zip(rows, vocab, strict=True):
            common = query & words
            if not common:
                continue
            score = sum(idf[t] * (4 if t in named else 1) for t in common) / max(
                1, sum(idf.get(t, 1) * (4 if t in named else 1) for t in query)
            )
            ranked.append(
                {
                    **row,
                    "score": round(score, 4),
                    "matched_terms": sorted(common),
                    "name_matched_terms": sorted(named & words),
                }
            )
        # Adjacent clauses describing the same asset are one context, rather
        # than competing locations. Never join across a sentence or long pause.
        by_index = {
            next(i for i, row in enumerate(rows) if row["id"] == r["id"]): r
            for r in ranked
        }
        clocks = {token.id: token for token in transcript.tokens}
        grouped = []
        consumed = set()
        for index in sorted(by_index):
            if index in consumed:
                continue
            indices = [index]
            cursor = index
            while cursor + 1 in by_index:
                current, following = rows[cursor], rows[cursor + 1]
                gap = (
                    clocks[following["first_token_id"]].start_ms
                    - clocks[current["last_token_id"]].end_ms
                )
                proposed = indices + [cursor + 1]
                members = [by_index[j] for j in proposed]
                if (
                    re.search(r"[。！？!?；;]", current["text"])
                    or not members[0]["name_matched_terms"]
                    or gap > 650
                    or by_index[cursor + 1]["score"] < 0.06
                    or len(proposed) > 3
                    or sum(len(rows[j]["text"]) for j in proposed) > 80
                    or clocks[following["last_token_id"]].end_ms
                    - clocks[rows[index]["first_token_id"]].start_ms
                    > 12000
                ):
                    break
                indices = proposed
                cursor += 1
            consumed.update(indices)
            members = [by_index[j] for j in indices]
            common = set().union(*(set(m["matched_terms"]) for m in members))
            score = sum(idf[t] * (4 if t in named else 1) for t in common) / max(
                1, sum(idf.get(t, 1) * (4 if t in named else 1) for t in query)
            )
            grouped.append(
                {
                    **members[0],
                    "id": "+".join(m["id"] for m in members),
                    "sentence_ids": [m["id"] for m in members],
                    "text": "".join(m["text"] for m in members),
                    "last_token_id": members[-1]["last_token_id"],
                    "score": round(score, 4),
                    "matched_terms": sorted(common),
                    "name_matched_terms": sorted(
                        set().union(*(set(m["name_matched_terms"]) for m in members))
                    ),
                }
            )
        ranked = grouped
        ranked.sort(
            key=lambda r: (
                -r["score"],
                next(i for i, s in enumerate(rows) if s["id"] == r["sentence_ids"][0]),
            )
        )
        top = ranked[:3]
        status = "unmatched"
        if top and top[0]["score"] >= 0.15:
            status = (
                "ambiguous"
                if len(top) > 1 and top[0]["score"] - top[1]["score"] < 0.08
                else "candidate"
            )
        materials.append(
            {
                "material_id": card["id"],
                "sha256": card["sha256"],
                "kind": card["kind"],
                "name": name,
                "description": description,
                "status": status,
                "candidates": top,
            }
        )
    inputs = {
        "source_sha256": transcript.source_sha256,
        "sentences": rows,
        "materials": materials,
    }
    digest = hashlib.sha256(
        json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()
    return {
        "version": ALIGNMENT_VERSION,
        "input_sha256": digest,
        **inputs,
        "policy": (
            "候选仅为检索提示。先理解完整台词及素材名称说明，再在同一次规划中确定位置；"
            "sentence_ids内相邻分句是同一连续语义段，不是互相竞争的歧义位置。明确相关的命名素材应使用；"
            "歧义或不相关素材跳过。禁止逐帧API查看或渲染后重新规划。"
        ),
    }


def placement_receipt(
    plan: SemanticPlan, transcript: Transcript, cards: list[dict]
) -> dict:
    """Record the final plan's real native media bindings, including unused media."""
    known = {card["id"]: card for card in cards}
    positions = {token.id: i for i, token in enumerate(transcript.tokens)}
    placements = []
    for beat in plan.beats:
        for material_id in sorted(
            set(beat.asset_ids) | {m.asset_id for m in beat.native_media}
        ):
            if material_id not in known:
                raise ValueError("Material placement references an unknown material")
            first, last = positions[beat.first_token_id], positions[beat.last_token_id]
            if last < first:
                raise ValueError("Material placement has reversed word anchors")
            placements.append(
                {
                    "material_id": material_id,
                    "sha256": known[material_id]["sha256"],
                    "kind": known[material_id]["kind"],
                    "beat_id": beat.id,
                    "first_token_id": beat.first_token_id,
                    "last_token_id": beat.last_token_id,
                    "start_ms": transcript.tokens[first].start_ms,
                    "end_ms": transcript.tokens[last].end_ms,
                    "spoken_text": "".join(
                        t.text for t in transcript.tokens[first : last + 1]
                    ),
                    "reason": beat.reason,
                }
            )
    used = {row["material_id"] for row in placements}
    return {
        "version": ALIGNMENT_VERSION,
        "source_sha256": transcript.source_sha256,
        "placements": placements,
        "unused_material_ids": sorted(
            key
            for key, value in known.items()
            if value["kind"] in {"image", "video"} and key not in used
        ),
        "planning_phase": "before_render",
        "render_replanning": False,
    }
