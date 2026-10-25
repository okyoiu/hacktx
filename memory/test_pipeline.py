import asyncio
from unittest.mock import Mock

import pytest

from memory import app, pipeline


def test_places_use_only_the_query_muse_wrote(monkeypatch):
    search = Mock(return_value={"title": "Real gym", "detail": "Austin"})
    monkeypatch.setattr(pipeline.serp, "lookup", search)
    text, sources = pipeline.lookup("places", "  climbing gyms Austin ")
    search.assert_called_once_with("place", "climbing gyms Austin")
    assert text == "Real gym\nAustin"
    assert sources == [{"title": "Real gym", "url": "https://www.google.com/maps/search/?api=1&query=Real+gym"}]


@pytest.mark.parametrize("query", [None, "", "   "])
def test_blank_queries_never_reach_serpapi(monkeypatch, query):
    lookup, web = Mock(), Mock()
    monkeypatch.setattr(pipeline.serp, "lookup", lookup)
    monkeypatch.setattr(pipeline.serp, "search", web)
    assert pipeline.lookup("events", query) == ("There was nothing to search for.", [])
    assert pipeline.search(query, {}, []) == ("There was nothing to search for.", [])
    lookup.assert_not_called()
    web.assert_not_called()


def test_no_result_is_said_plainly_and_never_invented(monkeypatch):
    monkeypatch.setattr(pipeline.serp, "lookup", Mock(return_value=None))
    assert pipeline.lookup("events", "Austin climbing meetup") == ('Nothing found for "Austin climbing meetup".', [])


def test_search_answers_from_results_and_cites_them(monkeypatch):
    results = [{"title": "Windsurf deal", "url": "https://example.com/a", "snippet": "…"}]
    monkeypatch.setattr(pipeline.serp, "search", Mock(return_value=results))
    summarise = Mock(return_value="Cognition bought Windsurf [1].")
    monkeypatch.setattr(pipeline.picks, "answer", summarise)
    text, sources = pipeline.search("who bought Windsurf", {}, ["Neel: who bought Windsurf?"])
    summarise.assert_called_once_with("search", "who bought Windsurf", {}, ["Neel: who bought Windsurf?"], results)
    assert text == "Cognition bought Windsurf [1]."
    assert sources == [{"title": "Windsurf deal", "url": "https://example.com/a"}]


def test_search_failure_surfaces_as_serpapi_error(monkeypatch):
    monkeypatch.setattr(pipeline.serp, "search", Mock(side_effect=pipeline.SerpApiError("Unavailable")))
    with pytest.raises(pipeline.SerpApiError):
        pipeline.search("anything", {}, [])


def test_partial_or_blank_transcripts_never_schedule_muse(monkeypatch):
    async def push(event):
        pass

    monkeypatch.setattr(app, "push", push)
    monkeypatch.setitem(app.listening, "on", True)
    monkeypatch.setattr(app, "fresh", [])
    monkeypatch.setattr(app, "wake", asyncio.Event())
    for line in [app.Line(speaker="Jordan", text="Climbing", final=False),
                 app.Line(speaker="Jordan", text="  ", final=True)]:
        asyncio.run(app.transcript(line))
        assert app.fresh == [] and not app.wake.is_set()
    asyncio.run(app.transcript(app.Line(speaker="Jordan", text="Climbing", final=True)))
    assert app.fresh == ["Jordan: Climbing"] and app.wake.is_set()
    app.fresh.clear()
    app.wake.clear()
