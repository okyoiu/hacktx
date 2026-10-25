"""Postgres (Tiger Data) + pgvector: people, face prints, consent, notes and per-call encounters."""
import hashlib
import os
import secrets
from datetime import datetime
from pathlib import Path

import numpy as np
import psycopg
from pgvector.psycopg import register_vector

# Cosine similarity an ArcFace print needs to count as the same person.
# shortcut: one fixed cutoff picked by eye; upgrade by measuring enrolled faces on real call video.
MATCH_MIN = 0.45
CONSENT_DAYS = 365

_conn: psycopg.Connection | None = None


def conn() -> psycopg.Connection:
    # shortcut: one shared connection; switch to psycopg_pool if requests start queuing.
    global _conn
    if _conn is None:
        _conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, connect_timeout=5)  # fail fast, never hang
        _conn.execute("create extension if not exists vector")
        register_vector(_conn)
        _conn.execute(Path(__file__).with_name("schema.sql").read_text())
        purge_expired()
    return _conn


def purge_expired() -> None:
    """Delete everyone whose consent has run out (faces and notes go with them)."""
    from memory import notes  # lazy: notes imports store

    rows = conn().execute(
        "delete from people where id in (select person_id from consents where expires_at < current_date) returning id"
    ).fetchall()
    for (pid,) in rows:
        notes.forget(pid)


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


def enroll(name: str, face_print: np.ndarray, selfie: bytes | None, role: str = "") -> tuple[str, str]:
    """Save a consenting person; returns (personId, deleteToken)."""
    pid, token = "p_" + secrets.token_hex(4), secrets.token_urlsafe(16)
    with conn().transaction():
        conn().execute(
            "insert into people (id, name, selfie, delete_token, role, role_source) values (%s, %s, %s, %s, %s, %s)",
            (pid, name, selfie, digest(token), role, "user" if role else "muse"),
        )
        conn().execute("insert into faces (person_id, print) values (%s, %s)", (pid, face_print))
        conn().execute(
            "insert into consents (person_id, expires_at) values (%s, current_date + %s::int)",
            (pid, CONSENT_DAYS),
        )
    return pid, token


def delete_person(pid: str, token: str) -> bool:
    row = conn().execute("select delete_token from people where id = %s", (pid,)).fetchone()
    if row is None or not secrets.compare_digest(row[0], digest(token)):
        return False
    conn().execute("delete from people where id = %s", (pid,))
    from memory import notes  # lazy: notes imports store

    notes.forget(pid)
    return True


def set_role(pid: str, role: str, source: str) -> None:
    """A user's role always wins; Muse's suggestion only fills in or replaces an earlier suggestion."""
    conn().execute(
        "update people set role = %s, role_source = %s where id = %s and (%s = 'user' or role_source <> 'user')",
        (role, source, pid, source),
    )


def person(pid: str) -> dict | None:
    """Name, first-met date, every encounter and note, newest first; None if unknown or their consent has run out."""
    row = conn().execute(
        """select p.name, p.first_met, p.role from people p join consents c on c.person_id = p.id
           where p.id = %s and c.expires_at >= current_date""",
        (pid,),
    ).fetchone()
    if row is None:
        return None
    encounters = conn().execute(
        "select met_at, about, last_time from encounters where person_id = %s order by met_at desc, id desc", (pid,)
    ).fetchall()
    notes = conn().execute(
        "select text, created_at from notes where person_id = %s order by created_at desc, id desc", (pid,)
    ).fetchall()
    return {
        "id": pid,
        "name": row[0],
        "role": row[2],
        "firstMet": row[1],
        "encounters": [{"metAt": at, "about": about, "lastTime": last} for at, about, last in encounters],
        "notes": [{"text": t, "createdAt": at} for t, at in notes],
    }


def add_encounter(pid: str, met_at: datetime, about: str, last_time: str) -> None:
    conn().execute(
        "insert into encounters (person_id, met_at, about, last_time) values (%s, %s, %s, %s)",
        (pid, met_at, about, last_time),
    )


def last_time(pid: str) -> str | None:
    """What you talked about at your latest encounter with this person."""
    row = conn().execute(
        "select last_time from encounters where person_id = %s order by met_at desc, id desc limit 1", (pid,)
    ).fetchone()
    return row[0] if row else None


def key_fact(pid: str) -> str | None:
    """One thing worth remembering about them: what Muse wrote they're about, else their newest note."""
    row = conn().execute(
        "select about from encounters where person_id = %s and about <> '' order by met_at desc, id desc limit 1", (pid,)
    ).fetchone()
    return row[0] if row else latest_note(pid)


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
