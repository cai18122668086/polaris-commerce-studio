"""Global history reads durable sessions without exposing private checkpoint data."""

from datetime import timedelta
from uuid import uuid4

from app.models import ReplicaDocumentRecord, WorkspaceRecord, utc_now


def test_records_include_pre_generation_sessions_and_keep_private_payloads_server_side(
    client,
):
    assert client.get("/api/v1/workspaces/ws_test/replica/records").status_code == 200
    keep = "rep_" + uuid4().hex
    with client.app.state.session_factory() as db:
        db.add(
            WorkspaceRecord(
                id="ws_other", name="Other workspace", created_by_user_id="usr_test"
            )
        )
        db.flush()
        for workspace, kind, age, did in [
            ("ws_test", "session", 0, keep),
            ("ws_other", "session", 0, "rep_" + uuid4().hex),
            ("ws_test", "product", 0, "rep_" + uuid4().hex),
            ("ws_test", "session", 31, "rep_" + uuid4().hex),
        ]:
            db.add(
                ReplicaDocumentRecord(
                    id=did,
                    workspace_id=workspace,
                    created_by="usr_test",
                    kind=kind,
                    fingerprint=uuid4().hex * 2,
                    status="analysing",
                    updated_at=utc_now() - timedelta(days=age),
                    payload={
                        "replication_method": "style",
                        "references": [{"asset_id": "ref"}],
                        "facts": "PRIVATE_PRODUCT_FACTS",
                        "_analysis_checkpoint": {"secret": "PRIVATE_RAW_MODEL_RESULT"},
                        "analysis_stage": "规划商品画面",
                        "analysis_progress": {"total": 12},
                        "progress": 42,
                    },
                )
            )
        db.commit()
    response = client.get("/api/v1/workspaces/ws_test/replica/records")
    assert response.status_code == 200, response.text
    assert [r["id"] for r in response.json()] == [keep]
    item = response.json()[0]
    assert (
        item["status"] == "analysing"
        and item["expected"] == 12
        and item["job_ids"] == []
    )
    assert "PRIVATE_" not in response.text and "payload" not in item
    assert client.get("/api/v1/workspaces/ws_other/replica/records").status_code == 404
