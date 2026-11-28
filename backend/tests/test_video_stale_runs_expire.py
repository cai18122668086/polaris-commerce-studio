"""C5 (第 2 点): an AI 润色 or AI 配图 whose background run died with the API
fails on the next query and its credit hold is released."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import update

from app import video_avatar_polish
from app.models import utc_now
from app.video_avatar_polish_models import VideoAvatarPolishRecord
from app.video_editing_task_models import EditingImageRequestRecord
from tests.test_video_avatar_polish import holds, polish_env, submit  # noqa: F401
from tests.test_video_editing_supplement import _holds as image_holds
from tests.test_video_editing_supplement import api  # noqa: F401
from tests.test_video_projects import base

pytest_plugins = ["tests.test_video_generation", "tests.test_video_projects"]


def test_interrupted_polish_fails_after_30_minutes_and_frees_its_hold(
    polish_env, monkeypatch  # noqa: F811
):
    client, _, root, fake, ws = polish_env
    # The API restarted before the background run started: rows stay queued.
    monkeypatch.setattr(video_avatar_polish, "process", lambda *a, **k: None)
    request_id = str(uuid4())
    assert submit(client, root, request_id=request_id).status_code == 200
    listed = lambda: client.get(  # noqa: E731
        root + "/avatar-polishes", params={"request_id": request_id}
    ).json()
    assert [row["status"] for row in listed()] == ["queued", "queued"]
    assert holds(client, ws)[2] == ["active", "active"]
    with client.app.state.session_factory() as session:
        session.execute(
            update(VideoAvatarPolishRecord)
            .where(VideoAvatarPolishRecord.request_id == request_id)
            .values(updated_at=utc_now() - timedelta(minutes=10))
        )
        session.commit()
    assert [row["status"] for row in listed()] == ["queued", "queued"]  # not yet
    with client.app.state.session_factory() as session:
        session.execute(
            update(VideoAvatarPolishRecord)
            .where(VideoAvatarPolishRecord.request_id == request_id)
            .values(status="running", updated_at=utc_now() - timedelta(minutes=40))
        )
        session.commit()
    rows = listed()
    assert [row["status"] for row in rows] == ["failed", "failed"]
    assert all("中断" in row["message"] for row in rows)
    assert holds(client, ws) == (100, 0, ["released", "released"])
    assert fake.calls == []


def test_interrupted_ai_image_fails_after_15_minutes_and_frees_its_hold(
    api, monkeypatch  # noqa: F811
):
    from app import video_editing_supplement_routes as routes

    client, ws, settings, project = api
    settings.video_supplement_ai_image_enabled = True
    settings.image_api_key = type(settings.image_api_key)("k-test")
    monkeypatch.setattr(routes, "_spawn", lambda request, s, ids: None)  # run lost
    url = base(ws) + "/editing-supplement/ai-images"
    item = {
        "request_id": str(uuid4()),
        "sentence_index": 1,
        "sentence": "一抹就化开",
        "subject": "白色面霜化开",
    }
    created = client.post(
        url, json={"project_id": project, "work_item_ref": "wi-1", "items": [item]}
    )
    assert created.status_code == 201, created.text
    image_id = created.json()["items"][0]["id"]
    assert image_holds(client, [image_id]) == [("editing_auto_image", "active", 0)]
    with client.app.state.session_factory() as session:
        session.execute(
            update(EditingImageRequestRecord)
            .where(EditingImageRequestRecord.id == image_id)
            .values(status="running", updated_at=utc_now() - timedelta(minutes=20))
        )
        session.commit()
    status = client.get(url, params={"project_id": project, "ids": [image_id]})
    row = status.json()["items"][0]
    assert row["status"] == "failed" and "未扣积分" in row["error"]
    assert image_holds(client, [image_id]) == [("editing_auto_image", "released", 0)]
