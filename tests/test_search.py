"""Tests for the search/knowledge-grounding layer (paper §3.1-3.2)."""

import json

import pytest

from genclaw.pipeline import Pipeline
from genclaw.schemas import (
    CanvasBackend,
    CanvasPlan,
    CanvasSize,
    KnowledgeRef,
    TaskType,
)
from genclaw.search import NullSearchProvider, SearchProvider, SerperSearchProvider


def _kg_plan(request_id="kg-1"):
    return CanvasPlan(
        request_id=request_id,
        prompt="poster of the 2026 World Cup host cities",
        task_type=TaskType.knowledge_grounded,
        backend=CanvasBackend.html,
        size=CanvasSize(width=400, height=600),
    )


class StubAgent:
    """Returns a fixed knowledge-grounded plan regardless of prompt."""

    def conceptualize(self, prompt, task_type=None, request_id=None):
        return _kg_plan(request_id or "kg-1")


class RecordingSearch(SearchProvider):
    name = "recording"

    def __init__(self):
        self.queries = []

    def search(self, query, *, max_results=5):
        self.queries.append(query)
        return [
            KnowledgeRef(claim="Final hosted in 2026", source="https://example.com", confidence=0.9)
        ]


def test_null_search_returns_nothing():
    assert NullSearchProvider().search("anything") == []


def test_should_search_only_for_knowledge_grounded():
    p = NullSearchProvider()
    assert p.should_search("x", TaskType.knowledge_grounded) is True
    assert p.should_search("x", TaskType.composition) is False
    assert p.should_search("x", None) is False


def test_search_node_merges_knowledge_into_plan(tmp_path):
    search = RecordingSearch()
    pipeline = Pipeline(
        agent=StubAgent(),
        search=search,
        base_dir=tmp_path / "runs",
    )
    state = pipeline.run("poster of the 2026 World Cup host cities")

    # The search provider was invoked and its facts landed in the plan.
    assert search.queries
    assert len(state.plan.knowledge) == 1
    assert state.plan.knowledge[0].source == "https://example.com"
    # And the persisted plan artifact reflects the merged knowledge.
    plan_json = json.loads(state.artifacts.plan_path.read_text(encoding="utf-8"))
    assert plan_json["knowledge"][0]["claim"] == "Final hosted in 2026"


def test_search_node_traces_skip_for_non_knowledge(tmp_path):
    # Composition fixture is not knowledge-grounded; search node no-ops.
    pipeline = Pipeline(base_dir=tmp_path / "runs")
    state = pipeline.run("three red circles on the left")
    events = state.artifacts.trace_path.read_text(encoding="utf-8").splitlines()
    search_events = [json.loads(e) for e in events if json.loads(e)["stage"] == "search"]
    assert search_events
    assert "skipped" in search_events[0]["input_summary"]
    assert state.plan.knowledge == []


def test_search_failure_is_non_fatal(tmp_path):
    class FailingSearch(SearchProvider):
        name = "failing"

        def search(self, query, *, max_results=5):
            raise RuntimeError("network down")

    pipeline = Pipeline(
        agent=StubAgent(),
        search=FailingSearch(),
        base_dir=tmp_path / "runs",
    )
    state = pipeline.run("poster of the 2026 World Cup host cities")
    # The run still completes (render/generate/review happened) despite search failing.
    assert state.rendered_canvas is not None
    assert any("search:" in e for e in state.errors)
    assert state.artifacts.error_path("search").exists()


def test_serper_search_provider_missing_key():
    """SerperSearchProvider should raise when API key is missing."""
    import os
    env = {k: v for k, v in os.environ.items() if k != "SERPER_API_KEY"}
    provider = SerperSearchProvider(env=env)

    from genclaw.config import ProviderNotConfiguredError
    with pytest.raises(ProviderNotConfiguredError):
        provider.search("test query")


def test_serper_search_provider_initialization():
    """SerperSearchProvider should initialize with custom base_url from env."""
    import os
    env = {
        "SERPER_API_KEY": "test-key",
        "SERPER_BASE_URL": "https://custom.serper.dev",
    }
    provider = SerperSearchProvider(env=env)
    assert provider._api_key == "test-key"
    assert provider.base_url == "https://custom.serper.dev"


def test_serper_search_provider_default_base_url():
    """SerperSearchProvider should use default base_url when not specified."""
    env = {"SERPER_API_KEY": "test-key"}
    provider = SerperSearchProvider(env=env)
    assert provider.base_url == "https://google.serper.dev"
