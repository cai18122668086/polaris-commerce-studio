"""W4 supplement materials: sources, downloads, billing, MG validation, brand."""

from __future__ import annotations

import asyncio
import io
import json
import re
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app import services
from app.mg import brand
from app.mg.catalog import (
    COMPONENTS,
    FULLSCREEN_MAX_MS,
    STYLES,
    TOKENS,
    box_size,
    cue_window,
    validate_params,
)
from app.mg.overlay import occupancy, place
from app.models import CreditReservationRecord, WorkspaceCreditAccountRecord
from app.video_editing_contracts import EditingPlanningTaskCreate
from app.video_editing_stock_fetch import (
    FetchError,
    clear,
    download,
    evict,
    normalise_image,
)
from app.video_editing_stock_sources import (
    Candidate,
    _health,
    allowed_url,
    parse_commons,
    parse_openverse,
    parse_pexels_photos,
    parse_pexels_videos,
    parse_pixabay_photos,
    parse_pixabay_videos,
    rank,
    read_key,
    search_provider,
    states,
)
from app.video_editing_supplement_plan import (
    analyze_script,
    plan_mg,
    split_sentences,
    validate_cues,
)
from app.video_editing_task_models import EditingImageRequestRecord
from tests.test_video_editing_tasks import setup_source
from tests.test_video_projects import base

pytest_plugins = ["tests.test_video_projects"]
MG_DIR = Path(__file__).resolve().parents[1] / "app" / "mg"


@pytest.fixture(autouse=True)
def _clean_health():
    _health.blocked_until.clear()
    _health.healthy_until.clear()
    yield
    _health.blocked_until.clear()
    _health.healthy_until.clear()


# ---------------------------------------------------------------- sources


def test_key_files_gate_pexels_and_pixabay(tmp_path, video):
    settings = video[4]
    settings.video_stock_pexels_key_file = tmp_path / "missing.key"
    key = tmp_path / "pixabay.key"
    key.write_text("abcDEF123456789\n")
    settings.video_stock_pixabay_key_file = key
    rows = {row.provider: row for row in states(settings)}
    assert not rows["pexels"].available and rows["pexels"].reason == "暂未开通"
    assert rows["pixabay"].available and rows["pixabay"].reason is None
    assert read_key(None) is None
    bad = tmp_path / "bad.key"
    bad.write_text("not a key; rm -rf /")
    assert read_key(bad) is None


def test_blocked_fallback_marks_unavailable_without_error(tmp_path, video):
    settings = video[4]
    settings.video_stock_cache_dir = tmp_path / "cache"
    settings.video_stock_pexels_key_file = None
    settings.video_stock_pixabay_key_file = None

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="<html>Just a moment...</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    assert (
        search_provider(settings, "openverse", "coffee", "image", client=client) == []
    )
    rows = {row.provider: row for row in states(settings)}
    assert not rows["openverse"].available
    assert rows["openverse"].reason == "暂时无法访问"


def test_fallback_probe_marks_refused_source_before_first_search(video):
    from app.video_editing_stock_sources import probe_fallbacks

    settings = video[4]
    settings.video_stock_commons_enabled = True
    settings.video_stock_openverse_enabled = True

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.openverse.org":
            return httpx.Response(403, text="<html>challenge</html>")
        return httpx.Response(200, json={"query": {}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    probe_fallbacks(settings, client=client)
    rows = {row.provider: row for row in states(settings)}
    assert rows["openverse"].reason == "暂时无法访问"
    assert rows["commons"].available
    calls = []
    counting = httpx.Client(
        transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(200))
    )
    probe_fallbacks(settings, client=counting)  # cached: no new requests
    assert calls == []


def test_allow_list_is_https_and_per_provider():
    assert allowed_url("pexels", "https://images.pexels.com/photos/1/a.jpeg")
    assert not allowed_url("pexels", "http://images.pexels.com/photos/1/a.jpeg")
    assert not allowed_url("pexels", "https://cdn.pixabay.com/a.jpg")
    assert not allowed_url("pixabay", "https://user:pw@cdn.pixabay.com/a.jpg")
    assert not allowed_url("commons", "https://evil.example/upload.wikimedia.org/a.jpg")
    assert not allowed_url("nope", "https://images.pexels.com/a.jpg")


def test_parsers_record_source_author_and_licence():
    pexels = parse_pexels_photos(
        {
            "photos": [
                {
                    "id": 7,
                    "width": 3000,
                    "height": 4500,
                    "url": "https://www.pexels.com/photo/7/",
                    "photographer": "Ann",
                    "photographer_url": "https://www.pexels.com/@ann",
                    "src": {
                        "large2x": "https://images.pexels.com/7-l.jpeg",
                        "medium": "https://images.pexels.com/7-m.jpeg",
                    },
                }
            ]
        }
    )[0]
    assert (pexels.author, pexels.page_url) == (
        "Ann",
        "https://www.pexels.com/photo/7/",
    )
    assert "Pexels License" in pexels.license and pexels.license_url
    assert "download_url" not in pexels.public() and "thumb_url" not in pexels.public()
    video = parse_pexels_videos(
        {
            "videos": [
                {
                    "id": 9,
                    "duration": 12,
                    "url": "https://www.pexels.com/video/9/",
                    "image": "https://images.pexels.com/9.jpg",
                    "user": {"name": "Bo", "url": "https://www.pexels.com/@bo"},
                    "video_files": [
                        {
                            "link": "https://videos.pexels.com/a.mp4",
                            "width": 2160,
                            "height": 3840,
                            "file_type": "video/mp4",
                        },
                        {
                            "link": "https://videos.pexels.com/b.mp4",
                            "width": 1080,
                            "height": 1920,
                            "file_type": "video/mp4",
                        },
                    ],
                }
            ]
        }
    )[0]
    assert video.download_url.endswith("b.mp4") and video.duration_ms == 12000
    pix = parse_pixabay_photos(
        {
            "hits": [
                {
                    "id": 3,
                    "pageURL": "https://pixabay.com/photos/x-3/",
                    "largeImageURL": "https://pixabay.com/get/3.jpg",
                    "webformatURL": "https://pixabay.com/get/3_640.jpg",
                    "imageWidth": 1200,
                    "imageHeight": 1800,
                    "user": "cat",
                }
            ]
        }
    )[0]
    assert pix.author == "cat" and "Pixabay Content License" in pix.license
    pixv = parse_pixabay_videos(
        {
            "hits": [
                {
                    "id": 4,
                    "pageURL": "https://pixabay.com/videos/x-4/",
                    "duration": 8,
                    "user": "dog",
                    "videos": {
                        "large": {
                            "url": "https://cdn.pixabay.com/l.mp4",
                            "width": 1920,
                            "height": 1080,
                            "thumbnail": "https://cdn.pixabay.com/l.jpg",
                        },
                        "medium": {
                            "url": "https://cdn.pixabay.com/m.mp4",
                            "width": 1280,
                            "height": 720,
                            "thumbnail": "https://cdn.pixabay.com/m.jpg",
                        },
                    },
                }
            ]
        }
    )[0]
    assert pixv.kind == "video" and pixv.download_url.endswith("l.mp4")
    # Only CC0 / CC BY, and only on allow-listed hosts.
    verse = parse_openverse(
        {
            "results": [
                {
                    "id": "a",
                    "license": "by",
                    "license_version": "4.0",
                    "url": "https://live.staticflickr.com/a.jpg",
                    "thumbnail": "https://api.openverse.org/t/a",
                    "creator": "C",
                    "width": 800,
                    "height": 1200,
                    "foreign_landing_url": "https://flickr.com/a",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                },
                {
                    "id": "b",
                    "license": "by-sa",
                    "url": "https://live.staticflickr.com/b.jpg",
                    "thumbnail": "https://api.openverse.org/t/b",
                    "width": 800,
                    "height": 1200,
                },
                {
                    "id": "c",
                    "license": "cc0",
                    "url": "https://elsewhere.example/c.jpg",
                    "thumbnail": "https://api.openverse.org/t/c",
                    "width": 800,
                    "height": 1200,
                },
            ]
        }
    )
    assert [row.provider_ref for row in verse] == ["a"] and verse[
        0
    ].license == "CC BY 4.0"
    commons = parse_commons(
        {
            "query": {
                "pages": {
                    "1": {
                        "pageid": 1,
                        "title": "File:a.jpg",
                        "imageinfo": [
                            {
                                "url": "https://upload.wikimedia.org/a.jpg",
                                "thumburl": "https://upload.wikimedia.org/t/a.jpg",
                                "width": 900,
                                "height": 1600,
                                "mime": "image/jpeg",
                                "descriptionurl": "https://commons.wikimedia.org/wiki/File:a.jpg",
                                "extmetadata": {
                                    "LicenseShortName": {"value": "CC BY 4.0"},
                                    "Artist": {"value": "<a>Dee</a>"},
                                },
                            }
                        ],
                    },
                    "2": {
                        "pageid": 2,
                        "title": "File:b.jpg",
                        "imageinfo": [
                            {
                                "url": "https://upload.wikimedia.org/b.jpg",
                                "thumburl": "https://upload.wikimedia.org/t/b.jpg",
                                "width": 900,
                                "height": 1600,
                                "mime": "image/jpeg",
                                "extmetadata": {
                                    "LicenseShortName": {"value": "CC BY-SA 4.0"}
                                },
                            }
                        ],
                    },
                }
            }
        }
    )
    assert [row.provider_ref for row in commons] == ["1"] and commons[0].author == "Dee"
    ordered = rank([pix, video, pexels])
    assert ordered[0].kind == "video"


def test_search_results_are_cached_24h(tmp_path, video):
    settings = video[4]
    settings.video_stock_cache_dir = tmp_path / "cache"
    key = tmp_path / "pixabay.key"
    key.write_text("abcDEF123456789")
    settings.video_stock_pixabay_key_file = key
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.url.host == "pixabay.com"
        return httpx.Response(
            200,
            json={
                "hits": [
                    {
                        "id": 1,
                        "pageURL": "https://pixabay.com/p/1",
                        "largeImageURL": "https://pixabay.com/get/1.jpg",
                        "webformatURL": "https://pixabay.com/get/1s.jpg",
                        "imageWidth": 1000,
                        "imageHeight": 1500,
                        "user": "u",
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    first = search_provider(settings, "pixabay", "咖啡", "image", client=client)
    again = search_provider(settings, "pixabay", "咖啡", "image", client=client)
    assert first == again and len(calls) == 1
    assert "abcDEF123456789" not in json.dumps([row.public() for row in first])


# ---------------------------------------------------------------- downloads


def _client(routes):
    def handler(request: httpx.Request) -> httpx.Response:
        return routes(request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_download_refuses_redirect_off_allow_list_and_oversize():
    redirect = _client(
        lambda r: httpx.Response(
            302, headers={"location": "https://evil.example/x.jpg"}
        )
    )
    with pytest.raises(FetchError, match="STOCK_HOST_NOT_ALLOWED"):
        download("pexels", "https://images.pexels.com/a.jpg", 1000, client=redirect)
    with pytest.raises(FetchError, match="STOCK_HOST_NOT_ALLOWED"):
        download("pexels", "https://evil.example/a.jpg", 1000)
    big = _client(lambda r: httpx.Response(200, content=b"x" * 5000))
    with pytest.raises(FetchError, match="STOCK_TOO_LARGE"):
        download("pexels", "https://images.pexels.com/a.jpg", 1000, client=big)
    ok = _client(
        lambda r: (
            httpx.Response(302, headers={"location": "/b.jpg"})
            if r.url.path == "/a.jpg"
            else httpx.Response(
                200, content=b"img", headers={"content-type": "image/jpeg"}
            )
        )
    )
    assert (
        download("pexels", "https://images.pexels.com/a.jpg", 1000, client=ok)[0]
        == b"img"
    )


def test_images_are_reencoded_without_metadata():
    source = io.BytesIO()
    image = Image.new("RGB", (4000, 3000), (200, 120, 80))
    exif = Image.Exif()
    exif[0x010E] = "secret description"
    image.save(source, format="JPEG", exif=exif)
    data, width, height = normalise_image(source.getvalue())
    assert (width, height) == (2160, 1620)
    with Image.open(io.BytesIO(data)) as out:
        assert out.format == "JPEG" and not out.getexif()
    with pytest.raises(FetchError):
        normalise_image(b"<svg/>")


def test_cache_cap_evicts_oldest_and_clear_empties(tmp_path, video):
    settings = video[4]
    settings.video_stock_cache_dir = tmp_path / "cache"
    settings.video_stock_cache_max_bytes = 2500
    folder = settings.video_stock_cache_dir / "media" / "ab"
    folder.mkdir(parents=True)
    for index in range(4):
        path = folder / f"f{index}"
        path.write_bytes(b"x" * 1000)
        import os

        os.utime(path, (1000 + index, 1000 + index))
    assert evict(settings) == 2000
    assert (
        sorted(p.name for p in folder.iterdir()) == ["f2", "f3"]
        or len(list(folder.iterdir())) == 2
    )
    assert clear(settings) == 2000 and not settings.video_stock_cache_dir.exists()


# ---------------------------------------------------------------- analysis


SCRIPT = (
    "秋冬皮肤干到起皮怎么办？这款面霜一抹就化开，清爽不黏腻。"
    "持久保湿72小时不紧绷。以前要涂三层，现在一瓶搞定。好皮肤是养出来的。"
)


def test_sentences_and_model_output_are_validated(tmp_path, video):
    settings = video[4]
    settings.video_stock_cache_dir = tmp_path / "cache"
    sentences = split_sentences(SCRIPT)
    assert sentences[0] == "秋冬皮肤干到起皮怎么办？" and len(sentences) == 5
    calls = []

    def ask(system, payload, max_tokens):
        calls.append(payload)
        return {
            "sentences": [
                {
                    "index": 1,
                    "type": "selling",
                    "queries": ["face cream texture", "面霜"],
                    "paintable": True,
                    "subject": "白色面霜在指尖轻轻化开",
                    "purpose": "texture",
                },
                {
                    "index": 2,
                    "type": "data",
                    "queries": ["moisture"],
                    "paintable": True,
                    "subject": "医院医生推荐的面霜",
                    "purpose": "concept",
                },
                {"index": 99, "type": "x"},
                "junk",
            ]
        }

    result = analyze_script(settings, SCRIPT, ask=ask)
    rows = {row.index: row for row in result.sentences}
    assert result.source == "model" and len(calls) == 1
    assert rows[1].paintable and rows[1].queries[0] == "face cream texture"
    assert not rows[2].paintable and rows[2].subject == ""  # sensitive subject dropped
    assert not rows[0].paintable
    # Cached: never asks again for the same script.
    assert analyze_script(settings, SCRIPT, ask=ask).public() == result.public()
    assert len(calls) == 1

    def broken(*_):
        raise RuntimeError("gateway down")

    fallback = analyze_script(settings, SCRIPT + "再来一句。", ask=broken)
    assert fallback.source == "rules"
    assert not any(row.paintable for row in fallback.sentences)


def test_ai_image_picks_respect_spacing_and_cap(tmp_path, video):
    from app.video_editing_supplement_plan import ScriptAnalysis, SentencePlan
    from app.video_editing_supplement_routes import pick_paintable

    rows = [
        SentencePlan(
            index=i,
            text="这是一句足够长的口播句子用来估算时长" * 2,
            paintable=True,
            subject="画面",
        )
        for i in range(8)
    ]
    chosen = pick_paintable(ScriptAnalysis("v", "d", "model", rows), 6)
    indexes = [row["sentence_index"] for row in chosen]
    assert all(b - a >= 2 for a, b in zip(indexes, indexes[1:], strict=False))
    assert len(chosen) <= 6


# ---------------------------------------------------------------- MG


def test_mg_params_must_be_verbatim_and_bounded():
    source = "持久保湿72小时不紧绷"
    ok = validate_params(
        "data_callout", {"value": "72", "unit": "小时", "label": "不紧绷"}, source
    )
    assert ok == {"value": "72", "unit": "小时", "label": "不紧绷"}
    assert (
        validate_params("data_callout", {"value": "96", "unit": "小时"}, source) is None
    )
    assert (
        validate_params("data_callout", {"value": "72", "label": "超级保湿"}, source)
        is None
    )
    assert (
        validate_params("data_callout", {"value": "72", "extra": "x"}, source) is None
    )
    assert (
        validate_params(
            "quote_card", {"text": "好皮肤是养出来的" * 4}, "好皮肤是养出来的" * 4
        )
        is None
    )
    assert validate_params("checklist", {"items": ["无酒精"]}, "无酒精") is None
    assert validate_params(
        "checklist", {"items": ["无酒精", "无香精"]}, "无酒精、无香精，孕妇可用"
    ) == {"items": ["无酒精", "无香精"]}
    assert validate_params("nope", {}, source) is None
    assert box_size("checklist", {"items": ["a", "b", "c"]})[1] == 88 + 96 * 3


def test_mg_cues_are_ordered_non_overlapping_and_fullscreen_short():
    utterances = [
        {"id": "u1", "text": "秋冬干皮急救指南"},
        {"id": "u2", "text": "持久保湿72小时不紧绷"},
        {"id": "u3", "text": "以前要涂三层"},
        {"id": "u4", "text": "现在一瓶搞定"},
        {"id": "u5", "text": "好皮肤是养出来的"},
    ]
    raw = {
        "cues": [
            {
                "component": "title_reveal",
                "utterance_ids": ["u1"],
                "params": {"text": "秋冬干皮急救指南"},
            },
            {
                "component": "data_callout",
                "utterance_ids": ["u2"],
                "params": {"value": "72", "unit": "小时"},
            },
            {
                "component": "compare_split",
                "utterance_ids": ["u3", "u4"],
                "params": {"left": "要涂三层", "right": "一瓶搞定"},
            },
            {
                "component": "quote_card",
                "utterance_ids": ["u5"],
                "params": {"text": "好皮肤是养出来的"},
            },
            {
                "component": "title_reveal",
                "utterance_ids": ["u1"],
                "params": {"text": "秋冬"},
            },
            {
                "component": "data_callout",
                "utterance_ids": ["u9"],
                "params": {"value": "1"},
            },
        ]
    }
    from app.mg.catalog import prompt_catalog

    cues, warnings = validate_cues(raw, utterances, prompt_catalog(), validate_params)
    assert [cue.component for cue in cues] == ["title_reveal", "compare_split"]
    assert "mg_cue_overlap" in warnings and "mg_cue_anchor" in warnings
    window = cue_window("title_reveal", 0, 6000, 30000)
    assert window and window[1] - window[0] <= FULLSCREEN_MAX_MS
    assert cue_window("data_callout", 1000, 1300, 30000) == (880, 2480)


def test_mg_plan_falls_back_to_rules_with_one_call_budget(tmp_path, video):
    settings = video[4]
    settings.video_stock_cache_dir = tmp_path / "cache"
    from app.mg.catalog import prompt_catalog

    calls = []

    def ask(system, payload, max_tokens):
        calls.append(1)
        assert "只输出 JSON" in system and len(payload["utterances"]) == 2
        return {
            "cues": [
                {
                    "component": "data_callout",
                    "utterance_ids": ["a"],
                    "params": {"value": "3", "unit": "倍"},
                }
            ]
        }

    rows = [{"id": "a", "text": "吸收快3倍"}, {"id": "b", "text": "真的好用"}]
    first = plan_mg(settings, rows, prompt_catalog(), validate_params, ask=ask)
    again = plan_mg(settings, rows, prompt_catalog(), validate_params, ask=ask)
    assert first == again and len(calls) == 1 and first["source"] == "model"
    rules = plan_mg(
        settings,
        [{"id": "x", "text": "保湿72小时"}],
        prompt_catalog(),
        validate_params,
        use_model=False,
    )
    assert rules["source"] == "rules" and rules["cues"][0]["params"]["value"] == "72"


def test_mg_placement_avoids_face_caption_and_cards_or_skips():
    blocked = [(300, 300, 800, 800), (0, 1500, 1080, 1700)]
    x, y, scale = place("data_callout", blocked, (1080, 1920))
    rect = (x, y, x + 840, y + 400)
    assert not any(
        rect[0] < b[2] and b[0] < rect[2] and rect[1] < b[3] and b[1] < rect[3]
        for b in blocked
    )
    assert place("data_callout", [(0, 0, 1080, 1920)], (1080, 1920)) is None
    assert place("title_reveal", [(0, 0, 1080, 1920)], (1080, 1920)) == (0, 0, 1.0)
    timeline = [
        {
            "n": n,
            "roles": {
                "material": {"bbox": [0, 0, 500, 500], "peak": 1.0},
                "caption": {"bbox": [60, 1500, 1020, 1640], "peak": 1.0},
                "background": {"bbox": [0, 0, 1080, 1920], "peak": 1.0},
            },
        }
        for n in range(30)
    ]
    busy = occupancy(timeline, 0, 29, 1.0)
    assert busy["material"] is True
    assert (60, 1500, 1020, 1640) in busy["boxes"]
    assert all(box != (0, 0, 1080, 1920) for box in busy["boxes"])


def test_brand_palette_and_component_sources_have_no_blue_or_purple():
    assert not any(brand.hex_is_blue_purple(value) for value in TOKENS.values())
    for style in STYLES.values():
        assert not any(
            brand.hex_is_blue_purple(v) for k, v in style.items() if k != "label"
        )
    for name in ("runtime.js", "runtime.css", "catalog.py"):
        assert brand.source_colours((MG_DIR / name).read_text("utf-8")) == [], name
    blue = Image.new("RGBA", (100, 100), (40, 90, 220, 255))
    assert brand.blue_purple_ratio(blue) == 1.0
    warm = Image.new("RGBA", (100, 100), (217, 87, 43, 255))
    for x in range(4):
        warm.putpixel((x, 0), (120, 60, 200, 255))  # 0.04 % purple: allowed
    assert brand.blue_purple_ratio(warm) < brand.LIMIT
    transparent = Image.new("RGBA", (10, 10), (0, 0, 255, 0))
    assert brand.blue_purple_ratio(transparent) == 0.0
    assert len(COMPONENTS) >= 6


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("playwright") is None,
    reason="Chromium renderer only in the editing image",
)
def test_mg_components_render_chinese_without_blue(tmp_path):
    from app.mg.render import browser, render_cue, verify_resources

    verify_resources()
    samples = {
        "data_callout": {"value": "72", "unit": "小时", "label": "持久保湿"},
        "title_reveal": {"text": "秋冬干皮急救指南"},
    }
    with browser() as instance:
        for name, params in samples.items():
            paths = render_cue(
                instance, tmp_path / name, name, params, "paper", 20, 25.0
            )
            assert len(paths) == 20
            assert brand.check_image(paths[15]) < brand.LIMIT
            with Image.open(paths[15]) as image:
                assert image.mode == "RGBA" and image.getbbox()


# ---------------------------------------------------------------- contracts


def test_planning_create_without_supplement_serialises_unchanged():
    body = {"request_id": str(uuid4()), "mode": "prepare", "template_id": "bihuo-02-v1"}
    dumped = EditingPlanningTaskCreate.model_validate(body).model_dump(mode="json")
    assert "supplement" not in dumped
    assert (
        EditingPlanningTaskCreate.model_validate(
            {**body, "supplement": {"mg": {"style": "ink"}}}
        ).supplement.mg.style
        == "ink"
    )
    with pytest.raises(ValueError):
        EditingPlanningTaskCreate.model_validate(
            {**body, "template_id": "apple-minimal-v1", "supplement": {"mg": {}}}
        )
    with pytest.raises(ValueError):
        EditingPlanningTaskCreate.model_validate(
            {
                "request_id": str(uuid4()),
                "mode": "generate",
                "prepared_task_id": str(uuid4()),
                "supplement": {"mg": {}},
            }
        )


# ---------------------------------------------------------------- API + billing


@pytest.fixture
def api(video, tmp_path):
    client, auth, ws, user, settings, project, source = setup_source(video, tmp_path)
    settings.video_stock_cache_dir = tmp_path / "stock-cache"
    settings.video_stock_pexels_key_file = None
    settings.video_stock_pixabay_key_file = None
    settings.video_stock_openverse_enabled = False
    settings.video_stock_commons_enabled = False
    settings.video_script_planning_enabled = False
    settings.video_credit_prices = {"editing_auto_image": 7}
    services.set_quota_enabled(True)
    services.set_credit_enforcement_enabled(True)
    with client.app.state.session_factory() as session:
        account = session.get(WorkspaceCreditAccountRecord, ws)
        if account is not None:
            account.balance_credits = 100
            session.commit()
    try:
        yield client, ws, settings, project
    finally:
        services.set_credit_enforcement_enabled(
            settings.workspace_credit_enforcement_enabled
        )


def test_sources_without_keys_say_not_open(api):
    client, ws, settings, _ = api
    data = client.get(base(ws) + "/editing-supplement/sources").json()
    by_key = {row["key"]: row for row in data["sources"]}
    assert by_key["stock"] == {
        "key": "stock",
        "available": False,
        "reason": "暂未开通",
        "price": "免费",
    }
    assert (
        by_key["ai_image"]["available"] is False
        and by_key["mg"]["reason"] == "暂未开通"
    )
    assert {row["provider"] for row in data["stock_providers"]} == {
        "pexels",
        "pixabay",
        "openverse",
        "commons",
    }
    assert len(data["mg_components"]) >= 6 and len(data["mg_styles"]) == 3
    search = client.post(
        base(ws) + "/editing-supplement/stock/search", json={"script_text": SCRIPT}
    )
    assert search.status_code == 200 and search.json()["providers"] == []
    assert all(row["candidates"] == [] for row in search.json()["sentences"])


def _png(color=(200, 120, 80)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 96), color).save(out, format="PNG")
    return out.getvalue()


def _holds(client, owner_ids):
    with client.app.state.session_factory() as session:
        rows = session.scalars(
            select(CreditReservationRecord).where(
                CreditReservationRecord.owner_id.in_(owner_ids)
            )
        ).all()
        return sorted((r.charge_action, r.status, r.settled_credits) for r in rows)


def test_ai_images_settle_on_success_release_on_failure_cache_is_free(api, monkeypatch):
    from app import video_editing_supplement_images as images
    from app import video_editing_supplement_routes as routes

    client, ws, settings, project = api
    settings.video_supplement_ai_image_enabled = True
    settings.image_api_key = type(settings.image_api_key)("k-test")
    spawned: list[str] = []
    monkeypatch.setattr(routes, "_spawn", lambda request, s, ids: spawned.extend(ids))
    outcomes = {"白色面霜化开": _png(), "被拒的画面": images.ImageRefused()}

    async def fake_provider(settings, prompt, key, client=None):
        assert "画面内无任何文字" in prompt
        for subject, value in outcomes.items():
            if subject in prompt:
                if isinstance(value, Exception):
                    raise value
                return value
        raise RuntimeError("unexpected")

    monkeypatch.setattr(images, "call_provider", fake_provider)
    url = base(ws) + "/editing-supplement/ai-images"
    items = [
        {
            "request_id": str(uuid4()),
            "sentence_index": 1,
            "sentence": "一抹就化开",
            "subject": "白色面霜化开",
        },
        {
            "request_id": str(uuid4()),
            "sentence_index": 3,
            "sentence": "以前要涂三层",
            "subject": "被拒的画面",
        },
    ]
    body = {"project_id": project, "work_item_ref": "wi-1", "items": items}
    created = client.post(url, json=body)
    assert created.status_code == 201, created.text
    ids = [row["id"] for row in created.json()["items"]]
    assert client.post(url, json=body).json()["items"][0]["id"] in ids  # replay
    assert _holds(client, ids) == [("editing_auto_image", "active", 0)] * 2
    factory = client.app.state.session_factory
    for request_id in spawned:
        asyncio.run(images.run_request(factory, settings, request_id))
    status = client.get(url, params={"project_id": project, "ids": ids}).json()["items"]
    by_sentence = {row["sentence_index"]: row for row in status}
    assert (
        by_sentence[1]["status"] == "succeeded"
        and by_sentence[1]["material"]["origin"] == "ai_generated"
    )
    assert (
        by_sentence[3]["status"] == "failed" and "不扣积分" in by_sentence[3]["error"]
    )
    assert _holds(client, ids) == [
        ("editing_auto_image", "released", 0),
        ("editing_auto_image", "settled", 7),
    ]
    # Same prompt again for another video: cache hit, new material, no hold.
    again = client.post(
        url,
        json={
            "project_id": project,
            "work_item_ref": "wi-2",
            "items": [{**items[0], "request_id": str(uuid4())}],
        },
    ).json()["items"][0]
    assert again["status"] == "succeeded" and again["reused"] is True
    assert _holds(client, [again["id"]]) == []
    # Per-video cap.
    settings.video_supplement_ai_image_max_per_video = 2
    many = [
        {
            "request_id": str(uuid4()),
            "sentence_index": i,
            "sentence": "句子",
            "subject": "白色面霜化开",
        }
        for i in (5, 7)
    ]
    capped = client.post(
        url, json={"project_id": project, "work_item_ref": "wi-1", "items": many}
    )
    assert capped.status_code == 422 and "最多生成 2 张" in capped.text


def test_stale_ai_request_is_released_by_sweep(api, monkeypatch):
    from datetime import timedelta

    from app import video_credit_billing
    from app import video_editing_supplement_routes as routes
    from app.models import utc_now

    client, ws, settings, project = api
    settings.video_supplement_ai_image_enabled = True
    settings.image_api_key = type(settings.image_api_key)("k-test")
    monkeypatch.setattr(routes, "_spawn", lambda *a: None)
    created = client.post(
        base(ws) + "/editing-supplement/ai-images",
        json={
            "project_id": project,
            "items": [
                {
                    "request_id": str(uuid4()),
                    "sentence_index": 0,
                    "sentence": "句子",
                    "subject": "清晨的浴室台面",
                }
            ],
        },
    ).json()["items"][0]
    factory = client.app.state.session_factory
    with factory() as session:
        row = session.get(EditingImageRequestRecord, created["id"])
        row.status = "running"
        row.updated_at = utc_now() - timedelta(minutes=30)
        session.commit()
    video_credit_billing.sweep(factory)
    assert _holds(client, [created["id"]]) == [("editing_auto_image", "released", 0)]


def test_stock_import_records_licence_and_delete_guard(api, monkeypatch, tmp_path):
    from app import video_editing_supplement_routes as routes

    client, ws, settings, project = api
    candidate = Candidate(
        provider="pixabay",
        provider_ref="42",
        kind="image",
        width=1000,
        height=1500,
        duration_ms=None,
        thumb_url="https://pixabay.com/get/42s.jpg",
        download_url="https://pixabay.com/get/42.jpg",
        page_url="https://pixabay.com/photos/42/",
        author="Lee",
        author_url=None,
        license="Pixabay Content License（可免费商用，无需署名）",
        license_url="https://pixabay.com/service/license-summary/",
    )
    token = routes._remember(settings, candidate)
    cached = tmp_path / "media.jpg"
    Image.new("RGB", (100, 150), (230, 200, 170)).save(cached, format="JPEG")
    monkeypatch.setattr(
        routes, "fetch_media", lambda s, c: (cached, "image/jpeg", 100, 150)
    )
    body = {
        "project_id": project,
        "request_id": str(uuid4()),
        "token": token,
        "sentence_index": 2,
        "sentence": "持久保湿72小时不紧绷。",
        "work_item_ref": "wi-1",
    }
    url = base(ws) + "/editing-supplement/stock/import"
    first = client.post(url, json=body)
    assert first.status_code == 201, first.text
    row = first.json()
    assert row["origin"] == "stock"
    assert (
        row["provenance"]["license"].startswith("Pixabay")
        and row["provenance"]["author"] == "Lee"
    )
    assert row["provenance"]["page_url"] == "https://pixabay.com/photos/42/"
    assert "token" not in row["provenance"] and "download_url" not in row["provenance"]
    assert client.post(url, json=body).json() == row
    listed = client.get(base(ws) + f"/projects/{project}/editing-materials").json()[
        "items"
    ]
    assert listed[0]["provenance"]["license"] == row["provenance"]["license"]
    removed = client.delete(
        base(ws) + f"/projects/{project}/editing-materials/{row['id']}"
    )
    assert removed.status_code == 204
    assert (
        client.get(base(ws) + f"/projects/{project}/editing-materials").json()["items"]
        == []
    )
    assert re.fullmatch(r"[0-9a-f]{32}", token)


def test_manual_sentence_placement_rewrites_description_until_used(api):
    client, ws, settings, project = api
    url = base(ws) + f"/projects/{project}/editing-materials"
    upload = client.post(
        url,
        data={
            "request_id": str(uuid4()),
            "label": "耳机实拍",
            "description": "商家上传的补充素材，放在画面最贴合的句子",
        },
        files={"file": ("a.png", _png(), "image/png")},
    )
    assert upload.status_code == 201, upload.text
    row = upload.json()
    placement = f"{url}/{row['id']}/placement"
    placed = client.put(placement, json={"sentence_index": 2, "sentence": "耳罩很软。"})
    assert placed.status_code == 200, placed.text
    assert placed.json()["description"] == "用于第 3 句：耳罩很软。"
    assert "origin" not in placed.json()  # still an owner upload
    auto = client.put(placement, json={}).json()
    assert auto["description"] == "商家上传的补充素材，放在画面最贴合的句子"
    assert client.put(placement, json={"sentence_index": 1}).status_code == 422


def test_one_supplement_per_sentence_excludes_covered_sentences():
    from app.video_editing_supplement_plan import ScriptAnalysis, SentencePlan
    from app.video_editing_supplement_routes import pick_paintable, pick_stock_sentences

    rows = [
        SentencePlan(
            index=i,
            text="一句可以画出来的口播内容" * 3,
            paintable=True,
            subject="画面",
            queries=["q"],
        )
        for i in range(6)
    ]
    analysis = ScriptAnalysis("v", "d", "model", rows)
    assert [r["sentence_index"] for r in pick_paintable(analysis, 6, exclude=[0, 2])][
        :1
    ] == [1]
    assert 0 not in [
        r["sentence_index"] for r in pick_paintable(analysis, 6, exclude=[0])
    ]
    assert 3 not in pick_stock_sentences(analysis, exclude=[3])


def test_rank_prefers_candidates_whose_tags_match_the_query():
    def cand(ref, title, kind="image"):
        return Candidate(
            provider="pixabay",
            provider_ref=ref,
            kind=kind,
            width=1000,
            height=1500,
            duration_ms=None,
            thumb_url="https://pixabay.com/t.jpg",
            download_url="https://pixabay.com/d.jpg",
            page_url="https://pixabay.com/p",
            author="a",
            author_url=None,
            license="l",
            license_url="https://pixabay.com/l",
            title=title,
        )

    cat = cand("1", "cat, soft, pet, fur")
    ear = cand("2", "headphones, ear cushion, music")
    assert rank([cat, ear], ["white headphones ear cushion"])[0].provider_ref == "2"
    assert rank([cat, ear])[0].provider_ref == "1"  # no query: original order rules


def test_search_language_follows_the_query(tmp_path, video):
    settings = video[4]
    settings.video_stock_cache_dir = tmp_path / "cache"
    key = tmp_path / "pixabay.key"
    key.write_text("abcDEF123456789")
    settings.video_stock_pixabay_key_file = key
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.params["lang"])
        return httpx.Response(200, json={"hits": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    search_provider(settings, "pixabay", "white headphones", "image", client=client)
    search_provider(settings, "pixabay", "白色耳机", "image", client=client)
    assert seen == ["en", "zh"]


def test_tagged_candidates_must_contain_a_whole_query():
    from app.video_editing_stock_sources import relevant

    def cand(title):
        return Candidate(
            provider="pixabay",
            provider_ref="1",
            kind="image",
            width=1,
            height=2,
            duration_ms=None,
            thumb_url="https://pixabay.com/t.jpg",
            download_url="https://pixabay.com/d.jpg",
            page_url="https://pixabay.com/p",
            author="a",
            author_url=None,
            license="l",
            license_url="https://pixabay.com/l",
            title=title,
        )

    assert relevant(cand("woman, dj, music, headphones"), ["headphones"])
    assert not relevant(cand("animal, cat, soft, pet"), ["headphones", "ear cushion"])
    assert relevant(cand("hand cream, tube, skin care"), ["hand cream"])
    assert not relevant(cand("child, hand, ice cream, cone"), ["hand cream"])
    assert not relevant(cand("ice cream, dessert, waffle"), ["hand cream"])
    assert relevant(cand(None), ["headphones"])  # untagged: provider relevance


def test_mg_plan_uses_short_ids_and_maps_back(tmp_path, video):
    settings = video[4]
    settings.video_stock_cache_dir = tmp_path / "cache"
    from app.mg.catalog import prompt_catalog

    seen = []

    def ask(system, payload, max_tokens):
        seen.append([row["id"] for row in payload["utterances"]])
        return {
            "cues": [
                {
                    "component": "data_callout",
                    "utterance_ids": ["u2"],
                    "params": {"value": "3", "unit": "倍"},
                }
            ]
        }

    rows = [
        {"id": "fb45384b60578-u000001", "text": "你好"},
        {"id": "fb45384b60578-u000002", "text": "吸收快3倍"},
    ]
    plan = plan_mg(settings, rows, prompt_catalog(), validate_params, ask=ask)
    assert seen == [["u1", "u2"]]
    assert plan["cues"][0]["utterance_ids"] == ["fb45384b60578-u000002"]


def test_ai_image_tries_each_failover_key_in_order(video):
    from app import video_editing_supplement_images as images

    settings = video[4]
    secret = type(settings.image_api_key)
    settings.image_api_key = secret("primary-key")
    settings.image_base_url = "https://primary.example"
    settings.provider_failover_enabled = True
    settings.provider_failover_base_url = "https://failover.example"
    settings.provider_failover_api_key = secret("k-one, k-two")
    tried = []

    def handler(request: httpx.Request) -> httpx.Response:
        key = request.headers["Authorization"].removeprefix("Bearer ")
        tried.append((request.url.host, key))
        if key == "primary-key":
            return httpx.Response(502, text="bad gateway")
        if key == "k-one":
            return httpx.Response(401, text="invalid key")
        import base64

        return httpx.Response(
            200, json={"data": [{"b64_json": base64.b64encode(b"img").decode()}]}
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await images.call_provider(settings, "prompt", "idem", client=client)

    assert asyncio.run(run()) == b"img"
    assert tried == [
        ("primary.example", "primary-key"),
        ("failover.example", "k-one"),
        ("failover.example", "k-two"),
    ]


def test_opening_sentence_never_gets_supplements():
    from app.video_editing_supplement_plan import ScriptAnalysis, SentencePlan
    from app.video_editing_supplement_routes import pick_paintable, pick_stock_sentences

    rows = [
        SentencePlan(
            index=i,
            text="可以画出来的一句口播" * 3,
            paintable=True,
            subject="画面",
            queries=["q"],
        )
        for i in range(5)
    ]
    analysis = ScriptAnalysis("v", "d", "model", rows)
    assert 0 not in [r["sentence_index"] for r in pick_paintable(analysis, 6)]
    assert 0 not in pick_stock_sentences(analysis)
