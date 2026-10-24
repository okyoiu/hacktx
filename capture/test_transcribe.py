import numpy as np
import pytest

from capture.transcribe import RATE, resampler


@pytest.mark.parametrize("input_rate", [48_000, 44_100])
def test_mic_audio_reaches_muse_at_24khz(input_rate):
    to_muse = resampler(input_rate)
    tone = (np.sin(np.arange(input_rate) * 2 * np.pi * 440 / input_rate) * 8000).astype(np.int16)
    chunk = int(input_rate * 0.08)
    out = b"".join(to_muse(tone[i:i + chunk].tobytes()) for i in range(0, len(tone), chunk))
    samples = np.frombuffer(out, dtype=np.int16)
    # one second in -> about one second out at 24 kHz (the stream holds back a few ms at the end)
    assert RATE * 0.95 < len(samples) <= RATE
    assert np.abs(samples).max() > 4000  # the tone survived, not silence


def test_24khz_mic_passes_through_untouched():
    data = np.arange(100, dtype=np.int16).tobytes()
    assert resampler(RATE)(data) == data
