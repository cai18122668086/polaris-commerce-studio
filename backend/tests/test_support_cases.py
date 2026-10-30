from uuid import uuid4

from sqlalchemy import select

from app.admin_commerce_models import SupportCaseRecord
from app.models import AdminUserRecord, AuditEventRecord
from tests.test_customer_credit_billing import seed_job

BASE = "/api/v1/workspaces/ws_test/support-cases"
ADMIN = "/api/v1/admin/commerce/cases"


def test_support_is_scoped_and_retries_do_not_duplicate(client):
    with client.app.state.session_factory() as session:
        job, _ = seed_job(session, count=1, deliverables=False)
        job_id = job.id
        session.commit()
    headers = {"Idempotency-Key": str(uuid4())}
    body = {"job_id": job_id, "issue": "测试任务需要核对图片与积分"}
    first = client.post(BASE, headers=headers, json=body)
    assert first.status_code == 201, first.text
    assert (
        client.post(BASE, headers=headers, json=body).json()["id"] == first.json()["id"]
    )
    assert len(client.get(BASE).json()) == 1
    assert client.get("/api/v1/workspaces/ws_other/support-cases").status_code == 404
    assert (
        client.post(
            BASE, headers=headers, json={**body, "issue": "改成其他问题"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            BASE,
            headers={"Idempotency-Key": str(uuid4())},
            json={**body, "job_id": "job_foreign"},
        ).status_code
        == 404
    )
    assert client.get(ADMIN).status_code == 403
    assert (
        client.patch(
            ADMIN + "/" + first.json()["id"],
            json={"status": "resolved", "resolution": "未授权"},
        ).status_code
        == 403
    )
    with client.app.state.session_factory() as session:
        session.add(
            AdminUserRecord(
                user_id="usr_test",
                role="admin",
                status="active",
                permissions=["commerce:read"],
            )
        )
        session.commit()
    assert len(client.get(ADMIN).json()["items"]) == 1
    assert (
        client.patch(
            ADMIN + "/" + first.json()["id"],
            json={"status": "in_progress", "resolution": "核对中"},
        ).status_code
        == 403
    )
    with client.app.state.session_factory() as session:
        session.get(AdminUserRecord, "usr_test").permissions = [
            "commerce:read",
            "support:manage",
        ]
        session.commit()
    assert (
        client.patch(
            ADMIN + "/" + first.json()["id"],
            json={"status": "resolved", "resolution": ""},
        ).status_code
        == 422
    )
    result = client.patch(
        ADMIN + "/" + first.json()["id"],
        json={"status": "resolved", "resolution": "已核对原任务，问题处理完成"},
    )
    assert result.status_code == 200
    assert client.get(BASE).json()[0]["status"] == "resolved"
    with client.app.state.session_factory() as session:
        assert (
            session.scalar(
                select(AuditEventRecord).where(
                    AuditEventRecord.action == "commerce.case_updated"
                )
            )
            is not None
        )


def test_staff_notes_stay_private_and_customer_creator_survives_staff_updates(client):
    client.get(BASE)
    with client.app.state.session_factory() as session:
        session.add(
            SupportCaseRecord(
                id="case_staff",
                workspace_id="ws_test",
                actor_user_id="usr_test",
                issue="后台内部核对记录",
                status="open",
                resolution="内部备注",
            )
        )
        session.commit()
    assert client.get(BASE).json() == []
    result = client.post(
        BASE,
        headers={"Idempotency-Key": str(uuid4())},
        json={"issue": "用户提交帮助请求"},
    )
    assert result.status_code == 201
    with client.app.state.session_factory() as session:
        row = session.get(SupportCaseRecord, result.json()["id"])
        assert row.created_by == "usr_test" and row.actor_user_id == "usr_test"
        assert row.request_key
