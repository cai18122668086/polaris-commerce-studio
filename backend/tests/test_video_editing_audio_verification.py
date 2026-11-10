import numpy as np
import pytest

from app.video_editing_audio_verification import RATE, compare_audio_samples
from app.video_editing_native_audio_channels import stereo_composition_graph


def test_stereo_adaptation_is_limited_to_native_audio_split_and_mix():
    video = "[v]fade=t=out:st=3.6:d=0.4[ending];\n"
    voice = "[0:a]atrim=duration=4,asplit=2[voice][voice_stem];\n"
    bgm = "[1:a]amix=inputs=1,asplit=2[bgm_bus][bgm_stem];\n"
    output = "[voice][2:a][bgm_bus]amix=inputs=3:normalize=0[mixed]"
    original = video + voice + bgm + output
    applied = stereo_composition_graph(original)
    assert applied.startswith(video)
    assert applied.count(",aformat=channel_layouts=stereo") == 3
    assert applied.replace(",aformat=channel_layouts=stereo", "") == original
    assert (
        stereo_composition_graph(video + voice + output).count(
            ",aformat=channel_layouts=stereo"
        )
        == 2
    )
    with pytest.raises(ValueError, match="filter graph changed"):
        stereo_composition_graph(video + output)


def samples(tmp_path, change=None):
    frames = RATE * 2
    t = np.arange(frames * 2) / (2 * RATE)
    voice = 0.16 * np.sin(2 * np.pi * 192 * t)
    fx = 0.004 * np.sin(2 * np.pi * 528 * t)
    music = 0.0015 * np.sin(2 * np.pi * 240 * t)
    block = {
        "source": voice.copy(),
        "voice": voice,
        "fx": fx,
        "bgm": music,
        "master": voice + fx + music,
    }
    if change:
        change(block)
    paths = {}
    for role, audio in block.items():
        paths[role] = tmp_path / (role + ".f32")
        audio.astype("<f4").tofile(paths[role])
    return paths, frames


def test_mix_check_allows_aac_padding_and_accepts_a_quiet_selected_stem(tmp_path):
    def padding(block):
        block["master"] = np.concatenate([block["master"], np.zeros(2048)])

    paths, frames = samples(tmp_path, padding)
    report = compare_audio_samples(paths, frames, {"bgm", "fx"}, lambda: None)
    assert report["frames_compared"] == frames
    assert report["aac_padding_samples"] == 1024
    assert report["selected_stems"]["bgm"]["decoded_projection_gain"] == 1


@pytest.mark.parametrize("missing", ["fx", "bgm"])
def test_quiet_track_omission_is_detected_beneath_the_narration(tmp_path, missing):
    def mute(block):
        block["master"] -= block[missing]

    paths, frames = samples(tmp_path, mute)
    with pytest.raises(ValueError, match="selected native sound stem is missing"):
        compare_audio_samples(paths, frames, {"bgm", "fx"}, lambda: None)


def test_audio_check_detects_local_narration_mute_and_voice_stem_shift(tmp_path):
    def mute_part(block):
        block["master"][RATE : RATE + RATE // 2] -= block["voice"][
            RATE : RATE + RATE // 2
        ]

    paths, frames = samples(tmp_path, mute_part)
    with pytest.raises(ValueError, match="local mix mismatch"):
        compare_audio_samples(paths, frames, {"bgm", "fx"}, lambda: None)

    def shift_voice(block):
        block["voice"] = np.roll(block["voice"], 72)
        block["master"] = block["voice"] + block["fx"] + block["bgm"]

    paths, frames = samples(tmp_path, shift_voice)
    with pytest.raises(ValueError, match="voice stem differs"):
        compare_audio_samples(paths, frames, {"bgm", "fx"}, lambda: None)
