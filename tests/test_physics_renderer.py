"""Tests for the Python/Canvas physics renderers (paper §3.2).

Source-compilation tests are pure. PNG tests are gated: the matplotlib path
needs matplotlib (``render`` marker is reused as a proxy for "rasterization
deps available"); the canvas path needs Playwright.
"""

import pytest

from genclaw.renderers.physics import PhysicsRenderer
from genclaw.schemas import (
    CanvasBackend,
    CanvasPlan,
    CanvasSize,
    ObjectSpec,
    ReasoningStep,
    TaskType,
)


def _physics_plan(backend=CanvasBackend.python):
    return CanvasPlan(
        request_id="phys-1",
        prompt="spring deflection under load",
        task_type=TaskType.physical_reasoning,
        backend=backend,
        size=CanvasSize(width=400, height=300),
        objects=[
            ObjectSpec(id="ball", kind="circle", x=200, y=150,
                       attributes={"radius": 20, "color": "#e63946"}),
            ObjectSpec(id="base", kind="rectangle", x=0, y=0, width=400, height=10,
                       fill="#333333"),
        ],
        reasoning=[
            ReasoningStep(question="deflection", conclusion="x=30mm", values={"x": 30}),
        ],
    )


def test_python_backend_rejects_wrong_backend():
    with pytest.raises(ValueError):
        PhysicsRenderer(CanvasBackend.svg)


def test_python_source_is_matplotlib_script():
    src = PhysicsRenderer(CanvasBackend.python).compile_source(_physics_plan())
    assert "matplotlib" in src
    assert "plt.Circle((200.0, 150.0), 20" in src
    assert "plt.Rectangle((0.0, 0.0), 400" in src
    # Reasoning steps are recorded in the generated source for traceability.
    assert "deflection" in src


def test_canvas_source_is_html_canvas():
    src = PhysicsRenderer(CanvasBackend.canvas).compile_source(
        _physics_plan(CanvasBackend.canvas)
    )
    assert "<canvas" in src
    assert "getContext" in src
    assert "ctx.arc(200.0, 150.0, 20" in src


def test_python_render_writes_py_source(tmp_path):
    result = PhysicsRenderer(CanvasBackend.python).render(_physics_plan(), tmp_path)
    assert result.backend is CanvasBackend.python
    assert result.source_path.name == "canvas.py"
    assert result.source_path.exists()


@pytest.mark.render
def test_python_png_is_nonempty(tmp_path):
    # matplotlib is installed alongside the scientific stack; if present this
    # rasterizes without a browser.
    pytest.importorskip("matplotlib")
    result = PhysicsRenderer(CanvasBackend.python).render(_physics_plan(), tmp_path)
    assert result.png_path is not None
    assert result.png_path.stat().st_size > 0
