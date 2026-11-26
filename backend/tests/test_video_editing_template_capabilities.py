"""Templates the server cannot render fail before paid planning (e2e 2026-11-25).

bihuo-11/16/19 need the presenter matte model. On a server without it the
planning call was charged first and the render then failed in
bihuo_suite/foreground.py. The picker must not offer such templates and the
planning request must be rejected before any hold or provider call.
"""

import json

import pytest

from app.bihuo_suite import foreground
from app.bihuo_suite.registry import definitions
from app.config import Settings
from app.errors import ApiError
from app.motion_library import sha256
from app.video_editing_planning_store import require_active_planning_template
from app.video_editing_template_capabilities import (
    FOREGROUND_UNAVAILABLE,
    suite_template_blocker,
)
from app.video_editing_template_catalog import template_catalog

MATTE = sorted(k for k, v in definitions().items() if v.get("requires_foreground"))


def settings_with_model(tmp_path, monkeypatch, *, installed: bool) -> Settings:
    if not installed:
        return Settings(_env_file=None, video_editing_tasks_dir=tmp_path)
    model = tmp_path / "matte.onnx"
    model.write_bytes(b"stand-in matte weights")
    monkeypatch.setattr(foreground, "MODEL_SHA", sha256(model))
    manifest = tmp_path / "bindings.json"
    manifest.write_text(json.dumps({"resources": {foreground.MODEL_ID: str(model)}}))
    return Settings(
        _env_file=None,
        video_editing_tasks_dir=tmp_path,
        video_editing_native_bindings_file=manifest,
    )


def test_matte_templates_are_the_ones_that_failed_in_e2e():
    assert {"bihuo-11-v1", "bihuo-16-v1", "bihuo-19-v1"} <= set(MATTE)


def test_planning_rejected_before_charge_without_matte_model(tmp_path, monkeypatch):
    settings = settings_with_model(tmp_path, monkeypatch, installed=False)
    for template_id in MATTE:
        with pytest.raises(ApiError) as caught:
            require_active_planning_template(template_id, settings)
        assert caught.value.status_code == 409
        assert caught.value.code == "EDITING_TEMPLATE_CAPABILITY_UNAVAILABLE"
        assert caught.value.message == FOREGROUND_UNAVAILABLE
    # Templates without the matte requirement are unaffected.
    require_active_planning_template("bihuo-09-v1", settings)
    assert suite_template_blocker("apple-minimal-v1", settings) is None


def test_installed_model_with_matching_bytes_allows_planning(tmp_path, monkeypatch):
    settings = settings_with_model(tmp_path, monkeypatch, installed=True)
    for template_id in MATTE:
        require_active_planning_template(template_id, settings)


def test_wrong_model_bytes_count_as_unavailable(tmp_path, monkeypatch):
    settings = settings_with_model(tmp_path, monkeypatch, installed=True)
    monkeypatch.setattr(foreground, "MODEL_SHA", "0" * 64)
    assert suite_template_blocker(MATTE[0], settings) == FOREGROUND_UNAVAILABLE


@pytest.mark.parametrize("installed", [False, True])
def test_picker_hides_templates_this_server_cannot_render(
    tmp_path, monkeypatch, installed
):
    settings = settings_with_model(tmp_path, monkeypatch, installed=installed)
    offered = {card["id"] for card in template_catalog(settings, "ws_test")}
    assert set(MATTE) <= offered if installed else not set(MATTE) & offered
    assert "bihuo-09-v1" in offered
