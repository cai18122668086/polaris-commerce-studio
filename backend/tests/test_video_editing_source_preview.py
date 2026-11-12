"""Restored source previews keep source ownership and immutable-byte checks."""

from pathlib import Path

from app.video_editing_task_models import EditingSourceRecord
from tests.test_video_editing_tasks import setup_source

pytest_plugins = ["tests.test_video_projects"]


def test_restored_source_has_range_support_and_rejects_foreign_or_changed_bytes(
    video, tmp_path
):
    client, _, ws, _, _, _, source = setup_source(video, tmp_path)
    url = f"/api/v1/video-studio/workspaces/{ws}/editing-sources/{source}/video"
    response = client.get(url, headers={"Range": "bytes=0-4"})
    assert response.status_code == 206 and len(response.content) == 5
    assert client.get(url.replace(ws, "ws_foreign")).status_code in {403, 404}
    with client.app.state.session_factory() as session:
        stored = session.get(EditingSourceRecord, source)
        Path(stored.media_path).write_bytes(b"changed source")
    assert client.get(url).status_code == 409
