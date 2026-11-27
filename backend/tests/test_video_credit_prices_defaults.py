"""Pin the default video credit prices (docs/video-pricing-20261125.md)."""

import pytest

from app.config import Settings
from app.video_credit_prices import ACTIONS, DEFAULT_PRICES, price_list

EXPECTED = {
    "lipsync": 50,
    "avatar_motion": 60,
    "avatar_register": 5,
    "voice_clone": 30,
    "editing_planning": 10,
    "editing_render": 10,
    "benchmark_search": 5,
    "writing_generate": 10,
    "cover_generate": 7,
    "editing_auto_image": 7,
    "avatar_polish": 7,
    "writing_publish_fill": 2,
}


def test_defaults_are_pinned_and_cover_every_action() -> None:
    assert DEFAULT_PRICES == EXPECTED
    assert set(DEFAULT_PRICES) == set(ACTIONS)
    assert all(type(value) is int and value >= 1 for value in DEFAULT_PRICES.values())


def test_settings_use_defaults_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POLARIS_VIDEO_CREDIT_PRICES", raising=False)
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.video_credit_prices == EXPECTED
    # Each Settings gets its own copy; mutating one never edits the defaults.
    settings.video_credit_prices["lipsync"] = 1
    assert DEFAULT_PRICES["lipsync"] == 50
    listed = price_list(Settings(_env_file=None).video_credit_prices)  # type: ignore[call-arg]
    assert listed.configured is True
    assert {item.action: item.credits for item in listed.prices} == EXPECTED


def test_env_overrides_and_empty_object_disables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POLARIS_VIDEO_CREDIT_PRICES", '{"lipsync": 70}')
    assert Settings(_env_file=None).video_credit_prices == {"lipsync": 70}  # type: ignore[call-arg]
    monkeypatch.setenv("POLARIS_VIDEO_CREDIT_PRICES", "{}")
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.video_credit_prices == {}
    assert price_list(settings.video_credit_prices).configured is False


def test_env_example_matches_defaults() -> None:
    import json
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / ".env.example"
    line = next(
        row
        for row in example.read_text(encoding="utf-8").splitlines()
        if row.startswith("POLARIS_VIDEO_CREDIT_PRICES=")
    )
    assert json.loads(line.split("=", 1)[1]) == EXPECTED
