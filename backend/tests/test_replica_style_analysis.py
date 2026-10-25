"""Synthetic evidence gaps, real recrops and durable stage recovery."""

import asyncio
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path
from shutil import rmtree
from uuid import uuid4

import pytest
from PIL import Image, ImageDraw

from app.replica_native import NativeReplicaRun, ReplicaNativeError, digest, write_json
from app.replica_style_analysis import (
    CURSOR,
    FLAGS,
    PROVENANCE,
    VERSION,
    StyleEvidenceInvalid,
    StyleReplicaRun,
    crop_errors,
    revision_checkpoint,
)
from app.storage import ImageValidator, LocalImageStorage


def setup_run(tmp_path):
    root = tmp_path / "run"
    run = StyleReplicaRun(
        "style",
        "rep_" + uuid4().hex,
        "ws_test",
        None,
        LocalImageStorage(tmp_path / "objects", ImageValidator(1_000_000, 1_000_000)),
        root=root,
    )
    reference = root / "inputs/reference-00.img"
    reference.parent.mkdir()
    image = Image.new("RGB", (64, 128), "red")
    ImageDraw.Draw(image).rectangle((0, 64, 63, 127), fill="blue")
    image.save(reference, "PNG")
    product = root / "inputs/product-00.img"
    Image.new("RGB", (32, 32), "yellow").save(product, "PNG")
    refs = {
        "R01": {
            "id": "R01",
            "role": "benchmark_reference",
            "path": str(reference),
            "sha256": digest(reference.read_bytes()),
        }
    }
    run.run = root / "native"
    write_json(
        run.run / "artifacts/workflow.json",
        {
            "state": "ROUTE_CLASSIFIED",
            "inputs": list(refs.values()),
        },
    )
    run.context = {
        "user_facts": "Synthetic confirmed geometry",
        "references": [{"asset_id": "ref"}],
        "language": "zh-CN",
        "platform": "tmall",
    }
    write_json(root / "context.json", run.context)
    crop = run.crop(reference, [0, 0, 16, 16], root / "crops/style-C01.png")
    analysis = {
        "overview_detection": {
            "panels": [
                {
                    "panel_id": "B01",
                    "reference_input_id": "R01",
                    "bbox": [0, 0, 64, 64],
                },
                {
                    "panel_id": "B02",
                    "reference_input_id": "R01",
                    "bbox": [0, 64, 64, 128],
                },
            ]
        },
        "source_content_analysis": {
            "sequence": [
                {"id": "T01", "source_panel_ids": ["B01"]},
                {"id": "T02", "source_panel_ids": ["B02"]},
            ]
        },
        "units": [
            {
                "id": "C01",
                "reference_input_id": "R01",
                "source_crop_path": str(crop),
                "source_content_step_ids": ["T01"],
                "review_status": "visual_model",
                **dict.fromkeys(FLAGS, False),
            }
        ],
    }
    payload = {
        "product_asset_ids": ["product"],
        "references": [{"asset_id": "ref"}],
        "facts": run.context["user_facts"],
        "language": "zh-CN",
        "platform_code": "tmall",
    }
    records = {
        "product": (None, None, digest(product.read_bytes())),
        "ref": (None, None, digest(reference.read_bytes())),
    }
    return run, analysis, refs, payload, records


def corrected(analysis):
    value = deepcopy(analysis)
    value["units"].append(
        {**deepcopy(value["units"][0]), "id": "C02", "source_content_step_ids": ["T02"]}
    )
    value["crop_specs"] = [
        {"id": "C02", "reference_input_id": "R01", "bbox": [0, 64, 16, 80]}
    ]
    return value


def test_missing_source_step_is_detected_before_any_page_planning(tmp_path):
    run, analysis, refs, _, _ = setup_run(tmp_path)
    provenance = json.loads((run.root / PROVENANCE).read_text())
    errors = crop_errors(analysis, provenance, refs)
    assert len(errors) == 1 and errors[0].startswith("T02:")
    # Reusing a first-panel swatch for the second panel cannot fix coverage.
    analysis["units"][0]["source_content_step_ids"].append("T02")
    assert crop_errors(analysis, provenance, refs) == errors
    analysis["units"][0]["reference_input_id"] = "R_OTHER"
    assert any(
        "registered reference" in e for e in crop_errors(analysis, provenance, refs)
    )


def test_repair_physically_crops_then_freshly_reviews_returned_pixels(
    tmp_path, monkeypatch
):
    run, analysis, refs, _, _ = setup_run(tmp_path)
    calls = []

    async def ask(self, stage, instruction, context, **kwargs):
        calls.append(stage)
        if stage == "style-crop-repair-0":
            assert any(e.startswith("T02:") for e in context["validation_errors"])
            return corrected(context["analysis"])
        if stage == "style-crop-review-1":
            actual = Path(context["analysis"]["units"][1]["source_crop_path"])
            with Image.open(actual) as image:
                assert image.getpixel((0, 0)) == (0, 0, 255)
            assert (
                context["analysis"]["source_content_analysis"]
                == analysis["source_content_analysis"]
            )
        return deepcopy(context["analysis"])

    monkeypatch.setattr(NativeReplicaRun, "ask", ask)
    result = asyncio.run(run._review_crops(analysis))
    assert calls == [
        "style-crop-review-0",
        "style-crop-repair-0",
        "style-crop-review-1",
    ]
    provenance = json.loads((run.root / PROVENANCE).read_text())
    assert not crop_errors(result, provenance, refs)
    assert len(result["units"]) == 2


@pytest.mark.parametrize(
    "defect", ["flags_only", "delete_source_step", "contamination"]
)
def test_relabeling_or_changing_source_observations_never_repairs_crops(
    tmp_path, monkeypatch, defect
):
    run, analysis, _, _, _ = setup_run(tmp_path)
    original_source = deepcopy(analysis["source_content_analysis"])

    async def ask(self, stage, instruction, context, **kwargs):
        value = deepcopy(context["analysis"])
        if defect == "flags_only":
            value["units"][0]["source_content_step_ids"] = ["T01", "T02"]
        elif defect == "delete_source_step":
            value["source_content_analysis"]["sequence"] = value[
                "source_content_analysis"
            ]["sequence"][:1]
        else:
            value["units"][0]["source_product_presence"] = True
        return value

    monkeypatch.setattr(NativeReplicaRun, "ask", ask)
    with pytest.raises(StyleEvidenceInvalid):
        asyncio.run(run._review_crops(analysis))
    assert run.cursor["source_analysis"]["source_content_analysis"] == original_source
    assert not (run.root / "crops/style-C02.png").exists()


def test_failed_crop_stage_restores_after_temp_removal_without_new_intake(
    tmp_path, monkeypatch
):
    run, analysis, _, payload, records = setup_run(tmp_path)
    run.cursor.update(stage="crop_review", source_analysis=analysis, candidate=analysis)
    asyncio.run(run.checkpoint())
    snapshot = asyncio.run(run.snapshot())
    original_root = run.root
    rmtree(original_root)
    restored = StyleReplicaRun(
        "style", run.document_id, "ws_test", None, run.storage, root=original_root
    )
    asyncio.run(restored.restore(snapshot))
    calls = []

    async def review(self, current):
        assert current == analysis
        calls.append("crop_stage_only")
        raise StyleEvidenceInvalid("Synthetic stop after restored crop stage")

    async def forbidden(*args, **kwargs):
        raise AssertionError("Intake/physical analysis must not restart")

    monkeypatch.setattr(StyleReplicaRun, "_review_crops", review)
    monkeypatch.setattr(NativeReplicaRun, "prepare", forbidden)
    with pytest.raises(StyleEvidenceInvalid):
        asyncio.run(restored.prepare(payload, records))
    assert calls == ["crop_stage_only"]
    assert (original_root / "crops/style-C01.png").is_file()
    records["ref"] = (None, None, "0" * 64)
    with pytest.raises(ReplicaNativeError, match="bytes or order"):
        asyncio.run(restored.prepare(payload, records))
    assert calls == ["crop_stage_only"]


def test_explicit_plan_revision_keeps_failed_audit_and_skips_completed_stages(
    tmp_path, monkeypatch
):
    run, _, _, payload, records = setup_run(tmp_path)
    write_json(run.run / "artifacts/workflow.json", {"state": "PLAN_AUDIT_REQUIRED"})
    failed = {
        "pass": False,
        "review_kind": "visual_model",
        "evidence": ["Synthetic rejected layout"],
    }
    write_json(run.root / "contracts/prior-audit.json", failed)
    run.cursor.update(stage="plan", last_plan_audit=failed)
    asyncio.run(run.checkpoint())
    snapshot = asyncio.run(run.snapshot())
    assert revision_checkpoint({"_analysis_checkpoint": snapshot})
    rmtree(run.root)
    restored = StyleReplicaRun(
        "style", run.document_id, "ws_test", None, run.storage, root=run.root
    )
    asyncio.run(restored.restore(snapshot))

    async def planning(self, previous_audit):
        assert previous_audit == failed
        assert self.state()["state"] == "PLAN_AUDIT_REQUIRED"
        return [{"unit_id": "synthetic"}]

    async def forbidden(*args, **kwargs):
        raise AssertionError("Completed intake/facts/crops must not repeat")

    monkeypatch.setattr(NativeReplicaRun, "prepare", forbidden)
    monkeypatch.setattr(StyleReplicaRun, "finish_style_planning", planning)
    result = asyncio.run(restored.prepare(payload, records))
    assert result == [{"unit_id": "synthetic"}]
    assert (restored.root / "contracts/prior-audit.json").read_bytes() == snapshot[
        "files"
    ]["contracts/prior-audit.json"]["text"].encode()
    bad = deepcopy(snapshot)
    bad["files"][CURSOR]["sha256"] = "0" * 64
    assert not revision_checkpoint({"_analysis_checkpoint": bad})
    assert restored.cursor == {
        "version": VERSION,
        "stage": "approved",
        "last_plan_audit": failed,
    }


@pytest.mark.parametrize(
    "invalid", [None, "facts_changed", "checkpoint_corrupt", "has_job"]
)
def test_normal_style_revision_route_is_bound_and_idempotent(
    client, monkeypatch, tmp_path, invalid
):
    from app import replica
    from app.models import ReplicaDocumentRecord

    run, _, _, payload, _ = setup_run(tmp_path)
    run.cursor.update(stage="plan", last_plan_audit={"pass": False})
    asyncio.run(run.checkpoint())
    snapshot = asyncio.run(run.snapshot())
    payload.update(
        replication_method="style",
        _analysis_checkpoint=snapshot,
        error_code="REPLICA_PLAN_AUDIT_REJECTED",
        job_ids=[],
        analysis_attempt_id="previous",
    )
    payload["_analysis_input_hash"] = replica._analysis_input_hash(payload)
    if invalid == "facts_changed":
        payload["facts"] += " changed"
    elif invalid == "checkpoint_corrupt":
        payload["_analysis_checkpoint"]["files"][CURSOR]["sha256"] = "0" * 64
    elif invalid == "has_job":
        payload["job_ids"] = ["already_started"]
    original = deepcopy(payload)
    calls = []

    async def analyse(app, document_id, attempt_id):
        calls.append((document_id, attempt_id))

    monkeypatch.setattr(replica, "_analyse", analyse)
    with client.app.state.session_factory() as session:
        session.add(
            ReplicaDocumentRecord(
                id=run.document_id,
                workspace_id="ws_test",
                created_by="usr_test",
                kind="session",
                fingerprint=uuid4().hex * 2,
                status="failed",
                payload=payload,
            )
        )
        session.commit()
    base = "/api/v1/workspaces/ws_test/replica"
    wire = client.get(base + "/documents/" + run.document_id).json()
    assert wire["payload"]["analysis_revision_available"] is (invalid is None)
    response = client.post(base + "/sessions/" + run.document_id + "/revise", json={})
    if invalid:
        assert response.status_code == 409 and not calls
        with client.app.state.session_factory() as session:
            assert (
                session.get(ReplicaDocumentRecord, run.document_id).payload == original
            )
        return
    assert response.status_code == 202, response.text
    assert "_style_analysis_revision" not in response.json()["payload"]
    assert "_exact_model_protocol" not in response.json()["payload"]
    again = client.post(base + "/sessions/" + run.document_id + "/revise", json={})
    assert again.status_code == 202 and len(calls) == 1
    with client.app.state.session_factory() as session:
        saved = session.get(ReplicaDocumentRecord, run.document_id).payload
        assert saved["_analysis_checkpoint"] == original["_analysis_checkpoint"]
        assert saved["_style_analysis_revision"][
            "parent_snapshot_sha256"
        ] == replica._hash(snapshot)
        assert "_exact_model_protocol" not in saved


def test_repaired_step_bindings_pass_the_unchanged_native_request_compiler(tmp_path):
    run, analysis, _, _, _ = setup_run(tmp_path)
    for i, step in enumerate(analysis["source_content_analysis"]["sequence"], 1):
        step.update(source_reference_ids=["R01"], source_order=i)
    script = """
import json,sys
sys.path.insert(0,sys.argv[1])
from workflow import target_reference_bindings
value=json.loads(sys.argv[2]);units=value['units']
for unit in units:
 unit.update(path=unit['source_crop_path'],sha256='a'*64)
try:
 refs=target_reference_bindings({'reference_content_analysis':value['source_content_analysis']},
       {'units':units},[{'source_content_step_ids':['T01','T02']}])
 print(json.dumps({'passed':True,'count':len(refs)}))
except ValueError:
 print(json.dumps({'passed':False}))
"""
    skill = (
        Path(__file__).parents[1]
        / "skill_sources/all-category-style-benchmark-still/scripts"
    )

    def native(value):
        proc = subprocess.run(
            [sys.executable, "-c", script, str(skill), json.dumps(value)],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout)

    assert native(analysis) == {"passed": False}
    repaired = corrected(analysis)
    run._apply_specs(repaired)
    assert native(repaired) == {"passed": True, "count": 2}
