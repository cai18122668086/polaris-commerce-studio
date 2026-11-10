import hashlib
import json

import pytest

from app.config import Settings
from app.errors import ApiError
from app.motion_library import atomic_json, sha256
from app.video_editing_contracts import Transcript, TranscriptToken
from app.video_editing_planner import generate


def setup_request(tmp_path, monkeypatch):
    package = tmp_path / "package"
    atomic_json(package / "catalog/groups.json", {"groups": [{"id": "G1"}]})
    transcript = Transcript(
        audio_sha256="a" * 64,
        source_sha256="b" * 64,
        duration_ms=1000,
        provider="fixture",
        model="fixture",
        language="zh",
        tokens=[TranscriptToken(id="t0", text="完整原声", start_ms=0, end_ms=1000)],
        utterances=[],
    )
    settings = Settings(
        _env_file=None,
        video_editing_library_dir=package,
        video_editing_planning_enabled=True,
    )

    def request(
        t,
        p,
        m,
        assets,
        choices=None,
        template=None,
        runtime=None,
        *,
        public_copy_only=False,
    ):
        body = {"transcript": t.model_dump(), "model": m, "assets": assets}
        if template is not None:
            body["overlay_template"] = template
        fingerprint = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode()
        ).hexdigest()
        return body, {"request_sha256": fingerprint}

    monkeypatch.setattr("app.video_editing_planner.build_request", request)
    return transcript, settings


class Provider:
    def __init__(self, lost=False, malformed=False):
        self.calls = 0
        self.lost, self.malformed = lost, malformed

    def request(self, *args, **kwargs):
        self.calls += 1
        if self.lost:
            raise ApiError(502, "OUTCOME_UNKNOWN", "fixture")
        plan = {
            "audience_question": "内容是什么",
            "argument_outline": ["完整原声"],
            "style_reason": "fixture",
            "beats": [
                {
                    "id": "b",
                    "first_token_id": "t0",
                    "last_token_id": "t0",
                    "relation": "explanation",
                    "group_id": "G1",
                    "reason": "fixture",
                }
            ],
        }
        return {
            "id": "fixture-response",
            "choices": [
                {
                    "message": {
                        "content": "invalid" if self.malformed else json.dumps(plan)
                    }
                }
            ],
        }


def test_recovery_reuses_saved_response_and_rejects_changed_source(
    tmp_path, monkeypatch
):
    transcript, settings = setup_request(tmp_path, monkeypatch)
    provider = Provider()
    root = tmp_path / "stable-task-planning"
    first = generate(root, transcript, settings, provider)
    # Simulate loss of post-response validation files, not the billed response.
    (root / "semantic-plan.json").unlink()
    (root / "semantic-validated.json").unlink()
    assert generate(root, transcript, settings, provider) == first
    assert provider.calls == 1
    receipt = json.loads((root / "semantic-validated.json").read_text())
    assert receipt["plan_sha256"] == sha256(root / "semantic-plan.json")
    assert receipt["validation"] == "contract_only"
    changed = transcript.model_copy(deep=True)
    changed.tokens[0].text = "校对后的另一份录音文字"
    with pytest.raises(ApiError) as error:
        generate(root, changed, settings, provider)
    assert error.value.code == "EDITING_PLAN_INPUT_CHANGED"
    assert provider.calls == 1


@pytest.mark.parametrize("malformed", [False, True])
def test_uncertain_or_invalid_result_never_blindly_bills_again(
    tmp_path, monkeypatch, malformed
):
    transcript, settings = setup_request(tmp_path, monkeypatch)
    provider = Provider(lost=not malformed, malformed=malformed)
    root = tmp_path / "stable-task-planning"
    for _ in range(2):
        with pytest.raises((ApiError, ValueError)):
            generate(root, transcript, settings, provider)
    assert provider.calls == 1
    assert (root / "semantic-submit-intent.json").is_file()
