from app.video_avatar_catalog import public_avatar_gender
from app.video_generation_models import VideoAvatarRecord

pytest_plugins = ["tests.test_video_generation"]


def test_public_gender_uses_exact_published_identity_and_preserves_curated_values():
    assert public_avatar_gender(224, "徐烬-休闲-whole_body") == "男"
    assert public_avatar_gender(230, "尹宜-专业-sit_body") == "女"
    assert public_avatar_gender(224, "Unrelated name") == "未知"
    assert public_avatar_gender(999999, "徐烬-休闲-whole_body") == "未知"
    assert public_avatar_gender(224, "徐烬-休闲-whole_body", "女") == "女"


def test_existing_unknown_gender_is_classified_without_reimport_or_database_write(
    video_gen,
):
    client, _, provider, root, _, _ = video_gen
    with client.app.state.session_factory() as session:
        session.add(
            VideoAvatarRecord(
                id="qy-model-224",
                source="quanyu_public",
                name="徐烬-休闲-whole_body",
                gender="未知",
                provider_model_id=224,
            )
        )
        session.commit()
    posts = len(provider.posts)
    response = client.get(root + "/avatars")
    assert response.status_code == 200
    assert (
        next(row for row in response.json() if row["id"] == "qy-model-224")["gender"]
        == "男"
    )
    assert len(provider.posts) == posts
    with client.app.state.session_factory() as session:
        assert session.get(VideoAvatarRecord, "qy-model-224").gender == "未知"
