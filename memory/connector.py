"""Read-only routes for a Muse custom connector. The Muse app calls them through a tunnel with a bearer key, so these are the
only routes that skip the laptop-only rule. They return names, labels and what was learned, never face prints or tokens."""
import json
import os
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from memory import store

router = APIRouter(prefix="/connector")
FAILS_PER_MINUTE = 20  # wrong keys, all callers together: through a tunnel every caller looks the same
failures: list[float] = []

SUMMARY = ("Hello Again memory: people the user has met on video calls, who agreed to be remembered. For each person: "
           "who they are to the user, when they last met and last spoke, what the last conversation was about, whether it was "
           "work or personal (context), plain facts they shared about themselves, how they first met (howMet), and the user's own notes. Read-only; there is nothing to change.")


def require_key(request: Request) -> None:
    key = os.getenv("MUSE_CONNECTOR_KEY")
    if not key:
        raise HTTPException(404, "Not found")  # not set up: these routes do not exist
    # Muse's credential store may send the key bare, as "Bearer …"/"Token …", or in X-API-Key: accept the key in any of them
    given = (request.headers.get("authorization") or request.headers.get("x-api-key") or "").strip()
    for prefix in ("Bearer ", "Token ", ""):
        if given.startswith(prefix) and secrets.compare_digest(given[len(prefix):].strip().encode(), key.encode()):
            return  # the right key always gets in; only wrong ones are counted, so strangers can't lock Muse out
    print(f"connector: wrong key ({'no auth header' if not given else 'header present, value differs'})")
    now = time.monotonic()
    failures[:] = [t for t in failures if t > now - 60]
    if len(failures) >= FAILS_PER_MINUTE:
        raise HTTPException(429, "Too many wrong keys. Wait a minute.")
    failures.append(now)
    raise HTTPException(401, "Missing or wrong key", headers={"WWW-Authenticate": "Bearer"})


@router.get("/health")
def health():
    return {"ok": True}  # for the tunnel check; says nothing about the data


@router.get("/people", dependencies=[Depends(require_key)])
def people():
    keep = ("id", "name", "role", "lastSeen", "lastSpoke", "topic", "context")
    return [{k: p[k] for k in keep} for p in store.people() if "connector" in p["scope"]]  # only people who ticked it


@router.get("/people/{pid}", dependencies=[Depends(require_key)])
def one_person(pid: str):
    p = store.person(pid)
    if p is None or "connector" not in p["scope"]:
        raise HTTPException(404, "Nobody with that id (or they did not agree to the connector).")
    latest = p["encounters"][0] if p["encounters"] else None
    return {**{k: p[k] for k in ("id", "name", "role", "lastSeen", "lastSpoke", "topic", "context", "howMet")},
            "facts": [f["text"] for f in p["facts"]],
            "about": latest["about"] if latest else None, "lastTime": latest["lastTime"] if latest else None,
            "notes": [n["text"] for n in p["notes"]]}


@router.get("/calls", dependencies=[Depends(require_key)])
def recent_calls(limit: int = Query(5, ge=1, le=20)):
    """The last calls, newest first, with only the people who agreed to the connector."""
    return store.calls(limit, "connector")


def schema(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


STR, NULLABLE = {"type": "string"}, {"type": ["string", "null"]}
PERSON = {"id": STR, "name": STR, "role": {"type": "string", "description": "Who they are to the user, e.g. Your team lead; may be empty"},
          "lastSeen": {**NULLABLE, "description": "Date (YYYY-MM-DD) of the latest call they were on; null if none yet"},
          "lastSpoke": {**NULLABLE, "description": "Date of the latest call where they spoke"},
          "topic": {**NULLABLE, "description": "What that latest call was about"},
          "context": {**NULLABLE, "description": "work, personal, or empty when unsure"}}
OPENAPI = {
    "openapi": "3.1.0",
    "info": {"title": "Hello Again memory", "version": "1.0.0", "description": SUMMARY},
    "components": {"securitySchemes": {"bearer": {"type": "http", "scheme": "bearer"}}},
    "security": [{"bearer": []}],
    "paths": {
        "/connector/calls": {"get": {
            "operationId": "recentCalls", "summary": "The meeting recap: what happened in the user's last calls",
            "description": "Use this for \"what happened in my last meeting?\". Newest first. Each call has when it ended, the app, what it "
                           "was about, the key points, the follow-up actions that were suggested, and who was there with their last conversation.",
            "parameters": [{"name": "limit", "in": "query", "required": False, "schema": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}}],
            "responses": {"200": {"description": "Calls", "content": {"application/json": {"schema": {"type": "array", "items": schema({
                "endedAt": STR, "app": NULLABLE, "topic": STR, "points": {"type": "array", "items": STR},
                "actions": {"type": "array", "items": STR, "description": "Labels of the suggested actions"},
                "people": {"type": "array", "items": schema({"id": STR, "name": STR, "role": STR, "lastTime": STR}, ["id", "name"])}},
                ["endedAt", "topic", "points", "actions", "people"])}}}}}}},
        "/connector/people": {"get": {
            "operationId": "listPeople", "summary": "Everyone the user remembers, with when they last met",
            "responses": {"200": {"description": "People", "content": {"application/json": {"schema": {
                "type": "array", "items": schema(PERSON, list(PERSON))}}}}}}},
        "/connector/people/{id}": {"get": {
            "operationId": "getPerson", "summary": "One person in full: facts, how they met, the last conversation and notes",
            "parameters": [{"name": "id", "in": "path", "required": True, "schema": STR}],
            "responses": {"200": {"description": "The person", "content": {"application/json": {"schema": schema(PERSON | {
                "howMet": {"type": "string", "description": "One line about the first call together: date, app and what it was about; may be empty"},
                "facts": {"type": "array", "items": STR}, "about": NULLABLE, "lastTime": NULLABLE,
                "notes": {"type": "array", "items": STR, "description": "The user's own notes"}}, ["id", "name"])}}},
                          "404": {"description": "Unknown person"}}}},
    },
}


@router.get("/openapi.json", dependencies=[Depends(require_key)])
def openapi_document():
    return OPENAPI


# --- MCP: the same three reads as a JSON-RPC 2.0 tool server, so an MCP client (the Muse app) can use them ---

MCP_VERSION = "2025-06-18"
TOOLS = {
    "list_people": ("Everyone the user remembers, with when they last met and spoke, what it was about and whether it was work or personal.",
                    {"type": "object", "properties": {}}),
    "get_person": ("One person in full: facts, how they met, the last conversation and the user's notes.",
                   {"type": "object", "properties": {"id": {"type": "string", "description": "A person id from list_people"}}, "required": ["id"]}),
    "recent_calls": ("The user's last meetings, newest first: topic, key points, suggested actions and who was there. Use it for "
                     "\"what happened in my last meeting?\".",
                     {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}}}),
}


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        self.code, self.message = code, message


def call_tool(name: object, args: object) -> dict:
    if name not in TOOLS or not isinstance(args, dict):
        raise RpcError(-32602, "Unknown tool or bad arguments")
    if name == "list_people":
        data = people()
    elif name == "get_person":
        if not isinstance(args.get("id"), str) or not args["id"]:
            raise RpcError(-32602, "get_person needs a string id")
        try:
            data = one_person(args["id"])
        except HTTPException:  # unknown, expired or not agreed: a tool error the model can read, not a protocol error
            return {"content": [{"type": "text", "text": "Nobody with that id."}], "isError": True}
    else:
        limit = args.get("limit", 5)
        if type(limit) is not int or not 1 <= limit <= 20:
            raise RpcError(-32602, "limit must be a whole number from 1 to 20")
        data = recent_calls(limit)
    return {"content": [{"type": "text", "text": json.dumps(data, default=str)}]}


def handle(message: object) -> dict | None:
    """One JSON-RPC message: the response object, or None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
    method, params, rid = message["method"], message.get("params") or {}, message.get("id")
    if "id" not in message:
        return None  # notifications/initialized and any other notification: nothing to answer
    try:
        if method == "initialize":
            result = {"protocolVersion": MCP_VERSION, "serverInfo": {"name": "hello-again", "version": "1.0.0"}, "capabilities": {"tools": {}}}
        elif method == "tools/list":
            result = {"tools": [{"name": n, "description": d, "inputSchema": s} for n, (d, s) in TOOLS.items()]}
        elif method == "tools/call":
            if not isinstance(params, dict):
                raise RpcError(-32602, "params must be an object")
            result = call_tool(params.get("name"), params.get("arguments") or {})
        elif method == "ping":
            result = {}
        else:
            raise RpcError(-32601, "Method not found")
    except RpcError as e:
        return {"jsonrpc": "2.0", "id": rid, "error": {"code": e.code, "message": e.message}}
    return {"jsonrpc": "2.0", "id": rid, "result": result}


@router.post("/mcp", dependencies=[Depends(require_key)])
async def mcp(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}})
    replies = [r for r in map(handle, body)] if isinstance(body, list) and body else [handle(body)]
    replies = [r for r in replies if r is not None]
    if not replies:
        return Response(status_code=202)  # only notifications
    return JSONResponse(replies if isinstance(body, list) else replies[0])


@router.get("/mcp", dependencies=[Depends(require_key)])
def mcp_get():
    return JSONResponse({"error": "POST JSON-RPC here"}, status_code=405, headers={"Allow": "POST"})
