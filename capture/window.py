"""Find a call app's window and grab its pixels, so capture/faces.py can run without --region.

macOS: the window list CGWindowListCopyWindowInfo exposes (through osascript) and the screencapture tool, both shipped with
the system. Windows: EnumWindows through ctypes; windows are grabbed by rect with mss. No extra dependency either way.
"""
import json
import os
import re
import subprocess
import sys
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
    """Normal on-screen app windows, front to back, as macOS describes them (kCGWindow… keys), on either platform."""
    if sys.platform == "win32":
        return win32_windows()
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", LIST_WINDOWS], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"couldn't list windows: {out.stderr.strip()}")
    return [w for w in json.loads(out.stdout) if w.get("kCGWindowLayer") == 0]  # layer 0: menus, docks, overlays sit higher


# Windows process names (without .exe) -> the app names the rest of this file knows, so the same CALL_APPS, has_call and
# window event work on both platforms
WIN_APPS = {"zoom": "Zoom", "chrome": "Google Chrome", "arc": "Arc", "msedge": "Microsoft Edge", "teams": "Microsoft Teams",
            "ms-teams": "Microsoft Teams", "discord": "Discord", "slack": "Slack", "webex": "Webex", "webexmta": "Webex"}


def win32_window(title: str, exe: str, rect: tuple[int, int, int, int]) -> dict:
    """One Windows top-level window in the shape of a macOS list entry (no window number: it is grabbed by rect)."""
    stem = os.path.splitext(exe.replace("\\", "/").rsplit("/", 1)[-1])[0]  # file name; os.path on a Mac keeps backslashes
    left, top, right, bottom = rect
    return {"kCGWindowOwnerName": WIN_APPS.get(stem.lower(), stem), "kCGWindowName": title,
            "kCGWindowBounds": {"X": left, "Y": top, "Width": right - left, "Height": bottom - top}}


def win32_windows() -> list[dict]:
    """Visible, titled top-level windows, front to back. Untested: written without a Windows machine (see TASKS.md)."""
    import ctypes
    from ctypes import wintypes

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.SetProcessDPIAware()  # so GetWindowRect gives the same pixels mss grabs
    found = []

    def each(hwnd, _):
        if user32.IsWindowVisible(hwnd) and user32.GetWindowTextLengthW(hwnd):
            title, rect, pid = ctypes.create_unicode_buffer(512), wintypes.RECT(), wintypes.DWORD()
            user32.GetWindowTextW(hwnd, title, 512)
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            exe, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
            if handle := kernel32.OpenProcess(0x1000, False, pid):  # PROCESS_QUERY_LIMITED_INFORMATION
                kernel32.QueryFullProcessImageNameW(handle, 0, exe, ctypes.byref(size))
                kernel32.CloseHandle(handle)
            if title.value != "Program Manager":  # the desktop itself
                found.append(win32_window(title.value, exe.value, (rect.left, rect.top, rect.right, rect.bottom)))
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(each), 0)
    return found


MIN_SIZE = (300, 200)  # points; a call's toolbar or thumbnail window is smaller, so it doesn't count as the call

# behind: the owner of another app's window in front of this one and overlapping it (the frontmost in the list), or None
# calls: whether faces in it are people on a call (has_call), so faces.py knows to look for them
Window = namedtuple("Window", "app rect id behind calls", defaults=(True,))

BROWSERS = ("Google Chrome", "Arc", "Safari")  # in CALL_APPS: a call only when the tab is on one of these sites
CALL_SITES = ("meet.google.com", "Google Meet", "Meet -", "Meet –", "zoom.us", "Zoom", "teams.microsoft.com", "Microsoft Teams",
              "webex", "discord.com", "whereby", "jitsi")  # "Meet - <code>" is how Chrome titles a Meet tab


def named(owner: str, apps) -> bool:
    # \b so "Arc" doesn't match "Archive Utility" but "zoom" still matches "zoom.us"
    return any(re.match(re.escape(a) + r"\b", owner, re.I) for a in apps)


def has_call(owner: str, title: str) -> bool:
    """Whether a window's faces are people on a call: a native call app, or a browser on a call site. Cesar: a lot of faces
    online are just images, but people do join Zoom through the web. The title is only matched here, never kept."""
    if named(owner, BROWSERS):
        return any(site.lower() in title.lower() for site in CALL_SITES)
    return named(owner, CALL_APPS)


def overlap(a: dict, b: dict) -> bool:
    return a["X"] < b["X"] + b["Width"] and b["X"] < a["X"] + a["Width"] and a["Y"] < b["Y"] + b["Height"] and b["Y"] < a["Y"] + a["Height"]


# Hello Again's own windows, by owner name: Electron while developing, the app's name once packaged
OWN_APPS = ("Electron", "Hello Again", "hello-again-overlay")


def pick(windows: list[dict], apps) -> Window | None:
    """The frontmost window of any of these apps, as macOS lists them front to back; when none of them has a window, the
    frontmost regular window of whatever app is in front (never Hello Again's own). Its rect is (x, y, width, height) in
    screen points. Toolbars and thumbnails are skipped; if a call app has only those, its largest one wins."""
    ours = [w for w in windows if named(w.get("kCGWindowOwnerName", ""), apps)]
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
    return Window(app, (int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"])), w.get("kCGWindowNumber"), behind,
                  has_call(app, w.get("kCGWindowName", "")))


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
