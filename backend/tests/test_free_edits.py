"""Each generated image has three free edits; detail pages adopt in place."""

import hashlib
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from sqlalchemy import select

from app.models import (
    AssetRecord,
    CreditLedgerEntryRecord,
    JobAssetRecord,
    JobItemRecord,
    JobRecord,
    WorkspaceCreditAccountRecord,
    utc_now,
)
from tests.test_api import WORKSPACE_ID, local_edit_payload
from tests.test_local_edit_review import _get, _resolve
from tests.test_masked_repair import (
    OfflineMaskedGateway,
    _dispatch,
    _install_runner,
    _png,
    _upload,
    _valid_inputs,
)

BASE = f"/api/v1/workspaces/{WORKSPACE_ID}"


def _detail_set(client, pipeline):
    first, mask, _ = _valid_inputs(client)
    second = _upload(
        client,
        _png((8, 8), (10, 180, 40, 255)),
        media_kind="image",
        filename="page-2.png",
    )
    gateway = OfflineMaskedGateway(review_success=True, outcomes=["success"] * 10)
    _install_runner(client, gateway)
    job_id = f"job_detail_{uuid4().hex[:8]}"
    with client.app.state.session_factory() as session:
        job = JobRecord(
            id=job_id,
            workspace_id=WORKSPACE_ID,
            type="detail_pack",
            status="completed",
            stage="completed",
            progress=100,
            configuration={
                "domestic_detail_pipeline": pipeline,
                "input": {},
                "settings": {},
            },
            expected_item_count=2,
            succeeded_item_count=2,
            failed_item_count=0,
            estimated_credits=30,
            actual_credits=30,
            finished_at=utc_now(),
        )
        session.add(job)
        session.flush()
        for ordinal, asset_id in enumerate([first["id"], second["id"]]):
            item = JobItemRecord(
                id=f"{job_id}_item_{ordinal}",
                item_key=f"page-{ordinal}",
                workspace_id=WORKSPACE_ID,
                job_id=job.id,
                ordinal=ordinal,
                status="succeeded",
                stage="generated",
                configuration={},
                result_source="generated",
                finished_at=utc_now(),
            )
            session.add(item)
            session.flush()
            session.add(
                JobAssetRecord(
                    workspace_id=WORKSPACE_ID,
                    job_id=job.id,
                    job_item_id=item.id,
                    asset_id=asset_id,
                    direction="output",
                    role="detail_page",
                    ordinal=ordinal,
                    is_deliverable=True,
                    validation={"sha256": session.get(AssetRecord, asset_id).sha256},
                )
            )
        session.commit()
    return {
        "job_id": job_id,
        "pages": [first["id"], second["id"]],
        "items": [f"{job_id}_item_0", f"{job_id}_item_1"],
        "mask": mask["id"],
        "gateway": gateway,
    }


@pytest.fixture
def detail_set(client):
    return _detail_set(client, "aurora-domestic-detail-v2.3-authored")


def _edit(client, frame, page, source=None):
    payload = local_edit_payload(source or frame["pages"][page], frame["mask"])
    payload["input"]["replica_output"] = {
        "job_id": frame["job_id"],
        "job_item_id": frame["items"][page],
    }
    return client.post(
        f"{BASE}/jobs", json=payload, headers={"Idempotency-Key": str(uuid4())}
    )


def _balance(client):
    with client.app.state.session_factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, WORKSPACE_ID)
        return account.balance_credits, account.reserved_credits


def _settled(client, job_id):
    with client.app.state.session_factory() as session:
        return [
            row.delta_balance_credits
            for row in session.scalars(
                select(CreditLedgerEntryRecord).where(
                    CreditLedgerEntryRecord.job_id == job_id,
                    CreditLedgerEntryRecord.entry_type == "settle",
                )
            )
        ]


def _allowance(client, asset_id):
    response = client.get(f"{BASE}/assets/{asset_id}/free-edits")
    assert response.status_code == 200, response.text
    return response.json()


def _generate(client, frame, page, source=None):
    """Create one edit and run it to its candidate."""
    created = _edit(client, frame, page, source=source)
    assert created.status_code == 202, created.text
    assert _dispatch(client) == 1
    job = _get(client, created.json()["id"])
    image = next(r for r in job["assets"] if r["role"] == "locked_candidate")
    return job, image


def test_page_edit_is_free_and_replaces_the_page_in_order(client, detail_set):
    frame = detail_set
    before = _balance(client)
    assert _allowance(client, frame["pages"][1])["remaining"] == 3
    created = _edit(client, frame, 1)
    assert created.status_code == 202, created.text
    job = created.json()
    assert job["cost"]["estimated_credits"] == 0
    assert job["configuration"]["_local_edit_free_of_asset_id"] == frame["pages"][1]
    assert _dispatch(client) == 1
    job = _get(client, job["id"])
    assert job["status"] == "awaiting_final_review", job
    image = next(row for row in job["assets"] if row["role"] == "locked_candidate")
    # The free candidate is viewable before adoption, like a paid one.
    access = client.post(
        f"{BASE}/assets/{image['asset_id']}/access-url",
        json={"disposition": "inline"},
    )
    assert access.status_code == 200, access.text
    accepted = _resolve(client, job, image, "accept")
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["cost"]["actual_credits"] == 0

    parent = _get(client, frame["job_id"])
    outputs = sorted(
        (
            r
            for r in parent["assets"]
            if r["is_deliverable"] and r["direction"] == "output"
        ),
        key=lambda r: r["ordinal"],
    )
    assert [r["asset_id"] for r in outputs] == [frame["pages"][0], image["asset_id"]]
    assert [r["ordinal"] for r in outputs] == [0, 1]
    assert parent["status"] == "completed" and parent["cost"]["actual_credits"] == 30
    assert _balance(client) == before
    assert _settled(client, job["id"]) == [0]
    # The edited page continues the allowance of the page it came from.
    assert _allowance(client, image["asset_id"])["remaining"] == 2

    archive = client.get(f"{BASE}/jobs/{frame['job_id']}/deliverables.zip")
    assert archive.status_code == 200, archive.text
    with ZipFile(BytesIO(archive.content)) as zipped:
        names = sorted(n for n in zipped.namelist() if n.endswith(".png"))
        digests = [hashlib.sha256(zipped.read(n)).hexdigest() for n in names]
    assert image["validation"]["sha256"] in digests and len(digests) == 2


def test_three_free_edits_per_generated_image_then_normal_price(client, detail_set):
    frame = detail_set
    balance, _ = _balance(client)
    first, image = _generate(client, frame, 0)
    assert first["cost"]["estimated_credits"] == 0
    # Regenerating with a new instruction spends the second free use.
    retried = client.post(
        f"{BASE}/jobs/{first['id']}/retry",
        headers={"Idempotency-Key": str(uuid4())},
        json={"scope": "failed", "local_edit_instruction": "把标题改为清爽保湿"},
    )
    assert retried.status_code == 201, retried.text
    second = retried.json()
    assert second["cost"]["estimated_credits"] == 0
    assert _dispatch(client) == 1
    second = _get(client, second["id"])
    image = next(r for r in second["assets"] if r["role"] == "locked_candidate")
    assert _resolve(client, second, image, "accept").status_code == 202
    assert _allowance(client, frame["pages"][0]) == {
        "asset_id": frame["pages"][0],
        "eligible": True,
        "limit": 3,
        "used": 2,
        "remaining": 1,
    }
    # Editing the adopted result spends the same image's last free use.
    third, image = _generate(client, frame, 0, source=image["asset_id"])
    assert third["cost"]["estimated_credits"] == 0
    assert _resolve(client, third, image, "accept").status_code == 202
    assert _balance(client)[0] == balance
    assert _allowance(client, image["asset_id"])["remaining"] == 0
    fourth, _ = _generate(client, frame, 0, source=image["asset_id"])
    assert fourth["cost"]["estimated_credits"] == 5
    assert "_local_edit_free_of_asset_id" not in fourth["configuration"]
    assert _settled(client, fourth["id"]) == [-5]
    assert _balance(client)[0] == balance - 5
    # The other page keeps its own three.
    assert _allowance(client, frame["pages"][1])["remaining"] == 3


def test_failed_edit_without_a_generation_gives_its_use_back(client, detail_set):
    frame = detail_set
    frame["gateway"].outcomes = ["bad_request"] + ["success"] * 5
    created = _edit(client, frame, 0)
    assert created.status_code == 202, created.text
    assert _allowance(client, frame["pages"][0])["remaining"] == 2
    _dispatch(client)
    failed = _get(client, created.json()["id"])
    assert failed["status"] == "failed", failed["status"]
    assert _allowance(client, frame["pages"][0])["remaining"] == 3


def test_uploaded_images_have_no_free_edits(client):
    source, mask, _ = _valid_inputs(client)
    assert _allowance(client, source["id"])["eligible"] is False
    plain = client.post(
        f"{BASE}/jobs",
        json=local_edit_payload(source["id"], mask["id"]),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert plain.status_code == 202, plain.text
    assert plain.json()["cost"]["estimated_credits"] == 5
    assert "_local_edit_free_of_asset_id" not in plain.json()["configuration"]


def test_any_feature_output_is_free_to_edit_without_binding(client):
    frame = _detail_set(client, "aurora-domestic-detail-v4.3.1")
    # Native detail pages cannot be replaced in place ...
    assert _edit(client, frame, 0).status_code == 404
    # ... but editing the generated image itself still uses its free edits.
    plain = client.post(
        f"{BASE}/jobs",
        json=local_edit_payload(frame["pages"][0], frame["mask"]),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert plain.status_code == 202, plain.text
    assert plain.json()["cost"]["estimated_credits"] == 0


def test_edit_must_start_from_the_current_page(client, detail_set):
    frame = detail_set
    response = _edit(client, frame, 0, source=frame["pages"][1])
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "REPLICA_SOURCE_CHANGED"
