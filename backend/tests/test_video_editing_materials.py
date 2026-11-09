"""Project and immutable-byte boundaries without any provider or renderer."""

from datetime import UTC, datetime
from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image

from app.models import AssetRecord, JobAssetRecord, JobItemRecord, JobRecord
from app.services import new_id
from app.video_editing_materials import (
    material_cards,
    material_file,
    project_material_files,
)
from app.video_editing_pipeline import EditingFailure
from app.video_editing_task_models import EditingSourceRecord
from app.video_editing_worker import stage_plan_materials
from tests.test_auth_external import verified_identity
from tests.test_processing_consent import CHOICE
from tests.test_processing_consent import PATH as CONSENT_PATH
from tests.test_video_editing_tasks import setup_source
from tests.test_video_projects import base, payload

pytest_plugins = ["tests.test_video_projects"]


def test_original_replay_project_access_and_frozen_material_bytes(video, tmp_path):
    client, auth, ws, user, settings, project, source_id = setup_source(video, tmp_path)
    data = {
        "request_id": str(uuid4()),
        "label": "当前图片",
        "description": "图片测试合同",
    }
    image = BytesIO()
    Image.new("RGB", (12, 12), "red").save(image, format="PNG")
    content = image.getvalue()
    files = {"file": ("current.png", content, "image/png")}
    url = base(ws) + f"/projects/{project}/editing-materials"
    original = client.post(url, data=data, files=files)
    assert original.status_code == 201, original.text
    row = original.json()
    assert client.post(url, data=data, files=files).json() == row
    assert (
        client.post(url, data={**data, "label": "修改"}, files=files).status_code == 409
    )
    assert client.get(row["url"]).content == content
    assert client.get(url).json()["items"] == [row]
    assert str(tmp_path) not in original.text

    other = str(uuid4())
    assert (
        client.put(base(ws) + "/projects/" + other, json=payload()).status_code == 200
    )
    assert client.get(row["url"].replace(project, other)).status_code == 404
    auth.identity = verified_identity(
        primary_user_id="other-user", email="1474953130@qq.com"
    )
    assert client.get(row["url"]).status_code in (403, 404)

    factory = client.app.state.session_factory
    aid = row["asset_id"]
    with factory() as session:
        source = session.get(EditingSourceRecord, source_id)
        assert source is not None
        assets = project_material_files(session, settings, source, {aid})
        plan = {
            "asset_files": assets,
            "source_id": source_id,
            "workspace_id": ws,
            "owner_user_id": source.owner_user_id,
            "project_id": project,
            "semantic": {"beats": [{"asset_ids": [aid]}]},
        }
        staged = stage_plan_materials(
            session, tmp_path / "run", plan, settings, lambda: None
        )
        assert staged[aid]["path"] != assets[aid]["path"]
        material_file(settings, row["id"], row["mime"]).write_bytes(b"z" * len(content))
        with pytest.raises(EditingFailure, match="EDITING_MATERIAL_CHANGED"):
            stage_plan_materials(
                session, tmp_path / "tampered", plan, settings, lambda: None
            )
        original_only = tmp_path / "original-only"
        plan["semantic"] = {"beats": [{"id": "picture", "asset_ids": [aid]}]}
        assert (
            stage_plan_materials(
                session, original_only, plan, settings, lambda: None, {"picture"}
            )
            == assets
        )
        assert not original_only.exists()


def attach_creative_output(
    session, workspace, asset, *, direction="output", title=None
):
    job_id, item_id = new_id("job"), new_id("item")
    finished = datetime.now(UTC)
    session.add(
        JobRecord(
            id=job_id,
            workspace_id=workspace,
            type="creative_image",
            status="completed",
            display_name=title,
            expected_item_count=1,
            succeeded_item_count=1,
            finished_at=finished,
        )
    )
    session.flush()
    session.add(
        JobItemRecord(
            id=item_id,
            job_id=job_id,
            workspace_id=workspace,
            item_key="image",
            ordinal=0,
            status="succeeded",
            finished_at=finished,
        )
    )
    session.flush()
    session.add(
        JobAssetRecord(
            job_id=job_id,
            job_item_id=item_id,
            workspace_id=workspace,
            asset_id=asset.id,
            direction=direction,
            role="creative_image_result",
            is_deliverable=True,
        )
    )
    asset.origin_kind = "generated"
    session.commit()
    return job_id


def test_import_creative_delivery_checks_original_and_preserves_provenance(
    video, tmp_path
):
    client, auth, ws, _, settings, project, source_id = setup_source(video, tmp_path)
    image = BytesIO()
    Image.new("RGB", (12, 12), "green").save(image, format="PNG")
    content = image.getvalue()
    assert client.post(CONSENT_PATH, json=CHOICE).json()["accepted"] is True
    upload = client.post(
        f"/api/v1/workspaces/{ws}/assets",
        headers={"Idempotency-Key": str(uuid4())},
        files={"file": ("scene.png", content, "image/png")},
    )
    assert upload.status_code == 201, upload.text
    asset_id = upload.json()["id"]
    factory = client.app.state.session_factory
    with factory() as session:
        asset = session.get(AssetRecord, asset_id)
        job_id = attach_creative_output(session, ws, asset)
        input_job = attach_creative_output(session, ws, asset, direction="input")
        storage_file = settings.storage_dir / asset.object_key

    root = base(ws) + f"/projects/{project}/editing-materials"
    url = root + "/image-results"
    body = {
        "job_id": job_id,
        "asset_id": asset_id,
        "request_id": str(uuid4()),
        "label": "洗水果",
        "description": "水果放在水里，场景示意。",
    }
    assert client.post(url, json={**body, "job_id": input_job}).status_code == 404
    assert (
        client.post(url, json={**body, "asset_id": new_id("asset")}).status_code == 404
    )
    changed = BytesIO()
    Image.new("RGB", (12, 12), "blue").save(changed, format="PNG")
    storage_file.write_bytes(changed.getvalue())
    assert (
        client.post(url, json=body).json()["error"]["code"]
        == "EDITING_IMAGE_RESULT_CHANGED"
    )
    assert client.get(root).json()["items"] == []
    storage_file.write_bytes(content)

    result = client.post(url, json=body)
    assert result.status_code == 201, result.text
    row = result.json()
    assert (row["source_job_id"], row["source_asset_id"]) == (job_id, asset_id)
    assert client.get(row["url"]).content == content
    assert client.post(url, json={**body, "description": "不同"}).status_code == 409
    assert client.get(root).json()["items"] == [row]
    with factory() as session:
        source = session.get(EditingSourceRecord, source_id)
        aid = row["asset_id"]
        files = project_material_files(
            session, settings, source, {aid}, verify_bytes=True
        )
        assert material_cards(files)[0]["scope"].startswith("generated illustration")
        asset = session.get(AssetRecord, asset_id)
        asset.deleted_at = datetime.now(UTC)
        session.commit()
    assert (
        client.post(url, json={**body, "request_id": str(uuid4())}).status_code == 404
    )
    assert client.post(url, json=body).json() == row
    assert client.get(row["url"]).content == content
    auth.identity = verified_identity(
        primary_user_id="other-user", email="1474953130@qq.com"
    )
    assert client.post(url, json=body).status_code in (403, 404)
