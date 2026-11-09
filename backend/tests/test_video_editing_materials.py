"""Project and immutable-byte boundaries without any provider or renderer."""

from io import BytesIO
from uuid import uuid4

import pytest
from PIL import Image

from app.video_editing_materials import material_file, project_material_files
from app.video_editing_pipeline import EditingFailure
from app.video_editing_task_models import EditingSourceRecord
from app.video_editing_worker import stage_plan_materials
from tests.test_auth_external import verified_identity
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
