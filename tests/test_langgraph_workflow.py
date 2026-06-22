"""Tests for the routing logic and LangGraph wiring (plan task 11).

The route-function tests are pure and always run. The compiled-graph test is
gated behind the ``langgraph`` marker (skipped when langgraph is absent).
"""

import pytest

from genclaw.graph.routes import FINISH, REVISE, route_after_review
from genclaw.graph.state import GenClawState
from genclaw.schemas import ReviewResult


def _state(passed=None, revision_count=0, max_revisions=1):
    state = GenClawState.from_prompt("r", "p", max_revisions=max_revisions)
    state.revision_count = revision_count
    if passed is not None:
        state.review_result = ReviewResult(passed=passed, score=1.0 if passed else 0.0)
    return state


def test_route_finishes_when_review_passes():
    assert route_after_review(_state(passed=True)) == FINISH


def test_route_revises_when_failed_under_budget():
    assert route_after_review(_state(passed=False, revision_count=0, max_revisions=1)) == REVISE


def test_route_finishes_when_failed_at_budget():
    assert route_after_review(_state(passed=False, revision_count=1, max_revisions=1)) == FINISH


def test_route_finishes_when_no_review():
    assert route_after_review(_state(passed=None)) == FINISH


@pytest.mark.langgraph
def test_langgraph_workflow_runs_end_to_end(tmp_path):
    import json

    from genclaw.pipeline import Pipeline

    pipeline = Pipeline(base_dir=tmp_path / "runs", use_langgraph=True)
    state = pipeline.run("three red circles on the left")

    lines = state.artifacts.trace_path.read_text(encoding="utf-8").splitlines()
    stages = [json.loads(line)["stage"] for line in lines]
    # Node order through the compiled graph (search runs but no-ops for
    # non-knowledge tasks).
    assert stages[:5] == ["conceptualize", "search", "render", "generate", "review"]
    assert state.review_result.passed is True
