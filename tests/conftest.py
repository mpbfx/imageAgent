"""Shared pytest fixtures and helpers for the GenClaw reproduction tests."""

import importlib.util

import pytest

# The deterministic core (schema, source compilation, review rules, fixture
# agent, graph state) must import and test without a browser or langgraph.
# Tests that genuinely need those are gated behind these skips.

_HAS_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None
_HAS_LANGGRAPH = importlib.util.find_spec("langgraph") is not None


def pytest_collection_modifyitems(config, items):
    skip_render = pytest.mark.skip(reason="playwright not installed (no PNG rasterization)")
    skip_lg = pytest.mark.skip(reason="langgraph not installed")
    for item in items:
        if "render" in item.keywords and not _HAS_PLAYWRIGHT:
            item.add_marker(skip_render)
        if "langgraph" in item.keywords and not _HAS_LANGGRAPH:
            item.add_marker(skip_lg)


@pytest.fixture
def tmp_run_dir(tmp_path):
    """A clean output base directory for artifact tests."""
    d = tmp_path / "outputs" / "runs"
    d.mkdir(parents=True)
    return d
