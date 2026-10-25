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
        out += ["## Asked during the call", ""]
    for r in responses:
        # a recall carries its person's id, so forget() can take it out; Muse text can't start a heading of its own
        marker = f" <!-- {r['personId']} -->" if r.get("personId") else ""
        out += [f"### {one_line(r['query'])}{marker}", "", re.sub(r"^#", r"\\#", r["text"], flags=re.M), ""]
        if r["sources"]:
            out += ["Sources: " + ", ".join(f"[{s['title']}]({s['url']})" for s in r["sources"]), ""]
    return "\n".join(out)


def private_folders() -> Path:
    """notes/ and notes/people/, readable by this account only; returns the people folder."""
    for folder in (NOTES, NOTES / "people"):
        folder.mkdir(mode=0o700, exist_ok=True)
        folder.chmod(0o700)  # mkdir's mode is skipped for a folder that already exists
    return NOTES / "people"


def tighten() -> None:
    """On startup: make notes written by older versions private too."""
    if NOTES.is_dir():
        private_folders()
        for path in [*NOTES.glob("*.md"), *(NOTES / "people").glob("*.md")]:
            path.chmod(0o600)


def write(started: datetime, learned: dict[str, list[str]], points: list[str], responses: list[dict]) -> Path | None:
    """learned: person id -> notes added this call. None (no file) when the call left nothing to write down."""
    # store.person is None for anyone who deleted themselves or whose consent ran out mid-call: leave them out
    people = [p | {"learned": learned[p["id"]]} for p in map(store.person, learned) if p]
    if not people and not points and not responses:
        return None
    private_folders()
    path = NOTES / f"{started:%Y-%m-%d-%H%M}.md"
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600), "a") as f:  # a second call starting in the same minute appends instead of overwriting
        f.write(render(started, people, points, responses) + "\n")  # blank line before any call appended later
    return path


GONE = "someone who deleted their data"


def forget(pid: str, name: str | None = None) -> None:
    """For someone who deleted themselves or whose consent ran out: drop their section and file, and say GONE
    wherever else their name appears in old call notes (key points, AI answers)."""
    section = re.compile(rf"^#{{2,3}} [^\n]*<!-- {re.escape(pid)} -->\n.*?(?=^#{{1,3}} |\Z)", re.M | re.S)  # their section, and recalls about them
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
    """notes/people/<id>.md: the card's header (role, last seen, last spoke, about, context, how we met), Muse's facts,
    every conversation newest first, then the user's own notes.
    Rewritten whole each time. The file is named by id, so names stay out of paths and can't escape the folder."""
    p = store.person(pid)
    if p is None:
        return None
    path = private_folders() / f"{pid}.md"
    about = next((e["about"] for e in p["encounters"] if e["about"]), "")
    # the same facts the card shows, then Muse's facts, the conversations and the user's own notes
    out = [f"# {one_line(p['name'])}", "",
           f"- Who they are to you: {one_line(p['role']) or 'not set'}",
           f"- Last seen: {p.get('lastSeen') or 'not yet'}",
           f"- Last spoke: {p.get('lastSpoke') or 'not yet'}",
           f"- About: {one_line(about) or 'unknown'}",
           f"- Context: {p.get('context') or 'unknown'}",
           f"- How we met: {one_line(p.get('howMet') or '') or 'unknown'}",
           f"- First met: {day(p['firstMet'])}"]
    if p.get("facts"):
        out += ["", "## Facts (Muse)", ""] + [f"- {one_line(f['text'])}" for f in p["facts"]]
    if p.get("mentions"):
        out += ["", "## Places and events (from AI answers)", ""] + [f"- {one_line(m['text'])}" for m in p["mentions"]]
    out += ["", "## Conversations", ""]
    out += [f"- {day(e['metAt'].astimezone())}: {one_line(e['lastTime'])}" for e in p["encounters"]] or ["Nothing yet."]
    if p["notes"]:
        out += ["", "## Notes", ""] + [f"- {one_line(n['text'])}" for n in p["notes"]]
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)  # about real people: only this user can read it
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(out) + "\n")
    path.chmod(0o600)  # O_CREAT's mode is skipped for a file that already exists
    return path
