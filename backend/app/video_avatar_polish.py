# ruff: noqa: E501
"""AI 润色：定制形象时，把用户上传的本人 / 授权照片润色成数字人可用的形象照。

流程：上传照片 + 授权确认 + 描述 → 生成 1～2 张候选（参考图编辑，锁定本人五官）→
商家选一张（或用原图）→ 走原有 ``POST /avatar-clones`` 创建形象。

- 安全：沿用形象授权勾选；描述里要求换成他人 / 名人的脸、或不适宜内容时直接拒绝（不调用、不扣费）；
  供应商的内容安全拦截给出友好中文提示。
- 计费：每张候选单独冻结 ``avatar_polish``（默认 7 积分），只有通过规格检查的候选结算，
  失败 / 不合格的释放，不扣费。
- 规格：竖版、短边 ≥ 768、能检测到清晰正脸且大小 / 位置合适（检测模型不可用时只查尺寸）。
- 图片服务：站点已配置的 OpenAI 兼容 ``/v1/images/edits``（``POLARIS_IMAGE_*``）；
  测试替换 ``app.state.video_avatar_polish_client``。
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import shutil
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Protocol
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from . import video_credit_billing as video_credits
from .auth import SessionDependency, WorkspaceContext, require_workspace_write
from .config import Settings
from .errors import ApiError
from .models import utc_now
from .video_avatar_polish_models import VideoAvatarPolishRecord
from .video_avatar_uploads import CONSENT_VERSION, IMAGE_BYTES
from .video_studio_routes import VideoWorkspace
from .video_studio_schemas import StrictVideoModel

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/v1/video-studio/workspaces/{workspace_id}", tags=["video-avatars"]
)

OUTPUT_SIZE = "1200x1600"  # 3:4 竖版，中转接受的尺寸
MIN_SHORT_SIDE = 768
MAX_DESCRIPTION = 120
ACTION = "avatar_polish"
OWNER: Final = "video_avatar_polish"

# ---------------------------------------------------------------- 描述安全检查

_FACE_SWAP = re.compile(
    r"换脸|换.{0,4}脸|(变成|换成|改成|弄成|p成|P成).{0,12}(的脸|的长相|的五官|的面孔)|脸.{0,4}换成|别人的脸|他人的脸|别人的长相|"
    r"(变成|换成|改成|弄成|p成|P成).{0,12}(明星|名人|网红|演员|歌手|偶像|总统|主席)|"
    r"(长得|长相|脸).{0,6}像|像.{0,12}(明星|名人|演员|歌手|偶像)|"
    r"明星脸|名人脸|网红脸|整容成|"
    r"face\s*-?\s*swap|deep\s*-?\s*fake|celebrity",
    re.IGNORECASE,
)
_UNSAFE = re.compile(
    r"裸|露点|色情|情色|性感内衣|比基尼|泳装|暴露|走光|低胸|透视装|血腥|暴力|"
    r"毒品|未成年|nude|naked|nsfw|lingerie|bikini|sexy",
    re.IGNORECASE,
)


def description_rejection(text: str) -> str | None:
    """描述不合规时返回中文提示；合规返回 None。不调用任何服务。"""

    if _FACE_SWAP.search(text):
        return "AI 润色只会在保持你本人五官的前提下修改穿着、场景和光线，不能换成他人或名人的脸。请改一下描述。"
    if _UNSAFE.search(text):
        return "描述里有不适合用于数字人形象的内容，请换成穿着、场景、光线方面的描述。"
    return None


PRESETS: dict[str, str] = {
    "职业西装·干净背景": "穿合身的深色西装、白衬衫，干净的浅灰色纯色背景，柔和均匀的影棚光",
    "门店店长·暖光": "穿整洁的店长工作服，站在明亮整洁的门店里，背景虚化，暖色自然光",
    "居家主播·自然光": "穿简洁的日常针织上衣，坐在干净温馨的客厅里，背景虚化，窗边柔和自然光",
    "户外街景·清爽": "穿清爽的休闲衬衫，站在干净的城市街道旁，背景虚化，白天柔和日光",
}


def build_prompt(description: str, slot: int) -> str:
    variation = (
        "Framing A: half-body from head to waist, centered."
        if slot == 1
        else "Framing B: slightly wider half-body from head to hips, centered, a touch more background."
    )
    return (
        "Edit the reference photo of a real person into a realistic portrait for a "
        "talking-head digital human video.\n"
        "IDENTITY LOCK (highest priority): it must remain exactly the same person — same "
        "face shape, eyes, eyebrows, nose, mouth, ears, skin tone, age, hairline and "
        "hairstyle length. Do not beautify into a different face, do not change gender, "
        "age or ethnicity. If anything below conflicts with the identity lock, keep the "
        "identity.\n"
        "Composition: exactly one person, facing the camera directly, eyes looking into "
        "the lens, natural closed-mouth expression, head and both shoulders fully in "
        "frame, nothing covering the face or mouth. Arms relaxed down by the body; if "
        "hands are visible they have natural anatomy with five fingers each. "
        f"{variation}\n"
        "Quality: photorealistic, sharp focus on the face, soft even lighting on the face, "
        "clean uncluttered background, no text, no watermark, no logo, no extra people, "
        "no distortion.\n"
        f"Requested style (outfit, scene, light): {description}"
    )


# ---------------------------------------------------------------- 图片服务


class PolishImageError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class PolishImageResult:
    image: Image.Image
    model_requested: str
    model_reported: str | None


class PolishImageClient(Protocol):
    def edit(
        self, reference_png: bytes, prompt: str, *, idempotency_key: str
    ) -> PolishImageResult: ...


_SAFETY_HINTS = (
    "moderation",
    "safety",
    "content_policy",
    "content policy",
    "sensitive",
)


@dataclass(frozen=True)
class ImageRoute:
    name: str
    base_url: str
    api_key: str
    model: str


def image_routes(settings: Settings) -> list[ImageRoute]:
    """与站内生图同一套路由：主通道，再按 POLARIS_PROVIDER_FAILOVER_* 的备用通道（多 key 各成一条）。

    与 W5 的 video_image_routes 规则一致；该模块进集成分支后可改为直接复用。
    """

    routes: list[ImageRoute] = []
    primary_key = settings.image_api_key.get_secret_value().strip()
    if primary_key and settings.image_base_url.startswith("https://"):
        routes.append(
            ImageRoute(
                "primary",
                settings.image_base_url.rstrip("/"),
                primary_key,
                settings.image_model,
            )
        )
    keys = [
        part.strip()
        for part in re.split(
            r"[\s,]+", settings.provider_failover_api_key.get_secret_value()
        )
        if part.strip()
    ]
    if (
        settings.provider_failover_enabled
        and keys
        and settings.provider_failover_base_url.startswith("https://")
    ):
        for index, key in enumerate(keys, start=1):
            routes.append(
                ImageRoute(
                    "failover" if len(keys) == 1 else f"failover-{index}",
                    settings.provider_failover_base_url.rstrip("/"),
                    key,
                    settings.provider_failover_image_model,
                )
            )
    return routes


class _RouteUnavailable(Exception):
    pass


class HttpPolishImageClient:
    """逐条通道尝试；只有连不上、超时、5xx、401/403、429 才换下一条，被拒（其余 4xx）不重试。"""

    def __init__(self, settings: Settings, timeout_seconds: float = 300):
        self.routes = image_routes(settings)
        self.timeout = timeout_seconds

    def edit(
        self, reference_png: bytes, prompt: str, *, idempotency_key: str
    ) -> PolishImageResult:
        if not self.routes:
            raise PolishImageError("AVATAR_POLISH_NOT_CONFIGURED", "AI 润色暂不可用。")
        last = PolishImageError("AVATAR_POLISH_UNAVAILABLE", "AI 润色服务暂时连不上。")
        for route in self.routes:
            try:
                return self._call(route, reference_png, prompt, idempotency_key)
            except _RouteUnavailable as exc:
                logger.warning(
                    "avatar_polish_route_unavailable route=%s reason=%s",
                    route.name,
                    exc,
                )
                last = PolishImageError(
                    "AVATAR_POLISH_TIMEOUT"
                    if str(exc) == "timeout"
                    else "AVATAR_POLISH_UNAVAILABLE",
                    "AI 润色服务暂时连不上。",
                )
        raise last

    def _call(
        self, route: ImageRoute, reference_png: bytes, prompt: str, key: str
    ) -> PolishImageResult:
        try:
            response = httpx.post(
                route.base_url + "/v1/images/edits",
                headers={
                    "Authorization": f"Bearer {route.api_key}",
                    "Idempotency-Key": key,
                },
                data={
                    "model": route.model,
                    "prompt": prompt,
                    "n": "1",
                    "size": OUTPUT_SIZE,
                    "quality": "medium",
                    "output_format": "png",
                    "response_format": "b64_json",
                },
                files=[("image", ("portrait.png", reference_png, "image/png"))],
                timeout=self.timeout,
            )
        except httpx.TimeoutException:
            raise _RouteUnavailable("timeout") from None
        except httpx.HTTPError:
            raise _RouteUnavailable("transport") from None
        status = response.status_code
        if status >= 500 or status in {401, 403, 429}:
            raise _RouteUnavailable(str(status))
        if status >= 400:
            text = response.text[:2000].lower()
            if any(h in text for h in _SAFETY_HINTS):
                raise PolishImageError(
                    "AVATAR_POLISH_UNSAFE", "这张照片或描述没有通过内容安全检查。"
                )
            raise PolishImageError(
                "AVATAR_POLISH_REJECTED", "AI 润色服务没有返回图片。"
            )
        try:
            body = response.json()
            item = body["data"][0]
            if item.get("b64_json"):
                raw = base64.b64decode(item["b64_json"])
            else:
                fetched = httpx.get(item["url"], timeout=120)
                fetched.raise_for_status()
                raw = fetched.content
            image = Image.open(io.BytesIO(raw))
            image.load()
        except Exception:
            raise PolishImageError(
                "AVATAR_POLISH_INVALID", "AI 润色返回的图片无法读取。"
            ) from None
        reported = body.get("model") if isinstance(body, dict) else None
        return PolishImageResult(
            image.convert("RGB"), f"{route.name}:{route.model}", reported
        )


def image_client(request: Request) -> PolishImageClient:
    client = getattr(request.app.state, "video_avatar_polish_client", None)
    return client or HttpPolishImageClient(request.app.state.settings)


# ---------------------------------------------------------------- 规格检查


def detect_face(
    image: Image.Image,
) -> tuple[tuple[int, int, int, int], float] | None | bool:
    """最大人脸；检测模型不可用时返回 False（只做尺寸检查）。"""

    try:
        from .bihuo_suite.subject import FaceDetector, model_available
    except Exception:  # pragma: no cover - 依赖缺失
        return False
    if not model_available():
        return False
    try:
        scale = 4 if min(image.size) >= 720 else 2
        return FaceDetector(size=image.size, scale=scale).detect(image.convert("RGB"))
    except Exception:  # pragma: no cover - 检测失败不阻断，只记录
        logger.warning("avatar_polish_face_detect_failed", exc_info=True)
        return False


# 和最大的那张脸相比，高度不到这个比例的（远处路人、海报上的小脸）不算第二张脸。
SECOND_FACE_RATIO = 0.4


def count_faces(image: Image.Image) -> int | None:
    """照片里够大的人脸数；检测模型不可用时返回 None（不拦截）。"""

    try:
        from .bihuo_suite.subject import FaceDetector, model_available
    except Exception:  # pragma: no cover - 依赖缺失
        return None
    if not model_available():
        return None
    try:
        import numpy as np

        # 与剪辑共用的 FaceDetector 只返回最大的一张脸；这里直接读它的全部检测结果，
        # 不改 bihuo_suite（模板 bundle 身份的一部分）。
        scale = 4 if min(image.size) >= 720 else 2
        detector = FaceDetector(size=image.size, scale=scale)
        small = image.convert("RGB").resize(detector.small)
        bgr = np.ascontiguousarray(np.asarray(small, dtype=np.uint8)[..., ::-1])
        _, faces = detector.detector.detect(bgr)
    except Exception:  # pragma: no cover - 检测失败不阻断，只记录
        logger.warning("avatar_polish_face_count_failed", exc_info=True)
        return None
    if faces is None or not len(faces):
        return 0
    heights = [float(row[3]) for row in faces]
    tallest = max(heights)
    return sum(1 for height in heights if height >= tallest * SECOND_FACE_RATIO)


def reject_multiple_faces(reference: Path) -> None:
    """多人照片在下单前拒绝：不建候选、不冻结积分、不调用生图。"""

    with Image.open(reference) as image:
        found = count_faces(image)
    if found is not None and found > 1:
        raise ApiError(
            422,
            "VIDEO_AVATAR_MULTIPLE_FACES",
            "照片里有多张人脸，请上传单人照片。",
        )


def spec_check(image: Image.Image) -> tuple[bool, dict[str, Any]]:
    """数字人可用的规格：竖版、清晰尺寸、单张正脸大小与位置合适。"""

    width, height = image.size
    checks: dict[str, Any] = {
        "width": width,
        "height": height,
        "size_ok": min(width, height) >= MIN_SHORT_SIDE and height >= width,
    }
    found = detect_face(image)
    if found is False:
        checks["face"] = "unchecked"
        return bool(checks["size_ok"]), checks
    if not found:
        checks.update(face="missing", face_ok=False)
        return False, checks
    (x0, y0, x1, y1), score = found  # type: ignore[misc]
    face_h = (y1 - y0) / height
    center_x = (x0 + x1) / 2 / width
    checks.update(
        face="found",
        face_score=round(score, 3),
        face_height_ratio=round(face_h, 3),
        face_center_x=round(center_x, 3),
        face_ok=0.06 <= face_h <= 0.6 and 0.2 <= center_x <= 0.8 and y0 >= 0,
    )
    return bool(checks["size_ok"] and checks["face_ok"]), checks


SPEC_MESSAGE = (
    "这张候选不适合做数字人（需要竖版、正面、脸部清晰居中），已自动作废，不扣费。"
)
ERROR_MESSAGES = {
    "AVATAR_POLISH_UNSAFE": "这张照片或描述没有通过内容安全检查，请换一张本人照片或修改描述。不扣费。",
    "AVATAR_POLISH_SPEC": SPEC_MESSAGE,
    "AVATAR_POLISH_TIMEOUT": "AI 润色超时了，不扣费，可以重新生成。",
    "AVATAR_POLISH_UNAVAILABLE": "AI 润色服务暂时连不上，不扣费，请稍后再试。",
    "AVATAR_POLISH_NOT_CONFIGURED": "AI 润色暂不可用，可以直接用原图创建形象。",
}


# ---------------------------------------------------------------- 存储与响应


def polish_root(settings: Settings) -> Path:
    return Path(settings.video_media_dir) / "avatar-polish"


class PolishCandidateResponse(StrictVideoModel):
    id: str
    request_id: str
    slot: int
    status: Literal["queued", "running", "ready", "failed"]
    description: str
    error_code: str | None
    message: str | None
    image_url: str | None
    credits: int | None
    created_at: datetime


def _credits(session: Session, row: VideoAvatarPolishRecord) -> int | None:
    holds = video_credits._holds(session, OWNER, row.id, ACTION)  # noqa: SLF001
    if not holds:
        return None
    hold = holds[0]
    return hold.settled_credits or hold.reserved_credits


def response(session: Session, row: VideoAvatarPolishRecord) -> PolishCandidateResponse:
    return PolishCandidateResponse(
        id=row.id,
        request_id=row.request_id,
        slot=row.slot,
        status=row.status,  # type: ignore[arg-type]
        description=row.description,
        error_code=row.error_code,
        message=ERROR_MESSAGES.get(row.error_code or "", "这张没有生成成功，不扣费。")
        if row.status == "failed"
        else None,
        image_url=(
            f"/api/v1/video-studio/workspaces/{row.workspace_id}/avatar-polishes/{row.id}/image"
            if row.status == "ready"
            else None
        ),
        credits=_credits(session, row),
        created_at=row.created_at,
    )


def scoped(workspace: WorkspaceContext) -> tuple[Any, Any]:
    return (
        VideoAvatarPolishRecord.workspace_id == workspace.workspace_id,
        VideoAvatarPolishRecord.owner_user_id == workspace.principal.user_id,
    )


def normalize_source(source: Path, target: Path) -> None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError()
                if min(image.size) < 256 or max(image.size) > 8192:
                    raise ValueError()
                image.load()
                normalized = ImageOps.exif_transpose(image).convert("RGB")
                normalized.thumbnail((1536, 1536))
                normalized.save(target, format="PNG")
    except (OSError, ValueError, Image.DecompressionBombError, Warning):
        raise ApiError(
            422,
            "VIDEO_AVATAR_IMAGE_INVALID",
            "请上传清晰的 JPG、PNG 或 WebP 照片，边长为 256～8192 像素。",
        ) from None


# ---------------------------------------------------------------- 后台处理


def _run_one(
    factory: sessionmaker[Session],
    settings: Settings,
    client: PolishImageClient,
    row_id: str,
    reference: bytes,
) -> None:
    with factory() as session:
        row = session.get(VideoAvatarPolishRecord, row_id)
        if row is None or row.status not in {"queued", "running"}:
            return
        row.status = "running"
        session.commit()
        description, slot, workspace_id = row.description, row.slot, row.workspace_id
        root = Path(row.source_path).parent
    started = time.monotonic()
    prompt = build_prompt(description, slot)
    status, error_code, result_path = "failed", None, None
    checks: dict[str, Any] = {}
    receipt: dict[str, Any] = {
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
    }
    try:
        result = client.edit(
            reference, prompt, idempotency_key=f"avatar-polish-{row_id}"
        )
        receipt.update(
            model_requested=result.model_requested, model_reported=result.model_reported
        )
        ok, checks = spec_check(result.image)
        target = root / f"candidate-{slot}.jpg"
        result.image.save(target, format="JPEG", quality=94)
        receipt["result_sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        if ok:
            status, result_path = "ready", str(target)
        else:
            error_code = "AVATAR_POLISH_SPEC"
    except PolishImageError as exc:
        error_code = exc.code
    except Exception:
        logger.exception(
            "avatar_polish_failed id=%s workspace=%s", row_id, workspace_id
        )
        error_code = "AVATAR_POLISH_FAILED"
    receipt["seconds"] = round(time.monotonic() - started, 2)
    with factory() as session:
        row = session.get(VideoAvatarPolishRecord, row_id)
        if row is None:
            return
        row.status, row.error_code, row.result_path = status, error_code, result_path
        row.checks, row.receipt = checks, {**(row.receipt or {}), **receipt}
        session.commit()
        video_credits.reconcile_owner(session, OWNER, row_id)
        session.commit()


def process(
    factory: sessionmaker[Session],
    settings: Settings,
    client: PolishImageClient,
    row_ids: list[str],
    reference_path: str,
) -> None:
    reference = Path(reference_path).read_bytes()
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in [
            pool.submit(_run_one, factory, settings, client, rid, reference)
            for rid in row_ids
        ]:
            future.result()


# ---------------------------------------------------------------- 路由


@router.post("/avatar-polishes", response_model=list[PolishCandidateResponse])
async def create_polish(
    request: Request,
    background: BackgroundTasks,
    workspace: VideoWorkspace,
    session: SessionDependency,
    request_id: Annotated[UUID, Form()],
    description: Annotated[str, Form(min_length=1, max_length=MAX_DESCRIPTION)],
    consent: Annotated[bool, Form()],
    consent_version: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    count: Annotated[int, Form(ge=1, le=2)] = 2,
) -> list[PolishCandidateResponse]:
    require_workspace_write(workspace)
    if not consent or consent_version != CONSENT_VERSION:
        raise ApiError(
            422, "VIDEO_AVATAR_CONSENT_REQUIRED", "请确认这是你本人或已获授权的照片。"
        )
    text = " ".join(description.split())
    if not text:
        raise ApiError(422, "VIDEO_AVATAR_POLISH_DESCRIPTION", "请写一句想要的样子。")
    rejection = description_rejection(text)
    if rejection:
        raise ApiError(422, "VIDEO_AVATAR_POLISH_PROMPT_REJECTED", rejection)
    settings: Settings = request.app.state.settings
    if not settings.video_providers_enabled:
        raise ApiError(503, "VIDEO_PROVIDER_DISABLED", "AI 润色暂不可用。")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise ApiError(
            422, "VIDEO_AVATAR_TYPE_INVALID", "AI 润色只支持 JPG、PNG、WebP 照片。"
        )

    directory = polish_root(settings) / str(uuid4())
    directory.mkdir(parents=True)
    retained = False
    try:
        source = directory / ("source" + suffix)
        digest = hashlib.sha256()
        size = 0
        with source.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > IMAGE_BYTES:
                    raise ApiError(413, "VIDEO_AVATAR_TOO_LARGE", "照片最大 10 MB。")
                digest.update(chunk)
                out.write(chunk)
        fingerprint = hashlib.sha256(
            json.dumps(
                {"sha256": digest.hexdigest(), "description": text, "count": count},
                sort_keys=True,
            ).encode()
        ).hexdigest()

        def existing() -> list[VideoAvatarPolishRecord]:
            return list(
                session.scalars(
                    select(VideoAvatarPolishRecord)
                    .where(
                        VideoAvatarPolishRecord.request_id == str(request_id),
                        *scoped(workspace),
                    )
                    .order_by(VideoAvatarPolishRecord.slot)
                ).all()
            )

        def reconcile(
            rows: list[VideoAvatarPolishRecord],
        ) -> list[PolishCandidateResponse]:
            if rows[0].request_hash != fingerprint:
                raise ApiError(
                    409,
                    "VIDEO_REQUEST_REUSED",
                    "这次提交和之前的照片或描述不同，请刷新后重试。",
                )
            return [response(session, row) for row in rows]

        old = existing()
        if old:
            return reconcile(old)
        reference = directory / "reference.png"
        await run_in_threadpool(normalize_source, source, reference)
        await run_in_threadpool(reject_multiple_faces, reference)
        now = utc_now()
        rows = [
            VideoAvatarPolishRecord(
                id=str(uuid4()),
                workspace_id=workspace.workspace_id,
                owner_user_id=workspace.principal.user_id,
                request_id=str(request_id),
                request_hash=fingerprint,
                slot=slot,
                status="queued",
                description=text,
                source_path=str(reference),
                source_sha256=digest.hexdigest(),
                consent_version=consent_version,
                consent_at=now,
                checks={},
                receipt={},
            )
            for slot in range(1, count + 1)
        ]
        session.add_all(rows)
        try:
            session.flush()
            for row in rows:
                video_credits.hold(
                    session, settings, workspace.workspace_id, ACTION, OWNER, row.id
                )
            session.commit()
        except IntegrityError:
            session.rollback()
            old = existing()
            if old:
                return reconcile(old)
            raise
        retained = True
        background.add_task(
            process,
            request.app.state.session_factory,
            settings,
            image_client(request),
            [row.id for row in rows],
            str(reference),
        )
        return [response(session, row) for row in rows]
    finally:
        await file.close()
        if not retained:
            shutil.rmtree(directory, ignore_errors=True)


@router.get("/avatar-polishes", response_model=list[PolishCandidateResponse])
def list_polishes(
    workspace: VideoWorkspace,
    session: SessionDependency,
    request_id: Annotated[UUID, Query()],
) -> list[PolishCandidateResponse]:
    rows = session.scalars(
        select(VideoAvatarPolishRecord)
        .where(
            VideoAvatarPolishRecord.request_id == str(request_id), *scoped(workspace)
        )
        .order_by(VideoAvatarPolishRecord.slot)
    ).all()
    return [response(session, row) for row in rows]


@router.get("/avatar-polishes/{polish_id}/image")
def polish_image(
    polish_id: str, workspace: VideoWorkspace, session: SessionDependency
) -> FileResponse:
    row = session.scalar(
        select(VideoAvatarPolishRecord).where(
            VideoAvatarPolishRecord.id == polish_id, *scoped(workspace)
        )
    )
    if row is None or row.status != "ready" or not row.result_path:
        raise ApiError(404, "VIDEO_AVATAR_POLISH_NOT_FOUND", "未找到这张候选。")
    path = Path(row.result_path)
    if not path.is_file():
        raise ApiError(
            404, "VIDEO_AVATAR_POLISH_NOT_FOUND", "这张候选已过期，请重新生成。"
        )
    return FileResponse(
        path,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/avatar-polish-presets")
def presets(workspace: VideoWorkspace) -> list[dict[str, str]]:
    return [{"label": label, "description": text} for label, text in PRESETS.items()]
