# Hello Again

A private overlay for any video call (Zoom, FaceTime, Teams, Meet…). When someone you've met shows up, a glass card next to their face says who they are and what you last talked about, and **Live insights** turns what Muse hears into a running summary and one-click actions answered in an **AI response** panel. Only people who enrolled themselves are recognized. HackTX 26.

- Demo walkthrough and who builds what: https://claude.ai/artifact/QKtRcNkCchCHfctqJKQKeM
- Build plan: https://claude.ai/artifact/CJLtxYf6XvQwzoj1xj5ZFU

## How it fits together

```
call window ─ screen capture ─> capture/faces.py ──── face boxes + prints ───┐
call audio ─ Muse Voice Transcribe ─> capture/transcribe.py ── lines ───────┤
                                                                             v
guest's phone ─ web/enroll.html ─────────────────────────────────> memory/app.py ── WebSocket ──> overlay/
                                                                    │  Tiger Data (Postgres + pgvector)
                                                                    │  Muse Spark: notes + top picks
                                                                    └  SerpApi: places and events
```

| Person | Folder | Owns |
|---|---|---|
| A · Capture and vision | `capture/` | Screen capture, YOLO26 tracking, InsightFace prints, Muse Voice Transcribe |
| B · Memory and AI | `memory/` | Database, face matching, Muse Spark picks, SerpApi, enrollment API |
| C · Consent and experience | `overlay/`, `web/` | Glass overlay app, enrollment page, demo and pitch |

## Setup (once)

1. `cp .env.example .env` and fill in `MODEL_API_KEY` ([dev.meta.ai](https://dev.meta.ai/docs/overview)), `SERPAPI_KEY` and `DATABASE_URL`.
2. Python: `uv sync`. It installs Python 3.12 and everything else; the first run downloads PyTorch and takes a few minutes. InsightFace compiles on install, so on a Mac run `xcode-select --install` first if you haven't.
3. Database: create a Tiger Data service and paste its connection string into `DATABASE_URL` (pgvector is available there). Local fallback: `docker run -d --name hello-again-db -p 127.0.0.1:5432:5432 -e POSTGRES_PASSWORD=postgres pgvector/pgvector:pg17`. Tables are created on first start.
4. Overlay: `cd overlay && npm install`.

## Run it

One terminal each:

```sh
uv run --env-file .env uvicorn memory.app:app --host 127.0.0.1 --port 8000   # B: this laptop only
cd overlay && npm start                                                     # C
uv run --env-file .env python -m capture.faces --region 0,38,1100,700       # A: call window x,y,w,h in screen points
uv run --env-file .env python -m capture.transcribe --device "BlackHole 2ch" # A: --list-devices to see inputs
```

Muse labels voices `speaker_0`, `speaker_1`, … Name them once per call:

```sh
curl -X POST localhost:8000/speakers -H 'content-type: application/json' -d '{"label":"speaker_0","name":"Jordan Lee"}'
```

Guests enroll at `http://<laptop LAN IP>:8000/enroll` on the same Wi-Fi. Set `ENROLL_URL` to that address so the overlay's "Copy invite link" button hands out the right link.

## Work without the others

- **C, overlay only:** `cd overlay && npm run mock` replays `shared/mocks/overlay-demo.jsonl` over your real desktop. No Python needed.
- **B, real pipeline without camera or mic:** start uvicorn and the overlay, then `uv run --env-file .env python -m memory.replay`. It enrolls two fake people, fakes their faces, and sends `shared/mocks/transcript.jsonl` through Muse Spark and SerpApi.
- **A, capture without the call:** play a recorded call full screen and point `--region` at it; watch the uvicorn log for `/faces` posts.
- **Tests:** `uv run pytest`

## Overlay UI rules

The look is pinned by [`docs/ui-reference.png`](docs/ui-reference.png): dark smoked glass with real blur, floating over the call.

- **Three glass pieces.** A **control bar** (pause/resume, live waveform, call timer, `Ask AI ⌘↵`, `Show/Hide ⌘\`), a **Live insights** panel (topic, a few points, `Show transcript`, copy, and an **Actions** list), and an **AI response** panel (the question as a chip, copy, close, the answer and its sources).
- **Name cards beside faces stay**, restyled to the same glass. Faces we can't name yet keep the thinking sparkle and "Recalling…", never an "unknown" label.
- **Computer vision is never shown to users.** No boxes, track numbers or scores in the product; `tools/cv_check.py` is for debugging only.
- **Only the panels and the control bar take clicks.** Name cards are click-through. Actions highlight on hover; everything clickable shows a pointer.
- **Motion is part of the product.** Panels and cards blur in, the sparkle turns while the AI is thinking, the waveform moves while listening. Everything respects reduce-motion.
- **Nothing extra on screen.** `⌘\` hides everything; panels fade when the call has been quiet for a while.

## Overlay events (memory → overlay, WebSocket `/ws`)

On connect the server first sends the latest `listening` and `insights` events, so an overlay that starts mid-call catches up.

```jsonc
{"type": "face", "trackId": 3, "screenBox": [x, y, w, h],          // screen points
 "person": {"id": "p_1a2b", "name": "Jordan Lee", "line": "Moved to Austin", "met": "Met Sep 24"}}  // null = can't name them yet (thinking card)
{"type": "face_gone", "trackId": 3}
{"type": "caption", "speaker": "Jordan Lee", "text": "We finally finished the move…", "final": false}  // the overlay keeps these for "Show transcript"
{"type": "listening", "on": true, "startedAt": "2026-10-24T21:40:00Z"}   // pause state; the timer counts from startedAt
{"type": "insights", "topic": "Jordan's move to Austin",                 // the whole current state, replaces the last one
 "points": ["Jordan moved to Austin last week", "Maya asked whether Jordan found a climbing gym"],   // at most 3, each under 120 characters
 "actions": [{"id": "x1", "kind": "places", "label": "Find climbing gyms near South Congress"},     // at most 4
             {"id": "x2", "kind": "recall", "label": "Remind me who Maya is"},
             {"id": "x3", "kind": "followups", "label": "Suggest follow-up questions"}]}
// action kinds: define · search · places · events · recall · followups · helpful
{"type": "response", "id": "r1", "query": "Find climbing gyms near South Congress",
 "status": "thinking|done|error", "text": "…", "sources": [{"title": "…", "url": "https://…"}]}  // "thinking" first, then the same id with "done" or "error"
```

The old `pick` event is retired: places and events from the conversation become `places`/`events` actions, and facts become insight points.

## Memory API (capture, overlay and enrollment → memory)

| Call | Body | Sent by |
|---|---|---|
| `POST /faces` | `{trackId, screenBox, facePrint?}`; the 512-number print only for a new track | `capture/faces.py` |
| `POST /faces/gone` | `{trackId}` | `capture/faces.py` |
| `POST /transcript` | `{speaker, text, final}`; ignored while paused | `capture/transcribe.py` |
| `POST /speakers` | `{label, name}` | `capture/` (names voices from faces) or you |
| `POST /listening` | `{on: bool}` → emits `listening` | overlay pause button |
| `POST /ask` | `{question}` (≤ 500 characters) → `{id}`, then `response` events | overlay `Ask AI` |
| `POST /actions/{id}` | none → `{id}`, then `response` events | overlay action click |
| `POST /calls/end` | none → `{note}`, the path of the end-of-call note | overlay or you |
| `GET /people/{id}` | none → name, first met, notes | anyone |
| `GET /enroll`, `POST /enroll` | form: `name`, `consent`, `selfie` → `{id, deleteToken}` | guest's phone |
| `DELETE /people/{id}` | header `X-Delete-Token` | guest's phone |

## Known limits

- Voices are named by hand (`/speakers`); matching a voice to a face is future work.
- The face match cutoff (`MATCH_MIN = 0.45` in `memory/store.py`) was picked by eye. Tune it on your own faces over real call video.
- Cards sit beside faces, not on them, because `capture/faces.py` captures the screen and would otherwise see the cards instead of the faces.
- The cards are tinted glass only. Electron can't blur the desktop through a transparent full-screen window; the control bar and panels are their own windows, so they get real blur from macOS vibrancy and Windows acrylic.
- `setContentProtection` keeps the overlay out of screen shares on Windows. Newer macOS screen sharing can still capture it.
- Nothing is authenticated except deleting a person. Keep the server on localhost or your LAN; don't tunnel it to the internet.
- Muse realtime sessions last up to 60 minutes; restart `capture.transcribe` for longer calls.
- Licenses: InsightFace `buffalo_l` weights are non-commercial and Ultralytics YOLO is AGPL-3.0. Both are fine for a hackathon; replace them before selling anything.

Muse docs: [speech to text](https://dev.meta.ai/docs/speech-to-text) · [Model API overview](https://dev.meta.ai/docs/overview)
