"""Muse Spark reads one transcript line and returns notes about people plus the top picks to show."""
import json
import os
import re
from functools import lru_cache

from openai import OpenAI

KINDS = {"fact", "common", "place", "event"}
MAX_PICKS = 3

PROMPT = """You help someone on a video call remember the people they talk to and turn shared interests into plans.

People in the call (id: name, what we already know):
{people}

Recent lines:
{history}

New line from {speaker}: "{text}"

Reply with JSON only, no prose:
{{"notes": [{{"personId": "<id from the list>", "text": "short fact worth remembering about them"}}],
  "picks": [{{"kind": "fact" | "common" | "place" | "event", "title": "under 8 words", "detail": "one short line", "search": "Google Maps or events search, or null"}}]}}
Use [] when the line has nothing worth keeping. Only use ids from the list."""


@lru_cache(maxsize=1)
def client() -> OpenAI:
    # Meta Model API is OpenAI-compatible: same SDK, different base URL
    return OpenAI(base_url="https://api.meta.ai/v1", api_key=os.environ["MODEL_API_KEY"])


def extract(speaker: str, text: str, people: dict[str, dict], history: list[str]) -> dict:
    roster = "\n".join(
        f"{pid}: {p['name']} ({'; '.join(p.get('notes') or []) or 'nothing yet'})" for pid, p in people.items()
    )
    reply = client().chat.completions.create(
        model=os.getenv("MUSE_SPARK_MODEL", "muse-spark-1.3"),
        messages=[{"role": "user", "content": PROMPT.format(
            people=roster or "(nobody recognized yet)",
            history="\n".join(history) or "(none)",
            speaker=speaker,
            text=text,
        )}],
        temperature=0.2,
    )
    return parse(reply.choices[0].message.content or "", set(people))


def parse(reply: str, known_ids: set[str]) -> dict:
    """Pull the JSON object out of a model reply and drop anything malformed or about unknown people."""
    empty = {"notes": [], "picks": []}
    m = re.search(r"\{.*\}", reply, re.S)
    if not m:
        return empty
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return empty
    if not isinstance(data, dict):
        return empty
    notes = [
        {"personId": n["personId"], "text": str(n["text"])[:200]}
        for n in data.get("notes") or []
        if isinstance(n, dict) and n.get("personId") in known_ids and n.get("text")
    ]
    picks = [
        {
            "kind": p["kind"],
            "title": str(p["title"])[:80],
            "detail": str(p.get("detail") or "")[:160],
            "search": p.get("search") if isinstance(p.get("search"), str) else None,
        }
        for p in data.get("picks") or []
        if isinstance(p, dict) and p.get("kind") in KINDS and p.get("title")
    ]
    return {"notes": notes, "picks": picks[:MAX_PICKS]}
