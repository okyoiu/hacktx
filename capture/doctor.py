"""A 15-second self-check for teammates: uv run python -m capture.doctor

One line per item, OK or FAIL with the fix. Exit code 0 only when everything is OK. Nothing is saved: the one frame it
grabs and the faces it finds in it live only in memory for the check.
"""
import os
import sys
import time

import numpy as np

Result = tuple[str, bool, str, str]  # (item, ok, detail, fix)


def report(results: list[Result]) -> str:
    lines = [f"{'OK  ' if ok else 'FAIL'} {item}: {detail}" + ("" if ok else f"  ->  {fix}") for item, ok, detail, fix in results]
    return "\n".join(lines + ["all good" if all(ok for _, ok, _, _ in results) else "something to fix above"])


def check(item: str, fix: str, run) -> Result:
    """Run one check; it returns (ok, detail), and an exception is a FAIL with the error as detail."""
    try:
        ok, detail = run()
    except (Exception, SystemExit) as e:  # SystemExit: how window.windows() reports an unreadable window list
        ok, detail = False, f"{e!r}"
    return item, ok, detail, fix


def checks() -> list[Result]:
    from capture import window

    results, state = [], {}

    def permission():
        state["windows"] = window.windows()
        return window.can_record(state["windows"]), "the window list has names, so this process may record the screen"

    def found():
        state["window"] = w = window.pick(state.get("windows", []), window.CALL_APPS)
        if w is None:
            return False, "no window of a real size on screen"
        kind = "a call app" if w.calls else "not a call app, followed for the window event only (no faces)"
        return True, f"{w.app} window at {w.rect}, {kind}" + (f", behind {w.behind}" if w.behind else "")

    def grabbed():
        import cv2
        import mss

        w = state.get("window")
        if w is None:
            return False, "nothing to grab"
        if w.id is not None:
            frame = window.grab(w.id)
        else:
            x, y, width, height = w.rect
            with mss.MSS() as screen:
                frame = cv2.cvtColor(np.array(screen.grab({"left": x, "top": y, "width": width, "height": height})), cv2.COLOR_BGRA2BGR)
        if frame is None:
            return False, "screencapture gave nothing for that window"
        state["frame"] = frame
        blank = float(frame.std()) < 1
        return not blank, f"{frame.shape[1]}x{frame.shape[0]} px" + (", blank (all one colour)" if blank else ", has content")

    def sample():  # what the models run on when there is no grab: InsightFace's bundled photo of six people
        if "frame" not in state:
            from insightface.data import get_image

            state["frame"], state["sample"] = get_image("t1"), True
        return state["frame"], " (on the sample photo, no window grabbed)" if state.get("sample") else ""

    def yolo():
        from ultralytics import YOLO

        frame, note = sample()
        model = YOLO("yolo26n.pt")
        t = time.perf_counter()
        people = len(model(frame, classes=[0], verbose=False)[0].boxes)
        return True, f"{people} people in {(time.perf_counter() - t) * 1000:.0f} ms{note}"

    def insightface():
        from capture.embed import faces_in

        frame, note = sample()
        t = time.perf_counter()
        faces = len(faces_in(frame))
        return True, f"{faces} faces in {(time.perf_counter() - t) * 1000:.0f} ms{note}"

    def memory():
        import httpx

        url = os.getenv("MEMORY_URL", "http://localhost:8000")
        health = httpx.get(f"{url}/health", timeout=3).json()
        return True, f"{url}: " + ", ".join(f"{k}={v}" for k, v in health.items())

    def microphone():
        import sounddevice as sd

        device = sd.query_devices(None, "input")
        return True, f"{device['name']} at {int(device['default_samplerate'])} Hz"

    mac = sys.platform == "darwin"
    results.append(check("Screen Recording", "System Settings > Privacy & Security > Screen & System Audio Recording: allow the app "
                         "that launched this (Terminal, or Hello Again)", permission if mac or sys.platform == "win32" else lambda: (True, "not needed here")))
    results.append(check("call window", "open Zoom, Teams, FaceTime or Meet in a browser, or pass --region to capture.faces", found))
    results.append(check("grab", "if blank: Screen Recording permission (above); if nothing: the window closed", grabbed))
    results.append(check("YOLO", "uv sync, and let yolo26n.pt download once", yolo))
    results.append(check("InsightFace", "uv sync (buffalo_l downloads on first use); on a Mac: xcode-select --install", insightface))
    results.append(check("memory", "start it: uv run --env-file .env uvicorn memory.app:app --host 127.0.0.1 --port 8000 (or set MEMORY_URL)", memory))
    results.append(check("microphone", "plug one in, or allow Microphone for your terminal; list inputs with python -m capture.transcribe --list-devices", microphone))
    return results


def main() -> None:
    from capture import tuning

    results = checks()
    print(report(results))
    print("tunables (capture/tuning.py): " + ", ".join(f"{n}={getattr(tuning, n)}" for n in dir(tuning) if n.isupper()))
    raise SystemExit(0 if all(ok for _, ok, _, _ in results) else 1)


if __name__ == "__main__":
    main()
