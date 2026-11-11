import pytest
from PIL import Image

from app.motion_library import atomic_json, sha256
from app.video_editing_subtitle_sound_clock import (
    SUBTITLE_ENTRY_SYNC,
    subtitle_entry_clock,
)


@pytest.mark.parametrize(("event", "aligned"), [(0, True), (3, False)])
def test_subtitle_sound_uses_first_enabled_frame_or_keeps_later_event(
    tmp_path, event, aligned
):
    folder = tmp_path / "renders/000-AH-S02-rgba"
    folder.mkdir(parents=True)
    frames = []
    for number, alpha in enumerate((255, 96, 255, 255)):
        frame = folder / f"{number:06}.png"
        Image.new("RGBA", (12, 12), (255, 255, 255, alpha)).save(frame)
        frames.append({"frame": number, "path": frame.name, "sha256": sha256(frame)})
    native = {"fps": 30, "width": 12, "height": 12, "frames": len(frames)}
    atomic_json(folder / "sequence.json", {**native, "frames": frames})
    receipt = {
        "group_id": "AH-S02",
        "decoded": True,
        "native": native,
        "rgba_sequence": str(folder),
    }
    episode = {
        "output": {"fps": 30},
        "shots": [
            {
                "group_id": "AH-S02",
                "layer": "subtitle",
                "start_seconds": 0.410,
                "end_seconds": 0.55,
            }
        ],
    }
    cue = {
        "subtitle_entry_sync": SUBTITLE_ENTRY_SYNC,
        "group_id": "AH-S02",
        "phase": "entry",
        "word_binding": {"value": event},
        "anchor_ref": {"shot_index": 0, "unit": "frames"},
    }
    clock = subtitle_entry_clock(tmp_path, episode, cue, [receipt])
    assert clock == {
        "shot_index": 0,
        "native_frame": 2,
        "output_frame": 14,
        "frame_sha256": frames[2]["sha256"],
        "aligned_to_frame": aligned,
    }
    Image.new("RGBA", (12, 12)).save(folder / frames[2]["path"])
    with pytest.raises(ValueError, match="frame changed"):
        subtitle_entry_clock(tmp_path, episode, cue, [receipt])
