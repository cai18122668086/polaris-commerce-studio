from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.amazon_visual_suite_provider import AmazonVisualSuiteProvider
from app.database import Base
from app.domain import (
    AssetLifecycleStatus,
    AssetMediaKind,
    AssetOriginKind,
    AttemptStatus,
    JobAssetDirection,
    JobItemStatus,
    JobStatus,
    WorkspaceStatus,
)
from app.models import (
    AssetRecord,
    JobAssetRecord,
    JobAttemptRecord,
    JobItemRecord,
    JobRecord,
    UserRecord,
    WorkspaceRecord,
)
from app.provider import ProviderArtifact, ProviderOutcome, ProviderRequest
from app.skill_protocol import SkillProtocolError
from app.xinghe_agent import (
    ImageCallResult,
    ImageEditRequest,
    _artifact_from_bytes,
    normalize_usage,
)
from app.xinghe_single_image_provider import (
    SINGLE_IMAGE_ADAPTER_CONFIGURATION_KEY,
    SINGLE_IMAGE_ADAPTER_SCHEMA_VERSION,
    XingheSingleImageProvider,
)

CONTENT_HASH = "a" * 64
SKILL_ID = "xinghe-wanneng-shengtu-3-0"
OPERATION = "product_image"
SECRET = "sk-test-never-leak-123456789"


def _image_bytes(
    size: tuple[int, int] = (64, 48),
    *,
    image_format: str = "PNG",
    color: tuple[int, ...] = (220, 30, 30, 255),
) -> bytes:
    mode = "RGBA" if len(color) == 4 else "RGB"
    image = Image.new(mode, size, color)
    output = BytesIO()
    save_options: dict[str, Any] = {}
    if image_format == "JPEG":
        image = image.convert("RGB")
        save_options["quality"] = 95
    image.save(output, format=image_format, **save_options)
    return output.getvalue()


def _artifact(
    size: tuple[int, int] = (160, 120),
    *,
    image_format: str = "PNG",
) -> ProviderArtifact:
    payload = _image_bytes(size, image_format=image_format)
    suffix = "jpg" if image_format == "JPEG" else image_format.lower()
    content_type = "image/jpeg" if image_format == "JPEG" else f"image/{suffix}"
    return ProviderArtifact(
        payload=payload,
        filename=f"provider-output.{suffix}",
        content_type=content_type,
        width=size[0],
        height=size[1],
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _success_result(
    *,
    artifact: ProviderArtifact | None = None,
    raw_usage: dict[str, Any] | None = None,
) -> ImageCallResult:
    usage = raw_usage if raw_usage is not None else {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
        "sensitive_provider_payload": SECRET,
    }
    return ImageCallResult(
        outcome=ProviderOutcome.SUCCEEDED,
        provider_request_id="req_real_123",
        raw_usage=usage,
        normalized_usage=normalize_usage(usage),
        api_latency_seconds=0.25,
        actual_cost_micros=321_000,
        estimated_cost_micros=300_000,
        artifact=artifact if artifact is not None else _artifact(),
        http_status=200,
    )


@dataclass
class RecordingManifestValidator:
    content_hash: str = CONTENT_HASH
    error: Exception | None = None
    calls: list[str] = field(default_factory=list)

    def __call__(self, skill_id: str) -> str:
        self.calls.append(skill_id)
        if self.error is not None:
            raise self.error
        return self.content_hash

    def validate(self, skill_id: str) -> str:
        return self(skill_id)


class RecordingStorage:
    provider_name = "local"
    bucket_name = "local"
    validator = None

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.reads: list[str] = []
        self.error: Exception | None = None

    async def read_bytes(self, object_key: str) -> bytes:
        self.reads.append(object_key)
        if self.error is not None:
            raise self.error
        return self.objects[object_key]


class RecordingGateway:
    provider_name = "recording-xinghe"
    planner_model = "unused-planner"
    image_model = "recording-image-model"
    pricing_version = "test-pricing-v1"
    external_network_request_count = 0

    def __init__(self, result: ImageCallResult | None = None) -> None:
        self.result = result or _success_result()
        self.requests: list[ImageEditRequest] = []
        self.plan_calls = 0
        self.error: Exception | None = None

    async def plan(self, request: object) -> object:
        del request
        self.plan_calls += 1
        raise AssertionError("single-image delegate must not call plan")

    async def edit(self, request: ImageEditRequest) -> ImageCallResult:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


@dataclass
class Harness:
    session_factory: sessionmaker[Session]
    storage: RecordingStorage
    gateway: RecordingGateway
    manifest: RecordingManifestValidator
    source_payload: bytes

    def provider(
        self,
        *,
        operation: str = OPERATION,
        skill_id: str = SKILL_ID,
    ) -> XingheSingleImageProvider:
        return XingheSingleImageProvider(
            self.session_factory,
            self.gateway,
            storage=self.storage,
            operation=operation,
            skill_id=skill_id,
            manifest_validator=self.manifest,
            max_concurrency=2,
        )


@pytest.fixture
def harness(tmp_path: Any) -> Harness:
    engine = create_engine(f"sqlite:///{tmp_path / 'single-image.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    source_payload = _image_bytes()
    with factory() as session:
        session.add(
            UserRecord(
                id="usr_test",
                auth_provider="development",
                auth_subject="usr_test",
            )
        )
        session.add(
            WorkspaceRecord(
                id="ws_test",
                name="Test",
                status=WorkspaceStatus.ACTIVE.value,
                created_by_user_id="usr_test",
            )
        )
        session.flush()
        session.add(
            JobRecord(
                id="job_test",
                workspace_id="ws_test",
                type=OPERATION,
                status=JobStatus.PROCESSING.value,
                expected_item_count=1,
            )
        )
        session.flush()
        session.add(
            JobItemRecord(
                id="item_test",
                workspace_id="ws_test",
                job_id="job_test",
                item_key="image-001",
                ordinal=1,
                status=JobItemStatus.RUNNING.value,
            )
        )
        session.flush()
        session.add(
            JobAttemptRecord(
                id="attempt_test",
                workspace_id="ws_test",
                job_id="job_test",
                job_item_id="item_test",
                attempt_no=1,
                status=AttemptStatus.RUNNING.value,
                lease_token="lease-test",
                leased_by="test-worker",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
                provider="recording-xinghe",
                operation=OPERATION,
                provider_idempotency_key="idem-test",
            )
        )
        session.add(
            _asset_record(
                asset_id="asset_product",
                workspace_id="ws_test",
                object_key="ws_test/product.png",
                payload=source_payload,
            )
        )
        session.add(
            JobAssetRecord(
                workspace_id="ws_test",
                job_id="job_test",
                asset_id="asset_product",
                direction=JobAssetDirection.INPUT.value,
                role="product",
                ordinal=0,
                is_deliverable=False,
                validation={},
            )
        )
        session.commit()
    storage = RecordingStorage({"ws_test/product.png": source_payload})
    instance = Harness(
        session_factory=factory,
        storage=storage,
        gateway=RecordingGateway(),
        manifest=RecordingManifestValidator(),
        source_payload=source_payload,
    )
    yield instance
    engine.dispose()


def _asset_record(
    *,
    asset_id: str,
    workspace_id: str,
    object_key: str,
    payload: bytes,
    media_kind: str = AssetMediaKind.IMAGE.value,
    lifecycle_status: str = AssetLifecycleStatus.READY.value,
) -> AssetRecord:
    with Image.open(BytesIO(payload)) as image:
        width, height = image.size
        image_format = image.format
    content_type = {
        "JPEG": "image/jpeg",
        "PNG": "image/png",
        "WEBP": "image/webp",
    }[str(image_format)]
    return AssetRecord(
        id=asset_id,
        workspace_id=workspace_id,
        media_kind=media_kind,
        origin_kind=AssetOriginKind.UPLOAD.value,
        lifecycle_status=lifecycle_status,
        original_filename=f"{asset_id}.png",
        content_type=content_type,
        byte_size=len(payload),
        width=width,
        height=height,
        sha256=hashlib.sha256(payload).hexdigest(),
        storage_provider="local",
        storage_bucket="local",
        object_key=object_key,
        object_version="",
    )


def _envelope(
    *,
    asset_ids: list[tuple[str, str]] | None = None,
    width: int = 160,
    height: int = 120,
    output_format: str = "png",
    fit: str = "cover",
    prompt_input: dict[str, Any] | None = None,
    item_key: str = "image-001",
    item_ordinal: int = 1,
) -> dict[str, Any]:
    divisor = __import__("math").gcd(width, height)
    return {
        "schema_version": SINGLE_IMAGE_ADAPTER_SCHEMA_VERSION,
        "skill_id": SKILL_ID,
        "skill_content_hash": CONTENT_HASH,
        "operation": OPERATION,
        "item_key": item_key,
        "item_ordinal": item_ordinal,
        "source_assets": [
            {"asset_id": asset_id, "role": role}
            for asset_id, role in (asset_ids or [("asset_product", "product")])
        ],
        "target": {
            "width": width,
            "height": height,
            "aspect_ratio": f"{width // divisor}:{height // divisor}",
            "quality": "high",
            "output_format": output_format,
            "fit": fit,
        },
        "prompt_input": prompt_input
        or {
            "task_type": "white_background",
            "product_name": "safe product",
            "negative_constraints": ["no watermark", "no extra logo"],
        },
    }


def _request(
    envelope: dict[str, Any] | None = None,
    **changes: Any,
) -> ProviderRequest:
    values: dict[str, Any] = {
        "workspace_id": "ws_test",
        "job_id": "job_test",
        "job_item_id": "item_test",
        "attempt_id": "attempt_test",
        "operation": OPERATION,
        "idempotency_key": "idem-test",
        "configuration": {
            "api_key": SECRET,
            "untrusted_prompt": "must never be used",
            SINGLE_IMAGE_ADAPTER_CONFIGURATION_KEY: envelope or _envelope(),
        },
    }
    values.update(changes)
    return ProviderRequest(**values)


def _reference_follow_request(
    harness: Harness,
    *,
    reference_payload: bytes,
) -> tuple[XingheSingleImageProvider, ProviderRequest]:
    operation = "reference_remix"
    skill_id = "xinghe-reference-image-remix-3"
    with harness.session_factory() as session:
        job = session.get(JobRecord, "job_test")
        attempt = session.get(JobAttemptRecord, "attempt_test")
        product_binding = session.query(JobAssetRecord).one()
        assert job is not None and attempt is not None
        job.type = operation
        attempt.operation = operation
        product_binding.role = "product_reference"
        session.add(
            _asset_record(
                asset_id="asset_style",
                workspace_id="ws_test",
                object_key="ws_test/style-reference",
                payload=reference_payload,
            )
        )
        session.add(
            JobAssetRecord(
                workspace_id="ws_test",
                job_id="job_test",
                asset_id="asset_style",
                direction=JobAssetDirection.INPUT.value,
                role="style_reference",
                ordinal=0,
                is_deliverable=False,
                validation={},
            )
        )
        session.commit()
    harness.storage.objects["ws_test/style-reference"] = reference_payload
    envelope = _envelope(
        asset_ids=[
            ("asset_product", "product_reference"),
            ("asset_style", "style_reference"),
        ],
        fit="contain",
    )
    envelope.update({"skill_id": skill_id, "operation": operation})
    envelope["target"] = {
        "width": None,
        "height": None,
        "aspect_ratio": "follow-reference",
        "quality": "high",
        "output_format": "png",
        "fit": "contain",
    }
    provider = harness.provider(operation=operation, skill_id=skill_id)
    return provider, _request(envelope, operation=operation)


def test_success_calls_edit_once_and_returns_real_accounting(harness: Harness) -> None:
    provider = harness.provider()

    result = asyncio.run(provider.execute(_request()))

    assert result.outcome == ProviderOutcome.SUCCEEDED
    assert result.provider_request_id == "req_real_123"
    assert result.estimated_cost_micros == 300_000
    assert result.actual_cost_micros == 321_000
    assert result.usage_reported is True
    assert result.raw_usage["input_tokens"] == 11
    assert result.raw_usage["output_tokens"] == 7
    assert result.raw_usage["request_count"] == 1
    assert result.raw_usage["artifact_kind"] == "image"
    assert len(result.raw_usage["skill_protocol_sha256"]) == 64
    assert result.raw_usage["skill_protocol_length"] > 0
    assert "documents" not in result.raw_usage
    assert "skill_protocol" not in result.raw_usage
    assert SECRET not in json.dumps(result.raw_usage)
    assert result.artifact is harness.gateway.result.artifact
    assert len(harness.gateway.requests) == 1
    assert harness.gateway.plan_calls == 0
    assert harness.gateway.external_network_request_count == 0
    image_request = harness.gateway.requests[0]
    assert image_request.size == "1536x1024"
    assert image_request.output_format == "jpeg"
    assert image_request.preserve_provider_artifact is True
    assert len(image_request.sources) == 1
    assert image_request.sources[0].payload == harness.source_payload
    assert SECRET not in image_request.prompt
    assert "must never be used" not in image_request.prompt
    assert harness.manifest.calls == [SKILL_ID]


@pytest.mark.parametrize(
    ("reference_size", "reference_format"),
    [
        ((333, 777), "PNG"),
        ((1279, 853), "JPEG"),
        ((641, 641), "WEBP"),
    ],
)
def test_reference_follow_target_uses_real_first_style_canvas_for_final_delivery(
    harness: Harness,
    reference_size: tuple[int, int],
    reference_format: str,
) -> None:
    reference_payload = _image_bytes(
        reference_size,
        image_format=reference_format,
    )
    harness.gateway.result = _success_result(
        artifact=_artifact((257, 113), image_format="WEBP")
    )
    provider, request = _reference_follow_request(
        harness,
        reference_payload=reference_payload,
    )

    result = asyncio.run(provider.execute(request))

    assert result.outcome == ProviderOutcome.SUCCEEDED
    assert result.artifact is not None
    assert (result.artifact.width, result.artifact.height) == reference_size
    assert result.artifact.locally_resampled is True
    with Image.open(BytesIO(result.artifact.payload)) as delivered:
        assert delivered.size == reference_size
    assert harness.manifest.calls == ["xinghe-reference-image-remix-3"]
    assert harness.storage.reads == [
        "ws_test/product.png",
        "ws_test/style-reference",
    ]
    prompt = json.loads(harness.gateway.requests[0].prompt)
    assert prompt["target"]["width"] == reference_size[0]
    assert prompt["target"]["height"] == reference_size[1]
    assert prompt["target"]["fit"] == "contain"


def test_reference_follow_target_fails_closed_when_real_canvas_is_unsafe(
    harness: Harness,
) -> None:
    provider, request = _reference_follow_request(
        harness,
        reference_payload=_image_bytes((8193, 2), image_format="PNG"),
    )

    result = asyncio.run(provider.execute(request))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "TARGET_CONFIGURATION_INVALID"
    assert harness.gateway.requests == []
    assert harness.manifest.calls == ["xinghe-reference-image-remix-3"]
    assert harness.storage.reads == [
        "ws_test/product.png",
        "ws_test/style-reference",
    ]


def test_missing_protocol_fails_closed_after_manifest_and_before_asset_read(
    harness: Harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_protocol(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        raise SkillProtocolError(
            "SKILL_PROTOCOL_SOURCE_MISSING",
            "Skill protocol source is unavailable.",
        )

    monkeypatch.setattr(
        "app.xinghe_single_image_provider.load_skill_protocol",
        missing_protocol,
    )

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.error_code == "SKILL_PROTOCOL_SOURCE_MISSING"
    assert harness.manifest.calls == [SKILL_ID]
    assert harness.storage.reads == []
    assert harness.gateway.requests == []


def test_two_job_items_each_make_one_call(harness: Harness) -> None:
    with harness.session_factory() as session:
        session.add(
            JobItemRecord(
                id="item_second",
                workspace_id="ws_test",
                job_id="job_test",
                item_key="image-002",
                ordinal=2,
                status=JobItemStatus.RUNNING.value,
            )
        )
        session.flush()
        session.add(
            JobAttemptRecord(
                id="attempt_second",
                workspace_id="ws_test",
                job_id="job_test",
                job_item_id="item_second",
                attempt_no=1,
                status=AttemptStatus.RUNNING.value,
                lease_token="lease-second",
                leased_by="test-worker",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
                provider="recording-xinghe",
                operation=OPERATION,
                provider_idempotency_key="idem-second",
            )
        )
        session.commit()
    provider = harness.provider()
    first = asyncio.run(provider.execute(_request()))
    second_request = _request(
        _envelope(item_key="image-002", item_ordinal=2),
        job_item_id="item_second",
        attempt_id="attempt_second",
        idempotency_key="idem-second",
    )
    second = asyncio.run(provider.execute(second_request))

    assert first.outcome == ProviderOutcome.SUCCEEDED
    assert second.outcome == ProviderOutcome.SUCCEEDED
    assert [request.job_item_id for request in harness.gateway.requests] == [
        "item_test",
        "item_second",
    ]


def test_retryable_gateway_failure_is_not_retried_and_is_redacted(
    harness: Harness,
) -> None:
    raw_usage = {
        "input_tokens": 3,
        "provider_response": f"private raw response {SECRET}",
    }
    harness.gateway.result = ImageCallResult(
        outcome=ProviderOutcome.FAILED,
        provider_request_id="req_failed",
        raw_usage=raw_usage,
        normalized_usage=normalize_usage(raw_usage),
        api_latency_seconds=0.1,
        actual_cost_micros=90,
        estimated_cost_micros=100,
        error_code="RATE_LIMITED",
        error_message=f"sensitive failure {SECRET}",
        retryable=True,
        http_status=429,
    )

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.outcome == ProviderOutcome.FAILED
    assert result.error_code == "RATE_LIMITED"
    assert result.retryable is True
    assert result.http_status == 429
    assert len(harness.gateway.requests) == 1
    serialized = str(result)
    assert SECRET not in serialized
    assert "private raw response" not in serialized
    assert "sensitive failure" not in serialized


def test_gateway_exception_is_single_call_and_does_not_leak(
    harness: Harness,
    caplog: pytest.LogCaptureFixture,
) -> None:
    harness.gateway.error = RuntimeError(
        f"provider secret={SECRET}; raw={harness.source_payload!r}"
    )

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.error_code == "IMAGE_PROVIDER_FAILED"
    assert len(harness.gateway.requests) == 1
    assert result.raw_usage["request_count"] == 1
    prompt = harness.gateway.requests[0].prompt
    observable = f"{result!s}\n{caplog.text}"
    assert SECRET not in observable
    assert repr(harness.source_payload) not in observable
    assert prompt not in observable
    assert "RuntimeError" in (result.error_message or "")


@pytest.mark.parametrize(
    ("request_changes", "expected_code"),
    [
        ({"workspace_id": "ws_missing"}, "DURABLE_REQUEST_NOT_FOUND"),
        ({"job_id": "job_missing"}, "DURABLE_REQUEST_NOT_FOUND"),
        ({"job_item_id": "item_missing"}, "DURABLE_REQUEST_NOT_FOUND"),
        ({"attempt_id": "attempt_missing"}, "DURABLE_REQUEST_NOT_FOUND"),
        ({"idempotency_key": "wrong-idem"}, "DURABLE_REQUEST_MISMATCH"),
    ],
)
def test_durable_scope_failures_make_no_gateway_call(
    harness: Harness,
    request_changes: dict[str, str],
    expected_code: str,
) -> None:
    result = asyncio.run(harness.provider().execute(_request(**request_changes)))

    assert result.error_code == expected_code
    assert harness.gateway.requests == []
    assert result.raw_usage["request_count"] == 0


def test_cross_workspace_job_is_rejected_before_gateway(harness: Harness) -> None:
    with harness.session_factory() as session:
        session.add(
            WorkspaceRecord(
                id="ws_other",
                name="Other",
                status=WorkspaceStatus.ACTIVE.value,
                created_by_user_id="usr_test",
            )
        )
        session.commit()

    result = asyncio.run(
        harness.provider().execute(_request(workspace_id="ws_other"))
    )

    assert result.error_code == "WORKSPACE_SCOPE_MISMATCH"
    assert harness.gateway.requests == []


@pytest.mark.parametrize(
    ("asset_id", "expected_code"),
    [
        ("asset_missing", "INPUT_ASSET_AUTHORIZATION_MISMATCH"),
        ("asset_other", "INPUT_ASSET_AUTHORIZATION_MISMATCH"),
    ],
)
def test_missing_or_cross_workspace_asset_is_rejected(
    harness: Harness,
    asset_id: str,
    expected_code: str,
) -> None:
    if asset_id == "asset_other":
        other_payload = _image_bytes(color=(10, 20, 30, 255))
        with harness.session_factory() as session:
            session.add(
                WorkspaceRecord(
                    id="ws_other",
                    name="Other",
                    status=WorkspaceStatus.ACTIVE.value,
                    created_by_user_id="usr_test",
                )
            )
            session.flush()
            session.add(
                _asset_record(
                    asset_id=asset_id,
                    workspace_id="ws_other",
                    object_key="ws_other/product.png",
                    payload=other_payload,
                )
            )
            session.commit()
        harness.storage.objects["ws_other/product.png"] = other_payload
    result = asyncio.run(
        harness.provider().execute(
            _request(_envelope(asset_ids=[(asset_id, "product")]))
        )
    )

    assert result.error_code == expected_code
    assert harness.gateway.requests == []


@pytest.mark.parametrize(
    ("role", "ordinal"),
    [("style_reference", 0), ("product", 1)],
)
def test_durable_input_role_or_ordinal_mismatch_is_rejected(
    harness: Harness,
    role: str,
    ordinal: int,
) -> None:
    with harness.session_factory() as session:
        binding = session.query(JobAssetRecord).one()
        binding.role = role
        binding.ordinal = ordinal
        session.commit()

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.error_code == "INPUT_ASSET_AUTHORIZATION_MISMATCH"
    assert harness.storage.reads == []
    assert harness.gateway.requests == []


def test_extra_durable_input_is_rejected(harness: Harness) -> None:
    extra_payload = _image_bytes(color=(10, 20, 30, 255))
    with harness.session_factory() as session:
        session.add(
            _asset_record(
                asset_id="asset_extra",
                workspace_id="ws_test",
                object_key="ws_test/extra.png",
                payload=extra_payload,
            )
        )
        session.add(
            JobAssetRecord(
                workspace_id="ws_test",
                job_id="job_test",
                asset_id="asset_extra",
                direction=JobAssetDirection.INPUT.value,
                role="product",
                ordinal=1,
                is_deliverable=False,
                validation={},
            )
        )
        session.commit()
    harness.storage.objects["ws_test/extra.png"] = extra_payload

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.error_code == "INPUT_ASSET_AUTHORIZATION_MISMATCH"
    assert harness.storage.reads == []
    assert harness.gateway.requests == []


@pytest.mark.parametrize(
    ("field", "value", "expected_code"),
    [
        ("media_kind", AssetMediaKind.JSON.value, "INPUT_ASSET_NOT_IMAGE"),
        (
            "lifecycle_status",
            AssetLifecycleStatus.QUARANTINED.value,
            "INPUT_ASSET_NOT_READABLE",
        ),
    ],
)
def test_non_image_or_unreadable_asset_is_rejected(
    harness: Harness,
    field: str,
    value: str,
    expected_code: str,
) -> None:
    with harness.session_factory() as session:
        asset = session.get(AssetRecord, "asset_product")
        assert asset is not None
        setattr(asset, field, value)
        session.commit()

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.error_code == expected_code
    assert harness.gateway.requests == []


def test_asset_bytes_and_metadata_are_verified_before_gateway(harness: Harness) -> None:
    harness.storage.objects["ws_test/product.png"] = b"not-the-original-image"

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.error_code == "INPUT_ASSET_INTEGRITY_FAILED"
    assert harness.gateway.requests == []


def test_storage_error_is_redacted(harness: Harness) -> None:
    harness.storage.error = OSError(f"storage key {SECRET}")

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.error_code == "INPUT_ASSET_READ_FAILED"
    assert SECRET not in str(result)
    assert harness.gateway.requests == []


@pytest.mark.parametrize(
    ("mutator", "expected_code"),
    [
        (
            lambda value: value.update({"unexpected": True}),
            "SINGLE_IMAGE_ENVELOPE_INVALID",
        ),
        (
            lambda value: value.update({"schema_version": "future-v9"}),
            "SINGLE_IMAGE_SCHEMA_UNSUPPORTED",
        ),
        (
            lambda value: value.update({"skill_id": "other-skill"}),
            "SKILL_ID_MISMATCH",
        ),
        (
            lambda value: value.update({"operation": "creative_image"}),
            "OPERATION_MISMATCH",
        ),
        (
            lambda value: value.update({"skill_content_hash": "not-a-hash"}),
            "SKILL_CONTENT_HASH_INVALID",
        ),
        (
            lambda value: value.update(
                {
                    "source_assets": [
                        {"asset_id": "asset_product", "role": "product"},
                        {"asset_id": "asset_product", "role": "reference"},
                    ]
                }
            ),
            "SOURCE_ASSET_DUPLICATE",
        ),
    ],
)
def test_invalid_envelope_fails_closed(
    harness: Harness,
    mutator: Any,
    expected_code: str,
) -> None:
    envelope = _envelope()
    mutator(envelope)

    result = asyncio.run(harness.provider().execute(_request(envelope)))

    assert result.error_code == expected_code
    assert harness.gateway.requests == []


def test_missing_envelope_fails_closed(harness: Harness) -> None:
    request = _request(configuration={"job": {}, "item": {}})

    result = asyncio.run(harness.provider().execute(request))

    assert result.error_code == "SINGLE_IMAGE_ENVELOPE_INVALID"
    assert harness.gateway.requests == []


def test_manifest_hash_mismatch_fails_before_asset_read_or_gateway(
    harness: Harness,
) -> None:
    harness.manifest.content_hash = "b" * 64

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.error_code == "SKILL_CONTENT_HASH_MISMATCH"
    assert harness.storage.reads == []
    assert harness.gateway.requests == []


def test_manifest_exception_is_redacted(harness: Harness) -> None:
    harness.manifest.error = RuntimeError(f"manifest secret {SECRET}")

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.error_code == "SKILL_MANIFEST_VALIDATION_FAILED"
    assert SECRET not in str(result)
    assert harness.storage.reads == []
    assert harness.gateway.requests == []


def test_prompt_is_deterministic_and_uses_only_whitelisted_envelope(
    harness: Harness,
) -> None:
    first_prompt = {
        "style": "clean",
        "product_information": ["steel", "compact"],
        "task_type": "scene_main",
    }
    second_prompt = {
        "task_type": "scene_main",
        "product_information": ["steel", "compact"],
        "style": "clean",
    }
    provider = harness.provider()
    first_request = _request(_envelope(prompt_input=first_prompt))
    second_request = _request(_envelope(prompt_input=second_prompt))

    protocol = provider._load_protocol(CONTENT_HASH)
    first = provider._compile_prompt(
        provider._parse_envelope(first_request), protocol
    )
    second = provider._compile_prompt(
        provider._parse_envelope(second_request), protocol
    )

    assert first == second
    decoded = json.loads(first)
    assert decoded["instructions"] == first_prompt
    assert set(decoded) == {
        "schema_version",
        "skill_id",
        "operation",
        "item",
        "source_roles",
        "target",
        "instructions",
        "skill_protocol",
    }
    assert decoded["skill_protocol"]["skill_id"] == SKILL_ID
    assert decoded["skill_protocol"]["source_content_hash"] == CONTENT_HASH
    assert decoded["skill_protocol"]["documents"][0]["path"] == "SKILL.md"
    assert SECRET not in first
    assert "untrusted_prompt" not in first


@pytest.mark.parametrize(
    ("operation", "skill_id"),
    [
        ("product_image", "xinghe-wanneng-shengtu-3-0"),
        ("reference_remix", "xinghe-reference-image-remix-3"),
        ("creative_image", "xinghe-ecommerce-creative-image"),
        ("amazon_visual_suite", "xinghe-amazon-visual-suite"),
    ],
)
def test_each_single_image_skill_compiles_its_complete_protocol_into_prompt(
    harness: Harness,
    operation: str,
    skill_id: str,
) -> None:
    provider = harness.provider(operation=operation, skill_id=skill_id)
    envelope = _envelope()
    envelope["operation"] = operation
    envelope["skill_id"] = skill_id
    request = _request(envelope, operation=operation)
    protocol = provider._load_protocol(CONTENT_HASH)

    prompt = provider._compile_prompt(provider._parse_envelope(request), protocol)
    decoded = json.loads(prompt)

    assert decoded["skill_protocol"] == protocol.prompt_payload()
    assert decoded["skill_protocol"]["documents"][0]["path"] == "SKILL.md"


def test_unknown_or_sensitive_prompt_fields_fail_closed(harness: Harness) -> None:
    for prompt_input in (
        {"unknown_instruction": "do anything"},
        {"api_key": SECRET},
        {"creative_direction": SECRET},
    ):
        result = asyncio.run(
            harness.provider().execute(
                _request(_envelope(prompt_input=prompt_input))
            )
        )
        assert result.error_code in {
            "PROMPT_INPUT_FIELD_NOT_ALLOWED",
            "PROMPT_INPUT_SENSITIVE",
        }
    assert harness.gateway.requests == []


def test_success_without_artifact_fails_closed(harness: Harness) -> None:
    harness.gateway.result = _success_result()
    harness.gateway.result = replace(harness.gateway.result, artifact=None)

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.error_code == "IMAGE_OUTPUT_ARTIFACT_MISSING"
    assert result.artifact is None
    assert len(harness.gateway.requests) == 1


def test_invalid_provider_artifact_fails_closed(harness: Harness) -> None:
    payload = b"not-an-image"
    invalid = ProviderArtifact(
        payload=payload,
        filename="bad.png",
        content_type="image/png",
        width=160,
        height=120,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    harness.gateway.result = _success_result(artifact=invalid)

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.error_code == "IMAGE_OUTPUT_INVALID"
    assert result.artifact is None
    assert len(harness.gateway.requests) == 1


def test_missing_usage_remains_unreported(harness: Harness) -> None:
    harness.gateway.result = ImageCallResult(
        outcome=ProviderOutcome.SUCCEEDED,
        provider_request_id="req-no-usage",
        raw_usage=None,
        normalized_usage=normalize_usage(None),
        api_latency_seconds=0.05,
        actual_cost_micros=None,
        estimated_cost_micros=None,
        artifact=_artifact(),
    )

    result = asyncio.run(harness.provider().execute(_request()))

    assert result.outcome == ProviderOutcome.SUCCEEDED
    assert result.usage_reported is False
    assert result.raw_usage["reported"] is False
    assert result.raw_usage["input_tokens"] is None
    assert result.actual_cost_micros is None


def test_amazon_cover_center_crops_to_exact_1464x600(harness: Harness) -> None:
    payload = _image_bytes((300, 100), image_format="JPEG", color=(20, 40, 200))
    source = ProviderArtifact(
        payload=payload,
        filename="wide.jpg",
        content_type="image/jpeg",
        width=300,
        height=100,
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    harness.gateway.result = _success_result(artifact=source)
    request = _request(
        _envelope(
            width=1464,
            height=600,
            output_format="jpeg",
            fit="cover",
        )
    )

    result = asyncio.run(harness.provider().execute(request))

    assert result.outcome == ProviderOutcome.SUCCEEDED
    artifact = result.artifact
    assert artifact is not None
    assert (artifact.width, artifact.height) == (1464, 600)
    assert artifact.content_type == "image/jpeg"
    assert artifact.locally_resampled is True
    assert (artifact.provider_width, artifact.provider_height) == (300, 100)
    with Image.open(BytesIO(artifact.payload)) as image:
        assert image.size == (1464, 600)


@pytest.mark.parametrize("fit", ["contain", "pad"])
def test_amazon_contain_and_pad_are_exact_with_white_jpeg_canvas(
    harness: Harness,
    fit: str,
) -> None:
    harness.gateway.result = _success_result(
        artifact=_artifact((300, 100), image_format="PNG")
    )
    request = _request(
        _envelope(
            width=1200,
            height=1600,
            output_format="jpeg",
            fit=fit,
        )
    )

    result = asyncio.run(harness.provider().execute(request))

    assert result.outcome == ProviderOutcome.SUCCEEDED
    artifact = result.artifact
    assert artifact is not None
    assert (artifact.width, artifact.height) == (1200, 1600)
    assert artifact.filename.endswith(".jpg")
    with Image.open(BytesIO(artifact.payload)) as image:
        assert image.size == (1200, 1600)
        corner = image.convert("RGB").getpixel((0, 0))
        assert all(channel >= 245 for channel in corner)


def test_exact_amazon_size_and_format_are_not_reencoded(harness: Harness) -> None:
    exact = _artifact((1600, 1200), image_format="PNG")
    harness.gateway.result = _success_result(artifact=exact)
    request = _request(
        _envelope(
            width=1600,
            height=1200,
            output_format="png",
            fit="pad",
        )
    )

    result = asyncio.run(harness.provider().execute(request))

    assert result.outcome == ProviderOutcome.SUCCEEDED
    assert result.artifact is exact
    assert result.artifact.locally_resampled is False
    assert result.artifact.payload == exact.payload
    assert harness.gateway.external_network_request_count == 0


@pytest.mark.parametrize("image_format", ["PNG", "WEBP"])
def test_gateway_artifact_parser_preserves_safe_provider_format_and_canvas(
    image_format: str,
) -> None:
    payload = _image_bytes((90, 300), image_format=image_format)

    artifact = _artifact_from_bytes(
        payload,
        filename="provider-output.jpg",
        expected_size="1536x1024",
        preserve_provider_artifact=True,
    )

    expected_suffix = image_format.lower()
    assert artifact.filename.endswith(f".{expected_suffix}")
    assert artifact.content_type == f"image/{expected_suffix}"
    assert (artifact.width, artifact.height) == (90, 300)
    assert artifact.payload == payload
    assert artifact.locally_resampled is False


@pytest.mark.parametrize(
    ("provider_format", "delivery_format"),
    [("PNG", "webp"), ("WEBP", "png")],
)
def test_provider_format_and_canvas_are_independent_from_delivery_contract(
    harness: Harness,
    provider_format: str,
    delivery_format: str,
) -> None:
    harness.gateway.result = _success_result(
        artifact=_artifact((90, 300), image_format=provider_format)
    )
    request = _request(
        _envelope(
            width=160,
            height=120,
            output_format=delivery_format,
            fit="cover",
        )
    )

    result = asyncio.run(harness.provider().execute(request))

    assert result.outcome == ProviderOutcome.SUCCEEDED
    assert result.artifact is not None
    assert (result.artifact.width, result.artifact.height) == (160, 120)
    assert result.artifact.content_type == f"image/{delivery_format}"
    assert result.artifact.locally_resampled is True
    assert (
        result.artifact.provider_width,
        result.artifact.provider_height,
    ) == (90, 300)
    assert len(harness.gateway.requests) == 1
    assert harness.gateway.requests[0].size == "1536x1024"
    assert harness.gateway.requests[0].output_format == "jpeg"


def test_amazon_adapter_to_delegate_preserves_durable_key_and_calls_gateway_once(
    harness: Harness,
) -> None:
    operation = "amazon_visual_suite"
    skill_id = "xinghe-amazon-visual-suite"
    with harness.session_factory() as session:
        job = session.get(JobRecord, "job_test")
        item = session.get(JobItemRecord, "item_test")
        attempt = session.get(JobAttemptRecord, "attempt_test")
        binding = session.query(JobAssetRecord).one()
        assert job is not None and item is not None and attempt is not None
        job.type = operation
        job.expected_item_count = 21
        item.item_key = "A-DESKTOP-01"
        item.ordinal = 7
        attempt.operation = operation
        binding.role = "white_background_product"
        session.commit()

    harness.gateway.result = _success_result(
        artifact=_artifact((300, 100), image_format="WEBP")
    )
    delegate = harness.provider(operation=operation, skill_id=skill_id)
    provider = AmazonVisualSuiteProvider(
        delegate,
        manifest_validator=harness.manifest,
    )
    request = ProviderRequest(
        workspace_id="ws_test",
        job_id="job_test",
        job_item_id="item_test",
        attempt_id="attempt_test",
        operation=operation,
        idempotency_key="idem-test",
        configuration={
            "job": {
                "input": {
                    "white_background_product_asset_ids": ["asset_product"],
                    "detail_asset_ids": [],
                    "package_asset_ids": [],
                    "scene_asset_ids": [],
                    "brand_asset_ids": [],
                },
                "settings": {
                    "marketplace": "amazon-us",
                    "product_name": "Test product",
                    "product_information": ["Test listing"],
                    "language": "en-US",
                },
            },
            "item": {
                "item_key": "A-DESKTOP-01",
                "target_width": 1464,
                "target_height": 600,
                "group": "a_desktop",
                "group_ordinal": 1,
                "contact_sheet": False,
            },
        },
    )

    result = asyncio.run(provider.execute(request))

    assert result.outcome == ProviderOutcome.SUCCEEDED
    assert result.artifact is not None
    assert (result.artifact.width, result.artifact.height) == (1464, 600)
    assert result.artifact.content_type == "image/jpeg"
    assert len(harness.gateway.requests) == 1
    gateway_request = harness.gateway.requests[0]
    assert gateway_request.group_key == "A-DESKTOP-01"
    assert gateway_request.size == "1536x640"
    assert gateway_request.output_format == "jpeg"
    assert gateway_request.preserve_provider_artifact is True
