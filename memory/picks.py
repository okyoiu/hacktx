
"""Muse Spark extracts useful attendee notes and top picks from a transcript line."""

import json
import os
import re
from functools import lru_cache

from openai import OpenAI

KINDS = {"fact", "common", "place", "event"}
MAX_PICKS = 3

PROMPT = """You help someone on a video call remember people and find shared interests.

People in the call (id: name, existing notes):
{people}

Recent transcript:
{history}

New line from {speaker}: {text}

Return one JSON object only, with this shape:
{{
  "notes": [
    {{"personId": "an ID from the people list", "text": "short useful fact"}}
  ],
  "picks": [
    {{
      "kind": "fact",
      "title": "Short title",
      "detail": "One short explanation",
      "search": null
    }}
  ]
}}

Allowed kinds: fact, common, place, event.
For place/event picks, search must be a concise Google Maps or Google Events
query grounded in the transcript, including the city when known. These queries
are executed by SerpApi only after this response succeeds. Do not invent venues
or events; search for real options related to the conversation.
For fact/common picks, search should be null.
Use [] when there is nothing useful to save or suggest.
Only use person IDs from the supplied list. Do not infer private facts.
"""


@lru_cache(maxsize=1)
def client() -> OpenAI:
    key = os.getenv("MODEL_API_KEY")
    if not key:
        raise RuntimeError(
            "MODEL_API_KEY is empty. Add your Meta Model API key to .env."
        )

    return OpenAI(
        base_url="https://api.meta.ai/v1",
        api_key=key,
    )


def extract(
    speaker: str,
    text: str,
    people: dict[str, dict],
    history: list[str],
) -> dict:
    roster = "\n".join(
        f"{pid}: {person['name']} "
        f"({'; '.join(person.get('notes') or []) or 'nothing yet'})"
        for pid, person in people.items()
    )

    reply = client().chat.completions.create(
        model=os.getenv("MUSE_SPARK_MODEL", "muse-spark-1.3"),
        messages=[
            {
                "role": "user",
                "content": PROMPT.format(
                    people=roster or "(nobody recognized yet)",
                    history="\n".join(history) or "(none)",
                    speaker=speaker,
                    text=text,
                ),
            }
        ],
        temperature=0.2,
    )

    content = reply.choices[0].message.content or ""
    return parse(content, set(people))


def parse(reply: str, known_ids: set[str]) -> dict:
    """Extract and validate a JSON response, even if surrounded by Markdown."""
    empty = {"notes": [], "picks": []}

    # Find the JSON object if the model wraps it in fences or prose.
    match = re.search(r"\{.*\}", reply, re.S)
    if not match:
        return empty

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return empty

    if not isinstance(data, dict):
        return empty

    raw_notes = data.get("notes")
    raw_picks = data.get("picks")

    notes = []
    if isinstance(raw_notes, list):
        for note in raw_notes:
            if not isinstance(note, dict):
                continue

            pid = note.get("personId")
            value = note.get("text")

            if pid not in known_ids or not isinstance(value, str):
                continue

            value = value.strip()
            if value:
                notes.append({"personId": pid, "text": value[:200]})

    picks = []
    if isinstance(raw_picks, list):
        for pick in raw_picks:
            if not isinstance(pick, dict):
                continue

            kind = pick.get("kind")
            title = pick.get("title")

            if kind not in KINDS or not isinstance(title, str) or not title.strip():
                continue

            search = pick.get("search")
            picks.append(
                {
                    "kind": kind,
                    "title": title.strip()[:80],
                    "detail": str(pick.get("detail") or "")[:160],
                    "search": search[:300] if isinstance(search, str) else None,
                }
            )

    return {"notes": notes, "picks": picks[:MAX_PICKS]}
