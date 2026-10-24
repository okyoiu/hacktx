
"""Stream call audio to Muse Voice Transcribe and post transcript lines to memory."""

import argparse
import asyncio
import json
import os

import httpx
import sounddevice as sd
import soxr
import websockets

URL = "wss://api.meta.ai/v1/asr/realtime"

# The microphone's native sample rate and the rate required by Muse.
INPUT_RATE = 48_000
RATE = 24_000  # Muse PCM_24KHZ: 16-bit mono little-endian
FRAME = 1_920  # 80 ms at 24 kHz
INPUT_FRAME = int(FRAME * INPUT_RATE / RATE)  # 3,840 samples = 80 ms at 48 kHz


async def run(device: int | str | None) -> None:
    loop = asyncio.get_running_loop()
    audio: asyncio.Queue[bytes] = asyncio.Queue()

    def on_audio(indata, frames, when, status):
        # Capture at 48 kHz, then resample to Muse's required 24 kHz.
        samples = memoryview(indata).cast("h")
        converted = soxr.resample(
            samples, INPUT_RATE, RATE, quality="HQ"
        )
        pcm = converted.astype("<i2").tobytes()
        loop.call_soon_threadsafe(audio.put_nowait, pcm)

    async with (
        websockets.connect(URL) as ws,
        httpx.AsyncClient(
            base_url=os.getenv("MEMORY_URL", "http://localhost:8000")
        ) as http,
    ):
        await ws.send(json.dumps({
            "authorization": {
                "accessToken": f"Bearer {os.environ['MODEL_API_KEY']}"
            },
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
        print("Listening to microphone. Speak to test transcription.")

        async def send_audio():
            while True:
                await ws.send(await audio.get())

        async def read_events():
            speaker = "speaker"
            async for raw in ws:
                event = json.loads(raw)
                kind = event.get("type")

                if kind == "speaker":
                    speaker = event.get("label") or speaker
                elif kind == "transcript" and event.get("transcript"):
                    text = event["transcript"]
                    print(f"[{speaker}] {text}")
                    await post(
                        http,
                        {"speaker": speaker, "text": text, "final": False},
                    )
                elif kind == "speechComplete" and event.get("transcript"):
                    text = event["transcript"]
                    print(f"[{speaker}] FINAL: {text}")
                    await post(
                        http,
                        {"speaker": speaker, "text": text, "final": True},
                    )
                elif kind == "error":
                    print("Muse error:", event.get("message"))

        with sd.RawInputStream(
            samplerate=INPUT_RATE,
            channels=1,
            dtype="int16",
            blocksize=INPUT_FRAME,
            device=device,
            callback=on_audio,
        ):
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
        print(f"Memory service unreachable ({e!r})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", help="audio input name or index")
    ap.add_argument("--list-devices", action="store_true")
    args = ap.parse_args()

    if args.list_devices:
        print(sd.query_devices())
        return

    device = args.device
    if device is not None and device.isdigit():
        device = int(device)

    asyncio.run(run(device))


if __name__ == "__main__":
    main()
