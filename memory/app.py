"""Memory service: matches faces, turns Muse transcripts into Live insights, answers AI requests, and pushes it all to the overlay.

Run: uv run --env-file .env uvicorn memory.app:app --reload
Keep it on localhost or your LAN; nothing here is authenticated except deleting a person.
"""
import asyncio
import math
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

import numpy as np
import psycopg
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field, StringConstraints
from starlette.requests import HTTPConnection

from memory import connector, notes, picks, pipeline, store

WEB = Path(__file__).resolve().parent.parent / "web"
MAX_SELFIE_BYTES = 8_000_000
CALL_IDLE_SECONDS = 60  # a call ends this long after the last face was seen
INSIGHTS_SECONDS = 8  # Muse Spark refreshes the insights at most this often
MAX_ACTIONS_KEPT = 100  # actions from older insights stay clickable until this many newer ones exist
ENROLLS_PER_MINUTE = 5  # POST /enroll attempts per IP address; each one runs the face model
# Hard stop for one Muse Spark or SerpApi job: the clients time out per request and retry, so a slow service could
# otherwise hold a response on "thinking" or stall Live insights for minutes. The abandoned thread finishes on its own.
OUTBOUND_SECONDS = 45
THREAD_TURNS = 6  # question/answer turns of an Ask AI chat that follow-ups can see
LIVE_BULLET_SECONDS = 60  # check what people have said at most this often, all of them in one request
LIVE_MIN_WORDS = 8  # fewer words than this since the last check is not worth a Muse call
MAX_BULLETS = 3  # the card shows role, last seen, last spoke, topic and context itself
TOPIC_CHARS = 60  # the topic shown on a card is kept short
NOTE_POINTS = 10  # Muse rephrases points every refresh, so the call note keeps only the latest few


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


clients: set[WebSocket] = set()
tracks: dict[int, dict | None] = {}  # trackId -> card for the matched person (None = not enrolled)
unknown: dict[int, dict] = {}  # trackId -> {print, box} of a face on screen we can't name; RAM only, saved only on consent
speakers: dict[str, str] = {}  # Muse speaker label -> display name
history: list[str] = []  # lines Muse Spark has already seen, context for the next refresh
fresh: list[str] = []  # final lines since the last insights refresh
listening: dict = {"type": "listening", "on": True, "startedAt": utc_now()}  # latest listening event
latest_insights: dict | None = None  # latest insights event
live: dict[str, dict] = {}  # person id -> {name, lines}: what they said since the last live-bullets check
live_since: float | None = None  # when the current live-bullets window began (monotonic)
snippets: dict[str, list[str]] = {}  # person id -> this call's "This call: …" bullets (at most 2)
boxes: dict[int, list[float]] = {}  # trackId -> latest screen box, to re-send a face event
thread: list[tuple[str, str]] = []  # the Ask AI chat so far: (question, answer), the last THREAD_TURNS turns
thread_epoch = 0  # bumped whenever the thread is cleared
latest_recap: dict | None = None  # recap of the call that just ended, until the next call starts
latest_window: dict | None = None  # latest window event: where the followed call window is, for Ask AI placement
last_refresh: float | None = None  # when the last insights refresh started (monotonic); None = the next one is immediate
last_transcript_at: str | None = None  # when the last line was accepted, for the control bar's status dot
actions: dict[str, dict] = {}  # action id -> {kind, label, query, personId}
wake: asyncio.Event | None = None  # set when fresh lines wait for Muse Spark; made per event loop in lifespan


def notes_writable() -> bool:
    try:
        notes.tighten()
        probe = notes.private_folders() / ".write-test"
        probe.write_text("")
        probe.unlink()
        return True
    except OSError:
        return False


async def startup_checks() -> list[str]:
    """One line per dependency. Nothing here stops the server: a missing piece switches its feature off, and the
    feature says so when it is used (Muse and SerpApi errors already reach the overlay as plain sentences)."""
    try:
        await asyncio.wait_for(asyncio.to_thread(lambda: store.conn().execute("select 1")), 8)
        db = "database: reachable"
    except Exception as e:
        db = f"database: NOT reachable ({type(e).__name__}); recognition and memory are off until it is up"
    ok = await asyncio.to_thread(notes_writable)
    return [db,
            "Muse key: set" if os.getenv("MODEL_API_KEY") else "Muse key: MISSING; insights, summaries and Ask AI are off (set MODEL_API_KEY)",
            "SerpApi key: set" if os.getenv("SERPAPI_KEY") else "SerpApi key: MISSING; place, event and web searches are off (set SERPAPI_KEY)",
            "notes folder: writable" if ok else "notes folder: NOT writable; call notes and person files will not be saved"]


@asynccontextmanager
async def lifespan(_: FastAPI):
    global wake
    wake = asyncio.Event()
    for report in await startup_checks():
        print(report)
    worker = asyncio.create_task(insights_worker())
    yield
    worker.cancel()


app = FastAPI(title="Hello Again memory", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(connector.router)  # read-only, bearer key; the one set of routes a tunnel may reach


FORWARDED = ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded", "cf-connecting-ip", "cf-ray", "true-client-ip")


@app.exception_handler(RequestValidationError)
async def invalid(_: Request, exc: RequestValidationError):
    """422 without echoing the input back: a NaN or a face print in the error would not even serialize."""
    return JSONResponse({"detail": [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]}, 422)


def from_this_laptop(conn: HTTPConnection) -> bool:
    """Capture, the overlay and curl connect over loopback with no Origin (the overlay page sends file://); browsers
    send their page's origin, so other Wi-Fi devices and web pages open on this laptop both fail."""
    return (conn.client is not None and conn.client.host in ("127.0.0.1", "::1") and conn.headers.get("origin") in (None, "file://")
            and not any(h in conn.headers for h in FORWARDED))  # a tunnel also connects over loopback, but adds one of these


@app.middleware("http")
async def guests_only_enroll(request: Request, call_next):
    """Phones on the Wi-Fi may enroll and delete themselves; every other route is for this laptop only."""
    if any(h in request.headers for h in FORWARDED) and not request.url.path.startswith("/connector/"):
        return JSONResponse({"detail": "Not available through the tunnel."}, 403)  # the tunnel gets the connector, nothing else
    guest = request.url.path.startswith("/connector/") or request.url.path == "/enroll" or (request.method == "DELETE" and request.url.path.startswith("/people/"))
    if not guest and not from_this_laptop(request):
        return JSONResponse({"detail": "Only the laptop running Hello Again can use that."}, 403)
    return await call_next(request)


@dataclass
class Call:
    started: datetime = field(default_factory=datetime.now)
    people: dict[str, list[str]] = field(default_factory=dict)  # recognized person id -> notes learned this call
    points: list[str] = field(default_factory=list)  # the latest NOTE_POINTS distinct insight points, in order
    responses: list[dict] = field(default_factory=list)  # finished response events
    lines: list[str] = field(default_factory=list)  # every final transcript line, "who: text"
    app: str | None = None  # the call app followed while it ran, e.g. "zoom.us"
    topic: str = ""  # what its insights ended up about


call: Call | None = None  # None between calls
idle_timer: asyncio.TimerHandle | None = None
background: set[asyncio.Task] = set()  # pushes started from sync code, kept referenced until sent


def this_call() -> Call:
    global call, latest_recap
    if call is None:
        call = Call()
        latest_recap = None
        listening["startedAt"] = utc_now()  # the control bar's call timer starts with the call
        task = asyncio.get_running_loop().create_task(push(dict(listening)))
        background.add(task)
        task.add_done_callback(background.discard)
    return call


def end_call() -> asyncio.Future:
    """Close the current call and write its note in a thread; the future resolves to the note's path or None."""
    global call, latest_insights, last_refresh, live_since
    if idle_timer:
        idle_timer.cancel()
    ended, call = call or Call(), None
    clear_thread()
    live.clear()
    live_since = None
    snippets.clear()
    insights = latest_insights
    ended.topic = (insights or {}).get("topic", "")
    latest_insights = None  # the next call, and overlays connecting later, start clean
    last_refresh = None  # the next call's first insights don't wait out this call's interval
    history.clear()
    unknown.clear()  # strangers' prints never outlive the call
    fresh.clear()
    loop = asyncio.get_running_loop()
    task = loop.create_task(send_recap(ended, insights))  # Muse Spark is slow; the note doesn't wait for it
    background.add(task)
    task.add_done_callback(background.discard)
    return loop.run_in_executor(None, notes.write, ended.started, ended.people, ended.points, ended.responses)


async def send_recap(ended: Call, insights: dict | None) -> None:
    """Once the summaries are saved, broadcast the finished call's recap and keep it for an overlay that connects later."""
    global latest_recap
    lasts = await asyncio.get_running_loop().run_in_executor(None, remember_encounters, ended)
    people = [{"id": p["id"], "name": p["name"], "role": p["role"], "lastTime": lasts.get(p["id"], "")}
              for p in map(store.person, ended.people) if p]
    recap = {"type": "recap", "topic": (insights or {}).get("topic", ""), "points": (insights or {}).get("points", []),
             "actions": (insights or {}).get("actions", []), "people": people}
    if call is not None or not (recap["topic"] or recap["points"] or recap["actions"] or people):
        return  # a new call already started, or there was no call to recap
    latest_recap = recap
    await push(recap)


APP_NAMES = {"zoom.us": "Zoom", "facetime": "FaceTime", "microsoft teams": "Teams", "google chrome": "Chrome"}


def how_met(ended: Call) -> str:
    """"Oct 25, 2026 on Zoom: <what that call was about>", from facts we already have (no Muse call)."""
    app = ended.app and APP_NAMES.get(ended.app.casefold(), ended.app)
    return f"{notes.day(ended.started)} on {app or 'a call'}" + (f": {ended.topic}" if ended.topic else "")


def remember_encounters(ended: Call) -> dict[str, str]:
    """Runs in a thread: store Muse Spark's about/last-time summary for each recognized person of a finished call.
    Returns person id -> this call's last-time line (empty when the summary was skipped)."""
    lasts: dict[str, str] = {}
    try:
        # store.person drops anyone who deleted themselves or whose consent ran out; unenrolled faces never got here
        people = {p["id"]: {"name": p["name"], "role": p["role"], "notes": [n["text"] for n in p["notes"][:5]],
                            "facts": [f["text"] for f in p.get("facts", [])]}
                  for p in map(store.person, ended.people) if p}
        first_call = {p["id"]: not p["encounters"] for p in map(store.person, ended.people) if p}
        if not people or not ended.lines:
            return  # the finally below still refreshes their files
        for s in picks.summarise(people, ended.lines):
            spoke = any(l.startswith(f"{people[s['personId']]['name']}: ") for l in ended.lines)  # a caption under their name
            store.add_encounter(s["personId"], ended.started.astimezone(), s["about"], s["lastTime"],
                                ended.topic[:TOPIC_CHARS], spoke, s["context"])
            lasts[s["personId"]] = s["lastTime"]
            if s["role"]:
                store.set_role(s["personId"], s["role"], "muse")  # never replaces a role the user typed
            store.add_facts(s["personId"], s["facts"])
            if first_call.get(s["personId"]):
                store.set_how_met(s["personId"], how_met(ended))
    except Exception as e:  # e.g. no MODEL_API_KEY: the call still ends and its note is still written
        print(f"encounter summaries skipped: {e}")
    finally:
        for pid in ended.people:
            try:
                notes.write_person(pid)
            except Exception as e:
                print(f"person file skipped: {e}")
    return lasts


def saw_face(card: dict | None) -> None:
    """Count this face toward the current call and restart the idle countdown that ends it."""
    global idle_timer
    current = this_call()
    people = current.people
    if latest_window and latest_window["app"]:
        current.app = latest_window["app"]
    if card:
        people.setdefault(card["id"], [])
    if idle_timer:
        idle_timer.cancel()
    idle_timer = asyncio.get_running_loop().call_later(CALL_IDLE_SECONDS, end_call)


async def push(event: dict) -> None:
    for ws in list(clients):
        try:
            await ws.send_json(event)
        except Exception:
            clients.discard(ws)


@app.websocket("/ws")
async def overlay_socket(ws: WebSocket):
    if not from_this_laptop(ws):  # the http middleware doesn't see WebSockets
        return await ws.close(code=1008)
    await ws.accept()
    for event in (listening, latest_insights, latest_window, latest_recap):  # catch up an overlay that starts mid-call
        if event:
            await ws.send_json(event)
    clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # the overlay never sends; this waits for the disconnect
    except WebSocketDisconnect:
        clients.discard(ws)


# --- faces (from capture/faces.py) ---

Number = Annotated[float, Field(allow_inf_nan=False)]  # NaN would make the next push fail and drop every overlay


class Debug(BaseModel):
    personBox: list[Number] = Field(min_length=4, max_length=4)
    faceBox: list[Number] | None = Field(default=None, min_length=4, max_length=4)
    fps: Number


class FaceTrack(BaseModel):
    trackId: int
    screenBox: list[Number] = Field(min_length=4, max_length=4)  # x, y, width, height in screen points
    facePrint: list[Number] | None = Field(default=None, min_length=512, max_length=512)
    debug: Debug | None = None  # only sent by capture in developer mode


class Gone(BaseModel):
    trackId: int


def card_for(face_print: list[float]) -> dict | None:
    person = store.match(np.asarray(face_print, dtype=np.float32))
    return card(person) if person else None


def card(person: dict) -> dict:
    """The face-event card for a store.match or store.person result."""
    met = person["firstMet"]
    last = store.last_time(person["id"])
    how, facts, seen = store.card_extras(person["id"])
    live = snippets.get(person["id"], [])
    base = [*facts, *([f"Last time: {last}"] if last else []), *([f"Met {how}"] if how else [])]
    bullets = base[:MAX_BULLETS - len(live)] + live  # what they say now pushes out the oldest history, last in the list
    return {
        "id": person["id"],
        "name": person["name"],
        "role": person["role"],
        "self": store.is_self(person["role"]),
        "line": f"Last time: {last}" if last else store.latest_note(person["id"]) or "",
        "met": f"Met {met:%b} {met.day}",
        **seen,
        "bullets": bullets,
    }


debug_scores: dict[int, float | None] = {}  # trackId -> best similarity of its print; filled only in developer mode


async def send_debug(t: FaceTrack) -> None:
    """Developer mode (HELLO_DEBUG=1 on the server): tell the debug view what the matcher thinks of this track."""
    if t.facePrint is not None:
        try:
            debug_scores[t.trackId] = await asyncio.to_thread(store.nearest_score, np.asarray(t.facePrint, dtype=np.float32))
        except Exception:  # the debug view must never break face tracking
            debug_scores[t.trackId] = None
    shown = tracks.get(t.trackId)
    decision = shown["name"] if shown else f"below {store.MATCH_MIN}" if t.trackId in debug_scores else "no face yet"
    await push({"type": "debug", "trackId": t.trackId, "personBox": t.debug.personBox, "faceBox": t.debug.faceBox,
                "score": debug_scores.get(t.trackId), "decision": decision, "fps": t.debug.fps})


@app.post("/faces")
async def faces(t: FaceTrack):
    debugging = t.debug is not None and os.getenv("HELLO_DEBUG") == "1"  # otherwise `debug` is ignored
    if t.facePrint is not None:
        tracks[t.trackId] = await asyncio.to_thread(card_for, t.facePrint)
    elif t.trackId not in tracks:
        if debugging:
            await send_debug(t)
        return {"needPrint": True}  # we restarted and lost this track; capture resends its print
    if tracks[t.trackId] is None:  # can't name them: hold the print in RAM in case they agree to be remembered
        if t.facePrint is not None:
            unknown[t.trackId] = {"print": t.facePrint}
        if t.trackId in unknown:
            unknown[t.trackId]["box"] = t.screenBox
    boxes[t.trackId] = t.screenBox
    saw_face(tracks[t.trackId])
    await push({"type": "face", "trackId": t.trackId, "screenBox": t.screenBox, "person": tracks[t.trackId]})
    if debugging:
        await send_debug(t)
    return {"person": tracks[t.trackId]}


class Window(BaseModel):
    app: str | None  # the followed app's name, e.g. "zoom.us"; null together with rect
    rect: list | None  # checked by hand: pydantic's own 422 would echo an infinite number back and fail to serialize it


def good_rect(rect: list | None) -> bool:
    nums = isinstance(rect, list) and len(rect) == 4 and all(type(n) in (int, float) and math.isfinite(n) for n in rect)
    return rect is None or (nums and rect[2] > 0 and rect[3] > 0 and all(abs(n) <= 20000 for n in rect))  # screen points, with room to spare


@app.post("/window")
async def set_window(w: Window):
    global latest_window
    if not good_rect(w.rect):
        raise HTTPException(422, "rect must be null or [x, y, w, h] as finite numbers up to 20000 in size, with w and h above 0")
    if (w.app is None) != (w.rect is None) or (w.app is not None and not 0 < len(w.app.strip()) <= 100):
        raise HTTPException(422, "app and rect must both be null, or an app name (up to 100 characters) with its rect")
    latest_window = {"type": "window", "app": w.app and w.app.strip(), "rect": w.rect}
    await push(latest_window)
    return {"ok": True}


@app.post("/faces/gone")
async def face_gone(g: Gone):
    tracks.pop(g.trackId, None)
    unknown.pop(g.trackId, None)
    debug_scores.pop(g.trackId, None)
    boxes.pop(g.trackId, None)
    await push({"type": "face_gone", "trackId": g.trackId})
    return {"ok": True}


class Remember(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    consent: bool
    role: Annotated[str, StringConstraints(strip_whitespace=True, max_length=picks.ROLE_CHARS)] = ""
    connector: bool = False  # ticked: the Muse app may read this person


@app.post("/faces/{track_id}/remember")
async def remember(track_id: int, body: Remember):
    """Enroll the face on screen in this track from its print, once they've said yes; no photo needed."""
    if not body.consent:
        raise HTTPException(400, "Consent is required to remember someone. Nothing was saved.")
    face = unknown.pop(track_id, None)  # popped first, so a double click can't enroll them twice
    if face is None:
        raise HTTPException(409, "That face has left the call")
    pid, token = await asyncio.to_thread(store.enroll, body.name, np.asarray(face["print"], dtype=np.float32), None, body.role, body.connector)
    tracks[track_id] = await asyncio.to_thread(card_for, face["print"])
    saw_face(tracks[track_id])
    await push({"type": "face", "trackId": track_id, "screenBox": face["box"], "person": tracks[track_id]})
    return {"id": pid, "deleteToken": token}


# --- transcript (from capture/transcribe.py) and the pause button ---

class Line(BaseModel):
    speaker: str = Field(max_length=64)  # Muse diarization label, e.g. "speaker_0"
    text: str = Field(max_length=2000)
    final: bool = True


class SpeakerName(BaseModel):
    label: str = Field(max_length=64)
    name: str = Field(min_length=1, max_length=80)


class Listening(BaseModel):
    on: bool


@app.post("/speakers")
async def name_speaker(s: SpeakerName):
    # shortcut: voices are named by hand; upgrade by matching who is talking on video
    speakers[s.label] = s.name
    return {"ok": True}


def serp_status() -> str | None:
    from memory import serp  # last failure of a SerpApi call

    return serp.last_error


@app.get("/health")
async def health():
    """What the control bar's status dot shows: is the database up, are the keys set, is the mic feeding us."""
    try:
        await asyncio.wait_for(asyncio.to_thread(lambda: store.conn().execute("select 1")), 3)
        db = "ok"
    except Exception:  # down, unreachable or slow: all the same to the dot
        db = "error"
    return {"db": db, "muse": bool(os.getenv("MODEL_API_KEY")) and picks.status.error is None, "museError": picks.status.error,
            "serpapi": bool(os.getenv("SERPAPI_KEY")) and serp_status() is None, "serpapiError": serp_status(),
            "listening": listening["on"], "lastTranscriptAt": last_transcript_at}


@app.post("/listening")
async def set_listening(body: Listening):
    if body.on and not listening["on"] and call is None:
        listening["startedAt"] = utc_now()  # resuming outside a call starts a fresh timer
    listening["on"] = body.on
    await push(listening)
    return listening


@app.post("/transcript")
async def transcript(line: Line):
    global last_transcript_at
    if not listening["on"]:
        return {"ok": True, "ignored": True}  # paused: nothing is shown, kept or sent to Muse
    last_transcript_at = utc_now()
    who = speakers.get(line.speaker, line.speaker)
    await push({"type": "caption", "speaker": who, "text": line.text, "final": line.final})
    if line.final and line.text.strip():
        fresh.append(f"{who}: {line.text}")
        this_call().lines.append(f"{who}: {line.text}")
        wake.set()
        for shown in {c["id"]: c for c in tracks.values() if c}.values():
            if shown["name"] == who:
                note_said(shown["id"], who, line.text)
    return {"ok": True}


def note_said(pid: str, name: str, text: str) -> None:
    """Collect what recognized people say. Once LIVE_BULLET_SECONDS have passed, everyone with something new is
    checked in ONE Muse request, so a 10-person call costs one request a minute, not ten."""
    global live_since
    now = time.monotonic()
    live_since = live_since if live_since is not None else now
    live.setdefault(pid, {"name": name, "lines": []})["lines"].append(text)
    if now - live_since >= LIVE_BULLET_SECONDS:
        batch = {p: e for p, e in live.items() if sum(len(l.split()) for l in e["lines"]) >= LIVE_MIN_WORDS}
        live.clear()
        live_since = now
        if batch:
            task = asyncio.get_running_loop().create_task(live_bullets(batch, call))
            background.add(task)
            task.add_done_callback(background.discard)


async def live_bullets(batch: dict[str, dict], owner: Call | None) -> None:
    """Ask Muse once for new "This call: …" facts about everyone in the batch and re-send each changed card."""
    try:
        asked = {pid: {**e, "earlier": snippets.get(pid, [])} for pid, e in batch.items()}
        found = await asyncio.wait_for(asyncio.to_thread(picks.live_snippets, asked), OUTBOUND_SECONDS)
        if call is not owner:  # the call ended meanwhile
            return
        for pid, new in found.items():
            snippets[pid] = (snippets.get(pid, []) + [n for n in new if n not in snippets.get(pid, [])])[-2:]
            person = await asyncio.to_thread(store.person, pid)
            if person is None:  # deleted themselves while Muse thought
                snippets.pop(pid, None)
                continue
            for t, shown in list(tracks.items()):
                if shown and shown["id"] == pid:
                    tracks[t] = await asyncio.to_thread(card, person)
                    if t in boxes:
                        await push({"type": "face", "trackId": t, "screenBox": boxes[t], "person": tracks[t]})
    except Exception as e:  # a failed check just means no new bullets
        print(f"live bullets skipped: {e!r}")


async def insights_worker() -> None:
    global last_refresh
    muse_down = False
    while True:
        await wake.wait()
        wake.clear()
        if last_refresh is not None:  # the first refresh of a call goes out at once, later ones keep the pace
            await asyncio.sleep(max(0, last_refresh + INSIGHTS_SECONDS - time.monotonic()))
        last_refresh = time.monotonic()  # paced from the start, so Muse's own delay doesn't add to the wait
        try:
            await refresh_insights()
            if picks.status.error is None:
                muse_down = False
        except (picks.MuseError, TimeoutError) as e:  # an outage or a missing key: say so once, keep listening
            print(f"insights failed: {type(e).__name__}")
            if not muse_down:
                muse_down = True
                line = "Muse is unreachable; still listening" if os.getenv("MODEL_API_KEY") else "Add MODEL_API_KEY to .env; still listening"
                await push({"type": "insights", "topic": line, "points": [], "actions": []})
        except Exception as e:  # a failed note insert must not stop the stream
            print(f"insights failed: {e!r}")


async def refresh_insights() -> None:
    """One Muse Spark call over the fresh lines: store notes about people, then push the whole insights state."""
    global latest_insights
    new = fresh[:]
    fresh.clear()
    if not new:
        return  # the call they belonged to has ended
    owner = call  # the call these lines belong to
    present = {p["id"]: p for p in tracks.values() if p}
    try:
        known = await asyncio.to_thread(store.notes_for, list(present))
        people = {pid: {"name": p["name"], "role": p.get("role", ""), "notes": known.get(pid, [])} for pid, p in present.items()}
        out = await asyncio.wait_for(asyncio.to_thread(picks.extract, people, history[-12:], new), OUTBOUND_SECONDS)
    finally:
        if call is owner:  # a call that ended meanwhile took its transcript with it
            history.extend(new)
            del history[:-20]

    for note in out["notes"]:
        if len(owner.people.get(note["personId"], [])) >= picks.MAX_NOTES_PER_CALL:
            continue
        try:
            await asyncio.to_thread(store.add_note, note["personId"], note["text"])
        except psycopg.errors.ForeignKeyViolation:
            continue  # they deleted themselves while Muse thought
        owner.people.setdefault(note["personId"], []).append(note["text"])
    if call is not owner or not (out["topic"] or out["points"] or out["actions"]):
        return  # the call ended while Muse thought, or the reply was unusable: leave the panel as it is
    owner.points = (owner.points + [p for p in out["points"] if p not in owner.points])[-NOTE_POINTS:]
    shown = []
    for action in out["actions"]:
        aid = "a" + uuid.uuid4().hex[:7]
        actions[aid] = action
        shown.append({"id": aid, "kind": action["kind"], "label": action["label"]})
    while len(actions) > MAX_ACTIONS_KEPT:
        del actions[next(iter(actions))]
    latest_insights = {"type": "insights", "topic": out["topic"], "points": out["points"], "actions": shown}
    await push(latest_insights)


# --- AI response panel (overlay Ask AI and action clicks) ---

class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    new: bool = False  # start a fresh thread instead of following up


class NoAnswer(Exception):
    """Ends a response as an error with this message for the user."""


@app.post("/ask")
async def ask(q: Ask, tasks: BackgroundTasks):
    question = q.question.strip()
    if not question:
        raise HTTPException(422, "Type a question first.")
    if q.new:
        clear_thread()
    return await respond(tasks, question, "ask", question)


@app.post("/actions/{aid}")
async def run_action(aid: str, tasks: BackgroundTasks):
    action = actions.get(aid)
    if action is None:
        raise HTTPException(404, "That action is no longer available. Pick one from the latest insights.")
    return await respond(tasks, action["label"], action["kind"], action["personId"] or action["query"])


async def respond(tasks: BackgroundTasks, query: str, kind: str, arg: str | None) -> dict:
    """Push 'thinking' now and the answer after the HTTP reply; the overlay matches them by id."""
    event = {"type": "response", "id": "r" + uuid.uuid4().hex[:7], "query": query,
             "status": "thinking", "text": "", "sources": []}
    await push(event)
    present = {p["id"]: p["name"] for p in tracks.values() if p}
    tasks.add_task(finish, event, kind, arg, present, history[-12:] + fresh, thread[:], thread_epoch)
    return {"id": event["id"]}


def clear_thread() -> None:
    global thread_epoch
    thread.clear()
    thread_epoch += 1  # an answer still on its way belongs to the old thread and is dropped


async def finish(event: dict, kind: str, arg: str | None, present: dict[str, str], lines: list[str],
                 earlier: list[tuple[str, str]], epoch: int) -> None:
    try:
        text, sources = await asyncio.wait_for(asyncio.to_thread(answer, kind, arg, present, lines, earlier), OUTBOUND_SECONDS)
        event = event | {"status": "done", "text": text, "sources": sources}
        if kind == "ask" and epoch == thread_epoch:
            thread.append((event["query"], text))
            del thread[:-THREAD_TURNS]
        if call and kind != "recall":  # recall only repeats the database, about someone who may delete themselves
            call.responses.append(event)
    except (NoAnswer, picks.MuseError, pipeline.SerpApiError) as e:
        event = event | {"status": "error", "text": str(e)}
    except TimeoutError:
        event = event | {"status": "error", "text": "That took too long to answer. Try again."}
    except Exception as e:  # never leave the panel stuck on "thinking"
        print(f"response failed: {e!r}")
        event = event | {"status": "error", "text": "Something went wrong answering that. Try again."}
    await push(event)


def answer(kind: str, arg: str | None, present: dict[str, str], lines: list[str],
           earlier: list[tuple[str, str]] | None = None) -> tuple[str, list[dict]]:
    """Runs in a thread: the text and sources for one question or action."""
    if kind == "recall":
        return recall(arg), []
    if kind in ("places", "events"):
        return pipeline.lookup(kind, arg)  # SerpApi only through pipeline, for a query Muse wrote
    known = store.notes_for(list(present))
    people = {pid: {"name": name, "notes": known.get(pid, [])} for pid, name in present.items()}
    if kind == "search":
        return pipeline.search(arg, people, lines)
    return picks.answer(kind, arg or "", people, lines, thread=earlier if kind == "ask" else None), []


def recall(pid: str) -> str:
    person = store.person(pid)
    if person is None:
        raise NoAnswer("That person is no longer enrolled, so there's nothing to recall.")
    out = [f"{person['name']}, first met {notes.day(person['firstMet'])}."]
    if about := next((e["about"] for e in person["encounters"] if e["about"]), None):  # latest one Muse could write
        out.append(f"About: {about}")
    out += [f"Met {notes.day(e['metAt'].astimezone())}: {e['lastTime']}" for e in person["encounters"]]
    out += [f"- {n['text']}" for n in person["notes"]] or ["No notes about them yet."]
    return "\n".join(out)


@app.post("/calls/end")
async def calls_end():
    path = await end_call()
    return {"note": str(path) if path else None}


# --- enrollment (web/enroll.html, opened on the guest's own phone) ---

@app.get("/enroll")
def enroll_page():
    return FileResponse(WEB / "enroll.html")


enroll_hits: dict[str, list[float]] = {}  # IP address -> times of its recent POST /enroll attempts


def rate_limited(ip: str) -> bool:
    """Count this attempt; True once the IP has used up its enrollments for the last minute."""
    now = time.monotonic()
    for other in [k for k, v in enroll_hits.items() if v[-1] < now - 60]:
        del enroll_hits[other]  # keeps the table from growing with every phone that ever visited
    hits = [t for t in enroll_hits.get(ip, []) if t > now - 60]
    enroll_hits[ip] = hits + [now]
    return len(hits) >= ENROLLS_PER_MINUTE


@app.post("/enroll")
async def enroll(
    request: Request,
    name: str = Form(min_length=1, max_length=80),
    consent: bool = Form(),
    role: str = Form("", max_length=picks.ROLE_CHARS),
    connector: bool = Form(False),  # ticked on the enroll page: the Muse app may read them
    code: str = Form("", max_length=200),
    selfie: UploadFile = File(),
):
    if rate_limited(request.client.host if request.client else ""):
        raise HTTPException(429, "Too many tries from this device. Wait a minute and try again.")
    expected = os.getenv("ENROLL_CODE")  # unset: anyone who can reach the page may enroll
    if expected and not secrets.compare_digest(code.encode(), expected.encode()):
        raise HTTPException(403, "That invite link is missing its code or the code is wrong. Ask for a new link.")
    if not consent:
        raise HTTPException(400, "Consent is required to enroll. Nothing was saved.")
    if not name.strip():
        raise HTTPException(400, "A name is required to enroll. Nothing was saved.")
    data = await selfie.read(MAX_SELFIE_BYTES + 1)
    if len(data) > MAX_SELFIE_BYTES:
        raise HTTPException(413, "That photo is over 8 MB. Take a new selfie and try again.")
    from capture.embed import embed_image  # lazy: loads InsightFace only when someone enrolls

    face_print = await asyncio.to_thread(embed_image, data)
    if face_print is None:
        raise HTTPException(422, "No face found in that photo. Try again facing the camera in good light.")
    pid, token = await asyncio.to_thread(store.enroll, name.strip(), face_print, None, role.strip(), connector)  # the selfie is never kept
    return {"id": pid, "deleteToken": token}


@app.get("/people")
def list_people():
    return store.people()


@app.get("/people/stale")
def stale_people(days: int = Query(30, ge=1, le=3650)):
    """"Haven't talked in a while": people you last met at least `days` days ago, most overdue first."""
    return store.stale(days)


@app.get("/people/{pid}")
def get_person(pid: str):
    found = store.person(pid)
    if found is None:
        raise HTTPException(404, "Nobody with that id (or their consent has run out).")
    return found


class PersonEdit(BaseModel):
    role: Annotated[str, StringConstraints(strip_whitespace=True, max_length=picks.ROLE_CHARS)] | None = None
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)] | None = None


@app.patch("/people/{pid}")
async def edit_person(pid: str, body: PersonEdit):
    if await asyncio.to_thread(store.person, pid) is None:
        raise HTTPException(404, "Nobody with that id (or their consent has run out).")
    if body.name is not None:
        await asyncio.to_thread(store.rename, pid, body.name)
    if body.role is not None:  # what you type here is yours: Muse won't replace it
        await asyncio.to_thread(store.set_role, pid, body.role, "user")
    updated = await asyncio.to_thread(store.person, pid)
    await asyncio.to_thread(notes.write_person, pid)
    for t, shown in tracks.items():  # the next frame of a face on screen carries the new name and role
        if shown and shown["id"] == pid:
            tracks[t] = await asyncio.to_thread(card, updated)
    return updated


@app.delete("/people/{pid}")
async def forget(pid: str, request: Request, x_delete_token: str | None = Header(default=None)):
    mine = from_this_laptop(request)  # the dashboard needs no token; a phone on the Wi-Fi does
    if not mine and x_delete_token is None:
        raise HTTPException(403, "That delete link doesn't match. Nothing was deleted.")
    if not await asyncio.to_thread(store.delete_person, pid, None if mine else x_delete_token):  # also clears them from notes/
        raise HTTPException(404 if mine else 403, "Nobody with that id." if mine else "That delete link doesn't match. Nothing was deleted.")
    if call:
        call.people.pop(pid, None)  # not in this call's note, summary or recap from now on
    if latest_recap:
        latest_recap["people"] = [p for p in latest_recap["people"] if p["id"] != pid]
    snippets.pop(pid, None)
    live.pop(pid, None)
    clear_thread()  # an Ask AI answer may name them, and follow-ups would send that to Muse again
    for t, card in list(tracks.items()):  # their card comes off the screen, and nothing about them goes to Muse again
        if card and card["id"] == pid:
            for state in (tracks, unknown, boxes, debug_scores):
                state.pop(t, None)
            await push({"type": "face_gone", "trackId": t})
    return {"deleted": pid}
