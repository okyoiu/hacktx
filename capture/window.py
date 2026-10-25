"""Find a call app's window on macOS and grab its pixels, so capture/faces.py can run without --region.

Reads the window list macOS already exposes (CGWindowListCopyWindowInfo, through osascript) and captures one window with
the screencapture tool that ships with macOS, so no extra dependency.
"""
import json
import re
import subprocess
from collections import namedtuple

import cv2
import numpy as np

# Owner names as macOS reports them; a name also matches longer ones ("Microsoft Teams" finds "Microsoft Teams classic").
CALL_APPS = ("Zoom", "zoom.us", "FaceTime", "Photo Booth", "Microsoft Teams", "Google Chrome", "Arc", "Safari", "Discord", "Slack", "Webex")

# Prints every on-screen window's owner app, layer and bounds; bounds are screen points, top-left origin, like mss.
LIST_WINDOWS = """
ObjC.import("CoreGraphics");
JSON.stringify(ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo(
  $.kCGWindowListOptionOnScreenOnly | $.kCGWindowListExcludeDesktopElements, $.kCGNullWindowID))))
"""


def windows() -> list[dict]:
    """Normal on-screen app windows (layer 0; menus, docks and overlays sit on other layers)."""
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", LIST_WINDOWS], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"couldn't list windows: {out.stderr.strip()}")
    return [w for w in json.loads(out.stdout) if w.get("kCGWindowLayer") == 0]


MIN_SIZE = (300, 200)  # points; a call's toolbar or thumbnail window is smaller, so it doesn't count as the call

# behind: the owner of another app's window in front of this one and overlapping it (the frontmost in the list), or None
Window = namedtuple("Window", "app rect id behind")


def overlap(a: dict, b: dict) -> bool:
    return a["X"] < b["X"] + b["Width"] and b["X"] < a["X"] + a["Width"] and a["Y"] < b["Y"] + b["Height"] and b["Y"] < a["Y"] + a["Height"]


# Hello Again's own windows, by owner name: Electron while developing, the app's name once packaged
OWN_APPS = ("Electron", "Hello Again", "hello-again-overlay")


def pick(windows: list[dict], apps) -> Window | None:
    """The frontmost window of any of these apps, as macOS lists them front to back; when none of them has a window, the
    frontmost regular window of whatever app is in front (never Hello Again's own). Its rect is (x, y, width, height) in
    screen points. Toolbars and thumbnails are skipped; if a call app has only those, its largest one wins."""
    # \b so "Arc" doesn't match "Archive Utility" but "zoom" still matches "zoom.us"
    ours = [w for w in windows if any(re.match(re.escape(a) + r"\b", w.get("kCGWindowOwnerName", ""), re.I) for a in apps)]
    size = lambda w: (w["kCGWindowBounds"]["Width"], w["kCGWindowBounds"]["Height"])
    roomy = [w for w in windows if size(w)[0] >= MIN_SIZE[0] and size(w)[1] >= MIN_SIZE[1] and w.get("kCGWindowOwnerName") not in OWN_APPS]
    if ours:
        w = next((w for w in roomy if w in ours), None) or max(ours, key=lambda w: size(w)[0] * size(w)[1])
    elif roomy:
        w = roomy[0]  # no call app open: follow what's in front (Cesar: work in general, best with the call apps)
    else:
        return None
    b, app = w["kCGWindowBounds"], w.get("kCGWindowOwnerName", "")
    front = next((f for f in windows if f.get("kCGWindowOwnerName") not in OWN_APPS), w)
    front_app = front.get("kCGWindowOwnerName", "")  # a nameless window (rare) never counts as covering
    behind = front_app if front_app and front_app != app and overlap(front["kCGWindowBounds"], b) else None
    return Window(app, (int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"])), w.get("kCGWindowNumber"), behind)


NO_PERMISSION = ("Screen Recording permission is off for the app that launched Hello Again (System Settings > Privacy & Security > "
                 "Screen & System Audio Recording); it sees only the wallpaper")


class NoScreenRecording(Exception):
    pass


def can_record(windows: list[dict]) -> bool:
    """False when macOS hides every other app's window name: that is how it says this process may not record the screen
    (its grabs would show only the wallpaper). An empty list says nothing, so it counts as fine."""
    return not windows or any("kCGWindowName" in w for w in windows)


def call_window(apps=CALL_APPS) -> Window | None:
    found = windows()
    if not can_record(found):
        raise NoScreenRecording(NO_PERMISSION)
    return pick(found, apps)


def grab(window_id: int) -> np.ndarray | None:
    """That window's own pixels (BGR), even while other windows cover it; None once it is gone. -x: no sound, -o: no shadow."""
    out = subprocess.run(["screencapture", "-l", str(window_id), "-x", "-o", "-t", "png", "-"], capture_output=True)
    if out.returncode != 0 or not out.stdout:
        return None
    return cv2.imdecode(np.frombuffer(out.stdout, np.uint8), cv2.IMREAD_COLOR)


def apps_on_screen() -> list[str]:
    return sorted({w.get("kCGWindowOwnerName", "") for w in windows()})
