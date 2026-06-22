"""Tests for the deterministic fixture agent (plan task 4)."""

import pytest

from genclaw.agent.fixture import FixtureAgent, FixtureAgentError
from genclaw.schemas import CanvasBackend, TaskType


@pytest.fixture
def agent():
    return FixtureAgent()


def test_composition_fixture_returns_three_objects(agent):
    plan = agent.conceptualize("three red circles on the left")
    assert plan.task_type is TaskType.composition
    assert plan.backend is CanvasBackend.svg
    circles = [o for o in plan.objects if o.kind == "circle"]
    assert len(circles) == 3
    assert all(o.fill == "#d62828" for o in circles)


def test_poster_fixture_preserves_exact_text(agent):
    plan = agent.conceptualize("a poster for GenClaw")
    assert plan.backend is CanvasBackend.html
    assert plan.task_type is TaskType.long_text
    texts = {t.id: t.text for t in plan.text}
    assert texts["title"] == "Code as Brush"
    assert texts["subtitle"] == "代码即画笔"


def test_mirror_fixture_selects_three_backend(agent):
    plan = agent.conceptualize("mirror reflection of a small ball")
    assert plan.backend is CanvasBackend.three
    assert plan.task_type is TaskType.physical_reasoning
    kinds = {o.kind for o in plan.objects}
    assert {"sphere", "mirror", "plane", "directional_light", "camera"} <= kinds


def test_request_id_is_threaded(agent):
    plan = agent.conceptualize("three red circles", request_id="req-42")
    assert plan.request_id == "req-42"


def test_unknown_prompt_raises(agent):
    with pytest.raises(FixtureAgentError, match="no fixture plan"):
        agent.conceptualize("an impressionist landscape")


def test_all_fixtures_validate_and_are_structured(agent):
    for prompt in ("three red circles", "poster", "mirror"):
        plan = agent.conceptualize(prompt)
        assert plan.source.value == "structured"
        # Round-trips through the schema validators without error.
        assert plan.model_dump(mode="json")["request_id"]
