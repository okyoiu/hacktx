import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
cv2 = pytest.importorskip("cv2", reason="Install capture dependencies to run image tests")
import numpy as np
import pytest
def get_image(name):
    return pytest.importorskip("insightface.data", reason="Requires face model dependencies").get_image(name)

from capture import faces
from capture.embed import add_print, faces_in, find_faces
from capture.faces import assign, video_frames
from capture import window as win
from capture.window import CALL_APPS, NO_PERMISSION, NoScreenRecording, Window, can_record, has_call, pick


def test_video_frames_skips_to_keep_real_speed(tmp_path):
    path = str(tmp_path / "call.avi")
    out = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 30, (64, 48))
    for i in range(30):
        out.write(np.full((48, 64, 3), i * 8, np.uint8))
    out.release()
    frames = list(video_frames(cv2.VideoCapture(path), fps=5))
    assert len(frames) == 5  # one second of 30 fps video sampled at 5 fps
    frame, origin = frames[0]
    assert frame.shape == (48, 64, 3) and origin == (0, 0, 64, None, True)


def window(owner, x, y, w, h, n=1):
    return {"kCGWindowOwnerName": owner, "kCGWindowNumber": n, "kCGWindowBounds": {"X": x, "Y": y, "Width": w, "Height": h}}


def test_pick_takes_the_frontmost_big_window_of_the_apps_asked_for():
    windows = [  # macOS lists windows front to back
        window("Finder", 0, 0, 3000, 2000, 1),
        window("zoom.us", 900, 40, 200, 60, 2),  # meeting toolbar
        window("Google Chrome", 0, 0, 1400, 900, 3),
        window("zoom.us", 10, 38.5, 1100, 700, 4),
    ]
    assert pick(windows, ["zoom.us"]) == Window("zoom.us", (10, 38, 1100, 700), 4, "Finder")  # Finder's window covers it
    assert pick(windows, ["ZOOM"]) == Window("zoom.us", (10, 38, 1100, 700), 4, "Finder")
    assert pick(windows, CALL_APPS) == Window("Google Chrome", (0, 0, 1400, 900), 3, "Finder", False)  # in front of Zoom; no call tab
    assert pick(windows[:2], ["zoom.us"]) == Window("zoom.us", (900, 40, 200, 60), 2, "Finder")  # only a toolbar: better than nothing
    assert pick([window("Microsoft Teams classic", 5, 30, 1200, 800)], CALL_APPS).app == "Microsoft Teams classic"
    assert pick([window("Zoom", 5, 30, 1200, 800)], CALL_APPS).app == "Zoom"  # how newer Zoom versions are named


def test_pick_says_which_other_app_covers_the_window():
    zoom, toolbar = window("Zoom", 10, 38, 1100, 700, 4), window("Zoom", 900, 40, 200, 60, 2)
    assert pick([zoom, window("Terminal", 0, 0, 800, 600)], ["Zoom"]).behind is None  # Zoom is in front
    assert pick([window("Terminal", 2000, 0, 800, 600), zoom], ["Zoom"]).behind is None  # in front but beside it
    assert pick([toolbar, zoom], ["Zoom"]).behind is None  # Zoom's own toolbar doesn't count
    assert pick([window("Electron", 0, 0, 3000, 2000), zoom], ["Zoom"]).behind is None  # nor Hello Again's overlay
    assert pick([window("Terminal", 0, 0, 800, 600), zoom], ["Zoom"]).behind == "Terminal"
    nameless = {"kCGWindowNumber": 1, "kCGWindowBounds": {"X": 0, "Y": 0, "Width": 800, "Height": 600}}  # macOS lists a few
    assert pick([nameless, zoom], ["Zoom"]).behind is None


def test_pick_follows_the_frontmost_app_when_no_call_app_is_open():
    assert pick([window("Archive Utility", 0, 0, 800, 600, 1), window("Electron", 0, 0, 3000, 2000, 2)], CALL_APPS) == \
        Window("Archive Utility", (0, 0, 800, 600), 1, None, False)
    assert pick([window("Electron", 0, 0, 3000, 2000), window("Notes", 0, 0, 800, 600, 3)], CALL_APPS).app == "Notes"  # never our own windows
    assert pick([window("Terminal", 0, 0, 100, 50, 1), window("Notes", 0, 0, 800, 600, 3)], CALL_APPS) == \
        Window("Notes", (0, 0, 800, 600), 3, "Terminal", False)  # a palette in front: too small to follow, but it does cover
    assert pick([window("Notes", 0, 0, 800, 600), window("Zoom", 0, 0, 1100, 700)], CALL_APPS).app == "Zoom"  # a call app wins
    assert pick([window("Terminal", 0, 0, 200, 100)], CALL_APPS) is None  # nothing of a real size
    assert pick([window("Electron", 0, 0, 3000, 2000)], CALL_APPS) is None
    assert pick([], CALL_APPS) is None


def test_faces_are_looked_for_only_in_call_apps_and_browser_tabs_on_call_sites():
    assert has_call("Zoom", "") and has_call("zoom.us", "Zoom Meeting") and has_call("Microsoft Teams classic", "")
    assert has_call("Google Chrome", "Meet - weekly sync - Google Chrome")
    assert has_call("Arc", "Launch Meeting - Zoom") and has_call("Safari", "https://teams.microsoft.com/...")
    assert has_call("Google Chrome", "My room | whereby") and has_call("Google Chrome", "Jitsi Meet")
    assert not has_call("Google Chrome", "GitHub - okyoiu/hacktx") and not has_call("Google Chrome", "")
    assert not has_call("Notes", "Zoom notes") and not has_call("Archive Utility", "Zoom")  # not a browser, not a call app
    tab = dict(window("Google Chrome", 0, 0, 1400, 900, 3), kCGWindowName="Meet - abc-defg-hij - Google Chrome")
    assert pick([tab], CALL_APPS).calls and not pick([window("Google Chrome", 0, 0, 1400, 900, 3)], CALL_APPS).calls
    assert pick([window("Zoom", 0, 0, 1100, 700)], CALL_APPS).calls and not pick([window("Notes", 0, 0, 800, 600)], CALL_APPS).calls
    assert "Meet" not in repr(pick([tab], CALL_APPS))  # the title is matched, never kept


def test_missing_screen_recording_permission_shows_as_windows_without_names(monkeypatch):
    named = [dict(window("Terminal", 0, 0, 800, 600), kCGWindowName="bash"), window("Zoom", 0, 0, 1100, 700)]
    assert can_record(named)  # one named window is enough: some windows have no name even with permission
    assert can_record([dict(window("Finder", 0, 0, 800, 600), kCGWindowName="")])  # present but empty still counts
    assert not can_record([window("Terminal", 0, 0, 800, 600), window("Zoom", 0, 0, 1100, 700)])
    assert can_record([])  # nothing on screen: can't tell, so don't give up
    monkeypatch.setattr(win, "windows", lambda: [window("Zoom", 0, 0, 1100, 700)])
    with pytest.raises(NoScreenRecording):
        win.call_window(["Zoom"])


def test_screen_frames_exits_with_code_3_when_the_screen_cannot_be_recorded(monkeypatch, capsys):
    monkeypatch.setattr(faces.mss, "MSS", FakeScreen)
    monkeypatch.setattr(faces, "call_window", lambda apps: (_ for _ in ()).throw(NoScreenRecording(NO_PERMISSION)))
    with pytest.raises(SystemExit) as stop:
        next(faces.screen_frames(None, follow=["Zoom"]))
    assert stop.value.code == 3
    assert capsys.readouterr().out.strip() == NO_PERMISSION


def test_grab_decodes_what_screencapture_hands_over_and_gives_none_once_the_window_is_gone(monkeypatch):
    png = cv2.imencode(".png", np.full((48, 64, 3), 7, np.uint8))[1].tobytes()
    runs = []

    def run(cmd, capture_output):
        runs.append(cmd)
        return SimpleNamespace(returncode=0 if len(runs) == 1 else 1, stdout=png if len(runs) == 1 else b"")

    monkeypatch.setattr(win.subprocess, "run", run)
    frame = win.grab(42)
    assert frame.shape == (48, 64, 3) and frame[0, 0].tolist() == [7, 7, 7]
    assert runs[0][:3] == ["screencapture", "-l", "42"] and "-o" in runs[0]  # that window only, without its shadow
    assert win.grab(42) is None


class FakeScreen:  # stands in for mss.MSS, which needs a display
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def grab(self, box):
        return np.zeros((box["height"], box["width"], 4), np.uint8)


def test_screen_frames_follows_the_window_and_yields_nothing_while_it_is_gone(monkeypatch):
    monkeypatch.setattr(faces.mss, "MSS", FakeScreen)
    spots = iter([Window("zoom.us", (50, 60, 30, 20), 7, None), None, Window("zoom.us", (5, 6, 30, 20), 7, None)])  # moved, closed, back
    monkeypatch.setattr(faces, "FOLLOW_EVERY", -1)
    monkeypatch.setattr(faces, "call_window", lambda apps: next(spots))
    monkeypatch.setattr(faces, "grab", lambda window_id: np.full((20, 30, 3), window_id, np.uint8))
    frames = faces.screen_frames((0, 0, 30, 20), follow=["zoom.us"])
    frame, origin = next(frames)
    assert origin == (50, 60, 30, "zoom.us", True) and frame[0, 0, 0] == 7  # the window's own pixels, by its id
    assert next(frames)[0] is None
    assert next(frames)[1] == (5, 6, 30, "zoom.us", True)


@pytest.mark.models
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

    chrome, zoom = Window("Google Chrome", (1, 2, 30, 20), 7, None), Window("zoom.us", (5, 6, 30, 20), 8, None)
    notes = Window("Notes", (1, 2, 30, 20), 3, None, False)
    looks = iter([None, None, "unreadable", chrome, zoom._replace(behind="Terminal"), zoom, notes, None])
    monkeypatch.setattr(faces, "call_window", lookup)
    monkeypatch.setattr(faces, "grab", lambda window_id: np.zeros((20, 30, 3), np.uint8))
    frames = faces.screen_frames(None, follow=["zoom.us", "Google Chrome"])
    got = [next(frames) for _ in range(8)]
    assert [f is None for f, _ in got] == [True, True, True, False, False, False, False, True]
    assert got[6][1] == (1, 2, 30, "Notes", False)  # followed for the window event, but no faces
    assert all(apps == ["zoom.us", "Google Chrome"] for apps in seen)  # always every call app: the frontmost one wins
    assert capsys.readouterr().out.splitlines() == [  # one line per change, not per frame
        "waiting for a call window", "couldn't list windows: no permission", "following the Google Chrome window",
        "following the zoom.us window", "the zoom.us window is behind Terminal", "the zoom.us window is clear again",
        "following the Notes window (not a call: no faces)", "waiting for a call window"]


def test_screen_frames_says_so_once_when_the_window_cannot_be_captured(monkeypatch, capsys):
    monkeypatch.setattr(faces.mss, "MSS", FakeScreen)
    monkeypatch.setattr(faces, "FOLLOW_EVERY", -1)
    looks = iter([Window("Zoom", (0, 0, 30, 20), 9, None), Window("Zoom", (0, 0, 30, 20), 9, None), None])
    monkeypatch.setattr(faces, "call_window", lambda apps: next(looks))
    monkeypatch.setattr(faces, "grab", lambda window_id: None)  # screencapture gave nothing: closed, or no permission
    frames = faces.screen_frames(None, follow=["Zoom"])
    assert next(frames)[0] is None and next(looks, "all looked") == "all looked"
    assert capsys.readouterr().out.splitlines() == [
        "following the Zoom window",
        "couldn't capture the Zoom window; if it is still open, allow Screen Recording for this app",
        "waiting for a call window"]  # once per change, not per attempt


@pytest.mark.models
def test_a_print_is_only_computed_for_the_face_that_asks_for_one():
    found = find_faces(get_image("t1"))
    assert len(found) == 6 and all(not hasattr(f, "embedding") or f.embedding is None for f in found)
    add_print(get_image("t1"), found[0])
    assert abs(np.linalg.norm(found[0].normed_embedding) - 1) < 1e-3 and found[1].embedding is None


def test_debug_face_box_is_dropped_once_the_person_has_moved_off_it():
    person = [100, 100, 200, 400]
    assert faces.face_in([150, 120, 60, 80], person) == [150, 120, 60, 80]
    assert faces.face_in([500, 120, 60, 80], person) is None and faces.face_in(None, person) is None


@pytest.mark.models
def test_a_box_is_a_person_only_while_its_pixels_keep_changing():
    t1, box = get_image("t1"), {1: [337, 219, 735, 648]}  # one person on the sample photo
    rng = np.random.default_rng(0)
    camera = lambda: np.clip(t1 + rng.normal(0, 1, t1.shape), 0, 255).astype(np.uint8)  # live video: a little sensor noise
    pictures = faces.Pictures()
    assert pictures.update(t1, box, 0.0) == {1}  # new: not proven live yet, so no print
    assert pictures.update(camera(), box, 0.2) == set()  # changed: a person
    assert pictures.update(t1, box, 1.0) == set()  # changed again (noise gone), still a person...
    assert pictures.update(t1, box, 3.0) == set()  # ...identical now, but only for 2 s
    assert pictures.update(t1, {1: [340, 222, 738, 651]}, 4.5) == {1}  # frozen 3.5 s: a picture (box jitter doesn't count)
    assert pictures.update(camera(), box, 5.0) == set()  # the camera came on: a person at once
    assert pictures.update(camera(), {}, 6.0) == set() and not pictures.last and not pictures.moved  # track ended: forgotten
    live = faces.Pictures()
    assert [live.update(camera(), box, t) for t in (0.0, 0.2, 3.0, 6.0, 9.0)] == [{1}, set(), set(), set(), set()]


def test_windows_windows_take_the_shape_the_mac_list_has_so_picking_works_unchanged():
    zoom = win.win32_window("Zoom Meeting", r"C:\Users\me\AppData\Roaming\Zoom\bin\Zoom.exe", (10, 20, 1110, 720))
    meet = win.win32_window("Meet - abc-defg-hij - Google Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe", (0, 0, 1400, 900))
    github = win.win32_window("GitHub - Google Chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe", (0, 0, 1400, 900))
    notepad = win.win32_window("Untitled - Notepad", r"C:\Windows\notepad.exe", (0, 0, 800, 600))
    # a call app wins over the window in front; no window id, so faces.py grabs it by rect with mss
    assert pick([notepad, zoom], CALL_APPS) == Window("Zoom", (10, 20, 1100, 700), None, "notepad", True)
    assert pick([meet], CALL_APPS).calls and not pick([github], CALL_APPS).calls
    assert pick([notepad], CALL_APPS) == Window("notepad", (0, 0, 800, 600), None, None, False)  # follow any app, no faces
    assert can_record([notepad])  # titles are always there on Windows: no permission check to trip


def test_a_window_without_an_id_is_grabbed_from_the_screen_by_its_rect(monkeypatch):
    monkeypatch.setattr(faces.mss, "MSS", FakeScreen)
    monkeypatch.setattr(faces, "FOLLOW_EVERY", -1)
    monkeypatch.setattr(faces, "call_window", lambda apps: Window("Zoom", (10, 20, 30, 20), None, None, True))
    monkeypatch.setattr(faces, "grab", lambda window_id: pytest.fail("screencapture is macOS only"))
    frame, origin = next(faces.screen_frames(None, follow=["Zoom"]))
    assert frame.shape == (20, 30, 3) and origin == (10, 20, 30, "Zoom", True)


def test_is_me_reads_the_roles_people_give_their_own_face():
    assert all(faces.is_me({"role": r}) for r in ("Me", "me!", " MYSELF ", "myself"))
    assert faces.is_me({"role": "", "self": True}) and not faces.is_me({"role": None}) and not faces.is_me({})
    assert not faces.is_me({"role": "Your team lead"}) and not faces.is_me({"role": "Met me at HackTX"})


def test_a_dark_frame_is_lifted_so_the_same_people_are_found_with_nearly_the_same_prints():
    t1 = get_image("t1")
    bright = sorted(faces_in(t1), key=lambda f: f.bbox[0])
    dark = (t1 * 0.25).astype(np.uint8)  # a dark room
    assert not faces.is_dark(t1) and faces.is_dark(dark) and faces.is_dark(dark[219:648, 337:735])
    lifted = sorted(faces_in(faces.brighten(dark)), key=lambda f: f.bbox[0])
    assert len(lifted) == 6
    distances = [1 - float(a.normed_embedding @ b.normed_embedding) for a, b in zip(bright, lifted)]
    assert max(distances) < 0.1, distances  # the task's bar at 25 % brightness (measured 0.017-0.054)
