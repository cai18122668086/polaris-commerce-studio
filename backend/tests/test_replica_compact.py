"""Compact model boundary using real native guards and synthetic visual responses.

These tests verify orchestration and binding, not real image quality or live UI.
"""

import asyncio
import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from PIL import Image

from app.replica_exact_compact import (
    ARTWORK_DIMENSIONS,
    OBSERVATIONS,
    PLAN_DIMENSIONS,
    CompactExactReplicaRun,
    CompactResponseInvalid,
    protocol_binding,
    run_class,
)
from app.replica_native import NativeReplicaRun, ReplicaNativeError, digest, read_json
from app.replica_native_provider import NativeReplicaProvider


def observed(prefix):
    return {key: f"{prefix}: concrete synthetic {key}" for key in OBSERVATIONS}


def compared(dimensions, prefix, fail=False):
    return [
        {
            "dimension": key,
            "match": not (fail and index == 0),
            "evidence": f"{prefix}: observed separate synthetic evidence for {key}",
        }
        for index, key in enumerate(dimensions)
    ]


class SyntheticGateway:
    provider_name = "synthetic"
    image_model = "synthetic-image"
    planner_model = "synthetic-planner"
    pricing_version = "synthetic-pricing"

    def __init__(self, reject_first=False):
        self.requests = []
        self.reject_first = reject_first
        self.reject_always = False
        self.reject_artwork_once = False
        self.reject_artwork_always = False
        self.artwork_reviews = {}
        self.image_requests = []

    async def plan(self, request):
        self.requests.append(request)
        envelope = json.loads(request.product_information[0])
        phase, data = envelope["stage"], envelope["context"]
        if phase == "intake":
            value = {
                "product_geometry": [
                    f"Supported synthetic geometry {i}" for i in range(3)
                ],
                "product_crops": [{"product_index": 0, "bbox": [0, 0, 64, 96]}],
                "columns": [
                    {
                        "reference_index": 0,
                        "column_index": 0,
                        "bbox": [0, 0, 256, 640],
                        "column_boundary_reason": "Complete synthetic reference column",
                    }
                ],
                "route": "DETAIL_PAGE",
            }
        elif phase in {"screen_split", "screen_inventory"}:
            value = {
                "columns": [
                    {
                        "column_id": c["column_id"],
                        "screens": [
                            {
                                "headline": f"Synthetic headline {i}",
                                "buyer_question": f"Synthetic buyer question {i}",
                            }
                            for i in range(2)
                        ],
                        **({"boundary_ys": [320]} if phase == "screen_split" else {}),
                    }
                    for c in data["columns"]
                ],
                **(
                    {"all_columns_covered": True} if phase == "screen_inventory" else {}
                ),
            }
        elif phase == "product":
            value = {
                "products": [
                    {
                        "product_index": 0,
                        "readable_marks": [],
                        "uncertainty_notes": (
                            "The synthetic unbranded rectangle has no physical text"
                        ),
                    }
                ]
            }
        elif phase == "layout":
            value = {
                "units": [
                    {
                        "reference_unit_id": u["id"],
                        "reference_observation": observed(
                            "Independent layout " + u["id"]
                        ),
                        "reference_product_present": True,
                        "layout_anchors": [
                            {
                                "label": "Synthetic rectangular product",
                                "bbox": [100, 300, 600, 900],
                            }
                        ],
                        "has_poster_text": True,
                        "text_regions": [
                            {
                                "id": "headline",
                                "role": "headline",
                                "font_tier": "dominant",
                                "line_group": "main",
                                "observed_text": "Reference slogan",
                                "bbox": [80, 40, 920, 180],
                            }
                        ],
                        "typography_notes": (
                            "One dominant headline above the synthetic product"
                        ),
                    }
                    for u in data["physical_units"]
                ]
            }
        elif phase == "plan":
            value = {
                "modules": [
                    {
                        "reference_unit_id": u["id"],
                        "visual_contract": observed("Intended replacement " + u["id"]),
                        "page_duty": "Present supported synthetic product",
                        "buyer_conclusion": "Recognize the supported synthetic product",
                        "generation_brief": (
                            "Preserve the independent headline and rectangular "
                            "subject bounds"
                        ),
                        "copy_units": ["Supported synthetic product"],
                        "product_visibility": "visible_product",
                        "required_identity_checks": [
                            "Preserve the actual blue rectangular body"
                        ],
                        "not_applicable_checks": [],
                        "text_bindings": [
                            {
                                "region_id": "headline",
                                "action": "render",
                                "copy_unit_index": 0,
                                "fragment": "Supported synthetic product",
                            }
                        ],
                    }
                    for u in data["requested_units"]
                ]
            }
        elif phase == "review_plan":
            value = {"unit_audits": []}
            for unit in data["review_targets"]:
                uid = unit["reference_unit_id"]
                fail = uid == "R002" and (
                    self.reject_always
                    or (self.reject_first and "-r0-" in request.group_key)
                )
                value["unit_audits"].append(
                    {
                        "unit_id": uid,
                        "fresh_pixel_observation": observed(
                            "Fresh reinspection " + request.group_key + uid
                        ),
                        "comparisons": compared(PLAN_DIMENSIONS, uid, fail),
                        "material_mismatches": [
                            "Synthetic second-screen subject bounds require correction"
                        ]
                        if fail
                        else [],
                        "decision": "FAIL" if fail else "PASS",
                    }
                )
        elif phase == "review_artwork":
            mid = data["module"]["id"]
            count = self.artwork_reviews.get(mid, 0) + 1
            self.artwork_reviews[mid] = count
            fail = mid == "M001" and (
                self.reject_artwork_always or (self.reject_artwork_once and count == 1)
            )
            value = {
                "fresh_reference_observation": observed("Fresh original pixels " + mid),
                "fresh_artwork_observation": observed("Fresh output pixels " + mid),
                "comparisons": compared(ARTWORK_DIMENSIONS, mid, fail),
                "major_mismatches": [
                    "The synthetic output product color needs correction"
                ]
                if fail
                else [],
                "decision": "FAIL" if fail else "PASS",
                "product_geometry_match": not fail,
            }
        elif phase == "repair":
            value = {
                "single_edit_instruction": (
                    "Edit only the incorrect synthetic product color; "
                    "preserve subject bounds"
                )
            }
        else:
            raise AssertionError("Unexpected synthetic stage: " + phase)
        return SimpleNamespace(
            payload=value,
            error_code=None,
            normalized_usage={"reported": False},
            actual_cost_micros=None,
        )

    async def edit(self, request):
        from .test_replica_resolution import result

        self.image_requests.append(request)
        response = result((1024, 1280))
        buffer = BytesIO()
        Image.new("RGB", (1024, 1280), (len(self.image_requests) * 35, 80, 160)).save(
            buffer, "PNG"
        )
        response.artifact.payload = buffer.getvalue()
        return response


def setup_run(tmp_path, gateway=None):
    payloads, records = {}, {}
    for index, size in enumerate([(64, 96), (256, 640)]):
        buffer = BytesIO()
        Image.new("RGB", size, "blue" if index == 0 else "yellow").save(buffer, "PNG")
        key = f"asset-{index}"
        payloads[key] = buffer.getvalue()
        records[key] = (key, "image/png", digest(payloads[key]), key, *size)

    async def read_bytes(key):
        return payloads[key]

    async def save_validated(image):
        payloads[image.object_key] = image.payload

    gateway = gateway or SyntheticGateway()
    run = CompactExactReplicaRun(
        "exact",
        "rep_" + uuid4().hex,
        "ws_test",
        gateway,
        SimpleNamespace(read_bytes=read_bytes, save_validated=save_validated),
        root=tmp_path,
    )
    payload = {
        "product_asset_ids": ["asset-0"],
        "references": [{"asset_id": "asset-1"}],
        "facts": "Supported synthetic product",
        "language": "zh-CN",
        "platform_code": "tmall",
    }
    return run, gateway, payload, records


def test_compact_preparation_uses_real_guard_and_server_owned_metadata(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    progress = []
    run.on_progress = lambda value, label: progress.append(value)
    result = asyncio.run(run.prepare(payload, records))
    assert len(result) == 2 and run.state()["state"] == "READY"
    assert len(gateway.requests) == 7  # Includes independent column split/count.
    assert progress == [12, 12, 12, 24, 30, 48, 82, 92]
    for request in gateway.requests:
        assert request.planning_profile == "replica_exact_compact"
        assert len(request.system_prompt) < 4000
        assert "native_validators" not in request.system_prompt
        assert "harness.py" not in request.system_prompt
        assert "verified_skill" not in request.system_prompt
        envelope = json.loads(request.product_information[0])
        assert "crop_path" not in json.dumps(envelope)
        assert "sha256" not in json.dumps(envelope)
        assert len(envelope["image_order"]) == len(request.sources)
    state = run.state()
    assert state["plan"]["sequence_contract"]["source_unit_order"] == ["R001", "R002"]
    assert state["input"]["product_images"] == run.context["product_paths"]
    assert run.context["product_evidence"][0]["source_sha256"] == records["asset-0"][2]
    assert set(run.context["module_constraints"]) == {"M001", "M002"}
    assert state["plan"]["modules"][0]["output_canvas"] == {
        "width": 1024,
        "height": 1280,
    }
    layout = next(
        r
        for r in gateway.requests
        if json.loads(r.product_information[0])["stage"] == "layout"
    )
    assert len(layout.sources) == 2
    plan = next(
        r
        for r in gateway.requests
        if json.loads(r.product_information[0])["stage"] == "plan"
    )
    assert (
        len(plan.sources) == 3
    )  # Original + two screen crops, no duplicate auxiliary views.


def test_plan_revision_replaces_only_failed_unit_and_keeps_full_native_audit(tmp_path):
    run, gateway, payload, records = setup_run(
        tmp_path, SyntheticGateway(reject_first=True)
    )
    asyncio.run(run.prepare(payload, records))
    plans = [
        json.loads(r.product_information[0])
        for r in gateway.requests
        if json.loads(r.product_information[0])["stage"] == "plan"
    ]
    assert [[u["id"] for u in p["context"]["requested_units"]] for p in plans] == [
        ["R001", "R002"],
        ["R002"],
    ]
    reviews = [
        r
        for r in gateway.requests
        if json.loads(r.product_information[0])["stage"] == "review_plan"
    ]
    assert len(reviews) == 2 and all(len(r.sources) == 3 for r in reviews)
    original = read_json(next((tmp_path / "contracts").glob("exact-plan-r0-0-*.json")))
    revised = read_json(next((tmp_path / "contracts").glob("exact-plan-r1-0-*.json")))
    assert original["modules"][0] == revised["modules"][0]
    assert (
        original["_compact_scopes"]["modules"][0]
        == revised["_compact_scopes"]["modules"][0]
    )
    assert run.state()["state"] == "READY"


def test_written_plan_review_joins_source_and_proposal_without_module_aliases(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    payload["facts"] = "The user explicitly authorizes a supported synthetic benefit"
    asyncio.run(run.prepare(payload, records))
    review = next(
        json.loads(r.product_information[0])
        for r in gateway.requests
        if json.loads(r.product_information[0])["stage"] == "review_plan"
    )
    data = review["context"]
    assert data["audit_subject"] == "written_plan_before_rendering"
    assert data["user_facts"] == payload["facts"]
    assert "M001" not in json.dumps(data) and "M002" not in json.dumps(data)
    assert [t["reference_unit_id"] for t in data["review_targets"]] == ["R001", "R002"]
    for target in data["review_targets"]:
        assert target["proposed_screen"]["copy_units"] == [
            "Supported synthetic product"
        ]
        assert target["identity_scope"]["product_visibility"] == "visible_product"
        assert target["canvas_binding"] == {
            "reference_pixels": [256, 320],
            "planned_pixels": [1024, 1280],
        }
    schema = review["response_schema"]["properties"]["unit_audits"]
    assert schema["minItems"] == schema["maxItems"] == 2
    assert schema["items"]["properties"]["unit_id"]["enum"] == ["R001", "R002"]


def test_wrong_module_alias_can_be_corrected_without_resampling_valid_fail(tmp_path):
    gateway = SyntheticGateway(reject_first=True)
    original = gateway.plan
    seen = []

    async def plan(request):
        response = await original(request)
        envelope = json.loads(request.product_information[0])
        if envelope["stage"] == "review_plan":
            seen.append(envelope)
            if len(seen) == 1:
                response.payload["unit_audits"][0]["unit_id"] = "M001"
        return response

    gateway.plan = plan
    run, _, payload, records = setup_run(tmp_path, gateway)
    asyncio.run(run.prepare(payload, records))
    assert (
        len(seen) == 3
    )  # Invalid field correction, real FAIL, fresh revised-plan audit.
    assert "reference_unit_id" in seen[1]["validation_error"]
    plans = [
        r
        for r in gateway.requests
        if json.loads(r.product_information[0])["stage"] == "plan"
    ]
    assert len(plans) == 2
    assert run.state()["state"] == "READY" and not gateway.image_requests
    original_plan = read_json(next(tmp_path.glob("contracts/exact-plan-r0-0-*.json")))
    repaired_plan = read_json(next(tmp_path.glob("contracts/exact-plan-r1-0-*.json")))
    assert original_plan["modules"][0] == repaired_plan["modules"][0]


def test_persistent_wrong_reference_ids_stop_before_images_with_safe_error(tmp_path):
    from app.replica_native import ReplicaAnalysisUnavailable

    gateway = SyntheticGateway()
    original = gateway.plan
    reviews = []

    async def plan(request):
        response = await original(request)
        if json.loads(request.product_information[0])["stage"] == "review_plan":
            reviews.append(request)
            response.payload["unit_audits"][0]["unit_id"] = "M001"
        return response

    gateway.plan = plan
    run, _, payload, records = setup_run(tmp_path, gateway)
    with pytest.raises(CompactResponseInvalid) as error:
        asyncio.run(run.prepare(payload, records))
    assert len(reviews) == 2 and not gateway.image_requests
    assert isinstance(error.value, ReplicaAnalysisUnavailable)
    assert error.value.message == CompactResponseInvalid.message
    assert "M001" not in error.value.message


@pytest.mark.parametrize("counts", [(4, 4, 4), (1, 3, 2)])
def test_column_pixels_determine_all_screen_counts_without_fixed_grid(tmp_path, counts):
    gateway = SyntheticGateway()
    original = gateway.plan

    async def plan(request):
        result = await original(request)
        envelope = json.loads(request.product_information[0])
        phase, data = envelope["stage"], envelope["context"]
        if phase == "intake":
            edges = [0, 80, 160, 256]
            result.payload["columns"] = [
                {
                    "reference_index": 0,
                    "column_index": i,
                    "bbox": [edges[i], 0, edges[i + 1], 640],
                    "column_boundary_reason": f"Visible synthetic column gutter {i}",
                }
                for i in range(3)
            ]
        elif phase in {"screen_split", "screen_inventory"}:
            for column, source in zip(
                result.payload["columns"], data["columns"], strict=True
            ):
                count = counts[source["column_index"]]
                column["screens"] = [
                    {
                        "headline": f"Distinct screen {i}",
                        "buyer_question": f"A different buyer question {i}",
                    }
                    for i in range(count)
                ]
                if phase == "screen_split":
                    column["boundary_ys"] = [640 * i // count for i in range(1, count)]
        return result

    gateway.plan = plan
    run, _, payload, records = setup_run(tmp_path, gateway)
    result = asyncio.run(run.prepare(payload, records))
    assert len(result) == sum(counts)
    segmentation = read_json(tmp_path / "identity-segmentation.json")
    for i, count in enumerate(counts):
        units = [u for u in segmentation["units"] if u["column_index"] == i]
        assert len(units) == count
        assert [u["screen_index"] for u in units] == list(range(count))
        assert units[0]["bbox"][1] == 0 and units[-1]["bbox"][3] == 640
        assert all(
            a["bbox"][3] == b["bbox"][1] for a, b in zip(units, units[1:], strict=False)
        )
    counter = next(
        r
        for r in gateway.requests
        if json.loads(r.product_information[0])["stage"] == "screen_inventory"
    )
    evidence = json.loads(counter.product_information[0])
    assert "boundary_ys" not in json.dumps(evidence["context"])
    assert "screens" not in json.dumps(evidence["context"])
    assert {r["role"] for r in evidence["image_order"]} == {
        "reference_original",
        "reference_column",
    }
    assert len(counter.sources) == 4


def test_screen_count_disagreement_gets_one_directed_repair_and_blind_recount(tmp_path):
    gateway = SyntheticGateway()
    original = gateway.plan

    async def plan(request):
        result = await original(request)
        envelope = json.loads(request.product_information[0])
        phase = envelope["stage"]
        if phase == "screen_inventory" or (
            phase == "screen_split" and envelope["context"].get("boundary_mismatch")
        ):
            for column in result.payload["columns"]:
                column["screens"] = [
                    {
                        "headline": f"Actual physical screen {i}",
                        "buyer_question": f"Actual distinct buyer question {i}",
                    }
                    for i in range(3)
                ]
                if phase == "screen_split":
                    column["boundary_ys"] = [200, 400]
        return result

    gateway.plan = plan
    run, _, payload, records = setup_run(tmp_path, gateway)
    assert len(asyncio.run(run.prepare(payload, records))) == 3
    proof = read_json(tmp_path / "screen-inventory.json")
    assert proof["directed_repair_columns"] == ["C001"]
    assert not proof["mismatched_columns"]
    phases = [json.loads(r.product_information[0])["stage"] for r in gateway.requests]
    assert phases.count("screen_split") == phases.count("screen_inventory") == 2


def test_unresolved_screen_count_stops_before_planning_or_images(tmp_path):
    from app.replica_native import ReplicaSegmentationInvalid

    gateway = SyntheticGateway()
    original = gateway.plan

    async def plan(request):
        result = await original(request)
        if json.loads(request.product_information[0])["stage"] == "screen_inventory":
            result.payload["columns"][0]["screens"].append(
                {
                    "headline": "A missed independent headline",
                    "buyer_question": "An additional question requiring its own screen",
                }
            )
        return result

    gateway.plan = plan
    run, _, payload, records = setup_run(tmp_path, gateway)
    with pytest.raises(ReplicaSegmentationInvalid):
        asyncio.run(run.prepare(payload, records))
    phases = [json.loads(r.product_information[0])["stage"] for r in gateway.requests]
    assert phases == [
        "intake",
        "screen_split",
        "screen_inventory",
        "screen_split",
        "screen_inventory",
    ]
    assert read_json(tmp_path / "screen-inventory.json")["mismatched_columns"] == [
        "C001"
    ]
    assert not gateway.image_requests and not (tmp_path / "session.json").exists()


def test_missing_column_is_a_visual_failure_without_verdict_resampling(tmp_path):
    from app.replica_native import ReplicaSegmentationInvalid

    gateway = SyntheticGateway()
    original = gateway.plan

    async def plan(request):
        result = await original(request)
        if json.loads(request.product_information[0])["stage"] == "screen_inventory":
            result.payload["all_columns_covered"] = False
        return result

    gateway.plan = plan
    run, _, payload, records = setup_run(tmp_path, gateway)
    with pytest.raises(ReplicaSegmentationInvalid):
        asyncio.run(run.prepare(payload, records))
    assert len(gateway.requests) == 3 and not gateway.image_requests


def test_protocol_snapshot_is_frozen_and_cannot_silently_restore_as_legacy(tmp_path):
    run, _, payload, records = setup_run(tmp_path)
    asyncio.run(run.prepare(payload, records))
    snapshot = asyncio.run(run.snapshot())
    assert snapshot["model_protocol"] == protocol_binding()
    assert run_class("exact", snapshot["model_protocol"]) is CompactExactReplicaRun
    assert run_class("exact") is NativeReplicaRun
    legacy = NativeReplicaRun(
        "exact", run.document_id, run.workspace_id, None, run.storage, root=tmp_path
    )
    with pytest.raises(ReplicaNativeError, match="协议"):
        asyncio.run(legacy.restore(snapshot))
    invalid = deepcopy(snapshot)
    invalid["model_protocol"]["content_sha256"] = "0" * 64
    with pytest.raises(CompactResponseInvalid, match="protocol changed"):
        asyncio.run(run.restore(invalid))


def test_invalid_visual_response_stops_after_two_returned_json_attempts(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    original = gateway.plan

    async def malformed(request):
        result = await original(request)
        result.payload["arbitrary_program_path"] = "../untrusted.py"
        return result

    gateway.plan = malformed
    with pytest.raises(CompactResponseInvalid):
        asyncio.run(run.prepare(payload, records))
    assert len(gateway.requests) == 2
    assert not (tmp_path / "session.json").exists()
    assert len(list((tmp_path / "contracts").glob("model-raw-*.json"))) == 2
    assert run.usage and all(r["actual_cost_micros"] is None for r in run.usage)


def test_a_real_failed_verdict_is_preserved_instead_of_being_resampled(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    asyncio.run(run.prepare(payload, records))
    module = run.state()["plan"]["modules"][0]
    artwork = tmp_path / "current.png"
    Image.new("RGB", (1024, 1280), "red").save(artwork)
    value = {
        "fresh_reference_observation": observed("Fresh reference pixels"),
        "fresh_artwork_observation": observed("Fresh red artwork pixels"),
        "comparisons": compared(ARTWORK_DIMENSIONS, "Fresh artwork", True),
        "major_mismatches": ["The current synthetic body has the wrong actual color"],
        "decision": "FAIL",
        "product_geometry_match": False,
    }
    before = len(gateway.requests)

    async def review(request):
        gateway.requests.append(request)
        return SimpleNamespace(
            payload=deepcopy(value),
            error_code=None,
            normalized_usage={"reported": False},
            actual_cost_micros=None,
        )

    gateway.plan = review
    bound = asyncio.run(
        run.ask(
            "exact-pixel-audit-fixture",
            "ignored legacy instruction",
            {"data": {"module": module, "artwork": str(artwork)}},
            paths=[
                *map(Path, run.context["product_paths"]),
                Path(module["reference_path"]),
                artwork,
            ],
        )
    )
    assert (
        bound["decision"] == "FAIL"
        and bound["major_mismatches"] == value["major_mismatches"]
    )
    assert bound["method"] == "AI_FRESH_SIDE_BY_SIDE_PIXEL_AUDIT"
    assert len(gateway.requests) == before + 1


def test_native_generation_repairs_once_and_finalizes_original_output_bytes(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    gateway.reject_artwork_once = True
    asyncio.run(run.prepare(payload, records))
    provider = NativeReplicaProvider(None, gateway, run.storage)

    async def save(*args, **kwargs):
        pass  # Only isolate persistence; execute the actual native state machine.

    provider._save = save
    request = SimpleNamespace(
        workspace_id="ws_test",
        job_id="job_fixture",
        job_item_id="item_fixture",
        attempt_id="attempt_fixture",
    )
    outputs = asyncio.run(provider._exact(run, request))
    assert run.state()["state"] == "FINALIZED" and len(outputs) == 2
    assert len(gateway.image_requests) == 3
    assert [len(m["attempts"]) for m in run.state()["modules"]] == [2, 1]
    assert gateway.artwork_reviews == {"M001": 3, "M002": 1}
    assert all("Return its JSON" not in r.prompt for r in gateway.image_requests)
    assert all(
        "The target language for new poster copy is" in r.prompt
        for r in gateway.image_requests
    )
    assert len({digest(Path(p).read_bytes()) for p in outputs}) == 2
    for path, module in zip(outputs, run.state()["modules"], strict=True):
        assert module["attempts"][-1]["judgment"]["derived_decision"] == "PASS"
        assert (
            digest(Path(path).read_bytes())
            == module["attempts"][-1]["judgment"]["artwork_sha256"]
        )
    repair = next(r for r in gateway.image_requests if "EDIT the supplied" in r.prompt)
    bindings = json.loads(repair.prompt.split("IMAGE_BINDINGS=", 1)[1].splitlines()[0])
    assert bindings[0]["role"] == "current_artwork"
    assert sum(b["role"] == "product_original" for b in bindings) == 1


def test_normal_http_submission_worker_history_and_original_download(
    client, monkeypatch, tmp_path
):
    from sqlalchemy import select

    from app.models import AssetRecord, JobAssetRecord, JobRecord, ReplicaDocumentRecord
    from app.task_runner import MockTaskRunner
    from tests.test_api import dispatch_pending

    client.app.state.settings.reference_remix_provider_enabled = True
    client.app.state.settings.replica_exact_compact_workspaces = ("ws_test",)
    gateway = SyntheticGateway()
    client.app.state.replica_gateway = gateway
    client.app.state.task_runner = MockTaskRunner(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=gateway,
        reference_remix_provider_enabled=True,
        aurora_work_root=tmp_path / "compact-worker",
    )
    original_init = CompactExactReplicaRun.__init__

    def isolated_init(self, *args, **kwargs):
        # Keep the actual CLI artwork filenames below Windows' path limit.
        kwargs.setdefault("root", tmp_path.parent / "n")
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(CompactExactReplicaRun, "__init__", isolated_init)
    ids = []
    for i, size in enumerate([(64, 96), (256, 640)]):
        buffer = BytesIO()
        Image.new("RGB", size, "blue" if i == 0 else "yellow").save(buffer, "PNG")
        uploaded = client.post(
            "/api/v1/workspaces/ws_test/assets",
            headers={"Idempotency-Key": str(uuid4())},
            files={"file": (f"source-{i}.png", buffer.getvalue(), "image/png")},
        )
        assert uploaded.status_code == 201, uploaded.text
        ids.append(uploaded.json()["id"])
    route = "/api/v1/workspaces/ws_test/replica"
    response = client.post(
        route + "/sessions",
        json={
            "request_id": str(uuid4()),
            "replication_method": "exact",
            "product_asset_ids": ids[:1],
            "references": [{"asset_id": ids[1]}],
            "facts": "Supported synthetic product",
            "auto_start_after_plan": True,
        },
    )
    assert response.status_code == 202, response.text
    document = client.get(route + "/documents/" + response.json()["id"]).json()
    assert document["status"] == "generating", document
    assert len(document["payload"]["job_ids"]) == 1
    assert "_exact_model_protocol" not in document["payload"]
    assert len(gateway.requests) == 7
    for _ in range(2):
        client.get(route + "/documents/" + document["id"])
    with client.app.state.session_factory() as session:
        saved = session.get(ReplicaDocumentRecord, document["id"])
        jobs = session.scalars(select(JobRecord)).all()
        assert saved.payload["native_snapshot"]["model_protocol"] == protocol_binding()
        assert len(jobs) == 1 and jobs[0].expected_item_count == 2
        assert jobs[0].configuration["replica_session_id"] == saved.id
    job_id = document["payload"]["job_ids"][0]
    dispatch_pending(client)
    completed = client.get(f"/api/v1/workspaces/ws_test/jobs/{job_id}").json()
    assert completed["status"] == "completed", completed
    assert (
        completed["succeeded_item_count"] == 2 and completed["failed_item_count"] == 0
    )
    assert len(gateway.image_requests) == 2
    restored = client.get(route + "/documents/" + document["id"]).json()
    assert restored["status"] == "completed"
    history = client.get(route + "/sessions").json()
    assert (
        next(r for r in history if r["id"] == document["id"])["status"] == "completed"
    )
    with client.app.state.session_factory() as session:
        outputs = session.execute(
            select(JobAssetRecord, AssetRecord)
            .join(AssetRecord, JobAssetRecord.asset_id == AssetRecord.id)
            .where(
                JobAssetRecord.job_id == job_id,
                JobAssetRecord.direction == "output",
                JobAssetRecord.is_deliverable.is_(True),
            )
        ).all()
        assets = [(a.id, a.sha256) for _, a in outputs]
    assert len(assets) == len({sha for _, sha in assets}) == 2
    for asset_id, sha in assets:
        access = client.post(
            f"/api/v1/workspaces/ws_test/assets/{asset_id}/access-url",
            json={"disposition": "attachment", "variant": "original"},
        )
        assert access.status_code == 200, access.text
        downloaded = client.get(access.json()["url"])
        assert downloaded.status_code == 200
        assert digest(downloaded.content) == sha
        assert "attachment" in downloaded.headers["content-disposition"]
    asyncio.run(client.app.state.task_runner.run(job_id))
    assert len(gateway.image_requests) == 2


def test_repeated_plan_failure_stops_after_one_directed_repair(tmp_path):
    from app.replica_native import ReplicaPlanAuditRejected

    run, gateway, payload, records = setup_run(tmp_path)
    gateway.reject_always = True
    with pytest.raises(ReplicaPlanAuditRejected):
        asyncio.run(run.prepare(payload, records))
    phases = [json.loads(r.product_information[0])["stage"] for r in gateway.requests]
    assert phases.count("plan") == phases.count("review_plan") == 2
    assert not gateway.image_requests
    assert run.state()["state"] == "PLAN_REJECTED"


def test_repeated_pixel_failure_keeps_real_images_and_refuses_delivery(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    gateway.reject_artwork_always = True
    asyncio.run(run.prepare(payload, records))
    provider = NativeReplicaProvider(None, gateway, run.storage)

    async def save(*args, **kwargs):
        pass

    provider._save = save
    request = SimpleNamespace(
        workspace_id="ws_test",
        job_id="job_fixture",
        job_item_id="item_fixture",
        attempt_id="attempt_fixture",
    )
    with pytest.raises(ReplicaNativeError):
        asyncio.run(provider._exact(run, request))
    assert len(gateway.image_requests) == 3
    assert run.state()["state"] == "SET_COMPLETE"
    assert [m["status"] for m in run.state()["modules"]] == [
        "REJECTED_BEST_EFFORT",
        "COMPLETE",
    ]
    assert not (tmp_path / "delivery.json").exists()
    failed = run.state()["modules"][0]
    assert len(failed["attempts"]) == 2
    assert all(Path(a["artwork"]).is_file() for a in failed["attempts"])
    assert all(a["judgment"]["derived_decision"] == "FAIL" for a in failed["attempts"])


def test_server_binding_failure_never_triggers_another_model_request(tmp_path):
    run, gateway, payload, records = setup_run(tmp_path)
    asyncio.run(run.prepare(payload, records))
    before = len(gateway.requests)

    def broken_binding(value):
        raise ReplicaNativeError("Synthetic immutable file binding failed")

    with pytest.raises(ReplicaNativeError, match="immutable"):
        asyncio.run(
            run.ask(
                "exact-product-evidence-bound",
                "ignored",
                {
                    "products": [
                        {
                            "product_index": 0,
                            "sha256": records["asset-0"][2],
                            "width": 64,
                            "height": 96,
                        }
                    ],
                },
                paths=list(map(Path, run.context["product_paths"])),
                bind_evidence=broken_binding,
            )
        )
    assert len(gateway.requests) == before + 1


def test_compact_gateway_uses_its_stage_schema_and_visual_task_prompt(tmp_path):
    from app.xinghe_agent import _planner_prompt_body, _planner_response_format

    run, gateway, payload, records = setup_run(tmp_path)
    asyncio.run(run.prepare(payload, records))
    request = gateway.requests[0]
    envelope = json.loads(request.product_information[0])
    transport = _planner_response_format(request)
    assert transport["type"] == "json_schema"
    assert transport["json_schema"]["schema"] == envelope["response_schema"]
    assert "Server metadata is managed separately" in _planner_prompt_body(request)


def test_generation_language_binding_keeps_the_native_request_unchanged(tmp_path):
    run, _, payload, records = setup_run(tmp_path)
    asyncio.run(run.prepare(payload, records))
    run.context["language"] = "en-US"
    original = (
        "Create ONE complete Chinese ecommerce visual for the current token only.\n"
        "Reference image 2 is the binding composition blueprint;"
    )
    dispatched = run.image_prompt(original)
    assert 'target language for new poster copy is "en-US"' in dispatched
    assert "Reference image 2 is the binding composition blueprint;" in dispatched
    assert "Create ONE complete Chinese" in original
    assert "Return its JSON" not in dispatched


def test_compact_request_crosses_the_actual_gateway_transport_boundary(tmp_path):
    from app.xinghe_agent import TengliOpenAICompatibleGateway

    run, fake, payload, records = setup_run(tmp_path)
    asyncio.run(run.prepare(payload, records))
    request = fake.requests[0]
    expected = asyncio.run(fake.plan(request)).payload
    sent = []

    async def post_json(**kwargs):
        sent.append(kwargs)
        return 200, {
            "id": "synthetic-provider-response",
            "choices": [{"message": {"content": json.dumps(expected)}}],
            "usage": {"prompt_tokens": 13, "completion_tokens": 17},
        }

    gateway = TengliOpenAICompatibleGateway(
        api_key="synthetic-test-credential",
        base_url="https://provider.invalid",
        planner_model="configured-planner",
        image_model="configured-image",
        transport=SimpleNamespace(post_json=post_json),
    )
    result = asyncio.run(gateway.plan(request))
    assert not result.error_code and result.payload == expected
    assert len(sent) == gateway.external_network_request_count == 1
    body = sent[0]["payload"]
    assert body["model"] == "configured-planner"
    assert body["max_completion_tokens"] == 16000
    assert (
        body["response_format"]["json_schema"]["schema"]
        == json.loads(request.product_information[0])["response_schema"]
    )
    assert body["messages"][0]["content"] == request.system_prompt
    assert sum(p["type"] == "image_url" for p in body["messages"][1]["content"]) == 2
    assert result.normalized_usage["input_tokens"] == 13
    assert result.actual_cost_micros is None
