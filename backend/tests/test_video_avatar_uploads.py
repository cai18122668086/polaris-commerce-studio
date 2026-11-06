import io
import subprocess
from uuid import uuid4

import imageio_ffmpeg
from PIL import Image

from app.video_generation_models import VideoAvatarRecord, VideoGenerationRecord
from tests.test_auth_external import verified_identity

pytest_plugins = ["tests.test_video_generation"]


def portrait():
    out = io.BytesIO()
    Image.new("RGB", (320, 480), "#c8b9da").save(out, format="PNG")
    return out.getvalue()


def upload(env, data=None, filename="portrait.png", request_id=None, **changes):
    client, _, _, root, _, _ = env
    fields = {
        "request_id": request_id or str(uuid4()),
        "name": "我的形象",
        "consent": "true",
        "consent_version": "avatar-v1",
        **changes,
    }
    return client.post(
        root + "/avatar-clones",
        data=fields,
        files={"file": (filename, portrait() if data is None else data)},
    )


def test_image_uses_uploaded_reference_and_requires_review_before_registration(
    video_gen,
):
    client, _, provider, root, _, _ = video_gen
    response = upload(video_gen)
    assert response.status_code == 200, response.text
    job = client.get(root + "/generation-tasks").json()[0]
    assert job["status"] == "awaiting_review"
    assert [path for _, path, _ in provider.posts] == ["/v1/videos"]
    sample = provider.uploads[0][0]
    assert sample.name == "cover.png" and "avatar-uploads" in str(sample)
    assert client.get(job["video_url"]).status_code == 200
    assert (
        client.post(
            root + f"/generation-tasks/{job['id']}/approve-template"
        ).status_code
        == 200
    )
    avatar = next(
        a for a in client.get(root + "/avatars").json() if a["id"] == job["avatar_id"]
    )
    assert avatar["ready"] and avatar["tag"] == "我的形象"
    assert (
        client.get(avatar["cover_url"]).headers["content-type"].startswith("image/png")
    )
    assert client.get(avatar["preview_url"]).status_code == 200
    with client.app.state.session_factory() as session:
        saved = session.get(VideoGenerationRecord, job["id"])
        assert saved.details["consent_version"] == "avatar-v1"
        assert saved.details["sample_sha256"] and saved.details["consent_at"]


def test_video_reuses_uploaded_motion_without_h3(video_gen, tmp_path):
    client, _, provider, root, _, _ = video_gen
    source = tmp_path / "motion.mp4"
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=256x384:rate=25:duration=2",
            "-c:v",
            "libx264",
            str(source),
        ],
        check=True,
    )
    response = upload(video_gen, source.read_bytes(), "motion.mp4")
    assert response.status_code == 200, response.text
    job = response.json()
    assert job["status"] == "awaiting_review" and provider.posts == []
    assert (
        client.post(
            root + f"/generation-tasks/{job['id']}/approve-template"
        ).status_code
        == 200
    )
    assert [path for _, path, _ in provider.posts] == ["/api/digital_human/models"]
    assert client.get(root + "/generation-tasks").json()[0]["status"] == "completed"
    project_id = video_gen[4]
    project = client.get(root + "/projects/" + project_id).json()
    project["content"]["draft"]["avatarId"] = job["avatar_id"]
    saved = client.put(
        root + "/projects/" + project_id,
        json={
            "request_id": str(uuid4()),
            "expected_revision": project["revision"],
            "content": project["content"],
        },
    ).json()
    generated = client.post(
        root + "/generation-tasks",
        json={
            "request_id": str(uuid4()),
            "kind": "lipsync",
            "avatar_id": job["avatar_id"],
            "project_id": project_id,
            "expected_revision": saved["project"]["revision"],
        },
    )
    assert generated.status_code == 200, generated.text
    result = next(
        row
        for row in client.get(root + "/generation-tasks").json()
        if row["id"] == generated.json()["id"]
    )
    assert result["status"] == "completed"
    assert "/v1/videos" not in [path for _, path, _ in provider.posts]


def test_avatar_upload_replay_is_idempotent_and_payload_change_rejected(video_gen):
    _, _, provider, _, _, _ = video_gen
    request_id = str(uuid4())
    first = upload(video_gen, request_id=request_id)
    second = upload(video_gen, request_id=request_id)
    assert first.status_code == second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert [path for _, path, _ in provider.posts].count("/v1/videos") == 1
    assert (
        upload(video_gen, request_id=request_id, name="另一个名称").status_code == 409
    )


def test_avatar_upload_requires_consent_and_valid_contents(video_gen):
    _, _, provider, _, _, _ = video_gen
    assert upload(video_gen, consent="false").status_code == 422
    assert upload(video_gen, b"not an image").status_code == 422
    assert upload(video_gen, b"not a video", "sample.mp4").status_code == 422
    assert provider.posts == []


def test_private_avatar_not_listed_read_or_submitted_by_another_user(video_gen):
    client, auth, _, root, _, _ = video_gen
    upload(video_gen)
    job = client.get(root + "/generation-tasks").json()[0]
    avatar_id = job["avatar_id"]
    auth.identity = verified_identity(
        primary_user_id="another-user", email="1474953130@qq.com"
    )
    assert avatar_id not in client.get(root + "/avatars").text
    assert client.get(root + f"/avatars/{avatar_id}/cover").status_code == 404
    assert client.get(root + f"/avatars/{avatar_id}/preview").status_code == 404
    assert client.get(job["video_url"]).status_code == 404
    result = client.post(
        root + "/generation-tasks",
        json={
            "request_id": str(uuid4()),
            "kind": "h3_template",
            "avatar_id": avatar_id,
        },
    )
    assert result.status_code == 404
    with client.app.state.session_factory() as session:
        assert session.get(VideoAvatarRecord, avatar_id)
