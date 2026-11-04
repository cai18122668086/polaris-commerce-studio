"""Narrative orchestration, bounded correction and a byte-frozen rollback path.

Synthetic decisions test the wiring; they do not certify generated image quality.
"""

import asyncio
import json
import sys
from uuid import uuid4

import pytest

from app.replica_completion import PLAN
from app.replica_completion import prepare as complete
from app.replica_direct_delivery import V10_BINDING
from app.replica_exact_compact import (
    CompactExactReplicaRun,
    CompactResponseInvalid,
    run_class,
)
from app.replica_native import ReplicaPlanAuditRejected, ReplicaSegmentationInvalid
from app.replica_story import StoryEvidenceMissing
from tests.test_replica_auto_start import setup
from tests.test_replica_compact import SyntheticGateway, setup_run


def envelopes(gateway, phase):
    return [
        json.loads(r.product_information[0])
        for r in gateway.requests
        if json.loads(r.product_information[0])["stage"] == phase
    ]


def change_gateway(gateway, change):
    original = gateway.plan

    async def plan(request):
        response = await original(request)
        envelope = json.loads(request.product_information[0])
        change(envelope, response.payload)
        return response

    gateway.plan = plan


def test_entire_story_is_assigned_before_first_screen_and_bound_to_generation(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    payload["facts"] += "\nAn optional fact that need not appear on every screen"
    asyncio.run(run.prepare(payload, records))
    phases = [json.loads(r.product_information[0])["stage"] for r in gateway.requests]
    assert phases.index("layout") < phases.index("story_mapping") < phases.index("plan")
    first = envelopes(gateway, "plan")[0]["context"]
    assert first["sequence_summary"] == []
    assert [r["reference_unit_id"] for r in first["story_mapping"]["entries"]] == [
        "R001",
        "R002",
    ]
    review = envelopes(gateway, "review_story")[0]
    assert len(review["context"]["target_screens"]) == 2
    assert review["image_order"] == []
    for module in run.state()["plan"]["modules"]:
        header = (
            "Create ONE complete Chinese ecommerce visual for the current token only."
        )
        prompt = run.image_prompt_for_module(header, module["id"])
        bound = json.loads(prompt.split("CURRENT_STORY=", 1)[1])
        assert bound == module["story_binding"]
        facts = json.loads(
            prompt.split("RESOLVED_FACTS=", 1)[1].split("\nFACT_ADAPTATIONS=", 1)[0]
        )
        assert [f["id"] for f in facts["facts"]] == ["F001"]
    assert not gateway.image_requests


@pytest.mark.parametrize("case", ["order", "handoff", "unapproved_fact", "role"])
def test_invalid_story_bindings_stop_before_generation(tmp_path, case):
    gateway = SyntheticGateway()

    def change(env, raw):
        if env["stage"] == "story_mapping":
            if case == "order":
                raw["entries"].reverse()
            elif case == "handoff":
                raw["entries"][0]["next_unit_id"] = None
            elif case == "unapproved_fact":
                raw["entries"][0]["target_fact_ids"] = ["F999"]
        if env["stage"] == "plan" and case == "role":
            raw["modules"][0]["page_duty"] = (
                "Another convenient ingredient introduction"
            )

    change_gateway(gateway, change)
    run, _, payload, records = setup_run(tmp_path, gateway)
    with pytest.raises(CompactResponseInvalid):
        asyncio.run(run.prepare(payload, records))
    assert not envelopes(gateway, "review_plan") and not gateway.image_requests


def test_evidence_gap_is_persisted_and_cannot_use_automatic_completion(tmp_path):
    gateway = SyntheticGateway()

    def change(env, raw):
        if env["stage"] == "story_mapping":
            raw["entries"][0]["evidence_gap"] = (
                "No supported product mechanism supplied"
            )

    change_gateway(gateway, change)
    run, _, payload, records = setup_run(tmp_path, gateway)
    with pytest.raises(StoryEvidenceMissing):
        asyncio.run(run.prepare(payload, records))
    assert run.context["story_mapping"]["entries"][0]["evidence_gap"]
    with pytest.raises(StoryEvidenceMissing):
        asyncio.run(complete(run, payload, records, ReplicaSegmentationInvalid()))
    assert not (run.root / PLAN).exists()
    assert not envelopes(gateway, "plan") and not gateway.image_requests


def test_whole_story_failure_repairs_only_affected_plan_and_reuses_local_pass(tmp_path):
    gateway = SyntheticGateway()
    rejected = False

    def change(env, raw):
        nonlocal rejected
        if env["stage"] == "review_story" and not rejected:
            rejected = True
            row = raw["unit_checks"][1]
            row["comparisons"][1].update(
                match=False,
                evidence=(
                    "R002 repeats R001's ingredient claim instead of its source job"
                ),
            )
            row["material_mismatches"] = [
                "R002 must explain its source mechanism instead of repeating R001"
            ]
            row["decision"] = "FAIL"

    change_gateway(gateway, change)
    run, _, payload, records = setup_run(tmp_path, gateway)
    asyncio.run(run.prepare(payload, records))
    assert [
        p["context"]["requested_units"][0]["id"] for p in envelopes(gateway, "plan")
    ] == ["R001", "R002", "R002"]
    assert len(envelopes(gateway, "story_mapping")) == 1
    assert len(envelopes(gateway, "review_plan")) == 3
    assert len(envelopes(gateway, "review_story")) == 2
    prior = envelopes(gateway, "plan")[-1]["context"]["prior_audit"]
    assert any("Story:" in m for m in prior["unit_audits"][0]["material_mismatches"])
    assert run.state()["state"] == "READY" and not gateway.image_requests


@pytest.mark.parametrize("repetition", ["different_argument", "source_repetition"])
def test_shared_fact_and_observed_repetition_do_not_trigger_keyword_dedup(
    tmp_path, repetition
):
    gateway = SyntheticGateway()

    def change(env, raw):
        if env["stage"] == "story_mapping":
            for entry in raw["entries"]:
                entry["repetition_mode"] = repetition

    change_gateway(gateway, change)
    run, _, payload, records = setup_run(tmp_path, gateway)
    asyncio.run(run.prepare(payload, records))
    assert run.state()["state"] == "READY"
    assert [r["target_fact_ids"] for r in run.context["story_mapping"]["entries"]] == [
        ["F001"],
        ["F001"],
    ]


def test_mapping_repair_is_bounded_and_leaves_unchanged_page_intact(tmp_path):
    gateway = SyntheticGateway()
    mapping_round = 0

    def change(env, raw):
        nonlocal mapping_round
        if env["stage"] == "story_mapping":
            mapping_round += 1
            if mapping_round > 1:
                raw["entries"][1]["target_role"] = (
                    "Explain the supported mechanism clearly"
                )
                raw["entries"][1]["information_gain"] = (
                    "Explain why the promise is supported"
                )
        if env["stage"] == "review_story" and mapping_round == 1:
            row = raw["unit_checks"][1]
            row["comparisons"][0].update(
                match=False,
                evidence="R002's ingredient assignment misses the source explanation",
            )
            row.update(decision="FAIL", revise_mapping=True)

    change_gateway(gateway, change)
    run, _, payload, records = setup_run(tmp_path, gateway)
    asyncio.run(run.prepare(payload, records))
    assert mapping_round == 2
    plans = envelopes(gateway, "plan")
    assert [p["context"]["requested_units"][0]["id"] for p in plans] == [
        "R001",
        "R002",
        "R002",
    ]
    assert len(envelopes(gateway, "review_plan")) == 3
    assert run.state()["plan"]["modules"][1]["page_duty"] == (
        "Explain the supported mechanism clearly"
    )


def test_rejected_story_never_enters_best_effort_generation(tmp_path):
    gateway = SyntheticGateway()

    def change(env, raw):
        if env["stage"] == "review_story":
            row = raw["unit_checks"][1]
            row["comparisons"][3].update(
                match=False,
                evidence="R002's composition ratio cannot prove the claimed outcome",
            )
            row["decision"] = "FAIL"

    change_gateway(gateway, change)
    run, _, payload, records = setup_run(tmp_path, gateway)
    with pytest.raises(ReplicaPlanAuditRejected):
        asyncio.run(run.prepare(payload, records))
    calls = len(gateway.requests)
    with pytest.raises(ReplicaPlanAuditRejected):
        asyncio.run(complete(run, payload, records, ReplicaSegmentationInvalid()))
    assert len(gateway.requests) == calls
    assert not (run.root / PLAN).exists() and not gateway.image_requests


def test_v10_is_byte_frozen_restorable_and_keeps_its_source_only_completion(tmp_path):
    current, gateway, payload, records = setup_run(tmp_path)
    cls = run_class("exact", V10_BINDING)
    assert sys.modules[cls.__module__].protocol_binding() == V10_BINDING
    old = cls(
        "exact",
        current.document_id,
        current.workspace_id,
        gateway,
        current.storage,
        root=tmp_path,
    )
    asyncio.run(old.prepare(payload, records))
    assert old.binding == V10_BINDING
    assert not envelopes(gateway, "story_mapping")
    saved = asyncio.run(old.snapshot())
    restored = cls(
        "exact", old.document_id, old.workspace_id, gateway, old.storage, root=tmp_path
    )
    asyncio.run(restored.restore(saved))
    assert restored.state() == old.state()
    (old.root / "session.json").unlink()
    asyncio.run(complete(old, payload, records, ReplicaSegmentationInvalid()))
    assert (old.root / PLAN).exists() and not gateway.image_requests


def test_roll_back_setting_selects_v10_for_new_sessions_only(client, monkeypatch):
    route, body = setup(client, monkeypatch)
    seen = []
    old_cls = run_class("exact", V10_BINDING)

    async def prepare(self, values, records):
        seen.append(values["_exact_model_protocol"])
        return [
            {
                "reference": values["references"][0],
                "analysis": {},
                "prompt": "",
                "unit_id": "M001",
            }
        ]

    async def snapshot(self):
        return {
            "schema": "replica-native-v1",
            "skill_id": self.skill_id,
            "source_hash": self.source_hash,
            "files": {},
        }

    for cls in (old_cls, CompactExactReplicaRun):
        monkeypatch.setattr(cls, "prepare", prepare)
        monkeypatch.setattr(cls, "snapshot", snapshot)
    for configured, expected in (
        ("current", "exact-compact-v11"),
        ("exact-compact-v10", "exact-compact-v10"),
    ):
        client.app.state.settings.replica_exact_planning_protocol = configured
        response = client.post(
            route + "/sessions", json={**body, "request_id": str(uuid4())}
        )
        assert response.status_code == 202
        doc = client.get(route + "/documents/" + response.json()["id"]).json()
        assert doc["status"] == "generating", doc
        assert seen[-1] == expected
