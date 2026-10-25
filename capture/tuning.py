"""Capture's knobs, in one place. Tune them on a real call: run `uv run --env-file .env python -m capture.faces`, watch the
log (`capture: …` lines; `HELLO_DEBUG=1` adds boxes and match scores to the overlay's debug view), change one number, run
again. `uv run python -m capture.doctor` prints the current values at the end of its report."""

FOLLOW_EVERY = 3  # s between looks at the window list (~0.1 s each); lower if cards lag behind a moved or switched window
RETRY = 3.0  # s before InsightFace looks again for a person whose face wasn't visible; lower if cards come late, raise to save CPU
QUIET_AFTER = 30  # s with nobody in the followed window before the log says so (and again every QUIET_AFTER); log readability only
STILL_SECONDS = 3.0  # s a tile may stay pixel-identical before it counts as a picture; raise if a motionless person loses their card
STILL_DIFF = 0.25  # mean grey change (0-255, 64x64 sampled) that counts as live video: identical grabs read 0.00, camera noise 0.5+; raise if profile pictures still get cards
RECENT_SECONDS = 30.0  # s a face that left is remembered, so a view switch (new track ids) keeps the person; raise if cards reset after long freezes
SAME_FACE = 0.1  # cosine distance under which a new print is a remembered face; lower if two different people get merged after a view switch
YOLO_LONG_SIDE = None  # px to shrink a frame to before YOLO, None = off (measured as a loss: YOLO resizes to 640 itself); try 960 on a slow laptop and compare the capture: line
DARK_LUMA = 60  # mean grey (0-255) under which a frame or a person box is dark and gets lifted (gamma 0.5 + CLAHE) before YOLO and InsightFace; raise if dim rooms lose faces, lower if the debug view looks washed out
REPORT_EVERY = 60  # s between `capture: N fps, YOLO x ms, InsightFace y ms, cpu z%` log lines
