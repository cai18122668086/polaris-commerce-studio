"""Native W-R14 layout identities and measured action checks."""

import math

JUDGMENT_GROUP = "W-R14"
JUDGMENT_BRUSH_FONT = "font-06b2048c592b1dae"
JUDGMENT_BACKGROUND = "/media/background/path"
JUDGMENT_IMAGES = ("/media/person_right/path", "/media/evidence_left/path")
JUDGMENT_LABELS = ("/content/left_label", "/content/right_label")
JUDGMENT_CONCLUSION = "/content/conclusion"
JUDGMENT_EVENTS = tuple(
    "/timing/events/" + name
    for name in (
        "evidence_entries/0",
        "evidence_entries/1",
        "check_in",
        "cross_in",
        "conclusion_in",
        "exit_in",
    )
)


# The original Build12 remaps measured actions to these draw() thresholds.
_NATIVE_THRESHOLDS = (0.35, 0.5, 1.1, 1.75, 2.25, 3.45)


def judgment_entry_frame(shot: dict, fps: int, path: str) -> int:
    if (
        shot["group_id"] != JUDGMENT_GROUP
        or shot["layer"] != "scene"
        or fps != 30
        or path not in JUDGMENT_EVENTS[:-1]
    ):
        raise ValueError("Judgment sound needs an original visible entry")
    events = shot["config"]["timing"]["events"]
    measured = (
        *events["evidence_entries"],
        events["check_in"],
        events["cross_in"],
        events["conclusion_in"],
        events["exit_in"],
    )
    index = JUDGMENT_EVENTS.index(path)
    actual_at, actual_next = measured[index : index + 2]
    native_at, native_next = _NATIVE_THRESHOLDS[index : index + 2]
    if actual_next <= actual_at:
        raise ValueError("Judgment actions must keep the original order")
    slope = (native_next - native_at) / (actual_next - actual_at)
    start_ms = round(shot["start_seconds"] * 1000)
    for frame in range(math.floor(actual_at * fps), math.ceil(actual_next * fps) + 1):
        native_frame = round((native_at + (frame / fps - actual_at) * slope) * fps)
        if native_frame / fps > native_at:
            return max((start_ms * fps + 999) // 1000, start_ms * fps // 1000 + frame)
    raise ValueError("Judgment action does not have a visible frame")
