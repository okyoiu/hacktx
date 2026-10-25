"""`faces --video` end to end on InsightFace's sample photo and a fake memory server (real YOLO and InsightFace)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import cv2
import numpy as np
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


def test_video_posts_each_face_once_with_a_print_then_face_gone(tmp_path, monkeypatch):
    t1 = get_image("t1")  # six people around a table
    posts = run_video(tmp_path, monkeypatch, [t1] * 8 + [np.zeros_like(t1)] * 4)
    seen = [body for path, body in posts if path == "/faces"]
    printed = [b for b in seen if "facePrint" in b]
    tracks = {b["trackId"] for b in printed}
    assert len(tracks) == 6 and len(printed) == 6  # a print only for a new track
    assert all(len(b["facePrint"]) == 512 and len(b["screenBox"]) == 4 for b in printed)
    assert {b["trackId"] for path, b in posts if path == "/faces/gone"} == tracks
    kinds = [path for path, _ in posts]
    assert kinds.index("/faces/gone") > max(i for i, k in enumerate(kinds) if k == "/faces")  # gone only after the last face
