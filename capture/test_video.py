"""`faces --video` end to end on InsightFace's sample photo and a fake memory server (real YOLO and InsightFace)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import numpy as np
import pytest
import pytest
from insightface.data import get_image

from capture import faces
from capture.window import Window


class FakeMemory(HTTPServer):
    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.posts = []


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.posts.append((self.path, body))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *args):
        pass


def run_video(tmp_path, monkeypatch, frames: list[np.ndarray], still_after=1e9) -> list:
    monkeypatch.setattr(faces, "STILL_AFTER", still_after)  # identical test frames would otherwise count as pictures
    path = str(tmp_path / "call.avi")
    # FFV1 is lossless and deterministic; MJPG's first frames of an identical sequence come out slightly different
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"FFV1"), 30, frames[0].shape[1::-1])
    for frame in frames:
        out.write(frame)
    out.release()
    server = FakeMemory()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("MEMORY_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr("sys.argv", ["faces", "--video", path, "--fps", "30"])
    try:
        faces.main()
    finally:
        server.shutdown()
    return server.posts


@pytest.mark.parametrize("debug", [False, True])
def test_video_posts_each_face_once_with_a_print_then_face_gone(tmp_path, monkeypatch, capsys, debug):
    monkeypatch.setenv("HELLO_DEBUG", "1") if debug else monkeypatch.delenv("HELLO_DEBUG", raising=False)
    monkeypatch.setattr(faces, "QUIET_AFTER", 0)  # say so on every frame without a person, instead of every 30 s
    t1 = get_image("t1")  # six people around a table
    posts = run_video(tmp_path, monkeypatch, [t1] * 8 + [np.zeros_like(t1)] * 4)
    assert capsys.readouterr().out.count("following the region, no person seen for 0 s") == 4  # the blank frames
    seen = [body for path, body in posts if path == "/faces"]
    printed = [b for b in seen if "facePrint" in b]
    tracks = {b["trackId"] for b in printed}
    assert len(tracks) == 6 and len(printed) == 6  # a print only for a new track
    assert all(len(b["facePrint"]) == 512 and len(b["screenBox"]) == 4 for b in printed)
    assert {b["trackId"] for path, b in posts if path == "/faces/gone"} == tracks
    if debug:  # developer mode: what the computer vision saw, in screen points, on every /faces
        assert all(set(b["debug"]) == {"personBox", "faceBox", "fps"} for b in seen)
        first = printed[0]["debug"]
        assert first["personBox"] == printed[0]["screenBox"] and len(first["faceBox"]) == 4 and first["fps"] >= 0
        assert any(b["debug"]["fps"] > 0 for b in seen)
    else:
        assert all("debug" not in b for b in seen)
    assert [b for path, b in posts if path == "/window"] == [{"app": None, "rect": [0, 0, t1.shape[1], t1.shape[0]]}]  # once
    kinds = [path for path, _ in posts]
    assert kinds.index("/faces/gone") > max(i for i, k in enumerate(kinds) if k == "/faces")  # gone only after the last face


class Stop(Exception):
    pass


def test_leaving_the_call_clears_the_cards_and_coming_back_brings_them_again(monkeypatch):
    t1 = get_image("t1")
    h, w = t1.shape[:2]
    checks = iter([True] * 5 + [False] * 4 + [True] * 2 + ["moved"] * 2 + ["chrome"] * 2 + ["notes"] * 2)  # one look per frame

    def call_window(apps):
        try:
            return {True: Window("zoom.us", (0, 0, w, h), 7, None), False: None, "moved": Window("zoom.us", (5, 6, w, h), 7, None),
                    "chrome": Window("Google Chrome", (5, 6, w, h), 8, None), "notes": Window("Notes", (5, 6, w, h), 9, None, False)}[next(checks)]
        except StopIteration:
            raise Stop from None

    class Screen:  # stands in for mss.MSS, which needs a display
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def grab(self, box):
            return cv2.cvtColor(t1, cv2.COLOR_BGR2BGRA)

    server = FakeMemory()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("MEMORY_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr("sys.argv", ["faces", "--app", "zoom.us", "--fps", "30"])
    monkeypatch.setattr(faces.sys, "platform", "darwin")
    monkeypatch.setattr(faces.mss, "MSS", Screen)
    monkeypatch.setattr(faces, "FOLLOW_EVERY", -1)
    monkeypatch.setattr(faces, "call_window", call_window)
    monkeypatch.setattr(faces, "grab", lambda window_id: t1)  # the window's own pixels, whatever is in front of it
    monkeypatch.setattr(faces, "STILL_AFTER", 1e9)  # identical test frames would otherwise count as pictures
    try:
        with pytest.raises(Stop):
            faces.main()
    finally:
        server.shutdown()
    kinds = [path if "facePrint" not in body else "print" for path, body in server.posts]  # a print marks a new card
    cards = [k for k in kinds if k in ("print", "/faces/gone")]
    # six cards; cleared when the window is gone; six again; cleared again when the followed window isn't a call
    assert cards == ["print"] * 6 + ["/faces/gone"] * 6 + ["print"] * 6 + ["/faces/gone"] * 6
    assert [(b["app"], b["rect"]) for path, b in server.posts if path == "/window"] == [  # only when the app or rect changes
        ("zoom.us", [0, 0, w, h]), (None, None), ("zoom.us", [0, 0, w, h]), ("zoom.us", [5, 6, w, h]), ("Google Chrome", [5, 6, w, h]),
        ("Notes", [5, 6, w, h])]


def test_pictures_get_no_card_but_live_video_does(tmp_path, monkeypatch):
    t1 = get_image("t1")
    kinds = lambda posts: [p if "facePrint" not in b else "print" for p, b in posts]
    # the same frame over and over, checked every frame: six cards, then all cleared as pictures, and nothing more
    frozen = kinds(run_video(tmp_path, monkeypatch, [t1] * 6, still_after=0))
    assert [k for k in frozen if k != "/window"] == ["print"] * 6 + ["/faces/gone"] * 6
    rng = np.random.default_rng(0)
    camera = [np.clip(t1 + rng.normal(0, 2, t1.shape), 0, 255).astype(np.uint8) for _ in range(6)]  # sensor noise
    live = kinds(run_video(tmp_path, monkeypatch, camera, still_after=0))
    assert live.count("print") == 6 and live.count("/faces") > 6  # cards stay and keep moving...
    assert live.index("/faces/gone") > max(i for i, k in enumerate(live) if k in ("/faces", "print"))  # ...until the video ends


def test_yolo_is_skipped_while_the_grab_is_unchanged_and_the_minute_line_sums_up(tmp_path, monkeypatch, capsys):
    import re

    monkeypatch.setattr(faces, "REPORT_EVERY", 0)  # the once-a-minute line, every frame
    widths = []
    real = faces.YOLO

    class Counting:
        def __init__(self, weights):
            self.model = real(weights)

        def track(self, img, **kw):
            widths.append(img.shape[1])
            return self.model.track(img, **kw)

        def __call__(self, *a, **kw):
            return self.model(*a, **kw)

    monkeypatch.setattr(faces, "YOLO", Counting)
    t1 = get_image("t1")
    posts = run_video(tmp_path, monkeypatch, [t1] * 5)  # the same bytes five times: a still window
    assert len(widths) == 1  # YOLO ran once; the other four frames reused its boxes
    assert sum("facePrint" in b for p, b in posts if p == "/faces") == 6 and sum(p == "/faces" for p, _ in posts) == 30  # cards kept moving
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("capture: ")]
    assert len(lines) == 5 and all(re.fullmatch(r"capture: [\d.]+ fps, YOLO \d+ ms, InsightFace \d+ ms, cpu \d+%", l) for l in lines)
