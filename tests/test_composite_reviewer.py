"""Tests for the composite reviewer (structural + perceptual separation)."""

from pathlib import Path

from genclaw.agent.fixture import FixtureAgent
from genclaw.renderers.svg import SVGRenderer
from genclaw.review.composite import CompositeReviewer
from genclaw.schemas import ReviewResult


class StubPerceptual:
    """A fake VLM reviewer with a scripted verdict."""

    def __init__(self, result):
        self._result = result
        self.called_with_image = None

    def review(self, plan, canvas_source_path=None, image_path=None):
        self.called_with_image = image_path
        return self._result


def _render(tmp_path):
    plan = FixtureAgent().conceptualize("three red circles on the left")
    rendered = SVGRenderer().render(plan, tmp_path)
    return plan, rendered


def test_structural_runs_on_canvas_not_raster(tmp_path):
    # The three-circle fixture's structural checks (backend=svg, count=3) pass
    # against the canvas source even though we pass a bogus image path.
    plan, rendered = _render(tmp_path)
    reviewer = CompositeReviewer()  # no perceptual layer
    result = reviewer.review(plan, canvas_source_path=rendered.source_path,
                             image_path=tmp_path / "final.png")
    assert result.passed
    assert all(f.startswith("[structural]") for f in result.failures)


def test_passes_only_if_both_layers_pass(tmp_path):
    plan, rendered = _render(tmp_path)
    img = tmp_path / "final.png"
    img.write_bytes(b"x")

    perceptual = StubPerceptual(ReviewResult(passed=False, score=0.2, failures=["wrong count"]))
    reviewer = CompositeReviewer(perceptual=perceptual)
    result = reviewer.review(plan, canvas_source_path=rendered.source_path, image_path=img)

    assert result.passed is False
    # Perceptual reviewer received the final image.
    assert perceptual.called_with_image == img
    assert any(f == "[perceptual] wrong count" for f in result.failures)


def test_both_pass_combines_scores(tmp_path):
    plan, rendered = _render(tmp_path)
    img = tmp_path / "final.png"
    img.write_bytes(b"x")

    perceptual = StubPerceptual(ReviewResult(passed=True, score=0.8))
    reviewer = CompositeReviewer(perceptual=perceptual)
    result = reviewer.review(plan, canvas_source_path=rendered.source_path, image_path=img)

    assert result.passed is True
    # structural score is 1.0, perceptual 0.8 -> mean 0.9
    assert abs(result.score - 0.9) < 1e-6


def test_perceptual_skipped_without_image(tmp_path):
    plan, rendered = _render(tmp_path)
    perceptual = StubPerceptual(ReviewResult(passed=True, score=1.0))
    reviewer = CompositeReviewer(perceptual=perceptual)
    result = reviewer.review(plan, canvas_source_path=rendered.source_path, image_path=None)

    assert any("skipped" in w for w in result.warnings)
    # Perceptual reviewer was never called.
    assert perceptual.called_with_image is None
