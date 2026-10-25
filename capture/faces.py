"""Watch the call window: YOLO26 tracks people, InsightFace prints each new face, the memory service names them.

Run: uv run --env-file .env python -m capture.faces --region 0,38,1100,700
The region is the call window as x,y,width,height in screen points (on a Mac: the numbers Cmd+Shift+4 shows).
On a Mac, --app zoom.us (or FaceTime, 'Google Chrome', …) follows that app's window instead, even when you move it;
with neither, it follows the largest window of a known call app (capture/window.py), waiting quietly until one appears.
Without a live call: --video call.mp4 reads a recording instead; its pixels stand in for screen points.
It also names Muse's voices from whose lips move (capture/speakers.py) and tells memory with POST /speakers.
Nothing here shows frames or boxes to anyone; tools/cv_check.py is the debug view.
"""
import argparse
import math
import os
import sys
import threading
import time
from collections import deque

import cv2
import httpx
import mss
import numpy as np
from ultralytics import YOLO

from capture.embed import add_print, find_faces, mouths_in, warm_up
from capture.speakers import Namer, listen
from capture.window import CALL_APPS, call_window

PERSON = 0  # COCO class id YOLO uses for people
FOLLOW_EVERY = 3  # seconds between window position checks (each takes ~0.1 s)
RETRY = 3.0  # seconds before another InsightFace pass for a person whose face wasn't visible last time


def screen_frames(region: tuple[int, int, int, int] | None, follow: list[str] | None = None):
    """Yield (frame, (x, y, width)) of the region in screen points; with follow (app names), move with that app's window.
    While there is no such window (not started yet, or the user left the call) it yields (None, ...) instead and keeps
    looking, logging one line when that changes."""
    checked = time.time() if region else 0  # no region yet: look right away
    apps, shown = follow, None
    with mss.MSS() as screen:
        while True:
            if follow and time.time() - checked > FOLLOW_EVERY:
                # shortcut: follows the app's largest window, so a bigger second window of the same app (another browser
                # window) takes over; follow kCGWindowNumber instead if that bites
                why = "waiting for a call window"
                try:
                    found = call_window(apps)
                except SystemExit as e:  # the window list isn't readable (no osascript, no permission): keep waiting
                    found, why = None, str(e)
                checked = time.time()
                region, apps = (found[1], [found[0]]) if found else (None, follow)  # stick with the app we found
                state = f"following the {found[0]} window" if found else why
                if state != shown:
                    print(state)
                    shown = state
            if region is None:
                yield None, (0, 0, 1)
                continue
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
    else:  # also how the overlay app starts us, before any call: wait for a call window to appear
        frames = screen_frames(None, follow=[args.app] if args.app else list(CALL_APPS))

    model = YOLO("yolo26n.pt")  # downloads on first run
    warm_up()
    model(np.zeros((64, 64, 3), np.uint8), verbose=False)
    memory_url = os.getenv("MEMORY_URL", "http://localhost:8000")
    http = httpx.Client(base_url=memory_url, timeout=10)
    printed: set[int] = set()  # track ids whose face print the memory service already has
    people: dict[int, dict] = {}  # track id -> the recognized person memory replied with
    tried: dict[int, float] = {}  # track id -> when InsightFace last looked for its face
    namer, captions = Namer(), deque()
    threading.Thread(target=listen, args=(memory_url.replace("http", "ws", 1) + "/ws", captions), daemon=True).start()

    def send(path: str, body: dict) -> dict:
        try:
            return http.post(path, json=body).json()
        except httpx.HTTPError as e:
            print(f"memory service unreachable ({e!r}); is uvicorn running?")
            return {}

    for frame, (x, y, w) in frames:
        started = time.time()
        scale = frame.shape[1] / w if frame is not None else 1  # pixels per screen point (2.0 on Retina)
        result = model.track(frame, persist=True, classes=[PERSON], verbose=False)[0] if frame is not None else None

        live: set[int] = set()  # empty while the call window is gone, so every card clears
        if result is not None and result.boxes is not None and result.boxes.is_track:
            boxes = dict(zip(result.boxes.id.int().tolist(), result.boxes.xyxy.tolist()))
            now = time.monotonic()
            wanting = {t for t in boxes.keys() - printed if now - tried.get(t, -RETRY) >= RETRY}
            if wanting:
                found = assign(find_faces(frame), boxes)  # one InsightFace pass gives every face's lips
                for tid in wanting & found.keys():
                    add_print(frame, found[tid])  # prints only for people who need one
                tried.update(dict.fromkeys(wanting, now))
            elif namer.wants_lips([p["id"] for p in people.values()], now):
                found = assign(mouths_in(frame), boxes)
            else:
                found = {}
            for tid, face in found.items():
                if tid in people:
                    namer.saw(people[tid], face, now)
            for tid, (x1, y1, x2, y2) in boxes.items():
                live.add(tid)
                body = {"trackId": tid, "screenBox": [x + x1 / scale, y + y1 / scale, (x2 - x1) / scale, (y2 - y1) / scale]}
                if tid not in printed:
                    if tid not in wanting or tid not in found:
                        continue  # face not visible yet (turned away); looked again after RETRY
                    body["facePrint"] = found[tid].normed_embedding.tolist()
                    printed.add(tid)
                reply = send("/faces", body)
                if reply.get("needPrint"):
                    printed.discard(tid)
                if reply.get("person"):
                    people[tid] = reply["person"]
                    namer.met(reply["person"])

        tried = {t: v for t, v in tried.items() if t in live}
        for tid in printed - live:
            send("/faces/gone", {"trackId": tid})
            printed.discard(tid)
            people.pop(tid, None)
        while captions:
            if named := namer.caption(*captions.popleft()):
                send("/speakers", {"label": named[0], "name": named[1]})
                print(f"Muse speaker {named[0]} is {named[1]}")
        time.sleep(max(0.0, 1 / args.fps - (time.time() - started)))

    for tid in printed:  # the video ended; clear its cards
        send("/faces/gone", {"trackId": tid})


if __name__ == "__main__":
    main()
