import json
import sqlite3

import httpx
import pytest
from tengli_manual_flow_runtime import ManualFlowTransport


def test_startup_and_disabled_mode_cannot_spend(tmp_path):
    sent = []
    transport = ManualFlowTransport(tmp_path)
    transport.http = httpx.MockTransport(lambda request: sent.append(request))
    assert sent == []
    with pytest.raises(ValueError, match="disabled"):
        transport.handle_request(
            httpx.Request("POST", "https://www.wuyeai.cn/v1/videos", json={})
        )
    with sqlite3.connect(transport.ledger) as db:
        assert db.execute("select count(*) from paid_attempts").fetchone()[0] == 0
    assert sent == []


def test_manual_flow_blocks_other_paid_services_before_transmission(tmp_path):
    sent = []
    transport = ManualFlowTransport(tmp_path, user_submissions=True)
    transport.http = httpx.MockTransport(lambda request: sent.append(request))
    for url, body in [
        ("https://quanyu.sowa.chat/api/voice/clone", {}),
        (
            "https://api.tengliapi.xyz/v1/chat/completions",
            {"messages": [{}, {"content": json.dumps({"brief": "write a script"})}]},
        ),
    ]:
        with pytest.raises(ValueError):
            transport.handle_request(httpx.Request("POST", url, json=body))
    assert sent == []


def test_paid_attempt_is_durable_before_an_uncertain_reply_without_secrets(tmp_path):
    def lost_reply(request):
        raise httpx.ReadError("response lost")

    transport = ManualFlowTransport(tmp_path, user_submissions=True)
    transport.http = httpx.MockTransport(lost_reply)
    with pytest.raises(httpx.ReadError):
        transport.handle_request(
            httpx.Request(
                "POST",
                "https://www.wuyeai.cn/v1/videos",
                headers={"Authorization": "Bearer test-private-key"},
                json={"referenceImages": ["private-photo-url"]},
            )
        )
    restored = ManualFlowTransport(tmp_path, user_submissions=True)
    with sqlite3.connect(restored.ledger) as db:
        rows = db.execute("select * from paid_attempts").fetchall()
    assert len(rows) == 1 and rows[0][0] == "photo_motion"
    assert len(rows[0][1]) == 64
    assert "private" not in str(rows)


def test_template_plan_and_free_upload_use_the_same_guarded_transport(tmp_path):
    sent = []

    def accepted(request):
        sent.append(request.url.path)
        return httpx.Response(200, json={})

    transport = ManualFlowTransport(tmp_path, user_submissions=True)
    transport.http = httpx.MockTransport(accepted)
    body = {
        "messages": [
            {},
            {
                "content": json.dumps(
                    {
                        "overlay_template": {"id": "presenter-openings-v1"},
                    }
                )
            },
        ]
    }
    for url, payload in [
        ("https://quanyu.sowa.chat/api/oss/upload_policy", {}),
        ("https://sowa.oss-cn-beijing.aliyuncs.com/", {}),
        ("https://api.tengliapi.xyz/v1/chat/completions", body),
    ]:
        transport.handle_request(httpx.Request("POST", url, json=payload))
    assert len(sent) == 3
    with sqlite3.connect(transport.ledger) as db:
        assert db.execute("select stage from paid_attempts").fetchall() == [
            ("editing_plan",)
        ]
