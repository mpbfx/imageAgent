"""Tests for GenClawState (plan task 3.5)."""

from genclaw.graph.state import GenClawState
from genclaw.schemas import (
    CanvasBackend,
    CanvasPlan,
    CanvasSize,
    LayerSpec,
    ObjectSpec,
    TaskType,
)


def _plan():
    return CanvasPlan(
        request_id="req-1",
        prompt="three red circles on the left",
        task_type=TaskType.composition,
        backend=CanvasBackend.svg,
        size=CanvasSize(width=512, height=512),
        layers=[LayerSpec(id="base", order=0)],
        objects=[ObjectSpec(id="c1", kind="circle", layer_id="base")],
    )


def test_initial_state_from_prompt():
    state = GenClawState.from_prompt("req-1", "three red circles on the left")
    assert state.request_id == "req-1"
    assert state.prompt == "three red circles on the left"
    assert state.plan is None
    assert state.revision_count == 0


def test_errors_default_to_empty_list():
    state = GenClawState.from_prompt("req-1", "x")
    assert state.errors == []
    assert state.trace_events == []


def test_state_holds_canvas_plan():
    state = GenClawState.from_prompt("req-1", "x", task_type=TaskType.composition)
    state.plan = _plan()
    assert state.plan.objects[0].id == "c1"
    assert state.task_type is TaskType.composition


def test_state_serializes_after_revision_increment():
    state = GenClawState.from_prompt("req-1", "x")
    state.plan = _plan()
    state.revision_count += 1
    dumped = state.model_dump(mode="json")
    assert dumped["revision_count"] == 1
    assert dumped["plan"]["objects"][0]["id"] == "c1"
    # The IO handle is excluded from serialization.
    assert "artifacts" not in dumped


def test_max_revisions_default():
    state = GenClawState.from_prompt("req-1", "x")
    assert state.max_revisions == 1
    state2 = GenClawState.from_prompt("req-1", "x", max_revisions=3)
    assert state2.max_revisions == 3
