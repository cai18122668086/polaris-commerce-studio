"""固定形象 persona（契约 C3）：隔离、重名、幂等、依赖对象被删除后的状态。"""

from uuid import uuid4

from app.video_generation_models import VideoAvatarRecord, VideoGenerationRecord
from app.video_persona_models import VideoPersonaRecord
from tests.test_auth_external import verified_identity
from tests.test_video_avatar_uploads import upload

pytest_plugins = ["tests.test_video_generation"]

PUBLIC_AVATAR = "qy-model-11"
PUBLIC_VOICE = "qy-voice-1"


def body(**changes):
    return {
        "request_id": str(uuid4()),
        "name": "店长小林",
        "avatar_id": PUBLIC_AVATAR,
        "voice_id": PUBLIC_VOICE,
        **changes,
    }


def create(env, **changes):
    client, _, _, root, _, _ = env
    return client.post(root + "/personas", json=body(**changes))


def test_create_lists_with_cover_voice_name_and_is_idempotent(video_gen):
    client, _, provider, root, _, _ = video_gen
    payload = body(emotion="愉快")
    first = client.post(root + "/personas", json=payload)
    assert first.status_code == 200, first.text
    data = first.json()
    assert data["available"] is True and data["unavailable_reason"] is None
    assert data["avatar_id"] == PUBLIC_AVATAR and data["voice_id"] == PUBLIC_VOICE
    assert data["voice_name"] == "温柔女声 · 居家好物"
    assert data["cover_url"].endswith(f"/avatars/{PUBLIC_AVATAR}/cover")
    assert data["avatar_preview_url"].endswith(f"/avatars/{PUBLIC_AVATAR}/preview")
    assert data["emotion"] == "愉快"
    again = client.post(root + "/personas", json=payload)
    assert again.status_code == 200 and again.json()["id"] == data["id"]
    changed = client.post(root + "/personas", json={**payload, "name": "另一个"})
    assert changed.status_code == 409
    assert changed.json()["error"]["code"] == "VIDEO_REQUEST_REUSED"
    listed = client.get(root + "/personas").json()
    assert [row["id"] for row in listed] == [data["id"]]
    assert client.get(root + f"/personas/{data['id']}").json()["name"] == "店长小林"
    # 不向供应商发起任何付费请求
    assert provider.posts == []


def test_duplicate_name_is_rejected_on_create_and_rename(video_gen):
    client, _, _, root, _, _ = video_gen
    first = create(video_gen).json()
    duplicate = create(video_gen, name="  店长小林 ")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "VIDEO_PERSONA_NAME_TAKEN"
    second = create(video_gen, name="居家主播").json()
    clash = client.patch(root + f"/personas/{second['id']}", json={"name": "店长小林"})
    assert clash.status_code == 409
    same = client.patch(root + f"/personas/{first['id']}", json={"name": "店长小林"})
    assert same.status_code == 200
    renamed = client.patch(root + f"/personas/{second['id']}", json={"name": "新名字"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "新名字"
    assert create(video_gen, name="   ").status_code == 422
    assert {row["name"] for row in client.get(root + "/personas").json()} == {
        "店长小林",
        "新名字",
    }


def test_personas_are_isolated_per_user(video_gen):
    client, auth, _, root, _, _ = video_gen
    mine = create(video_gen).json()
    with client.app.state.session_factory() as session:
        # 同一工作区的成员身份不足以看到别人的固定形象
        session.get(VideoPersonaRecord, mine["id"]).owner_user_id = "different-owner"
        session.commit()
    assert client.get(root + "/personas").json() == []
    assert client.get(root + f"/personas/{mine['id']}").status_code == 404
    assert (
        client.patch(
            root + f"/personas/{mine['id']}", json={"name": "抢走"}
        ).status_code
        == 404
    )
    assert client.delete(root + f"/personas/{mine['id']}").status_code == 404
    # 不同用户可以用同一个名字，互不影响
    assert create(video_gen).status_code == 200
    with client.app.state.session_factory() as session:
        assert session.get(VideoPersonaRecord, mine["id"]).name == "店长小林"
    # 非本工作区的账号连列表都拿不到
    auth.identity = verified_identity(
        primary_user_id="another-user", email="1474953130@qq.com"
    )
    assert client.get(root + "/personas").status_code in {403, 404}


def test_cannot_bind_another_users_private_avatar(video_gen):
    client, auth, _, root, _, _ = video_gen
    assert upload(video_gen).status_code == 200
    avatar_id = client.get(root + "/generation-tasks").json()[0]["avatar_id"]
    auth.identity = verified_identity(
        primary_user_id="another-user", email="1474953130@qq.com"
    )
    response = create(video_gen, avatar_id=avatar_id)
    assert response.status_code == 404
    assert "我的形象" not in response.text


def test_unknown_avatar_voice_or_setting_rejected(video_gen):
    assert create(video_gen, avatar_id="qy-model-404").status_code == 404
    assert create(video_gen, voice_id="qy-voice-404").status_code == 404
    assert create(video_gen, emotion="狂喜").status_code == 422
    assert create(video_gen, language="火星语").status_code == 422


def test_pending_own_avatar_can_be_bound_and_shows_customising(video_gen):
    client, _, _, root, _, _ = video_gen
    assert upload(video_gen).status_code == 200
    avatar_id = client.get(root + "/generation-tasks").json()[0]["avatar_id"]
    with client.app.state.session_factory() as session:
        job = session.query(VideoGenerationRecord).filter_by(avatar_id=avatar_id).one()
        job.status = "awaiting_review"
        session.commit()
    data = create(video_gen, avatar_id=avatar_id).json()
    assert data["available"] is False
    assert "定制中" in data["unavailable_reason"]
    with client.app.state.session_factory() as session:
        job = session.query(VideoGenerationRecord).filter_by(avatar_id=avatar_id).one()
        job.status = "completed"
        session.commit()
    again = client.get(root + f"/personas/{data['id']}").json()
    assert again["available"] is True


def test_deleted_avatar_marks_persona_unavailable_instead_of_error(video_gen):
    client, _, _, root, _, _ = video_gen
    data = create(video_gen).json()
    with client.app.state.session_factory() as session:
        session.get(VideoAvatarRecord, PUBLIC_AVATAR).active = False
        session.commit()
    listed = client.get(root + "/personas")
    assert listed.status_code == 200
    row = listed.json()[0]
    assert row["available"] is False and "形象已删除" in row["unavailable_reason"]
    assert row["avatar_name"] == data["avatar_name"]  # 名称快照仍在
    assert row["cover_url"] is None
    # 换一个可用形象即可恢复
    with client.app.state.session_factory() as session:
        session.get(VideoAvatarRecord, PUBLIC_AVATAR).active = True
        session.commit()
    assert client.get(root + "/personas").json()[0]["available"] is True


def test_removed_voice_marks_persona_unavailable(video_gen):
    client, _, provider, root, _, _ = video_gen
    data = create(video_gen).json()
    provider.voices = lambda: []
    row = client.get(root + "/personas").json()[0]
    assert row["available"] is False and "声音已删除" in row["unavailable_reason"]
    assert row["voice_name"] == data["voice_name"] == "温柔女声 · 居家好物"


def test_voice_catalogue_outage_does_not_break_list(video_gen):
    client, _, provider, root, _, _ = video_gen
    create(video_gen)

    def broken():
        raise RuntimeError("upstream down")

    provider.voices = broken
    response = client.get(root + "/personas")
    assert response.status_code == 200
    assert response.json()[0]["voice_name"] == "温柔女声 · 居家好物"


def test_delete_and_switch_voice(video_gen):
    client, _, _, root, _, _ = video_gen
    data = create(video_gen, emotion="愉快").json()
    switched = client.patch(
        root + f"/personas/{data['id']}", json={"voice_id": PUBLIC_VOICE}
    )
    assert switched.status_code == 200
    assert client.delete(root + f"/personas/{data['id']}").status_code == 204
    assert client.get(root + "/personas").json() == []
    assert client.delete(root + f"/personas/{data['id']}").status_code == 404
