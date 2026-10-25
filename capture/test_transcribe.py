import asyncio
import json

import sounddevice as sd
import numpy as np
import pytest

from capture import transcribe
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


class FakeWS:  # stands in for Muse's WebSocket
    def __init__(self, ack, events=()):
        self.ack, self.events = ack, events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        pass

    async def send(self, data):
        pass

    async def recv(self):
        return json.dumps(self.ack)

    async def __aiter__(self):
        for event in self.events:
            yield json.dumps(event)


class FakeMic:
    def __init__(self, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


@pytest.mark.parametrize("verbose", [False, True])
def test_keeps_listening_through_no_mic_a_rejection_and_the_end_of_a_session(monkeypatch, capsys, verbose):
    monkeypatch.setenv("MODEL_API_KEY", "fake")
    monkeypatch.setattr(transcribe.sd, "RawInputStream", FakeMic)
    mics = iter([sd.PortAudioError("no input device"), None, None, None, None])

    def query(device, kind):
        if isinstance(m := next(mics), Exception):
            raise m
        return {"default_samplerate": RATE}

    sessions = iter([
        FakeWS({"type": "error", "message": "bad key"}),
        FakeWS({"type": "ack", "sessionId": "s1"}, [{"type": "speechComplete", "transcript": "hello"}]),  # then Muse hangs up
        OSError("network down"),
        FakeWS({"type": "ack", "sessionId": "s2"}),
    ])

    def connect(url):
        if isinstance(s := next(sessions), Exception):
            raise s
        return s

    lines, waits = [], []

    async def post(http, line):
        lines.append(line)

    async def sleep(seconds):
        waits.append(seconds)
        if len(waits) == 5:
            raise StopAsyncIteration

    monkeypatch.setattr(transcribe.sd, "query_devices", query)
    monkeypatch.setattr(transcribe.websockets, "connect", connect)
    monkeypatch.setattr(transcribe, "post", post)
    monkeypatch.setattr(transcribe.asyncio, "sleep", sleep)
    with pytest.raises(StopAsyncIteration):
        asyncio.run(transcribe.keep_listening(None, verbose))
    assert waits == [2, 4, 2, 2, 2]  # no mic, rejection (wait doubles), a clean end resets it, network drop, clean end
    assert lines == [{"speaker": "speaker", "text": "hello", "final": True}]
    out = capsys.readouterr().out
    assert "no input device" in out and "bad key" in out and "network down" in out and "starting a new one" in out
    assert ("[speaker] hello" in out) == verbose  # sentences print only with --verbose
