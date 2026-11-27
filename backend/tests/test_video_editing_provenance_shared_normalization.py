"""Preview-time provenance must replay exactly the repairs planning recorded.

Planning normalizes a saved response in five steps (measured windows, native
assets, chapter starts, beat relations, unified scene repair) and writes the
window/scene repairs into its receipt. Provenance used to replay only the first
two, so any plan whose signature scene was downgraded (e.g. an empty Z-M11 beat
in unified-paper-typewriter) failed at preview with
EDITING_PLANNING_PROVENANCE_CHANGED after a paid planning call.
"""

import inspect

from app import video_editing_planner, video_editing_planning_provenance


def test_provenance_replays_the_planner_normalization():
    assert (
        video_editing_planning_provenance.normalize_response_plan
        is video_editing_planner.normalize_response_plan
    )
    source = inspect.getsource(video_editing_planning_provenance)
    assert "normalize_azl_windows(" not in source
    assert "bind_selected_native_assets(" not in source


def test_normalization_covers_every_recorded_repair_step():
    source = inspect.getsource(video_editing_planner.normalize_response_plan)
    for step in (
        "normalize_azl_windows(",
        "bind_selected_native_assets(",
        "normalize_chapter_starts(",
        "normalize_beat_relations(",
        "repair_unified_beats(",
    ):
        assert step in source
    generate = inspect.getsource(video_editing_planner.generate)
    assert "normalize_response_plan(" in generate
    assert "repair_unified_beats(" not in generate
