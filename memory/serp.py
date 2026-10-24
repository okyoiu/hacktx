"""SerpApi lookups that turn a place or event pick into a real result."""
import os
from functools import lru_cache

import httpx

URL = "https://serpapi.com/search.json"


@lru_cache(maxsize=256)
def lookup(kind: str, query: str) -> dict | None:
    """First Google Maps place (kind="place") or Google Events result (kind="event"); cached per query."""
    params = {"q": query, "api_key": os.environ["SERPAPI_KEY"], "hl": "en", "gl": "us"}
    if kind == "place":
        params |= {"engine": "google_maps", "type": "search"}
        if ll := os.getenv("DEMO_LL"):
            params["ll"] = ll
    else:
        params["engine"] = "google_events"
    r = httpx.get(URL, params=params, timeout=15)
    r.raise_for_status()
    return first(kind, r.json())


def first(kind: str, data: dict) -> dict | None:
    """Shape the top SerpApi hit as {title, detail}."""
    if kind == "place":
        # Maps returns place_results instead of a list when the query names one place
        hit = (data.get("local_results") or [None])[0] or data.get("place_results")
        if not hit:
            return None
        parts = [hit.get("type"), hit.get("address"), hit.get("rating") and f"{hit['rating']} stars"]
    else:
        hit = (data.get("events_results") or [None])[0]
        if not hit:
            return None
        parts = [(hit.get("date") or {}).get("when"), ", ".join(hit.get("address") or [])]
    return {"title": hit.get("title", ""), "detail": " · ".join(p for p in parts if p)}
