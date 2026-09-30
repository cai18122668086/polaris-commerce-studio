import asyncio
import json
import socket
import ssl
from dataclasses import replace
from io import BytesIO
from urllib.error import URLError
from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from app.creative_image_provider import CREATIVE_DIRECTIONS, CreativeImageProvider
from app.creative_planning_contract import CREATIVE_FIELDS
from app.execution import ExecutionCoordinator
from app.models import JobAttemptRecord, JobItemRecord, JobRecord
from app.schemas_v1 import DetailPackConfiguration
from app.task_runner import MockTaskRunner
from app.transport_diagnostics import transport_failure
from app.xinghe_agent import PlannerRequest, _planner_prompt, _planner_response_format
from tests.test_api import WORKSPACE_ID, dispatch_pending, idem, upload_asset
from tests.test_domestic_detail_execution import (
    _create_detail_job as create_domestic_job,
)
from tests.test_new_image_skill_providers import (
    ManifestSpy,
    StubDelegate,
    _artifact_result,
    _request,
)
from tests.test_xinghe_agent import _OfflineNonMockGateway


@pytest.mark.parametrize("count", [None, "", "abc", "3", 0, -1, 1.5, 3.0, 13, True])
def test_detail_count_does_not_coerce_invalid_input(count):
    with pytest.raises(ValidationError):
        DetailPackConfiguration(
            product_name="Test", platform_code="tmall", page_count=count
        )


@pytest.mark.parametrize("count", [1, 3, 5, 7, 12])
@pytest.mark.parametrize("region", ["domestic", "international"])
def test_detail_count_plan_edit_execution_and_zip(client, count, region):
    gateway = _OfflineNonMockGateway()
    client.app.state.task_runner = MockTaskRunner(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=gateway,
        xinghe_concurrency=2,
    )
    source = upload_asset(client, filename="count.jpg")
    job = create_domestic_job(
        client,
        source["id"],
        market_region=region,
        auto_start_after_plan=False,
        page_count=count,
    )
    assert job["configuration"]["settings"]["page_count"] == count
    assert job["expected_item_count"] == count
    assert dispatch_pending(client) == 1
    url = f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    planned = client.get(url).json()
    assert len(planned["plan"]["payload"]["pages"]) == count
    payload = planned["plan"]["payload"]
    payload["pages"][0]["title"] = "Edited title"
    edited = client.put(
        url + "/plan", json={"expected_revision": 1, "payload": payload}
    )
    assert edited.status_code == 200, edited.text
    assert (
        client.post(
            url + "/plan/confirm", headers=idem(), json={"expected_revision": 2}
        ).status_code
        == 202
    )
    assert dispatch_pending(client) == 1
    done = client.get(url).json()
    assert done["status"] == "completed", done
    assert done["succeeded_item_count"] == done["expected_item_count"] == count
    assert done["failed_item_count"] == 0
    assert len(done["items"]) == len(gateway.image_calls) == count
    assert [i["ordinal"] for i in done["items"]] == list(range(count))
    archive = client.get(url + "/deliverables.zip")
    assert archive.status_code == 200, archive.text
    with ZipFile(BytesIO(archive.content)) as bundle:
        assert len(bundle.namelist()) == count
        assert bundle.testzip() is None


@pytest.mark.parametrize("count", [3, 5, 7])
def test_domestic_auto_start_preserves_count_and_zip(client, count):
    gateway = _OfflineNonMockGateway()
    client.app.state.task_runner = MockTaskRunner(
        client.app.state.session_factory,
        0,
        storage=client.app.state.storage,
        xinghe_gateway=gateway,
        xinghe_concurrency=2,
    )
    source = upload_asset(client, filename="domestic-auto.jpg")
    job = create_domestic_job(
        client,
        source["id"],
        market_region="domestic",
        auto_start_after_plan=True,
        page_count=count,
    )
    assert dispatch_pending(client) == 1
    url = f"/api/v1/workspaces/{WORKSPACE_ID}/jobs/{job['id']}"
    done = client.get(url).json()
    assert done["status"] == "completed", done
    assert len(done["plan"]["payload"]["pages"]) == len(gateway.image_calls) == count
    assert done["expected_item_count"] == done["succeeded_item_count"] == count
    assert gateway.planner_calls[0].page_count == count
    assert all(call.size == "1200x1600" for call in gateway.image_calls)
    archive = client.get(url + "/deliverables.zip")
    assert archive.status_code == 200, archive.text
    with ZipFile(BytesIO(archive.content)) as bundle:
        assert len(bundle.namelist()) == count
        assert bundle.testzip() is None


@pytest.mark.parametrize("direction", sorted(CREATIVE_DIRECTIONS))
@pytest.mark.parametrize("switch", [None, False, True])
def test_creative_default_false_and_inspiration_true(direction, switch):
    delegate = StubDelegate(_artifact_result())
    provider = CreativeImageProvider(delegate, manifest_validator=ManifestSpy())
    settings = {"image_count": 1, "creative_direction": direction}
    if switch is not None:
        settings["inspiration_planning"] = switch
    result = asyncio.run(
        provider.execute(
            _request(
                "creative_image",
                input_config={"product_asset_ids": ["asset_product"]},
                settings=settings,
            )
        )
    )
    assert result.error_code is None
    assert len(delegate.requests) == 1
    prompt = delegate.requests[0].configuration["new_skill_adapter"]["prompt_input"]
    assert (prompt.get("planning_mode") == "creative") is (switch is True)


@pytest.mark.parametrize(
    "operation",
    ["product_image", "reference_remix", "creative_image", "model_pose_transfer"],
)
@pytest.mark.parametrize("ordinal", [0, 1, 2])
def test_lease_uses_durable_identity_even_if_config_conflicts(operation, ordinal):
    job = JobRecord(
        id="job_test", workspace_id="ws_test", type=operation, configuration={}
    )
    item = JobItemRecord(
        id="item_test",
        job_id=job.id,
        item_key=f"image-{ordinal + 1:03}",
        ordinal=ordinal,
        configuration={"ordinal": 99, "item_key": "wrong"},
    )
    attempt = JobAttemptRecord(
        id="attempt_test",
        operation=operation,
        lease_token="token",
        provider_idempotency_key="idem",
    )
    lease = ExecutionCoordinator._lease_from_records(job, item, attempt)
    assert lease.configuration["item"] == {
        "ordinal": ordinal,
        "item_key": item.item_key,
    }


def test_creative_prompt_and_schema_share_contract():
    request = PlannerRequest(
        workspace_id="w",
        job_id="j",
        group_key="g",
        sources=(),
        page_count=1,
        language="zh-CN",
        product_name="Product",
        product_information=("User exact brief",),
        platform_code="tmall",
        size="1024x1024",
        idempotency_key="i",
        planning_profile="creative_image",
    )
    prompt = _planner_prompt(request)
    schema = _planner_response_format(request)["json_schema"]["schema"]
    assert schema["required"] == list(CREATIVE_FIELDS)
    assert all(field in prompt for field in CREATIVE_FIELDS)
    assert "User exact brief" in prompt
    assert _planner_response_format(
        replace(request, planning_profile="detail_pack")
    ) != _planner_response_format(request)


@pytest.mark.parametrize(
    "error,category,phase",
    [
        (
            URLError(socket.gaierror(socket.EAI_AGAIN, "secret-host")),
            "dns_error",
            "dns",
        ),
        (
            URLError(ssl.SSLCertVerificationError(1, "secret-cert")),
            "certificate_verification",
            "tls",
        ),
        (
            URLError(ConnectionRefusedError(111, "secret-ip")),
            "connection_refused",
            "connect",
        ),
        (URLError(TimeoutError("secret-url")), "timeout", "response_read"),
    ],
)
def test_transport_diagnostic_redacts_and_fences_unknown_outcome(
    error, category, phase
):
    result = transport_failure(error, "response_read", 601.1234)
    assert result["reason"] == category and result["phase"] == phase
    assert result["elapsed_seconds"] == 601.123
    assert "secret" not in json.dumps(result)
    if category == "timeout":
        assert result["outcome_unknown"] is True
        assert result["safe_to_retry"] is False


def test_wrapped_timeout_does_not_regenerate_a_billed_aurora_image():
    from app.aurora_main_image_provider import _classify_transient_failure

    diagnostic = transport_failure(TimeoutError(), "response_read", 601)
    error = RuntimeError(
        "Planner failed: Provider transport failed: " + json.dumps(diagnostic)
    )
    assert _classify_transient_failure(error) == (False, None)


def test_read_timeout_retains_available_request_id_without_secrets(monkeypatch):
    from app.xinghe_agent import UrllibOpenAITransport, XingheAgentError

    class Response:
        status = 200
        headers = {"x-request-id": "req-test-123"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            raise TimeoutError("secret upstream URL")

    monkeypatch.setattr("app.xinghe_agent.urlopen", lambda *args, **kwargs: Response())
    with pytest.raises(XingheAgentError) as raised:
        UrllibOpenAITransport._send("https://example.test", {}, b"{}", 1)
    assert raised.value.provider_request_id == "req-test-123"
    assert raised.value.retryable is False
    assert '"phase": "response_read"' in str(raised.value)
    assert "secret" not in str(raised.value)


@pytest.mark.parametrize("size", [23999, 24000, 24001])
def test_prompt_budget_counts_final_utf8_bytes(size):
    from app.xinghe_single_image_provider import (
        SingleImageProviderError,
        validate_execution_prompt_budget,
    )

    prompt = "商品" * (size // 6) + "x" * (size % 6)
    assert len(prompt.encode("utf-8")) == size
    if size > 24000:
        with pytest.raises(SingleImageProviderError, match="24001 UTF-8"):
            validate_execution_prompt_budget(prompt)
    else:
        validate_execution_prompt_budget(prompt)
