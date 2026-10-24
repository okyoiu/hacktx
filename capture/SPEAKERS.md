# Naming Muse speakers from the faces on screen

Built in `capture/speakers.py`, run by `capture/faces.py`. It sends `POST /speakers {label, name}` so captions and Live insights say "Maya asked…" instead of Muse's raw label. There's no API change: it uses the existing `/faces` replies, `caption` events on `/ws` and `POST /speakers`.

## How it works
- **Who is talking on screen:** for each recognized face, the inner-lip gap from InsightFace's 68-point landmarks (already in `buffalo_l`, no new model), divided by face height. This runs only while an unnamed voice has spoken in the last 15 s and someone on screen has no voice yet. Faces under 60 px tall are skipped because their landmarks are noise.
- **Who is talking per Muse:** `faces.py` listens to memory's `caption` events. Until a voice is named, its speaker is the raw label (`A`, `B`, … per Muse's docs). A speaker that is a name we know (someone memory recognized, or a name set by hand) is left alone.
- **One verdict per finished line**, not per partial, because Muse's partials can still carry the previous label. A line's lips are read from 1 s before its first caption to its final one. Its winner is the one face whose lips moved clearly (`TALKING`) and at least twice as much as anyone else's. Otherwise the line counts for nobody.
- **A label is named** once one person won at least 3 of its lines and at least 75% of all its lines, counting lines nobody clearly won. Each person gets at most one label. If memory still shows a named label's raw form (it restarted), the name is sent again.

## Never guesses
These cases send nothing, and captions stay as they are today:
- someone talking off camera,
- crosstalk,
- cameras off or people not enrolled,
- names set by hand,
- `transcribe.py`'s placeholder before Muse's first label,
- a second label pointing at someone who already has one.

`capture/test_speakers.py` scripts each case.

## Tested on synthetic data only
- **No real people's media.** Lips come from InsightFace's bundled sample photo, with mouths opened synthetically. Still faces with video-like compression move 0.001–0.0025; synthetic speech moves 0.013–0.025; `TALKING` is 0.008.
- **End to end** (scratch harness, not committed): a two-face synthetic call against a fake memory server with scripted captions. Each voice was named right after its third line, with nothing wrong first. The same call with still faces named nobody.

## Open
- **Tune `TALKING` on real speech:** use a clip the team records of themselves (play it with `faces.py --video`). It's the same kind of by-eye number as `MATCH_MIN`.
- **Muse session restart (60-minute limit):** labels start over, but memory keeps the old label → name map, so a new voice can inherit an old name. Fixing this needs memory to forget names when `transcribe.py` opens a new session: a contract change for the coordinator.
- **README:** it still says `speaker_0`; Muse's docs show `A`, `B`. Nothing here depends on the format.
