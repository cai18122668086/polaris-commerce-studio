from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain import JobType
from app.errors import ApiError
from app.routes_v1 import _reserve_real_provider_job_if_enabled


@pytest.mark.parametrize(
    "job_type",
    [
        JobType.PRODUCT_IMAGE.value,
        JobType.REFERENCE_REMIX.value,
        JobType.CREATIVE_IMAGE.value,
        JobType.AMAZON_VISUAL_SUITE.value,
    ],
)
def test_tengli_rejects_unregistered_provider_before_quota_or_dispatch(
    job_type: str,
) -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(task_runner="tengli"),
            )
        )
    )
    job = SimpleNamespace(type=job_type)

    with pytest.raises(ApiError) as captured:
        _reserve_real_provider_job_if_enabled(
            SimpleNamespace(),
            request,
            job,
            "user_test",
        )

    assert captured.value.status_code == 503
    assert captured.value.code == "REAL_PROVIDER_NOT_REGISTERED"
    assert captured.value.details == {
        "job_type": job_type,
        "provider_called": False,
    }


def test_mock_keeps_new_skill_submission_available() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(task_runner="mock"),
            )
        )
    )

    _reserve_real_provider_job_if_enabled(
        SimpleNamespace(),
        request,
        SimpleNamespace(type=JobType.PRODUCT_IMAGE.value),
        "user_test",
    )
