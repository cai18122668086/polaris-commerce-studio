import pytest
from PIL import Image

from app import video_editing_line_branch as line
from app.motion_library import read_json, sha256
from app.video_editing_template_materials import line_image_slots


def test_stage_line_sheet_keeps_row_major_alpha_frames(tmp_path, monkeypatch):
    monkeypatch.setattr(line, "_LINE_FRAME", (4, 4))
    source = tmp_path / "current.png"
    sheet = Image.new("RGBA", (24, 16))
    for index in range(24):
        row, column = divmod(index, 6)
        sheet.putpixel((column * 4 + 1, row * 4 + 2), (index, 0, 0, 255))
    sheet.save(source)

    directory, digest = line.stage_line_sheet(tmp_path / "task", source, sha256(source))
    manifest = directory / "sequence-binding.json"
    assert sha256(manifest) == digest
    binding = read_json(manifest)
    assert binding["sheet_sha256"] == sha256(source)
    assert len(binding["frames"]) == 24
    with Image.open(directory / "006.png") as frame:
        assert frame.getpixel((1, 2)) == (6, 0, 0, 255)
        assert frame.getpixel((3, 3)) == (0, 0, 0, 0)

    with pytest.raises(ValueError, match="transparent 540"):
        wrong = tmp_path / "wrong.png"
        sheet.convert("RGB").save(wrong)
        line.stage_line_sheet(tmp_path / "wrong-task", wrong, sha256(wrong))

    sheet.putpixel((17, 14), (0, 0, 0, 0))
    missing_frame = tmp_path / "missing-frame.png"
    sheet.save(missing_frame)
    target = tmp_path / "missing-frame-task"
    with pytest.raises(ValueError, match="Every hand frame"):
        line.stage_line_sheet(target, missing_frame, sha256(missing_frame))
    assert list(target.iterdir()) == []


def test_line_preflight_distinguishes_moving_frames_from_stills(tmp_path, monkeypatch):
    monkeypatch.setattr(line, "_LINE_FRAME", (4, 4))
    frame = Image.new("RGBA", (4, 4))
    frame.putpixel((1, 1), (20, 30, 40, 255))
    sheet = Image.new("RGBA", (24, 16))
    for index in range(24):
        row, column = divmod(index, 6)
        sheet.paste(frame, (column * 4, row * 4))
    # RGB values in fully transparent pixels do not make the hand move.
    sheet.putpixel((0, 0), (50, 60, 70, 0))
    still = tmp_path / "still.png"
    sheet.save(still)
    sheet.putpixel((1, 2), (20, 30, 40, 255))
    moving = tmp_path / "moving.png"
    sheet.save(moving)
    drawing = tmp_path / "drawing.png"
    frame.save(drawing)
    previous = tmp_path / "previous.png"
    frame.convert("RGB").save(previous)
    assets = {p.stem: {"path": str(p)} for p in (still, moving, drawing, previous)}
    assert line_image_slots(assets) == {
        line.LINE_DIRECTOR_PATH: ["drawing"],
        line.LINE_HAND_PATH: ["moving"],
        line.LINE_PREVIOUS_PATH: ["previous"],
    }
