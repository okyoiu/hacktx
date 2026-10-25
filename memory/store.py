"""Postgres (Tiger Data) + pgvector: people, face prints, consent, notes and per-call encounters."""
import hashlib
import os
import secrets
from datetime import datetime
from pathlib import Path

import numpy as np
import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector

# Cosine similarity an ArcFace print needs to count as the same person.
# shortcut: one fixed cutoff picked by eye; upgrade by measuring enrolled faces on real call video.
MATCH_MIN = 0.45
CONSENT_DAYS = 365
SCOPE = ['facePrint', 'name', 'voice', 'notes', 'facts']  # agreed to by default; `connector` only when ticked

_conn: psycopg.Connection | None = None


def conn() -> psycopg.Connection:
    # shortcut: one shared connection; switch to psycopg_pool if requests start queuing.
    global _conn
    if _conn is None:
        _conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, connect_timeout=5)  # fail fast, never hang
        _conn.execute("create extension if not exists vector")
        try:
            _conn.execute("create extension if not exists timescaledb")  # Tiger Cloud has it; plain Postgres doesn't, and that is fine
        except psycopg.Error:
            pass
        register_vector(_conn)
        _conn.execute(Path(__file__).with_name("schema.sql").read_text())
        purge_expired()
    return _conn


def purge_expired() -> None:
    """Delete everyone whose consent has run out (faces and notes go with them)."""
    from memory import notes  # lazy: notes imports store

    rows = conn().execute(
        "delete from people where id in (select person_id from consents where expires_at < current_date) returning id, name"
    ).fetchall()
    for pid, name in rows:
        notes.forget(pid, name)


def match(face_print: np.ndarray) -> dict | None:
    """Closest consenting person, or None when nobody is close enough."""
    row = conn().execute(
        """select p.id, p.name, p.first_met, 1 - (f.print <=> %s) as score, p.role
           from faces f
           join people p on p.id = f.person_id
           join consents c on c.person_id = p.id
           where c.expires_at >= current_date
           order by f.print <=> %s
           limit 1""",
        (face_print, face_print),
    ).fetchone()
    if row is None or row[3] < MATCH_MIN:
        return None
    return {"id": row[0], "name": row[1], "firstMet": row[2], "role": row[4], "score": round(float(row[3]), 3)}


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def nearest_score(face_print: np.ndarray) -> float | None:
    """Best cosine similarity to any consenting person, even below MATCH_MIN. Developer mode only."""
    row = conn().execute(
        """select max(1 - (f.print <=> %s)) from faces f join consents c on c.person_id = f.person_id
           where c.expires_at >= current_date""",
        (face_print,),
    ).fetchone()
    return None if row is None or row[0] is None else round(float(row[0]), 3)


def enroll(name: str, face_print: np.ndarray, selfie: bytes | None, role: str = "", connector: bool = False) -> tuple[str, str]:
    """Save a consenting person; returns (personId, deleteToken)."""
    pid, token = "p_" + secrets.token_hex(4), secrets.token_urlsafe(16)
    role = " ".join(role.split())
    with conn().transaction():
        conn().execute(
            "insert into people (id, name, selfie, delete_token, role, role_source) values (%s, %s, %s, %s, %s, %s)",
            (pid, name, selfie, digest(token), role, "user" if role else "muse"),
        )
        conn().execute("insert into faces (person_id, print) values (%s, %s)", (pid, Vector(face_print)))
        conn().execute(
            "insert into consents (person_id, expires_at, scope) values (%s, current_date + %s::int, %s)",
            (pid, CONSENT_DAYS, SCOPE + ["connector"] * connector),
        )
    return pid, token


def delete_person(pid: str, token: str | None) -> bool:
    """Delete with their token; token=None skips the check and is only for callers that know the request came
    from this laptop."""
    row = conn().execute("select delete_token, name from people where id = %s", (pid,)).fetchone()
    if row is None or (token is not None and not secrets.compare_digest(row[0], digest(token))):
        return False
    from memory import notes  # lazy: notes imports store

    conn().execute("delete from people where id = %s", (pid,))
    notes.forget(pid, row[1])  # every way of deleting someone also clears them from notes/
    return True


def set_role(pid: str, role: str, source: str) -> None:
    """A user's role always wins; Muse's suggestion only fills in or replaces an earlier suggestion.
    A role the user cleared (empty) stays empty: it is theirs, so Muse never suggests one again."""
    role = " ".join(role.split())  # one line: a role ends up in prompts and in notes files
    conn().execute(
        "update people set role = %s, role_source = %s where id = %s and (%s = 'user' or role_source <> 'user')",
        (role, source, pid, source),
    )


def is_self(role: str) -> bool:
    """The user's own card: capture and the overlay skip it."""
    return role.strip().casefold() in ("me", "me!", "myself")


def people() -> list[dict]:
    """Everyone with valid consent, most recently met first, for the dashboard."""
    rows = conn().execute(
        """select p.id, p.name, p.role, p.first_met, p.how_met, c.scope,
                  coalesce((select max(met_at) from encounters where person_id = p.id), p.first_met::timestamptz) as last_met,
                  (select last_time from encounters where person_id = p.id order by met_at desc, id desc limit 1)
           from people p join consents c on c.person_id = p.id
           where c.expires_at >= current_date
           order by last_met desc, p.first_met desc, p.id""").fetchall()
    by_person: dict[str, list] = {}
    for pid, *row in conn().execute("select person_id, met_at, spoke, topic, context from encounters order by met_at desc, id desc").fetchall():
        by_person.setdefault(pid, []).append(tuple(row))
    return [{"id": i, "name": n, "role": r, "self": is_self(r), "howMet": h, "scope": sc, "firstMet": f, "lastMet": m, "lastTime": t,
             **seen_fields(by_person.get(i, []))} for i, n, r, f, h, sc, m, t in rows]


def stale(days: int) -> list[dict]:
    """Consenting people not seen on a call for `days` days or more, most overdue first. Someone never on a call
    counts from the day they were enrolled."""
    rows = conn().execute(
        """select p.id, p.name, p.role, last_met, (select last_time from encounters e where e.person_id = p.id
                                                   order by e.met_at desc, e.id desc limit 1)
           from people p join consents c on c.person_id = p.id
           cross join lateral (select coalesce(max(met_at), p.first_met::timestamptz) as last_met
                               from encounters where person_id = p.id) m
           where c.expires_at >= current_date and last_met <= now() - make_interval(days => %s)
           order by last_met, p.id""",
        (days,),
    ).fetchall()
    now = datetime.now().astimezone()
    return [{"id": i, "name": n, "role": r, "lastMet": m, "daysSince": (now - m).days, "lastTime": t} for i, n, r, m, t in rows]


def rename(pid: str, name: str) -> None:
    conn().execute("update people set name = %s where id = %s", (name, pid))


def person(pid: str) -> dict | None:
    """Name, first-met date, every encounter and note, newest first; None if unknown or their consent has run out."""
    row = conn().execute(
        """select p.name, p.first_met, p.role, p.how_met, c.scope from people p join consents c on c.person_id = p.id
           where p.id = %s and c.expires_at >= current_date""",
        (pid,),
    ).fetchone()
    if row is None:
        return None
    encounters = conn().execute(
        "select met_at, about, last_time, spoke, topic, context from encounters where person_id = %s order by met_at desc, id desc",
        (pid,),
    ).fetchall()
    notes = conn().execute(
        "select text, created_at from notes where person_id = %s order by created_at desc, id desc", (pid,)
    ).fetchall()
    facts = conn().execute(
        "select text, created_at from facts where person_id = %s order by created_at desc, id desc", (pid,)
    ).fetchall()
    return {
        "id": pid,
        "name": row[0],
        "role": row[2],
        "howMet": row[3],
        "scope": row[4],
        "firstMet": row[1],
        **seen_fields([(at, spoke, topic, ctx) for at, _, _, spoke, topic, ctx in encounters]),
        "encounters": [{"metAt": at, "about": about, "lastTime": last} for at, about, last, *_ in encounters],
        "notes": [{"text": t, "createdAt": at} for t, at in notes],
        "facts": [{"text": t, "createdAt": at} for t, at in facts],
    }


def add_encounter(pid: str, met_at: datetime, about: str, last_time: str,
                  topic: str = "", spoke: bool = False, context: str = "") -> None:
    conn().execute(
        "insert into encounters (person_id, met_at, about, last_time, topic, spoke, context) values (%s, %s, %s, %s, %s, %s, %s)",
        (pid, met_at, about, last_time, topic, spoke, context),
    )


def seen_fields(rows: list[tuple]) -> dict:
    """lastSeen, lastSpoke, topic and context from a person's encounters, newest first, as (met_at, spoke, topic, context).
    All None before a first call together; lastSpoke is lastSeen when we never knew them to speak."""
    if not rows:
        return {"lastSeen": None, "lastSpoke": None, "topic": None, "context": None}
    day = lambda at: at.astimezone().date().isoformat()
    spoke = next((r for r in rows if r[1]), rows[0])
    return {"lastSeen": day(rows[0][0]), "lastSpoke": day(spoke[0]), "topic": rows[0][2] or None, "context": rows[0][3]}


def seen(pid: str) -> dict:
    return seen_fields(conn().execute(
        "select met_at, spoke, topic, context from encounters where person_id = %s order by met_at desc, id desc", (pid,)
    ).fetchall())


def last_time(pid: str) -> str | None:
    """What you talked about at your latest encounter with this person."""
    row = conn().execute(
        "select last_time from encounters where person_id = %s order by met_at desc, id desc limit 1", (pid,)
    ).fetchone()
    return row[0] if row else None


def card_extras(pid: str, facts: int = 2) -> tuple[str, list[str], dict]:
    """What a card shows beyond role and last time: how we met, the newest facts, and the lastSeen/lastSpoke/topic/context fields."""
    how = conn().execute("select how_met from people where id = %s", (pid,)).fetchone()
    rows = conn().execute("select text from facts where person_id = %s order by created_at desc, id desc limit %s", (pid, facts)).fetchall()
    return (how[0] if how else ""), [r[0] for r in rows], seen(pid)


def set_how_met(pid: str, line: str) -> None:
    """Written once, at the first encounter; never rewritten."""
    conn().execute("update people set how_met = %s where id = %s and how_met = ''", (line, pid))


def add_facts(pid: str, texts: list[str]) -> None:
    """Muse's facts about a person; one it already has (any capitalisation) is skipped."""
    for text in texts:
        conn().execute("insert into facts (person_id, text) values (%s, %s) on conflict do nothing", (pid, text))


def add_note(pid: str, text: str) -> None:
    conn().execute("insert into notes (person_id, text) values (%s, %s)", (pid, text))


def latest_note(pid: str) -> str | None:
    row = conn().execute(
        "select text from notes where person_id = %s order by created_at desc limit 1", (pid,)
    ).fetchone()
    return row[0] if row else None


def notes_for(pids: list[str], per_person: int = 5) -> dict[str, list[str]]:
    if not pids:
        return {}
    rows = conn().execute(
        """select person_id, text from (
             select person_id, text, row_number() over (partition by person_id order by created_at desc) as n
             from notes where person_id = any(%s)) t
           where n <= %s""",
        (pids, per_person),
    ).fetchall()
    out: dict[str, list[str]] = {}
    for pid, text in rows:
        out.setdefault(pid, []).append(text)
    return out
