# Hello Again

A private overlay for Teams and Zoom calls. When someone you've met shows up, a glass card next to their face says who they are and what you last talked about, and a **Top picks** dock surfaces the highlights Muse hears in the conversation. Only people who enrolled themselves are recognized. HackTX 26.

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
3. Database: create a Tiger Data service and paste its connection string into `DATABASE_URL` (pgvector is available there). Local fallback: `docker run -d -p 5432:5432 -e POSTGRES_PASSWORD=postgres pgvector/pgvector:pg17`. Tables are created on first start.
4. Overlay: `cd overlay && npm install`.

## Run it

One terminal each:

```sh
uv run --env-file .env uvicorn memory.app:app --host 0.0.0.0 --port 8000   # B
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

The overlay sits on top of someone's call, so it must never get in the way.

- **Not clickable by default.** Name cards and everything else let clicks pass straight through to the call, and they have no hover state.
- **Clickable things say so.** Only cards with an action (class `actionable`) take the mouse. On hover they show a ring and a pointer, and only then reveal their one action. The Top picks dock is a normal window you can drag.
- **One action per card at most**, hidden until hover. Anything more belongs in the dock.
- **No "unknown" labels.** A face we can't name yet (still matching, or not enrolled) keeps a small glass card with the thinking sparkle and a shimmering verb ("Recalling…"). Hovering it reveals "Copy invite link".
- **Motion is part of the product.** Cards blur in, the sparkle turns while we think, and picks slide into the dock. Everything respects the system's reduce-motion setting.
- **Still to do:** keep auditing for clutter. Hide cards for people who aren't talking in big calls, and fade the dock when nothing new has happened for a while.

## Overlay events (memory → overlay, WebSocket `/ws`)

```jsonc
{"type": "face", "trackId": 3, "screenBox": [x, y, w, h],          // screen points
 "person": {"id": "p_1a2b", "name": "Jordan Lee", "line": "Moved to Austin", "met": "Met Sep 24"}}  // null = can't name them yet (thinking card)
{"type": "face_gone", "trackId": 3}
{"type": "caption", "speaker": "Jordan Lee", "text": "We finally finished the move…", "final": false}
{"type": "pick", "id": "a1", "kind": "fact|common|place|event", "title": "…", "detail": "…", "quote": "…", "speaker": "Jordan Lee"}
```

## Memory API (capture and enrollment → memory)

| Call | Body | Sent by |
|---|---|---|
| `POST /faces` | `{trackId, screenBox, facePrint?}`; the 512-number print only for a new track | `capture/faces.py` |
| `POST /faces/gone` | `{trackId}` | `capture/faces.py` |
| `POST /transcript` | `{speaker, text, final}` | `capture/transcribe.py` |
| `POST /speakers` | `{label, name}` | you, once per call |
| `GET /enroll`, `POST /enroll` | form: `name`, `consent`, `selfie` → `{id, deleteToken}` | guest's phone |
| `DELETE /people/{id}` | header `X-Delete-Token` | guest's phone |

## Known limits

- Voices are named by hand (`/speakers`); matching a voice to a face is future work.
- The face match cutoff (`MATCH_MIN = 0.45` in `memory/store.py`) was picked by eye. Tune it on your own faces over real call video.
- Cards sit beside faces, not on them, because `capture/faces.py` captures the screen and would otherwise see the cards instead of the faces.
- The cards are tinted glass only. Electron can't blur the desktop through a transparent full-screen window; the Top picks dock gets real blur from macOS vibrancy and Windows acrylic.
- `setContentProtection` keeps the overlay out of screen shares on Windows. Newer macOS screen sharing can still capture it.
- Nothing is authenticated except deleting a person. Keep the server on localhost or your LAN; don't tunnel it to the internet.
- Muse realtime sessions last up to 60 minutes; restart `capture.transcribe` for longer calls.
- Licenses: InsightFace `buffalo_l` weights are non-commercial and Ultralytics YOLO is AGPL-3.0. Both are fine for a hackathon; replace them before selling anything.

Muse docs: [speech to text](https://dev.meta.ai/docs/speech-to-text) · [Model API overview](https://dev.meta.ai/docs/overview)
