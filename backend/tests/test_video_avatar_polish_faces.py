"""C5 第 1 点：AI 润色遇到多人照片直接拒绝，不建候选、不冻结积分、不调用生图。"""

import io
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image, ImageOps
from sqlalchemy import select

from app import video_avatar_polish
from app.bihuo_suite.subject import model_available
from app.video_avatar_polish import count_faces
from app.video_avatar_polish_models import VideoAvatarPolishRecord
from tests.test_video_avatar_polish import holds

pytest_plugins = ["tests.test_video_avatar_polish"]

PRESENTER = (
    Path(__file__).resolve().parents[2]
    / "assets/video-studio/owned/presenter-female-v1.png"
)
needs_model = pytest.mark.skipif(not model_available(), reason="face model missing")


def single() -> Image.Image:
    with Image.open(PRESENTER) as opened:
        return opened.convert("RGB")


def couple() -> Image.Image:
    one = single()
    two = Image.new("RGB", (one.width * 2, one.height), "white")
    two.paste(one, (0, 0))
    two.paste(ImageOps.mirror(one), (one.width, 0))
    return two


def png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def submit(client, root, image):
    return client.post(
        root + "/avatar-polishes",
        data={
            "request_id": str(uuid4()),
            "description": "穿深色西装，浅灰纯色背景",
            "consent": "true",
            "consent_version": "avatar-v1",
        },
        files={"file": ("me.png", png(image), "image/png")},
    )


@needs_model
def test_face_counter_sees_one_and_two_people():
    assert count_faces(single()) == 1
    assert count_faces(couple()) == 2
    assert count_faces(Image.new("RGB", (800, 1000), "#d9d2c5")) == 0
    # 远处的小脸（高度不到最大脸的 40%）不算第二个人
    tiny = single()
    small = tiny.copy()
    small.thumbnail((180, 320))
    tiny.paste(small, (10, 10))
    assert count_faces(tiny) == 1


@needs_model
def test_two_person_photo_is_refused_before_any_charge(polish_env):
    client, _, root, fake, ws = polish_env
    response = submit(client, root, couple())
    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VIDEO_AVATAR_MULTIPLE_FACES"
    assert "请上传单人照片" in error["message"]
    assert fake.calls == []
    assert holds(client, ws) == (100, 0, [])
    with client.app.state.session_factory() as session:
        assert session.scalars(select(VideoAvatarPolishRecord)).all() == []
    # 上传的照片不留盘
    polish_root = video_avatar_polish.polish_root(client.app.state.settings)
    assert not polish_root.exists() or not any(polish_root.iterdir())


@needs_model
def test_single_person_photo_still_goes_through(polish_env):
    client, _, root, fake, ws = polish_env
    response = submit(client, root, single())
    assert response.status_code == 200, response.text
    assert len(response.json()) == 2


def test_without_the_model_nothing_is_blocked(polish_env, monkeypatch):
    client, _, root, fake, ws = polish_env
    monkeypatch.setattr(video_avatar_polish, "count_faces", lambda image: None)
    assert submit(client, root, couple()).status_code == 200
