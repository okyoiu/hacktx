"""Insights, pause and AI responses through the real endpoints, with fake Muse Spark and SerpApi: no keys or database."""
import json
import time
from datetime import date, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from memory import app as server
from memory import notes, picks, serp, store

JORDAN = {"id": "p_jordan", "name": "Jordan Lee", "line": "", "met": "Met Sep 24"}


class FakeMuse:
    """Stands in for picks.chat: insights JSON for refreshes, a fixed answer for everything else."""

    def __init__(self, insights: dict | None = None):
        self.insights = insights or {}
        self.prompts: list[str] = []
        self.times: list[float] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        self.times.append(time.monotonic())
        return json.dumps(self.insights) if "New lines:" in prompt else "Answer from Muse"


def fake_serpapi(url, params, timeout):
    request = httpx.Request("GET", url)
    if params["engine"] == "google":
        hits = [{"title": f"Result {i}", "link": f"https://example.com/{i}", "snippet": f"snippet {i}"} for i in range(4)]
        return httpx.Response(200, json={"organic_results": [{"title": "No link"}] + hits}, request=request)
    if params["engine"] == "google_maps":
        return httpx.Response(200, json={"local_results": [{"title": "Ledge", "type": "Climbing gym", "address": "1 Main St"}]}, request=request)
    return httpx.Response(200, json={"events_results": []}, request=request)


@pytest.fixture
def http(monkeypatch, tmp_path):
    """A fresh server: no call, transcript, insights or faces, and listening."""
    state = {"call": None, "history": [], "fresh": [], "actions": {}, "latest_insights": None, "tracks": {},
             "speakers": {}, "clients": set(), "listening": {"type": "listening", "on": True, "startedAt": "2026-10-24T20:00:00Z"}}
    for name, value in state.items():
        monkeypatch.setattr(server, name, value)
    monkeypatch.setattr(server, "INSIGHTS_SECONDS", 0.3)
    monkeypatch.setattr(notes, "NOTES", tmp_path)
    monkeypatch.setattr(store, "notes_for", lambda pids, per_person=5: {})
    serp._lookup.cache_clear()
    serp._search.cache_clear()
    with TestClient(server.app) as client:
        yield client


@pytest.fixture
def events(monkeypatch):
    """Every event the server pushes, copied as it was sent."""
    seen: list[dict] = []

    async def record(event: dict) -> None:
        seen.append(dict(event))

    monkeypatch.setattr(server, "push", record)
    return seen


def wait_for(check, timeout: float = 3) -> None:
    deadline = time.time() + timeout
    while not check():
        assert time.time() < deadline, "timed out"
        time.sleep(0.02)


def line(speaker: str, text: str, final: bool = True) -> dict:
    return {"speaker": speaker, "text": text, "final": final}


def test_insights_refresh_at_most_every_interval_and_actions_answer(http, events, monkeypatch):
    muse = FakeMuse({"topic": "Jordan's move", "points": ["Jordan moved to Austin"],
                     "actions": [{"kind": "followups", "label": "Suggest follow-up questions"}]})
    monkeypatch.setattr(picks, "chat", muse)

    http.post("/transcript", json=line("speaker_0", "We moved to Austin."))
    http.post("/transcript", json=line("speaker_0", "partial words", final=False))
    wait_for(lambda: len(muse.prompts) == 1)
    http.post("/transcript", json=line("speaker_1", "Found a gym yet?"))
    http.post("/transcript", json=line("speaker_0", "Not yet."))
    wait_for(lambda: len(muse.prompts) == 2)
    time.sleep(server.INSIGHTS_SECONDS * 2)

    assert len(muse.prompts) == 2  # no new lines, no third call
    assert muse.times[1] - muse.times[0] >= server.INSIGHTS_SECONDS
    assert "New lines:\nspeaker_1: Found a gym yet?\nspeaker_0: Not yet." in muse.prompts[1]
    assert "speaker_0: We moved to Austin." in muse.prompts[1].split("New lines:")[0]
    assert "partial words" not in "".join(muse.prompts)
    assert [e["final"] for e in events if e["type"] == "caption"] == [True, False, True, True]

    insights = [e for e in events if e["type"] == "insights"]
    assert len(insights) == 2 and insights[-1] == server.latest_insights
    action = insights[-1]["actions"][0]
    assert insights[-1]["topic"] == "Jordan's move" and insights[-1]["points"] == ["Jordan moved to Austin"]
    assert set(action) == {"id", "kind", "label"} and action["kind"] == "followups"

    rid = http.post(f"/actions/{action['id']}").json()["id"]
    assert [(e["status"], e["text"]) for e in events if e.get("id") == rid] == [("thinking", ""), ("done", "Answer from Muse")]
    assert "Suggest three short follow-up questions" in muse.prompts[-1] and "Not yet." in muse.prompts[-1]


def test_next_call_does_not_see_the_last_calls_insights_or_transcript(http, events, monkeypatch):
    muse = FakeMuse({"topic": "Old call", "points": ["Something private"], "actions": []})
    monkeypatch.setattr(picks, "chat", muse)
    http.post("/transcript", json=line("speaker_0", "Last call's private line"))
    wait_for(lambda: server.latest_insights is not None)

    http.post("/calls/end")
    assert server.latest_insights is None  # a newly connected overlay gets no stale insights
    http.post("/transcript", json=line("speaker_0", "New call starts"))
    wait_for(lambda: len(muse.prompts) == 2)
    assert "Last call's private line" not in muse.prompts[1]


def test_pause_ignores_transcript_and_resume_restarts_timer_only_between_calls(http, events):
    paused = http.post("/listening", json={"on": False}).json()
    assert paused == {"type": "listening", "on": False, "startedAt": "2026-10-24T20:00:00Z"} and events == [paused]
    assert http.post("/transcript", json=line("speaker_0", "Off the record")).json()["ignored"]
    assert server.fresh == [] and len(events) == 1  # no caption, nothing kept

    resumed = http.post("/listening", json={"on": True}).json()
    assert resumed["on"] and resumed["startedAt"] != paused["startedAt"] and events[-1] == resumed

    server.this_call()  # a call is in progress: the timer keeps counting through a pause
    server.listening["startedAt"] = "2026-10-24T20:05:00Z"
    http.post("/listening", json={"on": False})
    assert http.post("/listening", json={"on": True}).json()["startedAt"] == "2026-10-24T20:05:00Z"


def test_overlay_connecting_gets_listening_then_insights_first(http):
    with http.websocket_connect("/ws") as ws:
        assert ws.receive_json() == server.listening  # no insights yet: listening only
        http.post("/listening", json={"on": False})
        assert ws.receive_json()["on"] is False
    server.latest_insights = {"type": "insights", "topic": "Jordan's move", "points": [], "actions": []}
    with http.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "listening"
        assert ws.receive_json() == server.latest_insights


def test_every_action_kind_and_ask_answer_and_land_in_the_call_note(http, events, monkeypatch):
    muse = FakeMuse()
    monkeypatch.setattr(picks, "chat", muse)
    monkeypatch.setenv("SERPAPI_KEY", "test-key")
    monkeypatch.setattr(serp.httpx, "get", fake_serpapi)
    monkeypatch.setattr(store, "person", lambda pid: {
        "id": pid, "name": "Jordan Lee", "firstMet": date(2025, 9, 24),
        "encounters": [{"metAt": datetime(2026, 10, 2, 18, 0).astimezone(), "about": "Engineer who climbs", "lastTime": "Planned the move."},
                       {"metAt": datetime(2025, 9, 24, 18, 0).astimezone(), "about": "Engineer", "lastTime": "Met at a meetup."}],
        "notes": [{"text": "Started climbing"}, {"text": "Moved to Austin"}],
    })
    server.tracks[1] = JORDAN
    server.actions.update({
        "a_define": {"kind": "define", "label": "What is bouldering?", "query": "bouldering", "personId": None},
        "a_search": {"kind": "search", "label": "Search climbing gyms", "query": "climbing gyms austin", "personId": None},
        "a_places": {"kind": "places", "label": "Find climbing gyms", "query": "climbing gyms", "personId": None},
        "a_events": {"kind": "events", "label": "Find a meetup", "query": "climbing meetup", "personId": None},
        "a_recall": {"kind": "recall", "label": "Remind me who Jordan is", "query": None, "personId": "p_jordan"},
        "a_helpful": {"kind": "helpful", "label": "Give me helpful information", "query": None, "personId": None},
    })

    def run(path: str, body: dict | None = None) -> dict:
        rid = http.post(path, json=body).json()["id"]
        sent = [e for e in events if e.get("id") == rid]
        assert [e["status"] for e in sent] == ["thinking", "done"]
        assert sent[0]["query"] == sent[1]["query"]
        return sent[1]

    assert run("/actions/a_define")["text"] == "Answer from Muse"
    assert 'Explain "bouldering"' in muse.prompts[-1] and "p_jordan: Jordan Lee" in muse.prompts[-1]
    found = run("/actions/a_search")
    assert found["sources"] == [{"title": f"Result {i}", "url": f"https://example.com/{i}"} for i in range(3)]
    assert "[3] Result 2: snippet 2 (https://example.com/2)" in muse.prompts[-1] and "Result 3" not in muse.prompts[-1]
    place = run("/actions/a_places")
    assert place["text"] == "Ledge\nClimbing gym · 1 Main St"
    assert place["sources"] == [{"title": "Ledge", "url": "https://www.google.com/maps/search/?api=1&query=Ledge"}]
    assert run("/actions/a_events")["text"] == 'Nothing found for "climbing meetup".'
    assert run("/actions/a_recall")["text"] == (
        "Jordan Lee, first met Sep 24, 2025.\nAbout: Engineer who climbs\n"
        "Met Oct 2, 2026: Planned the move.\nMet Sep 24, 2025: Met at a meetup.\n- Started climbing\n- Moved to Austin"
    )
    assert run("/actions/a_helpful")["text"] == "Answer from Muse"
    asked = run("/ask", {"question": "  Where should we eat? "})
    assert asked["query"] == "Where should we eat?" and "Answer their question: Where should we eat?" in muse.prompts[-1]

    assert http.post("/ask", json={"question": "   "}).status_code == 422
    assert http.post("/ask", json={"question": "x" * 501}).status_code == 422
    assert http.post("/actions/a_gone").status_code == 404

    note = http.post("/calls/end").json()["note"]
    text = open(note).read()
    assert "## AI responses" in text and "### Where should we eat?" in text
    assert "Sources: [Ledge](https://www.google.com/maps/search/?api=1&query=Ledge)" in text


def test_missing_keys_end_as_errors_and_never_crash(http, events, monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_KEY", raising=False)
    picks.client.cache_clear()
    server.actions.update({
        "a_search": {"kind": "search", "label": "Search gyms", "query": "gyms", "personId": None},
        "a_places": {"kind": "places", "label": "Find gyms", "query": "gyms", "personId": None},
        "a_define": {"kind": "define", "label": "Define bouldering", "query": "bouldering", "personId": None},
    })

    def error(path: str, body: dict | None = None) -> str:
        rid = http.post(path, json=body).json()["id"]
        sent = [e for e in events if e.get("id") == rid]
        assert [e["status"] for e in sent] == ["thinking", "error"]
        return sent[1]["text"]

    assert "Add MODEL_API_KEY to .env" in error("/ask", {"question": "Hi?"})
    assert "Add MODEL_API_KEY to .env" in error("/actions/a_define")
    assert "Add SERPAPI_KEY to .env" in error("/actions/a_search")
    assert "Add SERPAPI_KEY to .env" in error("/actions/a_places")

    monkeypatch.setattr(picks, "chat", lambda prompt: 1 / 0)
    assert error("/actions/a_define") == "Something went wrong answering that. Try again."

    http.post("/transcript", json=line("speaker_0", "Still talking"))  # insights fail quietly; the stream goes on
    wait_for(lambda: server.history == ["speaker_0: Still talking"])
    assert server.latest_insights is None
    assert http.post("/calls/end").json() == {"note": None}  # errors aren't written down
