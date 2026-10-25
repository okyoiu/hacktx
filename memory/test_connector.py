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
    assert set(doc["paths"]) == {"/connector/people", "/connector/people/{id}", "/connector/calls"} and doc["security"] == [{"bearer": []}]
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


def test_calls_route_needs_the_key_asks_the_store_for_connector_people_only_and_is_documented(web, monkeypatch):
    asked = []
    monkeypatch.setattr(store, "calls", lambda limit, scope=None: asked.append((limit, scope)) or [
        {"endedAt": "2026-10-25T20:00:00Z", "app": "zoom.us", "topic": "Demo", "points": ["p"], "actions": ["Find gyms"],
         "people": [{"id": "p_jordan", "name": "Jordan Lee", "role": "", "lastTime": "Chat."}]}])
    assert web.get("/connector/calls").status_code == 401 and web.get("/connector/calls", headers=auth("wrong")).status_code == 401
    assert asked == []
    got = web.get("/connector/calls", headers=auth()).json()
    assert got[0]["topic"] == "Demo" and got[0]["actions"] == ["Find gyms"] and asked == [(5, "connector")]
    web.get("/connector/calls?limit=12", headers=auth())
    assert asked[-1] == (12, "connector")
    assert web.get("/connector/calls?limit=0", headers=auth()).status_code == 422 and web.get("/connector/calls?limit=99", headers=auth()).status_code == 422
    assert web.post("/connector/calls", headers=auth()).status_code == 405
    monkeypatch.delenv("MUSE_CONNECTOR_KEY")
    assert web.get("/connector/calls", headers=auth()).status_code == 404
    monkeypatch.setenv("MUSE_CONNECTOR_KEY", KEY)
    doc = web.get("/connector/openapi.json", headers=auth()).json()["paths"]["/connector/calls"]["get"]
    assert "last meeting" in doc["description"] and "recap" in doc["summary"]


# --- MCP ---

def rpc(web, method, params=None, key=KEY, **extra):
    body = {"jsonrpc": "2.0", "method": method, **({"id": 1} if "id" not in extra else {}), **extra}
    if params is not None:
        body["params"] = params
    return web.post("/connector/mcp", json=body, headers=auth(key) if key else {})


def tool_json(reply):
    return json.loads(reply.json()["result"]["content"][0]["text"])


def test_mcp_needs_the_key_and_get_says_to_post(web, monkeypatch):
    assert rpc(web, "ping", key=None).status_code == 401 and rpc(web, "ping", key="wrong").status_code == 401
    assert rpc(web, "ping").status_code == 200
    got = web.get("/connector/mcp", headers=auth())
    assert got.status_code == 405 and "POST JSON-RPC here" in got.json()["error"] and got.headers["allow"] == "POST"
    assert web.get("/connector/mcp").status_code == 401
    monkeypatch.delenv("MUSE_CONNECTOR_KEY")
    assert rpc(web, "ping").status_code == 404


def test_mcp_initialize_notifications_and_errors(web):
    init = rpc(web, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "muse", "version": "1"}}).json()
    assert init == {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                                                          "serverInfo": {"name": "hello-again", "version": "1.0.0"}}}
    note = web.post("/connector/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=auth())
    assert note.status_code == 202 and note.content == b""
    assert rpc(web, "nope").json()["error"]["code"] == -32601
    assert web.post("/connector/mcp", content="{not json", headers=auth() | {"content-type": "application/json"}).json()["error"]["code"] == -32700
    assert web.post("/connector/mcp", json=[1], headers=auth()).json()[0]["error"]["code"] == -32600
    assert web.post("/connector/mcp", json={"method": "ping"}, headers=auth()).json()["error"]["code"] == -32600  # no jsonrpc field
    batch = web.post("/connector/mcp", json=[{"jsonrpc": "2.0", "id": 7, "method": "ping"}, {"jsonrpc": "2.0", "method": "notifications/initialized"}], headers=auth())
    assert batch.json() == [{"jsonrpc": "2.0", "id": 7, "result": {}}]


def test_mcp_tools_list_and_calls_return_the_same_data_as_the_routes(web, monkeypatch):
    tools = rpc(web, "tools/list").json()["result"]["tools"]
    assert [t["name"] for t in tools] == ["list_people", "get_person", "recent_calls"] and all(t["inputSchema"]["type"] == "object" for t in tools)
    assert tools[1]["inputSchema"]["required"] == ["id"]

    listed = rpc(web, "tools/call", {"name": "list_people", "arguments": {}})
    assert listed.json()["result"]["content"][0]["type"] == "text" and tool_json(listed) == web.get("/connector/people", headers=auth()).json()
    assert tool_json(rpc(web, "tools/call", {"name": "list_people"})) == tool_json(listed)  # arguments may be left out
    one = rpc(web, "tools/call", {"name": "get_person", "arguments": {"id": "p_jordan"}})
    assert tool_json(one) == web.get("/connector/people/p_jordan", headers=auth()).json()
    for text in (listed.text, one.text):
        assert "print" not in text.lower() and "token" not in text.lower()
    gone = rpc(web, "tools/call", {"name": "get_person", "arguments": {"id": "p_nobody"}}).json()["result"]
    assert gone["isError"] is True and "Nobody" in gone["content"][0]["text"]  # a tool error, not a protocol error

    asked = []
    monkeypatch.setattr(store, "calls", lambda limit, scope=None: asked.append((limit, scope)) or [{"topic": "Demo"}])
    assert tool_json(rpc(web, "tools/call", {"name": "recent_calls", "arguments": {"limit": 3}})) == [{"topic": "Demo"}] and asked == [(3, "connector")]
    rpc(web, "tools/call", {"name": "recent_calls"})
    assert asked[-1] == (5, "connector")


def test_mcp_bad_params_are_32602(web):
    bad = [{"name": "nope"}, {"name": "get_person", "arguments": {}}, {"name": "get_person", "arguments": {"id": 5}},
           {"name": "recent_calls", "arguments": {"limit": 0}}, {"name": "recent_calls", "arguments": {"limit": "5"}},
           {"name": "recent_calls", "arguments": {"limit": True}}, {"name": "list_people", "arguments": "x"}, {}, "x"]
    for params in bad:
        assert rpc(web, "tools/call", params).json()["error"]["code"] == -32602, params


def test_the_tunnel_reaches_mcp_with_the_key_only(monkeypatch):
    monkeypatch.setenv("MUSE_CONNECTOR_KEY", KEY)
    monkeypatch.setattr(connector, "failures", [])
    tunnel = {"X-Forwarded-For": "198.51.100.7", "CF-Connecting-IP": "198.51.100.7"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    with TestClient(server.app, client=("127.0.0.1", 50000)) as laptop:
        assert laptop.post("/connector/mcp", json=body, headers=tunnel).status_code == 401
        assert laptop.post("/connector/mcp", json=body, headers=tunnel | auth()).json()["result"] == {}
        assert laptop.post("/listening", json={"on": False}, headers=tunnel | auth()).status_code == 403  # nothing else opens


def test_the_hosts_own_row_is_shared_without_the_tick(web, monkeypatch):
    me = {**LISTED, "id": "p_me", "name": "Cesar Sample", "role": "Me", "scope": ["facePrint", "name"]}
    other = {**LISTED, "id": "p_other", "name": "Not Ticked", "role": "Friend", "scope": ["facePrint", "name"]}
    monkeypatch.setattr(store, "people", lambda: [me, other])
    monkeypatch.setattr(store, "person", lambda pid: {**JORDAN, **{"p_me": me, "p_other": other}[pid]})
    assert [p["id"] for p in web.get("/connector/people", headers=auth()).json()] == ["p_me"]
    assert web.get("/connector/people/p_me", headers=auth()).status_code == 200
    assert web.get("/connector/people/p_other", headers=auth()).status_code == 404
    me["role"] = "  myself "
    assert [p["id"] for p in web.get("/connector/people", headers=auth()).json()] == ["p_me"]
