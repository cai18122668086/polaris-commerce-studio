import pytest
from app.video_editing_contracts import (
    BilingualContrastGloss,
    SemanticBeat,
    SemanticPlan,
    SemanticRelationItem,
    Transcript,
    TranscriptToken,
)
from app.video_editing_native_content import (
    FILM_EVENTS,
    FILM_FEEDBACK_TEMPLATE_ID,
    FILM_LABELS,
    FILM_PHOTOS,
    automatic_translation_labels,
    chapter_ordinal,
    film_feedback_entries,
    number_glyphs,
    package_entries,
    role_scene_chain,
    translation_labels,
    validate_film_feedback_anchors,
    why_word_bindings,
    year_glyphs,
)
from app.video_editing_native_sound import package_entry_frame
from app.video_editing_overlay_templates import overlay_template, validate_template_plan
from app.video_editing_paper_typewriter import paper_character_times
from app.video_editing_template_materials import template_image_requirements
from app.video_editing_unified_alpha import ALPHA_PRESENTER, alpha_source_clock
from app.video_editing_unified_scenes import (
    CHAPTER_TEMPLATE_ID,
    UNIFIED_TEMPLATE_ID,
    unified_action_frame,
)
from PIL import Image


def test_chapter_ordinal_is_derived_from_ordered_source_starts():
    transcript = Transcript(
        source_sha256="a" * 64,
        audio_sha256="b" * 64,
        duration_ms=3000,
        provider="fixture",
        model="fixture",
        language="zh",
        tokens=[
            TranscriptToken(
                id=f"t{i}", text="段", start_ms=i * 500, end_ms=(i + 1) * 500
            )
            for i in range(6)
        ],
        utterances=[],
    )
    beat = SemanticBeat(
        id="chapter",
        group_id="Z-M15",
        first_token_id="t2",
        last_token_id="t3",
        relation="explanation",
        reason="章次对照",
    )
    proof = chapter_ordinal(beat, transcript, ["t0", "t2", "t4"])
    assert proof["display_text"] == "Second" and proof["chapter_number"] == 2
    with pytest.raises(ValueError, match="follow source order"):
        chapter_ordinal(beat, transcript, ["t0", "t4", "t2"])
    with pytest.raises(ValueError, match="saved outline anchor"):
        chapter_ordinal(beat, transcript, ["t0", "t1", "t4"])
    with pytest.raises(ValueError, match="saved outline interval"):
        chapter_ordinal(beat, transcript, ["t0", "t2", "t3"])


def test_automatic_chapters_use_complete_ordered_beat_boundaries():
    plan = SemanticPlan(
        audience_question="要讲什么",
        argument_outline=["现状", "用途", "条件"],
        style_reason="章名用于实录话题切换",
        chapter_start_token_ids=["t0", "t2", "t4"],
        beats=[
            SemanticBeat(
                id=f"b{i}",
                group_id="Z-M15" if i == 1 else "Z-M00",
                first_token_id=f"t{2 * i}",
                last_token_id=f"t{2 * i + 1}",
                relation="explanation",
                reason="章次对照",
            )
            for i in range(3)
        ],
    )
    template = overlay_template(CHAPTER_TEMPLATE_ID)
    validate_template_plan(plan, template, complete=False)
    for markers in ([], ["t0", "t4", "t2"], ["t0", "t3", "t4"], ["t0", "t2", "t2"]):
        invalid = plan.model_copy(update={"chapter_start_token_ids": markers})
        with pytest.raises(ValueError, match="measured plan boundaries"):
            validate_template_plan(invalid, template, complete=False)
    with pytest.raises(ValueError, match="measured plan boundaries"):
        validate_template_plan(
            plan, overlay_template(UNIFIED_TEMPLATE_ID), complete=False
        )


def test_original_number_glyphs_preserve_each_spoken_unit_and_its_reveal():
    native = {
        "text": [
            {"path": "/content/numbers/0", "text": "两斤", "token_ids": ["t1", "t2"]},
            {"path": "/content/numbers/1", "text": "4斤", "token_ids": ["t4", "t5"]},
            {"path": "/content/label", "text": "斤", "token_ids": ["t2"]},
            {
                "path": "/content/captions/0",
                "text": "每瓶两斤",
                "token_ids": ["t0", "t1", "t2"],
            },
            {
                "path": "/content/captions/1",
                "text": "到手4斤",
                "token_ids": ["t3", "t4", "t5"],
            },
        ],
        "events": [
            {"path": "/timing/events/black_in", "token_id": "t1", "edge": "start"},
            {"path": "/timing/events/second_number", "token_id": "t4", "edge": "start"},
        ],
    }
    proof = number_glyphs(native)
    assert [row["display_text"] for row in proof] == ["2", "4"]
    assert proof[0]["text"] == "两斤" and proof[1]["unit"] == "斤"
    native["text"][1]["text"] = "4克"
    with pytest.raises(ValueError, match="same spoken unit"):
        number_glyphs(native)
    native["text"][1]["text"] = "4斤"
    native["events"][1]["token_id"] = "t3"
    with pytest.raises(ValueError, match="spoken amount start"):
        number_glyphs(native)
    native["events"][1]["token_id"] = "t4"
    native["text"][4]["token_ids"] = ["t4", "t6", "t5"]
    with pytest.raises(ValueError, match="within its own caption"):
        number_glyphs(native)


def test_year_glyphs_preserve_spoken_digits_and_reveal_anchor():
    native = {
        "text": [
            {
                "path": "/content/year",
                "text": "二〇二六年",
                "token_ids": ["t1", "t2", "t3", "t4", "t5"],
            }
        ],
        "events": [{"path": "/events/year_frame", "token_id": "t1", "edge": "start"}],
    }
    proof = year_glyphs(native)
    assert proof["display_text"] == "2026年" and proof["text"] == "二〇二六年"
    native["events"][0]["token_id"] = "t2"
    with pytest.raises(ValueError, match="first digit"):
        year_glyphs(native)
    native["text"][0]["text"] = "二十六年"
    with pytest.raises(ValueError, match="four spoken digits"):
        year_glyphs(native)


def test_translation_labels_require_matching_spoken_occurrences():
    native = {
        "group_id": "W-R02",
        "text": [
            {"path": "/content/before", "text": "每瓶", "token_ids": ["t0", "t1"]},
            {"path": "/content/after", "text": "到手", "token_ids": ["t3", "t4"]},
            {"path": "/content/caption_before", "token_ids": ["t0", "t1", "t2"]},
            {"path": "/content/caption_after", "token_ids": ["t3", "t4", "t5"]},
        ],
    }
    labels = {
        "before": {"source_text": "每瓶", "display_text": "PER BOTTLE"},
        "after": {"source_text": "到手", "display_text": "TOTAL"},
    }
    beat = SemanticBeat(
        id="bilingual",
        group_id="W-R02",
        first_token_id="t0",
        last_token_id="t5",
        relation="contrast",
        reason="前后换字",
        translation_gloss=BilingualContrastGloss(before="PER BOTTLE", after="TOTAL"),
    )
    assert automatic_translation_labels(beat, native) == labels
    duplicate = beat.model_copy(
        update={
            "translation_gloss": BilingualContrastGloss(before="TOTAL", after="TOTAL")
        }
    )
    with pytest.raises(ValueError, match="two distinct translations"):
        automatic_translation_labels(duplicate, native)
    result = translation_labels(native, labels)
    assert [r["display_text"] for r in result] == ["PER BOTTLE", "TOTAL"]
    assert result[0]["source_token_ids"] == ["t0", "t1"]
    assert result[1]["semantic_review"] == "unreviewed"
    assert result[1]["origin"] == "trusted_recipe"
    labels["after"]["display_text"] = "<script>"
    with pytest.raises(ValueError, match="short uppercase English"):
        translation_labels(native, labels)
    labels["after"]["display_text"] = "TOTAL"
    native["text"][3]["token_ids"] = ["t6", "t7"]
    with pytest.raises(ValueError, match="its own spoken label and caption"):
        translation_labels(native, labels)


def test_paper_typewriter_uses_measured_words_for_every_glyph():
    tokens = [
        TranscriptToken(id=f"t{i}", text=word, start_ms=500 * i, end_ms=500 * (i + 1))
        for i, word in enumerate(("每瓶", "1000", "克", "到手", "4", "斤", "囤一次"))
    ]
    transcript = Transcript(
        source_sha256="a" * 64,
        audio_sha256="b" * 64,
        duration_ms=3500,
        provider="fixture",
        model="fixture",
        language="zh",
        tokens=tokens,
        utterances=[],
    )
    paths = [f"/content/rows/{i}/{key}" for i in range(2) for key in ("label", "text")]
    beat = SemanticBeat(
        id="paper",
        group_id="Z-M11",
        first_token_id="t0",
        last_token_id="t6",
        relation="parallel",
        reason="分行规格",
        relation_items=[
            SemanticRelationItem(
                id=f"row{i}",
                first_token_id=f"t{i * 3}",
                last_token_id=f"t{i * 3 + 2}",
                native_text_paths=paths[2 * i : 2 * i + 2],
            )
            for i in range(2)
        ],
    )
    native = {
        "clock": {"start_ms": 0, "end_ms": 3500},
        "events": [
            {
                "path": f"/timing/events/row{i}",
                "value": 1.5 * i,
                "token_id": f"t{i * 3}",
                "edge": "start",
            }
            for i in range(2)
        ],
        "text": [
            {
                "path": path,
                "text": "".join(tokens[j].text for j in indexes),
                "token_ids": [f"t{j}" for j in indexes],
                "punctuation_policy": "preserve",
            }
            for path, indexes in zip(paths, ((0,), (1, 2), (3,), (4, 5)), strict=True)
        ],
    }
    assert paper_character_times(beat, native, transcript) == [
        [0.5, 0.5, 0.5, 0.5, 1],
        [2, 2.5],
    ]
    native["events"][1]["token_id"] = "t4"
    with pytest.raises(ValueError, match="their own measured word range"):
        paper_character_times(beat, native, transcript)


def test_role_scene_chain_keeps_the_shared_original_clock():
    timing = "/timing/events/"
    scenes = [
        {
            "path": f"{timing}scene_boundaries/{i}",
            "value": i * 0.7,
            "token_id": f"t{i}",
            "edge": "start",
        }
        for i in range(16)
    ]
    handoff = {**scenes[5], "path": timing + "handoff"}
    native = {
        "events": [
            *scenes,
            {**scenes[4], "path": timing + "door_close"},
            handoff,
            {**scenes[15], "path": timing + "prohibition_in"},
        ],
        "media": [
            {"path": f"/media/scene_layers/{i}/path", "asset_id": f"image-{i}"}
            for i in range(16)
        ],
    }
    assets = {f"image-{i}": {"kind": "image"} for i in range(16)}
    result = role_scene_chain(native, assets)
    assert result["scene_asset_ids"][5] == "image-5"
    assert result["boundaries"][5] == {
        "token_id": "t5",
        "edge": "start",
        "start_seconds": 3.5,
    }
    handoff["token_id"] = "t6"
    with pytest.raises(ValueError, match="handoff"):
        role_scene_chain(native, assets)
    handoff["token_id"] = "t5"
    scenes[4]["value"] = scenes[5]["value"]
    with pytest.raises(ValueError, match="follow speech"):
        role_scene_chain(native, assets)
    assets["image-7"]["kind"] = "video"
    with pytest.raises(ValueError, match="sixteen original"):
        role_scene_chain(native, assets)


def test_package_entries_bind_each_project_image_to_its_own_label_start():
    labels = ("14块9", "两大瓶", "1000克", "4斤")
    native = {
        "text": [
            {"path": f"/content/items/{i}/label", "text": label, "token_ids": [f"t{i}"]}
            for i, label in enumerate(labels)
        ],
        "events": [
            {
                "path": f"/timing/events/item{i}",
                "token_id": f"t{i}",
                "edge": "start",
                "value": i * 0.5,
            }
            for i in range(4)
        ],
        "media": [
            {"path": f"/media/product_images/{i}/path", "asset_id": f"image-{i}"}
            for i in range(4)
        ],
    }
    assets = {
        f"image-{i}": {"kind": "image", "source": "project_upload"} for i in range(4)
    }
    assert [row["label"] for row in package_entries(native, assets)] == list(labels)
    native["events"][2]["token_id"] = "t1"
    with pytest.raises(ValueError, match="spoken label"):
        package_entries(native, assets)
    native["events"][2]["token_id"] = "t2"
    assets["image-2"]["kind"] = "video"
    with pytest.raises(ValueError, match="package image"):
        package_entries(native, assets)


def test_package_sound_starts_on_first_frame_after_zero_alpha():
    shot = {
        "group_id": "Z-M12",
        "layer": "scene",
        "start_seconds": 8.65,
        "config": {"timing": {"events": {"item0": 1.36, "item1": 3.24}}},
    }
    assert package_entry_frame(shot, 30, "/timing/events/item0") == 300
    assert package_entry_frame(shot, 30, "/timing/events/item1") == 357
    with pytest.raises(ValueError, match="30 fps"):
        package_entry_frame(shot, 25, "/timing/events/item1")


def test_film_feedback_counts_are_bound_to_dated_current_evidence():
    native = {
        "text": [
            {
                "path": f"/content/comments/{i}/text",
                "text": "反馈",
                "token_ids": [f"t{i}"],
            }
            for i in range(3)
        ],
        "events": [
            {
                "path": f"/timing/events/comments/{i}",
                "token_id": f"t{i}",
                "edge": "start",
            }
            for i in range(3)
        ],
        "media": [
            {"path": f"/media/photos/{i}/path", "asset_id": f"evidence-{i}"}
            for i in range(3)
        ],
    }
    assets = {
        f"evidence-{i}": {"kind": "image", "source": "project_upload", "sha256": str(i)}
        for i in range(3)
    }
    observations = [
        {
            "asset_id": f"evidence-{i}",
            "label": "反馈",
            "likes": i,
            "source_ref": "已登记反馈页",
            "observed_at": "2026-11-09T08:50:00+00:00",
        }
        for i in range(3)
    ]
    proof = film_feedback_entries(native, assets, observations)
    assert [row["likes"] for row in proof] == [0, 1, 2]
    assert proof[1]["asset_sha256"] == "1"
    registered = {
        item["asset_id"]: {
            **assets[item["asset_id"]],
            "feedback_observation": {
                **{key: value for key, value in item.items() if key != "asset_id"},
                "attests_observation": True,
            },
        }
        for item in observations
    }
    proof = film_feedback_entries(native, registered, None)
    assert [row["likes"] for row in proof] == [0, 1, 2]
    assert {row["observation_provenance"] for row in proof} == {
        "project_owner_attested"
    }
    wrong_count = [observations[0], {**observations[1], "likes": 99}, observations[2]]
    with pytest.raises(ValueError, match="matching project evidence"):
        film_feedback_entries(native, registered, wrong_count)
    duplicate_image = {
        **registered,
        "evidence-2": {**registered["evidence-2"], "sha256": "1"},
    }
    with pytest.raises(ValueError, match="three distinct registered images"):
        film_feedback_entries(native, duplicate_image, None)
    with pytest.raises(ValueError, match="matching project evidence"):
        film_feedback_entries(native, assets, None)
    generated = {
        **assets,
        "evidence-1": {
            **assets["evidence-1"],
            "source_image_result": {"job_id": "job", "asset_id": "asset"},
        },
    }
    with pytest.raises(ValueError, match="matching project evidence"):
        film_feedback_entries(native, generated, observations)
    observations[1]["asset_id"] = "evidence-2"
    with pytest.raises(ValueError, match="matching project evidence"):
        film_feedback_entries(native, assets, observations)
    observations[1]["asset_id"] = "evidence-1"
    observations[1]["observed_at"] = "2026-11-09T08:50:00"
    with pytest.raises(ValueError, match="timezone"):
        film_feedback_entries(native, assets, observations)


def test_film_automatic_admission_needs_measured_labels_and_original_presenter():
    texts = ["Case，", "录", "像。", "对齐。", "时间。", "回放。", "完。"]
    tokens = [
        TranscriptToken(id=f"t{i}", text=value, start_ms=i * 500, end_ms=(i + 1) * 500)
        for i, value in enumerate(texts)
    ]
    transcript = Transcript(
        source_sha256="a" * 64,
        audio_sha256="b" * 64,
        duration_ms=3500,
        provider="fixture",
        model="fixture",
        language="zh",
        tokens=tokens,
        utterances=[],
    )
    images = {
        f"material-{i}": {
            "id": f"material-{i}",
            "kind": "image",
            "sha256": str(i) * 64,
            "feedback_observation_sha256": "c" * 64,
            "feedback_observation_label": label,
        }
        for i, label in enumerate(("对齐", "时间", "回放"))
    }
    items = []
    native = {
        "clock": {"start_ms": 0, "end_ms": 3500},
        "text": [{"path": "/content/english", "text": "Case", "token_ids": ["t0"]}],
        "events": [],
        "media": [{"path": ALPHA_PRESENTER, "asset_id": "source"}],
    }
    for i, (photo, label, event) in enumerate(
        zip(FILM_PHOTOS, FILM_LABELS, FILM_EVENTS, strict=True)
    ):
        asset_id = f"material-{i}"
        token = tokens[i + 3]
        items.append(
            SemanticRelationItem(
                id=f"i{i}",
                first_token_id=token.id,
                last_token_id=token.id,
                asset_ids=[asset_id],
                native_text_paths=[label],
                native_media_paths=[photo],
            )
        )
        native["text"].append(
            {"path": label, "text": texts[i + 3][:-1], "token_ids": [token.id]}
        )
        native["events"].append(
            {
                "path": event,
                "token_id": token.id,
                "edge": "start",
                "measured_anchor_ms": token.start_ms,
            }
        )
        native["media"].append({"path": photo, "asset_id": asset_id})
    beat = SemanticBeat(
        id="film",
        first_token_id="t0",
        last_token_id="t6",
        relation="explanation",
        group_id="W-R01",
        reason="三份实际反馈",
        relation_items=items,
    )
    template = overlay_template(FILM_FEEDBACK_TEMPLATE_ID)
    (requirement,) = template_image_requirements(
        template, list(images.values()), transcript=transcript
    )
    assert requirement["selected_distinct_images"] == 3
    assert requirement["feedback_word_matches"]["material-1"][0] == {
        "first_token_id": "t4",
        "last_token_id": "t4",
    }
    images["material-1"]["feedback_observation_label"] = "本期无对应词"
    (requirement,) = template_image_requirements(
        template, list(images.values()), transcript=transcript
    )
    assert requirement["selected_distinct_images"] == 2
    with pytest.raises(ValueError, match="spoken item must match"):
        validate_film_feedback_anchors(beat, native, transcript, images)
    images["material-1"]["feedback_observation_label"] = "时间"
    validate_film_feedback_anchors(beat, native, transcript, images)
    assets = {
        **images,
        "source": {"kind": "original_video", "sha256": transcript.source_sha256},
    }
    assert alpha_source_clock(beat, native, transcript, assets)["frames"] == 105
    with pytest.raises(ValueError, match="current presenter"):
        alpha_source_clock(
            beat, native, transcript, {**assets, "source": images["material-0"]}
        )
    beat.relation_items[1].asset_ids = ["material-0"]
    with pytest.raises(ValueError, match="spoken item must match"):
        validate_film_feedback_anchors(beat, native, transcript, images)

    shot = {
        "group_id": "W-R01",
        "layer": "scene",
        "rect": [0, 0, 1, 1],
        "start_seconds": 2,
        "end_seconds": 5.5,
        "config": {"timing": {"events": {"comments": [1.5, 2.0, 2.5]}}},
    }
    assert [unified_action_frame(shot, 30, event) for event in FILM_EVENTS] == [
        106,
        121,
        136,
    ]


def test_short_question_gloss_preserves_spoken_anchor_and_original_clock(tmp_path):
    props = {}
    bindings = []
    for index in range(2):
        path = tmp_path / f"prop-{index}.png"
        image = Image.new("RGBA", (540, 960))
        image.putpixel((index, 0), (255, 255, 255, 255))
        image.save(path)
        aid = f"prop-{index}"
        props[aid] = {
            "kind": "image",
            "source": "project_upload",
            "path": path,
            "sha256": str(index),
        }
        bindings.append(
            {"path": f"/media/question_props/{index}/path", "asset_id": aid}
        )
    native = {
        "clock": {"start_ms": 0, "end_ms": 3000},
        "text": [
            {"path": "/content/english_question", "text": "谁", "token_ids": ["who"]}
        ],
        "events": [
            {
                "path": f"/timing/events/{key}",
                "value": at,
                "token_id": token,
                "edge": "start",
            }
            for key, at, token in (
                ("props_in/0", 0.1, "first"),
                ("props_in/1", 0.4, "second"),
                ("english_in", 0.8, "who"),
                ("blur_exit", 2.4, "tail"),
            )
        ],
        "media": bindings,
    }
    gloss = why_word_bindings(native, props)
    assert (gloss["source_token_ids"], gloss["display_text"]) == (["who"], "Who?")
    native["events"][0]["value"] = 0
    with pytest.raises(ValueError, match="four ordered W-R17 events"):
        why_word_bindings(native, props)
