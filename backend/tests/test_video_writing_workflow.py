import importlib.util
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select, text

from app.video_studio_models import VideoScriptVersionRecord
from app.video_writing_contracts import WritingAnalysis, WritingDraft, WritingFacts
from app.video_writing_models import VideoWritingAdoption
from app.video_writing_provider import validate_analysis, validate_draft
from app.video_writing_rules import reference_from_project
from tests.test_video_projects import base, payload

pytest_plugins = ["tests.test_video_projects"]


def reference():
    return reference_from_project(
        {"id": str(uuid4()), "original_text": "这款旧款只要99元。它是500毫升装。"}
    )


def analysis():
    return WritingAnalysis(
        topic="价格与规格介绍",
        hook_sentence_ids=["r0000"],
        sections=[
            {
                "id": "a",
                "first_sentence_id": "r0000",
                "last_sentence_id": "r0000",
                "function": "价格钩子",
                "explanation": "原句直接报价格",
            },
            {
                "id": "b",
                "first_sentence_id": "r0001",
                "last_sentence_id": "r0001",
                "function": "规格",
                "explanation": "原句接规格",
            },
        ],
        reusable_structure=["钩子后补规格"],
        limitations=["仅文字，不知道画面和销量"],
        source_claims=[
            {
                "sentence_id": "r0000",
                "quote": "99元",
                "category": "product",
                "handling": "requires_user_fact",
                "reason": "参考价格不是客户价格",
            }
        ],
    )


def facts():
    return WritingFacts(
        facts=[
            {
                "id": "name",
                "category": "product",
                "label": "名称",
                "value": "新款",
                "status": "user_declared",
            },
            {
                "id": "price",
                "category": "product",
                "label": "价格",
                "value": "39元",
                "status": "user_declared",
            },
            {
                "id": "volume",
                "category": "product",
                "label": "规格",
                "value": "250毫升",
                "status": "user_declared",
            },
            {
                "id": "effect",
                "category": "product",
                "label": "效果",
                "status": "unknown",
            },
        ],
        forbidden_terms=["全网最低"],
    )


def draft():
    return WritingDraft(
        title="新款介绍",
        sentences=[
            {
                "reference_sentence_id": "r0000",
                "text": "这款新款只要39元。",
                "fact_ids": ["name", "price"],
                "rewritten_for": "fact_replacement",
            },
            {
                "reference_sentence_id": "r0001",
                "text": "它是250毫升装。",
                "fact_ids": ["volume"],
                "rewritten_for": "fact_replacement",
            },
        ],
        replacements=[
            {
                "category": "product",
                "original": "旧款",
                "replacement": "新款",
                "fact_id": "name",
            },
            {
                "category": "product",
                "original": "99元",
                "replacement": "39元",
                "fact_id": "price",
            },
            {
                "category": "product",
                "original": "500毫升",
                "replacement": "250毫升",
                "fact_id": "volume",
            },
        ],
    )


def test_writing_contract_rejects_invented_evidence_unknown_facts_and_old_claims():
    ref, a, f, d = reference(), analysis(), facts(), draft()
    validate_analysis(a, ref)
    assert validate_draft(d, ref, f, a) == "这款新款只要39元。它是250毫升装。"
    invented = a.model_copy(deep=True)
    invented.source_claims[0].quote = "销量第一"
    with pytest.raises(ValueError):
        validate_analysis(invented, ref)
    for field, value in [
        ("text", "这款新款只要99元。"),
        ("fact_ids", ["effect"]),
        ("text", "全网最低39元。"),
    ]:
        changed = d.model_copy(deep=True)
        setattr(changed.sentences[0], field, value)
        with pytest.raises(ValueError):
            validate_draft(changed, ref, f, a)
    for restriction in ["price", "net_quantity"]:
        changed_facts = f.model_copy(update={"restricted_claims": [restriction]})
        with pytest.raises(ValueError):
            validate_draft(d, ref, changed_facts, a)


def test_documents_tasks_and_adoption_keep_reference_facts_and_confirmation_separate(
    video, tmp_path, monkeypatch
):
    client, _, ws, _, settings = video
    settings.video_writing_workflow_enabled = True
    settings.video_script_planning_enabled = True
    monkeypatch.setattr("app.video_writing_routes.verify_writing_package", lambda _: {})
    ref = reference()
    a = analysis()
    f = facts()
    d = draft()

    class FakeWriting:
        calls = []

        def plan(self, kind, inputs):
            self.calls.append((kind, inputs))
            if kind == "ref_analysis":
                return {"analysis": a.model_dump()}, {}
            return {
                "draft": d.model_dump(),
                "text": "".join(s.text for s in d.sentences),
                "shape_check": {"verdict": "PASS"},
            }, {}

    fake = FakeWriting()
    client.app.state.video_assistance_provider = fake
    pid = str(uuid4())
    url = base(ws)
    body = payload("原草稿仍在")
    body["content"]["references"][0].update(
        id=str(ref.reference_id), original_text=ref.original_text
    )
    assert client.put(url + "/projects/" + pid, json=body).status_code == 200
    saved = client.post(
        url + "/writing-documents/reference",
        json={
            "request_id": str(uuid4()),
            "project_id": pid,
            "expected_revision": 1,
            "reference_id": str(ref.reference_id),
        },
    )
    assert saved.status_code == 200, saved.text
    rid = saved.json()["id"]
    saved_facts = client.post(
        url + "/writing-documents/facts",
        json={"request_id": str(uuid4()), "project_id": pid, "body": f.model_dump()},
    )
    assert saved_facts.status_code == 200, saved_facts.text
    request = {
        "request_id": str(uuid4()),
        "project_id": pid,
        "expected_revision": 1,
        "kind": "ref_analysis",
        "reference_document_id": rid,
    }
    task = client.post(url + "/writing-tasks", json=request)
    assert task.status_code == 200, task.text
    assert (
        client.post(url + "/writing-tasks", json=request).json()["id"]
        == task.json()["id"]
    )
    saved_analysis = client.post(
        url + "/writing-documents/result",
        json={"request_id": str(uuid4()), "task_id": task.json()["id"]},
    )
    assert saved_analysis.status_code == 200, saved_analysis.text
    request = {
        **request,
        "request_id": str(uuid4()),
        "kind": "fact_draft",
        "analysis_document_id": saved_analysis.json()["id"],
        "facts_document_id": saved_facts.json()["id"],
    }
    task = client.post(url + "/writing-tasks", json=request)
    assert task.status_code == 200, task.text
    saved_draft = client.post(
        url + "/writing-documents/result",
        json={"request_id": str(uuid4()), "task_id": task.json()["id"]},
    )
    assert saved_draft.status_code == 200, saved_draft.text
    assert (
        client.get(url + "/projects/" + pid).json()["content"]["draft"]["text"]
        == "原草稿仍在"
    )
    apply = {"request_id": str(uuid4()), "expected_revision": 1}
    applied = client.post(
        url + f"/writing-documents/{saved_draft.json()['id']}/apply", json=apply
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["version"]["kind"] == "draft"
    assert (
        client.post(
            url + f"/writing-documents/{saved_draft.json()['id']}/apply", json=apply
        ).json()
        == applied.json()
    )
    assert len(fake.calls) == 2
    with client.app.state.session_factory() as session:
        assert len(list(session.scalars(select(VideoWritingAdoption)))) == 1
        assert not list(
            session.scalars(
                select(VideoScriptVersionRecord).where(
                    VideoScriptVersionRecord.kind == "confirmed"
                )
            )
        )
    kinds = {
        r["kind"]
        for r in client.get(
            url + "/writing-documents", params={"project_id": pid}
        ).json()
    }
    assert kinds == {"reference", "analysis", "facts", "draft"}


def test_writing_migration_roundtrip_preserves_existing_project_tables(tmp_path):
    path = (
        Path(__file__).resolve().parents[1]
        / "migrations/versions/20261109_0043_video_writing_documents.py"
    )
    spec = importlib.util.spec_from_file_location("writing_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine(f"sqlite:///{tmp_path / 'writing-migration.db'}")
    with engine.begin() as connection:
        for table in [
            "users",
            "workspaces",
            "video_projects",
            "video_script_versions",
            "video_assistance_tasks",
        ]:
            connection.execute(
                text(f"CREATE TABLE {table} (id VARCHAR(40) PRIMARY KEY)")
            )
        connection.execute(
            text("INSERT INTO video_projects VALUES ('existing-project')")
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert "video_writing_documents" in inspect(connection).get_table_names()
            migration.downgrade()
        assert (
            connection.execute(text("SELECT id FROM video_projects")).scalar_one()
            == "existing-project"
        )
        assert "video_writing_documents" not in inspect(connection).get_table_names()
