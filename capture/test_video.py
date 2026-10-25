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
        self.reply = lambda path, body: {}  # tests can answer like memory would


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.posts.append((self.path, body))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.server.reply(self.path, body)).encode())

    def log_message(self, *args):
        pass


def live(image: np.ndarray, n: int, sigma: float = 1.0) -> list[np.ndarray]:
    """n frames of an image as a camera would deliver them: a little sensor noise, so they read as live video, not a picture."""
    rng = np.random.default_rng(0)
    return [np.clip(image + rng.normal(0, sigma, image.shape), 0, 255).astype(np.uint8) for _ in range(n)]


def run_video(tmp_path, monkeypatch, frames: list[np.ndarray], reply=None) -> list:
    path = str(tmp_path / "call.avi")
    # FFV1 is lossless and deterministic; MJPG's first frames of an identical sequence come out slightly different
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"FFV1"), 30, frames[0].shape[1::-1])
    for frame in frames:
        out.write(frame)
    out.release()
    server = FakeMemory()
    if reply:
        server.reply = reply
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
    posts = run_video(tmp_path, monkeypatch, live(t1, 8) + [np.zeros_like(t1)] * 4)
    # the first frame (nobody proven live yet) and the four blank ones
    assert capsys.readouterr().out.count("following the region, no person seen for") == 5
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
    camera = iter(live(t1, 40))
    monkeypatch.setattr(faces, "grab", lambda window_id: next(camera))  # the window's own pixels, whatever is in front of it
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
    frozen = kinds(run_video(tmp_path, monkeypatch, [t1] * 6))  # the same frame over and over: pictures, never people
    assert [k for k in frozen if k != "/window"] == []  # no print, no card, nothing to clear
    moving = kinds(run_video(tmp_path, monkeypatch, live(t1, 6, sigma=2)))
    assert moving.count("print") == 6 and moving.count("/faces") > 6  # cards stay and keep moving...
    assert moving.index("/faces/gone") > max(i for i, k in enumerate(moving) if k in ("/faces", "print"))  # ...until the video ends


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
    a, b, c = live(get_image("t1"), 3)
    posts = run_video(tmp_path, monkeypatch, [a, a, b, b, c])  # a grab repeated: the same bytes, YOLO would say the same
    assert len(widths) == 3  # frames 2 and 4 reused the boxes of 1 and 3
    # people are proven live at frame 3 (first change) and printed then; cards posted on frames 3, 4, 5
    assert sum("facePrint" in b for p, b in posts if p == "/faces") == 6 and sum(p == "/faces" for p, _ in posts) == 18
    lines = [l for l in capsys.readouterr().out.splitlines() if l.startswith("capture: ")]
    assert len(lines) == 5 and all(re.fullmatch(r"capture: [\d.]+ fps, YOLO \d+ ms, InsightFace \d+ ms, cpu \d+%", l) for l in lines)


def test_your_own_tile_is_told_gone_once_and_then_left_alone(tmp_path, monkeypatch, capsys):
    me = []

    def reply(path, body):  # memory recognizes the first face printed as the user themself
        if path == "/faces" and "facePrint" in body and not me:
            me.append(body["trackId"])
            return {"person": {"id": "p_me", "name": "Cesar", "role": "Me!"}}
        return {}

    posts = run_video(tmp_path, monkeypatch, live(get_image("t1"), 5), reply=reply)
    about_me = [(p, b) for p, b in posts if b.get("trackId") == me[0]]
    assert [p for p, _ in about_me] == ["/faces", "/faces/gone"]  # the print, gone once, nothing more
    others = [b["trackId"] for p, b in posts if p == "/faces" and b["trackId"] != me[0]]
    assert len(set(others)) == 5 and len(others) > 5  # the other five kept their cards and kept moving
    assert capsys.readouterr().out.count("that's you, skipping") == 1


def test_an_error_in_one_frame_is_logged_and_the_loop_goes_on(tmp_path, monkeypatch, capsys):
    calls = []
    real = faces.YOLO

    class Flaky:
        def __init__(self, weights):
            self.model = real(weights)

        def track(self, img, **kw):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("CUDA fell over")
            return self.model.track(img, **kw)

        def __call__(self, *a, **kw):
            return self.model(*a, **kw)

    monkeypatch.setattr(faces, "YOLO", Flaky)
    posts = run_video(tmp_path, monkeypatch, live(get_image("t1"), 4, sigma=2))  # all different: YOLO runs on each
    assert len(calls) == 4 and sum(p == "/faces" for p, _ in posts) >= 2 * 6  # frames 3 and 4 posted; frame 2 was skipped
    out = capsys.readouterr().out
    assert out.count("skipped a frame after an error") == 1 and "CUDA fell over" in out


def test_a_face_that_just_left_comes_back_as_the_same_person():
    rng = np.random.default_rng(0)
    unit = lambda v: (v / np.linalg.norm(v)).astype(np.float32)
    maya, jordan = unit(rng.normal(size=512)), unit(rng.normal(size=512))
    recent = faces.Recent()
    recent.add(maya.tolist(), {"id": "p_maya", "name": "Maya Chen"}, now=0.0)
    again = unit(maya + rng.normal(0, 0.01, 512))  # the same face, printed from a new frame
    assert recent.find(again, now=5.0)["id"] == "p_maya"
    assert recent.find(jordan, now=5.0) is None  # someone else
    assert recent.find(again, now=31.0) is None  # too long ago


def call_clip(n: int = 40) -> tuple[list[np.ndarray], np.ndarray]:
    """A synthetic call: InsightFace's six-person photo panned and slightly zoomed (reads as live video), and beside it one
    of those people frozen (a profile picture). Returns the frames and the frozen tile's region as x1, y1, x2, y2."""
    t1 = get_image("t1")
    h, w = t1.shape[:2]
    frozen = t1[219:648, 337:735]  # the person in the middle
    frames = []
    for i in range(n):
        zoom = 1.04 + 0.05 * i / n
        big = cv2.resize(t1, None, fx=zoom, fy=zoom)
        x, y = i, i // 2  # pan a pixel a frame
        canvas = np.zeros((h, w + frozen.shape[1], 3), np.uint8)
        canvas[:, :w] = big[y:y + h, x:x + w]
        canvas[:frozen.shape[0], w:] = frozen
        frames.append(canvas)
    return frames, np.array([w, 0, w + frozen.shape[1], frozen.shape[0]])


def test_a_synthetic_call_gets_one_print_per_moving_face_none_for_the_profile_picture(tmp_path, monkeypatch, capsys):
    import time

    monkeypatch.setenv("HELLO_DEBUG", "1")
    frames, tile = call_clip()
    started = time.perf_counter()
    posts = run_video(tmp_path, monkeypatch, frames)
    seconds = time.perf_counter() - started
    seen = [b for p, b in posts if p == "/faces"]
    printed = [b for b in seen if "facePrint" in b]
    assert len(printed) == 6 and len({b["trackId"] for b in printed}) == 6  # one print per moving face
    assert {b["trackId"] for b in seen} == {b["trackId"] for b in printed}  # nothing at all for the frozen tile...
    out = capsys.readouterr().out
    assert out.count("on screen, looking for a face") >= 7  # ...although YOLO tracked it as a person
    assert not any(tile[0] <= b["screenBox"][0] for b in seen)  # no card ever sat over the frozen tile
    kinds = [p for p, _ in posts]
    assert kinds[-6:] == ["/faces/gone"] * 6 and kinds.index("/faces/gone") > max(i for i, k in enumerate(kinds) if k == "/faces")
    assert all(set(b["debug"]) == {"personBox", "faceBox", "fps"} for b in seen)  # HELLO_DEBUG=1 adds the debug field
    print(f"synthetic call: {len(frames)} frames in {seconds:.1f} s")


def test_pause_from_the_pill_clears_the_cards_and_resume_brings_them_back(monkeypatch, capsys):
    t1 = get_image("t1")
    h, w = t1.shape[:2]
    checks = iter([True] * 11)
    pill = []  # the listening state main hands to listen(); the test flips it like the pill would

    def call_window(apps):
        try:
            return Window("zoom.us", (0, 0, w, h), 7, None) if next(checks) else None
        except StopIteration:
            raise Stop from None

    camera, grabs = iter(live(t1, 11)), []

    def grab(window_id):  # one grab per frame, so the pause lands on exact frames: paused for frames 5-7
        grabs.append(1)
        if len(grabs) in (5, 8):
            pill[0]["on"] = len(grabs) == 8
        return next(camera)

    class Screen:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

    server = FakeMemory()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("MEMORY_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setattr("sys.argv", ["faces", "--app", "zoom.us", "--fps", "30"])
    monkeypatch.setattr(faces.sys, "platform", "darwin")
    monkeypatch.setattr(faces.mss, "MSS", Screen)
    monkeypatch.setattr(faces, "FOLLOW_EVERY", -1)
    monkeypatch.setattr(faces, "call_window", call_window)
    monkeypatch.setattr(faces, "grab", grab)
    monkeypatch.setattr(faces, "listen", lambda url, captions, listening: pill.append(listening))
    try:
        with pytest.raises(Stop):
            faces.main()
    finally:
        server.shutdown()
    kinds = [path if "facePrint" not in body else "print" for path, body in server.posts]
    assert [k for k in kinds if k in ("print", "/faces/gone")] == ["print"] * 6 + ["/faces/gone"] * 6 + ["print"] * 6
    gone, back = kinds.index("/faces/gone"), len(kinds) - 1 - kinds[::-1].index("print")
    assert "/faces" not in kinds[gone:back]  # nothing posted while paused
    out = capsys.readouterr().out
    assert out.count("paused from the pill") == 1 and out.count("resumed: looking for faces again") == 1
