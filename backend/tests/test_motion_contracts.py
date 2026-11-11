import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text

from app.motion_library import atomic_json
from app.video_editing_contracts import (
    SemanticBeat,
    SemanticPlan,
    Transcript,
    TranscriptToken,
)
from app.video_editing_pipeline import caption_rows
from app.video_editing_planner import validate_plan
from app.video_editing_word_bindings import IncompleteDenial


def test_repeated_chinese_words_numbers_and_negation_keep_distinct_audio_anchors():
    words = ["不是越贵越好", "，", "每瓶1000克", "，", "1000克"]
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=6000,
        provider="human_test_annotation",
        model="boundary-fixture",
        language="zh",
        tokens=[
            TranscriptToken(
                id=f"t{i}", text=w, start_ms=100 + i * 1000, end_ms=800 + i * 1000
            )
            for i, w in enumerate(words)
        ],
        utterances=[],
    )
    captions = caption_rows(transcript)
    assert "".join(c["text"] for c in captions) == "".join(words)
    assert [t for c in captions for t in c["token_ids"]] == [f"t{i}" for i in range(5)]
    assert captions[0]["start_seconds"] == 0.1
    assert captions[-1]["end_seconds"] == 4.8


def test_semantic_model_cannot_inject_seconds_paths_or_code():
    beat = dict(
        id="b1",
        first_token_id="t1",
        last_token_id="t3",
        relation="contrast",
        group_id="Z-M09",
        reason="完整保留否定关系",
    )
    for key, value in [
        ("start_ms", 100),
        ("path", "C:/other.mp4"),
        ("code", "import os"),
        ("locked_by_user", True),
    ]:
        with pytest.raises(ValidationError):
            SemanticBeat.model_validate({**beat, key: value})


def test_planner_cannot_drop_negation_repeat_word_occurrence_or_invent_assets(tmp_path):
    atomic_json(tmp_path / "catalog/groups.json", {"groups": [{"id": "Z-M09"}]})
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=5000,
        provider="annotated_test",
        model="fixture",
        language="zh",
        tokens=[
            TranscriptToken(
                id=f"t{i}", text=w, start_ms=i * 1000, end_ms=(i + 1) * 1000
            )
            for i, w in enumerate(["不是", "越贵", "越好", "越贵"])
        ],
        utterances=[],
    )
    base = dict(
        audience_question="如何选择",
        argument_outline=["纠偏"],
        style_reason="完整否定",
        beats=[
            dict(
                id="b",
                first_token_id="t0",
                last_token_id="t3",
                relation="contrast",
                group_id="Z-M09",
                reason="保留完整否定",
                emphasis_token_ids=["t0", "t1", "t2"],
                asset_ids=[],
            )
        ],
    )
    validate_plan(SemanticPlan.model_validate(base), transcript, tmp_path, set())
    variants = [
        dict(emphasis_token_ids=["t1", "t2"]),
        dict(last_token_id="t2"),
        dict(emphasis_token_ids=["t0", "t3"]),
        dict(asset_ids=["invented-evidence"]),
    ]
    for variant in variants:
        broken = {**base, "beats": [{**base["beats"][0], **variant}]}
        with pytest.raises(ValueError):
            validate_plan(
                SemanticPlan.model_validate(broken), transcript, tmp_path, set()
            )
    split = {
        **base,
        "beats": [
            {**base["beats"][0], "last_token_id": "t0", "emphasis_token_ids": []},
            {
                **base["beats"][0],
                "id": "after-denial",
                "first_token_id": "t1",
                "relation": "explanation",
                "emphasis_token_ids": ["t1", "t2"],
            },
        ],
    }
    with pytest.raises(IncompleteDenial):
        validate_plan(SemanticPlan.model_validate(split), transcript, tmp_path, set())


def test_new_editing_migration_roundtrip_preserves_existing_tables(tmp_path):
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261109_0042_video_editing_tasks.py"
    )
    spec = importlib.util.spec_from_file_location("editing_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        for table in (
            "users",
            "workspaces",
            "video_projects",
            "video_script_versions",
            "video_generations",
        ):
            connection.execute(
                text(f"CREATE TABLE {table} (id VARCHAR(40) PRIMARY KEY)")
            )
        connection.execute(text("INSERT INTO users VALUES ('preserved-user')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        schema = inspect(connection)
        assert {c["name"] for c in schema.get_columns("video_editing_tasks")} >= {
            "source_id",
            "library_release",
            "owner_token",
            "lease_until",
            "checkpoint",
        }
        assert len(schema.get_unique_constraints("video_editing_tasks")) == 1
        migration.downgrade()
        assert not any(
            name.startswith("video_editing_")
            for name in inspect(connection).get_table_names()
        )
        assert connection.scalar(text("SELECT id FROM users")) == "preserved-user"
    engine.dispose()
