"""See what the computer vision sees: webcam (or a screen region) with YOLO26 person boxes,
InsightFace face boxes, and who each face matches in the database, live.

Run: uv run --env-file .env python -m tools.cv_check --enroll-as "Your Name"
     uv run --env-file .env python -m tools.cv_check --region 0,38,1100,700   # a call window instead
Keys in the window: e = enroll the biggest face as --enroll-as (only yourself, with your consent), q = quit.
"""
import argparse
import time

import cv2
import mss
import numpy as np
from ultralytics import YOLO

from capture.embed import _model
from memory import store

BLUE, GREEN, AMBER = (255, 170, 70), (110, 220, 120), (60, 190, 255)  # BGR


def label(img, text, x, y, color):
    (w, h), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(img, (x, y - h - 10), (x + w + 10, y), color, -1)
    cv2.putText(img, text, (x + 5, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (20, 20, 20), 2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--region", help="screen region x,y,width,height instead of the webcam")
    ap.add_argument("--camera", type=int, default=0)
    ap.add_argument("--enroll-as", help="name to enroll when you press e")
    args = ap.parse_args()
    if args.region and args.enroll_as:
        ap.error("--enroll-as works with the camera only: enroll yourself, never a face on someone's call")

    yolo, faces = YOLO("yolo26n.pt"), _model()
    if args.region:
        screen = mss.MSS()
        region = dict(zip(("left", "top", "width", "height"), (int(v) for v in args.region.split(","))))
    else:
        cam = cv2.VideoCapture(args.camera)
        if not cam.isOpened():
            raise SystemExit("Can't open the camera. Allow camera access for your terminal app in "
                             "System Settings → Privacy & Security → Camera, then run this again.")
    flash, flash_until, misses = "", 0.0, 0

    while True:
        started = time.time()
        if args.region:
            frame = cv2.cvtColor(np.array(screen.grab(region)), cv2.COLOR_BGRA2BGR)
        else:
            ok, frame = cam.read()
            if not ok:  # macOS cameras go quiet while warming up, behind the permission prompt, or when another app grabs them
                misses += 1
                if misses % 30 == 0:  # quiet for 3 s: reconnect
                    cam.release()
                    cam = cv2.VideoCapture(args.camera)
                if misses > 300:
                    raise SystemExit("The camera sent no frames for 30 seconds. Close other apps using it "
                                     "(FaceTime, Photo Booth, Zoom) and check camera permission for your terminal app.")
                time.sleep(0.1)
                continue
            misses = 0

        people = yolo.track(frame, persist=True, classes=[0], verbose=False)[0]
        if people.boxes is not None and people.boxes.is_track:
            for (x1, y1, x2, y2), tid in zip(people.boxes.xyxy.int().tolist(), people.boxes.id.int().tolist()):
                cv2.rectangle(frame, (x1, y1), (x2, y2), BLUE, 2)
                label(frame, f"YOLO person #{tid}", x1, y2 + 24, BLUE)

        found = faces.get(frame)
        for f in found:
            x1, y1, x2, y2 = f.bbox.astype(int)
            who = store.match(f.normed_embedding)
            color, text = (GREEN, f"{who['name']}  {who['score']:.2f}") if who else (AMBER, "not enrolled")
            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
            label(frame, text, x1, y1, color)

        fps = 1 / max(1e-6, time.time() - started)
        label(frame, f"{fps:.1f} fps  ·  {len(found)} face(s)  ·  e enroll  ·  q quit", 10, 34, (230, 230, 230))
        if time.time() < flash_until:
            label(frame, flash, 10, 70, GREEN)
        cv2.imshow("Hello Again - computer vision check", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("e"):
            if not args.enroll_as:
                flash = "Start with --enroll-as \"Your Name\" to enroll"
            elif not found:
                flash = "No face to enroll"
            else:
                f = max(found, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
                x1, y1, x2, y2 = np.clip(f.bbox.astype(int), 0, None)
                _, jpg = cv2.imencode(".jpg", frame[y1:y2, x1:x2])
                pid, _ = store.enroll(args.enroll_as, f.normed_embedding, jpg.tobytes())
                flash = f"Enrolled {args.enroll_as} ({pid})"
            flash_until = time.time() + 3
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
