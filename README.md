# Hello Again

A private memory for video calls (Zoom, FaceTime, Teams, Meet…). When someone you've met shows up, a see-through card pops open beside their face: who they are to you, when you last saw and spoke to them, what it was about (work or personal), and three short bullets. Then it shrinks out of the way. While you talk, **Live insights** turns what Muse hears into a running summary and one-click actions. After the call, Muse condenses what you learned about each person, and the **People** dashboard lets you browse everyone anytime. Opening the app starts everything. Only people who agreed to be remembered are recognized, and only you see it. HackTX 26.

**New here? Do the Quick start below, top to bottom.** It takes about 15 minutes the first time.

## Quick start

### 1. What you need

- A Mac (the window-following and overlay are built and tested on macOS)
- [uv](https://docs.astral.sh/uv/) (Python), [Node.js](https://nodejs.org/) 20+, and [Docker Desktop](https://www.docker.com/products/docker-desktop/) (for the local database)
- Xcode command line tools, for one package that compiles: `xcode-select --install`
- The two API keys, from Cesar in a private message (never post them in a channel): `MODEL_API_KEY` (Meta Muse) and `SERPAPI_KEY`. Optional: `ENROLL_CODE` (an invite word; phones can enroll only with it, so set it before the demo) and `MUSE_CONNECTOR_KEY` (only for the Muse connector).

### 2. Get the code and install

```sh
git clone https://github.com/okyoiu/hacktx.git && cd hacktx    # or: git pull, if you already have it
uv sync                         # installs Python 3.12 and everything; first time downloads PyTorch (a few minutes). The first call also downloads the face models (yolo26n.pt 5.5 MB, InsightFace buffalo_l ~280 MB into ~/.insightface): do one test run on good internet before the demo
cd overlay && npm install && cd ..
```

### 3. Add your keys

```sh
cp .env.example .env
open -e .env                    # paste MODEL_API_KEY and SERPAPI_KEY, save
```

`.env` is git-ignored. Never commit it or paste keys anywhere else.

### 4. Start a database

Pick one:

- **Local (easiest):** `docker run -d --name hello-again-db -p 127.0.0.1:5432:5432 -e POSTGRES_PASSWORD=postgres pgvector/pgvector:pg17`, and keep `DATABASE_URL=postgresql://postgres:postgres@localhost:5432/postgres` in `.env`. Next time, just `docker start hello-again-db`.
- **Tiger Cloud (the shared team database, and the Tiger Data prize track):** put the Tiger connection string in `DATABASE_URL`. Venue Wi-Fi often blocks database ports, so use a **phone hotspot** with Tiger.

The app creates its tables on first start.

### 5. Open the app

Build the app once: `cd overlay && npm run package`. Then **double-click `overlay/dist/Hello Again.app`** (drag it to the Dock if you like). It runs the code in this folder, so `git pull` updates it without rebuilding. `Hello Again.command` in the `hacktx` folder still works as a fallback (or run `cd overlay && npm start`). On Windows: double-click `Start-Hello-Again.bat` in the repo root (or build `overlay\dist\Hello Again\Hello Again.exe` the same way; both untested so far). The launcher installs Python packages but not Docker, `uv` or Node; if one is missing, the control strip names the part that is down. The overlay app opens and starts everything else: the local database, the memory server, face capture and transcription. The first run also installs anything missing, so it takes a few minutes.

You should see a small glass **control strip** above the call window (at the top of the screen until a call window is found). If one part isn't running, it shows a warning naming it; each part's log is in `logs/<name>.log`.

The first run asks for **Screen Recording** and **Microphone** permission (System Settings → Privacy & Security). Allow both, then quit the app (⌘Q) and open it again.

To stop everything, **quit the app (⌘Q)** or close the Terminal window it opened.

## Try it on a real call: call, leave, rejoin

This is the demo. You need one other person on Zoom.

1. **Before the call,** make the Zoom window big and use gallery view. **Don't wear headphones,** so the laptop mic hears both of you.
2. **Join the call.** A **"Recalling…"** pill appears next to their face.
3. **Remember them, with their OK.** Ask "Okay if this remembers you?" If yes, hover the pill, click **Remember them**, type their name, tick **They said yes**, Save. The pill becomes their name card. No photo needed. (They can also enroll themselves, see below.)
4. **Talk for 2–3 minutes** about real things: where they live, work, plans, a place you'd like to go. **Live insights** fills in a topic, points and actions in its spot beside the call. Click an action and the answer opens in the Ask AI panel. **Show transcript** shows the captions. Press **⌘↵** to ask the AI anything; Enter asks a follow-up.
5. **End the call** with the **End call** button (a **Recap** opens: topic, points, actions, who was there). Or just leave: about **60 seconds** after the last face disappears, the call ends by itself, and Muse saves what you talked about for each person (about 10 seconds later). To skip the wait: `curl -X POST localhost:8000/calls/end`. A readable note also lands in `notes/` (git-ignored, because it's about real people).
6. **Rejoin.** Their card now says **"Last time: …"**. Click **"Remind me who [name] is"** for everything saved about them.

Other controls: **pause** in the control bar stops listening (nothing is sent to Muse while paused), and **⌘\** hides or shows the whole overlay.

## Enrolling someone (three ways, all with consent)

1. **From the call, no photo:** the **Remember them** action on their "Recalling…" pill (step 3 above).
2. **On this laptop:** open http://localhost:8000/enroll, type their name, add a selfie they sent you, tick consent.
3. **From their own phone:** set an invite word as `ENROLL_CODE` in `.env`. Before opening the app, start the server by hand so phones can reach it: `uv run --env-file .env uvicorn memory.app:app --host 0.0.0.0 --port 8000` (the app reuses it). Put both devices on the same network (your hotspot) and send them the app's **Copy invite link** (it carries the code). With `--host 0.0.0.0`, only the enroll and delete-my-data routes answer to other devices; everything else stays on this laptop.

Anyone can delete themselves from the link they get after enrolling.

**People on the call who are not enrolled** agreed to nothing: their voice still goes to Meta's Muse to become text, and their words still go into the live prompts and the transcript (nothing is stored for them and no face print is kept). The host is responsible for telling the call that Hello Again is listening.

## If something's not working

| Problem | Fix |
|---|---|
| `address already in use` | A server is already running on port 8000. The app reuses it; if you started one by hand, that's fine too. |
| No card appears next to a face | Capture follows the frontmost window: a known call app (Zoom, Teams, FaceTime, Discord…) if one is open, otherwise whatever app is in front (for the layout). It looks for faces only in call apps, and in a browser only when the window is on a call site (Meet, Zoom web, Teams web, Webex…); never in other apps. A still image (a photo, a profile picture, a stock image) is never treated as a person: only video that moves counts. It grabs the window by its id, so other windows on top don't matter (another desktop does). Check `logs/faces.log`: it says which window it follows, when a person appears, and when it has seen nobody for 30 s. Make the person's face bigger if it sees nobody. |
| Captions show `speaker_0` instead of names | Names come from whose lips move; give it a moment, or name them yourself: `curl -X POST localhost:8000/speakers -H 'content-type: application/json' -d '{"label":"speaker_0","name":"Their Name"}'` |
| No captions at all | Microphone permission (System Settings → Privacy & Security); check `logs/transcribe.log`. To pick another input: `uv run python -m capture.transcribe --list-devices`. |
| Live insights stays empty | Say a few full sentences, then wait about 10 seconds; check `MODEL_API_KEY` in `.env`. |
| Database connection times out | That network blocks database ports; use the local Docker database, or Tiger Cloud on a phone hotspot. |
| "Last time" doesn't show on rejoin | Wait about 70 seconds after leaving (or run the `curl … /calls/end` above) before rejoining. |

## Hackathon day checklist

- [ ] One laptop runs everything, on a **phone hotspot** (venue Wi-Fi blocks the database and exposes the laptop to strangers)
- [ ] `DATABASE_URL` points at **Tiger Cloud**, so the whole team shares one database
- [ ] Laptop plugged in, Do Not Disturb on, other camera apps closed
- [ ] Rehearse the full call → leave → rejoin flow with a teammate on a second laptop, and **record it as a backup video**
- [ ] Judges get remembered with **Remember them** (with their OK), or enroll from their phone (option 3 above)

## How it fits together (for developers)

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


### Running the parts by hand (developers)

The app runs these for you. To run one by hand (to read its output, say), use the same commands from the `hacktx` folder:

| # | Command | You should see |
|---|---|---|
| 1 | `uv run --env-file .env uvicorn memory.app:app --host 127.0.0.1 --port 8000` | `Application startup complete` |
| 2 | `cd overlay && npm start` | A small glass control bar at the top right of your screen |
| 3 | `uv run --env-file .env python -m capture.faces --app zoom.us` | It finds your Zoom window (use `FaceTime`, `"Microsoft Teams"` or `"Google Chrome"` for other apps) |
| 4 | `uv run --env-file .env python -m capture.transcribe` | `Listening at … Hz`; add `--verbose` to see each sentence (it then also lands in `logs/transcribe.log`) |

Start the server first. If it says **"address already in use"**, a server is already running (maybe the app's), so use that one.

Run by hand, face capture needs **Screen Recording** and transcription needs **Microphone** permission for your terminal app (System Settings → Privacy & Security).

To stop everything, press `Ctrl+C` in each terminal.

## Work without the others (developers)

- **Overlay only:** `cd overlay && npm run mock` replays `shared/mocks/overlay-demo.jsonl` over your desktop. No Python needed.
- **Server without a camera or mic:** start the server and the overlay, then `uv run --env-file .env python -m memory.replay`. It adds two **sample** people (Jordan Lee and Maya Chen) and sends `shared/mocks/transcript.jsonl` through Muse Spark. Use it on the local database only, and delete those people afterwards.
- **Capture without a call:** `python -m capture.faces --video <your own recording>`.
- **Something's off? Run the doctor:** `uv run --env-file .env python -m capture.doctor` checks Screen Recording, the call window, one grab, YOLO, InsightFace, the memory server and the microphone in about 15 seconds, one line each with the fix.
- **See what the computer vision sees (debugging only):** `uv run --env-file .env python -m tools.cv_check`. Users never see this.
- **Tests:** `uv run pytest` (database tests use the local database)

## Ask Muse about your people (optional)

Lets the Muse app answer questions about the people you've met. It sees names, labels and what was learned, never face prints, and can't change anything.

1. Put a long random `MUSE_CONNECTOR_KEY=` in `.env` (see `.env.example`) and restart the memory server. Without it the connector routes don't exist.
2. Set `ENROLL_CODE` and `MUSE_CONNECTOR_KEY` in `.env` first. Run `tools/tunnel.sh` and copy the URL it prints. Through the tunnel the server answers `/connector/*` only (everything else gets 403); stop it after the demo and change the key.
3. In the Muse app: add a custom connector with `<url>/connector/openapi.json` and that key (read-only).
4. Try: "Who haven't I talked to in a while?", "What did Jordan and I talk about last time?", "Which of my contacts love F1?"

## Overlay UI rules

The look is the **Island** Cesar picked from three mockups (`overlay/mockups/island.html`): black glass with real blur, one object at the top of the call, name tags beside faces, nothing else while you talk.

- **The island.** One black-glass pill at the top of the call window (waveform, timer, the AI sparkle, a count of notes that arrived while it was closed). When an insight arrives it widens for six seconds into a one-line **notice** (topic, the newest point, the first action as a chip). A click, `⌘↵`, the sparkle or an answer opens it into the **sheet**: pause, transcript, **People**, **End call**, hide, then the topic, points, actions in two columns and the Ask AI thread with its question field. A click, Escape or twenty quiet seconds (unless you're typing) fold it back into the pill. `⌘\` hides everything.
- **Every call app has a spot.** The `window` event's `app` picks a preset (Zoom, Teams, FaceTime, Meet in a browser, general): the island sits centred over the call window (left for Teams, whose own controls are top right) and grows around that anchor; above the window when there's room. The **transcript** is a slim strip along the bottom of the call, raised above the app's own bar, off until you turn it on in the sheet.
- **Tags and the memory-jogger card.** A known person gets a name tag beside their face. It opens into the card when they appear (about ten seconds), on hover, or when a "This call: …" line arrives: their name and who they are to you, then small labels (**Last seen**, **Last spoke**, **About**, work or personal; dates as "Oct 18", "a week ago" on hover), then at most three one-line bullets (Muse's facts, last time, how you met, "This call: …"). Faces we can't name yet keep the thinking sparkle and "Recalling…", never an "unknown" label. Your own tile (`person.self`) gets no tag and no card.
- **Cards never cover a face.** A card goes right of its face, else left, else below, else above, the first spot that covers no other face, no other card and not the island; if the island grows over it, the card moves, never the island. It only glides when its face has clearly moved (never tracker jitter). ✕ closes it for the call; the tag reopens it.
- **Ask AI keeps the thread.** Questions and answers stack in the sheet. Enter asks a follow-up in the same conversation (the server keeps the thread); `⌘↵` or the sparkle starts a fresh one; the thread clears when the call ends.
- **Recap at the end.** When the call ends (**End call**, or 60 s after the last face leaves), the island opens one last time as the **Recap**: "Call ended · N min", the topic, the key points, one-click actions, and what you talked about with each person. It stays until you close it; if the server's recap doesn't arrive within 15 s of End call, the overlay builds one from the call's insights.
- **Who they are to you.** Each person can have a short label ("Your team lead", "Recruiter at Meta"). You can type it when you remember someone or in the dashboard; after a call, Muse suggests one if there isn't one, but never overwrites a label you typed. It shows under the name on the card.
- **People dashboard.** A glass **People** window, opened from the sheet or with `⌘⇧P`: a **Haven't talked in a while** list at the top (`GET /people/stale?days=30`, hidden when empty), search everyone you've met, and each person's page laid out like the card (the labels, Muse's facts, how you met), every past conversation and notes, edit the label, delete someone (with a confirm step inside the window). It works without a call running.
- **One launch.** Opening the overlay app starts the local database, the memory server, face capture and transcription, and stops them all when you quit. The island shows an amber dot and a warning if something isn't running. Ports: only `8000`, on this laptop (plus the local database on `5432`, also laptop-only).
- **Debug view (developers only).** In developer mode, a toggle in the sheet (and `⌘⌥D`) draws what the computer sees over the call: each person's box and track number, the face box, the match score against the 0.45 cutoff and the decision (name, or why it stayed "Recalling…"), plus frames per second. It is drawn on the click-through layer and hidden from screen shares like everything else.
- **A real app.** `Hello Again.app` (built with `cd overlay && npm run package`, into `overlay/dist/`) has its own icon: drag it to the Dock or Applications and double-click to start everything. It runs the code from this repo folder, so `git pull` updates it without rebuilding.
- **Enroll from the call, no photo needed.** Hovering a "Recalling…" pill reveals **Remember them**: type their name and confirm they said yes, and the face print capture already has from the call is saved. Nothing about an unknown face is stored before that; its print lives only in the server's memory while it's on screen.
- **Computer vision is never shown to users.** No boxes, track numbers or scores in the product. Developers get a **debug view** only when the app is started in developer mode (`npm run dev`, or `HELLO_DEBUG=1`); it is never reachable from the normal app or the network.
- **Only the island and the panels take clicks.** Name tags, open cards and "Recalling…" pills take hover and a click; the rest of the cards layer is click-through. Actions highlight on hover; everything clickable shows a pointer.
- **Motion is part of the product.** Panels and cards blur in, the sparkle turns while the AI is thinking, the waveform moves while listening. Everything respects reduce-motion.
- **Nothing extra on screen.** `⌘\` hides everything; panels fade when the call has been quiet for a while.

## Overlay events (memory → overlay, WebSocket `/ws`)

On connect the server first sends the latest `listening` and `insights` events, so an overlay that starts mid-call catches up.

```jsonc
{"type": "face", "trackId": 3, "screenBox": [x, y, w, h],          // screen points
 "person": {"id": "p_1a2b", "name": "Jordan Lee", "role": "Your team lead", "line": "Last time: …", "met": "Met Sep 24",
            "lastSeen": "2026-10-18", "lastSpoke": "2026-10-18", "topic": "his move to Austin", "context": "work",   // context: "work" | "personal" | "" (Muse's call)
            "bullets": ["Your team lead", "Last time: talked about his move to Austin", "Starts a fintech job Monday"]}}  // null = can't name them yet (thinking card); role may be ""; bullets has at most 5; lastSeen/lastSpoke/topic null before a first call together
{"type": "face_gone", "trackId": 3}
{"type": "window", "app": "Zoom", "rect": [x, y, w, h]}   // the followed window: its app (as capture/window.py names it; a known call app if one is open, else the frontmost app) and screen points; both null when there is none
{"type": "recap", "topic": "…", "points": ["…"], "actions": [{"id": "x1", "kind": "places", "label": "…"}],
 "people": [{"id": "p_1a2b", "name": "Jordan Lee", "role": "…", "lastTime": "…"}]}   // once per call, when it ends; also sent to an overlay that connects later
{"type": "debug", "trackId": 3, "personBox": [x, y, w, h], "faceBox": [x, y, w, h] | null, "score": 0.62 | null,
 "decision": "Jordan Lee" | "below 0.45" | "no face yet", "fps": 4.8}   // developer mode only (HELLO_DEBUG=1 on the server)
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

`insights` events show in the preset's live-insights spot during the call and are kept for the Recap. The old `pick` event is retired: places and events from the conversation become `places`/`events` actions, and facts become insight points.

## Memory API (capture, overlay and enrollment → memory)

| Call | Body | Sent by |
|---|---|---|
| `POST /faces` | `{trackId, screenBox, facePrint?, debug?}`; the 512-number print only for a new track; `debug` = `{personBox, faceBox, fps}` only when capture runs with `HELLO_DEBUG=1` | `capture/faces.py` |
| `POST /faces/gone` | `{trackId}` | `capture/faces.py` |
| `POST /window` | `{app, rect}` (the app name and screen points, or both `null`), sent when the followed window moves, appears or goes away | `capture/faces.py` |
| `POST /transcript` | `{speaker, text, final}`; ignored while paused | `capture/transcribe.py` |
| `POST /speakers` | `{label, name}` | `capture/` (names voices from faces) or you |
| `POST /listening` | `{on: bool}` → emits `listening` | overlay pause button |
| `POST /ask` | `{question, new?}` (≤ 500 characters) → `{id}`, then `response` events; the server keeps the last turns as a thread until `new: true` or the call ends | overlay `Ask AI` |
| `POST /actions/{id}` | none → `{id}`, then `response` events | overlay action click |
| `POST /faces/{trackId}/remember` | `{name, consent: true, role?}` → `{id, deleteToken}`; saves the print of the face on screen in that track, then pushes its updated `face` event; `409` if that face has left | overlay "Remember them" |
| `POST /calls/end` | none → `{note}`, the path of the end-of-call note | overlay or you |
| `GET /people` | none → `[{id, name, role, firstMet, lastMet, lastTime, lastSeen, lastSpoke, topic, context, self}]`, newest first | overlay People dashboard |
| `GET /people/stale?days=30` | people with consent you haven't met in that many days, most overdue first (this laptop only) | dashboard "Haven't talked in a while" |
| `GET /health` | `{db, muse, serpapi, listening, lastTranscriptAt}` | the control strip's status light |
| `GET /connector/people`, `GET /connector/people/{id}`, `GET /connector/openapi.json` | for a Muse **custom connector** (the Muse app calls these): `Authorization: Bearer <MUSE_CONNECTOR_KEY>` required; read-only; name, role, last seen, last spoke, topic, facts and the last conversation, never prints or tokens. The only routes allowed through the demo tunnel (`tools/tunnel.sh`). | Muse app |
| `GET /people/{id}` | none → name, role, first met, `howMet` (one line Muse writes at the first encounter: date, app, what that call was about), `facts` (plain things Muse noticed across calls, e.g. "Loves F1", at most 3 new per call, no repeats, never mixed into the user's notes), encounters (about, last time) and notes (the user's own) | overlay dashboard, recall action |
| `PATCH /people/{id}` | `{role?, name?}` (role ≤ 60, name ≤ 80 characters) → the updated person; a role set here is never replaced by Muse | overlay dashboard |
| `GET /enroll`, `POST /enroll` | form: `name`, `consent`, `selfie`, optional `role`, and `code` (must match `ENROLL_CODE` when it's set; the invite link carries it as `?code=`) → `{id, deleteToken}` | guest's phone |
| `DELETE /people/{id}` | from this laptop: nothing; from another device: header `X-Delete-Token` | dashboard, guest's phone |

## Files it keeps on this laptop

- `notes/<date-time>.md`: one note per call (who was there, insights, answers).
- `notes/people/<person id>.md`: one file per person (the name is inside; IDs keep names out of file paths), rewritten after every call: who they are to you, what they're about, and every past conversation, newest first. It's the readable copy of what the dashboard shows. Deleting someone deletes their file.
- Both are git-ignored, because they're about real people.
- `logs/<name>.log` (server, faces, transcribe, db): git-ignored, mode 0600, trimmed to 1 MB at start; no sentences unless `--verbose`.
- `overlay/dist/`: the built app, git-ignored.

## Known limits

- Voices are named from whose lips move (`capture/speakers.py`); when that's unsure, nothing is guessed and you can name them with `/speakers`.
- The face match cutoff (`MATCH_MIN = 0.45` in `memory/store.py`) was picked by eye. Tune it on your own faces over real call video.
- Cards sit beside faces, not on them, because `capture/faces.py` captures the screen and would otherwise see the cards instead of the faces.
- The cards are tinted glass only. Electron can't blur the desktop through a transparent full-screen window; the control bar and panels are their own windows, so they get real blur from macOS vibrancy and Windows acrylic.
- `setContentProtection` keeps the overlay out of screen shares on Windows. Newer macOS screen sharing can still capture it.
- What happens to people's data, on one page: `docs/privacy.md` (what is kept, where, for how long, what goes to Meta and SerpApi, how to delete).
- Only this laptop can use the server's routes; other devices can only enroll and delete themselves, plus `/connector/*` with the key (see `docs/security-review.md`). Never tunnel it to the internet, except `tools/tunnel.sh` for the Muse connector during the demo (only `/connector/*` answers through it).
- Muse realtime sessions last up to 60 minutes; restart `capture.transcribe` for longer calls.
- Licenses: InsightFace `buffalo_l` weights are non-commercial and Ultralytics YOLO is AGPL-3.0. Both are fine for a hackathon; replace them before selling anything.

Muse docs: [speech to text](https://dev.meta.ai/docs/speech-to-text) · [Model API overview](https://dev.meta.ai/docs/overview)
