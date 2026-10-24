"""Stream call audio to Muse Voice Transcribe (speaker labels on) and post each line to the memory service.

Run: uv run --env-file .env python -m capture.transcribe --device "BlackHole 2ch"
List audio inputs with --list-devices (pass the name or its number). To hear the *call* (not just your mic)
on a Mac, route call audio through a virtual device such as BlackHole and pick it here.
The mic is recorded at its own rate (Windows mics often only do 48 kHz) and resampled to Muse's 24 kHz.
Protocol: https://dev.meta.ai/docs/speech-to-text
"""
import argparse
import asyncio
import json
import os

import httpx
import numpy as np
import sounddevice as sd
import soxr
import websockets

from capture.speakers import UNLABELED

URL = "wss://api.meta.ai/v1/asr/realtime"
RATE = 24_000  # Muse PCM_24KHZ: 16-bit mono little-endian
FRAME_SECONDS = 0.08  # 80 ms per frame, as in Meta's example


def resampler(input_rate: int):
    """bytes of 16-bit mono at input_rate -> bytes at Muse's 24 kHz; keeps state so chunk edges don't click."""
    if input_rate == RATE:
        return bytes
    stream = soxr.ResampleStream(input_rate, RATE, 1, dtype="int16", quality="HQ")
    return lambda chunk: stream.resample_chunk(np.frombuffer(chunk, dtype=np.int16)).tobytes()


async def run(device: int | str | None) -> None:
    loop = asyncio.get_running_loop()
    audio: asyncio.Queue[bytes] = asyncio.Queue()
    input_rate = int(sd.query_devices(device, "input")["default_samplerate"])
    to_muse = resampler(input_rate)

    def on_audio(indata, frames, when, status):
        # keep the real-time audio callback light: resampling happens in send_audio
        loop.call_soon_threadsafe(audio.put_nowait, bytes(indata))

    async with websockets.connect(URL) as ws, httpx.AsyncClient(base_url=os.getenv("MEMORY_URL", "http://localhost:8000")) as http:
        await ws.send(json.dumps({
            "authorization": {"accessToken": f"Bearer {os.environ['MODEL_API_KEY']}"},
            "model": "muse-voice-transcribe-1.0",
            "audioEncoding": "PCM_24KHZ",
            "mode": "DIARIZATION",
            "partialMode": "CUMULATIVE",
            "emitAudioProgress": False,
        }))
        ack = json.loads(await ws.recv())
        if ack.get("type") == "error":
            raise SystemExit(f"Muse rejected the session: {ack.get('message')}")
        print("Muse session", ack.get("sessionId"))
        print(f"Listening at {input_rate} Hz (sent to Muse at {RATE} Hz). Speak to test transcription.")

        async def send_audio():
            while True:
                pcm = to_muse(await audio.get())
                if pcm:  # the resampler holds back a few ms at the start
                    await ws.send(pcm)

        async def read_events():
            # shortcut: a turn takes the most recent speaker label; overlapping turns can be mislabeled
            speaker = UNLABELED
            async for raw in ws:
                event = json.loads(raw)
                kind = event.get("type")
                if kind == "speaker":
                    speaker = event.get("label") or speaker
                elif kind == "transcript" and event.get("transcript"):
                    await post(http, {"speaker": speaker, "text": event["transcript"], "final": False})
                elif kind == "speechComplete" and event.get("transcript"):
                    print(f"[{speaker}] {event['transcript']}")
                    await post(http, {"speaker": speaker, "text": event["transcript"], "final": True})
                elif kind == "error":
                    print("Muse error:", event.get("message"))
                # other event types are progress signals; Meta says to ignore unknown types

        blocksize = int(input_rate * FRAME_SECONDS)
        with sd.RawInputStream(samplerate=input_rate, channels=1, dtype="int16", blocksize=blocksize, device=device, callback=on_audio):
            sender = asyncio.create_task(send_audio())
            try:
                await read_events()
            finally:
                sender.cancel()
                try:
                    await sender
                except asyncio.CancelledError:
                    pass
                await ws.send(json.dumps({"type": "endStream"}))


async def post(http: httpx.AsyncClient, line: dict) -> None:
    try:
        response = await http.post("/transcript", json=line)
        response.raise_for_status()
    except httpx.HTTPError as e:
        print(f"memory service unreachable ({e!r})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", help="audio input name or number (default: system default mic)")
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()
    if args.list_devices:
        print(sd.query_devices())
        return
    device = int(args.device) if args.device and args.device.isdigit() else args.device
    # Muse sessions last up to 60 minutes; restart this script for longer calls.
    asyncio.run(run(device))


if __name__ == "__main__":
    main()
