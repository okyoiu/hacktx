import json
from datetime import date, datetime

from memory import notes
from memory.notes import render
from memory.picks import parse, parse_summary
from memory.serp import first

KNOWN = {"p_jordan"}


def test_parse_reads_json_inside_fences_and_prose():
    reply = 'Sure!\n```json\n{"notes": [{"personId": "p_jordan", "text": " Moved to Austin "}], "topic": "Jordan\'s move", "points": ["Jordan moved to Austin"], "actions": [{"kind": "places", "label": "Find climbing gyms", "query": "climbing gym South Congress"}, {"kind": "recall", "label": "Remind me who Jordan is", "personId": "p_jordan"}, {"kind": "followups", "label": "Suggest follow-ups", "query": "ignored"}]}\n```'
    out = parse(reply, KNOWN)
    assert out["notes"] == [{"personId": "p_jordan", "text": "Moved to Austin"}]
    assert out["topic"] == "Jordan's move" and out["points"] == ["Jordan moved to Austin"]
    assert out["actions"] == [
        {"kind": "places", "label": "Find climbing gyms", "query": "climbing gym South Congress", "personId": None},
        {"kind": "recall", "label": "Remind me who Jordan is", "query": None, "personId": "p_jordan"},
        {"kind": "followups", "label": "Suggest follow-ups", "query": None, "personId": None},
    ]


def test_parse_drops_unknown_people_bad_kinds_and_caps_lists():
    reply = json.dumps({
        "notes": [{"personId": "p_stranger", "text": "x"}],
        "points": ["p%d" % i for i in range(5)] + ["y" * 300],
        "actions": [{"kind": "recall", "label": "Who?", "personId": "p_stranger"}, {"kind": "gossip", "label": "no"},
                    {"kind": "search", "label": "  "}] + [{"kind": "search", "label": "s%d" % i} for i in range(6)],
    })
    out = parse(reply, KNOWN)
    assert out["notes"] == [] and out["topic"] == ""
    assert out["points"] == ["p0", "p1", "p2"]
    assert [(a["label"], a["query"]) for a in out["actions"]] == [("s0", "s0"), ("s1", "s1"), ("s2", "s2"), ("s3", "s3")]
    long = parse(json.dumps({"points": ["y" * 300]}), KNOWN)["points"][0]
    assert len(long) < 120 and long.endswith("…")


def test_parse_survives_garbage():
    empty = {"notes": [], "topic": "", "points": [], "actions": []}
    assert parse("no json here", KNOWN) == empty
    assert parse("{broken", KNOWN) == empty
    assert parse("[1, 2]", KNOWN) == empty
    assert parse('{"points": "not a list", "actions": [1, null], "topic": 7}', KNOWN) == empty


def test_parse_summary_keeps_one_valid_entry_per_known_person():
    reply = "Here you go:\n" + json.dumps({"people": [
        {"personId": "p_jordan", "about": " Engineer, just moved to Austin ", "lastTime": "Talked about finding a climbing gym."},
        {"personId": "p_jordan", "about": "duplicate", "lastTime": "duplicate"},
        {"personId": "p_stranger", "about": "Not in the call", "lastTime": "x"},
        {"personId": "p_maya", "about": "", "lastTime": "empty about"},
        "junk",
    ]})
    assert parse_summary(reply, KNOWN | {"p_maya"}) == [
        {"personId": "p_jordan", "about": "Engineer, just moved to Austin", "lastTime": "Talked about finding a climbing gym."},
    ]
    assert parse_summary("no json", KNOWN) == []
    assert parse_summary('{"people": "nope"}', KNOWN) == []


def test_first_shapes_place_and_event_results():
    place = first("place", {"local_results": [{"title": "Ledge", "type": "Climbing gym", "address": "1 Main St", "rating": 4.7}]})
    assert place == {"title": "Ledge", "detail": "Climbing gym · 1 Main St · 4.7 stars"}
    single = first("place", {"place_results": {"title": "Only One"}})
    assert single == {"title": "Only One", "detail": ""}
    event = first("event", {"events_results": [{"title": "Boulder morning", "date": {"when": "Sat, 10 AM"}, "address": ["Gym", "Austin, TX"]}]})
    assert event == {"title": "Boulder morning", "detail": "Sat, 10 AM · Gym, Austin, TX"}
    assert first("event", {}) is None


def test_render_lists_people_points_and_responses():
    people = [
        {"name": "Jordan Lee", "firstMet": date(2025, 9, 24), "learned": ["Moved to Austin"]},
        {"name": "Maya Chen", "firstMet": date(2026, 10, 24), "learned": []},
    ]
    responses = [{"query": "Find climbing gyms", "text": "Ledge\nClimbing gym · 1 Main St",
                  "sources": [{"title": "Ledge", "url": "https://maps.example/ledge"}]},
                 {"query": "Suggest follow-ups", "text": "How is the new place?", "sources": []}]
    assert render(datetime(2026, 10, 24, 15, 30), people, ["Both of you climb"], responses) == """# Call on Saturday Oct 24, 2026, 15:30

## Jordan Lee

First met Sep 24, 2025.

- Moved to Austin

## Maya Chen

First met Oct 24, 2026.

Nothing new this call.

## Key points

- Both of you climb

## AI responses

### Find climbing gyms

Ledge
Climbing gym · 1 Main St

Sources: [Ledge](https://maps.example/ledge)

### Suggest follow-ups

How is the new place?
"""


def test_write_skips_empty_calls_and_appends_within_a_minute(tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "NOTES", tmp_path / "notes")
    started = datetime(2026, 10, 24, 15, 30)
    assert notes.write(started, {}, [], []) is None
    path = notes.write(started, {}, ["Both of you climb"], [])
    assert notes.write(started, {}, ["Both of you climb"], []) == path and path.name == "2026-10-24-1530.md"
    assert path.read_text().count("# Call on") == 2
