#!/usr/bin/env python3
"""爆款文案评测：对一批自动写稿 run 复算方案第四节用到的全部指标。

只读。数据来自 ``psql``（命令前缀由 ``--psql`` 给出，脚本只拼 SELECT），或来自
``--dump`` 保存的 JSON（CI 与离线复算用）。不依赖 app 包，宿主机 python3 即可跑。

指标：模型调用次数（按步骤）、写稿任务失败率与失败原因、交付率、对标受众违规
（面向同行 / 游戏 / 多品牌横评 / 图文当骨架）、成稿受众与视角违规、编造（无依据
数字、事实外的经历与服务细节、语义质检点名）、重复度（标题+前两句 3-gram
重合、同一卖点出现次数）、时长落档、耗时、token、搜索与转写次数。

用法（正式站只读，PGOPTIONS 里设 default_transaction_read_only=on）::

    python3 backend/scripts/writing_eval.py \\
      --psql "sudo docker exec -e PGOPTIONS=-cdefault_transaction_read_only=on \\
              -i polaris-production-postgres-1 psql -U polaris -d polaris" \\
      c8dbc697-2c28-43ab-a734-5e47ffd68451

    --all                 评测库里全部 auto_writing run（可配 --since 2026-11-27）
    --scenario <id|文件>  按回归集场景的 must_not 词表检查（可多次，按顺序对应 run）
    --dump out.json       另存取到的原始数据；--from-dump in.json 离线复算
    --merge a.json b.json 合并多份 --json 输出（如正式站 + dev 的总失败率）
    --json out.json       指标写成 JSON
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

ID = re.compile(r"^[0-9a-fA-F-]{8,40}$")
REGRESSION = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "writing_regression"
)
CHARS_PER_SECOND = 4.8
WORD_RANGE = {30: (130, 170), 45: (200, 260), 60: (270, 340)}

# 默认词表（回归集场景另有各自的补充）。只用于评测统计，不影响线上逻辑。
PEER_BENCHMARK = [
    "怎么拍",
    "拍视频",
    "拍短视频",
    "获客",
    "引流",
    "自媒体",
    "IP打造",
    "运营",
    "线下课",
    "老板必看",
    "同行",
    "招商",
    "加盟",
    "起号",
    "涨粉",
    "流量密码",
    "做账号",
    "实体店老板",
    "短视频运营",
    "私域",
    "爆款视频的开头",
    "带来十几个",
]
GAME = [
    "洛克王国",
    "迷你世界",
    "光遇",
    "我的世界",
    "原神",
    "王者荣耀",
    "蛋仔",
    "动森",
    "摩尔庄园",
]
MULTI_BRAND = ["大品牌", "品牌盘点", "几个品牌", "十大", "横评", "品牌推荐", "哪个牌子"]
PEER_AUDIENCE_WHO = ["商家", "实体店", "老板", "同行", "创业", "开店的", "做本地"]
PEER_DRAFT = [
    "怎么拍",
    "拍短视频",
    "拍视频",
    "获客",
    "引流",
    "做账号",
    "起号",
    "涨粉",
    "流量",
    "评论区打出",
    "开头思路",
    "同行",
    "实体店老板",
    "短视频选题",
    "同城生意",
]
VISITOR = [
    "朋友推荐",
    "朋友都在提",
    "朋友都在说",
    "趁周末去",
    "去看了看",
    "去逛了",
    "逛到一家",
    "路过",
    "店员跟我说",
    "店员还介绍",
    "销售先招呼",
    "被种草",
    "打卡了",
    "我去了一家",
    "进门先",
]
# 访客叙述的句式（店主自己念不了的话）：朋友推荐 / 周末过去看看 / 店员跟我介绍。
VISITOR_PATTERNS = [
    r"(朋友|闺蜜|同事|身边).{0,4}(推荐|在聊|在说|在提|都说)",
    r"(周末|今天|那天|下班).{0,6}(过去|去了|去看|逛了)",
    r"店员.{0,3}(介绍|说|跟我|告诉)",
    r"(销售|导购|顾问).{0,4}(招呼|追着|跟在后面|说)",
    r"我(上手|坐上去|试了|走进|逛下来|还愣)",
]
INVENTED = [
    "喝茶",
    "喝杯茶",
    "招呼",
    "我坐上去",
    "试了试",
    "久坐",
    "不觉得累",
    "没人追着",
    "款式不少",
    "反复推敲",
    "顾客都说",
    "回头客",
    "好评",
    "销量",
]


# ------------------------------------------------------------------ data ---


def rid(run_id: str, *parts: object) -> str:
    return str(
        uuid5(
            NAMESPACE_URL, ":".join(["tengli-auto-writing", run_id, *map(str, parts)])
        )
    )


def extraction_rid(project_id: str, platform: str, platform_id: str) -> str:
    marker = f"tengli-benchmark-extraction:{project_id}:{platform_id}"
    if platform != "douyin":
        marker = f"tengli-benchmark-extraction:{project_id}:{platform}:{platform_id}"
    return str(uuid5(NAMESPACE_URL, marker))


def quoted(values: list[str]) -> str:
    bad = [v for v in values if not ID.match(v)]
    if bad:
        raise SystemExit(f"不是合法的 id：{bad[:3]}")
    return ",".join(f"'{v}'" for v in values) or "''"


class Psql:
    """Run SELECTs through a psql command line; every query returns one JSON."""

    def __init__(self, command: str) -> None:
        self.command = shlex.split(command)

    def rows(self, sql: str) -> list[dict[str, Any]]:
        if not re.match(r"^\s*select\b", sql, re.I) or ";" in sql:
            raise SystemExit("只允许单条 SELECT")
        wrapped = f"select coalesce(json_agg(t), '[]'::json) from ({sql}) t"
        out = subprocess.run(
            [*self.command, "-X", "-A", "-t", "-v", "ON_ERROR_STOP=1", "-c", wrapped],
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        return json.loads(out.strip() or "[]")


RUN_COLUMNS = (
    "id, project_id, status, error_code, created_at, updated_at, "
    "inputs::jsonb as inputs, result::jsonb as result"
)
TASK_COLUMNS = (
    "id, kind, status, error_code, request_id, created_at, updated_at, "
    "receipt::jsonb as receipt, "
    "case when kind = 'benchmark_search' then result::jsonb "
    "else jsonb_build_object("
    "'validation_issue', result::jsonb->'validation_issue', "
    "'validation_error', result::jsonb->'validation_error', "
    "'source', result::jsonb->'source') end as result"
)


def fetch(
    source: Psql, run_ids: list[str], all_runs: bool, since: str
) -> dict[str, Any]:
    if all_runs:
        where = "kind = 'auto_writing'"
        if since:
            if not re.match(r"^\d{4}-\d{2}-\d{2}", since):
                raise SystemExit("--since 要写成 2026-11-27")
            where += f" and created_at >= '{since[:19]}'"
        runs = source.rows(
            f"select {RUN_COLUMNS} from video_assistance_tasks where {where} "
            "order by created_at"
        )
    else:
        bad = [r for r in run_ids if not ID.match(r)]
        if bad:
            raise SystemExit(f"不是合法的 run id：{bad[:3]}")
        likes = " or ".join(f"id like '{r}%'" for r in run_ids)
        runs = source.rows(
            f"select {RUN_COLUMNS} from video_assistance_tasks "
            f"where kind = 'auto_writing' and ({likes}) order by created_at"
        )
    request_ids: set[str] = set()
    task_ids: set[str] = set()
    for run in runs:
        request_ids |= expected_request_ids(run)
        task_ids |= referenced_task_ids(run)
    tasks = []
    if request_ids or task_ids:
        tasks = source.rows(
            f"select {TASK_COLUMNS} from video_assistance_tasks where "
            f"request_id in ({quoted(sorted(request_ids))}) "
            f"or id in ({quoted(sorted(task_ids))})"
        )
    doc_ids: set[str] = set()
    for run in runs:
        doc_ids |= referenced_documents(run)
    documents = []
    if doc_ids:
        documents = source.rows(
            "select id, kind, body::jsonb->'text' as text, "
            "body::jsonb->'draft'->'publish_title' as publish_title, "
            "body::jsonb->'draft'->'publish_body' as publish_body, "
            "body::jsonb->'draft'->'title' as title, "
            "body::jsonb->'facts' as facts, body::jsonb->'audience' as audience, "
            "body::jsonb->'topic' as topic, "
            "body::jsonb->'audience_type' as audience_type "
            f"from video_writing_documents where id in ({quoted(sorted(doc_ids))})"
        )
    out: dict[str, Any] = {"runs": runs, "tasks": tasks, "documents": documents}
    if all_runs:
        # 库内全部写稿任务（含手动流程），方案第二节的 45% 用的是这个口径。
        out["all_write_tasks"] = source.rows(
            "select id, status, created_at, "
            "inputs::jsonb->>'draft_mode' as draft_mode, "
            "result::jsonb->'validation_error' as validation_error "
            "from video_assistance_tasks where kind = 'fact_draft'"
            + (f" and created_at >= '{since[:19]}'" if since else "")
        )
    return out


def lanes(run: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """(lane id, platform, lane state) — a single lane lives at the top."""
    result = run.get("result") or {}
    if result.get("lanes"):
        return [(f"{run['id']}:{k}", k, v) for k, v in result["lanes"].items()]
    platform = (run.get("inputs") or {}).get("platform") or "douyin"
    return [(run["id"], platform, result)]


def draft_keys(run: dict[str, Any]) -> list[str]:
    result = run.get("result") or {}
    keys = [d["key"] for d in result.get("drafts") or [] if d.get("key")]
    allocation = result.get("allocation") or {}
    two = len([p for p, n in allocation.items() if n]) > 1
    for platform, n in allocation.items():
        keys += [f"{platform}-v{i + 1}" if two else f"v{i + 1}" for i in range(int(n))]
    if not allocation:
        count = int((run.get("inputs") or {}).get("count") or 3)
        keys += [f"v{i + 1}" for i in range(count)]
    return list(dict.fromkeys(keys))


def expected_request_ids(run: dict[str, Any]) -> set[str]:
    result = run.get("result") or {}
    retries = range(int(result.get("retry") or 0) + 1)
    ids: set[str] = set()
    for lane_id, platform, lane in lanes(run):
        ids |= {rid(lane_id, "search"), rid(lane_id, "links")}
        ids |= {rid(lane_id, "compare", r) for r in retries}
        for bench in lane.get("benchmarks") or []:
            if bench.get("reference_id"):
                ids |= {
                    rid(lane_id, "analysis", bench["reference_id"], r) for r in retries
                }
        for platform_id in lane.get("tried") or []:
            ids.add(extraction_rid(run["project_id"], platform, platform_id))
        # W1 v2 searches several queries per lane: rid(lane, "search", n).
        for n in range(len((lane.get("screening") or {}).get("queries") or [])):
            ids.add(rid(lane_id, "search", n))
    for key in draft_keys(run):
        for r in retries:
            for attempt in range(3):
                ids.add(rid(run["id"], "draft", key, r, attempt))
    return ids


def referenced_task_ids(run: dict[str, Any]) -> set[str]:
    result = run.get("result") or {}
    ids = {d["task_id"] for d in result.get("drafts") or [] if d.get("task_id")}
    for _, _, lane in lanes(run):
        ids |= set((lane.get("screening") or {}).get("search_task_ids") or [])
        if lane.get("search_task_id"):
            ids.add(lane["search_task_id"])
        ids |= {
            b["extraction_id"]
            for b in lane.get("benchmarks") or []
            if b.get("extraction_id")
        }
    return {i for i in ids if ID.match(str(i))}


def referenced_documents(run: dict[str, Any]) -> set[str]:
    result = run.get("result") or {}
    ids = {d["document_id"] for d in result.get("drafts") or [] if d.get("document_id")}
    if result.get("facts_document_id"):
        ids.add(result["facts_document_id"])
    for _, _, lane in lanes(run):
        ids |= {
            b["analysis_id"]
            for b in lane.get("benchmarks") or []
            if b.get("analysis_id")
        }
    return {i for i in ids if ID.match(str(i))}


# --------------------------------------------------------------- metrics ---


def ts(value: str) -> datetime:
    text = str(value).replace(" ", "T")
    if re.search(r"[+-]\d\d$", text):
        text += ":00"
    return datetime.fromisoformat(text)


def calls_of(task: dict[str, Any]) -> int:
    attempts = (task.get("receipt") or {}).get("attempts")
    return len(attempts) if isinstance(attempts, list) and attempts else 1


def tokens_of(task: dict[str, Any]) -> tuple[int, int]:
    receipt = task.get("receipt") or {}
    usages = [a.get("usage") or {} for a in receipt.get("attempts") or []]
    if not usages and receipt.get("usage"):
        usages = [receipt["usage"]]
    return (
        sum(int(u.get("prompt_tokens") or 0) for u in usages),
        sum(int(u.get("completion_tokens") or 0) for u in usages),
    )


def spoken_chars(text: str) -> int:
    """口播字数：去掉换行和空白后的全部字符（与方案第二节口径一致）。"""
    return len(re.sub(r"\s", "", text or ""))


def grams(text: str, n: int = 3) -> set[str]:
    clean = re.sub(r"[^一-鿿A-Za-z0-9]", "", text or "")
    return {clean[i : i + n] for i in range(max(0, len(clean) - n + 1))}


def overlap(a: str, b: str, n: int = 2) -> float:
    """字符 n-gram 的 Jaccard 重合度（标题和首两句用 2-gram，全文用 3-gram）。"""
    ga, gb = grams(a, n), grams(b, n)
    if not ga or not gb:
        return 0.0
    return len(ga & gb) / len(ga | gb)


def hits(text: str, terms: list[str]) -> list[str]:
    return [t for t in terms if t and t in (text or "")]


def matches(text: str, patterns: list[str]) -> list[str]:
    return [m.group(0) for p in patterns for m in [re.search(p, text or "")] if m]


SAME_RULE = {"multi_brand_review": "multi_brand", "game": "game", "peer": "peer"}


def head(text: str, lines: int = 2) -> str:
    parts = [p for p in re.split(r"[\n。！？!?]", text or "") if p.strip()]
    return "".join(parts[:lines])


def unbacked_numbers(text: str, facts_text: str, allowed: list[str]) -> list[str]:
    found = re.findall(r"\d+(?:\.\d+)?", text or "")
    pool = (facts_text or "") + " ".join(allowed)
    return sorted({n for n in found if n not in pool})


def scenario_rules(scenario: dict[str, Any] | None, side: str) -> list[dict[str, Any]]:
    if not scenario:
        return []
    return list(((scenario.get("expect") or {}).get("must_not") or {}).get(side) or [])


def evaluate_run(
    run: dict[str, Any],
    tasks: list[dict[str, Any]],
    documents: dict[str, dict[str, Any]],
    scenario: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = run.get("result") or {}
    inputs = run.get("inputs") or {}
    brief = result.get("brief") or {}
    expect = (scenario or {}).get("expect") or {}
    audience = (
        brief.get("audience")
        or expect.get("audience")
        or ("peer" if inputs.get("goal") == "peer_share" else "consumer")
    )
    speaker = (
        brief.get("speaker")
        or expect.get("speaker")
        or inputs.get("speaker")
        or "merchant_self"
    )
    facts_text = inputs.get("facts_text") or ""
    if isinstance(inputs.get("facts"), dict):
        facts_text += " " + " ".join(str(v) for v in inputs["facts"].values() if v)
    allowed_numbers = list(expect.get("allowed_numbers") or [])
    wanted = expected_request_ids(run)
    mine = [
        t
        for t in tasks
        if t["request_id"] in wanted or t["id"] in referenced_task_ids(run)
    ]
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for task in {t["id"]: t for t in mine}.values():
        by_kind.setdefault(task["kind"], []).append(task)
    started = ts(run["created_at"])

    # ---- model calls ------------------------------------------------------
    funnel = result.get("funnel") or {}
    drafting = result.get("drafting") or {}
    calls: dict[str, int] = {}
    tokens_in = tokens_out = 0
    wasted_calls = wasted_in = wasted_out = 0
    for kind in ("fact_draft", "ref_analysis", "ref_compare"):
        for task in by_kind.get(kind, []):
            n = calls_of(task)
            p, c = tokens_of(task)
            calls[kind] = calls.get(kind, 0) + n
            tokens_in += p
            tokens_out += c
            if not ok(task):
                wasted_calls += n
                wasted_in += p
                wasted_out += c
    if drafting:  # W2 counts the writing stage itself (v2 runs)
        calls.pop("fact_draft", None)
        calls.pop("ref_compare", None)
        for key in (
            "write_calls",
            "fix_calls",
            "rewrite_calls",
            "review_calls",
            "compare_calls",
        ):
            calls[f"drafting.{key}"] = int(drafting.get(key) or 0)
    pick_calls = 0
    for _, _, lane in lanes(run):
        if (
            lane.get("ranked")
            and lane.get("mode") != "links"
            and not lane.get("screening")
        ):
            pick_calls += 1
    if funnel:
        calls["brief"] = int(funnel.get("brief_calls") or 0)
        calls["judge"] = int(funnel.get("judge_calls") or 0)
    else:
        calls["pick"] = pick_calls
        calls["facts"] = 1 if result.get("facts_document_id") else 0
    total_calls = sum(calls.values())
    if drafting:
        tokens_in += int(drafting.get("prompt_tokens") or 0)
        tokens_out += int(drafting.get("completion_tokens") or 0)
    tokens_in += int(funnel.get("prompt_tokens") or 0)
    tokens_out += int(funnel.get("completion_tokens") or 0)

    # ---- writing tasks ----------------------------------------------------
    writes = by_kind.get("fact_draft", [])
    failed = [t for t in writes if not ok(t)]
    reasons = Counter(issue_kind(t) for t in failed)
    compare_failed = sum(1 for t in by_kind.get("ref_compare", []) if not ok(t))

    # ---- searches / transcripts -------------------------------------------
    searches = by_kind.get("benchmark_search", [])
    extracts = by_kind.get("extract", [])
    new_extracts = [e for e in extracts if ts(e["created_at"]) >= started]
    extract_seconds = sorted(
        (ts(e["updated_at"]) - ts(e["created_at"])).total_seconds()
        for e in new_extracts
    )

    # ---- benchmarks -------------------------------------------------------
    items: dict[str, dict[str, Any]] = {}
    for search in searches:
        for item in (search.get("result") or {}).get("items") or []:
            items.setdefault(str(item.get("platform_id")), item)
    bench_rows = []
    bench_flags: dict[str, list[str]] = {}
    for _, platform, lane in lanes(run):
        for bench in lane.get("benchmarks") or []:
            if not bench.get("analysis_id") or bench.get("rejected"):
                continue
            item = items.get(str(bench.get("platform_id")), {})
            text = " ".join(
                str(item.get(k) or "") for k in ("title", "description", "author_name")
            )
            analysis = documents.get(bench["analysis_id"], {})
            who = str(((analysis.get("audience") or {}) or {}).get("who") or "")
            marks: list[str] = []
            if audience == "consumer" and (
                hits(text, PEER_BENCHMARK)
                or hits(who, PEER_AUDIENCE_WHO)
                or (bench.get("fit") or {}).get("audience_type") == "peer"
            ):
                marks.append("peer")
            if hits(text, GAME):
                marks.append("game")
            if hits(text, MULTI_BRAND):
                marks.append("multi_brand")
            if bench.get("no_speech_note") and bench.get("role") != "copy_ref":
                marks.append("no_speech_skeleton")
            for rule in scenario_rules(scenario, "benchmark"):
                name = SAME_RULE.get(rule["rule"], rule["rule"])
                if hits(text, rule["terms"]) and name not in marks:
                    marks.append(name)
            bench_flags[str(bench.get("reference_id"))] = marks
            bench_rows.append(
                {
                    "platform": platform,
                    "title": str(item.get("title") or "")[:40],
                    "author": item.get("author_name"),
                    "likes": item.get("like_count"),
                    "audience_who": who[:60],
                    "flags": marks,
                }
            )

    # ---- drafts -----------------------------------------------------------
    drafts = result.get("drafts") or []
    count_requested = int(
        brief.get("count_requested") or inputs.get("count") or len(drafts) or 0
    )
    delivered = [d for d in drafts if d.get("document_id")]
    duration = brief.get("duration") if brief else inputs.get("duration")
    band = (
        WORD_RANGE.get(int(duration))
        if isinstance(duration, int) and duration
        else None
    )
    draft_rows = []
    for draft in delivered:
        doc = documents.get(draft["document_id"], {})
        script = str(doc.get("text") or "")
        title = str(doc.get("publish_title") or doc.get("title") or "")
        body = str(doc.get("publish_body") or "")
        whole = "\n".join([title, body, script])
        flags: dict[str, list[str]] = {}
        if audience == "consumer" and (found := hits(whole, PEER_DRAFT)):
            flags["peer_teaching"] = found
        if speaker == "merchant_self" and (
            found := hits(script, VISITOR) + matches(script, VISITOR_PATTERNS)
        ):
            flags["visitor_narration"] = sorted(set(found))
        if found := hits(script, INVENTED):
            flags["invented_detail"] = [t for t in found if t not in facts_text]
        if found := unbacked_numbers(script, facts_text, allowed_numbers):
            flags["unbacked_number"] = found
        for rule in scenario_rules(scenario, "draft"):
            found = [
                t
                for t in hits(
                    whole if rule["rule"] != "visitor_narration" else script,
                    rule["terms"],
                )
                if t not in facts_text
            ]
            if found:
                flags.setdefault(rule["rule"], [])
                flags[rule["rule"]] = sorted(set(flags[rule["rule"]]) | set(found))
        flags = {k: v for k, v in flags.items() if v}
        quality = draft.get("quality") or {}
        chars = spoken_chars(script)
        draft_rows.append(
            {
                "key": draft.get("key"),
                "platform": draft.get("platform"),
                "label": (draft.get("angle") or {}).get("name") or draft.get("label"),
                "title": title,
                "head": head(script),
                "script": script,
                "chars": chars,
                "seconds": round(chars / CHARS_PER_SECOND),
                "in_band": (band[0] <= chars <= band[1]) if band else None,
                "flags": flags,
                "skeleton_flags": bench_flags.get(str(draft.get("reference_id")), []),
                "quality_invented": len(quality.get("invented") or []),
                "quality_speaker_ok": quality.get("speaker_ok"),
                "quality_audience_ok": quality.get("audience_ok"),
                "max_point_repeats": point_repeats(
                    script, documents.get(result.get("facts_document_id") or "", {})
                ),
            }
        )
    pairs = []
    for i, a in enumerate(draft_rows):
        for b in draft_rows[i + 1 :]:
            pairs.append(
                {
                    "a": a["key"],
                    "b": b["key"],
                    "title": round(overlap(a["title"], b["title"]), 2),
                    "head": round(overlap(a["head"], b["head"]), 2),
                    "script": round(overlap(a["script"], b["script"], 3), 2),
                }
            )
    seconds = (ts(run["updated_at"]) - started).total_seconds()
    return {
        "run_id": run["id"],
        "status": run["status"],
        "brief_v2": bool(brief),
        "query": inputs.get("query"),
        "platforms": inputs.get("platforms") or [inputs.get("platform")],
        "audience": audience,
        "speaker": speaker,
        "seconds": round(seconds),
        "model_calls": total_calls,
        "calls_by_step": calls,
        "tokens": {
            "prompt": tokens_in,
            "completion": tokens_out,
            "total": tokens_in + tokens_out,
        },
        "wasted": {
            "calls": wasted_calls,
            "prompt": wasted_in,
            "completion": wasted_out,
        },
        "write_tasks": len(writes),
        "write_tasks_failed": len(failed),
        "write_failure_reasons": dict(reasons),
        "compare_failed": compare_failed,
        "searches": len(searches),
        "candidates": sum(
            len((s.get("result") or {}).get("items") or []) for s in searches
        ),
        "screening": {
            k: v.get("screening") for _, k, v in lanes(run) if v.get("screening")
        },
        "transcripts_new": len(new_extracts),
        "transcripts_cached": len(extracts) - len(new_extracts),
        "transcript_seconds_avg": round(sum(extract_seconds) / len(extract_seconds))
        if extract_seconds
        else None,
        "count_requested": count_requested,
        "delivered": len(delivered),
        "benchmarks": bench_rows,
        "drafts": draft_rows,
        "similar_pairs": [
            p
            for p in pairs
            if p["title"] >= 0.45 or p["head"] >= 0.5 or p["script"] >= 0.3
        ],
        "max_title_overlap": max((p["title"] for p in pairs), default=0.0),
        "max_script_overlap": max((p["script"] for p in pairs), default=0.0),
        "distinct_heads": len({d["head"] for d in draft_rows}),
        "distinct_angles": len({d["label"] for d in draft_rows}),
        "band": list(band) if band else None,
    }


def issue_kind(task: dict[str, Any]) -> str:
    issue = (task.get("result") or {}).get("validation_issue")
    if isinstance(issue, dict) and issue.get("kind"):
        return str(issue["kind"])
    if isinstance(issue, str) and issue:
        return issue[:40]
    return str(task.get("error_code") or "unknown")


def ok(task: dict[str, Any]) -> bool:
    return task["status"] == "completed" and not (task.get("result") or {}).get(
        "validation_error"
    )


def point_repeats(script: str, facts_doc: dict[str, Any]) -> int:
    """How often the most repeated short fact (a selling point) is said."""
    values = [
        str(f.get("value") or "")
        for f in (facts_doc.get("facts") or [])
        if isinstance(f, dict) and 2 <= len(str(f.get("value") or "")) <= 12
    ]
    return max((script.count(v) for v in values), default=0)


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    writes = sum(r["write_tasks"] for r in rows)
    failed = sum(r["write_tasks_failed"] for r in rows)
    delivered = sum(r["delivered"] for r in rows)
    requested = sum(r["count_requested"] for r in rows)
    drafts = [d for r in rows for d in r["drafts"]]
    benches = [b for r in rows for b in r["benchmarks"]]
    in_band = [d["in_band"] for d in drafts if d["in_band"] is not None]
    write_calls = sum(
        r["calls_by_step"].get("fact_draft", 0)
        + sum(v for k, v in r["calls_by_step"].items() if k.startswith("drafting."))
        for r in rows
    )

    def count(flag: str) -> int:
        return sum(1 for d in drafts if flag in d["flags"])

    return {
        "runs": len(rows),
        "model_calls": sum(r["model_calls"] for r in rows),
        "write_tasks": writes,
        "write_tasks_failed": failed,
        "write_failure_rate": round(failed / writes, 4) if writes else None,
        "write_failure_reasons": dict(
            sum((Counter(r["write_failure_reasons"]) for r in rows), Counter())
        ),
        "requested": requested,
        "delivered": delivered,
        "delivery_rate": round(delivered / requested, 4) if requested else None,
        "write_calls_per_delivered": round(write_calls / delivered, 2)
        if delivered
        else None,
        "tokens_total": sum(r["tokens"]["total"] for r in rows),
        "wasted_token_share": round(
            sum(r["wasted"]["prompt"] + r["wasted"]["completion"] for r in rows)
            / max(1, sum(r["tokens"]["total"] for r in rows)),
            4,
        ),
        "seconds_max": max((r["seconds"] for r in rows), default=0),
        "benchmarks_selected": len(benches),
        "benchmarks_peer": sum(1 for b in benches if "peer" in b["flags"]),
        "benchmarks_game": sum(1 for b in benches if "game" in b["flags"]),
        "benchmarks_multi_brand": sum(
            1 for b in benches if "multi_brand" in b["flags"]
        ),
        "benchmarks_no_speech_skeleton": sum(
            1 for b in benches if "no_speech_skeleton" in b["flags"]
        ),
        "drafts_peer_teaching": count("peer_teaching"),
        "drafts_visitor_narration": count("visitor_narration"),
        "drafts_invented_detail": count("invented_detail"),
        "drafts_unbacked_number": count("unbacked_number"),
        "drafts_quality_invented": sum(1 for d in drafts if d["quality_invented"]),
        "drafts_from_flagged_benchmark": sum(1 for d in drafts if d["skeleton_flags"]),
        "drafts_clean": sum(1 for d in drafts if not d["flags"]),
        "drafts_clean_and_good_skeleton": sum(
            1 for d in drafts if not d["flags"] and not d["skeleton_flags"]
        ),
        "in_band_rate": round(sum(in_band) / len(in_band), 4) if in_band else None,
        "chars_range": [
            min((d["chars"] for d in drafts), default=0),
            max((d["chars"] for d in drafts), default=0),
        ],
        "similar_pairs": sum(len(r["similar_pairs"]) for r in rows),
        "max_title_overlap": max((r["max_title_overlap"] for r in rows), default=0.0),
        "max_script_overlap": max((r["max_script_overlap"] for r in rows), default=0.0),
    }


def merge(files: list[str]) -> dict[str, Any]:
    parts = [json.loads(Path(f).read_text()) for f in files]
    rows = [r for part in parts for r in part["runs"]]
    out: dict[str, Any] = {"runs": rows, "summary": summarise(rows)}
    db = [part["db_write_tasks"] for part in parts if part.get("db_write_tasks")]
    if db:
        tasks = sum(d["tasks"] for d in db)
        failed = sum(d["failed"] for d in db)
        out["db_write_tasks"] = {
            "tasks": tasks,
            "failed": failed,
            "failure_rate": round(failed / tasks, 4) if tasks else None,
            "parts": db,
        }
    return out


def load_scenario(value: str) -> dict[str, Any]:
    path = Path(value)
    if not path.exists():
        matches = sorted(REGRESSION.glob(f"*{value}*.json"))
        if len(matches) != 1:
            raise SystemExit(f"找不到唯一的回归场景：{value}")
        path = matches[0]
    return json.loads(path.read_text(encoding="utf-8"))


def evaluate(data: dict[str, Any], scenarios: list[dict[str, Any]]) -> dict[str, Any]:
    documents = {d["id"]: d for d in data["documents"]}
    rows = []
    for i, run in enumerate(data["runs"]):
        scenario = (
            scenarios[i]
            if i < len(scenarios)
            else (scenarios[-1] if len(scenarios) == 1 else None)
        )
        rows.append(evaluate_run(run, data["tasks"], documents, scenario))
    out = {"runs": rows, "summary": summarise(rows)}
    if "all_write_tasks" in data:
        out["db_write_tasks"] = db_write_stats(data["all_write_tasks"])
    return out


def db_write_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [
        r for r in rows if r["status"] != "completed" or r.get("validation_error")
    ]
    modes = Counter(str(r.get("draft_mode") or "structure") for r in rows)
    return {
        "tasks": len(rows),
        "failed": len(failed),
        "failure_rate": round(len(failed) / len(rows), 4) if rows else None,
        "by_mode": dict(modes),
    }


def report(out: dict[str, Any]) -> str:
    lines = []
    for r in out["runs"]:
        flow = "brief v2" if r["brief_v2"] else "旧流程"
        platforms = "/".join(map(str, r["platforms"]))
        tok, waste = r["tokens"], r["wasted"]
        lines += [
            f"run {r['run_id']}  {r['status']}  {flow}  "
            f"query={r['query']!r}  {platforms}",
            f"  耗时 {r['seconds']}s · 模型调用 {r['model_calls']} {r['calls_by_step']}"
            f" · token {tok['prompt']}+{tok['completion']}"
            f" · 零产出 {waste['calls']} 次 / "
            f"{waste['prompt'] + waste['completion']} token",
            f"  写稿任务 {r['write_tasks']} 失败 {r['write_tasks_failed']} "
            f"{r['write_failure_reasons']} · 对比失败 {r['compare_failed']}"
            f" · 搜索 {r['searches']}（候选 {r['candidates']}）"
            f" · 转写 新 {r['transcripts_new']} 缓存 {r['transcripts_cached']}",
            f"  交付 {r['delivered']}/{r['count_requested']}"
            f" · 不同角度 {r['distinct_angles']} · 不同首句 {r['distinct_heads']}",
        ]
        for b in r["benchmarks"]:
            lines.append(
                f"  对标[{b['platform']}] {b['title']} · {b['author']}"
                f" · {b['likes']} 赞 · {','.join(b['flags']) or '—'}"
            )
        for d in r["drafts"]:
            marks = "; ".join(f"{k}:{'/'.join(v[:4])}" for k, v in d["flags"].items())
            lines.append(
                f"  稿 {d['key']} {d['chars']} 字≈{d['seconds']}s"
                f" 卖点重复 {d['max_point_repeats']} · {d['title'][:24]}"
                f" · {marks or '—'} · 骨架 {','.join(d['skeleton_flags']) or '—'}"
            )
        for p in r["similar_pairs"]:
            lines.append(
                f"  相似 {p['a']}~{p['b']} 标题 {p['title']}"
                f" 首句 {p['head']} 全文 {p['script']}"
            )
    lines.append("汇总 " + json.dumps(out["summary"], ensure_ascii=False))
    if out.get("db_write_tasks"):
        db = json.dumps(out["db_write_tasks"], ensure_ascii=False)
        lines.append("库内全部写稿任务（含手动流程） " + db)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run_ids", nargs="*")
    parser.add_argument("--psql", default="")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--since", default="")
    parser.add_argument("--scenario", action="append", default=[])
    parser.add_argument("--dump")
    parser.add_argument("--from-dump")
    parser.add_argument("--merge", nargs="+")
    parser.add_argument("--json")
    args = parser.parse_args(argv)
    if args.merge:
        out = merge(args.merge)
    else:
        if args.from_dump:
            data = json.loads(Path(args.from_dump).read_text())
        else:
            if not args.psql or not (args.run_ids or args.all):
                parser.error("需要 --psql 和 run id（或 --all）")
            data = fetch(Psql(args.psql), args.run_ids, args.all, args.since)
            if args.dump:
                Path(args.dump).write_text(
                    json.dumps(data, ensure_ascii=False, default=str)
                )
        out = evaluate(data, [load_scenario(s) for s in args.scenario])
    if args.json:
        Path(args.json).write_text(
            json.dumps(out, ensure_ascii=False, indent=1, default=str)
        )
    print(report(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
