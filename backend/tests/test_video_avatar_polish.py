"""AI 润色：换脸 / 不适宜描述拒绝、按张计费失败不扣、规格不合格作废、幂等、隔离。"""

import io
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import select

from app import services, video_avatar_polish
from app.models import CreditReservationRecord, WorkspaceCreditAccountRecord
from app.video_avatar_polish import (
    PolishImageError,
    PolishImageResult,
    build_prompt,
    description_rejection,
)
from tests.test_auth_external import verified_identity
from tests.test_video_avatar_uploads import portrait

pytest_plugins = ["tests.test_video_generation"]


class FakeClient:
    def __init__(self, outcomes=None):
        self.calls = []
        self.outcomes = list(outcomes or [])

    def edit(self, reference_png, prompt, *, idempotency_key):
        self.calls.append((prompt, idempotency_key, len(reference_png)))
        outcome = self.outcomes.pop(0) if self.outcomes else "ok"
        if isinstance(outcome, Exception):
            raise outcome
        size = (1200, 1600) if outcome == "ok" else (1600, 900)
        return PolishImageResult(
            Image.new("RGB", size, "#d9d2c5"), "fake-image", "fake"
        )


@pytest.fixture
def polish_env(video_gen, monkeypatch):
    client, auth, provider, root, pid, user = video_gen
    fake = FakeClient()
    client.app.state.video_avatar_polish_client = fake
    # 人脸检测：默认给一张居中的正脸
    monkeypatch.setattr(
        video_avatar_polish, "detect_face", lambda image: ((480, 300, 720, 620), 0.95)
    )
    ws = client.get("/api/v1/workspaces").json()[0]["id"]
    services.set_quota_enabled(True)
    services.set_credit_enforcement_enabled(True)
    client.app.state.settings.video_credit_prices = {"avatar_polish": 7}
    with client.app.state.session_factory() as session:
        session.get(WorkspaceCreditAccountRecord, ws).balance_credits = 100
        session.commit()
    try:
        yield client, auth, root, fake, ws
    finally:
        services.set_credit_enforcement_enabled(
            client.app.state.settings.workspace_credit_enforcement_enabled
        )


def submit(
    client, root, request_id=None, description="穿深色西装，浅灰纯色背景", **fields
):
    data = {
        "request_id": request_id or str(uuid4()),
        "description": description,
        "consent": "true",
        "consent_version": "avatar-v1",
        **fields,
    }
    return client.post(
        root + "/avatar-polishes",
        data=data,
        files={"file": ("me.png", portrait(), "image/png")},
    )


def holds(client, ws):
    with client.app.state.session_factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, ws)
        rows = session.scalars(
            select(CreditReservationRecord).where(
                CreditReservationRecord.owner_type == "video_avatar_polish"
            )
        ).all()
        return (
            account.balance_credits,
            account.reserved_credits,
            sorted(r.status for r in rows),
        )


@pytest.mark.parametrize(
    "text",
    [
        "把我换成刘德华的脸",
        "换脸成我喜欢的明星",
        "变成一个当红明星",
        "长得像某个演员",
        "用别人的脸",
        "face swap with a celebrity",
        "穿比基尼在海边",
        "裸露上身",
    ],
)
def test_face_swap_and_unsafe_descriptions_are_rejected_before_any_call(
    polish_env, text
):
    client, _, root, fake, ws = polish_env
    assert description_rejection(text)
    response = submit(client, root, description=text)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VIDEO_AVATAR_POLISH_PROMPT_REJECTED"
    assert fake.calls == []
    assert holds(client, ws) == (100, 0, [])


@pytest.mark.parametrize(
    "text",
    [
        "把我变成一个很帅、穿西装、站在门店里的人",
        "职业西装·干净背景",
        "枪灰色西装，儿童服装店店长",
        "穿白衬衫，像专业主播一样自然",
    ],
)
def test_normal_style_descriptions_pass(text):
    assert description_rejection(text) is None


def test_two_candidates_charge_seven_each_and_keep_identity_lock(polish_env):
    client, _, root, fake, ws = polish_env
    request_id = str(uuid4())
    first = submit(client, root, request_id=request_id)
    assert first.status_code == 200, first.text
    assert [row["slot"] for row in first.json()] == [1, 2]
    rows = client.get(
        root + "/avatar-polishes", params={"request_id": request_id}
    ).json()
    assert [row["status"] for row in rows] == ["ready", "ready"]
    assert all(row["credits"] == 7 for row in rows)
    assert len(fake.calls) == 2
    prompt, key, _ = fake.calls[0]
    assert "IDENTITY LOCK" in prompt and "穿深色西装" in prompt
    assert key.startswith("avatar-polish-")
    image = client.get(rows[0]["image_url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(image.content)).size == (1200, 1600)
    assert holds(client, ws) == (86, 0, ["settled", "settled"])
    # 同一次提交重试：不再调用、不再扣费
    again = submit(client, root, request_id=request_id)
    assert again.status_code == 200 and len(fake.calls) == 2
    assert holds(client, ws) == (86, 0, ["settled", "settled"])
    changed = submit(client, root, request_id=request_id, description="门店暖光")
    assert changed.status_code == 409


def test_failed_and_out_of_spec_candidates_are_free(polish_env):
    client, _, root, fake, ws = polish_env
    fake.outcomes = [
        PolishImageError("AVATAR_POLISH_UNSAFE", "x"),
        "landscape",
    ]
    request_id = str(uuid4())
    assert submit(client, root, request_id=request_id).status_code == 200
    rows = client.get(
        root + "/avatar-polishes", params={"request_id": request_id}
    ).json()
    by_code = {row["error_code"]: row for row in rows}
    assert set(by_code) == {"AVATAR_POLISH_UNSAFE", "AVATAR_POLISH_SPEC"}
    assert all(row["status"] == "failed" and row["image_url"] is None for row in rows)
    assert "内容安全" in by_code["AVATAR_POLISH_UNSAFE"]["message"]
    assert "不扣费" in by_code["AVATAR_POLISH_SPEC"]["message"]
    assert holds(client, ws) == (100, 0, ["released", "released"])


def test_no_face_detected_is_rejected_as_out_of_spec(polish_env, monkeypatch):
    client, _, root, _, ws = polish_env
    monkeypatch.setattr(video_avatar_polish, "detect_face", lambda image: None)
    request_id = str(uuid4())
    submit(client, root, request_id=request_id, count="1")
    rows = client.get(
        root + "/avatar-polishes", params={"request_id": request_id}
    ).json()
    assert rows[0]["error_code"] == "AVATAR_POLISH_SPEC"
    assert holds(client, ws) == (100, 0, ["released"])


def test_requires_consent_and_balance(polish_env):
    client, _, root, fake, ws = polish_env
    assert submit(client, root, consent="false").status_code == 422
    with client.app.state.session_factory() as session:
        session.get(WorkspaceCreditAccountRecord, ws).balance_credits = 10
        session.commit()
    short = submit(client, root)
    assert short.status_code == 402
    assert fake.calls == []
    assert holds(client, ws) == (10, 0, [])


def test_candidates_are_private_to_their_owner(polish_env):
    client, auth, root, _, _ = polish_env
    request_id = str(uuid4())
    submit(client, root, request_id=request_id)
    url = client.get(
        root + "/avatar-polishes", params={"request_id": request_id}
    ).json()[0]["image_url"]
    auth.identity = verified_identity(
        primary_user_id="another-user", email="1474953130@qq.com"
    )
    assert client.get(url).status_code in {403, 404}
    assert client.get(
        root + "/avatar-polishes", params={"request_id": request_id}
    ).status_code in {
        200,
        403,
        404,
    }
    listed = client.get(root + "/avatar-polishes", params={"request_id": request_id})
    if listed.status_code == 200:
        assert listed.json() == []


def test_prompt_variations_differ_but_both_lock_identity():
    a, b = build_prompt("门店暖光", 1), build_prompt("门店暖光", 2)
    assert a != b
    for prompt in (a, b):
        assert "same person" in prompt and "five fingers" in prompt
        assert "no extra people" in prompt and "门店暖光" in prompt


def test_spec_check_rules(monkeypatch):
    from app.video_avatar_polish import spec_check

    portrait_image = Image.new("RGB", (1200, 1600))
    monkeypatch.setattr(video_avatar_polish, "detect_face", lambda image: False)
    assert spec_check(portrait_image)[0] is True  # 检测模型不可用：只查尺寸
    assert spec_check(Image.new("RGB", (1600, 1200)))[0] is False
    assert spec_check(Image.new("RGB", (600, 800)))[0] is False
    monkeypatch.setattr(
        video_avatar_polish, "detect_face", lambda image: ((40, 300, 200, 500), 0.9)
    )
    assert spec_check(portrait_image)[0] is False  # 脸偏到边上
    monkeypatch.setattr(
        video_avatar_polish, "detect_face", lambda image: ((560, 400, 620, 460), 0.9)
    )
    assert spec_check(portrait_image)[0] is False  # 脸太小


def test_http_client_fails_over_on_502_but_not_on_rejection(monkeypatch):
    import base64 as b64

    import httpx
    from pydantic import SecretStr

    from app.config import Settings
    from app.video_avatar_polish import HttpPolishImageClient

    settings = Settings().model_copy(
        update={
            "image_base_url": "https://primary.invalid",
            "image_api_key": SecretStr("p"),
            "provider_failover_enabled": True,
            "provider_failover_base_url": "https://backup.invalid",
            "provider_failover_api_key": SecretStr("b1, b2"),
        }
    )
    buffer = io.BytesIO()
    Image.new("RGB", (1200, 1600)).save(buffer, "PNG")
    ok = {"data": [{"b64_json": b64.b64encode(buffer.getvalue()).decode()}]}
    seen = []

    def post(url, headers, **kwargs):
        seen.append((url, headers["Authorization"]))
        if "primary" in url:
            return httpx.Response(502, text="bad gateway")
        if headers["Authorization"] == "Bearer b1":
            return httpx.Response(429, text="busy")
        return httpx.Response(200, json=ok)

    monkeypatch.setattr(httpx, "post", post)
    client = HttpPolishImageClient(settings)
    result = client.edit(b"png", "prompt", idempotency_key="k")
    assert result.image.size == (1200, 1600)
    assert [auth for _, auth in seen] == ["Bearer p", "Bearer b1", "Bearer b2"]
    assert result.model_requested.startswith("failover-2:")

    seen.clear()
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, headers, **kw: (
            seen.append(url)
            or httpx.Response(400, json={"error": {"code": "moderation_blocked"}})
        ),
    )
    with pytest.raises(PolishImageError) as caught:
        HttpPolishImageClient(settings).edit(b"png", "prompt", idempotency_key="k")
    assert caught.value.code == "AVATAR_POLISH_UNSAFE"
    assert len(seen) == 1  # 被拒不换通道重试
