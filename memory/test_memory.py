from memory import app
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
