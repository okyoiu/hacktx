import cv2
import numpy as np

from capture import faces
from capture.faces import video_frames
from capture.window import CALL_APPS, pick


def test_video_frames_skips_to_keep_real_speed(tmp_path):
    path = str(tmp_path / "call.avi")
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 30, (64, 48))
    for i in range(30):
        out.write(np.full((48, 64, 3), i * 8, np.uint8))
    out.release()
    frames = list(video_frames(cv2.VideoCapture(path), fps=5))
    assert len(frames) == 5  # one second of 30 fps video sampled at 5 fps
    frame, origin = frames[0]
    assert frame.shape == (48, 64, 3) and origin == (0, 0, 64)


def window(owner, x, y, w, h):
    return {"kCGWindowOwnerName": owner, "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h}}


def test_pick_takes_the_biggest_window_of_the_apps_asked_for():
    windows = [
        window("Finder", 0, 0, 3000, 2000),
        window("zoom.us", 900, 40, 200, 60),  # meeting toolbar
        window("zoom.us", 10, 38.5, 1100, 700),
        window("Google Chrome", 0, 0, 1400, 900),
    ]
    assert pick(windows, ["zoom.us"]) == ("zoom.us", (10, 38, 1100, 700))
    assert pick(windows, ["ZOOM"]) == ("zoom.us", (10, 38, 1100, 700))
    assert pick(windows, CALL_APPS) == ("Google Chrome", (0, 0, 1400, 900))
    assert pick([window("Microsoft Teams classic", 5, 30, 1200, 800)], CALL_APPS)[0] == "Microsoft Teams classic"


def test_pick_finds_nothing_without_a_call_app():
    assert pick([window("Archive Utility", 0, 0, 800, 600), window("Electron", 0, 0, 3000, 2000)], CALL_APPS) is None
    assert pick([], CALL_APPS) is None


def test_screen_frames_follows_the_window_and_keeps_its_last_spot(monkeypatch):
    spots = iter([("zoom.us", (50, 60, 30, 20)), None])  # moved, then closed
    monkeypatch.setattr(faces, "FOLLOW_EVERY", -1)
    monkeypatch.setattr(faces, "call_window", lambda apps: next(spots))
    frames = faces.screen_frames((0, 0, 30, 20), follow="zoom.us")
    assert next(frames)[1] == (50, 60, 30)
    assert next(frames)[1] == (50, 60, 30)
