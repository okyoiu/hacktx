"""Security checks across the app: consent, unknown faces, deletion, Electron settings and who may reach the server.
Each xfail is an open finding in docs/security-review.md; it starts failing once fixed, so delete its marker then.
Run: uv run pytest tools/test_security.py (the deletion test also needs DATABASE_URL)."""
import os
import re
from datetime import date
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from memory import app as server
from memory import store

ROOT = Path(__file__).resolve().parent.parent
LAPTOP, WIFI = ("127.0.0.1", 50000), ("192.168.1.50", 50000)  # this laptop, and a phone on the venue Wi-Fi


class FakeDb:
    """Stands in for store.conn(): records every SQL statement and answers with a face that matches nobody."""

    def __init__(self):
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append(sql)
        return self

    def fetchone(self):
        return ("p_someone", "Someone", date.today(), 0.1)  # far below store.MATCH_MIN


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()
    monkeypatch.setattr(store, "conn", lambda: fake)
    monkeypatch.setattr(server, "tracks", {})
    monkeypatch.setattr(server, "saw_face", lambda card: None)  # no call timers
    return fake


def test_an_unknown_face_is_never_saved(db):
    body = {"trackId": 1, "screenBox": [0, 0, 10, 10], "facePrint": [0.044] * 512}
    assert TestClient(server.app, client=LAPTOP).post("/faces", json=body).json()["person"] is None
    assert db.sql and all(s.lstrip().lower().startswith("select") for s in db.sql)


def test_enrolling_without_consent_saves_nothing(db):
    r = TestClient(server.app, client=LAPTOP).post(
        "/enroll", data={"name": "Sam", "consent": "false"}, files={"selfie": ("s.jpg", b"x", "image/jpeg")}
    )
    assert r.status_code == 400 and db.sql == []


def test_deleting_a_person_deletes_everything_about_them():
    """Every table pointing at people must go with them: faces, consents, notes, encounters and any added later."""
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    try:
        rows = store.conn().execute(
            "select conrelid::regclass::text, confdeltype from pg_constraint where contype = 'f' and confrelid = 'people'::regclass"
        ).fetchall()
    except psycopg.OperationalError as e:
        pytest.skip(f"database unreachable: {e}")
    assert {"faces", "consents", "notes"} <= {table for table, _ in rows}
    assert all(kind == "c" for _, kind in rows), rows  # c = on delete cascade


def test_guests_on_the_wifi_can_open_the_enroll_page():
    assert TestClient(server.app, client=WIFI).get("/enroll").status_code == 200


@pytest.mark.xfail(strict=True, reason="security-review #2: every route is open to the venue Wi-Fi")
def test_the_wifi_cannot_read_people(monkeypatch):
    monkeypatch.setattr(store, "person", lambda pid: {"id": pid, "name": "Someone", "notes": []})
    assert TestClient(server.app, client=WIFI).get("/people/p_someone").status_code in (401, 403)


def test_the_overlay_can_open_its_socket():
    with TestClient(server.app, client=LAPTOP).websocket_connect("/ws"):
        pass


@pytest.mark.xfail(strict=True, reason="security-review #3: any web page open on this laptop can read /ws")
def test_web_pages_cannot_open_the_overlay_socket():
    with pytest.raises(WebSocketDisconnect):
        with TestClient(server.app, client=LAPTOP).websocket_connect("/ws", headers={"origin": "https://example.com"}):
            pass


def test_electron_keeps_its_safe_settings():
    main = (ROOT / "overlay/main.js").read_text()
    for unsafe in ("nodeIntegration: true", "contextIsolation: false", "sandbox: false", "webSecurity: false"):
        assert unsafe not in main
    html = (ROOT / "overlay/index.html").read_text()
    assert "default-src 'self'" in html and "unsafe-" not in html


def test_untrusted_text_never_becomes_html():
    html_sinks = [p.name for p in [*ROOT.glob("overlay/*.js"), ROOT / "web/enroll.html"]
                  if re.search(r"\.(inner|outer)HTML\s*\+?=|document\.write\(", p.read_text())]
    assert html_sinks == []


def test_keys_and_call_notes_stay_out_of_git():
    ignored = (ROOT / ".gitignore").read_text().split()
    assert ".env" in ignored and "notes/" in ignored
