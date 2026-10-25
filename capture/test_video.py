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


def run_video(tmp_path, monkeypatch, frames: list[np.ndarray]) -> list:
    path = str(tmp_path / "call.avi")
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 30, frames[0].shape[1::-1])
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
def test_video_posts_each_face_once_with_a_print_then_face_gone(tmp_path, monkeypatch, debug):
    monkeypatch.setenv("HELLO_DEBUG", "1") if debug else monkeypatch.delenv("HELLO_DEBUG", raising=False)
    t1 = get_image("t1")  # six people around a table
    posts = run_video(tmp_path, monkeypatch, [t1] * 8 + [np.zeros_like(t1)] * 4)
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
    checks = iter([True] * 5 + [False] * 4 + [True] * 2 + ["moved"] * 2 + ["chrome"] * 2)  # one look per frame: there, gone, back

    def call_window(apps):
        try:
            return {True: ("zoom.us", (0, 0, w, h)), False: None, "moved": ("zoom.us", (5, 6, w, h)),
                    "chrome": ("Google Chrome", (5, 6, w, h))}[next(checks)]
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
    try:
        with pytest.raises(Stop):
            faces.main()
    finally:
        server.shutdown()
    kinds = [path if "facePrint" not in body else "print" for path, body in server.posts]  # a print marks a new card
    first_gone, last_gone = kinds.index("/faces/gone"), len(kinds) - 1 - kinds[::-1].index("/faces/gone")
    assert kinds[:first_gone].count("print") == 6 and kinds[last_gone + 1:].count("print") == 6  # six cards, cleared, six again
    assert kinds.count("/faces/gone") == 6
    assert [(b["app"], b["rect"]) for path, b in server.posts if path == "/window"] == [  # only when the app or rect changes
        ("zoom.us", [0, 0, w, h]), (None, None), ("zoom.us", [0, 0, w, h]), ("zoom.us", [5, 6, w, h]), ("Google Chrome", [5, 6, w, h])]
