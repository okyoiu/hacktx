"""Name Muse's voices from the faces on screen, so Live insights can say "Maya asked…" instead of a raw label.

capture/faces.py feeds a Namer two things: how far apart each recognized person's lips are, frame by frame, and the
captions memory pushes over /ws, whose speaker stays Muse's raw label ("A", "B", …) until someone names it. After each
finished line, the one person whose mouth was clearly moving during it, and nobody else's, wins that line for its
label. A label is named only after the same person won most of its lines; anything less certain stays unnamed, which
is how captions look without this. Names set by hand with POST /speakers arrive as names and are never touched.
"""
import json
import time
from collections import Counter, defaultdict, deque

import numpy as np
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

UNLABELED = "speaker"  # what transcribe.py calls a line before Muse sends its first label
MIN_FACE = 60  # px tall; smaller faces' lip landmarks are noise
LEAD_IN = 1.0  # s of mouth movement before a line's first caption that still belong to it (Muse and network lag)
MIN_SAMPLES = 5  # lip readings a line needs before it counts, about 1 s at 5 fps
# Mean frame-to-frame change of the lip gap, as a share of face height, that counts as talking. Synthetic check on
# InsightFace's sample faces: still faces with video compression move 0.001-0.0025, synthetic speech 0.013-0.025.
# shortcut: not yet measured on real speech; tune it on a clip the team records of themselves, like MATCH_MIN
TALKING = 0.008
LEAD = 2.0  # the talker's mouth moves at least this many times more than anyone else's on screen
MIN_LINES, SHARE = 3, 0.75  # name a label once one person won this many of its lines and this share of all of them
ACTIVE = 15  # s after an unnamed voice spoke during which lips are worth reading


def lip_gap(face) -> float:
    """Inner-lip gap as a share of face height (68-point layout: 61-63 upper inner lip, 65-67 lower inner lip)."""
    lm = face.landmark_3d_68[:, :2]
    return float(np.linalg.norm(lm[[61, 62, 63]] - lm[[67, 66, 65]], axis=1).mean() / (face.bbox[3] - face.bbox[1]))


class Namer:
    def __init__(self):
        self.gaps = defaultdict(lambda: deque(maxlen=300))  # person id -> (time, lip gap), about a minute at 5 fps
        self.who: dict[str, str] = {}  # person id -> name
        self.names: set[str] = {UNLABELED}  # caption speakers that are not raw Muse labels
        self.lines = defaultdict(Counter)  # label -> who clearly talked in each of its lines (None: nobody clearly)
        self.named: dict[str, str] = {}  # label -> person id we told memory
        self.line_start: float | None = None  # when the current line's first caption arrived
        self.heard = -ACTIVE  # when an unnamed voice last spoke

    def met(self, person: dict) -> None:
        """A recognized person from memory's /faces reply; their name in a caption means that voice is named."""
        self.who[person["id"]] = person["name"]
        self.names.add(person["name"])

    def wants_lips(self, person_ids, now: float) -> bool:
        """Worth reading lips: an unnamed voice spoke lately and someone on screen has no voice yet."""
        return now - self.heard < ACTIVE and any(p not in self.named.values() for p in person_ids)

    def saw(self, person: dict, face, now: float) -> None:
        self.met(person)
        if face.bbox[3] - face.bbox[1] >= MIN_FACE:
            self.gaps[person["id"]].append((now, lip_gap(face)))

    def caption(self, now: float, speaker: str, final: bool) -> tuple[str, str] | None:
        """Take one caption as it arrives; returns (label, name) when memory should hear that label's name."""
        if self.line_start is None:
            self.line_start = now
        if speaker not in self.names:
            self.heard = now
        if not final:
            return None
        start, self.line_start = self.line_start, None
        if speaker in self.names:
            return None
        if speaker in self.named:  # memory still shows the raw label (it restarted, or our post failed): say it again
            return speaker, self.who[self.named[speaker]]

        moving = {}
        for person, gaps in self.gaps.items():
            g = [gap for t, gap in gaps if start - LEAD_IN <= t <= now]
            if len(g) >= MIN_SAMPLES:
                moving[person] = float(np.abs(np.diff(g)).mean())
        if not moving:
            return None  # nobody recognized was on screen: no evidence either way
        (top, score), *rest = sorted(moving.items(), key=lambda kv: -kv[1])
        clear = score >= TALKING and score >= LEAD * (rest[0][1] if rest else 0.0)
        votes = self.lines[speaker]
        votes[top if clear else None] += 1
        if clear and votes[top] >= MIN_LINES and votes[top] / sum(votes.values()) >= SHARE and top not in self.named.values():
            self.named[speaker] = top
            return speaker, self.who[top]
        return None


def listen(url: str, captions: deque, listening: dict | None = None) -> None:
    """Forever: append (arrival time, speaker, final) for each caption memory pushes on /ws, and keep listening["on"], the
    pill's pause state, up to date (memory sends the latest on connect). Run it in a thread."""
    while True:
        try:
            with connect(url) as ws:
                for raw in ws:
                    event = json.loads(raw)
                    if event.get("type") == "caption":
                        captions.append((time.monotonic(), event["speaker"], bool(event.get("final"))))
                    elif event.get("type") == "listening" and listening is not None:
                        listening["on"] = bool(event.get("on"))
        except (OSError, WebSocketException):
            time.sleep(2)  # memory isn't up yet or restarted
