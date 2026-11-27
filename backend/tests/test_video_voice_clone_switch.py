"""声音克隆「新建」开关（用户 11-28 决定保持关闭）。

关闭时：config.available=false、新建被拒且不读录音 / 不冻结积分 / 不调供应商；
已有克隆声音的列表、试听与口播合成照常可用。打开后完整流程走得通（假供应商）。
"""

from uuid import uuid4

from app.config import Settings
from app.models import CreditReservationRecord
from tests.test_video_voice_cloning import create

pytest_plugins = ["tests.test_video_generation", "tests.test_video_voice_cloning"]


def test_clone_creation_is_off_by_default():
    assert Settings().video_voice_clone_enabled is False


def test_switch_off_rejects_creation_without_any_side_effect(clone_env):
    client, _, provider, root, _, _, state = clone_env
    client.app.state.settings.video_voice_clone_enabled = False
    config = client.get(root + "/voice-clone-config").json()
    assert config["available"] is False
    assert config["synthesis_available"] is True
    posts = len(provider.posts)
    response = create(clone_env)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "VIDEO_CLONE_DISABLED"
    assert "暂未开通" in response.json()["error"]["message"]
    assert state["created"] == [] and state["synthesis"] == []
    assert len(provider.posts) == posts
    assert client.get(root + "/voice-clones").json() == []
    with client.app.state.session_factory() as session:
        assert session.query(CreditReservationRecord).count() == 0


def test_switch_on_runs_the_full_flow_with_fake_provider(clone_env):
    client, _, _, root, _, _, state = clone_env
    assert client.get(root + "/voice-clone-config").json()["available"] is True
    created = create(clone_env)
    assert created.status_code == 200, created.text
    assert len(state["created"]) == 1
    assert created.json()["id"] in {
        v["id"] for v in client.get(root + "/voice-clones").json()
    }


def test_existing_clone_keeps_working_after_switch_off(clone_env):
    client, _, _, root, pid, _, state = clone_env
    vid = create(clone_env).json()["id"]
    client.app.state.settings.video_voice_clone_enabled = False
    voices = {v["id"]: v for v in client.get(root + "/voices").json()}
    assert voices[vid]["available"] is True
    preview = client.post(root + f"/voice-clones/{vid}/preview")
    assert preview.status_code == 200, preview.text
    project = client.get(root + "/projects/" + pid).json()
    project["content"]["draft"].update(voiceId=vid, text="中文。")
    saved = client.put(
        root + "/projects/" + pid,
        json={
            "request_id": str(uuid4()),
            "expected_revision": project["revision"],
            "content": project["content"],
        },
    ).json()
    result = client.post(
        root + "/generation-tasks",
        json={
            "request_id": str(uuid4()),
            "kind": "lipsync",
            "avatar_id": "qy-model-11",
            "project_id": pid,
            "expected_revision": saved["project"]["revision"],
        },
    )
    assert result.status_code == 200, result.text
    assert state["synthesis"], "已有克隆声音仍应走合成"
    # 新建仍被拒
    assert create(clone_env).status_code == 403
