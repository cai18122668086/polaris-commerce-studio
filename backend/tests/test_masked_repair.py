import asyncio
import hashlib
from collections.abc import Sequence
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from app.domain import AssetLifecycleStatus, AssetMediaKind, AssetOriginKind
from app.masked_repair import (
    MaskedEditCallResult,
    MaskedEditGatewayRequest,
    MaskedVisualReviewCallResult,
    MaskedVisualReviewRequest,
)
from app.models import (
    AssetRecord,
    AuditEventRecord,
    JobAssetRecord,
    JobAttemptRecord,
    UsageEventRecord,
    WorkspaceRecord,
)
from app.outbox import publish_pending_events
from app.provider import (
    ProviderArtifact,
    ProviderOutcome,
    ProviderRequest,
    ProviderResult,
)
from app.task_runner import MockTaskRunner
from app.xinghe_agent import FakeXingheGateway, OperationRoutingProvider
from tests.test_api import WORKSPACE_ID, local_edit_payload


def _png(
    size: tuple[int, int],
    color: tuple[int, int, int, int],
) -> bytes:
    buffer = BytesIO()
    Image.new("RGBA", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _selection_png(
    size: tuple[int, int],
    *,
    selected: Sequence[tuple[int, int]],
) -> bytes:
    image = Image.new("L", size, 0)
    for point in selected:
        image.putpixel(point, 255)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _upload(
    client: TestClient,
    payload: bytes,
    *,
    media_kind: str,
    filename: str,
) -> dict:
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/assets",
        headers={"Idempotency-Key": str(uuid4())},
        data={"origin_kind": "upload", "media_kind": media_kind},
        files={"file": (filename, payload, "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_job(
    client: TestClient,
    source_id: str,
    mask_id: str,
) -> tuple[int, dict]:
    response = client.post(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs",
        headers={"Idempotency-Key": str(uuid4())},
        json=local_edit_payload(source_id, mask_id),
    )
    return response.status_code, response.json()


def _artifact(payload: bytes) -> ProviderArtifact:
    with Image.open(BytesIO(payload)) as image:
        width, height = image.size
    return ProviderArtifact(
        payload=payload,
        filename="raw.png",
        content_type="image/png",
        width=width,
        height=height,
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _usage() -> dict[str, int | bool | None]:
    return {
        "reported": True,
        "input_tokens": 0,
        "output_tokens": 0,
        "cached_tokens": 0,
        "total_tokens": 0,
    }


class OfflineMaskedGateway(FakeXingheGateway):
    provider_name = "tengli-offline"
    image_model = "gpt-image-2"
    pricing_version = "offline-test-v1"

    def __init__(
        self,
        outcomes: Sequence[str] = ("success",),
        *,
        review_success: bool | None = True,
    ) -> None:
        super().__init__()
        self.outcomes = list(outcomes)
        self.review_success = review_success
        self.masked_calls: list[MaskedEditGatewayRequest] = []
        self.review_calls: list[MaskedVisualReviewRequest] = []

    async def edit_masked(
        self,
        request: MaskedEditGatewayRequest,
    ) -> MaskedEditCallResult:
        self.masked_calls.append(request)
        outcome = self.outcomes.pop(0)
        if outcome == "transient":
            return MaskedEditCallResult(
                outcome=ProviderOutcome.FAILED,
                provider_request_id="offline_transient",
                raw_usage={},
                normalized_usage=_usage(),
                actual_cost_micros=0,
                estimated_cost_micros=80_000,
                error_code="LOCAL_EDIT_REQUEST_FAILED",
                error_message="controlled HTTP 503",
                retryable=True,
                http_status=503,
            )
        if outcome == "bad_request":
            return MaskedEditCallResult(
                outcome=ProviderOutcome.FAILED,
                provider_request_id="offline_bad_request",
                raw_usage={},
                normalized_usage=_usage(),
                actual_cost_micros=0,
                estimated_cost_micros=80_000,
                error_code="LOCAL_EDIT_REQUEST_FAILED",
                error_message="controlled HTTP 400",
                retryable=False,
                http_status=400,
            )
        raw = _png((request.width, request.height), (220, 20, 40, 255))
        return MaskedEditCallResult(
            outcome=ProviderOutcome.SUCCEEDED,
            provider_request_id="offline_success",
            raw_usage={"actual_cost_micros": 12_000},
            normalized_usage=_usage(),
            actual_cost_micros=12_000,
            estimated_cost_micros=80_000,
            artifact=_artifact(raw),
            http_status=200,
        )

    async def review_masked(
        self,
        request: MaskedVisualReviewRequest,
    ) -> MaskedVisualReviewCallResult:
        self.review_calls.append(request)
        return MaskedVisualReviewCallResult(
            provider_request_id="offline_review_success",
            raw_usage={"actual_cost_micros": 2_000},
            normalized_usage=_usage(),
            actual_cost_micros=2_000,
            estimated_cost_micros=10_000,
            visual_success=self.review_success,
            summary="Controlled offline visual-review result.",
            reason_codes=(
                ("offline_review_passed",)
                if self.review_success
                else ("instruction_not_satisfied",)
            ),
            error_code=(
                "LOCAL_EDIT_VISUAL_REVIEW_UNAVAILABLE"
                if self.review_success is None
                else None
            ),
            error_message=(
                "Controlled review unavailable."
                if self.review_success is None
                else None
            ),
            http_status=200,
        )


def _install_runner(
    client: TestClient,
    gateway: OfflineMaskedGateway,
) -> None:
    client.app.state.task_runner = MockTaskRunner(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=gateway,
        xinghe_concurrency=2,
        budget_limit_micros=200_000_000,
    )


def _dispatch(client: TestClient) -> int:
    return publish_pending_events(
        client.app.state.settings,
        client.app.state.session_factory,
        client.app.state.task_runner,
    )


def _valid_inputs(client: TestClient) -> tuple[dict, dict, bytes]:
    source_bytes = _png((8, 8), (10, 40, 90, 255))
    selected = [(x, y) for x in range(2, 6) for y in range(2, 6)]
    mask_bytes = _selection_png((8, 8), selected=selected)
    source = _upload(
        client,
        source_bytes,
        media_kind="image",
        filename="source.png",
    )
    mask = _upload(
        client,
        mask_bytes,
        media_kind="mask",
        filename="selection.png",
    )
    return source, mask, source_bytes


def test_real_local_edit_locks_every_outside_pixel_and_records_raw(
    client: TestClient,
) -> None:
    gateway = OfflineMaskedGateway()
    _install_runner(client, gateway)
    source, mask, source_bytes = _valid_inputs(client)
    status_code, job = _create_job(client, source["id"], mask["id"])
    assert status_code == 202

    assert _dispatch(client) == 1
    assert _dispatch(client) == 0

    with client.app.state.session_factory() as session:
        relations = session.scalars(
            select(JobAssetRecord)
            .where(JobAssetRecord.job_id == job["id"])
            .order_by(JobAssetRecord.id)
        ).all()
        raw_relation = next(item for item in relations if item.role == "provider_raw")
        output_relation = next(
            item for item in relations if item.role == "local_edit_result"
        )
        raw_asset = session.get(AssetRecord, raw_relation.asset_id)
        output_asset = session.get(AssetRecord, output_relation.asset_id)
        assert raw_asset is not None
        assert output_asset is not None
        assert raw_relation.is_deliverable is False
        assert output_relation.is_deliverable is True
        assert raw_asset.asset_metadata["immutable_provider_raw"] is True
        assert raw_asset.asset_metadata["source_sha256"] == source["sha256"]
        assert raw_asset.asset_metadata["mask_sha256"] == mask["sha256"]
        assert raw_asset.asset_metadata["provider_request_id"] == "offline_success"
        assert raw_asset.asset_metadata["raw_visual_success"] is True
        assert (
            raw_asset.asset_metadata["visual_review_request_id"]
            == "offline_review_success"
        )
        assert raw_relation.validation["raw_visual_success"] is True
        assert output_relation.validation["outside_changed_pixels"] == 0
        assert output_relation.validation["raw_visual_success"] is True
        output_key = output_asset.object_key

        assert (
            session.scalar(
                select(func.count())
                .select_from(JobAttemptRecord)
                .where(JobAttemptRecord.job_id == job["id"])
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(UsageEventRecord)
                .where(UsageEventRecord.job_id == job["id"])
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(AuditEventRecord)
                .where(
                    AuditEventRecord.resource_id == job["items"][0]["id"],
                    AuditEventRecord.action == "masked_repair.image_reserved",
                )
            )
            == 1
        )

    delivered = asyncio.run(client.app.state.storage.read_bytes(output_key))
    with Image.open(BytesIO(source_bytes)) as source_image:
        source_rgba = source_image.convert("RGBA")
    with Image.open(BytesIO(delivered)) as result_image:
        result_rgba = result_image.convert("RGBA")
    assert result_rgba.size == source_rgba.size == (8, 8)
    for y in range(8):
        for x in range(8):
            if not (2 <= x < 6 and 2 <= y < 6):
                assert result_rgba.getpixel((x, y)) == source_rgba.getpixel((x, y))
    assert len(gateway.masked_calls) == 1
    assert gateway.masked_calls[0].idempotency_key
    assert len(gateway.review_calls) == 1
    assert gateway.review_calls[0].source_png == source_bytes
    assert gateway.review_calls[0].authority_png
    assert gateway.review_calls[0].candidate_png


def test_visual_review_rejection_retains_raw_without_delivery_or_regeneration(
    client: TestClient,
) -> None:
    gateway = OfflineMaskedGateway(review_success=False)
    _install_runner(client, gateway)
    source, mask, _ = _valid_inputs(client)
    status_code, job = _create_job(client, source["id"], mask["id"])
    assert status_code == 202

    assert _dispatch(client) == 1
    body = client.get(
        f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    ).json()
    assert body["status"] == "failed"
    assert body["items"][0]["error_code"] == (
        "LOCAL_EDIT_VISUAL_REVIEW_REJECTED"
    )

    with client.app.state.session_factory() as session:
        relations = session.scalars(
            select(JobAssetRecord).where(JobAssetRecord.job_id == job["id"])
        ).all()
        raw_relation = next(
            item for item in relations if item.role == "provider_raw"
        )
        assert raw_relation.is_deliverable is False
        assert raw_relation.validation["raw_visual_success"] is False
        assert all(item.role != "local_edit_result" for item in relations)

    assert len(gateway.masked_calls) == 1
    assert len(gateway.review_calls) == 1


@pytest.mark.parametrize(
    ("mask_payload", "expected_code"),
    [
        (_selection_png((8, 8), selected=[]), "LOCAL_EDIT_MASK_EMPTY"),
        (
            _selection_png(
                (8, 8),
                selected=[(x, y) for x in range(8) for y in range(8)],
            ),
            "LOCAL_EDIT_MASK_FULL_FRAME",
        ),
    ],
)
def test_empty_and_full_masks_fail_before_provider(
    client: TestClient,
    mask_payload: bytes,
    expected_code: str,
) -> None:
    gateway = OfflineMaskedGateway()
    _install_runner(client, gateway)
    source = _upload(
        client,
        _png((8, 8), (10, 20, 30, 255)),
        media_kind="image",
        filename="source.png",
    )
    mask = _upload(
        client,
        mask_payload,
        media_kind="mask",
        filename="selection.png",
    )
    status_code, job = _create_job(client, source["id"], mask["id"])
    assert status_code == 202

    assert _dispatch(client) == 1
    response = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}")
    failed_item = response.json()["items"][0]
    assert failed_item["error_code"] == expected_code
    assert failed_item["error_details"]["needs_reselection"] is True
    assert gateway.masked_calls == []


def test_dimensions_kind_and_cross_workspace_are_rejected_at_api(
    client: TestClient,
) -> None:
    source = _upload(
        client,
        _png((8, 8), (10, 20, 30, 255)),
        media_kind="image",
        filename="source.png",
    )
    wrong_size = _upload(
        client,
        _selection_png((7, 8), selected=[(2, 2)]),
        media_kind="mask",
        filename="wrong-size.png",
    )
    status_code, body = _create_job(client, source["id"], wrong_size["id"])
    assert status_code == 422
    assert body["error"]["code"] == "LOCAL_EDIT_DIMENSIONS_MISMATCH"

    wrong_kind = _upload(
        client,
        _selection_png((8, 8), selected=[(2, 2)]),
        media_kind="image",
        filename="wrong-kind.png",
    )
    status_code, body = _create_job(client, source["id"], wrong_kind["id"])
    assert status_code == 422
    assert body["error"]["code"] == "LOCAL_EDIT_MASK_KIND_INVALID"

    with client.app.state.session_factory() as session:
        session.add(
            WorkspaceRecord(
                id="ws_other",
                name="Other",
                created_by_user_id="usr_test",
            )
        )
        session.flush()
        session.add(
            AssetRecord(
                id="asset_other_mask",
                workspace_id="ws_other",
                media_kind=AssetMediaKind.MASK.value,
                origin_kind=AssetOriginKind.UPLOAD.value,
                lifecycle_status=AssetLifecycleStatus.READY.value,
                original_filename="other.png",
                content_type="image/png",
                byte_size=1,
                width=8,
                height=8,
                sha256="0" * 64,
                storage_provider="local",
                storage_bucket="local",
                object_key="ws_other/other.png",
                object_version="",
            )
        )
        session.commit()
    status_code, body = _create_job(client, source["id"], "asset_other_mask")
    assert status_code == 404
    assert body["error"]["code"] == "INPUT_ASSET_NOT_FOUND"


@pytest.mark.parametrize(
    ("outcomes", "expected_calls", "expected_status"),
    [
        (("transient", "success"), 2, "completed"),
        (("transient", "transient"), 2, "failed"),
        (("bad_request",), 1, "failed"),
    ],
)
def test_retry_policy_is_one_transient_retry_and_no_4xx_retry(
    client: TestClient,
    outcomes: Sequence[str],
    expected_calls: int,
    expected_status: str,
) -> None:
    gateway = OfflineMaskedGateway(outcomes)
    _install_runner(client, gateway)
    source, mask, _ = _valid_inputs(client)
    status_code, job = _create_job(client, source["id"], mask["id"])
    assert status_code == 202

    assert _dispatch(client) == 1
    response = client.get(f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}")
    body = response.json()
    assert body["status"] == expected_status
    if expected_status == "failed":
        assert body["items"][0]["error_details"]["retryable"] is (
            outcomes[-1] == "transient"
        )
    assert len(gateway.masked_calls) == expected_calls
    assert len({call.idempotency_key for call in gateway.masked_calls}) == 1
    assert len(gateway.review_calls) == (1 if expected_status == "completed" else 0)


class RecordingProvider:
    name = "recording"
    model = "none"
    pricing_version = "test"

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, request: ProviderRequest) -> ProviderResult:
        self.calls += 1
        return ProviderResult(outcome=ProviderOutcome.SUCCEEDED)


def test_operation_router_keeps_mock_default_and_routes_real_local_provider() -> None:
    default = RecordingProvider()
    detail = RecordingProvider()
    local = RecordingProvider()
    request = ProviderRequest(
        workspace_id="ws",
        job_id="job",
        job_item_id="item",
        attempt_id="attempt",
        operation="local_edit",
        idempotency_key="idem",
        configuration={},
    )

    asyncio.run(OperationRoutingProvider(default, detail).execute(request))
    assert default.calls == 1
    assert local.calls == 0

    asyncio.run(OperationRoutingProvider(default, detail, local).execute(request))
    assert local.calls == 1
