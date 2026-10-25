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


def test_parse_summary_gives_every_known_person_one_last_time_line():
    reply = "Here you go:\n" + json.dumps({"people": [
        {"personId": "p_jordan", "about": " Engineer, just moved to Austin ", "lastTime": "Talked about finding a climbing gym.", "role": "  Your   team lead "},
        {"personId": "p_jordan", "about": "duplicate", "lastTime": "duplicate"},
        {"personId": "p_stranger", "about": "Not in the call", "lastTime": "x"},
        {"personId": "p_maya", "about": None, "lastTime": "Asked Jordan about climbing gyms."},
        {"personId": "p_sam", "about": "Nurse", "lastTime": "  "},
        "junk",
    ]})
    together = "You were on a call together."
    assert parse_summary(reply, {"p_jordan", "p_maya", "p_sam", "p_kai"}) == [
        {"personId": "p_jordan", "about": "Engineer, just moved to Austin", "lastTime": "Talked about finding a climbing gym.", "role": "Your team lead"},
        {"personId": "p_maya", "about": "", "lastTime": "Asked Jordan about climbing gyms.", "role": ""},  # about may be empty
        {"personId": "p_sam", "about": "Nurse", "lastTime": together, "role": ""},
        {"personId": "p_kai", "about": "", "lastTime": together, "role": ""},  # Muse left them out
    ]
    assert parse_summary("no json", KNOWN) == [{"personId": "p_jordan", "about": "", "lastTime": together, "role": ""}]
    assert parse_summary('{"people": "nope"}', set()) == []


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
        {"id": "p_j", "name": "Jordan Lee", "firstMet": date(2025, 9, 24), "learned": ["Moved to Austin"]},
        {"id": "p_m", "name": "Maya Chen", "firstMet": date(2026, 10, 24), "learned": []},
    ]
    responses = [{"query": "Find climbing gyms", "text": "Ledge\nClimbing gym · 1 Main St",
                  "sources": [{"title": "Ledge", "url": "https://maps.example/ledge"}]},
                 {"query": "Suggest follow-ups", "text": "How is the new place?", "sources": []}]
    assert render(datetime(2026, 10, 24, 15, 30), people, ["Both of you climb"], responses) == """# Call on Saturday Oct 24, 2026, 15:30

## Jordan Lee <!-- p_j -->

First met Sep 24, 2025.

- Moved to Austin

## Maya Chen <!-- p_m -->

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


def test_forget_removes_only_that_persons_section(tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "NOTES", tmp_path)
    people = [{"id": "p_j", "name": "Jordan\n## Evil", "firstMet": date(2025, 9, 24), "learned": ["Moved to Austin"]},
              {"id": "p_m", "name": "Maya Chen", "firstMet": date(2026, 10, 24), "learned": ["Climbs"]}]
    path = tmp_path / "call.md"
    path.write_text(render(datetime(2026, 10, 24, 15, 30), people, ["Both of you climb"], []))
    notes.forget("p_j")
    text = path.read_text()
    assert "Jordan" not in text and "Austin" not in text
    assert "## Maya Chen <!-- p_m -->" in text and "Climbs" in text and "## Key points" in text


def test_parse_summary_caps_a_role_and_ignores_a_non_string():
    reply = json.dumps({"people": [{"personId": "a", "lastTime": "x", "role": "R" * 100}, {"personId": "b", "lastTime": "x", "role": 7}]})
    got = {e["personId"]: e["role"] for e in parse_summary(reply, {"a", "b"})}
    assert got == {"a": "R" * 60, "b": ""}


def test_forget_with_a_name_replaces_it_in_key_points_and_answers_too(tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "NOTES", tmp_path)
    people = [{"id": "p_j", "name": "Jordan Lee", "firstMet": date(2025, 9, 24), "learned": ["Moved to Austin"]}]
    answers = [{"query": "Who is jordan lee?", "text": "Jordan Lee, a friend of Jordan Leeds.", "sources": []}]
    path = tmp_path / "call.md"
    path.write_text(render(datetime(2026, 10, 24, 15, 30), people, ["Jordan Lee moved"], answers))
    notes.forget("p_j", "Jordan Lee")
    text = path.read_text()
    assert "Jordan Lee " not in text and "Jordan Lee," not in text and "jordan lee" not in text and "Austin" not in text
    assert "Who is someone who deleted their data?" in text and "Jordan Leeds" in text  # whole names only
    notes.forget("p_x", "")  # a blank name replaces nothing
    assert path.read_text() == text
