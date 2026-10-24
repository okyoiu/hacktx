import cv2
import numpy as np

from capture.faces import video_frames
from capture.window import pick


def test_video_frames_skips_to_keep_real_speed(tmp_path):
    path = str(tmp_path / "call.avi")
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 30, (64, 48))
    for i in range(30):
        out.write(np.full((48, 64, 3), i * 8, np.uint8))
    out.release()
    frames = list(video_frames(cv2.VideoCapture(path), fps=5))
    assert len(frames) == 5  # one second of 30 fps video sampled at 5 fps
    assert frames[0].shape == (48, 64, 3)


def window(owner, x, y, w, h, layer=0):
    return {"kCGWindowOwnerName": owner, "kCGWindowLayer": layer, "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h}}


def test_pick_takes_the_big_call_window():
    windows = [
        window("Finder", 0, 0, 3000, 2000),
        window("zoom.us", 900, 40, 200, 60),  # meeting toolbar
        window("zoom.us", 0, 0, 3000, 2000, layer=3),  # floating overlay layer
        window("zoom.us", 10, 38.5, 1100, 700),
    ]
    assert pick(windows) == (10, 38, 1100, 700)
    assert pick([window("Microsoft Teams", 5, 30, 1200, 800)]) == (5, 30, 1200, 800)


def test_pick_finds_nothing_without_a_call_app():
    assert pick([window("Finder", 0, 0, 800, 600), window("Electron", 0, 0, 3000, 2000)]) is None
    assert pick([]) is None
