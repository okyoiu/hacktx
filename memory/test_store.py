"""store.py, and the endpoints that read it, against the real database. Run with: uv run --env-file .env pytest
Every test makes its own people and deletes them afterwards; nothing else is touched."""
import json
import os
import secrets
import time
from pathlib import Path

import numpy as np
import psycopg
import pytest
from fastapi.testclient import TestClient

from memory import app as server
from memory import notes, picks, store


def unit(v: np.ndarray) -> np.ndarray:
    return (v / np.linalg.norm(v)).astype(np.float32)


def random_print() -> np.ndarray:
    return unit(np.random.default_rng().normal(size=512))


def near(a: np.ndarray, sim: float) -> np.ndarray:
    """A unit print whose cosine similarity to unit print a is exactly sim."""
    u = np.random.default_rng().normal(size=512)
    u = unit(u - u.dot(a) * a)
    return unit(sim * a + np.sqrt(1 - sim**2) * u)


@pytest.fixture(scope="module")
def db():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set: run uv run --env-file .env pytest")
    try:
        return store.conn()
    except psycopg.OperationalError as e:
        pytest.skip(f"database unreachable: {e}")


@pytest.fixture
def enroll(db):
    """store.enroll for a throwaway person; everyone it creates is deleted at teardown."""
    pids = []

    def make(face_print: np.ndarray) -> tuple[str, str]:
        pid, token = store.enroll("Test " + secrets.token_hex(3), face_print, b"selfie")
        pids.append(pid)
        return pid, token

    yield make
    db.execute("delete from people where id = any(%s)", (pids,))


def count(db, table: str, pid: str) -> int:
    col = "id" if table == "people" else "person_id"
    return db.execute(f"select count(*) from {table} where {col} = %s", (pid,)).fetchone()[0]


def test_enroll_saves_person_face_and_consent(db, enroll):
    face = random_print()
    pid, token = enroll(face)
    assert pid.startswith("p_") and token
    assert [count(db, t, pid) for t in ("people", "faces", "consents")] == [1, 1, 1]
    days = db.execute(
        "select c.expires_at - p.first_met from consents c join people p on p.id = c.person_id where p.id = %s", (pid,)
    ).fetchone()[0]
    assert days == store.CONSENT_DAYS
    assert store.match(face)["id"] == pid


def test_match_above_and_below_cutoff(enroll):
    face = random_print()
    pid, _ = enroll(face)
    hit = store.match(near(face, store.MATCH_MIN + 0.05))
    assert hit["id"] == pid and hit["score"] == pytest.approx(store.MATCH_MIN + 0.05, abs=0.01)
    assert store.match(near(face, store.MATCH_MIN - 0.05)) is None


def test_expired_consent_stops_matching_and_is_purged(db, enroll):
    face = random_print()
    pid, _ = enroll(face)
    db.execute("update consents set expires_at = current_date - 1 where person_id = %s", (pid,))
    assert store.match(face) is None
    store.purge_expired()
    assert [count(db, t, pid) for t in ("people", "faces", "consents")] == [0, 0, 0]


def test_delete_needs_the_right_token(db, enroll):
    pid, token = enroll(random_print())
    assert store.delete_person(pid, "wrong-token") is False
    assert count(db, "people", pid) == 1
    assert store.delete_person(pid, token) is True
    assert [count(db, t, pid) for t in ("people", "faces", "consents")] == [0, 0, 0]
    assert store.delete_person(pid, token) is False


def test_person_returns_notes_newest_first(db, enroll):
    pid, _ = enroll(random_print())
    store.add_note(pid, "Moved to Austin")
    store.add_note(pid, "Started climbing")
    got = store.person(pid)
    assert [n["text"] for n in got["notes"]] == ["Started climbing", "Moved to Austin"]
    assert got["firstMet"] is not None and got["name"].startswith("Test ")
    assert store.person("p_nobody") is None
    db.execute("update consents set expires_at = current_date - 1 where person_id = %s", (pid,))
    assert store.person(pid) is None


def test_call_note_on_end_and_after_faces_go_idle(db, enroll, tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "NOTES", tmp_path)
    monkeypatch.setattr(server, "CALL_IDLE_SECONDS", 30)
    for name, value in {"call": None, "history": [], "fresh": [], "tracks": {}, "latest_insights": None}.items():
        monkeypatch.setattr(server, name, value)
    face = random_print()
    pid, _ = enroll(face)
    name = store.person(pid)["name"]
    monkeypatch.setattr(picks, "chat", lambda prompt: json.dumps({
        "notes": [{"personId": pid, "text": "Training for a marathon"}],
        "topic": "Running", "points": ["They both run"], "actions": [],
    }))
    box = {"trackId": 990001, "screenBox": [0, 0, 100, 100]}

    with TestClient(server.app) as http:
        assert http.get(f"/people/{pid}").json()["name"] == name
        assert http.get("/people/p_nobody").status_code == 404

        assert http.post("/calls/end").json() == {"note": None}  # nothing happened, no file
        http.post("/faces", json=box | {"facePrint": face.tolist()})
        http.post("/transcript", json={"speaker": "You", "text": "Are you still running?", "final": True})
        deadline = time.time() + 3
        while not http.get(f"/people/{pid}").json()["notes"] and time.time() < deadline:
            time.sleep(0.05)
        assert http.get(f"/people/{pid}").json()["notes"][0]["text"] == "Training for a marathon"
        text = Path(http.post("/calls/end").json()["note"]).read_text()
        assert f"## {name}" in text and "- Training for a marathon" in text and "## Key points\n\n- They both run" in text

        def calls_written() -> int:
            return sum(f.read_text().count("# Call on") for f in tmp_path.glob("*.md"))

        monkeypatch.setattr(server, "CALL_IDLE_SECONDS", 0.2)
        http.post("/faces", json=box)  # same track still on screen: starts the next call, which then goes idle
        deadline = time.time() + 3
        while calls_written() < 2 and time.time() < deadline:
            time.sleep(0.05)
        http.post("/faces/gone", json={"trackId": 990001})
    assert calls_written() == 2 and server.call is None
