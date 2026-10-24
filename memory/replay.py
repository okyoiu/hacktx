"""Run the real pipeline without a camera or mic: seeds two demo people, fakes their faces, replays transcript lines.

Run (with uvicorn and the overlay running): uv run --env-file .env python -m memory.replay
"""
import json
import os
import time
from pathlib import Path

import httpx
import numpy as np

from memory import store

MOCKS = Path(__file__).resolve().parent.parent / "shared" / "mocks"
DEMO = {"Jordan Lee": (1, [180, 260, 200, 260]), "Maya Chen": (2, [620, 270, 190, 250])}  # name -> (seed, screenBox)


def fake_print(seed: int, noise: float = 0.0) -> np.ndarray:
    """A fixed unit-length 'face print' per seed; noise makes it look like a fresh camera frame."""
    v = np.random.default_rng(seed).normal(size=512)
    if noise:
        v += np.random.default_rng().normal(scale=noise, size=512)
    return (v / np.linalg.norm(v)).astype(np.float32)


def main() -> None:
    http = httpx.Client(base_url=os.getenv("MEMORY_URL", "http://localhost:8000"), timeout=60)
    for name, (seed, _) in DEMO.items():
        if store.match(fake_print(seed)) is None:
            store.enroll(name, fake_print(seed), b"")
    for i, (name, (seed, box)) in enumerate(DEMO.items()):
        http.post("/faces", json={"trackId": 900 + i, "screenBox": box, "facePrint": fake_print(seed, 0.02).tolist()})
        http.post("/speakers", json={"label": f"speaker_{i}", "name": name})
    http.post("/speakers", json={"label": f"speaker_{len(DEMO)}", "name": "You"})

    for raw in (MOCKS / "transcript.jsonl").read_text().splitlines():
        line = json.loads(raw)
        time.sleep(line.pop("delayMs") / 1000)
        http.post("/transcript", json=line)
    print("Replay sent. Top picks arrive on the overlay as Muse Spark answers.")


if __name__ == "__main__":
    main()
