"""系统声音显示名：正经命名、隐藏角色化声音、被引用的仍可用（用户 11-28 要求）。"""

import os
import re
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.video_generation_models import VideoGenerationRecord
from app.video_persona_models import VideoPersonaRecord
from app.video_voice_catalog import (
    CATALOG,
    VOICES,
    official_voices,
    preview_path,
    referenced_voice_ids,
    select_tao_voice,
    voice_key,
)
from app.video_voice_names import (
    BANNED_WORDS,
    CHINESE,
    HIDDEN_CHINESE,
    MINIMAX_DISPLAY,
    QUANYU,
    clean_original,
    quanyu_display,
)
from app.video_work_models import VideoWorkBatchRecord, VideoWorkItemRecord
from tests.test_video_minimax_failover import settings as speech_settings

pytest_plugins = ["tests.test_video_generation"]

HIDDEN_SAMPLES = [
    "bingjiao_didi",  # 病娇弟弟
    "junlang_nanyou",  # 俊朗男友
    "cartoon_pig",  # 卡通猪小琪
    "male-qn-badao-jingpin",  # 霸道青年音色-beta
    "female-yujie-jingpin",  # 御姐音色-beta
    "lovely_girl",  # 萌萌女童
    "Korean_PossessiveMan",
    "Spanish_CaringGirlfriend",
]


def visible_names():
    names = [shown["name"] for shown in MINIMAX_DISPLAY.values() if shown]
    return names + [entry[2] for entry in QUANYU.values()]


def test_every_chinese_voice_was_reviewed_by_hand():
    chinese = [
        v["voice_id"] for v in CATALOG["voices"] if v["language"].startswith("中文")
    ]
    assert len(chinese) == 64
    assert {*chinese} == {*CHINESE} | {*HIDDEN_CHINESE}
    assert not set(CHINESE) & set(HIDDEN_CHINESE)


@pytest.mark.parametrize("name", visible_names())
def test_display_names_contain_no_banned_words(name):
    lowered = name.lower()
    assert not [word for word in BANNED_WORDS if word.lower() in lowered], name
    assert not re.search(r"-?beta|音色", name, re.I)
    assert " · " in name


def test_display_names_are_unique_and_follow_the_format():
    names = visible_names()
    assert len(names) == len(set(names))
    for voice in CATALOG["voices"]:
        shown = MINIMAX_DISPLAY[voice["voice_id"]]
        if shown and not voice["language"].startswith("中文"):
            # 其他语言：语言 + 性别 + 特质
            assert re.fullmatch(r"\S+语(男声|女声|人声) · \S+( \d)?", shown["name"]), (
                shown
            )


def test_beta_duplicates_keep_only_one():
    for voice_id in [v["voice_id"] for v in CATALOG["voices"]]:
        if voice_id.endswith("-jingpin"):
            base = voice_id.removesuffix("-jingpin")
            assert MINIMAX_DISPLAY[voice_id] is None
            assert MINIMAX_DISPLAY[base] is not None


def test_hidden_voices_are_not_listed_but_stay_usable_when_referenced():
    settings = speech_settings()
    keys = {voice_key(voice_id) for voice_id in HIDDEN_SAMPLES}
    listed = {v["id"]: v for v in official_voices(settings, "/r")}
    assert not keys & set(listed)
    assert len(listed) == sum(1 for shown in MINIMAX_DISPLAY.values() if shown)
    assert (
        listed[voice_key("Chinese (Mandarin)_Reliable_Executive")]["name"]
        == "沉稳男声 · 商务讲解"
    )
    assert all(v["description"] != "系统声音" for v in listed.values())
    referenced = voice_key("bingjiao_didi")
    restored = {v["id"]: v for v in official_voices(settings, "/r", {referenced})}
    # 被引用的放回列表，显示供应商原名
    assert restored[referenced]["name"] == "病娇弟弟"
    # 提交生成仍然按原始 voice_id 走，不受显示名影响
    chosen = select_tao_voice(
        settings,
        {"voiceId": referenced, "speed": 1, "emotion": "自然", "language": "auto"},
    )
    assert chosen["voice_id"] == "bingjiao_didi" and chosen["voice_name"] == "病娇弟弟"


def test_quanyu_names_follow_the_table_and_fall_back_when_upstream_changes():
    assert quanyu_display("1", "温柔女声")["name"] == "温柔女声 · 居家好物"
    # 上游换序：id 1 变成了别的声音，不能张冠李戴
    assert quanyu_display("1", "活力男声音色")["name"] == "活力男声"
    assert quanyu_display("99", "知性女声-beta")["name"] == "知性女声"
    assert clean_original("青涩青年音色-beta") == "青涩青年"


def test_voices_endpoint_uses_display_names_and_restores_referenced(video_gen):
    client, _, _, root, _, user = video_gen
    workspace = root.rsplit("/", 1)[1]
    voices = client.get(root + "/voices").json()
    by_id = {v["id"]: v for v in voices}
    assert by_id["qy-voice-1"]["name"] == "温柔女声 · 居家好物"
    assert by_id["qy-voice-1"]["gender"] == "女"
    assert not any(
        any(w in v["name"] for w in ("病娇", "男友", "-beta", "音色")) for v in voices
    )
    persona_voice, history_voice = voice_key("junlang_nanyou"), voice_key("cartoon_pig")
    assert persona_voice not in by_id and history_voice not in by_id
    with client.app.state.session_factory() as session:
        session.add(
            VideoPersonaRecord(
                id="persona-old",
                workspace_id=workspace,
                owner_user_id=user,
                request_id=str(uuid4()),
                name="旧搭配",
                avatar_id="qy-model-11",
                voice_id=persona_voice,
                avatar_name="模特",
                voice_name="俊朗男友",
                voice_settings={},
            )
        )
        session.add(
            VideoGenerationRecord(
                id="gen-old",
                workspace_id=workspace,
                owner_user_id=user,
                avatar_id="qy-model-11",
                request_id=str(uuid4()),
                request_hash="x" * 64,
                kind="lipsync",
                status="succeeded",
                stage="done",
                details={
                    "tts": {"voice_id": "cartoon_pig", "voice_name": "卡通猪小琪"}
                },
            )
        )
        session.commit()
    by_id = {v["id"]: v for v in client.get(root + "/voices").json()}
    assert by_id[persona_voice]["name"] == "俊朗男友"
    assert by_id[history_voice]["name"] == "卡通猪小琪"
    # 固定形象卡仍然可用
    persona = client.get(root + "/personas/persona-old").json()
    assert persona["voice_name"] == "俊朗男友"
    assert persona["unavailable_reason"] != "声音已删除或不可用，请更换声音"


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
    schema = "voice_names_" + uuid4().hex
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


def test_referenced_voice_ids_on_postgres(postgres_factory):
    with postgres_factory() as session:
        # 只验证查询本身；外键所需的工作区/用户/形象行不在这里造
        session.execute(text("SET session_replication_role = replica"))
        now = datetime.now(UTC)
        session.add(
            VideoPersonaRecord(
                id="p1",
                workspace_id="ws",
                owner_user_id="u",
                request_id="r1",
                name="甲",
                avatar_id="a",
                voice_id=voice_key("junlang_nanyou"),
                avatar_name="a",
                voice_name="俊朗男友",
                voice_settings={},
            )
        )
        session.add(
            VideoWorkBatchRecord(
                id="b1",
                workspace_id="ws",
                owner_user_id="u",
                source="talking",
                request_id="r2",
                request_hash="h" * 64,
            )
        )
        session.add(
            VideoWorkItemRecord(
                id="i1",
                batch_id="b1",
                workspace_id="ws",
                owner_user_id="u",
                position=0,
                voice_id="qy-voice-2",
                drive_mode="text",
                stage="talking",
                status="pending",
            )
        )
        for index, voice_id in enumerate(["cartoon_pig", "cartoon_pig", None]):
            session.add(
                VideoGenerationRecord(
                    id=f"g{index}",
                    workspace_id="ws",
                    owner_user_id="u",
                    avatar_id="a",
                    request_id=f"rq{index}",
                    request_hash="h" * 64,
                    kind="lipsync",
                    details={"tts": {"voice_id": voice_id}} if voice_id else {},
                    created_at=now,
                    updated_at=now,
                )
            )
        session.add(
            VideoGenerationRecord(
                id="g-other",
                workspace_id="ws",
                owner_user_id="someone-else",
                avatar_id="a",
                request_id="rq9",
                request_hash="h" * 64,
                kind="lipsync",
                details={"tts": {"voice_id": "bingjiao_didi"}},
            )
        )
        session.flush()
        assert referenced_voice_ids(session, "ws", "u") == {
            voice_key("junlang_nanyou"),
            "qy-voice-2",
            voice_key("cartoon_pig"),
        }
        assert voice_key("cartoon_pig") in VOICES


def test_voices_list_stays_small_even_with_every_preview_cached(video_gen):
    """正式站曾因列表 44 万字节在慢网下超时（首页 0 个音色）；目标 ≤60KB。"""

    client, _, _, root, _, _ = video_gen
    settings = client.app.state.settings
    for key in VOICES:
        path = preview_path(settings, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    response = client.get(root + "/voices")
    official = [v for v in response.json() if v["id"] in VOICES]
    assert len(official) == 204 and all(v["preview"] for v in official)
    assert not any("emotions" in v or "languages" in v for v in official)
    assert len(response.content) <= 60_000, len(response.content)
    options = client.get(root + "/voice-options").json()
    assert options["emotions"][0] == "自然" and options["languages"]["auto"]
