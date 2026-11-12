"""Compare the delivery's decoded audio with the original and the native stems."""

from __future__ import annotations

import math
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, BinaryIO

if TYPE_CHECKING:
    import numpy as np
    import numpy.typing as npt

RATE = 48_000
CHANNELS = 2
MAX_SOURCE_AUDIO_OFFSET_SAMPLES = RATE // 2
AUDIO_VALIDATION_VERSION = "tengli.decoded-mix/2"
_SAMPLE_BYTES = CHANNELS * 4
_WINDOW = RATE // 4
_VOICE_TOLERANCE = 2e-5
_MIX_ERROR_DB = -22
_WINDOW_ERROR_DB = -12
_WINDOW_ERROR_FLOOR = 0.001
_AAC_FRAME_SAMPLES = 1024
_MIN_PLANNED_STEM_RMS = 10 ** (-90 / 20)


def _read(stream: BinaryIO, frames: int) -> npt.NDArray[np.float64]:
    import numpy as np

    values = np.frombuffer(stream.read(frames * _SAMPLE_BYTES), dtype="<f4")
    if len(values) != frames * CHANNELS or not np.isfinite(values).all():
        raise ValueError("Decoded audio is truncated or nonfinite")
    return values.astype(np.float64)


def _db(level: float) -> float:
    return round(20 * math.log10(max(level, 1e-10)), 3)


def _mapped_voice(
    source: BinaryIO, start: int, width: int, offset: int, frames: int
) -> npt.NDArray[np.float64]:
    import numpy as np

    begin = max(0, start - offset)
    padding = min(width, max(0, offset - start))
    count = min(width - padding, max(0, frames - begin))
    block = np.zeros(width * CHANNELS, dtype=np.float64)
    if count:
        source.seek(begin * _SAMPLE_BYTES)
        block[padding * CHANNELS : (padding + count) * CHANNELS] = _read(source, count)
    return block


def compare_audio_samples(
    decoded: dict[str, Path],
    frames: int,
    required_stems: set[str],
    guard: Callable[[], None],
    source_offset_samples: int = 0,
) -> dict:
    """Verify stream content in bounded windows on the rendered sample clock."""
    import numpy as np

    lengths = {}
    for name, path in decoded.items():
        length, tail = divmod(path.stat().st_size, _SAMPLE_BYTES)
        # Some AAC muxers expose final encoder padding. The requested sample
        # interval and both container clocks are checked independently.
        padding = _AAC_FRAME_SAMPLES if name == "master" else 0
        unaligned_source = name == "source" and source_offset_samples
        valid = length > 0 if unaligned_source else frames <= length <= frames + padding
        if tail or not valid:
            raise ValueError("Decoded audio length differs from the episode clock")
        lengths[name] = length

    peak_voice_error = 0.0
    peak_output = 0.0
    reference_energy = error_energy = 0.0
    worst_window_error_db = -200.0
    stem_energy = dict.fromkeys(required_stems, 0.0)
    stem_error_projection = dict.fromkeys(required_stems, 0.0)
    with ExitStack() as stack:
        streams = {
            name: stack.enter_context(path.open("rb")) for name, path in decoded.items()
        }
        for start in range(0, frames, _WINDOW):
            guard()
            width = min(_WINDOW, frames - start)
            block = {
                name: _read(stream, width)
                for name, stream in streams.items()
                if name != "source"
            }
            source = _mapped_voice(
                streams["source"],
                start,
                width,
                source_offset_samples,
                lengths["source"],
            )
            voice_error = float(np.max(np.abs(source - block["voice"])))
            peak_voice_error = max(voice_error, peak_voice_error)
            if peak_voice_error > _VOICE_TOLERANCE:
                raise ValueError(
                    "Native voice stem differs from the original narration"
                )
            if "fx" not in required_stems and np.any(block["fx"]):
                raise ValueError("Unplanned sound is present in the native FX stem")
            expected = block["voice"] + block["fx"]
            if "bgm" in block:
                expected += block["bgm"]
            actual = block["master"]
            peak_output = max(peak_output, float(np.max(np.abs(actual))))
            if peak_output > 1:
                raise ValueError("Decoded master audio is overloaded")
            error = actual - expected
            signal = float(np.sum(expected**2))
            residual = float(np.sum(error**2))
            signal_rms = math.sqrt(signal / len(expected))
            error_rms = math.sqrt(residual / len(expected))
            if error_rms > max(
                _WINDOW_ERROR_FLOOR, signal_rms * 10 ** (_WINDOW_ERROR_DB / 20)
            ):
                raise ValueError("Decoded master audio has a local mix mismatch")
            if signal_rms >= 0.003:
                worst_window_error_db = max(
                    worst_window_error_db, _db(error_rms / signal_rms)
                )
            reference_energy += signal
            error_energy += residual
            for name in required_stems:
                stem_energy[name] += float(np.sum(block[name] ** 2))
                stem_error_projection[name] += float(np.sum(error * block[name]))
    if reference_energy <= 0:
        raise ValueError("Expected narration mix is silent")
    mix_error = _db(math.sqrt(error_energy / reference_energy))
    if mix_error > _MIX_ERROR_DB:
        raise ValueError("Decoded master audio differs from the verified native mix")
    stem_evidence = {}
    for name, energy in stem_energy.items():
        rms = math.sqrt(energy / (frames * CHANNELS))
        if rms < _MIN_PLANNED_STEM_RMS:
            raise ValueError("A selected native sound stem is silent")
        # A whole stem can disappear beneath louder narration while aggregate
        # error stays small. Its waveform projects onto that missing content.
        projected_gain = 1 + stem_error_projection[name] / energy
        if not 0.65 <= projected_gain <= 1.35:
            raise ValueError("A selected native sound stem is missing or altered")
        stem_evidence[name] = {
            "rms_dbfs": _db(rms),
            "decoded_projection_gain": round(projected_gain, 6),
        }
    return {
        "version": AUDIO_VALIDATION_VERSION,
        "sample_rate": RATE,
        "source_audio_offset_samples": source_offset_samples,
        "frames_compared": frames,
        "aac_padding_samples": lengths["master"] - frames,
        "source_voice_peak_error_dbfs": _db(peak_voice_error),
        "master_peak_dbfs": _db(peak_output),
        "master_mix_error_db": mix_error,
        "worst_active_window_error_db": worst_window_error_db,
        "window_ms": 250,
        "selected_stems": stem_evidence,
    }
