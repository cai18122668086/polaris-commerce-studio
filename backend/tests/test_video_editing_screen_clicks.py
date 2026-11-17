from pathlib import Path

import cv2
import numpy as np

from app.video_editing_screen_clicks import detect_screen_clicks
from app.video_editing_tutorial_sound import recording_sound


def test_only_persistent_single_selection_receives_a_click(monkeypatch):
    frames = []
    for index in range(60):
        frame = np.full((512, 960, 3), 235, dtype=np.uint8)
        if 10 <= index < 12:
            cv2.circle(frame, (180, 350), 5, (30, 255, 170), -1, cv2.LINE_AA)
        if index >= 20:
            cv2.circle(frame, (280, 250), 5, (30, 255, 170), -1, cv2.LINE_AA)
        if index >= 40:
            frame[80:480, :250] = 80
            for x in (80, 120, 170):
                cv2.circle(frame, (x, 200), 5, (30, 255, 170), -1, cv2.LINE_AA)
        frames.append(frame)

    class Capture:
        index = 0

        def get(self, property_id):
            return 30 if property_id == cv2.CAP_PROP_FPS else len(frames)

        def isOpened(self):
            return True

        def grab(self):
            self.index += 1
            return self.index <= len(frames)

        def read(self):
            frame = frames[self.index]
            self.index += 1
            return True, frame

        def release(self):
            pass

    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: Capture())
    clicks = detect_screen_clicks(Path("fixture.mp4"), 2000, lambda: None)
    assert clicks == [{"source_ms": 667, "evidence": "selection_feedback"}]


def test_recording_click_follows_retimed_visual(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.video_editing_tutorial_sound.detect_screen_clicks",
        lambda *_: [{"source_ms": 2400, "evidence": "selection_feedback"}],
    )
    monkeypatch.setattr(
        "app.video_editing_tutorial_sound._cue_wave",
        lambda *_: np.full(500, 0.05, dtype=np.float32),
    )
    _, evidence = recording_sound(
        {
            "duration_ms": 4000,
            "steps": [
                {
                    "asset_id": "recording",
                    "start_ms": 1000,
                    "source_in_ms": 0,
                    "source_out_ms": 3000,
                    "playback_segments": [
                        {"source_in_ms": 0, "source_out_ms": 2000, "output_ms": 1000},
                        {
                            "source_in_ms": 2000,
                            "source_out_ms": 3000,
                            "output_ms": 1000,
                        },
                    ],
                }
            ],
        },
        {"recording": {"path": str(tmp_path / "recording.mp4")}},
        tmp_path,
        None,
        lambda: None,
    )
    assert [event["at_ms"] for event in evidence["events"]] == [1000, 2400]
