import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
from insightface.data import get_image

from capture import faces
from capture.embed import add_print, faces_in, find_faces
from capture.faces import assign, video_frames
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


def test_pick_takes_the_frontmost_big_window_of_the_apps_asked_for():
    windows = [  # macOS lists windows front to back
        window("Finder", 0, 0, 3000, 2000),
        window("zoom.us", 900, 40, 200, 60),  # meeting toolbar
        window("Google Chrome", 0, 0, 1400, 900),
        window("zoom.us", 10, 38.5, 1100, 700),
    ]
    assert pick(windows, ["zoom.us"]) == ("zoom.us", (10, 38, 1100, 700))
    assert pick(windows, ["ZOOM"]) == ("zoom.us", (10, 38, 1100, 700))
    assert pick(windows, CALL_APPS) == ("Google Chrome", (0, 0, 1400, 900))  # Chrome is in front of Zoom
    assert pick(windows[:2], ["zoom.us"]) == ("zoom.us", (900, 40, 200, 60))  # only a toolbar: better than nothing
    assert pick([window("Microsoft Teams classic", 5, 30, 1200, 800)], CALL_APPS)[0] == "Microsoft Teams classic"


def test_pick_finds_nothing_without_a_call_app():
    assert pick([window("Archive Utility", 0, 0, 800, 600), window("Electron", 0, 0, 3000, 2000)], CALL_APPS) is None
    assert pick([], CALL_APPS) is None


class FakeScreen:  # stands in for mss.MSS, which needs a display
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def grab(self, box):
        return np.zeros((box["height"], box["width"], 4), np.uint8)


def test_screen_frames_follows_the_window_and_yields_nothing_while_it_is_gone(monkeypatch):
    monkeypatch.setattr(faces.mss, "MSS", FakeScreen)
    spots = iter([("zoom.us", (50, 60, 30, 20)), None, ("zoom.us", (5, 6, 30, 20))])  # moved, closed, back
    monkeypatch.setattr(faces, "FOLLOW_EVERY", -1)
    monkeypatch.setattr(faces, "call_window", lambda apps: next(spots))
    frames = faces.screen_frames((0, 0, 30, 20), follow=["zoom.us"])
    assert next(frames)[1] == (50, 60, 30)
    assert next(frames)[0] is None
    assert next(frames)[1] == (5, 6, 30)


def test_assign_gives_overlapping_people_their_own_face():
    t1 = get_image("t1")  # InsightFace's group photo: six people around a table, close together
    found = sorted(faces_in(t1), key=lambda f: f.bbox[0])
    boxes = dict(enumerate([  # yolo26n person boxes for t1, left to right
        [0, 231, 310, 879], [258, 103, 473, 665], [337, 219, 735, 648],
        [586, 291, 936, 639], [872, 1, 1271, 662], [992, 233, 1280, 714],
    ]))
    x1, y1, x2, y2 = boxes[4]  # the man standing at the back right: the woman in front of him is inside his box too
    fx, fy = (found[5].bbox[0] + found[5].bbox[2]) / 2, (found[5].bbox[1] + found[5].bbox[3]) / 2
    assert len(found) == 6 and x1 <= fx <= x2 and y1 <= fy <= y2
    index = {id(f): i for i, f in enumerate(found)}
    assert {tid: index[id(face)] for tid, face in assign(found, boxes).items()} == {i: i for i in range(6)}


def test_assign_ignores_a_bigger_neighbours_face_in_your_box():
    # the old per-crop embed() took the biggest face in the crop, which here is the neighbour's
    me, neighbour = SimpleNamespace(bbox=[90, 10, 110, 30]), SimpleNamespace(bbox=[150, 40, 200, 90])
    got = assign([me, neighbour], {1: [50, 0, 200, 300], 2: [120, 30, 260, 400]})
    assert got[1] is me and got[2] is neighbour


def test_embed_image_refuses_a_huge_image_instead_of_decoding_it():
    # a fresh process, because OpenCV reads its pixel cap when it loads
    code = ("import cv2, numpy as np; from capture.embed import embed_image\n"
            "png = cv2.imencode('.png', np.zeros((7000, 7000), np.uint8))[1].tobytes()  # 49 MP, a few KB\n"
            "print(embed_image(png))")
    root = Path(__file__).resolve().parent.parent
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "None", out.stderr


def test_screen_frames_started_before_any_call_waits_quietly_then_follows(monkeypatch, capsys):
    monkeypatch.setattr(faces.mss, "MSS", FakeScreen)
    monkeypatch.setattr(faces, "FOLLOW_EVERY", -1)
    seen = []

    def lookup(apps):
        seen.append(list(apps))
        look = next(looks)
        if look == "unreadable":
            raise SystemExit("couldn't list windows: no permission")
        return look

    looks = iter([None, None, "unreadable", ("Google Chrome", (1, 2, 30, 20)), ("zoom.us", (5, 6, 30, 20)), None])
    monkeypatch.setattr(faces, "call_window", lookup)
    frames = faces.screen_frames(None, follow=["zoom.us", "Google Chrome"])
    got = [next(frames) for _ in range(6)]
    assert [f is None for f, _ in got] == [True, True, True, False, False, True]
    assert all(apps == ["zoom.us", "Google Chrome"] for apps in seen)  # always every call app: the frontmost one wins
    assert capsys.readouterr().out.splitlines() == [  # one line per change, not per frame
        "waiting for a call window", "couldn't list windows: no permission", "following the Google Chrome window",
        "following the zoom.us window", "waiting for a call window"]


def test_a_print_is_only_computed_for_the_face_that_asks_for_one():
    found = find_faces(get_image("t1"))
    assert len(found) == 6 and all(not hasattr(f, "embedding") or f.embedding is None for f in found)
    add_print(get_image("t1"), found[0])
    assert abs(np.linalg.norm(found[0].normed_embedding) - 1) < 1e-3 and found[1].embedding is None
