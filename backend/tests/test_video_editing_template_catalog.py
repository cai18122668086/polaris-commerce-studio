"""Catalog presentation must not mutate frozen templates or leak arbitrary files."""

from pathlib import Path

import pytest

from app.config import Settings
from app.errors import ApiError
from app.motion_library import atomic_json, sha256
from app.video_editing_overlay_templates import (
    overlay_templates,
    template_snapshot_matches,
)
from app.video_editing_template_catalog import example_file, template_catalog
from tests.test_video_projects import base

pytest_plugins = ["tests.test_video_projects"]


def test_catalog_retains_all_templates_without_changing_snapshots(tmp_path):
    settings = Settings(_env_file=None, video_editing_tasks_dir=tmp_path)
    before = overlay_templates()
    all_cards = template_catalog(settings, "ws_test")
    cards = [card for card in all_cards if card.get("engine") != "bihuo-full-suite"]
    assert len(before) == 46
    assert len(cards) == 8
    assert {c["id"] for c in cards} < {t["id"] for t in before}
    assert all(template_snapshot_matches(t) for t in before)
    assert overlay_templates() == before
    assert len([c for c in cards if c["featured"]]) == 8
    assert next(c for c in cards if c["id"] == "rotation-cards-v1")["featured"]
    assert len({tuple(c["visual_features"]) for c in cards}) == 8
    assert all(set(c["signature_group_ids"]) <= set(c["group_ids"]) for c in cards)
    assert all(c["business_review"] == "pending" for c in cards)
    assert all(c["sampled_group_count"] == 0 for c in cards)
    assert "question-card-b-story-v1" not in {c["id"] for c in cards}


def install_example(tmp_path: Path):
    video = tmp_path / "film.mp4"
    video.write_bytes(b"sample bytes for transport-contract test, not a rendered film")
    entry = {
        "video": {"file": video.name, "sha256": sha256(video)},
        "metadata": {
            "title": "Contract fixture",
            "round": "recorded_response_replay",
            "distinct_groups": 9,
            "occurrences": 14,
            "width": 768,
            "height": 1366,
        },
    }
    atomic_json(
        tmp_path / "manifest.json", {"examples": {"product-explainer-v1": entry}}
    )
    return entry, video


def test_example_tamper_and_path_escape_are_rejected(tmp_path):
    entry, video = install_example(tmp_path)
    settings = Settings(_env_file=None, video_editing_template_examples_dir=tmp_path)
    assert example_file(settings, "product-explainer-v1", "video")[1] == video
    video.write_bytes(b"changed")
    with pytest.raises(ApiError):
        example_file(settings, "product-explainer-v1", "video")
    entry["video"] = {"file": "../private.mp4", "sha256": "0" * 64}
    atomic_json(
        tmp_path / "manifest.json", {"examples": {"product-explainer-v1": entry}}
    )
    with pytest.raises(ApiError):
        example_file(settings, "product-explainer-v1", "video")


def test_catalog_and_example_are_workspace_scoped_with_range_support(video, tmp_path):
    client, _, ws, _, settings = video
    settings.video_editing_enabled = True
    settings.video_editing_library_dir = tmp_path
    (tmp_path / "adapter.py").touch()
    settings.video_editing_tasks_dir = tmp_path / "tasks"
    settings.video_editing_template_examples_dir = tmp_path
    _, media = install_example(tmp_path)
    response = client.get(base(ws) + "/editing-template-catalog")
    assert response.status_code == 200, response.text
    card = response.json()[0]
    assert card["example"]["distinct_groups"] == 9
    url = card["example"]["url"]
    assert client.get(url).content == media.read_bytes()
    assert client.get(url, headers={"Range": "bytes=0-5"}).status_code == 206
    assert client.get(url.replace(ws, "ws_outside")).status_code in {403, 404}
    media.write_bytes(b"changed")
    assert client.get(url).status_code == 404
    assert (
        client.get(base(ws) + "/editing-template-catalog").json()[0]["example"] is None
    )
