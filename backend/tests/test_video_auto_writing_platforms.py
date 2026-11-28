"""全自动爆款文案（第二轮 L7）：多平台、条数、平分、单平台失败的部分完成。"""

from uuid import uuid4

import pytest

from app import video_auto_writing as auto
from tests.test_video_auto_writing import FACTS, stored

pytest_plugins = ["tests.test_video_auto_writing"]


def body(project, **extra):
    return {
        "request_id": str(uuid4()),
        "project_id": project,
        "expected_revision": 1,
        "query": "护手霜",
        "facts_text": FACTS,
        **extra,
    }


def bench(ref, analysis="a"):
    return {"reference_id": ref, "analysis_id": f"{analysis}-{ref}"}


# ------------------------------------------------------------ the request ----


@pytest.mark.parametrize(
    "extra",
    [
        {"count": 0},
        {"count": 11},
        {"platforms": []},
        {"platforms": ["douyin", "xiaohongshu", "douyin"]},
        {"platforms": ["bilibili"]},
        {"count": "三"},
    ],
)
def test_platforms_and_count_out_of_range_are_refused(app_client, monkeypatch, extra):
    app, client, root, project = app_client
    monkeypatch.setattr(auto, "orchestrate", lambda *a: None)
    response = client.post(f"{root}/auto-writing", json=body(project, **extra))
    assert response.status_code == 422, response.text


def test_an_old_page_without_platforms_or_count_writes_what_it_always_did(
    app_client, monkeypatch
):
    """旧前端只发 platform：一个平台、3 条（以前固定的版本数），键 v1–v3。"""
    app, client, root, project = app_client
    monkeypatch.setattr(auto, "orchestrate", lambda *a: None)
    sent = body(project, platform="xiaohongshu")
    run_id = client.post(f"{root}/auto-writing", json=sent).json()["id"]
    row = stored(app, run_id)
    assert row.inputs["platforms"] == ["xiaohongshu"] and row.inputs["count"] == 3
    assert row.inputs["platform"] == "xiaohongshu"
    assert row.result["allocation"] == {"xiaohongshu": 3}
    assert auto.DEFAULT_COUNT == 3
    state = {"benchmarks": [bench("m"), bench("x")], "main_reference_id": "m"}
    plan, skipped = auto.write_plan(row.inputs, state)
    assert skipped == []
    assert [v["key"] for v in plan] == ["v1", "v2", "v3"]
    assert {v["platform"] for v in plan} == {"xiaohongshu"}
    old = [{k: v[k] for k in ("key", "label", "variant")} for v in auto.versions(state)]
    assert [{k: v[k] for k in ("key", "label", "variant")} for v in plan] == old
    # A run stored before this change (no platforms, no count) reads the same.
    legacy = {"platform": "douyin", "query": "护手霜"}
    assert auto.planned(legacy) == {"douyin": 3}
    assert [v["key"] for v in auto.write_plan(legacy, state)[0]] == ["v1", "v2", "v3"]


def test_new_page_fields_are_kept_deduplicated_and_in_ticked_order(
    app_client, monkeypatch
):
    app, client, root, project = app_client
    monkeypatch.setattr(auto, "orchestrate", lambda *a: None)
    sent = body(
        project, platform="douyin", platforms=["xiaohongshu", "douyin"], count=5
    )
    row = stored(app, client.post(f"{root}/auto-writing", json=sent).json()["id"])
    assert row.inputs["platforms"] == ["xiaohongshu", "douyin"]
    assert row.inputs["platform"] == "xiaohongshu"  # the first ticked
    assert row.result["allocation"] == {"xiaohongshu": 3, "douyin": 2}
    assert row.result["request"]["count"] == 5
    same = body(project, platforms=["douyin", "douyin"], count=2)
    row = stored(app, client.post(f"{root}/auto-writing", json=same).json()["id"])
    assert row.inputs["platforms"] == ["douyin"]


# ------------------------------------------------------------- the split ----


@pytest.mark.parametrize(
    ("count", "platforms", "expected"),
    [
        (1, ["douyin"], {"douyin": 1}),
        (2, ["douyin"], {"douyin": 2}),
        (3, ["xiaohongshu"], {"xiaohongshu": 3}),
        (10, ["douyin"], {"douyin": 10}),
        (1, ["douyin", "xiaohongshu"], {"douyin": 1, "xiaohongshu": 0}),
        (2, ["douyin", "xiaohongshu"], {"douyin": 1, "xiaohongshu": 1}),
        (3, ["douyin", "xiaohongshu"], {"douyin": 2, "xiaohongshu": 1}),
        (3, ["xiaohongshu", "douyin"], {"xiaohongshu": 2, "douyin": 1}),
        (10, ["douyin", "xiaohongshu"], {"douyin": 5, "xiaohongshu": 5}),
    ],
)
def test_versions_are_split_evenly_and_the_odd_one_goes_to_the_first(
    count, platforms, expected
):
    assert auto.allocation(count, platforms) == expected
    inputs = {"platforms": platforms, "count": count, "query": "护手霜"}
    lanes = {p: {"benchmarks": [bench(p)], "main_reference_id": p} for p in platforms}
    state = lanes[platforms[0]] if len(platforms) == 1 else {"lanes": lanes}
    plan, skipped = auto.write_plan(inputs, state)
    assert skipped == []
    got = {p: sum(1 for v in plan if v["platform"] == p) for p in platforms}
    assert got == expected and len(plan) == count
    keys = [v["key"] for v in plan]
    assert len(set(keys)) == len(keys)
    # Each platform writes from its own benchmarks.
    assert all(v["benchmark"]["reference_id"] == v["platform"] for v in plan)
    # One platform written (one chosen, or 1 version over two) keeps v1… keys.
    if sum(1 for n in expected.values() if n) == 1:
        assert keys == [f"v{i + 1}" for i in range(count)]
    else:
        assert all(
            k.startswith(f"{v['platform']}-v") for k, v in zip(keys, plan, strict=True)
        )


def test_ten_versions_use_valid_openings_and_go_round_the_benchmarks():
    state = {
        "benchmarks": [bench("m"), bench("x"), bench("y")],
        "main_reference_id": "m",
    }
    plan = auto.versions(state, 10)
    assert len(plan) == 10
    assert all(0 <= v["variant"] <= auto.MAX_VARIANT for v in plan)
    pairs = [(v["benchmark"]["reference_id"], v["variant"]) for v in plan]
    assert len(set(pairs)) == 10
    assert {p[0] for p in pairs} == {"m", "x", "y"}
    # The first three are exactly what three versions always were.
    assert pairs[:3] == [("m", 0), ("m", 1), ("x", 0)]
    one = auto.versions(
        {"benchmarks": [bench("m")], "main_reference_id": "m"}, 10, "douyin-"
    )
    assert [v["key"] for v in one] == [f"douyin-v{i}" for i in range(1, 11)]
    assert all(0 <= v["variant"] <= auto.MAX_VARIANT for v in one)


# ----------------------------------------------- one platform that fails ----


def lane_steps(fail=(), crash=()):
    seen = []

    def search(run, inputs, state=None):
        seen.append(("search", run.platform, run.id))
        if run.platform in fail:
            raise auto.Stop("VIDEO_AUTO_NO_CANDIDATES", "没有找到可用的视频")
        run.save(search_task_id=f"page-{run.platform}")

    def done(name, value):
        def step(run, inputs, state):
            assert inputs["platform"] == run.platform
            run.save(**{auto.DONE_WHEN[name]: value(run)})

        return step

    def write(run, inputs, state):
        plan, _ = auto.write_plan(inputs, state)
        drafts = [
            {"key": v["key"], "platform": v["platform"], "document_id": f"d-{v['key']}"}
            for v in plan
        ]
        run.save(
            drafts=drafts, partial_message=auto.partial_message(inputs, state, drafts)
        )

    steps = [
        ("search", search),
        ("pick", done("pick", lambda r: [{"platform_id": "a", "reason": "r"}])),
        ("extract", done("extract", lambda r: [bench(f"ref-{r.platform}")])),
        ("analyse", done("analyse", lambda r: f"ref-{r.platform}")),
        ("facts", lambda run, inputs, state: run.save(facts_document_id="f")),
        ("write", write),
    ]
    return steps, search, seen


def start(client, root, project, monkeypatch, steps, search, **extra):
    monkeypatch.setattr(auto, "STEPS", steps)
    monkeypatch.setattr(auto, "step_search", search)
    response = client.post(f"{root}/auto-writing", json=body(project, **extra))
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_two_platforms_search_apart_and_write_their_own_share(app_client, monkeypatch):
    app, client, root, project = app_client
    steps, search, seen = lane_steps()
    run_id = start(
        client,
        root,
        project,
        monkeypatch,
        steps,
        search,
        platforms=["douyin", "xiaohongshu"],
        count=3,
    )
    row = stored(app, run_id)
    assert row.status == "completed" and row.result["message"] == ""
    lanes = row.result["lanes"]
    assert {k: v["status"] for k, v in lanes.items()} == {
        "douyin": "completed",
        "xiaohongshu": "completed",
    }
    assert lanes["xiaohongshu"]["search_task_id"] == "page-xiaohongshu"
    # Different request ids per lane: the two searches are never one.
    assert len({s[2] for s in seen}) == 2
    keys = [(d["platform"], d["key"]) for d in row.result["drafts"]]
    assert keys == [
        ("douyin", "douyin-v1"),
        ("douyin", "douyin-v2"),
        ("xiaohongshu", "xiaohongshu-v1"),
    ]


def test_one_platform_failing_leaves_the_other_and_says_so(app_client, monkeypatch):
    app, client, root, project = app_client
    steps, search, _ = lane_steps(fail={"xiaohongshu"})
    run_id = start(
        client,
        root,
        project,
        monkeypatch,
        steps,
        search,
        platforms=["douyin", "xiaohongshu"],
        count=3,
    )
    row = stored(app, run_id)
    assert row.status == "completed" and row.result["stage"] == "done"
    lane = row.result["lanes"]["xiaohongshu"]
    assert lane["status"] == "failed"
    assert lane["error_code"] == "VIDEO_AUTO_NO_CANDIDATES"
    assert [d["platform"] for d in row.result["drafts"]] == ["douyin", "douyin"]
    assert row.result["message"].startswith("小红书没写成：没有找到可用的视频")
    assert "抖音 2 条已存进文案库" in row.result["message"]


def test_both_platforms_failing_stops_the_run_and_resume_tries_again(
    app_client, monkeypatch
):
    app, client, root, project = app_client
    steps, search, seen = lane_steps(fail={"douyin", "xiaohongshu"})
    run_id = start(
        client,
        root,
        project,
        monkeypatch,
        steps,
        search,
        platforms=["xiaohongshu", "douyin"],
        count=2,
    )
    row = stored(app, run_id)
    assert (row.status, row.error_code) == ("failed", "VIDEO_AUTO_NO_CANDIDATES")
    good, good_search, _ = lane_steps()
    monkeypatch.setattr(auto, "STEPS", good)
    monkeypatch.setattr(auto, "step_search", good_search)
    assert client.post(f"{root}/auto-writing/{run_id}/resume").status_code == 200
    row = stored(app, run_id)
    assert row.status == "completed"
    assert sorted(d["platform"] for d in row.result["drafts"]) == [
        "douyin",
        "xiaohongshu",
    ]


def test_one_platform_with_n_one_is_the_old_run_shape(app_client, monkeypatch):
    """单平台 N=1：结果仍在顶层（没有 lanes），一条 v1。"""
    app, client, root, project = app_client
    steps, search, seen = lane_steps()
    run_id = start(
        client,
        root,
        project,
        monkeypatch,
        steps,
        search,
        platform="douyin",
        platforms=["douyin"],
        count=1,
    )
    row = stored(app, run_id)
    assert row.status == "completed" and "lanes" not in row.result
    assert row.result["search_task_id"] == "page-douyin"
    assert [d["key"] for d in row.result["drafts"]] == ["v1"]
    assert seen[0][2] == run_id  # same request ids as before


def test_pasted_links_are_one_shared_benchmark_lane(app_client, monkeypatch):
    app, client, root, project = app_client
    steps, search, seen = lane_steps()
    run_id = start(
        client,
        root,
        project,
        monkeypatch,
        steps,
        search,
        platforms=["douyin", "xiaohongshu"],
        count=3,
        query="https://v.douyin.com/abc/ https://www.xiaohongshu.com/explore/1",
    )
    row = stored(app, run_id)
    assert row.status == "completed" and "lanes" not in row.result
    assert len(seen) == 1
    assert [d["platform"] for d in row.result["drafts"]] == [
        "douyin",
        "douyin",
        "xiaohongshu",
    ]


def test_partial_message_counts_versions_that_failed_the_checks():
    inputs = {"platforms": ["douyin", "xiaohongshu"], "count": 4}
    state = {"lanes": {"douyin": {"status": "completed"}, "xiaohongshu": {}}}
    drafts = [
        {"platform": "douyin", "document_id": "a"},
        {"platform": "douyin", "document_id": None},
        {"platform": "xiaohongshu", "document_id": None},
        {"platform": "xiaohongshu", "document_id": None},
    ]
    text = auto.partial_message(inputs, state, drafts)
    assert "抖音有 1 条没通过事实检查" in text
    assert "小红书的 2 条都没通过事实检查" in text
    full = [{**d, "document_id": "x"} for d in drafts]
    assert auto.partial_message(inputs, state, full) == ""
    assert auto.partial_message({"platforms": ["douyin"], "count": 3}, {}, []) == ""
