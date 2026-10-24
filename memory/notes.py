"""End-of-call note in notes/YYYY-MM-DD-HHMM.md: who you saw, what you learned about them, and the top picks."""
from datetime import date, datetime
from pathlib import Path

from memory import store

NOTES = Path(__file__).resolve().parent.parent / "notes"


def day(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def render(started: datetime, people: list[dict], picks: list[dict]) -> str:
    """people: [{name, firstMet, learned}]; picks: the pick events pushed to the overlay."""
    out = [f"# Call on {started:%A} {day(started)}, {started:%H:%M}", ""]
    for p in people:
        out += [f"## {p['name']}", "", f"First met {day(p['firstMet'])}.", ""]
        out += [f"- {text}" for text in p["learned"]] or ["Nothing new this call."]
        out.append("")
    if picks:
        out += ["## Top picks", ""]
        out += [f"- **{k['title']}**" + (f": {k['detail']}" if k["detail"] else "") + f" ({k['speaker']})" for k in picks]
        out.append("")
    return "\n".join(out)


def write(started: datetime, learned: dict[str, list[str]], picks: list[dict]) -> Path | None:
    """learned: person id -> notes added this call. None (no file) when nobody was recognized and nothing was picked."""
    # store.person is None for anyone who deleted themselves or whose consent ran out mid-call: leave them out
    people = [p | {"learned": learned[p["id"]]} for p in map(store.person, learned) if p]
    if not people and not picks:
        return None
    NOTES.mkdir(exist_ok=True)
    path = NOTES / f"{started:%Y-%m-%d-%H%M}.md"
    with path.open("a") as f:  # a second call starting in the same minute appends instead of overwriting
        f.write(render(started, people, picks) + "\n")  # blank line before any call appended later
    return path
