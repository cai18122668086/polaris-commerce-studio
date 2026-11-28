"""backend/scripts/writing_eval.py recomputes the plan's numbers from rows.

Synthetic rows shaped like the production run c8dbc697 (two lanes, a failed
comparison, failed writing tasks, a peer-facing benchmark, drafts in a
customer's voice); the real run is recomputed by hand against production.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from app.video_auto_writing import rid as app_rid

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "writing_eval.py"
spec = importlib.util.spec_from_file_location("writing_eval", SCRIPT)
assert spec and spec.loader
we = importlib.util.module_from_spec(spec)
sys.modules["writing_eval"] = we
spec.loader.exec_module(we)

RUN = "c8dbc697-2c28-43ab-a734-5e47ffd68451"
PROJECT = "6e6d834a-cec7-4528-90b8-d2e406980979"


def task(
    kind: str,
    request_id: str,
    status: str = "completed",
    attempts: int = 1,
    issue: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    usage = {"prompt_tokens": 1000, "completion_tokens": 100}
    return {
        "id": f"t-{kind}-{request_id[:8]}",
        "kind": kind,
        "status": status,
        "error_code": "VIDEO_SCRIPT_INVALID" if status == "failed" else None,
        "request_id": request_id,
        "created_at": "2026-11-28T14:13:20+00:00",
        "updated_at": "2026-11-28T14:13:40+00:00",
        "receipt": {"attempts": [{"usage": usage}] * attempts},
        "result": {"validation_issue": {"kind": issue}} if issue else {},
        **extra,
    }


def dataset() -> dict[str, Any]:
    lanes = {}
    tasks = []
    documents: list[dict[str, Any]] = [
        {"id": "facts", "facts": [{"value": "真皮家具"}, {"value": "名师设计"}]},
    ]
    for platform, peer in (("douyin", True), ("xiaohongshu", False)):
        lane_id = f"{RUN}:{platform}"
        bench = {
            "platform_id": f"{platform}-1",
            "reference_id": f"ref-{platform}",
            "analysis_id": f"ana-{platform}",
            "extraction_id": f"ext-{platform}",
            "no_speech_note": False,
        }
        lanes[platform] = {
            "mode": "search",
            "ranked": [{"platform_id": bench["platform_id"]}],
            "tried": [bench["platform_id"]],
            "benchmarks": [bench],
            "search_task_id": f"search-{platform}",
        }
        tasks.append(
            task(
                "benchmark_search",
                app_rid_str(lane_id, "search"),
                id=f"search-{platform}",
                result={
                    "items": [
                        {
                            "platform_id": bench["platform_id"],
                            "title": "卖家具的你就这么整 #自媒体"
                            if peer
                            else "新店实拍",
                            "author_name": "李大成IP打造" if peer else "店主",
                            "like_count": 4510,
                        }
                    ]
                },
            )
        )
        tasks.append(
            task(
                "ref_analysis",
                app_rid_str(lane_id, "analysis", bench["reference_id"], 0),
            )
        )
        documents.append({"id": bench["analysis_id"], "audience": {"who": "顾客"}})
    tasks.append(
        task("ref_compare", app_rid_str(f"{RUN}:douyin", "compare", 0), "failed", 2)
    )
    drafts = []
    texts = {
        "douyin-v1": (
            "家具店拍产品没流量？换这几个开头",
            "评论区打出家具，我把开头思路发你。",
        ),
        "xiaohongshu-v1": (
            "逛家具店不累",
            "最近朋友都在提这家店，趁周末去看了看。\n销售先招呼坐下喝杯茶。",
        ),
    }
    for key, platform in (
        ("douyin-v1", "douyin"),
        ("douyin-v2", "douyin"),
        ("xiaohongshu-v1", "xiaohongshu"),
    ):
        first = task(
            "fact_draft",
            app_rid_str(RUN, "draft", key, 0, 0),
            "failed",
            2,
            "replacement_ungrounded",
        )
        tasks.append(first)
        if key == "douyin-v2":  # all three attempts fail
            for attempt in (1, 2):
                tasks.append(
                    task(
                        "fact_draft",
                        app_rid_str(RUN, "draft", key, 0, attempt),
                        "failed",
                        2,
                        "numeric_claim",
                    )
                )
            drafts.append(
                {
                    "key": key,
                    "platform": platform,
                    "document_id": None,
                    "task_id": tasks[-1]["id"],
                    "reference_id": f"ref-{platform}",
                }
            )
            continue
        second = task("fact_draft", app_rid_str(RUN, "draft", key, 0, 1))
        tasks.append(second)
        drafts.append(
            {
                "key": key,
                "platform": platform,
                "document_id": f"doc-{key}",
                "task_id": second["id"],
                "reference_id": f"ref-{platform}",
                "label": "照主对标的结构写",
            }
        )
        title, text = texts[key]
        documents.append({"id": f"doc-{key}", "text": text, "publish_title": title})
    run = {
        "id": RUN,
        "project_id": PROJECT,
        "status": "completed",
        "created_at": "2026-11-28T14:13:09+00:00",
        "updated_at": "2026-11-28T14:17:13+00:00",
        "inputs": {
            "count": 3,
            "platform": "douyin",
            "platforms": ["douyin", "xiaohongshu"],
            "query": "家具店",
            "facts_text": "在新恒开了家恒志欧式家具店\n高端设计，真皮家具，名师设计",
        },
        "result": {
            "lanes": lanes,
            "drafts": drafts,
            "allocation": {"douyin": 2, "xiaohongshu": 1},
            "facts_document_id": "facts",
        },
    }
    return {"runs": [run], "tasks": tasks, "documents": documents}


def app_rid_str(*parts: object) -> str:
    return str(app_rid(str(parts[0]), *parts[1:]))


def test_request_ids_match_the_orchestrator() -> None:
    assert we.rid(RUN, "draft", "douyin-v1", 0, 2) == app_rid_str(
        RUN, "draft", "douyin-v1", 0, 2
    )


def test_recomputes_calls_failures_and_delivery() -> None:
    out = we.evaluate(dataset(), [])
    run = out["runs"][0]
    # writing 2+1 + 2+2+2 + 2+1 = 12, analyses 2, compare 2, pick 2, facts 1
    assert run["calls_by_step"] == {
        "fact_draft": 12,
        "ref_analysis": 2,
        "ref_compare": 2,
        "pick": 2,
        "facts": 1,
    }
    assert run["model_calls"] == 19
    assert run["write_tasks"] == 7 and run["write_tasks_failed"] == 5
    assert run["write_failure_reasons"] == {
        "replacement_ungrounded": 3,
        "numeric_claim": 2,
    }
    assert run["compare_failed"] == 1
    assert (run["delivered"], run["count_requested"]) == (2, 3)
    assert run["seconds"] == 244
    assert run["wasted"]["calls"] == 2 + 2 + 2 + 2 + 2 + 2  # failed writes + compare
    summary = out["summary"]
    assert summary["write_failure_rate"] == round(5 / 7, 4)
    assert summary["write_calls_per_delivered"] == 6.0


def test_flags_peer_benchmark_peer_teaching_and_visitor_voice() -> None:
    run = we.evaluate(dataset(), [])["runs"][0]
    flags = {b["platform"]: b["flags"] for b in run["benchmarks"]}
    assert flags == {"douyin": ["peer"], "xiaohongshu": []}
    drafts = {d["key"]: d for d in run["drafts"]}
    assert "peer_teaching" in drafts["douyin-v1"]["flags"]
    assert drafts["douyin-v1"]["skeleton_flags"] == ["peer"]
    visitor = drafts["xiaohongshu-v1"]["flags"]
    assert "visitor_narration" in visitor and "invented_detail" in visitor


def test_scenario_rules_add_their_terms() -> None:
    scenario = we.load_scenario("euro_furniture_store")
    run = we.evaluate(dataset(), [scenario])["runs"][0]
    drafts = {d["key"]: d for d in run["drafts"]}
    assert "喝杯茶" in drafts["xiaohongshu-v1"]["flags"]["invented_detail"]


def test_speaker_visitor_allows_visitor_voice() -> None:
    data = dataset()
    data["runs"][0]["inputs"]["speaker"] = "visitor"
    run = we.evaluate(data, [])["runs"][0]
    drafts = {d["key"]: d for d in run["drafts"]}
    assert "visitor_narration" not in drafts["xiaohongshu-v1"]["flags"]


def test_v2_counters_replace_derived_writing_calls() -> None:
    data = dataset()
    result = data["runs"][0]["result"]
    result["brief"] = {
        "audience": "consumer",
        "speaker": "merchant_self",
        "duration": 30,
        "count_requested": 3,
    }
    result["funnel"] = {"brief_calls": 1, "judge_calls": 2, "prompt_tokens": 50}
    result["drafting"] = {"write_calls": 3, "fix_calls": 1, "review_calls": 1}
    run = we.evaluate(data, [])["runs"][0]
    assert (
        "fact_draft" not in run["calls_by_step"] and "pick" not in run["calls_by_step"]
    )
    assert run["calls_by_step"]["brief"] == 1 and run["calls_by_step"]["judge"] == 2
    assert (
        run["model_calls"] == 2 + 1 + 2 + 3 + 1 + 1
    )  # analyses, brief, judge, drafting
    assert run["band"] == [130, 170]


def test_overlap_and_merge(tmp_path: Path) -> None:
    assert we.overlap(
        "欧式家具怎么选不踩坑？", "欧式家具怎么挑不踩坑？先看这家"
    ) == pytest.approx(0.47, abs=0.01)
    out = we.evaluate(dataset(), [])
    out["db_write_tasks"] = {"tasks": 22, "failed": 9}
    other = {"runs": [], "db_write_tasks": {"tasks": 53, "failed": 25}}
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(out, ensure_ascii=False))
    b.write_text(json.dumps(other))
    merged = we.merge([str(a), str(b)])
    assert merged["db_write_tasks"]["failure_rate"] == round(34 / 75, 4)
    assert merged["summary"]["runs"] == 1


def test_only_single_selects_are_sent() -> None:
    psql = we.Psql("psql")
    with pytest.raises(SystemExit):
        psql.rows("delete from video_assistance_tasks")
    with pytest.raises(SystemExit):
        psql.rows("select 1; drop table x")
    with pytest.raises(SystemExit):
        we.quoted(["x' or '1'='1"])
