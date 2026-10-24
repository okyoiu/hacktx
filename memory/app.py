"""Memory service: matches faces, turns Muse transcripts into top picks, and pushes both to the overlay.

Run: uv run --env-file .env uvicorn memory.app:app --reload
Keep it on localhost or your LAN; nothing here is authenticated except deleting a person.
"""
import asyncio
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np
from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from memory import notes, pipeline, store

WEB = Path(__file__).resolve().parent.parent / "web"
MAX_SELFIE_BYTES = 8_000_000
REPEAT_SECONDS = 300
CALL_IDLE_SECONDS = 60  # a call ends this long after the last face was seen

app = FastAPI(title="Hello Again memory")
clients: set[WebSocket] = set()
tracks: dict[int, dict | None] = {}  # trackId -> card for the matched person (None = not enrolled)
speakers: dict[str, str] = {}  # Muse speaker label -> display name
history: list[str] = []  # recent lines, context for Muse Spark
recent_titles: dict[str, float] = {}  # lowercased pick title -> when it was last pushed


@dataclass
class Call:
    started: datetime = field(default_factory=datetime.now)
    people: dict[str, list[str]] = field(default_factory=dict)  # recognized person id -> notes learned this call
    picks: list[dict] = field(default_factory=list)  # pick events pushed this call


call: Call | None = None  # None between calls
idle_timer: asyncio.TimerHandle | None = None


def this_call() -> Call:
    global call
    call = call or Call()
    return call


def end_call() -> asyncio.Future:
    """Close the current call and write its note in a thread; the future resolves to the note's path or None."""
    global call
    if idle_timer:
        idle_timer.cancel()
    ended, call = call or Call(), None
    return asyncio.get_running_loop().run_in_executor(None, notes.write, ended.started, ended.people, ended.picks)


def saw_face(card: dict | None) -> None:
    """Count this face toward the current call and restart the idle countdown that ends it."""
    global idle_timer
    people = this_call().people
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
    await ws.accept()
    clients.add(ws)
    try:
        while True:
            await ws.receive_text()  # the overlay never sends; this waits for the disconnect
    except WebSocketDisconnect:
        clients.discard(ws)


# --- faces (from capture/faces.py) ---

class FaceTrack(BaseModel):
    trackId: int
    screenBox: list[float] = Field(min_length=4, max_length=4)  # x, y, width, height in screen points
    facePrint: list[float] | None = Field(default=None, min_length=512, max_length=512)


class Gone(BaseModel):
    trackId: int


def card_for(face_print: list[float]) -> dict | None:
    person = store.match(np.asarray(face_print, dtype=np.float32))
    if person is None:
        return None
    met = person["firstMet"]
    return {
        "id": person["id"],
        "name": person["name"],
        "line": store.latest_note(person["id"]) or "",
        "met": f"Met {met:%b} {met.day}",
    }


@app.post("/faces")
async def faces(t: FaceTrack):
    if t.facePrint is not None:
        tracks[t.trackId] = await asyncio.to_thread(card_for, t.facePrint)
    elif t.trackId not in tracks:
        return {"needPrint": True}  # we restarted and lost this track; capture resends its print
    saw_face(tracks[t.trackId])
    await push({"type": "face", "trackId": t.trackId, "screenBox": t.screenBox, "person": tracks[t.trackId]})
    return {"person": tracks[t.trackId]}


@app.post("/faces/gone")
async def face_gone(g: Gone):
    tracks.pop(g.trackId, None)
    await push({"type": "face_gone", "trackId": g.trackId})
    return {"ok": True}


# --- transcript (from capture/transcribe.py) ---

class Line(BaseModel):
    speaker: str = Field(max_length=64)  # Muse diarization label, e.g. "speaker_0"
    text: str = Field(max_length=2000)
    final: bool = True


class SpeakerName(BaseModel):
    label: str = Field(max_length=64)
    name: str = Field(min_length=1, max_length=80)


@app.post("/speakers")
async def name_speaker(s: SpeakerName):
    # shortcut: voices are named by hand; upgrade by matching who is talking on video
    speakers[s.label] = s.name
    return {"ok": True}


@app.post("/transcript")
async def transcript(line: Line, tasks: BackgroundTasks):
    who = speakers.get(line.speaker, line.speaker)
    await push({"type": "caption", "speaker": who, "text": line.text, "final": line.final})
    if line.final and line.text.strip():
        tasks.add_task(make_picks, who, line.text)
    return {"ok": True}


def seen_recently(title: str, now: float) -> bool:
    """True if a pick with this title went out in the last REPEAT_SECONDS; otherwise record it as sent now."""
    for k in [k for k, t in recent_titles.items() if now - t >= REPEAT_SECONDS]:
        del recent_titles[k]
    key = title.strip().lower()
    if key in recent_titles:
        return True
    recent_titles[key] = now
    return False


async def make_picks(who: str, text: str) -> None:
    present = {p["id"]: p for p in tracks.values() if p}
    try:
        known = await asyncio.to_thread(store.notes_for, list(present))
        people = {pid: {"name": p["name"], "notes": known.get(pid, [])} for pid, p in present.items()}
        out = await asyncio.to_thread(pipeline.process, who, text, people, history[-6:])
    except Exception as e:  # one failed model call must not stop the stream
        print(f"picks failed: {e!r}")
        return
    finally:
        history.append(f"{who}: {text}")
        del history[:-20]

    for note in out["notes"]:
        await asyncio.to_thread(store.add_note, note["personId"], note["text"])
        this_call().people.setdefault(note["personId"], []).append(note["text"])
    for pick in out["picks"]:
        if seen_recently(pick["title"], time.monotonic()):  # after SerpApi, so two searches landing on one place count once
            continue
        event = {
            "type": "pick",
            "id": uuid.uuid4().hex[:8],
            "kind": pick["kind"],
            "title": pick["title"],
            "detail": pick["detail"],
            "quote": text,
            "speaker": who,
        }
        this_call().picks.append(event)
        await push(event)


@app.post("/calls/end")
async def calls_end():
    path = await end_call()
    return {"note": str(path) if path else None}


# --- enrollment (web/enroll.html, opened on the guest's own phone) ---

@app.get("/enroll")
def enroll_page():
    return FileResponse(WEB / "enroll.html")


@app.post("/enroll")
async def enroll(
    name: str = Form(min_length=1, max_length=80),
    consent: bool = Form(),
    selfie: UploadFile = File(),
):
    if not consent:
        raise HTTPException(400, "Consent is required to enroll. Nothing was saved.")
    data = await selfie.read(MAX_SELFIE_BYTES + 1)
    if len(data) > MAX_SELFIE_BYTES:
        raise HTTPException(413, "That photo is over 8 MB. Take a new selfie and try again.")
    from capture.embed import embed_image  # lazy: loads InsightFace only when someone enrolls

    face_print = await asyncio.to_thread(embed_image, data)
    if face_print is None:
        raise HTTPException(422, "No face found in that photo. Try again facing the camera in good light.")
    pid, token = await asyncio.to_thread(store.enroll, name.strip(), face_print, data)
    return {"id": pid, "deleteToken": token}


@app.get("/people/{pid}")
def get_person(pid: str):
    found = store.person(pid)
    if found is None:
        raise HTTPException(404, "Nobody with that id (or their consent has run out).")
    return found


@app.delete("/people/{pid}")
def forget(pid: str, x_delete_token: str = Header()):
    if not store.delete_person(pid, x_delete_token):
        raise HTTPException(403, "That delete link doesn't match. Nothing was deleted.")
    return {"deleted": pid}
