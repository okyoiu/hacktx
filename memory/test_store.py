"""store.py, and the endpoints that read it, against the real database. Run with: uv run --env-file .env pytest
Every test makes its own people and deletes them afterwards; nothing else is touched."""
import json
import os
import secrets
import time
from datetime import datetime
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


def test_deleting_yourself_or_expiring_removes_your_section_from_call_notes(db, enroll, tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "NOTES", tmp_path)
    (a, ta), (b, _), (c, _) = enroll(random_print()), enroll(random_print()), enroll(random_print())
    people = [{**store.person(p), "learned": [f"fact about {p}"]} for p in (a, b, c)]
    path = tmp_path / "call.md"
    path.write_text(notes.render(datetime(2026, 10, 24, 15, 30), people, [], []))
    store.delete_person(a, "wrong-token")
    assert f"fact about {a}" in path.read_text()  # a refused delete changes nothing
    store.delete_person(a, ta)
    db.execute("update consents set expires_at = current_date - 1 where person_id = %s", (b,))
    store.purge_expired()
    text = path.read_text()
    assert f"fact about {a}" not in text and f"fact about {b}" not in text and f"fact about {c}" in text


def test_delete_tokens_are_stored_hashed_and_old_plain_ones_upgrade(db, enroll):
    pid, token = enroll(random_print())
    assert db.execute("select delete_token from people where id = %s", (pid,)).fetchone()[0] == store.digest(token)
    assert store.delete_person(pid, store.digest(token)) is False  # the stored hash is not a key

    old, _ = enroll(random_print())
    db.execute("update people set delete_token = 'plain-old-token' where id = %s", (old,))
    schema = (Path(store.__file__).with_name("schema.sql")).read_text()
    db.execute(schema)
    db.execute(schema)  # running it again changes nothing
    assert db.execute("select delete_token from people where id = %s", (old,)).fetchone()[0] == store.digest("plain-old-token")
    assert store.delete_person(old, "plain-old-token") is True


def test_a_role_you_typed_is_never_replaced_by_muses_suggestion(db, enroll):
    typed, _ = store.enroll("Test " + secrets.token_hex(3), random_print(), None, "Your team lead")
    guessed, _ = enroll(random_print())  # no role given
    try:
        assert store.person(typed)["role"] == "Your team lead" and store.person(guessed)["role"] == ""
        for pid in (typed, guessed):
            store.set_role(pid, "Recruiter at Meta", "muse")
        assert [store.person(p)["role"] for p in (typed, guessed)] == ["Your team lead", "Recruiter at Meta"]
        store.set_role(guessed, "Your friend", "user")  # the dashboard edit wins, and later suggestions can't undo it
        store.set_role(guessed, "Someone else", "muse")
        assert store.person(guessed)["role"] == "Your friend"
    finally:
        db.execute("delete from people where id = %s", (typed,))


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

    with TestClient(server.app, client=("127.0.0.1", 50000)) as http:
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


def test_encounters_newest_first_and_card_says_last_time(db, enroll):
    face = random_print()
    pid, _ = enroll(face)
    assert store.last_time(pid) is None and store.person(pid)["encounters"] == []
    assert server.card_for(face.tolist())["line"] == ""
    store.add_note(pid, "Moved to Austin")
    assert server.card_for(face.tolist())["line"] == "Moved to Austin"  # no encounter yet: latest note
    store.add_encounter(pid, datetime(2026, 9, 24, 18, 0).astimezone(), "Engineer", "Met at a climbing meetup.")
    store.add_encounter(pid, datetime(2026, 10, 24, 18, 0).astimezone(), "Engineer in Austin", "Talked about gyms near South Congress.")
    got = store.person(pid)["encounters"]
    assert [(e["about"], e["lastTime"]) for e in got] == [
        ("Engineer in Austin", "Talked about gyms near South Congress."), ("Engineer", "Met at a climbing meetup.")]
    assert server.card_for(face.tolist())["line"] == "Last time: Talked about gyms near South Congress."


def test_call_end_summarises_only_recognized_people(db, enroll, tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "NOTES", tmp_path)
    for name, value in {"call": None, "history": [], "fresh": [], "tracks": {}, "latest_insights": None, "speakers": {}}.items():
        monkeypatch.setattr(server, name, value)
    face, quiet_face = random_print(), random_print()
    pid, _ = enroll(face)
    quiet, _ = enroll(quiet_face)  # recognized, mostly asks questions, and Muse leaves them out
    name, quiet_name = store.person(pid)["name"], store.person(quiet)["name"]
    store.set_role(quiet, "Your friend", "user")
    prompts = []

    def muse(prompt: str) -> str:
        prompts.append(prompt)
        if "A video call just ended" in prompt:
            return json.dumps({"people": [
                {"personId": pid, "about": "Runner training for a marathon", "lastTime": "Talked about the March race.", "role": "Running buddy"},
                {"personId": "p_stranger", "about": "Not in the call", "lastTime": "Never stored"},
            ]})
        return json.dumps({"topic": "", "points": [], "actions": []})

    monkeypatch.setattr(picks, "chat", muse)
    with TestClient(server.app, client=("127.0.0.1", 50000)) as http:
        http.post("/faces", json={"trackId": 990011, "screenBox": [0, 0, 100, 100], "facePrint": face.tolist()})
        http.post("/faces", json={"trackId": 990014, "screenBox": [400, 0, 100, 100], "facePrint": quiet_face.tolist()})
        stranger = http.post("/faces", json={"trackId": 990012, "screenBox": [200, 0, 100, 100], "facePrint": random_print().tolist()})
        assert stranger.json()["person"] is None  # not enrolled
        http.post("/speakers", json={"label": "speaker_0", "name": name})
        http.post("/speakers", json={"label": "speaker_1", "name": quiet_name})
        http.post("/transcript", json={"speaker": "speaker_1", "text": "When is your race?", "final": True})
        http.post("/transcript", json={"speaker": "speaker_0", "text": "My race is in March.", "final": True})
        http.post("/calls/end")
        deadline = time.time() + 3
        while (store.last_time(pid) is None or store.last_time(quiet) is None or not store.person(pid)["role"]) and time.time() < deadline:
            time.sleep(0.05)
        assert [store.person(p)["role"] for p in (pid, quiet)] == ["Running buddy", "Your friend"]  # Muse fills in a missing role; one you typed stays

        summary = next(p for p in prompts if "A video call just ended" in p)
        roster = summary.split("<people>\n")[1].split("\n</people>")[0]
        assert roster.splitlines() == [f"{pid}: {name} (nothing yet)", f"{quiet}: {quiet_name} (nothing yet)"]  # no stranger
        assert f"{name}: My race is in March." in summary
        got = http.get(f"/people/{pid}").json()["encounters"]
        assert [(e["about"], e["lastTime"]) for e in got] == [("Runner training for a marathon", "Talked about the March race.")]
        assert [(e["about"], e["lastTime"]) for e in http.get(f"/people/{quiet}").json()["encounters"]] == [
            ("", "You were on a call together.")]

        again = http.post("/faces", json={"trackId": 990013, "screenBox": [0, 0, 100, 100], "facePrint": face.tolist()})
        assert again.json()["person"]["line"] == "Last time: Talked about the March race."
        rejoin = http.post("/faces", json={"trackId": 990015, "screenBox": [400, 0, 100, 100], "facePrint": quiet_face.tolist()})
        assert rejoin.json()["person"]["line"] == "Last time: You were on a call together."
        for track in (990011, 990012, 990013, 990014, 990015):
            http.post("/faces/gone", json={"trackId": track})
    assert db.execute("select count(*) from encounters where person_id = 'p_stranger'").fetchone()[0] == 0


def test_remember_from_the_call_enrolls_with_consent_and_no_photo(db, monkeypatch):
    for name, value in {"call": None, "tracks": {}, "unknown": {}}.items():
        monkeypatch.setattr(server, name, value)
    face = random_print()

    def saved_prints() -> int:
        return db.execute("select count(*) from faces where print = %s", (face,)).fetchone()[0]

    with TestClient(server.app, client=("127.0.0.1", 50000)) as http:
        assert http.post("/faces", json={"trackId": 990301, "screenBox": [0, 0, 100, 100], "facePrint": face.tolist()}).json() == {"person": None}
        assert saved_prints() == 0  # on screen and unknown: RAM only
        got = http.post("/faces/990301/remember", json={"name": "Kai Park", "consent": True}).json()
        try:
            person = http.get(f"/people/{got['id']}").json()
            assert person["name"] == "Kai Park" and saved_prints() == 1
            assert db.execute("select selfie is null from people where id = %s", (got["id"],)).fetchone()[0]
            assert server.card_for(face.tolist())["id"] == got["id"]  # recognized from now on
            http.post("/faces/gone", json={"trackId": 990301})
        finally:
            assert store.delete_person(got["id"], got["deleteToken"])  # the returned token works, and cleans up
    assert saved_prints() == 0


def test_remembering_someone_too_unlike_their_enrollment_makes_a_second_record(db, enroll, monkeypatch):
    for name, value in {"call": None, "tracks": {}, "unknown": {}}.items():
        monkeypatch.setattr(server, name, value)
    first = random_print()
    old_pid, _ = enroll(first)
    today = near(first, store.MATCH_MIN - 0.05)  # same person, but too unlike their enrollment to be recognized

    with TestClient(server.app, client=("127.0.0.1", 50000)) as http:
        assert http.post("/faces", json={"trackId": 990401, "screenBox": [0, 0, 100, 100], "facePrint": today.tolist()}).json() == {"person": None}
        got = http.post("/faces/990401/remember", json={"name": "Same Person", "consent": True}).json()
        try:
            assert got["id"] != old_pid  # agreed: a duplicate becomes a second record, nothing is merged
            assert server.card_for(today.tolist())["id"] == got["id"]
            assert server.card_for(first.tolist())["id"] == old_pid
            http.post("/faces/gone", json={"trackId": 990401})
        finally:
            store.delete_person(got["id"], got["deleteToken"])


def test_summary_without_model_key_is_skipped_and_logged(db, enroll, monkeypatch, capsys):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    picks.client.cache_clear()
    pid, _ = enroll(random_print())
    server.remember_encounters(server.Call(people={pid: []}, lines=["You: hello"]))  # returns instead of raising
    assert "encounter summaries skipped: Add MODEL_API_KEY to .env" in capsys.readouterr().out
    assert store.last_time(pid) is None
