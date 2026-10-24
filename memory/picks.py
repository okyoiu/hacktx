
"""Muse Spark: per-person notes plus the Live insights state from the transcript, and answers for the AI response panel."""

import json
import os
import re
from functools import lru_cache

import openai
from openai import OpenAI

ACTION_KINDS = {"define", "search", "places", "events", "recall", "followups", "helpful"}
QUERY_KINDS = {"define", "search", "places", "events"}  # kinds that act on a search query or term
MAX_POINTS = 3
MAX_ACTIONS = 4
POINT_CHARS = 120  # each point must stay under this

PROMPT = """You help someone on a live video call: keep a short running summary, suggest useful one-click actions, and remember facts about the people in it.

People in the call (id: name, existing notes):
{people}

Earlier transcript:
{history}

New lines:
{new}

Return one JSON object only, with this shape:
{{
  "notes": [
    {{"personId": "an ID from the people list", "text": "short useful fact from the new lines"}}
  ],
  "topic": "What the conversation is about now, under 8 words",
  "points": ["The most useful thing to keep in mind, under 120 characters"],
  "actions": [
    {{"kind": "places", "label": "Find climbing gyms near South Congress", "query": "climbing gyms near South Congress Austin"}},
    {{"kind": "recall", "label": "Remind me who Maya is", "personId": "an ID from the people list"}}
  ]
}}

At most 3 points and 4 actions. Action kinds:
- define: explain a term that came up; query is the term
- search: look something up on the web; query is the search
- places: find a real place; query is a Google Maps search
- events: find an event; query is an events search
- recall: remind the user who someone in the call is; personId is their ID
- followups: suggest follow-up questions to ask
- helpful: give helpful information about the conversation
Take notes from the new lines only. Use [] when there is nothing useful.
Only use person IDs from the supplied list. Do not infer private facts.
"""

ANSWER = """You help someone during a live video call. Answer in plain text, at most 5 short lines, no Markdown headings.

People in the call (id: name, existing notes):
{people}

Recent transcript:
{history}

{task}
"""

TASKS = {
    "ask": "Answer their question: {query}",
    "define": "Explain \"{query}\" in two or three plain sentences, as it came up in this conversation.",
    "followups": "Suggest three short follow-up questions they could ask next, one per line.",
    "helpful": "Give the most helpful information for them right now about this conversation.",
    "search": "Answer \"{query}\" using only these web results, citing them as [1], [2], [3]:\n{results}",
}

SUMMARY = """A video call just ended. For each person below, write what the user should remember next time they meet.

People in the call (id: name, existing notes):
{people}

Transcript:
{transcript}

Return one JSON object only, with this shape:
{{
  "people": [
    {{
      "personId": "an ID from the people list",
      "about": "Who they are: a few short facts",
      "lastTime": "What you talked about this time, 1-2 short lines"
    }}
  ]
}}

Only include people from the list, and leave out anyone the transcript says nothing about.
Do not infer private facts.
"""
SUMMARY_LINES = 500


class MuseError(RuntimeError):
    """Safe to show the user: never includes the API key."""


@lru_cache(maxsize=1)
def client() -> OpenAI:
    key = os.getenv("MODEL_API_KEY")
    if not key:
        raise MuseError(
            "Add MODEL_API_KEY to .env (your Meta Model API key) and restart the memory service"
        )

    return OpenAI(
        base_url="https://api.meta.ai/v1",
        api_key=key,
        timeout=30,  # a live overlay can't wait out the SDK's 10-minute default
    )


def chat(prompt: str) -> str:
    """One Muse Spark reply; every API failure becomes a MuseError."""
    try:
        reply = client().chat.completions.create(
            model=os.getenv("MUSE_SPARK_MODEL", "muse-spark-1.3"),
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
    except openai.APIStatusError as exc:
        raise MuseError(
            f"Muse Spark returned HTTP {exc.status_code}; check MODEL_API_KEY and MUSE_SPARK_MODEL"
        ) from None
    except openai.APIConnectionError:
        raise MuseError("Muse Spark could not be reached or timed out; try again") from None
    return reply.choices[0].message.content or ""


def roster(people: dict[str, dict]) -> str:
    return "\n".join(
        f"{pid}: {person['name']} "
        f"({'; '.join(person.get('notes') or []) or 'nothing yet'})"
        for pid, person in people.items()
    ) or "(nobody recognized yet)"


def extract(
    people: dict[str, dict],
    history: list[str],
    new: list[str],
) -> dict:
    """Notes from the new lines plus the whole current insights state."""
    content = chat(
        PROMPT.format(
            people=roster(people),
            history="\n".join(history) or "(none)",
            new="\n".join(new),
        )
    )
    return parse(content, set(people))


def answer(
    kind: str,
    query: str,
    people: dict[str, dict],
    history: list[str],
    results: list[dict] | None = None,
) -> str:
    """Muse Spark's answer for an ask, define, followups, helpful or search (with its web results)."""
    numbered = "\n".join(
        f"[{i}] {r['title']}: {r['snippet']} ({r['url']})"
        for i, r in enumerate(results or [], 1)
    )
    task = TASKS[kind].format(query=query, results=numbered)
    return chat(
        ANSWER.format(
            people=roster(people),
            history="\n".join(history) or "(none)",
            task=task,
        )
    ).strip()


def summarise(people: dict[str, dict], lines: list[str]) -> list[dict]:
    """About and last-time summaries for the people of a finished call, from its transcript."""
    content = chat(
        SUMMARY.format(
            people=roster(people),
            # shortcut: only the last SUMMARY_LINES lines; summarise in chunks if calls run longer
            transcript="\n".join(lines[-SUMMARY_LINES:]),
        )
    )
    return parse_summary(content, set(people))


def parse_summary(reply: str, known_ids: set[str]) -> list[dict]:
    """Validated [{personId, about, lastTime}], at most one per known person."""
    match = re.search(r"\{.*\}", reply, re.S)
    if not match:
        return []

    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []

    if not isinstance(data, dict) or not isinstance(data.get("people"), list):
        return []

    out = []
    seen = set()
    for entry in data["people"]:
        if not isinstance(entry, dict):
            continue

        pid = entry.get("personId")
        about = entry.get("about")
        last = entry.get("lastTime")

        if pid not in known_ids or pid in seen:
            continue
        if not isinstance(about, str) or not isinstance(last, str):
            continue

        about, last = about.strip(), last.strip()
        if about and last:
            seen.add(pid)
            out.append({"personId": pid, "about": about[:300], "lastTime": last[:240]})

    return out


def parse(reply: str, known_ids: set[str]) -> dict:
    """Extract and validate a JSON response, even if surrounded by Markdown."""
    empty = {"notes": [], "topic": "", "points": [], "actions": []}

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
    raw_points = data.get("points")
    raw_actions = data.get("actions")

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

    topic = data.get("topic")
    topic = topic.strip()[:80] if isinstance(topic, str) else ""

    points = []
    if isinstance(raw_points, list):
        for point in raw_points:
            if not isinstance(point, str) or not point.strip():
                continue

            point = point.strip()
            if len(point) >= POINT_CHARS:
                point = point[: POINT_CHARS - 2].rstrip() + "…"
            points.append(point)

    actions = []
    if isinstance(raw_actions, list):
        for action in raw_actions:
            if not isinstance(action, dict):
                continue

            kind = action.get("kind")
            label = action.get("label")

            if kind not in ACTION_KINDS or not isinstance(label, str) or not label.strip():
                continue

            label = label.strip()[:80]
            pid = action.get("personId")
            if kind == "recall" and pid not in known_ids:
                continue

            query = action.get("query")
            query = query.strip()[:300] if isinstance(query, str) else ""
            actions.append(
                {
                    "kind": kind,
                    "label": label,
                    # the label works as a search when the model leaves query out
                    "query": (query or label) if kind in QUERY_KINDS else None,
                    "personId": pid if kind == "recall" else None,
                }
            )

    return {
        "notes": notes,
        "topic": topic,
        "points": points[:MAX_POINTS],
        "actions": actions[:MAX_ACTIONS],
    }
