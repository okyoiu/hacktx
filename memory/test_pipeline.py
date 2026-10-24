import asyncio
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks

from memory import app, pipeline


def test_meta_precedes_search_and_only_explicit_queries_search(monkeypatch):
    order = []
    note = {"personId": "p_jordan", "text": "Likes climbing"}
    fact = {"kind": "fact", "title": "Likes climbing", "search": "ignored"}

    def meta(*args):
        order.append("meta")
        return {"notes": [note], "picks": [
            fact,
            {"kind": "place", "title": "Gym", "search": "climbing Austin"},
            {"kind": "event", "title": "Meetup", "search": "  "},
        ]}

    def search(kind, query):
        order.append((kind, query))
        return {"title": "Real gym", "detail": "Austin"}

    monkeypatch.setattr(pipeline.picks, "extract", meta)
    monkeypatch.setattr(pipeline.serp, "lookup", search)
    result = pipeline.process("Jordan", "Let's climb in Austin", {}, [])
    assert order == ["meta", ("place", "climbing Austin")]
    assert result["notes"] == [note]
    assert result["picks"] == [fact, {
        "kind": "place", "title": "Real gym", "detail": "Austin", "search": "climbing Austin",
    }]


def test_meta_failure_never_calls_serpapi(monkeypatch):
    search = Mock()
    monkeypatch.setattr(pipeline.serp, "lookup", search)
    monkeypatch.setattr(pipeline.picks, "extract", Mock(side_effect=RuntimeError("Meta unavailable")))
    with pytest.raises(RuntimeError, match="Meta unavailable"):
        pipeline.process("Jordan", "Find gyms", {}, [])
    search.assert_not_called()


@pytest.mark.parametrize("outcome", [None, pipeline.serp.SerpApiError("Unavailable")])
def test_failed_search_preserves_meta_notes_and_other_picks(monkeypatch, outcome):
    fact = {"kind": "common", "title": "Both climb"}
    monkeypatch.setattr(pipeline.picks, "extract", lambda *args: {
        "notes": [{"text": "Likes climbing"}], "picks": [
            {"kind": "event", "title": "Meetup", "search": "Austin climbing events"}, fact,
        ],
    })
    search = Mock(side_effect=outcome) if isinstance(outcome, Exception) else Mock(return_value=outcome)
    monkeypatch.setattr(pipeline.serp, "lookup", search)
    result = pipeline.process("Jordan", "Climbing", {}, [])
    assert result["picks"] == [fact]
    assert result["notes"] == [{"text": "Likes climbing"}]


def test_partial_or_blank_transcripts_never_schedule_pipeline(monkeypatch):
    async def push(event):
        pass

    monkeypatch.setattr(app, "push", push)
    for line in [app.Line(speaker="Jordan", text="Climbing", final=False),
                 app.Line(speaker="Jordan", text="  ", final=True)]:
        tasks = BackgroundTasks()
        asyncio.run(app.transcript(line, tasks))
        assert tasks.tasks == []
    tasks = BackgroundTasks()
    asyncio.run(app.transcript(app.Line(speaker="Jordan", text="Climbing", final=True), tasks))
    assert len(tasks.tasks) == 1
