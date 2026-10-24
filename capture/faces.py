"""Watch the call window: YOLO26 tracks people, InsightFace prints each new face, the memory service names them.

Run: uv run --env-file .env python -m capture.faces --region 0,38,1100,700
The region is the call window as x,y,width,height in screen points (on a Mac: the numbers Cmd+Shift+4 shows).
On a Mac, --app zoom.us (or FaceTime, 'Google Chrome', …) follows that app's window instead, even when you move it;
with neither, it follows the largest window of a known call app (capture/window.py).
Without a live call: --video call.mp4 reads a recording instead; its pixels stand in for screen points.
"""
import argparse
import math
import os
import sys
import time

import cv2
import httpx
import mss
import numpy as np
from ultralytics import YOLO

from capture.embed import faces_in
from capture.window import CALL_APPS, apps_on_screen, call_window

PERSON = 0  # COCO class id YOLO uses for people
FOLLOW_EVERY = 3  # seconds between window position checks (each takes ~0.1 s)


def screen_frames(region: tuple[int, int, int, int], follow: str | None = None):
    """Yield (frame, (x, y, width)) of the region in screen points; with follow (an app name), move with its window."""
    checked = time.time()
    with mss.MSS() as screen:
        while True:
            if follow and time.time() - checked > FOLLOW_EVERY:
                # shortcut: follows the app's largest window, so a bigger second window of the same app (another browser
                # window) takes over; follow kCGWindowNumber instead if that bites
                found, checked = call_window([follow]), time.time()
                region = found[1] if found else region  # minimized or closed: keep the last spot
            x, y, w, h = region
            frame = cv2.cvtColor(np.array(screen.grab({"left": x, "top": y, "width": w, "height": h})), cv2.COLOR_BGRA2BGR)
            yield frame, (x, y, w)


def video_frames(video: cv2.VideoCapture, fps: float):
    skip = max(0, round((video.get(cv2.CAP_PROP_FPS) or fps) / fps) - 1)  # keep the recording at real speed
    while True:
        ok, frame = video.read()
        if not ok:
            return
        yield frame, (0, 0, frame.shape[1])  # video pixels stand in for screen points
        for _ in range(skip):
            video.grab()


def assign(faces: list, boxes: dict[int, list[float]]) -> dict[int, object]:
    """Give each person box (track id -> x1, y1, x2, y2) the face that belongs to it, so overlapping people (a shared room
    camera) can't get a neighbour's face: the face's centre is inside the box and nearest the box's top middle, where a
    head sits. A face goes to one box only."""
    best: dict[int, tuple[float, object]] = {}
    for face in faces:
        fx, fy = (face.bbox[0] + face.bbox[2]) / 2, (face.bbox[1] + face.bbox[3]) / 2
        fits = [
            (math.hypot((fx - (x1 + x2) / 2) / (x2 - x1), (fy - y1) / (y2 - y1)), tid)
            for tid, (x1, y1, x2, y2) in boxes.items() if x1 <= fx <= x2 and y1 <= fy <= y2
        ]
        if fits:
            d, tid = min(fits)
            if tid not in best or d < best[tid][0]:
                best[tid] = (d, face)
    return {tid: face for tid, (_, face) in best.items()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", help="call window as x,y,width,height in screen points")
    ap.add_argument("--app", help="macOS: follow this app's largest window, e.g. zoom.us, FaceTime, 'Google Chrome'")
    ap.add_argument("--video", help="read frames from this video file instead of the screen")
    ap.add_argument("--fps", type=float, default=5)
    args = ap.parse_args()
    if args.video:
        video = cv2.VideoCapture(args.video)
        if not video.isOpened():
            raise SystemExit(f"can't open video {args.video}")
        frames = video_frames(video, args.fps)
    elif args.region:
        frames = screen_frames(tuple(int(v) for v in args.region.split(",")))
    elif sys.platform != "darwin":
        ap.error("pass --region or --video")
    elif found := call_window([args.app] if args.app else CALL_APPS):
        app, region = found  # stick with this app from now on, even if another call app opens a bigger window
        print(f"following the {app} window, now at --region {','.join(map(str, region))}")
        frames = screen_frames(region, follow=app)
    else:
        ap.error(f"no {args.app or 'call app'} window on screen; apps with windows now: {', '.join(apps_on_screen())}")

    model = YOLO("yolo26n.pt")  # downloads on first run
    http = httpx.Client(base_url=os.getenv("MEMORY_URL", "http://localhost:8000"), timeout=10)
    printed: set[int] = set()  # track ids whose face print the memory service already has

    def send(path: str, body: dict) -> dict:
        try:
            return http.post(path, json=body).json()
        except httpx.HTTPError as e:
            print(f"memory service unreachable ({e!r}); is uvicorn running?")
            return {}

    for frame, (x, y, w) in frames:
        started = time.time()
        scale = frame.shape[1] / w  # pixels per screen point (2.0 on Retina)
        result = model.track(frame, persist=True, classes=[PERSON], verbose=False)[0]

        live: set[int] = set()
        if result.boxes is not None and result.boxes.is_track:
            boxes = dict(zip(result.boxes.id.int().tolist(), result.boxes.xyxy.tolist()))
            found = assign(faces_in(frame), boxes) if boxes.keys() - printed else {}  # one InsightFace pass, only when needed
            for tid, (x1, y1, x2, y2) in boxes.items():
                live.add(tid)
                body = {"trackId": tid, "screenBox": [x + x1 / scale, y + y1 / scale, (x2 - x1) / scale, (y2 - y1) / scale]}
                if tid not in printed:
                    if tid not in found:
                        continue  # face not visible yet (turned away); try again next frame
                    body["facePrint"] = found[tid].normed_embedding.tolist()
                    printed.add(tid)
                if send("/faces", body).get("needPrint"):
                    printed.discard(tid)

        for tid in printed - live:
            send("/faces/gone", {"trackId": tid})
            printed.discard(tid)
        time.sleep(max(0.0, 1 / args.fps - (time.time() - started)))

    for tid in printed:  # the video ended; clear its cards
        send("/faces/gone", {"trackId": tid})


if __name__ == "__main__":
    main()
