"""SerpApi lookups that turn a place or event pick into a real result."""
import os
from functools import lru_cache
from threading import Lock

import httpx

URL = "https://serpapi.com/search.json"
_lock = Lock()


class SerpApiError(RuntimeError):
    """A safe-to-log error: never includes the credential-bearing request URL."""


def lookup(kind: str, query: str) -> dict | None:
    """Look up a pick, caching normalized queries for this server process.

    Set SERPAPI_KEY in .env. DEMO_LL centers Maps; events default to Austin
    unless SERPAPI_LOCATION is set. Run this module directly to check setup.
    """
    if kind not in {"place", "event"}:
        raise ValueError("SerpApi kind must be 'place' or 'event'")
    query = " ".join(query.split())
    if not query:
        raise ValueError("SerpApi query must not be empty")
    key = os.getenv("SERPAPI_KEY", "").strip()
    if not key:
        raise SerpApiError("Set SERPAPI_KEY in .env and restart the memory service")
    ll = os.getenv("DEMO_LL", "@30.2672,-97.7431,13z").strip()
    location = os.getenv("SERPAPI_LOCATION", "Austin, Texas, United States").strip()
    # Coalesce concurrent repeated queries instead of spending credits twice.
    with _lock:
        hit = _lookup(kind, query.casefold(), key, ll, location)
        return dict(hit) if hit else None


@lru_cache(maxsize=256)
def _lookup(kind: str, query: str, key: str, ll: str, location: str) -> dict | None:
    params = {"q": query, "api_key": key, "hl": "en", "gl": "us"}
    if kind == "place":
        params |= {"engine": "google_maps", "type": "search"}
        if ll:
            params["ll"] = ll
    else:
        params["engine"] = "google_events"
        if location:
            params["location"] = location
    try:
        r = httpx.get(URL, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()
    except httpx.HTTPStatusError as exc:
        raise SerpApiError(f"SerpApi returned HTTP {exc.response.status_code}; check key and quota") from None
    except httpx.RequestError:
        raise SerpApiError("SerpApi request failed or timed out; try again") from None
    except ValueError:
        raise SerpApiError("SerpApi returned invalid JSON") from None
    if not isinstance(data, dict) or data.get("error"):
        raise SerpApiError("SerpApi could not complete the search; check key, quota and query")
    return first(kind, data)


def first(kind: str, data: dict) -> dict | None:
    """Shape the top SerpApi hit as {title, detail}."""
    if kind == "place":
        # Maps returns place_results instead of a list when the query names one place
        hit = (data.get("local_results") or [None])[0] or data.get("place_results")
        if not hit or not hit.get("title"):
            return None
        parts = [hit.get("type"), hit.get("address"), hit.get("rating") and f"{hit['rating']} stars"]
    else:
        hit = (data.get("events_results") or [None])[0]
        if not hit or not hit.get("title"):
            return None
        address = hit.get("address") or []
        parts = [(hit.get("date") or {}).get("when"), address if isinstance(address, str) else ", ".join(address)]
    return {"title": hit.get("title", ""), "detail": " · ".join(p for p in parts if p)}


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["place", "event"])
    parser.add_argument("query", help='For example: "climbing gyms in Austin"')
    args = parser.parse_args()
    try:
        print(json.dumps(lookup(args.kind, args.query), ensure_ascii=False, indent=2))
    except (SerpApiError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
