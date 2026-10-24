"""Find the Teams or Zoom call window on macOS, so capture/faces.py can run without --region.

Reads the window list macOS already exposes (CGWindowListCopyWindowInfo, through osascript), so no extra dependency.
"""
import json
import subprocess

# Prints every on-screen window's owner app, layer and bounds; bounds are screen points, top-left origin, like mss.
LIST_WINDOWS = """
ObjC.import("CoreGraphics");
JSON.stringify(ObjC.deepUnwrap(ObjC.castRefToObject($.CGWindowListCopyWindowInfo(
  $.kCGWindowListOptionOnScreenOnly | $.kCGWindowListExcludeDesktopElements, $.kCGNullWindowID))))
"""


def pick(windows: list[dict]) -> tuple[int, int, int, int] | None:
    """The largest normal Teams or Zoom window as x, y, width, height; their toolbars and thumbnails are smaller."""
    calls = [
        w["kCGWindowBounds"] for w in windows
        if w.get("kCGWindowLayer") == 0
        and (w.get("kCGWindowOwnerName") == "zoom.us" or w.get("kCGWindowOwnerName", "").startswith("Microsoft Teams"))
    ]
    if not calls:
        return None
    b = max(calls, key=lambda b: b["Width"] * b["Height"])
    return int(b["X"]), int(b["Y"]), int(b["Width"]), int(b["Height"])


def call_window() -> tuple[int, int, int, int] | None:
    out = subprocess.run(["osascript", "-l", "JavaScript", "-e", LIST_WINDOWS], capture_output=True, text=True)
    if out.returncode != 0:
        raise SystemExit(f"couldn't list windows: {out.stderr.strip()}")
    return pick(json.loads(out.stdout))
