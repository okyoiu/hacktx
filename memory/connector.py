"""Read-only routes for a Muse custom connector. The Muse app calls them through a tunnel with a bearer key, so these are the
only routes that skip the laptop-only rule. They return names, labels and what was learned, never face prints or tokens."""
import os
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request

from memory import store

router = APIRouter(prefix="/connector")
FAILS_PER_MINUTE = 20  # wrong keys, all callers together: through a tunnel every caller looks the same
failures: list[float] = []

SUMMARY = ("Hello Again memory: people the user has met on video calls, who agreed to be remembered. For each person: "
           "who they are to the user, when they last met and last spoke, what the last conversation was about, whether it was "
           "work or personal (context), plain facts they shared about themselves, how they first met (howMet), and the user's own notes. Read-only; there is nothing to change.")


def require_key(request: Request) -> None:
    key = os.getenv("MUSE_CONNECTOR_KEY")
    if not key:
        raise HTTPException(404, "Not found")  # not set up: these routes do not exist
    given = request.headers.get("authorization", "")
    if given.startswith("Bearer ") and secrets.compare_digest(given[7:].encode(), key.encode()):
        return  # the right key always gets in; only wrong ones are counted, so strangers can't lock Muse out
    now = time.monotonic()
    failures[:] = [t for t in failures if t > now - 60]
    if len(failures) >= FAILS_PER_MINUTE:
        raise HTTPException(429, "Too many wrong keys. Wait a minute.")
    failures.append(now)
    raise HTTPException(401, "Missing or wrong key", headers={"WWW-Authenticate": "Bearer"})


@router.get("/health")
def health():
    return {"ok": True}  # for the tunnel check; says nothing about the data


@router.get("/people", dependencies=[Depends(require_key)])
def people():
    keep = ("id", "name", "role", "lastSeen", "lastSpoke", "topic", "context")
    return [{k: p[k] for k in keep} for p in store.people() if "connector" in p["scope"]]  # only people who ticked it


@router.get("/people/{pid}", dependencies=[Depends(require_key)])
def one_person(pid: str):
    p = store.person(pid)
    if p is None or "connector" not in p["scope"]:
        raise HTTPException(404, "Nobody with that id (or they did not agree to the connector).")
    latest = p["encounters"][0] if p["encounters"] else None
    return {**{k: p[k] for k in ("id", "name", "role", "lastSeen", "lastSpoke", "topic", "context", "howMet")},
            "facts": [f["text"] for f in p["facts"]],
            "about": latest["about"] if latest else None, "lastTime": latest["lastTime"] if latest else None,
            "notes": [n["text"] for n in p["notes"]]}


def schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


STR, NULLABLE = {"type": "string"}, {"type": ["string", "null"]}
PERSON = {"id": STR, "name": STR, "role": {"type": "string", "description": "Who they are to the user, e.g. Your team lead; may be empty"},
          "lastSeen": {**NULLABLE, "description": "Date (YYYY-MM-DD) of the latest call they were on; null if none yet"},
          "lastSpoke": {**NULLABLE, "description": "Date of the latest call where they spoke"},
          "topic": {**NULLABLE, "description": "What that latest call was about"},
          "context": {**NULLABLE, "description": "work, personal, or empty when unsure"}}
OPENAPI = {
    "openapi": "3.1.0",
    "info": {"title": "Hello Again memory", "version": "1.0.0", "description": SUMMARY},
    "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}},
    "security": [{"bearer": []}],
    "paths": {
        "/connector/people": {"get": {
            "operationId": "listPeople", "summary": "Everyone the user remembers, with when they last met",
            "responses": {"200": {"description": "People", "content": {"application/json": {"schema": {
                "type": "array", "items": schema(PERSON, list(PERSON))}}}}}}},
        "/connector/people/{id}": {"get": {
            "operationId": "getPerson", "summary": "One person in full: facts, how they met, the last conversation and notes",
            "parameters": [{"name": "id", "in": "path", "required": True, "schema": STR}],
            "responses": {"200": {"description": "The person", "content": {"application/json": {"schema": schema(PERSON | {
                "howMet": {"type": "string", "description": "One line about the first call together: date, app and what it was about; may be empty"},
                "facts": {"type": "array", "items": STR}, "about": NULLABLE, "lastTime": NULLABLE,
                "notes": {"type": "array", "items": STR, "description": "The user's own notes"}}, ["id", "name"])}}},
                          "404": {"description": "Unknown person"}}}},
    },
}


@router.get("/openapi.json", dependencies=[Depends(require_key)])
def openapi_document():
    return OPENAPI
