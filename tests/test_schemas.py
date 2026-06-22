"""Tests for the core CanvasPlan schema (plan task 2)."""

import pytest
from pydantic import ValidationError

from genclaw.schemas import (
    CanvasBackend,
    CanvasPlan,
    CanvasSize,
    CanvasSource,
    LayerSpec,
    ObjectSpec,
    RelationSpec,
    TaskType,
    TextSpec,
)


def _valid_plan_kwargs(**overrides):
    base = dict(
        request_id="req-1",
        prompt="three red circles on the left",
        task_type=TaskType.composition,
        backend=CanvasBackend.svg,
        size=CanvasSize(width=512, height=512),
        layers=[LayerSpec(id="base", order=0)],
        objects=[
            ObjectSpec(id="c1", kind="circle", layer_id="base", x=10, y=10),
            ObjectSpec(id="c2", kind="circle", layer_id="base", x=20, y=20),
        ],
    )
    base.update(overrides)
    return base


def test_valid_plan_parses():
    plan = CanvasPlan(**_valid_plan_kwargs())
    assert plan.source is CanvasSource.structured
    assert len(plan.objects) == 2


def test_unknown_layer_reference_fails():
    with pytest.raises(ValidationError, match="unknown layer"):
        CanvasPlan(
            **_valid_plan_kwargs(
                objects=[ObjectSpec(id="c1", kind="circle", layer_id="ghost")]
            )
        )


def test_negative_size_fails():
    with pytest.raises(ValidationError):
        CanvasSize(width=-1, height=512)


def test_duplicate_object_id_fails():
    with pytest.raises(ValidationError, match="duplicate id"):
        CanvasPlan(
            **_valid_plan_kwargs(
                objects=[
                    ObjectSpec(id="dup", kind="circle"),
                    ObjectSpec(id="dup", kind="circle"),
                ],
                layers=[],
            )
        )


def test_relation_unknown_element_fails():
    with pytest.raises(ValidationError, match="unknown element"):
        CanvasPlan(
            **_valid_plan_kwargs(
                relations=[
                    RelationSpec(subject_id="c1", relation="left_of", object_id="nope")
                ]
            )
        )


def test_code_source_requires_payload():
    with pytest.raises(ValidationError, match="code_source"):
        CanvasPlan(
            **_valid_plan_kwargs(source=CanvasSource.code, layers=[], objects=[])
        )


def test_code_plan_with_payload_parses():
    plan = CanvasPlan(
        **_valid_plan_kwargs(
            source=CanvasSource.code,
            code_source="<svg></svg>",
            code_lang="svg",
            layers=[],
            objects=[],
        )
    )
    assert plan.source is CanvasSource.code
    assert plan.code_lang == "svg"


def test_ordered_layers_sorts_by_order():
    plan = CanvasPlan(
        **_valid_plan_kwargs(
            layers=[
                LayerSpec(id="top", order=10),
                LayerSpec(id="base", order=0),
            ],
            objects=[ObjectSpec(id="c1", kind="circle", layer_id="base")],
        )
    )
    assert [layer.id for layer in plan.ordered_layers()] == ["base", "top"]


def test_text_exact_preserved():
    plan = CanvasPlan(
        **_valid_plan_kwargs(
            task_type=TaskType.long_text,
            backend=CanvasBackend.html,
            objects=[],
            layers=[],
            text=[TextSpec(id="t1", text="代码即画笔 Code as Brush")],
        )
    )
    assert plan.text[0].text == "代码即画笔 Code as Brush"
