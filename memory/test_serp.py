"""Offline connection checks; no API credits, Muse key or database required."""
import httpx
import pytest

from memory import serp


@pytest.fixture(autouse=True)
def configuration(monkeypatch):
    monkeypatch.setenv("SERPAPI_KEY", "test-secret")
    monkeypatch.setenv("DEMO_LL", "@30.2672,-97.7431,13z")
    monkeypatch.setenv("SERPAPI_LOCATION", "Austin, Texas, United States")
    serp._lookup.cache_clear()
    serp._search.cache_clear()
    yield
    serp._lookup.cache_clear()
    serp._search.cache_clear()


def test_maps_connection_cache_and_location(monkeypatch):
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs["params"])
        return httpx.Response(200, json={"local_results": [{"title": "Gym"}]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(serp.httpx, "get", get)
    hit = serp.lookup("place", "  Climbing   Austin ")
    hit["title"] = "mutated"
    assert serp.lookup("place", "climbing austin")["title"] == "Gym"
    assert len(calls) == 1
    assert calls[0]["engine"] == "google_maps"
    assert calls[0]["type"] == "search"
    assert calls[0]["ll"] == "@30.2672,-97.7431,13z"
    monkeypatch.setenv("DEMO_LL", "@40,-74,13z")
    serp.lookup("place", "climbing austin")
    assert len(calls) == 2


def test_event_connection(monkeypatch):
    def get(url, **kwargs):
        assert kwargs["params"]["engine"] == "google_events"
        assert kwargs["params"]["location"] == "Austin, Texas, United States"
        assert "ll" not in kwargs["params"]
        return httpx.Response(200, json={"events_results": [{
            "title": "Climbing meetup", "date": {"when": "Saturday"}, "address": "Austin",
        }]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(serp.httpx, "get", get)
    assert serp.lookup("event", "climbing meetups") == {
        "title": "Climbing meetup", "detail": "Saturday · Austin",
    }


@pytest.mark.parametrize("failure", ["http", "timeout", "json", "api"])
def test_errors_are_safe_and_not_cached(monkeypatch, failure):
    calls = []

    def get(url, **kwargs):
        calls.append(1)
        request = httpx.Request("GET", url, params=kwargs["params"])
        if failure == "timeout":
            raise httpx.ReadTimeout("test-secret", request=request)
        if failure == "json":
            return httpx.Response(200, text="broken", request=request)
        return httpx.Response(401 if failure == "http" else 200,
                              json={"error": "test-secret"}, request=request)

    monkeypatch.setattr(serp.httpx, "get", get)
    for _ in range(2):
        with pytest.raises(serp.SerpApiError) as error:
            serp.lookup("place", "gym")
        assert "test-secret" not in str(error.value)
    assert len(calls) == 2


def test_missing_key_and_bad_inputs(monkeypatch):
    monkeypatch.delenv("SERPAPI_KEY")
    with pytest.raises(serp.SerpApiError, match="SERPAPI_KEY"):
        serp.lookup("place", "gym")
    with pytest.raises(ValueError):
        serp.lookup("fact", "gym")
    with pytest.raises(ValueError):
        serp.lookup("place", "  ")


def test_no_results_is_empty_not_an_error(monkeypatch):
    def get(url, **kwargs):
        return httpx.Response(200, json={"error": "Google hasn't returned any results for this query.",
                                         "search_metadata": {"status": "Success"}}, request=httpx.Request("GET", url))

    monkeypatch.setattr(serp.httpx, "get", get)
    assert serp.lookup("event", "climbing meetup") is None
    assert serp.search("climbing meetup") == []


def test_search_returns_top_three_linked_results(monkeypatch):
    def get(url, **kwargs):
        assert kwargs["params"]["engine"] == "google"
        hits = [{"title": "No link"}] + [{"title": f"R{i}", "link": f"https://e.com/{i}"} for i in range(4)]
        return httpx.Response(200, json={"organic_results": hits}, request=httpx.Request("GET", url))

    monkeypatch.setattr(serp.httpx, "get", get)
    assert serp.search("  Climbing  Gyms ") == [{"title": f"R{i}", "url": f"https://e.com/{i}", "snippet": ""} for i in range(3)]


def test_empty_and_single_place_results():
    assert serp.first("place", {}) is None
    assert serp.first("event", {"events_results": []}) is None
    assert serp.first("place", {"place_results": {"title": "Gym"}}) == {"title": "Gym", "detail": ""}
    assert serp.first("place", {"local_results": [{"address": "No name"}]}) is None
