"""Tests for the HTML renderer (plan task 7)."""

import pytest

from genclaw.agent.fixture import FixtureAgent
from genclaw.renderers.html import HTMLRenderer
from genclaw.schemas import (
    CanvasBackend,
    CanvasPlan,
    CanvasSize,
    TaskType,
    TextSpec,
)


@pytest.fixture
def renderer():
    return HTMLRenderer()


def test_source_preserves_exact_text(renderer):
    plan = FixtureAgent().conceptualize("a poster for GenClaw")
    source = renderer.compile_source(plan)
    assert "Code as Brush" in source
    assert "代码即画笔" in source


def test_user_html_fragment_is_escaped(renderer):
    plan = CanvasPlan(
        request_id="r",
        prompt="p",
        task_type=TaskType.long_text,
        backend=CanvasBackend.html,
        size=CanvasSize(width=400, height=300),
        text=[TextSpec(id="t", text="<b>bold</b> & <script>alert(1)</script>")],
    )
    source = renderer.compile_source(plan)
    # The injected markup must not appear as live tags.
    assert "<script>alert(1)</script>" not in source
    assert "&lt;script&gt;" in source
    assert "&lt;b&gt;bold&lt;/b&gt;" in source


def test_render_writes_html_source(renderer, tmp_path):
    plan = FixtureAgent().conceptualize("a poster for GenClaw")
    result = renderer.render(plan, tmp_path)
    assert result.backend is CanvasBackend.html
    assert result.source_path.exists()
    assert "Code as Brush" in result.source_path.read_text(encoding="utf-8")


@pytest.mark.render
def test_poster_png_is_nonempty(renderer, tmp_path):
    plan = FixtureAgent().conceptualize("a poster for GenClaw")
    result = renderer.render(plan, tmp_path)
    assert result.png_path is not None
    assert result.png_path.stat().st_size > 0
