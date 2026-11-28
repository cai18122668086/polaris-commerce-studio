"""第三轮自动写稿（run 带 ``brief`` 时）：按角度写 → 批量质检 → 句子级修 → 去重。

Called from ``video_auto_writing.step_write`` when ``state["brief"]`` exists;
without a brief nothing here runs and the old flow is unchanged.

Per draft at most three model calls: write (1) + a targeted fix (the task's
corrective retry for a hard rule, or the sentence-level repair after review)
+ one rewrite on a different skeleton. The semantic review is one call for
the whole run (plus one recheck of what was changed).
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select

from . import video_brief_writing as bw
from .errors import ApiError
from .video_assistance_models import VideoAssistanceRecord
from .video_planner_policy import json_planning_options
from .video_writing_contracts import WritingFacts
from .video_writing_rules import (
    RECHECK_RULES,
    REPAIR_RULES,
    REVIEW_RULES,
    SKELETON_RULES,
    generic_skeleton,
)

if TYPE_CHECKING:
    from .video_auto_writing import Lane, Run

MAX_CALLS = 3
TITLE_MAX = 30

ISSUE_TEXT = {
    "numeric": "用了你没写过的数字",
    "visitor_voice": "写成了顾客到店的口吻",
    "peer_talk": "写成了对同行说的话",
    "unbacked": "用了没有依据的说法",
    "benchmark_brand": "带上了别人视频里的品牌或店名",
    "length": "长度没控制在所选时长里",
    "repetition": "同一个卖点重复太多",
    "forbidden": "用了你设的禁用词",
    "restricted": "写了你不让写的内容",
    "placeholder": "留了没填的空位",
}


def has_brief(state: dict[str, Any]) -> bool:
    return bool(state.get("brief"))


# ------------------------------------------------------------- helpers ----


class Stats:
    """写稿阶段的调用与 token（W1 并入 funnel）。"""

    def __init__(self, before: dict[str, Any] | None = None) -> None:
        keys = (
            "write_calls",
            "fix_calls",
            "rewrite_calls",
            "review_calls",
            "compare_calls",
            "prompt_tokens",
            "completion_tokens",
        )
        self.values = {k: int((before or {}).get(k) or 0) for k in keys}

    def add(self, kind: str, usage: Any = None, calls: int = 1) -> None:
        self.values[kind] += calls
        if isinstance(usage, dict):
            self.values["prompt_tokens"] += int(usage.get("prompt_tokens") or 0)
            self.values["completion_tokens"] += int(usage.get("completion_tokens") or 0)


def call_json(
    run: Run, rules: list[str], payload: dict[str, Any], max_tokens: int
) -> tuple[Any, dict[str, Any] | None]:
    """One of this module's own small calls; returns the JSON and the usage."""
    settings = run.app.state.settings
    data = run.service.request(
        "planner",
        "POST",
        "/v1/chat/completions",
        json={
            "model": settings.video_script_model,
            **json_planning_options(settings.video_script_model),
            "stream": False,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": "\n".join(rules)},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        },
    )
    usage = data.get("usage") if isinstance(data, dict) else None
    try:
        return bw.parse_json(data["choices"][0]["message"]["content"]), usage
    except (KeyError, IndexError, TypeError, ValueError):
        return None, usage


def ready_benchmarks(lane: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Benchmarks a draft may borrow structure from (W1: not rejected, skeleton)."""
    if not lane or lane.get("generic_skeleton"):
        return []
    return [
        b
        for b in lane.get("benchmarks") or []
        if b.get("analysis_id")
        and not b.get("rejected")
        and (b.get("role") or "skeleton") == "skeleton"
    ]


def documents(run: Run, ids: list[str]) -> dict[str, dict[str, Any]]:
    from .video_writing_routes import own_document

    with run.factory() as session:
        return {
            i: own_document(session, run.workspace, i).body for i in dict.fromkeys(ids)
        }


# ----------------------------------------------------------- skeletons ----


def benchmark_skeletons(run: Run, lane: dict[str, Any]) -> list[dict[str, Any]]:
    """每条合格对标的骨架（钩子 + 段落功能），给写稿的那一层。"""
    ready = ready_benchmarks(lane)
    if not ready:
        return []
    bodies = documents(
        run, [b["analysis_id"] for b in ready] + [b["reference_id"] for b in ready]
    )
    rows: list[dict[str, Any]] = []
    for bench in ready:
        metrics = bodies[bench["reference_id"]].get("source_metrics") or {}
        name = str(metrics.get("title") or "爆款参考")
        skeleton = bw.skeleton_from_analysis(bodies[bench["analysis_id"]], name)
        rows.append(
            {
                **skeleton,
                "id": f"b{len(rows) + 1}",
                "kind": "benchmark",
                "name": name[:TITLE_MAX],
                "genre": (bench.get("fit") or {}).get("genre") or "",
                "reference_id": bench["reference_id"],
                "analysis_id": bench["analysis_id"],
            }
        )
    return rows


def compare_lane(run: Run, lane: Lane, stats: Stats) -> None:
    """ref_compare 改为提炼 2–3 个骨架；模型只用「对标N」，后端映射回 id。"""
    state = lane.state()
    if state.get("skeletons_done"):
        return
    ready = ready_benchmarks(state)
    if len(ready) < 2:
        lane.save(skeletons=[], skeletons_done=True)
        return
    bodies = documents(run, [b["analysis_id"] for b in ready])
    labels = {f"对标{i + 1}": b["reference_id"] for i, b in enumerate(ready)}
    payload = {
        "benchmarks": [
            {
                "label": label,
                **bw.skeleton_from_analysis(bodies[b["analysis_id"]]),
                "topic": str(bodies[b["analysis_id"]].get("topic") or "")[:80],
            }
            for (label, _), b in zip(labels.items(), ready, strict=True)
        ],
        "hook_types": sorted(bw.HOOKS),
    }
    try:
        answer, usage = call_json(run, SKELETON_RULES, payload, 1500)
    except ApiError:
        answer, usage = None, None
    stats.add("compare_calls", usage)
    skeletons = bw.map_skeletons(answer, labels)
    lane.save(
        skeletons=skeletons,
        skeletons_done=True,
        skeleton_note="" if skeletons else "共性没提炼出来，按单条对标的结构写",
    )


def lane_skeletons(run: Run, lane: dict[str, Any]) -> list[dict[str, Any]]:
    """这个平台能用的骨架：提炼出的共性骨架优先，否则每条对标一个，都没有就是空。"""
    singles = benchmark_skeletons(run, lane)
    by_ref = {s["reference_id"]: s for s in singles}
    merged = []
    for row in lane.get("skeletons") or []:
        source = next((by_ref[r] for r in row.get("refs") or [] if r in by_ref), None)
        if source is None:
            continue
        merged.append(
            {
                **row,
                "kind": "benchmark",
                "name": source["name"],
                "skeleton_name": row.get("name") or "",
                "genre": source.get("genre") or "",
                "reference_id": source["reference_id"],
                "analysis_id": source["analysis_id"],
            }
        )
    return merged or singles


def generic(angle: dict[str, Any], skip: set[str]) -> dict[str, Any]:
    row = generic_skeleton(str(angle.get("genre") or ""), skip)
    return {**row, "kind": "generic"}


# ---------------------------------------------------------------- plan ----


def angles_for(
    brief: dict[str, Any], platform: str, count: int, first: bool
) -> list[dict[str, Any]]:
    """W1 已按 allocation 给每个角度分了平台；没分的按顺序补给第一个平台。"""
    angles = [
        a for a in brief.get("angles") or [] if isinstance(a, dict) and a.get("name")
    ]
    mine = [a for a in angles if a.get("platform") == platform]
    if not any(a.get("platform") for a in angles) and first:
        mine = angles
    return mine[:count]


def brief_plan(
    run: Run, inputs: dict[str, Any], state: dict[str, Any]
) -> list[dict[str, Any]]:
    from .video_auto_writing import lane_state, planned

    brief = state["brief"]
    split = planned(inputs)
    two = len(split) > 1
    words = brief.get("word_range") or bw.word_range(brief.get("duration"))
    plan: list[dict[str, Any]] = []
    for index, (platform, count) in enumerate(split.items()):
        lane = lane_state(state, platform)
        if lane is None and two:
            continue  # this platform's search failed; the lane says why
        skeletons = lane_skeletons(run, lane or {})
        used: set[str] = set()
        for i, angle in enumerate(angles_for(brief, platform, count, index == 0)):
            if skeletons:
                matching = [
                    s
                    for s in skeletons
                    if s.get("genre") and s["genre"] == angle.get("genre")
                ]
                skeleton = (matching or skeletons)[i % len(matching or skeletons)]
            else:
                skeleton = generic(angle, used)
                used.add(skeleton["id"])
            plan.append(
                {
                    "key": f"{platform}-v{i + 1}" if two else f"v{i + 1}",
                    "platform": platform,
                    "angle": {
                        k: angle.get(k)
                        for k in ("id", "name", "genre", "hook", "focus")
                        if angle.get(k) is not None
                    },
                    "skeleton": skeleton,
                    "alternatives": [s for s in skeletons if s is not skeleton],
                    "words": list(words) if words else None,
                    "duration": brief.get("duration", 45),
                }
            )
    return plan


def basis_of(
    brief: dict[str, Any], version: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    return {
        "brief": {
            k: brief.get(k)
            for k in (
                "summary",
                "speaker",
                "audience",
                "goal",
                "category",
                "locality",
                "audience_note",
                "cta",
            )
            if brief.get(k) is not None
        },
        "angle": version["angle"],
        "skeleton": {
            k: version["skeleton"].get(k)
            for k in (
                "id",
                "kind",
                "name",
                "hook",
                "hook_note",
                "sections",
                "expressions",
            )
        },
        "words": version["words"],
        "platform": version["platform"],
        **{k: v for k, v in extra.items() if v},
    }


# ----------------------------------------------------------------- tasks ----


def draft_task(
    run: Run,
    inputs: dict[str, Any],
    state: dict[str, Any],
    version: dict[str, Any],
    skeleton: dict[str, Any],
    attempt: int,
    basis: dict[str, Any],
) -> VideoAssistanceRecord:
    """A fact_draft task in brief mode, queued and processed inline.

    Same record, credit hold and processing as the public writing task, so
    idempotency, receipts and billing stay identical; only the inputs differ.
    """
    from . import video_credit_billing as video_credits
    from .video_assistance import process
    from .video_auto_writing import rid
    from .video_studio_routes import digest
    from .video_writing_routes import own_document

    request_id = str(
        rid(run.id, "brief", version["key"], state.get("retry", 0), attempt)
    )
    workspace = run.workspace
    with run.factory() as session:
        existing = session.scalar(
            select(VideoAssistanceRecord).where(
                VideoAssistanceRecord.workspace_id == workspace.workspace_id,
                VideoAssistanceRecord.owner_user_id == workspace.principal.user_id,
                VideoAssistanceRecord.request_id == request_id,
            )
        )
        if existing is None:
            facts = own_document(
                session, workspace, state["facts_document_id"], "facts"
            )
            parents = [facts]
            task_id = str(uuid4())
            task_inputs: dict[str, Any] = {
                "revision": run.revision(inputs["project_id"]),
                "target_duration_seconds": None,
                "presentation": "unspecified",
                "facts_document_id": facts.id,
                "facts": facts.body,
                "draft_mode": "brief",
                "variant": 0,
                "publish_platform": version["platform"],
                "brief_basis": basis,
                "writing_task_id": task_id,
            }
            if skeleton.get("reference_id"):
                ref = own_document(
                    session, workspace, skeleton["reference_id"], "reference"
                )
                ana = own_document(
                    session, workspace, skeleton["analysis_id"], "analysis"
                )
                parents += [ref, ana]
                task_inputs.update(
                    reference_document_id=ref.id,
                    reference=ref.body,
                    analysis_document_id=ana.id,
                    analysis=ana.body,
                )
            task_inputs["document_hashes"] = {p.id: p.body_sha256 for p in parents}
            row = VideoAssistanceRecord(
                id=task_id,
                workspace_id=workspace.workspace_id,
                owner_user_id=workspace.principal.user_id,
                project_id=inputs["project_id"],
                request_id=request_id,
                request_hash=digest(
                    {"workflow": "writing-brief", "request_id": request_id}
                ),
                kind="fact_draft",
                inputs=task_inputs,
            )
            session.add(row)
            video_credits.hold(
                session,
                run.app.state.settings,
                workspace.workspace_id,
                "writing_generate",
                "video_assistance",
                row.id,
            )
            session.commit()
        else:
            task_id = existing.id
    process(run.factory, task_id, run.service)
    video_credits.settle_after(run.factory, "video_assistance", task_id)
    return run.task(task_id)


def task_calls(task: VideoAssistanceRecord) -> tuple[int, list[Any]]:
    attempts = (task.receipt or {}).get("attempts") or []
    return max(1, len(attempts)), [a.get("usage") for a in attempts]


def stored_draft(run: Run, task: VideoAssistanceRecord) -> str | None:
    from .video_writing_contracts import SaveWritingResult
    from .video_writing_routes import store_result

    if task.status != "completed" or (task.result or {}).get("validation_error"):
        return None
    saved = run.plain(
        store_result, SaveWritingResult(request_id=UUID(task.id), task_id=UUID(task.id))
    )
    return str(saved["id"])


# ------------------------------------------------------------ one draft ----


class Work:
    """One planned draft while it goes through write → review → repair."""

    def __init__(self, version: dict[str, Any], before: dict[str, Any] | None) -> None:
        self.version = version
        self.skeleton = version["skeleton"]
        self.calls = 0
        self.doc: str | None = None
        self.lines: list[str] = []
        self.publish_title = ""
        self.notes: dict[str, list[str]] = {"unused": [], "removed": [], "suggest": []}
        self.quality: dict[str, Any] | None = None
        self.dropped: tuple[str, str] | None = None
        self.dropped_doc: str | None = None
        self.task_id: str | None = None
        self.error: Any = None
        self.recheck: list[int] | None = None  # lines to recheck after a change
        self.passed = False
        if before and before.get("document_id"):
            self.doc = before["document_id"]
            self.calls = int(before.get("attempts") or 1)
            self.task_id = before.get("task_id")
            self.quality = before.get("quality")
            self.notes = before.get("notes") or self.notes
            self.passed = bool(self.quality and self.quality.get("checked"))

    def load(self, body: dict[str, Any]) -> None:
        self.lines = [
            s["text"] for s in (body.get("draft") or {}).get("sentences") or []
        ]
        self.publish_title = (body.get("draft") or {}).get("publish_title") or ""

    def view(self) -> dict[str, Any]:
        return {
            "key": self.version["key"],
            "platform": self.version["platform"],
            "angle": self.version["angle"],
            "publish_title": self.publish_title,
            "lines": self.lines,
        }

    def drop(self, reason: str, message: str) -> None:
        self.dropped = (reason, message)
        if reason in {"duplicate", "quality"}:
            self.dropped_doc = self.doc
        self.doc = None

    def entry(self) -> dict[str, Any]:
        text = "".join(self.lines) if (self.doc or self.dropped_doc) else ""
        chars = bw.spoken_chars(text) if text else None
        skeleton = self.skeleton
        row: dict[str, Any] = {
            "key": self.version["key"],
            "label": self.version["angle"].get("name") or "",
            "platform": self.version["platform"],
            "mode": "brief",
            "reference_id": skeleton.get("reference_id"),
            "task_id": self.task_id,
            "document_id": self.doc,
            "angle": self.version["angle"],
            "skeleton": {
                "kind": skeleton.get("kind") or "generic",
                **(
                    {"reference_id": skeleton["reference_id"]}
                    if skeleton.get("reference_id")
                    else {}
                ),
                "name": str(skeleton.get("name") or "")[:TITLE_MAX],
            },
            "duration": self.version.get("duration", 45),
            "chars": chars,
            "seconds": bw.spoken_seconds(chars) if chars else None,
            "quality": self.quality,
            "attempts": self.calls,
            "notes": self.notes,
            "dropped_reason": self.dropped[0] if self.dropped else None,
            "dropped_message": self.dropped[1] if self.dropped else None,
        }
        if self.dropped_doc:
            row["dropped_document_id"] = self.dropped_doc
        if self.error and not self.doc:
            row["error"] = self.error
        return row


def write(
    run: Run,
    inputs: dict[str, Any],
    state: dict[str, Any],
    work: Work,
    stats: Stats,
    *,
    rewrite: bool = False,
    avoid: list[str] | None = None,
    note: str = "",
) -> bool:
    """Write (or rewrite on another skeleton); True when a draft was saved."""
    if rewrite:
        alternatives = [
            s for s in work.version.get("alternatives") or [] if s is not work.skeleton
        ]
        work.skeleton = (
            alternatives[0]
            if alternatives
            else generic(work.version["angle"], {str(work.skeleton.get("id"))})
        )
    budget = MAX_CALLS - work.calls
    if budget <= 0:
        return False
    basis = basis_of(
        state["brief"],
        {**work.version, "skeleton": work.skeleton},
        single_attempt=rewrite or budget < 2,
        avoid=avoid,
        note=note,
    )
    task = draft_task(
        run, inputs, state, work.version, work.skeleton, work.calls, basis
    )
    calls, usages = task_calls(task)
    work.calls += calls
    for i, usage in enumerate(usages or [None]):
        stats.add(
            "rewrite_calls" if rewrite else "write_calls" if i == 0 else "fix_calls",
            usage,
        )
    work.task_id = task.id
    doc = stored_draft(run, task)
    if doc is None:
        issue = (task.result or {}).get("validation_issue") or {}
        work.error = issue or task.error_code
        return False
    work.doc = doc
    work.error = None
    work.passed = False
    work.quality = None
    work.notes = (task.result or {}).get("notes") or work.notes
    body = documents(run, [doc])[doc]
    work.load(body)
    return True


def failed_message(work: Work) -> tuple[str, str]:
    issue = work.error if isinstance(work.error, dict) else {}
    kind = str(issue.get("kind") or "")
    if kind == "length":
        try:
            short = int(issue.get("text") or 0) < int(
                (work.version.get("words") or [0])[0]
            )
        except (TypeError, ValueError):
            short = False
        if short:
            return (
                "insufficient_facts",
                "信息太少，撑不起这个角度，没写成。补充一些真实信息后可以再写。",
            )
    reason = ISSUE_TEXT.get(kind, "没通过检查")
    return "failed", f"这条没写成：{reason}，重写一次仍不过。"


# -------------------------------------------------------------- review ----


def review(
    run: Run, state: dict[str, Any], works: list[Work], stats: Stats
) -> dict[str, dict[str, Any]]:
    """一次批量语义质检：所有待审的稿一起送审。"""
    if not works:
        return {}
    brief = state["brief"]
    facts = documents(run, [state["facts_document_id"]])[state["facts_document_id"]]
    payload = {
        "brief": bw.brief_for_review(brief),
        "facts": [
            f.get("value")
            for f in facts.get("facts") or []
            if f.get("status") == "user_declared"
        ],
        "drafts": [bw.review_item(w.version["key"], w.view()) for w in works],
    }
    try:
        answer, usage = call_json(run, REVIEW_RULES, payload, 600 + 350 * len(works))
    except ApiError:
        answer, usage = None, None
    stats.add("review_calls", usage)
    verdicts = bw.parse_reviews(answer, {w.version["key"]: w.lines for w in works})
    card = WritingFacts.model_validate(facts)
    return {
        key: bw.with_code_checks(
            verdict,
            next(w.lines for w in works if w.version["key"] == key),
            card,
            brief,
        )
        for key, verdict in verdicts.items()
    }


def recheck(
    run: Run, state: dict[str, Any], works: list[Work], stats: Stats
) -> dict[str, bool]:
    """只复查被改过的句子（重写的稿整条复查）。"""
    if not works:
        return {}
    brief = state["brief"]
    facts = documents(run, [state["facts_document_id"]])[state["facts_document_id"]]
    payload = {
        "brief": bw.brief_for_review(brief),
        "facts": [
            f.get("value")
            for f in facts.get("facts") or []
            if f.get("status") == "user_declared"
        ],
        "drafts": [
            {
                "key": w.version["key"],
                "lines": [{"line": i, "text": t} for i, t in enumerate(w.lines)],
                "check_lines": [
                    {"line": i, "text": w.lines[i]}
                    for i in (
                        w.recheck if w.recheck is not None else range(len(w.lines))
                    )
                    if i < len(w.lines)
                ],
            }
            for w in works
        ],
    }
    try:
        answer, usage = call_json(run, RECHECK_RULES, payload, 400 + 150 * len(works))
    except ApiError:
        answer, usage = None, None
    stats.add("review_calls", usage)
    rows = answer.get("reviews") if isinstance(answer, dict) else None
    verdict: dict[str, bool] = {}
    for raw in rows if isinstance(rows, list) else []:
        if isinstance(raw, dict) and raw.get("key"):
            verdict[str(raw["key"])] = raw.get("ok") is not False and not raw.get("bad")
    return verdict


def quality_of(verdict: dict[str, Any] | None) -> dict[str, Any]:
    if verdict is None:
        return {
            "checked": False,
            "speaker_ok": True,
            "audience_ok": True,
            "invented": [],
            "repetition": 0,
        }
    return {
        "checked": True,
        "speaker_ok": verdict["speaker_ok"],
        "audience_ok": verdict["audience_ok"],
        "on_goal": verdict["on_goal"],
        "readable": verdict["readable"],
        "invented": [row["text"] for row in verdict["invented"]],
        "repetition": verdict["repetition"],
    }


def quality_message(verdict: dict[str, Any]) -> str:
    if not verdict["speaker_ok"]:
        return "这条的说话口吻和你选的不一致，改了一次仍不对，没有保留。"
    if not verdict["audience_ok"]:
        return "这条像是说给同行听的，改了一次仍不对，没有保留。"
    if verdict["invented"]:
        return "这条提到了你没写过的内容，改了一次仍不过，没有保留。"
    return "这条读起来不够顺，改了一次仍不过，没有保留。"


def repair(
    run: Run, state: dict[str, Any], work: Work, marked: dict[int, str], stats: Stats
) -> bool:
    """句子级修复：只改被点名的句子；改完的稿走同一套硬规则另存一版。"""
    from .video_auto_writing import rid
    from .video_writing_contracts import ReviseWritingDraft
    from .video_writing_routes import revise_draft

    if work.calls >= MAX_CALLS or not work.doc:
        return False
    brief = state["brief"]
    facts = documents(run, [state["facts_document_id"]])[state["facts_document_id"]]
    payload = {
        "brief": bw.brief_for_review(brief),
        "facts": [
            {"label": f.get("label"), "value": f.get("value")}
            for f in facts.get("facts") or []
            if f.get("status") == "user_declared"
        ],
        "lines": [{"line": i, "text": t} for i, t in enumerate(work.lines)],
        "fix": [{"line": i, "reason": r} for i, r in sorted(marked.items())],
    }
    try:
        answer, usage = call_json(run, REPAIR_RULES, payload, 1200)
    except ApiError:
        answer, usage = None, None
    work.calls += 1
    stats.add("fix_calls", usage)
    lines, touched = bw.apply_fixes(work.lines, answer, set(marked))
    if not lines or lines == work.lines:
        return False
    body = documents(run, [work.doc])[work.doc]
    draft = body.get("draft") or {}
    try:
        revised = run.plain(
            revise_draft,
            UUID(work.doc),
            ReviseWritingDraft(
                request_id=rid(
                    run.id, "repair", work.version["key"], state.get("retry", 0)
                ),
                title=draft.get("title")
                or work.version["angle"].get("name")
                or "爆款文案",
                sentences=[{"text": line, "fact_ids": []} for line in lines],  # type: ignore[misc]
            ),
        )
    except ApiError:
        return False
    work.doc = str(revised["id"])
    work.load(revised["body"])
    work.recheck = touched
    removed = "去掉或改写了几句你没写过的内容"
    if removed not in work.notes.get("removed", []):
        work.notes = {
            **work.notes,
            "removed": [*work.notes.get("removed", []), removed],
        }
    return True


def dedupe(works: list[Work]) -> list[tuple[Work, Work]]:
    """两两比较标题和开头；返回 (要处理的那条, 保留的那条)。先到先留。"""
    pairs = []
    kept: list[Work] = []
    for work in works:
        twin = next((k for k in kept if bw.too_similar(k.view(), work.view())), None)
        if twin is None:
            kept.append(work)
        else:
            pairs.append((work, twin))
    return pairs


# ----------------------------------------------------------------- step ----


def step_write_brief(run: Run, inputs: dict[str, Any], state: dict[str, Any]) -> None:
    from .video_auto_writing import STAGES, Stop, lanes_of

    started = time.monotonic()
    stats = Stats(state.get("drafting"))
    lanes = lanes_of(run, inputs)
    with ThreadPoolExecutor(max_workers=max(1, len(lanes))) as pool:
        list(pool.map(lambda lane: compare_lane(run, lane, stats), lanes))
    state = run.row().result
    plan = brief_plan(run, inputs, state)
    before = {d["key"]: d for d in state.get("drafts") or []}
    works = [Work(v, before.get(v["key"])) for v in plan]
    width = 3 * max(1, len(lanes))

    def first(work: Work) -> None:
        if work.doc:
            work.load(documents(run, [work.doc])[work.doc])
            return
        if not write(run, inputs, state, work, stats) and not write(
            run, inputs, state, work, stats, rewrite=True
        ):
            work.drop(*failed_message(work))

    with ThreadPoolExecutor(max_workers=width) as pool:
        list(pool.map(first, works))

    def checkpoint() -> None:
        run.save(drafts=[w.entry() for w in works], drafting=stats.values)

    checkpoint()
    if "check" in STAGES:
        run.save(stage="check")
    # Review everything written and not yet reviewed, in one call.
    pending = [w for w in works if w.doc and not w.passed]
    verdicts = review(run, state, pending, stats)
    fixes: list[tuple[Work, dict[int, str]]] = []
    rewrites: list[tuple[Work, str]] = []
    for work in pending:
        verdict = verdicts.get(work.version["key"])
        work.quality = quality_of(verdict)
        if verdict is None or bw.verdict_passes(verdict):
            work.passed = True
            continue
        marked = bw.flagged_lines(verdict)
        if work.calls >= MAX_CALLS:
            work.drop("quality", quality_message(verdict))
        elif marked and len(marked) <= max(3, len(work.lines) // 2):
            fixes.append((work, marked))
        else:
            rewrites.append((work, quality_message(verdict)))
    # Near-duplicates among what is still in: the later one is rewritten once.
    alive = [w for w in works if w.doc and all(w is not x for x, _ in rewrites)]
    for work, twin in dedupe(alive):
        if any(work is x for x, _ in fixes):
            fixes = [(x, m) for x, m in fixes if x is not work]
        if work.calls >= MAX_CALLS:
            work.drop(
                "duplicate",
                f"和「{twin.version['angle'].get('name')}」太像，没有保留。",
            )
        else:
            rewrites.append((work, "duplicate"))

    def second(job: tuple[str, Work, Any]) -> None:
        kind, work, extra = job
        if kind == "fix":
            if not repair(run, state, work, extra, stats) and work.doc:
                work.drop(
                    "quality",
                    "这条提到了你没写过的内容，改了一次仍不过，没有保留。",
                )
            return
        avoid = [
            text
            for other in works
            if other is not work and other.doc
            for text in (other.publish_title, other.lines[0] if other.lines else "")
            if text
        ]
        previous = work.doc
        note = (
            "上一版和同批另一条太像，换一个明显不同的开头和讲法"
            if extra == "duplicate"
            else "上一版的问题：" + str(extra)
        )
        if write(run, inputs, state, work, stats, rewrite=True, avoid=avoid, note=note):
            work.recheck = None
            return
        work.doc = previous
        if extra == "duplicate":
            work.drop("duplicate", "和同批另一条太像，重写一次仍不过，没有保留。")
        else:
            work.drop("quality", str(extra))

    jobs = [("fix", w, m) for w, m in fixes] + [("rewrite", w, r) for w, r in rewrites]
    with ThreadPoolExecutor(max_workers=width) as pool:
        list(pool.map(second, jobs))
    changed = [w for _, w, _ in jobs if w.doc]
    verdict = recheck(run, state, changed, stats) if changed else {}
    for work in changed:
        if verdict.get(work.version["key"], True):
            work.passed = True
            if work.quality is None:
                work.quality = quality_of(None)
            work.quality = {
                **work.quality,
                "invented": [],
                "speaker_ok": True,
                "audience_ok": True,
            }
        else:
            work.drop("quality", "这条提到了你没写过的内容，改了一次仍不过，没有保留。")
    # Rewrites can collide again: the later one goes.
    for work, twin in dedupe([w for w in works if w.doc]):
        work.drop(
            "duplicate", f"和「{twin.version['angle'].get('name')}」太像，没有保留。"
        )
    stats.values["seconds"] = int(
        state.get("drafting", {}).get("seconds") or 0
    ) + round(time.monotonic() - started)
    stats.values["delivered"] = sum(1 for w in works if w.doc)
    stats.values["dropped"] = sum(1 for w in works if not w.doc)
    checkpoint()
    if not any(w.doc for w in works):
        raise Stop(
            "VIDEO_AUTO_DRAFTS_FAILED",
            "这次几条稿子都没通过检查，点「继续」会重新写一次。",
        )
