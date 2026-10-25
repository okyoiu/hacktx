"""Contain Google search inside the Meta-driven flow: every SerpApi call happens here.

Muse Spark writes the search query into a Live insights action; SerpApi runs only
when the user clicks that action (or asks a search question). app.py never calls
SerpApi itself, blank queries never reach it, and a failed search ends that one
response as an error while the call goes on.
"""
from urllib.parse import quote_plus

from memory import picks, serp

SerpApiError = serp.SerpApiError
LINKS = {"places": "https://www.google.com/maps/search/?api=1&query=", "events": "https://www.google.com/search?q="}


def lookup(kind: str, query: str | None) -> tuple[str, list[dict], list[dict]]:
    """A places or events action: the first real result and a link to it, plus up to 5 result rows for the overlay."""
    query = (query or "").strip()
    if not query:
        return "There was nothing to search for.", [], []
    hit = serp.lookup(kind[:-1], query)  # "places" -> "place", "events" -> "event"
    if not hit:
        return f'Nothing found for "{query}".', [], []
    return (f"{hit['title']}\n{hit['detail']}".strip(), [{"title": hit["title"], "url": LINKS[kind] + quote_plus(hit["title"])}],
            hit.get("items", []))


def search(query: str | None, people: dict, lines: list[str]) -> tuple[str, list[dict], list[dict]]:
    """A web search: SerpApi's top results, summarised by Muse Spark, which cites them as sources."""
    query = (query or "").strip()
    if not query:
        return "There was nothing to search for.", [], []
    results = serp.search(query)
    if not results:
        return f'No web results for "{query}".', [], []
    rows = [{"title": r["title"], "detail": " ".join(r["snippet"].split())[:120], "url": r["url"]} for r in results[:5]]
    return picks.answer("search", query, people, lines, results), [{"title": r["title"], "url": r["url"]} for r in results], rows
