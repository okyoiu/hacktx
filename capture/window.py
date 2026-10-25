"""Find a call app's window on macOS, so capture/faces.py can run without --region.

Reads the window list macOS already exposes (CGWindowListCopyWindowInfo, through osascript), so no extra dependency.
"""
import json
import re
import subprocess

# Owner names as macOS reports them; a name also matches longer ones ("Microsoft Teams" finds "Microsoft Teams classic").
CALL_APPS = ("zoom.us", "FaceTime", "Photo Booth", "Microsoft Teams", "Google Chrome", "Arc", "Safari", "Discord", "Slack", "Webex")

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


def pick(windows: list[dict], apps) -> tuple[str, tuple[int, int, int, int]] | None:
    """(owner, (x, y, width, height)) of the frontmost window of any of these apps, as macOS lists them front to back.
    Toolbars and thumbnails are skipped; if every window is that small, the largest wins."""
    # \b so "Arc" doesn't match "Archive Utility" but "zoom" still matches "zoom.us"
    ours = [w for w in windows if any(re.match(re.escape(a) + r"\b", w.get("kCGWindowOwnerName", ""), re.I) for a in apps)]
    if not ours:
        return None
    size = lambda w: (w["kCGWindowBounds"]["Width"], w["kCGWindowBounds"]["Height"])
    roomy = [w for w in ours if size(w)[0] >= MIN_SIZE[0] and size(w)[1] >= MIN_SIZE[1]]
    w = roomy[0] if roomy else max(ours, key=lambda w: size(w)[0] * size(w)[1])
    b = w["kCGWindowBounds"]
    return w["kCGWindowOwnerName"], (int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"]))


def call_window(apps=CALL_APPS) -> tuple[str, tuple[int, int, int, int]] | None:
    return pick(windows(), apps)


def apps_on_screen() -> list[str]:
    return sorted({w.get("kCGWindowOwnerName", "") for w in windows()})
