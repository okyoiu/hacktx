from datetime import date, datetime

from memory import app, notes
from memory.notes import render
from memory.picks import parse
from memory.serp import first

KNOWN = {"p_jordan"}


def test_parse_reads_json_inside_fences_and_prose():
    reply = 'Sure!\n```json\n{"notes": [{"personId": "p_jordan", "text": "Moved to Austin"}], "picks": [{"kind": "place", "title": "Climbing gym", "search": "climbing gym South Congress"}]}\n```'
    out = parse(reply, KNOWN)
    assert out["notes"] == [{"personId": "p_jordan", "text": "Moved to Austin"}]
    assert out["picks"][0] == {"kind": "place", "title": "Climbing gym", "detail": "", "search": "climbing gym South Congress"}


def test_parse_drops_unknown_people_bad_kinds_and_caps_picks():
    reply = '{"notes": [{"personId": "p_stranger", "text": "x"}], "picks": [' + ",".join(
        ['{"kind": "fact", "title": "t%d"}' % i for i in range(5)] + ['{"kind": "gossip", "title": "no"}']
    ) + "]}"
    out = parse(reply, KNOWN)
    assert out["notes"] == []
    assert [p["title"] for p in out["picks"]] == ["t0", "t1", "t2"]


def test_parse_survives_garbage():
    assert parse("no json here", KNOWN) == {"notes": [], "picks": []}
    assert parse("{broken", KNOWN) == {"notes": [], "picks": []}
    assert parse("[1, 2]", KNOWN) == {"notes": [], "picks": []}


def test_first_shapes_place_and_event_results():
    place = first("place", {"local_results": [{"title": "Ledge", "type": "Climbing gym", "address": "1 Main St", "rating": 4.7}]})
    assert place == {"title": "Ledge", "detail": "Climbing gym · 1 Main St · 4.7 stars"}
    single = first("place", {"place_results": {"title": "Only One"}})
    assert single == {"title": "Only One", "detail": ""}
    event = first("event", {"events_results": [{"title": "Boulder morning", "date": {"when": "Sat, 10 AM"}, "address": ["Gym", "Austin, TX"]}]})
    assert event == {"title": "Boulder morning", "detail": "Sat, 10 AM · Gym, Austin, TX"}
    assert first("event", {}) is None


def test_seen_recently_blocks_repeat_titles_for_five_minutes():
    app.recent_titles.clear()
    assert not app.seen_recently("Climbing gym", 1000)
    assert app.seen_recently("  climbing GYM ", 1299)
    assert not app.seen_recently("Ledge", 1299)
    assert not app.seen_recently("Climbing gym", 1300)  # window counts from the last push, not the last repeat
    assert app.seen_recently("Climbing gym", 1301)


def test_render_lists_people_learned_notes_and_picks():
    people = [
        {"name": "Jordan Lee", "firstMet": date(2025, 9, 24), "learned": ["Moved to Austin"]},
        {"name": "Maya Chen", "firstMet": date(2026, 10, 24), "learned": []},
    ]
    picks = [{"title": "Ledge", "detail": "Climbing gym · 1 Main St", "speaker": "Jordan Lee"},
             {"title": "Both run", "detail": "", "speaker": "You"}]
    assert render(datetime(2026, 10, 24, 15, 30), people, picks) == """# Call on Saturday Oct 24, 2026, 15:30

## Jordan Lee

First met Sep 24, 2025.

- Moved to Austin

## Maya Chen

First met Oct 24, 2026.

Nothing new this call.

## Top picks

- **Ledge**: Climbing gym · 1 Main St (Jordan Lee)
- **Both run** (You)
"""


def test_write_skips_empty_calls_and_appends_within_a_minute(tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "NOTES", tmp_path / "notes")
    started = datetime(2026, 10, 24, 15, 30)
    pick = [{"title": "Ledge", "detail": "", "speaker": "You"}]
    assert notes.write(started, {}, []) is None
    path = notes.write(started, {}, pick)
    assert notes.write(started, {}, pick) == path and path.name == "2026-10-24-1530.md"
    assert path.read_text().count("# Call on") == 2
