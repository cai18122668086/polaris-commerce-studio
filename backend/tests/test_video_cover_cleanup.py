"""B14 磁盘清理：未引用的旧封面候选、海报缓存上限、免费素材 1G 上限；被引用的绝不删。"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app import video_media_cleanup as cleanup
from app.database import Base
from app.video_cover_models import VideoCoverCandidateRecord
from app.video_work_models import VideoWorkBatchRecord, VideoWorkItemRecord
from tests.test_video_covers import (
    base,
    finished_talk,
    generate,
    listed,
    work_item,
)

pytest_plugins = ["tests.test_video_covers"]

OLD = timedelta(days=20)


def backdate(client, ids, age=OLD):
    with client.app.state.session_factory() as session:
        for cid in ids:
            session.get(VideoCoverCandidateRecord, cid).created_at = (
                datetime.now(UTC) - age
            )
        session.commit()


def folder(client, cid) -> Path:
    return Path(client.app.state.settings.video_media_dir) / "covers" / cid


def test_only_unreferenced_old_candidates_are_removed(env, clip):
    client, ws, user, _ = env
    factory = client.app.state.session_factory
    settings = client.app.state.settings
    # 作品 A：生成两张，换字一张，选中换字后的那张
    talk = finished_talk(client, ws, user, clip)
    item = work_item(client, ws, talk)
    generate(client, ws, work_item_id=item["id"])
    frame, ai = sorted(
        listed(client, ws, work_item_id=item["id"]), key=lambda r: r["slot"]
    )
    child = client.post(
        base(ws) + f"/cover-candidates/{ai['id']}/retext",
        json={"request_id": str(uuid4()), "cover_text": "睡得凉快的秘密"},
    ).json()
    done = client.post(
        base(ws) + f"/work-items/{item['id']}/finish",
        json={
            "expected_version": item["version"],
            "cover_candidate_id": child["id"],
            "publish_title": "夏天必备！冰丝凉席",
        },
    )
    assert done.status_code == 200, done.text
    # 视频 B：生成了但一直没选；视频 C：刚生成（不到 14 天）
    other = finished_talk(client, ws, user, clip)
    generate(client, ws, generation_task_id=other)
    stale = [r["id"] for r in listed(client, ws, generation_task_id=other)]
    fresh_talk = finished_talk(client, ws, user, clip)
    generate(client, ws, generation_task_id=fresh_talk)
    fresh = [r["id"] for r in listed(client, ws, generation_task_id=fresh_talk)]
    backdate(client, [frame["id"], ai["id"], child["id"], *stale])
    doomed = {frame["id"], *stale}
    kept = {ai["id"], child["id"], *fresh}
    assert all(folder(client, cid).is_dir() for cid in doomed | kept)

    # 演练：只列出，不删文件、不改库
    dry = cleanup.run(factory, settings, dry_run=True)
    assert dry.covers == 3 and dry.cover_bytes > 0
    assert {Path(p).name for p in dry.files if "/covers/" in p} == doomed
    assert all(folder(client, cid).is_dir() for cid in doomed)

    report = cleanup.run(factory, settings)
    assert report.covers == 3 and report.cover_bytes == dry.cover_bytes
    assert "腾出" in report.summary()
    assert not any(folder(client, cid).exists() for cid in doomed)
    assert all(folder(client, cid).is_dir() for cid in kept)
    # 选中的封面照常可看；被清掉的从候选列表消失
    image = client.get(base(ws) + f"/cover-candidates/{child['id']}/image")
    assert image.status_code == 200
    assert [r["id"] for r in listed(client, ws, generation_task_id=other)] == []
    remaining = {r["id"] for r in listed(client, ws, work_item_id=item["id"])}
    assert remaining == {ai["id"], child["id"]}
    with factory() as session:
        row = session.get(VideoCoverCandidateRecord, frame["id"])
        assert (row.status, row.error_code, row.files) == (
            "failed",
            "COVER_EXPIRED",
            {},
        )
    # 第二轮什么都不删
    assert cleanup.run(factory, settings).covers == 0


def test_poster_cache_evicts_least_recently_used_above_the_cap(env):
    client = env[0]
    settings = client.app.state.settings.model_copy(
        update={"video_poster_cache_max_bytes": 250}
    )
    root = Path(settings.video_media_dir) / "posters"
    root.mkdir(parents=True, exist_ok=True)
    now = time.time()
    for index, name in enumerate(["old", "middle", "recent"]):
        path = root / f"generation-{name}.jpg"
        path.write_bytes(b"x" * 100)
        os.utime(path, (now - 3000 + index * 1000, now - 3000 + index * 1000))
    # "old" 刚被访问过（接口命中会 touch），应保留
    os.utime(root / "generation-old.jpg")
    report = cleanup.run(client.app.state.session_factory, settings)
    assert report.posters == 1 and report.poster_bytes == 100
    assert sorted(p.name for p in root.iterdir()) == [
        "generation-old.jpg",
        "generation-recent.jpg",
    ]


def test_stock_cache_cap_is_enforced_each_round(env):
    client = env[0]
    settings = client.app.state.settings.model_copy(
        update={"video_stock_cache_max_bytes": 150}
    )
    media = settings.video_editing_tasks_dir / "stock-cache" / "media" / "ab"
    media.mkdir(parents=True, exist_ok=True)
    for index in range(3):
        path = media / f"entry-{index}"
        path.write_bytes(b"y" * 100)
        os.utime(path, (time.time() - 100 + index, time.time() - 100 + index))
    dry = cleanup.run(client.app.state.session_factory, settings, dry_run=True)
    assert dry.stock_bytes == 200 and len(list(media.iterdir())) == 3
    report = cleanup.run(client.app.state.session_factory, settings)
    assert report.stock_bytes == 200 and report.stock_total == 100
    assert [p.name for p in media.iterdir()] == ["entry-2"]


def test_scheduler_runs_once_per_interval_and_can_be_disabled(env, monkeypatch):
    client = env[0]
    calls = []
    monkeypatch.setattr(cleanup, "run", lambda factory, settings: calls.append(1))
    settings = client.app.state.settings.model_copy(
        update={"video_media_cleanup_interval_seconds": 3600}
    )
    clock = [10_000.0]
    monkeypatch.setattr(cleanup.time, "monotonic", lambda: clock[0])
    scheduler = cleanup.Scheduler(settings)
    scheduler.tick(client.app.state.session_factory)
    assert calls == []  # 启动后先等 10 分钟
    clock[0] += cleanup.WARMUP_SECONDS
    for _ in range(3):
        scheduler.tick(client.app.state.session_factory)
    assert calls == [1]
    clock[0] += 3600
    scheduler.tick(client.app.state.session_factory)
    assert calls == [1, 1]
    off = cleanup.Scheduler(
        settings.model_copy(update={"video_media_cleanup_interval_seconds": 0})
    )
    off.tick(client.app.state.session_factory)
    assert calls == [1, 1]


@pytest.fixture
def postgres_factory():
    raw = os.environ.get("POLARIS_TEST_DATABASE_URL")
    if not raw:
        pytest.skip("set POLARIS_TEST_DATABASE_URL for isolated PostgreSQL tests")
    url = make_url(raw)
    if (
        url.get_backend_name() != "postgresql"
        or url.host not in {"localhost", "127.0.0.1", "::1"}
        or not url.database
        or not any(token in url.database.lower() for token in ("test", "ci"))
    ):
        raise pytest.UsageError("requires a local test/CI database")
    schema = "cover_cleanup_" + uuid4().hex
    admin = create_engine(url)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(
        url.update_query_dict({"options": f"-csearch_path={schema}"})
    )
    try:
        Base.metadata.create_all(engine)
        yield sessionmaker(engine, expire_on_commit=False)
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _candidate(cid, created, parent=None, status="ready"):
    return VideoCoverCandidateRecord(
        id=cid,
        workspace_id="ws",
        owner_user_id="u",
        request_id=cid,
        request_hash="h" * 64,
        slot=0,
        source_kind="generation",
        source_id="g",
        platform="douyin",
        cover_text="标题",
        background="frame",
        parent_id=parent,
        status=status,
        created_at=created,
        updated_at=created,
    )


def test_unreferenced_candidate_query_on_postgres(postgres_factory):
    old = datetime.now(UTC) - OLD
    with postgres_factory() as session:
        # 只验证查询；外键所需的工作区/用户行不在这里造
        session.execute(text("SET session_replication_role = replica"))
        session.add_all(
            [
                _candidate("root", old),
                _candidate("picked", old, parent="root"),
                _candidate("unused", old),
                _candidate("running", old, status="running"),
                _candidate("young-parent", old),
                _candidate("young", datetime.now(UTC), parent="young-parent"),
                VideoWorkBatchRecord(
                    id="b",
                    workspace_id="ws",
                    owner_user_id="u",
                    source="talking",
                    request_id="r",
                    request_hash="h" * 64,
                ),
                VideoWorkItemRecord(
                    id="i",
                    batch_id="b",
                    workspace_id="ws",
                    owner_user_id="u",
                    position=0,
                    drive_mode="text",
                    stage="done",
                    status="succeeded",
                    cover_asset_id="picked",
                ),
            ]
        )
        session.flush()
        assert cleanup.referenced_cover_ids(session) == {"picked", "root"}
        expired = cleanup.expired_cover_candidates(session, 14)
        assert [row.id for row in expired] == ["unused"]
