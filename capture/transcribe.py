"""Stream call audio to Muse Voice Transcribe (speaker labels on) and post each line to the memory service.

Run: uv run --env-file .env python -m capture.transcribe --device "BlackHole 2ch"
List audio inputs with --list-devices. To hear the *call* (not just your mic) on a Mac, route call audio
through a virtual device such as BlackHole and pick it here.
Protocol: https://dev.meta.ai/docs/speech-to-text
"""
import argparse
import asyncio
import json
import os

import httpx
import sounddevice as sd
import websockets

from capture.speakers import UNLABELED

URL = "wss://api.meta.ai/v1/asr/realtime"
RATE = 24_000  # PCM_24KHZ: 16-bit mono little-endian
FRAME = 1_920  # 80 ms per frame, as in Meta's example


async def run(device: str | None) -> None:
    loop = asyncio.get_running_loop()
    audio: asyncio.Queue[bytes] = asyncio.Queue()

    def on_audio(indata, frames, when, status):
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

        async def send_audio():
            while True:
                await ws.send(await audio.get())

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
                    await post(http, {"speaker": speaker, "text": event["transcript"], "final": True})
                elif kind == "error":
                    print("Muse error:", event.get("message"))
                # other event types are progress signals; Meta says to ignore unknown types

        with sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16", blocksize=FRAME, device=device, callback=on_audio):
            sender = asyncio.create_task(send_audio())
            try:
                await read_events()
            finally:
                sender.cancel()
                await ws.send(json.dumps({"type": "endStream"}))


async def post(http: httpx.AsyncClient, line: dict) -> None:
    try:
        await http.post("/transcript", json=line)
    except httpx.HTTPError as e:
        print(f"memory service unreachable ({e!r})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", help="audio input name or index (default: system default mic)")
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()
    if args.list_devices:
        print(sd.query_devices())
        return
    # Muse sessions last up to 60 minutes; restart this script for longer calls.
    asyncio.run(run(args.device))


if __name__ == "__main__":
    main()
