"""End-of-call note in notes/YYYY-MM-DD-HHMM.md: who you saw, what you learned about them, key points and AI answers."""
import os
import re
from datetime import date, datetime
from pathlib import Path

from memory import store

NOTES = Path(__file__).resolve().parent.parent / "notes"


def day(d: date) -> str:
    return f"{d:%b} {d.day}, {d.year}"


def render(started: datetime, people: list[dict], points: list[str], responses: list[dict]) -> str:
    """people: [{id, name, firstMet, learned}]; points: insight points; responses: finished response events."""
    out = [f"# Call on {started:%A} {day(started)}, {started:%H:%M}", ""]
    for p in people:
        # the id marks the section so forget() can find it; a name can't add lines or headings of its own
        out += [f"## {' '.join(p['name'].split())} <!-- {p['id']} -->", "", f"First met {day(p['firstMet'])}.", ""]
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


GONE = "someone who deleted their data"


def forget(pid: str, name: str | None = None) -> None:
    """For someone who deleted themselves or whose consent ran out: drop their section and file, and say GONE
    wherever else their name appears in old call notes (key points, AI answers)."""
    section = re.compile(rf"^## [^\n]*<!-- {re.escape(pid)} -->\n.*?(?=^#{{1,2}} |\Z)", re.M | re.S)
    mention = re.compile(rf"\b{re.escape(name)}\b", re.I) if name and name.strip() else None
    (NOTES / "people" / f"{pid}.md").unlink(missing_ok=True)
    for path in NOTES.glob("*.md"):
        text = path.read_text()
        cleaned = section.sub("", text)
        if mention:
            cleaned = mention.sub(GONE, cleaned)
        if cleaned != text:
            path.write_text(cleaned)


def one_line(text: str) -> str:
    return " ".join(text.split())


def write_person(pid: str) -> Path | None:
    """notes/people/<id>.md: who they are to you, what they're about and every conversation, newest first.
    Rewritten whole each time. The file is named by id, so names stay out of paths and can't escape the folder."""
    p = store.person(pid)
    if p is None:
        return None
    folder = NOTES / "people"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{pid}.md"
    about = next((e["about"] for e in p["encounters"] if e["about"]), "")
    out = [f"# {one_line(p['name'])}", "", f"Who they are to you: {one_line(p['role']) or 'not set'}", "",
           f"First met {day(p['firstMet'])}.", ""]
    if about:
        out += ["## About", "", one_line(about), ""]
    out += ["## Conversations", ""]
    out += [f"- {day(e['metAt'].astimezone())}: {one_line(e['lastTime'])}" for e in p["encounters"]] or ["Nothing yet."]
    if p["notes"]:
        out += ["", "## Notes", ""] + [f"- {one_line(n['text'])}" for n in p["notes"]]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # about real people: only this user can read it
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(out) + "\n")
    path.chmod(0o600)  # O_CREAT's mode is skipped for a file that already exists
    return path
