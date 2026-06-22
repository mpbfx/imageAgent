"""Tests for the Three.js renderer (plan task 8).

Source-compilation tests are browser-free. The PNG test is gated behind the
``render`` marker (skipped without Playwright) and depends on the task 7.5
WebGL spike for stable Windows headless capture.
"""

import pytest

from genclaw.agent.fixture import FixtureAgent
from genclaw.renderers.three import ThreeRenderer
from genclaw.schemas import CanvasBackend


@pytest.fixture
def renderer():
    return ThreeRenderer()


def test_source_contains_scene_objects(renderer):
    plan = FixtureAgent().conceptualize("mirror reflection of a small ball")
    source = renderer.compile_source(plan)
    assert "SphereGeometry" in source
    assert "PlaneGeometry" in source
    assert "DirectionalLight" in source
    assert "PerspectiveCamera" in source
    assert "WebGLRenderer" in source


def test_render_reports_three_backend(renderer, tmp_path):
    plan = FixtureAgent().conceptualize("mirror reflection of a small ball")
    result = renderer.render(plan, tmp_path)
    assert result.backend is CanvasBackend.three
    assert result.source_path.exists()
    assert result.source_path.name == "canvas.html"


def test_camera_uses_plan_coordinates(renderer):
    plan = FixtureAgent().conceptualize("mirror reflection of a small ball")
    source = renderer.compile_source(plan)
    # camera fixture position is (0, 3, 8).
    assert "camera.position.set(0, 3, 8)" in source


@pytest.mark.render
def test_mirror_png_is_nonempty(renderer, tmp_path):
    plan = FixtureAgent().conceptualize("mirror reflection of a small ball")
    result = renderer.render(plan, tmp_path)
    assert result.png_path is not None
    assert result.png_path.stat().st_size > 0
