"""End-of-call note in notes/YYYY-MM-DD-HHMM.md: who you saw, what you learned about them, key points and AI answers."""
from datetime import date, datetime
from pathlib import Path

from memory import store

NOTES = Path(__file__).resolve().parent.parent / "notes"


def day(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def render(started: datetime, people: list[dict], points: list[str], responses: list[dict]) -> str:
    """people: [{name, firstMet, learned}]; points: insight points; responses: finished response events."""
    out = [f"# Call on {started:%A} {day(started)}, {started:%H:%M}", ""]
    for p in people:
        out += [f"## {p['name']}", "", f"First met {day(p['firstMet'])}.", ""]
        out += [f"- {text}" for text in p["learned"]] or ["Nothing new this call."]
        out.append("")
    if points:
        out += ["## Key points", ""] + [f"- {p}" for p in points] + [""]
    if responses:
        out += ["## AI responses", ""]
    for r in responses:
        out += [f"### {r['query']}", "", r["text"], ""]
        if r["sources"]:
            out += ["Sources: " + ", ".join(f"[{s['title']}]({s['url']})" for s in r["sources"]), ""]
    return "\n".join(out)


def write(started: datetime, learned: dict[str, list[str]], points: list[str], responses: list[dict]) -> Path | None:
    """learned: person id -> notes added this call. None (no file) when the call left nothing to write down."""
    # store.person is None for anyone who deleted themselves or whose consent ran out mid-call: leave them out
    people = [p | {"learned": learned[p["id"]]} for p in map(store.person, learned) if p]
    if not people and not points and not responses:
        return None
    NOTES.mkdir(exist_ok=True)
    path = NOTES / f"{started:%Y-%m-%d-%H%M}.md"
    with path.open("a") as f:  # a second call starting in the same minute appends instead of overwriting
        f.write(render(started, people, points, responses) + "\n")  # blank line before any call appended later
    return path
