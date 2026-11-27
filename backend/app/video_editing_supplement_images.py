"""AI supplement images (plan §4): prompt, cache, one hold per image (W4, v3).

* The model only proposes ``subject`` / ``purpose``; the server assembles the
  prompt from a fixed style anchor (shared by every image of one video), the
  purpose phrase, the subject and fixed negative constraints.
* Cache: ``sha256(prompt + model + size + anchor version)`` per workspace. A
  hit reuses the stored image and creates no hold (not charged).
* Billing: one ``editing_auto_image`` hold per request (owner_type
  ``video_editing_image``). Success settles; provider failure, content-policy
  refusal or timeout releases. A crashed run is released by the sweep.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import logging
from datetime import timedelta
from typing import Any
from uuid import uuid4

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .models import utc_now
from .video_editing_materials import material_file
from .video_editing_task_models import EditingImageRequestRecord, EditingMaterialRecord

logger = logging.getLogger(__name__)

ACTION = "editing_auto_image"
OWNER_TYPE = "video_editing_image"
ANCHOR_VERSION = "anchor/1"
SIZE = "1024x1536"
STALE_AFTER = timedelta(minutes=15)
STYLE_ANCHORS = {
    "bright": "明亮干净的商业产品摄影，浅暖灰背景，柔和顶光，浅景深，干净留白",
    "warm": "温暖的生活方式摄影，自然窗光，暖色调，胶片质感，低饱和",
    "minimal": "极简静物摄影，米白背景，柔和侧光，大面积留白，高级质感",
}
PURPOSE_PHRASES = {
    "scene": "生活场景画面：",
    "usage": "使用动作特写：",
    "texture": "成分或质地微距特写：",
    "concept": "概念意象画面：",
    "comparison": "直观的对比示意画面（不出现文字）：",
}
NEGATIVE = "画面内无任何文字、无 logo、无水印、无品牌名、无人脸特写。"
COMPOSITION = "竖版构图，主体居中偏下，上方约 20% 留白。"
_semaphores: dict[str, asyncio.Semaphore] = {}


class ImageRefused(Exception):
    """Content policy refusal: never retried, never charged."""


def prompt_for(style: str, purpose: str, subject: str) -> str:
    anchor = STYLE_ANCHORS.get(style, STYLE_ANCHORS["bright"])
    phrase = PURPOSE_PHRASES.get(purpose, PURPOSE_PHRASES["scene"])
    # Subject is untrusted model output: quoted as content, never instructions.
    clean = subject.replace("\n", " ").replace("「", "").replace("」", "")[:60]
    return f"{anchor}。{phrase}「{clean}」。{COMPOSITION}{NEGATIVE}"


def cache_key(settings: Settings, prompt: str) -> str:
    return hashlib.sha256(
        "\n".join((ANCHOR_VERSION, settings.image_model, SIZE, prompt)).encode()
    ).hexdigest()


def available(settings: Settings) -> bool:
    return bool(
        settings.video_supplement_ai_image_enabled
        and settings.image_api_key.get_secret_value()
        and settings.image_base_url.startswith("https://")
    )


def _routes(settings: Settings) -> list[tuple[str, str, str]]:
    routes = [
        (
            settings.image_base_url.rstrip("/"),
            settings.image_api_key.get_secret_value(),
            settings.image_model,
        )
    ]
    if (
        settings.provider_failover_enabled
        and settings.provider_failover_api_key.get_secret_value()
        and settings.provider_failover_base_url.startswith("https://")
    ):
        routes.append(
            (
                settings.provider_failover_base_url.rstrip("/"),
                settings.provider_failover_api_key.get_secret_value(),
                settings.provider_failover_image_model,
            )
        )
    return routes


async def call_provider(
    settings: Settings,
    prompt: str,
    idempotency_key: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> bytes:
    """One generated JPEG/PNG payload. Raises ImageRefused / RuntimeError."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=httpx.Timeout(170.0, connect=15.0))
    last: Exception | None = None
    try:
        for base, key, model in _routes(settings):
            try:
                response = await client.post(
                    f"{base}/v1/images/generations",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Idempotency-Key": idempotency_key,
                    },
                    json={
                        "model": model,
                        "prompt": prompt,
                        "n": 1,
                        "size": SIZE,
                        "quality": "medium",
                        "response_format": "b64_json",
                    },
                )
            except httpx.TransportError as error:
                last = error
                continue
            text = response.text[:2000].lower()
            if response.status_code in (400, 403, 422) and (
                "content_policy" in text or "safety" in text or "moderation" in text
            ):
                raise ImageRefused()
            if response.status_code >= 500 or response.status_code == 429:
                last = RuntimeError(f"provider {response.status_code}")
                continue
            if response.status_code != 200:
                raise RuntimeError(f"provider {response.status_code}")
            data = response.json()
            item = (data.get("data") or [{}])[0]
            if item.get("b64_json"):
                return base64.b64decode(item["b64_json"])
            if item.get("url", "").startswith("https://"):
                got = await client.get(item["url"])
                got.raise_for_status()
                return got.content
            raise RuntimeError("provider returned no image")
        raise RuntimeError(f"all image routes failed: {last}")
    finally:
        if own:
            await client.aclose()


def _crop_jpeg(payload: bytes) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(payload)) as image:
        rgb = image.convert("RGB")
        out = io.BytesIO()
        rgb.save(out, format="JPEG", quality=92)
        return out.getvalue(), rgb.width, rgb.height


def store_image(
    session: Session,
    settings: Settings,
    row: EditingImageRequestRecord,
    payload: bytes,
    *,
    model: str,
    prompt: str,
    reused_from: str | None = None,
) -> EditingMaterialRecord:
    data, width, height = _crop_jpeg(payload)
    material_id = str(uuid4())
    target = material_file(settings, material_id, "image/jpeg")
    target.parent.mkdir(parents=True)
    target.write_bytes(data)
    material = EditingMaterialRecord(
        id=material_id,
        request_id=f"ai-{row.id}"[:40],
        workspace_id=row.workspace_id,
        owner_user_id=row.owner_user_id,
        project_id=row.project_id,
        kind="image",
        mime="image/jpeg",
        sha256=hashlib.sha256(data).hexdigest(),
        bytes=len(data),
        label=f"AI 配图：{row.subject}"[:120],
        description=f"{row.sentence[:200]}（画面：{row.subject[:120]}）",
        width=width,
        height=height,
        origin="ai_generated",
        provenance={
            "provider": "site_image_gateway",
            "model": model,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "cache_key": row.cache_key,
            "image_request_id": row.id,
            "reused_from": reused_from,
            "license": "AI 生成，归本工作区使用",
            "sentence_index": row.sentence_index,
            "work_item_ref": row.work_item_ref,
        },
    )
    session.add(material)
    return material


def cached_material(
    session: Session, row: EditingImageRequestRecord
) -> EditingMaterialRecord | None:
    previous = session.scalar(
        select(EditingImageRequestRecord)
        .where(
            EditingImageRequestRecord.workspace_id == row.workspace_id,
            EditingImageRequestRecord.cache_key == row.cache_key,
            EditingImageRequestRecord.status == "succeeded",
            EditingImageRequestRecord.material_id.is_not(None),
            EditingImageRequestRecord.id != row.id,
        )
        .order_by(EditingImageRequestRecord.created_at.desc())
    )
    if previous is None:
        return None
    return session.get(EditingMaterialRecord, previous.material_id)


async def run_request(
    factory: sessionmaker[Session], settings: Settings, request_id: str
) -> None:
    """Generate one image row; settle/release its hold from the outcome."""
    from .video_credit_billing import reconcile_owner

    with factory() as session:
        row = session.get(EditingImageRequestRecord, request_id)
        if row is None or row.status != "queued":
            return
        row.status = "running"
        session.commit()
        prompt = prompt_for(row.style, row.purpose, row.subject)
        workspace = row.workspace_id
    semaphore = _semaphores.setdefault(workspace, asyncio.Semaphore(3))
    outcome: tuple[str, str | None, bytes | None] = ("failed", "AI_IMAGE_FAILED", None)
    async with semaphore:
        try:
            payload = await asyncio.wait_for(
                call_provider(settings, prompt, f"editing-image-{request_id}"), 180
            )
            outcome = ("succeeded", None, payload)
        except ImageRefused:
            outcome = ("failed", "AI_IMAGE_REFUSED", None)
        except TimeoutError:
            outcome = ("failed", "AI_IMAGE_TIMEOUT", None)
        except Exception:  # noqa: BLE001
            logger.warning("editing_image_failed id=%s", request_id, exc_info=True)
    with factory() as session:
        row = session.get(EditingImageRequestRecord, request_id)
        if row is None:
            return
        status, code, result = outcome
        if result is not None:
            try:
                material = store_image(
                    session,
                    settings,
                    row,
                    result,
                    model=settings.image_model,
                    prompt=prompt,
                )
                row.material_id = material.id
            except Exception:  # noqa: BLE001 — unreadable payload: not charged
                logger.warning(
                    "editing_image_store_failed id=%s", request_id, exc_info=True
                )
                status, code = "failed", "AI_IMAGE_INVALID"
        row.status, row.error_code = status, code
        session.commit()
        reconcile_owner(session, OWNER_TYPE, row.id)  # type: ignore[arg-type]
        session.commit()


def classify(session: Session, owner_id: str) -> str | None:
    """Billing classifier: settle on success, release on failure/stale."""
    row = session.get(EditingImageRequestRecord, owner_id, populate_existing=True)
    if row is None:
        return "release"
    if row.status == "succeeded":
        return "settle"
    if row.status == "failed":
        return "release"
    updated = row.updated_at
    if updated is not None and updated.tzinfo is None:
        from datetime import UTC

        updated = updated.replace(tzinfo=UTC)
    if updated is not None and utc_now() - updated > STALE_AFTER:
        row.status, row.error_code = "failed", "AI_IMAGE_TIMEOUT"
        session.flush()
        return "release"
    return None


def public(row: EditingImageRequestRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "request_id": row.request_id,
        "work_item_ref": row.work_item_ref,
        "sentence_index": row.sentence_index,
        "sentence": row.sentence,
        "subject": row.subject,
        "status": row.status,
        "reused": row.reused,
        "material_id": row.material_id,
        "error": {
            "AI_IMAGE_REFUSED": "这句画面没通过内容审核，未生成、不扣积分。",
            "AI_IMAGE_TIMEOUT": "生成超时，未扣积分，可重试。",
            "AI_IMAGE_INVALID": "生成结果无法使用，未扣积分，可重试。",
            "AI_IMAGE_FAILED": "生成失败，未扣积分，可重试。",
        }.get(row.error_code or "")
        if row.status == "failed"
        else None,
    }
