"""The Muse connector routes: bearer key, read-only, and the rest of the server still shut to a tunnel."""
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from memory import app as server
from memory import connector, store

KEY = "test-connector-key"
JORDAN = {"id": "p_jordan", "name": "Jordan Lee", "role": "Your team lead", "howMet": "Oct 25, 2026 on Zoom", "firstMet": date(2026, 10, 1),
          "lastSeen": "2026-10-18", "lastSpoke": "2026-10-18", "topic": "his move", "context": "work",
          "scope": ["facePrint", "connector"], "facts": [{"text": "Loves F1", "createdAt": None}], "notes": [{"text": "Owes me a book", "createdAt": None}],
          "encounters": [{"metAt": None, "about": "Engineer", "lastTime": "Talked about Austin."}]}
LISTED = {k: JORDAN[k] for k in ("id", "name", "role", "lastSeen", "lastSpoke", "topic", "context", "scope")} | {"howMet": "x", "lastMet": "y"}


@pytest.fixture
def web(monkeypatch):
    monkeypatch.setenv("MUSE_CONNECTOR_KEY", KEY)
    monkeypatch.setattr(connector, "failures", [])
    monkeypatch.setattr(store, "people", lambda: [LISTED])
    monkeypatch.setattr(store, "person", lambda pid: JORDAN if pid == "p_jordan" else None)
    with TestClient(server.app, client=("203.0.113.9", 50000)) as client:  # anywhere on the internet
        yield client


def auth(key: str = KEY) -> dict:
    return {"Authorization": f"Bearer {key}"}


ROUTES = ["/connector/people", "/connector/people/p_jordan", "/connector/openapi.json"]


@pytest.mark.parametrize("path", ROUTES)
def test_the_key_is_required(web, path, monkeypatch):
    assert web.get(path).status_code == 401
    assert web.get(path, headers=auth("wrong")).status_code == 401
    assert web.get(path, headers={"Authorization": KEY}).status_code == 401  # not a Bearer header
    assert web.get(path, headers=auth()).status_code == 200
    monkeypatch.delenv("MUSE_CONNECTOR_KEY")
    assert web.get(path, headers=auth()).status_code == 404  # not set up: the routes do not exist
    monkeypatch.setenv("MUSE_CONNECTOR_KEY", "")
    assert web.get(path, headers=auth("")).status_code == 404


def test_people_and_one_person_are_read_only_and_never_hold_prints_or_tokens(web):
    listed = web.get("/connector/people", headers=auth()).json()
    assert listed == [{k: LISTED[k] for k in ("id", "name", "role", "lastSeen", "lastSpoke", "topic", "context")}]
    assert "scope" not in listed[0]
    one = web.get("/connector/people/p_jordan", headers=auth()).json()
    assert one["facts"] == ["Loves F1"] and one["notes"] == ["Owes me a book"] and one["howMet"] == "Oct 25, 2026 on Zoom"
    assert (one["about"], one["lastTime"]) == ("Engineer", "Talked about Austin.")
    for body in (web.get("/connector/people", headers=auth()).text, json.dumps(one)):
        assert "print" not in body.lower() and "token" not in body.lower()
    assert web.get("/connector/people/p_nobody", headers=auth()).status_code == 404  # unknown, or consent ran out
    for method in ("post", "put", "patch", "delete"):
        assert getattr(web, method)("/connector/people", headers=auth()).status_code == 405


def test_the_document_describes_both_routes_and_health_needs_no_key(web):
    doc = web.get("/connector/openapi.json", headers=auth()).json()
    assert doc["openapi"].startswith("3.1") and doc["info"]["title"] == "Hello Again memory" and "Read-only" in doc["info"]["description"]
    assert set(doc["paths"]) == {"/connector/people", "/connector/people/{id}"} and doc["security"] == [{"bearer": []}]
    assert web.get("/connector/health").json() == {"ok": True}


def test_wrong_keys_are_throttled_but_the_right_key_still_works(web, monkeypatch):
    monkeypatch.setattr(connector, "FAILS_PER_MINUTE", 3)
    for _ in range(3):
        assert web.get("/connector/people", headers=auth("wrong")).status_code == 401
    assert web.get("/connector/people", headers=auth("wrong")).status_code == 429
    assert web.get("/connector/people", headers=auth()).status_code == 200  # the right key is never locked out


def test_a_tunnel_reaches_the_connector_and_nothing_else(monkeypatch):
    monkeypatch.setenv("MUSE_CONNECTOR_KEY", KEY)
    monkeypatch.setattr(store, "people", lambda: [LISTED])
    tunnel = {"X-Forwarded-For": "198.51.100.7"}  # a local tunnel connects over loopback and adds forwarding headers
    with TestClient(server.app, client=("127.0.0.1", 50000)) as laptop:
        assert laptop.get("/connector/people", headers=auth() | tunnel).status_code == 200
        for header in ("X-Forwarded-For", "Forwarded", "X-Real-IP", "CF-Connecting-IP", "X-Forwarded-Host"):
            for method, path in (("get", "/people"), ("post", "/listening"), ("post", "/calls/end"), ("get", "/people/p_jordan")):
                assert getattr(laptop, method)(path, headers={header: "x"} | auth()).status_code == 403, (header, path)
            with pytest.raises(Exception):
                with laptop.websocket_connect("/ws", headers={header: "x"}):
                    pass
        assert laptop.get("/people").status_code == 200  # the laptop itself is unaffected


def test_the_detail_and_the_document_carry_how_we_met_and_context(web):
    one = web.get("/connector/people/p_jordan", headers=auth()).json()
    assert one["howMet"] == "Oct 25, 2026 on Zoom" and one["context"] == "work"
    doc = web.get("/connector/openapi.json", headers=auth()).json()
    assert "howMet" in doc["info"]["description"] and "context" in doc["info"]["description"]
    props = doc["paths"]["/connector/people/{id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["properties"]
    assert "howMet" in props and "context" in props and "first call" in props["howMet"]["description"]


def test_only_people_who_ticked_the_connector_are_listed_or_readable(web, monkeypatch):
    private = {**LISTED, "id": "p_private", "name": "Private Pat", "scope": ["facePrint", "name", "voice", "notes", "facts"]}
    monkeypatch.setattr(store, "people", lambda: [private, LISTED])
    monkeypatch.setattr(store, "person", lambda pid: {**JORDAN, "id": pid, "scope": private["scope"]} if pid == "p_private" else JORDAN)
    assert [p["id"] for p in web.get("/connector/people", headers=auth()).json()] == ["p_jordan"]
    assert web.get("/connector/people/p_private", headers=auth()).status_code == 404
    assert "Private Pat" not in web.get("/connector/people", headers=auth()).text
    assert web.get("/connector/people/p_jordan", headers=auth()).status_code == 200
