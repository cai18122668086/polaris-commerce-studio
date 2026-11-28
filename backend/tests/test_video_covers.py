"""成片 covers (W5): two candidates, exact title, frame/AI split, credits, finish."""

from __future__ import annotations

import importlib.util
import io
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from PIL import Image, ImageOps
from sqlalchemy import create_engine, inspect, select

from app import services
from app import video_cover_compose as compose
from app import video_cover_skill as skill
from app.main import create_app
from app.models import CreditReservationRecord, WorkspaceCreditAccountRecord
from app.video_cover_image_client import CoverImageError, CoverImageResult
from app.video_cover_models import VideoCoverCandidateRecord
from app.video_generation_models import VideoAvatarRecord, VideoGenerationRecord
from tests.test_auth_external import (
    FakeExternalAuthBackend,
    external_settings,
    verified_identity,
)
from tests.test_video_projects import EMAIL, base

PRESENTER = (
    Path(__file__).resolve().parents[2]
    / "assets/video-studio/owned/presenter-female-v1.png"
)
MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "migrations/versions/20261128_0058_video_cover_candidates.py"
)


class FakeImages:
    """Returns the reference with a warm wash, like a repaint that kept the person."""

    def __init__(self, fail: str | None = None):
        self.fail = fail
        self.calls: list[str] = []

    def edit(
        self, reference_png: bytes, prompt: str, *, idempotency_key: str
    ) -> CoverImageResult:
        self.calls.append(prompt)
        if self.fail:
            raise CoverImageError(self.fail, "fake failure", retryable=True)
        image = (
            Image.open(io.BytesIO(reference_png)).convert("RGB").resize((1200, 1600))
        )
        warm = Image.new("RGB", image.size, (240, 200, 160))
        return CoverImageResult(Image.blend(image, warm, 0.15), "gpt-image-fake", None)


def presenter_frame() -> Image.Image:
    with Image.open(PRESENTER) as opened:
        return ImageOps.fit(opened.convert("RGB"), (720, 1280))


@pytest.fixture
def clip(tmp_path, monkeypatch) -> Path:
    """A stand-in video file; keyframe picking is replaced so CI needs no ffmpeg."""

    out = tmp_path / "talk.mp4"
    out.write_bytes(b"not-a-real-video")
    frame = presenter_frame()

    def fake_pick(video, workdir, count=12):
        assert Path(video) == out
        face = compose.detect_face(frame)
        return compose.Keyframe(
            frame, face[0] if face else (250, 380, 470, 640), 1.0, 1.0
        )

    monkeypatch.setattr(compose, "pick_keyframe", fake_pick)
    return out


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")
def test_real_keyframe_is_picked_from_a_video(tmp_path):
    still = tmp_path / "still.png"
    presenter_frame().save(still)
    video = tmp_path / "talk.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-y",
            "-loop",
            "1",
            "-i",
            str(still),
            "-t",
            "2",
            "-r",
            "10",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            str(video),
        ],
        check=True,
        timeout=120,
    )
    key = compose.pick_keyframe(video, tmp_path, count=4)
    assert key.image.size == (720, 1280) and 0 < key.at < 2
    assert not list(tmp_path.glob("frame-*.jpg"))


@pytest.fixture
def env(tmp_path, clip):
    auth = FakeExternalAuthBackend(identity=verified_identity(email=EMAIL))
    settings = external_settings(tmp_path).model_copy(
        update={"video_media_dir": tmp_path / "video"}
    )
    app = create_app(settings, auth)
    images = FakeImages()
    app.state.video_cover_image_client = images
    with TestClient(app) as client:
        user = client.get("/api/v1/me").json()["id"]
        ws = client.get("/api/v1/workspaces").json()[0]["id"]
        yield client, ws, user, images


def finished_talk(client, ws, user, clip: Path, status="completed") -> str:
    task_id = str(uuid4())
    with client.app.state.session_factory() as session:
        if session.get(VideoAvatarRecord, "cover-test-avatar") is None:
            session.add(
                VideoAvatarRecord(
                    id="cover-test-avatar", source="quanyu_public", name="测试形象"
                )
            )
            session.flush()
        session.add(
            VideoGenerationRecord(
                id=task_id,
                workspace_id=ws,
                owner_user_id=user,
                avatar_id="cover-test-avatar",
                request_id=str(uuid4()),
                request_hash="0" * 64,
                kind="lipsync",
                status=status,
                details={"result_path": str(clip)},
            )
        )
        session.commit()
    return task_id


def work_item(client, ws, generation_id) -> dict:
    body = {
        "request_id": str(uuid4()),
        "source": "talking",
        "items": [
            {
                "publish_title": "夏天必备的冰丝凉席",
                "publish_body": "睡得凉快 #好物推荐",
                "script_text": "今天给大家推荐一款冰丝凉席。",
                "avatar_id": "female-020",
                "voice_id": "warm",
            }
        ],
    }
    batch = client.post(base(ws) + "/work-batches", json=body)
    assert batch.status_code == 200, batch.text
    item = batch.json()["items"][0]
    patched = client.patch(
        base(ws) + f"/work-items/{item['id']}",
        json={
            "expected_version": item["version"],
            "generation_task_id": generation_id,
            "stage": "finishing",
            "status": "pending",
        },
    )
    assert patched.status_code == 200, patched.text
    return patched.json()


def generate(client, ws, **body):
    payload = {
        "request_id": str(uuid4()),
        "cover_text": "夏天必备的冰丝凉席",
        "platform": "douyin",
        **body,
    }
    return client.post(base(ws) + "/cover-candidates", json=payload)


def listed(client, ws, **query):
    response = client.get(base(ws) + "/cover-candidates", params=query)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def priced(env):
    client = env[0]
    services.set_quota_enabled(True)
    services.set_credit_enforcement_enabled(True)
    client.app.state.settings.video_credit_prices = {"cover_generate": 7}
    try:
        yield env
    finally:
        services.set_credit_enforcement_enabled(
            client.app.state.settings.workspace_credit_enforcement_enabled
        )


def fund(client, ws, credits):
    with client.app.state.session_factory() as session:
        session.get(WorkspaceCreditAccountRecord, ws).balance_credits = credits
        session.commit()


def balance_and_holds(client, ws):
    with client.app.state.session_factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, ws)
        holds = [
            (r.charge_action, r.status)
            for r in session.scalars(
                select(CreditReservationRecord).where(
                    CreditReservationRecord.owner_type == "video_cover"
                )
            )
        ]
        return (account.balance_credits, account.reserved_credits), holds


# ---------------------------------------------------------------- generation


def test_two_candidates_frame_and_ai_in_different_layouts_with_exact_title(
    priced, clip
):
    client, ws, user, images = priced
    fund(client, ws, 100)
    talk = finished_talk(client, ws, user, clip)
    item = work_item(client, ws, talk)
    created = generate(client, ws, work_item_id=item["id"], highlight="冰丝")
    assert created.status_code == 200, created.text
    rows = listed(client, ws, work_item_id=item["id"])
    assert [r["slot"] for r in sorted(rows, key=lambda r: r["slot"])] == [0, 1]
    frame, ai = sorted(rows, key=lambda r: r["slot"])
    assert (frame["background"], ai["background"]) == ("frame", "ai")
    assert frame["status"] == ai["status"] == "ready"
    assert frame["layout"] != ai["layout"]
    for row in rows:
        assert row["cover_text"] == "夏天必备的冰丝凉席"
        assert all(
            row["checks"][k]
            for k in (
                "text_exact",
                "glyphs_ok",
                "face_clear",
                "design_colors_ok",
                "size_ok",
            )
        )
        image = client.get(row["image_url"])
        assert (
            image.status_code == 200 and image.headers["content-type"] == "image/jpeg"
        )
        assert Image.open(io.BytesIO(image.content)).size == (1080, 1440)
        assert client.get(row["thumb_url"]).status_code == 200
    # Only the AI candidate is charged, exactly once.
    assert frame["credits"] is None and ai["credits"] == 7
    assert balance_and_holds(client, ws) == ((93, 0), [("cover_generate", "settled")])
    # The prompt came from the skill and forbids drawn text.
    assert len(images.calls) == 1 and "Strictly no text of any kind" in images.calls[0]
    with client.app.state.session_factory() as session:
        stored = session.get(VideoCoverCandidateRecord, ai["id"])
        assert "".join(stored.params["lines"]) == "夏天必备的冰丝凉席"
        assert stored.receipt["model_requested"] == "gpt-image-fake"
        assert stored.receipt["skill"] == skill.SKILL_ID


def test_ai_failure_falls_back_to_the_frame_and_charges_nothing(priced, clip):
    client, ws, user, images = priced
    images.fail = "COVER_IMAGE_UNAVAILABLE"
    fund(client, ws, 100)
    talk = finished_talk(client, ws, user, clip)
    assert generate(client, ws, generation_task_id=talk).status_code == 200
    rows = sorted(listed(client, ws, generation_task_id=talk), key=lambda r: r["slot"])
    assert [r["status"] for r in rows] == ["ready", "ready"]
    assert (
        rows[1]["background"] == "frame"
        and rows[1]["error_code"] == "COVER_IMAGE_UNAVAILABLE"
    )
    assert "未扣积分" in rows[1]["message"]
    assert rows[0]["layout"] != rows[1]["layout"]
    assert rows[1]["credits"] == 0
    assert balance_and_holds(client, ws) == ((100, 0), [("cover_generate", "released")])


def test_short_balance_creates_nothing(priced, clip):
    client, ws, user, _ = priced
    fund(client, ws, 6)
    talk = finished_talk(client, ws, user, clip)
    rejected = generate(client, ws, generation_task_id=talk)
    assert (
        rejected.status_code == 402
        and rejected.json()["error"]["code"] == "BUDGET_LIMIT_EXCEEDED"
    )
    with client.app.state.session_factory() as session:
        assert session.scalar(select(VideoCoverCandidateRecord.id)) is None
    assert balance_and_holds(client, ws) == ((6, 0), [])


def test_replay_returns_the_same_candidates_and_never_charges_twice(priced, clip):
    client, ws, user, images = priced
    fund(client, ws, 100)
    talk = finished_talk(client, ws, user, clip)
    body = {
        "request_id": str(uuid4()),
        "cover_text": "别再乱买了",
        "generation_task_id": talk,
    }
    first = client.post(base(ws) + "/cover-candidates", json=body).json()
    again = client.post(base(ws) + "/cover-candidates", json=body).json()
    assert [r["id"] for r in first] == [r["id"] for r in again]
    assert len(images.calls) == 1
    assert balance_and_holds(client, ws) == ((93, 0), [("cover_generate", "settled")])
    reused = client.post(
        base(ws) + "/cover-candidates", json={**body, "cover_text": "换了内容"}
    )
    assert reused.status_code == 409


def test_text_is_validated_before_any_charge(priced, clip):
    client, ws, user, images = priced
    fund(client, ws, 100)
    talk = finished_talk(client, ws, user, clip)
    emoji = generate(client, ws, generation_task_id=talk, cover_text="好物推荐😀")
    assert (
        emoji.status_code == 422
        and emoji.json()["error"]["code"] == "COVER_TEXT_GLYPHS"
    )
    bad = generate(client, ws, generation_task_id=talk, highlight="不在标题里")
    assert (
        bad.status_code == 422
        and bad.json()["error"]["code"] == "COVER_HIGHLIGHT_INVALID"
    )
    assert images.calls == [] and balance_and_holds(client, ws) == ((100, 0), [])


def test_unfinished_or_foreign_video_is_refused(env, clip):
    client, ws, user, _ = env
    running = finished_talk(client, ws, user, clip, status="running")
    refused = generate(client, ws, generation_task_id=running)
    assert (
        refused.status_code == 422
        and refused.json()["error"]["code"] == "COVER_SOURCE_NOT_READY"
    )
    assert generate(client, ws, generation_task_id=str(uuid4())).status_code == 422
    assert generate(client, ws, work_item_id="missing").status_code == 404


def test_retext_is_free_and_keeps_the_background(priced, clip):
    client, ws, user, images = priced
    fund(client, ws, 100)
    talk = finished_talk(client, ws, user, clip)
    generate(client, ws, generation_task_id=talk)
    ai = next(r for r in listed(client, ws, generation_task_id=talk) if r["slot"] == 1)
    changed = client.post(
        base(ws) + f"/cover-candidates/{ai['id']}/retext",
        json={
            "request_id": str(uuid4()),
            "cover_text": "睡得凉快的秘密",
            "highlight": "凉快",
        },
    )
    assert changed.status_code == 200, changed.text
    row = changed.json()
    assert row["status"] == "ready" and row["cover_text"] == "睡得凉快的秘密"
    assert (
        row["parent_id"] == ai["id"]
        and row["background"] == "ai"
        and row["checks"]["text_exact"]
    )
    assert len(images.calls) == 1
    assert balance_and_holds(client, ws) == ((93, 0), [("cover_generate", "settled")])


def test_finish_saves_cover_title_and_body_onto_the_work_item(env, clip):
    client, ws, user, _ = env
    talk = finished_talk(client, ws, user, clip)
    item = work_item(client, ws, talk)
    generate(client, ws, work_item_id=item["id"])
    cover = listed(client, ws, work_item_id=item["id"])[0]
    done = client.post(
        base(ws) + f"/work-items/{item['id']}/finish",
        json={
            "expected_version": item["version"],
            "cover_candidate_id": cover["id"],
            "publish_title": "夏天必备！冰丝凉席",
            "publish_body": "真的凉快 #好物推荐 #夏天",
        },
    )
    assert done.status_code == 200, done.text
    saved = done.json()
    assert saved["stage"] == "done" and saved["status"] == "succeeded"
    assert saved["cover_asset_id"] == cover["id"]
    assert saved["publish_title"] == "夏天必备！冰丝凉席"
    finished = client.get(base(ws) + "/work-items", params={"stage": "done"}).json()
    assert [w["id"] for w in finished] == [item["id"]]
    # A cover from another video cannot be attached.
    other = work_item(client, ws, finished_talk(client, ws, user, clip))
    wrong = client.post(
        base(ws) + f"/work-items/{other['id']}/finish",
        json={
            "expected_version": other["version"],
            "cover_candidate_id": cover["id"],
            "publish_title": "x",
        },
    )
    assert (
        wrong.status_code == 422
        and wrong.json()["error"]["code"] == "COVER_ITEM_MISMATCH"
    )


def test_stale_running_candidate_expires_and_releases(priced, clip, monkeypatch):
    """A worker that died mid-run: the hold is released, nothing is charged."""

    from datetime import UTC, datetime, timedelta

    from app import video_cover_routes

    client, ws, user, _ = priced
    fund(client, ws, 100)
    monkeypatch.setattr(
        video_cover_routes, "process_request", lambda *args, **kwargs: None
    )
    talk = finished_talk(client, ws, user, clip)
    rows = generate(client, ws, generation_task_id=talk).json()
    assert [r["status"] for r in rows] == ["queued", "queued"]
    assert balance_and_holds(client, ws) == ((100, 7), [("cover_generate", "active")])
    with client.app.state.session_factory() as session:
        for row in session.scalars(select(VideoCoverCandidateRecord)):
            row.updated_at = datetime.now(UTC) - timedelta(hours=1)
        session.commit()
    stale = listed(client, ws, generation_task_id=talk)
    assert {r["status"] for r in stale} == {"failed"}
    assert {r["error_code"] for r in stale} == {"COVER_INTERRUPTED"}
    assert balance_and_holds(client, ws) == ((100, 0), [("cover_generate", "released")])


# ---------------------------------------------------------------- skill files


def test_skill_tables_drive_the_prompt():
    assert skill.choose_dimensions("干货：3个护肤技巧").type == "typography"
    assert skill.choose_dimensions("美食探店").palette == "warm"
    assert skill.choose_dimensions("限时福利").mood == "bold"
    assert skill.choose_dimensions("随便说说") == skill.Dimensions(
        "hero", "warm", "balanced"
    )
    assert skill.choose_dimensions("随便说说", rotate=1).palette != "warm"
    prompt = skill.build_prompt(
        "夏天“冰丝”凉席", "top", skill.choose_dimensions("夏天冰丝凉席")
    )
    assert "{" not in prompt and "“" not in prompt
    assert "must not be blue, purple" in prompt and "Identity lock" in prompt
    root = skill.SKILL_ROOT
    for name in ("SKILL.md", "SOURCES.md", "LICENSE-THIRD-PARTY.md", "VERSION"):
        assert (root / name).is_file()
    sources = (root / "SOURCES.md").read_text(encoding="utf-8")
    assert (
        "MIT" in sources and "directors-chair" in sources and "baoyu-skills" in sources
    )


def test_migration_matches_the_model(tmp_path):
    spec = importlib.util.spec_from_file_location("cover_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert (module.revision, module.down_revision) == ("20261128_0058", "20261125_0053")
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    from app.database import Base

    with engine.begin() as connection:
        Base.metadata.tables["users"].create(connection)
        Base.metadata.tables["workspaces"].create(connection)
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            module.upgrade()
        columns = {
            c["name"] for c in inspect(connection).get_columns("video_cover_candidates")
        }
    assert columns == set(VideoCoverCandidateRecord.__table__.columns.keys())


def test_image_client_moves_to_the_next_route_only_when_unavailable(
    monkeypatch, tmp_path
):
    import base64

    import httpx
    from pydantic import SecretStr

    from app import video_cover_image_client as vc

    settings = external_settings(tmp_path).model_copy(
        update={
            "image_base_url": "https://primary.test",
            "image_api_key": SecretStr("k1"),
            "image_model": "m1",
            "provider_failover_enabled": True,
            "provider_failover_base_url": "https://backup.test",
            "provider_failover_api_key": SecretStr("k2, k3"),
            "provider_failover_image_model": "m2",
        }
    )
    assert [r.name for r in vc.image_routes(settings)] == [
        "primary",
        "failover-1",
        "failover-2",
    ]
    png = io.BytesIO()
    Image.new("RGB", (12, 16), (200, 150, 120)).save(png, "PNG")
    ok = {
        "data": [{"b64_json": base64.b64encode(png.getvalue()).decode()}],
        "model": "m2-real",
    }
    calls: list[str] = []

    def fake_post(url, **kwargs):
        calls.append(url)
        request = httpx.Request("POST", url)
        if url.startswith("https://primary.test") or kwargs["headers"][
            "Authorization"
        ].endswith("k2"):
            return httpx.Response(status, request=request, text="bad gateway")
        return httpx.Response(200, request=request, json=ok)

    monkeypatch.setattr(vc.httpx, "post", fake_post)
    client = vc.HttpCoverImageClient(settings)
    status = 502
    result = client.edit(png.getvalue(), "p", idempotency_key="x")
    assert (
        result.model_requested == "failover-2:m2" and result.model_reported == "m2-real"
    )
    assert [c.split("/v1")[0] for c in calls] == [
        "https://primary.test",
        "https://backup.test",
        "https://backup.test",
    ]
    calls.clear()
    status = 400  # a rejected prompt is final: never retried elsewhere
    with pytest.raises(CoverImageError) as error:
        client.edit(png.getvalue(), "p", idempotency_key="y")
    assert error.value.code == "COVER_IMAGE_REJECTED" and len(calls) == 1


def test_restart_resumes_interrupted_covers_and_charges_once(priced, clip, monkeypatch):
    """An API restart mid-run: startup recovery finishes the same request."""

    from datetime import UTC, datetime, timedelta

    from app import video_cover_routes

    client, ws, user, images = priced
    fund(client, ws, 100)
    real = video_cover_routes.process_request
    monkeypatch.setattr(video_cover_routes, "process_request", lambda *a, **k: None)
    talk = finished_talk(client, ws, user, clip)
    rows = generate(client, ws, generation_task_id=talk).json()
    with client.app.state.session_factory() as session:
        for row in session.scalars(select(VideoCoverCandidateRecord)):
            row.status = "running"
            row.updated_at = datetime.now(UTC) - timedelta(minutes=2)
        session.commit()
    monkeypatch.setattr(video_cover_routes, "process_request", real)
    resumed = video_cover_routes.recover_interrupted(
        client.app.state.session_factory,
        client.app.state.settings,
        images,
        datetime.now(UTC),
    )
    assert resumed == 1
    after = {r["id"]: r for r in listed(client, ws, generation_task_id=talk)}
    assert [after[r["id"]]["status"] for r in rows] == ["ready", "ready"]
    assert after[rows[1]["id"]]["background"] == "ai"
    assert len(images.calls) == 1
    assert balance_and_holds(client, ws) == ((93, 0), [("cover_generate", "settled")])
    # Nothing left to resume on the next start.
    assert (
        video_cover_routes.recover_interrupted(
            client.app.state.session_factory,
            client.app.state.settings,
            images,
            datetime.now(UTC),
        )
        == 0
    )


def test_cover_recovery_runs_only_where_video_providers_are_enabled(
    tmp_path, monkeypatch
):
    """Core roles share app.main but cannot see video files: no recovery there."""

    from app import video_cover_routes

    calls: list[object] = []
    monkeypatch.setattr(
        video_cover_routes,
        "recover_interrupted",
        lambda factory, settings, client, started: calls.append(settings) or 0,
    )
    auth = FakeExternalAuthBackend(identity=verified_identity(email=EMAIL))
    settings = external_settings(tmp_path).model_copy(
        update={"video_media_dir": tmp_path / "video"}
    )
    assert settings.video_providers_enabled is False
    started: list[object] = []
    real_start = video_cover_routes.start_recovery
    monkeypatch.setattr(
        video_cover_routes,
        "start_recovery",
        lambda application: started.append(real_start(application)),
    )

    # Providers off (core roles): the lifespan never starts the thread, and the
    # function refuses on its own if someone calls it anyway.
    app = create_app(settings, auth)
    app.state.video_cover_image_client = FakeImages()
    with TestClient(app):
        pass
    assert started == [] and calls == []
    assert real_start(app) is None and calls == []

    # Providers on (video API): recovery starts once and runs.
    on = settings.model_copy(update={"video_providers_enabled": True})
    app = create_app(on, auth)
    app.state.video_cover_image_client = FakeImages()
    with TestClient(app):
        assert len(started) == 1 and started[0] is not None
        started[0].join(timeout=10)
    assert calls == [app.state.settings]


def test_grid_poster_is_cut_once_cached_and_404_without_video(env, clip, monkeypatch):
    client, ws, user, _ = env
    cuts: list[str] = []

    def fake_extract(video, at, target):
        cuts.append(str(video))
        presenter_frame().save(target, "JPEG")
        return target

    monkeypatch.setattr(compose, "probe_duration", lambda video: 12.0)
    monkeypatch.setattr(compose, "extract_frame", fake_extract)
    talk = finished_talk(client, ws, user, clip)
    url = base(ws) + f"/work-posters/generation/{talk}"
    first = client.get(url)
    assert first.status_code == 200 and first.headers["content-type"] == "image/jpeg"
    assert Image.open(io.BytesIO(first.content)).size == (480, 640)
    assert client.get(url).status_code == 200
    assert len(cuts) == 1  # cached
    running = finished_talk(client, ws, user, clip, status="running")
    assert (
        client.get(base(ws) + f"/work-posters/generation/{running}").status_code == 404
    )
    assert client.get(base(ws) + f"/work-posters/editing/{uuid4()}").status_code == 404
    assert client.get(base(ws) + "/work-posters/other/x").status_code == 422
