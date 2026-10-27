"""HTTP smoke for our isolated mock API. No supplier or production connection."""

import time
from io import BytesIO
from uuid import uuid4

import httpx
from PIL import Image

BASE = "http://127.0.0.1:8190/api/v1/workspaces/ws_credit_preview"
HEADERS = {"X-User-Id": "usr_credit_preview"}
with httpx.Client(headers=HEADERS, timeout=30) as client:
    before = client.get(BASE + "/credits").json()
    image = BytesIO()
    Image.new("RGB", (96, 96), (235, 197, 64)).save(image, "PNG")

    def upload(kind):
        response = client.post(
            BASE + "/assets",
            headers={"Idempotency-Key": str(uuid4())},
            data={"origin_kind": "upload", "media_kind": kind},
            files={"file": (kind + ".png", image.getvalue(), "image/png")},
        )
        response.raise_for_status()
        return response.json()["id"]

    source, mask = upload("image"), upload("mask")
    body = {
        "type": "local_edit",
        "intent": "submit",
        "display_name": "积分验证 · 普通单图（模拟结果）",
        "input": {"source_asset_id": source, "selection_mask_asset_id": mask},
        "configuration": {
            "instruction": "将局部改为深蓝色",
            "quality": "balanced",
            "output_format": "png",
        },
    }
    quote = client.post(BASE + "/credits/quote", json=body)
    quote.raise_for_status()
    assert quote.json()["estimated_credits"] == 5
    response = client.post(
        BASE + "/jobs", headers={"Idempotency-Key": str(uuid4())}, json=body
    )
    response.raise_for_status()
    job_id = response.json()["id"]
    result = client.get(BASE + "/jobs/" + job_id).json()
    for _ in range(50):
        if result["status"] in {"completed", "partial", "failed", "cancelled"}:
            break
        time.sleep(0.1)
        result = client.get(BASE + "/jobs/" + job_id).json()
    after = client.get(BASE + "/credits").json()
    assert result["status"] == "completed", result.get("error_message")
    outputs = [
        link
        for link in result["assets"]
        if link["direction"] == "output" and link["is_deliverable"]
    ]
    assert len(outputs) == 1, result
    assert result["cost"]["actual_credits"] == 5
    assert after["balance_credits"] == before["balance_credits"] - 5
    assert after["reserved_credits"] == 0
    print(
        {
            "job_id": job_id,
            "status": result["status"],
            "credits_before": before["balance_credits"],
            "credits_after": after["balance_credits"],
            "charged": 5,
        }
    )
