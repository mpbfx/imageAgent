"""Tests for the SVG renderer (plan task 6).

Source-compilation tests are browser-free. The PNG test is gated behind the
``render`` marker (skipped without Playwright) per the conftest strategy.
"""

import re

import pytest

from genclaw.agent.fixture import FixtureAgent
from genclaw.renderers.svg import SVGRenderer
from genclaw.schemas import (
    CanvasBackend,
    CanvasPlan,
    CanvasSize,
    LayerSpec,
    ObjectSpec,
    TaskType,
)


@pytest.fixture
def renderer():
    return SVGRenderer()


def test_three_circle_plan_emits_three_circles(renderer):
    plan = FixtureAgent().conceptualize("three red circles on the left")
    source = renderer.compile_source(plan)
    assert len(re.findall(r"<circle\b", source)) == 3
    assert 'fill="#d62828"' in source


def test_layer_order_reflected_in_source(renderer):
    plan = CanvasPlan(
        request_id="r",
        prompt="p",
        task_type=TaskType.composition,
        backend=CanvasBackend.svg,
        size=CanvasSize(width=200, height=200),
        layers=[LayerSpec(id="top", order=10), LayerSpec(id="base", order=0)],
        objects=[
            ObjectSpec(id="on-top", kind="rectangle", layer_id="top",
                       x=0, y=0, width=50, height=50, fill="#fff"),
            ObjectSpec(id="behind", kind="circle", layer_id="base",
                       x=0, y=0, width=40, height=40, fill="#000"),
        ],
    )
    source = renderer.compile_source(plan)
    # base (order 0) paints first, top (order 10) paints after.
    assert source.index("<circle") < source.index("<rect")


def test_supported_shapes_compile(renderer):
    plan = CanvasPlan(
        request_id="r",
        prompt="p",
        task_type=TaskType.composition,
        backend=CanvasBackend.svg,
        size=CanvasSize(width=300, height=300),
        objects=[
            ObjectSpec(id="c", kind="circle", x=0, y=0, width=40, height=40),
            ObjectSpec(id="r1", kind="rectangle", x=0, y=0, width=40, height=40),
            ObjectSpec(id="e", kind="ellipse", x=0, y=0, width=40, height=20),
            ObjectSpec(id="p1", kind="polygon", x=0, y=0,
                       attributes={"points": [[0, 0], [10, 0], [5, 10]]}),
        ],
    )
    source = renderer.compile_source(plan)
    assert "<circle" in source
    assert "<rect" in source
    assert "<ellipse" in source
    assert '<polygon points="0,0 10,0 5,10"' in source


def test_text_is_escaped(renderer):
    plan = CanvasPlan(
        request_id="r",
        prompt="p",
        task_type=TaskType.composition,
        backend=CanvasBackend.svg,
        size=CanvasSize(width=200, height=200),
        text=[],
    )
    # build text via dict to avoid import noise
    from genclaw.schemas import TextSpec

    plan.text = [TextSpec(id="t", text="<script>&", x=10, y=10)]
    source = renderer.compile_source(plan)
    assert "<script>" not in source
    assert "&lt;script&gt;&amp;" in source


def test_render_writes_svg_source(renderer, tmp_path):
    plan = FixtureAgent().conceptualize("three red circles on the left")
    result = renderer.render(plan, tmp_path)
    assert result.backend is CanvasBackend.svg
    assert result.source_path.exists()
    assert result.source_path.read_text(encoding="utf-8").count("<circle") == 3


@pytest.mark.render
def test_three_circle_png_is_nonempty(renderer, tmp_path):
    plan = FixtureAgent().conceptualize("three red circles on the left")
    result = renderer.render(plan, tmp_path)
    assert result.png_path is not None
    assert result.png_path.exists()
    assert result.png_path.stat().st_size > 0
