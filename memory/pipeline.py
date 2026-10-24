"""Contain Google search inside the Meta transcript-processing operation."""
from memory import picks, serp


def process(speaker: str, text: str, people: dict, history: list[str]) -> dict:
    """Call Meta first; only its explicit place/event queries can call SerpApi.

    A failed Meta call propagates without making any Google requests. Ordinary
    notes and shared interests pass through without touching SerpApi.
    """
    result = picks.extract(speaker, text, people, history)
    resolved = []
    for pick in result["picks"]:
        if pick["kind"] not in {"place", "event"}:
            resolved.append(pick)
            continue
        query = pick.get("search")
        if not isinstance(query, str) or not query.strip():
            continue
        try:
            hit = serp.lookup(pick["kind"], query)
        except (serp.SerpApiError, ValueError) as exc:
            print(f"serpapi failed: {exc}")
            continue
        if hit:
            resolved.append({**pick, **hit})
    return {"notes": result["notes"], "picks": resolved}
