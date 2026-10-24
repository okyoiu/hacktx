"""Watch the call window: YOLO26 tracks people, InsightFace prints each new face, the memory service names them.

Run: uv run --env-file .env python -m capture.faces --region 0,38,1100,700
The region is the call window as x,y,width,height in screen points (on a Mac: the numbers Cmd+Shift+4 shows).
"""
import argparse
import os
import time

import cv2
import httpx
import mss
import numpy as np
from ultralytics import YOLO

from capture.embed import embed

PERSON = 0  # COCO class id YOLO uses for people


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", required=True, help="call window as x,y,width,height in screen points")
    ap.add_argument("--fps", type=float, default=5)
    args = ap.parse_args()
    x, y, w, h = (int(v) for v in args.region.split(","))
    region = {"left": x, "top": y, "width": w, "height": h}

    model = YOLO("yolo26n.pt")  # downloads on first run
    http = httpx.Client(base_url=os.getenv("MEMORY_URL", "http://localhost:8000"), timeout=10)
    printed: set[int] = set()  # track ids whose face print the memory service already has

    def send(path: str, body: dict) -> dict:
        try:
            return http.post(path, json=body).json()
        except httpx.HTTPError as e:
            print(f"memory service unreachable ({e!r}); is uvicorn running?")
            return {}

    with mss.MSS() as screen:
        while True:
            started = time.time()
            frame = cv2.cvtColor(np.array(screen.grab(region)), cv2.COLOR_BGRA2BGR)
            scale = frame.shape[1] / w  # pixels per screen point (2.0 on Retina)
            result = model.track(frame, persist=True, classes=[PERSON], verbose=False)[0]

            live: set[int] = set()
            if result.boxes is not None and result.boxes.is_track:
                for (x1, y1, x2, y2), tid in zip(result.boxes.xyxy.tolist(), result.boxes.id.int().tolist()):
                    live.add(tid)
                    body = {"trackId": tid, "screenBox": [x + x1 / scale, y + y1 / scale, (x2 - x1) / scale, (y2 - y1) / scale]}
                    if tid not in printed:
                        face_print = embed(frame[int(y1):int(y2), int(x1):int(x2)])
                        if face_print is None:
                            continue  # face not visible yet (turned away); try again next frame
                        body["facePrint"] = face_print.tolist()
                        printed.add(tid)
                    if send("/faces", body).get("needPrint"):
                        printed.discard(tid)

            for tid in printed - live:
                send("/faces/gone", {"trackId": tid})
                printed.discard(tid)
            time.sleep(max(0.0, 1 / args.fps - (time.time() - started)))


if __name__ == "__main__":
    main()
