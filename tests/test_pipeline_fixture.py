"""End-to-end fixture pipeline tests (plan task 11, direct path)."""

import json

import pytest

from genclaw.pipeline import Pipeline
from genclaw.schemas import CanvasBackend


@pytest.fixture
def pipeline(tmp_path):
    return Pipeline(base_dir=tmp_path / "runs", use_langgraph=False)


def test_composition_run_creates_all_artifacts(pipeline):
    state = pipeline.run("three red circles on the left")
    arts = state.artifacts

    assert state.plan is not None
    assert state.plan.backend is CanvasBackend.svg
    assert arts.request_path.exists()
    assert arts.plan_path.exists()
    assert arts.canvas_path("svg").exists()
    assert arts.final_path.exists()
    assert arts.review_path.exists()
    assert arts.trace_path.exists()


def test_review_result_serialized_to_json(pipeline):
    state = pipeline.run("three red circles on the left")
    data = json.loads(state.artifacts.review_path.read_text(encoding="utf-8"))
    assert data["passed"] is True
    assert "score" in data


def test_trace_contains_node_names(pipeline):
    state = pipeline.run("three red circles on the left")
    lines = state.artifacts.trace_path.read_text(encoding="utf-8").splitlines()
    stages = {json.loads(line)["stage"] for line in lines}
    assert {"conceptualize", "render", "generate", "review"} <= stages


def test_poster_run_preserves_text_in_canvas(pipeline):
    state = pipeline.run("a poster for GenClaw")
    source = state.artifacts.canvas_path("html").read_text(encoding="utf-8")
    assert "Code as Brush" in source
    assert "代码即画笔" in source


def test_unknown_prompt_produces_error_artifact(pipeline):
    state = pipeline.run("an impressionist landscape")
    assert state.plan is None
    assert state.errors
    assert state.artifacts.error_path("conceptualize").exists()
    err = json.loads(
        state.artifacts.error_path("conceptualize").read_text(encoding="utf-8")
    )
    assert err["stage"] == "conceptualize"


def test_failed_review_loops_to_revise_until_budget(pipeline):
    # Force review to fail so routing exercises the revise loop.
    from genclaw.schemas import ReviewResult

    class FailingReviewer:
        def review(self, plan, canvas_source_path=None, image_path=None):
            return ReviewResult(passed=False, score=0.0, failures=["forced"])

    pipeline.reviewer = FailingReviewer()
    state = pipeline.run("three red circles on the left", max_revisions=2)

    assert state.review_result.passed is False
    assert state.revision_count == 2  # looped until the budget, then stopped.
    assert any("revise is unsupported" in e for e in state.errors)
